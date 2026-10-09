from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from apm.delivery import link_commit, link_mr
from apm.facts import dump_yaml, read_yaml, validate_project
from apm.operations import OperationError
from apm.state import current_subject, derive, utc_now
from apm.storage import RevisionConflict
from apm.verification import execute_checks
from .test_cli import cli
from .test_operations import snapshot
from .test_verification import configured, FAILED


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=True).stdout.decode().strip()


def repository(root):
    git(root, 'init')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
    return git(root, 'rev-parse', 'HEAD')


def fixture_mr(root, feature, run, state='merged'):
    f = validate_project(root)
    feature = f.features[feature['id']]
    identity = 'EVD-' + str(uuid4())
    artifact = root / '.project/artifacts/review.txt'; artifact.parent.mkdir(exist_ok=True)
    artifact.write_text('Synthetic fixture reviewer confirms this exact merge/ref/subject.\n')
    ref = 'https://example.invalid/pull/1'
    ev = {'version': 1, 'id': identity, 'feature_ref': feature['id'], 'type': 'delivery',
          'produced_by': {'run_ref': run['id'], 'reviewer': 'fixture-reviewer'}, 'result': 'passed',
          'acceptance_revision': feature['acceptance_revision'],
          'requirement_revisions': {ref: f.requirements[ref]['revision'] for ref in feature['requirement_refs']},
          'subject': feature['implementation']['subject'], 'delivery_ref': ref, 'delivery_state': state,
          'command': None, 'artifacts': [{'path': '.project/artifacts/review.txt', 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}],
          'note': 'Synthetic manual review; no actual remote merge claimed', 'supersedes': [], 'created_at': utc_now()}
    record = {'kind': 'mr', 'ref': ref, 'state': state, 'subject': ev['subject'], 'evidence_refs': [identity]}
    return {'record': record, 'evidence': [ev]}


def test_link_commit_resolves_sha_without_creating_commit_or_merge(project):
    feature, run = configured(project)
    sha = repository(project)
    f = validate_project(project); feature = f.features[feature['id']]
    feature['implementation']['subject'] = current_subject(project)
    (project / f.files[feature['id']]).write_text(dump_yaml(feature))
    before = git(project, 'rev-parse', 'HEAD')
    outcome = link_commit(project, feature['id'], sha[:9], run['id'], 1)
    assert outcome['record']['ref'] == sha and outcome['record']['state'] == 'committed'
    assert outcome['delivery'] == 'committed' and outcome['lifecycle'] == 'verifying'
    assert git(project, 'rev-parse', 'HEAD') == before
    ev = validate_project(project).evidence[outcome['record']['evidence_refs'][0]]
    assert ev['delivery_observation']['commit'] == sha and ev['delivery_observation']['tree'] == git(project, 'show', '-s', '--format=%T', sha)
    assert 'reviewer' not in ev['produced_by']


def test_historical_commit_does_not_cover_dirty_subject(project):
    feature, run = configured(project)
    sha = repository(project)
    (project / 'src/code.py').write_text('new code')
    f = validate_project(project); feature = f.features[feature['id']]
    feature['implementation']['subject'] = current_subject(project)
    (project / f.files[feature['id']]).write_text(dump_yaml(feature))
    outcome = link_commit(project, feature['id'], sha, run['id'], 1)
    assert outcome['record']['state'] == 'committed' and outcome['delivery'] == 'none'
    state = derive(validate_project(project), utc_now())['features'][0]
    assert not state['delivery_records'][0]['verified'] and state['lifecycle'] != 'delivered'


def test_git_dry_run_and_missing_ref_preserve_files(project):
    feature, run = configured(project); repository(project)
    before = snapshot(project)
    assert link_commit(project, feature['id'], 'HEAD', run['id'], 1, dry_run=True)['dry_run']
    assert snapshot(project) == before
    with pytest.raises(OperationError) as exc:
        link_commit(project, feature['id'], '--invalid-option', run['id'], 1)
    assert exc.value.code == 4 and snapshot(project) == before


def test_commit_duplicate_and_stale_revision_rejected(project):
    feature, run = configured(project); repository(project)
    link_commit(project, feature['id'], 'HEAD', run['id'], 1)
    with pytest.raises(RevisionConflict):
        link_commit(project, feature['id'], 'HEAD', run['id'], 1)
    with pytest.raises(OperationError) as exc:
        link_commit(project, feature['id'], 'HEAD', run['id'], 2)
    assert exc.value.code == 3


def test_local_commit_still_does_not_satisfy_merged_gate(project):
    feature, run = configured(project); repository(project)
    f = validate_project(project); feature = f.features[feature['id']]
    feature['implementation']['subject'] = current_subject(project)
    (project / f.files[feature['id']]).write_text(dump_yaml(feature))
    assert execute_checks(project, feature['id'], run['id'], 1)['required_passed']
    outcome = link_commit(project, feature['id'], 'HEAD', run['id'], 2)
    assert outcome['delivery'] == 'committed' and outcome['lifecycle'] == 'verified'


def test_manual_merge_binds_actual_review_without_remote_calls(project):
    feature, run = configured(project)
    execute_checks(project, feature['id'], run['id'], 1)
    payload = fixture_mr(project, feature, run)
    outcome = link_mr(project, feature['id'], payload, run['id'], 2)
    assert outcome['delivery'] == 'merged' and outcome['lifecycle'] == 'delivered'
    (project / payload['evidence'][0]['artifacts'][0]['path']).write_text('overwritten original')
    assert derive(validate_project(project), utc_now())['features'][0]['lifecycle'] == 'delivered'


