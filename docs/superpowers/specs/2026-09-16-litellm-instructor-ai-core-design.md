# LiteLLM + Instructor AI Core Replacement (AI Reintegration) — Design

Date: 2026-09-16
Status: Approved in brainstorming (operator); phase A implemented 2026-09-16 on branch `litellm-instructor-core` (ADR-0010); phase B (enrichment step) implemented 2026-09-16 on branch `ai-enrichment-step`; phase C (admin settings + telemetry, incl. a validated-only caching fix) implemented 2026-09-16 on branch `ai-settings-phase-c`; phase D (cleanup) implemented 2026-09-16 on branch `ai-cleanup-phase-d` — all four phases complete
Baseline: `main` at `0272bb0`

## Purpose and premise correction

The incoming task specification ("AI Enrichment Pipeline Step") describes a greenfield LLM integration: it asserts there is *no* AI/LLM code anywhere, mandates LiteLLM as transport with a two-tier Router, Instructor for structured output, LiteLLM-native caching, and enrichment as a new pipeline step that is explicitly not a plugin.

That premise is false for this repository. A complete AI subsystem already exists and is already integrated into the pipeline:

- `backend/app/ai/` — `AiService` facade, `AIProvider` Protocol, `OpenAICompatibleProvider` (httpx, no vendor SDK), DB-backed result cache (`ai_result_cache`), usage logs (`ai_usage_logs`), versioned prompt templates, retry policy, in-process circuit breaker, retention purge.
- `backend/app/chat/` — server-side read-only tool loop over `AiService.complete_chat`.
- `backend/app/qc/ai_rules.py` — `AiPolicyCheck` runs inside `QualityCheckStep` (Z3), budgeted per feed source.
- `plugins/core/enrichment/` + `frontend/src/features/enrichment/` — Z4 enrichment: AI scan writes pending suggestions, a human accepts fields into `pinned`, the plugin applies pins (review gates output).
- `backend/app/routes/ai_admin.py` + `frontend/src/features/admin/ai/` — provider CRUD, prompt-template library, usage overview.
- Migrations `m13`/`m14`; ~13 backend AI test files.

The operator has chosen to **replace the AI core** (transport + structured output + cache) with LiteLLM + Instructor, while preserving **full feature parity**: every existing AI feature above must keep working.

This document records the decisions, the deviations from the incoming spec that parity forces, and the implementation shape. It supersedes the incoming spec where they conflict.

## Operator decisions

| Question | Decision |
|---|---|
| What does "reintegrate AI features" mean? | Full spec as written: replace the AI core |
| What must survive the rewrite? | Full feature parity — QC policy check, chat, prompt-template library, provider/usage admin UI, usage logs, enrichment review flow |
| Where does provider/model config live? | `ai_provider_configs` DB rows are the Router deployments, edited in the Admin AI area |
| Where do AI runtime settings live? | DB `GlobalSetting` row, admin-editable via `/admin/ai/settings`, hot-applied on save; `.env` holds only `redis_url` and `ai_cache_dir` |
| How does a request pick a provider? | `is_default` is dropped; enabled providers are grouped by `tier` (`bulk` / `precision`); failover is fixed `bulk → precision` |
| Enrichment step vs review flow | The pipeline step generates suggestions; the existing human review still gates what reaches product output |
| Execution strategy | Strangler behind `AiService`, phased, each phase merges green on ruff/mypy/pytest |

## Non-goals

- Do not modify the plugin framework (`backend/app/plugins/contract.py`, `manifest.py`, `discovery.py`, `loader.py`, `runtime.py`) or add a new plugin.
- Do not remove `plugins/core/enrichment/` or `frontend/src/features/enrichment/` — the review surface is retained.
- Do not build a custom cache storage engine — use LiteLLM's native cache backends.
- Do not introduce a second concurrency mechanism at the step level beyond `AiService`'s existing per-config semaphore and `locks.py`.
- Chat does not gain structured outputs, streaming, or persisted history in this work.

## Architecture

### The seam

`AiService` remains the only surface callers know. Its public API is unchanged:

