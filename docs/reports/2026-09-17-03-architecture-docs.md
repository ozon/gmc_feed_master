# Architecture & Documentation Review — 2026-09-17

Scope: `gmc-feed-engine-spec.md` (authoritative), `backend/docs/`, `frontend/docs/`, `docs/decisions/` (ADRs), `README.md`, AGENTS.md files — reconciled against implementation in `backend/app/`, `plugins/`, `frontend/src/`. Read-only; no code modified.

Rule applied: the spec is always right; where docs contradict it, the doc is the bug. Where the **implementation** has outgrown the spec, that is an operator flag, not a doc fix.

## Status update — 2026-09-19

| # | Status | Note |
|---|--------|------|
| A2 | Fixed | `cccb501` — plugin-contributed routers mount behind `enforce_scope_access`; startup test added. |
| A3 | Fixed | `cccb501` — category taxonomy fetch gated to admin; frontend hides the control for non-admins. |
| A1, A8, A15 | Open — operator-owned | Spec amendments still pending (see Operator flags). |
| A4–A7 | Open | Not addressed. |
| A9–A10 | Open | Single-worker invariants still implicit. |
| A11 | Open | ADR coverage incomplete; `docs/decisions/0013` exists but the AGENTS ADR map is not refreshed. |
| A12–A14, A16 | Open | Not addressed. |

No other architecture/doc findings were changed by the remediation cycles (`O*` over-engineering, `B3/B4/B5/B9` event-loop, `T*` quality-contract).

## Overall assessment

The core engine (pipeline order, delta hashing, three-tier scope merge, plugin contract/reserved routes, atomic publish, migrations) is implemented faithfully to the spec, and the backend docs largely match the code. The main problem is governance: the implementation has grown well past `gmc-feed-engine-spec.md` (RBAC, AI/LiteLLM+Redis, enrichment as a seventh stage) without the spec being updated, so several spec sections are now false while AGENTS.md still declares the spec authoritative. Doc drift is concentrated in Category and RBAC/plugin-scope details. Two boundary-quality issues stand out: plugin-contributed routers bypass central tenant-scope enforcement, and a client-scoped user can mutate a global taxonomy file.

## Findings

### High

**[A1] The authoritative spec is factually wrong (RBAC, Redis, enrichment, new entities)** — `gmc-feed-engine-spec.md` §2:34,37 vs. implementation.
Spec §2:37 says "Single user … no role model" and §2:34 "no Celery/Redis", but RBAC shipped (ADR-0009, `app/access.py`) and LiteLLM's Redis cache is configured (ADR-0010, `docker-compose.yml` redis profile, `main.py:270-290`). Spec §4/§9 also omit `UserClient`, `GlobalSetting`, `Session`, `ImageDimension`, `AiProviderConfig`, `AiUsageLog`, `PromptTemplate`, and the Admin/AI/Chat areas. ADRs do not amend the spec.
*Recommendation:* version/update the spec to absorb ADRs 0009/0010 (or declare supersession explicitly). Operator action.

**[A2] Plugin routers bypass central tenant-scope enforcement** — `app/plugins/discovery.py:141`.
`app.include_router(candidate.router, prefix=f"/plugins/{candidate.manifest.id}")` mounts plugin routers with no `Depends(enforce_scope_access)`, unlike core routers (`main.py:209-220`). Tenant isolation is therefore opt-in per plugin body (`plugins/core/category/plugin.py:488,531`), and nothing requires an auth dependency at the router level. A future plugin route carrying `feed_source_id`/`client_id` silently bypasses isolation.
*Recommendation:* mount plugin routers behind `enforce_scope_access` and assert an auth dependency in the plugin contract test.

**[A3] Global taxonomy file is writable by any authenticated user** — `plugins/core/category/plugin.py:426-475`.
`POST /plugins/category/taxonomy/fetch` writes/replaces the shared taxonomy CSV (`os.replace` at `:456`) for every tenant, guarded only by `get_current_user`; by contrast, global plugin config/data require admin (`routes/plugins.py:86-87`). A client-scoped user can poison a global file used by all clients' categorization.
*Recommendation:* require admin for taxonomy fetch and treat plugin filesystem writes as privileged.

### Medium

**[A4] `architecture.md` says Category is "not yet implemented"** — `backend/docs/architecture.md:99`. False: `plugins/core/category/` exists, `api.md:167-175` documents its routes, and the same doc's mermaid diagram (`:143`) lists it as core. Update the row.

**[A5] `plugins.md` self-contradicts on Category data scope** — `backend/docs/plugins.md:101` (`["global","client"]`) vs. `:186` (`data: [client]`); the actual `plugins/core/category/plugin.json` declares `["global","client"]`. Fix `:186`.

