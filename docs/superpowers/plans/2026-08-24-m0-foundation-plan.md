# M0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the M0 repository foundation and a tested single-operator FastAPI/React login/logout slice with an interface-backed in-process session store.

**Architecture:** The backend is a FastAPI application factory with environment-backed settings and an auth service that depends only on a `SessionStore` protocol. M0 implements that protocol in memory, signs opaque cookie tokens with an environment secret, and exposes explicit interaction renewal separately from non-renewing reads. The frontend is a Vite React 19 TypeScript app with local React state, and CI verifies both projects while PostgreSQL runs as the only Dockerized service.

**Tech Stack:** Python with FastAPI, Pydantic Settings, pytest, and HTTPX/TestClient; PostgreSQL in Docker Compose; React 19.2.7 + TypeScript + Vite; Vitest + React Testing Library; GitHub Actions; `uv` and npm lockfiles.

## Global Constraints

- Implement M0 only: repository/tooling, CI, Docker PostgreSQL, FastAPI skeleton, Vite/React skeleton, and session login; do not implement business schema or later pipeline milestones.
- The backend and frontend run natively on the host; PostgreSQL is the only containerized component.
- The session logic must depend on `SessionStore.create`, `SessionStore.validate`, and `SessionStore.invalidate`; PostgreSQL persistence is a named M1 deliverable.
- M0's in-process session store supports one backend process and one worker; restart invalidates all sessions.
- The session secret comes from the environment; session data is never serialized into the cookie.
- Cookies must be `HttpOnly`, `Secure`, `SameSite=Lax`, and capped at the absolute session lifetime.
- `SESSION_IDLE_MINUTES` defaults to `30`; `SESSION_ABSOLUTE_HOURS` defaults to `12`; both are configurable.
- Idle expiry is sliding only for explicit user interactions. Automated status/finding polling and other read endpoints must not renew it.
- The absolute expiry is a hard cap and is never renewed.
- The initial operator is seeded from environment variables; M0 has one operator and no roles.
- Frontend client state uses React built-ins only; do not add a global store library.
- Every dependency must be pinned to an exact version in its lockfile and recorded in `docs/decisions.md` when first introduced.
- Every implementation task follows RED-GREEN-REFACTOR and ends with a focused verification command and a commit.

---

## File Map

Files created by this plan and their single responsibilities:

- `backend/pyproject.toml`: backend metadata, exact dependency pins, and test/lint commands.
- `backend/uv.lock`: reproducible Python dependency resolution.
- `backend/app/__init__.py`: package marker.
- `backend/app/config.py`: validated environment settings and cached settings dependency.
- `backend/app/clock.py`: injectable current-time protocol/default implementation.
- `backend/app/session_store.py`: `SessionStore` protocol and in-memory implementation.
- `backend/app/auth.py`: credential verification, session lifecycle, and auth dependency helpers.
- `backend/app/main.py`: FastAPI factory, routes, cookie handling, and health endpoint wiring.
- `backend/tests/conftest.py`: isolated test settings, controllable clock, and app/client fixtures.
- `backend/tests/test_config.py`: settings defaults and environment overrides.
- `backend/tests/test_session_store.py`: store expiry, renewal, invalidation, and restart behavior.
- `backend/tests/test_auth_api.py`: HTTP auth behavior and cookie assertions.
- `frontend/package.json`: exact frontend dependencies and scripts.
- `frontend/package-lock.json`: reproducible frontend dependency resolution.
- `frontend/index.html`: Vite document shell.
- `frontend/src/main.tsx`: React entry point.
- `frontend/src/App.tsx`: login/authenticated shell state machine.
- `frontend/src/api.ts`: typed auth HTTP calls.
- `frontend/src/App.css`: minimal responsive M0 styling.
- `frontend/src/App.test.tsx`: login, failure, authenticated state, interaction, and logout tests.
- `frontend/vite.config.ts`: Vite and Vitest configuration.
- `frontend/tsconfig.json`, `frontend/tsconfig.app.json`, `frontend/tsconfig.node.json`: TypeScript configuration.
- `frontend/src/test/setup.ts`: test DOM setup.
- `docker-compose.yml`: PostgreSQL service and health check only.
- `.env.example`: documented non-secret local settings.
- `.github/workflows/ci.yml`: backend/frontend checks and PostgreSQL readiness.
- `docs/decisions.md`: exact dependency versions and implementation decisions.

