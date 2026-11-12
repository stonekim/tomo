"""Additive domain schemas for integration; no change to frozen platform v1 shape."""
from .rules import Card, JudgmentState, OutcomeState
from .service import CreateInput, VersionInput, OutcomeInput, Suggestions


def contract_document():
    return {'contract_version': 1, 'domain': 'plan',
            'schemas': {name: cls.model_json_schema() for name, cls in {
                'PlanCard': Card, 'PlanJudgmentState': JudgmentState, 'PlanOutcomeState': OutcomeState,
                'PlanCreate': CreateInput, 'PlanUpdate': VersionInput, 'PlanOutcome': OutcomeInput,
                'PlanModelSuggestions': Suggestions}.items()},
            'business_constraints': [
                'Original plan horizon is 7–30 calendar days in the selected IANA zone; timestamps must have a UTC offset and timezone is an IANA zone.',
                'Server clock controls due-date eligibility. Referenced judgment is resolved by server, never supplied by clients.',
                'Only append immutable versions. Criteria/goal/deadline changes require a new judgment, not an update.',
                'No numeric success probability; qualitative time-budget baseline is not a validated forecast.',
                'Create includes an atomic first judgment and owner-scoped idempotency key.',
                'recorded_at is generated once per user mutation; retry identical payload/key. Server verifies freshness before committing.',
                'Outcomes are self-reported, must reference an existing judgment and cannot precede that judgment’s deadline.',
                'Unknown/missing results stay unknown/null, never success/failure/zero.'
            ]}
