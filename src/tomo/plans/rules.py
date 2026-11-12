"""Pure, fail-closed rules for real plans. No game statistics or invented probabilities."""
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from typing import Literal
from tomo.platform.errors import PlatformError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Card(StrictModel):
    goal: str = Field(min_length=1, max_length=300)
    completion_criteria: str = Field(min_length=1, max_length=2000)
    start_at: str = Field(json_schema_extra={"format": "date-time"})
    due_at: str = Field(json_schema_extra={"format": "date-time"})
    timezone: str = Field(min_length=1, max_length=80)
    facts: list[str] = Field(default_factory=list, max_length=20)
    unknowns: list[str] = Field(default_factory=list, max_length=20)
    required_hours: float | None = Field(default=None, ge=0, le=10000)
    available_hours_per_week: float | None = Field(default=None, ge=0, le=168)
    user_judgment: Literal['yes', 'uncertain', 'no', 'unknown'] = 'unknown'

    @model_validator(mode='after')
    def boundaries(self):
        if not self.goal.strip() or not self.completion_criteria.strip():
            raise ValueError('Goal and completion criteria must be meaningful')
        if any(not text.strip() or len(text) > 2000 for text in self.facts + self.unknowns):
            raise ValueError('Fact/unknown limits exceeded')
        start, due = instant(self.start_at), instant(self.due_at)
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Timezone must be an IANA zone') from None
        days = (due.astimezone(zone).date() - start.astimezone(zone).date()).days
        if not 7 <= days <= 30 or due <= start:
            raise ValueError('Plan horizon must be 7–30 calendar days in the selected timezone')
        return self


class Scenario(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    assumptions: list[str] = Field(min_length=1, max_length=10)
    actions: list[str] = Field(min_length=1, max_length=10)

    @model_validator(mode='after')
    def bounded_text(self):
        if any(not x.strip() or len(x) > 1000 for x in self.assumptions + self.actions):
            raise ValueError('Scenario text limits exceeded')
        return self


class Baseline(StrictModel):
    method: Literal['time_budget_v1'] = 'time_budget_v1'
    available_hours: float | None
    required_hours: float | None
    verdict: Literal['feasible', 'at_risk', 'unknown']


class Assessment(StrictModel):
    mode: Literal['rules'] = 'rules'
    assessed_at: str = Field(json_schema_extra={"format": "date-time"})
    judgment: Literal['feasible', 'at_risk', 'unknown']
    reason: str = Field(min_length=1, max_length=2000)
    risks: list[str] = Field(max_length=20)
    scenarios: list[Scenario] = Field(min_length=2, max_length=2)
    baseline: Baseline
    limitation: Literal['时间预算不是现实成功概率；输入是用户自报估计，结果未验证。']

    @model_validator(mode='after')
    def valid_clock(self):
        instant(self.assessed_at)
        return self


class JudgmentState(StrictModel):
    schema_version: Literal[1] = 1
    card: Card
    assessment: Assessment
    update_note: str = Field(default='', max_length=3000)


class Outcome(StrictModel):
    judgment_id: str = Field(min_length=1, max_length=100)
    status: Literal['completed', 'not_completed', 'unknown']
    evidence: str = Field(max_length=5000)
    actual_hours: float | None = Field(default=None, ge=0, le=10000)
    recorded_at: str = Field(json_schema_extra={"format": "date-time"})
    source: Literal['self_reported'] = 'self_reported'
    correction_note: str = Field(default='', max_length=3000)

    @model_validator(mode='after')
    def valid_clock(self):
        instant(self.recorded_at)
        return self


class OutcomeState(StrictModel):
    schema_version: Literal[1] = 1
    outcome: Outcome


def instant(text):
    if not isinstance(text, str) or len(text) > 80:
        raise ValueError('Timezone-aware RFC3339 time required')
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})', text):
        raise ValueError('RFC3339 time required')
    value = datetime.fromisoformat(text.replace('t', 'T').replace('z', 'Z').replace('Z', '+00:00'))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone-aware RFC3339 time required')
    return value.astimezone(timezone.utc)


def fail(code, message):
    raise PlatformError(422, code, message)


def parse(model, data):
    try:
        return model.model_validate(data)
    except (ValidationError, ValueError, TypeError):
        fail('INVALID_PLAN', 'Plan content does not satisfy the real-plan contract')


def baseline(card, now):
    remaining = max(0, (instant(card.due_at) - now).total_seconds() / 86400)
    available = round(card.available_hours_per_week * remaining / 7, 2) if card.available_hours_per_week is not None else None
    required = card.required_hours
    verdict = 'unknown' if available is None or required is None else 'feasible' if available >= required else 'at_risk'
    return {'method': 'time_budget_v1', 'available_hours': available, 'required_hours': required, 'verdict': verdict}


