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
| `/auth/*`, `/health`, `/admin/*`, `/clients`, `/clients/*`, `/feed-sources/*`, `/dashboard/*`, `/plugins`, `/plugins/*`, `/registry/*`, `/export/*`, `/chat`, `/logs/*` | `127.0.0.1:${BACKEND_PORT:-8000}` |
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
