"""Read-only derivation. Evidence and commits never imply completion by themselves."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

from .facts import Facts, parse_timestamp, safe_path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def canonical_digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def check_digest(check: dict, project: dict) -> str:
    value = {key: check.get(key) for key in
                             ['id', 'acceptance_ref', 'required', 'command_ref']} | {
        'command': project['commands'].get(check.get('command_ref'))
    }
    if 'testcase_refs' in check:
        value['testcase_refs'] = check['testcase_refs']
    return canonical_digest(value)


EXCLUDED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'dist'}


def _included(name: str) -> bool:
    parts = Path(name).parts
    return bool(parts) and parts[0] != '.project' and not any(part in EXCLUDED for part in parts)


def current_subject(root: Path) -> dict:
    head_entries = {}
    def git(*args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=False)
        if result.returncode:
            raise ValueError('Git cannot inspect code subject')
        return result.stdout

    try:
        git('rev-parse', '--git-dir')
    except ValueError:
        names = sorted(p.relative_to(root).as_posix() for p in root.rglob('*')
                       if p.is_file() and _included(p.relative_to(root).as_posix()))
        head = 'no-git'
        clean = False
    else:
        head_process = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', 'HEAD'], capture_output=True)
        head = head_process.stdout.decode().strip() if head_process.returncode == 0 else 'unborn'
        if head != 'unborn':
            for row in git('ls-tree', '-rz', 'HEAD').split(b'\0'):
                if row:
                    metadata, name = row.split(b'\t', 1)
                    mode, _, blob = metadata.split()
                    name = os.fsdecode(name)
                    if _included(name):
                        head_entries[name] = (mode.decode(), blob.decode())
        names = {os.fsdecode(n) for n in git('ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0') if n}
        # HEAD paths retain tombstones for staged deletions. Missing staged additions
        # have no source bytes and must not make a restored snapshot depend on its index.
        names = sorted(name for name in names | head_entries.keys() if _included(name)
                       and (name in head_entries or (root / name).exists() or (root / name).is_symlink()))
        clean = head != 'unborn' and set(names) == set(head_entries)
    entries = []
    for name in names:
        path = safe_path(root, name)
        original = root / name
        if original.is_symlink():
            content = os.readlink(original).encode('utf-8')
            kind = 'symlink'
            mode = '120000'
        elif path.is_file():
            content = path.read_bytes()
            kind = 'executable' if path.stat().st_mode & 0o111 else 'file'
            mode = '100755' if kind == 'executable' else '100644'
        else:
            content, kind = b'', 'deleted'
            mode = None
        # Inspect actual bytes/modes instead of trusting Git's index flags, stat
        # cache or core.filemode. Clean commit subjects require exact blob identity.
        blob = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        if head_entries.get(name) != (mode, blob):
            clean = False
        entries.append([name, kind, hashlib.sha256(content).hexdigest()])
    if clean:
        return {'kind': 'commit', 'value': head}
    return {'kind': 'working_tree', 'value': canonical_digest({'head': head, 'files': entries})}


def _freshness(f: Facts, feature: dict, ev: dict, at: datetime,
               actual_subject: dict | None, check: dict | None = None) -> list[str]:
    reasons = []
    if ev['result'] == 'not_verified':
        reasons.append('not_verified')
    if ev['acceptance_revision'] != feature['acceptance_revision']:
        reasons.append('stale_acceptance')
    revisions = {ref: f.requirements[ref]['revision'] for ref in feature['requirement_refs']}
    if ev['requirement_revisions'] != revisions:
        reasons.append('stale_requirements')
    if ev['subject'] != feature['implementation']['subject']:
        reasons.append('stale_subject')
    if ev['subject']['kind'] == 'example':
        reasons.append('example_evidence')
    elif actual_subject is not None and ev['subject'] != actual_subject:
        reasons.append('stale_code')
    if check and ev.get('check_digest') != check_digest(check, f.project):
        reasons.append('stale_check')
    configured = f.project['commands'].get(check.get('command_ref')) if check else None
    if configured and ev['type'] in {'test', 'ci_result'}:
        if not ev['command'] or any(ev['command'].get(key) != configured[key] for key in ['argv', 'cwd']):
            reasons.append('command_mismatch')
    if ev['type'] == 'code_reference':
        reasons.append('code_reference_is_not_behavior')
    if ev['type'] in {'api_response', 'screenshot'}:
        reasons.append('observation_requires_manual_review')
    if ev['type'] == 'manual_review' and not f.project['policies']['allow_manual_evidence']:
        reasons.append('manual_evidence_disabled')
    if ev['type'] == 'delivery' and not ev.get('delivery_observation') and not f.project['policies']['allow_manual_evidence']:
        reasons.append('manual_evidence_disabled')
    if ev.get('delivery_observation'):
        observation = ev['delivery_observation']
        process = subprocess.run(['git', '-C', str(f.root), 'show', '-s', '--format=%T', observation['commit']], capture_output=True)
        if process.returncode or process.stdout.decode().strip() != observation['tree']:
            reasons.append('git_observation_unverified')
    if not ev['artifacts']:
        reasons.append('missing_artifacts')
    for artifact in ev['artifacts']:
        if artifact.get('expires_at') and parse_timestamp(artifact['expires_at']) <= at:
            reasons.append('expired_artifact')
        if 'url' in artifact:
            reasons.append('remote_artifact_unverified')
        else:
            target = safe_path(f.root, artifact['path'])
            if not target.is_file():
                reasons.append('missing_artifact')
            elif artifact.get('sha256') and hashlib.sha256(target.read_bytes()).hexdigest() != artifact['sha256']:
                reasons.append('artifact_checksum_mismatch')
    if parse_timestamp(ev['created_at']) > at:
        reasons.append('future_evidence')
    return sorted(set(reasons))


def _check_state(f: Facts, feature: dict, check: dict, at: datetime,
                 actual_subject: dict | None) -> dict:
    evidence = [f.evidence[ref] for ref in check['evidence_refs']]
    # An explicit replacement chain retires old records even if its new result failed
    # or became stale; do not resurrect an old PASS.
    superseded = set()
    pending = [ref for ev in evidence for ref in ev['supersedes']]
    while pending:
        ref = pending.pop()
        if ref not in superseded:
            superseded.add(ref)
            pending.extend(f.evidence[ref]['supersedes'])
    details = []
    results = set()
    for ev in evidence:
        reasons = _freshness(f, feature, ev, at, actual_subject, check)
        if ev['id'] in superseded:
            reasons.append('superseded')
        details.append({'id': ev['id'], 'result': ev['result'], 'valid': not reasons, 'reasons': reasons})
        if not reasons:
            results.add(ev['result'])
    if check['activity'] == 'blocked' or {'passed', 'failed'}.issubset(results):
        state = 'blocked'
    elif 'failed' in results:
        state = 'failed'
    elif check['activity'] == 'running':
        state = 'in_progress'
    elif 'passed' in results:
        state = 'passed'
    else:
        state = 'not_started'
    return {'id': check['id'], 'acceptance_ref': check['acceptance_ref'],
            'required': check['required'], 'state': state, 'evidence': details}


DELIVERY_RANK = {'none': 0, 'committed': 1, 'mr_open': 2, 'merged': 3, 'released': 4, 'deployed': 5}


def derive(f: Facts, evaluated_at: str, actual_subject: dict | None = None) -> dict:
    if f.errors:
        raise ValueError('Cannot derive state from invalid facts')
    at = parse_timestamp(evaluated_at)
    if at.tzinfo is None:
        raise ValueError('Evaluation time must include timezone')
    if actual_subject is None and f.project['mode'] != 'example':
        actual_subject = current_subject(f.root)
    states: dict[str, dict] = {}
    for identity, feature in sorted(f.features.items()):
        checks = [_check_state(f, feature, check, at, actual_subject)
                  for check in feature['verification']['checks']]
        required_ac_ids = {ac['id'] for ac in feature['acceptance'] if ac['required']}
        required = [c for c in checks if c['required'] and c['acceptance_ref'] in required_ac_ids]
        values = [c['state'] for c in required]
        if 'blocked' in values:
            verification = 'blocked'
        elif 'failed' in values:
            verification = 'failed'
        elif 'in_progress' in values:
            verification = 'in_progress'
        elif all(v == 'passed' for v in values):
            verification = 'passed'
        elif 'passed' in values:
            verification = 'partial'
        else:
            verification = 'not_started'
        verified_ac = [ac for ac in sorted(required_ac_ids)
                       if all(c['state'] == 'passed' for c in required if c['acceptance_ref'] == ac)]
        delivery = 'none'
        delivery_details = []
        for record in feature['delivery']['records']:
            evidence = [f.evidence[ref] for ref in record['evidence_refs']]
            retired = set()
            pending_evidence = [ref for ev in evidence for ref in ev['supersedes']]
            while pending_evidence:
                ref = pending_evidence.pop()
                if ref not in retired:
                    retired.add(ref)
                    pending_evidence.extend(f.evidence[ref]['supersedes'])
            effective_results = {ev['result'] for ev in evidence if ev['id'] not in retired
                                 and ev.get('delivery_ref', record['ref']) == record['ref']
                                 and ev.get('delivery_state', record['state']) == record['state']
                                 and not _freshness(f, feature, ev, at, actual_subject)}
            valid = (record['subject'] == feature['implementation']['subject']
                     and (actual_subject is None or record['subject'] == actual_subject)
                     and effective_results == {'passed'})
            delivery_details.append({'ref': record['ref'], 'state': record['state'], 'verified': valid})
            if valid and DELIVERY_RANK[record['state']] > DELIVERY_RANK[delivery]:
                delivery = record['state']
        requirements = [f.requirements[ref] for ref in feature['requirement_refs']]
        statuses = {r['status'] for r in requirements}
        requirement_state = next((s for s in ['blocked', 'changed', 'draft'] if s in statuses), 'confirmed')
        implementation = feature['implementation']['state']
        reasons = []
        # Required Check activity blocks the Feature; evidence conflict also prevents
        # progression. Optional checks do not change the required lifecycle.
        if (feature['blockers'] or any(r['blockers'] for r in requirements)
                or requirement_state == 'blocked' or implementation == 'blocked'
                or verification == 'blocked'):
            lifecycle = 'blocked'
            reasons.append('Explicit blocker or required verification conflict')
        elif requirement_state in {'draft', 'changed'}:
            lifecycle = 'draft'
            reasons.append('Requirements are not confirmed at their current revisions')
        elif implementation == 'not_started':
            lifecycle = 'ready'
            reasons.append('Confirmed requirements; implementation not started')
        elif implementation == 'in_progress':
            lifecycle = 'developing'
            reasons.append('Implementation is in progress')
        elif verification != 'passed':
            lifecycle = 'verifying'
            reasons.append('Required AC lack valid passing evidence')
        elif DELIVERY_RANK[delivery] < DELIVERY_RANK[f.project['policies']['delivery_gate']]:
            lifecycle = 'verified'
            reasons.append('Required AC passed; delivery gate not reached')
        else:
            lifecycle = 'deployed' if delivery == 'deployed' else 'delivered'
            reasons.append('Implementation, required AC and delivery gate satisfied')
        active_runs = [r['id'] for r in f.runs.values() if r['status'] == 'active'
                       and any(c['feature_ref'] == identity for c in r['claims'])]
        handoffs = sorted((h for h in f.handoffs.values() if identity in h['feature_refs']),
                          key=lambda h: (parse_timestamp(h['created_at']), h['id']))
        states[identity] = {'id': identity, 'title': feature['title'], 'domain': feature['domain'],
                            'example': f.project['mode'] == 'example', 'requirement': requirement_state,
                            'implementation': implementation, 'verification': verification,
                            'delivery': delivery, 'lifecycle': lifecycle, 'reasons': reasons,
                            'required_ac': len(required_ac_ids), 'passed_ac': len(verified_ac),
                            'checks': checks, 'delivery_records': delivery_details,
                            'requirement_refs': feature['requirement_refs'],
                            'depends_on': feature['depends_on'], 'remaining': feature['implementation']['remaining'],
                            'active_runs': sorted(active_runs), 'latest_handoff': handoffs[-1]['id'] if handoffs else None}
    # Dependencies are a DAG. Evaluate bottom-up without recursion and propagate gates.
    pending = set(states)
    finished = set()
    gate = {'verified', 'delivered', 'deployed'} if f.project['policies']['dependency_gate'] == 'verified' else {'delivered', 'deployed'}
    while pending:
        progressed = False
        for identity in sorted(pending):
            deps = f.features[identity]['depends_on']
            if not set(deps).issubset(finished):
                continue
            unmet = [ref for ref in deps if states[ref]['lifecycle'] not in gate]
            if unmet:
                states[identity]['lifecycle'] = 'blocked'
                states[identity]['reasons'].append('Dependency gate not met: ' + ', '.join(unmet))
            pending.remove(identity)
            finished.add(identity)
            progressed = True
        if not progressed:
            raise ValueError('Cannot derive cyclic dependencies')
    distribution = {}
    for state in states.values():
        distribution[state['lifecycle']] = distribution.get(state['lifecycle'], 0) + 1
    return {'rule_version': 1, 'evaluated_at': evaluated_at, 'example': f.project['mode'] == 'example',
            'code_subject': actual_subject, 'features': list(states.values()),
            'summary': {'total': len(states), 'lifecycle': distribution,
                        'required_ac': sum(s['required_ac'] for s in states.values()),
                        'passed_ac': sum(s['passed_ac'] for s in states.values()),
                        'active_runs': sum(r['status'] == 'active' for r in f.runs.values())}}


def claim_ranges(f: Facts, claim: dict) -> list[tuple[str, bool]] | None:
    scope = claim['scope']
    if scope['type'] == 'path':
        values = [scope['value']]
    elif scope['type'] == 'component':
        values = f.project['components'][scope['value']]
    else:
        components = f.features[claim['feature_ref']]['implementation']['components']
        if not components:
            return None  # Unknown full Feature scope must be treated conservatively.
        values = [value for key in components for value in f.project['components'][key]]
    result = []
    for value in values:
        directory = value == '.' or value.endswith(('/', '/**')) or safe_path(f.root, value, claim=True).is_dir()
        normalized = value.removesuffix('/**').rstrip('/')
        result.append((normalized, directory))
    return result


def claims_overlap(f: Facts, a: dict, b: dict) -> bool:
    if a['feature_ref'] == b['feature_ref'] and ('feature' in {a['scope']['type'], b['scope']['type']}):
        return True
    left, right = claim_ranges(f, a), claim_ranges(f, b)
    if left is None or right is None:
        return True
    for x, xdir in left:
        for y, ydir in right:
            if x == y or (xdir and (x == '.' or y.startswith(x + '/'))) or (ydir and (y == '.' or x.startswith(y + '/'))):
                return True
    return False


def active_claims(f: Facts) -> list[dict]:
    return [{'run_ref': r['id'], **claim} for r in sorted(f.runs.values(), key=lambda r: r['id'])
            if r['status'] == 'active' for claim in r['claims']]


def conflicts(f: Facts) -> list[dict]:
    claims = active_claims(f)
    found = []
    for i, a in enumerate(claims):
        for b in claims[i + 1:]:
            if a['run_ref'] != b['run_ref'] and claims_overlap(f, a, b):
                found.append({'left': a, 'right': b,
                              'overridden': bool(a.get('override_reason') or b.get('override_reason'))})
    return found
