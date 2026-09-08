# Backend Logic Review — 2026-09-08

Scope: `backend/app/**` (routes, pipeline, export, ingest, staging, mapping, qc, plugins, security/access, models, persistence), `plugins/core/**`, cross-checked against `gmc-feed-engine-spec.md`.
Method: semantic exploration via CodeGraph + targeted source reads; controller re-verified every Medium-or-higher finding against the actual code. Read-only review.

Severity legend: Critical · Important · Medium · Minor. Status: NEW · CONFIRMED-known · REFUTED (verification-negative).

## Findings

### [B1] Scoped (non-admin) users can read and write global-tier plugin config/data
- Severity: **Important** (security / tenancy isolation; would be Critical-severity in a public multi-tenant product)
- Location: `backend/app/access.py:87-97` (guard), `backend/app/routes/plugins.py:82` (scope resolution), `plugins.py:105,286-295` (global-tier row write), `backend/app/main.py:199` (router wiring)
- Evidence: the plugins router is mounted with `dependencies=[Depends(enforce_scope_access)]`, but `enforce_scope_access` only checks `client_id`/`feed_source_id` **path or query params** and returns without raising when neither is present (access.py:87-93). The plugin config/data routes declare both as *optional query params*; when a scoped user calls `GET/PUT /plugins/{id}/config` (or `/data`) with no query params, `_resolve_target` resolves `scope = "global"` (plugins.py:79-82) and `_put_payload` writes the global-tier row (`client_id=None, feed_source_id=None`). The routes require only `require_user` — no `require_admin`.
- Impact: the three-tier merge (`backend/app/staging/config_resolver.py:64-68`) merges the global tier into **every client's** resolved config — including clients the user is not assigned to. A scoped user can therefore alter other clients' feed processing and read agency-global config. This violates the spec invariant that a client-scoped user "must never read/write client Y's … plugin configs/data" — the global tier affects Y.
- Suggestion: require admin for global-tier reads/writes in `_resolve_target`/`_get_payload`/`_put_payload` (reject `scope == "global"` when `user.client_ids is not None`), or extend `enforce_scope_access` to default-deny requests with no client/feed-source context for scoped users.
- Status: NEW (controller-verified end to end)

### [B2] FilterPlugin.process would crash on `None` config — latent, unreachable via the current pipeline
- Severity: **Medium** (latent; see reachability note)
- Location: `plugins/core/filter/plugin.py:120-121`
- Evidence: line 120 guards `config.get("conditions", []) if isinstance(config, dict) else []` — explicitly anticipating a non-dict config — but line 121 immediately calls `config.get("isActive", True)` unconditionally. `validate_config` accepts `None` (lines 92-93), so the plugin's own contract admits `None` configs that `process()` cannot handle.
- Reachability (controller-verified): the pipeline always passes `instance["resolved_config"]`, and `_resolve_declared` (`backend/app/staging/config_resolver.py:63-68`) always returns a dict (starts from `{}`), so `process()` cannot receive `None` through the pipeline today. The filter preview route calls `passes_all` directly. The crash is therefore latent — one new call path (or a test) away.
- Impact: `AttributeError` if any future path passes `None`; until then the two lines are mutually contradictory dead logic that misleads maintainers.
- Suggestion: `if not (isinstance(config, dict) and config.get("isActive", True)): return product` — one line, restores internal consistency.
- Status: NEW (severity adjusted from Important to Medium by reachability analysis)

### [B3] "Runner lock race" — REFUTED on verification
- Severity: — (refuted)
- Location: `backend/app/pipeline/runner.py:32-50`
- Original claim: check-then-acquire (`is_locked()` then `await lock.acquire()`) allows two concurrent runs to both pass the check.
- Verification: in the unlocked branch there is **no `await` between the check and the acquire**, and all invocations run on the same event loop — the scheduler is `AsyncIOScheduler` (`scheduler.py:38`) and the manual trigger uses `asyncio.create_task(runner.execute(...))` (`routes/clients.py:324`). Under single-threaded asyncio semantics the check-then-acquire is atomic; the second caller always observes `is_locked() == True` and takes the skip path.
- Residual note (Minor, informational): the pattern is one refactor away from becoming a real race (e.g., if `execute` were ever run from a thread or a second loop, or if an `await` is inserted between the check and the acquire). A non-blocking acquire or a comment would make the invariant load-bearing. Also `max_instances=2` (`scheduler.py:63`) deliberately lets APScheduler start a second fire during an active run — the lock then records a `"skipped"` run row (visible skip evidence, appears intentional).
- Status: REFUTED (kept on record to prevent re-reporting)

