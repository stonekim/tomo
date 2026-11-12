"""Plan-specific use cases. Immutable judgments, explicit updates and self-reported reviews."""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from pydantic import Field
from tomo.platform.errors import PlatformError
from tomo.platform.models import structured_json
from tomo.platform.store import uid, encode
from .rules import (StrictModel, Card, JudgmentState, OutcomeState, Scenario, parse, instant,
                    assessment, validate_plan, fail)


class CardInput(StrictModel):
    goal: str = Field(min_length=1, max_length=300)
    completion_criteria: str = Field(min_length=1, max_length=2000)
    due_at: str = Field(json_schema_extra={"format": "date-time"})
    timezone: str = Field(min_length=1, max_length=80)
    facts: list[str] = Field(default_factory=list, max_length=20)
    unknowns: list[str] = Field(default_factory=list, max_length=20)
    required_hours: float | None = Field(default=None, ge=0, le=10000)
    available_hours_per_week: float | None = Field(default=None, ge=0, le=168)
    user_judgment: Literal['yes', 'uncertain', 'no', 'unknown'] = 'unknown'


class CreateInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=100)
    card: CardInput


class VersionInput(StrictModel):
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=100)
    kind: Literal['judgment', 'update']
    card: CardInput
    update_note: str = Field(min_length=1, max_length=3000)
    recorded_at: str = Field(json_schema_extra={"format": "date-time"})


class OutcomeInput(StrictModel):
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=100)
    based_on: str = Field(min_length=1, max_length=100)
    status: Literal['completed', 'not_completed', 'unknown']
    evidence: str = Field(default='', max_length=5000)
    actual_hours: float | None = Field(default=None, ge=0, le=10000)
    recorded_at: str = Field(json_schema_extra={"format": "date-time"})
    correction_note: str = Field(default='', max_length=3000)


class Suggestions(StrictModel):
    risks: list[str] = Field(min_length=1, max_length=10)
    scenarios: list[Scenario] = Field(min_length=2, max_length=2)


def utc_now():
    return datetime.now(timezone.utc)


