import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from apm.facts import validate_project
from apm.operations import start_run
from apm.storage import PendingTransaction
from apm.state import current_subject
from evals.relay import export_snapshot


def git(root,*args):
    result=subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return result.stdout.strip()


@pytest.fixture
def checkout(project):
    git(project,'init','--quiet','--initial-branch=main')
    (project/'src/deleted.py').write_text('baseline = True\n')
    (project/'src/executable.py').write_text('print(1)\n');(project/'src/executable.py').chmod(0o755)
    git(project,'add','.')
    git(project,'-c','user.name=Synthetic fixture','-c','user.email=fixture@example.invalid','commit','--quiet','-m','Synthetic packet baseline')
    (project/'src/deleted.py').unlink();(project/'src/code.py').write_text('value = 2\n')
    (project/'src/new.py').write_text('new = True\n')
    return project


def export(root,tmp_path):
    feature=next(iter(validate_project(root).features))
    output=tmp_path/'packet.zip'
    return output,export_snapshot(root,output,feature)


def unpack(output,target):
    target.mkdir()
    with zipfile.ZipFile(output) as archive: archive.extractall(target)


def bootstrap(target):
    return subprocess.run([sys.executable,str(target/'.project/artifacts/relay/bootstrap.py')],cwd=target,capture_output=True,text=True)


def test_packet_restores_head_modes_deleted_files_and_subject(checkout,tmp_path):
    before=current_subject(checkout);head=git(checkout,'rev-parse','HEAD')
    output,receipt=export(checkout,tmp_path)
    assert receipt['subject']==before
    target=tmp_path/'restored';unpack(output,target)
    process=bootstrap(target)
    assert process.returncode==0,process.stderr
    assert json.loads(process.stdout)['subject']==before
    assert current_subject(target)==before and git(target,'rev-parse','HEAD')==head
    assert (target/'src/code.py').read_text()=='value = 2\n'
    assert not (target/'src/deleted.py').exists()
    assert (target/'src/new.py').is_file() and (target/'src/executable.py').stat().st_mode&0o777==0o755
    assert not validate_project(target).errors
    assert bootstrap(target).returncode==0
    assert current_subject(checkout)==before


def test_packet_excludes_host_configuration_caches_and_recursive_packets(checkout,tmp_path):
    (checkout/'.git/config').write_text((checkout/'.git/config').read_text()+'\n[synthetic]\n\tnote = DO-NOT-COPY-CONFIG\n')
    for name in ['.project/artifacts/relay/old.zip','.project/artifacts/eval/contexts/one/.git/config','.project/generated/status.json','.project/cache/local']:
        path=checkout/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('Excluded synthetic config fixture')
    transcript=checkout/'.project/artifacts/deepseek-observation/transcript.txt'
    transcript.parent.mkdir();transcript.write_text('Synthetic test of packaging; not a real provider transcript')
    output,_=export(checkout,tmp_path)
    with zipfile.ZipFile(output) as archive:
        names=archive.namelist()
        assert not any('.git/' in n or '.project/cache/' in n or '.project/generated/' in n or n.endswith('old.zip') for n in names)
        assert '.project/artifacts/deepseek-observation/transcript.txt' in names


def test_packet_refuses_active_claim(checkout,tmp_path):
    feature=next(iter(validate_project(checkout).features))
    start_run(checkout,feature,'synthetic-test','fixture','path:src/')
    with pytest.raises(ValueError,match='active Runs'): export(checkout,tmp_path)
    assert not (tmp_path/'packet.zip').exists()


def test_packet_refuses_unfinished_transactions(checkout,tmp_path):
    path=checkout/'.project/transactions/pending.json'
    path.parent.mkdir(exist_ok=True);path.write_text('{}')
    with pytest.raises(PendingTransaction): export(checkout,tmp_path)
    assert not (tmp_path/'packet.zip').exists()


@pytest.mark.parametrize('damage',['unknown_file','symlink','existing_output'])
def test_packet_rejects_unreviewed_or_unsafe_output(checkout,tmp_path,damage):
    if damage=='unknown_file': (checkout/'private.env').write_text('Synthetic forbidden path fixture, no credentials')
    elif damage=='symlink': (checkout/'src/new.py').unlink();(checkout/'src/new.py').symlink_to(checkout/'src/code.py')
    elif damage=='existing_output': (tmp_path/'packet.zip').write_text('Preserve')
    with pytest.raises(ValueError): export(checkout,tmp_path)
    if damage=='existing_output': assert (tmp_path/'packet.zip').read_text()=='Preserve'


def test_bootstrap_refuses_tampering_and_existing_other_head(checkout,tmp_path):
    output,_=export(checkout,tmp_path)
    target=tmp_path/'tampered';unpack(output,target)
    (target/'src/code.py').write_text('value = 99\n')
    assert bootstrap(target).returncode!=0 and not (target/'.git').exists()
    other=tmp_path/'different-head';unpack(output,other)
    git(other,'init','--quiet','--initial-branch=main');git(other,'add','src/')
    git(other,'-c','user.name=Synthetic fixture','-c','user.email=fixture@example.invalid','commit','--quiet','-m','Different fixture baseline')
    head=git(other,'rev-parse','HEAD')
    assert bootstrap(other).returncode!=0
    assert git(other,'rev-parse','HEAD')==head
