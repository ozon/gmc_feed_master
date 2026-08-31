# Makefile Reference

Shortcuts for common development tasks. All commands run from the project root.

## Quick Start

```bash
make help            # List all available targets with commands
make dev             # Start everything (postgres + backend + frontend)
make dev-stop        # Stop dev servers
```

## Targets

### Infrastructure

| Target | Description |
|--------|-------------|
| `make db-up` | Start PostgreSQL container |
| `make db-down` | Stop PostgreSQL container |
| `make db-logs` | Tail PostgreSQL logs |

### Backend

| Target | Description |
|--------|-------------|
| `make backend-dev` | Start FastAPI dev server (port 8000, auto-reload) |
| `make backend-test` | Run tests (parallel, `pytest -n auto`) |
| `make backend-test-seq` | Run tests (sequential, `pytest -n0`) |
| `make backend-lint` | Lint with ruff |
| `make backend-lint-fix` | Lint + auto-fix with ruff |
| `make backend-typecheck` | Type-check with mypy |
| `make backend-migrate` | Apply migrations (`alembic upgrade head`) |
| `make backend-migrate-down` | Revert migrations (`alembic downgrade base`) |
| `make backend-migrate-new MSG="msg"` | Generate new migration |
| `make backend-check` | Run lint + typecheck + test |

### Frontend

| Target | Description |
|--------|-------------|
| `make frontend-install` | Install npm dependencies |
| `make frontend-dev` | Start Vite dev server |
| `make frontend-build` | TypeScript check + production build |
| `make frontend-test` | Run vitest tests |
| `make frontend-typecheck` | Type-check with `tsc -b` |

### Plugins

| Target | Description |
|--------|-------------|
| `make plugin-test` | Run plugin contract tests |

### Registry

| Target | Description |
|--------|-------------|
| `make registry-check` | Validate registry against `gmc_def.md` |
| `make registry-update` | Regenerate `attributes.json` from `gmc_def.md` |

### Combined Workflows

| Target | Description |
|--------|-------------|
| `make dev` | Start postgres + backend + frontend in background |
| `make dev-stop` | Stop backend and frontend dev servers |
| `make test` | Run all tests (backend + frontend + plugins) |
| `make lint` | Run all linters and type-checkers |
| `make check` | Full CI check (lint + typecheck + all tests) |

## Examples

```bash
# Daily development
make db-up              # Start database
make backend-dev        # Start backend in one terminal
make frontend-dev       # Start frontend in another terminal

# Generate migration
make backend-migrate-new MSG="add user preferences"

# Quick quality check
make backend-check      # lint + typecheck + test

# Full CI simulation
make check              # everything

# Start everything at once (background)
make dev
# ... work ...
make dev-stop
```

## Environment Variables

| Variable | Default | Used by |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed` | backend targets |
| `MSG` | _(required)_ | `backend-migrate-new` |

## Notes

- `make dev` logs to `/tmp/gmc-backend.log` and `/tmp/gmc-frontend.log`
- `make backend-migrate-new` requires `MSG` — it will error without it
- `make dev-stop` kills processes by name (safe to run multiple times)
- Backend runs with `--workers 1` for session store consistency
