# TOMO-MVP-01: Fictional alternative-work-life game

## Integration surface

- `from tomo.game import router, register_game_rules`
- Register `register_game_rules(registry)` once, then `create_app(settings, rule_registry=registry, domain_routers=[router, ...])`.
- Frontend: `import {mountGame} from '/.../game/index.js'`; call `mountGame(root, context)` and call the returned cleanup before changing routes.
- `context.api(path,{method,body})` accepts an **absolute `/api/v1/...` path**, returns parsed JSON, rejects HTTP failures with `error.status` and preferably `error.message`. Auth is supplied by the shell; game never reads or persists bearer tokens.
- Optional context: `saveId`, `save`, `onSaveCreated(save)`, `onUnauthorized()`. Newly created saves invoke `onSaveCreated`; an existing ID reloads its branch. Branch choice alone is retained in sessionStorage (opaque IDs, no scenario, dialogue or credentials).
- Owns `src/tomo/game`, `web/src/game`, `tests/game`, `docs/game`. No platform or public schema file is changed by this task. The composed application's generated OpenAPI includes the following strict Pydantic domain routes; 04 should generate its full OpenAPI only after composition.

## Domain HTTP contract

All routes require the platform's bearer session. Wrong owner returns404; wrong save domain422. Bodies reject unknown fields.

| Method | Path after `/api/v1/game` | Input | Result |
|---|---|---|---|
| POST | `/saves` | `{scenario:1..1200 chars,title?:1..180 chars,engine?:"local"\|"model"}` | 201 `{save,branch,ending:null,agent_mode}` |
| GET | `/saves/{save}/branches` | — | `{save,branches:[{branch,ending,agent_mode}]}` |
| GET | `/saves/{save}/branches/{branch}` | — | `{branch,ending,agent_mode}` |
| POST | `/saves/{save}/branches/{branch}/actions` | `{action:{action,...tool args},expected_revision:int>=0,idempotency_key:8..100 chars}` | `{branch,ending,agent_mode}` |
| POST | `/saves/{save}/branches/{branch}/fork` | `{at_sequence:int>=0,idempotency_key:8..100 chars}` | 201 `{branch,ending,agent_mode}` |

Player tools: `move(destination)`, `talk(target,text?)`, `inspect(item)`, `take(item)`, `give(item,target)`, `decide(choice:"accept"|"stay")`, `wait()`, `finish()`. Frontend never submits `actor`; server sets `player`. Actors are player,mira,chen,lin; places office,cafe,studio; items notebook,key,coffee. Each NPC can perform only move/talk/take/give/wait, at most once in a turn; no NPC can choose for the player.

State is a constrained v1 world: positions, unique object holders, capped relationships, learned objects, per-character bounded structured memories, immutable accepted/stay choice, turn0–8, finite ending. At least2 explored turns before finish; all branches end by turn8. A decision cannot be overwritten, but can be changed in a branch forked before that event. Actual duration depends on reading and choices; a measured 15-minute duration is **not** claimed.

Possible endings: stable_plan, collaborative_jump, solo_jump, undecided. Player decision and active conversation with Mira determine the outcome; inventory affects available interactions and exposes concrete clues. Endings contain references to actual persisted event IDs in the branch, never inferred reality success percentages. Branch histories preserve prefix IDs and have independent suffixes.

## Agent/runtime boundary

- `engine=local` is a **clearly labelled rule-agent demonstration**, not an LLM call. Goals and current locations produce inspectable NPC proposals; the same world rules validate and persist them.
- `engine=model` requires a configured platform adapter. Each turn calls `app.state.models.generate` with only this user's game state and goals, parses JSON `{actions:[...]}`, and rejects invalid/impossible tools without any world write. Dialogue is untrusted fictional speech, not factual prediction. Real adapter's audit is `mode=real`; structured test adapter is `mode=mock`. No real-provider acceptance is claimed here.
- Model responses cannot set state, ending, actor inventory or the player's choice directly. A valid tool can still produce creative dialogue. Player tools are validated **before** a model request so invalid moves do not incur model usage.
- Pending duplicate requests within this one-process deployment are serialized per branch. A successful repeated key returns the current branch without another model call; changed tool/revision under the same key409. Store transactions also enforce CAS/idempotency. Multi-process deployment would need distributed request serialization to avoid duplicate model charges, though state CAS remains protected.
- Turns carry a process-secret signature to stop clients using the generic event endpoint to invent tool provenance; the secret is never sent to the client or persisted. Old events are read without requiring a previous process's secret. Context-binding integration is documented separately if required by the final platform composition.
- No agents run in the background. No photography, messaging, real payments or purchase claims are implemented.

## Verification

Use the project virtual environment, with the selected checkout first on PYTHONPATH:

```sh
PYTHONPATH=src python -m pytest tests/game tests/platform -q
PYTHONPATH=src python tests/game/check_browser.py
```

Browser harness creates a disposable localhost ASGI server and temp SQLite DB, uses synthetic accounts/scenario, never accesses production or a provider, and shuts the server down in `finally`. Requires local Playwright/Chromium paths currently documented in the test script; 04 may parameterize them for CI. It checks a full ending, causal references, a consequential fork, original-world preservation, reload, 393/1440 widths, HTML-injection-safe scenario rendering and disabled-provider failure. Harness results and screenshots are scratch output, not a shipped test user or seeded customer record.

First backend run correctly rejected a fixture conversation with a character at a different location; fixture path was fixed. First browser run used a QA username containing a hyphen contrary to the existing auth contract and received401 rather than a fake success; fixture now asserts registration201 and uses an allowed username. Final counts are recorded in `verification.json` once completed.

## Remaining release gates

Real provider smoke/usage receipts, full shell composition, production database persistence/HTTPS/deployment/rollback and complete product E2E remain 04 responsibilities. A safe local/mock game does not establish real-agent reliability, prediction accuracy, retention or willingness to pay.
