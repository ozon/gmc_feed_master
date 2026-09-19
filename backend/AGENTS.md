 Feed Master — Backend Agent Instructions

## WHAT
FastAPI + SQLAlchemy 2.0 async + PostgreSQL. Core modules: `app/` (routes, models, pipeline, staging, QC, plugins, ingest, export, auth, registry).

## HOW
```bash
# From backend/
cp ../.env.example ../.env
docker compose up -d postgres
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed \
  uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
uv run pytest                             # -n auto is the addopts default; needs TEST_DATABASE_URL
uv run ruff check . ../plugins            # gate: exit-0, hard (flipped 2026-09-16, no baseline file)
uv run mypy .                             # gate: exit-0, hard (flipped 2026-09-10, no baseline file anymore)
```

## Key conventions
- **Migrations only via Alembic** — never `create_all`. `uv run alembic revision --autogenerate -m "msg"`
- **Pipeline steps** in `app/pipeline/steps.py` — fixed order: `IngestStep` → `MappingStep` → `StagingStep` → `PluginStep` → `RuleAiStep` (opt-in) → `EnrichmentStep` (opt-in) → `QualityCheckStep` → `ExportStep`
- **Delta mechanics** in `app/staging/delta.py` — `content_hash` (canonical product) + `config_hash` (pipeline + resolved plugin config/data + versions)
- **Three-tier scope merge** in `app/staging/config_resolver.py` — `global` → `client` → `feed_source` (per-key dict merge)
- **Plugin runtime contract** in `app/plugins/runtime.py` — `RunContext` with read-only `original_product`
- **Quality Check** in `app/qc/engine.py` — sequential, non-blocking, per-product + cross-product rules
- **Atomic publish** in `app/export/service.py` — temp file + `os.replace()`
- **Per-feed-source lock** in `app/pipeline/locks.py` — overlapping runs skipped
- **Models** use typed SQLAlchemy 2.0 columns: `Mapped[T]` / `mapped_column(...)`, never legacy `Column(...)`
- **Nested/flexible data** (`field_mapping`, `configuration`, `plugin_configs`) is `JSONB`, not `TEXT`/`ARRAY` — this is a deliberate, already-settled convention, not an open choice

## Async & database conventions
- All I/O-bound code (routes, pipeline steps, plugin hooks) is `async def`. No blocking calls inside the event loop — use `asyncpg`, `httpx.AsyncClient`, or `run_in_executor` for unavoidable sync libs.
- One `AsyncSession` per request/task via the existing DI dependency — never share a session across concurrent `asyncio.gather` branches.
- Multi-step writes (stage → QC → export bookkeeping) run inside a single `async with session.begin():` — no ad-hoc mid-pipeline `commit()` calls.
- Bulk writes (staging deltas, QC results) use `session.execute(insert(...).values([...]))` instead of per-row `add()` in a loop.
- No N+1 queries on any endpoint/step iterating products — use explicit `selectinload`/`joinedload`.
- Fetch-then-persist: don't hold a session open across an `await` on an external HTTP call (ingest/plugin fetch).

## Plugin sandboxing & contracts
- Plugins run only through `RunContext` from `app/plugins/runtime.py` — no direct DB session or filesystem access beyond the manifest's declared permissions.
- Plugins intentionally do not import each other's code (established pattern, e.g. category plugin duplicates Labelizer's `resolve_path` helper locally rather than importing it) — do not "fix" this by introducing cross-plugin imports.
- A new plugin hook updates `docs/plugins.md` (runtime contract, manifest schema) and adds a `tests/fixtures/` case for both success and a contract-violation path (e.g. mutating `original_product`).
- Plugin failures are caught per-plugin, logged with structured context, and never abort `PluginStep` for other plugins or feed sources. Enforce a per-plugin `asyncio.wait_for` timeout so a hanging plugin can't stall the per-feed-source lock.

