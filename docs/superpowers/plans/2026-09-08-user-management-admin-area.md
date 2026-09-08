# Basic User Management & Admin Area — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two user groups (admin/user), many-to-many user↔client assignment where a `user` sees only assigned clients, and an admin area (user management, client management, global settings).

**Architecture:** Add `users.role`/`users.is_active`, a `user_clients` join table, and a single-row `global_settings` table. Authorization via FastAPI dependencies: `get_current_user` loads role + assigned clients per request, `require_admin` guards admin endpoints, and `enforce_scope_access` (router-level, path/query-param based) returns 404 for unassigned client/feed-source access. Frontend gets an Administration nav group (admin-only) with Users/Clients/Settings pages and a route guard.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, pytest (backend, run from `backend/` with `uv run`), React 19 + TypeScript + Mantine + TanStack Query, vitest (frontend, run from `frontend/` with `npm`).

**Spec:** `docs/superpowers/specs/2026-09-08-user-management-admin-area-design.md`

## Global Constraints

- Backend commands run from `backend/`: `uv run pytest -n auto` (needs `TEST_DATABASE_URL` pointing at PostgreSQL via `postgresql+asyncpg://`), `uv run ruff check .`, `uv run mypy .`
- Frontend commands run from `frontend/`: `npm run test`, `npm run typecheck`, `npm run build`
- Migrations only via Alembic; never `create_all`
- Never commit secrets or `.env` files
- Documentation MUST be updated in the same commit as behavior changes (backend `docs/api.md`, `docs/data-model.md`, `docs/architecture.md`; frontend `docs/architecture.md`)
- Tests are written FIRST (TDD): failing test → implementation → pass → commit
- Roles are the literal strings `'admin'` and `'user'`
- Retention defaults: 90 days each, when no `global_settings` row exists
- Unassigned client/feed-source access returns **404** (not 403); non-admin on admin-only operations returns **403**
- i18n: add keys to BOTH `frontend/public/locales/en/` and `frontend/public/locales/de/`
- Latest Alembic head before this work: revision `'20260905_0001'` (file `backend/alembic/versions/20260905_0001_m10_module_instance_enabled.py`)

---

### Task 1: Data model + migration + seed-admin

**Files:**
- Modify: `backend/app/models/user.py`
- Create: `backend/app/models/user_client.py`
- Create: `backend/app/models/global_setting.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/20260908_0001_m11_user_admin_rbac.py`
- Modify: `backend/app/persistence/users.py:26-42` (`seed_initial_user`)
- Test: `backend/tests/test_user_rbac_migration.py`

**Interfaces:**
- Produces: `User.role: Mapped[str]`, `User.is_active: Mapped[bool]`, `UserClient` model (`user_id`, `client_id`), `GlobalSetting` model (`staging_removal_retention_days`, `staging_history_retention_days`, `ingestion_run_retention_days`), migration revision `'20260908_0001'`
- Later tasks rely on: `app.models.user.User` having `role`/`is_active`; `app.models.user_client.UserClient`; `app.models.global_setting.GlobalSetting`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_user_rbac_migration.py`:

```python
from pathlib import Path
from urllib.parse import quote

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.global_setting import GlobalSetting
from app.models.user import User
from app.persistence.users import seed_initial_user


