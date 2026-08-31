# Caddy Production Deployment Design

## Problem

Dev workflow is simple (Vite + FastAPI + PostgreSQL). Production needs Caddy as a reverse proxy for TLS termination, frontend static serving, and API routing. We need a production Caddy config that doesn't complicate the dev setup.

## Decision

**Standalone Caddyfile** at project root. Caddy runs externally. Zero changes to existing dev tooling.

## What Changes

### New file: `Caddyfile`

```caddyfile
{$DOMAIN:localhost} {
    handle /auth/* {
        reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
    }
    handle /health {
        reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
    }
    handle /clients/* {
        reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
    }
    handle /feed-sources/* {
        reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
    }
    handle /dashboard/* {
        reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
    }
    handle /plugins/* {
        reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
    }
    handle /registry/* {
        reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
    }
    handle /export/* {
        reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
    }

    handle {
        root * /path/to/frontend/dist
        try_files {path} /index.html
        file_server
    }
}
```

### Updated file: `.env.example`

Add `PUBLIC_BASE_URL` for production:

```
# Production: set to your public URL (https://gmc.example.com)
# PUBLIC_BASE_URL=https://gmc.example.com
```

## Key Decisions

1. **Environment variables**: `DOMAIN` and `BACKEND_URL` with sensible defaults. No hardcoded hostnames.
2. **SPA routing**: `try_files {path} /index.html` for React Router client-side routes.
3. **API routing**: Each API prefix gets its own `handle` block (matches Vite's proxy config).
4. **TLS**: Caddy auto-provisions Let's Encrypt certs for real domains. localhost falls back to self-signed.
5. **Export endpoint**: `/export/*` goes to backend — Google fetches XML directly.

## What Does NOT Change

- `docker-compose.yml` — untouched
- `vite.config.ts` — untouched
- `Makefile` — untouched
- Dev workflow — completely unchanged

## Production Usage

```bash
# With real domain (auto-TLS):
DOMAIN=gmc.example.com BACKEND_URL=http://127.0.0.1:8000 caddy run --config Caddyfile

# Or with env file:
caddy run --config Caddyfile --adapter caddyfile
```

## API Route Mapping

| Path | Target | Notes |
|------|--------|-------|
| `/auth/*` | Backend | Login, logout, password, session |
| `/health` | Backend | Health check |
| `/clients/*` | Backend | Client + feed source CRUD |
| `/feed-sources/*` | Backend | Feed source operations |
| `/dashboard/*` | Backend | Dashboard data |
| `/plugins/*` | Backend | Plugin management |
| `/registry/*` | Backend | Attribute registry |
| `/export/*` | Backend | Public XML feed (Google fetches) |
| Everything else | Frontend | React SPA static files |

## Scope

Single implementation: Caddyfile + .env.example update. No Docker changes, no compose changes, no frontend changes.