## Error handling & logging
- Module-level `logger = logging.getLogger(__name__)`; never bare `print`.
- Logger calls use lazy `%s`-style interpolation, not f-strings: `logger.error("background pipeline run failed: %s", exc)`. This is the established pattern (see `app/routes/clients.py`) — it avoids building the string when the log level is disabled and keeps exception objects lazy. F-strings remain the default for all *non-logging* string construction.
- QC violations are the only intended non-blocking failure path in the pipeline. Everything else propagates or is logged and re-raised per the step's contract — no silent swallowing to "keep the run going."
- Every pipeline run carries a `run_id`, propagated through `RunContext`, included in every log line for that run for end-to-end tracing.
- **Logging is configured centrally** in `app/logging_setup.py:configure_logging()` (called first in `create_app()`): structlog bridged through stdlib, JSON to stdout by default (`LOG_FORMAT=console` for dev, `LOG_LEVEL` default `INFO`). Existing `logging.getLogger(__name__)` calls are unchanged. Do not add `logging.basicConfig()` or extra handlers.
- **Correlation contextvars** are bound automatically, not passed by hand: `RequestContextMiddleware` binds `request_id`/`method`/`path` (and echoes `X-Request-ID`); `get_current_user` binds `actor`/`actor_role`; `PipelineRunner.run` binds `run_id`/`feed_source_id`/`client_id`. Any log line during a request or run carries them via `merge_contextvars`.
- **Redaction is automatic but is a backstop.** `app/logging_setup.py` redacts denylisted keys (`password`, `token`, `secret`, `authorization`, `api_key`, …), truncates strings > 2048 chars, and recurses to depth 3. It is not a licence to log secrets — never log request/response bodies for `app/auth/` routes or ingest credentials.
- **Audit mutations via the helper**, not ad-hoc inserts: `from app.event_log import audit` inside a `session.begin()` block, e.g. `await audit(session, "client.create", target_type="client", target_id=client.id)`. It fills actor/role/request/run context from contextvars and writes `category="audit"`. Frontend errors use `record_client_error`; unhandled server errors are persisted as `category="server_error"` by the middleware. Reads and per-row pipeline churn are intentionally not audited.

