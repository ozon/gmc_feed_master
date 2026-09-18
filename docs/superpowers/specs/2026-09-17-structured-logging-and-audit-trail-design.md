# Structured Logging and Audit Trail — Design

**Date:** 2026-09-17
**Status:** Approved (design), pending implementation plan
**Scope:** Backend structured logging, unified event/audit store, admin log viewer, frontend error capture and request correlation.

## Problem

The system needs "full logging" serving three purposes, built in phases:

1. **Ops observability & debugging** — trace pipeline runs and HTTP requests end-to-end, correlate frontend errors to backend lines.
2. **Audit / compliance** — durable, append-only record of auth events, user administration, config mutations, and exports.
3. **Local dev debugging** — readable console output without infrastructure.

Today the backend uses stdlib `logging` with module-level loggers and lazy `%s` interpolation, but has **no central configuration** (it relies on uvicorn defaults), no structured output, and no HTTP request correlation. The frontend has **no logging at all** (no `console` calls, no error reporter). The only security control is `_ExportTokenRedactor`, which strips the export token from uvicorn access logs (`backend/app/main.py:68`).

Pipeline logs already carry `run_id` via `RunContext`/`StepContext`, and `backend/AGENTS.md` requires `run_id` on every log line for a run. A `SystemLogsPage` placeholder already exists at `/logs` in the global nav, with a `systemLogs` i18n namespace.

## Decisions

| Topic | Decision |
|-------|----------|
| Backend library | Add `structlog`, bridged through stdlib so existing `logging.getLogger(__name__)` call sites keep working unchanged |
| Destination | JSON to stdout (ops) + one Postgres `event_log` table (queryable) + admin UI |
| Frontend capture | `warn`/`error` shipped to backend; `debug`/`info` stay in the browser console |
| Audit scope | Auth, user administration, config mutations, exports — not reads, not per-row pipeline churn |
| Retention | 180 days default, configurable via `GlobalSetting`, enforced by a purge job |
| Table shape | One unified `event_log` table with a `category` column; append-only |
| Redaction | Key denylist + size caps, extending the existing export-token redactor |
| Backend lib choice | `structlog` (new dependency, explicitly approved) |
| Frontend lib | Small custom util, no dependency |
| Logs page access | Admin-only; `RequireAdmin` on the route, nav item hidden for non-admins |

## Section 1 — Backend logging core (Phase 1)

### Configuration

New module `backend/app/logging_setup.py` exposes `configure_logging(settings)`, idempotent, called first inside `create_app()` before the app object is built.

`structlog.configure` with:

- Processors: `structlog.contextvars.merge_contextvars`, `structlog.stdlib.add_log_level`, `structlog.stdlib.add_logger_name`, `structlog.processors.TimeStamper(fmt="iso", utc=True)`, `StackInfoRenderer`, `format_exc_info`, the redaction processor, then `structlog.stdlib.ProcessorFormatter.wrap_for_formatter`.
- `logger_factory=structlog.stdlib.LoggerFactory()`, `wrapper_class=structlog.stdlib.BoundLogger`, `cache_logger_on_first_use=True`.

A root `logging.StreamHandler(sys.stdout)` uses `structlog.stdlib.ProcessorFormatter`. Its `foreign_pre_chain` repeats `merge_contextvars`, level, logger name, timestamp, redaction, and `PositionalArgumentsFormatter`. This is the mechanism that keeps the existing stdlib loggers working **and** structured without rewriting call sites: foreign (stdlib) records flow through the same processor chain and renderers.

Renderer is selected by configuration:

- `LOG_FORMAT=json` (default) → `structlog.processors.JSONRenderer` (production, Docker/Caddy).
- `LOG_FORMAT=console` → `structlog.dev.ConsoleRenderer` (local dev).

