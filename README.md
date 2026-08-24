# gmc_feed_master

## Local operation (M0)

Copy the local-only environment values, start PostgreSQL, then run the backend
and frontend in separate terminals:

```bash
cp .env.example .env
docker compose up -d postgres
cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
cd frontend && npm run dev
```

The Vite development server proxies `/auth/*` and `/health` to the backend on
`127.0.0.1:8000`, so the documented frontend uses the same-origin API boundary
without requiring CORS configuration.

M0's session cookie is `HttpOnly`, `Secure`, and `SameSite=Lax`. Because it is
`Secure`, local browser operation requires an HTTPS-capable local setup (for
example, a local TLS reverse proxy). Run the backend with exactly one worker:
the M0 in-process session store is not shared between workers, and all
sessions are invalidated when the backend process restarts.

PostgreSQL is available in the local Compose setup, but M0 does not persist
sessions there. M1 is the named milestone for PostgreSQL session persistence
and password-change invalidation.
