from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from apm.facts import dump_yaml, find_project, read_yaml, safe_path, schema_resources, validate_project
from .conftest import REPO


def codes(project):
    return {issue.code for issue in validate_project(project).errors}


def test_valid_managed_project_and_example(project):
    assert not validate_project(project).errors
    assert not validate_project(REPO / 'examples/design').errors
    assert not validate_project(REPO).errors


def test_core_and_proposal_schemas_are_valid():
    schemas, _ = schema_resources()
    assert set(schemas) == {'protocol', 'project', 'registry', 'requirement', 'feature', 'run', 'evidence', 'handoff', 'proposal'}
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize('replacement', [
    'version: 1\nversion: 1\n',
    '!!python/object/apply:os.system ["touch /tmp/apm-forbidden"]\n',
    '---\nversion: 1\n---\nversion: 1\n',
])
def test_unsafe_yaml_is_rejected(project, replacement):
    (project / '.project/project.yaml').write_text(replacement)
    assert 'input_error' in codes(project)
    assert not Path('/tmp/apm-forbidden').exists()


@pytest.mark.parametrize('kind,key,value', [
    ('project', 'version', 2), ('project', 'revision', True),
    ('project', 'unexpected', 'bad'), ('feature', 'lifecycle', 'done'),
    ('feature', 'revision', 0), ('feature', 'priority', 'P9'),
    ('feature', 'id', 'FEAT-invalid'),
])
def test_invalid_structure_or_identity(project, mutate, kind, key, value):
    mutate(kind, lambda d: d.__setitem__(key, value))
    assert codes(project) & {'schema_error', 'filename_mismatch', 'id_format'}


@pytest.mark.parametrize('path', ['/tmp/x', '../x', 'src/../../x', r'C:\x', 'C:/x', 'src/*.py', './src', 'src//code.py'])
def test_unsafe_or_unsupported_paths(project, path):
    with pytest.raises(ValueError):
        safe_path(project, path)


def test_symlink_escape(project, tmp_path):
    (project / 'escape').symlink_to(tmp_path)
    with pytest.raises(ValueError):
        safe_path(project, 'escape/file')


def test_fact_file_symlink_escape(project, tmp_path):
    file = next((project / '.project/features').rglob('*.yaml'))
    outside = tmp_path / 'outside.yaml'
    outside.write_text(file.read_text())
    file.unlink()
    file.symlink_to(outside)
    assert 'input_error' in codes(project)


def test_local_links_and_yaml_12_booleans(project):
    assert safe_path(project, 'src/**', claim=True) == project / 'src'
    path = project / 'sample.yaml'
    path.write_text('on: yes\ntrue_value: true\n')
    assert read_yaml(path) == {'on': 'yes', 'true_value': True}


def test_duplicate_ids_across_files(project):
    path = next((project / '.project/features').rglob('*.yaml'))
    (path.parent / 'duplicate.yaml').write_text(path.read_text())
    errors = validate_project(project).errors
    assert any(e.code == 'duplicate_id' and e.file and e.field == 'id' for e in errors)


@pytest.mark.parametrize('mutation,expected', [
    (lambda f: f.update(requirement_refs=['REQ-missing']), 'missing_reference'),
    (lambda f: f.update(depends_on=[f['id']]), 'dependency_cycle'),
    (lambda f: f['acceptance'][0].update(required=False), 'required_ac_missing'),
    (lambda f: f['verification'].update(checks=[]), 'required_check_missing'),
    (lambda f: f['verification']['checks'][0].update(acceptance_ref='AC-missing'), 'missing_reference'),
    (lambda f: f['verification']['checks'][0].update(command_ref='missing'), 'missing_reference'),
    (lambda f: f.update(domain='other'), 'domain_mismatch'),
    (lambda f: f['implementation'].update(state='complete'), 'subject_required'),
    (lambda f: f['implementation'].update(subject={'kind':'example','value':'example'}), 'example_subject'),
    (lambda f: f['implementation'].update(subject={'kind':'commit','value':'bad'}), 'subject_format'),
    (lambda f: f['verification']['checks'].append(deepcopy(f['verification']['checks'][0])), 'duplicate_local_id'),
])
def test_cross_document_invariants(project, mutate, mutation, expected):
    mutate('feature', mutation)
    assert expected in codes(project)


def test_two_feature_dependency_cycle(project):
    path = next((project / '.project/features').rglob('*.yaml'))
    one = read_yaml(path)
    two = deepcopy(one)
    two['id'] = 'FEAT-' + str(uuid4())
    two['depends_on'] = [one['id']]
    one['depends_on'] = [two['id']]
    path.write_text(dump_yaml(one))
    (path.parent / (two['id'] + '.yaml')).write_text(dump_yaml(two))
    assert 'dependency_cycle' in codes(project)


def test_confirmed_inferred_requires_confirmation(project, mutate):
    mutate('registry', lambda d: d['sources'][0].update(authority='inferred'))
    assert 'confirmation_required' in codes(project)
    mutate('requirement', lambda d: d.update(confirmation={'reviewer':'human','note':'explicitly reviewed','confirmed_at':'2026-10-08T00:00:00Z'}))
    assert not codes(project)


def test_paths_and_timestamps_report_fields(project, mutate):
    mutate('project', lambda d: d['commands']['test'].update(cwd='../outside'))
    assert any(e.code == 'unsafe_path' and e.field == 'commands.test.cwd' for e in validate_project(project).errors)
    mutate('project', lambda d: d['metadata'].update(created_at='2026-10-08T12:00:00'))
    assert 'schema_error' in codes(project)


def test_discovery_from_nested_directory(project, monkeypatch):
    monkeypatch.chdir(project / 'src')
    assert find_project() == project


@pytest.mark.parametrize('text', [
    'extensions: {date: 2026-10-08}\n', 'extensions: {float: .nan}\n',
    'extensions: {1: value}\n', 'extensions: &loop {self: *loop}\n',
    'extensions: {binary: !!binary SGVsbG8=}\n',
])
def test_non_json_yaml_values_rejected(project, text):
    path = project / '.project/project.yaml'
    path.write_text(path.read_text() + text)
    assert 'input_error' in codes(project)


def test_case_insensitive_rfc3339_timestamp(project, mutate):
    mutate('project', lambda d: d['metadata'].update(created_at='2026-10-08t00:00:00z', updated_at='2026-10-08t00:00:00z'))
    assert not codes(project)