Level is `LOG_LEVEL` (default `INFO`). Uvicorn loggers (`uvicorn`, `uvicorn.access`, `uvicorn.error`) set `propagate=True` so access logs render through the same JSON formatter; the existing `_ExportTokenRedactor` filter remains installed on `uvicorn.access`.

### Redaction processor

A structlog processor that walks the event dict:

- Case-insensitive key denylist: `password`, `passwd`, `token`, `secret`, `cookie`, `authorization`, `api_key`, `apikey`, `session`, `credential`, `private_key`, `access_key`, `refresh_token`. Matching keys become `[REDACTED]`.
- String values longer than 2048 characters are truncated with a `…[truncated]` suffix.
- Recurses into dicts/lists to a depth of 3. `# ponytail: depth-3 recursion cap, raise if nested payloads appear`.
- Never logs request/response bodies for `/auth/*` or ingest credentials (already an AGENTS.md rule; redaction is the enforcement backstop).

### Context propagation

- **HTTP request** — `backend/app/middleware/request_context.py`: reads `X-Request-ID` (accepted only if it matches `[A-Za-z0-9._-]{8,64}`, otherwise a fresh `uuid4`), calls `structlog.contextvars.clear_contextvars()` then `bind_contextvars(request_id, method, path)`, sets the `X-Request-ID` response header, and clears contextvars in `finally`. No separate access-log line is emitted — uvicorn's remains, avoiding duplication.
- **Actor** — `get_current_user` binds `actor` (username) and `role`, so every log line during an authenticated request carries the actor.
- **Pipeline run** — `PipelineRunner.run` binds `run_id`, `feed_source_id`, and `client_id` for the duration of the run. Because `merge_contextvars` is in the foreign pre-chain, the existing step loggers emit `run_id` automatically, satisfying the AGENTS.md tracing requirement.
- **Unhandled exceptions** — logged with `request_id` at `error`, then persisted as `category=server_error` (Phase 2).

### Config surface

`backend/app/config.py` and `.env.example` gain `LOG_LEVEL` (default `INFO`), `LOG_FORMAT` (default `json`), and `EVENT_LOG_RETENTION_DAYS` (default `180`).

## Section 2 — Unified event store (Phase 2)

### Model and migration

New model `backend/app/models/event_log.py`, table `event_log`:

| Column | Type | Notes |
|--------|------|-------|
| `id` | bigint identity | PK, monotonic — cursor pagination key |
| `created_at` | timestamptz | server default `now()`, indexed |
| `category` | varchar(20) | `audit` \| `server_error` \| `client_error` |
| `level` | varchar(10) | `info` \| `warning` \| `error` \| `critical` |
| `source` | varchar(20) | `backend` \| `frontend` |
| `logger` | varchar(120) | nullable |
| `actor` | varchar(120) | nullable |
| `actor_role` | varchar(20) | nullable |
| `client_id` | integer | nullable, plain telemetry integer (not FK — mirrors `ai_usage_logs`) |
| `feed_source_id` | integer | nullable, plain telemetry integer (not FK — mirrors `ai_usage_logs`) |
| `request_id` | varchar(64) | nullable, indexed |
| `run_id` | integer | nullable |
| `message` | text | not null |
| `context` | jsonb | not null, default `'{}'` |

Indexes: `created_at`, `(category, created_at)`, `request_id`, `feed_source_id`.

Append-only: no update or delete routes exist. Correctness is enforced in the application layer (there is no `UPDATE`/`DELETE` path); this is a deliberate simplification. `# ponytail: append-only enforced in app, add a DB trigger/revoke if tamper resistance is required`.

Alembic migration via `uv run alembic revision --autogenerate`.

`GlobalSetting` (`backend/app/models/global_setting.py`) gains `event_log_retention_days` (integer, not null, default 180, server default `'180'`). `Settings.event_log_retention_days` is the fallback when no `GlobalSetting` row exists.

### Service

`backend/app/event_log/service.py`:

- `record_event(session, *, category, level, source, message, context, actor, actor_role, client_id, feed_source_id, request_id, run_id, logger)` — single insert.
- `audit(session, action, *, target_type=None, target_id=None, detail=None, level="info")` — convenience that pulls `actor`, `actor_role`, `request_id`, `run_id`, `client_id`, `feed_source_id` from contextvars and writes `category=audit`, `source=backend`. Most audit call sites are one line.
- `record_client_error(...)` — `category=client_error`, `source=frontend`.
- `record_server_error(...)` — `category=server_error`, `source=backend`.
- `purge_expired_events(session_factory, now)` — deletes rows older than the retention window, returns a count. Mirrors `purge_expired_ai`.

### Retention job

Register `system-event-log-purge` on the existing `PURGE_CRON` in the `create_app` lifespan, calling `purge_expired_events` and logging the removed count, mirroring the existing staging/ingestion/AI purge jobs (`backend/app/main.py:128-174`).

## Section 3 — Audit capture and logs API (Phase 3)

### Audit call sites

Explicit `audit(...)` calls at the in-scope mutations:

- **Auth**: login success, login failure, logout, self password change.
- **User admin**: user create, user update, admin password reset.
- **Clients/feeds**: client create/update/delete, feed-source create/update/delete, export-token rotate.
- **Config mutations**: field mapping, plugin config, pipeline config, AI settings, global settings.
- **Exports/runs**: successful export/publish with counts, manual run trigger.

Reads and per-row pipeline churn are intentionally excluded.

### API

New router `backend/app/routes/logs.py` (no path prefix, matching the repo convention of full paths in decorators). Paths sit under `/logs/*`, **not** `/logs`, because the SPA owns the bare `/logs` route (see Routing below):

- `GET /logs/entries` — **admin-only** via `require_admin` (`backend/app/access.py:76`). Query params: `category`, `level`, `source`, `logger`, `actor`, `client_id`, `feed_source_id`, `request_id`, `run_id`, `from`, `to`, `q` (literal message substring — LIKE wildcards escaped), `limit` (default 100, max 500), `cursor` (id). Returns `{items, next_cursor}`, ordered by `id desc`.
- `POST /logs/client` — **any authenticated user** via `require_user`. Accepts a batch of frontend error entries, validates, truncates, and redacts, writes `category=client_error`. Returns 204. Protected by an in-memory per-user fixed window (60 requests / 60 s) plus a request-body size cap. `# ponytail: in-memory fixed window, single worker — move to Redis if workers scale`.

The router is registered in `create_app` **without** `enforce_scope_access` (like `admin_router`); authorization is enforced per endpoint.

**Routing.** The deployment proxies only an allowlist of prefixes to the backend (`Caddyfile`, `Caddyfile.dev`); anything else is served the SPA. Bare `/logs` is the SPA route, so backend paths must be under a subpath. A `handle /logs/*` block is added to both Caddyfiles — Caddy's `handle /logs/*` matches `/logs/...` but not the bare `/logs`, so the SPA page still loads while the API is proxied. (Note: `POST /chat` was an existing backend route absent from both Caddyfiles; it was resolved in a same-day follow-up by adding `handle /chat` to both Caddyfiles and the Vite proxy.)

### Admin UI

Replace the `SystemLogsPage` placeholder (`frontend/src/features/systemLogs/SystemLogsPage.tsx`) with a real page at `/logs`:

- Read-only Mantine table with filters (level, category, source, actor, request id, message search, time range) and cursor pagination.
- Rows show `created_at`, level, category, source, actor, message; expanding a row shows the full structured `context`.
- TanStack Query hook(s) added to `frontend/src/api/hooks.ts` with keys in `frontend/src/api/queryKeys.ts`; no local server-state duplication.
- Gated by `RequireAdmin` in `frontend/src/app/router.tsx`; the `/logs` nav item in `frontend/src/app/AppShell.tsx` is hidden for non-admins.
- `frontend/public/locales/<lang>/systemLogs.json` extended; the `systemLogs` i18n namespace already exists.

