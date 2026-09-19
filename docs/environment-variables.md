# Environment Variables

Every environment variable the project reads, grouped by where it is used:
**backend**, **frontend (Vite)**, **production stack (Docker Compose / Caddy)**, and
**tests**. Each row lists whether it is required, its default, and what it does.

## How configuration is loaded

- **Backend** (`app/config.py`) reads `<repo-root>/.env` **regardless of the working
  directory** (`config.py:48`). Variable names are case-insensitive and unknown keys
  are ignored. Real process environment variables override the file, so a shell
  export wins over `.env`.
- **Frontend** `vite.config.ts` calls `loadEnv(mode, <repo-root>, '')`
  (`vite.config.ts:10`), so the `VITE_*` variables below are read from the
  **repo-root** `.env`/`.env.local`, not from `frontend/.env`. Relative paths such
  as the TLS certs are resolved from the repo root.
- **Alembic** uses the same `DATABASE_URL` and also accepts it via the programmatic
  `config.attributes["database_url"]` (used by tests).

Quick start:

```bash
cp .env.example .env          # local dev values (gitignored)
# production: cp .env.prod.example .env  and replace every CHANGE_ME
```

> Never commit `.env`. Secrets belong only in the gitignored files.

---

## Backend

### Required

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_SECRET` | — | Signs session cookies. Must be a long random string. |
| `INITIAL_USERNAME` | — | First admin user, seeded only when the `users` table is empty. |
| `INITIAL_PASSWORD` | — | Password for that initial admin user. |

Missing any of these makes the backend fail to start (`app/config.py:16`).

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/gmc_feed` | Runtime + Alembic connection. `postgresql://`, `postgres://`, and `postgresql+asyncpg://` are all accepted and normalized to asyncpg. |

### Sessions

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_IDLE_MINUTES` | `30` | Idle timeout before a session expires. Must be `> 0`. |
| `SESSION_ABSOLUTE_HOURS` | `12` | Hard session lifetime cap. Must be `> 0`. |

### Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `PLUGINS_DIR` | `<repo>/plugins` | Where plugins are discovered. Container value: `/app/plugins`. |
| `EXPORT_DIR` | `<repo>/exports` | Atomic feed XML output directory. Container value: `/data/exports`. |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Absolute public URL used for export links and the `Secure` cookie. Set to the public HTTPS URL in production. |

### AI cache / Redis

Only connection facts live in the environment; model ids and API keys are stored in
the database (`ai_provider_configs`).

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | — | Full Redis URL. Wins over the discrete variables below. Use `rediss://` to enable TLS. |
| `REDIS_HOST` | — | Redis host (used when `REDIS_URL` is unset). |
| `REDIS_PORT` | `6379` | Redis port. |
| `REDIS_PASSWORD` | — | Redis password. |
| `REDIS_SSL` | `false` | Enable TLS for the discrete connection. |
| `AI_CACHE_DIR` | `<repo>/.cache/ai` | Disk cache for AI responses when Redis is not configured. Container value: `/data/ai-cache`. |

### Logging & retention

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Standard library log level name (`DEBUG`, `INFO`, `WARNING`, …). |
| `LOG_FORMAT` | `json` | `json` for production, `console` for readable local output. |
| `EVENT_LOG_RETENTION_DAYS` | `180` | Audit/error event retention window. Must be `> 0`; also editable in admin settings. |

---

## Frontend (Vite dev server)

These are read by `vite.config.ts` — not by client code. Put them in the repo-root
`.env` (see the loading note above). They affect the **dev server only**; production
serves the static build behind Caddy.

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_HTTPS_CERT` | — | Path to a TLS certificate for HTTPS dev. Must be set together with `VITE_HTTPS_KEY` or Vite fails fast. Path is relative to the repo root. |
| `VITE_HTTPS_KEY` | — | Path to the matching TLS private key. |
| `VITE_ALLOWED_HOSTS` | `localhost` | Comma-separated `Host` headers the dev server accepts. Keep in sync with `DEV_HOST` when using `make dev-caddy`. |
| `VITE_API_TARGET` | `http://127.0.0.1:8000` | Backend origin the `/api` dev proxy targets. |

Generate local certs (repo root):

