from copy import deepcopy

import pytest

from apm.facts import dump_yaml, read_yaml, validate_project
from apm.operations import OperationError
from apm.sources import apply_proposal, propose_decomposition
from apm.state import utc_now
from apm.storage import pending_transactions, recover
from .test_cli import cli
from .test_operations import snapshot, started
from .test_sources import imported, confirm, document
from uuid import uuid4


def plan_setup(root):
    f = validate_project(root)
    identity = next(iter(f.requirements))
    feature = deepcopy(next(iter(f.features.values())))
    feature['id'] = 'FEAT-' + str(uuid4())
    (root / '.project/artifacts').mkdir(exist_ok=True)
    name = '.project/artifacts/plan.json'
    (root / name).write_text(dump_yaml({'features': [feature]}))
    run = started(root, 'path:.')
    return identity, feature, run, name


def apply(root, proposal, run, dry_run=False):
    return apply_proposal(root, proposal, run['id'], 'fixture', 'Reviewed decomposition',
                          kind='decompose', target=proposal['target'], dry_run=dry_run)


def test_decompose_explicitly_creates_only_initial_feature(project):
    identity, feature, run, name = plan_setup(project)
    before = snapshot(project)
    proposal = propose_decomposition(project, identity, name)
    assert snapshot(project) == before
    assert apply(project, proposal, run, True)['review_artifact'] is None and snapshot(project) == before
    result = apply(project, proposal, run)
    f = validate_project(project)
    assert f.features[feature['id']] == feature and not f.errors
    assert f.requirements[identity]['status'] == 'confirmed'
    assert not f.evidence and read_yaml(project / result['review_artifact'])['applied_by']['run_ref'] == run['id']


@pytest.mark.parametrize('mutation', [
    lambda f: f.update(requirement_refs=['REQ-missing']),
    lambda f: f.update(revision=2),
    lambda f: f.update(acceptance_revision=2),
    lambda f: f['implementation'].update(state='complete'),
    lambda f: f['implementation'].update(evidence_level='verified'),
    lambda f: f['implementation'].update(subject={'kind':'commit','value':'a'*40}),
    lambda f: f['implementation'].update(completed=['claimed done']),
    lambda f: f['verification']['checks'][0].update(evidence_refs=['EVD-missing']),
    lambda f: f['verification']['checks'][0].update(activity='running'),
    lambda f: f.update(acceptance=[]),
    lambda f: f.update(depends_on=['FEAT-missing']),
    lambda f: f.update(domain='../escape'),
])
def test_agent_plan_cannot_inject_completion_or_invalid_references(project, mutation):
    identity, feature, run, name = plan_setup(project); mutation(feature)
    (project / name).write_text(dump_yaml({'features':[feature]}))
    before = snapshot(project)
    with pytest.raises(OperationError) as exc:
        propose_decomposition(project, identity, name)
    assert exc.value.code == 2 and snapshot(project) == before


def test_decomposition_rejects_existing_and_duplicate_ids(project):
    identity, feature, _, name = plan_setup(project)
    feature['id'] = next(iter(validate_project(project).features))
    (project / name).write_text(dump_yaml({'features':[feature]}))
    with pytest.raises(OperationError) as exc:
        propose_decomposition(project, identity, name)
    assert exc.value.code == 3
    feature['id'] = 'FEAT-' + str(uuid4())
    (project / name).write_text(dump_yaml({'features':[feature, feature]}))
    with pytest.raises(OperationError) as exc:
        propose_decomposition(project, identity, name)
    assert exc.value.code == 3


@pytest.mark.parametrize('status', ['draft','changed','blocked'])
def test_decomposition_requires_confirmed_requirement(project, status):
    identity, _, _, name = plan_setup(project); f = validate_project(project)
    path = project / f.files[identity]; req = read_yaml(path); req['status'] = status; path.write_text(dump_yaml(req))
    with pytest.raises(OperationError) as exc:
        propose_decomposition(project, identity, name)
    assert exc.value.code == 5


