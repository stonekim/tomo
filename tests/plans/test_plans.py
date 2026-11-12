import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from tomo.plans import create_plan_app
from tomo.plans.rules import Card, assessment, validate_plan
from tomo.platform.config import Settings
from tomo.platform.errors import PlatformError
from tomo.platform.models import ModelResult, UNKNOWN_USAGE


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = [datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr('tomo.platform.store.timestamp', lambda: clock[0].isoformat())
    settings = Settings(database=str(tmp_path / 'plans.sqlite'))
    app = create_plan_app(settings, clock=lambda: clock[0])
    with TestClient(app) as client:
        session = client.post('/api/v1/auth/register', json={'username': 'alice', 'password': 'correct-password-123'}).json()
        headers = {'Authorization': 'Bearer ' + session['token']}
        yield {'client': client, 'app': app, 'clock': clock, 'headers': headers, 'settings': settings}


def card(env, **changes):
    value = {'goal': '完成作品集', 'completion_criteria': '交付三份可访问案例',
        'due_at': (env['clock'][0] + timedelta(days=14)).isoformat(), 'timezone': 'Asia/Shanghai',
        'facts': ['已有初稿'], 'unknowns': ['评审可用时间'], 'required_hours': 12.0,
        'available_hours_per_week': 10.0, 'user_judgment': 'yes'}
    value.update(changes)
    return value


def create(env, **changes):
    payload = {'title': '两周作品集', 'idempotency_key': 'create-one', 'card': card(env)}
    payload.update(changes)
    r = env['client'].post('/api/v1/plans', headers=env['headers'], json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def request(env, path, data=None, headers=None):
    return getattr(env['client'], 'post' if data is not None else 'get')(path, headers=headers if headers is not None else env['headers'], **({'json': data} if data is not None else {}))


def update(env, result, kind='update', **changes):
    c = copy.deepcopy(result['version']['content']['card'])
    c.pop('start_at')
    body = {'expected_revision': 1, 'idempotency_key': 'update-one', 'kind': kind, 'card': c,
        'recorded_at': env['clock'][0].isoformat(), 'update_note': '本周已完成第一个案例'}
    body.update(changes)
    return request(env, '/api/v1/plans/' + result['save']['id'] + '/versions', body)


def outcome(env, result, **changes):
    body = {'expected_revision': 1, 'idempotency_key': 'outcome-one', 'based_on': result['version']['id'],
            'status': 'completed', 'evidence': '已交付三份案例链接', 'actual_hours': 14.0,
            'recorded_at': env['clock'][0].isoformat()}
    body.update(changes)
    return request(env, '/api/v1/plans/' + result['save']['id'] + '/outcomes', body)


def test_create_real_plan_with_locked_first_judgment(env):
    value = create(env)
    detail = request(env, '/api/v1/plans/' + value['save']['id']).json()
    assert detail['revision'] == 1
    assert detail['versions'][0] == value['version']
    baseline = detail['current']['assessment']['baseline']
    assert baseline == {'method': 'time_budget_v1', 'available_hours': 20.0, 'required_hours': 12.0, 'verdict': 'feasible'}
    assert detail['due'] is False
    assert detail['review']['comparisons'][0]['user_match'] is None
    assert request(env, '/api/v1/plans').json()[0]['save']['id'] == value['save']['id']


@pytest.mark.parametrize('changes', [
    {'due_at': '2030-01-07T00:00:00+00:00'}, {'due_at': '2030-02-01T00:00:00Z'},
    {'due_at': '2030-01-15T00:00:00'}, {'timezone': 'Not/AZone'}, {'goal': ' '},
    {'required_hours': -1.0}, {'available_hours_per_week': 169.0}, {'required_hours': True},
    {'success_probability': 0.7}, {'facts': ['']}, {'unknowns': ['x' * 2001]},
])
def test_invalid_horizon_timezone_and_probability_rejected(env, changes):
    r = request(env, '/api/v1/plans', {'title': 'Invalid', 'idempotency_key': 'invalid', 'card': card(env, **changes)})
    assert r.status_code == 422, r.text
    assert request(env, '/api/v1/plans').json() == []


def test_boundary_horizons_and_timezone_offsets(env):
    for days in (7, 30):
        due = (env['clock'][0] + timedelta(days=days)).astimezone(timezone(timedelta(hours=8))).isoformat()
        create(env, idempotency_key='horizon-' + str(days), card=card(env, due_at=due))
    assert len(request(env, '/api/v1/plans').json()) == 2


def test_missing_time_estimates_remain_unknown(env):
    value = create(env, card=card(env, required_hours=None, available_hours_per_week=None, user_judgment='unknown'))
    a = value['version']['content']['assessment']
    assert a['judgment'] == 'unknown'
    assert a['baseline']['available_hours'] is None
    assert '概率' in a['limitation']
    assert len(a['scenarios']) == 2


def test_idempotent_create_concurrent_and_conflicting_payload(env):
    payload = {'title': 'One', 'idempotency_key': 'same-create', 'card': card(env)}
    def call():
        r = request(env, '/api/v1/plans', payload)
        assert r.status_code == 201, r.text
        return r.json()
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _: call(), range(4)))
    assert len({x['save']['id'] for x in values}) == 1
    assert len(request(env, '/api/v1/plans').json()) == 1
    assert request(env, '/api/v1/plans', dict(payload, title='Changed')).status_code == 409


