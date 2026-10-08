from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from apm.facts import dump_yaml, read_yaml, validate_project
from apm.operations import OperationError, start_run
from apm.state import check_digest, current_subject
from apm.storage import PendingTransaction, pending_transactions, recover
from apm.verification import assessment, execute_checks, import_evidence, junit_result
from .test_cli import cli
from .test_operations import snapshot


PASS = '<testsuite tests="1"><testcase classname="suite" name="test"/></testsuite>'
FAILED = '<testsuite tests="1"><testcase classname="suite" name="test"><failure message="fixture"/></testcase></testsuite>'
SKIPPED = '<testsuite tests="1"><testcase classname="suite" name="test"><skipped/></testcase></testsuite>'


def configured(root, xml=PASS, *, tail='', timeout=5, parser=True, testcase_refs=True, write_report=True):
    f = validate_project(root)
    feature = deepcopy(next(iter(f.features.values())))
    script = "from pathlib import Path\nPath('.project/artifacts').mkdir(exist_ok=True)\n"
    script += "p=Path('.project/artifacts/count.txt');p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n"
    if write_report:
        script += "Path('.project/artifacts/result.xml').write_text(" + repr(xml) + ")\n"
    script += tail
    project = deepcopy(f.project)
    project['commands']['verify'] = {'argv': [sys.executable, '-c', script], 'cwd': '.', 'timeout_seconds': timeout}
    if parser:
        project['commands']['verify']['result'] = {'kind': 'junit', 'path': '.project/artifacts/result.xml'}
    (root / '.project/project.yaml').write_text(dump_yaml(project))
    check = feature['verification']['checks'][0]
    check['command_ref'] = 'verify'
    if testcase_refs:
        check['testcase_refs'] = ['suite.test']
    feature['implementation'].update(state='complete', subject=current_subject(root), remaining=[])
    (root / f.files[feature['id']]).write_text(dump_yaml(feature))
    run = start_run(root, feature['id'], 'test', 'worker', 'path:.')['run']
    return feature, run


def recorded(root, feature, run, *, type='test', result='passed'):
    f = validate_project(root)
    path = root / '.project/artifacts/input.xml'
    path.parent.mkdir(exist_ok=True)
    path.write_text(PASS)
    check = feature['verification']['checks'][0]
    command = f.project['commands'][check['command_ref']]
    ev = {'version': 1, 'id': 'EVD-' + str(uuid4()), 'feature_ref': feature['id'], 'check_ref': check['id'],
          'type': type, 'produced_by': {'run_ref': run['id']}, 'result': result,
          'acceptance_revision': feature['acceptance_revision'],
          'requirement_revisions': {ref: f.requirements[ref]['revision'] for ref in feature['requirement_refs']},
          'subject': current_subject(root), 'check_digest': check_digest(check, f.project),
          'command': {'argv': command['argv'], 'cwd': command['cwd'], 'exit_code': 0},
          'artifacts': [{'path': '.project/artifacts/input.xml', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}],
          'note': 'Explicit synthetic fixture provenance', 'supersedes': [], 'created_at': '2026-10-08T00:00:00Z'}
    if type == 'manual_review':
        ev['produced_by']['reviewer'] = 'fixture-reviewer'
        ev['command'] = None
    return ev


def test_named_assertions_execute_and_persist_immutable_report(project):
    feature, run = configured(project)
    result = execute_checks(project, feature['id'], run['id'], 1)
    assert result['required_passed'] and result['executions'][0]['counts']['selected'] == 1
    ev = validate_project(project).evidence[result['new_evidence'][0]]
    assert ev['command']['exit_code'] == 0 and ev['result'] == 'passed'
    assert validate_project(project).features[feature['id']]['revision'] == 2
    (project / '.project/artifacts/result.xml').write_text('overwritten report')
    assert assessment(validate_project(project), feature['id'])['required_passed']
    assert all(hashlib.sha256((project / a['path']).read_bytes()).hexdigest() == a['sha256'] for a in ev['artifacts'])


def test_shared_command_executes_once_for_distinct_assertions(project):
    xml = '<testsuite tests="2"><testcase classname="suite" name="test"/><testcase classname="suite" name="other"/></testsuite>'
    feature, run = configured(project, xml)
    second = deepcopy(feature['verification']['checks'][0])
    second.update(id='CHECK-OTHER', testcase_refs=['suite.other'])
    feature['verification']['checks'].append(second)
    path = project / validate_project(project).files[feature['id']]
    path.write_text(dump_yaml(feature))
    result = execute_checks(project, feature['id'], run['id'], 1)
    assert result['required_passed'] and len(result['new_evidence']) == 2
    assert (project / '.project/artifacts/count.txt').read_text() == '1'


