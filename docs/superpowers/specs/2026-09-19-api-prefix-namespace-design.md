# API Prefix Namespace (`/api`) — Design

Date: 2026-09-19
Status: Approved (brainstorm session)
Builds on: `docs/decisions/0009-basic-rbac.md`, `docs/superpowers/specs/2026-09-08-admin-area-tabs-and-proxy-fix-design.md`

## Goal

Give the FastAPI API and the React SPA non-overlapping URL namespaces so every SPA deep link is refresh- and bookmark-safe, while keeping public SPA URLs unchanged.

## Problem / root cause

The SPA owns browser routes that share prefixes with backend API routes. Both dev and production proxies send those prefixes to the backend, so a hard refresh (or a direct/bookmarked load) of an SPA route returns backend JSON/404 instead of `index.html`:

| SPA route | Also matched by | Dev (Vite) | Prod (Caddy) |
|---|---|---|---|
| `/admin` | Vite `'/admin'` | backend 404 | SPA (Caddy `/admin/*` needs slash) |
| `/admin/users`, `/admin/clients`, `/admin/settings`, `/admin/ai` | `/admin/*` | backend JSON/404 | backend JSON/404 |
| `/logs` | Vite `'/logs'` | backend 404 | SPA (Caddy `/logs/*` needs slash) |
| `/clients/:clientId/feeds/**` | `/clients/*` | backend 404 | backend 404 |
| `/clients/:clientId/plugins/:pluginId` | `/clients/*` | backend 404 | backend 404 |
| `/plugins/:pluginId` | `/plugins/*` | backend 404 | backend 404 |

`frontend/docs/architecture.md:105-121` documents these admin/feed/plugin routes as "refresh-safe and shareable", so this is a supported contract that is currently broken. This is the same class of defect as the earlier bare-`/clients` proxy fix (`v0.2.1`), which addressed one instance of the collision rather than the collision itself.

## Decisions (from brainstorm)

| Question | Decision |
|---|---|
| Primary constraint | Keep public SPA root URLs stable (`/admin/users`, `/clients/...`, `/plugins/...`) |
| Where `/api` lives | Owned by the FastAPI app (prefixed router), not applied only at the proxy |
| Backend test adaptation | Auto-prefixing `app_client` fixture; 613 call sites unchanged |
| Frontend test adaptation | `stubFetch` strips `/api`; only the 4 direct-fetch test files change |
| Public root endpoints | `/export/{token}.xml` (Google Merchant Center) and `/health` stay at root |
| Docs URLs | `/api/docs`, `/api/openapi.json`, `/api/redoc` |

Rejected alternatives: moving the SPA under a basename (changes public URLs); routing by `GET` + `Accept: text/html` (heuristic, no docs backing, edge cases around export downloads); proxy-only prefix (backend would not own the namespace, OpenAPI would misdescribe paths).

## Target URL contract

| Namespace | Owner | Examples |
|---|---|---|
| `/api/**` | FastAPI | `/api/auth/login`, `/api/clients`, `/api/admin/users`, `/api/plugins/{id}/config`, `/api/logs/entries`, `/api/chat` |
| `/export/**` | FastAPI, root (public) | `/export/{token}.xml` |
| `/health` | FastAPI, root | liveness probe |
| `/api/docs`, `/api/openapi.json`, `/api/redoc` | FastAPI docs | interactive API docs |
| everything else | SPA (nginx) | `/`, `/admin/users`, `/clients/:c/feeds/:f/...`, `/plugins/:id`, `/logs`, `/rules` |

Same origin, so no CORS configuration. `PUBLIC_BASE_URL` and the derived `export_url` are unchanged and remain at the public root.

## Design

### 1. Backend (`backend/app/main.py`, `backend/app/config.py`, `backend/app/plugins/discovery.py`)

- Add module constant `API_PREFIX = "/api"` in `app/config.py`.
- `create_app()`:
  - `app = FastAPI(lifespan=lifespan, docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json", redoc_url=f"{API_PREFIX}/redoc")`.
  - Define `api = APIRouter(prefix=API_PREFIX)`.
  - Change the 15 `app.include_router(...)` calls at main.py:255-270 to `api.include_router(...)`, preserving each router's `dependencies=[Depends(enforce_scope_access)]`. `export_public_router` (main.py:259) deliberately stays on `app` (root).
  - Change the five inline auth decorators (`@app.post("/auth/login")` … `@app.post("/auth/interaction")`, main.py:345-462) to `@api.*`. Route bodies are unchanged; the closure read `app.state.clock` at main.py:378 still resolves because the handlers remain defined inside `create_app`.
  - `@app.get("/health")` stays on `app` (root).
  - `app.include_router(api)` at the end of `create_app`, after all `@api.*` decorators are registered (FastAPI snapshots routes at include time).