def test_initial_judgment_and_save_rollback_together(env, monkeypatch):
    import tomo.plans.service as module
    real = module.validate_plan
    def fail_on_judgment(old, state, event):
        if event.get('kind') == 'judgment':
            raise PlatformError(422, 'TEST_REJECTION', 'Rejected')
        return real(old, state, event)
    monkeypatch.setattr(module, 'validate_plan', fail_on_judgment)
    r = request(env, '/api/v1/plans', {'title': 'One', 'idempotency_key': 'rollback', 'card': card(env)})
    assert r.status_code == 422
    assert request(env, '/api/v1/plans').json() == []


def test_update_preserves_first_judgment_and_is_idempotent(env):
    value = create(env)
    env['clock'][0] += timedelta(days=7)
    updated = update(env, value)
    assert updated.status_code == 201, updated.text
    assert update(env, value).json() == updated.json()
    versions = request(env, '/api/v1/saves/' + value['save']['id'] + '/versions').json()
    assert len(versions) == 2 and versions[0] == value['version']
    assert versions[1]['kind'] == 'update'
    assert versions[1]['content']['assessment']['baseline']['available_hours'] == 10.0
    assert versions[0]['content']['assessment']['baseline']['available_hours'] == 20.0
    assert update(env, value, idempotency_key='stale').status_code == 409


def test_target_changes_require_new_judgment_version(env):
    value = create(env)
    c = card(env, completion_criteria='两份而非三份案例')
    assert update(env, value, card=c).status_code == 422
    assert update(env, value, kind='judgment', card=c).status_code == 201
    history = request(env, '/api/v1/plans/' + value['save']['id']).json()['versions']
    assert history[0]['content']['card']['completion_criteria'] == '交付三份可访问案例'
    assert history[1]['content']['card']['completion_criteria'] == '两份而非三份案例'


def test_early_outcome_and_late_retroactive_judgment_rejected(env):
    value = create(env)
    assert outcome(env, value).status_code == 422
    env['clock'][0] += timedelta(days=14)
    assert update(env, value, kind='judgment').status_code == 422
    r = outcome(env, value)
    assert r.status_code == 201, r.text
    review = request(env, '/api/v1/plans/' + value['save']['id'] + '/review').json()
    comparison = review['comparisons'][0]
    assert comparison['result'] == 'completed'
    assert comparison['user_match'] is True and comparison['baseline_match'] is True
    assert comparison['hours_error'] == 2.0
    assert comparison['state'] == 'self_reported_result'