## Security
- Secrets, DB credentials, third-party API keys live only in `.env` (gitignored).
- Feed-source credentials are currently stored as plaintext `JSONB` (recorded MVP decision, not a bug to silently "fix" — encryption is a separate, explicitly-scoped task; flag it, don't patch it inline).
- Never log full request/response bodies for `app/auth/` routes or ingest payloads that may carry client credentials.
- Registry/plugin code from `app/registry/` is validated against its manifest schema before execution — no `eval`/`exec` of untrusted plugin source outside the sandboxed runtime.
- Export/publish endpoints require an authorized feed-source scope check before the atomic `os.replace()` is reachable.

## Testing
- Contract test: `uv run pytest tests/test_plugin_contract.py`
- Fixtures in `tests/fixtures/` — feeds, registry, example plugin
- `TEST_DATABASE_URL` must point to PostgreSQL; integration tests use the `isolated_database_url` fixture (`tests/conftest.py`), backed by `pytest-postgresql` template-database cloning
- Do not export `DATABASE_URL` while running tests; if both `DATABASE_URL` and `TEST_DATABASE_URL` are set, pytest will warn at session start
- Async tests are marked `@pytest.mark.asyncio` explicitly (`asyncio_mode` is not set globally)
- Tests are immune to an ambient `DATABASE_URL`: alembic callers in tests pin their URL via `config.attributes["database_url"]`, which `alembic/env.py` prefers over the env var (the var remains the fallback for the dev command)
- The suite is large and growing fast (1079 backend tests as of the unified-field-list cycle, up from 1019 two cycles prior) — treat runtime and reporting ergonomics as a first-class concern, not an afterthought

### Test reporting (large-suite ergonomics)
- Run with `uv run pytest --report-log=.report.jsonl` — JSON Lines, one event per line.
- Use `pytest-reportlog`, not `pytest-json-report`: the latter has documented crashes and duplicate-report bugs under `pytest-xdist` (upstream numirias/pytest-json-report#51/#52, pytest-dev/pytest-xdist#1140), and this project runs with `-n auto` by default via `addopts`. `pytest-reportlog` only writes from the controller process, so it's xdist-safe by construction.
- `.report.jsonl` is a test artifact — gitignored, never committed.
- Failure triage (local — CI runs `uv run pytest --cov=app --cov-report=term-missing`; `coverage`'s `fail_under = 85` in `pyproject.toml` is the gate):
  ```bash
  uv run pytest --report-log=.report.jsonl
  FAILED=$(jq -c 'select(.["$report_type"]=="TestReport" and .when=="call" and .outcome=="failed")' \
    .report.jsonl | wc -l)
  if [ "$FAILED" -gt 0 ]; then
    jq -r 'select(.["$report_type"]=="TestReport" and .when=="call" and .outcome=="failed")
      | "\(.nodeid): \(.longrepr.reprcrash.message // "n/a")"' .report.jsonl
    exit 1
  fi
  ```
- Slow-test triage (relevant given the wall-time tracking already established in `docs/decisions.md`):
  ```bash
  jq -c 'select(.["$report_type"]=="TestReport" and .when=="call") | {nodeid, duration}' \
    .report.jsonl | jq -s 'sort_by(-.duration) | .[:10]'
  ```
- Any change to `content_hash`/`config_hash` computation includes a regression test asserting hash stability across a no-op re-run.
- Any change to the three-tier config merge covers all three override directions (`global`-only, `client`-over-`global`, `feed_source`-over-`client`).
- Locking (`app/pipeline/locks.py`) needs a concurrency test asserting a second overlapping run for the same `feed_source_id` is skipped, not queued or errored.
- Mock external ingest sources in unit tests; only integration tests marked as such hit the real Postgres container.

## Python best practices (enforced via Ruff, not prose)
Rather than restating generic rules Ruff already checks, point at the rule groups so the `ruff` exit-0 gate is the actual enforcement mechanism:
- `E711`/`E712` — `is`/`is not` for `None`/`True`/`False` comparisons
- `C4` — comprehension simplifications over manual loops
- `SIM113` — `enumerate()` over manual counters
- `B006`/`B008` — no mutable default arguments
- `I` — import sorting (replaces `isort`; do not add `isort` separately)
- New code must leave `uv run ruff check . ../plugins` (run from `backend/`) at exit 0. There is no baseline file: the gate is hard, like `mypy` since 2026-09-10. Do not run `ruff check` from the repository root — `I001` resolves first-party modules from the project root, so the root cwd reports phantom import-order findings; the root `ruff.toml` sets `src = ["backend", "plugins"]` to keep the two cwds identical.

## Performance
- Profile before optimizing pipeline hot paths (`cProfile`/`py-spy`); reference the measurement in the PR/commit, matching the existing wall-time-tracking style in `docs/decisions.md`.
- `QualityCheckStep` cross-product rules use one bulk query per rule, not one query per product.
- `app/export/service.py` renders the feed in memory but runs `render_feed` and the version/publish file writes off the event loop via `asyncio.to_thread` (single-worker deployment); streaming to file is future work if peak memory becomes a problem.

## CI gate (required, in order)
```bash
uv run ruff check . ../plugins   # exit-0, hard gate, no baseline file
uv run mypy .            # exit-0, hard gate, no baseline file
MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins   # plugins runtime-contract code
uv run alembic check     # no pending model changes without a migration
uv run pytest --cov=app --cov-report=term-missing   # coverage floor 85 (pyproject)
```
These gates are enforced in CI (`.github/workflows/ci.yml`), which runs them after `alembic upgrade head`.

## Documentation map
- `docs/architecture.md` — Pipeline stages, delta mechanics, plugin system
- `docs/data-model.md` — Entities, contenthash/confighash, retention rules
- `docs/api.md` — Endpoint reference, reserved plugin routes
- `docs/plugins.md` — Runtime contract, manifest, three-tier scope merge
- `docs/decisions.md` — Dated decision log (tooling choices, wall-time baselines, resolved ambiguities); append, never rewrite history
- `docs/superpowers/plans/` and `docs/superpowers/specs/` — per-cycle plan/design documents from the agentic dev workflow; read the relevant one before touching a module it covers

## Documentation
Any change to behavior, API surface, data model, or commands MUST update the affected docs and ADRs in the same commit. Documentation that contradicts `gmc-feed-engine-spec.md` is a bug: fix the doc, never the spec, and flag the conflict to the operator. Tooling/process decisions (like the reportlog switch above) get a dated entry in `docs/decisions.md`, following the existing entry format (Topic / Decision / Rationale).

