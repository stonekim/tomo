"""Independent foundation probes; synthetic accounts/providers only."""
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from fastapi.testclient import TestClient
from tomo.platform.api import create_app
from tomo.platform.config import Settings
from tomo.platform.rules import RuleRegistry
from tomo.platform.errors import PlatformError
from tomo.platform.models import HttpAdapter, ModelService

@pytest.fixture
def setup(tmp_path):
    registry = RuleRegistry()
    def rule(old, new, event):
        if new.get('n') != (0 if old is None else old['n'] + 1):
            raise PlatformError(422, 'INVALID_TRANSITION', 'increment required')
    registry.register('game', rule)
    registry.register('plan', rule)
    app = create_app(Settings(database=str(tmp_path / 'review.sqlite3')), rule_registry=registry)
    with TestClient(app) as client:
        session = client.post('/api/v1/auth/register', json={'username':'reviewer','password':'synthetic-password'}).json()
        headers = {'Authorization':'Bearer '+session['token']}
        saved = client.post('/api/v1/saves',headers=headers,json={'domain':'game','title':'Synthetic','state':{'n':0}}).json()
        yield app, client, session, headers, saved

def test_generic_api_rejects_reset_and_owner_injection(setup):
    app,c,s,h,g = setup
    url = f"/api/v1/saves/{g['id']}/branches/{g['initial_branch_id']}"
    body = {'expected_revision':0,'idempotency_key':'probe','type':'initialize','payload':{},'state':{'n':999},'causes':[]}
    assert c.post(url+'/events',headers=h,json=body).status_code == 422
    assert c.post(url+'/events',headers=h,json=body|{'owner_id':s['user_id']}).status_code == 422
    assert c.get(url,headers=h).json()['revision'] == 0
    assert c.post(url+'/events',headers=h,json=body|{'state':{'n':1}}).status_code == 200

def test_concurrent_identical_retry_is_one_event(setup):
    app,c,s,h,g = setup
    proposal = {'expected_revision':0,'idempotency_key':'same','type':'increment','payload':{},'state':{'n':1},'causes':[]}
    def write(_): return app.state.store.append_event(s['user_id'],g['id'],g['initial_branch_id'],proposal)
    with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(write,range(4)))
    assert all(r == results[0] for r in results)
    assert len(results[0]['events']) == 1

def model(setup, status, body):
    app,c,s,h,g = setup
    settings = Settings(database=app.state.store.db.path,model_mode='real',model_endpoint='https://synthetic.invalid/chat',model_name='synthetic',model_api_key='synthetic')
    transport = httpx.MockTransport(lambda _:httpx.Response(status,json=body))
    service = ModelService(app.state.store,HttpAdapter(settings,transport),1)
    return service,s,g,app

def test_reported_usage_retained_on_http_error(setup):
    service,s,g,app = model(setup,500,{'usage':{'prompt_tokens':42,'completion_tokens':7,'prompt_tokens_details':{'cached_tokens':12}}})
    with pytest.raises(PlatformError): service.generate(s['user_id'],g['id'],'review',[{'role':'user','content':'synthetic'}])
    audit = app.state.store.list_audit(s['user_id'],g['id'])[-1]
    assert audit['status'] == 'provider_error'
    assert audit['usage']['input_tokens'] == 42
    assert audit['usage']['output_tokens'] == 7
    assert audit['usage']['cached_input_tokens'] == 12

def test_reported_cost_currency_retained(setup):
    service,s,g,app = model(setup,200,{'choices':[{'message':{'content':'synthetic'}}],'usage':{'prompt_tokens':42,'cost':0.012,'currency':'USD'}})
    service.generate(s['user_id'],g['id'],'review',[{'role':'user','content':'synthetic'}])
    audit = app.state.store.list_audit(s['user_id'],g['id'])[-1]
    assert audit['usage']['input_tokens'] == 42
    assert audit['usage']['cost'] == 0.012 and audit['usage']['currency'] == 'USD'

def test_nonfinite_json_is_422_without_write(setup):
    app,c,s,h,g = setup
    with TestClient(app,raise_server_exceptions=False) as client:
        response = client.post('/api/v1/saves',headers=h|{'Content-Type':'application/json'},content='{"domain":"game","title":"synthetic","state":{"n":0,"extra":NaN}}')
    assert response.status_code == 422
    assert len(c.get('/api/v1/saves',headers=h).json()) == 1


def test_persistent_real_call_limit_rejects_before_provider(setup):
    app,c,s,h,g = setup
    settings=Settings(database=app.state.store.db.path,model_mode='real',model_endpoint='https://synthetic.invalid/chat',model_name='synthetic',model_api_key='synthetic')
    calls=[]
    def complete(request):
        calls.append(request)
        assert __import__('json').loads(request.content)['max_tokens']==1200
        return httpx.Response(200,json={'choices':[{'message':{'content':'synthetic'}}]})
    first=ModelService(app.state.store,HttpAdapter(settings,httpx.MockTransport(complete)),1,limits=(2,1))
    first.generate(s['user_id'],g['id'],'review',[{'role':'user','content':'synthetic'}])
    # A fresh service instance cannot reset the persisted daily allowance.
    second=ModelService(app.state.store,HttpAdapter(settings,httpx.MockTransport(complete)),1,limits=(2,1))
    with pytest.raises(PlatformError) as e:second.generate(s['user_id'],g['id'],'review',[{'role':'user','content':'synthetic'}])
    assert e.value.code=='MODEL_DAILY_LIMIT' and e.value.status==429
    assert len(calls)==1


def test_model_concurrency_gate_prevents_second_attempt(setup):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from tomo.platform.models import ModelResult,UNKNOWN_USAGE
    app,c,s,h,g=setup;started=threading.Event();release=threading.Event()
    class SyntheticAdapter:
        mode='mock';name='concurrency-fixture';calls=0
        def complete(self,messages):
            self.calls+=1;started.set();assert release.wait(5)
            return ModelResult('synthetic',UNKNOWN_USAGE.copy())
    adapter=SyntheticAdapter();service=ModelService(app.state.store,adapter,1,concurrency=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(service.generate,s['user_id'],g['id'],'fixture',[{'role':'user','content':'synthetic'}])
        assert started.wait(5)
        try:
            with pytest.raises(PlatformError) as e:service.generate(s['user_id'],g['id'],'fixture',[{'role':'user','content':'synthetic'}])
            assert e.value.code=='MODEL_BUSY' and e.value.status==429
        finally:release.set()
        assert future.result().text=='synthetic'
    assert adapter.calls==1 and len(app.state.store.list_audit(s['user_id'],g['id']))==1


def test_configurable_reported_cost_mapping_and_unknowns(setup):
    from tomo.platform.models import usage_from_response
    result=usage_from_response({'usage':{'fee':0.012,'unit':'USD','prompt_tokens':3}},'fee','unit')
    assert result['cost']==0.012 and result['currency']=='USD' and result['input_tokens']==3
    unknown=usage_from_response({'usage':{'cost':float('nan'),'currency':'USD'}})
    assert unknown['cost'] is None and unknown['currency']=='USD'
