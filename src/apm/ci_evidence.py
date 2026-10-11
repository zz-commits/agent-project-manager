"""Explicit GitHub Actions imports bound to native run metadata and artifact bytes."""

from copy import deepcopy
import hashlib
import io
import json
import re
import stat
import subprocess
from urllib.parse import urlsplit
from uuid import uuid4
import zipfile

from .facts import load_yaml
from .operations import fail, valid
from .state import check_digest, current_subject, utc_now
from .verification import import_evidence, junit_result, write_context, _selected

MAX_ARCHIVE = 16 * 1024 * 1024


class GitHub:
    """Read through the existing gh authentication; no token copying or mutation."""
    def api(self, path, *, raw=False):
        p = subprocess.run(['gh', 'api', path], capture_output=True, timeout=60)
        if p.returncode:
            fail(1, 'GitHub read failed; check access to this run/artifact', 'ci_read_failed')
        return p.stdout if raw else json.loads(p.stdout)


def repository(root):
    p = subprocess.run(['git', '-C', str(root), 'remote', 'get-url', 'origin'], capture_output=True)
    if p.returncode:
        fail(2, 'CI import requires a GitHub origin remote', 'ci_repository')
    origin = p.stdout.decode().strip()
    if origin.startswith('git@github.com:'):
        path = origin.removeprefix('git@github.com:')
    else:
        url = urlsplit(origin)
        if url.scheme != 'https' or url.hostname != 'github.com':
            fail(2, 'CI import requires a GitHub origin remote', 'ci_repository')
        path = url.path.lstrip('/')
    path = path.removesuffix('.git')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', path):
        fail(2, 'Invalid GitHub repository path', 'ci_repository')
    return path