---

### Task 1: Establish Reproducible Project Tooling

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/uv.lock`
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`
- Modify: `docs/decisions.md`

**Interfaces:**
- Produces backend commands `uv run pytest` and `uv run python -m compileall app` from `backend/`.
- Produces frontend commands `npm test -- --run`, `npm run typecheck`, and `npm run build` from `frontend/`.
- Produces a Vite/Vitest TypeScript project that later tasks can import without changing tool configuration.

- [ ] **Step 1: Create the minimal testable package placeholders**

Create `backend/app/__init__.py` and `backend/tests/__init__.py` as package
markers, plus `backend/tests/test_tooling.py`. Create
`frontend/src/App.tsx`, `frontend/src/main.tsx`, and
`frontend/src/App.test.tsx` with a temporary smoke screen. Task 2 replaces
the backend test's placeholder import with the real application factory, and
Task 5 replaces the frontend smoke screen with the auth flow.

```python
def test_python_test_runner_is_configured():
    assert True
```

```tsx
import {render, screen} from '@testing-library/react';
import App from './App';

it('renders the frontend smoke screen', () => {
  render(<App />);
  expect(screen.getByText('M0')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the commands to verify the scaffold is not complete**

Run from `backend/`: `uv run pytest tests/test_tooling.py -q`

Expected: FAIL because the backend project and test file are not yet
configured.

Run from `frontend/`: `npm test -- --run`

Expected: FAIL because the Vite project and `App.tsx` do not yet exist.

- [ ] **Step 3: Create the exact dependency manifests and configs**

Use the current version-specific documentation from Context7 for FastAPI,
Pydantic Settings, React 19, Vite, Vitest, and Testing Library. Choose the
latest mutually compatible versions available on the implementation date,
pin every direct dependency to an exact version rather than a caret/range,
and generate both lockfiles. The backend manifest must include FastAPI,
Pydantic Settings, pytest, and HTTPX/TestClient support. The frontend
manifest must include React `19.2.7`, React DOM `19.2.7`, TypeScript, Vite,
Vitest, jsdom, `@testing-library/react`, `@testing-library/user-event`, and
`@testing-library/jest-dom`.

Record the selected exact versions in `docs/decisions.md` in this step. If
Context7 has no current documentation for a required package, stop and ask
the human before selecting an alternative.

The backend scripts must include:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.uv]
package = true
```

The frontend scripts must be exactly named `dev`, `build`, `typecheck`, and
`test`, with `test` invoking Vitest. Configure Vitest with the jsdom
environment, setup file `src/test/setup.ts`, and globals enabled.

- [ ] **Step 4: Add minimal scaffold files and run the smoke tests**

Create `backend/tests/test_tooling.py`, `frontend/src/App.tsx`,
`frontend/src/main.tsx`, and the frontend smoke test.
The temporary `App.tsx` can be:

```tsx
export default function App() {
  return <main>M0</main>;
}
```

Run:

```bash
cd backend && uv run pytest tests/test_tooling.py -q
cd ../frontend && npm test -- --run && npm run typecheck && npm run build
```

Expected: all commands pass.

- [ ] **Step 5: Record resolved dependency versions**

Append the exact selected versions and lockfile strategy to the existing M0
tooling decision in `docs/decisions.md`. Do not record ranges.

- [ ] **Step 6: Commit the reproducible tooling**

```bash
git add backend frontend docs/decisions.md
git commit -m "build: scaffold backend and frontend tooling"
```

