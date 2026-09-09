# Review Remediation Cycle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the actionable findings from the 2026-09-08 full project review: the B1 tenancy-scoping gap, the CI/tooling enforcement drift (ruff/mypy gates, alembic URL, Makefile), the frontend error-path cluster (silent saves, perpetual spinner, misleading toasts, hook-order violation), the German i18n pass (missing keys, register, plurals), and the pivot-point doc drift (RJSF, Rolldown, data-model).

**Architecture:** No schema, migration, pipeline-order, or API-surface changes. Backend: scope guard inside the plugin config/data routes (admin-only global tier), robustness fix in `enforce_scope_access`, tooling pins/gates. Frontend: error handling added to the flows that lack it, i18n key additions/rewrites (en+de parity), no state-architecture changes. Docs: ADR amendments and model/API reference refresh. Reports → fixes traceability: every task header names the finding IDs from `docs/reports/2026-09-08-*.md`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + APScheduler + alembic + pytest (backend, `uv run pytest -n auto`, real PostgreSQL via `TEST_DATABASE_URL`), React 19.2.7 + TypeScript 7.0.2 (`tsc -b`) + Mantine 9.5.2 + TanStack Query 5.102.8 + i18next 26.4.0 + vitest 4.1.11 (frontend, Vite 8.2.2/Rolldown).

**Requirements source:** `docs/reports/2026-09-08-00-review-overview.md` (top-10 + suggested cycle order) and the five area reports `01`–`06`. This plan implements the overview's steps 1–5; findings intentionally deferred are listed in "Deferred findings" at the bottom and get filed into `TODO.md` by Task 15.

## Operator decisions required before/within execution

Per root AGENTS.md ("Ask first: new dependencies"), two tasks add dev-group dependencies — the operator approved this plan = approval, but each task is independently droppable:

- **Task 2 adds `ruff==0.16.6` to the backend dev group** (pin matches the version already installed globally; current error count 508).
- **Task 14 adds eslint + plugins to frontend devDependencies.**

Operator-only items NOT in this plan (flagged, not fixable by agents):

- **D2/D3 spec conflicts** (spec §10 vs §2/§5.9 labelizer scope; spec §2 single-user vs shipped RBAC) — spec amendments, see `docs/reports/2026-09-08-06-docs-consistency.md`.
- **B1 follow-up question:** should the plugin enable/disable toggle (`PUT /plugins/{id}/enabled`) also be admin-only? It is equally agency-global, but the frontend registry panel is currently operator-facing; 409-in-use already limits damage. Filed in TODO by Task 15.
- **U10 terminology:** "Mandant" — operator decision. de/admin.json + de/dashboard.json swept (Kunde→Mandant).

## Global Constraints

- No comments in production code; all UI strings via `t()`; en+de i18n trees structurally identical (same key sets, both languages, same commit).
- TDD per task where a behavior changes; pure refactors/deletions prove safety via the existing suite staying green.
- Gates — backend: from `backend/`, `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto`; frontend: from `frontend/`, `npm test -- --run && npm run typecheck && npm run build`.
- Lint gate per task: `uvx ruff check <touched backend files>` exits 0 and `uvx mypy <touched backend files>` adds zero new errors vs `backend/docs/mypy-baseline.md` (until Task 2 lands; afterwards `uv run ruff check <files>`). The full-repo `ruff check .` / `mypy .` remain baseline-gated (508 / 42), never exit-0 yet.
- Run backend and frontend suites sequentially, never concurrently (load-induced jsdom flakes); re-run solo before diagnosing any single failure.
- RTL lesson: `rerender` REMOUNTS in this repo — behavior is proven by the suite, not remount probes.
- Frontend test conventions: `render` from `src/test/render`, `stubFetch` from `src/test/fetch`, `notifications.clean()` in `beforeEach`, `await i18n.loadNamespaces(...)` in `beforeAll`, per-test `new QueryClient({ defaultOptions: { queries: { retry: false } } })`.
- Mantine 9.5.2. TypeScript 7.0.2 (`tsc -b`).
- Work on `main` (session convention); commit after every green gate; files end with a trailing newline (`git diff --check` clean).
- Documentation rule: any behavior/API/command change updates the affected doc in the same commit (Tasks 12/13 carry the doc batch).

---

### Task 1: B1 — admin-only global tier for plugin config/data (+ B7 malformed-param 422)

**Files:**
- Modify: `backend/app/routes/plugins.py` (imports; `_resolve_target`; `_get_payload`; `_put_payload`; the four config/data route signatures)
- Modify: `backend/app/access.py:94-109` (`enforce_scope_access` int conversions)
- Create: `backend/tests/test_plugin_global_scope_access.py`

**Interfaces:**
- Consumes: `CurrentUser` (client_ids `None` = unrestricted/admin; frozenset = scoped) and `get_current_user` from `backend/app/access.py`; existing `_declared_scopes` / `_validation_error` / `_BOTH_SCOPES_ERROR` in `routes/plugins.py`.
- Produces: nothing consumed by later tasks. Behavior contract: global-tier `GET/PUT /plugins/{id}/config|data` → 403 `admin role required` for any user with non-None `client_ids`; malformed `client_id`/`feed_source_id` query params → 422, never 500.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_plugin_global_scope_access.py` (modeled on `tests/test_admin_users_api.py` — same `isolated_database_url` engine/session pattern; the core plugin `custom_labels` is seeded by `create_app`'s plugin discovery and declares `config_scope: ["global", "client"]`, `data_scope: ["client", "feed_source"]`):

```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.client import Client
from app.models.session import Session
from app.models.user import User
from app.models.user_client import UserClient
from app.persistence.users import seed_initial_user
from app.security.passwords import hash_password


@pytest_asyncio.fixture
async def scope_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(UserClient))
            await session.execute(delete(Client))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "admin-pass")
        async with session.begin():
            acme = Client(name="Acme")
            session.add(acme)
            await session.flush()
            bob = User(username="bob", password_hash=hash_password("bob-pass"), role="user")
            session.add(bob)
            await session.flush()
            session.add(UserClient(user_id=bob.id, client_id=acme.id))
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app
    await engine.dispose()


async def _login(app, username: str, password: str) -> AsyncClient:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    response = await client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return client


@pytest.mark.asyncio
async def test_scoped_user_cannot_read_or_write_global_plugin_config(scope_app):
    app = scope_app
    async with await _login(app, "bob", "bob-pass") as bob:
        assert (await bob.get("/plugins/custom_labels/config")).status_code == 403
        assert (await bob.put(
            "/plugins/custom_labels/config", json={"slotRules": []}
        )).status_code == 403


@pytest.mark.asyncio
async def test_scoped_user_cannot_read_or_write_global_plugin_data(scope_app):
    app = scope_app
    async with await _login(app, "bob", "bob-pass") as bob:
        assert (await bob.get("/plugins/custom_labels/data")).status_code == 403
        assert (await bob.put(
            "/plugins/custom_labels/data", json={"slotIds": {}}
        )).status_code == 403


@pytest.mark.asyncio
async def test_admin_can_read_global_plugin_config(scope_app):
    app = scope_app
    async with await _login(app, "operator", "admin-pass") as admin:
        assert (await admin.get("/plugins/custom_labels/config")).status_code == 200


@pytest.mark.asyncio
async def test_scoped_user_can_use_client_tier(scope_app):
    app = scope_app
    async with await _login(app, "bob", "bob-pass") as bob:
        response = await bob.get("/plugins/custom_labels/config?client_id=1")
        assert response.status_code == 200
        assert response.json() == {}


@pytest.mark.asyncio
async def test_malformed_scope_query_params_return_422(scope_app):
    app = scope_app
    async with await _login(app, "bob", "bob-pass") as bob:
        assert (await bob.get("/plugins?client_id=abc")).status_code == 422
        assert (await bob.get("/plugins/custom_labels/config?feed_source_id=xyz")).status_code == 422
```

Note: `{"slotRules": []}` and `{"slotIds": {}}` are valid payloads against the `custom_labels` manifest schemas (empty array / empty object; `plugins/core/custom_labels/plugin.json` has no `minItems`/`minProperties`). Both malformed-param legs use the scoped user on purpose: an admin bypasses `enforce_scope_access` entirely (`client_ids is None` early return), so only a scoped user exercises the two `int()` conversion paths. (Pre-fix, both legs return 500 — the `feed_source_id` leg crashes inside `enforce_scope_access` before FastAPI's own query-param validation would run, because router-level dependencies solve first.)

- [ ] **Step 2: Run the new tests — they must FAIL**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_plugin_global_scope_access.py -v`
Expected: the two 403 tests FAIL with `assert 200 == 403` (bob currently reads/writes the global tier), the 422 test FAILS with `assert 500 == 422`; the admin and client-tier tests PASS already.

- [ ] **Step 3: Implement the global-tier guard in `routes/plugins.py`**

3a. Extend the imports (keep `require_user`; the list/enabled routes keep using it):