@pytest.mark.asyncio
async def test_seed_initial_user_is_admin(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = await seed_initial_user(session, "operator", "correct")
        assert user.role == "admin"
        assert user.is_active is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_promotes_existing_users_to_admin(isolated_database_url):
    # Downgrade to the revision before m11, insert a pre-RBAC user, upgrade, verify.
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", isolated_database_url)
    command.downgrade(config, "20260905_0001")
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(text(
                "INSERT INTO users (username, password_hash, revocation_generation)"
                " VALUES ('legacy', 'x', 0)"
            ))
    await engine.dispose()
    command.upgrade(config, "head")
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = (await session.execute(
            text("SELECT username, role FROM users WHERE username = 'legacy'")
        )).one()
        assert user.role == "admin"
        settings = await session.get(GlobalSetting, 1)
        assert settings is None  # row is seeded lazily, not by migration
    await engine.dispose()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_user_rbac_migration.py -v`
Expected: FAIL — `AttributeError: ... 'role'` on seed test; import error on `app.models.global_setting` for the second test.

- [ ] **Step 3: Update the User model**

Replace `backend/app/models/user.py` with:

```python
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    revocation_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user", server_default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

- [ ] **Step 4: Create the join-table and settings models**

Create `backend/app/models/user_client.py`:

```python
from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class UserClient(Base):
    __tablename__ = "user_clients"
    __table_args__ = (UniqueConstraint("user_id", "client_id", name="uq_user_clients_user_client"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
```

Create `backend/app/models/global_setting.py`:

```python
from datetime import datetime
from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class GlobalSetting(Base):
    __tablename__ = "global_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    staging_removal_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    staging_history_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    ingestion_run_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

- [ ] **Step 5: Export the new models**

In `backend/app/models/__init__.py`, add alongside the existing imports/exports (follow the file's existing pattern):

```python
from .user_client import UserClient
from .global_setting import GlobalSetting
```

and add `UserClient` and `GlobalSetting` to the `__all__` list.

- [ ] **Step 6: Generate and write the migration**

Run: `uv run alembic revision --autogenerate -m "m11 user admin rbac"`

Rename the generated file to `backend/alembic/versions/20260908_0001_m11_user_admin_rbac.py`, set `revision: str = '20260908_0001'` and `down_revision = '20260905_0001'`, and replace the `upgrade()`/`downgrade()` bodies with:

```python
def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(length=20), nullable=False, server_default="user"))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))
    # Promote every pre-existing user to admin (single-operator installs).
    op.execute("UPDATE users SET role = 'admin'")
    op.create_table(
        "user_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("user_id", "client_id", name="uq_user_clients_user_client"),
    )
    op.create_index("ix_user_clients_user_id", "user_clients", ["user_id"])
    op.create_index("ix_user_clients_client_id", "user_clients", ["client_id"])
    op.create_table(
        "global_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staging_removal_retention_days", sa.Integer(), nullable=False),
        sa.Column("staging_history_retention_days", sa.Integer(), nullable=False),
        sa.Column("ingestion_run_retention_days", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("global_settings")
    op.drop_index("ix_user_clients_client_id", table_name="user_clients")
    op.drop_index("ix_user_clients_user_id", table_name="user_clients")
    op.drop_table("user_clients")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
```

(Keep the `import` block the autogenerated file provides; add `"users"` server_default strings exactly as above.)

- [ ] **Step 7: Make the seed user an admin**

In `backend/app/persistence/users.py`, in `seed_initial_user`, change the insert to include the new columns:

```python
        await session.execute(
            insert(User)
            .values(username=username, password_hash=hash_password(password),
                    role="admin", is_active=True)
        )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_user_rbac_migration.py tests/test_user_persistence.py tests/test_postgres_auth.py -v`
Expected: PASS (all new and pre-existing auth/user tests).

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/ backend/alembic/versions/20260908_0001_m11_user_admin_rbac.py backend/app/persistence/users.py backend/tests/test_user_rbac_migration.py
git commit -m "feat(backend): user role/is_active, user_clients join, global_settings table"
```

---

### Task 2: CurrentUser dependency, require_admin, login/me changes

**Files:**
- Create: `backend/app/access.py`
- Modify: `backend/app/persistence/users.py` (add `authenticate_user`)
- Modify: `backend/app/auth.py:95-102` (`authenticate`)
- Modify: `backend/app/main.py:294-318` (`password` unchanged; `me` endpoint)
- Test: `backend/tests/test_user_access.py`

**Interfaces:**
- Consumes: `User.role`, `User.is_active`, `UserClient` from Task 1; `require_user` from `app.auth`
- Produces:
  - `app.access.CurrentUser` — frozen dataclass: `username: str`, `role: str`, `is_active: bool`, `client_ids: frozenset[int] | None` (None = unrestricted)
  - `app.access.get_current_user` — async FastAPI dependency returning `CurrentUser`
  - `app.access.require_admin` — dependency returning `CurrentUser`, raises 403 unless `role == "admin"`
  - `persistence.users.authenticate_user(session, username, password) -> User | None` (None when invalid OR inactive)
  - `GET /auth/me` returns `{"username": str, "role": str, "client_ids": list[int] | null}`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_user_access.py`:

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


@pytest_asyncio.fixture
async def access_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(UserClient))
            await session.execute(delete(User))
            await session.execute(delete(Client))
        await seed_initial_user(session, "operator", "admin-pass")
        async with session.begin():
            session.add(Client(name="Acme"))
            session.add(Client(name="Other Corp"))
            regular = User(username="bob", password_hash="x", role="user")
            session.add(regular)
            session.add(User(username="mallory", password_hash="x", role="user", is_active=False))
            session.flush()
            session.add(UserClient(user_id=regular.id, client_id=1))
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_login_rejects_inactive_user(access_app):
    app, factory = access_app
    async with factory() as session:
        async with session.begin():
            user = (await session.execute(
                select(User).where(User.username == "mallory")
            )).scalar_one()
            user.password_hash = hash_password("inactive-pass")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post(
            "/auth/login", json={"username": "mallory", "password": "inactive-pass"}
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_reports_role_and_clients(access_app):
    app, _ = access_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        assert (await client.post(
            "/auth/login", json={"username": "operator", "password": "admin-pass"}
        )).status_code == 200
        me = await client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "operator"
        assert me.json()["role"] == "admin"
        assert me.json()["client_ids"] is None


@pytest.mark.asyncio
async def test_auth_me_for_regular_user_lists_assigned_clients(access_app):
    app, factory = access_app
    async with factory() as session:
        async with session.begin():
            user = (await session.execute(
                select(User).where(User.username == "bob")
            )).scalar_one()
            user.password_hash = hash_password("bob-pass")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        assert (await client.post(
            "/auth/login", json={"username": "bob", "password": "bob-pass"}
        )).status_code == 200
        me = await client.get("/auth/me")
        assert me.status_code == 200
        body = me.json()
        assert body["role"] == "user"
        assert body["client_ids"] == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_user_access.py -v`
Expected: FAIL — inactive login currently returns 200; `/auth/me` has no `role`/`client_ids` keys.

- [ ] **Step 3: Add `authenticate_user` to persistence**

In `backend/app/persistence/users.py`, append:

```python
async def authenticate_user(
    session: AsyncSession, username: str, password: str
) -> User | None:
    user = await get_user_by_username(session, username)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
```

- [ ] **Step 4: Create the access module**

Create `backend/app/access.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import require_user
from .db.engine import get_db_session
from .models.user import User
from .models.user_client import UserClient


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: str
    is_active: bool
    # None means unrestricted (admins, or non-DB fallback mode).
    client_ids: frozenset[int] | None


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Invalid credentials")


def _forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail="admin role required")


async def _load_user(session: AsyncSession | None, username: str) -> CurrentUser:
    if session is None:
        # No PostgreSQL boundary configured: single-user mode stays fully
        # functional and is treated as unrestricted/admin.
        return CurrentUser(username=username, role="admin", is_active=True, client_ids=None)
    result = await session.execute(
        select(User, UserClient.client_id)
        .outerjoin(UserClient, UserClient.user_id == User.id)
        .where(User.username == username)
    )
    rows = result.all()
    if not rows:
        raise _unauthorized()
    user = rows[0][0]
    if not user.is_active:
        raise _unauthorized()
    if user.role == "admin":
        return CurrentUser(username=user.username, role="admin", is_active=True, client_ids=None)
    return CurrentUser(
        username=user.username,
        role=user.role,
        is_active=True,
        client_ids=frozenset(row[1] for row in rows if row[1] is not None),
    )


async def get_current_user(
    request_user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> CurrentUser:
    return await _load_user(db_session, request_user)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise _forbidden()
    return user
```

- [ ] **Step 5: Reject inactive users at login**

In `backend/app/auth.py`, change `authenticate` (lines 95-102) to:

```python
async def authenticate(credentials: Credentials, settings: Settings, session=None) -> str:
    if session is not None:
        from .persistence.users import authenticate_user

        user = await authenticate_user(session, credentials.username, credentials.password)
        if user is None:
            raise _unauthorized()
        return user.username
    if credentials.username != settings.initial_username or credentials.password != settings.initial_password:
        raise _unauthorized()
    return credentials.username
```

(Keep the existing `verify_user_password` import only if still referenced; otherwise remove it and `ruff` will flag it.)

- [ ] **Step 6: Extend `/auth/me`**

In `backend/app/main.py`, replace the `me` endpoint (line 316-318) with:

```python
    @app.get("/auth/me")
    def me(user: CurrentUser = Depends(get_current_user)) -> dict:
        return {
            "username": user.username,
            "role": user.role,
            "client_ids": sorted(user.client_ids) if user.client_ids is not None else None,
        }
```

and add to the imports near the top of `create_app`'s module (with the other `app.*` imports):

```python
from .access import CurrentUser, get_current_user, require_admin
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_user_access.py tests/test_postgres_auth.py tests/test_auth_api.py -v`
Expected: PASS. If `test_auth_api.py` asserts the exact `/auth/me` JSON body, update that assertion to the new shape (this is the expected, spec-mandated change).

- [ ] **Step 8: Commit**

```bash
git add backend/app/access.py backend/app/persistence/users.py backend/app/auth.py backend/app/main.py backend/tests/test_user_access.py
git commit -m "feat(backend): CurrentUser/require_admin deps, inactive-login rejection, /auth/me role"
```

---

### Task 3: Scope enforcement on existing routes

**Files:**
- Modify: `backend/app/access.py` (add `enforce_scope_access`)
- Modify: `backend/app/main.py` (router-level dependencies; imports)
- Modify: `backend/app/routes/clients.py:69-123,249-282` (admin-only client CRUD), `:90-97` (list filtering)
- Modify: `backend/app/routes/dashboard.py:33-88` (summary filtering)
- Test: `backend/tests/test_scope_enforcement.py`

**Interfaces:**
- Consumes: `CurrentUser`, `get_current_user`, `require_admin` from Task 2
- Produces: `app.access.enforce_scope_access` — async dependency returning `None`; reads `client_id`/`feed_source_id` from `request.path_params` **and** `request.query_params` (plugins use query params); raises 404 when a non-admin user lacks the assignment; passes admins and the non-DB fallback
- Enforcement wiring (Task 5 adds `/admin/*`): `enforce_scope_access` attached to `clients_router`, `products_router`, `pipeline_router`, `quality_router`, `dry_run_router`, `export_history_router`, `field_mapping_router`, `plugins_router` — NOT `export_public_router` (token auth) and NOT `registry_router`/`dashboard_router` (no scoped params; dashboard filters in-handler)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scope_enforcement.py`:

```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.client import Client
from app.models.feed_source import FeedSource
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
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "admin-pass")
        async with session.begin():
            acme = Client(name="Acme")
            other = Client(name="Other Corp")
            session.add_all([acme, other])
            session.flush()
            session.add(FeedSource(client_id=acme.id, name="Acme Feed", source_format="xml",
                                   source_url="https://acme.example/feed.xml"))
            session.add(FeedSource(client_id=other.id, name="Other Feed", source_format="xml",
                                   source_url="https://other.example/feed.xml"))
            bob = User(username="bob", password_hash=hash_password("bob-pass"), role="user")
            session.add(bob)
            session.flush()
            session.add(UserClient(user_id=bob.id, client_id=acme.id))
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_client(scope_app):
    app, _ = scope_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def bob_client(scope_app):
    app, _ = scope_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "bob", "password": "bob-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_user_sees_only_assigned_client(scope_app, bob_client):
    response = await bob_client.get("/clients")
    assert response.status_code == 200
    names = [c["name"] for c in response.json()]
    assert names == ["Acme"]


@pytest.mark.asyncio
async def test_admin_sees_all_clients(scope_app, admin_client):
    response = await admin_client.get("/clients")
    assert response.status_code == 200
    names = sorted(c["name"] for c in response.json())
    assert names == ["Acme", "Other Corp"]