### Task 2: Add Settings, Health, and Application Factory

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/app/clock.py`
- Create: `backend/app/main.py`
- Modify: `backend/tests/test_tooling.py`
- Create: `backend/tests/test_config.py`
- Create: `backend/tests/conftest.py`

**Interfaces:**
- Produces `Settings` with `SESSION_IDLE_MINUTES`, `SESSION_ABSOLUTE_HOURS`, `SESSION_SECRET`, initial username, initial password, and database URL fields.
- Produces `create_app(settings: Settings | None = None, session_store: SessionStore | None = None, clock: Clock | None = None) -> FastAPI`.
- Produces `GET /health` returning `{"status": "ok"}` without authentication.
- Produces `get_settings()` as a cached FastAPI dependency that tests can override.

- [ ] **Step 1: Write failing settings and health tests**

Create `backend/tests/test_config.py`:

```python
def test_session_defaults(monkeypatch):
    for key in ("SESSION_IDLE_MINUTES", "SESSION_ABSOLUTE_HOURS"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None, session_secret="test-secret")
    assert settings.session_idle_minutes == 30
    assert settings.session_absolute_hours == 12
```

Create `backend/tests/test_tooling.py` additions:

```python
from fastapi.testclient import TestClient
from app.main import create_app


def test_health_endpoint():
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run from `backend/`: `uv run pytest tests/test_config.py tests/test_tooling.py -q`

Expected: FAIL because `Settings`, `create_app`, and `/health` do not exist.

- [ ] **Step 3: Implement settings, clock, and factory minimally**

Define a `Clock` protocol with `now() -> datetime` returning timezone-aware
UTC values and a `SystemClock` implementation. Define `Settings` with
Pydantic Settings, strict positive duration validation, required
`session_secret`, required initial credentials, and a database URL default
usable by local Compose. Support `_env_file=None` in tests so the test suite
does not read a developer's `.env`.

Implement `create_app` as a factory that installs the supplied or default
clock/store dependencies on `app.state`, includes the health route, and
does not connect to PostgreSQL at import time. Keep the default app import
available for ASGI servers as `app = create_app()`.

- [ ] **Step 4: Run the focused tests and type/compile checks**

Run:

```bash
cd backend
uv run pytest tests/test_config.py tests/test_tooling.py -q
uv run python -m compileall app
```

Expected: all tests pass and compilation exits with status 0.

- [ ] **Step 5: Commit the application foundation**

```bash
git add backend/app backend/tests
git commit -m "feat: add FastAPI settings and health factory"
```

### Task 3: Implement the Injectable In-Process Session Store

**Files:**
- Create: `backend/app/session_store.py`
- Modify: `backend/app/clock.py`
- Create: `backend/tests/test_session_store.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Produces `class SessionStore(Protocol)` with `create(user_id: str, now: datetime) -> str`, `validate(session_id: str, now: datetime, renew_idle: bool) -> str | None`, and `invalidate(session_id: str) -> None`.
- Produces `class InMemorySessionStore(SessionStore)` with constructor `(idle: timedelta, absolute: timedelta, secret: str)`.
- Produces a token codec that accepts only opaque, cryptographically random tokens with an HMAC signature verified using constant-time comparison.
- Produces a test clock whose time can be advanced without sleeping.

- [ ] **Step 1: Write failing store tests**

Create tests that establish the exact boundary behavior:

```python
def test_create_and_validate_returns_user_id(store, clock):
    token = store.create("operator", clock.now())
    assert store.validate(token, clock.now(), renew_idle=False) == "operator"


def test_read_validation_does_not_renew_idle_expiry(store, clock):
    token = store.create("operator", clock.now())
    clock.advance(minutes=29)
    assert store.validate(token, clock.now(), renew_idle=False) == "operator"
    clock.advance(minutes=2)
    assert store.validate(token, clock.now(), renew_idle=False) is None


def test_explicit_interaction_renews_idle_but_not_absolute(store, clock):
    token = store.create("operator", clock.now())
    absolute = clock.now() + timedelta(hours=12)
    clock.advance(minutes=29)
    assert store.validate(token, clock.now(), renew_idle=True) == "operator"
    clock.advance(minutes=29)
    assert store.validate(token, clock.now(), renew_idle=False) == "operator"
    clock.set(absolute + timedelta(seconds=1))
    assert store.validate(token, clock.now(), renew_idle=True) is None