@pytest.mark.parametrize('xml,tail,result,reason', [
    ('<testsuite tests="0"/>', '', 'not_verified', 'zero_tests'),
    (SKIPPED, '', 'not_verified', 'named_assertion_skipped'),
    (FAILED, '', 'failed', 'named_assertion_failed'),
    (PASS, 'raise SystemExit(1)\n', 'failed', 'command_failed'),
    ('<testsuite><testcase classname="suite" name="other"/></testsuite>', '', 'not_verified', 'missing_or_ambiguous_testcases'),
    ('<testsuite><testcase classname="suite" name="test"/><testcase classname="suite" name="test"/></testsuite>', '', 'not_verified', 'missing_or_ambiguous_testcases'),
    ('invalid XML', '', 'not_verified', 'malformed_report'),
    ('<other/>', '', 'not_verified', 'unsupported_report'),
    ('<!DOCTYPE foo [<!ENTITY x "value">]><testsuite/>', '', 'not_verified', 'unsafe_or_oversized_report'),
    ('<testsuite><testcase classname="suite" name="test" status="notrun"/></testsuite>', '', 'not_verified', 'named_assertion_skipped'),
])
def test_nonpassing_runner_outcomes_are_distinct(project, xml, tail, result, reason):
    feature, run = configured(project, xml, tail=tail)
    outcome = execute_checks(project, feature['id'], run['id'], 1)
    assert not outcome['required_passed']
    assert outcome['executions'][0]['result'] == result
    assert outcome['executions'][0]['reason'] == reason
    assert validate_project(project).evidence[outcome['new_evidence'][0]]['result'] == result


@pytest.mark.parametrize('option', ['parser', 'testcase_refs', 'write_report'])
def test_unconfigured_or_missing_result_never_passes(project, option):
    feature, run = configured(project, **{option: False})
    assert not execute_checks(project, feature['id'], run['id'], 1)['required_passed']
    if option in {'parser', 'testcase_refs'}:
        assert not (project / '.project/artifacts/count.txt').exists()


def test_old_report_is_not_used(project):
    feature, run = configured(project, write_report=False)
    path = project / '.project/artifacts/result.xml'; path.parent.mkdir(); path.write_text(PASS)
    outcome = execute_checks(project, feature['id'], run['id'], 1)
    assert outcome['executions'][0]['reason'] == 'stale_report'


def test_timeout_kills_command_and_records_not_verified(project):
    feature, run = configured(project, tail='import time; time.sleep(2)\n', timeout=0.05)
    outcome = execute_checks(project, feature['id'], run['id'], 1)
    assert not outcome['required_passed'] and outcome['executions'][0]['reason'] == 'timeout'
    ev = validate_project(project).evidence[outcome['new_evidence'][0]]
    assert ev['result'] == 'not_verified' and ev['command']['exit_code'] is None


def test_timeout_also_kills_child_processes(project):
    child = 'import time; from pathlib import Path; time.sleep(0.6); Path(".project/artifacts/child-marker").write_text("leaked")'
    tail = 'import subprocess,time\nsubprocess.Popen([' + repr(sys.executable) + ',"-c",' + repr(child) + '])\ntime.sleep(2)\n'
    feature, run = configured(project, tail=tail, timeout=0.15)
    assert not execute_checks(project, feature['id'], run['id'], 1)['required_passed']
    time.sleep(0.65)
    assert not (project / '.project/artifacts/child-marker').exists()


def test_missing_executable_is_not_verified(project):
    feature, run = configured(project)
    path = project / '.project/project.yaml'; data = read_yaml(path)
    data['commands']['verify']['argv'] = ['/nonexistent/apm-fixture-command']
    path.write_text(dump_yaml(data))
    result = execute_checks(project, feature['id'], run['id'], 1)
    assert result['executions'][0]['reason'] == 'execution_environment_unavailable'
    assert not result['required_passed']


def test_selecting_one_check_does_not_claim_other_required_ac_passed(project):
    feature, run = configured(project)
    feature['acceptance'].append({'id': 'AC-OTHER', 'description': 'another AC', 'required': True})
    second = deepcopy(feature['verification']['checks'][0]); second.update(id='CHECK-OTHER', acceptance_ref='AC-OTHER')
    feature['verification']['checks'].append(second)
    (project / validate_project(project).files[feature['id']]).write_text(dump_yaml(feature))
    result = execute_checks(project, feature['id'], run['id'], 1, selected=['CHECK-001'])
    assert result['verification'] == 'partial' and not result['required_passed']
    assert len(result['new_evidence']) == 1


