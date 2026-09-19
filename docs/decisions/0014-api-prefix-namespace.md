# ADR-0014: Backend-Owned `/api` Namespace

## Status
Accepted

## Context
The SPA browser routes (`/admin/users`, `/clients/:clientId/feeds/:feedSourceId`, `/plugins/:pluginId`) shared prefixes with backend API routes. Both the Vite dev proxy and Caddy routed those prefixes to the backend, so a hard refresh or a bookmarked SPA deep link returned backend JSON/404 instead of the SPA. `frontend/docs/architecture.md` documents these routes as refresh-safe, so the collision was a defect, not a design choice. An earlier fix (v0.2.1) patched one instance (bare `/clients`) without removing the collision.

## Decision
Give the FastAPI app an `/api` prefix (`APIRouter(prefix="/api")`, constant `app.config.API_PREFIX`). The frontend prefixes every API request with `/api` through `src/api/base.ts`; `logger.ts`'s direct posts use the same helper, and the published-export fetch uses a non-prefixing `publicGetText`. Proxies route only `/api/*`, `/export/*`, and `/health` to the backend; the SPA owns everything else. The public export feed (`/export/{token}.xml`, consumed by Google Merchant Center) and `/health` deliberately stay at the public root, so `PUBLIC_BASE_URL`/`export_url` are unchanged. Interactive docs move to `/api/docs`.

## Consequences
- SPA deep links no longer collide with the API namespace; no Accept-header or other heuristics needed.
- Backend tests adapt by pointing the httpx `base_url` at `/api/...`; route-relative call sites are unchanged. Plugin route tests mount their routers at `/api/plugins/{id}`. Public-root tests (`/health`, `/export/...`) use absolute URLs.
- Frontend tests keep root-relative fetch-mock keys: `stubFetch` strips the `/api` prefix from both the handler input and the recorded call URL.
- Frontend and backend images must ship together (an old SPA calling root paths 404s). They are built from the same release tag.
- `API_PREFIX` is a fixed constant, not environment-configurable.

## Alternatives rejected
- SPA basename (`/app`): changes every user-facing URL.
- `GET` + `Accept: text/html` routing: heuristic, undocumented, breaks export downloads.
- Proxy-only prefix: the app would not own the namespace and OpenAPI would misdescribe paths.
