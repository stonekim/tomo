import json
import pytest
from copy import deepcopy
from fastapi.testclient import TestClient
from tomo.platform.api import create_app
from tomo.platform.config import Settings
from tomo.platform.rules import RuleRegistry
from tomo.platform.models import ModelResult, UNKNOWN_USAGE
from tomo.platform.errors import PlatformError
from tomo.game import router, register_game_rules
from tomo.game.engine import initial_state, transition, local_agents, validate_game


@pytest.fixture
def env(tmp_path):
    rules = RuleRegistry(); register_game_rules(rules)
    settings = Settings(database=str(tmp_path/'game.sqlite3'))
    app = create_app(settings, rule_registry=rules, domain_routers=[router])
    client = TestClient(app)
    r = client.post('/api/v1/auth/register', json={'username':'alice','password':'correct-password-123'})
    assert r.status_code == 201
    headers = {'Authorization':'Bearer '+r.json()['token']}
    return app, client, headers, settings


def new(env, engine='local'):
    app,c,h,_=env
    r=c.post('/api/v1/game/saves',headers=h,json={'scenario':'我收到另一份工作邀请，仍放不下旧团队。','engine':engine})
    assert r.status_code==201,r.text
    return r.json()


def action(env,save,branch,revision,tool,key=None):
    _,c,h,_=env
    return c.post(f'/api/v1/game/saves/{save}/branches/{branch}/actions',headers=h,json={'expected_revision':revision,'idempotency_key':key or f'turn-key-{revision}','action':tool})


def test_complete_story_and_actual_event_causes(env):
    r=new(env);s,b=r['save']['id'],r['branch']['id']
    tools=[{'action':'inspect','item':'notebook'},{'action':'move','destination':'cafe'},{'action':'talk','target':'mira'}, {'action':'decide','choice':'accept'},{'action':'finish'}]
    for i,t in enumerate(tools):
        response=action(env,s,b,i,t);assert response.status_code==200,response.text
    result=response.json();assert result['ending']['code']=='collaborative_jump'
    ids={e['id'] for e in result['branch']['events']}
    assert result['ending']['causes'] and all(c['event_id'] in ids for c in result['ending']['causes'])
    assert len(result['branch']['state']['characters'])==4 and len(result['branch']['state']['items'])==3
    assert result['agent_mode']=='local'
    assert action(env,s,b,5,{'action':'wait'}).status_code==422


def test_fork_changes_decision_and_preserves_prefix(env):
    app,c,h,_=env;r=new(env);s,b=r['save']['id'],r['branch']['id']
    assert action(env,s,b,0,{'action':'wait'}).status_code==200
    first=action(env,s,b,1,{'action':'decide','choice':'stay'}).json()
    assert action(env,s,b,2,{'action':'finish'}).json()['ending']['code']=='stable_plan'
    fork=c.post(f'/api/v1/game/saves/{s}/branches/{b}/fork',headers=h,json={'at_sequence':1,'idempotency_key':'fork-decision-1'})
    assert fork.status_code==201;child=fork.json()['branch'];assert child['events'][0]['id']==first['branch']['events'][0]['id']
    assert action(env,s,child['id'],1,{'action':'decide','choice':'accept'},'other-key-1').status_code==200
    ending=action(env,s,child['id'],2,{'action':'finish'},'other-key-2').json()['ending'];assert ending['code']=='solo_jump'
    assert c.get(f'/api/v1/game/saves/{s}/branches/{b}',headers=h).json()['ending']['code']=='stable_plan'


def test_idempotency_revision_and_invalid_tools_no_write(env):
    app,c,h,_=env;r=new(env);s,b=r['save']['id'],r['branch']['id']
    for tool in [{'action':'take','item':'key'},{'action':'give','item':'notebook','target':'chen'},{'action':'move','destination':'studio'},{'action':'talk','target':'mira'}]:
        assert action(env,s,b,0,tool).status_code==422
    result=action(env,s,b,0,{'action':'wait'},'retry-key-1');assert result.status_code==200
    retry=action(env,s,b,0,{'action':'wait'},'retry-key-1');assert retry.status_code==200 and retry.json()==result.json()
    assert action(env,s,b,0,{'action':'decide','choice':'stay'},'retry-key-1').status_code==409
    assert action(env,s,b,0,{'action':'wait'},'stale-key-1').status_code==409
    assert c.get(f'/api/v1/game/saves/{s}/branches/{b}',headers=h).json()['branch']['revision']==1


def test_owner_isolation_restart_and_no_cross_domain(env):
    app,c,h,settings=env;r=new(env);s,b=r['save']['id'],r['branch']['id']
    action(env,s,b,0,{'action':'take','item':'notebook'})
    r=c.post('/api/v1/auth/register',json={'username':'other','password':'correct-password-123'});other={'Authorization':'Bearer '+r.json()['token']}
    assert c.get(f'/api/v1/game/saves/{s}/branches',headers=other).status_code==404
    assert c.post(f'/api/v1/game/saves/{s}/branches/{b}/fork',headers=other,json={'at_sequence':0,'idempotency_key':'foreign-fork'}).status_code==404
    rules=RuleRegistry();register_game_rules(rules)
    restarted=TestClient(create_app(settings,rule_registry=rules,domain_routers=[router]))
    assert restarted.get(f'/api/v1/game/saves/{s}/branches/{b}',headers=h).json()['branch']['state']['items']['notebook']=='player'
    assert c.get(f'/api/v1/game/saves/{s}/branches').status_code==401