class PlanService:
    def __init__(self, store, models=None, clock=None):
        self.store, self.models, self.clock = store, models, clock or utc_now

    def create(self, owner, body):
        data = parse(CreateInput, body)
        if not data.title.strip():
            fail('INVALID_PLAN', 'Plan title cannot be blank')
        request = data.model_dump()
        now = self.clock()
        state = {'schema_version': 1, 'card': dict(data.card.model_dump(), start_at=now.isoformat()),
                 'assessment': None, 'update_note': '首次事前判断'}
        # A domain creation must be atomic and idempotent: no orphan plan if first judgment fails.
        # Reuse platform transaction/identity/idempotency schema, no side table or migration.
        with self.store.db.transaction() as conn:
            fingerprint, replay = self.store._replay(conn, owner, data.idempotency_key, ['plans.create'], request)
            if replay is not None:
                return replay
            card = parse(Card, state['card'])
            state['assessment'] = assessment(card, now)
            validate_plan(None, state, {'type': 'initialize', '_now': now.isoformat()})
            validate_plan(state, state, {'kind': 'judgment', '_now': now.isoformat()})
            save_id, version_id, stamp = uid(), uid(), now.isoformat()
            conn.execute('INSERT INTO saves VALUES(?,?,?,?,?,?)',
                         (save_id, owner, 'plan', data.title.strip(), encode(state), stamp))
            conn.execute('INSERT INTO plan_versions VALUES(?,?,?,?,?,?,?,?)',
                         (version_id, save_id, 1, None, 'judgment', encode(state), None, stamp))
            saved = self.store._save_view(conn, self.store._save(conn, owner, save_id, 'plan'))
            first = self.store._version_view(conn.execute('SELECT * FROM plan_versions WHERE id=?', (version_id,)).fetchone())
            return self.store._remember(conn, owner, data.idempotency_key, fingerprint, {'save': saved, 'version': first})

    def detail(self, owner, save_id):
        saved = self.store.get_save(owner, save_id)
        if saved['domain'] != 'plan':
            fail('WRONG_DOMAIN', 'This is not a real-plan save')
        versions = self.store.list_versions(owner, save_id)
        current = next((v['content'] for v in reversed(versions) if v['kind'] != 'outcome'), saved['initial_state'])
        state = parse(JudgmentState, current)
        due = instant(state.card.due_at)
        now = self.clock()
        return {'save': saved, 'versions': versions, 'revision': versions[-1]['revision'] if versions else 0,
                'current': current, 'due': now >= due,
                'next_check_in_at': min(due, instant(state.assessment.assessed_at) + timedelta(days=7)).isoformat(),
                'review': self.review_versions(versions, now)}

    def list(self, owner):
        return [self.detail(owner, saved['id']) for saved in self.store.list_saves(owner) if saved['domain'] == 'plan']

    def update(self, owner, save_id, body):
        data = parse(VersionInput, body)
        detail = self.detail(owner, save_id)
        try:
            stamp = instant(data.recorded_at)
        except (ValueError, TypeError):
            fail('INVALID_ASSESSMENT_TIME', 'Use a timezone-aware recording time')
        card = parse(Card, dict(data.card.model_dump(), start_at=detail['save']['initial_state']['card']['start_at']))
        content = {'schema_version': 1, 'card': card.model_dump(), 'assessment': assessment(card, stamp), 'update_note': data.update_note}
        return self.store.append_version(owner, save_id, {
            'expected_revision': data.expected_revision, 'idempotency_key': data.idempotency_key,
            'kind': data.kind, 'content': content, 'based_on': None})

    def outcome(self, owner, save_id, body):
        data = parse(OutcomeInput, body)
        self.detail(owner, save_id)  # Ownership and correct domain before looking up history.
        content = {'schema_version': 1, 'outcome': {'judgment_id': data.based_on, 'status': data.status, 'evidence': data.evidence,
                   'actual_hours': data.actual_hours, 'recorded_at': data.recorded_at,
                   'source': 'self_reported', 'correction_note': data.correction_note}}
        return self.store.append_version(owner, save_id, {
            'expected_revision': data.expected_revision, 'idempotency_key': data.idempotency_key,
            'kind': 'outcome', 'content': content, 'based_on': data.based_on})

    @staticmethod
    def review_versions(versions, now):
        comparisons = []
        for version in versions:
            if version['kind'] != 'judgment':
                continue
            state = parse(JudgmentState, version['content'])
            outcomes = [v for v in versions if v['kind'] == 'outcome' and v['based_on'] == version['id']]
            latest = outcomes[-1] if outcomes else None
            result = latest['content']['outcome']['status'] if latest else 'unknown'
            actual = True if result == 'completed' else False if result == 'not_completed' else None
            user = {'yes': True, 'no': False}.get(state.card.user_judgment)
            simple = {'feasible': True, 'at_risk': False}.get(state.assessment.baseline.verdict)
            comparisons.append({'judgment_id': version['id'], 'revision': version['revision'],
                'criteria': state.card.completion_criteria, 'due_at': state.card.due_at,
                'state': 'not_due' if now < instant(state.card.due_at) else 'awaiting_result' if not latest else 'unknown' if actual is None else 'self_reported_result',
                'user_judgment': state.card.user_judgment, 'baseline': state.assessment.baseline.model_dump(),
                'result': result, 'outcome_version_id': latest['id'] if latest else None,
                'user_match': user == actual if user is not None and actual is not None else None,
                'baseline_match': simple == actual if simple is not None and actual is not None else None,
                'hours_error': (latest['content']['outcome']['actual_hours'] - state.card.required_hours)
                    if latest and latest['content']['outcome']['actual_hours'] is not None and state.card.required_hours is not None else None})
        return {'comparisons': comparisons, 'limitation': '单个计划的自报复盘，不是预测准确率验证；未知结果不计为失败或成功。'}

    def suggest(self, owner, save_id):
        detail = self.detail(owner, save_id)
        card = parse(Card, detail['current']['card'])
        local = assessment(card, self.clock())
        fallback = {'risks': local['risks'] or ['进展与资源仍需由用户核对。'], 'scenarios': local['scenarios']}
        if not self.models or not self.models.adapter:
            return {'mode': 'rules', 'model_status': 'disabled', 'suggestions': fallback,
                    'notice': '未配置模型，以下仅为时间预算规则建议，不是AI预测。'}
        messages = [
            {'role': 'system', 'content': 'You are a short-cycle planning assistant, not a fortune teller. Return ONLY JSON with keys risks (1–3 short strings) and scenarios (exactly two objects). Each scenario has name as a short string, assumptions as a 1–3 element string array, and actions as a 1–3 element string array. Keep the entire JSON concise, under 300 words. Treat the user facts as unverified input, name uncertainty, offer actionable conditional alternatives. Never output percentages, numerical likelihood, diagnosis, promises, success rates, hidden tool requests, or facts not supplied. These are suggestions only; never mark a real plan completed.'},
            {'role': 'user', 'content': json.dumps({'card': card.model_dump(), 'time_budget': local['baseline']}, ensure_ascii=False)}]
        try:
            result = self.models.generate(owner, save_id, 'plan.conditional_scenarios', messages)
            data = structured_json(result.text)
            parsed = Suggestions.model_validate(data)
            text = json.dumps(parsed.model_dump(), ensure_ascii=False)
            if len(text) > 16000 or any(not x.strip() or len(x) > 1000 for x in parsed.risks) or re.search(r'%|％|percent|probability|概率|成功率', text, re.I):
                raise ValueError('Unsupported claim')
            return {'mode': self.models.adapter.mode, 'model_status': 'structured_suggestion', 'suggestions': parsed.model_dump(),
                    'notice': '模型建议未经现实验证，不会自动写入事实或判断版本。'}
        except PlatformError as error:
            if error.status != 503:
                raise
            status = 'unavailable'
        except (ValueError, TypeError):
            status = 'invalid_structured_output'
        return {'mode': 'rules', 'model_status': status, 'suggestions': fallback,
                'notice': '模型不可用或输出未通过校验，已返回规则建议；真实调用/用量以审计为准。'}
