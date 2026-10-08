from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest

from apm.facts import dump_yaml, read_yaml, validate_project
from apm.operations import OperationError, finish_run, init_project, rebuild, start_run, update_run
from apm.state import active_claims, claims_overlap, conflicts, derive
from apm.storage import PendingTransaction, RevisionConflict, pending_transactions, recover
from .test_state import AT


def feature_id(root):
    return next(iter(validate_project(root).features))


def started(root, scope='path:src/**', instance='worker'):
    return start_run(root, feature_id(root), 'test', instance, scope)['run']


def snapshot(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}


def handoff_for(run):
    return {'version':1,'id':'HANDOFF-'+str(uuid4()),'run_ref':run['id'],
            'feature_refs':run['feature_refs'],'summary':'Actual test-fixture handoff',
            **deepcopy(run['work']),'recommended_next':['continue fixture work'],
            'evidence_refs':[],'context_refs':[],'created_at':run['started_at']}


def test_empty_init_valid_and_no_overwrite(tmp_path):
    root=tmp_path/'new'
    result=init_project(root,'demo')
    assert result['project']['mode']=='managed'
    assert not validate_project(root).errors
    assert derive(validate_project(root),AT)['summary']['total']==0
    before=snapshot(root)
    with pytest.raises(OperationError) as exc:
        init_project(root,'again')
    assert exc.value.code==3
    assert snapshot(root)==before


def test_init_dry_run_creates_nothing(tmp_path):
    root=tmp_path/'absent'
    assert init_project(root,'demo',dry_run=True)['dry_run']
    assert not root.exists()


@pytest.mark.parametrize('left,right,expected',[
    ('path:src/**','path:src/code.py',True),
    ('path:src/','path:src/nested/file.py',True),
    ('path:src/code.py','path:src/other.py',False),
    ('path:.','path:other/file.py',True),
    ('path:src/**','path:src-other/file.py',False),
    ('component:core','path:src/apm/file.py',True),
    ('component:core','path:docs/file.md',False),
])
def test_claim_path_semantics(project,left,right,expected):
    facts=validate_project(project)
    def claim(scope):
        kind,_,value=scope.partition(':')
        return {'feature_ref':feature_id(project),'scope':{'type':kind,'value':value}}
    assert claims_overlap(facts,claim(left),claim(right)) is expected


def test_feature_claims_use_component_paths_across_features(project):
    f=validate_project(project)
    first=next(iter(f.features))
    second='FEAT-'+str(uuid4())
    f.features[second]=deepcopy(f.features[first])
    f.features[first]['implementation']['components']={'core':[]}
    f.features[second]['implementation']['components']={'core':[]}
    a={'feature_ref':first,'scope':{'type':'feature','value':first}}
    b={'feature_ref':second,'scope':{'type':'feature','value':second}}
    assert claims_overlap(f,a,b)
    f.features[second]['implementation']['components']={'docs':[]}
    assert not claims_overlap(f,a,b)


def test_start_claim_does_not_advance_feature_and_finish_releases(project):
    run=started(project)
    f=validate_project(project)
    assert len(active_claims(f))==1
    assert derive(f,AT)['features'][0]['lifecycle']=='ready'
    terminal=finish_run(project,run['id'],1)['run']
    assert terminal['status']=='completed'
    assert terminal['claims']==run['claims']
    f=validate_project(project)
    assert not active_claims(f)
    assert derive(f,AT)['features'][0]['lifecycle']=='ready'


def test_overlapping_claim_rejected_override_remains_visible(project):
    first=started(project)
    before=snapshot(project)
    with pytest.raises(OperationError) as exc:
        started(project,'path:src/code.py','second')
    assert exc.value.code==3
    assert snapshot(project)==before
    second=start_run(project,feature_id(project),'test','second','path:src/code.py',override_reason='explicit test coordination')['run']
    collision=conflicts(validate_project(project))[0]
    assert collision['overridden']
    assert {collision['left']['run_ref'],collision['right']['run_ref']}=={first['id'],second['id']}


def test_revision_conflict_preserves_file(project):
    run=started(project)
    updated=update_run(project,run['id'],1,{'goal':'new goal'})['run']
    assert updated['revision']==2
    before=snapshot(project)
    with pytest.raises(RevisionConflict):
        update_run(project,run['id'],1,{'goal':'stale writer'})
    assert snapshot(project)==before


def test_two_process_writers_cannot_overwrite_same_revision(project):
    run=started(project)
    script='''import sys
from pathlib import Path
from apm.operations import update_run
from apm.storage import RevisionConflict
try:
    update_run(Path(sys.argv[1]),sys.argv[2],1,{'goal':sys.argv[3]})
except RevisionConflict:
    raise SystemExit(3)
'''
    commands=[[sys.executable,'-c',script,str(project),run['id'],goal] for goal in ['writer-one','writer-two']]
    processes=[subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for command in commands]
    outcomes=[]
    for process in processes:
        _,stderr=process.communicate(timeout=20)
        assert not stderr,stderr.decode()
        outcomes.append(process.returncode)
    assert sorted(outcomes)==[0,3]
    assert validate_project(project).runs[run['id']]['revision']==2


