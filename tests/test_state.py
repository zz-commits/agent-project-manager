from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import subprocess
from uuid import uuid4

import pytest

from apm.facts import dump_yaml, read_yaml, validate_project
from apm.operations import start_run
from apm.state import check_digest, current_subject, derive


AT = '2026-10-08T12:00:00Z'


def write_feature(root, data):
    path = root / '.project/features/core' / (data['id'] + '.yaml')
    path.write_text(dump_yaml(data))


def evaluated(root):
    facts = validate_project(root)
    assert not facts.errors
    return derive(facts, AT)['features'][0]


def passing_evidence(root):
    f = validate_project(root)
    feature = deepcopy(next(iter(f.features.values())))
    run = start_run(root, feature['id'], 'test', 'worker', 'path:src/**')['run']
    feature['implementation']['state'] = 'complete'
    feature['implementation']['subject'] = current_subject(root)
    feature['implementation']['remaining'] = []
    write_feature(root, feature)
    artifact = root / '.project/evidence/result.txt'
    artifact.write_text('Actual fixture assertion result\n')
    check = feature['verification']['checks'][0]
    ev = {'version': 1, 'id': 'EVD-' + str(uuid4()), 'feature_ref': feature['id'],
          'check_ref': check['id'], 'type': 'test', 'produced_by': {'run_ref': run['id']},
          'result': 'passed', 'acceptance_revision': feature['acceptance_revision'],
          'requirement_revisions': {identity: f.requirements[identity]['revision'] for identity in feature['requirement_refs']},
          'subject': current_subject(root), 'check_digest': check_digest(check, f.project),
          'command': {**f.project['commands'][check['command_ref']], 'exit_code': 0},
          'artifacts': [{'path': '.project/evidence/result.txt', 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}],
          'note': 'Synthetic test fixture; not evidence of actual product delivery',
          'supersedes': [], 'created_at': '2026-10-08T00:00:00Z'}
    check['evidence_refs'] = [ev['id']]
    write_feature(root, feature)
    (root / '.project/evidence' / (ev['id'] + '.yaml')).write_text(dump_yaml(ev))
    return feature, ev


def rewrite_evidence(root, ev):
    (root / '.project/evidence' / (ev['id'] + '.yaml')).write_text(dump_yaml(ev))


def test_no_evidence_never_means_done(project, mutate):
    assert evaluated(project)['lifecycle'] == 'ready'
    mutate('feature', lambda d: d['implementation'].update(state='complete', subject=current_subject(project)))
    state = evaluated(project)
    assert state['lifecycle'] == 'verifying'
    assert state['verification'] == 'not_started'


def test_required_pass_is_verified_without_delivery(project):
    passing_evidence(project)
    state = evaluated(project)
    assert state['lifecycle'] == 'verified'
    assert state['passed_ac'] == state['required_ac'] == 1
    assert state['delivery'] == 'none'


@pytest.mark.parametrize('change,reason', [
    (lambda f, ev: ev.update(acceptance_revision=99), 'stale_acceptance'),
    (lambda f, ev: ev.update(requirement_revisions={}), 'stale_requirements'),
    (lambda f, ev: ev.update(subject={'kind':'commit','value':'a'*40}), 'stale_subject'),
    (lambda f, ev: ev.update(check_digest='sha256:'+'a'*64), 'stale_check'),
    (lambda f, ev: ev.update(result='not_verified'), 'not_verified'),
    (lambda f, ev: ev['artifacts'][0].update(sha256='0'*64), 'artifact_checksum_mismatch'),
    (lambda f, ev: ev['artifacts'][0].update(expires_at='2026-10-07T00:00:00Z'), 'expired_artifact'),
    (lambda f, ev: ev.update(created_at='2026-10-09T00:00:00Z'), 'future_evidence'),
    (lambda f, ev: ev.update(artifacts=[{'url':'https://example.com/result'}]), 'remote_artifact_unverified'),
])
def test_stale_missing_or_unverified_evidence_cannot_pass(project, change, reason):
    feature, ev = passing_evidence(project)
    change(feature, ev)
    rewrite_evidence(project, ev)
    state = evaluated(project)
    assert state['lifecycle'] == 'verifying'
    assert reason in state['checks'][0]['evidence'][0]['reasons']


