"""Read-only Git observations and explicit manual delivery evidence."""

from __future__ import annotations

from copy import deepcopy
import subprocess
from pathlib import Path
from uuid import uuid4

from .facts import dump_yaml
from .operations import fail, valid
from .state import current_subject, derive, utc_now
from .storage import commit_files, project_lock
from .verification import _artifact, snapshot_artifacts, write_context


def _git_commit(root: Path, ref: str) -> tuple[str, str]:
    if not ref or not ref.strip():
        fail(2, 'Commit ref must be nonempty', 'invalid_ref')
    resolved = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}'], capture_output=True)
    if resolved.returncode:
        fail(4, 'Git commit does not exist or cannot be read', 'commit_not_found')
    sha = resolved.stdout.decode().strip()
    observed = subprocess.run(['git', '-C', str(root), 'show', '-s', '--format=%T', sha], capture_output=True)
    if observed.returncode:
        fail(4, 'Git tree cannot be observed', 'commit_not_found')
    return sha, observed.stdout.decode().strip()


def _outcome(root, feature_id, record, dry_run):
    state = next(s for s in derive(valid(root), utc_now())['features'] if s['id'] == feature_id)
    return {'id': feature_id, 'record': record, 'dry_run': dry_run,
            'delivery': state['delivery'], 'lifecycle': state['lifecycle']}


def link_commit(root: Path, feature_id: str, ref: str, run_id: str, expected: int,
                *, dry_run: bool = False) -> dict:
    def prepare():
        f = valid(root)
        snapshot = write_context(f, feature_id, run_id, expected)
        sha, tree = _git_commit(root, ref)
        feature = deepcopy(snapshot['feature'])
        if any(r['kind'] == 'commit' and r['ref'] == sha for r in feature['delivery']['records']):
            fail(3, 'Commit record already exists', 'delivery_exists')
        subject = {'kind': 'commit', 'value': sha}
        identity = 'EVD-' + str(uuid4())
        writes = {}
        observation = {'kind': 'git_commit', 'commit': sha, 'tree': tree}
        name = f'.project/artifacts/{uuid4()}/commit.json'
        artifact = _artifact(name, dump_yaml(observation).encode(), writes)
        ev = {'version': 1, 'id': identity, 'feature_ref': feature_id, 'type': 'delivery',
              'produced_by': {'run_ref': run_id}, 'result': 'passed',
              'acceptance_revision': feature['acceptance_revision'],
              'requirement_revisions': {k: v['revision'] for k, v in snapshot['requirements'].items()},
              'subject': subject, 'delivery_ref': sha, 'delivery_state': 'committed',
              'delivery_observation': observation, 'command': None, 'artifacts': [artifact],
              'note': 'Observed local Git commit/tree; does not prove merge, release or deployment',
              'supersedes': [], 'created_at': utc_now()}
        record = {'kind': 'commit', 'ref': sha, 'state': 'committed', 'subject': subject, 'evidence_refs': [identity]}
        feature['delivery']['records'].append(record)
        feature['revision'] += 1
        feature['metadata']['updated_at'] = utc_now()
        changes = {f'.project/evidence/{identity}.yaml': ev, f.files[feature_id]: feature}
        valid(root, changes)
        return record, writes, changes
    if dry_run:
        record, _, _ = prepare()
        return _outcome(root, feature_id, record, True)
    with project_lock(root):
        record, writes, changes = prepare()
        commit_files(root, {**writes, **{name: dump_yaml(value) for name, value in changes.items()}})
        return _outcome(root, feature_id, record, False)


def link_mr(root: Path, feature_id: str, payload: dict, run_id: str, expected: int,
            *, dry_run: bool = False) -> dict:
    if not isinstance(payload, dict) or set(payload) != {'record', 'evidence'}:
        fail(2, 'MR input must be {record, evidence}', 'invalid_delivery')
    record, records = deepcopy(payload['record']), deepcopy(payload['evidence'])
    if (not isinstance(record, dict) or record.get('kind') != 'mr'
            or not isinstance(records, list) or not records or any(not isinstance(ev, dict) for ev in records)):
        fail(2, 'Expected MR record and nonempty delivery Evidence list', 'invalid_delivery')
    def prepare():
        f = valid(root)
        snapshot = write_context(f, feature_id, run_id, expected)
        feature = deepcopy(snapshot['feature'])
        ids = [ev.get('id') for ev in records]
        if any(not isinstance(identity, str) for identity in ids):
            fail(2, 'Evidence IDs are required', 'invalid_delivery')
        if len(ids) != len(set(ids)) or any(identity in f.evidence for identity in ids):
            fail(3, 'Delivery Evidence cannot overwrite or duplicate existing IDs', 'evidence_exists')
        if set(record.get('evidence_refs', [])) != set(ids):
            fail(2, 'MR record must reference exactly the supplied delivery Evidence', 'delivery_binding')
        changes = {}
        for ev in records:
            if (not isinstance(ev.get('produced_by'), dict)
                    or ev.get('type') != 'delivery' or ev.get('check_ref') or ev.get('delivery_observation')
                    or ev.get('feature_ref') != feature_id or ev.get('produced_by', {}).get('run_ref') != run_id
                    or ev.get('delivery_ref') != record.get('ref') or ev.get('delivery_state') != record.get('state')
                    or ev.get('subject') != record.get('subject')):
                fail(2, 'MR Evidence must bind this Run/Feature/ref/state/subject', 'delivery_binding')
            changes[f'.project/evidence/{ev["id"]}.yaml'] = ev
        existing = [r for r in feature['delivery']['records'] if r['kind'] == 'mr' and r['ref'] == record.get('ref')]
        if existing:
            # Updating the same delivery snapshot must explicitly retire its old evidence.
            retired = {ref for ev in records for ref in ev.get('supersedes', [])}
            if not set(existing[0]['evidence_refs']).issubset(retired):
                fail(3, 'Updating MR requires explicit supersedes of prior evidence', 'delivery_conflict')
            feature['delivery']['records'] = [r for r in feature['delivery']['records'] if r not in existing]
        feature['delivery']['records'].append(record)
        feature['revision'] += 1
        feature['metadata']['updated_at'] = utc_now()
        changes[f.files[feature_id]] = feature
        valid(root, changes)
        writes = {}
        for name, ev in list(changes.items()):
            if ev.get('type') == 'delivery':
                changes[name] = snapshot_artifacts(root, ev, writes, str(uuid4()))
        valid(root, changes)
        return changes, writes
    if dry_run:
        prepare()
        return _outcome(root, feature_id, record, True)
    with project_lock(root):
        changes, writes = prepare()
        commit_files(root, {**writes, **{name: dump_yaml(value) for name, value in changes.items()}})
        return _outcome(root, feature_id, record, False)
