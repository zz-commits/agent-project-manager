from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pytest

from apm.facts import dump_yaml, read_yaml, validate_project
from apm.state import active_claims, derive, utc_now
from evals.run import CASES, run_suite
from evals.score import main as score_main, score
from .conftest import REPO


@pytest.fixture(scope='module')
def suite(tmp_path_factory):
    output=tmp_path_factory.mktemp('eval')/'suite'
    result=run_suite(output)
    assert result['summary']=={'total':12,'passed':12,'failed':0,'skipped':0}, result
    return output,result


def test_actual_cli_cases_and_fresh_results(suite):
    output,report=suite
    assert {r['case_id'] for r in report['cases']}==set(CASES)
    xml=ET.parse(output/'junit.xml').getroot()
    assert xml.attrib['tests']=='12' and len(xml.findall('testcase'))==12
    assert not xml.findall('.//failure') and not xml.findall('.//skipped')
    for row in report['cases']:
        facts=validate_project(output/row['context'])
        assert not facts.errors
        current=derive(facts,utc_now())['features'][0]
        assert {k:current[k] for k in row['expected']}==row['actual']==row['expected']
        path=output/row['transcript']['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==row['transcript']['sha256']
        events=read_yaml(path)['events']
        assert events and all(e['elapsed_ms']>=0 and e['argv'] for e in events)
        if row['case_id'] in {'claim_conflict','revision_conflict'}:
            assert any(e['exit_code']==3 for e in events)
        if row['case_id']=='interrupted_handoff':
            assert any('--recover' in e['argv'] for e in events)


def test_skill_references_resolve_and_commands_are_current():
    skill=REPO/'skills/agent-project-manager/SKILL.md'
    text=skill.read_text()
    assert text.startswith('---\nname: agent-project-manager\n')
    assert 'description:' in text.split('---')[1]
    links=re.findall(r'\]\((references/[^)]+)\)',text)
    assert set(links)=={'references/facts.md','references/commands.md','references/handoff.md'}
    for link in links: assert (skill.parent/link).is_file()
    # Check the documented protocol's actual parser, rather than accept invented commands.
    from apm.cli import make_parser
    parsed=make_parser().parse_args(['run','start','FEATURE','--agent','actual','--instance','unique','--scope','path:src/'])
    assert parsed.agent=='actual' and parsed.scope=='path:src/'
    parsed=make_parser().parse_args(['run','finish','RUN','--expected-revision','2','--handoff-file','handoff.json'])
    assert parsed.expected_revision==2


def test_documented_run_verify_handoff_workflow(suite):
    output,report=suite
    row=next(r for r in report['cases'] if r['case_id']=='handoff_resume')
    facts=validate_project(output/row['context'])
    assert len(facts.runs)==2 and all(r['status']=='completed' for r in facts.runs.values())
    handoff=next(iter(facts.handoffs.values()))
    run=facts.runs[handoff['run_ref']]
    assert all(handoff[key]==run['work'][key] for key in ['completed','remaining','blockers'])
    assert row['actual']['verification']=='passed' and facts.evidence
    assert not active_claims(facts)


def test_report_keeps_agent_trial_unmeasured(suite):
    _,report=suite
    assert report['cross_agent']['status']=='not_run' and report['cross_agent']['tools']==[]
    assert report['metrics']['cli_suite_elapsed_ms']>0
    assert report['metrics']['tokens'] is report['metrics']['agent_recovery_ms'] is report['metrics']['clarifications'] is None
    assert report['metrics']['skill_baseline_comparison']['status']=='not_run'
    for row in report['cases']: assert row['kind']=='synthetic_cli'
    source=(REPO/'docs/pilot-report.md').read_text()
    assert '两个 Check 保留未验证' in source
    assert (REPO/'docs/pilot-guide.md').is_file()


def submission(tmp_path,suite,conditions=('with_skill',)):
    output,report=suite
    transcript=tmp_path/'transcript.txt'
    transcript.write_text('Explicit synthetic test of reviewer declarations; NOT an actual Agent observation.\n')
    artifact={'path':transcript.name,'sha256':hashlib.sha256(transcript.read_bytes()).hexdigest()}
    rows=[]
    for condition in conditions:
        for case in report['cases']:
            rows.append({'case_id':case['case_id'],'repetition':case['repetition'],'condition':condition,
             'agent':{'tool':'scoring-test-fixture','version':'test-only','instance_id':'test-only'},
             'answers':deepcopy(case['expected']),'transcript':deepcopy(artifact),'reviewer':'pytest fixture',
             'note':'Synthetic scorer input tests; no real trial claim','elapsed_ms':None,'token_usage':None,'clarifications':None})
    data={'version':1,'suite_id':report['suite_id'],'suite_sha256':hashlib.sha256((output/'report.json').read_bytes()).hexdigest(),'observations':rows}
    path=tmp_path/'submission.json';path.write_text(dump_yaml(data))
    return path,data


def test_scoring_complete_coverage_without_identity_claim(tmp_path,suite):
    path,data=submission(tmp_path,suite)
    result=score(suite[0]/'report.json',path)
    assert result['summary']['passed']==12 and result['coverage_complete']
    assert result['cross_agent_handoff']=='not_assessed' and result['comparison']==[]
    assert 'no automated provider' in result['identity_provenance']
    assert score_main(['--suite',str(suite[0]/'report.json'),'--submission',str(path),'--output',str(tmp_path/'score.json')])==0


def test_incomplete_or_wrong_answer_never_passes(tmp_path,suite):
    path,data=submission(tmp_path,suite)
    data['observations']=data['observations'][:1]
    path.write_text(dump_yaml(data))
    result=score(suite[0]/'report.json',path)
    assert result['all_submitted_answers_passed'] and not result['coverage_complete']
    assert score_main(['--suite',str(suite[0]/'report.json'),'--submission',str(path),'--output',str(tmp_path/'partial.json')])==5
    data['observations'][0]['answers']['lifecycle']='delivered';path.write_text(dump_yaml(data))
    result=score(suite[0]/'report.json',path)
    assert not result['all_submitted_answers_passed'] and result['summary']['incorrect_completion']==1


@pytest.mark.parametrize('damage', ['suite_sha','duplicate','unknown_case','no_observations','missing_transcript','empty_transcript','changed_transcript','script_identity','negative_time','boolean_tokens','missing_field','unsafe_path','nonstring_answer'])
def test_scorer_rejects_invalid_observations(tmp_path,suite,damage):
    path,data=submission(tmp_path,suite);row=data['observations'][0]
    if damage=='suite_sha': data['suite_sha256']='0'*64
    elif damage=='duplicate': data['observations'].append(deepcopy(row))
    elif damage=='unknown_case': row['case_id']='unknown'
    elif damage=='no_observations': data['observations']=[]
    elif damage=='missing_transcript': (tmp_path/'transcript.txt').unlink()
    elif damage=='empty_transcript':
        (tmp_path/'transcript.txt').write_bytes(b'');row['transcript']['sha256']=hashlib.sha256(b'').hexdigest()
    elif damage=='changed_transcript': (tmp_path/'transcript.txt').write_text('Changed')
    elif damage=='script_identity': row['agent']['tool']='protocol-harness'
    elif damage=='negative_time': row['elapsed_ms']=-1
    elif damage=='boolean_tokens': row['token_usage']={'input':True,'output':1}
    elif damage=='missing_field': del row['note']
    elif damage=='unsafe_path': row['transcript']['path']='../transcript.txt'
    elif damage=='nonstring_answer': row['answers']['lifecycle']=[]
    path.write_text(dump_yaml(data))
    with pytest.raises(ValueError): score(suite[0]/'report.json',path)


def test_scorer_requires_undamaged_suite_transcripts(tmp_path,suite):
    path,data=submission(tmp_path,suite)
    damaged=tmp_path/'damaged';damaged.mkdir()
    # Copy report alone, without its bound transcripts.
    target=damaged/'report.json';target.write_bytes((suite[0]/'report.json').read_bytes())
    with pytest.raises(ValueError): score(target,path)


def test_paired_measurements_need_complete_correct_data(tmp_path,suite):
    path,data=submission(tmp_path,suite,('with_skill','without_skill'))
    result=score(suite[0]/'report.json',path)
    assert result['comparison'][0]['status']=='not_measured'
    for row in data['observations']: row['elapsed_ms']=100 if row['condition']=='with_skill' else 200
    path.write_text(dump_yaml(data));result=score(suite[0]/'report.json',path)
    assert result['comparison'][0]['status']=='measured'
    assert result['comparison'][0]['with_skill_elapsed_ms']==1200 and result['comparison'][0]['without_skill_elapsed_ms']==2400
    data['observations'][0]['answers']['lifecycle']='developing';path.write_text(dump_yaml(data))
    assert score(suite[0]/'report.json',path)['comparison'][0]['status']=='not_measured'


def test_eval_refuses_zero_cases_and_existing_outputs(tmp_path,monkeypatch):
    import evals.run as module
    with pytest.raises(ValueError): run_suite(tmp_path/'bad',0)
    tmp_path.joinpath('existing').mkdir()
    with pytest.raises(ValueError): run_suite(tmp_path/'existing')
    monkeypatch.setattr(module,'CASES',{})
    assert module.main(['--output',str(tmp_path/'empty')])==1
    assert read_yaml(tmp_path/'empty/report.json')['summary']['total']==0