def test_state_forgery_and_generic_provenance_cannot_bypass_rules(env):
    app,c,h,_=env;r=new(env);s,b=r['save']['id'],r['branch']['id'];old=r['branch']['state']
    player={'actor':'player','action':'wait'};agents=local_agents(old,player);state,_=transition(old,player,agents)
    proposal={'expected_revision':0,'idempotency_key':'forged-request','type':'game.turn','payload':{'player':player,'agents':agents,'request_key':'forged-request','expected_revision':0,'mode':'real','proof':'not-signed'},'state':state,'causes':[]}
    with pytest.raises(PlatformError):app.state.store.append_event(app.state.auth.authenticate(h['Authorization'].split()[1]),s,b,proposal)
    assert app.state.store.get_branch(app.state.auth.authenticate(h['Authorization'].split()[1]),s,b)['revision']==0


def test_max_turns_produces_finite_ending(env):
    r=new(env);s,b=r['save']['id'],r['branch']['id']
    for i in range(8):
        response=action(env,s,b,i,{'action':'wait'});assert response.status_code==200
    assert response.json()['ending']['code']=='undecided'


class StructuredMock:
    mode='mock';name='test-tools-mock'
    def __init__(self,text='{"actions":[]}'):self.text=text;self.calls=0
    def complete(self,messages):
        self.calls+=1;assert 'goals' in messages[-1]['content']
        return ModelResult(self.text,UNKNOWN_USAGE.copy())


def test_model_tools_audit_and_replay_no_duplicate_call(env):
    app,c,h,_=env;adapter=StructuredMock();app.state.models.adapter=adapter
    r=new(env,'model');s,b=r['save']['id'],r['branch']['id']
    response=action(env,s,b,0,{'action':'wait'});assert response.status_code==200 and response.json()['agent_mode']=='mock'
    assert action(env,s,b,0,{'action':'wait'}).status_code==200 and adapter.calls==1
    owner=app.state.auth.authenticate(h['Authorization'].split()[1]);audit=app.state.store.list_audit(owner,s)
    assert audit[0]['mode']=='mock' and audit[0]['usage']['input_tokens'] is None


@pytest.mark.parametrize('text',['not json','{"actions":[{"actor":"player","action":"decide","choice":"accept"}]}','{"actions":[{"actor":"mira","action":"take","item":"notebook"}]}','{"actions":[{"actor":"lin","action":"wait"},{"actor":"lin","action":"wait"}]}'])
def test_model_invalid_or_impossible_tools_leave_world_unchanged(env,text):
    app,c,h,_=env;app.state.models.adapter=StructuredMock(text)
    r=new(env,'model');s,b=r['save']['id'],r['branch']['id'];response=action(env,s,b,0,{'action':'wait'})
    assert response.status_code in (422,503)
    assert c.get(f'/api/v1/game/saves/{s}/branches/{b}',headers=h).json()['branch']['revision']==0


def test_model_disabled_does_not_fake_call(env):
    _,c,h,_=env
    assert c.post('/api/v1/game/saves',headers=h,json={'scenario':'另一份工作','engine':'model'}).status_code==503


def test_inventory_transfer_and_decision_immutable():
    state=initial_state('another job');state,_=transition(state,{'actor':'player','action':'take','item':'notebook'},[])
    state,_=transition(state,{'actor':'player','action':'give','item':'notebook','target':'chen'},[])
    assert state['items']['notebook']=='chen'
    with pytest.raises(PlatformError):transition(state,{'actor':'player','action':'inspect','item':'notebook'},[])
    state,_=transition(state,{'actor':'player','action':'decide','choice':'stay'},[])
    with pytest.raises(PlatformError):transition(state,{'actor':'player','action':'decide','choice':'accept'},[])

@pytest.mark.parametrize('text',[
    '{"actions":[{"actor":[],"action":"wait"}]}',
    '{"actions":[{"actor":"lin","action":"talk","target":[]}]}',
    '{"actions":[{"actor":"chen","action":"take","item":[]}]}',
])
def test_malformed_model_tool_types_are_controlled_errors(env,text):
    app,c,h,_=env;app.state.models.adapter=StructuredMock(text)
    r=new(env,'model');s,b=r['save']['id'],r['branch']['id']
    response=action(env,s,b,0,{'action':'wait'});assert response.status_code==503
    assert response.json()['error']['code']=='INVALID_AGENT_PROPOSAL'
    assert c.get(f'/api/v1/game/saves/{s}/branches/{b}',headers=h).json()['branch']['revision']==0
