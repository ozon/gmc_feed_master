### Task 8: M6 acceptance gate

**Files:**
- Create: `backend/tests/test_m6_acceptance.py`
- Modify: `docs/decisions.md` (final verification entry)

**Interfaces:**
- Consumes: everything above; `discover_and_mount`, `contract_violations`, the fixture plugin, `PipelineRunner` with real steps.

Scenarios (each a test, following the M4/M5 acceptance patterns — engine/factory from `isolated_database_url`, manual lifespan-context invocation for discovery):

1. `test_dummy_plugin_passes_contract_without_core_changes` — copy `tests/fixtures/example_plugin` into a tmp plugins dir; `create_app(settings=..., db_session_factory=factory, plugins_dir=tmp)`; run lifespan context; assert one registered row (`enabled=False`, third-party default) and `contract_violations` empty.
2. `test_discovery_is_idempotent_across_restarts` — run discovery twice; single row; version updated when fixture version bumps in a copied manifest; `enabled=True` (manually flipped between runs) preserved.
3. `test_end_to_end_execution_through_runner` — seed client/feed source/run; stage two products via `IngestStep+MappingStep+StagingStep`; register the dummy instance in a registry dict passed through `default_steps(...)`; active pipeline seeded with a `ModuleInstance` pointing at the registered Plugin row; runner executes: product A transformed (staging row `processed_data` written, `excluded=False`, title uppercased + suffix), product B named `"drop-me"` → `processed_data NULL`, `excluded=True`; run statistics contain `plugins.processed == 1, dropped == 1`.
4. `test_error_isolation_preserves_last_known_good` — third product whose plugin raises for it specifically: staging row untouched from its previous state (seed a pre-existing `processed_data` value first), counted in `failed_count`/`errored`, run status still success.
5. `test_toggle_and_config_round_trip_via_api` — login → `GET /plugins` shows the disabled plugin → `PUT enabled` true → `PUT /plugins/example_upper/config?client_id=...` with valid payload → GET returns it; undeclared `feed_source_id` scope → 422.
6. `test_full_suite_serial_and_parallel_green` is the meta-gate: full backend suite under `-n0` and default `-n auto` both green; compileall clean; `git diff --check` clean.

Record an `### M6 final verification` entry in `docs/decisions.md` following the M1/M2 template: milestone complete statement, test counts, resolved dependency versions (jsonschema pin), deviations.

Commit: `feat: M6 acceptance gate — plugin host verified`.

---

## Self-Review Checklist (completed during planning)

- Spec coverage: §5.1 discovery/validation/registration + core-default-enabled (Tasks 4), §5.2 manifest incl. entry-point gap (Task 2), §5.3 wiring via existing scopes + API declaration checks (Task 6), §5.4 runtime contract incl. RunContext/original_product/drop/error semantics (Task 5), §5.10 contract suite + no-core-change proof (Tasks 7–8), §8 endpoints all present (Task 6), owner Option A processed store incl. migration + exception semantics (Task 5), GET /plugins all-plugins correction (Task 6).
- Placeholder scan: none — every task has concrete code, rules, or exact edit instructions; Task 2/3 tests are specified as enumerated case lists with exact inputs where values matter.
- Type consistency: `Candidate`, `RunContext`, `PluginOutcome`, `contract_violations(candidate)`, `PluginStep(registry)` names identical across definition and consumer tasks; `default_steps(fetcher, registry, plugin_registry=None)` matches main.py call-site change in Task 5.
- Ordering: Task 4 defers the `default_steps` call-site change to Task 5 to keep every commit green; Task 6's router import lands with the endpoints themselves.
