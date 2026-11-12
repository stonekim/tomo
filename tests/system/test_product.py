from fastapi.testclient import TestClient
from tomo.app import create_product_app
from tomo.platform.config import Settings


def register(client, name):
    response = client.post('/api/v1/auth/register', json={'username':name,'password':'synthetic-password-123'})
    assert response.status_code == 201
    return {'Authorization':'Bearer '+response.json()['token']}


def test_composed_product_and_context_bound_game(tmp_path):
    app=create_product_app(Settings(database=str(tmp_path/'qa.sqlite3')))
    c=TestClient(app);alice=register(c,'alice');bob=register(c,'bob')
    assert c.get('/').status_code == 200
    assert "script-src 'self'" in c.get('/').headers['Content-Security-Policy']
    assert c.get('/src/shell/index.js').status_code == 200
    body={'scenario':'A synthetic job choice','idempotency_key':'create-game-0001'}
    first=c.post('/api/v1/game/saves',headers=alice,json=body);assert first.status_code==201
    game=first.json();save=game['save']['id'];branch=game['branch']['id']
    assert c.post('/api/v1/game/saves',headers=alice,json=body).json()['save']['id']==save
    assert c.post('/api/v1/game/saves',headers=alice,json=body|{'scenario':'changed'}).status_code==409
    assert len(c.get('/api/v1/saves',headers=alice).json())==1
    assert c.get('/api/v1/game/saves/'+save+'/branches',headers=bob).status_code==404
    r=c.post(f'/api/v1/game/saves/{save}/branches/{branch}/actions',headers=alice,json={'action':{'action':'wait'},'expected_revision':0,'idempotency_key':'action-test-001'});assert r.status_code==200
    event=r.json()['branch']['events'][0]
    other=c.post('/api/v1/game/saves',headers=bob,json=body).json();s2,b2=other['save']['id'],other['branch']['id']
    forged={'type':event['type'],'payload':event['payload'],'state':event['state'],'causes':[],'expected_revision':0,'idempotency_key':'action-test-001'}
    assert c.post(f'/api/v1/saves/{s2}/branches/{b2}/events',headers=bob,json=forged).status_code==422
    assert c.get(f'/api/v1/saves/{s2}/branches/{b2}',headers=bob).json()['revision']==0
    forged['_context']={'owner_id':'alice','save_id':save,'branch_id':branch}
    assert c.post(f'/api/v1/saves/{s2}/branches/{b2}/events',headers=bob,json=forged).status_code==422


def test_game_locks_reclaimed_after_invalid_and_valid_requests(tmp_path):
    from tomo.game.api import _locks
    app=create_product_app(Settings(database=str(tmp_path/'locks.sqlite3')));c=TestClient(app);h=register(c,'locks')
    for n in range(10):
        r=c.post(f'/api/v1/game/saves/invalid{n}/branches/invalid/actions',headers=h,json={'action':{'action':'wait'},'expected_revision':0,'idempotency_key':'invalid-key-0001'})
        assert r.status_code==404
    assert not _locks
    game=c.post('/api/v1/game/saves',headers=h,json={'scenario':'locks QA'}).json();s,b=game['save']['id'],game['branch']['id']
    assert c.post(f'/api/v1/game/saves/{s}/branches/{b}/actions',headers=h,json={'action':{'action':'wait'},'expected_revision':0,'idempotency_key':'valid-key-0001'}).status_code==200
    assert not _locks


def test_concurrent_game_retry_calls_model_once_and_reclaims_locks(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from tomo.platform.models import ModelResult, UNKNOWN_USAGE
    from tomo.game.api import _locks
    import threading,time
    app=create_product_app(Settings(database=str(tmp_path/'concurrent.sqlite3')));c=TestClient(app);h=register(c,'concurrent')
    class Adapter:
        mode='mock';name='structured-tool-mock'
        calls=0
        def complete(self,messages):
            self.calls+=1;time.sleep(.03)
            return ModelResult('{"actions":[]}',UNKNOWN_USAGE.copy())
    adapter=Adapter();app.state.models.adapter=adapter
    game=c.post('/api/v1/game/saves',headers=h,json={'scenario':'concurrent QA','engine':'model'}).json();s,b=game['save']['id'],game['branch']['id']
    def write(_):
        return c.post(f'/api/v1/game/saves/{s}/branches/{b}/actions',headers=h,json={'action':{'action':'wait'},'expected_revision':0,'idempotency_key':'same-key-0001'})
    with ThreadPoolExecutor(max_workers=4) as pool:responses=list(pool.map(write,range(4)))
    assert all(r.status_code==200 for r in responses)
    assert adapter.calls==1
    assert len(responses[0].json()['branch']['events'])==1
    assert not _locks


def test_request_size_limit_for_fixed_and_chunked_bodies(tmp_path):
    c=TestClient(create_product_app(Settings(database=str(tmp_path/'limits.sqlite3'))))
    assert c.post('/api/v1/auth/register',content=b'x'*524289).status_code==413
    def chunks():
        yield b'x'*300000
        yield b'y'*300000
    assert c.post('/api/v1/auth/register',content=chunks()).status_code==413


def test_backup_restore_preserves_private_data_and_rollback(tmp_path):
    import importlib.util,sqlite3
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('backup_script',Path(__file__).resolve().parents[2]/'deploy/database.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=tmp_path/'source.sqlite3';snapshot=tmp_path/'snapshot.sqlite3'
    with sqlite3.connect(source) as db:db.execute('CREATE TABLE sample(value TEXT)');db.execute("INSERT INTO sample VALUES('before')")
    module.backup(source,snapshot)
    assert snapshot.stat().st_mode&0o777==0o600
    with sqlite3.connect(source) as db:db.execute("UPDATE sample SET value='after'")
    import pytest
    with pytest.raises(RuntimeError):module.restore(snapshot,source)
    previous=module.restore(snapshot,source,True)
    with sqlite3.connect(source) as db:assert db.execute('SELECT value FROM sample').fetchone()[0]=='before'
    with sqlite3.connect(previous) as db:assert db.execute('SELECT value FROM sample').fetchone()[0]=='after'


def test_product_reopen_preserves_user_session_and_game(tmp_path):
    settings=Settings(database=str(tmp_path/'persistent.sqlite3'))
    first=TestClient(create_product_app(settings));h=register(first,'persistent')
    game=first.post('/api/v1/game/saves',headers=h,json={'scenario':'persistence QA'}).json();s,b=game['save']['id'],game['branch']['id']
    assert first.post(f'/api/v1/game/saves/{s}/branches/{b}/actions',headers=h,json={'action':{'action':'wait'},'expected_revision':0,'idempotency_key':'restart-turn-01'}).status_code==200
    second=TestClient(create_product_app(settings))
    assert second.get('/api/v1/me',headers=h).status_code==200
    assert second.get(f'/api/v1/game/saves/{s}/branches/{b}',headers=h).json()['branch']['revision']==1


def test_structured_json_accepts_one_fence_not_prose_or_nonfinite():
    from tomo.platform.models import structured_json
    import pytest
    assert structured_json('```json\n{"actions":[]}\n```')=={'actions':[]}
    for text in ('Here is JSON: {"actions":[]}', '{"value":NaN}', '```json\n{}\n```\nother'):
        with pytest.raises(ValueError):structured_json(text)
