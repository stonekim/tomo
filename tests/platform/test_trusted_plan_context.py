from fastapi.testclient import TestClient
from tomo.platform.api import create_app
from tomo.platform.rules import RuleRegistry
from .conftest import register, version


def test_server_supplies_clock_and_historical_judgment(settings):
    contexts = []
    rules = RuleRegistry()
    rules.register('plan', lambda old, state, event: contexts.append(event))
    with TestClient(create_app(settings, rule_registry=rules)) as client:
        _, headers = register(client)
        saved = client.post('/api/v1/saves', headers=headers, json={'domain': 'plan', 'title': 'Plan', 'state': {}}).json()
        assert contexts[0]['_now']
        url = '/api/v1/saves/' + saved['id'] + '/versions'
        judgment = client.post(url, headers=headers, json=version()).json()
        outcome = version(revision=1, key='outcome', kind='outcome', counter=2, based_on=judgment['id'])
        assert client.post(url, headers=headers, json=outcome).status_code == 201
        context = contexts[-1]
        assert context['_judgment'] == {'id': judgment['id'], 'content': {'counter': 1}, 'created_at': judgment['created_at']}
        assert context['_now']
        assert context['_outcome_count'] == 0
        # Trusted data is never accepted from the client's proposal shape.
        for field, value in [('_now', '2099-01-01T00:00:00Z'), ('_judgment', {'id': 'fake'}), ('_outcome_count', 0)]:
            bad = dict(version(revision=2, key='spoof-' + field, counter=3), **{field: value})
            assert client.post(url, headers=headers, json=bad).status_code == 422
        assert len(client.get(url, headers=headers).json()) == 2