```python
from ..access import CurrentUser, get_current_user
```

3b. In `_resolve_target`, add a `user: CurrentUser` parameter (last position) and, immediately after the scope is determined (after the `else: scope = "global"` line), insert:

```python
    if scope == "global" and user.client_ids is not None:
        raise HTTPException(status_code=403, detail="admin role required")
```

Full signature becomes:

```python
async def _resolve_target(
    plugin_id: str,
    client_id: int | None,
    feed_source_id: int | None,
    db_session: AsyncSession,
    scope_kind: str,
    user: CurrentUser,
) -> tuple[Plugin, str, int | None, int | None] | JSONResponse:
```

3c. In the four route handlers `get_plugin_config`, `put_plugin_config`, `get_plugin_data`, `put_plugin_data`, replace the dependency `_user: str = Depends(require_user)` with `user: CurrentUser = Depends(get_current_user)`, and pass `user` as the last argument to `_get_payload` / `_put_payload`.

3d. In `_get_payload` and `_put_payload`, add a `user: CurrentUser` parameter (last position, after `db_session`) and forward it to `_resolve_target`.

Do NOT change `list_plugins` or `update_plugin_enabled` (operator decision pending — see header).

- [ ] **Step 4: Run the scope tests — B1 green, B7 still red**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest tests/test_plugin_global_scope_access.py -v`
Expected: the four 403/admin/client-tier tests PASS; `test_malformed_scope_query_params_return_422` still FAILS (500).

- [ ] **Step 5: Fix the int conversions in `access.py` (B7)**

In `enforce_scope_access`, replace the `client_id` block (lines 94-97) with:

```python
    if client_id is not None:
        try:
            client_id_int = int(client_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="client_id must be an integer",
            )
        if client_id_int not in user.client_ids:
            raise HTTPException(status_code=404, detail="client not found")
        return
```

and the `feed_source_id` block (lines 98-109) with:

```python
    if feed_source_id is not None:
        if db_session is None:
            return  # handler will raise 503 (database unavailable)
        from .models.feed_source import FeedSource

        try:
            feed_source_id_int = int(feed_source_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="feed_source_id must be an integer",
            )
        feed_source = await db_session.get(FeedSource, feed_source_id_int)
        feed_client_id = feed_source.client_id if feed_source is not None else None
        # Close the implicitly-begun read transaction so handlers can start
        # their own `session.begin()` without InvalidRequestError.
        await db_session.rollback()
        if feed_client_id is None or feed_client_id not in user.client_ids:
            raise HTTPException(status_code=404, detail="feed source not found")
```

(Keep the pre-existing explanatory comment; add no new comments.)

- [ ] **Step 6: Full backend gate**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto`
Expected: all pass. Existing plugin-config tests (test_custom_labels_*, test_m6 acceptance) authenticate as the seeded operator (role `admin`, `client_ids=None`) or run in single-user no-DB mode (also unrestricted), so the new 403 must not break them — if any existing test PUTs global config as a *scoped* user, that test fixture gets `role="user"` → `role="admin"` and the plan deviation is reported honestly.

Run: `uvx ruff check app/routes/plugins.py app/access.py && uvx mypy app/routes/plugins.py app/access.py`
Expected: ruff exit 0; mypy no new errors vs baseline for these files.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/plugins.py backend/app/access.py backend/tests/test_plugin_global_scope_access.py
git commit -m "fix(backend): admin-only global tier for plugin config/data; 422 on malformed scope params"
```

---

### Task 2: T1+T2 — pin ruff in the dev group; add ruff+mypy baseline gates to CI

**OPERATOR APPROVAL:** adds `ruff==0.16.6` to the backend dev group (new dev dependency; needs network for `uv add`). Droppable without affecting other tasks.

**Files:**
- Modify: `backend/pyproject.toml` (dev group), `backend/uv.lock` (via `uv add`)
- Create: `backend/ruff-baseline.txt`, `backend/mypy-baseline.txt`
- Modify: `.github/workflows/ci.yml` (backend job, after the migrations step)
- Modify: `backend/docs/mypy-baseline.md` (one header line: CI counter file reference)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `uv run ruff` becomes a working locked command (consumed by later tasks' lint steps); CI enforces "no new ruff/mypy errors" via the two baseline txt files. When either baseline reaches 0, flip the gate to plain `uv run ruff check .` / `uv run mypy .` exit-0 (matches TODO 10.1's acceptance).

- [ ] **Step 1: Add ruff to the dev group and re-lock**

Run: `cd backend && uv add --dev "ruff==0.16.6"`
Expected: `pyproject.toml` dev group gains `"ruff==0.16.6"`; `uv.lock` updated. Then `uv sync --locked` succeeds.

- [ ] **Step 2: Capture the current baseline counts**

Run: `cd backend && uv run ruff check . --output-format=concise 2>/dev/null | wc -l`
Expected: `508` (as of 2026-09-08; use whatever number prints — it is the pinned-ruff count).
Run: `cd backend && uv run mypy . 2>/dev/null | grep -c ': error:'`
Expected: `42` (cross-check against `backend/docs/mypy-baseline.md`; use the actual count).

- [ ] **Step 3: Write the baseline files**

`backend/ruff-baseline.txt` — single line with the ruff count from Step 2, e.g.:

```
508
```

`backend/mypy-baseline.txt` — single line with the mypy count:

```
42
```

In `backend/docs/mypy-baseline.md`, add one sentence under the header: "CI enforces the count via `backend/mypy-baseline.txt`; keep both in sync — each fix removes lines from both files in the same commit."

- [ ] **Step 4: Add the two CI gates**

In `.github/workflows/ci.yml`, insert between the "Run alembic migrations" step and the "Run backend tests and compile checks" step:

```yaml
      - name: Ruff baseline gate (no new lint errors)
        working-directory: backend
        run: |
          COUNT=$(uv run ruff check . --output-format=concise 2>/dev/null | wc -l)
          BASELINE=$(cat ruff-baseline.txt)
          echo "ruff errors: $COUNT (baseline $BASELINE)"
          if [ "$COUNT" -gt "$BASELINE" ]; then exit 1; fi
      - name: Mypy baseline gate (no new type errors)
        working-directory: backend
        run: |
          COUNT=$(uv run mypy . 2>/dev/null | grep -c ': error:')
          BASELINE=$(cat mypy-baseline.txt)
          echo "mypy errors: $COUNT (baseline $BASELINE)"
          if [ "$COUNT" -gt "$BASELINE" ]; then exit 1; fi
```

(The pipeline's exit status is `wc`/`grep`'s 0, so the count comparison — not ruff/mypy's exit 1 — decides the gate.)

- [ ] **Step 5: Verify the gates locally**

Run: `cd backend && COUNT=$(uv run ruff check . --output-format=concise 2>/dev/null | wc -l) && echo "count=$COUNT" && [ "$COUNT" -le "$(cat ruff-baseline.txt)" ] && echo GATE-OK`
Expected: `GATE-OK`. Repeat the mypy variant. Then run the frontend gate unchanged: `cd frontend && npm test -- --run && npm run typecheck && npm run build` (backend tests already green from Task 1; run the backend suite again if any backend file was touched).

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/ruff-baseline.txt backend/mypy-baseline.txt backend/docs/mypy-baseline.md .github/workflows/ci.yml
git commit -m "chore(backend): pin ruff in dev group; CI ruff/mypy baseline gates"
```

---

### Task 3: T3+T4+T5 — alembic honors DATABASE_URL; fix `make plugin-test`; fix backend/AGENTS.md env path

**Files:**
- Modify: `backend/alembic/env.py` (top of file)
- Modify: `Makefile:108` (`plugin-test` target)
- Modify: `backend/AGENTS.md` (setup command block)

**Interfaces:**
- Consumes: `Settings.async_database_url` (sync→asyncpg URL conversion) from `backend/app/config.py:22-33`.
- Produces: `DATABASE_URL=... uv run alembic upgrade head` (README/AGENTS command) becomes actually true; `make plugin-test` and `make test` work from the repo root.

- [ ] **Step 1: Read DATABASE_URL in `backend/alembic/env.py`**

Add at the top, after the `from alembic import context` import block and before `config = context.config` is used, so the file reads:

```python
import os

from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

from app.db.base import Base
from app import models  # noqa: F401

config = context.config
_database_url = os.environ.get("DATABASE_URL")
if _database_url:
    from app.config import Settings

    config.set_main_option(
        "sqlalchemy.url", Settings(database_url=_database_url).async_database_url
    )
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata
```

(Keep `run_migrations_offline` / `do_run_migrations` / `run_async_migrations` / `run_migrations_online` unchanged below. `Settings(database_url=...)` reuses the app's own sync→asyncpg conversion, so CI's `postgresql://` DATABASE_URL works. Settings still requires `session_secret`/`initial_username`/`initial_password` from env or the root `.env` — they are required to run the app anyway, and CI sets them.)

