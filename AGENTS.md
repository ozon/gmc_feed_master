# GMC Feed Master — Agent Instructions

## WHAT
**Stack:** Python 3.10+, FastAPI, PostgreSQL (Docker), SQLAlchemy 2.0, APScheduler. Frontend: React 19, TypeScript, Vite, Mantine, TanStack Query/Table/Form, dnd-kit.
**Layout:** `backend/` (FastAPI app, plugins, tests), `frontend/` (React app), `plugins/` (plugin directories with `plugin.json` + Python + optional React), `docs/` (architecture, ADRs).

## WHY
Authoritative GMC product data source per market. Plugin-based delta pipeline: Input Reader → Field Mapping → Staging/Hashing → Module Runner → Quality Check → XML Writer → atomic publish. One feed source = one XML output. Agency tenancy: 1 client → n feed sources.

## HOW
**Backend (from `backend/`):**
```bash
cp .env.example .env                          # configure DATABASE_URL, secrets
docker compose up -d postgres                 # start PostgreSQL
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed \
  uv run alembic upgrade head                  # apply migrations
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1  # dev server
uv run pytest -n auto                         # test suite (parallel, needs TEST_DATABASE_URL)
uv run ruff check .                           # lint
uv run mypy .                                 # typecheck
```

**Frontend (from `frontend/`):**
```bash
npm install                                   # install deps
npm run dev                                   # Vite dev server (HTTPS with certs in .env.local)
npm run build                                 # typecheck + production build
npm run test                                  # vitest
npm run typecheck                             # tsc -b
```

**Plugin development:**
```bash
# New plugin under plugins/<id>/
# plugin.json manifest (see spec §5.2), Python class with process()/validate_config()
# Optional: frontend/component.tsx for custom UI
# Contract test: uv run pytest backend/tests/test_plugin_contract.py
```

## Boundaries
**Always:**
- Run contract tests (`test_plugin_contract.py`) when adding/changing plugins
- Use `uv run alembic revision --autogenerate` for schema changes
- Keep per-feed-source run lock (skip overlapping runs)
- Atomic publish: temp file → `os.replace()` for export endpoint

**Ask first:**
- Schema changes (affects migrations, staging hashes, QC rules)
- New dependencies (backend: `pyproject.toml`, frontend: `package.json`)
- Changing pipeline step order or adding extension points

**Never:**
- Commit secrets, tokens, or `.env` files
- Bypass the per-feed-source run lock
- Mutate `original_product` in plugin `process()` (read-only)
- Use reserved plugin routes `/plugins/{id}/config` or `/plugins/{id}/data`
- Duplicate server state into client stores (TanStack Query only)

## Documentation map
- `docs/decisions/0001-server-state-tanstack-query.md` — ADR: TanStack Query for server state
- `docs/decisions/0002-schema-renderer-rjsf.md` — ADR: RJSF for schema-rendered plugin UIs
- `docs/decisions/0003-rolldown-optional-evaluation.md` — ADR: Rolldown as optional bundler evaluation
- `docs/decisions/0004-plugin-frontend-error-isolation.md` — ADR: Plugin frontend error isolation
- `backend/docs/architecture.md` — Pipeline stages, delta mechanics, plugin system
- `backend/docs/data-model.md` — Entities, contenthash/confighash, retention rules
- `backend/docs/api.md` — Endpoint reference, reserved plugin routes
- `backend/docs/plugins.md` — Runtime contract, manifest, three-tier scope merge
- `frontend/docs/architecture.md` — Stack, server-state strategy, routing, state boundaries
- `frontend/docs/plugin-uis.md` — Build-time discovery, RJSF schema rendering, error boundaries
- `backend/AGENTS.md` — Backend-specific commands and conventions
- `frontend/AGENTS.md` — Frontend-specific commands and conventions

## Documentation
Any change to behavior, API surface, data model, or commands MUST update the affected docs and ADRs in the same commit. Documentation that contradicts `gmc-feed-engine-spec.md` is a bug: fix the doc, never the spec, and flag the conflict to the operator.