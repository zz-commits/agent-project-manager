"""Local, read-only adapters and reviewed changes bound to exact input snapshots."""

from copy import deepcopy
import hashlib
import re
from uuid import uuid4

from jsonschema import Draft202012Validator
from ruamel.yaml.error import YAMLError

from .facts import FORMAT_CHECKER, dump_yaml, load_yaml, read_yaml, safe_path, schema_resources
from .operations import OperationError, fail, valid
from .state import canonical_digest, utc_now
from .storage import commit_files, project_lock


MAX_SOURCE = 2 * 1024 * 1024


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _schema(value, definition):
    documents, registry = schema_resources()
    validator = Draft202012Validator({'$ref': 'urn:apm:v1#/$defs/' + definition},
                                    registry=registry, format_checker=FORMAT_CHECKER)
    errors = list(validator.iter_errors(value))
    if errors:
        fail(2, errors[0].message, 'schema_error')


def _active(f, run_id):
    if run_id not in f.runs:
        fail(4, 'Run does not exist', 'not_found')
    if f.runs[run_id]['status'] != 'active':
        fail(5, 'An active Run is required', 'run_prerequisite')


def registry_view(root, identity=None):
    f = valid(root)
    if identity and identity not in f.sources:
        fail(4, 'Source does not exist', 'not_found', identity)
    return {'sources': [f.sources[identity]] if identity else list(f.sources.values()),
            'digest': _sha((root / '.project/sources/registry.yaml').read_bytes())}


def add_source(root, source, expected_digest, run_id, *, dry_run=False):
    def prepare():
        f = valid(root)
        _active(f, run_id)
        if not re.fullmatch(r'[0-9a-f]{64}', expected_digest):
            fail(2, 'Expected digest is a lowercase SHA-256', 'argument_error')
        path = root / '.project/sources/registry.yaml'
        if _sha(path.read_bytes()) != expected_digest:
            fail(3, 'Registry changed', 'stale_registry')
        _schema(source, 'source')
        if source['id'] in f.sources:
            fail(3, 'Source ID already exists', 'source_exists')
        registry = read_yaml(path)
        registry['sources'].append(deepcopy(source))
        changes = {'.project/sources/registry.yaml': registry}
        valid(root, changes)
        return changes
    if dry_run:
        changes = prepare()
    else:
        with project_lock(root):
            changes = prepare()
            commit_files(root, {name: dump_yaml(value) for name, value in changes.items()})
    return {'source': source, 'dry_run': dry_run,
            'digest': registry_view(root)['digest']}


def _input(root, name):
    path = safe_path(root, name)
    if not path.is_file():
        fail(4, 'Local input file does not exist', 'input_missing')
    if path.stat().st_size > MAX_SOURCE:
        fail(2, 'Input exceeds 2 MiB', 'input_too_large')
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE:
        fail(2, 'Input exceeds 2 MiB', 'input_too_large')
    return raw, {'path': name, 'sha256': _sha(raw)}


def _records(records):
    if not isinstance(records, list) or len(records) > 256:
        fail(2, 'Expected at most 256 requirement records', 'invalid_input')
    for record in records:
        _schema(record, 'source_record')
    keys = [record['key'] for record in records]
    if len(keys) != len(set(keys)):
        fail(2, 'Requirement keys must be unique within a Source', 'duplicate_key')
    return records


def parse_markdown(raw):
    text = raw.decode('utf-8-sig')
    records, opened, lines, selected = [], None, [], False
    for line in text.splitlines():
        if opened:
            marker, width = opened
            if re.fullmatch(r' {0,3}' + re.escape(marker) + '{' + str(width) + r',}\s*', line):
                if selected:
                    records.append(load_yaml('\n'.join(lines)))
                opened, lines, selected = None, [], False
            elif selected:
                lines.append(line)
            continue
        match = re.fullmatch(r' {0,3}(`{3,}|~{3,})([^\r\n]*)', line)
        if match:
            marker, info = match.groups()
            info = info.strip()
            if info.startswith('apm-requirement') and info != 'apm-requirement':
                fail(2, 'Dedicated fence requires exactly apm-requirement', 'invalid_fence')
            opened, selected = (marker[0], len(marker)), info == 'apm-requirement'
    if opened and selected:
        fail(2, 'Unclosed apm-requirement fence', 'unclosed_fence')
    return _records(records)


