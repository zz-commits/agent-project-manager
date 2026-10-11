from copy import deepcopy
from uuid import uuid4
import json
import pytest
from apm.fact_writes import propose,apply
from apm.facts import validate_project,read_yaml,dump_yaml
from apm.operations import OperationError,finish_run
from apm.state import current_subject
from apm.storage import RevisionConflict,PendingTransaction
from .test_operations import started,snapshot
from .test_cli import cli

def spec(root,kind):
 f=validate_project(root)
 if kind=='requirement':
  old=next(iter(f.requirements.values()))
  return {k:deepcopy(old[k]) for k in ['title','description','sources','acceptance']}
 return {'title':'Fixture new Feature','domain':'core','requirement_refs':list(f.requirements),'acceptance':[{'id':'AC-NEW','description':'Fixture AC','required':True}]}

def write(root,kind,action,data,run,target=None,expected=None):
 return apply(root,kind,action,propose(root,kind,action,data,target,expected),run['id'],'fixture reviewer','Reviewed actual fixture',target=target,expected=expected)

@pytest.mark.parametrize('kind',['requirement','feature'])
def test_create_preview_apply_and_audit(project,kind):
 run=started(project,'path:.');before=snapshot(project);proposal=propose(project,kind,'create',spec(project,kind));assert snapshot(project)==before
 preview=apply(project,kind,'create',proposal,run['id'],'fixture','Reviewed',dry_run=True);assert preview['dry_run'] and snapshot(project)==before
 result=apply(project,kind,'create',proposal,run['id'],'fixture','Reviewed');obj=result['facts'];assert obj['revision']==1 and read_yaml(project/result['review_artifact'])['kind']=='fact_write_review'
 assert obj['status']=='draft' if kind=='requirement' else obj['implementation']['state']=='not_started'
 assert not validate_project(project).errors
 if kind=='feature':
  f=validate_project(project);assert obj['id'] in f.runs[run['id']]['feature_refs']
  updated=write(project,'feature','update',{'title':'Updated in creating Run'},run,obj['id'],1)['facts'];assert updated['title']=='Updated in creating Run'

@pytest.mark.parametrize('kind',['requirement','feature'])
def test_protected_create_fields_rejected(project,kind):
 before=snapshot(project);incoming=spec(project,kind);incoming['status' if kind=='requirement' else 'delivery']={'records':[]} if kind=='feature' else 'confirmed'
 with pytest.raises(OperationError):propose(project,kind,'create',incoming)
 assert snapshot(project)==before

def test_requirement_changes_need_explicit_reconfirmation(project):
 run=started(project,'path:.');f=validate_project(project);identity=next(iter(f.requirements));old=f.requirements[identity];assert old['status']=='confirmed'
 changed=write(project,'requirement','update',{'description':'Revised fixture goal'},run,identity,old['revision'])['facts'];assert changed['status']=='changed' and 'confirmation' not in changed
 confirmed=write(project,'requirement','confirm',{},run,identity,changed['revision'])['facts'];assert confirmed['status']=='confirmed' and confirmed['confirmation']['reviewer']=='fixture reviewer'

@pytest.mark.parametrize('reason',['blocker','stale_source','no_primary'])
def test_confirmation_rejects_unresolved_sources(project,reason):
 run=started(project,'path:.');f=validate_project(project);identity=next(iter(f.requirements));old=f.requirements[identity]
 if reason=='blocker':old['blockers']=['Fixture unresolved conflict'];(project/f.files[identity]).write_text(dump_yaml(old))
 elif reason=='stale_source':old['sources'][0]['source_revision']='old';(project/f.files[identity]).write_text(dump_yaml(old))
 else:
  path=project/'.project/sources/registry.yaml';registry=read_yaml(path)
  for source in registry['sources']:source['authority']='secondary'
  path.write_text(dump_yaml(registry))
 with pytest.raises(OperationError) as exc:propose(project,'requirement','confirm',{},identity,old['revision'])
 assert exc.value.code==5

def test_feature_update_preserves_proof_and_bumps_ac_revision(project):
 from .test_verification import configured
 from .test_relay import git
 from apm.delivery import link_commit
 from apm.verification import execute_checks
 git(project,'init','-q');git(project,'add','.');git(project,'-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-qm','Fixture delivery baseline')
 feature,run=configured(project);execute_checks(project,feature['id'],run['id'],1);link_commit(project,feature['id'],'HEAD',run['id'],2);f=validate_project(project);old=f.features[feature['id']];assert old['delivery']['records'];ac=deepcopy(old['acceptance']);ac[0]['description']='Changed fixture acceptance'
 result=write(project,'feature','update',{'acceptance':ac,'implementation':{'remaining':['Revalidate changed AC']}},run,feature['id'],old['revision'])['facts'];assert result['acceptance_revision']==old['acceptance_revision']+1 and result['verification']==old['verification'] and result['delivery']==old['delivery'] and result['implementation']['subject']==current_subject(project)
 from apm.verification import assessment
 assert not assessment(validate_project(project),feature['id'])['required_passed']

