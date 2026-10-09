"""Export a checked, credential-free repository snapshot for a local Agent handoff."""

import argparse
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import zipfile

from apm.facts import dump_yaml, safe_path
from apm.operations import valid
from apm.state import _included, active_claims, current_subject, utc_now
from apm.storage import PendingTransaction, project_lock


PREFIXES={'src','schemas','docs','skills','evals','tests','examples','cli','.github'}
ROOT_FILES={'README.md','AGENTS.md','pyproject.toml','uv.lock','.gitignore','.gitattributes','.python-version'}

BOOTSTRAP='''"""Run only in a freshly extracted snapshot after uv sync --frozen."""
from pathlib import Path
import hashlib,json,subprocess
from apm.state import current_subject

root=Path(__file__).resolve().parents[3]
manifest=json.loads((root/'.project/artifacts/relay/manifest.json').read_text())
for name,item in manifest['files'].items():
 path=root/name
 if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
  raise SystemExit('Snapshot path is missing or unsafe: '+name)
 if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
  raise SystemExit('Snapshot file changed: '+name)
 path.chmod(item['mode'])
bundle=root/'.project/artifacts/relay/baseline.bundle'
if hashlib.sha256(bundle.read_bytes()).hexdigest()!=manifest['bundle_sha256']:
 raise SystemExit('Git bundle checksum differs')
def git(*args):
 result=subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True)
 if result.returncode: raise SystemExit('Git baseline restoration failed; use a fresh extraction')
 return result.stdout.strip()
if (root/'.git').exists():
 if git('rev-parse','--verify','HEAD')!=manifest['head']:
  raise SystemExit('Existing Git HEAD differs; do not reset an existing checkout')
else:
 git('init','--quiet','--initial-branch=relay-unborn')
 git('fetch','--quiet',str(bundle),'HEAD:refs/heads/relay-baseline')
 git('symbolic-ref','HEAD','refs/heads/relay-baseline')
 # --mixed writes only the newly created index; never replace snapshot source files.
 git('reset','--mixed',manifest['head'])
if current_subject(root)!=manifest['subject']:
 raise SystemExit('Code subject differs from the exported snapshot')
print(json.dumps({'ok':True,'subject':manifest['subject'],'target_feature':manifest['target_feature']}))
'''


def export_snapshot(root,output,feature_id):
    root=Path(root).resolve()
    # Serialize fact capture with protocol writers, including new entity files.
    with project_lock(root):
        return _export_snapshot(root,output,feature_id)


def _export_snapshot(root,output,feature_id):
    root=Path(root).resolve();output=Path(output).absolute()
    if output.exists() or output.is_symlink() or output.resolve()!=output:
        raise ValueError('Use a new archive path without symlinks')
    f=valid(root)
    if feature_id not in f.features: raise ValueError('Target Feature does not exist')
    if active_claims(f): raise ValueError('Finish and hand off active Runs before exporting')
    def git(*args):
        result=subprocess.run(['git','-C',str(root),*args],capture_output=True)
        if result.returncode: raise ValueError('A readable Git HEAD is required for portable subject restoration')
        return result.stdout
    if Path(git('rev-parse','--show-toplevel').decode().strip()).resolve()!=root:
        raise ValueError('Export must use the actual checkout root')
    head=git('rev-parse','--verify','HEAD').decode().strip()
    tracked=git('ls-tree','-rz','--name-only','HEAD')
    observed=git('ls-files','-z','--cached','--others','--exclude-standard')
    names=sorted(set(n.decode('utf-8') for n in (tracked+observed).split(b'\0') if n))
    source=[name for name in names if _included(name)]
    for name in source:
        if name not in ROOT_FILES and Path(name).parts[0] not in PREFIXES:
            raise ValueError('Unrecognized source path; review before exporting: '+name)
    files={};deleted=[]
    for name in source:
        if not (root/name).exists(): deleted.append(name)
        else: files[name]=safe_path(root,name)
    for folder in ['sources','requirements','features','runs','evidence','handoffs','refs','decisions','artifacts']:
        for path in sorted((root/'.project'/folder).rglob('*')):
            if not path.is_file(): continue
            name=path.relative_to(root).as_posix()
            if name.startswith('.project/artifacts/relay/'): continue
            if any(part in {'.git','.venv','__pycache__','.pytest_cache','.ruff_cache'} for part in path.relative_to(root/'.project').parts): continue
            files[name]=safe_path(root,name)
    for name in ['.project/project.yaml','.project/README.md']:
        if (root/name).is_file(): files[name]=safe_path(root,name)
    for name,path in files.items():
        if (root/name).is_symlink() or path!=root/name: raise ValueError('Snapshot files must not be symlinks')
    before=current_subject(root)
    # Keep source changes and facts out of the Git bundle; only the existing HEAD is needed.
    with tempfile.TemporaryDirectory(prefix='apm-relay-') as scratch:
        bundle=Path(scratch)/'baseline.bundle'
        git('bundle','create',str(bundle),'HEAD')
        bundle_raw=bundle.read_bytes()
    contents={name:path.read_bytes() for name,path in files.items()}
    manifest={'version':1,'kind':'local_agent_handoff','created_at':utc_now(),'target_feature':feature_id,
              'head':head,'subject':before,'deleted_source_paths':deleted,
              'bundle_sha256':hashlib.sha256(bundle_raw).hexdigest(),
              'files':{name:{'sha256':hashlib.sha256(raw).hexdigest(),'mode':stat.S_IMODE(files[name].stat().st_mode)} for name,raw in contents.items()},
              'handoffs':sorted(f.handoffs),'provider_identity':'Not authenticated by this archive'}
    if git('rev-parse','--verify','HEAD').decode().strip()!=head or current_subject(root)!=before or any(path.read_bytes()!=contents[name] for name,path in files.items()):
        raise ValueError('Snapshot changed while exporting; retry after changes finish')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as stream:
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,raw in contents.items(): archive.writestr(name,raw)
            archive.writestr('.project/artifacts/relay/manifest.json',dump_yaml(manifest))
            archive.writestr('.project/artifacts/relay/baseline.bundle',bundle_raw)
            archive.writestr('.project/artifacts/relay/bootstrap.py',BOOTSTRAP)
    return {'path':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'files':len(contents),'subject':before,'target_feature':feature_id}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',default='.');parser.add_argument('--output',required=True);parser.add_argument('--feature',required=True)
    args=parser.parse_args(argv)
    try: result=export_snapshot(args.project,args.output,args.feature)
    except (ValueError,OSError,PendingTransaction) as exc:
        print(json.dumps({'ok':False,'error':str(exc)}));return 2
    print(json.dumps({'ok':True,**result}));return 0


if __name__=='__main__': raise SystemExit(main())
