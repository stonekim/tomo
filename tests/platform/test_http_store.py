from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from tomo.contracts import validate
from tomo.platform.api import create_app, current_user
from .conftest import register, save, event, version


def branch_url(saved, branch_id=None):
    return f"/api/v1/saves/{saved['id']}/branches/{branch_id or saved['initial_branch_id']}"


def test_auth_and_contract_boundaries(client, account):
    session, headers = account
    validate('Session', session)
    assert client.get('/api/v1/me', headers=headers).json() == {'user_id': session['user_id']}
    for token in (None, 'Bearer wrong', 'Basic wrong'):
        response = client.get('/api/v1/saves', headers={'Authorization': token} if token else {})
        assert response.status_code == 401
        validate('Error', response.json())
    assert client.post('/api/v1/auth/register', json={'username': 'alice', 'password': 'correct-password-123'}).status_code == 409
    invalid = client.post('/api/v1/auth/login', json={'username': 'alice', 'password': 'incorrect-password-123'})
    assert invalid.status_code == 401
    assert 'incorrect-password' not in invalid.text
    assert client.post('/api/v1/auth/logout', headers=headers).status_code == 204
    assert client.get('/api/v1/me', headers=headers).status_code == 401


@pytest.mark.parametrize('body', [
    {'username': 'ab', 'password': 'short'},
    {'username': 'alice', 'password': 'correct-password-123', 'owner_id': 'admin'},
    {'username': 'alice', 'password': 123},
    {},
])
def test_credentials_strict(client, body):
    response = client.post('/api/v1/auth/register', json=body)
    assert response.status_code == 422
    validate('Error', response.json())


def test_body_limits_invalid_json_and_private_cache(client):
    response = client.post('/api/v1/auth/login', content='{"password":')
    assert response.status_code == 422
    assert 'password' not in response.text
    assert client.post('/api/v1/auth/login', content='x' * 262145).status_code == 413
    assert client.get('/healthz').headers['cache-control'] == 'no-store'
    assert client.get('/healthz').headers['x-content-type-options'] == 'nosniff'


def test_missing_domain_rules_fail_closed(settings):
    with TestClient(create_app(settings)) as client:
        _, headers = register(client)
        response = client.post('/api/v1/saves', headers=headers, json={'domain': 'game', 'title': 'unavailable', 'state': {}})
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'DOMAIN_UNAVAILABLE'
        assert client.get('/api/v1/saves', headers=headers).json() == []


def test_save_restart_preserves_sessions_state_and_history(client, account, settings, rules):
    _, headers = account
    saved = save(client, headers)
    validate('Save', saved)
    url = branch_url(saved)
    result = client.post(url + '/events', headers=headers, json=event()).json()
    validate('Branch', result)
    with TestClient(create_app(settings, rule_registry=rules)) as restarted:
        assert restarted.get('/api/v1/saves', headers=headers).json() == [saved]
        assert restarted.get(url, headers=headers).json() == result
        assert restarted.get('/healthz').json()['database_version'] == 2


def test_foreign_user_cannot_read_write_fork_versions_or_usage(client, account):
    _, alice = account
    game = save(client, alice)
    plan = save(client, alice, 'plan')
    _, bob = register(client, 'bob')
    assert client.get('/api/v1/saves', headers=bob).json() == []
    requests = [
        ('GET', f"/api/v1/saves/{game['id']}", None),
        ('GET', f"/api/v1/saves/{game['id']}/branches", None),
        ('GET', branch_url(game), None),
        ('POST', branch_url(game) + '/events', event()),
        ('POST', branch_url(game) + '/forks', {'at_sequence': 0, 'idempotency_key': 'fork-1'}),
        ('GET', f"/api/v1/saves/{plan['id']}/versions", None),
        ('POST', f"/api/v1/saves/{plan['id']}/versions", version()),
        ('GET', f"/api/v1/saves/{game['id']}/usage", None),
    ]
    for method, url, body in requests:
        response = client.request(method, url, headers=bob, json=body)
        assert response.status_code == 404, (method, url, response.text)
        assert response.json() == {'error': {'code': 'NOT_FOUND', 'message': 'Resource not found'}}
    assert client.get(branch_url(game), headers=alice).json()['revision'] == 0
    assert client.get(f"/api/v1/saves/{plan['id']}/versions", headers=alice).json() == []


def test_event_idempotency_conflicts_and_invalid_state_rollback(client, account):
    _, headers = account
    saved = save(client, headers)
    url = branch_url(saved)
    first = client.post(url + '/events', headers=headers, json=event())
    assert first.status_code == 200
    assert client.post(url + '/events', headers=headers, json=event()).json() == first.json()
    assert client.post(url + '/events', headers=headers, json=event(counter=99)).status_code == 409
    assert client.post(url + '/events', headers=headers, json=event(key='other')).status_code == 409
    assert client.post(url + '/events', headers=headers, json=event(1, 'invalid', 99)).status_code == 422
    assert client.post(url + '/events', headers=headers, json=event(1, 'invalid-cause', 2, ['unknown-event'])).status_code == 422
    assert client.get(url, headers=headers).json() == first.json()
    # Rejected proposal did not consume the idempotency key or revision.
    assert client.post(url + '/events', headers=headers, json=event(1, 'invalid', 2)).status_code == 200


