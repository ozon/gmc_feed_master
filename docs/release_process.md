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