- [ ] **Step 2: Verify the override is real**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/definitely_missing_db uv run alembic upgrade head`
Expected: FAILS with a connection error naming `definitely_missing_db` (proving the env var is honored — previously it silently used the hardcoded `alembic.ini` URL).
Run: `cd backend && uv run alembic upgrade head` (no env var; DB up)
Expected: pass against the `alembic.ini` URL as before.

- [ ] **Step 3: Fix the Makefile plugin-test target**

Replace `Makefile:106-108` with:

```makefile
.PHONY: plugin-test
plugin-test: ## Run plugin contract tests
	cd $(BACKEND_DIR) && uv run pytest tests/test_plugin_contract.py
```

- [ ] **Step 4: Verify from the repo root**

Run: `make plugin-test` (from repo root)
Expected: the contract tests run and pass (previously `uv run` failed: no pyproject at root, and `backend/tests/...` is the wrong path from `backend/`).

- [ ] **Step 5: Fix the backend/AGENTS.md env path**

In `backend/AGENTS.md`, change the setup line `cp .env.example .env` (under "From backend/") to:

```bash
cp ../.env.example ../.env
```

(`app/config.py` loads the repo-root `.env`; `backend/.env` would be silently ignored. The root AGENTS.md already shows the root-relative form — leave it.)

- [ ] **Step 6: Gates and commit**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -n auto`
Expected: green (alembic env.py is not imported by tests; `test_environment_docs.py` checks docs — run it explicitly if paranoid: `uv run pytest tests/test_environment_docs.py -v`).
Run: `uvx ruff check alembic/env.py && uvx mypy alembic/env.py`
Expected: exit 0 / no new errors.

```bash
git add backend/alembic/env.py Makefile backend/AGENTS.md
git commit -m "fix(tooling): alembic honors DATABASE_URL; repair make plugin-test; correct AGENTS env path"
```

---

### Task 4: F1 — SetupPage hook order; useFeedSource tolerates undefined ids

**Files:**
- Modify: `frontend/src/api/hooks.ts:109-114` (`useFeedSource`)
- Modify: `frontend/src/features/setup/SetupPage.tsx:11-26`
- Create: `frontend/src/features/setup/SetupPage.test.tsx`

**Interfaces:**
- Consumes: `queryKeys.feedSource(id).detail` from `src/api/queryKeys.ts`.
- Produces: `useFeedSource(id: number | string | undefined)` — disabled while `id` is falsy, stable `feedSource(0).detail` key for the never-fetched case (same convention as `useProductLookup`). Consumed by `SetupPage` (this task); `ExportPage`/`ExportUrlCard` callers pass always-present route params and are behaviorally unchanged.

- [ ] **Step 1: Make `useFeedSource` undefined-tolerant**

Replace `frontend/src/api/hooks.ts:109-114` with:

```typescript
export function useFeedSource(id: number | string | undefined) {
  return useQuery({
    queryKey: queryKeys.feedSource(id ?? 0).detail,
    queryFn: () => apiGet<FeedSourceRow>(`/feed-sources/${id}`),
    enabled: Boolean(id),
  });
}
```

- [ ] **Step 2: Hoist the hook above the early return in SetupPage**

`frontend/src/features/setup/SetupPage.tsx` — move `const feedSource = useFeedSource(feedSourceId);` to directly after the `tab` line, so the top of the component reads:

```tsx
export function SetupPage() {
  const { t } = useTranslation('setup');
  const [searchParams, setSearchParams] = useSearchParams();
  const { feedSourceId } = useParams<{ feedSourceId: string }>();
  const tab = searchParams.get('tab') === 'mapping' ? 'mapping' : 'settings';
  const feedSource = useFeedSource(feedSourceId);

  if (!feedSourceId) {
    return <ErrorState onRetry={() => {}} />;
  }

  if (feedSource.isPending) return <LoadingState />;
  if (feedSource.isError) {
    return <ErrorState onRetry={() => void feedSource.refetch()} />;
  }
```

(Rest of the file unchanged.)

- [ ] **Step 3: Add SetupPage.test.tsx**

Create `frontend/src/features/setup/SetupPage.test.tsx` (harness mirrors `ExportPage.test.tsx:1-66`):

```tsx
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { SetupPage } from './SetupPage';

beforeAll(async () => {
  await i18n.loadNamespaces(['setup', 'common']);
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/clients/:clientId/feeds/:feedSourceId?/setup" element={<SetupPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SetupPage', () => {
  it('renders the error state without fetching when the route param is missing', () => {
    const spy = stubFetch(() => jsonResponse({}));
    renderAt('/clients/1/feeds/setup');
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it('fetches the feed source when the route param is present', async () => {
    const spy = stubFetch((url) => {
      if (url === '/feed-sources/1') {
        return jsonResponse({
          id: 1, client_id: 1, name: 'Feed', source_format: 'xml',
          cron_expression: '0 * * * *', target_country: 'DE', target_language: 'de',
          currency: 'EUR', source_url: null, feed_type: 'full',
          history_retention_count: 30, volume_drop_threshold_pct: 20,
          configuration: {}, export_url: null,
          created_at: '2026-01-01T00:00:00', updated_at: '2026-01-01T00:00:00',
        });
      }
      return jsonResponse({});
    });
    renderAt('/clients/1/feeds/1/setup');
    await waitFor(() => expect(spy).toHaveBeenCalledWith('/feed-sources/1', expect.anything()));
  });
});
```