def test_handoff_required_and_terminal_run_immutable(project):
    run=started(project)
    run=update_run(project,run['id'],1,{'work':{'completed':['reviewed'],'remaining':['implement'],'blockers':[]}})['run']
    before=snapshot(project)
    with pytest.raises(OperationError) as exc:
        finish_run(project,run['id'],2)
    assert exc.value.code==2
    assert snapshot(project)==before
    handoff=handoff_for(run)
    terminal=finish_run(project,run['id'],2,handoff=handoff)['run']
    assert terminal['revision']==3 and terminal['handoff_ref']==handoff['id']
    assert not active_claims(validate_project(project))
    with pytest.raises(OperationError) as exc:
        update_run(project,run['id'],3,{'goal':'cannot edit terminal'})
    assert exc.value.code==3


def test_handoff_cannot_hide_remaining_work(project):
    run=started(project)
    run=update_run(project,run['id'],1,{'work':{'completed':[],'remaining':['pending'],'blockers':[]}})['run']
    handoff=handoff_for(run)
    handoff['remaining']=[]
    with pytest.raises(OperationError) as exc:
        finish_run(project,run['id'],2,handoff=handoff)
    assert any(e.code=='handoff_work_mismatch' for e in exc.value.issues)


def test_abort_requires_reason_and_handoff_for_blocker(project):
    run=started(project)
    run=update_run(project,run['id'],1,{'work':{'completed':[],'remaining':[],'blockers':['blocked']}})['run']
    terminal=finish_run(project,run['id'],2,handoff=handoff_for(run),abort_reason='stop fixture')['run']
    assert terminal['status']=='aborted' and terminal['finish_reason']=='stop fixture'
    assert not validate_project(project).errors


def test_run_write_dry_run_changes_nothing(project):
    before=snapshot(project)
    dry=start_run(project,feature_id(project),'test','dry','path:src/**',dry_run=True)
    assert dry['dry_run']
    assert snapshot(project)==before
    run=started(project)
    before=snapshot(project)
    update_run(project,run['id'],1,{'goal':'dry'},dry_run=True)
    finish_run(project,run['id'],1,dry_run=True)
    rebuild(project,AT,dry_run=True)
    assert snapshot(project)==before


def test_rebuild_is_deterministic_and_facts_unchanged_after_cache_deletion(project):
    before={k:v for k,v in snapshot(project).items() if k.startswith('.project/')}
    rebuild(project,AT)
    outputs={p.name:p.read_bytes() for p in (project/'.project/generated').iterdir()}
    rebuild(project,AT)
    assert outputs=={p.name:p.read_bytes() for p in (project/'.project/generated').iterdir()}
    for name,data in before.items():
        assert (project/name).read_bytes()==data
    shutil.rmtree(project/'.project/generated')
    (project/'.project/cache').mkdir()
    (project/'.project/cache/local').write_text('disposable')
    shutil.rmtree(project/'.project/cache')
    rebuild(project,AT)
    assert outputs=={p.name:p.read_bytes() for p in (project/'.project/generated').iterdir()}


def test_interrupted_handoff_keeps_claim_then_recovery_finishes(project,monkeypatch):
    import apm.storage as storage
    run=started(project)
    run=update_run(project,run['id'],1,{'work':{'completed':['done'],'remaining':['next'],'blockers':[]}})['run']
    handoff=handoff_for(run)
    original=storage._replace
    def crash(path,text):
        if path.parent.name=='runs':
            raise OSError('simulated crash before Run termination')
        original(path,text)
    with monkeypatch.context() as patch:
        patch.setattr(storage,'_replace',crash)
        with pytest.raises(OSError):
            finish_run(project,run['id'],2,handoff=handoff)
    assert pending_transactions(project)
    assert active_claims(validate_project(project))
    with pytest.raises(PendingTransaction):
        update_run(project,run['id'],2,{'goal':'blocked write'})
    assert len(recover(project))==1
    assert recover(project)==[]
    assert not pending_transactions(project)
    f=validate_project(project)
    assert not f.errors and not active_claims(f)
    assert f.runs[run['id']]['status']=='completed'


def test_recovery_refuses_outside_edits(project,monkeypatch):
    import apm.storage as storage
    run=started(project)
    original=storage._replace
    def crash(path,text):
        if path.parent.name=='runs':raise OSError('simulated crash')
        original(path,text)
    with monkeypatch.context() as patch:
        patch.setattr(storage,'_replace',crash)
        with pytest.raises(OSError):update_run(project,run['id'],1,{'goal':'new'})
    path=project/validate_project(project).files[run['id']]
    data=read_yaml(path);data['goal']='external edit';path.write_text(dump_yaml(data))
    with pytest.raises(RevisionConflict):recover(project)
    assert pending_transactions(project)
    assert read_yaml(path)['goal']=='external edit'


def test_generated_symlink_cannot_overwrite_source(project):
    directory=project/'.project/generated'
    directory.mkdir()
    source=project/'src/code.py'
    before=source.read_bytes()
    (directory/'status.json').symlink_to(source)
    with pytest.raises(ValueError):rebuild(project,AT)
    assert source.read_bytes()==before


def test_lock_symlink_cannot_truncate_source(project):
    source=project/'src/code.py'
    before=source.read_bytes()
    (project/'.project/.write.lock').symlink_to(source)
    with pytest.raises(ValueError):started(project)
    assert source.read_bytes()==before
