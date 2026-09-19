# API Prefix Namespace (`/api`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the FastAPI API and the React SPA non-overlapping URL namespaces so SPA deep links are refresh-/bookmark-safe, keeping public SPA URLs unchanged.

**Architecture:** FastAPI owns an `/api` prefix (`APIRouter(prefix=API_PREFIX)`); `/export/{token}.xml` and `/health` stay at the public root. The frontend prefixes every API request with `/api` via one helper; logger direct posts and the public export fetch are handled explicitly. Vite and Caddy proxy only `/api`, `/export`, `/health` to the backend. Test suites adapt at their client-construction choke points.

**Tech Stack:** FastAPI, Starlette TestClient, httpx, SQLAlchemy async, React 19, TypeScript, Vite, Caddy 2.

**Spec:** `docs/superpowers/specs/2026-09-19-api-prefix-namespace-design.md`

## Global Constraints

- `API_PREFIX = "/api"` is a fixed constant; do not make it environment-configurable.
- `/export/{token}.xml` and `/health` remain at the public root; `public_base_url` stays absolute and unchanged.
- Do not change any existing route body or route-relative path; only the mount prefix moves.
- Docs/ADR for behavior, API surface, or commands must be updated in the same commit.
- Backend gates: `uv run ruff check . ../plugins`, `uv run mypy .`, `MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins`, `uv run pytest`, `uv run alembic check`.
- Frontend gates: `npm run lint`, `npm run typecheck`, `npm run test`, `npm run build`.
- No new dependencies.

---

