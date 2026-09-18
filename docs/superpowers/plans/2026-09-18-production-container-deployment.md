# Production Container Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the backend and frontend as immutable GHCR images, run the full production stack (Postgres, Redis, backend, frontend, Caddy, backup) on one VPS via `docker-compose.prod.yml`, and release via Git tags with manual deploy/rollback.

**Architecture:** Two multi-stage Docker images built from the repo root (both need `plugins/`). A single production Compose file references images by `${IMAGE_TAG:-latest}`; secrets live in `.env`, the deploy tag in `.deploy.env`. Caddy is the container edge (TLS + API/SPA routing); the frontend is a static nginx SPA. GitHub Actions builds and pushes both images on `v*` tags only.

**Tech Stack:** Docker/Buildx, Docker Compose v2, GitHub Actions, GHCR, Caddy 2, nginx, PostgreSQL 16, Redis 7, `uv`/Python 3.11, Node 22.

**Spec:** `docs/superpowers/specs/2026-09-18-production-container-deployment-design.md`

## Global Constraints

- Backend runs **exactly one uvicorn worker and one replica** — APScheduler and the in-process lock registry forbid scaling.
- Image names: `ghcr.io/ozon/gmc-feed-backend`, `ghcr.io/ozon/gmc-feed-frontend`; namespace `ghcr.io/ozon/`.
- Build platforms: `linux/amd64,linux/arm64`.
- Release workflow triggers on `v*` tags **only**; it builds and pushes, never deploys.
- `IMAGE_TAG` lives in `.deploy.env`; all secrets live in `.env`; `.env` never changes on deploy/rollback.
- Postgres and Redis are never published to the host.
- Backup retention is 7 days: `BACKUP_KEEP_DAYS=7`, `BACKUP_KEEP_WEEKS=0`, `BACKUP_KEEP_MONTHS=0`, `SCHEDULE=@daily`.
- Redis is an always-on AI cache; `--maxmemory-policy allkeys-lru`, `REDIS_MAXMEMORY` default `256mb`.
- Dev workflow (`docker compose up -d postgres`, host backend/frontend) is unchanged.
- Any behavior/command/doc change updates the affected docs and ADRs in the same commit (`AGENTS.md` rule).
- Local tooling available: `uv 0.11.26`, Docker 29.7.2, Compose v5.4.0, Node 26.8.2, Python 3.11.

---

### Task 1: Backend production image

**Files:**
- Modify: `backend/pyproject.toml` (move `alembic` from dev group to main deps)
- Modify: `backend/uv.lock` (regenerated)
- Create: `.dockerignore`
- Create: `backend/docker-entrypoint.sh`
- Create: `backend/Dockerfile`

**Interfaces:**
- Consumes: nothing.
- Produces: image `ghcr.io/ozon/gmc-feed-backend:latest` exposing 8000; entrypoint runs migrations then `uvicorn app.main:app --workers 1`; env `PLUGINS_DIR`, `EXPORT_DIR`, `AI_CACHE_DIR` consumed by later tasks.

- [ ] **Step 1: Move `alembic` to main dependencies**

In `backend/pyproject.toml`, add `"alembic==1.16.4",` to the `dependencies` list (after `"diskcache==5.6.3",`) and remove the `"alembic==1.16.4",` line from the `[dependency-groups] dev` list.

- [ ] **Step 2: Regenerate the lockfile**

Run:
```bash
cd backend && uv lock
```
Expected: lockfile updated, exit 0.

- [ ] **Step 3: Create the repo-root `.dockerignore`**

Create `.dockerignore` with exactly:

```
# Git / CI
.git
.github

# Secrets and local env (never ship)
.env
**/.env
.env.*
**/.env.*
.deploy.env
*.local

# Python
**/.venv
**/__pycache__
**/*.py[cod]
**/*.egg-info
**/.mypy_cache
**/.ruff_cache
**/.pytest_cache
**/.testmondata*

# Node / frontend build output
**/node_modules
**/dist
**/*.tsbuildinfo

# Runtime data / artifacts
exports
backups
data
**/.report.json*

# Docs and tests (not needed in images)
docs
backend/tests
frontend/test-results
frontend/playwright-report

# Misc
.worktrees
.codegraph
.openchamber
```

- [ ] **Step 4: Create the backend entrypoint**

Create `backend/docker-entrypoint.sh` with exactly:

