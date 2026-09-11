# AI-Provider-Abstraktion — Design (Feature 1 of 5: AI Integration)

Date: 2026-09-11
Status: Approved (brainstorm session)
Scope: Foundation feature. Features 2–5 (Prompt-Template-Bibliothek, Admin Prompt-UI, AI-QC-Erweiterung, AI-Attribut-Anreicherung) get their own spec cycles and build on this one.

## Purpose

A swappable, resilient interface for LLM calls used by all later AI features (QC policy/image checks, attribute enrichment, title optimization). Centralizes provider access, caching, retry/backoff, circuit breaking, and cost tracking so no caller duplicates these concerns and provider swaps never touch calling code.

Terminology: this codebase uses **Client** for the tenant entity (1 client → n feed sources). Requirements written as "Merchant" map onto `clients`.

## Decisions (from brainstorm)

| Decision | Choice |
|---|---|
| Interface shape | Generic `complete()` + task registry (task semantics live in prompt templates, not provider methods) |
| Provider config storage | DB-backed admin settings (`ai_provider_configs` table, admin CRUD) |
| Cost tracking | Dedicated per-call usage table (`ai_usage_logs`) |
| Result cache | DB table (`ai_result_cache`), hash-keyed |
| Circuit breaker | In-process state per provider config |
| First protocol | OpenAI-compatible only (self-hosted via `base_url` override) |
| UI scope | Backend + minimal admin UI (provider settings + usage overview) |

## Placement

New domain module `backend/app/ai/`, peer to `qc/`, `staging/`, `export/`. Rejected alternatives: pipeline plugin (wrong lifecycle — plugins are per-product transformers bound to a feed source; the provider is shared infrastructure) and a separate AI gateway service (new deployable + ops burden for a single-app codebase).

## Module layout

```
backend/app/ai/
  __init__.py        # exports AiService, AIProvider, AiRequest, AiResponse, AiResult
  provider.py        # AIProvider Protocol, AiRequest/AiResponse dataclasses
  tasks.py           # task registry: task_type -> (prompt renderer, response validator)
  openai_compat.py   # OpenAICompatibleProvider (httpx, no vendor SDK)
  resilience.py      # retry/backoff + in-process circuit breaker
  cache.py           # DB result cache (lookup + store)
  service.py         # AiService facade: resolve -> cache -> call -> log -> return
  usage.py           # usage log writer + aggregation queries
  models.py          # SQLAlchemy models (3 tables)
  routes.py          # /admin/ai/* API
  schemas.py         # pydantic request/response models
```

### `provider.py`

```python
class AIProvider(Protocol):
    async def complete(self, request: AiRequest) -> AiResponse: ...

@dataclass(frozen=True)
class AiRequest:
    task_type: str
    messages: list[dict[str, str]]   # [{"role": "system"|"user", "content": str}]
    response_format: dict[str, Any] | None  # optional JSON schema
    max_tokens: int
    temperature: float

@dataclass(frozen=True)
class AiResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    latency_ms: int
```

No task-specific methods (`enrich_title()` etc. live nowhere in the provider). Adding a new AI task later = registry entry + prompt template + validator; zero provider changes.

### `tasks.py`

Registry mapping `task_type → TaskSpec`. Shipped task types: `title_optimization`, `category_classification`, `policy_check`, `attribute_enrichment`, `image_quality`. Each `TaskSpec` holds:

- `render(variables: dict) -> list[message dicts]` — built-in default prompt renderer (Feature 2 replaces these with versioned DB templates; the registry is the seam)
- `validate(content: str) -> Any` — response validator/JSON parser; raises on invalid model output

### `resilience.py`

- **Retry**: exponential backoff with jitter, max 3 attempts, retried on 429/timeout/5xx only. After final failure the service returns a fallback result (never raises to callers).
- **Circuit breaker**: in-process, one instance per provider config. Closed → open after 5 consecutive failures within a 60 s window → half-open probe after 30 s cooldown. One successful half-open call closes it. All thresholds configurable per provider config. State is not shared across processes (single-instance deployment assumption, consistent with in-process scheduler and LockRegistry).

### `service.py` — `AiService`

```python
@dataclass(frozen=True)
class AiResult:
    value: Any            # validated/parsed output; None on fallback
    status: str           # "ok" | "cache_hit" | "fallback"
    error_code: str | None  # "timeout" | "rate_limited" | "circuit_open" | ...
    prompt_tokens: int
    completion_tokens: int

async def run_task(task_type, variables, *, client_id, feed_source_id=None) -> AiResult
```

Flow: resolve task spec → build cache key → cache lookup → on miss: render prompt → provider call through retry+breaker → validate → cache store → usage log → return. On cache hit: log `cache_hit=true, tokens=0` usage row, return. On any provider failure: return `status="fallback", value=None` plus `error_code`; **the pipeline never blocks on AI errors** — callers decide their own non-AI fallback value.

Constructed in `lifespan()`, attached to `app.state.ai_service`. Feature 1 ships no pipeline-step consumers; Features 4/5 consume it.

## Data model (3 tables, one alembic migration)

### `ai_provider_configs`

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| name | String(255), unique | human label |
| provider_type | String(50) | `openai_compatible` (only value initially) |
| base_url | String(1024) | e.g. `https://api.openai.com/v1` or self-hosted |
| api_key | String(1024) | write-only via API; redacted in all responses and logs (same redaction discipline as export tokens in `main.py`) |
| model | String(255) | e.g. `gpt-4o-mini`, `llama3.3:70b` |
| input_price_per_mtok | Numeric, nullable | cost estimation |
| output_price_per_mtok | Numeric, nullable | cost estimation |
| max_concurrency | Integer | semaphore per config |
| timeout_s | Integer | per-request timeout |
| enabled | Boolean | |
| is_default | Boolean | one default enforced at write time |
| created_at / updated_at | DateTime(tz) | |

