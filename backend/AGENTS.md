# GMC Feed Master — Backend Agent Instructions

## WHAT
FastAPI + SQLAlchemy 2.0 async + PostgreSQL. Core modules: `app/` (routes, models, pipeline, staging, QC, plugins, ingest, export, auth, registry).

## HOW
```bash
# From backend/
cp .env.example .env
docker compose up -d postgres
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed \
  uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
uv run pytest -n auto                    # needs TEST_DATABASE_URL
uv run ruff check .
uv run mypy .
```

## Key conventions
- **Migrations only via Alembic** — never `create_all`. `uv run alembic revision --autogenerate -m "msg"`
- **Pipeline steps** in `app/pipeline/steps.py` — fixed order: `IngestStep` → `MappingStep` → `StagingStep` → `PluginStep` → `QualityCheckStep` → `ExportStep`
- **Delta mechanics** in `app/staging/delta.py` — `content_hash` (canonical product) + `config_hash` (pipeline + resolved plugin config/data + versions)
- **Three-tier scope merge** in `app/staging/config_resolver.py` — `global` → `client` → `feed_source` (per-key dict merge)
- **Plugin runtime contract** in `app/plugins/runtime.py` — `RunContext` with read-only `original_product`
- **Quality Check** in `app/qc/engine.py` — sequential, non-blocking, per-product + cross-product rules
- **Atomic publish** in `app/export/service.py` — temp file + `os.replace()`
- **Per-feed-source lock** in `app/pipeline/locks.py` — overlapping runs skipped

## Testing
- Contract test: `uv run pytest tests/test_plugin_contract.py`
- Fixtures in `tests/fixtures/` — feeds, registry, example plugin
- `TEST_DATABASE_URL` must point to PostgreSQL for integration tests

## Documentation map
- `docs/architecture.md` — Pipeline stages, delta mechanics, plugin system
- `docs/data-model.md` — Entities, contenthash/confighash, retention rules
- `docs/api.md` — Endpoint reference, reserved plugin routes
- `docs/plugins.md` — Runtime contract, manifest, three-tier scope merge

## Documentation
Any change to behavior, API surface, data model, or commands MUST update the affected docs and ADRs in the same commit. Documentation that contradicts `gmc-feed-engine-spec.md` is a bug: fix the doc, never the spec, and flag the conflict to the operator.