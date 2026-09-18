# Production Container Deployment Design

Date: 2026-09-18
Status: approved (design), pending implementation plan

## Problem

Production currently assumes host-installed processes: PostgreSQL in a dev-only
Compose file, the FastAPI backend run from a `uv` checkout, `frontend/dist`
served from disk by a host-run Caddy, and Alembic run by hand. There is no
container image, no image registry, no release pipeline, and no documented
deploy/rollback/backup procedure. We need a self-contained production stack on a
single VPS that is built from immutable images and deployed manually.

This design supersedes the containerization parts of
`docs/superpowers/specs/2026-08-31-caddy-production-deployment-design.md`. The
Caddyfile API routing table from that spec still applies; the catch-all block
changes from `file_server` to a reverse proxy (see §7).

## Decisions (agreed with the operator)

1. **Single host, production only.** No staging, no multi-host, no orchestrator.
2. **Two application images** in a private GHCR registry: `gmc-feed-backend`
   (Python) and `gmc-feed-frontend` (Node build → static runtime). Registry
   namespace `ghcr.io/ozon/` (repo is `github.com/ozon/gmc_feed_master`).
3. **Caddy runs as a container edge** (Option 1). `caddy:2-alpine` publishes
   80/443, terminates TLS, proxies API prefixes to the backend and everything
   else to the frontend.
4. **No-Caddy mode exists**: the frontend container is static-only, and an
   operator-supplied external reverse proxy must route both API and SPA. No
   automatic API proxying inside the frontend image.
5. **Backups via a sidecar container** (`prodrigestivill/postgres-backup-local`)
   with `pg_dump` on a schedule and 7-day retention, written to a host bind mount.
6. **Deploy and rollback are manual SSH actions.** The pipeline stops after
   build+push. `IMAGE_TAG` lives in `.deploy.env`, separate from secrets `.env`.
7. **Migrations run on backend startup** (entrypoint `alembic upgrade head`
   before `uvicorn`).
8. **Redis is an always-on service** in the production stack, used as the AI
   cache. It is not published to the host.
9. **Multi-arch images**: `linux/amd64` and `linux/arm64`.
10. **The VPS holds a git clone** at `/opt/gmc/gmc_feed_master`; tracked compose
    and Caddyfile updates arrive via `git pull`. `.env`, `.deploy.env`,
    `backups/`, and `data/` are untracked.

Additional approved judgment calls:

- `alembic` moves from the `[dependency-groups] dev` group to main dependencies
  so a `--no-dev` production image can run migrations.
- The backup sidecar sets `BACKUP_KEEP_WEEKS=0` and `BACKUP_KEEP_MONTHS=0`
  because its defaults (4 weeks / 6 months) would violate the 7-day retention
  requirement.

## 1. Topology

`docker-compose.prod.yml` runs six services on one private network:

| Service | Image | Host exposure | Role |
|---|---|---|---|
| `postgres` | `postgres:16.4-alpine` | none | system of record; named volume `postgres_data` |
| `redis` | `redis:7-alpine` | none | AI cache; named volume `redis_data` |
| `backend` | `ghcr.io/ozon/gmc-feed-backend:${IMAGE_TAG:-latest}` | loopback only | API, pipeline, scheduler; migrate-on-start |
| `frontend` | `ghcr.io/ozon/gmc-feed-frontend:${IMAGE_TAG:-latest}` | loopback only | static SPA (nginx) |
| `caddy` | `caddy:2-alpine` | `80:80`, `443:443`, `443:443/udp` | TLS + edge routing |
| `backup` | `prodrigestivill/postgres-backup-local:16-alpine` | none | daily `pg_dump`, 7-day retention |

Default request path: `client → Caddy :443 → (API prefixes) backend:8000`,
`(everything else) frontend:80`.

TLS certificates persist in the `caddy_data` named volume. Only Caddy reaches
the public interface.

## 2. Compose environment contract

Two files, strictly separate:

- **`.env`** (on VPS, never committed): all secrets and runtime config,
  including `POSTGRES_*`, `DATABASE_URL` with the `postgres` service host,
  `SESSION_SECRET`, `INITIAL_USERNAME`, `INITIAL_PASSWORD`, `PUBLIC_BASE_URL`,
  `DOMAIN`, `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD`, `LOG_*`, port/bind
  overrides.