```python
async def run_task(task_type, variables, *, client_id, feed_source_id) -> AiResult
async def complete_chat(messages, tools, *, client_id, feed_source_id) -> AiResponse
async def test_provider(config_id) -> dict
def invalidate(provider_config_id) -> None
```

`AiResult.status` semantics (`"ok"` | `"cache_hit"` | `"fallback"`) and `error_code` values are preserved, so `qc/ai_rules.py` budget logic and the enrichment scan logic keep working unchanged. Callers that must not change: `qc/ai_rules.py`, `plugins/core/enrichment/plugin.py`, `routes/chat.py`, `routes/ai_admin.py`.

### Target module layout (`backend/app/ai/`)

| Module | Action | Responsibility |
|---|---|---|
| `schemas.py` | new | Pydantic response model per task type (the Instructor `response_model`) |
| `taxonomy.py` | new | cached taxonomy-ID set loaded from the category plugin CSV |
| `tasks.py` | rewrite | `TaskSpec` gains `response_model`; builtin prompts and `CANONICAL_VARIABLES` updated per the schemas section |
| `router.py` | new | build `litellm.Router` from `ai_provider_configs`; wire Instructor `from_litellm(router.acompletion)`; own failover/retry/cooldown/timeout |
| `cache_config.py` | new | build `litellm.Cache` from the effective config (env `redis_url` or the `global_settings` row); namespace + TTL policy; `status()` / `stats()` / `clear()`; rebuild on `PUT /admin/ai/settings` |
| `service.py` | rewrite internals | resolve template → Instructor call → validate → cache → usage log; public API unchanged |
| `usage.py` | extend | persisted telemetry backbone + cache-stat aggregation; provider/tier/fallback fields |
| `templates.py` | unchanged | prompt-template library (parity) |
| `purge.py` | adjust | stop purging `ai_result_cache` (dropped); keep usage retention |
| `provider.py` | trim | keep `AiRequest`/`AiResponse` DTOs for chat; retire `AIProvider` Protocol + `default_provider_factory` |
| `openai_compat.py` | delete | replaced by LiteLLM Router |
| `cache.py` (DB store) | delete | replaced by LiteLLM native cache |
| `resilience.py` | delete | Router owns retry/cooldown; Instructor owns reask |

### Phasing (strangler order, each phase green on `ruff` / `mypy` / `pytest`)

- **A — AI core replacement (transport, structured output, native cache, provider tiers).** Add `litellm` + `instructor` via `uv add`; build `router.py`, `schemas.py`, `taxonomy.py`, `cache_config.py`; `AiService` calls Router + Instructor with validated-only native caching; implement cache-hit detection and usage logging. Provider model change rides along (Router needs it): **add `tier`** (additive), widen `provider_type` to `litellm` with backward-compatible mapping for existing `openai_compatible` rows, group deployments by tier, and rebuild the Router on provider/settings changes. **Add the `global_settings` AI columns** (additive). Phase A stops *using* `is_default`, `ai_result_cache`, and `ai_cache_retention_days` but does **not** drop them — the physical drops move to phase D so every phase-A commit stays green while `service.py`/`cache.py`/`ai_admin.py` still reference them. Validate the mypy override here, before anything depends on it. *(Native cache is merged into A rather than a separate phase: the existing DB cache key embeds `provider_config_id`/`model`, which tier routing invalidates, so a transport-only phase would rework a table the very next phase drops.)*
- **B — Enrichment step.** `EnrichmentStep` + dry-run path + per-feed opt-in config; generates suggestions into the existing review store.
- **C — Admin settings & telemetry surface.** `GET/PUT /admin/ai/settings` (hot-apply), usage summary/timeseries, cache status/stats/clear; build `AiSettingsPage`, update `AiAdminPage` sections, update `ProvidersPage` (tier, no default), and the UsagePage KPI row.
- **D — Cleanup.** Delete `openai_compat.py`, `cache.py`, `resilience.py`, retire the `AIProvider` Protocol and `default_provider_factory` from `provider.py` (keeping `AiRequest`/`AiResponse` as chat DTOs); **drop the now-unused `ai_result_cache` table, `ai_provider_configs.is_default` column, and `global_settings.ai_cache_retention_days`**; docs + ADR; final gates.

