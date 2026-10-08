"""Small write API used by the CLI; every write validates a complete candidate."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .facts import Facts, Issue, dump_yaml, read_yaml, validate_project
from .state import active_claims, claims_overlap, conflicts, derive, utc_now
from .storage import commit_files, project_lock, require_revision


class OperationError(Exception):
    def __init__(self, code: int, issues: list[Issue]):
        self.code, self.issues = code, issues
        super().__init__(issues[0].message)


def fail(code: int, message: str, error: str = 'operation_error', entity: str | None = None) -> None:
    raise OperationError(code, [Issue(error, message, entity_ref=entity)])


def valid(root: Path, overrides: dict | None = None) -> Facts:
    facts = validate_project(root, overrides)
    if facts.errors:
        raise OperationError(2, facts.errors)
    return facts


def init_project(root: Path, name: str, *, dry_run: bool = False) -> dict:
    root = root.resolve()
    if (root / '.project').exists():
        fail(3, 'Existing .project is never overwritten', 'project_exists')
    now = utc_now()
    project = {'version': 1, 'id': 'PROJ-' + str(uuid4()), 'revision': 1,
               'name': name, 'description': name, 'mode': 'managed',
               'stack': {'language': None, 'runtime': None}, 'commands': {}, 'components': {},
               'git': {'default_branch': None},
               'policies': {'delivery_gate': 'merged', 'dependency_gate': 'delivered', 'allow_manual_evidence': True},
               'metadata': {'created_at': now, 'updated_at': now}}
    overrides = {'.project/project.yaml': project, '.project/sources/registry.yaml': {'version': 1, 'sources': []}}
    # For dry-run, no directory, lock, cache or generated file is created.
    valid(root, overrides)
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
        # Atomic directory installation means two competing init commands cannot
        # overwrite each other's facts. A temporary sibling is cleaned on failure.
        import tempfile
        import shutil
        temporary = Path(tempfile.mkdtemp(prefix='.apm-init-', dir=root))
        try:
            for relative, data in overrides.items():
                target = temporary / relative.removeprefix('.project/')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(dump_yaml(data), encoding='utf-8')
            for directory in ['requirements', 'features', 'runs', 'evidence', 'handoffs', 'cache', 'generated', 'transactions']:
                (temporary / directory).mkdir(exist_ok=True)
            try:
                temporary.rename(root / '.project')
            except OSError:
                if (root / '.project').exists():
                    fail(3, 'Project appeared during initialization', 'project_exists')
                raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return {'project': project, 'dry_run': dry_run}


def _run(facts: Facts, identity: str) -> dict:
    if identity not in facts.runs:
        fail(4, f'Unknown Run {identity}', 'not_found', identity)
    return facts.runs[identity]


def start_run(root: Path, feature_id: str, agent: str, instance: str,
              scope: str, *, override_reason: str | None = None, dry_run: bool = False) -> dict:
    def prepare() -> tuple[dict, str]:
        f = valid(root)
        if feature_id not in f.features:
            fail(4, f'Unknown Feature {feature_id}', 'not_found', feature_id)
        state = next(s for s in derive(f, utc_now())['features'] if s['id'] == feature_id)
        if state['lifecycle'] not in {'ready', 'developing', 'verifying', 'verified'}:
            fail(5, 'Feature prerequisites are not satisfied', 'prerequisite_blocked', feature_id)
        scope_type, sep, value = scope.partition(':')
        if not sep:
            fail(2, 'Scope must be feature:ID, component:NAME or path:PATH', 'invalid_scope')
        now = utc_now()
        claim = {'feature_ref': feature_id, 'scope': {'type': scope_type, 'value': value}, 'claimed_at': now}
        if override_reason:
            claim['override_reason'] = override_reason
        identity = 'RUN-' + str(uuid4())
        run = {'version': 1, 'id': identity, 'revision': 1,
               'agent': {'type': agent, 'version': 'unknown', 'instance_id': instance},
               'feature_refs': [feature_id], 'goal': f.features[feature_id]['title'],
               'status': 'active', 'started_at': now, 'ended_at': None, 'claims': [claim],
               'work': {'completed': [], 'remaining': [], 'blockers': []},
               'files_touched': [], 'commit_refs': [], 'handoff_ref': None}
        name = f'.project/runs/{identity}.yaml'
        valid(root, {name: run})  # Validate scope before attempting overlap matching.
        blocking = [c for c in active_claims(f) if claims_overlap(f, claim, c)]
        if blocking and not override_reason:
            fail(3, 'Overlapping active Claim: ' + ', '.join(sorted({c['run_ref'] for c in blocking})), 'claim_conflict')
        return run, name
    if dry_run:
        run, name = prepare()
    else:
        with project_lock(root):
            run, name = prepare()
            commit_files(root, {name: dump_yaml(run)})
    return {'run': run, 'dry_run': dry_run}


def update_run(root: Path, identity: str, expected: int, update: dict,
               *, dry_run: bool = False) -> dict:
    allowed = {'goal', 'work', 'files_touched', 'commit_refs', 'heartbeat_at'}
    if not isinstance(update, dict) or not set(update).issubset(allowed):
        fail(2, 'Update file accepts only goal, work, files_touched, commit_refs and heartbeat_at', 'invalid_update')
    def prepare():
        f = valid(root)
        run = deepcopy(_run(f, identity))
        require_revision(run, expected)
        if run['status'] != 'active':
            fail(3, 'Terminal Run is immutable', 'terminal_run', identity)
        run.update(update)
        run['revision'] += 1
        name = f.files[identity]
        valid(root, {name: run})
        return run, name
    if dry_run:
        run, name = prepare()
    else:
        with project_lock(root):
            run, name = prepare()
            commit_files(root, {name: dump_yaml(run)})
    return {'run': run, 'dry_run': dry_run}


def finish_run(root: Path, identity: str, expected: int, *, handoff: dict | None = None,
               abort_reason: str | None = None, dry_run: bool = False) -> dict:
    def prepare():
        f = valid(root)
        run = deepcopy(_run(f, identity))
        require_revision(run, expected)
        if run['status'] != 'active':
            fail(3, 'Terminal Run cannot be finished again', 'terminal_run', identity)
        run['status'] = 'aborted' if abort_reason else 'completed'
        run['ended_at'] = utc_now()
        run['revision'] += 1
        if abort_reason:
            run['finish_reason'] = abort_reason
        changes = {}
        if handoff is not None:
            if not isinstance(handoff, dict) or 'id' not in handoff:
                fail(2, 'Expected complete Handoff document', 'invalid_handoff')
            if handoff['id'] in f.handoffs:
                fail(3, 'Handoff is immutable and cannot be overwritten', 'handoff_exists')
            # Schema/cross validation also ensures ID is safe before writing.
            handoff_name = '.project/handoffs/' + handoff['id'] + '.yaml'
            run['handoff_ref'] = handoff['id']
            changes[handoff_name] = handoff
        changes[f.files[identity]] = run
        valid(root, changes)
        return run, changes
    if dry_run:
        run, changes = prepare()
    else:
        with project_lock(root):
            run, changes = prepare()
            commit_files(root, {name: dump_yaml(data) for name, data in changes.items()})
    return {'run': run, 'dry_run': dry_run}


def rebuild(root: Path, evaluated_at: str, *, dry_run: bool = False) -> dict:
    def prepare():
        f = valid(root)
        state = derive(f, evaluated_at)
        claims = active_claims(f)
        collisions = conflicts(f)
        edges = ([[feature['id'], 'requires', ref] for feature in f.features.values() for ref in feature['requirement_refs']]
                 + [[feature['id'], 'depends_on', ref] for feature in f.features.values() for ref in feature['depends_on']]
                 + [[requirement['id'], 'source', item['source_ref']] for requirement in f.requirements.values() for item in requirement['sources']]
                 + [[run['id'], 'feature', ref] for run in f.runs.values() for ref in run['feature_refs']]
                 + [[ev['id'], 'feature', ev['feature_ref']] for ev in f.evidence.values()]
                 + [[ev['id'], 'produced_by', ev['produced_by']['run_ref']] for ev in f.evidence.values()]
                 + [[handoff['id'], 'run', handoff['run_ref']] for handoff in f.handoffs.values()]
                 + [[handoff['id'], 'feature', ref] for handoff in f.handoffs.values() for ref in handoff['feature_refs']])
        graph = {'nodes': sorted([f.project['id'], *f.sources, *f.requirements, *f.features, *f.runs, *f.evidence, *f.handoffs]),
                 'edges': sorted(edges)}
        outputs = {'status': state, 'features': state['features'],
                   'claims': {'claims': claims, 'conflicts': collisions}, 'graph': graph}
        return state, outputs
    if dry_run:
        state, outputs = prepare()
    else:
        with project_lock(root):
            state, outputs = prepare()
            commit_files(root, {f'.project/generated/{kind}.json': dump_yaml(value) for kind, value in outputs.items()})
    return {'summary': state['summary'], 'evaluated_at': evaluated_at,
            'files': [f'.project/generated/{kind}.json' for kind in outputs], 'dry_run': dry_run}
