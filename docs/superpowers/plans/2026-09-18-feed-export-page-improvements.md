# Feed Export Page Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-version XML preview + download, an admin-editable export token, and a redesigned human-readable version diff to the Export page.

**Architecture:** Frontend-heavy. The backend gains exactly two routes — an authenticated version-content reader and an admin-only token setter. Everything else (XML highlighting, truncation, download blob, diff summary/field-breakdown/findings-delta, URL-query state) is frontend code over existing APIs.

**Tech Stack:** FastAPI + SQLAlchemy async (backend); React 19 + TypeScript + Mantine + TanStack Query + vitest (frontend). No new dependencies. No DB migration.

## Global Constraints

- **No new dependencies** (backend `pyproject.toml` or frontend `package.json`) and **no DB migration**.
- Custom export token charset is exactly `^[A-Za-z0-9_~-]+$`, length 1–64 (`.` rejected because the public route is `/export/{token}.xml`).
- Preview cap: **5,000 lines**.
- Do not change `ExportVersionOut.source` (`'scheduled' | 'manual' | 'rollback'`).
- Docs affected by a behavior/API change are updated **in the same commit** (spec §Docs).
- Backend gates: `uv run ruff check . ../plugins`, `uv run mypy .`, `uv run pytest` (all from `backend/`).
- Frontend gates: `npm run test`, `npm run typecheck`, `npm run lint`, `npm run format:check` (all from `frontend/`).
- Backend logging uses lazy `%s` interpolation; no bare `print`.

---

### Task 1: Backend — version content endpoint

**Files:**
- Modify: `backend/app/export/service.py` (add `version_content` after `_load_version_products`, around line 265)
- Modify: `backend/app/routes/export_history.py` (imports; new route after `export_history`, around line 51)
- Test: `backend/tests/test_export_history_api.py`
- Modify: `backend/docs/api.md` (§Export History, line ~138)
- Modify: `backend/docs/architecture.md` (export history line ~171)

