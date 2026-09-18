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
