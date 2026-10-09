"""Inspect and restore trusted V1 acceptance archives without executing their code."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import zipfile

from .operations import fail, valid
from .state import current_subject, derive, utc_now


MAX_FILES = 20000
MAX_TOTAL = 512 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MANIFEST = '.project/artifacts/relay/manifest.json'
BUNDLE = '.project/artifacts/relay/baseline.bundle'
BOOTSTRAP = '.project/artifacts/relay/bootstrap.py'
ROOT_FILES = {'README.md', 'AGENTS.md', 'pyproject.toml', 'uv.lock', '.gitignore', '.gitattributes', '.python-version'}
PREFIXES = {'src', 'schemas', 'docs', 'skills', 'evals', 'tests', 'examples', 'cli', '.github'}


def safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        fail(2, 'Unsafe archive path', 'unsafe_snapshot')
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or any(p in {'.', '..', '.git', '.venv'} for p in path.parts):
        fail(2, 'Unsafe archive path', 'unsafe_snapshot')
    if name not in ROOT_FILES and path.parts[0] not in PREFIXES:
        if len(path.parts) < 2 or path.parts[:2] not in {
                ('.project', part) for part in ('sources', 'requirements', 'features', 'runs', 'evidence',
                                              'handoffs', 'refs', 'decisions', 'artifacts')}:
            if name not in {'.project/project.yaml', '.project/README.md'}:
                fail(2, 'Unrecognized archive path', 'unsafe_snapshot')
    return name


def digest(stream):
    sha = hashlib.sha256()
    for chunk in iter(lambda: stream.read(65536), b''):
        sha.update(chunk)
    return sha.hexdigest()


def hex_digest(value, length=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(length) + '}', value)


@contextmanager
def checked_archive(file, expected):
    if not hex_digest(expected):
        fail(2, 'A trusted complete SHA-256 is required', 'argument_error')
    file = Path(file)
    if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_TOTAL:
        fail(2, 'Archive is missing, unsafe or too large', 'unsafe_snapshot')
    try:
        with file.open('rb') as stream:
            if digest(stream) != expected:
                fail(5, 'Archive SHA-256 differs from the trusted value', 'snapshot_checksum')
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                infos = archive.infolist()
                names = [i.filename for i in infos]
                if (len(infos) > MAX_FILES or len(set(names)) != len(names)
                        or sum(i.file_size for i in infos) > MAX_TOTAL):
                    fail(2, 'Duplicate paths or archive resource limit exceeded', 'unsafe_snapshot')
                for item in infos:
                    safe_name(item.filename)
                    mode = item.external_attr >> 16
                    if item.is_dir() or item.file_size > MAX_FILE or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                        fail(2, 'Only bounded regular files are allowed', 'unsafe_snapshot')
                if MANIFEST not in names or archive.getinfo(MANIFEST).file_size > 8 * 1024 * 1024:
                    fail(2, 'Snapshot manifest is missing or too large', 'invalid_snapshot')
                # Strict YAML/JSON parsing rejects duplicate keys and custom tags.
                from .facts import load_yaml
                manifest = load_yaml(archive.read(MANIFEST).decode('utf-8'))
                if (not isinstance(manifest, dict) or type(manifest.get('version')) is not int or manifest['version'] != 1
                        or manifest.get('kind') != 'local_agent_handoff'
                        or not hex_digest(manifest.get('head'), 40)
                        or not hex_digest(manifest.get('bundle_sha256'))
                        or not isinstance(manifest.get('files'), dict)):
                    fail(2, 'Unsupported or invalid snapshot manifest', 'invalid_snapshot')
                files = manifest['files']
                if set(names) != set(files) | {MANIFEST, BUNDLE, BOOTSTRAP} or set(files) & {MANIFEST, BUNDLE, BOOTSTRAP}:
                    fail(2, 'Archive files differ from the manifest', 'invalid_snapshot')
                for name, item in files.items():
                    safe_name(name)
                    if (not isinstance(item, dict) or not hex_digest(item.get('sha256'))
                            or type(item.get('mode')) is not int or not 0 <= item['mode'] <= 0o777):
                        fail(2, 'Invalid file checksum or mode', 'invalid_snapshot')
                deleted = manifest.get('deleted_source_paths')
                if not isinstance(deleted, list) or len(deleted) != len(set(deleted)):
                    fail(2, 'Invalid deleted source list', 'invalid_snapshot')
                for name in deleted:
                    safe_name(name)
                    if name in files or name in {MANIFEST, BUNDLE, BOOTSTRAP} or name.startswith('.project/'):
                        fail(2, 'Deleted path collides with snapshot data', 'invalid_snapshot')
                subject = manifest.get('subject')
                if (not isinstance(subject, dict) or set(subject) != {'kind', 'value'}
                        or subject['kind'] not in {'commit', 'working_tree'}
                        or not isinstance(subject['value'], str)):
                    fail(2, 'Invalid snapshot subject', 'invalid_snapshot')
                if subject['kind'] == 'commit' and subject['value'] != manifest['head']:
                    fail(2, 'Commit subject and baseline HEAD differ', 'invalid_snapshot')
                for name, expected_hash in [*( (n, i['sha256']) for n, i in files.items()),
                                            (BUNDLE, manifest['bundle_sha256'])]:
                    with archive.open(name) as content:
                        if digest(content) != expected_hash:
                            fail(5, 'Snapshot file checksum differs', 'snapshot_checksum')
                yield archive, manifest
    except (zipfile.BadZipFile, UnicodeError, RuntimeError) as exc:
        fail(2, 'Invalid snapshot archive: ' + str(exc), 'invalid_snapshot')


def summary(manifest, expected):
    return {'archive_sha256': expected, 'manifest_version': 1, 'head': manifest['head'],
            'subject': manifest['subject'], 'target_feature': manifest.get('target_feature'),
            'files': len(manifest['files']), 'scripts_executed': False,
            'state': 'Archive checked; derived Feature state is available after restoration'}


def inspect(file, expected):
    with checked_archive(file, expected) as (_, manifest):
        return summary(manifest, expected)


def restore(file, expected, destination, *, dry_run=False):
    requested = Path(destination).absolute()
    dest = requested.parent.resolve() / requested.name
    if requested.is_symlink() or dest.exists() or dest.is_symlink():
        fail(3, 'Use a new destination; existing directories are never overwritten', 'destination_exists')
    with checked_archive(file, expected) as (archive, manifest):
        report = {**summary(manifest, expected), 'destination': str(dest), 'dry_run': dry_run}
        if dry_run:
            return report
        if not dest.parent.is_dir():
            fail(2, 'Destination parent must already exist', 'argument_error')
        with tempfile.TemporaryDirectory(prefix='.apm-restore-', dir=dest.parent) as temporary:
            stage = Path(temporary) / 'project'
            stage.mkdir()
            for name in archive.namelist():
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open('xb') as output:
                    for chunk in iter(lambda: source.read(65536), b''):
                        output.write(chunk)
                item = manifest['files'].get(name)
                if item:
                    with target.open('rb') as content:
                        if digest(content) != item['sha256']:
                            fail(5, 'Archive changed during extraction', 'snapshot_checksum')
                    target.chmod(item['mode'])
            with (stage / BUNDLE).open('rb') as content:
                if digest(content) != manifest['bundle_sha256']:
                    fail(5, 'Bundle changed during extraction', 'snapshot_checksum')
            def git(*args):
                process = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'init.templateDir=',
                                          '-C', str(stage), *args], capture_output=True, timeout=60)
                if process.returncode:
                    fail(5, 'Git baseline restoration failed', 'snapshot_git')
                return process.stdout.decode().strip()
            git('init', '--quiet', '--initial-branch=acceptance-unborn')
            git('fetch', '--quiet', str(stage / BUNDLE), 'HEAD:refs/heads/acceptance-baseline')
            git('symbolic-ref', 'HEAD', 'refs/heads/acceptance-baseline')
            git('reset', '--mixed', manifest['head'])
            if git('rev-parse', 'HEAD') != manifest['head'] or current_subject(stage) != manifest['subject']:
                fail(5, 'Restored code subject differs from the snapshot', 'snapshot_subject')
            f = valid(stage)
            if manifest.get('target_feature') not in f.features:
                fail(2, 'Target Feature is absent', 'invalid_snapshot')
            from .state import conflicts
            if any(not c['overridden'] for c in conflicts(f)):
                fail(3, 'Restored facts contain unresolved Claim conflicts', 'claim_conflict')
            state = derive(f, utc_now())
            # Exclusively reserve the final name, then atomically install the validated tree.
            try:
                dest.mkdir()
            except FileExistsError:
                fail(3, 'Destination appeared during restoration', 'destination_exists')
            reserved = dest.stat()
            try:
                os.rename(stage, dest)
            except Exception:
                if dest.exists() and dest.stat().st_ino == reserved.st_ino and not any(dest.iterdir()):
                    dest.rmdir()
                raise
            return {**report, 'restored': True, 'summary': state['summary'],
                    'features': state['features'], 'state': 'Restored; current state derived from saved facts'}
