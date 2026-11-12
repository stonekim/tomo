# Product deployment and rollback

The composed application is `tomo.app:create_product_app`, not the platform-only CLI `serve`. Both domains are validated by one shared registry/store and the frontend is served from `web/` on the same origin. Default model mode is **disabled**; the playable local rule-agent is clearly marked and plan advice is a time-budget rule comparison, not a real prediction.

## Local single-command startup

```
./deploy/start-local.sh
# http://127.0.0.1:8017/
```

Python 3.11+ required. The script installs pinned dependencies into `.venv`, migrates the configured `TOMO_DATABASE` (default `./data/tomo.sqlite3`) and runs **one** Uvicorn worker. Do not enable multi-worker execution: game-request serialization is process-local. The account database is persistent, never seeded with QA users. New users register in the UI. Use a supervisor/systemd/Docker for persistent operation, not a shell background process.

## Container

```
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml ps
curl --fail http://127.0.0.1:8017/healthz
```

To supply private settings explicitly, use `docker compose --env-file /private/tomo.env -f deploy/compose.yaml ...` or inject server environment from your secret manager; never put an actual key in the tracked example.

The nonroot container binds only localhost, uses a named persistent volume `/data`, drops Linux capabilities, has a read-only application filesystem and health check. **Never use `down -v` as an upgrade/rollback command**. The container sets `TOMO_WEB_ROOT=/app/web`; source checkouts infer their own web directory.

## Configuration (server environment only)

- `TOMO_DATABASE`: persistent SQLite path; never place under the web directory.
- `TOMO_SESSION_HOURS`: 1–168, default24.
- `TOMO_ALLOWED_ORIGINS`: empty by default; same-origin API requires no CORS opening.
- `TOMO_MODEL_MODE`: `disabled`, `mock` or `real`; mock is not a verified provider.
- `TOMO_MODEL_ENDPOINT`, `TOMO_MODEL_NAME`, `TOMO_MODEL_API_KEY`: real provider only, fixed HTTPS endpoint. Use a private configuration/secret reference launcher; never commit a key, include it in URLs, or pass it to the browser.
- `TOMO_MODEL_MAX_OUTPUT_TOKENS`: 1–4096, default1200; provider-side request output cap, not a billing guarantee. Reasoning models may need a higher tested value.
- `TOMO_MODEL_TIMEOUT`: default20 seconds, up to120; `TOMO_MODEL_ATTEMPTS`:1–3 (default2).
- `TOMO_MODEL_CONCURRENCY`:1–8, default2, per process.
- `TOMO_MODEL_DAILY_CALLS`: default200 global real-provider attempts/day UTC; `TOMO_MODEL_USER_DAILY_CALLS`: default20/user/day. Each retry is a separately audited/charged attempt; limits use persisted audit rows and survive restarts. These deployment allowances are unrelated to the user's unlimited development budget.
- `TOMO_MODEL_COST_FIELD`, `TOMO_MODEL_CURRENCY_FIELD`: provider `usage` member names, default`cost`/`currency`. Only explicitly reported finite amounts/currency are retained; no tariff inference. Missing input/output/cache/cost staysnull.
- `TOMO_MAX_REQUEST_BYTES`:16384–2000000, default524288, including chunked JSON bodies.

Real invocation context is limited to32000 characters. Model outputs remain untrusted; game tools are checked against world rules and signed with owner/save/branch binding, plan suggestions cannot directly write facts or outcomes. A provider returning unusable/illegal content is an actual failed interaction, not a successful game turn. The UI may explicitly return rule advice when model suggestions fail; audit still records the real call. Do not advertise reliable predictions, retention, or successful payment from these engineering checks.

## HTTPS

Use a dedicated domain, for example a separately configured `tomo.example.com`, and a TLS reverse proxy:

```
tomo.example.com {
    reverse_proxy 127.0.0.1:8017
}
```