- **`.deploy.env`** (on VPS, never committed): **only** `IMAGE_TAG=v1.2.0`.

Compose must interpolate `IMAGE_TAG` when resolving `image:`. Compose
automatically loads `./.env` (from the project directory) for interpolation, so
that covers `POSTGRES_*`, `DOMAIN`, and the port/bind overrides. `IMAGE_TAG` is
supplied by sourcing `.deploy.env` into the shell first — this avoids depending
on multiple `--env-file` flags (Compose ≥ 2.24) and keeps `.env` as the single
secret file:

```bash
cd /opt/gmc/gmc_feed_master
git pull
set -a && . ./.deploy.env && set +a
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Container-level environment comes from `env_file: .env` on the backend (and
explicit `environment:` interpolation for `postgres`, `redis`, `caddy`, and
`backup`). Auto-loading `.env` only sets interpolation variables; the backend's
`env_file` is what injects them into the container.

`.deploy.env` is the only file touched during a rollback. `.env` is unchanged
across deploys and rollbacks.

## 3. Images

Both images build from the repository root context. The frontend build reaches
into `plugins/` (`frontend/src/features/plugin/customComponents.ts` imports
`plugins/core/*/frontend/component`), and the backend needs the runtime Python
plugins, so a `frontend/`- or `backend/`-only context cannot work.

### 3.1 Backend (`backend/Dockerfile`)

Multi-stage:

- **Builder**: `python:3.11-slim` + `uv` binary; `uv sync --frozen --no-dev`
  into `/app/.venv`.
- **Runtime**: `python:3.11-slim`; copies the venv, `backend/app`,
  `backend/registry`, `backend/alembic`, `backend/alembic.ini`, and `plugins/`.
  `WORKDIR=/app`, `PYTHONPATH=/app`, `PATH=/app/.venv/bin:$PATH`.
- Environment overrides (config defaults resolve wrongly at `/app`):
  `PLUGINS_DIR=/app/plugins`, `EXPORT_DIR=/data/exports`,
  `AI_CACHE_DIR=/data/ai-cache`.
- `EXPOSE 8000`; entrypoint:

  ```sh
  #!/bin/sh
  set -e
  alembic upgrade head
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
  ```

- **Exactly one worker and one replica, always.** APScheduler and the
  per-feed-source `LockRegistry` are in-process; multiple workers would
  duplicate jobs and break the lock. The deployment docs state "never scale the
  backend."

### 3.2 Frontend (`frontend/Dockerfile`)

Multi-stage:

- **Build**: `node:22-alpine`; copies `frontend/` and `plugins/` into a
  `/src/frontend` + `/src/plugins` layout so the relative plugin imports resolve
  exactly as they do in CI; `npm ci && npm run build`.
- **Runtime**: `nginx:alpine`; copies `dist` to `/usr/share/nginx/html` and an
  SPA config (`try_files $uri /index.html`). Static only — no API proxying.

### 3.3 Build context hygiene

New root `.dockerignore` excludes `.git`, `**/node_modules`, `**/.venv`,
Python/JS caches, `exports/`, `backups/`, `data/`, `docs/`, and **every `.env`
file** (both root `.env` and `backend/.env` exist on developer disks and must
never enter an image).

## 4. Migrations and runtime

- `alembic` is a main dependency (moved out of the dev group); `asyncpg` is
  already a main dependency, so `alembic upgrade head` works in the image.
- `alembic/env.py` reads `DATABASE_URL` and converts it to the asyncpg URL, so
  `.env` may carry `postgresql+asyncpg://…@postgres:5432/…`.
- `depends_on` gives the backend `postgres: condition: service_healthy`, using
  the existing healthcheck, so migrations never race an unready database.
- The backend starts even if Redis is unhealthy: Redis is an optional cache and
  `app/ai/cache_config.py` fails open. Compose uses `depends_on: [redis]`
  (ordering only) with no health condition.

## 5. Persistence, Redis, and backups

### 5.1 Volumes

- `postgres_data` (named) — database.
- `redis_data` (named) — AI cache, survives restarts.
- `./data/exports` → `EXPORT_DIR` — atomically published feed XML is served
  from disk and must survive restarts.
- `./data/ai-cache` → `AI_CACHE_DIR` — disk cache fallback when Redis is unset.
- `./backups` → backup sidecar output.

### 5.2 Redis