**[A6] `api.md` RBAC matrix omits the admin-only global tier** — `backend/docs/api.md:13-19` grants client-scoped users full plugin config/data access, omitting that the global tier returns 403 for non-admins (code `routes/plugins.py:86-87`; documented in `docs/decisions.md:1081`). Add the global-tier rule.

**[A7] `GET /plugins` leaks cross-tenant state and contradicts spec §5.10** — `backend/docs/api.md:141`, `routes/plugins.py:113-140`. Returns all plugins (enabled + disabled) plus `used_by_feed_sources`, a global cross-tenant count, to any authenticated user (`require_user`); spec §5.10 says enabled manifests only.
*Recommendation:* restrict to admin, or scope usage counts to the caller's clients; reconcile with spec.

**[A8] Drop "reason" is never captured** — spec §5.4 and `architecture.md:23,88` say drops are "logged with plugin_id and reason"; `PluginStep` records only `{product_id, plugin_id}` (`steps.py:280-283`), and the `return None` contract carries no reason. Plugin error text lives only in server logs (`steps.py:263-267`), not `IngestionRun`.
*Recommendation:* add an optional reason channel, or correct the docs/spec (operator flag).

**[A9] In-process-only concurrency guarantees; single-worker constraint unenforced** — `app/pipeline/locks.py:6-19`, `main.py:286`.
`LockRegistry` is an `asyncio.Lock` and APScheduler runs in-process, so `--workers > 1` silently breaks the per-feed-source skip rule and can double-schedule. Nothing enforces `--workers 1`.
*Recommendation:* Postgres advisory lock / unique job guard, or a hard single-worker startup assertion.

**[A10] `resolve_config_bundle` loads every config row per run** — `app/staging/config_resolver.py:102-106`.
Reads all `PluginConfig` and `PluginData` rows then filters in Python — O(all tenant config rows) per pipeline run.
*Recommendation:* filter by `plugin_id IN (...)` and scope owner in SQL.

**[A11] ADR coverage gaps** — ADR-0010 and the AI/enrichment surfaces are missing from the AGENTS.md ADR map (lists 0001-0009); `EnrichmentStep` (seventh stage, `steps.py:312-366,558`) and AI QC/prompt-template/chat have no ADR (only `docs/decisions.md`). Add ADR(s) and refresh the map.

### Low

- **[A12] `plugins.md:31` marks `entry_point` required** but `manifest.py:14` omits it from `_REQUIRED_KEYS` and `loader.py:18-21` defaults to `plugin:Plugin`. Reconcile.
- **[A13] `backend/AGENTS.md` doc map points to a non-existent `docs/decisions.md`** inside backend; the file is at repo-root `docs/decisions.md`.
- **[A14] `data-model.md:230` cites "spec §4.7"** for `ExportVersion.source`; the spec has no §4.7. Cite §4/§10.
- **[A15] Category manifest scope vs. spec §5.9** — manifest declares `data_scope: ["global","client"]` while spec §5.9 says Category is "client-scope only for MVP". Align manifest or spec (operator flag).
- **[A16] `strip_derived` drops any `_`-prefixed dict key at any depth** — `app/staging/hashing.py:8-17`. A future `_`-prefixed content attribute becomes invisible to delta detection. Strip only known sidecar keys.

## Clean areas

- **API surface:** every route found in `app/routes/` matches `backend/docs/api.md` (export-history, quality-history, products/lookup, admin/ai/*, scheduler, chat all present) — accurate and complete.
- **Atomic publish + export token security** — temp → `os.replace`, log-token redaction (`main.py:68-86`).
- **Migration hygiene:** single linear chain, head `b1a2c3d4e5f6`, no forks.
- **Three-tier merge** incl. `union_by_key`, config-hash contents, reserved-route contract enforcement.

## Operator flags (spec action required)

`A1` (RBAC/Redis/enrichment/entities), `A15` (Category scope), `A8` (drop reason). Per the binding rule, forward these to the operator for spec amendment rather than editing the spec.

## Top 5 priority actions

1. Reconcile the spec with reality (RBAC, AI/Redis, enrichment, new entities/areas) or explicitly supersede §2/§4/§9.
2. Mount plugin routers behind `enforce_scope_access` and assert auth in the contract test.
3. Gate `taxonomy/fetch` (and plugin file writes) to admin.
4. Fix the Category/plugin-scope doc contradictions (`A4`–`A7`).
5. Replace the in-process lock/scheduler guarantee with a DB advisory lock or a hard single-worker startup assertion.