@pytest.mark.parametrize('field',['evidence_refs','subject','evidence_level'])
def test_cannot_inject_verified_implementation(project,field):
 f=validate_project(project);identity=next(iter(f.features));value='verified' if field=='evidence_level' else ([] if field=='evidence_refs' else current_subject(project))
 with pytest.raises(OperationError):propose(project,'feature','update',{'implementation':{field:value}},identity,1)

def test_stale_revision_snapshot_and_tampering_rejected(project):
 run=started(project,'path:.');f=validate_project(project);identity=next(iter(f.features))
 with pytest.raises(RevisionConflict):propose(project,'feature','update',{'title':'new'},identity,2)
 p=propose(project,'feature','update',{'title':'new'},identity,1);before=snapshot(project);bad=deepcopy(p);bad['proposal']['candidate']['title']='tampered'
 with pytest.raises(OperationError):apply(project,'feature','update',bad,run['id'],'fixture','Reviewed',target=identity,expected=1)
 assert snapshot(project)==before
 write(project,'feature','update',{'priority':'P2'},run,identity,1)
 with pytest.raises(OperationError) as exc:apply(project,'feature','update',p,run['id'],'fixture','Reviewed',target=identity,expected=1)
 assert exc.value.code==3

def test_terminal_run_rejected(project):
 run=started(project,'path:.');p=propose(project,'requirement','create',spec(project,'requirement'));finish_run(project,run['id'],1)
 with pytest.raises(OperationError) as exc:apply(project,'requirement','create',p,run['id'],'fixture','Reviewed')
 assert exc.value.code==5

def test_invalid_candidate_does_not_write(project):
 before=snapshot(project);incoming=spec(project,'feature');incoming['requirement_refs']=['REQ-'+str(uuid4())]
 with pytest.raises(OperationError):propose(project,'feature','create',incoming)
 assert snapshot(project)==before

def test_cli_json_proposal_roundtrip(project,tmp_path):
 run=started(project,'path:.');input_file=tmp_path/'input.json';input_file.write_text(json.dumps(spec(project,'requirement')));code,p=cli(project,'requirement','create','--file',str(input_file));assert code==0
 proposal_file=tmp_path/'proposal.json';proposal_file.write_text(json.dumps(p));code,result=cli(project,'requirement','create','--apply',str(proposal_file),'--run-id',run['id'],'--reviewer','fixture','--note','Reviewed');assert code==0
 assert result['data']['facts']['status']=='draft'

def test_markdown_changes_after_confirmation_preview_are_rejected(project):
 from .test_sources import imported
 source,run,identity=imported(project)
 f=validate_project(project);old=f.requirements[identity]
 p=propose(project,'requirement','confirm',{},identity,old['revision'])
 (project/'docs/requirements.md').write_text('Changed source outside sync')
 with pytest.raises(OperationError) as exc:
  apply(project,'requirement','confirm',p,run['id'],'fixture','Reviewed',target=identity,expected=old['revision'])
 assert exc.value.code==3 and validate_project(project).requirements[identity]['status']=='draft'

@pytest.mark.parametrize('field',['reviewer','note'])
def test_explicit_review_is_required(project,field):
 run=started(project,'path:.');p=propose(project,'requirement','create',spec(project,'requirement'));before=snapshot(project);args={'reviewer':'fixture','note':'Reviewed'};args[field]=' '
 with pytest.raises(OperationError) as exc:apply(project,'requirement','create',p,run['id'],**args)
 assert exc.value.code==2 and snapshot(project)==before

def test_interrupted_feature_and_run_write_recovers_atomically(project,monkeypatch):
 import apm.storage as storage
 run=started(project,'path:.');p=propose(project,'feature','create',spec(project,'feature'));original=storage._replace;calls=0
 def interrupted(path,text):
  nonlocal calls
  calls+=1
  if calls==3:raise RuntimeError('Isolated crash during transaction')
  return original(path,text)
 monkeypatch.setattr(storage,'_replace',interrupted)
 with pytest.raises(RuntimeError):apply(project,'feature','create',p,run['id'],'fixture','Reviewed')
 assert storage.pending_transactions(project)
 monkeypatch.setattr(storage,'_replace',original);assert storage.recover(project)
 f=validate_project(project);identity=p['proposal']['target'];assert not f.errors and identity in f.features and identity in f.runs[run['id']]['feature_refs'] and not storage.pending_transactions(project)
