# Whole-Branch Review Fix Report

## Status

Implemented the four Important whole-branch review fixes in one coordinated
fix wave.

## Files changed

- `backend/app/config.py` — resolves `.env` from the repository root, so the
  documented root-level copy is loaded when Uvicorn is started from `backend/`.
  Import safety and FastAPI dependency overrides remain unchanged.
- `backend/tests/test_config.py` — regression coverage for root `.env` loading
  from a `backend/` working directory.
- `frontend/vite.config.ts` — proxies `/auth` and `/health` to the backend at
  `127.0.0.1:8000`.
- `frontend/src/App.tsx` — clears authenticated state and returns to login for
  `401` responses from authenticated sign-out and interaction requests.
- `frontend/src/App.test.tsx` — regression coverage for interaction expiry.
- `backend/tests/test_environment_docs.py` — static assertions for Vite proxy
  wiring and CI PostgreSQL lifecycle commands.
- `.github/workflows/ci.yml` — starts the committed PostgreSQL Compose service,
  waits for health, runs backend checks, and always cleans up the service and
  volume. The separate Compose-only validation job was removed.
- `README.md` — documents the same-origin Vite proxy boundary.

## Verification commands and output

### Backend full tests and compileall

```text
cd /home/ozon/gmc_feed_master/.worktrees/m0-foundation/backend && uv run pytest -q && uv run python -m compileall app
...................................                                      [100%]
35 passed, 1 warning in 0.96s
Listing 'app'...
```

The warning is the existing Starlette/httpx deprecation warning recommending
`httpx2`.

### Frontend tests, typecheck, and build

```text
cd /home/ozon/gmc_feed_master/.worktrees/m0-foundation/frontend && npm test -- --run && npm run typecheck && npm run build
Test Files  1 passed (1)
Tests       8 passed (8)
tsc -b
vite v8.2.2 building client environment for production...
✓ built in 179ms
```

### Compose configuration

```text
cd /home/ozon/gmc_feed_master/.worktrees/m0-foundation && docker compose config -q
(no output; exit 0)
```

### PostgreSQL health check

```text
cd /home/ozon/gmc_feed_master/.worktrees/m0-foundation && docker compose up -d --wait postgres && docker compose ps && docker compose down --volumes
Container m0-foundation-postgres-1 Healthy
m0-foundation-postgres-1   postgres:16.4-alpine   ...   Up 5 seconds (healthy)
container, volume, and network removed without errors.
```

### Diff whitespace check

```text
cd /home/ozon/gmc_feed_master/.worktrees/m0-foundation && git diff --check
(no output; exit 0)
```

## Residual concerns

- Backend tests retain one pre-existing Starlette/httpx deprecation warning.
- M0 still uses the documented in-process session store and therefore requires
  one backend worker; PostgreSQL remains only the containerized development/CI
  service until M1 persistence work.
- The `Secure` cookie still requires an HTTPS-capable local browser setup, as
  documented.

## Final-review Important issue: optional local HTTPS

### Status

Resolved the documented local-login incompatibility without weakening the
mandatory `Secure` cookie design. Vite now enables HTTPS only when both
certificate and key paths are provided, while its normal HTTP mode remains
unchanged when neither is present. Partial TLS configuration fails fast.

### Files changed

- `frontend/vite.config.ts` — loads root `.env.local` values with Vite's
  `loadEnv`, validates `VITE_HTTPS_CERT`/`VITE_HTTPS_KEY` as a pair, reads the
  configured certificate and key into `server.https`, and retains the HTTP
  `/auth` and `/health` proxy targets.
- `frontend/package.json` and `frontend/package-lock.json` — add the Node type
  definitions required to typecheck the Node APIs used by the Vite config.
- `frontend/tsconfig.node.json` — enables the Node type definitions for the
  Vite config typecheck.
- `backend/tests/test_environment_docs.py` — adds static assertions for the
  HTTPS environment names, pair validation, Vite HTTPS configuration, and the
  documented local URLs and OpenSSL command.
- `README.md` — documents exact OpenSSL certificate generation, root
  `.env.local` values, separate backend/frontend commands, HTTPS URL, HTTP
  backend proxy boundary, and partial-variable behavior.
- `.gitignore` — ignores `.env.local` and generated `local-certs/` files.

### Verification commands and output

```text
cd /home/ozon/gmc_feed_master/.worktrees/m0-foundation/frontend && npm ci
added 118 packages, and audited 119 packages in 3s
found 0 vulnerabilities

cd /home/ozon/gmc_feed_master/.worktrees/m0-foundation/frontend && npm test -- --run && npm run typecheck && npm run build
Test Files  1 passed (1)
Tests       8 passed (8)
tsc -b
vite v8.2.2 building client environment for production...
✓ built in 164ms

cd /home/ozon/gmc_feed_master/.worktrees/m0-foundation/backend && uv run pytest -q && uv run python -m compileall app
36 passed, 1 warning in 0.97s
Listing 'app'...

cd /home/ozon/gmc_feed_master/.worktrees/m0-foundation && docker compose config -q
(no output; exit 0)

cd /home/ozon/gmc_feed_master/.worktrees/m0-foundation && git diff --check
(no output; exit 0)
```

The one backend warning is the pre-existing Starlette/httpx deprecation
warning recommending `httpx2`; it does not fail the suite.

### Concerns

- The generated certificate is self-signed; the browser's local certificate
  warning must be accepted, or the certificate must otherwise be trusted
  locally.
- Vite resolves the documented certificate paths relative to the repository
  root. The backend remains HTTP on `127.0.0.1:8000` behind the Vite HTTPS
  proxy, as required.