This is a deployment example, **not** a claim that DNS/TLS is configured. Preserve same-origin paths `/api/v1/*`, `/src/*` and `/`. Do not expose raw data volumes or credentials. Existing kimsh.top/SA routing is untouched. Configure upstream request/header/time limits and access logs without bodies/Authorization. The app emits a strict self-only CSP and no-store, nosniff, no-referrer, frame denial headers.

## Backup and restoration

Use a private destination outside web roots. SQLite backup API creates an integrity-checked 0600 snapshot and refuses to overwrite an existing file:

```
python deploy/database.py backup ./data/tomo.sqlite3 /private/backups/tomo-YYYYMMDD.sqlite3
```

Stop the application service/container first, confirm no target SQLite sidecars remain after a clean shutdown/checkpoint, then:

```
python deploy/database.py restore /private/backups/tomo-YYYYMMDD.sqlite3 ./data/tomo.sqlite3 --confirm-service-stopped
```

The flag is an operator assertion, **not** automatic proof that every process is stopped. Restore refuses sidecars and preserves the prior target as `.before-restore-*`; never delete these rollback files before verification. For container volumes, run the script in an offline utility container with the same volume and private backup mount; do not copy a live WAL database file with `cp`.

## Upgrade/rollback

Record the deployed Git commit/image digest, take a verified backup, stop the application, deploy the reviewed commit, start, then check health, login and an owned existing save. Backward-incompatible database versions fail closed. To roll back code, use the previously recorded image/commit; keep the persistent database and any new user data. If a schema rollback is truly needed, stop and explicitly restore a known backup with the documented data-loss boundary; don't silently replace current data. Never overwrite the host's original research checkout to roll back this dedicated integration branch.

## Verification

```
.venv/bin/python -m pytest -q
node --test tests/shell/api.test.cjs
PYTHONPATH=src .venv/bin/python tests/system/run_browser.py
```

Browser QA creates temporary synthetic users/DB, runs both real HTTP domain paths and a **test-only** controlled clock for due outcomes, then shuts down. It never adds a time-travel endpoint to the product. Real provider QA is separate and opt-in: `tests/system/real_provider_smoke.py` requires an authorized private server environment and records actual usage, not secrets or model response text. Backend tests use synthetic provider transports unless explicitly labelledreal. QA screenshots/raw logs are private scratch artifacts, not customer proof.

## Recorded candidate checks (2026-11-13)

116 Python tests, 7 Node API checks, 20 composed-product browser checks and 5 real Docker checks passed. The official Python slim image was built cleanly; the nonroot/read-only container was replaced while retaining the named-volume account/session/event data and reached healthy. Backup/restore uses temporary synthetic data with rollback preservation. No production data was restored or discarded.

The configured real provider was exercised with synthetic game tools and plan scenarios. The repaired final two-call smoke passed at requested outputcap2400; earlier illegal-tool, truncated/invalid structured output and fenced-JSON failures remain in private QA evidence. This is not a reliability benchmark. Public-source verification is in`docs/release/verification.json`, raw QA evidence is untracked private scratch. The host's loopback preview uses a separate persistent database and host-private configuration reference, not credentials in the Git tree.

## Prefix-stripping administrator proxy

The frontend now infers its API base from the HTTP module URL (`../../api/v1` relative to `src/shared/api.js`). Root hosting still uses`/api/v1`; a fixed administrator proxy at`/read/tomo/app/` automatically uses`/read/tomo/app/api/v1`. HTML entry script/CSS and domain styles use relative URLs. The upstream business API remainsroot-based; the proxy strips the configured prefix. An explicit same-origin meta override is still supported when required. Do not open `/read/` with an unauthenticated catch-all proxy or weaken the existing administrator gate.

A real isolated HTTP prefix-stripping proxy plus actual Chromium completed21 checks at`/read/tomo/app/`, including registration, full game ending and independent fork, plan updates/controlled due review, account-switch races, and mobile/desktop layout. The root version also passed21 browser checks. A delayed old logout response now preserves the new session **and** leaves its logout button usable; the test performs a normal logout afterward.