def collect(root, f, feature_id, run_id, expected, remote_run, artifact_name, selected, reviewer, note, client):
    context = write_context(f, feature_id, run_id, expected)
    subject = current_subject(root)
    if subject['kind'] != 'commit' or subject != context['feature']['implementation']['subject']:
        fail(5, 'CI import requires the exact clean commit and matching Feature subject', 'stale_subject')
    if not reviewer or not reviewer.strip() or not note or not note.strip() or not selected or not artifact_name:
        fail(2, 'CI import requires named Checks, artifact, reviewer and note', 'argument_error')
    repo = repository(root)
    value = str(remote_run)
    if value.isascii() and value.isdigit():
        identity = int(value)
    else:
        match = re.fullmatch(r'https://github\.com/([^/]+/[^/]+)/actions/runs/([0-9]+)', value)
        if not match or match[1].casefold() != repo.casefold():
            fail(2, 'CI run URL must belong to the origin repository', 'ci_repository')
        identity = int(match[2])
    if identity < 1:
        fail(2, 'CI run ID must be positive', 'argument_error')
    prefix = 'repos/' + repo
    native = client.api(f'{prefix}/actions/runs/{identity}')
    if (native['id'] != identity or native['repository']['full_name'].casefold() != repo.casefold()
            or native['head_repository']['full_name'].casefold() != repo.casefold()
            or native['head_sha'] != subject['value'] or native['status'] != 'completed'
            or native['conclusion'] != 'success'):
        fail(5, 'CI repository, commit or successful completion does not match', 'ci_binding')
    data = client.api(f'{prefix}/actions/runs/{identity}/artifacts?per_page=100')
    if data['total_count'] > 100:
        fail(5, 'Too many artifacts; select a run with an unambiguous evidence artifact', 'ci_artifact')
    matches = [a for a in data['artifacts'] if a['name'] == artifact_name]
    if len(matches) != 1:
        fail(5, 'Evidence artifact is missing or ambiguous', 'ci_artifact')
    artifact = matches[0]
    if (artifact['expired'] or artifact['workflow_run']['id'] != identity
            or artifact['workflow_run']['head_sha'] != subject['value']
            or type(artifact['size_in_bytes']) is not int or not 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest') or '')):
        fail(5, 'Artifact is expired, unbound, oversized or lacks its native digest', 'ci_artifact')
    raw = client.api(f'{prefix}/actions/artifacts/{artifact["id"]}/zip', raw=True)
    if len(raw) > MAX_ARCHIVE or 'sha256:' + hashlib.sha256(raw).hexdigest() != artifact['digest']:
        fail(5, 'Downloaded CI archive differs from the native digest', 'ci_checksum')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if (len(infos) != 2 or {i.filename for i in infos} != {'ci-tests.xml', 'ci-context.json'}
                    or any(i.file_size > MAX_ARCHIVE or stat.S_IFMT(i.external_attr >> 16) not in (0, stat.S_IFREG) for i in infos)):
                fail(5, 'CI artifact must contain only the bounded report and execution context', 'ci_artifact')
            report = archive.read('ci-tests.xml')
            context_raw = archive.read('ci-context.json')
    except (zipfile.BadZipFile, RuntimeError) as exc:
        fail(5, 'Invalid CI archive', 'ci_artifact')
    execution = load_yaml(context_raw.decode('utf-8'))
    if not isinstance(execution, dict):
        fail(5, 'Invalid CI execution context', 'ci_binding')
    command = execution.get('command')
    if (type(execution.get('version')) is not int or execution['version'] != 1
            or type(execution.get('run_id')) is not int or type(execution.get('run_attempt')) is not int
            or execution.get('repository', '').casefold() != repo.casefold()
            or execution.get('run_id') != identity or execution.get('run_attempt') != native['run_attempt']
            or execution.get('subject') != subject or execution.get('report') != 'ci-tests.xml'
            or execution.get('report_sha256') != hashlib.sha256(report).hexdigest()
            or not isinstance(command, dict) or set(command) != {'argv', 'cwd', 'exit_code'}
            or not isinstance(command['argv'], list) or not command['argv']
            or any(not isinstance(a, str) or not a for a in command['argv'])
            or command['cwd'] != '.' or type(command['exit_code']) is not int or command['exit_code'] != 0):
        fail(5, 'Execution context/report does not bind the native CI run and commit', 'ci_binding')
    checks = _selected(context['feature'], selected)
    records, assertions = [], []
    path = f'.project/artifacts/{uuid4()}'
    provenance = {'version': 1, 'kind': 'ci_import_review', 'reviewer': reviewer, 'note': note,
                  'run_ref': run_id, 'subject': subject, 'native_run': native, 'artifact': artifact,
                  'execution': execution, 'reviewed_at': utc_now()}
    supplied = {path + '/report.xml': report, path + '/context.json': context_raw,
                path + '/archive.zip': raw, path + '/provenance.json': json.dumps(provenance).encode()}
    artifacts = [{'path': name, 'sha256': hashlib.sha256(content).hexdigest()} for name, content in supplied.items()]
    for check in checks:
        configured = f.project['commands'].get(check.get('command_ref'), {})
        result, reason, counts = junit_result(report, check.get('testcase_refs'), command['exit_code'])
        if configured and any(command[k] != configured[k] for k in ['argv', 'cwd']):
            fail(5, 'CI execution command differs from the configured Check command', 'ci_command')
        if not configured.get('result') or check['activity'] == 'blocked' or result != 'passed':
            fail(5, 'CI report does not prove the selected configured assertions: ' + reason, 'ci_assertions')
        assertions.append({'check': check['id'], 'result': result, 'counts': counts})
        records.append({'version': 1, 'id': 'EVD-' + str(uuid4()), 'feature_ref': feature_id,
                        'check_ref': check['id'], 'type': 'ci_result',
                        'produced_by': {'run_ref': run_id, 'reviewer': reviewer}, 'result': 'passed',
                        'acceptance_revision': context['feature']['acceptance_revision'],
                        'requirement_revisions': {k: v['revision'] for k, v in context['requirements'].items()},
                        'subject': subject, 'check_digest': check_digest(check, f.project),
                        'command': deepcopy(command), 'artifacts': deepcopy(artifacts),
                        'note': f'Explicit GitHub CI import from run {identity}, artifact {artifact["id"]}: {note}',
                        'supersedes': list(check['evidence_refs']), 'created_at': utc_now()})
    return context, records, supplied, assertions, native, artifact


def import_ci(root, feature_id, run_id, expected, remote_run, artifact_name, selected, reviewer, note,
              *, apply=False, dry_run=False, client=None):
    f = valid(root)
    context, records, artifacts, assertions, native, artifact = collect(
        root, f, feature_id, run_id, expected, remote_run, artifact_name, selected, reviewer, note, client or GitHub())
    result = import_evidence(root, feature_id, run_id, expected, records, dry_run=(not apply or dry_run),
                             expected_context=context, incoming_artifacts=artifacts)
    return {**result, 'ci_run_url': native['html_url'], 'ci_artifact_id': artifact['id'],
            'ci_preview_checks': assertions}