def test_plan_or_requirement_changes_reject_old_proposal(project):
    identity, feature, run, name = plan_setup(project)
    proposal = propose_decomposition(project, identity, name)
    feature['title'] = 'new plan'; (project / name).write_text(dump_yaml({'features':[feature]}))
    before = snapshot(project)
    with pytest.raises(OperationError) as exc:
        apply(project, proposal, run)
    assert exc.value.code == 3 and snapshot(project) == before
    proposal = propose_decomposition(project, identity, name); f = validate_project(project)
    path = project / f.files[identity]; req = read_yaml(path); req['description'] = 'new requirement'; path.write_text(dump_yaml(req))
    with pytest.raises(OperationError) as exc:
        apply(project, proposal, run)
    assert exc.value.code == 3


def test_changed_manual_primary_revision_blocks_decomposition(project):
    identity, _, _, name = plan_setup(project)
    path = project / '.project/sources/registry.yaml'; registry = read_yaml(path)
    registry['sources'][0]['revision'] = 'new unreviewed snapshot'; path.write_text(dump_yaml(registry))
    with pytest.raises(OperationError) as exc:
        propose_decomposition(project, identity, name)
    assert exc.value.code == 3


def test_confirmed_content_must_match_primary_markdown_block(project):
    source, run, identity = imported(project); req = confirm(project, identity)
    feature = deepcopy(next(iter(validate_project(project).features.values())))
    feature['id'] = 'FEAT-' + str(uuid4()); feature['requirement_refs'] = [identity]
    name = '.project/artifacts/plan.json'; (project / name).write_text(dump_yaml({'features': [feature]}))
    req['description'] = 'Disagrees with actual primary block'
    (project / validate_project(project).files[identity]).write_text(dump_yaml(req))
    with pytest.raises(OperationError) as exc:
        propose_decomposition(project, identity, name)
    assert exc.value.code == 3 and exc.value.issues[0].code == 'source_conflict'


def test_changed_primary_markdown_requires_sync_before_decomposition(project):
    source, run, identity = imported(project); confirm(project, identity)
    feature = deepcopy(next(iter(validate_project(project).features.values()))); feature['id'] = 'FEAT-' + str(uuid4()); feature['requirement_refs'] = [identity]
    name = '.project/artifacts/plan.json'; (project / name).write_text(dump_yaml({'features':[feature]}))
    proposal = propose_decomposition(project, identity, name)
    (project / 'docs/requirements.md').write_text(document()+'new prose\n')
    with pytest.raises(OperationError) as exc:
        apply(project, proposal, run)
    assert exc.value.code == 3
    with pytest.raises(OperationError) as exc:
        propose_decomposition(project, identity, name)
    assert exc.value.code == 3


def test_decomposition_batch_validates_dependencies_and_recovers(project, monkeypatch):
    import apm.storage as storage
    identity, feature, run, name = plan_setup(project)
    second = deepcopy(feature); second['id'] = 'FEAT-' + str(uuid4()); second['depends_on'] = [feature['id']]
    (project / name).write_text(dump_yaml({'features':[feature,second]}))
    proposal = propose_decomposition(project, identity, name); original = storage._replace
    def crash(path, content):
        if path.stem == second['id']:
            raise OSError('simulated decomposition interruption')
        original(path, content)
    with monkeypatch.context() as patch:
        patch.setattr(storage,'_replace',crash)
        with pytest.raises(OSError):
            apply(project, proposal, run)
    assert pending_transactions(project)
    assert recover(project) and not validate_project(project).errors
    assert {feature['id'],second['id']}.issubset(validate_project(project).features)


def test_cli_decomposition_response_roundtrip(project):
    identity, feature, run, name = plan_setup(project)
    code, response = cli(project,'requirement','decompose',identity,'--file',name)
    assert code == 0
    output = project / '.project/artifacts/decompose.json'; output.write_text(dump_yaml(response))
    assert cli(project,'requirement','decompose',identity,'--apply',str(output),'--run-id',run['id'],'--reviewer','fixture','--note','reviewed')[0] == 0
    assert cli(project,'requirement','show',identity)[1]['data']['feature_refs'] == sorted(validate_project(project).features)