## Section 4 — Frontend logger and correlation (Phase 4)

### Logger util

New `frontend/src/logging/logger.ts` (~100 lines, no dependency):

- `createLogger(scope)` → `debug`/`info` (console only) and `warn`/`error` (console **and** queued for shipping).
- Mirrors backend redaction: denylist key scrubbing, message/stack/value caps.
- Batch flush on size (10), interval (5s), `pagehide`, and `visibilitychange`; delivered with `navigator.sendBeacon('/logs/client')`, falling back to `fetch(..., { keepalive: true })`.
- `captureException(error, context)` helper.

Wire-up in `frontend/src/main.tsx`: `window.onerror`, `window.onunhandledrejection`, and a new top-level `AppErrorBoundary` wrapping `<App/>`. The existing `PluginErrorBoundary` keeps its error-isolation role (ADR 0004) and additionally reports through the logger.

### Correlation

`frontend/src/api/client.ts` generates an `X-Request-ID` per request (`crypto.randomUUID()`), attaches it, and on a failed response logs an error carrying that id, method, url path (query stripped), and status. The backend echoes the id, so frontend and backend lines share it. Frontend-only errors get a locally generated id, so every shipped entry has a `request_id`. Context shipped: `request_id`, route, url path, truncated `userAgent`. No PII.

## Section 5 — Phasing and testing

Each phase ends with the full gate set. Backend: `uv run ruff check . ../plugins`, `uv run mypy .`, `uv run alembic check`, `uv run pytest --report-log=.report.jsonl`. Frontend: `npm run typecheck`, `npm run test`, `npm run build`.

1. **Core** (Section 1): structured config, redaction, request-context middleware, auth + pipeline contextvars, config/`.env.example`.
2. **Store** (Section 2): model + migration, `GlobalSetting` column, service, purge job.
3. **API + viewer** (Section 3): logs router + admin gating, audit instrumentation, frontend page + hooks + nav gating + i18n.
4. **Frontend shipping** (Section 4): logger util, global handlers, `AppErrorBoundary`, api-client request id + failure logging.

### Tests

- **Core**: redaction processor (each key class, nesting, truncation); contextvar merge into foreign stdlib records; request-id middleware generate vs. accept vs. reject-invalid, header echo; JSON vs. console rendering.
- **Store**: model/migration present; `record_event` insert; `purge_expired_events` cutoff behavior; retention default resolution (GlobalSetting over settings fallback).
- **API + viewer**: `GET /logs/entries` returns 403 for non-admin; filters and cursor pagination; `POST /logs/client` validation, redaction, body cap, and fixed-window limit; an audit row is emitted for each in-scope mutation; frontend page render/filter test and hook test.
- **Frontend shipping**: logger redaction and shipping path; api client attaches `X-Request-ID` and logs failed calls; error boundary reports.

## Risks and non-goals

- **Log flooding** via `POST /logs/client` is the main new abuse surface — mitigated by the fixed-window rate limit, body cap, and per-entry truncation.
- **Redaction is a backstop, not a guarantee** — developers must still avoid logging secrets; the denylist catches the common cases.
- **Non-goals**: external log aggregation (no OTel/Loki collector), read/access audit events, per-scope retention, and log-based alerting. These can be layered on later without changing the call-site surface.

## Documentation

Same commit as behavior change:

- New ADR `docs/decisions/0012-structured-logging-and-audit-trail.md`.
- Update `backend/docs/architecture.md`, `backend/docs/api.md`, `backend/docs/data-model.md`, `backend/AGENTS.md` (error-handling & logging section), `frontend/docs/architecture.md`, `frontend/AGENTS.md`, `backend/docs/decisions.md` (dated tooling entry for the `structlog` addition), and `.env.example`.
- Update `Caddyfile` and `Caddyfile.dev` with the `handle /logs/*` block.