```sh
#!/bin/sh
set -e

echo "applying database migrations..."
alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Then run `chmod +x backend/docker-entrypoint.sh`.

- [ ] **Step 5: Create the backend Dockerfile**

Create `backend/Dockerfile` with exactly:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/app ./app
RUN uv sync --frozen --no-dev

FROM python:3.11-slim AS runtime

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH=/app/.venv/bin:$PATH \
    PLUGINS_DIR=/app/plugins \
    EXPORT_DIR=/data/exports \
    AI_CACHE_DIR=/data/ai-cache

COPY --from=builder /app/.venv /app/.venv
COPY backend/app ./app
COPY backend/registry ./registry
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY plugins ./plugins
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
```

- [ ] **Step 6: Build the image (single-arch local verification)**

Run:
```bash
docker build -f backend/Dockerfile -t ghcr.io/ozon/gmc-feed-backend:latest .
```
Expected: `naming to ghcr.io/ozon/gmc-feed-backend:latest` and exit 0.

- [ ] **Step 7: Verify runtime contents**

Run:
```bash
docker run --rm --entrypoint sh ghcr.io/ozon/gmc-feed-backend:latest -c \
  'command -v alembic && command -v uvicorn && ls /app/plugins/core >/dev/null && echo IMAGE_OK'
```
Expected: paths printed followed by `IMAGE_OK`.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/Dockerfile backend/docker-entrypoint.sh .dockerignore
git commit -m "build(backend): add production Docker image with migrate-on-start"
```

---

### Task 2: Frontend production image

**Files:**
- Create: `frontend/nginx.conf`
- Create: `frontend/Dockerfile`

**Interfaces:**
- Consumes: `.dockerignore` from Task 1 (excludes `node_modules`/`dist`).
- Produces: image `ghcr.io/ozon/gmc-feed-frontend:latest` serving the SPA on port 80 with `try_files` fallback.

- [ ] **Step 1: Create the nginx SPA config**

Create `frontend/nginx.conf` with exactly:

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 2: Create the frontend Dockerfile**

Create `frontend/Dockerfile` with exactly:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS build

WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

COPY frontend ./frontend
COPY plugins ./plugins
RUN cd frontend && npm run build

FROM nginx:1.27-alpine AS runtime

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/frontend/dist /usr/share/nginx/html
EXPOSE 80
```

- [ ] **Step 3: Build the image**

Run:
```bash
docker build -f frontend/Dockerfile -t ghcr.io/ozon/gmc-feed-frontend:latest .
```
Expected: `naming to ghcr.io/ozon/gmc-feed-frontend:latest` and exit 0. The plugin imports under `plugins/core/*/frontend/` must resolve (same relative layout as CI).

- [ ] **Step 4: Verify the SPA is served**

Run:
```bash
docker run --rm -d --name gmc-fe-test -p 127.0.0.1:18080:80 ghcr.io/ozon/gmc-feed-frontend:latest && \
sleep 2 && curl -fsS http://127.0.0.1:18080/ | grep -q '<div id="root">' && echo FRONTEND_OK; \
docker rm -f gmc-fe-test
```
Expected: `FRONTEND_OK`.

- [ ] **Step 5: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf
git commit -m "build(frontend): add production nginx image"
```

---

### Task 3: Production Compose stack and env templates

**Files:**
- Create: `docker-compose.prod.yml`
- Create: `.env.prod.example`
- Create: `.deploy.env.example`
- Modify: `.gitignore` (add `data/`, `backups/`, `.deploy.env`)

**Interfaces:**
- Consumes: images from Tasks 1–2; `./Caddyfile` (edited in Task 4).
- Produces: services `postgres`, `redis`, `backend`, `frontend`, `caddy`, `backup`; volumes `postgres_data`, `redis_data`, `caddy_data`, `caddy_config`; loopback ports `BACKEND_PORT`/`FRONTEND_PORT`.

- [ ] **Step 1: Create `docker-compose.prod.yml`**

Create `docker-compose.prod.yml` with exactly:

```yaml
name: gmc-feed-prod

