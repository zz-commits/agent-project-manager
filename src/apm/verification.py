"""Execute configured checks and retain immutable, assertion-bound evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

from .facts import Facts, dump_yaml, safe_path
from .operations import OperationError, fail, valid
from .state import check_digest, current_subject, derive, utc_now
from .storage import commit_files, project_lock, require_revision


MAX_REPORT = 16 * 1024 * 1024
MAX_LOG = 1024 * 1024


def assessment(f: Facts, feature_id: str, at: str | None = None) -> dict:
    if feature_id not in f.features:
        fail(4, f'Unknown Feature {feature_id}', 'not_found', feature_id)
    state = next(s for s in derive(f, at or utc_now())['features'] if s['id'] == feature_id)
    return {'id': feature_id, 'verification': state['verification'],
            'required_passed': state['verification'] == 'passed',
            'passed_ac': state['passed_ac'], 'required_ac': state['required_ac'], 'checks': state['checks']}


def write_context(f: Facts, feature_id: str, run_id: str, expected: int) -> dict:
    if feature_id not in f.features:
        fail(4, f'Unknown Feature {feature_id}', 'not_found', feature_id)
    if expected < 1:
        fail(2, 'Expected revision must be positive', 'argument_error')
    feature = f.features[feature_id]
    require_revision(feature, expected)
    if run_id not in f.runs:
        fail(4, f'Unknown Run {run_id}', 'not_found', run_id)
    run = f.runs[run_id]
    if run['status'] != 'active' or feature_id not in run['feature_refs']:
        fail(5, 'An active Run containing this Feature is required', 'run_prerequisite')
    return deepcopy({'feature': feature, 'run': run, 'project': f.project,
                     'requirements': {ref: f.requirements[ref] for ref in feature['requirement_refs']}})


def _same_context(f: Facts, feature_id: str, run_id: str, expected: int, snapshot: dict) -> None:
    try:
        current = write_context(f, feature_id, run_id, expected)
    except OperationError:
        fail(3, 'Run or Feature prerequisites changed during verification', 'context_conflict', feature_id)
    if current != snapshot:
        fail(3, 'Verification context changed while collecting evidence', 'context_conflict', feature_id)


def _redact(raw: bytes) -> bytes:
    # Inspect bindings only inside the process; never emit their values or names.
    values = [v.encode('utf-8') for k, v in os.environ.items()
              if v and re.search(r'(TOKEN|SECRET|PASSWORD|CREDENTIAL|(?:^|_)KEY)(?:$|_)', k, re.IGNORECASE)]
    for secret in sorted(set(values), key=len, reverse=True):
        raw = raw.replace(secret, b'[REDACTED]')
    return raw


def _signature(path: Path):
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _report_path(root: Path, command: dict) -> Path | None:
    if 'result' not in command:
        return None
    name = command['result']['path']
    target = safe_path(root, name)
    if target != root / name:
        fail(2, 'Result report cannot be a symlink', 'unsafe_report')
    return target


def _stop_group(process: subprocess.Popen) -> None:
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()
    process.wait()


def _execute(root: Path, command: dict) -> dict:
    report = _report_path(root, command)
    before = _signature(report) if report else None
    result = {'exit_code': None, 'reason': None, 'log': b'', 'report': None}
    if report is None:
        result['reason'] = 'unconfigured_result_parser'
        return result
    cwd = safe_path(root, command['cwd'])
    if not cwd.is_dir():
        result['reason'] = 'missing_working_directory'
        return result
    with tempfile.TemporaryFile() as output:
        started_ns = time.time_ns()
        try:
            process = subprocess.Popen(command['argv'], cwd=cwd, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=os.name == 'posix')
        except OSError:
            result['reason'] = 'execution_environment_unavailable'
            return result
        try:
            result['exit_code'] = process.wait(timeout=command.get('timeout_seconds', 60))
        except subprocess.TimeoutExpired:
            result['reason'] = 'timeout'
        finally:
            _stop_group(process)
        output.seek(0)
        raw = output.read(MAX_LOG + 1)
        if len(raw) > MAX_LOG:
            raw = raw[:MAX_LOG] + b'\n[output truncated]\n'
        result['log'] = _redact(raw)
    # The runner may create a symlink or replace a directory after initial checking.
    report = _report_path(root, command)
    after = _signature(report)
    if result['reason']:
        return result
    if after is None:
        result['reason'] = 'missing_report'
    elif before == after or report.stat().st_mtime_ns < started_ns:
        result['reason'] = 'stale_report'
    elif report.stat().st_size > MAX_REPORT:
        result['reason'] = 'report_too_large'
    else:
        result['report'] = report.read_bytes()
    return result


def junit_result(raw: bytes | None, names: list[str] | None, exit_code: int | None) -> tuple[str, str, dict]:
    if not names:
        return 'not_verified', 'unconfigured_testcase_refs', {}
    if raw is None:
        return 'not_verified', 'missing_report', {}
    if len(raw) > MAX_REPORT:
        return 'not_verified', 'unsafe_or_oversized_report', {}
    try:
        text = raw.decode('utf-8-sig')
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            return 'not_verified', 'unsafe_or_oversized_report', {}
        document = ET.fromstring(text)
    except (ET.ParseError, ValueError):
        return 'not_verified', 'malformed_report', {}
    if document.tag not in {'testsuite', 'testsuites'}:
        return 'not_verified', 'unsupported_report', {}
    cases = {}
    for case in document.iter('testcase'):
        name = case.get('classname', '') + '.' + case.get('name', '')
        cases.setdefault(name, []).append(case)
    if not cases:
        return 'not_verified', 'zero_tests', {}
    missing = [name for name in names if name not in cases]
    duplicates = [name for name in names if len(cases.get(name, [])) > 1]
    if missing or duplicates:
        return 'not_verified', 'missing_or_ambiguous_testcases', {'missing': missing, 'duplicates': duplicates}
    selected = [cases[name][0] for name in names]
    counts = {'selected': len(selected), 'total': sum(len(v) for v in cases.values()),
              'failed': sum(c.find('failure') is not None or c.find('error') is not None for c in selected),
              'skipped': sum(c.find('skipped') is not None or c.get('status') in {'notrun', 'disabled', 'skipped'} for c in selected)}
    if counts['failed']:
        return 'failed', 'named_assertion_failed', counts
    if counts['skipped']:
        return 'not_verified', 'named_assertion_skipped', counts
    if exit_code is None:
        return 'not_verified', 'no_exit_result', counts
    if exit_code != 0:
        return 'failed', 'command_failed', counts
    return 'passed', 'named_assertions_passed', counts


def _artifact(name: str, content: bytes, writes: dict) -> dict:
    writes[name] = content
    return {'path': name, 'sha256': hashlib.sha256(content).hexdigest()}


def _selected(feature: dict, selected: list[str] | None) -> list[dict]:
    checks = feature['verification']['checks']
    if selected is None:
        return checks
    if len(selected) != len(set(selected)):
        fail(2, 'Check IDs must be unique', 'argument_error')
    missing = set(selected) - {c['id'] for c in checks}
    if missing:
        fail(4, 'Unknown Check: ' + ', '.join(sorted(missing)), 'not_found')
    return [c for c in checks if c['id'] in selected]


def execute_checks(root: Path, feature_id: str, run_id: str, expected: int,
                   selected: list[str] | None = None, *, dry_run: bool = False) -> dict:
    # Obtain a coherent snapshot, release the lock before starting a subprocess.
    def prepare():
        f = valid(root)
        snapshot = write_context(f, feature_id, run_id, expected)
        subject = current_subject(root)
        if snapshot['feature']['implementation']['subject'] != subject:
            fail(5, 'Feature.subject must match the current code before verification', 'stale_subject')
        return f, snapshot, subject, _selected(snapshot['feature'], selected)
    if dry_run:
        f, snapshot, subject, checks = prepare()
        return {**assessment(f, feature_id), 'dry_run': True,
                'would_execute': sorted({c['command_ref'] for c in checks if 'command_ref' in c}), 'new_evidence': []}
    with project_lock(root):
        f, snapshot, subject, checks = prepare()
    executions = {}
    for check in checks:
        ref = check.get('command_ref')
        if ref and ref not in executions and check['activity'] != 'blocked' and check.get('testcase_refs'):
            executions[ref] = _execute(root, f.project['commands'][ref])
    actual = current_subject(root)
    feature = deepcopy(snapshot['feature'])
    changes, writes, created, summaries = {}, {}, [], []
    artifact_id = str(uuid4())
    command_artifacts = {}
    for index, (ref, execution) in enumerate(executions.items()):
        artifacts = [_artifact(f'.project/artifacts/{artifact_id}/command-{index}.log', execution['log'], writes)]
        if execution['report'] is not None:
            artifacts.append(_artifact(f'.project/artifacts/{artifact_id}/command-{index}.xml', _redact(execution['report']), writes))
        command_artifacts[ref] = artifacts
    for check in checks:
        ref = check.get('command_ref')
        command = f.project['commands'].get(ref)
        execution = executions.get(ref, {'exit_code': None, 'reason': 'unconfigured_check', 'report': None})
        result, reason, counts = junit_result(execution['report'], check.get('testcase_refs'), execution['exit_code'])
        if execution['reason'] or check['activity'] == 'blocked':
            result, reason = 'not_verified', execution['reason'] or 'check_blocked'
        if actual != subject:
            result, reason = 'not_verified', 'code_changed_during_execution'
        summary = {'check': check['id'], 'result': result, 'reason': reason, 'counts': counts}
        summaries.append(summary)
        # IDs are schema-valid strings, but not necessarily safe filenames. Use an index.
        name = f'.project/artifacts/{artifact_id}/check-{len(summaries)}.json'
        artifacts = [*command_artifacts.get(ref, []), _artifact(name, dump_yaml(summary).encode(), writes)]
        identity = 'EVD-' + str(uuid4())
        evidence = {'version': 1, 'id': identity, 'feature_ref': feature_id, 'check_ref': check['id'],
                    'type': 'test', 'produced_by': {'run_ref': run_id}, 'result': result,
                    'acceptance_revision': feature['acceptance_revision'],
                    'requirement_revisions': {k: v['revision'] for k, v in snapshot['requirements'].items()},
                    'subject': subject, 'check_digest': check_digest(check, f.project),
                    'command': ({'argv': command['argv'], 'cwd': command['cwd'], 'exit_code': execution['exit_code']} if command else None),
                    'artifacts': artifacts, 'note': reason, 'supersedes': list(check['evidence_refs']), 'created_at': utc_now()}
        changes[f'.project/evidence/{identity}.yaml'] = evidence
        stored = next(c for c in feature['verification']['checks'] if c['id'] == check['id'])
        stored['evidence_refs'].append(identity)
        if stored['activity'] != 'blocked':
            stored['activity'] = 'idle'
        created.append(identity)
    feature['revision'] += 1
    feature['metadata']['updated_at'] = utc_now()
    changes[f.files[feature_id]] = feature
    with project_lock(root):
        fresh = valid(root)
        _same_context(fresh, feature_id, run_id, expected, snapshot)
        # A code edit between result parsing and commit cannot turn a PASS current.
        if current_subject(root) != subject:
            for value in changes.values():
                if value.get('type') == 'test':
                    value.update(result='not_verified', note='code_changed_during_execution')
        valid(root, changes)
        commit_files(root, {**writes, **{path: dump_yaml(value) for path, value in changes.items()}})
        outcome = assessment(valid(root), feature_id)
    return {**outcome, 'dry_run': False, 'new_evidence': created, 'executions': summaries}


def snapshot_artifacts(root: Path, evidence: dict, writes: dict, artifact_id: str, incoming_artifacts=None) -> dict:
    ev = deepcopy(evidence)
    copied = []
    for index, artifact in enumerate(ev['artifacts']):
        if 'url' in artifact:
            copied.append(artifact)
            continue
        path = safe_path(root, artifact['path'])
        supplied = (incoming_artifacts or {}).get(artifact['path'])
        if supplied is None and not path.is_file():
            fail(5, 'A local import artifact is missing', 'missing_artifact')
        raw = supplied if supplied is not None else path.read_bytes()
        if artifact.get('sha256') and hashlib.sha256(raw).hexdigest() != artifact['sha256']:
            fail(5, 'Import artifact checksum differs', 'artifact_checksum_mismatch')
        suffix = path.suffix if re.fullmatch(r'\.[A-Za-z0-9]+', path.suffix) else '.bin'
        name = f'.project/artifacts/{artifact_id}/artifact-{len(writes)}{suffix}'
        if suffix.lower() in {'.xml', '.json', '.txt', '.log'}:
            raw = _redact(raw)
        copied.append({**artifact, **_artifact(name, raw, writes)})
    ev['artifacts'] = copied
    return ev


def import_evidence(root: Path, feature_id: str, run_id: str, expected: int,
                    incoming: dict | list, *, dry_run: bool = False,
                    expected_context=None, incoming_artifacts=None) -> dict:
    records = deepcopy(incoming if isinstance(incoming, list) else [incoming])
    if not records or any(not isinstance(ev, dict) for ev in records):
        fail(2, 'Expected complete Evidence object or nonempty list', 'invalid_record')
    def prepare():
        f = valid(root)
        if expected_context is not None:
            _same_context(f, feature_id, run_id, expected, expected_context)
            if current_subject(root) != expected_context['feature']['implementation']['subject']:
                fail(5, 'Code changed during CI collection', 'stale_subject')
        snapshot = write_context(f, feature_id, run_id, expected)
        feature = deepcopy(snapshot['feature'])
        changes = {}
        checks = {c['id']: c for c in feature['verification']['checks']}
        for ev in records:
            if (not isinstance(ev.get('produced_by'), dict)
                    or ev.get('feature_ref') != feature_id or ev.get('check_ref') not in checks
                    or ev.get('produced_by', {}).get('run_ref') != run_id or ev.get('type') == 'delivery'):
                fail(2, 'Imported Evidence must belong to this Run/Feature/Check', 'evidence_mismatch')
            identity = ev.get('id')
            if not isinstance(identity, str):
                fail(2, 'Evidence ID is required', 'invalid_record')
            if identity in f.evidence or identity in {x['id'] for x in changes.values()}:
                fail(3, 'Evidence IDs are immutable and must be unique', 'evidence_exists')
            changes[f'.project/evidence/{identity}.yaml'] = ev
            checks[ev['check_ref']]['evidence_refs'].append(identity)
        feature['revision'] += 1
        feature['metadata']['updated_at'] = utc_now()
        changes[f.files[feature_id]] = feature
        valid(root, changes)
        return f, changes, checks
    def collect(f, changes, checks):
        writes = {}
        artifact_id = str(uuid4())
        for name, ev in list(changes.items()):
            if ev.get('type') not in {'test', 'ci_result', 'manual_review', 'api_response', 'screenshot', 'code_reference'}:
                continue
            if ev['result'] == 'passed' and ev['type'] not in {'test', 'ci_result', 'manual_review'}:
                fail(5, 'Observational material requires an explicit manual_review to verify a Check', 'unsupported_pass_source')
            if ev['result'] == 'passed' and ev['type'] in {'test', 'ci_result'}:
                check = checks[ev['check_ref']]
                command = f.project['commands'].get(check.get('command_ref'), {})
                if not command.get('result') or not check.get('testcase_refs'):
                    fail(5, 'Passed test import requires configured JUnit assertions', 'unconfigured_assertions')
                parsed = []
                for artifact in ev['artifacts']:
                    if 'path' in artifact:
                        path = safe_path(root, artifact['path'])
                        supplied = (incoming_artifacts or {}).get(artifact['path'])
                        if path.suffix.lower() == '.xml' and (supplied is not None or path.is_file()):
                            raw = supplied if supplied is not None else path.read_bytes()
                            parsed.append(junit_result(raw, check['testcase_refs'], ev['command']['exit_code'])[0])
                if 'passed' not in parsed:
                    fail(5, 'Imported report does not prove the named assertions', 'assertions_unverified')
            changes[name] = snapshot_artifacts(root, ev, writes, artifact_id, incoming_artifacts)
        return writes
    if dry_run:
        f, changes, checks = prepare()
        # Inspect local input while preserving every file. Do not bind copied paths
        # into a derived assessment until those artifacts have actually been saved.
        collect(f, deepcopy(changes), checks)
        return {**assessment(f, feature_id), 'dry_run': True, 'new_evidence': [], 'would_record': [ev['id'] for ev in records]}
    with project_lock(root):
        f, changes, checks = prepare()
        writes = collect(f, changes, checks)
        valid(root, changes)
        if expected_context is not None and current_subject(root) != expected_context['feature']['implementation']['subject']:
            fail(5, 'Code changed during CI collection', 'stale_subject')
        commit_files(root, {**writes, **{path: dump_yaml(value) for path, value in changes.items()}})
        return {**assessment(valid(root), feature_id), 'dry_run': False, 'new_evidence': [ev['id'] for ev in records]}
