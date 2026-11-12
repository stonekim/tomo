import json
import sqlite3
import pytest
from jsonschema import Draft202012Validator
from tomo.contracts import SCHEMA, validate
from tomo.platform.auth import Auth
from tomo.platform.config import Settings
from tomo.platform.db import Database, MIGRATIONS
from tomo.platform.errors import PlatformError


def test_migrate_v1_to_v2_keeps_existing_account_and_is_repeatable(tmp_path):
    path = tmp_path / 'upgrade.sqlite3'
    conn = sqlite3.connect(path)
    for statement in MIGRATIONS[0][1]:
        conn.execute(statement)
    conn.execute('PRAGMA user_version=1')
    conn.execute("INSERT INTO users VALUES('existing-user','alice','placeholder')")
    conn.commit()
    conn.close()
    database = Database(path)
    database.migrate()
    with database.transaction() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 2
        assert conn.execute('SELECT id FROM users').fetchone()[0] == 'existing-user'
        assert conn.execute('SELECT COUNT(*) FROM model_audit').fetchone()[0] == 0


def test_future_database_rejected_without_downgrade(tmp_path):
    path = tmp_path / 'future.sqlite3'
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA user_version=99')
    conn.close()
    with pytest.raises(RuntimeError, match='newer'):
        Database(path)
    conn = sqlite3.connect(path)
    assert conn.execute('PRAGMA user_version').fetchone()[0] == 99
    conn.close()


def test_session_expiration_and_failed_login_limit_persist(settings):
    now = [1000000]
    database = Database(settings.database)
    auth = Auth(database, hours=1, clock=lambda: now[0])
    credentials = {'username': 'alice', 'password': 'correct-password-123'}
    session = auth.register(credentials)
    assert auth.authenticate(session['token']) == session['user_id']
    now[0] += 3600
    with pytest.raises(PlatformError) as exc:
        auth.authenticate(session['token'])
    assert exc.value.status == 401
    for _ in range(10):
        with pytest.raises(PlatformError) as exc:
            auth.login(credentials | {'password': 'incorrect-password-123'})
        assert exc.value.status == 401
    restarted = Auth(database, clock=lambda: now[0])
    with pytest.raises(PlatformError) as exc:
        restarted.login(credentials)
    assert exc.value.status == 429
    now[0] += 301
    assert restarted.login(credentials)['user_id'] == session['user_id']


@pytest.mark.parametrize('kwargs', [
    {'session_hours': 0}, {'session_hours': 169}, {'model_attempts': 0}, {'model_attempts': 4},
    {'model_timeout': 0}, {'model_timeout': 121}, {'model_mode': 'surprise'},
    {'allowed_origins': ('*',)}, {'allowed_origins': ('https://site.example/path',)},
    {'allowed_origins': ('https://user:password@site.example',)},
    {'model_mode': 'real'},
    {'model_mode': 'real', 'model_endpoint': 'http://provider.example', 'model_name': 'test', 'model_api_key': 'synthetic'},
    {'model_mode': 'real', 'model_endpoint': 'https://user:pass@provider.example', 'model_name': 'test', 'model_api_key': 'synthetic'},
    {'model_mode': 'real', 'model_endpoint': 'https://provider.example?key=x', 'model_name': 'test', 'model_api_key': 'synthetic'},
])
def test_unsafe_config_rejected(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_defaults_disable_real_model_and_cors(client):
    defaults = Settings()
    assert defaults.model_mode == 'disabled' and defaults.allowed_origins == ()
    response = client.get('/healthz', headers={'Origin': 'https://untrusted.example'})
    assert 'access-control-allow-origin' not in response.headers


def test_all_contract_definitions_and_openapi_resolve(client):
    Draft202012Validator.check_schema(SCHEMA)
    for name in SCHEMA['$defs']:
        Draft202012Validator.check_schema({'$ref': f'#/$defs/{name}', '$defs': SCHEMA['$defs']})
    document = client.get('/openapi.json').json()
    assert document['openapi'] == '3.1.0'
    assert document == json.load(open('docs/contracts/openapi.json'))
    def refs(value):
        if isinstance(value, dict):
            if '$ref' in value:
                target = document
                for segment in value['$ref'].removeprefix('#/').split('/'):
                    target = target[segment]
            for child in value.values():
                refs(child)
        elif isinstance(value, list):
            for child in value:
                refs(child)
    refs(document)
    schema = document['paths']['/api/v1/saves']['post']['requestBody']['content']['application/json']['schema']
    assert schema == {'$ref': '#/components/schemas/SaveCreate'}
    validate('Usage', {'input_tokens': None, 'output_tokens': None, 'cached_input_tokens': None, 'cost': None, 'currency': None})
