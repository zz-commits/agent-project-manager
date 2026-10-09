"""Explicit, reviewed fact proposals; no inferred confirmation or PASS records."""

from copy import deepcopy
from uuid import uuid4

from .facts import dump_yaml, parse_timestamp
from .operations import fail, valid
from .state import canonical_digest, current_subject, utc_now
from .storage import commit_files, project_lock, require_revision


def snapshot(f):
    return canonical_digest({k: getattr(f, k) for k in
                             ('project', 'sources', 'requirements', 'features', 'runs', 'evidence', 'handoffs')})


def active(f, run_id, kind, action, target):
    run = f.runs.get(run_id)
    if not run or run['status'] != 'active':
        fail(5, 'An active Run is required', 'run_prerequisite')
    if kind == 'feature' and action == 'update' and target not in run['feature_refs']:
        fail(5, 'Feature must belong to the active Run', 'run_prerequisite')


def candidate(root, f, kind, action, target, expected, incoming, timestamp):
    if kind not in {'requirement', 'feature'} or action not in {'create', 'update', 'confirm'}:
        fail(2, 'Unknown fact operation', 'argument_error')
    entities = getattr(f, kind + 's')
    if not isinstance(incoming, dict):
        fail(2, 'Input must be an object', 'invalid_input')
    if action == 'create':
        if target in entities:
            fail(3, 'Entity already exists', 'fact_exists')
        obj = {'version': 1, 'id': target, 'revision': 1,
               'metadata': {'created_at': timestamp, 'updated_at': timestamp}}
    else:
        if target not in entities:
            fail(4, 'Entity does not exist', 'not_found', target)
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
            fail(2, 'A positive expected revision is required', 'argument_error')
        require_revision(entities[target], expected)
        obj = deepcopy(entities[target])
        obj['revision'] += 1
        obj['metadata']['updated_at'] = timestamp
    if action == 'confirm':
        if kind != 'requirement' or incoming or obj['blockers']:
            fail(5, 'Only an unblocked Requirement can be explicitly confirmed', 'confirmation_blocked')
        refs = obj['sources']
        if (not any(f.sources[r['source_ref']]['authority'] == 'primary' for r in refs)
                or any(r['source_revision'] != f.sources[r['source_ref']]['revision'] for r in refs)):
            fail(5, 'Confirmation requires a current primary source and reviewed source revisions', 'confirmation_blocked')
        obj['status'] = 'confirmed'
        return obj
    allowed = ({'title', 'description', 'sources', 'acceptance', 'blockers', 'extensions'}
               if kind == 'requirement' else
               {'title', 'domain', 'requirement_refs', 'priority', 'size', 'depends_on', 'blockers',
                'acceptance', 'verification', 'extensions'})
    if kind == 'feature' and action == 'update':
        allowed = (allowed - {'domain', 'requirement_refs'}) | {'implementation'}
    if not set(incoming).issubset(allowed):
        fail(2, 'Input contains protected or unknown fields', 'protected_field')
    if kind == 'requirement':
        if action == 'create':
            obj.update(status='draft', blockers=[])
        elif any(k in incoming and incoming[k] != obj.get(k)
                 for k in ('title', 'description', 'sources', 'acceptance')):
            if obj['status'] == 'confirmed':
                obj['status'] = 'changed'
            obj.pop('confirmation', None)
        obj.update(deepcopy(incoming))
        return obj
    if action == 'create':
        obj.update(priority='P1', size='M', depends_on=[], blockers=[], acceptance_revision=1,
                   implementation={'state': 'not_started', 'evidence_level': 'declared', 'components': {},
                                   'completed': [], 'remaining': [], 'evidence_refs': [], 'subject': None},
                   verification={'checks': []}, delivery={'records': []})
    else:
        if 'acceptance' in incoming and incoming['acceptance'] != obj['acceptance']:
            obj['acceptance_revision'] += 1
    patch = deepcopy(incoming)
    implementation = patch.pop('implementation', None)
    verification = patch.pop('verification', None)
    obj.update(patch)
    if implementation is not None:
        if (not isinstance(implementation, dict) or not set(implementation).issubset(
                {'state', 'evidence_level', 'components', 'completed', 'remaining'})
                or implementation.get('evidence_level') == 'verified'):
            fail(2, 'Implementation updates are declarations; subject/evidence are protected', 'protected_field')
        obj['implementation'].update(implementation)
        obj['implementation']['subject'] = (None if obj['implementation']['state'] == 'not_started'
                                             else current_subject(root))
    if verification is None and action == 'create':
        verification = {'checks': [{'id': f'CHECK-{i+1:03}', 'acceptance_ref': ac['id'],
                                     'required': ac['required']} for i, ac in enumerate(obj.get('acceptance', []))]}
    if verification is not None:
        if not isinstance(verification, dict) or set(verification) != {'checks'}:
            fail(2, 'Verification input accepts only Check definitions', 'protected_field')
        old = {c['id']: c for c in obj['verification']['checks']}
        checks = []
        for item in verification['checks']:
            if not isinstance(item, dict) or not set(item).issubset(
                    {'id', 'acceptance_ref', 'required', 'command_ref', 'testcase_refs', 'extensions'}):
                fail(2, 'Check activity and Evidence references are protected', 'protected_field')
            previous = old.get(item.get('id'), {})
            checks.append({**deepcopy(item), 'activity': previous.get('activity', 'idle'),
                           'evidence_refs': list(previous.get('evidence_refs', []))})
        if not set(old).issubset({c['id'] for c in checks}):
            fail(2, 'Existing Checks cannot be removed; preserve historical evidence bindings', 'protected_field')
        obj['verification']['checks'] = checks
    return obj