**Implementation plan shape:** the work is decomposed per phase — each phase A–E is one implementation plan / PR that leaves `ruff`, `mypy`, and `pytest` green on its own. Phase A is planned and executed first; phases B–E are planned when their predecessor merges, so later plans build on verified behavior rather than assumptions.

## Structured output (`app/ai/schemas.py`)

One Pydantic model per task type; it is the Instructor `response_model`. Field constraints are **sourced from `registry/attributes.json`** — the same registry the existing `LengthLimits` and `EnumValues` QC rules use — so no rule is duplicated.

| task_type | model | fields / constraints |
|---|---|---|
| `title_optimization` | `OptimizedTitle` | `title: str`, length 1..150 (`registry.attributes["title"].constraints.max_length`); promotional/all-caps validator |
| `description_optimization` | `OptimizedDescription` | `description: str`, length 1..5000 (`registry.attributes["description"]`) |
| `category_classification` | `CategoryAssignment` | `google_product_category: int`, validated against the taxonomy ID set |
| `policy_check` | `PolicyCheckResult` | `violations: list[Violation{rule, reason}]`, `confidence: float` 0..1 |
| `attribute_enrichment` | `EnrichedAttributes` | `color/size/material/gtin: str\|None`; `gender: Literal["male","female","unisex"]\|None`; `age_group: Literal["newborn","infant","toddler","kids","adult"]\|None`; `custom_label_0..4: str\|None` (max 100) |
| `image_quality` | `ImageQualityResult` | `watermark: bool`, `text_overlay: bool`, `background: str`, `confidence: float` |

- `gender`/`age_group` literals come from `registry` enum values; `custom_label_*` max length from registry.
- `chat` is deliberately **not** typed — free-form content plus `tool_calls`, preserving Z5/Z6 behavior. Instructor is not used on the chat path.
- **Promotional/all-caps**: `qc/rules.py` has no equivalent, so this is added **once** as a field validator on `OptimizedTitle` (a rejection triggers an Instructor reask). It is not also added as a QC rule. Deterministic QC rules remain the authoritative feed-quality gate.
- **Taxonomy membership**: `taxonomy.py` loads the existing `plugins/core/category/taxonomy-with-ids.en-US.csv` (`id → path`) into a cached ID set; the `CategoryAssignment` validator rejects unknown IDs so Instructor reasks. Single source of truth; the category plugin is not modified. This is a documented app→plugin data-file coupling (a shared registry file can replace it later).
- `TaskSpec` becomes `{response_model, system, user}`; `validate_task()` is removed — validation is the Pydantic model.
- Builtin prompts for `category_classification` and `attribute_enrichment` **are updated** to match the new schemas: `category_classification` must ask for a numeric taxonomy ID (not a category path), and `attribute_enrichment` must ask for the added `gender`, `age_group`, and `custom_label_*` fields. The content-hashed builtin template version (Z1) auto-invalidates stale cache rows.
- `description_optimization` is a new task type, so it is added to `CANONICAL_VARIABLES` in `app/ai/tasks.py` **and** to its client-side mirror `CANONICAL_VARIABLES` in `frontend/src/features/admin/promptLibrary/TemplateEditor.tsx` (the two must stay in sync). The prompt-template library mechanism itself is unchanged (parity).

## Configuration and admin AI settings

AI runtime settings are configured in the Admin AI area and applied at runtime; `.env` carries only deployment-level values that are not meaningful to edit per instance.

### Environment only (`config.py`)

```python
redis_url: str | None = None                 # presence selects the redis cache backend
ai_cache_dir: str = str(Path(__file__).resolve().parents[2] / ".cache" / "ai")  # disk backend path
```

- `.env.example` gains `REDIS_URL` (commented) and `AI_CACHE_DIR`.
- `docker-compose.yml` gains an opt-in `redis` service under `profiles: ["ai-cache"]`; it is never a default/required dependency.
- No `ai_max_concurrency`: spec §9's concurrency limit is already met by the existing per-provider `asyncio.Semaphore(config.max_concurrency)` in `AiService._semaphore_for`.

### Admin-editable, DB-backed (`GlobalSetting` row)

