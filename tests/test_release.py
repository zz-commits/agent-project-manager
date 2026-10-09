from copy import deepcopy
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
import zipfile

import pytest
from ruamel.yaml import YAML

from cli.release import blockers, junit_summary, package_assets, publish, version_and_target

TARGET = 'a' * 40


def candidates(folder, private=False):
    folder.mkdir(exist_ok=True)
    with zipfile.ZipFile(folder/'agent_project_manager-0.1.0-py3-none-any.whl', 'w') as z:
        z.writestr('agent_project_manager-0.1.0.dist-info/METADATA', 'Name: agent-project-manager\nVersion: 0.1.0\n')
        z.writestr('apm/__init__.py', '__version__="0.1.0"')
        for i in range(9):z.writestr(f'apm/schemas/v1/{i}.json', '{}')
    with tarfile.open(folder/'agent_project_manager-0.1.0.tar.gz', 'w:gz') as t:
        names={'PKG-INFO':b'Name: agent-project-manager\nVersion: 0.1.0\n'}
        if private:names['.project/runs/private.yaml']=b'private'
        for name,raw in names.items():
            item=tarfile.TarInfo('agent_project_manager-0.1.0/'+name);item.size=len(raw);t.addfile(item,io.BytesIO(raw))
    return package_assets(folder,'0.1.0')


class FakeGitHub:
    """Isolated transport fixture; no real Agent or delivery records."""
    def __init__(self, folder, assets, *, existing=0, digest=True, corrupt=False):
        self.folder=folder;self.assets=assets;self.corrupt=corrupt;self.calls=[]
        self.state={'main_sha':TARGET,'tag_commit':None,'release':None}
        if existing:
            self.create('v0.1.0',TARGET,'fixture')
            for asset in assets[:existing]:self.upload('v0.1.0',folder/asset['name'])
            if not digest:
                for asset in self.state['release']['assets']:asset['digest']=None
        self.calls=[]

    def snapshot(self,tag):return deepcopy(self.state)
    def create(self,tag,target,notes):
        self.calls.append(('create',tag))
        self.state['release']={'id':1,'tag_name':tag,'target_commitish':target,'draft':True,'published_at':None,'assets':[],'html_url':'https://example.invalid/fixture'}
        return deepcopy(self.state['release'])
    def upload(self,tag,file):
        self.calls.append(('upload',file.name))
        raw=file.read_bytes();self.state['release']['assets'].append({'name':file.name,'size':len(raw),'digest':'sha256:'+hashlib.sha256(raw).hexdigest(),'state':'uploaded'})
    def download(self,tag,folder):
        self.calls.append(('download',tag))
        for asset in self.state['release']['assets']:
            raw=(self.folder/asset['name']).read_bytes()
            (folder/asset['name']).write_bytes(b'x'*len(raw) if self.corrupt else raw)
    def api(self,path,payload):
        self.calls.append(('publish',path));self.state['release'].update(draft=False,published_at='2026-10-09T00:00:00Z');self.state['tag_commit']=TARGET


def plan(assets):return {'tag':'v0.1.0','target_sha':TARGET,'assets':assets,'tests':{'passed':3}}


@pytest.mark.parametrize('tag',['v1','0.1.0','v0.1.0-rc.1','v01.1.0','v0.1.0;echo bad','../v0.1.0'])
def test_invalid_tag_rejected(tmp_path,tag):
    (tmp_path/'pyproject.toml').write_text('[project]\nversion="0.1.0"\n')
    with pytest.raises(ValueError):version_and_target(tmp_path,tag,TARGET)


