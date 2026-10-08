"""Execute synthetic CLI cases; no model calls or simulated external Agent identities."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

from apm.facts import dump_yaml, read_yaml
from apm.operations import valid
from apm.state import current_subject, utc_now
from apm.verification import _redact


CASES = {
 'ready': ('ready', 'not_started', 'none'),
 'complete_no_evidence': ('verifying', 'not_started', 'none'),
 'verification_pass': ('verified', 'passed', 'none'),
 'failed_check': ('verifying', 'failed', 'none'),
 'stale_code': ('verifying', 'not_started', 'none'),
 'commit_is_not_delivery': ('verified', 'passed', 'committed'),
 'unverified_merge': ('verifying', 'not_started', 'merged'),
 'claim_conflict': ('ready', 'not_started', 'none'),
 'revision_conflict': ('ready', 'not_started', 'none'),
 'handoff_resume': ('verified', 'passed', 'none'),
 'confirmed_changed': ('draft', 'not_started', 'none'),
 'interrupted_handoff': ('ready', 'not_started', 'none'),
}

CHECK_CODE = '''from pathlib import Path
import runpy,sys,xml.etree.ElementTree as ET
suite=ET.Element('testsuite',tests='1')
case=ET.SubElement(suite,'testcase',classname='sample',name='value')
ok=runpy.run_path('src/code.py')['value']==1
if not ok: ET.SubElement(case,'failure',message='Expected value=1')
path=Path('.project/artifacts/result.xml');path.parent.mkdir(exist_ok=True)
ET.ElementTree(suite).write(path,encoding='utf-8',xml_declaration=True)
raise SystemExit(0 if ok else 1)
'''


def _write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(value), encoding='utf-8')


def _seed(root):
    root.mkdir(parents=True)
    uid = lambda prefix: prefix + '-' + str(uuid4())
    ids = {name: uid(prefix) for name, prefix in [('project','PROJ'),('source','SRC'),('requirement','REQ'),('feature','FEAT')]}
    now = utc_now()
    project = {'version':1,'id':ids['project'],'revision':1,'name':'Synthetic CLI protocol Eval',
      'description':'Isolated generated fixture, not a real Agent trial','mode':'managed','stack':{'language':'python','runtime':'3.12+'},
      'commands':{'test':{'argv':[sys.executable,'check.py'],'cwd':'.','timeout_seconds':10,'result':{'kind':'junit','path':'.project/artifacts/result.xml'}}},
      'components':{'core':['src/']},'git':{'default_branch':'main'},
      'policies':{'delivery_gate':'merged','dependency_gate':'delivered','allow_manual_evidence':True},'metadata':{'created_at':now,'updated_at':now}}
    source = {'version':1,'id':ids['source'],'type':'markdown','name':'Synthetic input','location':{'path':'requirements.md'},
      'authority':'primary','adapter':{'name':'manual'},'revision':'fixture-1','captured_at':now}
    requirement = {'version':1,'id':ids['requirement'],'revision':1,'title':'Observe sample value','description':'Sample value must equal 1',
      'status':'confirmed','sources':[{'source_ref':ids['source'],'source_revision':'fixture-1','locator':'block:value'}],
      'acceptance':['Sample value equals 1'],'blockers':[],'metadata':{'created_at':now,'updated_at':now}}
    feature = {'version':1,'id':ids['feature'],'revision':1,'title':'Verify synthetic sample value','domain':'core',
      'requirement_refs':[ids['requirement']],'priority':'P0','size':'S','depends_on':[],'blockers':[],'acceptance_revision':1,
      'acceptance':[{'id':'AC-001','description':'Sample value equals 1','required':True}],
      'implementation':{'state':'not_started','evidence_level':'declared','components':{'core':['src/']},'completed':[],
       'remaining':['Run the named check'],'evidence_refs':[],'subject':None},
      'verification':{'checks':[{'id':'CHECK-001','acceptance_ref':'AC-001','required':True,'activity':'idle','command_ref':'test','testcase_refs':['sample.value'],'evidence_refs':[]}]},
      'delivery':{'records':[]},'metadata':{'created_at':now,'updated_at':now}}
    _write(root,'.project/project.yaml',project)
    _write(root,'.project/sources/registry.yaml',{'version':1,'sources':[source]})
    _write(root,f'.project/requirements/{ids["requirement"]}.yaml',requirement)
    _write(root,f'.project/features/core/{ids["feature"]}.yaml',feature)
    (root/'src').mkdir();(root/'src/code.py').write_text('value = 1\n')
    (root/'check.py').write_text(CHECK_CODE)
    (root/'requirements.md').write_text('# Synthetic source\n')
    (root/'.gitignore').write_text('.project/\n')
    return ids


class Session:
    def __init__(self, root, ids):
        self.root,self.ids,self.events = root,ids,[]

    def command(self, argv, expected=0):
        started = time.perf_counter()
        process = subprocess.run(argv,cwd=self.root,capture_output=True,timeout=30)
        event = {'argv':argv,'exit_code':process.returncode,'elapsed_ms':round((time.perf_counter()-started)*1000,3),
                 'stdout':_redact(process.stdout).decode('utf-8','replace'), 'stderr':_redact(process.stderr).decode('utf-8','replace')}
        self.events.append(event)
        if process.returncode != expected:
            raise AssertionError(f'Expected exit {expected}, got {process.returncode}: {event["stderr"]}')
        return event['stdout']

    def apm(self,*args,expected=0):
        value = json.loads(self.command([sys.executable,'-m','apm.cli','--project',str(self.root),'--json',*args],expected))
        if value['ok'] != (expected==0):
            raise AssertionError('CLI status differs from exit code')
        return value['data']

    def start(self,instance='first'):
        return self.apm('run','start',self.ids['feature'],'--agent','protocol-harness','--instance',instance,'--scope','path:src/')['run']

    def complete(self):
        f=valid(self.root);feature=deepcopy(f.features[self.ids['feature']])
        feature['revision']+=1
        feature['implementation'].update(state='complete',evidence_level='observed',completed=['Fixture code is present'],remaining=[],subject=current_subject(self.root))
        _write(self.root,f.files[feature['id']],feature)

    def verify(self,run,expected=0):
        revision=valid(self.root).features[self.ids['feature']]['revision']
        return self.apm('verify',self.ids['feature'],'--run','--run-id',run['id'],'--expected-revision',str(revision),expected=expected)


def _handoff(run):
    return {'version':1,'id':'HANDOFF-'+str(uuid4()),'run_ref':run['id'],'feature_refs':run['feature_refs'],
      'summary':'Synthetic harness handoff; not external Agent execution',**deepcopy(run['work']),
      'recommended_next':['Run named verification'],'evidence_refs':[],'context_refs':['src/code.py'],'created_at':utc_now()}


def _scenario(name,s):
    s.command(['git','init','--quiet','--initial-branch=main'])
    s.apm('doctor')
    ids=s.ids
    if name=='ready':
        return
    if name in {'complete_no_evidence','verification_pass','failed_check','stale_code','commit_is_not_delivery','unverified_merge'}:
        if name=='failed_check': (s.root/'src/code.py').write_text('value = 2\n')
        if name=='commit_is_not_delivery':
            s.command(['git','add','.'])
            s.command(['git','-c','user.name=Protocol Eval','-c','user.email=eval@example.invalid','commit','--quiet','-m','Synthetic fixture baseline'])
        run=s.start();s.complete()
        if name in {'verification_pass','failed_check','stale_code','commit_is_not_delivery'}:
            outcome=s.verify(run,5 if name=='failed_check' else 0)
            assert outcome['required_passed'] is (name!='failed_check')
        if name=='stale_code': (s.root/'src/code.py').write_text('value = 2\n')
        if name=='commit_is_not_delivery':
            revision=valid(s.root).features[ids['feature']]['revision']
            s.apm('feature','link-commit',ids['feature'],'HEAD','--run-id',run['id'],'--expected-revision',str(revision))
        if name=='unverified_merge':
            f=valid(s.root);feature=f.features[ids['feature']];ref='https://example.invalid/synthetic/pull/1'
            artifact='.project/artifacts/synthetic-merge.txt'
            (s.root/artifact).parent.mkdir(exist_ok=True);(s.root/artifact).write_text('Synthetic fixture merge declaration; no real remote merge.\n')
            identity='EVD-'+str(uuid4());subject=feature['implementation']['subject']
            evidence={'version':1,'id':identity,'feature_ref':ids['feature'],'type':'delivery','produced_by':{'run_ref':run['id'],'reviewer':'protocol-harness'},
              'result':'passed','acceptance_revision':1,'requirement_revisions':{ids['requirement']:1},'subject':subject,'command':None,
              'delivery_ref':ref,'delivery_state':'merged','artifacts':[{'path':artifact,'sha256':hashlib.sha256((s.root/artifact).read_bytes()).hexdigest()}],
              'note':'Synthetic fixture only','supersedes':[],'created_at':utc_now()}
            _write(s.root,'.project/artifacts/mr.json',{'record':{'kind':'mr','ref':ref,'state':'merged','subject':subject,'evidence_refs':[identity]},'evidence':[evidence]})
            s.apm('feature','link-mr',ids['feature'],'--file',str(s.root/'.project/artifacts/mr.json'),'--run-id',run['id'],'--expected-revision',str(feature['revision']))
        return
    if name=='claim_conflict':
        s.start();s.apm('run','start',ids['feature'],'--agent','protocol-harness','--instance','second','--scope','path:src/',expected=3)
    elif name=='revision_conflict':
        run=s.start();_write(s.root,'.project/artifacts/update.json',{'goal':'Actual harness update'})
        args=('run','update',run['id'],'--expected-revision','1','--file',str(s.root/'.project/artifacts/update.json'))
        s.apm(*args);s.apm(*args,expected=3)
        assert s.apm('run','show',run['id'])['goal']=='Actual harness update'
    elif name in {'handoff_resume','interrupted_handoff'}:
        run=s.start();work={'completed':['Created actual sample code'],'remaining':['Execute named check'],'blockers':[]}
        _write(s.root,'.project/artifacts/update.json',{'work':work})
        run=s.apm('run','update',run['id'],'--expected-revision','1','--file',str(s.root/'.project/artifacts/update.json'))['run']
        handoff=_handoff(run);_write(s.root,'.project/artifacts/handoff.json',handoff)
        if name=='interrupted_handoff':
            # Fault injection is explicitly recorded and recovered using the real CLI.
            code="""from pathlib import Path
