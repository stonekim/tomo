"""Fixture rules are NOT game/plan implementations or real model calls."""
import pytest
from fastapi.testclient import TestClient
from tomo.platform.api import create_app
from tomo.platform.config import Settings
from tomo.platform.errors import PlatformError
from tomo.platform.rules import RuleRegistry


@pytest.fixture
def rules():
    registry = RuleRegistry()

    def fixture_rule(old, proposed, event):
        if set(proposed) != {'counter'} or type(proposed['counter']) is not int or proposed['counter'] < 0:
            raise PlatformError(422, 'INVALID_TRANSITION', 'Fixture requires nonnegative counter')
        if old is not None and proposed['counter'] != old['counter'] + 1:
            raise PlatformError(422, 'INVALID_TRANSITION', 'Fixture requires increment by one')
    registry.register('game', fixture_rule)
    registry.register('plan', fixture_rule)
    return registry


@pytest.fixture
def settings(tmp_path):
    return Settings(database=str(tmp_path / 'tomo.sqlite3'))


@pytest.fixture
def app(settings, rules):
    return create_app(settings, rule_registry=rules)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def register(client, name='alice'):
    response = client.post('/api/v1/auth/register', json={'username': name, 'password': 'correct-password-123'})
    assert response.status_code == 201, response.text
    session = response.json()
    return session, {'Authorization': 'Bearer ' + session['token']}


@pytest.fixture
def account(client):
    return register(client)


def save(client, headers, domain='game'):
    response = client.post('/api/v1/saves', headers=headers, json={'domain': domain, 'title': 'Test archive', 'state': {'counter': 0}})
    assert response.status_code == 201, response.text
    return response.json()


def event(revision=0, key='event-1', counter=1, causes=None):
    return {'expected_revision': revision, 'idempotency_key': key, 'type': 'fixture.increment', 'payload': {}, 'state': {'counter': counter}, 'causes': causes or []}


def version(revision=0, key='version-1', kind='judgment', counter=1, based_on=None):
    return {'expected_revision': revision, 'idempotency_key': key, 'kind': kind, 'content': {'counter': counter}, 'based_on': based_on}
