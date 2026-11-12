# TOMO-MVP-00 contract freeze v1

冻结日期：2026-11-12。来源 spec SHA256 `f6c66fad3aafae6a0354f5dcf335487e32846ad15325696ad1440239793085b6`。

目录所有权、错误语义、分叉/版本语义与技术栈：见 ADR-0002。机器契约：`src/tomo/contracts/v1.json`、`docs/contracts/openapi.json`。契约冻结不等于01–04业务验收。

## Integration entry points

`create_app(settings, rule_registry=..., domain_routers=...)` returns the shared ASGI application. Domain routers use `Depends(current_user)` and `request.app.state.store` / `.models`, never accept an owner ID from a browser. `RuleRegistry.register(domain, validator)` installs a pure `(old_state, proposed_state, event) -> None` validator. Raise `PlatformError(422, 'INVALID_TRANSITION', ...)` to reject. The registry checks detached JSON; missing validators reject with 503, with no write. 01 owns initial state/transition/character/tool rules and registers `game`; 02 owns due-date/forecast/update/result rules and registers `plan`. The foundation's generic schema accepts JSON objects, not completed domain semantics. 01/02 must publish their narrower state schemas through a coordinated v1 additive contract update before UI acceptance.

Create save → receive initial branch for game or revision 0 for plan. HTTP event append uses expected revision, idempotency key, proposed state and causal event IDs; these are proposals subject to server rules. Fork specifies an existing sequence; prefix IDs and states are preserved. Read branch returns replayable full prefix plus independent suffix. Plan append creates a new immutable version, `kind=judgment|update|outcome`, with `based_on` for an outcome. 02 must reject premature outcomes and enforce 7–30 day cards via its validator. Platform rejects missing/foreign judgment references and future causal references. No endpoint overwrites a prior version.

Model service is called by domain code as `app.state.models.generate(owner_id, save_id, purpose, messages)`. Owner and save are verified before dispatch. Provider is fixed in settings. No model endpoint is exposed to browser callers. Use authorized store reads to assemble prompt context; never mix game/plan without explicit user authorization. Treat returned model text as untrusted proposal, parse and validate with domain rules. `MockAdapter` is deterministic and its audit `mode=mock`; `HttpAdapter` audits `mode=real`. Disabled provider returns 503 without a network request. Actual real invocation acceptance remains null until separately run with authorized configuration.

## Commands

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/python -m tomo.platform.cli migrate
.venv/bin/python -m tomo.platform.cli contracts --check
.venv/bin/python -m pytest -q
.venv/bin/python -m tomo.platform.cli serve --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/healthz
```

`contracts` regenerates OpenAPI; `contracts --check` detects drift and validates JSON Schema. SQLite auto-migrates on startup, rejects future database versions, and persists accounts/sessions/saves/events/versions/audit across restarts. Use `TOMO_DATABASE` for a persistent path. Config defaults bind locally, disable real models and disable cross-origin access. Reverse proxy HTTPS and volume/backup/restore/container/rollback integration belong to 04; no production deployment is claimed here.

## Pending owners

01: game rules, characters/tools/autonomy, endings, causal explanations and game UI. 02: complete plan card schema, time zone and deadline semantics, scenarios/baselines and review UI. 03: shared shell/login/navigation/archive/explicit privacy controls; storage has no deletion API in 00. 04: full browser/E2E, clean deployment, backup/restore, real-provider smoke and accessible acceptance environment. Neither product completion nor prediction validity is claimed.