def _extract(root, source, agent_file=None):
    if agent_file:
        if source['adapter']['name'] != 'manual':
            fail(2, 'Agent requirement input requires the manual Adapter', 'unsupported_adapter')
        raw, snapshot = _input(root, agent_file)
        value = load_yaml(raw.decode('utf-8-sig'))
        if not isinstance(value, dict) or set(value) != {'requirements'}:
            fail(2, 'Agent input must be {requirements: [...]}', 'invalid_input')
        return _records(value['requirements']), snapshot
    if (source['type'] != 'markdown' or source['adapter']['name'] != 'markdown'
            or 'path' not in source['location']):
        fail(2, 'Only local Markdown Adapter is supported', 'unsupported_adapter')
    raw, snapshot = _input(root, source['location']['path'])
    return parse_markdown(raw), snapshot


def _base(f):
    names = {'.project/project.yaml', '.project/sources/registry.yaml'}
    names.update(f.files[identity] for identity in [*f.requirements, *f.features])
    return canonical_digest({name: _sha((f.root / name).read_bytes()) for name in sorted(names)})


def _body(record):
    return {key: record[key] for key in ['title', 'description', 'acceptance']}


def _source_requirements(f, source_id):
    result = {}
    for req in f.requirements.values():
        for link in req['sources']:
            if link['source_ref'] == source_id and link['locator'].startswith('block:'):
                key = link['locator'][6:]
                if key in result:
                    fail(3, 'More than one Requirement matches a source key', 'ambiguous_locator')
                result[key] = req
    return result


def _conflicts(root, f, req, record, inputs):
    notes = []
    for link in req['sources']:
        other = f.sources[link['source_ref']]
        if other['id'] == record['source_ref'] or other['authority'] != 'primary':
            continue
        observed = _body(req)
        if other['adapter']['name'] == 'markdown':
            try:
                if 'path' in other['location']:
                    _, snapshot = _input(root, other['location']['path'])
                    inputs[snapshot['path']] = snapshot
                records, snapshot = _extract(root, other)
                inputs[snapshot['path']] = snapshot
                matches = [r for r in records if 'block:' + r['key'] == link['locator']]
                observed = _body(matches[0]) if len(matches) == 1 else None
            except (OperationError, ValueError, YAMLError):
                observed = None
        if observed != _body(record):
            notes.append('source_conflict:' + other['id'])
    return sorted(set(notes))


def _source_changes(root, f, source_id, records, revision, created_at, allocated):
    known = _source_requirements(f, source_id)
    inputs, changes, conflicts = {}, [], []
    registry = read_yaml(root / '.project/sources/registry.yaml')
    source = next(s for s in registry['sources'] if s['id'] == source_id)
    if source['revision'] != revision:
        source.update(revision=revision, captured_at=created_at)
        changes.append({'path': '.project/sources/registry.yaml', 'before': read_yaml(root / '.project/sources/registry.yaml'), 'after': registry})
    for record in records:
        original = known.get(record['key'])
        if original:
            req = deepcopy(original)
            notes = _conflicts(root, f, req, {**record, 'source_ref': source_id}, inputs)
            req['blockers'] = [b for b in req['blockers'] if not b.startswith(('source_conflict:', 'source_missing:' + source_id + ':'))]
            req['blockers'].extend(notes)
            if not notes:
                req.update(_body(record))
            for link in req['sources']:
                if link['source_ref'] == source_id and link['locator'] == 'block:' + record['key']:
                    link['source_revision'] = revision
            if req == original:
                continue
            req['status'] = 'blocked' if req['blockers'] else ('draft' if original['status'] == 'draft' else 'changed')
            req.pop('confirmation', None)
            req['revision'] += 1
            req['metadata']['updated_at'] = created_at
            name = f.files[req['id']]
            conflicts.extend({'requirement_ref': req['id'], 'note': note} for note in notes)
        else:
            identity = allocated[record['key']]
            if identity in f.files:
                fail(3, 'Allocated Requirement ID already exists', 'requirement_exists')
            req = {'version': 1, 'id': identity, 'revision': 1, **_body(record), 'status': 'draft',
                   'sources': [{'source_ref': source_id, 'source_revision': revision, 'locator': 'block:' + record['key']}],
                   'blockers': [], 'metadata': {'created_at': created_at, 'updated_at': created_at}}
            name = '.project/requirements/' + identity + '.yaml'
        changes.append({'path': name, 'before': original, 'after': req})
    missing = set(known) - {r['key'] for r in records}
    for key in sorted(missing):
        original = known[key]
        note = 'source_missing:' + source_id + ':' + key
        if note in original['blockers']:
            continue
        req = deepcopy(original)
        req['blockers'].append(note)
        req['status'] = 'changed'
        req.pop('confirmation', None)
        req['revision'] += 1
        req['metadata']['updated_at'] = created_at
        changes.append({'path': f.files[req['id']], 'before': original, 'after': req})
    return changes, conflicts, list(inputs.values())