def test_invalidate_rejects_existing_token(store, clock):
    token = store.create("operator", clock.now())
    store.invalidate(token)
    assert store.validate(token, clock.now(), renew_idle=False) is None
```

Also test that a new `InMemorySessionStore` instance cannot validate a token
from the old instance, proving restart invalidation, and test malformed or
tampered token rejection.

- [ ] **Step 2: Run store tests and verify RED**

Run from `backend/`: `uv run pytest tests/test_session_store.py -q`

Expected: FAIL because the protocol, implementation, and test clock are not
yet present.

- [ ] **Step 3: Implement the minimal store**

Store records server-side in a dictionary keyed by a random token. Each
record includes user ID, created time, last explicit interaction, idle expiry,
and absolute expiry. Use aware UTC datetimes. On `validate`, reject missing,
malformed, tampered, idle-expired, or absolute-expired records; delete
expired records. Only when `renew_idle=True` update the idle deadline, and
cap it at the unchanged absolute deadline. Never return session data from the
cookie itself.

- [ ] **Step 4: Run store tests and refactor only after GREEN**

Run:

```bash
cd backend
uv run pytest tests/test_session_store.py -q
uv run python -m compileall app
```

Expected: all store tests pass. Refactor only names or private helpers that
improve readability without changing the public protocol, then rerun the same
commands.

- [ ] **Step 5: Commit the session store**

```bash
git add backend/app/clock.py backend/app/session_store.py backend/tests
git commit -m "feat: add injectable in-memory session store"
```

### Task 4: Add Auth Service and FastAPI Auth Routes

**Files:**
- Create: `backend/app/auth.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_auth_api.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Produces `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, and `POST /auth/interaction`.
- Produces `require_user(request) -> str` for protected routes.
- Produces a single cookie name constant used by both setting and clearing paths.
- Produces a cookie with `HttpOnly`, `Secure`, `SameSite=Lax`, and an absolute `max-age`.

- [ ] **Step 1: Write failing API tests**

Cover these cases with `TestClient` using an HTTPS base URL and injected test
settings/clock/store:

```python
def test_login_sets_secure_cookie_and_returns_operator(client):
    response = client.post("/auth/login", json={"username": "operator", "password": "correct"})
    assert response.status_code == 200
    assert response.json() == {"username": "operator"}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=43200" in cookie


def test_wrong_credentials_are_rejected(client):
    response = client.post("/auth/login", json={"username": "operator", "password": "wrong"})
    assert response.status_code == 401


def test_me_does_not_renew_idle_but_interaction_does(client, clock):
    assert client.post("/auth/login", json=valid_credentials).status_code == 200
    clock.advance(minutes=29)
    assert client.get("/auth/me").status_code == 200
    clock.advance(minutes=2)
    assert client.get("/auth/me").status_code == 401
```

Add separate assertions that `/auth/interaction` renews idle expiry,
`/auth/logout` invalidates the current session and clears the cookie, missing
cookies return `401`, and absolute expiry returns `401` even after an
interaction. Test the polling contract with a representative non-renewing
read route, not by relying only on the implementation flag.

- [ ] **Step 2: Run auth tests and verify RED**

Run from `backend/`: `uv run pytest tests/test_auth_api.py -q`

Expected: FAIL because auth routes and dependencies are not implemented.

- [ ] **Step 3: Implement auth service and routes**

Use a Pydantic request model for credentials. Login compares the submitted
credentials with configured values, creates a session at the injected clock
time, and sets the cookie using FastAPI's response cookie API. Protected
dependencies validate with `renew_idle=False`; only `/auth/interaction`
passes `renew_idle=True`. Logout invalidates the cookie's token and emits a
matching expired deletion cookie. Return `401` without revealing whether the
username or password was wrong.

Keep route code thin by placing credential checking and session operations in
`auth.py`. Do not make generic authentication middleware renew sessions.

- [ ] **Step 4: Run all backend tests**

Run from `backend/`: `uv run pytest -q`

Expected: tooling, settings, store, and auth API tests all pass.

- [ ] **Step 5: Commit the auth vertical slice**

```bash
git add backend/app backend/tests
git commit -m "feat: add session authentication routes"
```

### Task 5: Build the React Login and Authenticated Shell

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/api.ts`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/App.css`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces typed `login`, `getCurrentUser`, `logout`, and `recordInteraction` API functions using `fetch` with credentials included.
- Produces an `App` state flow: loading -> login form -> authenticated shell.
- Produces visible login errors without exposing backend internals.

- [ ] **Step 1: Write failing frontend behavior tests**

Mock `fetch` and replace the smoke test with tests for:

```tsx
it('submits credentials and renders the authenticated shell', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({username: 'operator'}));
  render(<App />);
  await userEvent.type(screen.getByLabelText(/username/i), 'operator');
  await userEvent.type(screen.getByLabelText(/password/i), 'correct');
  await userEvent.click(screen.getByRole('button', {name: /sign in/i}));
  expect(await screen.findByText(/signed in as operator/i)).toBeInTheDocument();
});