### Task 1: Backend owns the `/api` prefix + backend test adaptation

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/plugins/discovery.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/*.py` (base_url codemod, then exceptions)
- Create: `backend/tests/test_api_prefix.py`

**Interfaces:**
- Produces: `app.config.API_PREFIX: str = "/api"` (imported by `app.main` and `app/plugins/discovery`).
- Produces: all API routes respond under `/api/**`; `/health` and `/export/{token}.xml` stay at root.

- [ ] **Step 1: Add the constant**

In `backend/app/config.py`, after `DEFAULT_EXPORT_DIR` (line 8), add:

```python
API_PREFIX = "/api"
```

- [ ] **Step 2: Write the contract test (test-first)**

Create `backend/tests/test_api_prefix.py`:

```python
from fastapi.testclient import TestClient
from app.main import create_app


def test_api_only_under_prefix(settings, store, clock):
    root = TestClient(
        create_app(settings=settings, session_store=store, clock=clock),
        base_url="https://testserver",
    )
    assert root.get("/clients").status_code == 404
    assert root.get("/health").status_code == 200

    prefixed = TestClient(
        create_app(settings=settings, session_store=store, clock=clock),
        base_url="https://testserver/api",
    )
    assert prefixed.get("/clients").status_code == 401
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_api_prefix.py -v`
Expected: FAIL — `root.get("/clients")` currently returns 401 (route still at root), so the `== 404` assertion fails.

- [ ] **Step 4: Mount the API under the prefix**

In `backend/app/main.py`:

Add `APIRouter` to the FastAPI import (line 9):

```python
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
```

Add `API_PREFIX` to the config import (line 26):

```python
from .config import API_PREFIX, Settings, get_settings
```

Replace `app = FastAPI(lifespan=lifespan)` (line 253) with:

```python
    app = FastAPI(
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=f"{API_PREFIX}/redoc",
    )
    api = APIRouter(prefix=API_PREFIX)
```

Change the router includes (lines 255-270). Every `app.include_router(...)` becomes `api.include_router(...)` except `export_public_router`, which stays on `app`:

```python
    app.add_middleware(RequestContextMiddleware)
    api.include_router(clients_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(dashboard_router)
    api.include_router(dry_run_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(export_history_router, dependencies=[Depends(enforce_scope_access)])
    app.include_router(export_public_router)
    api.include_router(feed_dashboard_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(field_mapping_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(pipeline_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(plugins_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(products_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(quality_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(registry_router, dependencies=[Depends(enforce_scope_access)])
    api.include_router(admin_router)
    api.include_router(ai_admin_router)
    api.include_router(chat_router)
    api.include_router(logs_router)
```

Change the five auth decorators from `@app.` to `@api.` (route bodies unchanged): `@app.post("/auth/login")` (line 345), `@app.post("/auth/logout")` (396), `@app.post("/auth/password")` (423), `@app.get("/auth/me")` (454), `@app.post("/auth/interaction")` (462).

Leave `@app.get("/health")` (line 340) on `app`.

Before `return app` (line 466), add:

```python
    app.include_router(api)
```

(This must be after all `@api.*` decorators — FastAPI snapshots routes at include time.)

- [ ] **Step 5: Prefix plugin routers**

In `backend/app/plugins/discovery.py`, add `API_PREFIX` to the config import (near the top-level imports), then change line 144:

```python
                prefix=f"{API_PREFIX}/plugins/{candidate.manifest.id}",
```

- [ ] **Step 6: Run the contract test**

Run: `uv run pytest tests/test_api_prefix.py -v`
Expected: PASS.

- [ ] **Step 7: Adapt existing test clients**

From `backend/`, run:

```bash
uv run python - <<'PY'
from pathlib import Path
count = 0
for path in Path("tests").rglob("*.py"):
    text = path.read_text()
    if 'base_url="https://testserver"' in text:
        path.write_text(text.replace('base_url="https://testserver"', 'base_url="https://testserver/api"'))
        count += 1
print(f"updated {count} files")
PY
```

Then fix the public-route exceptions (absolute URLs bypass the base_url path):

- `backend/tests/test_request_context.py` lines 24, 27, 30: change `client.get("/health", ...)` to `client.get("https://testserver/health", ...)` (keep each `headers=` argument).
- `backend/tests/test_scheduler_startup.py` line 103: change `resp = await client.get("/health")` to `resp = await client.get("https://testserver/health")`.

Do not touch `backend/tests/test_tooling.py` (its health clients use the default `http://testserver` base_url) or the `http://test.public` export clients.

- [ ] **Step 8: Run the backend suite**

Run: `uv run pytest tests/test_api_prefix.py tests/test_request_context.py tests/test_auth_api.py tests/test_export_public.py -v`
Expected: PASS.

Run: `uv run pytest -x -q`
Expected: whole suite PASS (fix any remaining base_url exception surfaced by failures).

- [ ] **Step 9: Lint, typecheck, migration check**

```bash
uv run ruff check . ../plugins
uv run mypy .
MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins
uv run alembic check
```
Expected: exit 0, no pending migrations.

- [ ] **Step 10: Commit**

```bash
git add backend/app/config.py backend/app/main.py backend/app/plugins/discovery.py backend/tests
git commit -m "feat(api): serve backend routes under /api prefix"
```

---

### Task 2: Frontend API base helper + prefixing + test adaptation

**Files:**
- Create: `frontend/src/api/base.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/logging/logger.ts`
- Modify: `frontend/src/api/hooks.ts`
- Modify: `frontend/src/test/fetch.ts`
- Modify: `frontend/src/api/client.test.ts`
- Modify: `frontend/src/logging/logger.test.ts`
- Modify: `frontend/src/api/hooks.logs.test.tsx`

**Interfaces:**
- Produces: `frontend/src/api/base.ts`: `export const API_BASE = '/api'` and `export function withApiBase(url: string): string`.
- Produces: `frontend/src/api/client.ts`: `export function publicGetText(url: string): Promise<string>` (no prefixing, for the absolute public export URL).
- Consumes: `publicGetText` in `hooks.ts`.

- [ ] **Step 1: Create the base helper**

Create `frontend/src/api/base.ts`:

```ts
export const API_BASE = '/api';

export function withApiBase(url: string): string {
  if (!url.startsWith('/') || url.startsWith('//')) return url;
  if (url === API_BASE || url.startsWith(`${API_BASE}/`)) return url;
  return `${API_BASE}${url}`;
}
```

- [ ] **Step 2: Write the failing client test**

In `frontend/src/api/client.test.ts`, update the existing URL assertions to the prefixed form and add a pass-through test. Change line 34-37 to:

```ts
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/auth/me',
      expect.objectContaining({ credentials: 'include' }),
    );
```

Add inside `describe('apiGetText', ...)`:

```ts
  it('does not prefix absolute URLs', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<xml/>', { status: 200 }));
    await publicGetText('https://test.public/export/tok.xml');
    expect(fetchMock).toHaveBeenCalledWith('https://test.public/export/tok.xml', expect.anything());
  });
```

Add `publicGetText` to the import list at the top of the file.

- [ ] **Step 3: Run it to verify it fails**

Run: `npm run test -- --run src/api/client.test.ts`
Expected: FAIL — `withApiBase`/`publicGetText` do not exist yet and `/auth/me` is not prefixed.

- [ ] **Step 4: Implement the client changes**

In `frontend/src/api/client.ts`:

Add the import at the top:

```ts
import { withApiBase } from './base';
```

In `fetchWithContext` (line 59), change the `fetch` call to use the prefixed target:

```ts
  const response = await fetch(withApiBase(url), {
    ...init,
    credentials: 'include',
    headers,
  });
```

Apply the same change in `requestWithHeaders` (line 103). Leave the `authExempt` checks and the logger calls using the original `url`.

Add `publicGetText` after `apiGetText`:

```ts
export async function publicGetText(url: string): Promise<string> {
  const response = await fetch(url, { credentials: 'include' });
  if (!response.ok) throw await parseError(response);
  return response.text();
}
```

- [ ] **Step 5: Prefix the logger's direct posts**

In `frontend/src/logging/logger.ts`, add:

```ts
import { withApiBase } from '../api/base';
```

Change `/logs/client` in the `sendBeacon` call (line 72) and the `fetch` fallback (line 80) to `withApiBase('/logs/client')`.

- [ ] **Step 6: Use `publicGetText` for the published export**

In `frontend/src/api/hooks.ts`, add `publicGetText` to the `./client` import, and change the `usePublishedExportContent` query function (line 674) to:

```ts
    queryFn: () => publicGetText(exportUrl),
```

- [ ] **Step 7: Make `stubFetch` prefix-agnostic**

In `frontend/src/test/fetch.ts`, change `stubFetch` so handlers keep receiving root-relative paths:

```ts
export function stubFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
    async (url, init) => {
      const locale = localeResponse(url);
      if (locale) return locale;
      const stripped = url.startsWith('/api/') ? url.slice(4) : url;
      return handler(stripped, init);
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
```

- [ ] **Step 8: Update the remaining direct-fetch assertions**

- `frontend/src/logging/logger.test.ts` lines 31 and 48: `expect(url).toBe('/logs/client')` → `expect(url).toBe('/api/logs/client')`.
- `frontend/src/api/hooks.logs.test.tsx` line 24: `'/logs/entries?category=audit&q=login'` → `'/api/logs/entries?category=audit&q=login'`.
- `frontend/src/features/systemLogs/SystemLogsPage.test.tsx` needs no change (its mock is `mockResolvedValueOnce`, not URL-keyed).

- [ ] **Step 9: Run the frontend gates**

```bash
npm run test
npm run lint
npm run typecheck
npm run build
```
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add frontend/src
git commit -m "feat(api): prefix frontend API requests with /api"
```

---

### Task 3: Vite + Caddy proxy to /api

**Files:**
- Modify: `frontend/vite.config.ts`
- Modify: `Caddyfile`
- Modify: `Caddyfile.dev`
- Modify: `docs/prod_deployment.md`

**Interfaces:**
- Consumes: backend serving under `/api`, `/export`, `/health` (Task 1).

- [ ] **Step 1: Collapse the Vite proxy**

In `frontend/vite.config.ts`, replace the entire `proxy` object (lines 49-94) with:

```ts
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
```

- [ ] **Step 2: Simplify the Caddyfiles**

In `Caddyfile`, replace every `handle` block above the final catch-all `handle {` (currently the `/admin/*`, `/auth/*`, `/health`, `/clients`, `/clients/*`, `/feed-sources/*`, `/dashboard/*`, `/plugins`, `/plugins/*`, `/registry/*`, `/export/*`, `/chat`, and `/logs/*` blocks) with:

```caddyfile
	handle /api/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
	handle /export/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
	handle /health {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
```

Do the same in `Caddyfile.dev`, using `reverse_proxy http://127.0.0.1:8000`.

- [ ] **Step 3: Validate both Caddyfiles**

Run:

```bash
docker run --rm --network none -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker run --rm --network none -v "$PWD/Caddyfile.dev:/etc/caddy/Caddyfile:ro" caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```
Expected: `Valid configuration` for both.

- [ ] **Step 4: Update the deployment routing table**

In `docs/prod_deployment.md`, replace the backend routing row (line 119) with:

```markdown
| `/api/*`, `/export/*`, `/health` | `127.0.0.1:${BACKEND_PORT:-8000}` |
```

- [ ] **Step 5: Rebuild frontend to prove the proxy typechecks**

Run: `npm run build` (from `frontend/`)
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/vite.config.ts Caddyfile Caddyfile.dev docs/prod_deployment.md
git commit -m "chore(proxy): route /api, /export and /health to the backend"
```

---

### Task 4: Documentation + ADR

**Files:**
- Modify: `backend/docs/api.md`
- Modify: `frontend/docs/architecture.md`
- Modify: `AGENTS.md`
- Create: `docs/decisions/0014-api-prefix-namespace.md`

- [ ] **Step 1: Update the API reference**

In `backend/docs/api.md`, prefix every backend endpoint path with `/api` (e.g. `/clients` → `/api/clients`, `/admin/users` → `/api/admin/users`, `/auth/login` → `/api/auth/login`, `/logs/entries` → `/api/logs/entries`), except:
- `/health` and `/export/{token}.xml`, which stay at the root.
- The `GET /clients` in the enforcement matrix table, which becomes `/api/clients`.

Add one line under `## Authentication`:

```markdown
All backend routes are served under the `/api` prefix, except the public root `GET /health` and `GET /export/{token}.xml`. Interactive docs are at `/api/docs`.
```

- [ ] **Step 2: Update the frontend architecture proxy note**

In `frontend/docs/architecture.md`, replace the two proxy bullets (lines 246-247) with:

```markdown
- Vite proxies `/api` to `VITE_API_TARGET` (default `http://127.0.0.1:8000`; set it in `.env` to match a backend on another port) — the production Caddyfiles proxy the same `/api` prefix, plus the public root `/export/*` and `/health`.
- The `/api` prefix keeps the backend namespace disjoint from SPA routes, so `/admin/users`, `/clients/:c/feeds/:f/...`, and `/plugins/:id` are refresh- and bookmark-safe (they no longer collide with API prefixes).
```

- [ ] **Step 3: Update the reserved-route wording**

In `AGENTS.md` line 66, change to:

```markdown
- Use reserved plugin routes `/api/plugins/{id}/config` or `/api/plugins/{id}/data`
```

`backend/AGENTS.md` line 123 is only a docs-map label ("reserved plugin routes") and needs no change.

- [ ] **Step 4: Write the ADR**

Create `docs/decisions/0014-api-prefix-namespace.md`:

```markdown
# ADR-0014: Backend-Owned `/api` Namespace

## Status
Accepted

## Context
The SPA browser routes (`/admin/users`, `/clients/:clientId/feeds/:feedSourceId`, `/plugins/:pluginId`) share prefixes with backend API routes. Both the Vite dev proxy and Caddy routed those prefixes to the backend, so a hard refresh or a bookmarked SPA deep link returned backend JSON/404 instead of the SPA. `frontend/docs/architecture.md` documents these routes as refresh-safe, so the collision was a defect, not a design choice.

## Decision
Give the FastAPI app an `/api` prefix (`APIRouter(prefix="/api")`, constant `app.config.API_PREFIX`). The frontend prefixes every API request with `/api` through `src/api/base.ts`. Proxies route only `/api/*`, `/export/*`, and `/health` to the backend; the SPA owns everything else. The public export feed (`/export/{token}.xml`, consumed by Google Merchant Center) and `/health` deliberately stay at the public root, so `PUBLIC_BASE_URL`/`export_url` are unchanged. Interactive docs move to `/api/docs`.

## Consequences
- SPA deep links no longer collide with the API namespace; no Accept-header or heuristics needed.
- Backend tests adapt by pointing the httpx `base_url` at `/api/...`; route-relative call sites are unchanged.
- Frontend and backend images must ship together (an old SPA calling root paths 404s). They are built from the same release tag.
- `API_PREFIX` is a fixed constant, not environment-configurable.

## Alternatives rejected
- SPA basename (`/app`): changes every user-facing URL.
- `GET` + `Accept: text/html` routing: heuristic, undocumented, breaks export downloads.
- Proxy-only prefix: the app would not own the namespace and OpenAPI would misdescribe paths.
```

- [ ] **Step 5: Commit**

```bash
git add backend/docs/api.md frontend/docs/architecture.md AGENTS.md docs/decisions/0014-api-prefix-namespace.md
git commit -m "docs: document the /api namespace split"
```

---

### Task 5: End-to-end verification

- [ ] **Step 1: Backend full gates**

From `backend/`:

```bash
uv run ruff check . ../plugins
uv run mypy .
MYPYPATH=../plugins uv run mypy --explicit-package-bases ../plugins
uv run alembic check
uv run pytest
```
Expected: exit 0, coverage floor 85 satisfied.

- [ ] **Step 2: Frontend full gates**

From `frontend/`:

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```
Expected: exit 0.

- [ ] **Step 3: Manual smoke (dev)**

Start the backend and Vite dev server, log in, then verify:
- `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health` → `200`
- `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/clients` → `404`
- `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/auth/me` → `401`
- In the browser, load `/admin/users`, `/admin/clients`, `/clients/1/feeds/1`, and `/plugins/design` directly (hard refresh) and confirm the SPA renders (no backend JSON/404).

- [ ] **Step 4: Report**

Summarize gate output and the smoke results. Do not commit (no file changes in this task).