```bash
mkdir -p local-certs
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout local-certs/localhost-key.pem \
  -out local-certs/localhost-cert.pem -days 365 \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

`VITEST` (set automatically by Vitest) is the only value read from `import.meta.env`
inside the app; you do not set it yourself.

> Note: `frontend/.env.example` exists as a reference, but `vite.config.ts` reads the
> repo-root `.env`. Use the root file so the dev server actually picks the values up.

---

## Production stack (Docker Compose + Caddy)

Used by `docker-compose.prod.yml`, `Caddyfile`, and `.deploy.env`. Copy
`.env.prod.example` to `.env` on the VPS and replace every `CHANGE_ME`.

### Database & Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_DB` | `gmc_feed` (dev) / required (prod) | Database name. Must match the name in `DATABASE_URL`. |
| `POSTGRES_USER` | `postgres` (dev) / required (prod) | Database user. |
| `POSTGRES_PASSWORD` | `postgres` (dev) / required (prod) | Database password. |
| `POSTGRES_PORT` | `5432` | Host port published for Postgres (dev only). |
| `REDIS_PASSWORD` | required (prod) | Required for the bundled Redis service. |
| `REDIS_MAXMEMORY` | `256mb` | Redis memory cap (eviction: `allkeys-lru`). |

### Domain, TLS & proxy

| Variable | Default | Description |
|----------|---------|-------------|
| `DOMAIN` | `localhost` | Public hostname Caddy serves and obtains a TLS certificate for. |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Set to `https://$DOMAIN` so export links and `Secure` cookies work. |
| `BACKEND_URL` | `http://127.0.0.1:8000` (Caddyfile) / `http://backend:8000` (compose) | Backend upstream proxied by Caddy. |
| `FRONTEND_URL` | `http://127.0.0.1:5173` (Caddyfile) / `http://frontend:80` (compose) | Frontend upstream proxied by Caddy. |
| `BACKEND_BIND` | `127.0.0.1` | Host interface the backend port binds to. |
| `BACKEND_PORT` | `8000` | Host port for the backend. |
| `FRONTEND_BIND` | `127.0.0.1` | Host interface the frontend port binds to. |
| `FRONTEND_PORT` | `8080` | Host port for the frontend. |

### Release / image

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAGE_TAG` | `latest` | Image tag pulled from GHCR, set in `.deploy.env`. Must be a pushed Git tag (e.g. `v1.2.0`) or `latest`. |

### Backups (bundled service)

| Variable | Default | Description |
|----------|---------|-------------|
| `SCHEDULE` | `@daily` | Backup schedule. |
| `BACKUP_KEEP_DAYS` | `7` | Daily backups to retain. |
| `BACKUP_KEEP_WEEKS` | `0` | Weekly backups to retain. |
| `BACKUP_KEEP_MONTHS` | `0` | Monthly backups to retain. |
| `BACKUP_KEEP_MINS` | `1440` | Minute-level backups to retain. |

---

## Development tooling

| Variable | Default | Description |
|----------|---------|-------------|
| `DEV_HOST` | `localhost` | Caddy dev site label for `make dev-caddy`; pair with `VITE_ALLOWED_HOSTS`. |
| `FRONTEND_DIST` | `/srv/gmc/frontend/dist` | Static root served by `make prod`. |
| `MSG` | required | Migration message for `make backend-migrate-new`. |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed` | Exported by the `Makefile` for backend targets. |

---

## Tests

| Variable | Default | Description |
|----------|---------|-------------|
| `TEST_DATABASE_URL` | required | PostgreSQL URL for integration/migration tests. Must use `postgresql+asyncpg://` and contain no query parameters. |
| `PYTEST_XDIST_AUTO_NUM_WORKERS` | auto | Cap pytest-xdist workers on connection-limited servers. |
| `MIGRATION_SCHEMA` | — | Internal override used by migration tests. |
| `DATABASE_URL` | — | Do **not** export alongside `TEST_DATABASE_URL`; tests warn and ignore it. |

---

## Reference

- Backend settings definition: `backend/app/config.py`
- Local template: `.env.example` · Production template: `.env.prod.example`
- Frontend config: `frontend/vite.config.ts` · Deploy tag: `.deploy.env.example`
- Deployment guide: `docs/prod_deployment.md`