services:
  postgres:
    image: postgres:16.4-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command:
      - redis-server
      - --requirepass
      - ${REDIS_PASSWORD}
      - --maxmemory
      - ${REDIS_MAXMEMORY:-256mb}
      - --maxmemory-policy
      - allkeys-lru
    environment:
      REDIS_PASSWORD: ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD-SHELL", "redis-cli --no-auth-warning -a \"$$REDIS_PASSWORD\" ping | grep -q PONG"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    image: ghcr.io/ozon/gmc-feed-backend:${IMAGE_TAG:-latest}
    restart: unless-stopped
    env_file:
      - .env
    environment:
      PLUGINS_DIR: /app/plugins
      EXPORT_DIR: /data/exports
      AI_CACHE_DIR: /data/ai-cache
    volumes:
      - ./data/exports:/data/exports
      - ./data/ai-cache:/data/ai-cache
    expose:
      - "8000"
    ports:
      - "${BACKEND_BIND:-127.0.0.1}:${BACKEND_PORT:-8000}:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started

  frontend:
    image: ghcr.io/ozon/gmc-feed-frontend:${IMAGE_TAG:-latest}
    restart: unless-stopped
    expose:
      - "80"
    ports:
      - "${FRONTEND_BIND:-127.0.0.1}:${FRONTEND_PORT:-8080}:80"
    depends_on:
      - backend

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    environment:
      DOMAIN: ${DOMAIN:-localhost}
      BACKEND_URL: http://backend:8000
      FRONTEND_URL: http://frontend:80
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - backend
      - frontend

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

volumes:
  postgres_data:
  redis_data:
  caddy_data:
  caddy_config:
```

- [ ] **Step 2: Create `.env.prod.example`**

Create `.env.prod.example` with exactly:

```
# Production configuration for docker-compose.prod.yml.
# Copy to .env on the VPS and replace every CHANGE_ME value. Never commit .env.

# --- PostgreSQL ---
POSTGRES_DB=gmc_feed
POSTGRES_USER=gmc_feed
POSTGRES_PASSWORD=CHANGE_ME_db_password
# Must use the compose service host "postgres" and match POSTGRES_* above.
DATABASE_URL=postgresql+asyncpg://gmc_feed:CHANGE_ME_db_password@postgres:5432/gmc_feed

# --- Sessions / initial admin user ---
SESSION_SECRET=CHANGE_ME_long_random_session_secret
INITIAL_USERNAME=admin
INITIAL_PASSWORD=CHANGE_ME_admin_password
SESSION_IDLE_MINUTES=30
SESSION_ABSOLUTE_HOURS=12

# --- Public URL / domain (Caddy TLS, export links, Secure cookies) ---
DOMAIN=gmc.example.com
PUBLIC_BASE_URL=https://gmc.example.com

# --- Redis (AI cache; reachable only on the compose network) ---
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=CHANGE_ME_redis_password
REDIS_MAXMEMORY=256mb

# --- Logging / retention ---
LOG_LEVEL=INFO
LOG_FORMAT=json
EVENT_LOG_RETENTION_DAYS=180

# --- Optional host port bindings (loopback; needed for no-Caddy mode) ---
# BACKEND_BIND=127.0.0.1
# BACKEND_PORT=8000
# FRONTEND_BIND=127.0.0.1
# FRONTEND_PORT=8080
```

- [ ] **Step 3: Create `.deploy.env.example`**

Create `.deploy.env.example` with exactly:

```
# Image tag deployed by docker-compose.prod.yml. Must be a Git tag pushed to
# GHCR (for example v1.2.0) or "latest". This is the only file changed on rollback.
IMAGE_TAG=v1.2.0
```

- [ ] **Step 4: Ignore runtime data in git**

Append to `.gitignore`:
```
# Production runtime data / deploy tag
data/
backups/
.deploy.env
```

- [ ] **Step 5: Validate the Compose file**

Run (shell-provided variables take precedence over `.env`, so no real secrets are needed):
```bash
POSTGRES_DB=gmc_feed POSTGRES_USER=gmc_feed POSTGRES_PASSWORD=x \
REDIS_PASSWORD=x DOMAIN=localhost IMAGE_TAG=v0.0.1 \
docker compose -f docker-compose.prod.yml config >/dev/null && echo COMPOSE_OK
```
Expected: `COMPOSE_OK`. The backend `env_file` requires a root `.env` to exist; the dev `.env` is sufficient for this structural check (shell-provided variables above are used for interpolation).

- [ ] **Step 6: Commit**

```bash
git add docker-compose.prod.yml .env.prod.example .deploy.env.example .gitignore
git commit -m "build(prod): add production compose stack and env templates"
```

---

### Task 4: Caddy edge routing and Makefile targets

**Files:**
- Modify: `Caddyfile:45-49` (catch-all block)
- Modify: `Makefile` (prod compose targets; `prod` comment)

**Interfaces:**
- Consumes: `FRONTEND_URL` env set by `docker-compose.prod.yml` Task 3.
- Produces: Caddy proxying the SPA to `${FRONTEND_URL}`; `make prod-pull|prod-up|prod-down|prod-logs|prod-ps`.

- [ ] **Step 1: Change the Caddyfile catch-all to a reverse proxy**

Replace the final block in `Caddyfile` (currently):

```caddyfile
	handle {
		root * {$FRONTEND_DIST:/srv/gmc/frontend/dist}
		try_files {path} /index.html
		file_server
	}