```yaml
redis:
  image: redis:7-alpine
  restart: unless-stopped
  command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}",
            "--maxmemory", "${REDIS_MAXMEMORY:-256mb}",
            "--maxmemory-policy", "allkeys-lru"]
  environment:
    REDIS_PASSWORD: ${REDIS_PASSWORD}
  volumes:
    - redis_data:/data
  healthcheck:
    test: ["CMD-SHELL", "redis-cli --no-auth-warning -a \"$$REDIS_PASSWORD\" ping | grep -q PONG"]
```

- Not published to the host; reachable only as `redis:6379` on the private
  network.
- `allkeys-lru` with a configurable `maxmemory` prevents unbounded growth on a
  small VPS.
- `.env` sets `REDIS_PASSWORD` plus `REDIS_HOST=redis` and `REDIS_PORT=6379`.
  The discrete variables (not a `REDIS_URL`) are used deliberately: Compose does
  not interpolate `${…}` inside `env_file` values, so a URL containing
  `${REDIS_PASSWORD}` would be passed literally, and a URL would also require
  percent-encoding a password with special characters. Setting `REDIS_HOST`
  makes `effective_backend()` return `redis`; unsetting it falls back to the
  disk cache.
- Redis is a cache and is not backed up.

### 5.3 Backup sidecar

```yaml
backup:
  image: prodrigestivill/postgres-backup-local:16-alpine
  restart: unless-stopped
  environment:
    POSTGRES_HOST: postgres
    POSTGRES_DB: ${POSTGRES_DB}
    POSTGRES_USER: ${POSTGRES_USER}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    SCHEDULE: "@daily"
    BACKUP_KEEP_DAYS: "7"
    BACKUP_KEEP_WEEKS: "0"
    BACKUP_KEEP_MONTHS: "0"
    BACKUP_KEEP_MINS: "1440"
  volumes:
    - ./backups:/backups
  depends_on:
    postgres:
      condition: service_healthy
```

Backups land in `./backups/{last,daily,weekly,monthly}/` as gzipped SQL. With
`@daily` + `BACKUP_KEEP_DAYS=7`, the `daily/` folder holds the last 7 days;
`weekly/` and `monthly/` are disabled so nothing older survives.

Restore procedure (documented in `docs/prod_deployment.md`):

```bash
set -a && . ./.env && set +a
gunzip -c backups/daily/<db>-latest.sql.gz | \
  docker compose -f docker-compose.prod.yml \
    exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

## 6. CI/CD

New `.github/workflows/release.yml`, triggered **only** by a version tag:

```yaml
on:
  push:
    tags: ['v*']
permissions:
  contents: read
  packages: write
