# 0012: Structured logging and audit trail

## Status
Accepted (2026-09-17)

## Context
The backend had no central logging configuration (it relied on uvicorn defaults), no
structured output, and no HTTP request correlation; the frontend had no logging at all.
Full logging must serve ops observability, a durable audit record of privileged mutations,
and readable local-dev output. Pipeline logs already carried `run_id` through
`RunContext`/`StepContext` and module-level `logging.getLogger(__name__)` call sites exist
throughout `app/`, so a rewrite of every call site was not acceptable.

## Decision
- **stdlib-first with a structlog bridge.** `structlog` is added and configured in
  `backend/app/logging_setup.py:configure_logging` (idempotent, called first inside
  `create_app()`). A root stdout `StreamHandler` with
  `structlog.stdlib.ProcessorFormatter` renders both structlog and foreign stdlib records,
  so existing `logging.getLogger(__name__)` call sites keep working unchanged. JSON is the
  default renderer (`LOG_FORMAT=json`); `LOG_FORMAT=console` selects
  `structlog.dev.ConsoleRenderer` for local dev; `LOG_LEVEL` defaults to `INFO`. Uvicorn
  loggers are set to `propagate=True` and the existing `_ExportTokenRedactor` filter stays
  on `uvicorn.access`.
- **Redaction processor.** A processor walks the event dict: a case-insensitive key
  denylist (`password`, `token`, `secret`, `authorization`, `api_key`, …) → `[REDACTED]`,
  string values longer than 2048 chars truncate with a `…[truncated]` suffix, recursing
  into dicts/lists to depth 3. It is a backstop, not a licence to log secrets.
- **Contextvars.** `RequestContextMiddleware` reads/validates `X-Request-ID` (accepted only
  if it matches `[A-Za-z0-9._-]{8,64}`, else a fresh `uuid4`), binds
  `request_id`/`method`/`path`, echoes the id on the response, and clears in `finally`.
  `get_current_user` binds `actor`/`actor_role`; `PipelineRunner.run` binds
  `run_id`/`feed_source_id`/`client_id` for the run's duration. `merge_contextvars` is in
  the foreign pre-chain, so foreign stdlib lines carry the same context automatically.
  Unhandled exceptions are logged and persisted as `category=server_error`.
- **One append-only `event_log` table** with `category` ∈ `audit` | `server_error` |
  `client_error`, `source` ∈ `backend` | `frontend`, plus level, actor/role, telemetry
  `client_id`/`feed_source_id` (plain integers, not FKs), `request_id`, `run_id`, message,
  and a JSONB `context`. The service (`backend/app/event_log/service.py`) exposes
  `record_event`, `audit`, `record_client_error`, `record_server_error`, and
  `purge_expired_events`.
- **180-day configurable retention.** `global_settings.event_log_retention_days`
  (default 180, falling back to `Settings.event_log_retention_days` = 180 when no row),
  enforced by the nightly `system-event-log-purge` job on `PURGE_CRON`.
- **`/logs/*` API, not `/logs`.** The SPA owns the bare `/logs` route, so
  `GET /logs/entries` (admin-only, cursor-paginated, filterable) and `POST /logs/client`
  (any authenticated user; redacted, size-capped, rate-limited) live under a subpath. A
  `handle /logs/*` block is added to both `Caddyfile` and `Caddyfile.dev`; Caddy's pattern
  does not match the bare `/logs`, so the admin viewer page still loads.
- **Admin-only viewer.** `/logs` renders the read-only `SystemLogsPage` table with filters
  and cursor pagination, gated by `RequireAdmin` and hidden from non-admin nav.
- **Frontend errors shipped to `/logs/client`.** `frontend/src/logging/logger.ts` sends
  `warn`/`error` (debug/info stay in the console) in size/interval batches via
  `navigator.sendBeacon` with a `fetch(..., {keepalive})` fallback. `window.onerror`,
  `unhandledrejection`, and `AppErrorBoundary` report through it. Every API request carries
  an `X-Request-ID`, and failed calls log the id, method, path, and status, so frontend and
  backend lines share a correlation id.

## Consequences
New dependency `structlog`; one migration (`event_log` + the `event_log_retention_days`
column); new config keys `LOG_LEVEL`, `LOG_FORMAT`, `EVENT_LOG_RETENTION_DAYS`. Audit
instrumentation is explicit at auth, user admin, client/feed CRUD, field mapping, plugin
config, pipeline config, AI settings/admin, and export/publish call sites; reads and
per-row pipeline churn are deliberately not audited. Redaction and the `/logs/client`
rate limit are abuse/leak mitigations, not guarantees — the rate limiter is an in-memory
fixed window (60 requests / 60 s per user), which assumes the single-worker deployment.

**Follow-up (resolved):** the pre-existing `POST /chat` backend route was absent from both
`Caddyfile` and `Caddyfile.dev`, and from the Vite dev proxy, so the chat widget could not
reach the backend through either proxy. A `handle /chat` block was added to both Caddyfiles
and `/chat` to the Vite proxy (same-day follow-up); `/chat` is now reachable in dev and
production. A hardening follow-up also escaped LIKE wildcards in the viewer search, evicts
stale rate-limit windows, and caps the shipped `message` at the API's 2000-char limit while
truncating context values at 2048.