```

with:

```caddyfile
	handle {
		reverse_proxy {$FRONTEND_URL:http://127.0.0.1:5173}
	}
```

All other `handle` blocks stay unchanged.

- [ ] **Step 2: Validate the Caddyfile**

Run:
```bash
docker run --rm -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -e DOMAIN=localhost -e BACKEND_URL=http://backend:8000 \
  -e FRONTEND_URL=http://frontend:80 \
  caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```
Expected: `Valid configuration`.

- [ ] **Step 3: Add production Compose targets to the Makefile**

Insert this block immediately before the `# Help` section (`# =====...` above `.PHONY: help`):

```make
# ==============================================================================
#  Production compose (VPS)
# ==============================================================================

PROD_COMPOSE := docker compose -f docker-compose.prod.yml

.PHONY: prod-pull
prod-pull: ## Pull production images (IMAGE_TAG from .deploy.env)
	set -a && . ./.deploy.env && set +a && $(PROD_COMPOSE) pull

.PHONY: prod-up
prod-up: ## Start the production stack
	set -a && . ./.deploy.env && set +a && $(PROD_COMPOSE) up -d

.PHONY: prod-down
prod-down: ## Stop the production stack
	$(PROD_COMPOSE) down

.PHONY: prod-ps
prod-ps: ## Show production service status
	$(PROD_COMPOSE) ps

.PHONY: prod-logs
prod-logs: ## Tail production logs
	$(PROD_COMPOSE) logs -f --tail=100
```

- [ ] **Step 4: Clarify the host-only `prod` target**

Replace the existing target:

```make
.PHONY: prod
prod: ## Start Caddy production server (requires DOMAIN and BACKEND_URL env vars)
	caddy run --config Caddyfile --adapter caddyfile
```

with:

```make
.PHONY: prod
prod: ## Run Caddy on the host (local only; production uses prod-up)
	caddy run --config Caddyfile --adapter caddyfile
```

- [ ] **Step 5: Verify target parsing**

Run:
```bash
make help | grep -E 'prod-(pull|up|down|ps|logs)'
```
Expected: the five targets are listed.

- [ ] **Step 6: Commit**

```bash
git add Caddyfile Makefile
git commit -m "build(prod): route SPA to frontend container and add compose targets"
```

---

### Task 5: Release workflow

**Files:**
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: `backend/Dockerfile`, `frontend/Dockerfile`, root build context.
- Produces: on `v*` tag push, images tagged `:${{ github.ref_name }}` and `:latest` in GHCR.

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/release.yml` with exactly:

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: read
  packages: write

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - image: gmc-feed-backend
            dockerfile: backend/Dockerfile
          - image: gmc-feed-frontend
            dockerfile: frontend/Dockerfile
    steps:
      - uses: actions/checkout@v4

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push ${{ matrix.image }}
        uses: docker/build-push-action@v6
        with:
          context: .
          file: ${{ matrix.dockerfile }}
          platforms: linux/amd64,linux/arm64
          push: true
          provenance: false
          cache-from: type=gha,scope=${{ matrix.image }}
          cache-to: type=gha,mode=max,scope=${{ matrix.image }}
          tags: |
            ghcr.io/ozon/${{ matrix.image }}:${{ github.ref_name }}
            ghcr.io/ozon/${{ matrix.image }}:latest
```

- [ ] **Step 2: Lint the workflow**

Run:
```bash
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest .github/workflows/release.yml
```
Expected: no output, exit 0.

- [ ] **Step 3: Verify the trigger is tag-only**

Run:
```bash
grep -A3 '^on:' .github/workflows/release.yml
```
Expected: only `push:` → `tags:` → `- 'v*'` (no `branches`, no `pull_request`).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci(release): build and push images to GHCR on v* tags"
```

---

### Task 6: `docs/prod_deployment.md`

**Files:**
- Create: `docs/prod_deployment.md`

**Interfaces:**
- Consumes: all files/commands from Tasks 1–5.
- Produces: the provisioning/backup/reference guide referenced by `docs/release_process.md` and `AGENTS.md`.

- [ ] **Step 1: Write the guide**

Create `docs/prod_deployment.md` with exactly this content:

````markdown
# Production Deployment (Single VPS)

Production runs one Docker Compose stack (`docker-compose.prod.yml`) with six
services: `postgres`, `redis`, `backend`, `frontend`, `caddy`, and `backup`.
Images are built by `.github/workflows/release.yml` from Git tags and stored in
GHCR. Deploy and rollback are manual on the VPS. For the short operational
runbook see `docs/release_process.md`.

## 1. VPS provisioning

Ubuntu/Debian with sudo access.

1. Install Docker Engine + Compose plugin and grant your user docker access:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker "$USER"
   ```
   Log out and back in so the group membership applies.
2. Firewall — allow SSH and the web ports only:
   ```bash
   sudo ufw allow 22/tcp
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw allow 443/udp
   sudo ufw enable
   ```
3. Clone the repository:
   ```bash
   sudo mkdir -p /opt/gmc && sudo chown "$USER":"$USER" /opt/gmc
   cd /opt/gmc
   git clone git@github.com:ozon/gmc_feed_master.git
   cd gmc_feed_master
   ```
4. Authenticate to GHCR once with a GitHub PAT that has the `read:packages`
   scope:
   ```bash
   echo "$GHCR_PAT" | docker login ghcr.io -u <github-username> --password-stdin
   ```
   Credentials persist in `~/.docker/config.json`; no repeated login is needed.

## 2. Domain and DNS

1. Create an A record (e.g. `gmc.example.com`) pointing at the VPS public IP.
2. Set `DOMAIN` and `PUBLIC_BASE_URL` in `.env` (§3).
3. Caddy obtains a Let's Encrypt certificate automatically on first start.
   Ports 80 and 443 must be reachable from the internet.

## 3. Configuration

```bash
cd /opt/gmc/gmc_feed_master
cp .env.prod.example .env
cp .deploy.env.example .deploy.env
vi .env          # replace every CHANGE_ME value
vi .deploy.env   # set IMAGE_TAG to the tag to deploy
```

- `.env` holds all secrets and runtime config. It is gitignored — never commit
  it. It is unchanged across deploys and rollbacks.
- `.deploy.env` contains only `IMAGE_TAG` and is the only file changed on
  rollback.
- `DATABASE_URL` must use the compose service host `postgres` and the same
  credentials as `POSTGRES_*`. The backend converts it to the asyncpg driver.
- `PUBLIC_BASE_URL` must be the public HTTPS URL (export links and the `Secure`
  session cookie depend on it).
- `REDIS_HOST=redis` enables the Redis AI cache; remove it to fall back to the
  disk cache.

## 4. First deploy

```bash
cd /opt/gmc/gmc_feed_master
set -a && . ./.deploy.env && set +a
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

The backend entrypoint applies pending migrations (`alembic upgrade head`)
before starting uvicorn. On first start the initial admin user is seeded from
`INITIAL_USERNAME`/`INITIAL_PASSWORD` when the users table is empty.

Verify:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 backend caddy
curl -fsS "https://$DOMAIN/health"
```

The backend must run with exactly one worker and one replica; do not scale it.

## 5. Release flow

See `docs/release_process.md`. In short: push a `v*` tag, wait for the Release
workflow to push both images to GHCR, then on the VPS run `git pull` and the
`prod-pull`/`prod-up` commands from §4 with the new `IMAGE_TAG`.

## 6. Rollback

1. Set `IMAGE_TAG` in `.deploy.env` to the previous tag.
2. Re-run the §4 pull/up commands.

`.env` is not touched. A brief restart is expected; there is no zero-downtime
or blue-green setup.

## 7. Running without Caddy

Use the same compose file with Caddy scaled to zero, and point an external
reverse proxy at the published loopback ports:

```bash
docker compose -f docker-compose.prod.yml up -d --scale caddy=0
```

The external proxy must implement the same routing:

| Path | Target |
|---|---|
| `/auth/*`, `/health`, `/admin/*`, `/clients/*`, `/feed-sources/*`, `/dashboard/*`, `/plugins/*`, `/registry/*`, `/export/*`, `/chat`, `/logs/*` | `127.0.0.1:${BACKEND_PORT:-8000}` |
| everything else | `127.0.0.1:${FRONTEND_PORT:-8080}` |

If the proxy runs on another host, set `BACKEND_BIND`/`FRONTEND_BIND` to the
host interface and firewall accordingly.

## 8. Backups and restore

The `backup` service runs `pg_dump` daily and writes gzipped SQL under
`./backups/{last,daily,weekly,monthly}/`. Retention is the last 7 daily backups
(`BACKUP_KEEP_DAYS=7`, weekly/monthly disabled).

Restore into the running Postgres:

```bash
cd /opt/gmc/gmc_feed_master
set -a && . ./.env && set +a
gunzip -c backups/daily/<db>-latest.sql.gz | \
  docker compose -f docker-compose.prod.yml \
    exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

Redis is a cache and is not backed up.

## 9. Operations

- Status: `docker compose -f docker-compose.prod.yml ps`
- Logs: `docker compose -f docker-compose.prod.yml logs -f backend caddy`
- Restart one service: `docker compose -f docker-compose.prod.yml restart backend`
- Never scale the backend (in-process scheduler and run lock).
- `redis` is cache-only, bounded by `REDIS_MAXMEMORY` with `allkeys-lru`.
- Postgres and Redis are not published to the host.
````

- [ ] **Step 2: Sanity-check referenced files exist**

Run (note: `docs/release_process.md` is created in Task 7, so it is checked there):
```bash
for f in docker-compose.prod.yml .env.prod.example .deploy.env.example Caddyfile .github/workflows/release.yml; do test -e "$f" || echo "MISSING $f"; done; echo CHECK_DONE
```
Expected: only `CHECK_DONE` (no `MISSING`).

- [ ] **Step 3: Commit**

```bash
git add docs/prod_deployment.md
git commit -m "docs: add production deployment guide"
```

---

### Task 7: `docs/release_process.md`

**Files:**
- Create: `docs/release_process.md`

**Interfaces:**
- Consumes: the command contract from Tasks 3–6.
- Produces: the short runbook pointed to by `docs/prod_deployment.md` and `AGENTS.md`.

- [ ] **Step 1: Write the runbook**

Create `docs/release_process.md` with exactly this content:

````markdown
# Release & Deployment Runbook

Short, copy-paste steps for cutting a release and deploying it. First-time VPS
setup, backups, and no-Caddy mode are in `docs/prod_deployment.md`.

## 1. Cut a release

Ensure `main` is green, then create and push a version tag:

```bash
git checkout main && git pull
git tag v1.2.0
git push origin v1.2.0
```

Creating a GitHub Release with a `v*` tag also works. Only `v*` tags trigger
`.github/workflows/release.yml`, which builds both images and pushes them to
GHCR as `:v1.2.0` and `:latest`. The workflow does **not** deploy.

Wait for the Release workflow to finish successfully in the Actions tab.

## 2. Deploy on the VPS

```bash
cd /opt/gmc/gmc_feed_master
git pull
vi .deploy.env            # IMAGE_TAG=v1.2.0
set -a && . ./.deploy.env && set +a
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

(`make prod-pull` and `make prod-up` run the same commands with `.deploy.env`
sourced.)

## 3. Verify

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 backend caddy
curl -fsS "https://$DOMAIN/health"
```

## 4. Roll back

```bash
vi .deploy.env            # IMAGE_TAG=<previous tag>
set -a && . ./.deploy.env && set +a
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

`.env` is never changed during a rollback.

## 5. Troubleshooting

- **Images will not pull**: the GHCR PAT expired or lacks `read:packages`, or
  `docker login ghcr.io` was never run on the VPS.
- **Backend unhealthy / container exits**: check
  `docker compose -f docker-compose.prod.yml logs backend`; a failed migration
  or unreachable Postgres stops startup.
- **TLS not provisioning**: DNS A record missing/wrong, or ports 80/443 blocked
  by the firewall.
- **Login does not stick**: `DOMAIN`/`PUBLIC_BASE_URL` must match the HTTPS URL
  so the `Secure` session cookie is set.
````

- [ ] **Step 2: Cross-check command consistency**

Run:
```bash
grep -c 'docker compose -f docker-compose.prod.yml' docs/release_process.md docs/prod_deployment.md
```
Expected: a non-zero count for each file (both documents use the same command form).

- [ ] **Step 3: Commit**

```bash
git add docs/release_process.md
git commit -m "docs: add release and deployment runbook"
```

---

### Task 8: Agent instructions and decision records

**Files:**
- Modify: `AGENTS.md` (deployment section + doc map)
- Modify: `coding-agent-instructions.md` (deployment workflow section)
- Create: `docs/decisions/0013-production-deployment.md`
- Modify: `docs/decisions.md` (dated entry)

**Interfaces:**
- Consumes: the conventions defined in the spec and Tasks 1–7.
- Produces: durable agent-facing rules so future changes respect the conventions.

- [ ] **Step 1: Add a deployment section to `AGENTS.md`**

In `AGENTS.md`, insert after the `**Plugin development:**` code block and before the `## Boundaries` heading:

```markdown
## Production deployment

Images are built from Git tags by `.github/workflows/release.yml` (tag `v*` only)
and pushed to GHCR as `ghcr.io/ozon/gmc-feed-backend` and
`ghcr.io/ozon/gmc-feed-frontend` (both `:<tag>` and `:latest`). There is no
auto-deploy: on the VPS, `IMAGE_TAG` in `.deploy.env` is set and the stack is
updated with `docker compose -f docker-compose.prod.yml pull && up -d` (secrets
in `.env` stay untouched). Backend runs exactly one worker/replica. Full guide:
`docs/prod_deployment.md`; runbook: `docs/release_process.md`.
```

- [ ] **Step 2: Add the new docs to the `AGENTS.md` documentation map**

Append to the `## Documentation map` list in `AGENTS.md`:

```markdown
- `docs/prod_deployment.md` — VPS provisioning, domain/TLS, deploy, rollback, backups
- `docs/release_process.md` — short release/deploy runbook (tag → GHCR → pull/up)
```

- [ ] **Step 3: Add a deployment workflow section to `coding-agent-instructions.md`**

In `coding-agent-instructions.md`, insert before the `## 7. Non-negotiables (will be verified)` heading:

```markdown
## 6a. Production deployment workflow (added 2026-09-18)

- Releases are cut by pushing a `v*` Git tag. `.github/workflows/release.yml`
  builds the backend and frontend images and pushes both to GHCR (tag +
  `latest`). It never deploys.
- Deploy and rollback are manual on the VPS and must not be automated:
  `IMAGE_TAG` in `.deploy.env` selects the image tag; secrets live only in
  `.env` and are never changed by a deploy or rollback.
- Production backend runs exactly one uvicorn worker and one replica. Never
  introduce a design that requires horizontal scaling of the backend.
- See `docs/prod_deployment.md` (reference) and `docs/release_process.md`
  (runbook).
```

- [ ] **Step 4: Create the ADR**

Create `docs/decisions/0013-production-deployment.md` with exactly this content:

```markdown
# 0013: Production container deployment

## Status
Accepted (2026-09-18)

## Context
Production had no images, registry, release pipeline, or documented
deploy/rollback/backup procedure. The VPS is a single host with no staging.
The backend cannot be horizontally scaled: APScheduler and the per-feed-source
lock registry are in-process. The frontend build imports plugin code from
`plugins/`, so its build context cannot be `frontend/` alone.

## Decision
- One `docker-compose.prod.yml` stack: `postgres`, `redis`, `backend`,
  `frontend`, `caddy`, `backup`, on one private network.
- Two multi-stage images built from the repo root, stored privately in GHCR as
  `ghcr.io/ozon/gmc-feed-backend` and `ghcr.io/ozon/gmc-feed-frontend`,
  multi-arch (`amd64`, `arm64`).
- `caddy:2-alpine` is the edge (TLS + API/SPA routing); the frontend is a static
  nginx SPA. No-Caddy mode scales Caddy to zero and relies on an external proxy.
- Releases are tag-triggered (`v*`) and build/push only. Deploy/rollback are
  manual: `IMAGE_TAG` in `.deploy.env`, secrets in `.env`.
- Migrations run in the backend entrypoint before uvicorn.
- Redis (`redis:7-alpine`, `allkeys-lru`, `maxmemory 256mb`) is an always-on AI
  cache; Postgres and Redis are never published to the host.
- Backups use the `prodrigestivill/postgres-backup-local` sidecar, daily, with
  weekly/monthly retention disabled to enforce 7 days.
- `alembic` moves from the dev dependency group to main dependencies so the
  `--no-dev` image can run migrations.

## Consequences
Deploys cause a brief restart (no zero-downtime). Plugin changes require
rebuilding images (frontend imports plugin code; backend ships Python plugins).
Alembic is now a runtime dependency. The operator must authenticate to GHCR once
per VPS and keep `.env`/`.deploy.env` out of git.
```

- [ ] **Step 5: Add a dated entry to `docs/decisions.md`**

Append under the `## 2026-09-18` heading in `docs/decisions.md`:

```markdown
### Production container deployment

**Topic:** Packaging and releasing the production stack.

**Decision:** Production runs `docker-compose.prod.yml` (postgres, redis,
backend, frontend, caddy, backup) from private multi-arch GHCR images
(`ghcr.io/ozon/gmc-feed-backend`, `ghcr.io/ozon/gmc-feed-frontend`) built by a
tag-only (`v*`) GitHub Actions workflow. Deploy/rollback are manual via
`IMAGE_TAG` in `.deploy.env`; secrets stay in `.env`. Migrations run on backend
startup. Redis is an always-on AI cache. Postgres backups run daily with 7-day
retention. `alembic` is now a main dependency.

**Rationale:** Immutable images plus a tag-triggered build give reproducible
releases without an auto-deploy path the operator did not want. A single Compose
file keeps the no-Caddy mode to one `--scale caddy=0` flag. See
`docs/decisions/0013-production-deployment.md` and
`docs/superpowers/specs/2026-09-18-production-container-deployment-design.md`.
```

- [ ] **Step 6: Verify docs and gates**

Run:
```bash
grep -q 'prod_deployment.md' AGENTS.md && grep -q 'release_process.md' AGENTS.md && \
grep -q 'Production deployment workflow' coding-agent-instructions.md && \
test -f docs/decisions/0013-production-deployment.md && echo DOCS_OK
```
Expected: `DOCS_OK`.

- [ ] **Step 7: Commit**

```bash
git add AGENTS.md coding-agent-instructions.md docs/decisions.md docs/decisions/0013-production-deployment.md
git commit -m "docs: record production deployment conventions and decisions"
```

---

### Task 9: Final validation

**Files:** none (verification only).

**Interfaces:**
- Consumes: every artifact from Tasks 1–8.
- Produces: evidence the stack definition, images, workflows, and docs are coherent.

- [ ] **Step 1: Rebuild both images from a clean context**

Run:
```bash
docker build -f backend/Dockerfile -t ghcr.io/ozon/gmc-feed-backend:latest .
docker build -f frontend/Dockerfile -t ghcr.io/ozon/gmc-feed-frontend:latest .
```
Expected: both exit 0.

- [ ] **Step 2: Validate Compose rendering for both modes**

Run:
```bash
POSTGRES_DB=gmc_feed POSTGRES_USER=gmc_feed POSTGRES_PASSWORD=x \
REDIS_PASSWORD=x DOMAIN=localhost IMAGE_TAG=v0.0.1 \
docker compose -f docker-compose.prod.yml config >/dev/null && echo CADDY_MODE_OK

docker compose -f docker-compose.prod.yml config --services | sort
```
Expected: `CADDY_MODE_OK` and the six services `backend`, `backup`, `caddy`, `frontend`, `postgres`, `redis`.

- [ ] **Step 3: Confirm the release workflow is tag-gated and lints**

Run:
```bash
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest .github/workflows/release.yml && echo WORKFLOW_OK
grep -A3 '^on:' .github/workflows/release.yml
```
Expected: `WORKFLOW_OK`; the trigger renders only `on:` → `push:` → `tags:` → `- 'v*'` with no `branches` and no `pull_request`. (Note: `tags:` also appears as the `build-push-action` input, so do not count its occurrences.)

- [ ] **Step 4: Run the existing backend gates for regressions from the dependency move**

Run:
```bash
cd backend && uv run ruff check . ../plugins && uv run mypy . && cd ..
```
Expected: both exit 0 (no code changed; confirms the `alembic` move did not break the environment).

- [ ] **Step 5: Record the validation result**

No commit needed; this task produces no files. If any check fails, fix the owning task's artifact and re-run.

---

## Self-Review

- **Spec coverage:** Topology §1 → Task 3; env contract §2 → Task 3; images §3 → Tasks 1–2; migrations §4 → Task 1; persistence/Redis/backups §5 → Task 3; CI/CD §6 → Task 5; Caddyfile §7 → Task 4; no-Caddy §8 → Tasks 3 + 6; deploy/rollback/verification §9 → Tasks 6–7; files §10 → all tasks; docs §11 → Tasks 6–7; out-of-scope §12 → no task (deliberately unimplemented); risks §13 → noted in Tasks 3/5.
- **Placeholder scan:** no TBD/TODO; every code and config step shows full content.
- **Type/name consistency:** `IMAGE_TAG`, `BACKEND_PORT`/`BACKEND_BIND`, `FRONTEND_PORT`/`FRONTEND_BIND`, `REDIS_MAXMEMORY`, and service names are identical across compose, env templates, Makefile, and docs.
