from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from apm.facts import dump_yaml, read_yaml


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    shutil.copytree(REPO / 'tests/fixtures/valid/.project', root / '.project')
    # Git does not preserve the fixture's empty Evidence directory.
    (root / '.project/evidence').mkdir(exist_ok=True)
    (root / 'src').mkdir()
    (root / 'src/code.py').write_text('value = 1\n')
    return root


@pytest.fixture
def mutate(project):
    def change(kind, update):
        if kind == 'project':
            path = project / '.project/project.yaml'
        elif kind == 'registry':
            path = project / '.project/sources/registry.yaml'
        else:
            directory = {'feature': 'features', 'requirement': 'requirements',
                         'run': 'runs', 'handoff': 'handoffs', 'evidence': 'evidence'}[kind]
            path = next((project / '.project' / directory).rglob('*.yaml'))
        data = read_yaml(path)
        update(data)
        path.write_text(dump_yaml(data))
        return data
    return change