(`beforeEach(() => notifications.clean())` is not needed here — no toasts; add it if the file later grows mutation tests. `stubFetch`'s exact signature: mirror `src/test/fetch.ts` — if it passes `(url, init)` assert accordingly.)

- [ ] **Step 4: Run the gates**

Run: `cd frontend && npm test -- --run src/features/setup/SetupPage.test.tsx`
Expected: PASS. This is a correctness refactor — the new tests lock the behavior (no fetch without param; fetch with param); the hook-order fix itself is proven by the suite staying green and is statically enforced later by Task 14's react-hooks rule.
Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: all green (`tsc -b` proves the `string | undefined` param flows correctly through `useParams`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/hooks.ts frontend/src/features/setup/SetupPage.tsx frontend/src/features/setup/SetupPage.test.tsx
git commit -m "fix(frontend): SetupPage hook order; useFeedSource tolerates undefined ids"
```

---

### Task 5: F2 — diff area shows the select-versions empty state, not a perpetual spinner

**Files:**
- Modify: `frontend/src/features/export/ExportPage.tsx:94`
- Modify: `frontend/src/features/export/ExportPage.test.tsx` (new test)

**Interfaces:**
- Consumes: `useExportVersionDiff` result — TanStack Query v5 exposes `isFetching` (`fetchStatus === 'fetching'`); a disabled query is `isPending: true, isFetching: false`.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing test**

In `frontend/src/features/export/ExportPage.test.tsx`, add inside the `describe`:

```tsx
  it('shows the select-versions empty state before Compare, not a spinner', async () => {
    stubFetch((url) => {
      if (url === '/feed-sources/1') return jsonResponse(feed);
      if (url === '/feed-sources/1/export-history') return jsonResponse(versions);
      return jsonResponse({});
    });
    renderAt();
    await waitFor(() => expect(screen.getByTestId('version-row-3')).toBeInTheDocument());
    expect(screen.getByText(/select two versions above/i)).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run it — must FAIL**

Run: `cd frontend && npm test -- --run src/features/export/ExportPage.test.tsx`
Expected: FAIL — `getByText(/select two versions above/i)` finds nothing because `ExportVersionDiff` renders `LoadingState` (the disabled query reports `isPending`), and `queryByRole('progressbar')` finds the Loader.

- [ ] **Step 3: Fix the call site**

`frontend/src/features/export/ExportPage.tsx:94` — change:

```tsx
            isPending={diff.isPending}
```

to:

```tsx
            isPending={diff.isPending && diff.isFetching}
```

(`ExportVersionDiff.tsx` is unchanged; the spinner now only renders during an actual fetch.)

- [ ] **Step 4: Run the gates**

Run: `cd frontend && npm test -- --run src/features/export/ExportPage.test.tsx`
Expected: PASS (new test + all existing ExportPage tests).
Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/export/ExportPage.tsx frontend/src/features/export/ExportPage.test.tsx
git commit -m "fix(frontend): export diff shows empty state, not spinner, before Compare"
```

---

### Task 6: F3/U2 — CustomLabelsUI saves surface errors (no silent failures)

**Files:**
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx:237-252` (saveRules/saveIds) + the notifications import
- Modify: `frontend/public/locales/en/customLabels.json`, `frontend/public/locales/de/customLabels.json` (new `saveFailed`)
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx` (new test)

**Interfaces:**
- Consumes: `notifyApiError(error, fallback)` from `src/app/notifications.ts` (re-exported from `notifyApiError.ts` — surfaces the 422 summary/detail toast; returns the field map).
- Produces: `customLabels.saveFailed` key (en+de) — also used by nothing else; Task 10/11 do not touch it.

- [ ] **Step 1: Add the i18n key (en+de, same commit)**

`frontend/public/locales/en/customLabels.json` — after `"configSaved": "Slot rules saved",`:

```json
  "saveFailed": "Could not be saved.",
```

`frontend/public/locales/de/customLabels.json` — after `"configSaved": "Slot-Regeln gespeichert",`:

```json
  "saveFailed": "Konnte nicht gespeichert werden.",
```

- [ ] **Step 2: Write the failing test**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`, add a test inside the existing describe (uses the file's `renderUI(scope, url, fetchHandler, onlyTab)` helper and `jsonResponse`; the rules tab's Add-rule + Save buttons render for a client-scoped UI):

```tsx
  it('toasts and keeps edits when saving rules fails', async () => {
    const user = userEvent.setup();
    renderUI(
      { clientId: 1 },
      '/clients/1/feeds/1/plugins/custom_labels',
      (url, init) => {
        if (init?.method === 'PUT' && url.startsWith('/plugins/custom_labels/config')) {
          return jsonResponse({ detail: 'rules invalid' }, 422);
        }
        return jsonResponseFor(url);
      },
      'rules',
    );
    await user.click(await screen.findByRole('button', { name: /add rule/i }));
    await user.click(await screen.findByRole('button', { name: /^save$/i }));
    expect(await screen.findByText(/rules invalid/i)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /^save$/i })).toBeEnabled();
  });
```

(If `renderUI`'s fetch handler signature differs — check its definition around line 65-90 — adapt the handler to it. If the PUT to config uses `?client_id=1`, the `startsWith('/plugins/custom_labels/config')` prefix still matches.)

- [ ] **Step 3: Run it — must FAIL**

Run: `cd frontend && npm test -- --run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: FAIL — no toast appears; vitest also reports the unhandled rejection from `void saveRules()`.

- [ ] **Step 4: Wrap both saves**

In `frontend/src/features/customLabels/CustomLabelsUI.tsx`, extend the notifications import (find the existing `notifySuccess` import from `'../../app/notifications'` and add `notifyApiError`):

```tsx
import { notifyApiError, notifySuccess } from '../../app/notifications';
```

Replace `saveRules` (lines 237-245) with:

```tsx
  async function saveRules() {
    if (editableTier === null) return;
    const payloadRules = effectiveRules
      .filter((r) => r.origin === editableTier)
      .map(({ origin: _origin, ...rest }) => rest);
    try {
      await saveConfig.mutateAsync({ slotRules: payloadRules });
    } catch (error) {
      notifyApiError(error, t('saveFailed'));
      return;
    }
    setRules(null);
    notifySuccess(t('configSaved'));
  }
```

Replace `saveIds` (lines 247-252) with:

```tsx
  async function saveIds() {
    if (saveDataScope === undefined) return;
    try {
      await saveData.mutateAsync({ slotIds: effectiveIds });
    } catch (error) {
      notifyApiError(error, t('saveFailed'));
      return;
    }
    setSlotIds(null);
    notifySuccess(t('idsSaved'));
  }
```

- [ ] **Step 5: Gates and commit**

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: green (the new test passes; no other test pinned the silent-failure behavior).

```bash
git add frontend/src/features/customLabels/CustomLabelsUI.tsx frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx
git commit -m "fix(frontend): labelizer saves toast on failure instead of silent rejection"
```

---

### Task 7: U1/F10+F11 — honest toasts: rotateFailed + delete success copy

**Files:**
- Modify: `frontend/src/components/ExportUrlBlock.tsx:32-38`
- Modify: `frontend/src/features/dashboard/FeedSourceCard.tsx:66`, `frontend/src/features/dashboard/DeleteClientModal.tsx:23`
- Modify: `frontend/public/locales/en/export.json`, `frontend/public/locales/de/export.json` (`rotateFailed`)
- Modify: `frontend/public/locales/en/dashboard.json`, `frontend/public/locales/de/dashboard.json` (`deleted`)
- Create: `frontend/src/components/ExportUrlBlock.test.tsx`, `frontend/src/features/dashboard/DeleteClientModal.test.tsx`

**Interfaces:**
- Consumes: `notifyMutationError(error, fallback)` (shows `error.detail` when present, else fallback), `ApiError` from `src/api/client.ts`.
- Produces: `export.rotateFailed` and `dashboard.deleted` keys (en+de) — Task 10 adds `export.compareVersions` (de only) in the same file without conflicts (different keys).

- [ ] **Step 1: Add the i18n keys**

`frontend/public/locales/en/export.json` — after `"rotated": "Export token rotated successfully",`:

```json
  "rotateFailed": "Could not rotate the export token.",
```

`frontend/public/locales/de/export.json` — after `"rotated": "Export-Token erfolgreich rotiert",`:

```json
  "rotateFailed": "Export-Token konnte nicht rotiert werden.",
```

`frontend/public/locales/en/dashboard.json` — after `"saved": "Saved",`:

```json
  "deleted": "Deleted",
```

`frontend/public/locales/de/dashboard.json` — after `"saved": "Gespeichert",`:

```json
  "deleted": "Gelöscht",
```

- [ ] **Step 2: Fix ExportUrlBlock's error path**

`frontend/src/components/ExportUrlBlock.tsx:32-38` — replace the whole `onError` (both identical branches) with:

```tsx
      onError: (error) => {
        notifyMutationError(error, t('rotateFailed'));
      },
```

- [ ] **Step 3: Fix the delete success copy**

`frontend/src/features/dashboard/FeedSourceCard.tsx:66` — `notifySuccess(t('saved'));` → `notifySuccess(t('deleted'));`
`frontend/src/features/dashboard/DeleteClientModal.tsx:23` — `notifySuccess(t('saved'));` → `notifySuccess(t('deleted'));`

- [ ] **Step 4: Tests**

Create `frontend/src/components/ExportUrlBlock.test.tsx`:

```tsx
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Notifications, notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../i18n';
import { render } from '../test/render';
import { ExportUrlBlock } from './ExportUrlBlock';
import { ApiError } from '../api/client';

vi.mock('../api/hooks', () => ({
  useRotateExportToken: () => ({
    mutate: (_id: unknown, opts: { onError: (error: unknown) => void }) => {
      opts.onError(new ApiError('Network failed', 0, 'Network failed'));
    },
    isPending: false,
  }),
}));

beforeAll(async () => {
  await i18n.loadNamespaces(['export', 'common']);
});

beforeEach(() => {
  notifications.clean();
});

describe('ExportUrlBlock', () => {
  it('toasts rotateFailed when rotation fails without a server detail', async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Notifications position="top-right" limit={1} />
        <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole('button', { name: /rotate/i }));
    await user.click(await screen.findByRole('button', { name: /rotate/i }));
    expect(await screen.findByText(/could not rotate the export token/i)).toBeInTheDocument();
  });
});
```

(If `ApiError`'s constructor is not `(message, status, detail)`-shaped, check `src/api/client.ts` and construct it accordingly — the test's purpose is an `ApiError` with falsy `detail` so the fallback fires; alternatively pass a plain `new Error('x')`.)
Note: two rotate clicks are needed only if the first opens the ConfirmModal and the second confirms — inspect `ConfirmModal`'s confirm-button name while writing the test and adjust to the actual flow (the modal's confirm button is the one that calls `handleRotate`).

Create `frontend/src/features/dashboard/DeleteClientModal.test.tsx`:

```tsx
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Notifications, notifications } from '@mantine/notifications';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { DeleteClientModal } from './DeleteClientModal';

vi.mock('../../api/hooks', () => ({
  useDeleteClient: () => ({
    mutate: (_id: unknown, opts: { onSuccess: () => void }) => {
      opts.onSuccess();
    },
    isPending: false,
  }),
}));

beforeAll(async () => {
  await i18n.loadNamespaces(['dashboard', 'common']);
});

beforeEach(() => {
  notifications.clean();
});

describe('DeleteClientModal', () => {
  it('toasts the deleted confirmation on success', async () => {
    const user = userEvent.setup();
    render(
      <>
        <Notifications position="top-right" limit={1} />
        <DeleteClientModal
          opened
          client={{ id: 1, name: 'Acme', feed_count: 0, product_count: 0, status: 'active' } as never}
          onClose={() => {}}
        />
      </>,
    );
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /delete/i }));
    expect(await screen.findByText(/^deleted$/i)).toBeInTheDocument();
  });
});
```

(Import `within` from `@testing-library/react`; align the `client` fixture with the `ClientSummary` type from `src/api/types.ts`; if the ConfirmModal has `typeToConfirm`, the fixture's `name` must be typed into the input first — mirror the existing rollback-modal test in `ExportPage.test.tsx:96-101`.)

- [ ] **Step 5: Gates and commit**

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: green. If any existing test asserted the old "Saved"/"rotated" toast on these flows (rg `notifySuccess|t\('saved'\)` in dashboard/export tests), update it in this commit.

```bash
git add frontend/src/components/ExportUrlBlock.tsx frontend/src/components/ExportUrlBlock.test.tsx frontend/src/features/dashboard/FeedSourceCard.tsx frontend/src/features/dashboard/DeleteClientModal.tsx frontend/src/features/dashboard/DeleteClientModal.test.tsx frontend/public/locales/en/export.json frontend/public/locales/de/export.json frontend/public/locales/en/dashboard.json frontend/public/locales/de/dashboard.json
git commit -m "fix(frontend): honest toasts for token rotation failures and delete success"
```

---

### Task 8: F5+F4 — admin area: toggle errors surfaced; client_ids null-safety

**Files:**
- Modify: `frontend/src/features/admin/AdminSettingsPage.tsx:104-130` (plugin toggle) + imports
- Modify: `frontend/src/features/admin/AdminUsersPage.tsx:85,150` (null guards) + the `AdminUser` type if locally declared (else `src/api/types.ts`)
- Create: `frontend/src/features/admin/AdminSettingsPage.test.tsx`

**Interfaces:**
- Consumes: `pipeline.disableBlocked` i18n key (en+de, added in the m11b cycle — reused with `{count}`), `notifyError`/`notifyMutationError` from `src/app/notifications.ts`, `ApiError` from `src/api/client.ts`, `PluginInfo.used_by_feed_sources` from `usePlugins()` data.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the error path to the admin plugin toggle**

In `frontend/src/features/admin/AdminSettingsPage.tsx`: extend imports with `useTranslation('pipeline')` (add `const { t: tPipeline } = useTranslation('pipeline');` inside the component), import `ApiError` and `notifyError`. Replace the Switch `onChange` (lines 120-124) with:

```tsx
                <Switch
                  aria-label={t('settings.pluginEnabled')}
                  checked={plugin.enabled}
                  onChange={(event) =>
                    updatePluginEnabled.mutate(
                      { id: plugin.id, enabled: event.currentTarget.checked },
                      {
                        onError: (error) => {
                          if (error instanceof ApiError && error.status === 409) {
                            notifyError(
                              tPipeline('disableBlocked', {
                                count: plugin.used_by_feed_sources,
                              }),
                            );
                          } else {
                            notifyMutationError(error, t('settings.saveFailed'));
                          }
                        },
                      },
                    )
                  }
                />
