# gmc_feed_master

## Local operation (M0)

Copy the local-only environment values and start PostgreSQL:

```bash
cp .env.example .env
docker compose up -d postgres
```

Apply or remove the M1 PostgreSQL schema explicitly from `backend/`:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed \
  uv run alembic upgrade head
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed \
  uv run alembic downgrade base
```

`alembic upgrade head` is the required migration step for a new database. After
migrations, application startup explicitly seeds the first configured user only
when the `users` table is empty; it never mutates the schema or overwrites an
existing user.
Application startup does not call `create_all`; schema changes must be made by
the Alembic CLI. For migration tests, set `TEST_DATABASE_URL` to a PostgreSQL
`postgresql+asyncpg://` URL; tests intentionally fail if it is absent or points
to a non-PostgreSQL backend.

Generate a local self-signed certificate and key for Vite:

```bash
mkdir -p local-certs
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout local-certs/localhost-key.pem \
  -out local-certs/localhost-cert.pem \
  -days 365 \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
cat > .env.local <<'EOF'
VITE_HTTPS_CERT=local-certs/localhost-cert.pem
VITE_HTTPS_KEY=local-certs/localhost-key.pem
EOF
```

Run the backend and frontend in separate terminals. Keep the backend on HTTP;
Vite terminates local HTTPS and proxies the API requests to it:

```bash
# Terminal 1
cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
# Terminal 2
cd frontend && npm run dev
```

The Vite development server proxies `/auth/*` and `/health` to the backend at
`http://127.0.0.1:8000`, so the documented frontend uses the same-origin API boundary
without requiring CORS configuration. With both `VITE_HTTPS_CERT` and
`VITE_HTTPS_KEY` set, open `https://localhost:5173` in the browser. If neither
variable is set, Vite retains normal HTTP behavior. The variables must be
provided as a pair; a partial TLS configuration fails fast.

M0's session cookie is `HttpOnly`, `Secure`, and `SameSite=Lax`. Because it is
`Secure`, local browser operation requires the HTTPS setup above. Run the
backend with exactly one worker:
the M0 in-process session store is not shared between workers, and all
sessions are invalidated when the backend process restarts.

PostgreSQL is available in the local Compose setup, but M0 does not persist
sessions there. M1 is the named milestone for PostgreSQL session persistence
and password-change invalidation.