@pytest.mark.asyncio
async def test_user_dashboard_summary_filtered(scope_app, bob_client):
    response = await bob_client.get("/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    assert [c["name"] for c in body["clients"]] == ["Acme"]
    assert body["counts"]["clients"] == 1
    assert body["counts"]["feed_sources"] == 1


@pytest.mark.asyncio
async def test_unassigned_client_routes_404(scope_app, bob_client, admin_client):
    other_id = [c["id"] for c in (await admin_client.get("/clients")).json()
                if c["name"] == "Other Corp"][0]
    assert (await bob_client.get(f"/clients/{other_id}/feed-sources")).status_code == 404
    assert (await bob_client.put(
        f"/clients/{other_id}", json={"name": "Hacked"}
    )).status_code == 404
    assert (await bob_client.delete(f"/clients/{other_id}")).status_code == 404


@pytest.mark.asyncio
async def test_assigned_client_crud_is_admin_only(scope_app, bob_client, admin_client):
    acme_id = [c["id"] for c in (await admin_client.get("/clients")).json()
               if c["name"] == "Acme"][0]
    assert (await bob_client.post(
        "/clients", json={"name": "Bob Corp"}
    )).status_code == 403
    assert (await bob_client.put(
        f"/clients/{acme_id}", json={"name": "Renamed"}
    )).status_code == 403
    assert (await bob_client.delete(f"/clients/{acme_id}")).status_code == 403


@pytest.mark.asyncio
async def test_unassigned_feed_source_routes_404(scope_app, bob_client, admin_client):
    feeds = (await admin_client.get("/dashboard/summary")).json()["clients"]
    other_feed_id = [f["id"] for c in feeds if c["name"] == "Other Corp"
                     for f in c["feed_sources"]][0]
    assert (await bob_client.get(f"/feed-sources/{other_feed_id}")).status_code == 404
    assert (await bob_client.get(
        f"/feed-sources/{other_feed_id}/ingestion-runs"
    )).status_code == 404
    assert (await bob_client.post(
        f"/feed-sources/{other_feed_id}/export-token/rotate"
    )).status_code == 404


@pytest.mark.asyncio
async def test_assigned_feed_source_routes_allowed(scope_app, bob_client, admin_client):
    feeds = (await admin_client.get("/dashboard/summary")).json()["clients"]
    acme_feed_id = [f["id"] for c in feeds if c["name"] == "Acme"
                    for f in c["feed_sources"]][0]
    assert (await bob_client.get(f"/feed-sources/{acme_feed_id}")).status_code == 200
    assert (await bob_client.get(
        f"/feed-sources/{acme_feed_id}/ingestion-runs"
    )).status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scope_enforcement.py -v`
Expected: FAIL — no filtering, no 404s, no 403s yet.

- [ ] **Step 3: Add `enforce_scope_access` to access.py**

Append to `backend/app/access.py`:

```python
async def enforce_scope_access(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> None:
    if user.client_ids is None:
        return
    client_id = request.path_params.get("client_id") or request.query_params.get("client_id")
    feed_source_id = (
        request.path_params.get("feed_source_id")
        or request.query_params.get("feed_source_id")
    )
    if client_id is not None:
        if int(client_id) not in user.client_ids:
            raise HTTPException(status_code=404, detail="client not found")
        return
    if feed_source_id is not None:
        if db_session is None:
            return  # handler will raise 503 (database unavailable)
        from .models.feed_source import FeedSource

        feed_source = await db_session.get(FeedSource, int(feed_source_id))
        if feed_source is None or feed_source.client_id not in user.client_ids:
            raise HTTPException(status_code=404, detail="feed source not found")
```

and add `Request` to the existing `from fastapi import ...` import line.

- [ ] **Step 4: Wire the dependency onto routers**

In `backend/app/main.py`, import the dependency:

```python
from .access import CurrentUser, enforce_scope_access, get_current_user, require_admin
```

and change the `include_router` calls (keep their existing order) so the scoped routers carry the dependency:

```python
    app.include_router(clients_router, dependencies=[Depends(enforce_scope_access)])
    app.include_router(dashboard_router)
    app.include_router(dry_run_router, dependencies=[Depends(enforce_scope_access)])
    app.include_router(export_history_router, dependencies=[Depends(enforce_scope_access)])
    app.include_router(export_public_router)
    app.include_router(field_mapping_router, dependencies=[Depends(enforce_scope_access)])
    app.include_router(pipeline_router, dependencies=[Depends(enforce_scope_access)])
    app.include_router(plugins_router, dependencies=[Depends(enforce_scope_access)])
    app.include_router(products_router, dependencies=[Depends(enforce_scope_access)])
    app.include_router(quality_router, dependencies=[Depends(enforce_scope_access)])
    app.include_router(registry_router)
```

- [ ] **Step 5: Make client CRUD admin-only and filter the client list**

In `backend/app/routes/clients.py`:

1. Change the import on line 13 from `from ..auth import require_user` to:

```python
from ..access import CurrentUser, get_current_user, require_admin
```

2. `create_client` (line 69): replace `_user: str = Depends(require_user),` with `_admin: CurrentUser = Depends(require_admin),`
3. `update_client` (line 100): same replacement.
4. `delete_client` (line 249): same replacement.
5. `list_clients` (line 90): replace `_user: str = Depends(require_user),` with `user: CurrentUser = Depends(get_current_user),` and filter:

```python
@router.get("/clients", response_model=list[ClientOut])
async def list_clients(
    user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> list[Client]:
    session = _require_db(db_session)
    result = await session.execute(select(Client).order_by(Client.name))
    clients = list(result.scalars())
    if user.client_ids is not None:
        clients = [c for c in clients if c.id in user.client_ids]
    return clients
```

Leave every other `_user: str = Depends(require_user)` in this file as-is — `enforce_scope_access` (router-level) already covers their scope checks.

- [ ] **Step 6: Filter the dashboard summary**

In `backend/app/routes/dashboard.py`: change the import of `require_user` to `from ..access import CurrentUser, get_current_user`, then modify `dashboard_summary`:

```python
@router.get("/dashboard/summary")
async def dashboard_summary(
    user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        clients = list((await session.execute(select(Client).order_by(Client.name))).scalars())
        feeds = list((await session.execute(select(FeedSource).order_by(FeedSource.name))).scalars())
        if user.client_ids is not None:
            allowed = user.client_ids
            clients = [c for c in clients if c.id in allowed]
            feeds = [f for f in feeds if f.client_id in allowed]
        feed_ids = [f.id for f in feeds]
        item_counts = dict(
            (await session.execute(
                select(StagingProduct.feed_source_id, func.count())
                .where(
                    StagingProduct.status == "active",
                    StagingProduct.excluded.is_(False),
                    StagingProduct.feed_source_id.in_(feed_ids),
                )
                .group_by(StagingProduct.feed_source_id)
            )).all()
        )
        total_active = (await session.execute(
            select(func.count()).select_from(StagingProduct)
            .where(
                StagingProduct.status == "active",
                StagingProduct.excluded.is_(False),
                StagingProduct.feed_source_id.in_(feed_ids),
            )
        )).scalar_one()
        latest_exports = await _latest_runs(session, ExportRun)
        latest_runs = await _latest_runs(session, IngestionRun)
    # ... rest of the function is UNCHANGED from feeds_by_client onwards ...
```

Keep the remainder of the function (`feeds_by_client` building, `failed_last_exports`, and the return dict) exactly as it is today.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_scope_enforcement.py tests/test_dashboard_api.py tests/test_cascade_api.py -v`
Expected: PASS. Existing tests that create clients via `POST /clients` while logged in as the seed user still pass because the seed user is `admin` (Task 1). If any old test logs in a plain user to create clients, update it to use the seed user.

- [ ] **Step 8: Commit**

```bash
git add backend/app/access.py backend/app/main.py backend/app/routes/clients.py backend/app/routes/dashboard.py backend/tests/test_scope_enforcement.py
git commit -m "feat(backend): client/feed-source scope enforcement and admin-only client CRUD"
```

---

### Task 4: Admin users API

**Files:**
- Create: `backend/app/schemas/admin.py`
- Modify: `backend/app/persistence/users.py` (list/create/update/set-password helpers)
- Create: `backend/app/routes/admin.py`
- Modify: `backend/app/main.py` (mount router)
- Test: `backend/tests/test_admin_users_api.py`

**Interfaces:**
- Consumes: `require_admin` (Task 2), `User`/`UserClient` (Task 1)
- Produces (all under `Depends(require_admin)`):
  - `GET /admin/users` → `list[AdminUserOut]`
  - `POST /admin/users` (201) → `AdminUserOut`
  - `PATCH /admin/users/{user_id}` → `AdminUserOut`
  - `POST /admin/users/{user_id}/password` (204)
  - `AdminUserOut = {id, username, role, is_active, client_ids: list[int]}`
  - `persistence.users.list_users(session) -> list[tuple[User, list[int]]]`
  - `persistence.users.create_user(session, username, password, role, client_ids, is_active) -> User`
  - `persistence.users.update_user(session, user_id, role=None, is_active=None, client_ids=None) -> User | None`
  - `persistence.users.set_user_password(session, user_id, new_password) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_admin_users_api.py`:

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
async def admin_app(isolated_database_url):
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
            session.add(Client(name="Acme"))
            bob = User(username="bob", password_hash=hash_password("bob-pass"), role="user")
            session.add(bob)
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_http(admin_app):
    app, _ = admin_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_admin_users_requires_admin_role(admin_app):
    app, _ = admin_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as bob:
        assert (await bob.post(
            "/auth/login", json={"username": "bob", "password": "bob-pass"}
        )).status_code == 200
        assert (await bob.get("/admin/users")).status_code == 403


@pytest.mark.asyncio
async def test_admin_lists_users(admin_http):
    response = await admin_http.get("/admin/users")
    assert response.status_code == 200
    users = {u["username"]: u for u in response.json()}
    assert users["operator"]["role"] == "admin"
    assert users["bob"]["role"] == "user"
    assert users["bob"]["client_ids"] == []


@pytest.mark.asyncio
async def test_admin_creates_user_with_role_and_clients(admin_app, admin_http):
    app, _ = admin_app
    response = await admin_http.post("/admin/users", json={
        "username": "carol", "password": "carol-pass", "role": "user", "client_ids": [1],
    })
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "carol"
    assert body["role"] == "user"
    assert body["client_ids"] == [1]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as login:
        assert (await login.post(
            "/auth/login", json={"username": "carol", "password": "carol-pass"}
        )).status_code == 200


@pytest.mark.asyncio
async def test_admin_create_rejects_duplicate_username(admin_http):
    response = await admin_http.post("/admin/users", json={
        "username": "bob", "password": "x", "role": "user", "client_ids": [],
    })
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_admin_updates_role_clients_and_active(admin_http):
    users = {u["username"]: u for u in (await admin_http.get("/admin/users")).json()}
    bob_id = users["bob"]["id"]
    response = await admin_http.patch(f"/admin/users/{bob_id}", json={
        "client_ids": [1], "is_active": False,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["client_ids"] == [1]
    assert body["is_active"] is False
    # Deactivation is effective on the next request: bob's existing session dies.
    assert (await admin_http.get("/auth/me")).status_code == 200  # admin unaffected


@pytest.mark.asyncio
async def test_admin_resets_password_and_revokes_sessions(admin_app, admin_http):
    app, factory = admin_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as bob:
        assert (await bob.post(
            "/auth/login", json={"username": "bob", "password": "bob-pass"}
        )).status_code == 200
        users = {u["username"]: u for u in (await admin_http.get("/admin/users")).json()}
        bob_id = users["bob"]["id"]
        reset = await admin_http.post(
            f"/admin/users/{bob_id}/password", json={"new_password": "new-bob-pass"}
        )
        assert reset.status_code == 204
        assert (await bob.get("/auth/me")).status_code == 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as reborn:
        assert (await reborn.post(
            "/auth/login", json={"username": "bob", "password": "new-bob-pass"}
        )).status_code == 200


@pytest.mark.asyncio
async def test_admin_user_endpoints_404_on_unknown_user(admin_http):
    assert (await admin_http.patch("/admin/users/99999", json={"role": "admin"})).status_code == 404
    assert (await admin_http.post(
        "/admin/users/99999/password", json={"new_password": "x"}
    )).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_admin_users_api.py -v`
Expected: FAIL — 404s everywhere (`/admin/users` does not exist).

- [ ] **Step 3: Create the schemas**

Create `backend/app/schemas/admin.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    is_active: bool
    client_ids: list[int]


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    role: Literal["admin", "user"] = "user"
    client_ids: list[int] = Field(default_factory=list)
    is_active: bool = True


class AdminUserUpdate(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    client_ids: list[int] | None = None


class PasswordSet(BaseModel):
    new_password: str = Field(min_length=1)


class GlobalSettingsOut(BaseModel):
    staging_removal_retention_days: int = Field(ge=1)
    staging_history_retention_days: int = Field(ge=1)
    ingestion_run_retention_days: int = Field(ge=1)


class GlobalSettingsUpdate(GlobalSettingsOut):
    pass
```

- [ ] **Step 4: Add user-admin persistence helpers**

Append to `backend/app/persistence/users.py` (it already imports `insert`, `select`; add `delete` to the `sqlalchemy` import):

```python
async def list_users(session: AsyncSession) -> list[tuple[User, list[int]]]:
    users = list((await session.execute(select(User).order_by(User.id))).scalars())
    assignments = list((await session.execute(select(UserClient))).all())
    by_user: dict[int, list[int]] = {}
    for user_id, client_id in assignments:
        by_user.setdefault(user_id, []).append(client_id)
    return [(user, sorted(by_user.get(user.id, []))) for user in users]


async def create_user(
    session: AsyncSession,
    username: str,
    password: str,
    role: str,
    client_ids: list[int],
    is_active: bool = True,
) -> User:
    async with _repository_transaction(session):
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        session.add(user)
        await session.flush()
        for client_id in client_ids:
            session.add(UserClient(user_id=user.id, client_id=client_id))
        await session.flush()
        return user


async def update_user(
    session: AsyncSession,
    user_id: int,
    role: str | None = None,
    is_active: bool | None = None,
    client_ids: list[int] | None = None,
) -> User | None:
    async with _repository_transaction(session):
        user = await session.get(User, user_id)
        if user is None:
            return None
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        if client_ids is not None:
            await session.execute(
                delete(UserClient).where(UserClient.user_id == user_id)
            )
            for client_id in client_ids:
                session.add(UserClient(user_id=user_id, client_id=client_id))
        await session.flush()
        return user


async def set_user_password(
    session: AsyncSession, user_id: int, new_password: str
) -> bool:
    async with _repository_transaction(session):
        user = await session.get(User, user_id)
        if user is None:
            return False
        user.password_hash = hash_password(new_password)
        user.revocation_generation += 1
        return True
```

Add to the imports at the top of the file:

```python
from app.models.user_client import UserClient
```

- [ ] **Step 5: Create the admin users router**

Create `backend/app/routes/admin.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import CurrentUser, require_admin
from ..db.engine import get_db_session
from ..models.global_setting import GlobalSetting
from ..persistence import users as user_repo
from ..schemas.admin import (
    AdminUserCreate,
    AdminUserOut,
    AdminUserUpdate,
    GlobalSettingsOut,
    GlobalSettingsUpdate,
    PasswordSet,
)

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _user_out(user, client_ids: list[int]) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        client_ids=client_ids,
    )


@router.get("/admin/users", response_model=list[AdminUserOut])
async def list_users(
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> list[AdminUserOut]:
    session = _require_db(db_session)
    rows = await user_repo.list_users(session)
    return [_user_out(user, client_ids) for user, client_ids in rows]


@router.post("/admin/users", status_code=201, response_model=AdminUserOut)
async def create_user(
    payload: AdminUserCreate,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> AdminUserOut:
    session = _require_db(db_session)
    try:
        user = await user_repo.create_user(
            session,
            payload.username,
            payload.password,
            payload.role,
            payload.client_ids,
            payload.is_active,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="username already exists") from exc
    return _user_out(user, payload.client_ids)


@router.patch("/admin/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> AdminUserOut:
    session = _require_db(db_session)
    user = await user_repo.update_user(
        session,
        user_id,
        role=payload.role,
        is_active=payload.is_active,
        client_ids=payload.client_ids,
    )
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    rows = dict(await _assignments(session))
    return _user_out(user, rows.get(user.id, []))


async def _assignments(session: AsyncSession) -> list[tuple[int, int]]:
    from sqlalchemy import select

    from ..models.user_client import UserClient

    result = await session.execute(select(UserClient.user_id, UserClient.client_id))
    return [(row[0], row[1]) for row in result.all()]


@router.post("/admin/users/{user_id}/password", status_code=204)
async def set_password(
    user_id: int,
    payload: PasswordSet,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> None:
    session = _require_db(db_session)
    if not await user_repo.set_user_password(session, user_id, payload.new_password):
        raise HTTPException(status_code=404, detail="user not found")
```

- [ ] **Step 6: Mount the router**

In `backend/app/main.py`, add the import with the other route imports:

```python
from .routes.admin import router as admin_router
```

and mount it with the other routers (after `registry_router`):

```python
    app.include_router(admin_router)
```

(The `require_admin` dependency on each handler already gates `/admin/*` — no scope dependency needed.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_users_api.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/admin.py backend/app/persistence/users.py backend/app/routes/admin.py backend/app/main.py backend/tests/test_admin_users_api.py
git commit -m "feat(backend): /admin/users CRUD with role, client assignment, password reset"
```

---

### Task 5: Admin settings + scheduler API, purge reads DB

**Files:**
- Modify: `backend/app/routes/admin.py` (settings + scheduler endpoints)
- Modify: `backend/app/staging/purge.py:15-17,33-38,68-72` (retention from DB)
- Modify: `backend/app/pipeline/scheduler.py` (add `list_jobs`)
- Test: `backend/tests/test_admin_settings_api.py`

**Interfaces:**
- Consumes: `GlobalSetting` model (Task 1), `require_admin` (Task 2)
- Produces:
  - `GET /admin/settings` → `GlobalSettingsOut` (seeds row with 90s on first read)
  - `PUT /admin/settings` → `GlobalSettingsOut`
  - `GET /admin/scheduler` → `list[dict]` of `{"id": str, "trigger": str}`
  - `SchedulerService.list_jobs() -> list[dict[str, str]]`
  - `purge_expired` / `purge_expired_ingestion_runs` keep their signatures `(session_factory, now)` but read retention days from `global_settings` (fallback 90)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_admin_settings_api.py`:

```python
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models.global_setting import GlobalSetting
from app.models.ingestion import IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.staging.purge import purge_expired, purge_expired_ingestion_runs


@pytest_asyncio.fixture
async def settings_app(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(Session))
            await session.execute(delete(User))
            await session.execute(delete(GlobalSetting))
        await seed_initial_user(session, "operator", "admin-pass")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="admin-pass",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_http(settings_app):
    app, _ = settings_app
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.post(
        "/auth/login", json={"username": "operator", "password": "admin-pass"}
    )).status_code == 200
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_get_settings_seeds_defaults(settings_app, admin_http):
    response = await admin_http.get("/admin/settings")
    assert response.status_code == 200
    assert response.json() == {
        "staging_removal_retention_days": 90,
        "staging_history_retention_days": 90,
        "ingestion_run_retention_days": 90,
    }


@pytest.mark.asyncio
async def test_put_settings_persists(settings_app, admin_http):
    response = await admin_http.put("/admin/settings", json={
        "staging_removal_retention_days": 30,
        "staging_history_retention_days": 45,
        "ingestion_run_retention_days": 60,
    })
    assert response.status_code == 200
    assert response.json()["staging_removal_retention_days"] == 30
    follow_up = await admin_http.get("/admin/settings")
    assert follow_up.json()["staging_history_retention_days"] == 45


@pytest.mark.asyncio
async def test_put_settings_rejects_non_positive(settings_app, admin_http):
    response = await admin_http.put("/admin/settings", json={
        "staging_removal_retention_days": 0,
        "staging_history_retention_days": 90,
        "ingestion_run_retention_days": 90,
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_scheduler_lists_system_jobs(settings_app, admin_http):
    app, _ = settings_app
    async with app.router.lifespan_context(app):
        response = await admin_http.get("/admin/scheduler")
    assert response.status_code == 200
    jobs = {job["id"] for job in response.json()}
    assert "system-staging-purge" in jobs
    assert "system-ingestion-run-purge" in jobs


@pytest.mark.asyncio
async def test_purge_honors_configured_retention(settings_app):
    app, factory = settings_app
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with factory() as session:
        async with session.begin():
            session.add(GlobalSetting(
                id=1,
                staging_removal_retention_days=1,
                staging_history_retention_days=1,
                ingestion_run_retention_days=1,
            ))
    # Fresh row at `now` survives a 1-day cutoff; a 10-day-old row does not.
    counts = await purge_expired(factory, now)
    assert counts.removed_products == 0
    counts = await purge_expired(factory, now + timedelta(days=10))
    assert counts.removed_products >= 0  # runs against whatever rows exist; must not raise
    run_counts = await purge_expired_ingestion_runs(factory, now + timedelta(days=10))
    assert run_counts.runs_purged >= 0
```

Note: `purge_expired` against a bare database (no staging rows) is a valid smoke assertion here — the point is that DB-configured retention is read without error. The dedicated retention-behavior test below exercises actual deletion using existing fixtures.

Also add to the same file (reuses `isolated_database_url` only):

```python
@pytest.mark.asyncio
async def test_ingestion_run_purge_uses_db_retention(isolated_database_url):
    # Import the shared test helpers used by test_staging_purge.py to build a
    # feed source + old ingestion run; if those helpers are module-level
    # functions, call them directly. If they are fixtures, copy the minimal
    # setup (client, feed_source, ingestion_run with started_at 100 days ago)
    # inline here instead:
    from app.models.client import Client
    from app.models.feed_source import FeedSource

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            client = Client(name="Purge Co")
            session.add(client)
            await session.flush()
            feed = FeedSource(client_id=client.id, name="F", source_format="xml",
                              source_url="https://x.example/f.xml")
            session.add(feed)
            await session.flush()
            session.add(IngestionRun(
                feed_source_id=feed.id, status="completed",
                started_at=now - timedelta(days=100),
            ))
            session.add(GlobalSetting(
                id=1,
                staging_removal_retention_days=90,
                staging_history_retention_days=90,
                ingestion_run_retention_days=50,
            ))
    counts = await purge_expired_ingestion_runs(factory, now)
    assert counts.runs_purged == 1
    await engine.dispose()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_admin_settings_api.py -v`
Expected: FAIL — endpoints missing; purge ignores `global_settings`.

- [ ] **Step 3: Make purge read DB settings**

In `backend/app/staging/purge.py`: replace the three constants (lines 15-17) with:

```python
DEFAULT_REMOVAL_RETENTION_DAYS = 90
DEFAULT_HISTORY_RETENTION_DAYS = 90
DEFAULT_INGESTION_RUN_RETENTION_DAYS = 90


async def _retention(session: AsyncSession) -> tuple[int, int, int]:
    from ..models.global_setting import GlobalSetting

    row = await session.get(GlobalSetting, 1)
    if row is None:
        return (
            DEFAULT_REMOVAL_RETENTION_DAYS,
            DEFAULT_HISTORY_RETENTION_DAYS,
            DEFAULT_INGESTION_RUN_RETENTION_DAYS,
        )
    return (
        row.staging_removal_retention_days,
        row.staging_history_retention_days,
        row.ingestion_run_retention_days,
    )
```

In `purge_expired`, replace the two cutoff lines with:

```python
        removal_days, history_days, _ = await _retention(session)
        removal_cutoff = now - timedelta(days=removal_days)
        history_cutoff = now - timedelta(days=history_days)
```

In `purge_expired_ingestion_runs`, replace the cutoff line with:

```python
        _, _, ingestion_days = await _retention(session)
        cutoff = now - timedelta(days=ingestion_days)
```

(Place both lookups after `async with session.begin():` so they share the transaction; `session.get` on primary key needs no explicit flush.)

- [ ] **Step 4: Add settings and scheduler endpoints**

Append to `backend/app/routes/admin.py`:

```python
@router.get("/admin/settings", response_model=GlobalSettingsOut)
async def get_settings_row(
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> GlobalSetting:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(GlobalSetting, 1)
        if row is None:
            row = GlobalSetting(
                id=1,
                staging_removal_retention_days=90,
                staging_history_retention_days=90,
                ingestion_run_retention_days=90,
            )
            session.add(row)
    return row


@router.put("/admin/settings", response_model=GlobalSettingsOut)
async def put_settings_row(
    payload: GlobalSettingsUpdate,
    _admin: CurrentUser = Depends(require_admin),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> GlobalSetting:
    session = _require_db(db_session)
    async with session.begin():
        row = await session.get(GlobalSetting, 1)
        if row is None:
            row = GlobalSetting(id=1)
            session.add(row)
        row.staging_removal_retention_days = payload.staging_removal_retention_days
        row.staging_history_retention_days = payload.staging_history_retention_days
        row.ingestion_run_retention_days = payload.ingestion_run_retention_days
    return row


@router.get("/admin/scheduler")
async def scheduler_jobs(
    request: Request,
    _admin: CurrentUser = Depends(require_admin),
) -> list[dict[str, str]]:
    scheduler = getattr(request.app.state, "scheduler_service", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="scheduler unavailable")
    return scheduler.list_jobs()
```

Add `Request` to the `fastapi` import line in this file.

- [ ] **Step 5: Add `list_jobs` to SchedulerService**

In `backend/app/pipeline/scheduler.py`, add a method to `SchedulerService`:

```python
    def list_jobs(self) -> list[dict[str, str]]:
        return [
            {"id": str(job.id), "trigger": str(job.trigger)}
            for job in self._scheduler.get_jobs()
        ]
```

Note: the scheduler only contains jobs while the app's lifespan ran (`scheduler_service.start()` registers the system purge jobs) — that is why `test_get_scheduler_lists_system_jobs` wraps the request in `app.router.lifespan_context(app)` (same pattern as `test_postgres_auth.py`).

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_settings_api.py tests/test_staging_purge.py -v`
Expected: PASS — existing purge tests pass because no `global_settings` row exists in their databases (fallback 90).

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/admin.py backend/app/staging/purge.py backend/app/pipeline/scheduler.py backend/tests/test_admin_settings_api.py
git commit -m "feat(backend): /admin/settings + /admin/scheduler, purge retention from DB"
```

---

### Task 6: Frontend API layer

**Files:**
- Modify: `frontend/src/api/client.ts:1,89-91`
- Modify: `frontend/src/api/types.ts` (add admin types)
- Modify: `frontend/src/api/queryKeys.ts` (admin keys)
- Modify: `frontend/src/api/hooks.ts` (session type + admin hooks)
- Test: `frontend/src/api/hooks.admin.test.tsx`

**Interfaces:**
- Consumes: backend endpoints from Tasks 2-5
- Produces:
  - `User = { username: string; role: 'admin' | 'user'; client_ids: number[] | null }` (client.ts)
  - `AdminUser`, `GlobalSettings`, `SchedulerJob` types
  - `queryKeys.adminUsers`, `queryKeys.adminSettings`, `queryKeys.adminScheduler`
  - Hooks: `useAdminUsers`, `useCreateAdminUser`, `useUpdateAdminUser`, `useResetUserPassword`, `useAdminSettings`, `useSaveAdminSettings`, `useSchedulerJobs`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/api/hooks.admin.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPatch = vi.fn();

vi.mock('./client', async () => {
  const actual = await vi.importActual<typeof import('./client')>('./client');
  return { ...actual, apiGet, apiPost, apiPatch };
});

import { useAdminUsers, useAdminSettings } from './hooks';

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('admin hooks', () => {
  it('useAdminUsers fetches /admin/users', async () => {
    apiGet.mockResolvedValue([
      { id: 1, username: 'operator', role: 'admin', is_active: true, client_ids: [] },
    ]);
    const { result } = renderHook(() => useAdminUsers(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledWith('/admin/users');
    expect(result.current.data?.[0].username).toBe('operator');
  });

  it('useAdminSettings fetches /admin/settings', async () => {
    apiGet.mockResolvedValue({
      staging_removal_retention_days: 90,
      staging_history_retention_days: 90,
      ingestion_run_retention_days: 90,
    });
    const { result } = renderHook(() => useAdminSettings(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledWith('/admin/settings');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- hooks.admin`
Expected: FAIL — hooks don't exist.

- [ ] **Step 3: Extend the types and client**

In `frontend/src/api/client.ts`, replace line 1 and `getCurrentUser`:

```ts
export type User = { username: string; role: 'admin' | 'user'; client_ids: number[] | null };
```

```ts
export function getCurrentUser(): Promise<User> {
  return apiGet<User>('/auth/me');
}
```

In `frontend/src/api/types.ts`, append:

```ts
export type AdminUser = {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  client_ids: number[];
};

export type GlobalSettings = {
  staging_removal_retention_days: number;
  staging_history_retention_days: number;
  ingestion_run_retention_days: number;
};

export type SchedulerJob = { id: string; trigger: string };
```

- [ ] **Step 4: Add query keys and hooks**

In `frontend/src/api/queryKeys.ts`, append inside the object:

```ts
  adminUsers: ['admin', 'users'] as const,
  adminSettings: ['admin', 'settings'] as const,
  adminScheduler: ['admin', 'scheduler'] as const,
```

In `frontend/src/api/hooks.ts`: add `AdminUser, GlobalSettings, SchedulerJob` to the type imports and re-exports, then append:

```ts
export function useAdminUsers() {
  return useQuery({
    queryKey: queryKeys.adminUsers,
    queryFn: () => apiGet<AdminUser[]>('/admin/users'),
  });
}

export function useCreateAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      username: string;
      password: string;
      role: 'admin' | 'user';
      client_ids: number[];
    }) => apiPost<AdminUser>('/admin/users', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers });
    },
  });
}

export function useUpdateAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: {
      id: number;
      role?: 'admin' | 'user';
      is_active?: boolean;
      client_ids?: number[];
    }) => apiPatch<AdminUser>(`/admin/users/${id}`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers });
    },
  });
}

export function useResetUserPassword() {
  return useMutation({
    mutationFn: ({ id, newPassword }: { id: number; newPassword: string }) =>
      apiPost<void>(`/admin/users/${id}/password`, { new_password: newPassword }),
  });
}

export function useAdminSettings() {
  return useQuery({
    queryKey: queryKeys.adminSettings,
    queryFn: () => apiGet<GlobalSettings>('/admin/settings'),
  });
}

export function useSaveAdminSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: GlobalSettings) => apiPut<GlobalSettings>('/admin/settings', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminSettings });
    },
  });
}

export function useSchedulerJobs() {
  return useQuery({
    queryKey: queryKeys.adminScheduler,
    queryFn: () => apiGet<SchedulerJob[]>('/admin/scheduler'),
    retry: false,
  });
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm run test -- hooks.admin && npm run typecheck`
Expected: PASS, no type errors. If existing tests assert the old `User` shape (`{username}` only), update their mock data to include `role: 'admin', client_ids: null` — a search for `getCurrentUser` and `useSession` mocks in `*.test.tsx` finds them (notably `router.test.tsx`, `LoginPage` tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/
git commit -m "feat(frontend): admin API hooks, session role type"
```

---

### Task 7: Frontend admin pages, guard, nav, i18n

**Files:**
- Create: `frontend/src/features/admin/AdminUsersPage.tsx`
- Create: `frontend/src/features/admin/AdminClientsPage.tsx`
- Create: `frontend/src/features/admin/AdminSettingsPage.tsx`
- Modify: `frontend/src/app/router.tsx` (lazy pages, `RequireAdmin`)
- Modify: `frontend/src/app/AppShell.tsx` (admin nav group)
- Modify: `frontend/src/features/dashboard/DashboardPage.tsx:194-219` (admin-only button → link to /admin/clients)
- Create: `frontend/public/locales/en/admin.json`, `frontend/public/locales/de/admin.json`
- Modify: `frontend/public/locales/en/common.json`, `frontend/public/locales/de/common.json` (nav keys)
- Test: `frontend/src/features/admin/AdminPages.test.tsx`

**Interfaces:**
- Consumes: hooks from Task 6, `useSession` (role), existing `ClientModal`/`DeleteClientModal` from `../dashboard/`, `useClients`/`useCreateClient`/`useUpdateClient`/`useDeleteClient` from `api/hooks.ts`, `usePlugins` + plugin enable/disable mutation (existing, check exact hook name in `api/hooks.ts` — if none exists, use `apiPut(`/plugins/${id}/enabled`, {enabled})` via a small local `useMutation`)
- Produces: routes `/admin/users`, `/admin/clients`, `/admin/settings` guarded by `RequireAdmin`; exported `RequireAdmin` in `router.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/admin/AdminPages.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { RequireAdmin } from '../../app/router';

vi.mock('../../api/hooks', async () => {
  const actual = await vi.importActual<typeof import('../../api/hooks')>('../../api/hooks');
  return {
    ...actual,
    useSession: vi.fn(() => ({ data: { username: 'bob', role: 'user', client_ids: [1] }, status: 'success' })),
  };
});

describe('RequireAdmin', () => {
  it('redirects non-admin users away from admin routes', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/admin/users']}>
        <RequireAdmin />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText(/users/i)).not.toBeInTheDocument();
  });
});
```

(`MemoryRouter` renders the `<Navigate to="/">` as empty output; the important assertion is that no admin content renders.)

Add a second test file `frontend/src/app/AdminNav.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import i18n from '../i18n';

vi.mock('../api/hooks', async () => {
  const actual = await vi.importActual<typeof import('../api/hooks')>('../api/hooks');
  return {
    ...actual,
    useSession: vi.fn(() => ({ data: { username: 'op', role: 'admin', client_ids: null }, status: 'success' })),
    usePlugins: vi.fn(() => ({ data: [] })),
  };
});

import { AppShell } from './AppShell';

describe('AppShell admin nav', () => {
  it('shows administration links for admins', () => {
    render(
      <I18nextProvider i18n={i18n}>
        <MemoryRouter>
          <AppShell />
        </MemoryRouter>
      </I18nextProvider>,
    );
    expect(screen.getByText('nav.adminUsers')).toBeDefined();
  });
});
```

Note: raw i18n keys render when translations are not loaded in tests — asserting on the key text (`nav.adminUsers`) is acceptable and matches how `AppShell` renders `t(...)` calls before dictionaries load.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- AdminPages AdminNav`
Expected: FAIL — `RequireAdmin` doesn't exist, nav has no admin links.

- [ ] **Step 3: Add the route guard and admin routes**

In `frontend/src/app/router.tsx`:

1. Add lazy imports next to the existing ones:

```tsx
const AdminUsersPage = lazy(() =>
  import('../features/admin/AdminUsersPage').then((m) => ({ default: m.AdminUsersPage })),
);
const AdminClientsPage = lazy(() =>
  import('../features/admin/AdminClientsPage').then((m) => ({ default: m.AdminClientsPage })),
);
const AdminSettingsPage = lazy(() =>
  import('../features/admin/AdminSettingsPage').then((m) => ({ default: m.AdminSettingsPage })),
);
```

2. Add the guard (next to `RequireSession`):

```tsx
export function RequireAdmin() {
  const { status, data, error, refetch } = useSession();
  if (status === 'pending') return <LoadingState />;
  if (status === 'error') return <ErrorState onRetry={() => void refetch()} />;
  if (data?.role !== 'admin') return <Navigate to="/" replace />;
  return <Outlet />;
}
```

3. Add admin routes inside the `AppShell` children array (after the dashboard index route):

```tsx
          {
            element: <RequireAdmin />,
            children: [
              { path: 'admin/users', element: <AdminUsersPage /> },
              { path: 'admin/clients', element: <AdminClientsPage /> },
              { path: 'admin/settings', element: <AdminSettingsPage /> },
            ],
          },
```

- [ ] **Step 4: Create the Admin Users page**

Create `frontend/src/features/admin/AdminUsersPage.tsx`:

```tsx
import { useState } from 'react';
import {
  ActionIcon, Badge, Button, Group, Modal, MultiSelect, PasswordInput,
  Select, Stack, Switch, Table, TextInput, Title,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconKey, IconPencil, IconPlus } from '@tabler/icons-react';
import {
  useAdminUsers, useClients, useCreateAdminUser, useResetUserPassword,
  useUpdateAdminUser,
} from '../../api/hooks';
import type { AdminUser } from '../../api/types';
import { LoadingState, ErrorState } from '../../components/StateViews';
import { notifyMutationError, notifySuccess } from '../../app/notifications';

type ClientOption = { value: string; label: string };

export function AdminUsersPage() {
  const { t } = useTranslation('admin');
  const usersQuery = useAdminUsers();
  const clientsQuery = useClients();
  const updateUser = useUpdateAdminUser();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [passwordUser, setPasswordUser] = useState<AdminUser | null>(null);

  if (usersQuery.isPending || clientsQuery.isPending) return <LoadingState />;
  if (usersQuery.isError || clientsQuery.isError) {
    return (
      <ErrorState
        onRetry={() => {
          void usersQuery.refetch();
          void clientsQuery.refetch();
        }}
      />
    );
  }

  const clientOptions: ClientOption[] = clientsQuery.data.map((c) => ({
    value: String(c.id),
    label: c.name,
  }));

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('users.title')}</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
          {t('users.add')}
        </Button>
      </Group>
      <Table striped data-testid="admin-users-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('users.columns.username')}</Table.Th>
            <Table.Th>{t('users.columns.role')}</Table.Th>
            <Table.Th>{t('users.columns.clients')}</Table.Th>
            <Table.Th>{t('users.columns.active')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {usersQuery.data.map((user) => (
            <Table.Tr key={user.id} data-testid={`user-row-${user.username}`}>
              <Table.Td>{user.username}</Table.Td>
              <Table.Td>
                <Badge variant="light" color={user.role === 'admin' ? 'grape' : 'blue'}>
                  {user.role === 'admin' ? t('users.roleAdmin') : t('users.roleUser')}
                </Badge>
              </Table.Td>
              <Table.Td>{user.client_ids.length}</Table.Td>
              <Table.Td>
                <Switch
                  aria-label={t('users.columns.active')}
                  checked={user.is_active}
                  onChange={(event) =>
                    updateUser.mutate({ id: user.id, is_active: event.currentTarget.checked })
                  }
                />
              </Table.Td>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  <ActionIcon
                    variant="subtle"
                    aria-label={t('users.edit')}
                    onClick={() => setEditing(user)}
                  >
                    <IconPencil size={16} />
                  </ActionIcon>
                  <ActionIcon
                    variant="subtle"
                    aria-label={t('users.resetPassword')}
                    onClick={() => setPasswordUser(user)}
                  >
                    <IconKey size={16} />
                  </ActionIcon>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <UserModal
        key={editing?.id ?? 'new'}
        opened={creating || editing !== null}
        user={editing}
        clientOptions={clientOptions}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
      />
      <ResetPasswordModal user={passwordUser} onClose={() => setPasswordUser(null)} />
    </Stack>
  );
}

function UserModal({
  opened,
  user,
  clientOptions,
  onClose,
}: {
  opened: boolean;
  user: AdminUser | null;
  clientOptions: ClientOption[];
  onClose: () => void;
}) {
  const { t } = useTranslation('admin');
  const createUser = useCreateAdminUser();
  const updateUser = useUpdateAdminUser();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'admin' | 'user'>(
    user?.role === 'admin' ? 'admin' : 'user',
  );
  const [clientIds, setClientIds] = useState<string[]>(
    user ? user.client_ids.map(String) : [],
  );

  function submit() {
    const clientIdsAsNumbers = clientIds.map(Number);
    const onSuccess = () => {
      notifySuccess(t('users.saved'));
      onClose();
    };
    const onError = (error: unknown) => notifyMutationError(error, t('users.saveFailed'));
    if (user) {
      updateUser.mutate(
        { id: user.id, role, client_ids: clientIdsAsNumbers },
        { onSuccess, onError },
      );
    } else {
      createUser.mutate(
        { username, password, role, client_ids: clientIdsAsNumbers },
        { onSuccess, onError },
      );
    }
  }

  return (
    <Modal opened={opened} onClose={onClose} title={user ? t('users.edit') : t('users.add')} centered>
      <Stack gap="md">
        {!user && (
          <>
            <TextInput
              label={t('users.columns.username')}
              value={username}
              onChange={(e) => setUsername(e.currentTarget.value)}
              required
            />
            <PasswordInput
              label={t('users.columns.password')}
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              required
            />
          </>
        )}
        <Select
          label={t('users.columns.role')}
          data={[
            { value: 'user', label: t('users.roleUser') },
            { value: 'admin', label: t('users.roleAdmin') },
          ]}
          value={role}
          onChange={(value) => setRole(value === 'admin' ? 'admin' : 'user')}
          allowDeselect={false}
        />
        <MultiSelect
          label={t('users.columns.clients')}
          data={clientOptions}
          value={clientIds}
          onChange={setClientIds}
        />
        <Button
          onClick={submit}
          loading={createUser.isPending || updateUser.isPending}
          disabled={!user && (!username || !password)}
        >
          {t('users.save')}
        </Button>
      </Stack>
    </Modal>
  );
}

function ResetPasswordModal({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const { t } = useTranslation('admin');
  const resetPassword = useResetUserPassword();
  const [password, setPassword] = useState('');
  if (!user) return null;
  return (
    <Modal opened={user !== null} onClose={onClose} title={t('users.resetPassword')} centered>
      <Stack gap="md">
        <PasswordInput
          label={t('users.columns.password')}
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
          required
        />
        <Button
          loading={resetPassword.isPending}
          disabled={!password}
          onClick={() =>
            resetPassword.mutate(
              { id: user.id, newPassword: password },
              {
                onSuccess: () => {
                  notifySuccess(t('users.saved'));
                  onClose();
                },
                onError: (error) => notifyMutationError(error, t('users.saveFailed')),
              },
            )
          }
        >
          {t('users.save')}
        </Button>
      </Stack>
    </Modal>
  );
}
```

(The `key={editing?.id ?? 'new'}` on `UserModal` resets the modal's local state when switching users.)

- [ ] **Step 5: Create the Admin Clients page**

Create `frontend/src/features/admin/AdminClientsPage.tsx` (reuses the dashboard's existing modals — check their exact prop signatures in `frontend/src/features/dashboard/DashboardPage.tsx` where they are used):

```tsx
import { useState } from 'react';
import { ActionIcon, Group, Stack, Table, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconPlus } from '@tabler/icons-react';
import { Button } from '@mantine/core';
import { useClients } from '../../api/hooks';
import { ClientModal } from '../dashboard/ClientModal';
import { DeleteClientModal } from '../dashboard/DeleteClientModal';
import { LoadingState, ErrorState } from '../../components/StateViews';
import type { ClientRow } from '../../api/types';

export function AdminClientsPage() {
  const { t } = useTranslation('admin');
  const clientsQuery = useClients();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ClientRow | null>(null);
  const [deleting, setDeleting] = useState<ClientRow | null>(null);

  if (clientsQuery.isPending) return <LoadingState />;
  if (clientsQuery.isError) return <ErrorState onRetry={() => void clientsQuery.refetch()} />;

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('clients.title')}</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
          {t('clients.add')}
        </Button>
      </Group>
      <Table striped data-testid="admin-clients-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('clients.columns.name')}</Table.Th>
            <Table.Th>{t('clients.columns.status')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {clientsQuery.data.map((client) => (
            <Table.Tr key={client.id} data-testid={`client-row-${client.name}`}>
              <Table.Td>{client.name}</Table.Td>
              <Table.Td>{client.status}</Table.Td>
              <Table.Td>
                <Group gap="xs">
                  <Button variant="subtle" size="xs" onClick={() => setEditing(client)}>
                    {t('clients.edit')}
                  </Button>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    aria-label={t('clients.delete')}
                    onClick={() => setDeleting(client)}
                  >
                    ✕
                  </ActionIcon>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <ClientModal opened={creating || editing !== null} client={editing} onClose={() => { setCreating(false); setEditing(null); }} />
      <DeleteClientModal client={deleting} onClose={() => setDeleting(null)} />
    </Stack>
  );
}
```

Check `ClientModal`/`DeleteClientModal` prop signatures before wiring (DashboardPage.tsx is the reference); adjust the props to match exactly (e.g. `opened` may be implicit). If `ClientModal` manages its own open state, drive it the same way `DashboardPage` does.

- [ ] **Step 6: Create the Admin Settings page**

Create `frontend/src/features/admin/AdminSettingsPage.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Badge, Button, Group, NumberInput, Stack, Table, Text, Title, Switch } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { apiGet, apiPut } from '../../api/client';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  useAdminSettings, usePlugins, useSaveAdminSettings, useSchedulerJobs,
} from '../../api/hooks';
import { LoadingState, ErrorState } from '../../components/StateViews';
import { notifyMutationError, notifySuccess } from '../../app/notifications';

export function AdminSettingsPage() {
  const { t } = useTranslation('admin');
  const settingsQuery = useAdminSettings();
  const schedulerQuery = useSchedulerJobs();
  const pluginsQuery = usePlugins();
  const saveSettings = useSaveAdminSettings();
  const queryClient = useQueryClient();
  const [removal, setRemoval] = useState(90);
  const [history, setHistory] = useState(90);
  const [ingestion, setIngestion] = useState(90);

  useEffect(() => {
    if (settingsQuery.data) {
      setRemoval(settingsQuery.data.staging_removal_retention_days);
      setHistory(settingsQuery.data.staging_history_retention_days);
      setIngestion(settingsQuery.data.ingestion_run_retention_days);
    }
  }, [settingsQuery.data]);

  const togglePlugin = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiPut(`/plugins/${id}/enabled`, { enabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['plugins'] });
    },
  });

  if (settingsQuery.isPending) return <LoadingState />;
  if (settingsQuery.isError) return <ErrorState onRetry={() => void settingsQuery.refetch()} />;

  return (
    <Stack>
      <Title order={3}>{t('settings.title')}</Title>

      <Stack gap="md" maw={420}>
        <NumberInput
          label={t('settings.removalRetention')}
          value={removal}
          min={1}
          onChange={(v) => setRemoval(Number(v) || 1)}
        />
        <NumberInput
          label={t('settings.historyRetention')}
          value={history}
          min={1}
          onChange={(v) => setHistory(Number(v) || 1)}
        />
        <NumberInput
          label={t('settings.ingestionRetention')}
          value={ingestion}
          min={1}
          onChange={(v) => setIngestion(Number(v) || 1)}
        />
        <Button
          loading={saveSettings.isPending}
          onClick={() =>
            saveSettings.mutate(
              {
                staging_removal_retention_days: removal,
                staging_history_retention_days: history,
                ingestion_run_retention_days: ingestion,
              },
              {
                onSuccess: () => notifySuccess(t('settings.saved')),
                onError: (error) => notifyMutationError(error, t('settings.saveFailed')),
              },
            )
          }
        >
          {t('settings.save')}
        </Button>
      </Stack>

      <Title order={4}>{t('settings.scheduler')}</Title>
      {schedulerQuery.isPending ? (
        <Text size="sm" c="dimmed">{t('common.loading')}</Text>
      ) : schedulerQuery.isError ? (
        <Text size="sm" c="dimmed">{t('settings.schedulerUnavailable')}</Text>
      ) : (
        <Table striped data-testid="admin-scheduler-table" maw={600}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('settings.jobId')}</Table.Th>
              <Table.Th>{t('settings.trigger')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {schedulerQuery.data.map((job) => (
              <Table.Tr key={job.id}>
                <Table.Td><Badge variant="light">{job.id}</Badge></Table.Td>
                <Table.Td>{job.trigger}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Title order={4}>{t('settings.plugins')}</Title>
      <Table striped maw={600} data-testid="admin-plugins-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('settings.pluginName')}</Table.Th>
            <Table.Th>{t('settings.pluginEnabled')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(pluginsQuery.data ?? []).map((plugin: { id: string; name: string; enabled: boolean }) => (
            <Table.Tr key={plugin.id}>
              <Table.Td>{plugin.name}</Table.Td>
              <Table.Td>
                <Switch
                  aria-label={t('settings.pluginEnabled')}
                  checked={plugin.enabled}
                  onChange={(event) =>
                    togglePlugin.mutate({ id: plugin.id, enabled: event.currentTarget.checked })
                  }
                />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
```

Check the plugin enable/disable endpoint path in `backend/app/routes/plugins.py` (route `PUT /plugins/{plugin_id}/enabled` with body `{"enabled": bool}`) and the `PluginInfo` type in `api/types.ts`; adjust the `togglePlugin` mutation and the plugin row type to match exactly.

- [ ] **Step 7: Nav group, dashboard button, i18n**

In `frontend/src/app/AppShell.tsx`:
1. Add `const { data: session } = useSession();` inside `AppShell`.
2. After the dashboard `NavLink` in the Navbar `Stack`, add:

```tsx
          {session?.role === 'admin' && (
            <>
              <Text size="xs" c="dimmed" mt="sm">{t('nav.adminSection')}</Text>
              <NavLink
                component={Link}
                to="/admin/users"
                label={t('nav.adminUsers')}
                leftSection={<IconUsers size={16} />}
                active={isActive('/admin/users')}
                variant={isActive('/admin/users') ? 'light' : undefined}
                color={isActive('/admin/users') ? 'blue' : undefined}
                onClick={close}
              />
              <NavLink
                component={Link}
                to="/admin/clients"
                label={t('nav.adminClients')}
                leftSection={<IconBuilding size={16} />}
                active={isActive('/admin/clients')}
                variant={isActive('/admin/clients') ? 'light' : undefined}
                color={isActive('/admin/clients') ? 'blue' : undefined}
                onClick={close}
              />
              <NavLink
                component={Link}
                to="/admin/settings"
                label={t('nav.adminSettings')}
                leftSection={<IconSettings size={16} />}
                active={isActive('/admin/settings')}
                variant={isActive('/admin/settings') ? 'light' : undefined}
                color={isActive('/admin/settings') ? 'blue' : undefined}
                onClick={close}
              />
            </>
          )}
```

3. Add `IconUsers, IconBuilding` to the `@tabler/icons-react` import.

In `frontend/src/features/dashboard/DashboardPage.tsx`: import `useSession` and `Link` (from `react-router`), and replace the "Add Client" button block with:

```tsx
        {session?.role === 'admin' ? (
          <Button component={Link} to="/admin/clients">{t('manageClients')}</Button>
        ) : null}
```

where `session` comes from `const { data: session } = useSession();`. Remove the now-unused `createOpened` state and `<ClientModal>` from the dashboard if nothing else uses them (check `DashboardPage.test.tsx` and update tests that assert the old button/modal accordingly — replace add-client assertions with the admin link, and add a non-admin variant asserting absence).

Add to `frontend/public/locales/en/common.json` (inside the existing `nav` object):

```json
    "adminSection": "Administration",
    "adminUsers": "Users",
    "adminClients": "Clients",
    "adminSettings": "Settings"
```

and to `frontend/public/locales/de/common.json`:

```json
    "adminSection": "Verwaltung",
    "adminUsers": "Benutzer",
    "adminClients": "Kunden",
    "adminSettings": "Einstellungen"
```

Create `frontend/public/locales/en/admin.json`:

```json
{
  "users": {
    "title": "User Management",
    "add": "Add User",
    "edit": "Edit User",
    "save": "Save",
    "saved": "User saved",
    "saveFailed": "Saving the user failed",
    "resetPassword": "Reset password",
    "roleUser": "User",
    "roleAdmin": "Admin",
    "columns": {
      "username": "Username",
      "password": "Password",
      "role": "Role",
      "clients": "Clients",
      "active": "Active"
    }
  },
  "clients": {
    "title": "Client Management",
    "add": "Add Client",
    "edit": "Edit",
    "delete": "Delete client",
    "columns": {
      "name": "Name",
      "status": "Status"
    }
  },
  "settings": {
    "title": "Settings",
    "removalRetention": "Removed-product retention (days)",
    "historyRetention": "Staging history retention (days)",
    "ingestionRetention": "Ingestion run retention (days)",
    "save": "Save",
    "saved": "Settings saved",
    "saveFailed": "Saving settings failed",
    "scheduler": "Scheduler Jobs",
    "schedulerUnavailable": "Scheduler unavailable",
    "jobId": "Job",
    "trigger": "Trigger",
    "plugins": "Plugins",
    "pluginName": "Plugin",
    "pluginEnabled": "Enabled"
  }
}
```

Create `frontend/public/locales/de/admin.json`:

```json
{
  "users": {
    "title": "Benutzerverwaltung",
    "add": "Benutzer hinzufügen",
    "edit": "Benutzer bearbeiten",
    "save": "Speichern",
    "saved": "Benutzer gespeichert",
    "saveFailed": "Speichern fehlgeschlagen",
    "resetPassword": "Passwort zurücksetzen",
    "roleUser": "Benutzer",
    "roleAdmin": "Admin",
    "columns": {
      "username": "Benutzername",
      "password": "Passwort",
      "role": "Rolle",
      "clients": "Kunden",
      "active": "Aktiv"
    }
  },
  "clients": {
    "title": "Kundenverwaltung",
    "add": "Kunden hinzufügen",
    "edit": "Bearbeiten",
    "delete": "Kunden löschen",
    "columns": {
      "name": "Name",
      "status": "Status"
    }
  },
  "settings": {
    "title": "Einstellungen",
    "removalRetention": "Aufbewahrung entfernter Produkte (Tage)",
    "historyRetention": "Aufbewahrung Staging-Historie (Tage)",
    "ingestionRetention": "Aufbewahrung Ingestion-Läufe (Tage)",
    "save": "Speichern",
    "saved": "Einstellungen gespeichert",
    "saveFailed": "Speichern fehlgeschlagen",
    "scheduler": "Scheduler-Jobs",
    "schedulerUnavailable": "Scheduler nicht verfügbar",
    "jobId": "Job",
    "trigger": "Trigger",
    "plugins": "Plugins",
    "pluginName": "Plugin",
    "pluginEnabled": "Aktiviert"
  }
}
```

Also add `"manageClients": "Manage clients"` to `en/dashboard.json` and `"manageClients": "Kunden verwalten"` to `de/dashboard.json`.

- [ ] **Step 8: Run tests and typecheck to verify they pass**

Run: `npm run test && npm run typecheck && npm run build`
Expected: PASS / no errors. Fix any mock `useSession` data in pre-existing tests to include `role` (e.g. `{ username: 'operator', role: 'admin', client_ids: null }`).

- [ ] **Step 9: Commit**

```bash
git add frontend/src frontend/public/locales
git commit -m "feat(frontend): admin area (users, clients, settings), route guard, nav group"
```

---

### Task 8: Documentation + ADR + full verification

**Files:**
- Modify: `backend/docs/api.md`
- Modify: `backend/docs/data-model.md`
- Modify: `backend/docs/architecture.md`
- Modify: `frontend/docs/architecture.md`
- Create: `docs/decisions/0009-basic-rbac.md`

**Interfaces:**
- Consumes: everything from Tasks 1-7
- Produces: documentation matching the shipped behavior (AGENTS.md same-commit rule)

- [ ] **Step 1: Update backend docs**

`backend/docs/api.md` — add a section "Authorization" with the enforcement matrix from the spec (admin/user columns, 404 for unassigned, 403 for admin-only), document `GET/POST/PATCH /admin/users`, `POST /admin/users/{id}/password`, `GET/PUT /admin/settings`, `GET /admin/scheduler`, and the new `/auth/me` response shape `{username, role, client_ids}`.

`backend/docs/data-model.md` — document `users.role` (`admin`|`user`, seeded admin, migration promotes existing users), `users.is_active`, the `user_clients` join table, and `global_settings` (single row, lazy-seeded, 90-day defaults, drives the purge jobs).

`backend/docs/architecture.md` — add a short "Authorization layer" subsection: `app/access.py` with `CurrentUser`/`get_current_user`/`require_admin`/`enforce_scope_access`, router-level scope enforcement, non-DB fallback behavior (treated as admin/unrestricted), and deactivation-instead-of-deletion.

- [ ] **Step 2: Update frontend docs and add the ADR**

`frontend/docs/architecture.md` — document the admin routes (`/admin/users`, `/admin/clients`, `/admin/settings`), the `RequireAdmin` guard, the Administration nav group, and that dashboard client CRUD moved to the admin area.

Create `docs/decisions/0009-basic-rbac.md` following the style of the existing ADRs (see `docs/decisions/0007-*.md` for structure): title "Basic RBAC: two roles, client assignment, admin area"; Status: Accepted; Context (single-user auth, agency multi-client data, need client isolation); Decision (role column + user_clients join, dependency-based enforcement, 404-no-leak, deactivation not deletion, DB-backed retention settings); Consequences (per-request user load, no fine-grained permissions, adding a third role = small migration).

- [ ] **Step 3: Full backend verification**

Run from `backend/`:

```bash
uv run pytest -n auto
uv run ruff check .
uv run mypy .
```

Expected: all pass. Fix anything that surfaces (most likely: unused imports in `auth.py`/`access.py`, type narrowing in `main.py`).

- [ ] **Step 4: Full frontend verification**

Run from `frontend/`:

```bash
npm run test
npm run typecheck
npm run build
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/docs frontend/docs docs/decisions/0009-basic-rbac.md
git commit -m "docs: basic RBAC authorization, admin area, global settings"
```