```

- [ ] **Step 2: Null-guard client_ids in AdminUsersPage**

In `frontend/src/features/admin/AdminUsersPage.tsx:85` change `{user.client_ids.length}` to `{user.client_ids?.length ?? 0}` and at `:150` change `user.client_ids.map(String)` to `(user.client_ids ?? []).map(String)`. If `AdminUser` is declared with `client_ids: number[]`, change it to `client_ids: number[] | null` (matching the session `User` type in `src/api/client.ts`).

- [ ] **Step 3: Test the admin toggle error path**

Create `frontend/src/features/admin/AdminSettingsPage.test.tsx` (mock the hooks; assert the 409 toast uses the cached count):

```tsx
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Notifications, notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { AdminSettingsPage } from './AdminSettingsPage';
import { ApiError } from '../../api/client';

vi.mock('../../api/hooks', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useAdminSettings: () => ({
    data: {
      staging_removal_retention_days: 90,
      staging_history_retention_days: 90,
      ingestion_run_retention_days: 90,
    },
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useSchedulerJobs: () => ({ data: [], isPending: false, isError: false, refetch: vi.fn() }),
  usePlugins: () => ({
    data: [{ id: 'filter', name: 'Filter', version: '1.0.0', enabled: true, manifest: {}, used_by_feed_sources: 2 }],
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useUpdatePluginEnabled: () => ({
    mutate: (_payload: unknown, opts: { onError: (error: unknown) => void }) => {
      opts.onError(new ApiError('plugin in use by 2 feed sources', 409, 'plugin in use by 2 feed sources'));
    },
    isPending: false,
  }),
  useSaveAdminSettings: () => ({ mutate: vi.fn(), isPending: false }),
}));

beforeAll(async () => {
  await i18n.loadNamespaces(['admin', 'pipeline', 'plugins']);
});

beforeEach(() => {
  notifications.clean();
});

describe('AdminSettingsPage', () => {
  it('toasts disableBlocked with the cached count on a 409', async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Notifications position="top-right" limit={1} />
        <AdminSettingsPage />
      </QueryClientProvider>,
    );
    const toggle = await screen.findByRole('switch');
    await user.click(toggle);
    expect(await screen.findByText(/in use by 2 feed sources/i)).toBeInTheDocument();
  });
});
```

(Align the `ApiError` constructor and the `en/pipeline.json` `disableBlocked` wording with the actual files; the pipeline key is the m11b one — the toast text must match its en value.)

- [ ] **Step 4: Gates and commit**

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: green.

```bash
git add frontend/src/features/admin/AdminSettingsPage.tsx frontend/src/features/admin/AdminSettingsPage.test.tsx frontend/src/features/admin/AdminUsersPage.tsx
git commit -m "fix(frontend): admin plugin toggle errors surface; null-safe client_ids"
```

---

### Task 9: F8+F9 — FeedSettingsForm numeric inputs and cron-preset labels

**Files:**
- Modify: `frontend/src/features/setup/FeedSettingsForm.tsx:168-177` (preset Select), `:205-227` (two numeric fields)
- Modify: `frontend/public/locales/en/setup.json`, `frontend/public/locales/de/setup.json` (`cron.presetsLabel`, `cron.presetsPlaceholder`)
- Modify: `frontend/src/features/setup/FeedSettingsForm.test.tsx` (assertions)

**Interfaces:**
- Consumes: Mantine `NumberInput` (pattern already used in `AdminSettingsPage.tsx:42-59`), the existing `cron` section in `setup.json`.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the i18n keys**

In `frontend/public/locales/en/setup.json` inside the `"cron"` object (line ~43):

```json
    "presetsLabel": "Common schedules",
    "presetsPlaceholder": "Pick a schedule"
```

In `frontend/public/locales/de/setup.json` inside `"cron"`:

```json
    "presetsLabel": "Häufige Zeitpläne",
    "presetsPlaceholder": "Zeitplan wählen"
```

- [ ] **Step 2: Fix the preset Select (F9)**

`frontend/src/features/setup/FeedSettingsForm.tsx:168-177` — replace:

```tsx
        <Select
          label={t('cron.utcHint')}
          data={cronPresets}
          placeholder={t('fields.cronExpression')}
```

with:

```tsx
        <Select
          label={t('cron.presetsLabel')}
          data={cronPresets}
          placeholder={t('cron.presetsPlaceholder')}
```

(rest of the props unchanged).

- [ ] **Step 3: Replace the numeric TextInputs with NumberInputs (F8)**

`frontend/src/features/setup/FeedSettingsForm.tsx:205-227` — the two `form.Field` blocks become:

```tsx
        <form.Field name="volume_drop_threshold_pct">
          {(field) => (
            <NumberInput
              label={t('fields.volumeDropThreshold')}
              min={0}
              max={100}
              value={field.state.value}
              onChange={(v) => field.handleChange(Number(v) || 0)}
            />
          )}
        </form.Field>
        <form.Field name="history_retention_count">
          {(field) => (
            <NumberInput
              label={t('fields.historyRetention')}
              min={1}
              value={field.state.value}
              onChange={(v) => field.handleChange(Math.max(Number(v) || 1, 1))}
            />
          )}
        </form.Field>
```

(Add `NumberInput` to the `@mantine/core` import and drop `TextInput` from the import only if no other field still uses it. This kills the `NaN`/`Number('')===0` paths: Mantine hands us `number | ''`, the `|| 0` / `|| 1` clamps make the payload always a valid integer, and retention can never be 0 — which also closes the B6 edge on the client side.)

- [ ] **Step 4: Update tests**

In `frontend/src/features/setup/FeedSettingsForm.test.tsx`: extend/adjust per existing style — assert the preset Select renders the new label (`common schedules`), and that submitting after clearing the retention field sends `history_retention_count: 1` (not 0/NaN/null). If a test stubs the numeric `TextInput` role, retarget `spinbutton` (Mantine NumberInput's role).

- [ ] **Step 5: Gates and commit**

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: green.

```bash
git add frontend/src/features/setup/FeedSettingsForm.tsx frontend/src/features/setup/FeedSettingsForm.test.tsx frontend/public/locales/en/setup.json frontend/public/locales/de/setup.json
git commit -m "fix(frontend): NumberInput clamps for retention/threshold; correct cron preset labels"
```

---

### Task 10: U3+U4+U7+U8+U9 — German i18n pass: missing keys, Sie register, grammar

**Files:**
- Modify: `frontend/public/locales/de/notifications.json` (3 keys), `frontend/public/locales/de/export.json` (`compareVersions`), `frontend/public/locales/de/customLabels.json` (8 value rewrites)
- Modify: any tests pinning the old German strings (found via the Step-4 grep)

**Interfaces:**
- Consumes: nothing from earlier tasks. Task 11 builds on this task's `labeledOf` wording (stated below).
- Produces: en/de key parity for `notifications` and `export`; Sie-form customLabels copy.

- [ ] **Step 1: de/notifications.json — add the 3 auto-mapper keys**

```json
{
  "runFinished": "Lauf abgeschlossen",
  "runFailed": "Lauf fehlgeschlagen",
  "mutationSuccess": "Gespeichert",
  "mutationError": "Anfrage fehlgeschlagen",
  "validationError": "Bitte korrigieren Sie die markierten Felder.",
  "autoMappingRunning": "Automatische Zuordnung läuft…",
  "autoMappingDone": "Automatische Zuordnung abgeschlossen",
  "autoMappingFailed": "Automatische Zuordnung fehlgeschlagen"
}
```

- [ ] **Step 2: de/export.json — add `compareVersions`**

After `"selectVersions": "Wählen Sie oben zwei Versionen aus, um den Diff zu sehen.",` insert:

```json
  "compareVersions": "Versionen vergleichen",
