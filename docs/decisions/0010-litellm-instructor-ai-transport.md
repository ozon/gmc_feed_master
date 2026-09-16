# ADR-0010: LiteLLM + Instructor as the AI Transport and Structured-Output Layer

## Status
Accepted (phase A of the AI core replacement)

## Context
The first AI integration (ADR cycle Z1–Z6, migrations m13/m14) used a bespoke,
vendored-free stack: `OpenAICompatibleProvider` (raw `httpx` chat completions),
loose JSON validators in `app/ai/tasks.py`, a DB result cache
(`ai_result_cache` keyed on `provider_config_id` + `model` + `template_version`
+ `input_hash`), a hand-written retry policy and in-process circuit breaker
(`app/ai/resilience.py`), and a single `is_default` provider row.

The incoming requirements mandate LiteLLM as the only outbound transport path
(multi-provider routing with automatic failover), Instructor for strictly typed
structured outputs, LiteLLM's native cache, two provider tiers (bulk /
precision), and admin-editable AI settings. The existing stack cannot express
tiered multi-provider failover, and its DB cache key embeds
`provider_config_id`/`model`, which tier routing invalidates.

Feature parity is required: QC policy check (Z3), chat (Z5/Z6), the prompt
template library, the provider/usage admin UI, and the Z4 enrichment review
flow must all keep working.

## Decision
1. **LiteLLM Router is the only transport.** `app/ai/router.py` builds a
   `litellm.Router` from the enabled `ai_provider_configs` rows grouped by
   `tier` (`bulk` / `precision`); `fallbacks=[{"bulk": ["precision"]}]` gives
   automatic failover on 429/5xx. Retry count, allowed failures, cooldown, and
   timeout come from the `global_settings` AI row. Legacy
   `openai_compatible` rows map to `openai/<model>` + `api_base`, so existing
   configurations keep working. No provider SDK may be imported anywhere.
2. **Instructor is the only structured-output path.**
   `instructor.from_litellm(router.acompletion, async_client=True)`; each task
   in `app/ai/tasks.py` declares a Pydantic `response_model`
   (`app/ai/schemas.py`). Schema violations trigger a bounded reask
   (`ai_instructor_max_retries`). Loose `validate_task` JSON parsing is
   removed. Chat is the sole exception (free-form content + `tool_calls`).
3. **LiteLLM's native cache replaces `ai_result_cache`.** Backends `local` /
   `disk` / `redis` (`app/ai/cache_config.py`), namespaced per task type
   (`{namespace}:{task_type}`) with a long TTL for taxonomy tasks and a
   moderate TTL for content tasks. Because Instructor sits above the cache,
   Instructor runs with caching off (`CacheMode.default_off`) and the
   **validated** payload is written explicitly; reads are re-validated before
   use — this satisfies "never cache an invalid response". Cache errors are
   fail-open. Redis is selected purely by `REDIS_URL` (configuration only).
4. **`tier` replaces `is_default`.** Enabled rows join their tier's model
   group; the Router load-balances within a tier. Every task (including chat
   and the provider probe) starts on `bulk` with `precision` as fallback.
5. **Additive migration in phase A, destructive cleanup in phase D.** The m15
   migration added `tier`, the `global_settings` AI columns, and the
   `ai_usage_logs` telemetry columns, so every phase-A commit stayed green while
   the old code was still referenced. Phase D then deleted the bespoke modules
   (`openai_compat.py`, `cache.py`, `resilience.py`, the `AIProvider` Protocol)
   and migration `m16` (`b1a2c3d4e5f6`) dropped `is_default`, `ai_result_cache`,
   and `ai_cache_retention_days` — applied only after Phases A–C removed every
   reference.
6. **Model identifiers and API keys stay in `ai_provider_configs` (DB),
   admin-editable.** They are not environment variables. Only deployment-level
   values that are not meaningful per instance live in `.env`: `REDIS_URL` and
   `AI_CACHE_DIR`. This deliberately deviates from the incoming requirement
   that all model identifiers, keys, timeouts, and retries live on
   `Settings`; full feature parity (admin provider management, per-client
   configuration) requires DB-backed config.

## Deviations from the incoming specification
- **Provider config source (spec §4).** The spec placed all model ids, keys,
  timeouts, and retry counts on `Settings`/env. This ADR keeps them in the DB
  and limits env to `REDIS_URL` + `AI_CACHE_DIR`. AI runtime settings
  (cache namespace/TTLs, router knobs, instructor retries) live in the
  single-row `global_settings` table and are surfaced in the Admin AI area in
  the admin-settings phase.
- **Enrichment (spec §3).** The spec called for a pipeline step that generates
  *and applies* attributes, explicitly not a plugin. The Z4 review flow
  (scan → suggestions → human accept → pin) already exists and is retained;
  the enrichment pipeline step will *generate suggestions* while the human
  review remains the only path that changes product output.
- **Taxonomy reference (spec §5).** Category-id validation reads the existing
  `plugins/core/category/taxonomy-with-ids.en-US.csv` (id → path) rather than a
  new reference list, avoiding duplicate taxonomy sources. This is an
  app→plugin-data-file coupling, documented in the design spec; it can be
  promoted to `backend/registry/` later.

## Consequences
- **Manual cache ops must opt in.** With `CacheMode.default_off`, LiteLLM's `async_get_cache`/`async_add_cache` only act when the request carries `cache={"use-cache": True}`; the initial implementation omitted it, making the cache a silent no-op until phase C fixed it. The completion-level `caching=True`/`Router.cache_responses` path is intentionally not used (it would cache raw, unvalidated completions); the LLM call receives no cache-control.
- `litellm` and `instructor` are pinned exact dependencies (`litellm==1.101.0`,
  `instructor==1.17.0`) and pull a large transitive tree, including `openai`
  (used only transitively by LiteLLM — never imported by application code).
- The mypy hard gate is preserved via a `[[tool.mypy.overrides]]` entry for
  `litellm.*` / `instructor.*`; no new ruff findings (the gate is
  exit-0 since 2026-09-16, with no baseline file).
- Router construction validates deployments and can raise on a misconfigured
  model id. `AiService` catches router-build failures and degrades to
  `status="fallback"` / `AiChatUnavailable`, preserving the "AI never blocks
  the pipeline" contract.
- Free-form `provider_type` is narrowed to `litellm` / `openai_compatible` in
  the API and UI; `is_default` disappears from the API surface while the column
  remains until cleanup.
- `description_optimization` is a new task type and must stay in sync between
  `app/ai/tasks.py` `CANONICAL_VARIABLES` and its frontend mirror in
  `TemplateEditor.tsx`.
- LiteLLM's native-cache manual read/write path is version-sensitive; the
  cache wrapper isolates it so a future LiteLLM upgrade touches one module.