def propose(root, kind, action, incoming, target=None, expected=None):
    f = valid(root)
    target = target or ('REQ-' if kind == 'requirement' else 'FEAT-') + str(uuid4())
    now = utc_now()
    obj = candidate(root, f, kind, action, target, expected, incoming, now)
    # confirm adds its provenance only on explicit apply; validate a complete candidate preview.
    if action == 'confirm':
        obj['confirmation'] = {'reviewer': 'preview', 'note': 'Explicit confirmation preview', 'confirmed_at': now}
    name = (f'.project/requirements/{target}.yaml' if kind == 'requirement' else
            f'.project/features/{obj["domain"]}/{target}.yaml')
    valid(root, {name: obj})
    if action == 'confirm':
        from .sources import _confirmed
        _confirmed(valid(root, {name: obj}), target)
    p = {'version': 1, 'kind': 'fact_write', 'entity': kind, 'action': action, 'target': target,
         'expected_revision': expected, 'snapshot_digest': snapshot(f), 'created_at': now,
         'input': deepcopy(incoming), 'candidate': obj, 'before': deepcopy(getattr(f, kind + 's').get(target))}
    p['digest'] = canonical_digest(p)
    return {'proposal': p, 'dry_run': True}


def apply(root, kind, action, proposal, run_id, reviewer, note, *, target=None, expected=None, dry_run=False):
    if not reviewer or not reviewer.strip() or not note or not note.strip():
        fail(2, 'Apply requires a nonempty reviewer and note', 'argument_error')
    p = deepcopy(proposal)
    if isinstance(p, dict) and p.get('protocol_version') == 1:
        p = p.get('data', {})
    if isinstance(p, dict) and 'proposal' in p:
        p = p['proposal']
    if not isinstance(p, dict) or p.get('version') != 1 or p.get('kind') != 'fact_write':
        fail(2, 'Expected a fact_write proposal', 'invalid_proposal')
    digest = p.pop('digest', None)
    if digest != canonical_digest(p) or p['entity'] != kind or p['action'] != action:
        fail(3, 'Proposal was changed or belongs to another operation', 'proposal_conflict')
    if (target is not None and p['target'] != target) or p['expected_revision'] != expected:
        fail(3, 'Proposal target/revision differs from the command', 'proposal_conflict')
    if parse_timestamp(p['created_at']).tzinfo is None:
        fail(2, 'Proposal timestamp must have a timezone', 'invalid_proposal')
    def prepare():
        f = valid(root)
        active(f, run_id, kind, action, p['target'])
        if snapshot(f) != p['snapshot_digest']:
            fail(3, 'Facts changed; generate and review a fresh proposal', 'proposal_conflict')
        obj = candidate(root, f, kind, action, p['target'], expected, p['input'], p['created_at'])
        if action == 'confirm':
            preview = deepcopy(obj)
            preview['confirmation'] = {'reviewer': 'preview', 'note': 'Explicit confirmation preview',
                                       'confirmed_at': p['created_at']}
        else:
            preview = obj
        if preview != p['candidate'] or p['before'] != getattr(f, kind + 's').get(p['target']):
            fail(3, 'Candidate differs from its inputs/current facts', 'proposal_conflict')
        if action == 'confirm':
            obj['confirmation'] = {'reviewer': reviewer, 'note': note, 'confirmed_at': utc_now()}
        name = (f'.project/requirements/{obj["id"]}.yaml' if kind == 'requirement' else
                f'.project/features/{obj["domain"]}/{obj["id"]}.yaml')
        changes = {name: obj}
        if kind == 'feature' and action == 'create':
            run = deepcopy(f.runs[run_id])
            run['feature_refs'].append(obj['id'])
            run['revision'] += 1
            changes[f.files[run_id]] = run
        valid(root, changes)
        if action == 'confirm':
            from .sources import _confirmed
            _confirmed(valid(root, {name: obj}), obj['id'])
        audit = {'version': 1, 'kind': 'fact_write_review', 'run_ref': run_id, 'reviewer': reviewer,
                 'note': note, 'created_at': utc_now(), 'proposal': {**p, 'digest': digest}, 'after': obj}
        if len(changes) > 1:
            audit['run_after'] = run
        path = f'.project/artifacts/{uuid4()}/review.json'
        return obj, changes, audit, path
    if dry_run:
        obj, changes, audit, path = prepare()
    else:
        with project_lock(root):
            obj, changes, audit, path = prepare()
            commit_files(root, {**{n: dump_yaml(v) for n, v in changes.items()}, path: dump_yaml(audit)})
    return {'facts': obj, 'dry_run': dry_run, 'review_artifact': None if dry_run else path}
