"""Score reviewed observations; transcript hashes do not authenticate Agent identities."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from apm.facts import dump_yaml, read_yaml, safe_path
from apm.state import utc_now


def _number(value,name,integer=False):
    if value is None: return
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or (integer and not isinstance(value,int)):
        raise ValueError(name+' must be a nonnegative measured number or null')


def score(suite_file,submission_file):
    suite_file,submission_file=Path(suite_file).resolve(),Path(submission_file).resolve()
    suite=read_yaml(suite_file);submission=read_yaml(submission_file)
    if suite.get('version')!=1 or suite.get('kind')!='synthetic_cli' or not suite.get('cases'):
        raise ValueError('A nonempty synthetic CLI suite is required')
    if not all(row['result']=='passed' and row['actual']==row['expected'] for row in suite['cases']):
        raise ValueError('Suite has failures or unavailable gold observations')
    if not isinstance(submission,dict) or set(submission)!={'version','suite_id','suite_sha256','observations'}:
        raise ValueError('Expected complete observation submission')
    if (submission['version']!=1 or submission['suite_id']!=suite['suite_id']
        or submission['suite_sha256']!=hashlib.sha256(suite_file.read_bytes()).hexdigest()):
        raise ValueError('Submission is bound to a different suite snapshot')
    rows=submission['observations']
    if not isinstance(rows,list) or not rows: raise ValueError('No Agent observations; cannot score a PASS')
    cases={(row['case_id'],row['repetition']):row for row in suite['cases']}
    if len(cases)!=len(suite['cases']): raise ValueError('Duplicate suite cases')
    # Validate the local suite transcript too; do not grade against a damaged bundle.
    for row in cases.values():
        artifact=row['transcript'];path=safe_path(suite_file.parent,artifact['path'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=artifact['sha256']:
            raise ValueError('Suite transcript is missing or changed')
    seen=set();outcomes=[];groups={}
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'case_id','repetition','condition','agent','answers','transcript','reviewer','note','elapsed_ms','token_usage','clarifications'}:
            raise ValueError('Observation fields do not match the submission protocol')
        agent=row['agent']
        if not isinstance(agent,dict) or set(agent)!={'tool','version','instance_id'} or any(not isinstance(v,str) or not v.strip() for v in agent.values()):
            raise ValueError('Actual tool/version/instance declarations are required')
        if agent['tool'].lower() in {'protocol-harness','protocol_harness','synthetic','fixture'}:
            raise ValueError('Script roles are not actual Agent observations')
        if row['condition'] not in {'with_skill','without_skill'}: raise ValueError('Unknown observation condition')
        if any(not isinstance(row[key],str) or not row[key].strip() for key in ['reviewer','note']):
            raise ValueError('Reviewer and provenance note are required')
        identity=(row['case_id'],row['repetition'])
        if identity not in cases: raise ValueError('Unknown case/repetition')
        group=(agent['tool'],agent['version'],agent['instance_id'],row['condition'])
        key=(*group,*identity)
        if key in seen: raise ValueError('Duplicate Agent case observation')
        seen.add(key)
        artifact=row['transcript']
        if not isinstance(artifact,dict) or set(artifact)!={'path','sha256'}: raise ValueError('A transcript artifact is required')
        path=safe_path(submission_file.parent,artifact['path'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=artifact['sha256']:
            raise ValueError('Agent transcript is missing or changed')
        if path.stat().st_size==0: raise ValueError('Empty transcript cannot substantiate observation')
        _number(row['elapsed_ms'],'elapsed_ms');_number(row['clarifications'],'clarifications',True)
        tokens=row['token_usage']
        if tokens is not None:
            if not isinstance(tokens,dict) or set(tokens)!={'input','output'}: raise ValueError('token_usage must be measured input/output or null')
            for value in tokens.values(): _number(value,'token_usage',True)
        expected=cases[identity]['expected'];answers=row['answers']
        if not isinstance(answers,dict) or set(answers)!=set(expected): raise ValueError('Answers must contain lifecycle/verification/delivery')
        if any(not isinstance(value,str) for value in answers.values()): raise ValueError('Answers must be strings')
        mismatches={name:{'expected':value,'actual':answers[name]} for name,value in expected.items() if answers[name]!=value}
        result={'case_id':row['case_id'],'repetition':row['repetition'],'condition':row['condition'],'agent':agent,
                'passed':not mismatches,'mismatches':mismatches,'elapsed_ms':row['elapsed_ms'],'token_usage':tokens,'clarifications':row['clarifications']}
        outcomes.append(result);groups.setdefault(group,[]).append(result)
    complete=[key for key,values in groups.items() if len(values)==len(cases)]
    comparison=[]
    for key in complete:
        if key[-1]!='with_skill': continue
        partner=(*key[:-1],'without_skill')
        if partner not in complete: continue
        with_rows,without_rows=groups[key],groups[partner]
        # Failed or missing measurements cannot support an efficiency claim.
        measured=all(r['passed'] and r['elapsed_ms'] is not None for r in [*with_rows,*without_rows])
        comparison.append({'agent':dict(zip(['tool','version','instance_id'],key[:-1])),
            'status':'measured' if measured else 'not_measured',
            'with_skill_elapsed_ms':sum(r['elapsed_ms'] for r in with_rows) if measured else None,
            'without_skill_elapsed_ms':sum(r['elapsed_ms'] for r in without_rows) if measured else None})
    incorrect_completion=sum(row['mismatches'].get('lifecycle',{}).get('actual') in {'delivered','deployed'} for row in outcomes)
    return {'version':1,'kind':'reviewed_agent_submissions','suite_id':suite['suite_id'],'scored_at':utc_now(),
      'summary':{'observations':len(outcomes),'passed':sum(r['passed'] for r in outcomes),'failed':sum(not r['passed'] for r in outcomes),
                 'complete_conditions':len(complete),'incorrect_completion':incorrect_completion},
      'observations':outcomes,'comparison':comparison,
      'all_submitted_answers_passed':all(r['passed'] for r in outcomes),
      'coverage_complete':bool(complete) and len(complete)==len(groups),
      'cross_agent_handoff':'not_assessed',
      'identity_provenance':'Reviewer declarations and hashed files; no automated provider identity authentication'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',required=True);parser.add_argument('--submission',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    try:
        output=Path(args.output).absolute()
        if output.exists() or output.is_symlink() or output.resolve()!=output: raise ValueError('Use a new nonsymlink output file')
        result=score(args.suite,args.submission)
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(dump_yaml(result))
    except (ValueError,OSError,KeyError,TypeError,AttributeError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)}));return 2
    passed=result['all_submitted_answers_passed'] and result['coverage_complete']
    print(json.dumps({'ok':passed,'summary':result['summary'],'cross_agent_handoff':'not_assessed'}))
    return 0 if passed else 5


if __name__=='__main__': raise SystemExit(main())