```

- [ ] **Step 3: de/customLabels.json — rewrites (du→Sie, grammar, Denglisch)**

Apply exactly these value replacements (keys unchanged):

| Key | New value |
|---|---|
| `idsUnavailable` | `"Bulk-ID-Listen leben auf Client- oder Feed-Source-Ebene. Öffnen Sie dieses Plugin über einen Client oder eine Feed-Source, um sie zu verwalten."` |
| `noStagedProducts` | `"Noch keine Produkte im Staging — zuerst die Pipeline ausführen."` |
| `deleteConfirmBody` | `"Regel \"{{name}}\" löschen? Sie lässt sich bis zum Speichern über Abbrechen wiederherstellen."` |
| `deleteGlobalWarning` | `"Regel \"{{name}}\" löschen? Sie wird von allen Mandanten geerbt — das Löschen betrifft alle. Sie lässt sich bis zum Speichern über Abbrechen wiederherstellen."` |
| `unsavedChanges` | `"Sie haben ungespeicherte Änderungen. Trotzdem verlassen?"` |
| `matchMode.all` | `"Alle Produkte zuordnen"` |
| `howItWorks.templates.answer` | `"Verwenden Sie {field}-Tokens wie {brand} - Mid Funnel. Löst ein Token leer auf, wird die Regel übersprungen; eine Fallback-Vorlage deckt diesen Fall ab."` |
| `coverage.labeledOf` | `"{{count}} / {{total}} Produkte im Staging gelabelt"` (Task 11 converts this key to `_one`/`_other` carrying this wording) |

`"Mandanten"` in `deleteGlobalWarning` stays as-is (U10 terminology is an operator decision).

- [ ] **Step 4: Find and update pinned assertions**

Run: `rg -n "Öffne dieses|Du hast|kannst du|gestagte|gestagten|Alle Produkte treffen|Verwende \{field\}|1 Warnungen|matcht Produkte" frontend/src`
Expected: matches only in locale JSON (and possibly test assertions); update any test asserting the old strings to the new ones. Nothing in `en` changes.

- [ ] **Step 5: Parity check and gates**

Run: `node -e "const fs=require('fs');for(const ns of ['notifications','export','customLabels']){const flat=(o,p='')=>Object.entries(o).flatMap(([k,v])=>typeof v==='object'?flat(v,p+k+'.'):[p+k]);const en=flat(JSON.parse(fs.readFileSync('frontend/public/locales/en/'+ns+'.json'))).sort();const de=flat(JSON.parse(fs.readFileSync('frontend/public/locales/de/'+ns+'.json'))).sort();console.log(ns, en.length===de.length?'PARITY':'MISMATCH', en.filter(k=>!de.includes(k)).join(','), de.filter(k=>!en.includes(k)).join(','))}"`
Expected: `notifications PARITY`, `export PARITY`, `customLabels PARITY`.
Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add frontend/public/locales/de/notifications.json frontend/public/locales/de/export.json frontend/public/locales/de/customLabels.json
git commit -m "fix(i18n): missing de keys; customLabels German copy to Sie register, grammar fixes"
```

(plus any test files from Step 4)

---

### Task 11: U15 (+TODO 9.1) — plural forms for the visible-noun count keys

**Files:**
- Modify: `frontend/public/locales/en/customLabels.json`, `frontend/public/locales/de/customLabels.json` (`idCount`, `coverage.labeledOf`, `shadowedCount`, `matchedCount`)
- Modify: `frontend/public/locales/en/export.json`, `frontend/public/locales/de/export.json` (`findings.critical/warning/info`, `fieldsChanged`)
- Modify: `frontend/src/features/export/ExportPage.test.tsx:128` and any other pinned assertions (Step 3 grep)

**Interfaces:**
- Consumes: the i18next `_one`/`_other` plural pattern already shipped for `activeRulesCount` and `nProducts` in the same files; Task 10's `labeledOf` wording.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: customLabels plural keys**

In **en** `customLabels.json` replace `"idCount": "{{count}} unique IDs",` with:

```json
  "idCount_one": "{{count}} unique ID",
  "idCount_other": "{{count}} unique IDs",
```

replace `"labeledOf": "{{count}} / {{total}} staged products labeled",` (inside `coverage`) with:

```json
    "labeledOf_one": "{{count}} / {{total}} staged product labeled",
    "labeledOf_other": "{{count}} / {{total}} staged products labeled",
```

replace `"shadowedCount": "{{count}} overridden",` with:

```json
  "shadowedCount_one": "{{count}} overridden",
  "shadowedCount_other": "{{count}} overridden",
```

replace `"matchedCount": "{{count}} matched",` with:

```json
  "matchedCount_one": "{{count}} match",
  "matchedCount_other": "{{count}} matched",
```

In **de** `customLabels.json` replace `"idCount": "{{count}} eindeutige IDs",` with:

```json
  "idCount_one": "{{count}} eindeutige ID",
  "idCount_other": "{{count}} eindeutige IDs",
```

replace `"labeledOf": "{{count}} / {{total}} Produkte im Staging gelabelt",` with:

```json
    "labeledOf_one": "{{count}} / {{total}} Produkt im Staging gelabelt",
    "labeledOf_other": "{{count}} / {{total}} Produkte im Staging gelabelt",
```

replace `"shadowedCount": "{{count}} überschrieben",` with:

```json
  "shadowedCount_one": "{{count}} überschrieben",
  "shadowedCount_other": "{{count}} überschrieben",
```

replace `"matchedCount": "{{count}} Treffer",` with:

```json
  "matchedCount_one": "{{count}} Treffer",
  "matchedCount_other": "{{count}} Treffer",
```

(Structural parity keeps count-invariant German values as duplicated `_one`/`_other` pairs — same convention the existing `activeRulesCount` uses.)

- [ ] **Step 2: export plural keys**

In **en** `export.json` replace the `"findings"` object and `"fieldsChanged"` with:

```json
  "findings": {
    "critical_one": "{{count}} critical",
    "critical_other": "{{count}} critical",
    "warning_one": "{{count}} warning",
    "warning_other": "{{count}} warnings",
    "info_one": "{{count}} info",
    "info_other": "{{count}} info"
  },
```

```json
  "fieldsChanged_one": "{{count}} field changed",
  "fieldsChanged_other": "{{count}} fields changed",
```

In **de** `export.json`:

```json
  "findings": {
    "critical_one": "{{count}} kritisch",
    "critical_other": "{{count}} kritisch",
    "warning_one": "{{count}} Warnung",
    "warning_other": "{{count}} Warnungen",
    "info_one": "{{count}} Hinweis",
    "info_other": "{{count}} Hinweise"
  },
```

```json
  "fieldsChanged_one": "{{count}} Feld geändert",
  "fieldsChanged_other": "{{count}} Felder geändert",
```

- [ ] **Step 3: Update pinned test assertions**

`frontend/src/features/export/ExportPage.test.tsx:128` — change:

```tsx
    expect(screen.getByTestId('findings-warning-3')).toHaveAttribute('aria-label', '0 warning');
```

to:

```tsx
    expect(screen.getByTestId('findings-warning-3')).toHaveAttribute('aria-label', '0 warnings');
```

(count=0 resolves to `_other` in both en and de, so `2 critical` / `5 info` assertions are unchanged.)
Run: `rg -n "unique IDs|eindeutige IDs|field\(s\)|Feld\(er\)|\{\{count\}\} Treffer|\{\{count\}\} match" frontend/src`
Expected: locale JSON only (plus tests to update). Update any test pinning the old single-key strings; en locale values like "1 match" now render via `matchedCount_one`.

- [ ] **Step 4: Parity + gates**