def test_missing_artifact_cannot_pass(project):
    passing_evidence(project)
    (project / '.project/evidence/result.txt').unlink()
    assert evaluated(project)['lifecycle'] == 'verifying'


def test_code_change_invalidates_pass_without_metadata_update(project):
    passing_evidence(project)
    (project / 'src/code.py').write_text('value = 2\n')
    state = evaluated(project)
    assert state['lifecycle'] == 'verifying'
    assert 'stale_code' in state['checks'][0]['evidence'][0]['reasons']


def test_command_change_invalidates_check_definition(project, mutate):
    passing_evidence(project)
    mutate('project', lambda d: d['commands']['test'].update(argv=['false']))
    assert evaluated(project)['lifecycle'] == 'verifying'
    assert 'stale_check' in evaluated(project)['checks'][0]['evidence'][0]['reasons']


def test_different_recorded_command_cannot_pass(project):
    feature,ev=passing_evidence(project)
    ev['command']['argv']=['true']
    rewrite_evidence(project,ev)
    assert 'command_mismatch' in evaluated(project)['checks'][0]['evidence'][0]['reasons']
    assert evaluated(project)['lifecycle']=='verifying'


def test_conflicting_evidence_blocks_and_explicit_replacement_fails(project):
    feature, ev = passing_evidence(project)
    second = deepcopy(ev)
    second['id'] = 'EVD-' + str(uuid4())
    second['result'] = 'failed'
    second['command']['exit_code'] = 1
    rewrite_evidence(project, second)
    feature['verification']['checks'][0]['evidence_refs'].append(second['id'])
    write_feature(project, feature)
    assert evaluated(project)['verification'] == 'blocked'
    assert evaluated(project)['lifecycle'] == 'blocked'
    second['supersedes'] = [ev['id']]
    rewrite_evidence(project, second)
    assert evaluated(project)['verification'] == 'failed'
    assert evaluated(project)['lifecycle'] == 'verifying'
    # A stale replacement must not resurrect the retired PASS.
    second['acceptance_revision'] = 99
    rewrite_evidence(project, second)
    assert evaluated(project)['verification'] == 'not_started'


def test_supersedes_cycle_rejected(project):
    feature, ev = passing_evidence(project)
    ev['supersedes'] = [ev['id']]
    rewrite_evidence(project, ev)
    assert any(e.code == 'supersedes_cycle' for e in validate_project(project).errors)


def test_optional_failure_or_blocker_does_not_block_required_pass(project):
    feature, ev = passing_evidence(project)
    feature['acceptance'].append({'id':'AC-OPTIONAL','description':'optional','required':False})
    feature['verification']['checks'].append({'id':'CHECK-OPTIONAL','acceptance_ref':'AC-OPTIONAL',
                                            'required':True,'activity':'blocked','evidence_refs':[]})
    write_feature(project, feature)
    assert evaluated(project)['verification'] == 'passed'
    assert evaluated(project)['lifecycle'] == 'verified'


def test_manual_evidence_requires_policy(project, mutate):
    feature, ev = passing_evidence(project)
    ev['type'] = 'manual_review'
    ev['produced_by']['reviewer'] = 'reviewer'
    ev['command'] = None
    rewrite_evidence(project, ev)
    assert evaluated(project)['verification'] == 'passed'
    mutate('project', lambda d: d['policies'].update(allow_manual_evidence=False))
    assert evaluated(project)['lifecycle'] == 'verifying'