it('shows a login error and stays on the form after a 401', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({detail: 'Invalid credentials'}, 401));
  render(<App />);
  await userEvent.click(screen.getByRole('button', {name: /sign in/i}));
  expect(await screen.findByRole('alert')).toHaveTextContent(/unable to sign in/i);
  expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
});


it('logs out and returns to the login form', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({username: 'operator'}));
  render(<App />);
  expect(await screen.findByText(/signed in as operator/i)).toBeInTheDocument();
  fetchMock.mockResolvedValueOnce(new Response(null, {status: 204}));
  await userEvent.click(screen.getByRole('button', {name: /sign out/i}));
  expect(await screen.findByRole('button', {name: /sign in/i})).toBeInTheDocument();
});
```

Also test that the initial `GET /auth/me` `401` displays the login form and
that the explicit interaction button calls the interaction endpoint.

- [ ] **Step 2: Run frontend tests and verify RED**

Run from `frontend/`: `npm test -- --run`

Expected: FAIL because the typed API functions and login shell do not exist.

- [ ] **Step 3: Implement typed API functions and UI**

Implement a small `api.ts` around `fetch` with `credentials: 'include'` for
all auth calls. Parse JSON only when the response has a body, throw a typed
error for non-2xx responses, and keep the UI's error message generic.

In `App.tsx`, use React built-in state only. On mount call `getCurrentUser`;
render a loading state while it resolves, then the login form or shell. The
shell includes an explicit `Record interaction` button and `Sign out` button.
Disable submit while the request is pending and associate labels with inputs.

Use responsive, accessible CSS without adding a component framework in M0.

- [ ] **Step 4: Run frontend verification**

Run from `frontend/`:

```bash
npm test -- --run
npm run typecheck
npm run build
```

Expected: all tests pass, TypeScript reports no errors, and Vite produces a
production build.

- [ ] **Step 5: Commit the frontend auth flow**

```bash
git add frontend
git commit -m "feat: add React login and session shell"
```

### Task 6: Add PostgreSQL Compose and Environment Documentation

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Modify: `backend/app/config.py`
- Create: `backend/tests/test_environment_docs.py`

**Interfaces:**
- Produces a PostgreSQL-only Compose service with a health check.
- Produces documented environment names matching the settings model.
- Keeps the backend database connection lazy in M0; no schema or ORM is introduced yet.

- [ ] **Step 1: Write failing environment/documentation tests**

Create a test that reads `.env.example` from the repository root and asserts
the required names are present without requiring real credentials. Resolve
the path from the test file rather than relying on the process working
directory:

```python
def test_env_example_documents_required_settings():
    root = Path(__file__).resolve().parents[2]
    text = (root / ".env.example").read_text()
    for key in (
        "DATABASE_URL",
        "SESSION_SECRET",
        "INITIAL_USERNAME",
        "INITIAL_PASSWORD",
        "SESSION_IDLE_MINUTES",
        "SESSION_ABSOLUTE_HOURS",
    ):
        assert f"{key}=" in text