- `app/plugins/discovery.py:144`: prefix becomes `f"{API_PREFIX}/plugins/{candidate.manifest.id}"`.
- `public_base_url` / `_export_url` (`routes/clients.py:62`) unchanged.

Every existing route body and relative path is unchanged; only the mount prefix moves. OpenAPI paths now carry `/api`.

### 2. Frontend

- `frontend/src/api/client.ts`: add `const API_BASE = '/api'` and `withApiBase(url)` that prefixes site-relative paths only (leading `/`, not already `/api`); absolute (`http(s)://`, protocol-relative) URLs pass through. Apply in `fetchWithContext` and `requestWithHeaders`. Keep the original URL for the `authExempt` check and structured logging.
- `frontend/src/api/hooks.ts`: `useExportVersionContent` keeps `apiGetText` (prefixed API path). `usePublishedExportContent` uses a new `publicGetText(url)` that fetches the absolute `exportUrl` verbatim.
- `frontend/vite.config.ts`: collapse the 11 proxy entries to a single `'/api': { target: apiTarget, changeOrigin: true }`. `VITE_API_TARGET`, HTTPS, and `allowedHosts` are unchanged. In dev the public export URL is absolute (`PUBLIC_BASE_URL` default `http://localhost:8000`), so it needs no proxy.
- No changes to `router.tsx`, SPA routes, or links.

### 3. Proxies & deployment

- `Caddyfile` and `Caddyfile.dev`: replace the API handle list with `handle /api/*` → backend (no `handle_path`; the backend owns the prefix, so nothing is stripped), keep `handle /export/*` and `handle /health` → backend, keep the catch-all `handle` → frontend.
- `docker-compose.prod.yml`: no change. `PUBLIC_BASE_URL` stays the public domain.
- `docs/prod_deployment.md`: routing table becomes `/api/*`, `/export/*`, `/health` → backend; everything else → frontend.

### 4. Tests

- Backend `tests/conftest.py`: `app_client` returns a `TestClient` subclass that prepends `/api` to site-relative requests, skipping `/health`, `/export...`, `/docs`, `/openapi.json`, `/redoc`. The 613 root-relative call sites are unchanged.
- New backend contract test: an unprefixed API path (e.g. `/clients`) does not resolve through the app, while `/api/clients` does.
- Audit backend tests that assert root-level 404s or inspect `app.openapi()` paths; adjust only those.
- Frontend `src/test/fetch.ts`: `stubFetch` strips a leading `/api` before invoking the handler, so the 54 `stubFetch` test files keep root-relative keys. `localeResponse` is untouched (locales are not prefixed).
- Frontend direct-fetch test files updated for the prefix: `api/client.test.ts` (asserts prefix + absolute pass-through), `logging/logger.test.ts`, `features/systemLogs/SystemLogsPage.test.tsx`, `api/hooks.logs.test.tsx`.

### 5. Validation gates

- Backend: `uv run ruff check . ../plugins`, `uv run mypy .`, `MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins`, `uv run pytest`, `uv run alembic check` (no schema change expected).
- Frontend: `npm run lint`, `npm run typecheck`, `npm run test`, `npm run build`.
- `caddy validate` against both Caddyfiles.

### 6. Documentation (same commit)

- `backend/docs/api.md` — endpoints shown as `/api/...`; public root `/export/{token}.xml` and `/health` called out.
- `frontend/docs/architecture.md` — proxy list (line ~246) becomes `/api`; deep-link collision note.
- Root `AGENTS.md` and `backend/AGENTS.md` — reserved plugin routes become `/api/plugins/{id}/config|data`, and the "never use reserved routes" wording is updated.
- `docs/prod_deployment.md` — routing table.
- New `docs/decisions/0012-api-prefix-namespace.md` ADR: collision problem, backend-owned prefix decision, consequences, and rollout note.

## Risks / out of scope

- `API_PREFIX` is a fixed constant, not environment-configurable.
- `PUBLIC_BASE_URL` must remain an absolute URL; `export_url` already depends on this.
- Frontend and backend images must ship together: an old SPA (root API paths) against the new backend 404s, and vice versa. Both images are built from the same tag, so this is a single release; the single-worker deploy has a brief mixed-version window.
- No redirects from old root API paths. Only `/export` and `/health` remain public at root; there are no other external API consumers.
- OpenAPI tooling/bookmarks pointing at `/docs` move to `/api/docs`.