@pytest.mark.parametrize('change', [
    lambda p: p['evidence'][0].update(produced_by=None),
    lambda p: p['evidence'][0].update(delivery_ref='other MR'),
    lambda p: p['evidence'][0].update(delivery_state='mr_open'),
    lambda p: p['evidence'][0].update(subject={'kind': 'commit', 'value': 'a' * 40}),
    lambda p: p['evidence'][0]['produced_by'].pop('reviewer'),
    lambda p: p['record'].update(kind='commit'),
    lambda p: p['record'].update(evidence_refs=[]),
])
def test_manual_merge_wrong_binding_or_no_reviewer_rejected(project, change):
    feature, run = configured(project)
    payload = fixture_mr(project, feature, run); change(payload)
    before = snapshot(project)
    with pytest.raises(OperationError) as exc:
        link_mr(project, feature['id'], payload, run['id'], 1)
    assert exc.value.code == 2 and snapshot(project) == before


def test_merge_fact_does_not_hide_failed_or_stale_verification(project):
    feature, run = configured(project, FAILED)
    assert not execute_checks(project, feature['id'], run['id'], 1)['required_passed']
    outcome = link_mr(project, feature['id'], fixture_mr(project, feature, run), run['id'], 2)
    assert outcome['delivery'] == 'merged' and outcome['lifecycle'] == 'verifying'


def test_manual_policy_remote_or_expired_proof_stays_unverified(project):
    feature, run = configured(project)
    payload = fixture_mr(project, feature, run)
    payload['evidence'][0]['artifacts'][0]['expires_at'] = '2020-01-01T00:00:00Z'
    outcome = link_mr(project, feature['id'], payload, run['id'], 1)
    assert outcome['delivery'] == 'none'
    payload = fixture_mr(project, feature, run)
    payload['record']['ref'] = payload['evidence'][0]['delivery_ref'] = 'https://example.invalid/pull/2'
    payload['evidence'][0]['artifacts'] = [{'url': 'https://example.invalid/review'}]
    assert link_mr(project, feature['id'], payload, run['id'], 2)['delivery'] == 'none'
    path = project / '.project/project.yaml'; data = read_yaml(path)
    data['policies']['allow_manual_evidence'] = False; path.write_text(dump_yaml(data))
    payload = fixture_mr(project, feature, run)
    payload['record']['ref'] = payload['evidence'][0]['delivery_ref'] = 'https://example.invalid/pull/3'
    assert link_mr(project, feature['id'], payload, run['id'], 3)['delivery'] == 'none'


def test_mr_snapshot_update_requires_explicit_supersedes(project):
    feature, run = configured(project)
    first = fixture_mr(project, feature, run, 'mr_open')
    link_mr(project, feature['id'], first, run['id'], 1)
    second = fixture_mr(project, feature, run, 'merged')
    with pytest.raises(OperationError) as exc:
        link_mr(project, feature['id'], second, run['id'], 2)
    assert exc.value.code == 3
    second['evidence'][0]['supersedes'] = first['record']['evidence_refs']
    outcome = link_mr(project, feature['id'], second, run['id'], 2)
    assert outcome['record']['state'] == 'merged'
    assert len(validate_project(project).features[feature['id']]['delivery']['records']) == 1


def test_mr_dry_run_and_revision_conflict(project):
    feature, run = configured(project)
    payload = fixture_mr(project, feature, run); before = snapshot(project)
    assert link_mr(project, feature['id'], payload, run['id'], 1, dry_run=True)['dry_run']
    assert snapshot(project) == before
    with pytest.raises(RevisionConflict):
        link_mr(project, feature['id'], payload, run['id'], 999)
    assert snapshot(project) == before


def test_commit_cli_requires_run_and_revision(project):
    feature, run = configured(project); repository(project)
    assert cli(project, 'feature', 'link-commit', feature['id'], 'HEAD')[0] == 2
    code, result = cli(project, 'feature', 'link-commit', feature['id'], 'HEAD', '--run-id', run['id'], '--expected-revision', '1')
    assert code == 0 and result['data']['record']['ref'] == git(project, 'rev-parse', 'HEAD')


def test_commit_observation_is_rechecked_and_transaction_recoverable(project, monkeypatch):
    import apm.storage as storage
    from apm.storage import pending_transactions, recover
    feature, run = configured(project); repository(project)
    f = validate_project(project); feature = f.features[feature['id']]
    feature['implementation']['subject'] = current_subject(project)
    (project / f.files[feature['id']]).write_text(dump_yaml(feature))
    original = storage._replace
    def crash(path, text):
        if path.parent.name == 'core': raise OSError('fixture interruption')
        original(path, text)
    with monkeypatch.context() as patch:
        patch.setattr(storage, '_replace', crash)
        with pytest.raises(OSError): link_commit(project, feature['id'], 'HEAD', run['id'], 1)
    assert pending_transactions(project) and recover(project)
    f = validate_project(project); assert not f.errors
    assert derive(f, utc_now())['features'][0]['delivery'] == 'committed'
    ev = next(iter(f.evidence.values())); ev['delivery_observation']['tree'] = '0' * 40
    (project / f.files[ev['id']]).write_text(dump_yaml(ev))
    assert derive(validate_project(project), utc_now())['features'][0]['delivery'] == 'none'