The single-row `GlobalSetting` table gains typed columns, exposed via `GET/PUT /admin/ai/settings` and edited in the AI tab's new **Settings** section:

`ai_cache_type` (`local` | `disk`, default `local`), `ai_cache_namespace` (default `gmc-ai`), `ai_cache_ttl_taxonomy_s` (default 2592000), `ai_cache_ttl_content_s` (default 604800), `ai_router_timeout_s` (default 30), `ai_router_num_retries` (default 2), `ai_router_allowed_fails` (default 3), `ai_router_cooldown_s` (default 30), `ai_instructor_max_retries` (default 2), and the existing `ai_usage_retention_days`. `ai_cache_retention_days` is **dropped** (dead once the DB cache is removed).

- **Effective cache backend**: `redis_url` set in env → `redis`; otherwise the row's `ai_cache_type` (`local` or `disk`). When `redis_url` is set, the UI disables the backend selector and labels it "overridden by environment".
- **Hot-apply**: `PUT` validates the payload, persists it, then rebuilds the LiteLLM `Cache` and `Router` and swaps them onto `app.state.ai_service` before returning 200. A rebuild failure (e.g. disk path unusable) returns 422 and the previously active config stays in effect. In-flight calls keep their own references, so the swap is safe.
- Retention is folded in: the AI section edits `ai_usage_retention_days`; the other retention fields stay in the Settings tab.

### Provider selection

`ai_provider_configs` rows are the Router deployments. `tier` (`bulk` | `precision`) groups them; enabled rows in a tier form that model group; `fallbacks=[{"bulk": ["precision"]}]`; Router's default strategy load-balances within a tier. `is_default` is **dropped** from the model, API schema, and UI. Every task (including chat and the provider test probe) resolves through the `bulk` group with `precision` as fallback.

## Data model and migration (`m15`)

- `ai_provider_configs`: add `tier: str = "bulk"`, **drop `is_default`**. `provider_type` accepts `"litellm"` alongside `"openai_compatible"`; router build maps legacy rows (`openai_compatible` + bare `model` + `base_url`) to `openai/<model>` with `api_base`. Admin `Literal` widens; `_clear_other_defaults` and the default badge/switch are removed; admin tests updated.
- `global_settings`: add the AI settings columns listed under "Admin-editable, DB-backed" above; **drop `ai_cache_retention_days`**. Existing `ai_usage_retention_days` is retained and surfaced in the AI section.
- `ai_usage_logs`: add `provider: str | None`, `tier: str | None`, `fallback_used: bool = False` for spec §7 failover telemetry. Cache-hit rows record the served response's token usage and `cost_usd` with `cache_hit=True`, so the existing `aggregate_usage` yields tokens/cost saved with no new columns.
- **Drop `ai_result_cache`** (phase B). `purge.py` stops purging it; usage retention is unchanged.
- `prompt_templates`: unchanged.
- Data migration: existing `is_default=true` provider rows become `tier="bulk"` before the column is dropped.
- Migration discipline: `uv run alembic revision --autogenerate -m "m15 ai litellm core"`; `alembic check` must be clean before merge.

## Enrichment pipeline step (`app/pipeline/steps.py`)

- `EnrichmentStep` is an opt-in pipeline step, configured per feed source: `configuration["ai_enrichment"] = {enabled, tasks: [...], limit, budget}` (default `enabled=false`, mirroring `ai_qc`). It receives `ai_service` in its constructor and is registered in `default_steps`.
- Runs after `PluginStep`, before `QualityCheckStep`. It does not alter product output; it produces suggestions for review.
- For each candidate product (bounded by `limit`, counted against `budget` exactly like `qc/ai_rules.py` — `ok` spends one unit, `cache_hit` is free, `fallback` is a failure): call `run_task` for each configured task among `title_optimization`, `description_optimization`, `category_classification`, `attribute_enrichment`, with `client_id`/`feed_source_id` from the feed source.
- **Per-item isolation** mirrors `PluginStep`'s per-product `try/except` (`steps.py:245-268`), not `reconcile.py` — `reconcile.py` only marks interrupted `IngestionRun`s as error on restart. Each failure is logged with a reason and counted; the batch never aborts.
- Results are written to the **existing** enrichment `PluginData.suggestions` store (feed-source scope), preserving `pinned`. `EnrichmentUI` therefore needs no change — it reads step-generated suggestions.
- **Dry-run**: add `dry_run: bool = False` to `StepContext` (default preserves all existing behavior; runner untouched). `run_dry_run` sets it, passes `ai_service`, and `EnrichmentStep` skips the `PluginData` write when `dry_run` is true. Generated values surface through a new `DryRunResult.ai_suggestions`. `routes/dry_run.py` and its startup wiring are updated to pass `ai_service`.