def assessment(card, now):
    simple = baseline(card, now)
    risks = []
    if simple['verdict'] == 'at_risk':
        risks.append('自报所需时间超过当前可用时间；需要确认资源或调整范围。')
    if simple['verdict'] == 'unknown':
        risks.append('缺少所需工时或每周可用时间，无法进行时间预算对照。')
    if card.unknowns:
        risks.append('仍有未确认信息，需先核对：' + '；'.join(card.unknowns[:3]))
    if not card.facts:
        risks.append('尚无已确认事实；先补充当前进度和资源。')
    return {'mode': 'rules', 'assessed_at': now.isoformat(), 'judgment': simple['verdict'],
            'reason': '仅比较用户自报工时与截止前可用时间，不代表现实成功率。', 'risks': risks,
            'scenarios': [
                {'name': '按现范围推进', 'assumptions': ['目标、完成标准和自报可用时间保持不变。'], 'actions': ['优先核对未知项，拆分本周最小可交付步骤。', '一周后记录实际进展并重新估算剩余工作。']},
                {'name': '资源不足时缩小范围', 'assumptions': ['用户愿意主动选择缩减范围；不能偷偷更改原完成标准。'], 'actions': ['标出可以推迟的非核心事项。', '如决定改变完成标准，创建新的事前判断版本，保留原判断用于复盘。']}
            ], 'baseline': simple,
            'limitation': '时间预算不是现实成功概率；输入是用户自报估计，结果未验证。'}


def validate_plan(old, proposed, event):
    """Trusted _now/_judgment are inserted by Store, not accepted from HTTP input."""
    try:
        now = instant(event['_now'])
    except (KeyError, ValueError, TypeError):
        fail('TRUSTED_CONTEXT_REQUIRED', 'Server time context is required')
    kind = event.get('kind')
    if kind == 'outcome':
        outcome = parse(OutcomeState, proposed).outcome
        reference = event.get('_judgment')
        if not isinstance(reference, dict) or reference.get('id') != event.get('based_on'):
            fail('TRUSTED_CONTEXT_REQUIRED', 'Server-resolved judgment is required')
        if outcome.judgment_id != reference['id']:
            fail('INVALID_JUDGMENT_REFERENCE', 'Outcome snapshot must identify the referenced judgment')
        judgment = parse(JudgmentState, reference.get('content'))
        if instant(reference['created_at']) > now:
            fail('INVALID_JUDGMENT_REFERENCE', 'Judgment must precede evaluation')
        if now < instant(judgment.card.due_at):
            fail('OUTCOME_TOO_EARLY', 'Wait until this judgment’s deadline before evaluating it')
        if abs((instant(outcome.recorded_at) - now).total_seconds()) > 300:
            fail('INVALID_RECORDED_TIME', 'Outcome recording time must be current server time')
        if outcome.status != 'unknown' and not outcome.evidence.strip():
            fail('EVIDENCE_REQUIRED', 'Completed/not-completed results require an evidence note')
        if type(event.get('_outcome_count')) is not int or event['_outcome_count'] < 0:
            fail('TRUSTED_CONTEXT_REQUIRED', 'Server-resolved outcome count is required')
        if event['_outcome_count'] > 0 and not outcome.correction_note.strip():
            fail('CORRECTION_NOTE_REQUIRED', 'Append a correction note; never overwrite an earlier result')
        return
    state = parse(JudgmentState, proposed)
    checked_at = instant(state.assessment.assessed_at)
    if abs((checked_at - now).total_seconds()) > 300:
        fail('INVALID_ASSESSMENT_TIME', 'Assessment time must be current server time')
    if state.assessment.baseline.model_dump() != baseline(state.card, checked_at):
        fail('INVALID_BASELINE', 'Time budget must be derived from the recorded input')
    if state.assessment.judgment != state.assessment.baseline.verdict:
        fail('INVALID_BASELINE', 'Rule judgment must match its baseline')
    if state.assessment.model_dump() != assessment(state.card, checked_at):
        fail('INVALID_ASSESSMENT', 'Rule assessment must be generated from this card')
    if event.get('type') == 'initialize':
        if old is not None or abs((instant(state.card.start_at) - now).total_seconds()) > 300:
            fail('INVALID_PLAN_START', 'New real plans start at current server time')
        return
    if kind not in ('judgment', 'update'):
        fail('INVALID_PLAN_VERSION', 'Use judgment, update or referenced outcome')
    if old and 'outcome' in old:
        fail('PLAN_ALREADY_REVIEWED', 'Create a new plan rather than rewriting a reviewed plan')
    if old:
        previous = parse(JudgmentState, old)
        if previous.card.start_at != state.card.start_at:
            fail('IMMUTABLE_PLAN_START', 'Original plan start is immutable')
        if kind == 'update' and any(getattr(previous.card, k) != getattr(state.card, k) for k in ('goal', 'completion_criteria', 'due_at', 'timezone')):
            fail('NEW_JUDGMENT_REQUIRED', 'Changes to the target, criteria or deadline require a new judgment version')
        if not state.update_note.strip() and state.model_dump() != previous.model_dump():
            fail('UPDATE_NOTE_REQUIRED', 'Explain the changed facts or new judgment')
    if now >= instant(state.card.due_at):
        fail('JUDGMENT_TOO_LATE', 'Do not create a retrospective judgment after its deadline')
