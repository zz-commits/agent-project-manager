import json
from pathlib import Path
import subprocess
import sys

import pytest

from apm.facts import validate_project
from .test_operations import feature_id, started


def cli(root,*args):
    result=subprocess.run([sys.executable,'-m','apm.cli','--project',str(root),'--json',*args],
                          capture_output=True,text=True,timeout=20)
    output=json.loads(result.stdout)
    assert set(output)=={'protocol_version','ok','command','data','warnings','errors'}
    assert output['ok'] is (result.returncode==0)
    assert not result.stderr
    return result.returncode,output


def test_json_queries_have_real_data_and_never_execute_commands(project):
    code,doctor=cli(project,'doctor')
    assert code==0 and doctor['data']['counts']['features']==1
    code,state=cli(project,'status')
    assert code==0 and state['data']['summary']['total']==1
    assert state['data']['features'][0]['lifecycle']=='ready'
    code,listed=cli(project,'feature','list','--ready')
    assert code==0 and len(listed['data']['features'])==1
    code,shown=cli(project,'feature','show',feature_id(project))
    assert code==0 and shown['data']['requirements'] and shown['data']['remaining']
    assert cli(project,'feature','validate',feature_id(project))[0]==0


@pytest.mark.parametrize('args,code',[
    (['unknown'],2),(['feature','show'],2),(['feature','show','FEAT-missing'],4),
    (['status','--at','2026-10-08'],2),(['status','--at','invalid'],2),
    (['run','show','current'],2),(['run','show','current','--instance','none'],4),
    (['run','finish','RUN-missing','--expected-revision','1'],4),
    (['doctor','--recover','--dry-run'],2),
])
def test_errors_preserve_json_and_exit_codes(project,args,code):
    actual,result=cli(project,*args)
    assert actual==code and result['errors']


def test_missing_project_returns_four(tmp_path):
    code,result=cli(tmp_path,'doctor')
    assert code==4 and result['errors'][0]['code']=='not_found'


def test_ready_filter_accounts_for_claims_and_current_is_exact(project):
    run=started(project)
    assert cli(project,'feature','list','--ready')[1]['data']['features']==[]
    assert cli(project,'run','show','current','--instance','worker')[1]['data']['id']==run['id']
    from apm.operations import start_run
    start_run(project,feature_id(project),'test','worker','path:docs/**')
    assert cli(project,'run','show','current','--instance','worker')[0]==3


def test_invalid_update_file_and_stale_revision(project,tmp_path):
    run=started(project)
    patch=tmp_path/'patch.yaml'
    patch.write_text('goal: changed\n')
    assert cli(project,'run','update',run['id'],'--expected-revision','1','--file',str(patch))[0]==0
    assert cli(project,'run','update',run['id'],'--expected-revision','1','--file',str(patch))[0]==3
    patch.write_text('claims: []\n')
    assert cli(project,'run','update',run['id'],'--expected-revision','2','--file',str(patch))[0]==2


def test_override_requires_reason_and_doctor_warns(project):
    run=started(project)
    args=['run','start',feature_id(project),'--agent','test','--instance','other','--scope','path:src/**']
    assert cli(project,*args)[0]==3
    assert cli(project,*args,'--override-conflict')[0]==2
    assert cli(project,*args,'--override-conflict','--reason','coordination')[0]==0
    code,result=cli(project,'doctor')
    assert code==0 and result['warnings'][0]['code']=='claim_override'


def test_doctor_reports_and_recovers_real_interrupted_write(project,monkeypatch):
    import apm.storage as storage
    from apm.operations import update_run
    run=started(project)
    original=storage._replace
    def crash(path,text):
        if path.parent.name=='runs':raise OSError('fixture crash')
        original(path,text)
    with monkeypatch.context() as patch:
        patch.setattr(storage,'_replace',crash)
        with pytest.raises(OSError):update_run(project,run['id'],1,{'goal':'recovered update'})
    assert cli(project,'doctor')[0]==5
    assert cli(project,'status')[0]==5
    code,result=cli(project,'doctor','--recover')
    assert code==0 and len(result['data']['recovered_transactions'])==1
    assert cli(project,'run','show',run['id'])[1]['data']['revision']==2