## Cache policy (`app/ai/cache_config.py`)

- Backend built from the effective config (env `redis_url` if set, otherwise the admin-editable `ai_cache_type` in `global_settings`): `local` (in-memory; valid under the established single-worker assumption), `disk` (env `ai_cache_dir`), `redis` (from `redis_url`, plus namespace). The cache object is rebuilt and swapped on `PUT /admin/ai/settings`.
- **Namespace per task type**: `cache={"namespace": f"{ai_cache_namespace}:{task_type}"}` → scopes can be invalidated independently (spec §6).
- **Differentiated TTL**: `category_classification` → `ai_cache_ttl_taxonomy_s`; title/description/attribute tasks → `ai_cache_ttl_content_s`.
- **Validated-only caching**: Instructor runs with response caching off. On success, the *validated* payload is written to LiteLLM's native cache via `litellm.cache.async_add_cache(...)` keyed on the same request kwargs; reads use `litellm.cache.async_get_cache(...)` and are re-validated through the Pydantic model before being returned. A hit that fails re-validation is treated as a miss. This uses LiteLLM's native store (no custom engine) and guarantees spec §6's "never cache an invalid response". **Risk:** the manual get/set API and its key derivation are verified in phase B; if it proves impractical, the ADR records the actual behavior rather than inventing a workaround.
- **Fail-open**: any cache setup/lookup/store/status/clear error is logged as a warning and the call proceeds directly; a cache outage never fails a batch (spec §6).
- **Schema sensitivity**: cache keys include messages, model, and Instructor's encoding of the response schema; a test asserts that changing the response schema changes behavior (spec §6 requires verification, not assumption).

## Admin API (`routes/ai_admin.py`, extended)

Registered as today (route module included in `main.py`), all `require_admin`-guarded, response conventions matching `dashboard.py`/`quality.py`:

- `GET /admin/ai/settings` — AI settings row; seeds defaults on first read (existing `/admin/settings` pattern).
- `PUT /admin/ai/settings` — validate → persist → hot-apply (rebuild Cache + Router); 422 with the previous config retained on rebuild failure.
- `GET /admin/ai/usage/summary` — total requests, cache hit ratio, total tokens, total cost, cost avoided.
- `GET /admin/ai/usage/timeseries` — reuses `aggregate_usage(group_by="day")`.
- `GET /admin/ai/cache` — `{effective_backend, redis_from_env, healthy, namespaces, entries|null}`; `entries` is `null` where a backend cannot report it. Health is probed fail-open (a backend error reports `healthy=false`, never a 5xx).
- `GET /admin/ai/cache/stats?from&to` — hit ratio, tokens saved, cost saved from `ai_usage_logs`.
- `POST /admin/ai/cache/clear` — body `{namespace?}` clears one task scope or all.
- Provider endpoints (`/admin/ai/providers*`) gain `tier`, lose `is_default`; create/update/delete rebuild the Router (extending today's `service.invalidate()`).

Telemetry is persisted (existing `ai_usage_logs`), matching the established persistence pattern; no new "decide ephemeral vs persisted" question remains.

## Frontend

- `AiAdminPage.tsx`: sections become `providers | settings | templates | usage` (adds `settings`).
- New `AiSettingsPage.tsx` with two cards:
  - **Cache**: backend selector (`local`/`disk`, disabled with an "overridden by environment" note when `REDIS_URL` is set), namespace, taxonomy TTL, content TTL; a live status block (effective backend, enabled, healthy, namespaces, entry count) and stats (hit ratio, tokens saved, cost saved for a selectable range) with a Clear action.
  - **Router & retries**: timeout, num_retries, allowed_fails, cooldown, instructor max_retries, `ai_usage_retention_days`. One Save button issues the `PUT`.
- `ProvidersPage.tsx`: columns `name | model | tier | enabled`; modal fields name, provider_type (`litellm`/`openai_compatible`), tier (`bulk`/`precision`), model, API base (optional for litellm), api_key (write-only), max_concurrency, timeout_s, input/output price, enabled. Default badge and switch removed.
- New hooks `useAiSettings`, `useUpdateAiSettings`, `useAiCacheStatus`, `useAiCacheStats`, `useClearAiCache`; updated `AiProvider` type (`tier` in, `is_default` out) and a new `AiSettings` type; i18n en + de.
- No changes to `ChatWidget` or `EnrichmentUI` (step feeds the existing suggestions store).

## Testing

- `test_ai_schemas.py` — per-model constraints; unknown taxonomy ID rejected; promotional/all-caps rejected; lengths sourced from the registry.
- `test_ai_router.py` — Router built from config rows; legacy `openai_compatible` mapping; failover bulk→precision on 429/5xx; timeout/cooldown settings.
- `test_ai_cache.py` — per-task namespace; TTL selection; cache-hit detection and usage row; schema-change invalidation; fail-open; validated-only caching.
- `test_ai_service.py` — rewritten against the new internals, asserting preserved public behavior (parity regression).
- `test_enrichment_step.py` — opt-in gating; per-item isolation; limit/budget; suggestions written with `pinned` preserved; dry-run does not persist; no-provider/failure counts.
- `test_ai_settings_api.py` — GET seeds defaults; PUT persists and hot-applies; invalid payload / failed rebuild returns 422 and leaves the old config active; retention folded in; `ai_cache_retention_days` gone.
- `test_ai_admin_api.py` — summary/timeseries/cache-status/cache-stats/cache-clear endpoints and RBAC; provider `tier` present and `is_default` absent.
- Migration test — `alembic check`, `ai_result_cache` dropped, `is_default` dropped, `ai_cache_retention_days` dropped, legacy provider rows still resolve.
- Frontend — `AiSettingsPage` (save, hot-apply feedback, redis-override note, clear flow), `ProvidersPage` tier selector and absence of default toggle, provider timeout/concurrency editing, i18n parity.
- All pre-existing AI tests pass except where the provider model/literal widened (`test_ai_admin_api.py`, `test_ai_models.py`, `test_admin_settings_api.py`, `test_ai_purge.py`).

## Documentation (same commits)

- New `docs/decisions/0010-litellm-instructor-ai-transport.md` recording the spec deviations: DB deployments instead of spec §4 env-only config; AI runtime settings stored in `global_settings` and hot-applied via the Admin AI area with `.env` limited to `redis_url`/`ai_cache_dir`; human-gated enrichment instead of spec §3 auto-apply; and the validated-only caching approach.
- Update `backend/docs/architecture.md`, `backend/docs/data-model.md`, `backend/docs/api.md` (new settings/cache endpoints, provider `tier`), `docs/decisions.md`, and `frontend/docs/architecture.md` / `plugin-uis.md` where the provider/settings UI changes.

## Risks and open items

1. **mypy hard gate.** `litellm`/`instructor` typing depth is unverified. Mitigation: pin versions, add `[[tool.mypy.overrides]]` for `litellm.*`/`instructor.*`; validate in phase A before anything depends on it. No new `ruff-baseline.txt` exceptions.
2. **Instructor v2 API.** `from_litellm` lives in `instructor/v2/providers/litellm/client.py`; pin the version and confirm the async client shape in phase A.
3. **Manual native-cache get/set.** Key derivation for `async_get_cache`/`async_add_cache` must match what a standard completion would produce; verified in phase B, with the fallback documented in the ADR.
4. **`fallback_used` / served provider.** LiteLLM's response `_hidden_params` may not expose which deployment served a request; if not, derive it by comparing the served `model` against the primary-tier deployment list.
5. **Dependency weight.** `litellm` pulls a large transitive tree and regenerates `uv.lock`. Operator has opted in.
