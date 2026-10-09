"""Strict, read-only loading and structural/cross-document validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    file: str | None = None
    entity_ref: str | None = None
    field: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Facts:
    root: Path
    project: dict = field(default_factory=dict)
    sources: dict[str, dict] = field(default_factory=dict)
    requirements: dict[str, dict] = field(default_factory=dict)
    features: dict[str, dict] = field(default_factory=dict)
    runs: dict[str, dict] = field(default_factory=dict)
    evidence: dict[str, dict] = field(default_factory=dict)
    handoffs: dict[str, dict] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    def error(self, code: str, message: str, entity: str | None = None,
              field: str | None = None, file: str | None = None) -> None:
        self.errors.append(Issue(code, message, file or self.files.get(entity), entity, field))


class ProjectNotFound(Exception):
    pass


def find_project(path: str | Path | None = None) -> Path:
    candidate = Path(path or Path.cwd()).resolve()
    if path is not None:
        if not (candidate / '.project/project.yaml').is_file():
            raise ProjectNotFound(str(candidate))
        return candidate
    for parent in [candidate, *candidate.parents]:
        if (parent / '.project/project.yaml').is_file():
            return parent
    raise ProjectNotFound(str(candidate))


def read_yaml(path: Path) -> Any:
    return load_yaml(path.read_text(encoding='utf-8'))


def load_yaml(text: str) -> Any:
    yaml = YAML(typ='safe', pure=True)
    yaml.version = (1, 2)
    yaml.allow_duplicate_keys = False
    value = yaml.load(text)
    _json_compatible(value, set())
    return value


def _json_compatible(value: Any, visiting: set[int]) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Non-finite numbers are forbidden')
        return
    if isinstance(value, (dict, list)):
        if id(value) in visiting:
            raise ValueError('Cyclic YAML aliases are forbidden')
        visiting.add(id(value))
        if isinstance(value, dict) and any(not isinstance(key, str) for key in value):
            raise ValueError('Object keys must be strings')
        for item in value.values() if isinstance(value, dict) else value:
            _json_compatible(item, visiting)
        visiting.remove(id(value))
        return
    raise ValueError('Only JSON-compatible YAML values are supported; quote timestamps')


def parse_timestamp(value: str) -> datetime:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value, re.IGNORECASE):
        raise ValueError('Expected RFC3339 timestamp with seconds and timezone')
    return datetime.fromisoformat(value.upper())


FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks('date-time', raises=ValueError)
def _rfc3339(value):
    if not isinstance(value, str):
        return True  # JSON Schema's type rule supplies the diagnostic.
    parse_timestamp(value)
    return True


def dump_yaml(value: Any) -> str:
    # JSON is a YAML 1.2 subset, preserves string timestamps and needs no custom tags.
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def safe_path(root: Path, value: str, *, claim: bool = False) -> Path:
    if not value or '\\' in value or '\x00' in value or value.startswith('/'):
        raise ValueError('Expected a repository-relative POSIX path')
    if re.match(r'^[A-Za-z]:', value):
        raise ValueError('Drive paths are not repository-relative')
    raw = value
    if claim and value.endswith('/**'):
        value = value[:-3] or '.'
    if any(ch in value for ch in '*?[]') or '..' in PurePosixPath(value).parts:
        raise ValueError('Parent traversal and unsupported globs are forbidden')
    if value != '.' and any(p == '' or p == '.' for p in value.rstrip('/').split('/')):
        raise ValueError('Path must be normalized')
    target = (root / value).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes project: {raw}')
    return target


def schema_resources() -> tuple[dict, Registry]:
    source = Path(__file__).resolve().parents[2] / 'schemas/v1'
    directory = source if source.is_dir() else Path(__file__).parent / 'schemas/v1'
    documents = {p.stem: json.loads(p.read_text()) for p in sorted(directory.glob('*.json'))}
    if 'protocol' not in documents:
        raise RuntimeError('Packaged schemas are missing')
    registry = Registry().with_resources(
        (doc['$id'], Resource.from_contents(doc)) for doc in documents.values()
    )
    return documents, registry


def validate_project(root: Path, overrides: dict[str, dict] | None = None) -> Facts:
    root = root.resolve()
    facts = Facts(root)
    overrides = overrides or {}
    documents, registry = schema_resources()
    base = root / '.project'
    candidates: dict[str, str] = {'.project/project.yaml': 'project',
                                  '.project/sources/registry.yaml': 'registry'}
    for folder, kind in [('requirements', 'requirement'), ('features', 'feature'),
                         ('runs', 'run'), ('evidence', 'evidence'), ('handoffs', 'handoff')]:
        for path in sorted((base / folder).rglob('*')):
            if path.suffix in {'.yaml', '.yml', '.json'} and path.is_file():
                candidates[path.relative_to(root).as_posix()] = kind
    for name in overrides:
        folder = PurePosixPath(name).parts[1]
        kind = {'requirements': 'requirement', 'features': 'feature', 'runs': 'run',
                'evidence': 'evidence', 'handoffs': 'handoff', 'sources': 'registry'}.get(folder)
        if name == '.project/project.yaml':
            kind = 'project'
        if not kind:
            raise ValueError(f'Unsupported fact override {name}')
        candidates[name] = kind
    groups = {'source': facts.sources, 'requirement': facts.requirements,
              'feature': facts.features, 'run': facts.runs,
              'evidence': facts.evidence, 'handoff': facts.handoffs}
    seen: set[str] = set()
    for name, kind in sorted(candidates.items()):
        try:
            path = safe_path(root, name)
            data = overrides[name] if name in overrides else read_yaml(path)
        except (OSError, ValueError, YAMLError) as exc:
            # Parsing errors never permit partial facts to be treated as a valid project.
            facts.error('input_error', str(exc), file=name)
            continue
        validator = Draft202012Validator(documents[kind], registry=registry,
                                          format_checker=FORMAT_CHECKER)
        issues = sorted(validator.iter_errors(data), key=lambda e: str(list(e.absolute_path)))
        for error in issues:
            facts.error('schema_error', error.message,
                        data.get('id') if isinstance(data, dict) else None,
                        '.'.join(map(str, error.absolute_path)) or '$', name)
        if issues:
            continue
        if kind == 'registry':
            entities = [('source', source) for source in data['sources']]
        else:
            entities = [(kind, data)]
        for entity_kind, entity in entities:
            identity = entity['id']
            if identity in seen:
                facts.error('duplicate_id', f'Duplicate ID {identity}', identity, 'id', name)
                continue
            seen.add(identity)
            facts.files[identity] = name
            if entity_kind == 'project':
                facts.project = entity
            else:
                groups[entity_kind][identity] = entity
                if entity_kind != 'source' and PurePosixPath(name).stem != identity:
                    facts.error('filename_mismatch', 'Filename must equal entity ID', identity, 'id')
    if facts.errors:
        return facts
    _cross_validate(facts)
    return facts


def _cross_validate(f: Facts) -> None:
    example = f.project['mode'] == 'example'
    all_entities = {f.project['id']: f.project, **f.sources, **f.requirements,
                    **f.features, **f.runs, **f.evidence, **f.handoffs}

    def path(value: str, identity: str, field: str, claim: bool = False) -> None:
        try:
            safe_path(f.root, value, claim=claim)
        except ValueError as exc:
            f.error('unsafe_path', str(exc), identity, field)

    def reference(value: str, group: dict, identity: str, field: str) -> bool:
        if value not in group:
            f.error('missing_reference', f'Unknown reference {value}', identity, field)
            return False
        return True

    def unique(items: list[dict], identity: str, field: str) -> None:
        ids = [item['id'] for item in items]
        if len(ids) != len(set(ids)):
            f.error('duplicate_local_id', 'IDs must be unique within Feature', identity, field)

    def subject(value: dict | None, identity: str, field: str) -> None:
        if value is None:
            return
        kind, val = value['kind'], value['value']
        pattern = r'[0-9a-f]{40}' if kind == 'commit' else r'sha256:[0-9a-f]{64}'
        if kind == 'example':
            if not example:
                f.error('example_subject', 'Example subject forbidden in managed project', identity, field)
        elif not re.fullmatch(pattern, val):
            f.error('subject_format', f'Invalid {kind} subject', identity, field)

    for identity, entity in all_entities.items():
        if not example:
            try:
                suffix = identity.split('-', 1)[1]
                parsed = UUID(suffix)
                if parsed.version != 4 or str(parsed) != suffix:
                    raise ValueError()
            except (ValueError, IndexError):
                f.error('id_format', 'Managed IDs require canonical UUIDv4', identity, 'id')
        metadata = entity.get('metadata')
        if metadata and parse_timestamp(metadata['updated_at']) < parse_timestamp(metadata['created_at']):
            f.error('time_order', 'updated_at precedes created_at', identity, 'metadata')
    for name, command in f.project['commands'].items():
        path(command['cwd'], f.project['id'], f'commands.{name}.cwd')
        if 'result' in command:
            path(command['result']['path'], f.project['id'], f'commands.{name}.result.path')
    for name, paths in f.project['components'].items():
        for value in paths:
            path(value, f.project['id'], f'components.{name}')
    for identity, source in f.sources.items():
        if 'path' in source['location']:
            path(source['location']['path'], identity, 'location.path')
    for identity, requirement in f.requirements.items():
        for source in requirement['sources']:
            if reference(source['source_ref'], f.sources, identity, 'sources'):
                if (requirement['status'] == 'confirmed'
                        and f.sources[source['source_ref']]['authority'] == 'inferred'
                        and 'confirmation' not in requirement):
                    f.error('confirmation_required', 'Inferred sources require explicit confirmation', identity, 'confirmation')
    check_maps = {}
    for identity, feature in f.features.items():
        if PurePosixPath(f.files[identity]).parent.name != feature['domain']:
            f.error('domain_mismatch', 'Feature domain must equal parent directory', identity, 'domain')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', feature['domain']):
            f.error('domain_format', 'Domain must be a single directory name', identity, 'domain')
        for value in feature['requirement_refs']:
            reference(value, f.requirements, identity, 'requirement_refs')
        for value in feature['depends_on']:
            reference(value, f.features, identity, 'depends_on')
        acceptance, checks = feature['acceptance'], feature['verification']['checks']
        unique(acceptance, identity, 'acceptance')
        unique(checks, identity, 'verification.checks')
        acs = {a['id']: a for a in acceptance}
        check_maps[identity] = {c['id']: c for c in checks}
        required = [a for a in acceptance if a['required']]
        if not required:
            f.error('required_ac_missing', 'At least one required AC is required', identity, 'acceptance')
        for ac in required:
            if not any(c['required'] and c['acceptance_ref'] == ac['id'] for c in checks):
                f.error('required_check_missing', f'No required Check for {ac["id"]}', identity, 'verification.checks')
        for index, check in enumerate(checks):
            reference(check['acceptance_ref'], acs, identity, f'verification.checks.{index}.acceptance_ref')
            if 'command_ref' in check:
                reference(check['command_ref'], f.project['commands'], identity, f'verification.checks.{index}.command_ref')
            for value in check['evidence_refs']:
                if reference(value, f.evidence, identity, f'verification.checks.{index}.evidence_refs'):
                    ev = f.evidence[value]
                    if ev['feature_ref'] != identity or ev.get('check_ref') != check['id']:
                        f.error('evidence_mismatch', 'Evidence must belong to this Feature/Check', identity, f'verification.checks.{index}')
        implementation = feature['implementation']
        subject(implementation['subject'], identity, 'implementation.subject')
        if implementation['state'] != 'not_started' and implementation['subject'] is None:
            f.error('subject_required', 'Started implementation requires a subject', identity, 'implementation.subject')
        for component, values in implementation['components'].items():
            reference(component, f.project['components'], identity, 'implementation.components')
            for value in values:
                path(value, identity, 'implementation.components')
        for value in implementation['evidence_refs']:
            if reference(value, f.evidence, identity, 'implementation.evidence_refs') and f.evidence[value]['feature_ref'] != identity:
                f.error('evidence_mismatch', 'Implementation evidence belongs to another Feature', identity, 'implementation.evidence_refs')
        compatible = {'commit': {'committed'}, 'mr': {'mr_open', 'merged'},
                      'release': {'released'}, 'deployment': {'deployed'}}
        for i, record in enumerate(feature['delivery']['records']):
            if record['state'] not in compatible[record['kind']]:
                f.error('delivery_kind_state', 'Incompatible delivery kind/state', identity, f'delivery.records.{i}')
            subject(record['subject'], identity, f'delivery.records.{i}.subject')
            for value in record['evidence_refs']:
                if reference(value, f.evidence, identity, f'delivery.records.{i}.evidence_refs'):
                    if f.evidence[value]['feature_ref'] != identity or f.evidence[value]['type'] != 'delivery':
                        f.error('evidence_mismatch', 'Delivery requires delivery Evidence for this Feature', identity, f'delivery.records.{i}')
    _cycles(f, f.features, lambda x: x['depends_on'], 'dependency_cycle', 'depends_on')
    for identity, ev in f.evidence.items():
        if reference(ev['feature_ref'], f.features, identity, 'feature_ref'):
            if 'check_ref' in ev:
                reference(ev['check_ref'], check_maps.get(ev['feature_ref'], {}), identity, 'check_ref')
        if reference(ev['produced_by']['run_ref'], f.runs, identity, 'produced_by.run_ref'):
            if ev['feature_ref'] not in f.runs[ev['produced_by']['run_ref']]['feature_refs']:
                f.error('run_feature_mismatch', 'Evidence Feature is outside producing Run', identity, 'produced_by')
        for value in ev['requirement_revisions']:
            reference(value, f.requirements, identity, 'requirement_revisions')
        subject(ev['subject'], identity, 'subject')
        if ev['command']:
            path(ev['command']['cwd'], identity, 'command.cwd')
        for artifact in ev['artifacts']:
            if 'path' in artifact:
                path(artifact['path'], identity, 'artifacts.path')
        if ev['result'] == 'passed':
            if ev.get('check_ref') and not ev.get('check_digest'):
                f.error('check_digest_required', 'Passed verification requires Check digest', identity, 'check_digest')
            if not ev['artifacts']:
                f.error('artifact_required', 'Passed Evidence requires inspectable artifacts', identity, 'artifacts')
            if (ev['type'] in {'manual_review', 'delivery'} and not ev.get('delivery_observation')
                    and not ev['produced_by'].get('reviewer')):
                f.error('reviewer_required', 'Manual/delivery Evidence requires reviewer', identity, 'produced_by.reviewer')
            if ev['type'] in {'test', 'ci_result'} and (not ev['command'] or ev['command']['exit_code'] != 0):
                f.error('command_result_required', 'Passed test requires actual exit_code=0', identity, 'command')
        if ('delivery_ref' in ev) != ('delivery_state' in ev):
            f.error('delivery_binding', 'delivery_ref and delivery_state must be supplied together', identity, 'delivery_ref')
        if ev.get('delivery_observation'):
            observation = ev['delivery_observation']
            if (ev['type'] != 'delivery' or ev.get('check_ref') or ev['command'] is not None
                    or ev['subject'] != {'kind': 'commit', 'value': observation['commit']}
                    or ev.get('delivery_ref') != observation['commit'] or ev.get('delivery_state') != 'committed'):
                f.error('delivery_observation', 'Git observation must bind the exact commit subject and committed state', identity, 'delivery_observation')
        for value in ev['supersedes']:
            if reference(value, f.evidence, identity, 'supersedes'):
                old = f.evidence[value]
                if old['feature_ref'] != ev['feature_ref'] or old.get('check_ref') != ev.get('check_ref'):
                    f.error('supersedes_mismatch', 'Supersedes must stay within Feature/Check', identity, 'supersedes')
    _cycles(f, f.evidence, lambda x: x['supersedes'], 'supersedes_cycle', 'supersedes')
    for identity, run in f.runs.items():
        for value in run['feature_refs']:
            reference(value, f.features, identity, 'feature_refs')
        if run['ended_at'] and parse_timestamp(run['ended_at']) < parse_timestamp(run['started_at']):
            f.error('time_order', 'Run ended before it started', identity, 'ended_at')
        for value in run['files_touched']:
            path(value, identity, 'files_touched')
        for claim in run['claims']:
            if claim['feature_ref'] not in run['feature_refs']:
                f.error('claim_feature_mismatch', 'Claim must belong to Run Feature', identity, 'claims')
            scope = claim['scope']
            if scope['type'] == 'feature' and scope['value'] != claim['feature_ref']:
                f.error('claim_feature_mismatch', 'Feature scope must equal Feature ref', identity, 'claims.scope')
            elif scope['type'] == 'component':
                reference(scope['value'], f.project['components'], identity, 'claims.scope')
            elif scope['type'] == 'path':
                path(scope['value'], identity, 'claims.scope', True)
        if run['status'] != 'active' and (run['work']['remaining'] or run['work']['blockers']) and not run['handoff_ref']:
            f.error('handoff_required', 'Remaining work/blockers require Handoff', identity, 'handoff_ref')
        if run['handoff_ref'] and reference(run['handoff_ref'], f.handoffs, identity, 'handoff_ref'):
            if f.handoffs[run['handoff_ref']]['run_ref'] != identity:
                f.error('handoff_mismatch', 'Handoff belongs to another Run', identity, 'handoff_ref')
    for identity, handoff in f.handoffs.items():
        if reference(handoff['run_ref'], f.runs, identity, 'run_ref'):
            run = f.runs[handoff['run_ref']]
            if not set(handoff['feature_refs']).issubset(run['feature_refs']):
                f.error('handoff_mismatch', 'Handoff Feature must belong to Run', identity, 'feature_refs')
            if run['status'] != 'active' and run['handoff_ref'] == identity:
                for key in ['completed', 'remaining', 'blockers']:
                    if handoff[key] != run['work'][key]:
                        f.error('handoff_work_mismatch', 'Terminal Run and Handoff must agree', identity, key)
        for value in handoff['evidence_refs']:
            if reference(value, f.evidence, identity, 'evidence_refs'):
                if f.evidence[value]['feature_ref'] not in handoff['feature_refs']:
                    f.error('evidence_mismatch', 'Handoff evidence outside its Features', identity, 'evidence_refs')
        for value in handoff['context_refs']:
            if value not in f.sources:
                path(value, identity, 'context_refs')


def _cycles(f: Facts, entities: dict, edges, code: str, field: str) -> None:
    # Iterative DFS avoids recursion-limit failures on a long but valid project.
    colors: dict[str, int] = {}
    for identity in entities:
        if colors.get(identity):
            continue
        stack = [(identity, iter(edges(entities[identity])))]
        colors[identity] = 1
        while stack:
            node, children = stack[-1]
            target = next(children, None)
            if target is None:
                colors[node] = 2
                stack.pop()
            elif target not in entities:
                continue  # A missing-reference diagnostic has already been emitted.
            elif colors.get(target) == 1:
                f.error(code, f'Cycle edge {node} -> {target}', node, field)
            elif not colors.get(target):
                colors[target] = 1
                stack.append((target, iter(edges(entities[target]))))