**Interfaces:**
- Consumes: existing `ExportFileStore.read_version(feed_source_id, version_number) -> bytes | None`, existing `_service(request, settings)` and `_require_db` in `export_history.py`, existing `require_feed_source`.
- Produces: `ExportService.version_content(feed_source_id: int, version_number: int) -> bytes`; route `GET /feed-sources/{feed_source_id}/export-history/{version_number}/content` → 200 `application/xml` or 404.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_export_history_api.py`:

```python
async def test_version_content_returns_stored_xml(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history/1/content")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "<g:id>A</g:id>" in resp.text
    assert "<g:id>B</g:id>" not in resp.text


async def test_version_content_404_when_version_unknown(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history/9/content")
    assert resp.status_code == 404


async def test_version_content_404_when_file_pruned(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    _, _, settings = app_factory
    ExportFileStore(settings.export_dir).delete_version_file(feed_source_id, 1)
    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history/1/content")
    assert resp.status_code == 404


async def test_version_content_requires_auth_and_known_feed_source(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    app, _, _ = app_factory
    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (
        await anonymous.get(f"/feed-sources/{feed_source_id}/export-history/1/content")
    ).status_code == 401

    client = await logged_in_client(app_factory)
    assert (await client.get("/feed-sources/999999/export-history/1/content")).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_export_history_api.py -k version_content -v`
Expected: FAIL — 404/405 for `/content` (route does not exist).

- [ ] **Step 3: Add `ExportService.version_content`**

In `backend/app/export/service.py`, add this method after `_load_version_products` (line ~265):

```python
    async def version_content(self, feed_source_id: int, version_number: int) -> bytes:
        async with self._session_factory() as session:
            version = (
                await session.execute(
                    select(ExportVersion).where(
                        ExportVersion.feed_source_id == feed_source_id,
                        ExportVersion.version_number == version_number,
                    )
                )
            ).scalar_one_or_none()
        if version is None:
            raise LookupError(f"version {version_number} not found")
        data = self._store.read_version(feed_source_id, version_number)
        if data is None:
            raise LookupError(f"version file {version_number} missing")
        return data
```

- [ ] **Step 4: Add the route**

In `backend/app/routes/export_history.py`, change the FastAPI import line to include `Response`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response
```

Then add this route after `export_history` (before `export_diff`, around line 52):

```python
@router.get("/feed-sources/{feed_source_id}/export-history/{version_number}/content")
async def export_version_content(
    feed_source_id: int,
    version_number: int,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    session = _require_db(db_session)
    async with session.begin():
        await require_feed_source(session, feed_source_id)
    try:
        content = await _service(request, settings).version_content(
            feed_source_id, version_number
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=content, media_type="application/xml")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_export_history_api.py -k version_content -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Update docs**

In `backend/docs/api.md`, under `### Export History` (after the `{v}/diff` line, ~139), add:

```markdown
- `GET /feed-sources/{id}/export-history/{v}/content` — raw stored XML for a version, `application/xml`. 404 when the version row or its stored file is gone (retention-pruned). Auth + scope required.
```

In `backend/docs/architecture.md` line ~171, extend the export-history bullet list with a sibling bullet:

```markdown
- **Version content**: `GET /feed-sources/{id}/export-history/{v}/content` — authenticated raw XML of a single version (preview/download)
```

- [ ] **Step 7: Commit**

```bash
cd backend && uv run ruff check . ../plugins && uv run mypy .
git add app/export/service.py app/routes/export_history.py tests/test_export_history_api.py docs/api.md docs/architecture.md
git commit -m "feat(export): add per-version content endpoint"
```

---

### Task 2: Backend — admin export-token route

**Files:**
- Modify: `backend/app/schemas/clients.py` (imports; add `ExportTokenUpdate`, `ExportTokenOut`)
- Modify: `backend/app/routes/clients.py` (schema imports; replace `rotate_export_token` response typing; add new route after it)
- Test: `backend/tests/test_export_history_api.py` (token tests can live here; it already has the app/logged-in helpers)
- Modify: `backend/docs/api.md` (§Export Token)

**Interfaces:**
- Consumes: `audit` (already imported in `clients.py:16`), `_export_url`, `_resolve_settings`, `require_admin`, `get_db_session`, `select`, `IntegrityError`.
- Produces: `PUT /feed-sources/{feed_source_id}/export-token` → 200 `{export_token, export_url}`; `ExportTokenUpdate` (`export_token: str`), `ExportTokenOut` (`export_token: str`, `export_url: str`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_export_history_api.py` (add imports at the top with the others):

```python
from app.persistence.users import create_user, seed_initial_user
```

(`seed_initial_user` is already imported; only add `create_user`.)

```python
async def _second_feed_source_token(app_factory, token: str) -> int:
    _, factory, _ = app_factory
    async with factory() as session, session.begin():
        client = Client(name="Other")
        session.add(client)
        await session.flush()
        feed = FeedSource(
            client_id=client.id, name="Other Feed", source_format="tsv", export_token=token
        )
        session.add(feed)
        await session.flush()
        return feed.id


async def test_set_export_token_as_admin(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    client = await logged_in_client(app_factory)

    resp = await client.put(
        f"/feed-sources/{feed_source_id}/export-token", json={"export_token": "my-shop"}
    )
    assert resp.status_code == 200
    assert resp.json()["export_token"] == "my-shop"
    assert resp.json()["export_url"] == "http://test.public/export/my-shop.xml"


async def test_set_export_token_rejects_non_admin(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    _, factory, _ = app_factory
    async with factory() as session, session.begin():
        feed = await session.get(FeedSource, feed_source_id)
        await create_user(session, "plain", "user-pass", "user", [feed.client_id])

    plain = AsyncClient(
        transport=ASGITransport(app=app_factory[0]), base_url="https://testserver"
    )
    login = await plain.post("/auth/login", json={"username": "plain", "password": "user-pass"})
    assert login.status_code == 200
    resp = await plain.put(
        f"/feed-sources/{feed_source_id}/export-token", json={"export_token": "mine"}
    )
    assert resp.status_code == 403


async def test_set_export_token_conflicts(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    await _second_feed_source_token(app_factory, "taken")
    client = await logged_in_client(app_factory)

    resp = await client.put(
        f"/feed-sources/{feed_source_id}/export-token", json={"export_token": "taken"}
    )
    assert resp.status_code == 409


@pytest.mark.parametrize("bad", ["", "bad/token", "bad token", "bad.token", "a" * 65])
async def test_set_export_token_rejects_invalid_values(app_factory, bad):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    client = await logged_in_client(app_factory)

    resp = await client.put(
        f"/feed-sources/{feed_source_id}/export-token", json={"export_token": bad}
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_export_history_api.py -k export_token -v`
Expected: FAIL — 405 (route does not exist) / 404.

- [ ] **Step 3: Add the schemas**

In `backend/app/schemas/clients.py`, change the imports at the top:

```python
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EXPORT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_~-]+$")
```

Then append at the end of the file:

```python
class ExportTokenUpdate(BaseModel):
    export_token: str = Field(min_length=1, max_length=64)

    @field_validator("export_token")
    @classmethod
    def _path_safe(cls, value: str) -> str:
        if not _EXPORT_TOKEN_RE.fullmatch(value):
            raise ValueError(
                "export token may only contain letters, digits, '_', '~' and '-'"
            )
        return value


class ExportTokenOut(BaseModel):
    export_token: str
    export_url: str
```

- [ ] **Step 4: Add the route and tighten the rotate response**

In `backend/app/routes/clients.py`, add to the `..schemas.clients` import block (`ExportTokenOut`, `ExportTokenUpdate`):

```python
from ..schemas.clients import (
    ClientCreate,
    ClientOut,
    ClientUpdate,
    ExportTokenOut,
    ExportTokenUpdate,
    FeedSourceCreate,
    FeedSourceOut,
    FeedSourceUpdate,
    IngestionRunOut,
)
```

Change the existing `rotate_export_token` decorator to declare the response model (behavior unchanged):

```python
@router.post(
    "/feed-sources/{feed_source_id}/export-token/rotate",
    response_model=ExportTokenOut,
)
```

Add this new route immediately after `rotate_export_token` (before `trigger_run`, ~line 341):

```python
@router.put("/feed-sources/{feed_source_id}/export-token", response_model=ExportTokenOut)
async def set_export_token(
    feed_source_id: int,
    payload: ExportTokenUpdate,
    request: Request,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, str]:
    session = _require_db(db_session)
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        clash = (
            await session.execute(
                select(FeedSource.id).where(
                    FeedSource.export_token == payload.export_token,
                    FeedSource.id != feed_source_id,
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(status_code=409, detail="export token already in use")
        feed_source.export_token = payload.export_token
        try:
            await session.flush()
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409, detail="export token already in use"
            ) from exc
        await audit(
            session,
            "feed_source.export_token.set",
            target_type="feed_source",
            target_id=feed_source_id,
        )
    settings = _resolve_settings(request)
    return {
        "export_token": payload.export_token,
        "export_url": _export_url(settings, payload.export_token),
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_export_history_api.py -k export_token -v`
Expected: PASS. (`-k export_token` matches the set-token tests; `rotate` is not named export_token.)

- [ ] **Step 6: Update docs**

In `backend/docs/api.md`, under `### Export Token` (~line 142), replace the section body with:

```markdown
- `POST /feed-sources/{id}/export-token/rotate` — rotates to a new random token, old URL invalid immediately. Returns `{export_token, export_url}`
- `PUT /feed-sources/{id}/export-token` — **admin only**. Sets a custom token. Body `{export_token}`; charset `[A-Za-z0-9_~-]`, length 1–64. 403 non-admin, 404 unknown feed source, 409 token already in use, 422 invalid value. Returns `{export_token, export_url}`
```

- [ ] **Step 7: Commit**

```bash
cd backend && uv run ruff check . ../plugins && uv run mypy .
git add app/schemas/clients.py app/routes/clients.py tests/test_export_history_api.py docs/api.md
git commit -m "feat(export): add admin custom export token route"
```

---

### Task 3: Frontend — i18n keys

**Files:**
- Modify: `frontend/public/locales/en/export.json`
- Modify: `frontend/public/locales/de/export.json`

**Interfaces:**
- Produces: the translation keys every later component uses via `useTranslation('export')`.

- [ ] **Step 1: Add the English keys**

In `frontend/public/locales/en/export.json`, add these top-level keys (place them after `"feedNotFound"`, keeping valid JSON — add a comma after the previous entry):

```json
  "preview": {
    "title": "Version {{version}} preview",
    "openFor": "Preview version",
    "notRetained": "This version is no longer retained.",
    "truncated": "Showing the first {{shown}} of {{total}} lines."
  },
  "download": {
    "version": "Download version",
    "failed": "Could not download the feed version."
  },
  "liveBadge": "Live",
  "generateRandom": "Generate random",
  "customToken": "Custom export URL value",
  "changeToken": "Apply",
  "changeWarning": "Changing the export token invalidates the current URL immediately. All systems using the old URL will stop working.",
  "tokenSaved": "Export URL updated.",
  "tokenSaveFailed": "Could not update the export URL.",
  "weakHint": "This value is easy to guess. Consider a longer random value.",
  "diff": {
    "summary": {
      "added": "Added",
      "removed": "Removed",
      "changed": "Changed",
      "fields": "Fields changed"
    },
    "findingsDelta": "Findings delta",
    "notQcd": "Not QC'd",
    "byField": "Changes by field",
    "allFields": "All fields",
    "emptyValue": "(empty)"
  }
```

Also add `"actions": "Actions",` inside the existing `columns` object.

- [ ] **Step 2: Add the German keys**

In `frontend/public/locales/de/export.json`, add the same keys with German values:

```json
  "preview": {
    "title": "Vorschau Version {{version}}",
    "openFor": "Version in der Vorschau öffnen",
    "notRetained": "Diese Version wird nicht mehr aufbewahrt.",
    "truncated": "Zeige die ersten {{shown}} von {{total}} Zeilen."
  },
  "download": {
    "version": "Version herunterladen",
    "failed": "Feed-Version konnte nicht heruntergeladen werden."
  },
  "liveBadge": "Live",
  "generateRandom": "Zufällig erzeugen",
  "customToken": "Eigener Export-URL-Wert",
  "changeToken": "Übernehmen",
  "changeWarning": "Das Ändern des Export-Tokens macht die aktuelle URL sofort ungültig. Alle Systeme, die die alte URL verwenden, funktionieren nicht mehr.",
  "tokenSaved": "Export-URL aktualisiert.",
  "tokenSaveFailed": "Export-URL konnte nicht aktualisiert werden.",
  "weakHint": "Dieser Wert ist leicht zu erraten. Verwenden Sie einen längeren zufälligen Wert.",
  "diff": {
    "summary": {
      "added": "Hinzugefügt",
      "removed": "Entfernt",
      "changed": "Geändert",
      "fields": "Geänderte Felder"
    },
    "findingsDelta": "Qualitäts-Delta",
    "notQcd": "nicht geprüft",
    "byField": "Änderungen nach Feld",
    "allFields": "Alle Felder",
    "emptyValue": "(leer)"
  }
```

Also add `"actions": "Aktionen",` inside the existing `columns` object.

- [ ] **Step 3: Verify both files parse**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('public/locales/en/export.json','utf8')); JSON.parse(require('fs').readFileSync('public/locales/de/export.json','utf8')); console.log('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add frontend/public/locales/en/export.json frontend/public/locales/de/export.json
git commit -m "feat(export): add i18n keys for preview, download, token, diff"
```

---

### Task 4: Frontend — `apiGetText` helper

**Files:**
- Modify: `frontend/src/api/client.ts` (extract `fetchWithContext`, add `apiGetText`)
- Test: `frontend/src/api/client.test.ts` (create)

**Interfaces:**
- Produces: `apiGetText(url: string): Promise<string>` exported from `../../api/client`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/api/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiGetText } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('apiGetText', () => {
  it('returns the response body as text and sends X-Request-ID', async () => {
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response('<g:id>A</g:id>', {
          status: 200,
          headers: { 'Content-Type': 'application/xml' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiGetText('/feed-sources/1/export-history/1/content')).resolves.toBe(
      '<g:id>A</g:id>',
    );
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get('X-Request-ID')).toBeTruthy();
  });

  it('throws ApiError on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 404 })));
    await expect(apiGetText('/x')).rejects.toBeInstanceOf(ApiError);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/api/client.test.ts`
Expected: FAIL — `apiGetText` is not exported.

- [ ] **Step 3: Extract `fetchWithContext` and add `apiGetText`**

In `frontend/src/api/client.ts`, replace the current `request` function (lines 55–89) with the extracted helper plus the slimmer `request`:

```ts
async function fetchWithContext(url: string, init?: RequestInit): Promise<Response> {
  const requestId = newRequestId();
  const headers = new Headers(init?.headers);
  headers.set('X-Request-ID', requestId);
  const response = await fetch(url, {
    ...init,
    credentials: 'include',
    headers,
  });
  if (!response.ok) {
    const authExempt = url.startsWith('/auth/login') || url.startsWith('/auth/password');
    if (response.status === 401 && unauthorizedHandler && !authExempt) {
      unauthorizedHandler();
    }
    const error = await parseError(response);
    createLogger('api').error(
      'request failed',
      {
        request_id: requestId,
        method: init?.method ?? 'GET',
        url: url.split('?')[0],
        status: response.status,
      },
      error,
    );
    throw error;
  }
  return response;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithContext(url, init);
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type');
  if (contentType && !contentType.includes('application/json')) {
    throw new ApiError(response.status, `Unexpected response content type: ${contentType}`);
  }
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}
```

Then add `apiGetText` next to the other `api*` exports (after `apiGetWithHeaders`, ~line 140):

```ts
export async function apiGetText(url: string): Promise<string> {
  const response = await fetchWithContext(url);
  return response.text();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat(api): add apiGetText helper for raw text responses"
```

---

### Task 5: Frontend — query key and hooks

**Files:**
- Modify: `frontend/src/api/queryKeys.ts` (`feedSource(id)` factory)
- Modify: `frontend/src/api/hooks.ts` (import `apiGetText`; add two hooks after `useRollbackToVersion`, ~line 656)
- Test: `frontend/src/api/hooks.export.test.tsx` (create)

**Interfaces:**
- Consumes: `apiGetText` (Task 4), `apiPut`.
- Produces: `queryKeys.feedSource(id).exportVersionContent(version: number)`; `useExportVersionContent(feedSourceId, version, enabled)`; `useSetExportToken(feedSourceId)`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/api/hooks.export.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '../test/render';
import { stubFetch } from '../test/fetch';
import { useExportVersionContent } from './hooks';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useExportVersionContent', () => {
  it('fetches raw XML text for a version', async () => {
    stubFetch((url) =>
      url === '/feed-sources/1/export-history/2/content'
        ? new Response('<g:id>A</g:id>', {
            status: 200,
            headers: { 'Content-Type': 'application/xml' },
          })
        : new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    const { result } = renderHook(() => useExportVersionContent(1, 2, true));
    await waitFor(() => expect(result.current.data).toBe('<g:id>A</g:id>'));
  });

  it('does not fetch when disabled', () => {
    const fetchMock = stubFetch(() => new Response('', { status: 200 }));
    renderHook(() => useExportVersionContent(1, undefined, false));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/api/hooks.export.test.tsx`
Expected: FAIL — `useExportVersionContent` is not exported.

- [ ] **Step 3: Add the query key**

In `frontend/src/api/queryKeys.ts`, inside `feedSource: (id) => ({ ... })`, add after the `exportDiff` entry (line ~22):

```ts
    exportVersionContent: (version: number) =>
      ['feed-source', id, 'export-version-content', version] as const,
```

- [ ] **Step 4: Add the hooks**

In `frontend/src/api/hooks.ts`, add `apiGetText` to the `./client` import list (line ~10), then add after `useRollbackToVersion` (line ~656):

```ts
export function useExportVersionContent(
  feedSourceId: number | string,
  version: number | undefined,
  enabled: boolean,
) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).exportVersionContent(version ?? 0),
    queryFn: () =>
      apiGetText(`/feed-sources/${feedSourceId}/export-history/${version}/content`),
    enabled: enabled && version !== undefined,
  });
}

export function useSetExportToken(feedSourceId: number | string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (exportToken: string) =>
      apiPut<{ export_token: string; export_url: string }>(
        `/feed-sources/${feedSourceId}/export-token`,
        { export_token: exportToken },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(feedSourceId).detail,
      });
    },
  });
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/api/hooks.export.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/queryKeys.ts frontend/src/api/hooks.ts frontend/src/api/hooks.export.test.tsx
git commit -m "feat(api): add export version content and set-token hooks"
```

---

### Task 6: Frontend — XML highlighter

**Files:**
- Create: `frontend/src/components/XmlHighlight.tsx`
- Test: `frontend/src/components/XmlHighlight.test.tsx`

**Interfaces:**
- Produces: `type Token = { text: string; kind: 'tag' | 'attr' | 'string' | 'comment' | 'cdata' | 'decl' | 'text' | 'entity' }`; `tokenizeXml(xml: string): Token[]`; `sliceXmlLines(xml: string, maxLines: number): { text: string; totalLines: number; truncated: boolean }`; component `XmlHighlight({ xml, maxLines })` rendering `<pre data-testid="xml-preview">`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/XmlHighlight.test.tsx`:

```tsx
import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../i18n';
import { render } from '../test/render';
import { XmlHighlight, sliceXmlLines, tokenizeXml } from './XmlHighlight';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

describe('tokenizeXml', () => {
  it('splits tags, attributes, values and text', () => {
    const kinds = tokenizeXml('<g:id lang="de">A</g:id>');
    expect(kinds.some((t) => t.kind === 'tag' && t.text.includes('g:id'))).toBe(true);
    expect(kinds.some((t) => t.kind === 'attr' && t.text === 'lang')).toBe(true);
    expect(kinds.some((t) => t.kind === 'string' && t.text === '"de"')).toBe(true);
    expect(kinds.some((t) => t.kind === 'text' && t.text === 'A')).toBe(true);
  });

  it('classifies comments, CDATA, declarations and entities', () => {
    const kinds = tokenizeXml('<!--c--><![CDATA[x]]><?xml?>&amp;');
    expect(kinds.map((t) => t.kind)).toEqual([
      'comment',
      'cdata',
      'decl',
      'entity',
    ]);
  });

  it('does not throw on an unmatched <', () => {
    expect(() => tokenizeXml('a < b')).not.toThrow();
    expect(tokenizeXml('a < b').some((t) => t.kind === 'text')).toBe(true);
  });
});

describe('sliceXmlLines', () => {
  it('caps lines and reports truncation', () => {
    const xml = 'l1\nl2\nl3';
    expect(sliceXmlLines(xml, 2)).toEqual({
      text: 'l1\nl2',
      totalLines: 3,
      truncated: true,
    });
    expect(sliceXmlLines(xml, 5)).toEqual({
      text: 'l1\nl2\nl3',
      totalLines: 3,
      truncated: false,
    });
  });
});

describe('XmlHighlight', () => {
  it('renders the raw XML as text content', () => {
    render(<XmlHighlight xml={'<g:id>A</g:id>'} />);
    expect(screen.getByTestId('xml-preview').textContent).toContain('<g:id>A</g:id>');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/components/XmlHighlight.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the highlighter**

Create `frontend/src/components/XmlHighlight.tsx`:

```tsx
import { useComputedColorScheme } from '@mantine/core';

export type TokenKind =
  | 'tag'
  | 'attr'
  | 'string'
  | 'comment'
  | 'cdata'
  | 'decl'
  | 'text'
  | 'entity';

export type Token = { text: string; kind: TokenKind };

const TOKEN_COLOR: Record<'light' | 'dark', Record<TokenKind, string>> = {
  light: {
    tag: '#1f6feb',
    attr: '#953800',
    string: '#0a7d33',
    comment: '#6e7781',
    cdata: '#8250df',
    decl: '#8250df',
    text: 'inherit',
    entity: '#cf222e',
  },
  dark: {
    tag: '#79c0ff',
    attr: '#ffa657',
    string: '#7ee787',
    comment: '#8b949e',
    cdata: '#d2a8ff',
    decl: '#d2a8ff',
    text: 'inherit',
    entity: '#ff7b72',
  },
};

const TAG_RE = /^(<\/?)([^\s/>]+)/;
const ATTR_RE = /(\s+)([^\s=/>]+)(\s*=\s*)("[^"]*"|'[^']*')?/g;

function pushText(tokens: Token[], text: string): void {
  if (!text) return;
  for (const part of text.split(/(&[^;\s]+;)/)) {
    if (!part) continue;
    tokens.push({
      text: part,
      kind: /^&[^;\s]+;$/.test(part) ? 'entity' : 'text',
    });
  }
}

function pushTag(tokens: Token[], segment: string): void {
  const open = TAG_RE.exec(segment);
  if (!open) {
    pushText(tokens, segment);
    return;
  }
  const rest = segment.slice(open[0].length);
  ATTR_RE.lastIndex = 0;
  let last = 0;
  let match: RegExpExecArray | null;
  const attrs: Token[] = [];
  while ((match = ATTR_RE.exec(rest))) {
    if (match.index > last) attrs.push({ text: rest.slice(last, match.index), kind: 'tag' });
    attrs.push({ text: match[1], kind: 'tag' });
    attrs.push({ text: match[2], kind: 'attr' });
    if (match[3]) attrs.push({ text: match[3], kind: 'tag' });
    if (match[4]) attrs.push({ text: match[4], kind: 'string' });
    last = match.index + match[0].length;
  }
  tokens.push({ text: open[0], kind: 'tag' });
  if (last < rest.length) attrs.push({ text: rest.slice(last), kind: 'tag' });
  tokens.push(...attrs);
}

export function tokenizeXml(xml: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < xml.length) {
    const lt = xml.indexOf('<', i);
    if (lt === -1) {
      pushText(tokens, xml.slice(i));
      break;
    }
    if (lt > i) pushText(tokens, xml.slice(i, lt));

    if (xml.startsWith('<!--', lt)) {
      const end = xml.indexOf('-->', lt + 4);
      const stop = end === -1 ? xml.length : end + 3;
      tokens.push({ text: xml.slice(lt, stop), kind: 'comment' });
      i = stop;
      continue;
    }
    if (xml.startsWith('<![CDATA[', lt)) {
      const end = xml.indexOf(']]>', lt + 9);
      const stop = end === -1 ? xml.length : end + 3;
      tokens.push({ text: xml.slice(lt, stop), kind: 'cdata' });
      i = stop;
      continue;
    }
    if (xml.startsWith('<?', lt) || xml.startsWith('<!', lt)) {
      const end = xml.indexOf('>', lt);
      const stop = end === -1 ? xml.length : end + 1;
      tokens.push({ text: xml.slice(lt, stop), kind: 'decl' });
      i = stop;
      continue;
    }
    const gt = xml.indexOf('>', lt);
    if (gt === -1) {
      pushText(tokens, xml.slice(lt));
      break;
    }
    pushTag(tokens, xml.slice(lt, gt + 1));
    i = gt + 1;
  }
  return tokens;
}

export function sliceXmlLines(
  xml: string,
  maxLines: number,
): { text: string; totalLines: number; truncated: boolean } {
  const lines = xml.split('\n');
  const totalLines = lines.length;
  const truncated = totalLines > maxLines;
  return {
    text: truncated ? lines.slice(0, maxLines).join('\n') : xml,
    totalLines,
    truncated,
  };
}

export function XmlHighlight({ xml, maxLines }: { xml: string; maxLines?: number }) {
  const scheme = useComputedColorScheme('light');
  const colors = TOKEN_COLOR[scheme];
  const { text } = maxLines === undefined ? { text: xml } : sliceXmlLines(xml, maxLines);
  return (
    <pre
      data-testid="xml-preview"
      style={{
        margin: 0,
        padding: 'var(--mantine-spacing-sm)',
        overflow: 'auto',
        fontSize: 'var(--mantine-font-size-xs)',
        lineHeight: 1.5,
      }}
    >
      {tokenizeXml(text).map((token, index) => (
        <span key={index} style={{ color: colors[token.kind] }}>
          {token.text}
        </span>
      ))}
    </pre>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/components/XmlHighlight.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/XmlHighlight.tsx frontend/src/components/XmlHighlight.test.tsx
git commit -m "feat(export): add local XML syntax highlighter"
```

---

### Task 7: Frontend — download helper

**Files:**
- Create: `frontend/src/features/export/download.ts`
- Test: `frontend/src/features/export/download.test.ts`

**Interfaces:**
- Consumes: `apiGetText` (Task 4).
- Produces: `downloadVersionXml(feedSourceId: number | string, version: number, xml?: string): Promise<void>`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/export/download.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch } from '../../test/fetch';
import { downloadVersionXml } from './download';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('downloadVersionXml', () => {
  it('fetches when no xml is supplied and triggers an anchor download', async () => {
    stubFetch(
      () =>
        new Response('<g:id>A</g:id>', {
          status: 200,
          headers: { 'Content-Type': 'application/xml' },
        }),
    );
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x');
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});

    await downloadVersionXml(1, 2);

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledOnce();
  });

  it('does not fetch when xml is supplied', async () => {
    const fetchMock = stubFetch(() => new Response('', { status: 200 }));
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    await downloadVersionXml(1, 2, '<g:id>A</g:id>');

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/features/export/download.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the helper**

Create `frontend/src/features/export/download.ts`:

```ts
import { apiGetText } from '../../api/client';

export async function downloadVersionXml(
  feedSourceId: number | string,
  version: number,
  xml?: string,
): Promise<void> {
  const content =
    xml ?? (await apiGetText(`/feed-sources/${feedSourceId}/export-history/${version}/content`));
  const url = URL.createObjectURL(new Blob([content], { type: 'application/xml' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `feed-${feedSourceId}-v${version}.xml`;
  anchor.click();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/features/export/download.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/export/download.ts frontend/src/features/export/download.test.ts
git commit -m "feat(export): add version download helper"
```

---

### Task 8: Frontend — version preview modal

**Files:**
- Create: `frontend/src/features/export/FeedVersionPreviewModal.tsx`
- Test: `frontend/src/features/export/FeedVersionPreviewModal.test.tsx`

**Interfaces:**
- Consumes: `useExportVersionContent` (Task 5), `XmlHighlight` + `sliceXmlLines` (Task 6), `downloadVersionXml` (Task 7), existing `LoadingState`/`ErrorState`/`EmptyState`.
- Produces: `FeedVersionPreviewModal({ feedSourceId, version, opened, onClose })`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/export/FeedVersionPreviewModal.test.tsx`:

```tsx
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { FeedVersionPreviewModal } from './FeedVersionPreviewModal';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function xmlResponse(body: string) {
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'application/xml' },
  });
}

describe('FeedVersionPreviewModal', () => {
  it('renders the fetched XML', async () => {
    stubFetch((url) =>
      url === '/feed-sources/1/export-history/2/content'
        ? xmlResponse('<g:id>A</g:id>')
        : new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    render(
      <FeedVersionPreviewModal feedSourceId={1} version={2} opened onClose={() => {}} />,
    );
    expect(await screen.findByTestId('xml-preview')).toHaveTextContent('<g:id>A</g:id>');
  });

  it('shows the not-retained state on 404', async () => {
    stubFetch(() => new Response('gone', { status: 404 }));
    render(
      <FeedVersionPreviewModal feedSourceId={1} version={9} opened onClose={() => {}} />,
    );
    expect(await screen.findByText(/no longer retained/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/features/export/FeedVersionPreviewModal.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the modal**

Create `frontend/src/features/export/FeedVersionPreviewModal.tsx`:

```tsx
import { Alert, Button, Group, Modal, ScrollArea } from '@mantine/core';
import { IconDownload } from '@tabler/icons-react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useExportVersionContent } from '../../api/hooks';
import { ApiError } from '../../api/client';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { XmlHighlight, sliceXmlLines } from '../../components/XmlHighlight';
import { downloadVersionXml } from './download';

const MAX_PREVIEW_LINES = 5000;

type Props = {
  feedSourceId: number | string;
  version: number | null;
  opened: boolean;
  onClose: () => void;
};

export function FeedVersionPreviewModal({ feedSourceId, version, opened, onClose }: Props) {
  const { t } = useTranslation('export');
  const content = useExportVersionContent(feedSourceId, version ?? undefined, opened);

  const sliced = useMemo(
    () => sliceXmlLines(content.data ?? '', MAX_PREVIEW_LINES),
    [content.data],
  );

  async function handleDownload() {
    if (version === null) return;
    try {
      await downloadVersionXml(feedSourceId, version, content.data);
      notifySuccess(t('download.version'));
    } catch (error) {
      notifyApiError(error, t('download.failed'));
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xl"
      title={version !== null ? t('preview.title', { version }) : ''}
    >
      {content.isPending ? <LoadingState /> : null}
      {content.isError ? (
        content.error instanceof ApiError && content.error.status === 404
          ? <EmptyState message={t('preview.notRetained')} />
          : <ErrorState onRetry={() => void content.refetch()} />
      ) : null}
      {content.data ? (
        <>
          {sliced.truncated ? (
            <Alert color="yellow" mb="sm">
              {t('preview.truncated', { shown: MAX_PREVIEW_LINES, total: sliced.totalLines })}
            </Alert>
          ) : null}
          <ScrollArea.Autosize mah="70vh">
            <XmlHighlight xml={content.data} maxLines={MAX_PREVIEW_LINES} />
          </ScrollArea.Autosize>
          <Group justify="flex-end" mt="md">
            <Button leftSection={<IconDownload size={16} />} onClick={() => void handleDownload()}>
              {t('download.version')}
            </Button>
          </Group>
        </>
      ) : null}
    </Modal>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/features/export/FeedVersionPreviewModal.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/export/FeedVersionPreviewModal.tsx frontend/src/features/export/FeedVersionPreviewModal.test.tsx
git commit -m "feat(export): add version preview modal"
```

---

### Task 9: Frontend — version list actions, live badge, relative time

**Files:**
- Modify: `frontend/src/features/export/ExportVersionList.tsx`
- Test: `frontend/src/features/export/ExportVersionList.test.tsx` (create)
- Modify: `frontend/src/features/export/ExportPage.tsx` (pass the two new props — required for typecheck)
- Modify: `frontend/src/test/setup.ts` (register dayjs `relativeTime` globally)

**Interfaces:**
- Produces: `ExportVersionList` props gain `onPreview: (v: number) => void` and `onDownload: (v: number) => void`; live badge `data-testid="live-badge"`; preview button `data-testid="preview-{v}"`; download button `data-testid="download-{v}"`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/export/ExportVersionList.test.tsx`:

```tsx
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { ExportVersionList } from './ExportVersionList';
import type { ExportVersionOut } from '../../api/types';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

const versions: ExportVersionOut[] = [
  {
    id: 3,
    version_number: 3,
    product_count: 100,
    file_hash: 'h3',
    source: 'scheduled',
    source_version_id: null,
    created_at: '2026-08-29T10:00:00Z',
    findings: { critical: 0, warning: 0, info: 0 },
  },
  {
    id: 1,
    version_number: 1,
    product_count: 90,
    file_hash: 'h1',
    source: 'manual',
    source_version_id: null,
    created_at: '2026-08-27T10:00:00Z',
    findings: { critical: 0, warning: 0, info: 0 },
  },
];

function setup() {
  const onPreview = vi.fn();
  const onDownload = vi.fn();
  render(
    <ExportVersionList
      versions={versions}
      versionA={undefined}
      versionB={undefined}
      onSelectA={() => {}}
      onSelectB={() => {}}
      onRollback={() => {}}
      onPreview={onPreview}
      onDownload={onDownload}
    />,
  );
  return { onPreview, onDownload };
}

describe('ExportVersionList', () => {
  it('marks only the newest version as live', () => {
    setup();
    expect(screen.getAllByTestId('live-badge')).toHaveLength(1);
    expect(screen.getByTestId('version-row-3').textContent).toContain('Live');
  });

  it('invokes preview and download per row', async () => {
    const user = userEvent.setup();
    const { onPreview, onDownload } = setup();
    await user.click(screen.getByTestId('preview-1'));
    await user.click(screen.getByTestId('download-1'));
    expect(onPreview).toHaveBeenCalledWith(1);
    expect(onDownload).toHaveBeenCalledWith(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/features/export/ExportVersionList.test.tsx`
Expected: FAIL — missing props/`data-testid`s.

- [ ] **Step 3: Update the list component**

First, register dayjs `relativeTime` globally for tests. In `frontend/src/test/setup.ts`, add at the top (after the existing imports):

```ts
import { registerRelativeTime } from '../i18n/relativeTime';

registerRelativeTime();
```

Then in `frontend/src/features/export/ExportVersionList.tsx`:

Change the Mantine import (line 1) and icon import (line 2):

```tsx
import { ActionIcon, Badge, Group, Radio, Table, Text } from '@mantine/core';
import { IconArrowBackUp, IconDownload, IconEye } from '@tabler/icons-react';
```

Extend `Props` (line 7):

```tsx
type Props = {
  versions: ExportVersionOut[];
  versionA: number | undefined;
  versionB: number | undefined;
  onSelectA: (v: number) => void;
  onSelectB: (v: number) => void;
  onRollback: (v: number) => void;
  onPreview: (v: number) => void;
  onDownload: (v: number) => void;
};
```

Destructure the new props in the function signature:

```tsx
export function ExportVersionList({
  versions,
  versionA,
  versionB,
  onSelectA,
  onSelectB,
  onRollback,
  onPreview,
  onDownload,
}: Props) {
```

Add an actions header cell after the rollback `<Table.Th>` (line ~42):

```tsx
          <Table.Th>{t('columns.actions')}</Table.Th>
```

Change the `versions.map` callback to receive the index:

```tsx
        {versions.map((version, index) => (
```

Add the live badge inside the version `<Table.Td>` group, after the rollback `Badge` block (line ~58):

```tsx
                {index === 0 ? (
                  <Badge color="green" variant="light" size="xs" data-testid="live-badge">
                    {t('liveBadge')}
                  </Badge>
                ) : null}
```

Replace the timestamp `<Text>` body (line ~62) to add the relative value:

```tsx
              <Text size="sm">
                {dayjs(version.created_at).locale(i18n.language).format('L LTS')}
                <Text component="span" c="dimmed" size="xs" ml={6}>
                  {dayjs(version.created_at).locale(i18n.language).fromNow()}
                </Text>
              </Text>
```

Add the actions `<Table.Td>` after the rollback cell (just before `</Table.Tr>`, line ~138):

```tsx
            <Table.Td>
              <Group gap={4} wrap="nowrap">
                <ActionIcon
                  variant="subtle"
                  onClick={() => onPreview(version.version_number)}
                  aria-label={`${t('preview.openFor')} ${version.version_number}`}
                  data-testid={`preview-${version.version_number}`}
                >
                  <IconEye size={16} />
                </ActionIcon>
                <ActionIcon
                  variant="subtle"
                  onClick={() => onDownload(version.version_number)}
                  aria-label={`${t('download.version')} ${version.version_number}`}
                  data-testid={`download-${version.version_number}`}
                >
                  <IconDownload size={16} />
                </ActionIcon>
              </Group>
            </Table.Td>
```

- [ ] **Step 4: Update `ExportPage` call site so it typechecks**

In `frontend/src/features/export/ExportPage.tsx`, add the two props to `<ExportVersionList>` (temporary no-op handlers; Task 12 wires them). After `onRollback={setRollbackTarget}`:

```tsx
            onPreview={() => undefined}
            onDownload={() => undefined}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm run test -- src/features/export/ExportVersionList.test.tsx && npm run typecheck`
Expected: PASS and clean typecheck.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/export/ExportVersionList.tsx frontend/src/features/export/ExportVersionList.test.tsx frontend/src/features/export/ExportPage.tsx frontend/src/test/setup.ts
git commit -m "feat(export): add preview/download row actions, live badge, relative time"
```

---

### Task 10: Frontend — admin export-URL editor

**Files:**
- Modify: `frontend/src/components/ExportUrlBlock.tsx`
- Test: `frontend/src/components/ExportUrlBlock.test.tsx` (extend)

**Interfaces:**
- Consumes: `useSession` (already in `api/hooks`), `useSetExportToken` (Task 5).
- Produces: admin-only `TextInput` (`data-testid="token-input"`) + Apply button (`data-testid="token-save"`); non-admins see no editor.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/ExportUrlBlock.test.tsx`, `ExportUrlBlock` now calls `useSession()`, which fetches `/auth/me`. Add a `/auth/me` branch to every `stubFetch` handler. For the existing four tests, prefix the handler body with:

```tsx
      if (url === '/auth/me') return jsonResponse({ username: 'u', role: 'user', client_ids: null });
```

Then add these three tests to the existing `describe('ExportUrlBlock', ...)`:

```tsx
  it('shows the token editor for admins', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'u', role: 'admin', client_ids: null });
      return jsonResponse({});
    });
    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);
    expect(await screen.findByTestId('token-input')).toBeInTheDocument();
    expect(screen.getByTestId('token-save')).toBeInTheDocument();
  });

  it('hides the token editor for non-admins', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'u', role: 'user', client_ids: [1] });
      return jsonResponse({});
    });
    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);
    expect(await screen.findByRole('button', { name: /rotate/i })).toBeInTheDocument();
    expect(screen.queryByTestId('token-input')).not.toBeInTheDocument();
  });

  it('PUTs the custom token as admin', async () => {
    const user = userEvent.setup();
    let body: string | null = null;
    fetchMock = stubFetch((url, init) => {
      if (url === '/auth/me') return jsonResponse({ username: 'u', role: 'admin', client_ids: null });
      if (url === '/feed-sources/1/export-token' && init?.method === 'PUT') {
        body = typeof init.body === 'string' ? init.body : null;
        return jsonResponse({ export_token: 'my-shop', export_url: 'http://localhost/export/my-shop.xml' });
      }
      return jsonResponse({});
    });
    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);

    const input = await screen.findByTestId('token-input');
    await user.clear(input);
    await user.type(input, 'my-shop');
    await user.click(screen.getByTestId('token-save'));
    const confirm = await screen.findByRole('button', { name: 'Confirm' });
    await user.click(confirm);

    await waitFor(() => expect(body).toBe(JSON.stringify({ export_token: 'my-shop' })));
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- src/components/ExportUrlBlock.test.tsx`
Expected: FAIL — `token-input` missing.

- [ ] **Step 3: Implement the editor**

Replace `frontend/src/components/ExportUrlBlock.tsx` with:

```tsx
import { useState } from 'react';
import { Button, Group, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconCheck, IconRotate } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useRotateExportToken, useSession, useSetExportToken } from '../api/hooks';
import { ApiError } from '../api/client';
import { notifyMutationError, notifySuccess } from '../app/notifications';
import { ConfirmModal } from './ConfirmModal';
import { CopyField } from './CopyField';

function isWeakToken(value: string): boolean {
  return value.length < 8 || /^\d+$/.test(value);
}

export function ExportUrlBlock({
  feedSourceId,
  exportUrl,
  onRotated,
}: {
  feedSourceId: number | string;
  exportUrl: string;
  onRotated?: () => void;
}) {
  const { t } = useTranslation('export');
  const { data: session } = useSession();
  const isAdmin = session?.role === 'admin';
  const rotateToken = useRotateExportToken();
  const setToken = useSetExportToken(feedSourceId);
  const currentToken = exportUrl.split('/export/')[1]?.replace(/\.xml$/, '') ?? '';
  const [tokenValue, setTokenValue] = useState(currentToken);
  const [rotateOpened, setRotateOpened] = useState(false);
  const [saveOpened, setSaveOpened] = useState(false);

  function handleRotate() {
    rotateToken.mutate(feedSourceId, {
      onSuccess: () => {
        notifySuccess(t('rotated'));
        setRotateOpened(false);
        onRotated?.();
      },
      onError: (error) => {
        notifyMutationError(error, t('rotateFailed'));
      },
    });
  }

  function handleSave() {
    setToken.mutate(tokenValue, {
      onSuccess: () => {
        notifySuccess(t('tokenSaved'));
        setSaveOpened(false);
        onRotated?.();
      },
      onError: (error) => {
        notifyMutationError(error, t('tokenSaveFailed'));
      },
    });
  }

  return (
    <Stack gap="md">
      <Title order={4}>{t('urlTitle')}</Title>
      <CopyField label={t('publicUrl')} value={exportUrl} />
      {isAdmin ? (
        <>
          <TextInput
            label={t('customToken')}
            value={tokenValue}
            onChange={(event) => setTokenValue(event.currentTarget.value)}
            data-testid="token-input"
          />
          {isWeakToken(tokenValue) ? (
            <Text size="xs" c="dimmed">
              {t('weakHint')}
            </Text>
          ) : null}
          <Group>
            <Button
              variant="light"
              leftSection={<IconCheck size={16} />}
              onClick={() => setSaveOpened(true)}
              disabled={tokenValue.length === 0}
              data-testid="token-save"
            >
              {t('changeToken')}
            </Button>
            <Button
              variant="light"
              color="orange"
              leftSection={<IconRotate size={16} />}
              onClick={() => setRotateOpened(true)}
            >
              {t('generateRandom')}
            </Button>
          </Group>
        </>
      ) : (
        <Button
          variant="light"
          color="orange"
          leftSection={<IconRotate size={16} />}
          onClick={() => setRotateOpened(true)}
        >
          {t('rotate')}
        </Button>
      )}
      <ConfirmModal
        opened={rotateOpened}
        title={t('rotate')}
        message={t('rotateWarning')}
        danger
        loading={rotateToken.isPending}
        onConfirm={handleRotate}
        onClose={() => setRotateOpened(false)}
      />
      <ConfirmModal
        opened={saveOpened}
        title={t('changeToken')}
        message={t('changeWarning')}
        danger
        loading={setToken.isPending}
        onConfirm={handleSave}
        onClose={() => setSaveOpened(false)}
      />
    </Stack>
  );
}
```

Note: `ApiError` import is unused after this rewrite — do not import it. (It was in the original for the rotate handler's error shaping; `notifyMutationError` already handles it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test -- src/components/ExportUrlBlock.test.tsx && npm run typecheck`
Expected: PASS. If typecheck flags the unused `stubSession` helper, delete that helper (it is a leftover from Step 1).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ExportUrlBlock.tsx frontend/src/components/ExportUrlBlock.test.tsx
git commit -m "feat(export): admin-editable export URL token"
```

---

### Task 11: Frontend — diff redesign

**Files:**
- Modify: `frontend/src/features/export/ExportVersionDiff.tsx`
- Test: `frontend/src/features/export/ExportVersionDiff.test.tsx` (rewrite)
- Modify: `frontend/src/features/export/ExportPage.tsx` (pass `findingsA`/`findingsB` — Task 12 finalizes, but add here to typecheck)

**Interfaces:**
- Consumes: `DiffOut` (existing), `ExportVersionOut['findings']`.
- Produces: `ExportVersionDiff` props `{ diff, isPending, isError, onRetry, findingsA, findingsB }`. `findingsA`/`findingsB` are `ExportVersionOut['findings']` (`{critical;warning;info} | null`).

- [ ] **Step 1: Rewrite the test**

Replace `frontend/src/features/export/ExportVersionDiff.test.tsx` with:

```tsx
import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { ExportVersionDiff } from './ExportVersionDiff';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

const diff = {
  version: 3,
  against: 2,
  added: ['p3'],
  removed: ['p4'],
  changed: [
    { product_id: 'p1', fields: [{ field: 'title', old: 'Old', new: 'New' }] },
    { product_id: 'p2', fields: [{ field: 'title', old: 'A', new: 'B' }, { field: 'price', old: null, new: '9 USD' }] },
  ],
};

describe('ExportVersionDiff', () => {
  it('renders summary cards and the field breakdown', () => {
    render(
      <ExportVersionDiff
        diff={diff}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={{ critical: 1, warning: 0, info: 0 }}
        findingsB={{ critical: 3, warning: 2, info: 0 }}
      />,
    );
    expect(screen.getByTestId('summary-added')).toHaveTextContent('1');
    expect(screen.getByTestId('summary-removed')).toHaveTextContent('1');
    expect(screen.getByTestId('summary-changed')).toHaveTextContent('2');
    expect(screen.getByTestId('summary-fields')).toHaveTextContent('3');
    expect(screen.getByTestId('field-breakdown').textContent).toContain('title');
    expect(screen.getByTestId('field-breakdown').textContent).toContain('2');
  });

  it('shows the findings delta', () => {
    render(
      <ExportVersionDiff
        diff={diff}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={{ critical: 1, warning: 0, info: 0 }}
        findingsB={{ critical: 3, warning: 2, info: 0 }}
      />,
    );
    expect(screen.getByTestId('findings-delta').textContent).toContain('3');
  });

  it('shows not-QCd when a compared side has no findings', () => {
    render(
      <ExportVersionDiff
        diff={diff}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={null}
        findingsB={{ critical: 3, warning: 2, info: 0 }}
      />,
    );
    expect(screen.getByTestId('findings-delta').textContent).toMatch(/not qc/i);
  });

  it('renders the empty state when no changes', () => {
    render(
      <ExportVersionDiff
        diff={{ version: 2, against: 1, added: [], removed: [], changed: [] }}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={null}
        findingsB={null}
      />,
    );
    expect(screen.getByText(/no changes/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/features/export/ExportVersionDiff.test.tsx`
Expected: FAIL — new props/testids missing.

- [ ] **Step 3: Rewrite the component**

Replace `frontend/src/features/export/ExportVersionDiff.tsx` with:

```tsx
import {
  Accordion,
  Badge,
  Card,
  Code,
  Group,
  SimpleGrid,
  Stack,
  Table,
  Text,
} from '@mantine/core';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import type { DiffOut, ExportVersionOut } from '../../api/types';

type Props = {
  diff: DiffOut | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  findingsA: ExportVersionOut['findings'];
  findingsB: ExportVersionOut['findings'];
};

function ValueCell({ value }: { value: unknown }) {
  const { t } = useTranslation('export');
  if (value === null || value === undefined) {
    return (
      <Text component="span" c="dimmed" size="sm">
        {t('diff.emptyValue')}
      </Text>
    );
  }
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  const shown = text.length > 120 ? `${text.slice(0, 120)}…` : text;
  return <Code title={text}>{shown}</Code>;
}

function FindingsDelta({
  a,
  b,
}: {
  a: ExportVersionOut['findings'];
  b: ExportVersionOut['findings'];
}) {
  const { t } = useTranslation('export');
  if (!a || !b) {
    return (
      <Text c="dimmed" size="sm">
        {t('diff.notQcd')}
      </Text>
    );
  }
  const severities = ['critical', 'warning', 'info'] as const;
  return (
    <Group gap="lg">
      {severities.map((severity) => {
        const delta = b[severity] - a[severity];
        return (
          <Stack key={severity} gap={0}>
            <Text size="xs" c="dimmed">
              {t(`findings.${severity}_other`, { count: b[severity] })}
            </Text>
            <Text fw={600} c={delta > 0 ? 'red' : delta < 0 ? 'green' : undefined}>
              {a[severity]} → {b[severity]}
            </Text>
          </Stack>
        );
      })}
    </Group>
  );
}

export function ExportVersionDiff({
  diff,
  isPending,
  isError,
  onRetry,
  findingsA,
  findingsB,
}: Props) {
  const { t } = useTranslation('export');
  const [selectedField, setSelectedField] = useState<string | null>(null);

  const fieldCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const product of diff?.changed ?? []) {
      for (const field of product.fields) {
        counts.set(field.field, (counts.get(field.field) ?? 0) + 1);
      }
    }
    return [...counts.entries()].sort(
      (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
    );
  }, [diff?.changed]);

  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={onRetry} />;
  if (!diff) return <EmptyState message={t('selectVersions')} />;
  const hasChanges = diff.added.length > 0 || diff.removed.length > 0 || diff.changed.length > 0;
  if (!hasChanges) return <EmptyState message={t('noChanges')} />;

  const totalFields = diff.changed.reduce((sum, product) => sum + product.fields.length, 0);
  const visibleChanged = selectedField
    ? diff.changed.filter((product) => product.fields.some((f) => f.field === selectedField))
    : diff.changed;

  return (
    <Stack gap="md" data-testid="export-version-diff">
      <Text fw={600}>{t('diffTitle', { version: diff.version, against: diff.against })}</Text>

      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <Card withBorder padding="sm">
          <Text fw={700} data-testid="summary-added">
            {diff.added.length}
          </Text>
          <Text size="xs" c="dimmed">
            {t('diff.summary.added')}
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text fw={700} data-testid="summary-removed">
            {diff.removed.length}
          </Text>
          <Text size="xs" c="dimmed">
            {t('diff.summary.removed')}
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text fw={700} data-testid="summary-changed">
            {diff.changed.length}
          </Text>
          <Text size="xs" c="dimmed">
            {t('diff.summary.changed')}
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text fw={700} data-testid="summary-fields">
            {totalFields}
          </Text>
          <Text size="xs" c="dimmed">
            {t('diff.summary.fields')}
          </Text>
        </Card>
      </SimpleGrid>

      <Card withBorder padding="sm" data-testid="findings-delta">
        <Text size="sm" fw={600} mb={4}>
          {t('diff.findingsDelta')}
        </Text>
        <FindingsDelta a={findingsA} b={findingsB} />
      </Card>

      {diff.added.length > 0 ? (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {t('added')} ({diff.added.length})
          </Text>
          <Group gap={4}>
            {diff.added.map((id) => (
              <Badge key={id} color="green" variant="light">
                {id}
              </Badge>
            ))}
          </Group>
        </Stack>
      ) : null}
      {diff.removed.length > 0 ? (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {t('removed')} ({diff.removed.length})
          </Text>
          <Group gap={4}>
            {diff.removed.map((id) => (
              <Badge key={id} color="red" variant="light">
                {id}
              </Badge>
            ))}
          </Group>
        </Stack>
      ) : null}

      {fieldCounts.length > 0 ? (
        <Stack gap={4}>
          <Group justify="space-between">
            <Text size="sm" fw={500}>
              {t('diff.byField')}
            </Text>
            {selectedField ? (
              <Badge
                variant="light"
                style={{ cursor: 'pointer' }}
                onClick={() => setSelectedField(null)}
              >
                {t('diff.allFields')}
              </Badge>
            ) : null}
          </Group>
          <Group gap={4} data-testid="field-breakdown">
            {fieldCounts.map(([field, count]) => (
              <Badge
                key={field}
                variant={selectedField === field ? 'filled' : 'light'}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelectedField(selectedField === field ? null : field)}
              >
                {field} · {count}
              </Badge>
            ))}
          </Group>
        </Stack>
      ) : null}

      {visibleChanged.length > 0 ? (
        <Accordion variant="separated" multiple>
          {visibleChanged.map((product) => (
            <Accordion.Item key={product.product_id} value={product.product_id}>
              <Accordion.Control>
                <Group justify="space-between">
                  <Text fw={500}>{product.product_id}</Text>
                  <Text size="sm" c="dimmed">
                    {t('fieldsChanged', { count: product.fields.length })}
                  </Text>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Table withTableBorder>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('columns.field')}</Table.Th>
                      <Table.Th>{t('columns.old')}</Table.Th>
                      <Table.Th>{t('columns.new')}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {product.fields.map((field, idx) => (
                      <Table.Tr key={`${field.field}-${idx}`}>
                        <Table.Td>{field.field}</Table.Td>
                        <Table.Td>
                          <ValueCell value={field.old} />
                        </Table.Td>
                        <Table.Td>
                          <ValueCell value={field.new} />
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      ) : null}
    </Stack>
  );
}
```

- [ ] **Step 4: Pass findings from `ExportPage` so it typechecks**

In `frontend/src/features/export/ExportPage.tsx`, add to `<ExportVersionDiff>`:

```tsx
            findingsA={versions.find((v) => v.version_number === versionA)?.findings}
            findingsB={versions.find((v) => v.version_number === versionB)?.findings}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm run test -- src/features/export/ExportVersionDiff.test.tsx && npm run typecheck`
Expected: PASS and clean typecheck.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/export/ExportVersionDiff.tsx frontend/src/features/export/ExportVersionDiff.test.tsx frontend/src/features/export/ExportPage.tsx
git commit -m "feat(export): redesign version diff with summary, field breakdown, findings delta"
```

---

### Task 12: Frontend — Export page wiring (preview, download, URL query)

**Files:**
- Modify: `frontend/src/features/export/ExportPage.tsx`
- Modify: `frontend/src/features/export/ExportPage.test.tsx` (extend)

**Interfaces:**
- Consumes: `FeedVersionPreviewModal` (Task 8), `downloadVersionXml` (Task 7), list callbacks (Task 9).
- Produces: eye opens the modal; download fetches and saves; A/B selection round-trips via `?a=`/`?b=`.

- [ ] **Step 1: Add the failing tests**

In `frontend/src/features/export/ExportPage.test.tsx`, import `useSearchParams` helpers are not needed; render inside `MemoryRouter initialEntries={['/clients/1/feeds/1/export?a=3&b=2']}`. Add a test for preview and one for query round-trip:

```tsx
  it('opens the preview modal from the row eye', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/feed-sources/1') return jsonResponse(feed);
      if (url === '/feed-sources/1/export-history') return jsonResponse(versions);
      if (url === '/feed-sources/1/export-history/3/content')
        return new Response('<g:id>A</g:id>', {
          status: 200,
          headers: { 'Content-Type': 'application/xml' },
        });
      if (url.startsWith('/feed-sources/1/export-history/'))
        return jsonResponse({ version: 3, against: 2, added: [], removed: [], changed: [] });
      return jsonResponse({});
    });
    renderAt();
    await screen.findByTestId('version-row-3');
    await user.click(screen.getByTestId('preview-3'));
    expect(await screen.findByTestId('xml-preview')).toHaveTextContent('<g:id>A</g:id>');
  });

  it('reads the compared versions from the URL query', async () => {
    stubFetch((url) => {
      if (url === '/feed-sources/1') return jsonResponse(feed);
      if (url === '/feed-sources/1/export-history') return jsonResponse(versions);
      if (url.startsWith('/feed-sources/1/export-history/'))
        return jsonResponse({ version: 3, against: 2, added: [], removed: [], changed: [] });
      return jsonResponse({});
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/clients/1/feeds/1/export?a=3&b=2']}>
          <Routes>
            <Route path="/clients/:clientId/feeds/:feedSourceId/export" element={<ExportPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('version-row-3')).toBeInTheDocument());
    expect(screen.getByTestId('compare-versions-button')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- src/features/export/ExportPage.test.tsx`
Expected: FAIL — preview not wired; query not read.

- [ ] **Step 3: Wire the page**

In `frontend/src/features/export/ExportPage.tsx`:

Add imports (`notifyApiError` is already imported at the top — do not re-add it):

```tsx
import { useSearchParams } from 'react-router';
import { FeedVersionPreviewModal } from './FeedVersionPreviewModal';
import { downloadVersionXml } from './download';
```

Replace the `useState` selection block (lines 27–30) with URL-backed state:

```tsx
  const [searchParams, setSearchParams] = useSearchParams();
  const [versionA, setVersionAState] = useState<number | undefined>(() => {
    const raw = searchParams.get('a');
    return raw === null ? undefined : Number(raw);
  });
  const [versionB, setVersionBState] = useState<number | undefined>(() => {
    const raw = searchParams.get('b');
    return raw === null ? undefined : Number(raw);
  });
  const [compared, setCompared] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null);
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);

  function setVersionA(value: number) {
    setVersionAState(value);
    const next = new URLSearchParams(searchParams);
    next.set('a', String(value));
    setSearchParams(next, { replace: true });
  }

  function setVersionB(value: number) {
    setVersionBState(value);
    const next = new URLSearchParams(searchParams);
    next.set('b', String(value));
    setSearchParams(next, { replace: true });
  }
```

Add the download handler after `onConfirmRollback`:

```tsx
  async function onDownload(version: number) {
    try {
      await downloadVersionXml(id, version);
    } catch (error) {
      notifyApiError(error, t('download.failed'));
    }
  }
```

Replace the two Task-9 placeholder props on `<ExportVersionList>`:

```tsx
            onPreview={setPreviewVersion}
            onDownload={(version) => void onDownload(version)}
```

Render the modal before `<RollbackConfirmModal>`:

```tsx
      <FeedVersionPreviewModal
        feedSourceId={id}
        version={previewVersion}
        opened={previewVersion !== null}
        onClose={() => setPreviewVersion(null)}
      />
```

- [ ] **Step 4: Run the full frontend suite and typecheck**

Run: `cd frontend && npm run test && npm run typecheck`
Expected: PASS, clean typecheck.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/export/ExportPage.tsx frontend/src/features/export/ExportPage.test.tsx
git commit -m "feat(export): wire preview modal, download, and URL-query selection"
```

---

### Task 13: Full verification and docs check

**Files:**
- Modify (only if drift found): `backend/docs/api.md`, `backend/docs/architecture.md`, `frontend/AGENTS.md`

**Interfaces:**
- Consumes: everything above.
- Produces: green gates and consistent docs.

- [ ] **Step 1: Run all backend gates**

Run:
```bash
cd backend
uv run ruff check . ../plugins
uv run mypy .
uv run pytest --report-log=.report.jsonl
```
Expected: ruff exit 0, mypy exit 0, pytest all pass. If pytest fails, inspect with:
```bash
jq -r 'select(.["$report_type"]=="TestReport" and .when=="call" and .outcome=="failed") | .nodeid' .report.jsonl
```

- [ ] **Step 2: Run all frontend gates**

Run:
```bash
cd frontend
npm run test
npm run typecheck
npm run lint
npm run format:check
```
Expected: all exit 0. If `format:check` fails, run `npm run format` and commit the formatting as part of the offending task's fix.

- [ ] **Step 3: Verify docs match behavior**

Confirm `backend/docs/api.md` documents both new routes and `backend/docs/architecture.md` mentions the content endpoint. No new frontend convention was introduced (no dependency, no new store), so `frontend/AGENTS.md` needs no change. If either backend doc is missing, add it and commit.

- [ ] **Step 4: Commit any doc fixes**

```bash
git add backend/docs/api.md backend/docs/architecture.md frontend/AGENTS.md
git commit -m "docs: align export page docs with implementation"
```

(If there are no changes, skip this commit.)

---

## Self-Review

- **Spec coverage:** §Backend 1 → Task 1; §Backend 2 → Task 2; §3 API helper → Task 4; §query keys/hooks → Task 5; §4 highlighter → Task 6; §5 modal → Task 8; §6 download → Task 7; §7 list → Task 9; §8 diff → Task 11; §9 URL editor → Task 10; §10 page wiring → Task 12; §11 i18n → Task 3; testing/verification/docs → Tasks 1/2/13. All covered.
- **Placeholder scan:** no TBD/TODO; every code step contains complete code.
- **Type consistency:** `version_content` name matches route call; `apiGetText` matches hooks/download; `useExportVersionContent`/`useSetExportToken` names match modal/URL-block imports; `tokenizeXml`/`sliceXmlLines`/`XmlHighlight` names match modal import; `downloadVersionXml` matches page import; `onPreview`/`onDownload` prop names match list ↔ page; `findingsA`/`findingsB` match page ↔ diff; `exportVersionContent` key matches hook. `columns.actions` is added in Task 3 alongside the other new keys.
