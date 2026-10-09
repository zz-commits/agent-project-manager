from copy import deepcopy
from pathlib import Path
import hashlib,io,json,zipfile
import pytest
from apm.ci_evidence import import_ci
from apm.operations import OperationError
from apm.facts import validate_project,dump_yaml
from apm.state import current_subject
from .test_operations import snapshot
from .test_verification import configured,PASS,SKIPPED,FAILED
from .test_relay import git

class Transport:
 """Isolated GitHub transport fixture, not native CI or a real Agent."""
 def __init__(self,sha,xml=PASS,edit_context=None):
  self.calls=[];self.native={'id':42,'repository':{'full_name':'fixture/project'},'head_repository':{'full_name':'fixture/project'},'head_sha':sha,'status':'completed','conclusion':'success','run_attempt':1,'html_url':'https://github.com/fixture/project/actions/runs/42'}
  context={'version':1,'repository':'fixture/project','run_id':42,'run_attempt':1,'subject':{'kind':'commit','value':sha},'report':'ci-tests.xml','report_sha256':hashlib.sha256(xml.encode()).hexdigest(),'command':{'argv':['pytest'],'cwd':'.','exit_code':0}}
  if edit_context:edit_context(context)
  output=io.BytesIO()
  with zipfile.ZipFile(output,'w') as z:z.writestr('ci-tests.xml',xml);z.writestr('ci-context.json',json.dumps(context))
  self.raw=output.getvalue();self.artifact={'id':84,'name':'fixture-junit','expired':False,'workflow_run':{'id':42,'head_sha':sha},'size_in_bytes':len(self.raw),'digest':'sha256:'+hashlib.sha256(self.raw).hexdigest()}
 def api(self,path,raw=False):
  self.calls.append(path)
  if raw:return self.raw
  if '/artifacts?' in path:return {'total_count':1,'artifacts':[deepcopy(self.artifact)]}
  return deepcopy(self.native)

@pytest.fixture
def setup(project):
 feature,run=configured(project)
 git(project,'init','-q');git(project,'remote','add','origin','https://github.com/fixture/project.git');git(project,'add','.');git(project,'-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-qm','Isolated CI fixture')
 f=validate_project(project);f.project['commands']['verify']['argv']=['pytest'];(project/'.project/project.yaml').write_text(dump_yaml(f.project));feature=f.features[feature['id']];feature['implementation']['subject']=current_subject(project);(project/f.files[feature['id']]).write_text(dump_yaml(feature));return feature,run,current_subject(project)['value']

def collect(project,setup,client,**options):
 feature,run,sha=setup
 return import_ci(project,feature['id'],run['id'],1,42,'fixture-junit',['CHECK-001'],'fixture reviewer','Reviewed isolated transport',client=client,**options)

def test_default_preview_writes_nothing_then_explicit_ci_import(setup,project):
 client=Transport(setup[2]);before=snapshot(project);preview=collect(project,setup,client);assert preview['dry_run'] and not preview['new_evidence'] and preview['ci_preview_checks'][0]['result']=='passed' and snapshot(project)==before
 result=collect(project,setup,client,apply=True);assert result['required_passed'] and len(result['new_evidence'])==1
 f=validate_project(project);ev=f.evidence[result['new_evidence'][0]];assert ev['type']=='ci_result' and ev['subject']==current_subject(project) and ev['command']['argv']==['pytest']
 assert any(a['path'].endswith('.zip') for a in ev['artifacts']) and all(hashlib.sha256((project/a['path']).read_bytes()).hexdigest()==a['sha256'] for a in ev['artifacts'])

@pytest.mark.parametrize('change',[{'head_sha':'b'*40},{'status':'in_progress'},{'conclusion':'failure'},{'conclusion':'cancelled'},{'repository':{'full_name':'other/project'}},{'head_repository':{'full_name':'fork/project'}}])
def test_wrong_failed_or_incomplete_run_cannot_write(setup,project,change):
 client=Transport(setup[2]);client.native.update(change);before=snapshot(project)
 with pytest.raises(OperationError) as exc:collect(project,setup,client,apply=True)
 assert exc.value.code==5 and snapshot(project)==before and len(client.calls)==1

@pytest.mark.parametrize('change',[{'expired':True},{'digest':None},{'digest':'sha256:'+'0'*64},{'workflow_run':{'id':41,'head_sha':'b'*40}},{'name':'missing'},{'size_in_bytes':10**9}])
def test_invalid_missing_or_expired_artifact_cannot_write(setup,project,change):
 client=Transport(setup[2]);client.artifact.update(change);before=snapshot(project)
 with pytest.raises(OperationError):collect(project,setup,client,apply=True)
 assert snapshot(project)==before

@pytest.mark.parametrize('xml',[SKIPPED,FAILED,'<testsuite/>','<testsuite><testcase classname="other" name="test"/></testsuite>',PASS.replace('</testsuite>','<testcase classname="suite" name="test"/></testsuite>')])
def test_named_assertions_are_required_even_when_ci_success(setup,project,xml):
 before=snapshot(project)
 with pytest.raises(OperationError) as exc:collect(project,setup,Transport(setup[2],xml),apply=True)
 assert exc.value.code==5 and snapshot(project)==before

@pytest.mark.parametrize('change',[{'subject':{'kind':'commit','value':'b'*40}},{'run_attempt':2},{'report_sha256':'0'*64},{'command':{'argv':['pytest'],'cwd':'.','exit_code':1}},{'command':{'argv':['echo','not pytest'],'cwd':'.','exit_code':0}}])
def test_execution_context_must_bind_run_commit_and_report(setup,project,change):
 client=Transport(setup[2],edit_context=lambda c:c.update(change));before=snapshot(project)
 with pytest.raises(OperationError):collect(project,setup,client,apply=True)
 assert snapshot(project)==before

def test_dirty_source_and_changed_facts_during_download_rejected(setup,project):
 client=Transport(setup[2]);original=client.api
 def changed(path,raw=False):
  value=original(path,raw)
  if raw:
   f=validate_project(project);req=next(iter(f.requirements.values()));req['revision']+=1;(project/f.files[req['id']]).write_text(dump_yaml(req))
  return value
 client.api=changed
 with pytest.raises(OperationError) as exc:collect(project,setup,client,apply=True)
 assert exc.value.code==3 and not validate_project(project).evidence
 (project/'src/code.py').write_text('dirty = True\n');client=Transport(setup[2])
 with pytest.raises(OperationError) as exc:collect(project,setup,client,apply=True)
 assert exc.value.code==5 and not client.calls