import apm.storage as storage
from apm.operations import finish_run
from apm.facts import read_yaml
original=storage._replace
def crash(path,content):
    if path.parent.name=='runs': raise OSError('Synthetic injected interruption')
    original(path,content)
storage._replace=crash
finish_run(Path.cwd(),%r,2,handoff=read_yaml(Path('.project/artifacts/handoff.json')))
""" % run['id']
            s.command([sys.executable,'-c',code],1)
            assert valid(s.root).runs[run['id']]['status']=='active'
            s.apm('doctor',expected=5);s.apm('doctor','--recover')
        else:
            s.apm('run','finish',run['id'],'--expected-revision','2','--handoff-file',str(s.root/'.project/artifacts/handoff.json'))
        state=s.apm('status');assert not state['claims']
        shown=s.apm('feature','show',ids['feature'])
        assert shown['handoff']['remaining']==work['remaining']
        if name=='handoff_resume':
            second=s.start('second');s.complete();s.verify(second)
            s.apm('run','finish',second['id'],'--expected-revision','1')
            assert not s.apm('status')['claims']
    elif name=='confirmed_changed':
        run=s.start()
        record={'key':'value','title':'Observe sample value','description':'Sample value must equal 1','acceptance':['Sample value equals 1']}
        path=s.root/'requirements.md';path.write_text('```apm-requirement\n'+dump_yaml(record)+'```\n')
        registry=read_yaml(s.root/'.project/sources/registry.yaml');source=registry['sources'][0]
        source['adapter']['name']='markdown';source['revision']='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
        _write(s.root,'.project/sources/registry.yaml',registry)
        f=valid(s.root);req=deepcopy(f.requirements[ids['requirement']]);req['sources'][0]['source_revision']=source['revision'];_write(s.root,f.files[req['id']],req)
        record['description']='Sample must follow a newly reviewed rule';path.write_text('```apm-requirement\n'+dump_yaml(record)+'```\n')
        response=s.apm('source','sync',ids['source']);assert valid(s.root).requirements[ids['requirement']]['status']=='confirmed'
        _write(s.root,'.project/artifacts/proposal.json',response['proposal'])
        s.apm('source','sync',ids['source'],'--apply',str(s.root/'.project/artifacts/proposal.json'),'--run-id',run['id'],'--reviewer','protocol-harness','--note','Reviewed synthetic source change')
        assert valid(s.root).requirements[ids['requirement']]['status']=='changed'


def run_suite(output,repetitions=1):
    output=Path(output).absolute()
    if not 1<=repetitions<=10: raise ValueError('Repetitions must be 1..10')
    if output.exists() or output.is_symlink() or output.resolve()!=output:
        raise ValueError('Use a new output directory without symlinks')
    output.mkdir(parents=True)
    rows=[];started=time.perf_counter()
    for repetition in range(1,repetitions+1):
        for name,expected in CASES.items():
            root=output/'contexts'/f'{name}-{repetition}'
            ids=_seed(root);s=Session(root,ids);case_start=time.perf_counter();error=None;actual=None
            try:
                _scenario(name,s)
                shown=s.apm('feature','show',ids['feature'])
                actual={key:shown[key] for key in ['lifecycle','verification','delivery']}
                assert tuple(actual.values())==expected,(expected,actual)
                s.apm('doctor')
            except Exception as exc:
                error=_redact(str(exc).encode()).decode('utf-8','replace')
            relative=f'transcripts/{name}-{repetition}.json'
            _write(output,relative,{'kind':'synthetic_cli','events':s.events})
            row={'case_id':name,'repetition':repetition,'kind':'synthetic_cli','result':'failed' if error else 'passed','error':error,
                 'expected':dict(zip(['lifecycle','verification','delivery'],expected)),'actual':actual,
                 'feature_ref':ids['feature'],'context':root.relative_to(output).as_posix(),
                 'elapsed_ms':round((time.perf_counter()-case_start)*1000,3),
                 'transcript':{'path':relative,'sha256':hashlib.sha256((output/relative).read_bytes()).hexdigest()}}
            rows.append(row)
            _write(root,'.project/artifacts/questions.json',{'case_id':name,'repetition':repetition,'feature_ref':ids['feature'],
               'questions':['What are lifecycle, verification and delivery?','What remains and why?','What evidence supports the answer?'],
               'notice':'Synthetic context for observation, not a real product delivery.'})
    passed=sum(row['result']=='passed' for row in rows)
    report={'version':1,'suite_id':str(uuid4()),'kind':'synthetic_cli','created_at':utc_now(),'cases':rows,
      'summary':{'total':len(rows),'passed':passed,'failed':len(rows)-passed,'skipped':0},
      'metrics':{'cli_suite_elapsed_ms':round((time.perf_counter()-started)*1000,3),'tokens':None,'agent_recovery_ms':None,
       'clarifications':None,'skill_baseline_comparison':{'status':'not_run','reason':'No actual paired Agent observations'}},
      'cross_agent':{'status':'not_run','tools':[],'reason':'Protocol harness roles are not external Agent executions'}}
    _write(output,'report.json',report)
    suite=ET.Element('testsuite',name='apm.protocol_eval',tests=str(len(rows)),failures=str(len(rows)-passed),errors='0',skipped='0')
    for row in rows:
        case=ET.SubElement(suite,'testcase',classname='evals.protocol',name=f'{row["case_id"]}-{row["repetition"]}',time=str(row['elapsed_ms']/1000))
        if row['result']!='passed': ET.SubElement(case,'failure',message=row['error'] or 'Case failed')
    ET.ElementTree(suite).write(output/'junit.xml',encoding='utf-8',xml_declaration=True)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--repetitions',type=int,default=1)
    args=parser.parse_args(argv)
    try: report=run_suite(args.output,args.repetitions)
    except (ValueError,OSError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)}));return 2
    print(json.dumps({'ok':report['summary']['failed']==0,'kind':report['kind'],'summary':report['summary'],'output':str(Path(args.output).absolute())}))
    return 0 if report['summary']['failed']==0 and report['summary']['total'] else 1


if __name__=='__main__': raise SystemExit(main())