Run the Task 10 Step 5 parity check extended to all touched namespaces.
Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json frontend/public/locales/en/export.json frontend/public/locales/de/export.json frontend/src/features/export/ExportPage.test.tsx
git commit -m "fix(i18n): plural forms for visible-noun count keys (en+de)"
```

(plus any other test files from Step 3)

---

### Task 12: D1+D9+D10+D15/T9 — pivot-point docs: RJSF, Rolldown, proxy list

**Files:**
- Modify: `docs/decisions/0002-schema-renderer-rjsf.md` (superseded status note)
- Modify: `docs/decisions/0003-rolldown-optional-evaluation.md` (status note)
- Modify: `frontend/docs/architecture.md:7` (stack line)
- Modify: `frontend/docs/plugin-uis.md` (RJSF/AJV mentions)
- Modify: `backend/docs/plugins.md:173` ("(RJSF)" suffix)
- Modify: `AGENTS.md` and `frontend/AGENTS.md` (doc-map line for plugin-uis)
- Modify: `README.md:64` (proxy list)

**Interfaces:**
- Consumes: the review evidence in `docs/reports/2026-09-08-06-docs-consistency.md` (D1, D9, D10, D15).
- Produces: doc statements consistent with `frontend/package.json` (no `@rjsf/*`; vite 8.2.2) — verified in Step 3.

- [ ] **Step 1: Amend ADR-0002**

Append at the end of `docs/decisions/0002-schema-renderer-rjsf.md`:

```markdown

## Status: Superseded (2026-09-08)

RJSF was never installed. The shipped renderer is a custom Mantine-themed
`JsonSchemaForm` (`frontend/src/components/JsonSchemaForm.tsx`, no `@rjsf/*`
and no AJV dependency); payload validation happens server-side against the
plugin manifest's JSON Schema. The "Rejected Alternative" above is what
shipped. See `frontend/docs/plugin-uis.md` for the current rendering story.
```

- [ ] **Step 2: Amend ADR-0003**

Append at the end of `docs/decisions/0003-rolldown-optional-evaluation.md`:

```markdown

## Status: Completed (2026-09-08)

Rolldown became the production bundler via the Vite 8.2.2 upgrade
(`build.rolldownOptions.output.codeSplitting.groups` for vendor chunks;
`manualChunks` no longer exists). The evaluation criteria passed — this ADR's
rollback path ("remove rolldownOptions") is moot; see `docs/decisions.md`
2026-08-30 for the chunking-strategy entry.
```

- [ ] **Step 3: Fix the stack line and RJSF/AJV mentions**

`frontend/docs/architecture.md:7` — replace the "Vite 6 (esbuild dev, Rollup prod)" wording with: `Vite 8 (Rolldown bundler; vendor chunks via build.rolldownOptions.output.codeSplitting.groups)`.
`frontend/docs/plugin-uis.md` — replace the RJSF mention (~line 37) and the AJV line (~line 58) with the custom-renderer description (`JsonSchemaForm`, server-side schema validation). Read both lines first and keep the surrounding doc structure.
`backend/docs/plugins.md:173` — `JsonSchemaForm (RJSF)` → `JsonSchemaForm (custom Mantine renderer)`.
Root `AGENTS.md` doc map and `frontend/AGENTS.md` doc map — `RJSF schema rendering` → `custom JsonSchemaForm schema rendering`.
`README.md:64` — replace the proxy sentence with: `The Vite development server proxies the backend API prefixes (/admin, /auth, /health, /clients, /feed-sources, /dashboard, /plugins, /registry, /export) to the backend.`

- [ ] **Step 4: Consistency verification**

Run: `rg -n "RJSF|AJV|rjsf" AGENTS.md frontend/AGENTS.md backend/AGENTS.md README.md docs/decisions/000*.md frontend/docs backend/docs`
Expected: hits only in ADR-0002's historical decision text and its new superseded note (history stays), and nowhere prescriptive.
Run: `rg -n "manualChunks|esbuild dev|Rollup prod" frontend/docs README.md docs/decisions/000*.md`
Expected: ADR-0003 historical text + the new note only.

- [ ] **Step 5: Commit**

```bash
git add docs/decisions/0002-schema-renderer-rjsf.md docs/decisions/0003-rolldown-optional-evaluation.md frontend/docs/architecture.md frontend/docs/plugin-uis.md backend/docs/plugins.md AGENTS.md frontend/AGENTS.md README.md
git commit -m "docs: mark RJSF ADR superseded, Rolldown adopted; fix stack lines and proxy list"
```

---

### Task 13: D4–D8, D11–D16 — data-model.md + api.md + makefile.md refresh

**Files:**
- Modify: `backend/docs/data-model.md` (Session, ExportVersion, StagingHistory, IngestionRun, ExportRun, User, Client, PluginConfig/PluginData sections)
- Modify: `backend/docs/api.md` (remove phantom endpoints; add `/feed-sources/{id}/fields`)
- Modify: `docs/makefile.md` (Caddy targets)

**Interfaces:**
- Consumes: `docs/reports/2026-09-08-06-docs-consistency.md` findings D4–D8, D11–D16 (each carries doc-claim vs code evidence) — the implementing agent reads that report plus the model/route sources below.
- Produces: docs that match code, verified column-by-column in Step 4.

- [ ] **Step 1: data-model.md corrections**

Ground truth: `backend/app/models/session.py`, `export.py`, `staging.py`, `ingestion.py`, `user.py`, `client.py`, `plugin.py`, `user_client.py`. Apply the D-list:
- **Session (D4):** rewrite the table — Integer PK, `token_hash` (hashed, not raw token), `last_interaction_at`, `idle_expires_at`, `absolute_expires_at`, `revocation_generation`, `revoked_at`, `user_id` FK.
- **ExportVersion (D5):** drop `xml_path`; document `file_hash`, `product_count`, `source` (values `run`/`rollback` — the 3-value enum question is open as TODO 2.2), `source_version_id` (SET NULL).
- **StagingHistory (D6):** `created_at` → `recorded_at`.
- **IngestionRun (D12):** add `pending` to the status enum (created by the manual trigger's 202; reconciled to `error` "interrupted by restart" at startup).
- **ExportRun (D13):** add `status`, `options` JSONB, `started_at`, `completed_at`; note `ingestion_run_id`/`export_version_id` nullability (90-day purge NULLs `ingestion_run_id`).
- **User (D14):** `password_hash` is `String(512)`; document `role`, `is_active`, `user_clients` join.
- **Client (D14):** add `settings` JSONB, `contact_details`, `updated_at` if present in the model (read it).
- **PluginConfig/PluginData (D14):** drop the "identical structure incl. `created_at`" claim — PluginConfig has no `created_at`; PluginData does.

- [ ] **Step 2: api.md corrections**

- Remove `GET /clients/{id}` (D7 — does not exist; `routes/clients.py` has list/create/update/delete only).
- Remove `POST /registry/generate` (D8) and document the CLI: `cd backend && uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json` (as README does).
- Add `GET /feed-sources/{id}/fields` (D11) to the Products section (returns source field list for the column picker / preview extraFields).
- While editing, cross-check every documented route path against the `@router` decorators in `backend/app/routes/*.py` and add any other undocumented route found (the docs report's endpoint appendix lists none beyond the above as of 2026-09-08).

- [ ] **Step 3: makefile.md — add the Caddy targets (D16)**

Add a short section documenting `make prod` (Caddy production; requires `DOMAIN`/`BACKEND_URL`; `Caddyfile`) and `make dev-caddy` (Caddy dev, `Caddyfile.dev`, no TLS) mirroring the Makefile's own `##` target descriptions (lines 141-147).

- [ ] **Step 4: Verification**

Run: `rg -n "xml_path|last_accessed_at|created_at.*StagingHistory|POST /registry/generate|GET /clients/\{id\}" backend/docs`
Expected: no hits. Read the refreshed sections side-by-side with the model files; every documented column must exist in the model and vice versa (spot-check Session and ExportVersion exhaustively).

- [ ] **Step 5: Commit**

```bash
git add backend/docs/data-model.md backend/docs/api.md docs/makefile.md
git commit -m "docs: refresh data-model and api reference to match code; makefile Caddy targets"
```

---

### Task 14: T7 — frontend eslint adoption (OPERATOR APPROVAL: new devDependencies)

> **STATUS 2026-09-09: BLOCKED — not executed.** `typescript-eslint@8.70.0` hard-fails at import on the repo's `typescript 7.0.2` pin (TS 7's native package ships no JS AST API; tracking issue typescript-eslint/typescript-eslint#10940; plain eslint cannot parse TS syntax, so partial adoption is impossible). Attempted and reverted; evidence and fallbacks in TODO 9A.14. Re-run this task verbatim once typescript-eslint supports TS ≥7.1.

**OPERATOR APPROVAL:** adds eslint + plugins to `frontend/package.json` devDependencies (needed for the Task 4 hook-order class to be statically enforced). Droppable without affecting other tasks; do NOT run in the same commit as any other task.

**Files:**
- Modify: `frontend/package.json` (devDependencies + `lint` script)
- Create: `frontend/eslint.config.js`
- Modify: `.github/workflows/ci.yml` (frontend job: lint step)
- Modify: `frontend/AGENTS.md` (add `npm run lint` to the HOW block)

**Interfaces:**
- Consumes: nothing from earlier tasks (but Task 4 already removed the known rules-of-hooks violation; this task proves it and locks it).
- Produces: `npm run lint` (consumed by the CI gate matrix; AGENTS.md frontend gate list).

- [ ] **Step 1: Install**

Run: `cd frontend && npm install -D eslint @eslint/js typescript-eslint eslint-plugin-react-hooks eslint-plugin-react-refresh globals`
Expected: devDependencies added; `package-lock.json` updated. Then normalize `package.json`: the repo pins exact versions (no `^` ranges — see every existing dep), so strip carets from the six new devDependency entries to the exact installed versions (`npm ls eslint` etc. to confirm).

- [ ] **Step 2: Create `frontend/eslint.config.js`**

```javascript
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';

export default tseslint.config(
  { ignores: ['dist', 'coverage'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.browser },
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': 'warn',
      '@typescript-eslint/no-unused-vars': 'warn',
      'no-unused-vars': 'off',
    },
  },
);
```

(`rules-of-hooks` and `exhaustive-deps` stay errors — correctness class; unused-vars demoted to warn so the first run is a baseline, not a wall.)

- [ ] **Step 3: Add the lint script with a warnings baseline**

Run: `cd frontend && npx eslint src; echo "exit=$?"`
Read the summary line (`✖ X problems (0 errors, N warnings)`) and use `N` as the baseline, then add to `frontend/package.json` scripts:

```json
    "lint": "eslint src --max-warnings N"
```

(replace `N` with the captured number; note it in `docs/decisions.md` later — Task 15 records the convention: warnings must not grow; errors must stay zero).

Run: `npm run lint`
Expected: exit 0 with `N` warnings, zero errors. If `react-hooks/rules-of-hooks` reports any violation, fix it (expected: none — Task 4 removed the one known instance; if one appears, that finding goes back to the controller as a plan deviation).

- [ ] **Step 4: CI step**

In `.github/workflows/ci.yml`, frontend job, before the test step:

```yaml
      - name: Lint frontend
        working-directory: frontend
        run: npm run lint
```

- [ ] **Step 5: AGENTS.md + gates + commit**

In `frontend/AGENTS.md` HOW block add `npm run lint` after the test line (and mention the warnings-baseline convention in one sentence).
Run: `cd frontend && npm run lint && npm test -- --run && npm run typecheck && npm run build`
Expected: all green.

```bash
git add frontend/package.json frontend/package-lock.json frontend/eslint.config.js frontend/AGENTS.md .github/workflows/ci.yml
git commit -m "chore(frontend): adopt eslint with react-hooks rules and warnings baseline"
```

---

### Task 15: Bookkeeping — TODO.md cycle log, 9.1 reconciliation, deferred-findings filing, decisions.md

**Files:**
- Modify: `TODO.md`
- Modify: `docs/decisions.md`

**Interfaces:**
- Consumes: everything above (the cycle's landed commits) plus `docs/reports/2026-09-08-*.md`.
- Produces: an accurate backlog for the next agent (repo convention).

- [ ] **Step 1: TODO.md — add a "Review remediation" section**

Following the file's existing style (checkbox items with priority tags), add a section listing the deferred findings as new P2 backlog items, each one line with its report ID:

- [x] U5 products-table keyboard/row activation path (a11y, Important) — `docs/reports/2026-09-08-04-ux-i18n.md`
- [x] U6 raw enum values in tables/filters (translate via existing keys) — same report
- [x] U12 NotFound route instead of silent redirect — same report
- [x] U11 disabled-nav tooltip when no feed source selected — same report
- [x] U14 ProductDrawer dayjs locale + `drawerRawData` key — same report
- [x] U16 ConfirmModal for unsaved-changes guards (replace `window.confirm`) — same report
- [x] U17 i18n a11y labels (pagination, user menu) — same report
- [x] U18 localized lead-in for raw server error details — same report
- [x] F6 ProductsPage state reset on feed-source change; F13 deep-link page strip; F14 usePreview deps/unmount; F15 toggle rollback scope; F16 ProductsTable dead code; F17 raw_data heading; F18 MonitoringLayout dead code — `docs/reports/2026-09-08-03-frontend.md`
- T6 Caddyfile parameterized document root; T11 compose restart policy; T12 Caddy encode/headers; T13 engines field + committed .nvmrc — `docs/reports/2026-09-08-05-tooling.md`
- Operator questions: enable/disable toggle admin-gating (B1 follow-up), U10 terminology pick, TODO 2.2 source enum

Also reconcile **TODO 9.1**: `slotLabeled` and `freshnessHint` no longer exist (removed by the 2026-09-08 rule-card refactor); the remaining keys were pluralized by Task 11 — mark 9.1 complete with a Done note naming Task 11's commit.

- [ ] **Step 2: TODO.md cycle log**

Prepend a cycle-log entry (date, branch `main`, head commit) in the established style summarizing: this plan's tasks, the operator-approval flags honored (ruff, eslint), gates run (backend/frontend numbers), and the leftover notes (eslint warnings baseline `N`, ruff/mypy baseline counts at landing).

- [ ] **Step 3: docs/decisions.md**

Append a dated entry recording: (1) B1 fix semantics — global plugin tier is admin-only, scoped users 403; single-user mode unaffected; (2) CI baseline-gate design (count files, flip-to-exit-0 at zero, mypy-baseline.md sync duty); (3) eslint adoption + warnings-baseline convention; (4) the B6 non-action (API `ge=1` already enforced — `app/schemas/clients.py:49`) and the B3/T10 refutations with one-line evidence each (pointer to the review reports).

- [ ] **Step 4: Gates and commit**

Run: `rg -n "slotLabeled|freshnessHint" frontend/src frontend/public` → expected: no hits (sanity for the 9.1 note).
Run both suites one final time (sequential).
```bash
git add TODO.md docs/decisions.md
git commit -m "docs: review remediation cycle log; file deferred findings; reconcile 9.1"
```

---

## Deferred findings (explicitly out of scope for this cycle)

Filed into `TODO.md` by Task 15 with report references — not silently dropped:

- **U5, U6, U11, U12, U14, U16, U17, U18** (UX) — small UX/a11y additions; U5/U6 deserve their own focused task with interaction design, not a drive-by. **DONE 2026-09-09.**
- **F6, F13, F14, F15, F16, F17, F18** (frontend Minors) — F16/F17 are mechanical and could be pulled into Task 9 opportunistically if the reviewer approves; F18 needs a delete-or-wire decision. **DONE 2026-09-09.**
- **T6, T11, T12, T13** (deployment hardening) — Caddy/compose production hardening; owner-operated surface. **DONE 2026-09-09.**
- **B3, T10** — REFUTED on verification (see reports); recorded in decisions.md by Task 15 to prevent re-reporting.
- **B6** — moot: `history_retention_count` is already `Field(ge=1)` at the API (`backend/app/schemas/clients.py:49`); Task 9 closes the client-side 0/NaN path. The `max(retention, 1)` clamp stays as defense.
- **D2, D3** — operator spec amendments (flagged in the plan header and reports; not agent-fixable).
- **U10** — operator terminology decision ("Mandant" vs "Kunde"). **DONE 2026-09-09.**
- **TODO 2.2 / 5.1 / 8.1 / 9.2–9.6 / 10.1** — pre-existing backlog items unchanged by this cycle (10.1 gets CI-enforced by Task 2; the fix work remains).

## Self-review (completed by plan author)

- **Coverage:** B1→T1(+B7), T1/T2→T2, T3/T4/T5→T3, F1→T4, F2→T5, F3/U2→T6, U1/F10+F11→T7, F5+F4→T8, F8+F9→T9, U3/U4/U7/U8/U9→T10, U15→T11, D1/D9/D10/D15→T12, D4-D8/D11-D16→T13, T7→T14, bookkeeping→T15. Every overview top-10 item maps to a task; the refuted/moot items (B3, B6, T10) are explicitly dispositioned. Gaps: none for in-scope findings.
- **Placeholder scan:** every code step carries complete code or an exact command with expected output; the two "align with the actual file" notes (ExportUrlBlock test's ApiError constructor, CustomLabelsUI test's renderUI handler signature) are verification instructions against named files, not deferred work.
- **Type consistency:** `useFeedSource(id: number | string | undefined)` in Task 4 matches the `useParams` type; `CurrentUser`/`get_current_user` names in Task 1 match `backend/app/access.py`; i18n key names (`saveFailed`, `rotateFailed`, `deleted`, `presetsLabel`, `presetsPlaceholder`, `compareVersions`, `autoMapping*`) are used identically in the code steps and locale steps.
