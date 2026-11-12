"""HTTP provider responses here are simulated; no external model is invoked."""
import httpx
import pytest
from tomo.contracts import validate
from tomo.platform.config import Settings
from tomo.platform.errors import PlatformError
from tomo.platform.models import HttpAdapter, MockAdapter, ModelService, UNKNOWN_USAGE
from .conftest import register, save

MESSAGES = [{'role': 'user', 'content': 'private prompt never stored in audit'}]


def service(app, transport, attempts=2):
    settings = Settings(database=app.state.store.db.path, model_mode='real',
                        model_endpoint='https://provider.example/v1/chat/completions',
                        model_name='test-model', model_api_key='synthetic-test-key', model_attempts=attempts)
    return ModelService(app.state.store, HttpAdapter(settings, transport), attempts, sleeper=lambda _: None)


def test_disabled_model_and_wrong_owner_no_dispatch(app, client, account):
    session, headers = account
    saved = save(client, headers)
    with pytest.raises(PlatformError) as exc:
        app.state.models.generate(session['user_id'], saved['id'], 'fixture', MESSAGES)
    assert exc.value.code == 'MODEL_DISABLED'
    bob, _ = register(client, 'bob')
    model = ModelService(app.state.store, MockAdapter())
    with pytest.raises(PlatformError) as exc:
        model.generate(bob['user_id'], saved['id'], 'fixture', MESSAGES)
    assert exc.value.status == 404
    assert app.state.store.list_audit(session['user_id'], saved['id']) == []


def test_mock_explicit_null_usage_and_private_context_not_persisted(app, client, account, settings, rules):
    session, headers = account
    saved = save(client, headers)
    model = ModelService(app.state.store, MockAdapter())
    result = model.generate(session['user_id'], saved['id'], 'fixture', MESSAGES)
    assert result.usage == UNKNOWN_USAGE
    audit = client.get(f"/api/v1/saves/{saved['id']}/usage", headers=headers).json()
    assert len(audit) == 1
    validate('Audit', audit[0])
    assert audit[0]['mode'] == 'mock' and audit[0]['status'] == 'ok'
    assert audit[0]['usage'] == {'input_tokens': None, 'output_tokens': None, 'cached_input_tokens': None, 'cost': None, 'currency': None}
    assert MESSAGES[0]['content'] not in str(audit)
    from tomo.platform.api import create_app
    assert create_app(settings, rule_registry=rules).state.store.list_audit(session['user_id'], saved['id']) == audit


def test_http_adapter_maps_independent_input_output_cache_counts(app, client, account):
    session, headers = account
    saved = save(client, headers)
    def response(request):
        assert request.url == 'https://provider.example/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer synthetic-test-key'
        return httpx.Response(200, json={'choices': [{'message': {'content': 'proposal'}}], 'usage': {'prompt_tokens': 120, 'completion_tokens': 7, 'prompt_tokens_details': {'cached_tokens': 80}}})
    model = service(app, httpx.MockTransport(response))
    result = model.generate(session['user_id'], saved['id'], 'fixture', MESSAGES)
    assert result.text == 'proposal'
    expected = {'input_tokens': 120, 'output_tokens': 7, 'cached_input_tokens': 80, 'cost': None, 'currency': None}
    assert result.usage == expected
    audit = app.state.store.list_audit(session['user_id'], saved['id'])
    assert audit[0]['usage'] == expected
    assert 'synthetic-test-key' not in str(audit)


@pytest.mark.parametrize('usage,expected', [
    (None, (None, None, None)),
    ({'completion_tokens': 0}, (None, 0, None)),
    ({'prompt_tokens': 0, 'prompt_tokens_details': {'cached_tokens': 0}}, (0, None, 0)),
    ({'prompt_tokens': True, 'completion_tokens': -1, 'prompt_tokens_details': {'cached_tokens': '4'}}, (None, None, None)),
    ({'prompt_tokens_details': []}, (None, None, None)),
])
def test_missing_usage_stays_null_without_inference(app, client, account, usage, expected):
    session, headers = account
    saved = save(client, headers)
    model = service(app, httpx.MockTransport(lambda _: httpx.Response(200, json={'choices': [{'message': {'content': 'some text'}}], 'usage': usage})))
    result = model.generate(session['user_id'], saved['id'], 'fixture', MESSAGES)
    assert tuple(result.usage[key] for key in ('input_tokens', 'output_tokens', 'cached_input_tokens')) == expected


def test_timeout_and_rate_limit_retry_each_attempt_audited(app, client, account):
    session, headers = account
    saved = save(client, headers)
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout('secret provider detail', request=request)
        if len(calls) == 2:
            return httpx.Response(429, text='secret provider detail')
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
    result = service(app, httpx.MockTransport(respond), 3).generate(session['user_id'], saved['id'], 'fixture', MESSAGES)
    assert result.text == 'ok' and len(calls) == 3
    audit = app.state.store.list_audit(session['user_id'], saved['id'])
    assert [entry['status'] for entry in audit] == ['timeout', 'rate_limited', 'ok']
    assert [entry['attempt'] for entry in audit] == [1, 2, 3]
    assert all(entry['usage'] == UNKNOWN_USAGE for entry in audit)
    assert 'secret provider' not in str(audit)


@pytest.mark.parametrize('failure,status,attempts', [('timeout', 'timeout', 2), ('transport', 'transport', 2), (500, 'provider_error', 2), (401, 'provider_error', 1), (302, 'provider_error', 1), ('invalid', 'invalid_response', 1)])
def test_failures_bounded_and_redacted(app, client, account, failure, status, attempts):
    session, headers = account
    saved = save(client, headers)
    def respond(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('private', request=request)
        if failure == 'transport':
            raise httpx.ConnectError('private', request=request)
        if failure == 'invalid':
            return httpx.Response(200, text='private non-json')
        return httpx.Response(failure, text='private')
    with pytest.raises(PlatformError) as exc:
        service(app, httpx.MockTransport(respond)).generate(session['user_id'], saved['id'], 'fixture', MESSAGES)
    assert exc.value.code == 'MODEL_UNAVAILABLE'
    assert 'private' not in str(exc.value)
    audit = app.state.store.list_audit(session['user_id'], saved['id'])
    assert len(audit) == attempts
    assert all(entry['status'] == status for entry in audit)


def test_invalid_output_preserves_reported_usage(app, client, account):
    session, headers = account
    saved = save(client, headers)
    model = service(app, httpx.MockTransport(lambda _: httpx.Response(200, json={'choices': [], 'usage': {'prompt_tokens': 42}})))
    with pytest.raises(PlatformError):
        model.generate(session['user_id'], saved['id'], 'fixture', MESSAGES)
    audit = app.state.store.list_audit(session['user_id'], saved['id'])
    assert audit[0]['status'] == 'invalid_response'
    assert audit[0]['usage']['input_tokens'] == 42


def test_pending_attempt_survives_worker_crash_with_unknown_usage(app, client, account):
    session, headers = account
    saved = save(client, headers)
    class CrashingAdapter(MockAdapter):
        def complete(self, messages):
            raise RuntimeError('simulated process failure')
    with pytest.raises(RuntimeError):
        ModelService(app.state.store, CrashingAdapter()).generate(session['user_id'], saved['id'], 'fixture', MESSAGES)
    audit = app.state.store.list_audit(session['user_id'], saved['id'])
    assert len(audit) == 1 and audit[0]['status'] == 'pending'
    assert audit[0]['usage'] == UNKNOWN_USAGE