def test_missing_outcome_is_not_failure_and_unknown_outcome_keeps_null(env):
    value = create(env)
    env['clock'][0] += timedelta(days=14)
    url = '/api/v1/plans/' + value['save']['id'] + '/review'
    missing = request(env, url).json()['comparisons'][0]
    assert missing['state'] == 'awaiting_result' and missing['baseline_match'] is None
    assert outcome(env, value, status='unknown', evidence='', actual_hours=None).status_code == 201
    missing = request(env, url).json()['comparisons'][0]
    assert missing['state'] == 'unknown' and missing['baseline_match'] is None and missing['hours_error'] is None


def test_evidence_and_append_only_corrections(env):
    value = create(env)
    env['clock'][0] += timedelta(days=14)
    assert outcome(env, value, evidence='').status_code == 422
    first = outcome(env, value).json()
    assert outcome(env, value, expected_revision=2, idempotency_key='correction', status='not_completed').status_code == 422
    correction = outcome(env, value, expected_revision=2, idempotency_key='correction', status='not_completed', correction_note='补充核实：一份尚未通过验收')
    assert correction.status_code == 201, correction.text
    versions = request(env, '/api/v1/saves/' + value['save']['id'] + '/versions').json()
    assert versions[1] == first and versions[2]['content']['outcome']['status'] == 'not_completed'


def test_generic_endpoint_cannot_spoof_clock_reference_or_baseline(env):
    value = create(env)
    state = copy.deepcopy(value['version']['content'])
    state['assessment']['baseline']['available_hours'] = 900.0
    proposal = {'expected_revision': 1, 'idempotency_key': 'forged', 'kind': 'judgment', 'based_on': None, 'content': state}
    url = '/api/v1/saves/' + value['save']['id'] + '/versions'
    assert request(env, url, proposal).status_code == 422
    state = copy.deepcopy(value['version']['content'])
    state['card']['start_at'] = '2029-12-01T00:00:00Z'
    proposal['content'] = state
    assert request(env, url, proposal).status_code == 422
    outcome_state = {'schema_version': 1, 'outcome': {'judgment_id': value['version']['id'], 'status': 'completed', 'evidence': 'fake', 'actual_hours': None, 'recorded_at': '2099-01-01T00:00:00Z', 'source': 'self_reported', 'correction_note': ''}}
    proposal.update(kind='outcome', content=outcome_state, based_on=value['version']['id'])
    assert request(env, url, proposal).status_code == 422
    with pytest.raises(PlatformError):
        validate_plan(value['version']['content'], outcome_state, {'kind': 'outcome', 'based_on': value['version']['id']})


def test_historical_judgment_deadline_is_used_not_latest_criteria(env):
    value = create(env)
    assert update(env, value, kind='judgment', card=card(env, due_at=(env['clock'][0] + timedelta(days=7)).isoformat())).status_code == 201
    env['clock'][0] += timedelta(days=7)
    assert outcome(env, value, expected_revision=2).status_code == 422  # Original deadline is still day 14.
    detail = request(env, '/api/v1/plans/' + value['save']['id']).json()
    recent = {'save': value['save'], 'version': detail['versions'][1]}
    assert outcome(env, recent, expected_revision=2).status_code == 201


def test_ownership_restart_and_wrong_domain(env):
    value = create(env)
    bob = env['client'].post('/api/v1/auth/register', json={'username': 'bobby', 'password': 'correct-password-123'}).json()
    other = {'Authorization': 'Bearer ' + bob['token']}
    path = '/api/v1/plans/' + value['save']['id']
    for suffix in ('', '/review'):
        assert request(env, path + suffix, headers=other).status_code == 404
    assert request(env, path + '/suggestions', {}, other).status_code == 404
    assert request(env, '/api/v1/plans', headers=other).json() == []
    assert request(env, path, headers={}).status_code == 401
    with TestClient(create_plan_app(env['settings'], clock=lambda: env['clock'][0])) as restarted:
        result = restarted.get(path, headers=env['headers'])
        assert result.status_code == 200 and result.json()['versions'][0] == value['version']


def test_disabled_model_honest_fallback_without_audit(env):
    value = create(env)
    result = request(env, '/api/v1/plans/' + value['save']['id'] + '/suggestions', {}).json()
    assert result['mode'] == 'rules' and result['model_status'] == 'disabled'
    assert request(env, '/api/v1/saves/' + value['save']['id'] + '/usage').json() == []


