### Task 8: M5 acceptance gate

**Files:**
- Create: `backend/tests/test_m5_acceptance.py`

**Interfaces:**
- Consumes: everything above; `create_app(settings=..., db_session_factory=factory)` pattern from `test_m4_acceptance.py`; `HttpFetcher` injection point of `create_app`.

- [ ] **Step 1: Write the acceptance test**

Create `backend/tests/test_m5_acceptance.py`. Structure it exactly like `test_m4_acceptance.py` (read that file first): same fixtures/helpers for engine/factory/login via the API, same stub-fetcher approach serving TSV bytes, but asserting staging behavior. Required scenarios (each is one test):

```python
SCENARIOS = [
    # (name, description of what is asserted)
]
```

1. `test_first_run_stages_everything` — two products ingested through the full runner; `GET /clients/{id}/feed-sources/{fid}/ingestion-runs` statistics contain `"staging": {..., "new": 2}`; both rows exist with `status="active"`.
2. `test_identical_second_run_enqueues_nothing` — rerun via `POST /feed-sources/{id}/run`; latest run statistics show `unchanged: 2, new: 0`; history row count still 2.
3. `test_content_change_reprocesses_with_history` — change one product title in the stubbed source; rerun; statistics show `changed: 1`; history count 3.
4. `test_config_change_reprocesses_without_history` — seed an active pipeline (Plugin row + ModulePipeline + ModuleInstance per Task 3 seeding), run once so hashes incorporate it, then mutate the instance `configuration` JSON directly in the DB; rerun; statistics show `changed: 2` while history count stays at 3.
5. `test_removed_product_flips_status_and_returns` — serve a one-product source; rerun (`removed: 1`, row status `removed`, `removed_at` set); serve the original two-product source again; rerun (`reactivated: 1`, row active again, `removed_at` cleared).
6. `test_purge_clears_expired_rows_end_to_end` — remove a product, backdate its `removed_at` by 91 days via SQL, run `purge_expired(factory, now)` directly, assert product and its history are gone.
7. `test_invalid_ids_do_not_block_run` — include a row without an `id` column value; run completes `success` with `failed_count >= 1` and the invalid row is absent from `staging_products`.
8. `test_migration_head_matches_models` — alembic upgrade head on a fresh database then `inspect()` shows `removed_at` and CASCADE FK (guards CI drift like prior milestones).

Each scenario asserts through public surfaces where possible (API endpoints, DB state via SQL), never through internals of `app.staging.*`.

- [ ] **Step 2: Run the acceptance suite**

Run: `uv run pytest tests/test_m5_acceptance.py -v`
Expected: PASS (all scenarios). Debug failures through the specific unit suites from Tasks 1–7.

- [ ] **Step 3: Full milestone gate**

Run all of:

```bash
uv run compileall app
uv run pytest
uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check
git diff --check
cd ../frontend && npm run test -- --run && npm run typecheck && npm run build && cd ../backend
```

Expected: backend suite green (prior ~155+ tests plus new ones), registry artifact unchanged, frontend untouched-and-green. This is the done criterion: "`content_hash`/`config_hash` behave exactly as specified, incl. reactivation & purge."

- [ ] **Step 4: Record final verification in docs/decisions.md**

Append under `## 2026-08-26` an entry `### M5 final verification` following the M1/M2 template: milestone complete statement, test counts, resolved dependency versions (unchanged pins), any deviations from this plan encountered during execution.

- [ ] **Step 5: Commit**

```bash
git add tests/test_m5_acceptance.py ../docs/decisions.md
git commit -m "feat: M5 acceptance gate — staging delta verified"
```

---

## Self-Review Checklist (completed during planning)

- Spec coverage: §4 delta mechanics (Tasks 4/6), reactivation (Task 4 matrix), purge (Task 7), config_hash over resolved configs incl. three-tier merge §5.3 (Tasks 2/3), content_hash canonical form incl. sidecar stripping (Task 1), history-on-content-change-only (Tasks 4/6), StepContext/run-state reduction (Task 6), system-job namespace decision (Task 7).
- Type consistency: `StoredRow`/`RowUpsert`/`StagingDelta`/`PurgeCounts` field names identical across definition and consumer tasks; `resolve_config_bundle(session, feed_source)` signature matches Task 6 usage.
- No placeholders: every code step contains full code or exact edit instructions.