def _seal(proposal):
    proposal['digest'] = canonical_digest(proposal)
    _schema(proposal, 'proposal')
    return proposal


def propose_source(root, source_id, agent_file=None, *, allocated=None, created_at=None, identity=None):
    f = valid(root)
    if source_id not in f.sources:
        fail(4, 'Source does not exist', 'not_found')
    records, snapshot = _extract(root, f.sources[source_id], agent_file)
    known = _source_requirements(f, source_id)
    if not records and not known:
        fail(5, 'No dedicated requirements found', 'zero_requirements')
    keys = {r['key'] for r in records} - set(known)
    allocated = allocated if allocated is not None else {key: 'REQ-' + str(uuid4()) for key in sorted(keys)}
    if set(allocated) != keys:
        fail(3, 'Requirement allocation does not match extracted input', 'proposal_mismatch')
    now = created_at or utc_now()
    changes, conflicts, other_inputs = _source_changes(root, f, source_id, records, 'sha256:' + snapshot['sha256'], now, allocated)
    valid(root, {c['path']: c['after'] for c in changes})
    return _seal({'version': 1, 'id': identity or str(uuid4()), 'kind': 'source_sync', 'target': source_id,
                  'base_digest': _base(f), 'inputs': sorted({i['path']: i for i in [snapshot, *other_inputs]}.values(), key=lambda i: i['path']),
                  'payload': {'agent_file': agent_file, 'allocated': allocated, 'records': records}, 'changes': changes,
                  'conflicts': conflicts, 'created_at': now})


def _confirmed(f, identity):
    if identity not in f.requirements:
        fail(4, 'Requirement does not exist', 'not_found')
    req = f.requirements[identity]
    if req['status'] != 'confirmed' or req['blockers']:
        fail(5, 'Decomposition requires confirmed, unblocked Requirement', 'requirement_prerequisite')
    inputs = []
    for link in req['sources']:
        source = f.sources[link['source_ref']]
        if source['authority'] == 'primary' and source['revision'] != link['source_revision']:
            fail(3, 'Primary source revision differs from confirmed Requirement', 'stale_source')
        if source['authority'] == 'primary' and source['adapter']['name'] == 'markdown':
            records, snapshot = _extract(f.root, source)
            if link['source_revision'] != 'sha256:' + snapshot['sha256']:
                fail(3, 'Confirmed Requirement source has changed; sync first', 'stale_source')
            matches = [r for r in records if 'block:' + r['key'] == link['locator']]
            if len(matches) != 1 or _body(matches[0]) != _body(req):
                fail(3, 'Primary Markdown content disagrees with confirmed Requirement', 'source_conflict')
            inputs.append(snapshot)
    return req, inputs


