from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from ruamel.yaml.error import YAMLError

from apm.facts import dump_yaml, read_yaml, validate_project
from apm.operations import OperationError
from apm.sources import add_source, apply_proposal, parse_markdown, propose_source, registry_view
from apm.state import canonical_digest, derive, utc_now
from apm.storage import pending_transactions, recover
from .test_cli import cli
from .test_operations import snapshot, started


RECORD = {'key': 'login', 'title': '用户登录', 'description': '验证用户凭据', 'acceptance': ['有效凭据可以登录']}


def document(record=RECORD):
    return '# Requirements\n\n```apm-requirement\n' + dump_yaml(record) + '```\n'


def source_setup(root, adapter='markdown'):
    path = root / 'docs/requirements.md'
    path.parent.mkdir(exist_ok=True)
    path.write_text(document(), encoding='utf-8')
    source = {'version': 1, 'id': 'SRC-' + str(uuid4()), 'type': 'markdown', 'name': 'Fixture input',
              'location': {'path': 'docs/requirements.md'}, 'authority': 'primary', 'adapter': {'name': adapter},
              'revision': 'initial', 'captured_at': utc_now()}
    run = started(root, 'path:.')
    add_source(root, source, registry_view(root)['digest'], run['id'])
    return source, run


def apply(root, proposal, run, dry_run=False):
    return apply_proposal(root, proposal, run['id'], 'fixture-reviewer', 'Reviewed fixture diff',
                          kind='source_sync', target=proposal['target'], dry_run=dry_run)


def imported(root):
    source, run = source_setup(root)
    proposal = propose_source(root, source['id'])
    apply(root, proposal, run)
    identity = proposal['payload']['allocated']['login']
    return source, run, identity


def confirm(root, identity):
    f = validate_project(root)
    req = deepcopy(f.requirements[identity])
    req['status'] = 'confirmed'
    req['confirmation'] = {'reviewer': 'fixture', 'note': 'Fixture confirmation', 'confirmed_at': utc_now()}
    (root / f.files[identity]).write_text(dump_yaml(req))
    return req