def test_logs_and_report_redact_secret_bindings(project, monkeypatch):
    secret = 'fixture-secret-never-log'
    monkeypatch.setenv('PACKAGE_TOKEN', secret)
    xml = PASS.replace('/></testsuite>', f'><system-out>{secret}</system-out></testcase></testsuite>')
    feature, run = configured(project, xml, tail='import os; print(os.environ["PACKAGE_TOKEN"])\n')
    outcome = execute_checks(project, feature['id'], run['id'], 1)
    assert outcome['required_passed']
    ev = validate_project(project).evidence[outcome['new_evidence'][0]]
    saved = b''.join((project / a['path']).read_bytes() for a in ev['artifacts'])
    assert secret.encode() not in saved and b'[REDACTED]' in saved


def test_code_change_during_execution_cannot_pass(project):
    feature, run = configured(project, tail='Path("src/code.py").write_text("changed code")\n')
    outcome = execute_checks(project, feature['id'], run['id'], 1)
    assert not outcome['required_passed'] and outcome['executions'][0]['reason'] == 'code_changed_during_execution'


def test_fact_change_during_execution_is_conflict_and_not_overwritten(project):
    tail='import json\np=Path(".project/project.yaml");d=json.loads(p.read_text());d["description"]="concurrent change";p.write_text(json.dumps(d))\n'
    feature, run = configured(project, tail=tail)
    with pytest.raises(OperationError) as exc:
        execute_checks(project, feature['id'], run['id'], 1)
    assert exc.value.code == 3
    assert validate_project(project).project['description'] == 'concurrent change'
    assert not validate_project(project).evidence


def test_dry_run_executes_and_writes_nothing(project):
    feature, run = configured(project)
    before = snapshot(project)
    result = execute_checks(project, feature['id'], run['id'], 1, dry_run=True)
    assert result['dry_run'] and result['would_execute'] == ['verify']
    assert snapshot(project) == before


def test_rerun_retires_old_pass_and_keeps_failure(project):
    feature, run = configured(project)
    first = execute_checks(project, feature['id'], run['id'], 1)
    f = validate_project(project)
    project_data = deepcopy(f.project)
    project_data['commands']['verify']['argv'][2] = project_data['commands']['verify']['argv'][2].replace(repr(PASS), repr(FAILED))
    (project / '.project/project.yaml').write_text(dump_yaml(project_data))
    result = execute_checks(project, feature['id'], run['id'], 2)
    assert not result['required_passed'] and result['verification'] == 'failed'
    new = validate_project(project).evidence[result['new_evidence'][0]]
    assert first['new_evidence'][0] in new['supersedes']


def test_import_preserves_provenance_and_copies_artifacts(project):
    feature, run = configured(project)
    ev = recorded(project, feature, run)
    result = import_evidence(project, feature['id'], run['id'], 1, ev)
    assert result['required_passed']
    stored = validate_project(project).evidence[ev['id']]
    assert stored['produced_by'] == ev['produced_by'] and stored['subject'] == ev['subject']
    assert stored['artifacts'][0]['path'] != ev['artifacts'][0]['path']
    (project / ev['artifacts'][0]['path']).write_text('changed original')
    assert assessment(validate_project(project), feature['id'])['required_passed']


def test_import_dry_run_preserves_current_state_and_files(project):
    feature, run = configured(project)
    ev = recorded(project, feature, run); before = snapshot(project)
    result = import_evidence(project, feature['id'], run['id'], 1, ev, dry_run=True)
    assert result['dry_run'] and not result['required_passed'] and not result['new_evidence']
    assert result['would_record'] == [ev['id']] and snapshot(project) == before


@pytest.mark.parametrize('kind', ['screenshot', 'api_response', 'code_reference'])
def test_observation_cannot_bypass_manual_review_policy(project, kind):
    feature, run = configured(project)
    ev = recorded(project, feature, run, type=kind)
    with pytest.raises(OperationError) as exc:
        import_evidence(project, feature['id'], run['id'], 1, ev)
    assert exc.value.code == 5 and not validate_project(project).evidence


def test_import_conflict_requires_explicit_supersedes(project):
    feature, run = configured(project)
    first = recorded(project, feature, run)
    assert import_evidence(project, feature['id'], run['id'], 1, first)['required_passed']
    failed = recorded(project, feature, run, result='failed'); failed['command']['exit_code'] = 1
    result = import_evidence(project, feature['id'], run['id'], 2, failed)
    assert result['verification'] == 'blocked' and not result['required_passed']
    replacement = recorded(project, feature, run); replacement['supersedes'] = [first['id'], failed['id']]
    assert import_evidence(project, feature['id'], run['id'], 3, replacement)['required_passed']