```

A matrix builds both images with `context: .` and per-image `file`. Steps:
checkout → QEMU → Buildx → GHCR login with `GITHUB_TOKEN` →
`docker/build-push-action` with `platforms: linux/amd64,linux/arm64`,
`push: true`, GHA layer cache, `provenance: false`, and tags:

```
ghcr.io/ozon/<image>:${{ github.ref_name }}
ghcr.io/ozon/<image>:latest
```

No deploy step. The existing `ci.yml` is untouched; a release tag is expected to
be cut from an already-green `main`.

GHCR is private (private repo, private package). One-time VPS auth:
`docker login ghcr.io` with a PAT scoped `read:packages`; credentials persist in
`~/.docker/config.json`.

## 7. Caddyfile change

The Caddyfile keeps its environment-variable style and all API `handle` blocks.
Only the catch-all block changes:

```caddyfile
handle {
    reverse_proxy {$FRONTEND_URL:http://127.0.0.1:5173}
}
```

The container sets `DOMAIN`, `BACKEND_URL=http://backend:8000`, and
`FRONTEND_URL=http://frontend:80`. This changes the host `make prod` target
(which previously served `frontend/dist` from disk) to proxy instead; the
Makefile and docs note this.

## 8. No-Caddy mode

Same compose file, Caddy scaled to zero:

```bash
docker compose -f docker-compose.prod.yml up -d --scale caddy=0
```

The frontend and backend publish loopback ports for an on-host external proxy:

- SPA + static assets: `127.0.0.1:${FRONTEND_PORT:-8080}` → frontend:80
- API prefixes: `127.0.0.1:${BACKEND_PORT:-8000}` → backend:8000

Bind addresses are `${FRONTEND_BIND:-127.0.0.1}` and
`${BACKEND_BIND:-127.0.0.1}` so the operator can bind a routable interface when
the proxy is off-host (and firewall accordingly). The external proxy must
replicate the API routing table from the Caddyfile; the guide documents it.

## 9. Deploy, rollback, verification

- **Deploy**: push a `v*` tag → wait for the release workflow → on the VPS
  `git pull`, then the two `docker compose … pull` / `up -d` commands. A brief
  restart is acceptable (no zero-downtime).
- **Rollback**: set `IMAGE_TAG` in `.deploy.env` to the previous tag, then
  `pull` + `up -d`. `.env` is untouched.
- **Verification**: `docker compose … ps` shows all services healthy/running and
  `docker compose … logs -f backend caddy` is clean; optionally
  `curl https://$DOMAIN/health` (the endpoint already exists; not a hard
  requirement).

## 10. Files

**New**

- `backend/Dockerfile`
- `backend/docker-entrypoint.sh`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- `docker-compose.prod.yml`
- `.dockerignore`
- `.env.prod.example`
- `.deploy.env.example`
- `.github/workflows/release.yml`
- `docs/prod_deployment.md`

**Changed**

- `backend/pyproject.toml` + `backend/uv.lock` — move `alembic` to main deps.
- `Caddyfile` — catch-all to `reverse_proxy {$FRONTEND_URL:…}`.
- `.gitignore` — add `data/`, `backups/`, `.deploy.env`.
- `Makefile` — add minimal `prod-pull` / `prod-up` / `prod-down` / `prod-logs`
  targets that source `.deploy.env` before invoking Compose (which auto-loads
  `.env`); note `prod` is host-only.
- `AGENTS.md` and `coding-agent-instructions.md` — deployment conventions
  (tag-triggered release, GHCR, manual deploy, `IMAGE_TAG`).
- `docs/decisions/0013-production-deployment.md` + dated entry in
  `docs/decisions.md`.

## 11. `docs/prod_deployment.md` outline

1. Prerequisites: VPS provisioning (Docker Engine + Compose plugin), non-root
   deploy user, UFW allowing 22/80/443, one-time `docker login ghcr.io` with a
   `read:packages` PAT.
2. Domain + DNS: A record to the VPS IP; `DOMAIN` in `.env`; Caddy provisions
   Let's Encrypt automatically.
3. Configuration: clone to `/opt/gmc/gmc_feed_master`; copy
   `.env.prod.example → .env` and `.deploy.env.example → .deploy.env`; explain
   every variable and that `.env` is secret and never committed.
4. First deploy: `docker compose … pull` + `up -d`; migrations run on backend
   start; verification steps.
5. Release flow: create/push `v*` tag → watch Actions → `git pull` → pull/up.
6. Rollback flow: edit `IMAGE_TAG`, pull/up; `.env` unchanged.
7. No-Caddy mode and the API routing table the external proxy must implement.
8. Backup and restore: schedule, layout, retention, restore command, where files
   live.
9. Operations: logs, single-worker constraint ("never scale the backend"),
   Redis role and `maxmemory`, restarting individual services.

## 12. Out of scope

- Automatic deploy on push/merge; the pipeline ends after push.
- Zero-downtime / blue-green; a short restart is accepted.
- Staging environment; multi-host or orchestrator solutions.
- Publishing the Postgres or Redis ports publicly.
- Backing up Redis (cache only).
- Containerizing the dev workflow (dev keeps `docker compose up -d postgres`
  and runs backend/frontend on the host).

## 13. Risks and notes

- Cross-architecture builds use QEMU for `arm64`; CI time increases and emulated
  builds are slower. Acceptable for tag-only releases.
- The frontend image must be rebuilt for plugin-UI changes (it imports plugin
  code at build time). The backend image must be rebuilt for Python plugin
  changes. Both are in the same repo and tag, so a release rebuilds both.
- `--scale caddy=0` is the no-Caddy mechanism; because no service sets
  `container_name`, scaling is supported.
- `.env` must set `PUBLIC_BASE_URL` to the HTTPS domain so export URLs and the
  `Secure` session cookie behave correctly.
- `litellm`'s Redis cache connects to database 0; all cached keys share that DB
  under the configured namespace. Dedicated-DB isolation is not used.
