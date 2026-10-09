"""Local project write locking and durable, idempotent roll-forward transactions."""

from __future__ import annotations

from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from uuid import UUID, uuid4

from filelock import FileLock

from .facts import read_yaml, safe_path, validate_project


class PendingTransaction(Exception):
    pass


class RevisionConflict(Exception):
    pass


def pending_transactions(root: Path) -> list[Path]:
    directory = safe_path(root, '.project/transactions')
    if directory != root.resolve() / '.project/transactions':
        raise ValueError('Transaction directory cannot be a symlink')
    return sorted(directory.glob('*.json'))


@contextmanager
def project_lock(root: Path, *, recovering: bool = False):
    path = safe_path(root, '.project/.write.lock')
    if path != root.resolve() / '.project/.write.lock':
        raise ValueError('Write lock cannot be a symlink')
    with FileLock(str(path), timeout=10):
        if not recovering and pending_transactions(root):
            raise PendingTransaction('Unfinished transaction; run doctor --recover before new writes')
        yield


def _sync_directory(path: Path) -> None:
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _replace(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.apm-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(text.encode('utf-8') if isinstance(text, str) else text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _checksum(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _target(root: Path, name: str) -> Path:
    path = safe_path(root, name)
    if path != root.resolve() / name:
        raise ValueError('Transaction targets cannot be symlinks')
    parts = PurePosixPath(name).parts
    artifact = False
    if len(parts) == 4 and parts[:2] == ('.project', 'artifacts'):
        try:
            parsed = UUID(parts[2])
            artifact = parsed.version == 4 and str(parsed) == parts[2]
        except ValueError:
            pass
    allowed = (name in {'.project/project.yaml', '.project/sources/registry.yaml'}
               or (len(parts) >= 3 and parts[0] == '.project'
                   and parts[1] in {'requirements', 'features', 'runs', 'evidence', 'handoffs'}
                   and path.suffix in {'.yaml', '.yml', '.json'})
               or (name in {f'.project/generated/{kind}.json' for kind in ['status', 'features', 'claims', 'graph']})
               or artifact)
    if not allowed:
        raise ValueError(f'Transaction target is not a fact/generated file: {name}')
    return path


def commit_files(root: Path, writes: dict[str, str | bytes]) -> None:
    """Caller must hold project_lock and have validated the complete candidate facts."""
    if not writes:
        return
    identity = str(uuid4())
    directory = safe_path(root, '.project/transactions')
    directory.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, text in writes.items():
        target = _target(root, name)
        raw = text.encode('utf-8') if isinstance(text, str) else text
        entries.append({'path': name, 'before': _checksum(target),
                        'after': hashlib.sha256(raw).hexdigest(),
                        'encoding': 'utf8' if isinstance(text, str) else 'base64',
                        'content': text if isinstance(text, str) else base64.b64encode(text).decode('ascii')})
    journal = directory / (identity + '.json')
    _replace(journal, json.dumps({'version': 1, 'id': identity, 'entries': entries}, ensure_ascii=False, indent=2))
    for entry in entries:
        _replace(_target(root, entry['path']), _payload(entry))
    journal.unlink()
    _sync_directory(directory)


def _payload(entry: dict) -> bytes:
    if entry.get('encoding', 'utf8') == 'utf8':
        return entry['content'].encode('utf-8')
    if entry['encoding'] == 'base64':
        return base64.b64decode(entry['content'], validate=True)
    raise ValueError('Unknown transaction content encoding')


def recover(root: Path) -> list[str]:
    recovered = []
    with project_lock(root, recovering=True):
        for journal in pending_transactions(root):
            safe_path(root, journal.relative_to(root).as_posix())
            data = json.loads(journal.read_text(encoding='utf-8'))
            if data.get('version') != 1 or data.get('id') != journal.stem or not isinstance(data.get('entries'), list):
                raise ValueError('Invalid transaction journal')
            seen = set()
            overrides = {}
            for entry in data['entries']:
                target = _target(root, entry['path'])
                if entry['path'] in seen:
                    raise ValueError('Duplicate transaction target')
                seen.add(entry['path'])
                if hashlib.sha256(_payload(entry)).hexdigest() != entry['after']:
                    raise ValueError('Transaction content checksum mismatch')
                if _checksum(target) not in {entry['before'], entry['after']}:
                    raise RevisionConflict('A transaction target was changed outside this transaction')
                if not entry['path'].startswith(('.project/generated/', '.project/artifacts/')):
                    # New facts are JSON-as-YAML emitted by the writer. Recovery
                    # validates their final cross-document state before replay.
                    overrides[entry['path']] = json.loads(_payload(entry))
            facts = validate_project(root, overrides)
            if facts.errors:
                raise ValueError('Recovered candidate facts are invalid: ' + facts.errors[0].message)
            for entry in data['entries']:
                target = _target(root, entry['path'])
                if _checksum(target) != entry['after']:
                    _replace(target, _payload(entry))
            journal.unlink()
            _sync_directory(journal.parent)
            recovered.append(data['id'])
    return recovered


def require_revision(entity: dict, expected: int) -> None:
    if entity['revision'] != expected:
        raise RevisionConflict(f'Expected revision {expected}; actual revision {entity["revision"]}')