@pytest.mark.parametrize('mutation,code', [
    (lambda e: e.update(produced_by=None), 2),
    (lambda e: e.update(feature_ref='FEAT-other'), 2),
    (lambda e: e.update(check_ref='CHECK-other'), 2),
    (lambda e: e['produced_by'].update(run_ref='RUN-other'), 2),
    (lambda e: e['artifacts'][0].update(sha256='0' * 64), 5),
])
def test_import_rejects_wrong_binding_and_checksum(project, mutation, code):
    feature, run = configured(project)
    ev = recorded(project, feature, run); mutation(ev)
    before = snapshot(project)
    with pytest.raises(OperationError) as exc:
        import_evidence(project, feature['id'], run['id'], 1, ev)
    assert exc.value.code == code and snapshot(project) == before


def test_import_checks_named_assertions_and_never_overwrites_id(project):
    feature, run = configured(project)
    ev = recorded(project, feature, run)
    import_evidence(project, feature['id'], run['id'], 1, ev)
    with pytest.raises(OperationError) as exc:
        import_evidence(project, feature['id'], run['id'], 2, ev)
    assert exc.value.code == 3
    ev = recorded(project, feature, run)
    path = project / ev['artifacts'][0]['path']; path.write_text(SKIPPED)
    ev['artifacts'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(OperationError) as exc:
        import_evidence(project, feature['id'], run['id'], 2, ev)
    assert exc.value.code == 5


@pytest.mark.parametrize('change', [
    lambda e: e.update(acceptance_revision=99),
    lambda e: e.update(requirement_revisions={}),
    lambda e: e.update(subject={'kind': 'commit', 'value': 'a' * 40}),
    lambda e: e['artifacts'][0].update(expires_at='2020-01-01T00:00:00Z'),
])
def test_import_stale_evidence_is_retained_but_not_passed(project, change):
    feature, run = configured(project)
    ev = recorded(project, feature, run); change(ev)
    result = import_evidence(project, feature['id'], run['id'], 1, ev)
    assert not result['required_passed'] and ev['id'] in validate_project(project).evidence


def test_manual_import_policy_and_reviewer(project):
    feature, run = configured(project)
    ev = recorded(project, feature, run, type='manual_review')
    p = project / '.project/project.yaml'; data = read_yaml(p)
    data['policies']['allow_manual_evidence'] = False; p.write_text(dump_yaml(data))
    # Rebind only the method metadata to the newly configured policy context.
    assert not import_evidence(project, feature['id'], run['id'], 1, ev)['required_passed']
    ev = recorded(project, feature, run, type='manual_review'); ev['produced_by'].pop('reviewer')
    with pytest.raises(OperationError) as exc:
        import_evidence(project, feature['id'], run['id'], 2, ev)
    assert exc.value.code == 2


def test_evidence_transaction_recovers_artifacts_and_feature_reference(project, monkeypatch):
    import apm.storage as storage
    feature, run = configured(project)
    original = storage._replace
    def crash(path, text):
        if path.parent.name == 'core':
            raise OSError('simulated crash before Feature reference')
        original(path, text)
    with monkeypatch.context() as patch:
        patch.setattr(storage, '_replace', crash)
        with pytest.raises(OSError):
            execute_checks(project, feature['id'], run['id'], 1)
    assert pending_transactions(project)
    assert recover(project)
    assert not pending_transactions(project)
    assert assessment(validate_project(project), feature['id'])['required_passed']


def test_readonly_verify_and_cli_write_exit_status(project):
    feature, run = configured(project)
    before = snapshot(project)
    code, result = cli(project, 'verify', feature['id'])
    assert code == 5 and not result['data']['required_passed'] and snapshot(project) == before
    assert cli(project, 'verify', feature['id'], '--run')[0] == 2
    code, result = cli(project, 'verify', feature['id'], '--run', '--run-id', run['id'], '--expected-revision', '1')
    assert code == 0 and result['data']['required_passed']
    assert cli(project, 'verify', feature['id'])[0] == 0
    assert cli(project, 'verify', feature['id'], '--run', '--run-id', run['id'], '--expected-revision', '1')[0] == 3


def test_cli_failed_and_timeout_verification_exit_five(project):
    feature, run = configured(project, FAILED)
    code, result = cli(project, 'verify', feature['id'], '--run', '--run-id', run['id'], '--expected-revision', '1')
    assert code == 5 and result['data']['verification'] == 'failed'
