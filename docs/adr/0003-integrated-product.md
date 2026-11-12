# ADR-0003: Integrated product and runtime gates

Accepted 2026-11-13. This is the deployable composition of the three independent feature branches, not a replacement for the frozen platform v1 schema. The product factory is `tomo.app:create_product_app`; `integration/contracts.py` owns the composed OpenAPI snapshot while the original platform-only contract check remains intact.

## Integration repairs

- Domain UI accepts full `/api/v1/*` paths; shell normalizes the canonical prefix before applying its configured same-origin base. No bearer is forwarded cross-origin.
- Game turn provenance signs the server-derived owner/save/branch context as well as payload. Generic event writes cannot replay another resource's valid proof. Invalid/malformed model tools return a controlled503 without changing state; the provider audit still records actual paid usage.
- Game creation supports explicit owner-scoped idempotency. UI retains the same creation body/key when retrying an unconfirmed response. Game causal links scroll within the current domain rather than replacing the shell hash route.
- Branch serialization checks ownership before allocation and uses reference-counted locks removed after the final holder/waiter; missing resources cannot create a permanent lock map. The deployment must remain single process for this provider-call guarantee.
- Shell async results are guarded by session generation/token; stale lists, enter responses and domain callbacks cannot update a newer account. An old401 cannot clear a newer token.
- JSON contract validation rejects nested non-finite values before serialization or persistence; noNaN→500 path.
- HTTP provider error bodies are read with the same finite response cap as success bodies, and explicitly reported usage is retained on errors. Provider cost/currency fields are configurable, never estimated from a tariff or text length.
- Model transport requests a configured output cap and context is bounded. Real calls use a per-process concurrency semaphore and persistent global/user daily attempt gates; failed/retried real attempts count. The unlimited *development* budget does not grant unlimited anonymous product calls.
- Structured model content may be raw JSON or exactly one complete JSON fence; prose scraping, non-finite JSON and schema-invalid objects remain rejected. Game prompts expose legal action options without granting direct state writes; plan name/array types are explicit. An invalid provider interaction remains recorded as failure/fallback, not hidden by retrying until a desirable outcome.
- Request bodies, including chunked bodies, are bounded before JSON parsing. The default deployment is same-origin and has CSP/self-only scripts and no-store/security headers.

## Validation boundaries

Provider verification includes real synthetic calls and persisted input/output/cache usage; missing cost remainsnull. Earlier invalid tool, output truncation and fenced-JSON failures remain in private QA records. One repaired smoke does not prove general reliability, prediction accuracy or product-market fit. Browser future-outcome QA uses a test-only clock endpoint that is never present in the product factory.

The public source does not contain credentials, user records, private task-routing receipts or raw model output. Deployments retain separate persistent data volumes and explicit backup/restore/rollback steps. DNS/TLS and a specific public deployment require an actually configured target; container/start scripts alone are not claimed as a public launch.