def test_registry_digest_add_and_extensions_preserved(project):
    path = project / '.project/sources/registry.yaml'
    registry = read_yaml(path); registry['extensions'] = {'retained': True}; path.write_text(dump_yaml(registry))
    source, run = source_setup(project)
    view = registry_view(project, source['id'])
    assert view['digest'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert view['sources'] == [source] and read_yaml(path)['extensions'] == {'retained': True}
    with pytest.raises(OperationError) as exc:
        add_source(project, source, view['digest'], run['id'])
    assert exc.value.code == 3


@pytest.mark.parametrize('change,code', [
    (lambda s: s['location'].update(path='../outside.md'), 2),
    (lambda s: s.update(id='SRC-invalid'), 2),
    (lambda s: s.update(extra='unknown'), 2),
])
def test_source_add_invalid_candidate_is_atomic(project, change, code):
    source, run = source_setup(project); source['id'] = 'SRC-' + str(uuid4()); change(source)
    before = snapshot(project)
    with pytest.raises(OperationError) as exc:
        add_source(project, source, registry_view(project)['digest'], run['id'])
    assert exc.value.code == code and snapshot(project) == before


def test_registry_stale_digest_and_terminal_run_rejected(project):
    source, run = source_setup(project); source['id'] = 'SRC-' + str(uuid4())
    with pytest.raises(OperationError) as exc:
        add_source(project, source, '0' * 64, run['id'])
    assert exc.value.code == 3
    path = project / '.project/runs' / (run['id'] + '.yaml'); data = read_yaml(path)
    data.update(status='completed', ended_at=utc_now()); path.write_text(dump_yaml(data))
    with pytest.raises(OperationError) as exc:
        add_source(project, source, registry_view(project)['digest'], run['id'])
    assert exc.value.code == 5


def test_add_and_sync_dry_run_write_nothing(project):
    source, run = source_setup(project); source['id'] = 'SRC-' + str(uuid4())
    before = snapshot(project)
    assert add_source(project, source, registry_view(project)['digest'], run['id'], dry_run=True)['dry_run']
    assert source['id'] not in validate_project(project).sources and snapshot(project) == before
    source_id = next(s['id'] for s in registry_view(project)['sources'] if s['adapter']['name'] == 'markdown')
    proposal = propose_source(project, source_id)
    assert snapshot(project) == before
    assert apply(project, proposal, run, True)['review_artifact'] is None and snapshot(project) == before


def test_markdown_ignores_prose_links_and_nested_fences():
    ordinary = '```python\n```apm-requirement\nmalformed\n```\n'
    raw = ('[external](https://example.invalid/requirements)\n' + ordinary + document()).encode()
    assert parse_markdown(raw) == [RECORD]
    assert parse_markdown(document().replace('```', '~~~~').encode()) == [RECORD]


@pytest.mark.parametrize('text', [
    '```apm-requirement\nkey: login\n',
    '```apm-requirement extra\n{}\n```',
    document() + document(),
    document({**RECORD, 'key': '../login'}),
    document({**RECORD, 'status': 'confirmed'}),
    document({**RECORD, 'acceptance': []}),
    '```apm-requirement\nkey: login\nkey: duplicate\n```',
    '```apm-requirement\n!!python/object/apply:os.system ["bad"]\n```',
])
def test_invalid_markdown_does_not_silently_extract(text):
    with pytest.raises((OperationError, YAMLError, ValueError)):
        parse_markdown(text.encode())


@pytest.mark.parametrize('change,code', [
    (lambda s: s['location'].clear() or s['location'].update(url='https://example.invalid/input'), 2),
    (lambda s: s['adapter'].update(name='axure'), 2),
    (lambda s: s['location'].update(path='docs/missing.md'), 4),
])
def test_unavailable_or_unsupported_sources_are_explicit(project, change, code):
    source, _ = source_setup(project)
    path = project / '.project/sources/registry.yaml'; data = read_yaml(path); change(data['sources'][-1]); path.write_text(dump_yaml(data))
    with pytest.raises(OperationError) as exc:
        propose_source(project, source['id'])
    assert exc.value.code == code


def test_escaping_symlink_and_oversized_source_rejected(project, tmp_path):
    source, _ = source_setup(project)
    path = project / 'docs/requirements.md'; path.unlink()
    outside = tmp_path / 'outside.md'; outside.write_text(document()); path.symlink_to(outside)
    assert cli(project, 'source', 'sync', source['id'])[0] == 2
    path.unlink(); path.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
    assert cli(project, 'source', 'sync', source['id'])[0] == 2


def test_zero_requirements_cannot_initialize(project):
    source, _ = source_setup(project); (project / 'docs/requirements.md').write_text('# prose only\n')
    before = snapshot(project)
    with pytest.raises(OperationError) as exc:
        propose_source(project, source['id'])
    assert exc.value.code == 5 and snapshot(project) == before


def test_apply_creates_draft_with_snapshot_and_review_provenance(project):
    source, run = source_setup(project); before = snapshot(project)
    proposal = propose_source(project, source['id'])
    assert snapshot(project) == before
    result = apply(project, proposal, run)
    req = validate_project(project).requirements[proposal['payload']['allocated']['login']]
    assert req['status'] == 'draft' and req['revision'] == 1
    assert req['sources'][0]['locator'] == 'block:login'
    assert req['sources'][0]['source_revision'] == 'sha256:' + hashlib.sha256((project / 'docs/requirements.md').read_bytes()).hexdigest()
    review = read_yaml(project / result['review_artifact'])
    assert review['proposal'] == proposal and review['applied_by']['run_ref'] == run['id']
    with pytest.raises(OperationError) as exc:
        apply(project, proposal, run)
    assert exc.value.code == 3


def test_same_source_key_updates_existing_confirmed_requirement(project):
    source, run, identity = imported(project); original = confirm(project, identity)
    changed = {**RECORD, 'description': '新增二次验证'}
    (project / 'docs/requirements.md').write_text(document(changed))
    proposal = propose_source(project, source['id'])
    assert proposal['payload']['allocated'] == {} and validate_project(project).requirements[identity] == original
    apply(project, proposal, run)
    req = validate_project(project).requirements[identity]
    assert req['description'] == changed['description'] and req['status'] == 'changed'
    assert req['revision'] == 2 and 'confirmation' not in req


def test_source_deletion_keeps_requirement_and_feature_refs(project):
    source, run, identity = imported(project); confirm(project, identity)
    f = validate_project(project); feature = deepcopy(next(iter(f.features.values())))
    feature['requirement_refs'] = [identity]; (project / f.files[feature['id']]).write_text(dump_yaml(feature))
    (project / 'docs/requirements.md').write_text('# all blocks removed\n')
    apply(project, propose_source(project, source['id']), run)
    f = validate_project(project); req = f.requirements[identity]
    assert req['status'] == 'changed' and req['title'] == RECORD['title']
    assert req['blockers'][0].startswith('source_missing:') and f.features[feature['id']]['requirement_refs'] == [identity]
    (project / 'docs/requirements.md').write_text(document())
    apply(project, propose_source(project, source['id']), run)
    assert validate_project(project).requirements[identity]['blockers'] == []


@pytest.mark.parametrize('mutation', ['input', 'deleted_input', 'registry', 'requirement', 'feature', 'project'])
def test_stale_proposals_reject_changed_inputs_and_facts(project, mutation):
    source, run = source_setup(project); proposal = propose_source(project, source['id'])
    if mutation == 'input':
        (project / 'docs/requirements.md').write_text(document({**RECORD, 'title': 'changed'}))
    elif mutation == 'deleted_input':
        (project / 'docs/requirements.md').unlink()
    else:
        f = validate_project(project)
        name = {'registry': '.project/sources/registry.yaml', 'project': '.project/project.yaml',
                'requirement': f.files[next(iter(f.requirements))], 'feature': f.files[next(iter(f.features))]}[mutation]
        path = project / name; value = read_yaml(path); value['extensions'] = {'changed': True}; path.write_text(dump_yaml(value))
    before = snapshot(project)
    with pytest.raises(OperationError) as exc:
        apply(project, proposal, run)
    assert exc.value.code == 3 and snapshot(project) == before


@pytest.mark.parametrize('reseal', [False, True])
def test_tampered_proposal_cannot_bypass_confirmed_protection(project, reseal):
    source, run = source_setup(project); proposal = propose_source(project, source['id'])
    proposal['changes'][-1]['after']['status'] = 'confirmed'
    if reseal:
        proposal['digest'] = canonical_digest({k: v for k, v in proposal.items() if k != 'digest'})
    before = snapshot(project)
    with pytest.raises(OperationError) as exc:
        apply(project, proposal, run)
    assert exc.value.code == 3 and snapshot(project) == before


def competing_source(root, identity):
    f = validate_project(root); reg = read_yaml(root / '.project/sources/registry.yaml')
    source = deepcopy(reg['sources'][-1]); source.update(id='SRC-' + str(uuid4()), name='Other primary')
    source['location'] = {'path': 'docs/other.md'}; reg['sources'].append(source)
    (root / 'docs/other.md').write_text(document())
    (root / '.project/sources/registry.yaml').write_text(dump_yaml(reg))
    req = deepcopy(f.requirements[identity]); req['sources'].append({'source_ref': source['id'], 'source_revision': 'initial', 'locator': 'block:login'})
    (root / f.files[identity]).write_text(dump_yaml(req))
    return source


def test_primary_source_conflict_retains_content_and_blocks_confirmation(project):
    source, run, identity = imported(project); confirm(project, identity); competing_source(project, identity)
    changed = {**RECORD, 'title': '另一种登录规则'}
    (project / 'docs/requirements.md').write_text(document(changed))
    proposal = propose_source(project, source['id']); assert proposal['conflicts']
    assert proposal['payload']['records'] == [changed]
    apply(project, proposal, run)
    req = validate_project(project).requirements[identity]
    assert req['status'] == 'blocked' and req['title'] == RECORD['title'] and req['blockers'][0].startswith('source_conflict:')
    (project / 'docs/other.md').write_text(document(changed))
    apply(project, propose_source(project, source['id']), run)
    req = validate_project(project).requirements[identity]
    assert req['status'] == 'changed' and req['title'] == changed['title'] and req['blockers'] == []


def test_unreadable_primary_is_blocked_and_snapshot_is_bound(project):
    source, run, identity = imported(project); other = competing_source(project, identity)
    (project / 'docs/other.md').write_text('```apm-requirement\ninvalid\n')
    proposal = propose_source(project, source['id']); assert proposal['conflicts']
    (project / 'docs/other.md').write_text('```apm-requirement\nstill invalid\n')
    with pytest.raises(OperationError) as exc:
        apply(project, proposal, run)
    assert exc.value.code == 3
    apply(project, propose_source(project, source['id']), run)
    assert validate_project(project).requirements[identity]['status'] == 'blocked'


def test_sync_preserves_unrelated_source_and_manual_blockers(project):
    source, run, identity = imported(project)
    f = validate_project(project); req = deepcopy(f.requirements[identity])
    req['blockers'] = ['source_missing:SRC-other:key', 'Needs external review']
    (project / f.files[identity]).write_text(dump_yaml(req))
    (project / 'docs/requirements.md').write_text(document() + 'updated prose\n')
    apply(project, propose_source(project, source['id']), run)
    assert validate_project(project).requirements[identity]['blockers'] == req['blockers']


def test_secondary_source_cannot_override_other_primary(project):
    source, run, identity = imported(project); confirm(project, identity)
    competing_source(project, identity)
    path = project / '.project/sources/registry.yaml'; registry = read_yaml(path)
    next(s for s in registry['sources'] if s['id'] == source['id'])['authority'] = 'secondary'
    path.write_text(dump_yaml(registry))
    (project / 'docs/requirements.md').write_text(document({**RECORD, 'title': 'unreviewed override'}))
    proposal = propose_source(project, source['id']); assert proposal['conflicts']
    apply(project, proposal, run)
    req = validate_project(project).requirements[identity]
    assert req['status'] == 'blocked' and req['title'] == RECORD['title']


def test_ambiguous_locator_and_no_change_are_explicit(project):
    source, run, identity = imported(project)
    with pytest.raises(OperationError) as exc:
        apply(project, propose_source(project, source['id']), run)
    assert exc.value.code == 5
    f = validate_project(project); req = deepcopy(f.requirements[identity]); req['id'] = 'REQ-' + str(uuid4())
    (project / '.project/requirements' / (req['id'] + '.yaml')).write_text(dump_yaml(req))
    with pytest.raises(OperationError) as exc:
        propose_source(project, source['id'])
    assert exc.value.code == 3


def test_import_agent_requirements_never_confirms_inferred_source(project):
    source, run = source_setup(project, 'manual')
    path = project / '.project/sources/registry.yaml'; reg = read_yaml(path); reg['sources'][-1]['authority'] = 'inferred'; path.write_text(dump_yaml(reg))
    (project / 'agent.json').write_text(dump_yaml({'requirements': [RECORD]}))
    proposal = propose_source(project, source['id'], 'agent.json')
    apply(project, proposal, run)
    req = validate_project(project).requirements[proposal['payload']['allocated']['login']]
    assert req['status'] == 'draft' and req['sources'][0]['source_ref'] == source['id']
    (project / 'agent.json').write_text(dump_yaml({'requirements': [{**RECORD, 'status': 'confirmed'}]}))
    assert cli(project, 'source', 'sync', source['id'], '--file', 'agent.json')[0] == 2


def test_requirement_change_invalidates_old_evidence(project):
    from .test_verification import configured
    from apm.verification import execute_checks
    source, run, identity = imported(project); confirm(project, identity)
    f = validate_project(project); feature = deepcopy(next(iter(f.features.values())))
    feature['requirement_refs'] = [identity]; (project / f.files[feature['id']]).write_text(dump_yaml(feature))
    # Retire setup Run so fixture verification can claim the same scope.
    path = project / f.files[run['id']]; data = read_yaml(path); data.update(status='completed', ended_at=utc_now()); path.write_text(dump_yaml(data))
    feature, verifying = configured(project)
    assert execute_checks(project, feature['id'], verifying['id'], 1)['required_passed']
    # Root .project input is metadata; this changes Requirement revision without changing code.
    source_manual = deepcopy(source); source_manual['adapter']['name'] = 'manual'
    path = project / '.project/sources/registry.yaml'; reg = read_yaml(path); reg['sources'][-1] = source_manual; path.write_text(dump_yaml(reg))
    (project / '.project/artifacts/agent.json').write_text(dump_yaml({'requirements': [{**RECORD, 'description': 'new rule'}]}))
    proposal = propose_source(project, source['id'], '.project/artifacts/agent.json')
    apply(project, proposal, verifying)
    state = derive(validate_project(project), utc_now())['features'][0]
    assert state['verification'] != 'passed'
    assert 'stale_requirements' in json.dumps(state['checks'])


def test_apply_transaction_recovers_registry_requirement_and_review(project, monkeypatch):
    import apm.storage as storage
    source, run = source_setup(project); proposal = propose_source(project, source['id'])
    original = storage._replace
    def crash(path, content):
        if path.parent.name == 'requirements':
            raise OSError('simulated apply interruption')
        original(path, content)
    with monkeypatch.context() as patch:
        patch.setattr(storage, '_replace', crash)
        with pytest.raises(OSError):
            apply(project, proposal, run)
    assert pending_transactions(project) and cli(project, 'source', 'list')[0] == 5
    assert recover(project) and not pending_transactions(project)
    f = validate_project(project); assert not f.errors
    assert f.requirements[proposal['payload']['allocated']['login']]['status'] == 'draft'
    assert (project / '.project/artifacts' / proposal['id'] / 'review.json').is_file()


def test_cli_proposals_and_complete_response_application(project):
    source, run = source_setup(project); before = snapshot(project)
    assert cli(project, 'source', 'list')[0] == 0
    assert cli(project, 'source', 'show', source['id'])[0] == 0
    assert cli(project, 'requirement', 'list')[0] == 0
    code, response = cli(project, 'source', 'sync', source['id'], '--dry-run')
    assert code == 0 and snapshot(project) == before
    proposal_file = project / '.project/artifacts/proposal.json'; proposal_file.parent.mkdir(exist_ok=True)
    proposal_file.write_text(dump_yaml(response))
    args = ('source', 'sync', source['id'], '--apply', str(proposal_file))
    assert cli(project, *args)[0] == 2
    assert cli(project, *args, '--run-id', run['id'], '--reviewer', 'fixture', '--note', 'reviewed')[0] == 0
    identity = response['data']['proposal']['payload']['allocated']['login']
    assert cli(project, 'requirement', 'show', identity)[1]['data']['facts']['status'] == 'draft'