def test_default_gate_commit_is_not_delivered_and_merge_needs_pass(project):
    feature, ev = passing_evidence(project)
    delivery = deepcopy(ev)
    delivery['id'] = 'EVD-' + str(uuid4())
    delivery['type'] = 'delivery'
    delivery.pop('check_ref')
    delivery.pop('check_digest')
    delivery['produced_by']['reviewer'] = 'reviewer'
    rewrite_evidence(project, delivery)
    record = {'kind':'commit','ref':'commit-reference','state':'committed','subject':ev['subject'],'evidence_refs':[delivery['id']]}
    feature['delivery']['records'] = [record]
    write_feature(project, feature)
    assert evaluated(project)['delivery'] == 'committed'
    assert evaluated(project)['lifecycle'] == 'verified'
    record.update(kind='mr', state='merged', ref='reviewed-merge')
    write_feature(project, feature)
    assert evaluated(project)['lifecycle'] == 'delivered'
    ev['result'] = 'failed'
    ev['command']['exit_code'] = 1
    rewrite_evidence(project, ev)
    assert evaluated(project)['delivery'] == 'merged'
    assert evaluated(project)['lifecycle'] == 'verifying'


def test_conflicting_or_replaced_delivery_evidence_cannot_deliver(project):
    feature,ev=passing_evidence(project)
    delivery=deepcopy(ev)
    delivery['id']='EVD-'+str(uuid4())
    delivery['type']='delivery'
    delivery.pop('check_ref');delivery.pop('check_digest')
    delivery['produced_by']['reviewer']='reviewer'
    rewrite_evidence(project,delivery)
    failed=deepcopy(delivery)
    failed['id']='EVD-'+str(uuid4());failed['result']='failed'
    rewrite_evidence(project,failed)
    feature['delivery']['records']=[{'kind':'mr','ref':'reviewed merge','state':'merged',
                                    'subject':ev['subject'],'evidence_refs':[delivery['id'],failed['id']]}]
    write_feature(project,feature)
    assert evaluated(project)['lifecycle']=='verified'
    failed['supersedes']=[delivery['id']]
    rewrite_evidence(project,failed)
    assert evaluated(project)['delivery']=='none'


def test_dependency_blocking_propagates(project):
    f = validate_project(project)
    one = deepcopy(next(iter(f.features.values())))
    two = deepcopy(one)
    two['id'] = 'FEAT-' + str(uuid4())
    two['depends_on'] = [one['id']]
    write_feature(project, two)
    three = deepcopy(two)
    three['id'] = 'FEAT-' + str(uuid4())
    three['depends_on'] = [two['id']]
    write_feature(project, three)
    states = {s['id']:s for s in derive(validate_project(project), AT)['features']}
    assert states[one['id']]['lifecycle'] == 'ready'
    assert states[two['id']]['lifecycle'] == states[three['id']]['lifecycle'] == 'blocked'


def test_subject_ignores_metadata_but_not_nested_fixture_code(project):
    before = current_subject(project)
    (project / '.project/cache').mkdir()
    (project / '.project/cache/result.txt').write_text('new cache')
    assert current_subject(project) == before
    nested = project / 'tests/fixtures/.project'
    nested.mkdir(parents=True)
    (nested / 'project.yaml').write_text('source fixture')
    assert current_subject(project) != before


def test_git_subject_covers_staged_unstaged_untracked_deleted_and_executable(project):
    def git(*args):
        return subprocess.run(['git','-C',str(project),*args],check=True,capture_output=True).stdout
    git('init')
    git('add','.')
    git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','fixture')
    subject = current_subject(project)
    assert subject == {'kind':'commit','value':git('rev-parse','HEAD').decode().strip()}
    (project / '.project/cache').mkdir()
    (project / '.project/cache/local.txt').write_text('metadata')
    assert current_subject(project) == subject
    code = project / 'src/code.py'
    code.write_text('value=2\n')
    changed = current_subject(project)
    assert changed['kind'] == 'working_tree'
    git('add','src/code.py')
    assert current_subject(project) == changed
    code.chmod(0o755)
    assert current_subject(project) != changed
    code.unlink()
    deleted = current_subject(project)
    assert deleted != changed
    (project / 'new.py').write_text('new code')
    assert current_subject(project) != deleted