### `ai_result_cache`

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| task_type | String(100) | |
| provider_config_id | FK → ai_provider_configs | |
| model | String(255) | model is part of the key — model swap invalidates |
| template_version | String(100) | `builtin` initially; Feature 2's versioned templates plug in here — prompt edits invalidate cache gracefully |
| input_hash | String(64) | sha256 over canonical JSON of the template variables (staging `content_hash` discipline: unchanged product content → hit, no repeat call) |
| output | JSONB | validated response payload |
| created_at | DateTime(tz) | |

Unique constraint: `(task_type, provider_config_id, model, template_version, input_hash)`.

No TTL eviction: content-hash + template-version keying makes stale results practically impossible; growth handled by retention job.

### `ai_usage_logs`

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| client_id | Integer, nullable | per-tenant cost attribution |
| feed_source_id | FK, nullable | per-feed attribution |
| task_type | String(100) | |
| provider_config_id | Integer | |
| model | String(255) | |
| cache_hit | Boolean | cost reports show avoided spend |
| prompt_tokens | Integer | |
| completion_tokens | Integer | |
| cost_usd | Numeric, nullable | estimate from prices; null when prices unset |
| latency_ms | Integer | |
| error_code | String(100), nullable | `timeout`, `rate_limited`, `circuit_open`, `invalid_response`, … |
| created_at | DateTime(tz) | indexed |

Retention: extend the existing purge-job pattern — configurable `ai_usage_retention_days` in `GlobalSetting` (default 90), purged by the daily system purge job. Same for `ai_result_cache` rows older than a configurable retention (default 90) so the cache table cannot grow unbounded either.

## API surface (all admin-RBAC guarded)

- `GET /admin/ai/providers` — list (api_key redacted)
- `POST /admin/ai/providers` — create
- `PATCH /admin/ai/providers/{id}` — update (api_key optional on update; absent = unchanged)
- `DELETE /admin/ai/providers/{id}` — delete (runs read config at call time; deleting a config makes the next AI call fall back — no in-flight-run protection needed)
- `POST /admin/ai/providers/{id}/test` — live ping completion ("Reply with OK"), reports latency + token usage of the probe
- `GET /admin/ai/usage?client_id=&feed_source_id=&task_type=&from=&to=&group_by=client|feed_source|task_type|day` — aggregated counts/tokens/cost

No pipeline-facing endpoints in Feature 1.

## Frontend (minimal)

- New **AI** tab in `AdminPage.tsx` (pattern: existing users/clients/settings tabs) with two sub-areas:
  - **Providers**: table of configs (name, model, enabled, default badge), create/edit modal with write-only api_key field, "Test connection" button calling the test endpoint
  - **Usage**: time-range + group-by filters, aggregated token/cost/call table (no charts in this feature)
- Location: `frontend/src/features/admin/ai/` — `ProviderConfigPage.tsx`, `UsagePage.tsx`; the tab switches between them
- TanStack Query hooks in `api/hooks.ts` + types in `api/types.ts`; i18n under `admin` namespace per convention

## Error handling summary

| Failure | Behavior |
|---|---|
| 429 / rate limit | retry with backoff (max 3) → breaker failure count → eventually open circuit → callers get `status=fallback` |
| Timeout | same path, `error_code="timeout"` |
| 5xx / connection error | same path |
| Invalid model output | no retry (response was delivered), `error_code="invalid_response"`, fallback result |
| Circuit open | immediate fallback, no call attempt, `error_code="circuit_open"` |
| No provider configured / disabled | immediate fallback, `error_code="no_provider"` |
| Cache write failure | logged, does not fail the call (result still returned) |
| Usage log failure | logged, does not fail the call |

The per-feed-source run lock and pipeline error handling are untouched — AI failures degrade to non-AI values, never abort runs.

## Testing

- **Unit** (no network): `FakeProvider` returning canned responses; cache hit/miss including template-version and model invalidation; breaker state machine with `TestClock`; retry/backoff timing via `httpx.MockTransport`; usage-log aggregation queries
- **Contract**: provider config CRUD redaction (api_key never in responses); test endpoint against mock transport
- **Acceptance criteria mapping**:
  - Provider swap without caller changes → swap config row (or is_default flip); callers untouched ✓
  - No repeat call on unchanged product content → input_hash from content hash; test pins cache hit path ✓
  - Timeout/rate-limit never blocks pipeline → AiService returns fallback result; test pins non-raising behavior on exhausted retries and open circuit ✓

## Security notes

- api_key redacted in API responses and logs (export-token redaction pattern in `main.py` applied to `ai_provider_configs.api_key`)
- Prompt injection is out of scope here (no product content reaches prompts until Features 4/5); Feature 2's template design owns placeholder isolation
- Admin RBAC already guards `/admin/*` — new routes inherit it

## Out of scope (deferred to Features 2–5)

- PromptTemplate CRUD/versioning (Feature 2) — the `template_version` cache-key column is the only forward hook
- Prompt library admin UI (Feature 3)
- QC rules consuming AI (Feature 4), enrichment pipeline (Feature 5)
- Anthropic/Gemini protocols; usage dashboards with charts; per-client budget alerts