```

Add a Compose configuration check that loads the YAML and asserts there is
exactly one service, named `postgres`, with a health check.

- [ ] **Step 2: Run the documentation tests and verify RED**

Run from `backend/`: `uv run pytest tests/test_environment_docs.py -q`

Expected: FAIL because the Compose file and environment example do not exist.

- [ ] **Step 3: Implement Compose and environment documentation**

Define one PostgreSQL service using an exact image tag, environment-backed
database/user/password, a persistent named volume, and a `pg_isready`
health check. Do not add backend/frontend services to Compose.

Document safe placeholder values in `.env.example`, including a clearly
non-production session secret marker and the M0 one-worker requirement. Do
not commit real credentials.

- [ ] **Step 4: Run static and runtime Compose verification**

Run:

```bash
cd backend && uv run pytest tests/test_environment_docs.py -q
docker compose config
docker compose up -d postgres
docker compose ps
docker compose down
```

Expected: the test passes, Compose config validates, PostgreSQL reaches
`healthy`, and shutdown removes the service without errors.

- [ ] **Step 5: Commit the local database setup**

```bash
git add docker-compose.yml .env.example backend/app/config.py backend/tests/test_environment_docs.py
git commit -m "build: add PostgreSQL development service"
```

### Task 7: Add CI and Complete M0 Verification

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/decisions.md`
- Modify: `backend/tests/test_tooling.py`

**Interfaces:**
- Produces a CI workflow that runs backend tests/compile checks and frontend tests/typecheck/build.
- Produces README commands for local backend, frontend, and PostgreSQL startup.
- Produces a final backend test proving `create_app` is the supported entry point.

- [ ] **Step 1: Write the final integration check**

Add a backend test that creates the app with test settings and confirms both
`/health` and the auth flow work through the public factory. Add a frontend
test assertion that the interaction button uses the interaction API function.

- [ ] **Step 2: Run the final checks and verify any missing wiring**

Run from the repository root:

```bash
cd backend && uv run pytest -q && uv run python -m compileall app
cd ../frontend && npm test -- --run && npm run typecheck && npm run build
cd .. && docker compose config
```

Expected: all commands pass before CI is added.

- [ ] **Step 3: Implement CI workflow**

Configure `.github/workflows/ci.yml` on pushes and pull requests. Use a
PostgreSQL service container with a health check or start the repository's
Compose PostgreSQL service, then run backend and frontend jobs on a supported
Python/Node runner. Install from the committed lockfiles, set test-only
environment values, and execute the exact commands from Step 2. CI must not
require production secrets.

- [ ] **Step 4: Document local operation**

Update `README.md` with exact commands to:

```text
cp .env.example .env
docker compose up -d postgres
cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
cd frontend && npm run dev
```

Document that M0's `Secure` cookie requires an HTTPS-capable local setup and
that the in-process store invalidates sessions on restart. State that M1 is
the named milestone for PostgreSQL session persistence and password-change
invalidation.

- [ ] **Step 5: Run CI-equivalent checks locally**

Run the complete command set from Step 2 plus `git diff --check`. Expected:
all tests/builds pass and there is no whitespace error.

- [ ] **Step 6: Commit CI and M0 documentation**

```bash
git add .github/workflows/ci.yml README.md backend/tests/test_tooling.py docs/decisions.md
git commit -m "ci: verify M0 backend and frontend"
```

---

## Plan Self-Review

- **Spec coverage:** M0 tooling, FastAPI/Vite skeletons, session login/logout,
  PostgreSQL-only Compose, and CI are covered by Tasks 1-7. The M1 persistence
  and password-change invalidation gate is explicitly recorded but not
  implemented in M0. Later spec sections remain out of scope.
- **Placeholder scan:** No implementation step depends on a `TODO`, `TBD`, or
  unspecified observable behavior. Dependency versions are resolved from
  current documentation at first implementation use and recorded exactly in
  the decision log; React 19.2.7 is fixed by the approved stack choice.
- **Type consistency:** `SessionStore` signatures are used consistently by
  the store, auth service, factory, and tests. `create_app` accepts the same
  injectable dependencies in Tasks 2-4. Cookie renewal is controlled by the
  same `renew_idle` parameter throughout.
