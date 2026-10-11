import hashlib,json,stat,zipfile
from pathlib import Path
import pytest
from apm.snapshots import inspect,restore
from apm.operations import OperationError
from apm.state import current_subject
from .test_relay import checkout,export,git

def checked(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def rewrite(path,edit):
 with zipfile.ZipFile(path) as archive:files={n:archive.read(n) for n in archive.namelist()}
 edit(files)
 other=path.with_name('changed.zip')
 with zipfile.ZipFile(other,'w') as archive:
  for name,raw in files.items():archive.writestr(name,raw)
 return other

def test_inspect_dry_run_and_restore_actual_tree(checkout,tmp_path):
 packet,receipt=export(checkout,tmp_path);before=current_subject(checkout);target=tmp_path/'new';sha=receipt['sha256'];view=inspect(packet,sha);assert view['subject']==before and not view['scripts_executed'] and not target.exists()
 assert restore(packet,sha,target,dry_run=True)['dry_run'] and not target.exists()
 result=restore(packet,sha,target);assert result['restored'] and result['subject']==current_subject(target)==before
 assert current_subject(target)==before and git(target,'rev-parse','HEAD')==git(checkout,'rev-parse','HEAD')
 assert not (target/'src/deleted.py').exists() and (target/'src/executable.py').stat().st_mode&0o777==0o755 and current_subject(checkout)==before

@pytest.mark.parametrize('kind',['directory','symlink'])
def test_existing_destination_is_never_overwritten(checkout,tmp_path,kind):
 packet,receipt=export(checkout,tmp_path);target=tmp_path/'existing';outside=tmp_path/'original';outside.mkdir();(outside/'keep').write_text('keep')
 if kind=='directory':target.mkdir()
 else:target.symlink_to(outside,target_is_directory=True)
 with pytest.raises(OperationError) as exc:restore(packet,receipt['sha256'],target)
 assert exc.value.code==3 and (outside/'keep').read_text()=='keep'

def test_trusted_hash_is_required_before_extraction(checkout,tmp_path):
 packet,receipt=export(checkout,tmp_path);target=tmp_path/'new'
 with pytest.raises(OperationError) as exc:restore(packet,'0'*64,target)
 assert exc.value.code==5 and not target.exists()

@pytest.mark.parametrize('path',['../outside','/tmp/outside','docs/../outside','docs\\outside','.git/hooks/post-checkout','evil.sh'])
def test_archive_paths_cannot_escape_or_inject_git_configuration(checkout,tmp_path,path):
 packet,_=export(checkout,tmp_path);changed=rewrite(packet,lambda files:files.update({path:b'fixture'}));target=tmp_path/'new'
 with pytest.raises(OperationError):restore(changed,checked(changed),target)
 assert not target.exists()

@pytest.mark.parametrize('problem',['version','mode','sha','extra','subject'])
def test_invalid_manifest_and_changed_bytes_are_rejected(checkout,tmp_path,problem):
 packet,_=export(checkout,tmp_path)
 def edit(files):
  name='.project/artifacts/relay/manifest.json';m=json.loads(files[name])
  if problem=='version':m['version']=2
  elif problem=='mode':m['files']['src/code.py']['mode']=0o4755
  elif problem=='sha':files['src/code.py']=b'changed'
  elif problem=='extra':files['docs/unlisted.md']=b'extra'
  else:m['subject']={'kind':'commit','value':m['head']}
  files[name]=json.dumps(m).encode()
 changed=rewrite(packet,edit);target=tmp_path/'new'
 with pytest.raises(OperationError):restore(changed,checked(changed),target)
 assert not target.exists() and not list(tmp_path.glob('.apm-restore-*'))

def test_duplicate_paths_and_zip_symlinks_rejected(checkout,tmp_path):
 packet,_=export(checkout,tmp_path);changed=tmp_path/'bad.zip'
 with zipfile.ZipFile(packet) as archive,zipfile.ZipFile(changed,'w') as bad:
  for n in archive.namelist():bad.writestr(n,archive.read(n))
  item=zipfile.ZipInfo('docs/symlink');item.external_attr=(stat.S_IFLNK|0o777)<<16;bad.writestr(item,'../outside')
 with pytest.raises(OperationError):inspect(changed,checked(changed))
 with zipfile.ZipFile(changed,'a') as bad:
  with pytest.warns(UserWarning):bad.writestr('docs/symlink','duplicate')
 with pytest.raises(OperationError):inspect(changed,checked(changed))

def test_bundled_bootstrap_is_never_executed(checkout,tmp_path):
 packet,_=export(checkout,tmp_path);sentinel=tmp_path/'executed'
 changed=rewrite(packet,lambda files:files.update({'.project/artifacts/relay/bootstrap.py':f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n".encode()}))
 assert restore(changed,checked(changed),tmp_path/'new')['restored'] and not sentinel.exists()

def test_archive_resource_limits_checked_without_install(checkout,tmp_path,monkeypatch):
 import apm.snapshots as snapshots
 packet,_=export(checkout,tmp_path);monkeypatch.setattr(snapshots,'MAX_FILES',1)
 with pytest.raises(OperationError):restore(packet,checked(packet),tmp_path/'new')
 assert not (tmp_path/'new').exists()