def test_version_and_actual_subject_must_match(tmp_path):
    (tmp_path/'pyproject.toml').write_text('[project]\nversion="0.1.0"\n')
    def git(*args):return subprocess.run(['git','-C',str(tmp_path),*args],capture_output=True,check=True).stdout.decode().strip()
    git('init','-q');git('add','pyproject.toml');git('-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
    sha=git('rev-parse','HEAD');assert version_and_target(tmp_path,'v0.1.0',sha)==('0.1.0','v0.1.0')
    for tag,target in [('v0.1.1',sha),('v0.1.0','main')]:
        with pytest.raises(ValueError):version_and_target(tmp_path,tag,target)
    (tmp_path/'pyproject.toml').write_text('[project]\nversion="0.1.0"\n# changed\n')
    with pytest.raises(ValueError):version_and_target(tmp_path,'v0.1.0',sha)


@pytest.mark.parametrize('body',['','<failure/>','<error/>','<skipped/>','<!DOCTYPE x>'])
def test_incomplete_test_results_rejected(tmp_path,body):
    p=tmp_path/'tests.xml';p.write_text('<testsuite>'+('<testcase>'+body+'</testcase>' if body else '')+'</testsuite>')
    with pytest.raises(ValueError):junit_summary(p)


def test_source_archive_rejects_private_project_facts(tmp_path):
    with pytest.raises(ValueError,match='private'):candidates(tmp_path,private=True)


def test_candidate_checksums_cannot_be_rewritten_to_hide_changes(tmp_path):
    candidates(tmp_path);(tmp_path/'SHA256SUMS').write_text('wrong\n')
    with pytest.raises(ValueError,match='checksum'):package_assets(tmp_path,'0.1.0')


def test_checksum_symlink_is_rejected_without_overwriting_target(tmp_path):
    folder=tmp_path/'candidate';candidates(folder);outside=tmp_path/'outside.txt';outside.write_text('keep')
    (folder/'SHA256SUMS').unlink();(folder/'SHA256SUMS').symlink_to(outside)
    with pytest.raises(ValueError,match='symlink'):package_assets(folder,'0.1.0')
    assert outside.read_text()=='keep'


@pytest.mark.parametrize('change',[{'main_sha':'b'*40},{'tag_commit':'b'*40},{'published':True},{'draft_target':'b'*40}])
def test_publish_preconditions_prevent_all_mutations(tmp_path,change):
    assets=candidates(tmp_path);client=FakeGitHub(tmp_path,assets,existing=1)
    if 'published' in change:client.state['release']['draft']=False
    elif 'draft_target' in change:client.state['release']['target_commitish']=change['draft_target']
    else:client.state.update(change)
    with pytest.raises(ValueError):publish(client,plan(assets),tmp_path)
    assert client.calls==[]


@pytest.mark.parametrize('change',[{'name':'foreign.zip'},{'digest':'sha256:wrong'},{'size':1},{'state':'new'}])
def test_foreign_or_different_assets_are_never_overwritten(tmp_path,change):
    assets=candidates(tmp_path);client=FakeGitHub(tmp_path,assets,existing=1);client.state['release']['assets'][0].update(change)
    with pytest.raises(ValueError):publish(client,plan(assets),tmp_path)
    assert client.calls==[] and client.state['release']['draft']


def test_successful_publish_verifies_all_downloads_and_tag(tmp_path):
    assets=candidates(tmp_path);client=FakeGitHub(tmp_path,assets)
    result=publish(client,plan(assets),tmp_path)
    assert result['published'] and result['download_verified'] and result['target_sha']==TARGET
    assert len([c for c in client.calls if c[0]=='upload'])==3
    assert client.calls[-1][0]=='publish'


def test_matching_draft_resumes_only_missing_assets(tmp_path):
    assets=candidates(tmp_path);client=FakeGitHub(tmp_path,assets,existing=1)
    publish(client,plan(assets),tmp_path)
    uploads=[c[1] for c in client.calls if c[0]=='upload']
    assert uploads==[a['name'] for a in assets[1:]] and client.calls[0][0]=='download'


@pytest.mark.parametrize('existing,digest',[(0,True),(1,False)])
def test_download_mismatch_keeps_release_unpublished(tmp_path,existing,digest):
    assets=candidates(tmp_path);client=FakeGitHub(tmp_path,assets,existing=existing,digest=digest,corrupt=True)
    with pytest.raises(ValueError,match='bytes'):publish(client,plan(assets),tmp_path)
    assert not any(c[0]=='publish' for c in client.calls) and client.state['release']['draft']
    if existing:assert not any(c[0]=='upload' for c in client.calls)


def test_workflow_publishes_only_explicit_manual_requests():
    workflow=YAML(typ='safe').load((Path(__file__).parents[1]/'.github/workflows/release.yml').read_text())
    assert workflow['on']['workflow_dispatch']['inputs']['dry_run']['default'] is True
    assert workflow['permissions']=={'contents':'read'}
    job=workflow['jobs']['publish'];assert job['permissions']=={'contents':'write'}
    assert "github.event_name == 'workflow_dispatch'" in job['if'] and 'inputs.dry_run == false' in job['if']
    for job in workflow['jobs'].values():
        for step in job['steps']:assert '${{ inputs.' not in step.get('run','')