### [B4] `apply_plugin_outcomes` outcome ids: `PluginOutcome(pid, ...)` vs `PluginOutcome(str(pid), ...)`
- Severity: Minor
- Location: `backend/app/pipeline/steps.py:292` vs `:297`
- Evidence: dropped outcomes are appended with the raw `pid`, processed outcomes with `str(pid)`. Both call sites sit three lines apart.
- Impact: if a plugin/product id ever arrives as a non-string (e.g., numeric id from a source feed), dropped outcomes carry a different id type than processed ones; downstream persistence or diffing keyed on string ids sees inconsistent keys.
- Suggestion: `str(pid)` on the dropped branch too (and mirror the `pid is not None` guard used at line 288).
- Status: NEW

### [B6] Export version retention: `retention = 0` still keeps one version
- Severity: Minor
- Location: `backend/app/export/service.py:396`
- Evidence: `... .offset(max(retention, 1))` — the clamp maps 0 → 1, so a feed source configured with `history_retention_count = 0` keeps the newest version instead of none.
- Impact: semantic edge case only; unknown whether retention=0 is reachable from the UI validation (see frontend F8 — numeric fields are under-validated, so 0 can plausibly be saved). If "0 = keep nothing" is intended semantics, this is a bug; if "0 = keep minimum one", the clamp deserves a comment/naming.
- Suggestion: decide intended semantics; either `offset(retention)` or validate retention ≥ 1 at the API boundary.
- Status: NEW (controller-verified)

### [B7] `enforce_scope_access` raises 500 on malformed query params
- Severity: Minor
- Location: `backend/app/access.py:95,103`
- Evidence: `int(client_id)` / `int(feed_source_id)` on raw path/query strings. `GET /plugins/x/config?client_id=abc` raises `ValueError` → 500. FastAPI does not validate these because they are read from `request` directly, not declared as typed parameters.
- Impact: malformed input yields a server error instead of 422; noisy logs, wrong signal (500 implies server fault).
- Suggestion: wrap the conversion or validate digits, raising 422 on malformed ids (consistent with the routes' `_validation_error` pattern).
- Status: NEW (controller-observed during B1 verification)

## Confirmed-known (verified, no new action)

| Item | Reference |
|------|-----------|
| mypy 42-error baseline accepted | `backend/docs/mypy-baseline.md`, TODO 10.1 |
| ruff ~506 pre-existing errors, zero-new-in-touched-files convention | TODO working notes; see tooling report T2 for the missing-dependency problem |
| `manifest.py` `config_merge` error-message wording overstates | TODO 9.5 |
| App-side `plugin.py` re-exec in tests with `plugins_dir` | TODO 9.6 |
| TOCTOU accepted on plugin-disable 409 (defense-in-depth behind modal) | TODO 1.2 Done entry |
| `app/routes/quality.py:58-63` variable-reuse mypy artifact (not a runtime bug) | mypy-baseline.md |

## Verified invariants (checked and hold)

- **Run lock**: overlapping runs skipped, never queued — atomic under single-loop semantics (see B3); `finally: lock.release()` present.
- **Atomic publish**: temp file + `os.replace()` in `backend/app/export/service.py`.
- **Plugin contract**: `process()` does not mutate `original_product` — verified in custom_labels, filter, rules; `PluginStep` deep-copies the original (`steps.py:241`) and passes it via `RunContext`.
- **Delta mechanics**: per-product content hash; only changed products reprocessed; config-hash change invalidates all.
- **QC findings**: persisted per run; critical findings never block export (spec: non-blocking) — matches spec.
- **Reserved plugin routes**: `/plugins/{id}/config` and `/plugins/{id}/data` protected from plugin-registered subpaths via `_RESERVED_SUBPATHS` (`backend/app/plugins/discovery.py`).
- **Retention purge** (`backend/app/staging/purge.py`): 90-day IngestionRun purge skips runs still referenced by `staging_products`, NULLs `export_runs.ingestion_run_id`, deletes `quality_findings`, then the runs — ordering matches the documented invariant.
- **Scheduler**: single `AsyncIOScheduler` (UTC), `misfire_grace_time=None`, nightly system jobs `system-staging-purge` / `system-ingestion-run-purge` at `0 3 * * *` with `replace_existing=True`.
- **GS1 checksum, currency consistency, ISO-8601 dates, enum validation, cardinality rules**: spot-checked against spec; correct.
- **XML writer**: escaping, encoding, atomicity correct.
- **Admin routes** (`/admin/*`): admin-gated; batch product lookup and plugin preview body routes enforce client scope (`ensure_feed_source_access`).

## Backend health verdict

Core pipeline machinery is in good shape: the load-bearing invariants (lock, atomicity, contract, retention, scoping on recent routes) all verify. The one genuine gap is **B1 — the global plugin tier sits outside the scope guard** (an artifact of the scope guard being param-driven while the global tier needs *no* params). Everything else is hardening: robustness of error paths (B7), latent inconsistency (B2), and type polish (B4).