@pytest.mark.parametrize('invalid', [False, True])
def test_model_suggestion_is_audited_and_untrusted_output_rejected(env, invalid):
    value = create(env)
    class Adapter:
        mode, name = 'mock', 'structured-test'
        def complete(self, messages):
            assert '游戏' not in messages[1]['content']
            return ModelResult(json.dumps({'risks': ['70% success'] if invalid else ['未知评审时间'], 'scenarios': [
                {'name': '基准', 'assumptions': ['时间不变'], 'actions': ['核对本周进展']},
                {'name': '替代', 'assumptions': ['可延期'], 'actions': ['与评审沟通']}]}), UNKNOWN_USAGE.copy())
    env['app'].state.models.adapter = Adapter()
    result = request(env, '/api/v1/plans/' + value['save']['id'] + '/suggestions', {}).json()
    assert result['mode'] == ('rules' if invalid else 'mock')
    assert result['model_status'] == ('invalid_structured_output' if invalid else 'structured_suggestion')
    audit = request(env, '/api/v1/saves/' + value['save']['id'] + '/usage').json()
    assert len(audit) == 1 and audit[0]['mode'] == 'mock' and audit[0]['usage']['cost'] is None
    assert len(request(env, '/api/v1/plans/' + value['save']['id']).json()['versions']) == 1


def test_interleaved_outcome_correction_still_requires_explanation(env):
    value = create(env)
    second = update(env, value, kind='judgment', update_note='补充事实后的另一次事前判断').json()
    env['clock'][0] += timedelta(days=14)
    assert outcome(env, value, expected_revision=2).status_code == 201
    second_result = {'save': value['save'], 'version': second}
    assert outcome(env, second_result, expected_revision=3, idempotency_key='other-judgment').status_code == 201
    assert outcome(env, value, expected_revision=4, idempotency_key='interleaved', status='not_completed').status_code == 422
    assert outcome(env, value, expected_revision=4, idempotency_key='interleaved', status='not_completed', correction_note='核对后修正原判断的回填').status_code == 201


def test_invalid_recording_time_and_blank_title_are_validation_errors(env):
    value = create(env)
    assert update(env, value, recorded_at='not-a-time').status_code == 422
    assert request(env, '/api/v1/plans', {'title': ' ', 'idempotency_key': 'blank-title', 'card': card(env)}).status_code == 422


def test_idempotent_create_replay_survives_elapsed_horizon(env):
    payload = {'title': 'One', 'idempotency_key': 'long-retry', 'card': card(env)}
    first = request(env, '/api/v1/plans', payload)
    env['clock'][0] += timedelta(days=31)
    replay = request(env, '/api/v1/plans', payload)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert len(request(env, '/api/v1/plans').json()) == 1


def test_typed_api_exposes_narrow_request_contract(env):
    document = env['app'].openapi()
    schema = document['paths']['/api/v1/plans']['post']['requestBody']['content']['application/json']['schema']
    assert schema == {'$ref': '#/components/schemas/CreateInput'}
    assert document['components']['schemas']['CreateInput']['additionalProperties'] is False
    assert request(env, '/api/v1/plans', {'title': 'Bad', 'idempotency_key': 'x', 'card': card(env), 'owner_id': 'another'}).status_code == 422


def test_calendar_horizon_across_dst_uses_zone_but_deadline_is_exact(env):
    # Spring-forward week is 167 hours, still seven calendar days in New York.
    env['clock'][0] = datetime(2030, 3, 5, 13, 0, tzinfo=timezone.utc)
    result = create(env, card=card(env, timezone='America/New_York', due_at='2030-03-12T08:00:00-04:00'))
    due = datetime(2030, 3, 12, 12, 0, tzinfo=timezone.utc)
    env['clock'][0] = due - timedelta(seconds=1)
    assert outcome(env, result).status_code == 422
    env['clock'][0] = due
    assert outcome(env, result).status_code == 201