def propose_decomposition(root, requirement_id, plan_file, *, created_at=None, identity=None):
    f = valid(root)
    _, inputs = _confirmed(f, requirement_id)
    raw, snapshot = _input(root, plan_file)
    plan = load_yaml(raw.decode('utf-8-sig'))
    if not isinstance(plan, dict) or set(plan) != {'features'} or not isinstance(plan['features'], list) or not plan['features']:
        fail(2, 'Plan must be {features: [complete Feature, ...]}', 'invalid_plan')
    changes = {}
    for feature in plan['features']:
        _schema(feature, 'feature')
        implementation = feature['implementation']
        if (feature['id'] in f.files or feature['id'] in {v['id'] for v in changes.values()}):
            fail(3, 'Feature ID already exists or is duplicated', 'feature_exists')
        if (feature['requirement_refs'] != [requirement_id] or feature['revision'] != 1 or feature['acceptance_revision'] != 1
                or implementation['state'] != 'not_started' or implementation['evidence_level'] != 'declared'
                or implementation['subject'] is not None or implementation['evidence_refs'] or implementation['completed']
                or feature['delivery']['records'] or any(c['evidence_refs'] or c['activity'] != 'idle' for c in feature['verification']['checks'])):
            fail(2, 'Only new, unverified initial Features for this Requirement can be imported', 'invalid_plan')
        name = '.project/features/' + feature['domain'] + '/' + feature['id'] + '.yaml'
        changes[name] = feature
    valid(root, changes)
    return _seal({'version': 1, 'id': identity or str(uuid4()), 'kind': 'decompose', 'target': requirement_id,
                  'base_digest': _base(f), 'inputs': sorted({i['path']: i for i in [snapshot, *inputs]}.values(), key=lambda i: i['path']),
                  'payload': {'plan_file': plan_file}, 'changes': [{'path': name, 'before': None, 'after': value} for name, value in changes.items()],
                  'conflicts': [], 'created_at': created_at or utc_now()})


def apply_proposal(root, proposal, run_id, reviewer, note, *, kind, target, dry_run=False):
    # Also accept the exact CLI response redirected by an agent to a file.
    if isinstance(proposal, dict) and proposal.get('protocol_version') == 1 and proposal.get('ok') is True:
        data = proposal.get('data')
        proposal = data.get('proposal') if isinstance(data, dict) else None
    _schema(proposal, 'proposal')
    proposal = deepcopy(proposal)
    if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(note, str) or not note.strip():
        fail(2, 'Apply requires nonempty reviewer and note', 'review_required')
    def prepare():
        f = valid(root)
        _active(f, run_id)
        digest = canonical_digest({k: v for k, v in proposal.items() if k != 'digest'})
        if digest != proposal['digest'] or proposal['kind'] != kind or proposal['target'] != target:
            fail(3, 'Proposal contents or target do not match', 'proposal_mismatch')
        if _base(f) != proposal['base_digest']:
            fail(3, 'Proposal facts changed; regenerate before applying', 'stale_proposal')
        for input in proposal['inputs']:
            try:
                _, snapshot = _input(root, input['path'])
            except OperationError as exc:
                if exc.code == 4:
                    fail(3, 'Proposal input disappeared', 'stale_input')
                raise
            if snapshot != input:
                fail(3, 'Proposal input changed', 'stale_input')
        if kind == 'source_sync':
            expected = propose_source(root, target, proposal['payload'].get('agent_file'),
                                      allocated=proposal['payload'].get('allocated'), created_at=proposal['created_at'], identity=proposal['id'])
        else:
            expected = propose_decomposition(root, target, proposal['payload']['plan_file'],
                                             created_at=proposal['created_at'], identity=proposal['id'])
        if proposal != expected:
            fail(3, 'Proposal does not match adapter output; regenerate it', 'proposal_mismatch')
        changes = {c['path']: c['after'] for c in proposal['changes']}
        if not changes:
            fail(5, 'Proposal contains no changes', 'no_changes')
        valid(root, changes)
        # The transaction retains the reviewed content and pre/post snapshots.
        review = {'proposal': proposal, 'applied_by': {'run_ref': run_id, 'reviewer': reviewer, 'note': note}, 'applied_at': utc_now()}
        artifact = f'.project/artifacts/{proposal["id"]}/review.json'
        if (root / artifact).exists():
            fail(3, 'Proposal has already been applied', 'proposal_applied')
        return changes, artifact, review
    if dry_run:
        changes, artifact, review = prepare()
    else:
        with project_lock(root):
            changes, artifact, review = prepare()
            commit_files(root, {artifact: dump_yaml(review), **{name: dump_yaml(value) for name, value in changes.items()}})
    return {'proposal_id': proposal['id'], 'changes': proposal['changes'], 'conflicts': proposal['conflicts'],
            'review_artifact': None if dry_run else artifact, 'dry_run': dry_run}
