"""CLI protocol: one JSON object on stdout, explicit exit codes, no implicit tests."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from filelock import Timeout
from ruamel.yaml.error import YAMLError

from . import __version__
from .facts import Issue, ProjectNotFound, find_project, parse_timestamp, read_yaml
from .operations import OperationError, fail, finish_run, init_project, rebuild, start_run, update_run, valid
from .state import active_claims, claims_overlap, conflicts, derive, utc_now
from .storage import PendingTransaction, RevisionConflict, pending_transactions, recover
from .verification import assessment, execute_checks, import_evidence
from .delivery import link_commit, link_mr
from .sources import add_source, apply_proposal, propose_decomposition, propose_source, registry_view
from .fact_writes import propose as propose_fact, apply as apply_fact


class Parser(argparse.ArgumentParser):
    def error(self, message):
        fail(2, message, 'argument_error')


def make_parser() -> Parser:
    parser = Parser(prog='apm', description='APM V1 project facts and handoffs',
                    epilog='Common options (anywhere): --project PATH --json --at RFC3339 --dry-run')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    doctor = commands.add_parser('doctor', help='Validate facts and diagnose pending transactions/conflicts')
    doctor.add_argument('--recover', action='store_true')
    commands.add_parser('status', help='Derive current state without executing tests')
    commands.add_parser('rebuild', help='Rebuild generated views without changing facts')
    snapshots = commands.add_parser('snapshot').add_subparsers(dest='action', required=True)
    for action in ['inspect', 'restore']:
        command = snapshots.add_parser(action)
        command.add_argument('file')
        command.add_argument('--sha256', required=True)
        if action == 'restore':
            command.add_argument('--destination', required=True)
    project = commands.add_parser('project').add_subparsers(dest='action', required=True)
    initialize = project.add_parser('init')
    initialize.add_argument('--name', required=True)
    sources = commands.add_parser('source').add_subparsers(dest='action', required=True)
    sources.add_parser('list')
    sources.add_parser('show').add_argument('id')
    addition = sources.add_parser('add')
    addition.add_argument('--file', required=True)
    addition.add_argument('--expected-digest', required=True)
    addition.add_argument('--run-id', required=True)
    sync = sources.add_parser('sync')
    sync.add_argument('id')
    choice = sync.add_mutually_exclusive_group()
    choice.add_argument('--file')
    choice.add_argument('--apply')
    requirements = commands.add_parser('requirement').add_subparsers(dest='action', required=True)
    requirements.add_parser('list')
    requirements.add_parser('show').add_argument('id')
    for family, subcommands in [('requirement', requirements)]:
        for action in ['create', 'update', 'confirm']:
            command = subcommands.add_parser(action)
            if action != 'create':
                command.add_argument('id')
                command.add_argument('--expected-revision', type=int, required=True)
            mode = command.add_mutually_exclusive_group(required=action != 'confirm')
            if action != 'confirm':
                mode.add_argument('--file')
            mode.add_argument('--apply')
            for flag in ['run-id', 'reviewer', 'note']:
                command.add_argument('--' + flag)
    decompose = requirements.add_parser('decompose')
    decompose.add_argument('id')
    plan = decompose.add_mutually_exclusive_group(required=True)
    plan.add_argument('--file')
    plan.add_argument('--apply')
    for proposed in [sync, decompose]:
        proposed.add_argument('--run-id')
        proposed.add_argument('--reviewer')
        proposed.add_argument('--note')
    feature = commands.add_parser('feature').add_subparsers(dest='action', required=True)
    listing = feature.add_parser('list')
    listing.add_argument('--state', choices=['draft', 'ready', 'developing', 'verifying', 'verified', 'delivered', 'deployed', 'blocked'])
    listing.add_argument('--domain')
    listing.add_argument('--ready', action='store_true')
    feature.add_parser('show').add_argument('id')
    feature.add_parser('validate').add_argument('id')
    for action in ['create', 'update']:
        command = feature.add_parser(action)
        if action == 'update':
            command.add_argument('id')
            command.add_argument('--expected-revision', type=int, required=True)
        mode = command.add_mutually_exclusive_group(required=True)
        mode.add_argument('--file')
        mode.add_argument('--apply')
        for flag in ['run-id', 'reviewer', 'note']:
            command.add_argument('--' + flag)
    for action in ['link-commit', 'link-mr']:
        link = feature.add_parser(action)
        link.add_argument('id')
        link.add_argument('--run-id', required=True)
        link.add_argument('--expected-revision', type=int, required=True)
        if action == 'link-commit':
            link.add_argument('ref')
        else:
            link.add_argument('--file', required=True)
    verify = commands.add_parser('verify', help='Assess, execute or import named Check evidence')
    verify.add_argument('feature')
    mode = verify.add_mutually_exclusive_group()
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--record')
    mode.add_argument('--ci-run')
    verify.add_argument('--ci-artifact')
    verify.add_argument('--apply-ci', action='store_true')
    verify.add_argument('--reviewer')
    verify.add_argument('--note')
    verify.add_argument('--run-id')
    verify.add_argument('--expected-revision', type=int)
    verify.add_argument('--check', action='append')
    runs = commands.add_parser('run').add_subparsers(dest='action', required=True)
    start = runs.add_parser('start')
    start.add_argument('feature')
    start.add_argument('--agent', required=True)
    start.add_argument('--instance', required=True)
    start.add_argument('--scope', required=True)
    start.add_argument('--override-conflict', action='store_true')
    start.add_argument('--reason')
    show = runs.add_parser('show')
    show.add_argument('id')
    show.add_argument('--instance')
    update = runs.add_parser('update')
    update.add_argument('id')
    update.add_argument('--expected-revision', type=int, required=True)
    update.add_argument('--file', required=True)
    for action in ['finish', 'abort']:
        finish = runs.add_parser(action)
        finish.add_argument('id')
        finish.add_argument('--expected-revision', type=int, required=True)
        finish.add_argument('--handoff-file')
        if action == 'abort':
            finish.add_argument('--reason', required=True)
    return parser


def _evaluate_time(value: str | None) -> str:
    result = value or utc_now()
    try:
        moment = parse_timestamp(result)
        if moment.tzinfo is None:
            raise ValueError()
    except ValueError:
        fail(2, '--at must be an RFC3339 timestamp with timezone', 'invalid_time')
    return result


def dispatch(args, options) -> tuple[dict, list[Issue], int]:
    if args.command == 'snapshot':
        from .snapshots import inspect, restore
        if options.at or options.project:
            fail(2, 'Snapshot operations do not accept --at/--project', 'argument_error')
        if args.action == 'inspect':
            return inspect(args.file, args.sha256), [], 0
        return restore(args.file, args.sha256, args.destination, dry_run=options.dry_run), [], 0
    if args.command == 'project':
        return init_project(Path(options.project or Path.cwd()), args.name, dry_run=options.dry_run), [], 0
    root = find_project(options.project)
    recovered = []
    if args.command == 'doctor' and args.recover:
        if options.dry_run:
            fail(2, 'doctor --recover does not accept --dry-run', 'argument_error')
        recovered = recover(root)
    if args.command == 'doctor':
        from .facts import validate_project
        f = validate_project(root)
        if f.errors:
            raise OperationError(2, f.errors)
    else:
        f = valid(root)
    journals = pending_transactions(root)
    if journals and args.command != 'doctor':
        fail(5, 'Unfinished transaction; read state after doctor --recover', 'pending_transaction')
    if args.command == 'doctor':
        collisions = conflicts(f)
        unhandled = [c for c in collisions if not c['overridden']]
        issues = list(f.warnings)
        issues.extend(Issue('claim_override', 'Overlapping Claim explicitly overridden') for c in collisions if c['overridden'])
        problems = [Issue('claim_conflict', 'Overlapping active Claims', entity_ref=c['left']['run_ref']) for c in unhandled]
        problems.extend(Issue('pending_transaction', 'Unfinished transaction', file=str(j.relative_to(root))) for j in journals)
        if problems:
            raise OperationError(3 if unhandled else 5, problems)
        return {'project_id': f.project['id'], 'example': f.project['mode'] == 'example',
                'counts': {name: len(getattr(f, name)) for name in ['sources', 'requirements', 'features', 'runs', 'evidence', 'handoffs']},
                'recovered_transactions': recovered}, issues, 0
    evaluated_at = _evaluate_time(options.at)
    if args.command in {'requirement', 'feature'} and args.action in {'create', 'update', 'confirm'}:
        if options.at:
            fail(2, '--at is not supported for fact writes', 'argument_error')
        target, expected = getattr(args, 'id', None), getattr(args, 'expected_revision', None)
        if args.apply:
            if not args.run_id or not args.reviewer or not args.note:
                fail(2, 'Apply requires --run-id --reviewer --note', 'argument_error')
            return apply_fact(root, args.command, args.action, read_yaml(Path(args.apply)),
                              args.run_id, args.reviewer, args.note, target=target, expected=expected,
                              dry_run=options.dry_run), [], 0
        if args.run_id or args.reviewer or args.note:
            fail(2, 'Review options apply only with --apply', 'argument_error')
        incoming = {} if args.action == 'confirm' else read_yaml(Path(args.file))
        return propose_fact(root, args.command, args.action, incoming, target, expected), [], 0
    if args.command in {'source', 'requirement'}:
        if args.action == 'list':
            return (registry_view(root) if args.command == 'source' else {'requirements': list(f.requirements.values())}), [], 0
        if args.action == 'show':
            if args.command == 'source':
                return registry_view(root, args.id), [], 0
            if args.id not in f.requirements:
                fail(4, 'Requirement does not exist', 'not_found', args.id)
            return {'facts': f.requirements[args.id], 'feature_refs': sorted(identity for identity, feature in f.features.items() if args.id in feature['requirement_refs'])}, [], 0
        if options.at:
            fail(2, '--at is not supported for source or proposal operations', 'argument_error')
        if args.action == 'add':
            return add_source(root, read_yaml(Path(args.file)), args.expected_digest, args.run_id, dry_run=options.dry_run), [], 0
        kind = 'source_sync' if args.command == 'source' else 'decompose'
        if args.apply:
            if not args.run_id or not args.reviewer or not args.note:
                fail(2, 'Applying a proposal requires --run-id --reviewer --note', 'argument_error')
            return apply_proposal(root, read_yaml(Path(args.apply)), args.run_id, args.reviewer, args.note,
                                  kind=kind, target=args.id, dry_run=options.dry_run), [], 0
        if args.run_id or args.reviewer or args.note:
            fail(2, 'Review options apply only with --apply', 'argument_error')
        proposal = propose_source(root, args.id, args.file) if kind == 'source_sync' else propose_decomposition(root, args.id, args.file)
        return {'proposal': proposal, 'dry_run': options.dry_run}, [], 0
    if args.command == 'verify':
        if (args.ci_artifact or args.apply_ci or args.reviewer or args.note) and not args.ci_run:
            fail(2, 'CI options require --ci-run', 'argument_error')
        if args.run or args.record or args.ci_run:
            if not args.run_id or args.expected_revision is None:
                fail(2, 'Verification writes require --run-id and --expected-revision', 'argument_error')
            if options.at:
                fail(2, '--at applies only to read-only verification', 'argument_error')
            if args.ci_run:
                from .ci_evidence import import_ci
                result = import_ci(root, args.feature, args.run_id, args.expected_revision, args.ci_run,
                                   args.ci_artifact, args.check, args.reviewer, args.note,
                                   apply=args.apply_ci, dry_run=options.dry_run)
            elif args.record:
                if args.check:
                    fail(2, '--record binds Checks through the complete Evidence input', 'argument_error')
                result = import_evidence(root, args.feature, args.run_id, args.expected_revision,
                                         read_yaml(Path(args.record)), dry_run=options.dry_run)
            else:
                result = execute_checks(root, args.feature, args.run_id, args.expected_revision,
                                        args.check, dry_run=options.dry_run)
        else:
            if args.run_id or args.expected_revision is not None or args.check or options.dry_run:
                fail(2, 'Read-only verify accepts only Feature and evaluation time', 'argument_error')
            result = assessment(f, args.feature, evaluated_at)
        return result, [], 0 if result['required_passed'] and not result.get('dry_run') else 5
    if args.command == 'feature' and args.action in {'link-commit', 'link-mr'}:
        if args.action == 'link-commit':
            result = link_commit(root, args.id, args.ref, args.run_id, args.expected_revision, dry_run=options.dry_run)
        else:
            result = link_mr(root, args.id, read_yaml(Path(args.file)), args.run_id, args.expected_revision, dry_run=options.dry_run)
        return result, [], 0
    if args.command == 'run':
        if args.action == 'start':
            if bool(args.override_conflict) != bool(args.reason):
                fail(2, '--override-conflict and nonempty --reason must be supplied together', 'argument_error')
            result = start_run(root, args.feature, args.agent, args.instance, args.scope,
                               override_reason=args.reason, dry_run=options.dry_run)
            return result, [], 0
        identity = args.id
        if args.action == 'show' and identity == 'current':
            if not args.instance:
                fail(2, 'run show current requires --instance', 'instance_required')
            candidates = [r['id'] for r in f.runs.values() if r['status'] == 'active' and r['agent']['instance_id'] == args.instance]
            if not candidates:
                fail(4, 'No active Run for this instance', 'not_found')
            if len(candidates) > 1:
                fail(3, 'More than one active Run; supply an explicit Run ID', 'ambiguous_run')
            identity = candidates[0]
        if identity not in f.runs:
            fail(4, f'Unknown Run {identity}', 'not_found', identity)
        if args.action == 'show':
            return f.runs[identity], [], 0
        if args.expected_revision < 1:
            fail(2, 'Expected revision must be positive', 'argument_error')
        if args.action == 'update':
            return update_run(root, identity, args.expected_revision, read_yaml(Path(args.file)), dry_run=options.dry_run), [], 0
        handoff = read_yaml(Path(args.handoff_file)) if args.handoff_file else None
        reason = args.reason if args.action == 'abort' else None
        if args.action == 'abort' and (not reason or not reason.strip()):
            fail(2, 'Abort requires a nonempty reason', 'argument_error')
        return finish_run(root, identity, args.expected_revision, handoff=handoff,
                          abort_reason=reason, dry_run=options.dry_run), [], 0
    if args.command == 'rebuild':
        return rebuild(root, evaluated_at, dry_run=options.dry_run), [], 0
    if args.command == 'feature' and args.action == 'validate':
        if args.id not in f.features:
            fail(4, f'Unknown Feature {args.id}', 'not_found', args.id)
        return {'id': args.id, 'valid': True}, [], 0
    state = derive(f, evaluated_at)
    state['claims'] = active_claims(f)
    state['conflicts'] = conflicts(f)
    if args.command == 'status':
        return state, [], 0
    if args.action == 'list':
        features = state['features']
        if args.state:
            features = [s for s in features if s['lifecycle'] == args.state]
        if args.domain:
            features = [s for s in features if s['domain'] == args.domain]
        if args.ready:
            features = [s for s in features if s['lifecycle'] == 'ready'
                        and not any(claims_overlap(f, {'feature_ref': s['id'], 'scope': {'type': 'feature', 'value': s['id']}}, c)
                                    for c in state['claims'])]
        return {'features': features, 'example': state['example'], 'evaluated_at': evaluated_at}, [], 0
    if args.id not in f.features:
        fail(4, f'Unknown Feature {args.id}', 'not_found', args.id)
    result = next(s for s in state['features'] if s['id'] == args.id)
    result['facts'] = f.features[args.id]
    result['requirements'] = [f.requirements[ref] for ref in result['requirement_refs']]
    result['handoff'] = f.handoffs.get(result['latest_handoff'])
    result['claims'] = [c for c in state['claims'] if claims_overlap(f, {'feature_ref': args.id, 'scope': {'type': 'feature', 'value': args.id}}, c)]
    return result, [], 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = '--json' in argv
    command = 'arguments'
    data, warnings, errors, code = None, [], [], 0
    try:
        # Parse shared flags separately so they work before or after subcommands.
        common = Parser(add_help=False, allow_abbrev=False)
        common.add_argument('--project')
        common.add_argument('--json', action='store_true')
        common.add_argument('--at')
        common.add_argument('--dry-run', action='store_true')
        options, remaining = common.parse_known_args(argv)
        args = make_parser().parse_args(remaining)
        command = args.command + ('.' + args.action if hasattr(args, 'action') else '')
        data, warnings, code = dispatch(args, options)
        if code == 5:
            errors = [Issue('verification_not_passed', 'Required verification has not passed (or dry-run was requested)')]
    except OperationError as exc:
        errors, code = exc.issues, exc.code
    except ProjectNotFound as exc:
        errors, code = [Issue('not_found', f'Project not found: {exc}')], 4
    except (RevisionConflict, Timeout) as exc:
        errors, code = [Issue('write_conflict', str(exc))], 3
    except PendingTransaction as exc:
        errors, code = [Issue('pending_transaction', str(exc))], 5
    except (ValueError, KeyError, TypeError, YAMLError) as exc:
        errors, code = [Issue('invalid_input', str(exc))], 2
    except Exception as exc:
        errors, code = [Issue('io_error', str(exc))], 1
    result = {'protocol_version': 1, 'ok': code == 0, 'command': command, 'data': data,
              'warnings': [w.as_dict() for w in warnings], 'errors': [e.as_dict() for e in errors]}
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    elif errors:
        if data is not None:
            print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
        for error in errors:
            location = ':'.join(p for p in [error.file, error.field] if p)
            print(f'{error.code}: {location + ": " if location else ""}{error.message}', file=sys.stderr)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
