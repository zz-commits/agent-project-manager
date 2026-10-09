"""Validate a release candidate; publish only after an explicit manual dispatch."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import tomllib
import xml.etree.ElementTree as ET
import zipfile

from apm.state import current_subject

REPOSITORY = 'zz-commits/agent-project-manager'


def run(argv, *, cwd=None, raw=False):
    result = subprocess.run([str(a) for a in argv], cwd=cwd, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace').strip() or 'Command failed')
    return result.stdout if raw else result.stdout.decode().strip()


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version_and_target(root, tag, target):
    version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
    tag = tag or 'v' + version
    if not re.fullmatch(r'v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)', tag):
        raise ValueError('Use a stable vMAJOR.MINOR.PATCH tag')
    if tag != 'v' + version:
        raise ValueError('Tag must match pyproject.toml version')
    if not re.fullmatch(r'[0-9a-f]{40}', target):
        raise ValueError('Use a complete commit SHA')
    if current_subject(root) != {'kind': 'commit', 'value': target}:
        raise ValueError('Actual clean source subject must match the target commit')
    return version, tag


def junit_summary(path):
    raw = path.read_bytes()
    if len(raw) > 16 * 1024 * 1024 or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise ValueError('Unsupported test report')
    cases = list(ET.fromstring(raw).iter('testcase'))
    if not cases or any(list(c.iter(k)) for c in cases for k in ('failure', 'error', 'skipped')):
        raise ValueError('Release requires nonempty tests with no failures, errors or skips')
    return {'passed': len(cases), 'failed': 0, 'errors': 0, 'skipped': 0, 'report_sha256': sha256(path)}


def package_assets(folder, version):
    names = [f'agent_project_manager-{version}-py3-none-any.whl', f'agent_project_manager-{version}.tar.gz']
    files = [folder / n for n in names]
    if any(not p.is_file() or p.is_symlink() for p in files):
        raise ValueError('Expected wheel and source archive are missing or unsafe')
    if {p.name for p in folder.glob('*.whl')} != {names[0]} or {p.name for p in folder.glob('*.tar.gz')} != {names[1]}:
        raise ValueError('Unexpected package files')
    with zipfile.ZipFile(files[0]) as archive:
        paths = archive.namelist()
        metadata = [p for p in paths if p.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise ValueError('Wheel metadata is missing or ambiguous')
        if any(not (p.startswith('apm/') or p.startswith(f'agent_project_manager-{version}.dist-info/'))
               or '..' in PurePosixPath(p).parts or p.startswith('/') for p in paths):
            raise ValueError('Unexpected wheel contents')
        if BytesParser().parsebytes(archive.read(metadata[0]))['Version'] != version:
            raise ValueError('Wheel version mismatch')
        if len([p for p in paths if p.startswith('apm/schemas/v1/') and p.endswith('.json')]) != 9:
            raise ValueError('Wheel schemas are incomplete')
    with tarfile.open(files[1]) as archive:
        members = archive.getmembers()
        prefix = 'agent_project_manager-' + version + '/'
        for item in members:
            parts = PurePosixPath(item.name).parts
            relative = item.name.removeprefix(prefix)
            if (not item.name.startswith(prefix) or '..' in parts or item.issym() or item.islnk()
                    or relative.startswith('.project/') or 'transcript-session' in relative or 'deepseek-result.zip' in relative):
                raise ValueError('Unsafe or private source archive contents')
        metadata = archive.extractfile(prefix + 'PKG-INFO')
        if metadata is None or BytesParser().parsebytes(metadata.read())['Version'] != version:
            raise ValueError('Source archive version mismatch')
    sums = ''.join(sha256(p) + '  ' + p.name + '\n' for p in files)
    checksum = folder / 'SHA256SUMS'
    if checksum.is_symlink():
        raise ValueError('Checksum file cannot be a symlink')
    if checksum.exists() and checksum.read_text() != sums:
        raise ValueError('Existing checksum file does not match candidate bytes')
    checksum.write_text(sums)
    return [{'name': p.name, 'sha256': sha256(p), 'bytes': p.stat().st_size} for p in [*files, checksum]]


def smoke(root, assets, version):
    """Install the wheel with frozen runtime dependencies outside the source checkout."""
    with tempfile.TemporaryDirectory(prefix='apm-release-smoke-') as directory:
        temp = Path(directory)
        reqs = temp / 'runtime.txt'
        run(['uv', 'export', '--frozen', '--no-dev', '--no-emit-project', '--format', 'requirements-txt', '--output-file', reqs, '--quiet'], cwd=root)
        run(['uv', 'venv', '--python', '3.12', temp / 'venv'], cwd=root)
        python = temp / 'venv/bin/python'
        apm = temp / 'venv/bin/apm'
        run(['uv', 'pip', 'install', '--python', python, '--require-hashes', '-r', reqs])
        run(['uv', 'pip', 'install', '--python', python, '--no-deps', assets / f'agent_project_manager-{version}-py3-none-any.whl'])
        if run([apm, '--version'], cwd=temp) != version:
            raise ValueError('Installed CLI version differs from package version')
        imported = json.loads(run([python, '-c', 'import apm,json; print(json.dumps(apm.__file__))'], cwd=temp))
        if '/site-packages/apm/' not in imported:
            raise ValueError('Smoke check imported source instead of the wheel')
        project = temp / 'project'
        run([apm, 'project', 'init', '--name', 'release-smoke', '--project', project, '--json'], cwd=temp)
        for verb in ('doctor', 'status'):
            if not json.loads(run([apm, '--project', project, verb, '--json'], cwd=temp))['ok']:
                raise ValueError('Installed CLI project check failed')
        run(['uv', 'build', '--wheel', assets / f'agent_project_manager-{version}.tar.gz', '--out-dir', temp / 'rebuilt'])


class GitHub:
    def api(self, path, payload=None, *, missing=False):
        argv = ['gh', 'api', f'repos/{REPOSITORY}/{path}']
        with tempfile.TemporaryDirectory(prefix='apm-release-api-') as directory:
            if payload is not None:
                file = Path(directory) / 'payload.json'
                file.write_text(json.dumps(payload))
                argv += ['--method', 'PATCH', '--input', str(file)]
            result = subprocess.run(argv, capture_output=True)
        if result.returncode:
            if missing and b'HTTP 404' in result.stderr:
                return None
            raise RuntimeError(result.stderr.decode(errors='replace').strip())
        return json.loads(result.stdout)

    def snapshot(self, tag):
        main = self.api('git/ref/heads/main')['object']['sha']
        ref = self.api('git/ref/tags/' + tag, missing=True)
        obj = ref['object'] if ref else None
        for _ in range(5):
            if obj is None or obj['type'] == 'commit':
                break
            if obj['type'] != 'tag':
                raise ValueError('Tag does not resolve to a commit')
            obj = self.api('git/tags/' + obj['sha'])['object']
        else:
            raise ValueError('Tag nesting exceeds supported depth')
        candidates = self.api('releases?per_page=100')
        release = next((r for r in candidates if r['tag_name'] == tag), None)
        if release is None:
            release = self.api('releases/tags/' + tag, missing=True)
        return {'main_sha': main, 'tag_commit': obj['sha'] if obj else None, 'release': release}

    def create(self, tag, target, notes):
        with tempfile.TemporaryDirectory(prefix='apm-release-notes-') as directory:
            file = Path(directory) / 'notes.md'; file.write_text(notes)
            run(['gh', 'release', 'create', tag, '--repo', REPOSITORY, '--target', target, '--title', tag, '--notes-file', file, '--draft'])
        release = self.snapshot(tag)['release']
        if release is None:
            raise ValueError('Created draft cannot be read')
        return release

    def upload(self, tag, file):
        run(['gh', 'release', 'upload', tag, file, '--repo', REPOSITORY])

    def download(self, tag, folder):
        run(['gh', 'release', 'download', tag, '--repo', REPOSITORY, '--dir', folder])


def blockers(snapshot, tag, target):
    result = []
    if snapshot['main_sha'] != target:
        result.append('Target must be the current main commit')
    if snapshot['tag_commit'] not in (None, target):
        result.append('Existing tag points to another commit; never move it')
    release = snapshot['release']
    if release and (not release['draft'] or release['target_commitish'] != target):
        result.append('Published versions or drafts for another commit cannot be replaced')
    return result


def validate_uploaded(release, assets):
    expected = {a['name']: a for a in assets}
    for item in release['assets']:
        candidate = expected.get(item['name'])
        if (candidate is None or item['state'] != 'uploaded' or item['size'] != candidate['bytes']
                or item.get('digest') not in (None, 'sha256:' + candidate['sha256'])):
            raise ValueError('Existing asset differs; do not overwrite or delete it')
    names = [a['name'] for a in release['assets']]
    if len(names) != len(set(names)):
        raise ValueError('Ambiguous uploaded assets')


def publish(client, plan, folder):
    """Resume a matching draft without overwrites, then compare downloaded bytes."""
    tag, target, assets = plan['tag'], plan['target_sha'], plan['assets']
    snapshot = client.snapshot(tag)
    reasons = blockers(snapshot, tag, target)
    if reasons:
        raise ValueError('; '.join(reasons))
    notes = f"{tag}: commit `{target}`. {plan['tests']['passed']} tests passed; wheel installation, schema packaging and source archive rebuild validated. SHA-256 values are in SHA256SUMS. Raw project facts and private Agent sessions are excluded."
    release = snapshot['release'] or client.create(tag, target, notes)
    validate_uploaded(release, assets)
    existing = {a['name'] for a in release['assets']}
    # Resume only verified assets. A matching size alone cannot establish matching bytes.
    if existing:
        with tempfile.TemporaryDirectory(prefix='apm-existing-assets-') as directory:
            client.download(tag, Path(directory))
            for asset in assets:
                if asset['name'] in existing and sha256(Path(directory) / asset['name']) != asset['sha256']:
                    raise ValueError('Existing downloaded bytes differ; keep the draft unchanged')
    for asset in assets:
        if asset['name'] not in existing:
            client.upload(tag, folder / asset['name'])
    snapshot = client.snapshot(tag)
    reasons = blockers(snapshot, tag, target)
    if reasons:
        raise ValueError('; '.join(reasons))
    release = snapshot['release']; validate_uploaded(release, assets)
    if {a['name'] for a in release['assets']} != {a['name'] for a in assets}:
        raise ValueError('Uploads are incomplete')
    with tempfile.TemporaryDirectory(prefix='apm-uploaded-assets-') as directory:
        client.download(tag, Path(directory))
        for asset in assets:
            if sha256(Path(directory) / asset['name']) != asset['sha256']:
                raise ValueError('Uploaded bytes differ; leave the Release draft')
    client.api('releases/' + str(release['id']), {'draft': False, 'make_latest': 'true'})
    final = client.snapshot(tag)
    if final['tag_commit'] != target or final['release']['draft'] or not final['release']['published_at']:
        raise ValueError('Published release/tag could not be verified')
    validate_uploaded(final['release'], assets)
    return {'tag': tag, 'target_sha': target, 'release_url': final['release']['html_url'], 'published': True,
            'download_verified': True, 'assets': assets}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'publish'])
    parser.add_argument('--tag', default='')
    parser.add_argument('--target-sha', required=True)
    parser.add_argument('--assets', type=Path, default=Path('dist'))
    parser.add_argument('--junit', type=Path)
    parser.add_argument('--validation', type=Path, default=Path('dist/release-validation.json'))
    args = parser.parse_args(argv)
    try:
        root = Path.cwd().resolve(); version, tag = version_and_target(root, args.tag, args.target_sha)
        assets = package_assets(args.assets, version); client = GitHub()
        if args.mode == 'prepare':
            if args.junit is None:
                raise ValueError('Prepare requires the newly executed JUnit report')
            tests = junit_summary(args.junit)
            smoke(root, args.assets, version)
            snapshot = client.snapshot(tag)
            reasons = blockers(snapshot, tag, args.target_sha)
            plan = {'version': 1, 'tag': tag, 'target_sha': args.target_sha, 'assets': assets, 'tests': tests,
                    'package_smoke': 'passed', 'publish_eligible': not reasons, 'publish_blockers': reasons,
                    'published': False, 'mode': 'read_only_preview'}
            args.validation.write_text(json.dumps(plan, indent=2) + '\n')
            print(json.dumps(plan))
        else:
            plan = json.loads(args.validation.read_text())
            if (plan['target_sha'] != args.target_sha or plan['tag'] != tag or plan['assets'] != assets
                    or plan['package_smoke'] != 'passed' or plan['tests']['passed'] < 1
                    or any(plan['tests'][k] for k in ['failed', 'errors', 'skipped'])):
                raise ValueError('Validation does not bind this exact candidate')
            print(json.dumps(publish(client, plan, args.assets)))
        return 0
    except (ValueError, RuntimeError, KeyError, OSError, ET.ParseError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(json.dumps({'published': False, 'error': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