def test_fork_prefix_causal_ids_and_independent_state(client, account):
    _, headers = account
    saved = save(client, headers)
    url = branch_url(saved)
    first = client.post(url + '/events', headers=headers, json=event()).json()
    cause = first['events'][0]['id']
    second = client.post(url + '/events', headers=headers, json=event(1, 'parent-next', 2, [cause])).json()
    proposal = {'at_sequence': 1, 'idempotency_key': 'fork-key'}
    child = client.post(url + '/forks', headers=headers, json=proposal)
    assert child.status_code == 201
    child = child.json()
    validate('Branch', child)
    assert child['events'] == first['events']
    assert child['state'] == {'counter': 1}
    assert child['parent_id'] == saved['initial_branch_id']
    assert client.post(url + '/forks', headers=headers, json=proposal).json() == child
    child_url = branch_url(saved, child['id'])
    assert client.post(child_url + '/events', headers=headers, json=event(1, 'child-next', 2, [second['events'][-1]['id']])).status_code == 422
    child_next = client.post(child_url + '/events', headers=headers, json=event(1, 'child-next', 2, [cause])).json()
    assert child_next['events'][-1]['id'] != second['events'][-1]['id']
    assert client.get(url, headers=headers).json() == second
    assert client.post(url + '/forks', headers=headers, json={'at_sequence': 100, 'idempotency_key': 'bad-fork'}).status_code == 422
    zero = client.post(child_url + '/forks', headers=headers, json={'at_sequence': 0, 'idempotency_key': 'zero'}).json()
    assert zero['state'] == {'counter': 0} and zero['events'] == []
    assert len(client.get(f"/api/v1/saves/{saved['id']}/branches", headers=headers).json()) == 3


def test_plan_versions_immutable_linked_and_outcomes_reference_judgment(client, account, settings, rules):
    _, headers = account
    saved = save(client, headers, 'plan')
    url = f"/api/v1/saves/{saved['id']}/versions"
    assert client.post(url, headers=headers, json=version(kind='update')).status_code == 422
    first_response = client.post(url, headers=headers, json=version())
    assert first_response.status_code == 201, first_response.text
    first = first_response.json()
    validate('PlanVersion', first)
    assert client.post(url, headers=headers, json=version()).json() == first
    second = client.post(url, headers=headers, json=version(1, 'update', 'update', 2)).json()
    assert second['previous_id'] == first['id']
    assert client.post(url, headers=headers, json=version(2, 'bad-outcome', 'outcome', 3, second['id'])).status_code == 422
    assert client.post(url, headers=headers, json=version(2, 'bad-outcome', 'outcome', 3, 'foreign')).status_code == 422
    third = client.post(url, headers=headers, json=version(2, 'result', 'outcome', 3, first['id'])).json()
    assert third['based_on'] == first['id'] and third['previous_id'] == second['id']
    assert client.post(url, headers=headers, json=version(0, 'stale')).status_code == 409
    assert client.put(url + '/' + first['id'], headers=headers, json=version()).status_code in (404, 405)
    assert client.get(url, headers=headers).json() == [first, second, third]
    with TestClient(create_app(settings, rule_registry=rules)) as restarted:
        assert restarted.get(url, headers=headers).json() == [first, second, third]


def test_game_plan_isolation_and_branch_save_association(client, account):
    _, headers = account
    game, other, plan = save(client, headers), save(client, headers), save(client, headers, 'plan')
    assert client.get(f"/api/v1/saves/{game['id']}/versions", headers=headers).status_code == 422
    assert client.post(f"/api/v1/saves/{game['id']}/versions", headers=headers, json=version()).status_code == 422
    assert client.get(f"/api/v1/saves/{plan['id']}/branches", headers=headers).status_code == 422
    assert client.post(f"/api/v1/saves/{plan['id']}/branches/{game['initial_branch_id']}/events", headers=headers, json=event()).status_code == 422
    assert client.get(branch_url(game, other['initial_branch_id']), headers=headers).status_code == 404
    first = client.post(f"/api/v1/saves/{plan['id']}/versions", headers=headers, json=version()).json()
    foreign_plan = save(client, headers, 'plan')
    foreign_url = f"/api/v1/saves/{foreign_plan['id']}/versions"
    client.post(foreign_url, headers=headers, json=version(key='foreign-plan'))
    assert client.post(foreign_url, headers=headers, json=version(1, 'foreign-result', 'outcome', 2, first['id'])).status_code == 422


def test_concurrent_compare_and_swap_has_exactly_one_winner(app, client, account):
    session, headers = account
    saved = save(client, headers)
    store = app.state.store
    def append(key):
        from tomo.platform.errors import PlatformError
        try:
            return store.append_event(session['user_id'], saved['id'], saved['initial_branch_id'], event(key=key))['revision']
        except PlatformError as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append, ['a', 'b']))
    assert sorted(outcomes) == [1, 409]
    assert len(client.get(branch_url(saved), headers=headers).json()['events']) == 1


def test_unknown_fields_wrong_types_and_domain_rejected(client, account):
    _, headers = account
    for body in [
        {'domain': 'unknown', 'title': 'bad', 'state': {}},
        {'domain': 'game', 'title': 'bad', 'state': {}, 'owner_id': 'admin'},
        {'domain': 'game', 'title': 'bad', 'state': []},
    ]:
        assert client.post('/api/v1/saves', headers=headers, json=body).status_code == 422
    saved = save(client, headers)
    for proposal in [event() | {'expected_revision': True}, event() | {'unexpected': 1}, event() | {'causes': ['x', 'x']}]:
        assert client.post(branch_url(saved) + '/events', headers=headers, json=proposal).status_code == 422


def test_domain_router_inherits_authenticated_identity(settings, rules):
    router = APIRouter()
    @router.get('/api/v1/fixture-domain')
    def domain(owner=Depends(current_user)):
        return {'owner': owner}
    with TestClient(create_app(settings, rule_registry=rules, domain_routers=[router])) as client:
        assert client.get('/api/v1/fixture-domain').status_code == 401
        session, headers = register(client)
        assert client.get('/api/v1/fixture-domain', headers=headers).json() == {'owner': session['user_id']}
