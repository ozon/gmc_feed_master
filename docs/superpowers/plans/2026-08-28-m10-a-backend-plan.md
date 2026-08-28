# M10-a — Backend Endpoints for the Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all backend endpoints the M10 frontend needs: dashboard summary (D1), staging products list/detail (D2), dry-run (D4), cascade deletes (D5), the pipeline read/write API (spec §8), client update, plugin usage counts, and ship the `example_upper` demo plugin.

**Architecture:** New FastAPI routers (`dashboard`, `products`, `pipeline`, `dry_run`) registered in `create_app`, following the existing route conventions in `backend/app/routes/` (session auth via `require_user`, 503 when DB unavailable, 422 `{"errors": […]}` validation bodies). Cascade deletes live in a dedicated service module with explicit FK-safe ordering. Dry-run composes the existing pipeline steps in-memory (no staging writes, no publish).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 async (asyncpg), Pydantic v2, pytest + pytest-asyncio against real PostgreSQL (pytest-postgresql), alembic (no new migrations in this plan).

**Design doc:** `docs/superpowers/specs/2026-08-28-m10-frontend-design.md` (§0.5–0.8 review changes included).

## Global Constraints

- Tests run against real PostgreSQL via pytest-postgresql; every test runs in a per-test cloned database; never hardcode database names (AGENTS.md).
- Run single tests as `uv run pytest tests/test_x.py::test_name -v` from `backend/`; full suite `uv run pytest -n auto`.
- No comments in code unless a comment already exists in the surrounding style; mimic existing module conventions (`from __future__ import annotations`, relative imports).
- All endpoints require the session (`Depends(require_user)`) and return 503 `database unavailable` when `get_db_session` yields `None` (existing `_require_db` pattern).
- Validation failures use `JSONResponse(status_code=422, content={"errors": […]})` (existing pattern in `routes/plugins.py` and `routes/field_mapping.py`).
- `POST /auth/password` already exists with M1 revocation semantics — do NOT rebuild it (design §0.5).
- Mapping targets are `attr` / `attr.subfield` only — positional paths are rejected by the existing field-mapping validation; this plan does not change that (design §0.6).
- Commit messages follow repo style: `feat(api): …`, `test: …`, `docs: …`.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/schemas/clients.py` (modify) | Add `ClientUpdate`; extend `FeedSourceUpdate`/`FeedSourceOut` |
| `backend/app/routes/clients.py` (modify) | `PUT /clients/{id}`; rework `DELETE /feed-sources/{id}`; add `DELETE /clients/{id}` |
| `backend/app/routes/dashboard.py` (create) | `GET /dashboard/summary` |
| `backend/app/routes/products.py` (create) | `GET /feed-sources/{id}/products` + detail |
| `backend/app/schemas/pipeline.py` (create) | Pipeline PUT/GET models |
| `backend/app/routes/pipeline.py` (create) | `GET/PUT /feed-sources/{id}/pipeline` |
| `backend/app/routes/plugins.py` (modify) | `used_by_feed_sources` count on `GET /plugins` |
| `backend/app/persistence/cascade.py` (create) | FK-safe cascade delete services |
| `backend/app/pipeline/steps.py` (modify) | `RunState.dropped` field; `PluginStep` records drops |
| `backend/app/pipeline/dry_run.py` (create) | In-memory dry-run composition |
| `backend/app/routes/dry_run.py` (create) | `POST /feed-sources/{id}/dry-run` |
| `backend/app/main.py` (modify) | Register new routers; expose `app.state.fetcher` / `app.state.image_probe` |
| `plugins/example_upper/` (create) | Demo plugin (copy of contract fixture + `frontend` manifest key) |
| `backend/tests/test_dashboard_api.py`, `test_products_api.py`, `test_pipeline_api.py`, `test_cascade_api.py`, `test_dry_run_api.py`, `test_example_plugin_contract.py` (create) | Endpoint tests |
| `backend/tests/test_clients_api.py`, `test_plugins_api.py` (modify) | Client update / usage count tests |

---

### Task 1: `PUT /clients/{id}` (client update)

**Files:**
- Modify: `backend/app/schemas/clients.py`
- Modify: `backend/app/routes/clients.py`
- Test: `backend/tests/test_clients_api.py`

**Interfaces:**
- Consumes: existing `Client` model, `ClientOut` schema, `logged_in_client` test helper.
- Produces: `ClientUpdate` schema; `PUT /clients/{client_id}` returning `ClientOut` (used by the dashboard edit modal in M10-c).

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_clients_api.py`:

```python
async def test_update_client_fields(app_factory):
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    resp = await client.put(
        f"/clients/{created['id']}",
        json={"name": "Acme GmbH", "status": "paused", "contact_details": {"email": "a@b.c"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Acme GmbH"
    assert body["status"] == "paused"
    assert body["contact_details"] == {"email": "a@b.c"}


async def test_update_client_partial_keeps_other_fields(app_factory):
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    resp = await client.put(f"/clients/{created['id']}", json={"status": "paused"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Acme"
    assert resp.json()["status"] == "paused"


async def test_update_client_not_found(app_factory):
    client = await logged_in_client(app_factory)
    assert (await client.put("/clients/99999", json={"name": "X"})).status_code == 404


async def test_update_client_duplicate_name_returns_409(app_factory):
    client = await logged_in_client(app_factory)
    await client.post("/clients", json={"name": "Acme"})
    other = (await client.post("/clients", json={"name": "Zeta"})).json()
    assert (await client.put(f"/clients/{other['id']}", json={"name": "Acme"})).status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_clients_api.py -k update_client -v` (from `backend/`)
Expected: FAIL with 404/405 (route missing).

- [ ] **Step 3: Add the schema** — in `backend/app/schemas/clients.py`, after `ClientCreate`:

```python
class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, max_length=50)
    contact_details: dict[str, Any] | None = None
```

- [ ] **Step 4: Add the route** — in `backend/app/routes/clients.py`, import `ClientUpdate` and add after the `list_clients` route:

```python
@router.put("/clients/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: int,
    payload: ClientUpdate,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> Client:
    session = _require_db(db_session)
    updates = payload.model_dump(exclude_unset=True)
    async with session.begin():
        client = await session.get(Client, client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="client not found")
        for key, value in updates.items():
            setattr(client, key, value)
    await session.refresh(client)
    return client
```

Note: the duplicate-name 409 falls out of the unique constraint — wrap the `session.begin()` block in `try/except IntegrityError` raising `HTTPException(status_code=409, detail="client name already exists")`, mirroring `create_client`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_clients_api.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/clients.py backend/app/routes/clients.py backend/tests/test_clients_api.py
git commit -m "feat(api): PUT /clients/{id} for client updates"
```

---

### Task 2: FeedSource schema extensions (Setup form support)

**Files:**
- Modify: `backend/app/schemas/clients.py`
- Test: `backend/tests/test_clients_api.py`

**Interfaces:**
- Consumes: `FeedSource.volume_drop_threshold_pct`, `FeedSource.configuration` columns (both exist).
- Produces: `FeedSourceUpdate` accepting both fields; `FeedSourceOut` returning both (Setup form in M10-c reads/writes them; Basic Auth credentials live in `configuration.basic_auth` per the M3 decision).

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_clients_api.py`:

```python
async def test_feed_source_update_volume_threshold_and_configuration(app_factory):
    client = await logged_in_client(app_factory)
    created_client = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created_client['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    resp = await client.put(
        f"/feed-sources/{feed['id']}",
        json={
            "volume_drop_threshold_pct": 35,
            "configuration": {"basic_auth": {"username": "u", "password": "p"}},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["volume_drop_threshold_pct"] == 35
    assert body["configuration"] == {"basic_auth": {"username": "u", "password": "p"}}


async def test_feed_source_update_volume_threshold_out_of_range(app_factory):
    client = await logged_in_client(app_factory)
    created_client = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created_client['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    resp = await client.put(f"/feed-sources/{feed['id']}", json={"volume_drop_threshold_pct": 101})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_clients_api.py -k "volume_threshold" -v`
Expected: FAIL (fields ignored → missing keys / no 422).

- [ ] **Step 3: Extend the schemas** — in `backend/app/schemas/clients.py`:

`FeedSourceUpdate` gains:

```python
    volume_drop_threshold_pct: int | None = Field(default=None, ge=0, le=100)
    configuration: dict[str, Any] | None = None
```

`FeedSourceOut` gains:

```python
    volume_drop_threshold_pct: int
    configuration: dict[str, Any]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_clients_api.py -v`
Expected: all PASS (`update_feed_source` already applies arbitrary `FeedSourceUpdate` fields via `setattr`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/clients.py backend/tests/test_clients_api.py
git commit -m "feat(api): expose volume_drop_threshold_pct and configuration on feed source endpoints"
```

---

### Task 3: `GET /dashboard/summary` (D1)

**Files:**
- Create: `backend/app/routes/dashboard.py`
- Modify: `backend/app/main.py` (router registration)
- Test: `backend/tests/test_dashboard_api.py`

**Interfaces:**
- Consumes: `Client`, `FeedSource`, `StagingProduct`, `ExportRun`, `IngestionRun` models.
- Produces: `GET /dashboard/summary` → `{counts: {clients, feed_sources, active_products, failed_last_exports}, clients: [{id, name, status, feed_sources: [{id, client_id, name, source_format, item_count, last_export_at, last_export_status, last_run_at, last_run_status}]}]}` (design §1.1).

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_dashboard_api.py`:

```python
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import seed_initial_user


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(StagingProduct))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _make_feed(factory, client, name):
    created = (await client.post("/clients", json={"name": name})).json()
    feed = (
        await client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": f"{name}-feed", "source_format": "wide_tsv"},
        )
    ).json()
    return created["id"], feed["id"]


async def _add_staging(factory, feed_id, product_id, status="active", excluded=False):
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed_id, status="success",
                               started_at=datetime.now(timezone.utc))
            session.add(run)
            await session.flush()
            session.add(
                StagingProduct(
                    feed_source_id=feed_id,
                    ingestion_run_id=run.id,
                    product_id=product_id,
                    content_hash="h",
                    config_hash="c",
                    status=status,
                    excluded=excluded,
                    raw_data={"id": product_id, "title": f"Title {product_id}"},
                )
            )


async def _add_export_run(factory, feed_id, status, product_count=1):
    async with factory() as session:
        async with session.begin():
            session.add(
                ExportRun(
                    feed_source_id=feed_id,
                    status=status,
                    product_count=product_count,
                    started_at=datetime.now(timezone.utc),
                )
            )


async def test_summary_requires_auth(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.get("/dashboard/summary")).status_code == 401


async def test_summary_empty(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.get("/dashboard/summary")
    assert resp.status_code == 200
    assert resp.json() == {"counts": {"clients": 0, "feed_sources": 0,
                                      "active_products": 0, "failed_last_exports": 0},
                           "clients": []}


async def test_summary_counts_and_per_feed_fields(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_a = await _make_feed(factory, client, "Acme")
    client_id_b, feed_b = await _make_feed(factory, client, "Zeta")

    await _add_staging(factory, feed_a, "p1")
    await _add_staging(factory, feed_a, "p2")
    await _add_staging(factory, feed_a, "p3", status="removed")
    await _add_staging(factory, feed_a, "p4", excluded=True)
    await _add_staging(factory, feed_b, "q1")

    await _add_export_run(factory, feed_a, "completed")
    await _add_export_run(factory, feed_b, "failed")

    resp = await client.get("/dashboard/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"] == {"clients": 2, "feed_sources": 2,
                              "active_products": 3, "failed_last_exports": 1}
    by_name = {c["name"]: c for c in body["clients"]}
    feed_a_out = by_name["Acme"]["feed_sources"][0]
    assert feed_a_out["item_count"] == 2
    assert feed_a_out["last_export_status"] == "completed"
    assert feed_a_out["last_export_at"] is not None
    assert feed_a_out["source_format"] == "wide_tsv"
    assert feed_a_out["client_id"] == by_name["Acme"]["id"]
    feed_b_out = by_name["Zeta"]["feed_sources"][0]
    assert feed_b_out["item_count"] == 1
    assert feed_b_out["last_export_status"] == "failed"
    assert feed_b_out["last_run_status"] is None


async def test_summary_last_export_uses_latest_run(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_a = await _make_feed(factory, client, "Acme")
    await _add_export_run(factory, feed_a, "failed")
    await _add_export_run(factory, feed_a, "completed")
    body = (await client.get("/dashboard/summary")).json()
    assert body["counts"]["failed_last_exports"] == 0
    assert body["clients"][0]["feed_sources"][0]["last_export_status"] == "completed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dashboard_api.py -v`
Expected: FAIL with 404 (route missing).

- [ ] **Step 3: Implement the route** — create `backend/app/routes/dashboard.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.client import Client
from ..models.export import ExportRun
from ..models.feed_source import FeedSource
from ..models.ingestion import IngestionRun
from ..models.staging import StagingProduct

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


async def _latest_runs(session, model):
    result = await session.execute(
        select(model)
        .distinct(model.feed_source_id)
        .order_by(model.feed_source_id, model.id.desc())
    )
    return {row.feed_source_id: row for row in result.scalars()}


@router.get("/dashboard/summary")
async def dashboard_summary(
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        clients = list((await session.execute(select(Client).order_by(Client.name))).scalars())
        feeds = list((await session.execute(select(FeedSource).order_by(FeedSource.name))).scalars())
        item_counts = dict(
            (await session.execute(
                select(StagingProduct.feed_source_id, func.count())
                .where(StagingProduct.status == "active", StagingProduct.excluded.is_(False))
                .group_by(StagingProduct.feed_source_id)
            )).all()
        )
        total_active = (await session.execute(
            select(func.count()).select_from(StagingProduct)
            .where(StagingProduct.status == "active", StagingProduct.excluded.is_(False))
        )).scalar_one()
        latest_exports = await _latest_runs(session, ExportRun)
        latest_runs = await _latest_runs(session, IngestionRun)

    feeds_by_client: dict[int, list[dict]] = {}
    failed_last_exports = 0
    for feed in feeds:
        last_export = latest_exports.get(feed.id)
        last_run = latest_runs.get(feed.id)
        if last_export is not None and last_export.status == "failed":
            failed_last_exports += 1
        feeds_by_client.setdefault(feed.client_id, []).append({
            "id": feed.id,
            "client_id": feed.client_id,
            "name": feed.name,
            "source_format": feed.source_format,
            "item_count": item_counts.get(feed.id, 0),
            "last_export_at": last_export.started_at.isoformat() if last_export else None,
            "last_export_status": last_export.status if last_export else None,
            "last_run_at": last_run.started_at.isoformat() if last_run else None,
            "last_run_status": last_run.status if last_run else None,
        })

    return {
        "counts": {
            "clients": len(clients),
            "feed_sources": len(feeds),
            "active_products": total_active,
            "failed_last_exports": failed_last_exports,
        },
        "clients": [
            {"id": c.id, "name": c.name, "status": c.status,
             "feed_sources": feeds_by_client.get(c.id, [])}
            for c in clients
        ],
    }
```

- [ ] **Step 4: Register the router** — in `backend/app/main.py`, import `from .routes.dashboard import router as dashboard_router` alongside the other route imports and add `app.include_router(dashboard_router)` next to the existing `include_router` calls.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_dashboard_api.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/dashboard.py backend/app/main.py backend/tests/test_dashboard_api.py
git commit -m "feat(api): GET /dashboard/summary (D1)"
```

---

### Task 4: Products list + detail (D2)

**Files:**
- Create: `backend/app/routes/products.py`
- Modify: `backend/app/main.py` (router registration)
- Test: `backend/tests/test_products_api.py`

**Interfaces:**
- Consumes: `StagingProduct` model (`raw_data` holds the post-mapping canonical product).
- Produces: `GET /feed-sources/{id}/products` (paginated, server search/filter/sort; design §1.2) and `GET /feed-sources/{id}/products/{product_id}` (full row for the drawer). `stage=processed` → 501 (D3 placeholder).

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_products_api.py` with the same `app_factory`/`logged_in_client` fixtures as Task 3 (copy them verbatim). Add helpers and tests:

```python
async def _setup_feed(factory, client, products):
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed["id"], status="success",
                               started_at=datetime.now(timezone.utc))
            session.add(run)
            await session.flush()
            for pid, raw, status in products:
                session.add(
                    StagingProduct(
                        feed_source_id=feed["id"], ingestion_run_id=run.id,
                        product_id=pid, content_hash="h", config_hash="c",
                        status=status, raw_data=raw,
                    )
                )
    return feed["id"]


_BASE = {"title": "T", "description": "D", "link": "L", "image_link": "I",
         "availability": "in_stock", "price": "1.00 EUR", "condition": "new"}


async def test_products_requires_auth_and_404(app_factory):
    app, _ = app_factory
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anon.get("/feed-sources/1/products")).status_code == 401
    client = await logged_in_client(app_factory)
    assert (await client.get("/feed-sources/99999/products")).status_code == 404


async def test_products_stage_processed_returns_501(app_factory):
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(app_factory[1], client, [])
    assert (await client.get(f"/feed-sources/{feed_id}/products", params={"stage": "processed"})).status_code == 501


async def test_products_pagination_search_filter_sort(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    products = [
        ("a", {"id": "a", **_BASE, "title": "Alpha Shoe"}, "active"),
        ("b", {"id": "b", **_BASE, "title": "Beta Shirt"}, "active"),
        ("c", {"id": "c", **_BASE, "title": "Gamma Shoe"}, "removed"),
    ]
    feed_id = await _setup_feed(factory, client, products)

    resp = await client.get(f"/feed-sources/{feed_id}/products")
    body = resp.json()
    assert body["total"] == 3
    assert body["page"] == 1 and body["page_size"] == 50
    assert [i["product_id"] for i in body["items"]] == ["a", "b", "c"]
    item = body["items"][0]
    for key in ("id", "title", "description", "link", "image_link",
                "availability", "price", "condition", "status", "last_seen_at"):
        assert key in item

    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"page_size": 2, "page": 2})
    body = resp.json()
    assert [i["product_id"] for i in body["items"]] == ["c"]

    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"q": "shoe"})
    assert [i["product_id"] for i in resp.json()["items"]] == ["a", "c"]

    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"q": "a", "status": "active"})
    assert [i["product_id"] for i in resp.json()["items"]] == ["a", "b"]

    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"status": "removed"})
    assert [i["product_id"] for i in resp.json()["items"]] == ["c"]

    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"sort": "-title"})
    assert [i["title"] for i in resp.json()["items"]] == ["Gamma Shoe", "Beta Shirt", "Alpha Shoe"]
    resp = await client.get(f"/feed-sources/{feed_id}/products", params={"sort": "-product_id"})
    assert [i["product_id"] for i in resp.json()["items"]] == ["c", "b", "a"]

    assert (await client.get(f"/feed-sources/{feed_id}/products", params={"sort": "bogus"})).status_code == 422
    assert (await client.get(f"/feed-sources/{feed_id}/products", params={"status": "bogus"})).status_code == 422


async def test_product_detail_returns_full_raw_data(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(factory, client,
                                [("a", {"id": "a", **_BASE, "shipping": [{"country": "DE", "price": "1 EUR"}]}, "active")])
    resp = await client.get(f"/feed-sources/{feed_id}/products/a")
    assert resp.status_code == 200
    body = resp.json()
    assert body["product_id"] == "a"
    assert body["status"] == "active"
    assert body["raw_data"]["shipping"] == [{"country": "DE", "price": "1 EUR"}]
    assert (await client.get(f"/feed-sources/{feed_id}/products/missing")).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_products_api.py -v`
Expected: FAIL with 404 (routes missing).

- [ ] **Step 3: Implement the routes** — create `backend/app/routes/products.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.feed_source import FeedSource
from ..models.staging import StagingProduct

router = APIRouter()

_BASELINE_FIELDS = ("title", "description", "link", "image_link",
                    "availability", "price", "condition")
_SORTS = {
    "product_id": StagingProduct.product_id,
    "title": StagingProduct.raw_data["title"].astext,
    "status": StagingProduct.status,
    "last_seen_at": StagingProduct.last_seen_at,
}


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _list_item(row: StagingProduct) -> dict:
    raw = row.raw_data or {}
    item = {
        "product_id": row.product_id,
        "id": raw.get("id", row.product_id),
        "status": row.status,
        "last_seen_at": row.last_seen_at.isoformat(),
    }
    for field in _BASELINE_FIELDS:
        item[field] = raw.get(field)
    return item


async def _require_feed_source(session: AsyncSession, feed_source_id: int) -> None:
    if await session.get(FeedSource, feed_source_id) is None:
        raise HTTPException(status_code=404, detail="feed source not found")


@router.get("/feed-sources/{feed_source_id}/products")
async def list_products(
    feed_source_id: int,
    stage: str = Query(default="raw"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    q: str | None = Query(default=None),
    status: str = Query(default="all"),
    sort: str = Query(default="product_id"),
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    if stage == "processed":
        raise HTTPException(status_code=501, detail="processed stage is not available yet")
    if stage != "raw":
        raise HTTPException(status_code=422, detail=f"unknown stage {stage!r}")
    if status not in ("active", "removed", "all"):
        raise HTTPException(status_code=422, detail=f"unknown status {status!r}")
    descending = sort.startswith("-")
    sort_field = sort[1:] if descending else sort
    if sort_field not in _SORTS:
        raise HTTPException(status_code=422, detail=f"unknown sort field {sort_field!r}")

    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
        filters = [StagingProduct.feed_source_id == feed_source_id]
        if status != "all":
            filters.append(StagingProduct.status == status)
        if q:
            pattern = f"%{q}%"
            filters.append(or_(
                StagingProduct.product_id.ilike(pattern),
                StagingProduct.raw_data["title"].astext.ilike(pattern),
            ))
        total = (await session.execute(
            select(func.count()).select_from(StagingProduct).where(*filters)
        )).scalar_one()
        order = _SORTS[sort_field].desc() if descending else _SORTS[sort_field].asc()
        rows = list((await session.execute(
            select(StagingProduct).where(*filters).order_by(order)
            .offset((page - 1) * page_size).limit(page_size)
        )).scalars())
    return {
        "items": [_list_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/feed-sources/{feed_source_id}/products/{product_id}")
async def product_detail(
    feed_source_id: int,
    product_id: str,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
        row = (await session.execute(
            select(StagingProduct).where(
                StagingProduct.feed_source_id == feed_source_id,
                StagingProduct.product_id == product_id,
            )
        )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="product not found")
    return {
        "product_id": row.product_id,
        "status": row.status,
        "content_hash": row.content_hash,
        "config_hash": row.config_hash,
        "last_seen_at": row.last_seen_at.isoformat(),
        "removed_at": row.removed_at.isoformat() if row.removed_at else None,
        "raw_data": row.raw_data,
    }
```

- [ ] **Step 4: Register the router** in `backend/app/main.py` (`products_router`), run tests:

Run: `uv run pytest tests/test_products_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/products.py backend/app/main.py backend/tests/test_products_api.py
git commit -m "feat(api): staging products list and detail endpoints (D2)"
```

---

### Task 5: Pipeline read/write API (spec §8)

**Files:**
- Create: `backend/app/schemas/pipeline.py`
- Create: `backend/app/routes/pipeline.py`
- Modify: `backend/app/main.py` (router registration)
- Test: `backend/tests/test_pipeline_api.py`

**Interfaces:**
- Consumes: `ModulePipeline`, `ModuleInstance`, `Plugin` models; `app.state.plugin_registry` (manifest-id → loaded plugin instance) for `validate_config`; `resolve_config_bundle` reads `ModuleInstance` rows (unchanged).
- Produces: `GET /feed-sources/{id}/pipeline` → `{"instances": [{"position", "plugin_id", "name", "configuration"}]}`; `PUT` full-replace with validation (design §1.5).

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_pipeline_api.py` (same fixtures as Task 3) plus:

```python
from app.models.pipeline import ModuleInstance, ModulePipeline
from app.models.plugin import Plugin


async def _register_plugin(factory, name="example_upper", enabled=True,
                           extension_point="pipeline_module"):
    manifest = {"id": name, "name": name, "version": "1.0.0",
                "extension_point": extension_point,
                "config_schema": {"type": "object",
                                  "properties": {"suffix": {"type": "string"}},
                                  "required": ["suffix"]},
                "data_schema": {"type": "object"}}
    async with factory() as session:
        async with session.begin():
            session.add(Plugin(name=name, version="1.0.0", enabled=enabled,
                               manifest=manifest))
            await session.flush()


async def test_get_pipeline_empty(app_factory):
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    resp = await client.get(f"/feed-sources/{feed['id']}/pipeline")
    assert resp.status_code == 200
    assert resp.json() == {"instances": []}


async def test_put_pipeline_roundtrip(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()

    class _Plugin:
        def validate_config(self, config):
            if "suffix" not in config:
                raise ValueError("suffix is required")
    app.state.plugin_registry["example_upper"] = _Plugin()

    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "name": "Upper",
                       "configuration": {"suffix": "!"}}]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["instances"] == [{"position": 0, "plugin_id": "example_upper",
                                  "name": "Upper", "configuration": {"suffix": "!"}}]
    assert (await client.get(f"/feed-sources/{feed['id']}/pipeline")).json() == body

    async with factory() as session:
        from sqlalchemy import select
        fs = await session.get(FeedSource, feed["id"])
        assert fs.active_pipeline_id is not None


async def test_put_pipeline_replaces_instances(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "configuration": {"suffix": "!"}}]})
    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={"instances": []})
    assert resp.status_code == 200
    assert resp.json() == {"instances": []}
    async with factory() as session:
        from sqlalchemy import select
        count = (await session.execute(select(func.count()).select_from(ModuleInstance))).scalar_one()
        assert count == 0


async def test_put_pipeline_validation_failures(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    await _register_plugin(factory, name="disabled_one", enabled=False)
    await _register_plugin(factory, name="not_a_module", extension_point="quality_rule")
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()

    class _Plugin:
        def validate_config(self, config):
            if "suffix" not in config:
                raise ValueError("suffix is required")
    app.state.plugin_registry["example_upper"] = _Plugin()

    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "missing", "configuration": {}}]})
    assert resp.status_code == 422 and resp.json()["errors"]

    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "disabled_one", "configuration": {}}]})
    assert resp.status_code == 422

    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "not_a_module", "configuration": {}}]})
    assert resp.status_code == 422

    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "configuration": {}}]})
    assert resp.status_code == 422
    assert any("suffix" in e for e in resp.json()["errors"])
```

(Add `from sqlalchemy import func` and `FeedSource` imports at the top of the test file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline_api.py -v`
Expected: FAIL with 404.

- [ ] **Step 3: Create the schemas** — `backend/app/schemas/pipeline.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PipelineInstanceIn(BaseModel):
    plugin_id: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    configuration: dict[str, Any] = Field(default_factory=dict)


class PipelinePut(BaseModel):
    instances: list[PipelineInstanceIn] = Field(default_factory=list)


class PipelineInstanceOut(BaseModel):
    position: int
    plugin_id: str
    name: str
    configuration: dict[str, Any]


class PipelineOut(BaseModel):
    instances: list[PipelineInstanceOut]
```

- [ ] **Step 4: Implement the routes** — create `backend/app/routes/pipeline.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.feed_source import FeedSource
from ..models.pipeline import ModuleInstance, ModulePipeline
from ..models.plugin import Plugin
from ..schemas.pipeline import PipelineOut, PipelinePut

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _validation_error(errors: list[str]) -> JSONResponse:
    return JSONResponse(status_code=422, content={"errors": errors})


@router.get("/feed-sources/{feed_source_id}/pipeline", response_model=PipelineOut)
async def get_pipeline(
    feed_source_id: int,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        if feed_source.active_pipeline_id is None:
            return {"instances": []}
        rows = list((await session.execute(
            select(ModuleInstance, Plugin)
            .join(Plugin, ModuleInstance.plugin_id == Plugin.id)
            .where(ModuleInstance.pipeline_id == feed_source.active_pipeline_id)
            .order_by(ModuleInstance.position)
        )).all())
    return {"instances": [
        {"position": instance.position,
         "plugin_id": (plugin.manifest or {}).get("id") or plugin.name,
         "name": instance.name,
         "configuration": instance.configuration}
        for instance, plugin in rows
    ]}


@router.put("/feed-sources/{feed_source_id}/pipeline", response_model=PipelineOut)
async def put_pipeline(
    feed_source_id: int,
    payload: PipelinePut,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    plugin_registry = getattr(request.app.state, "plugin_registry", {})

    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")

        plugins: dict[str, Plugin] = {}
        errors: list[str] = []
        for index, item in enumerate(payload.instances):
            plugin = (await session.execute(
                select(Plugin).where(Plugin.name == item.plugin_id)
            )).scalar_one_or_none()
            if plugin is None:
                errors.append(f"instance {index}: unknown plugin {item.plugin_id!r}")
                continue
            if not plugin.enabled:
                errors.append(f"instance {index}: plugin {item.plugin_id!r} is disabled")
                continue
            if (plugin.manifest or {}).get("extension_point") != "pipeline_module":
                errors.append(f"instance {index}: plugin {item.plugin_id!r} is not a pipeline_module")
                continue
            plugins[item.plugin_id] = plugin
            plugin_obj = plugin_registry.get(item.plugin_id)
            if plugin_obj is not None and hasattr(plugin_obj, "validate_config"):
                try:
                    plugin_obj.validate_config(item.configuration)
                except Exception as exc:
                    errors.append(f"instance {index}: invalid configuration: {exc}")
        if errors:
            return _validation_error(errors)

        pipeline = None
        if feed_source.active_pipeline_id is not None:
            pipeline = await session.get(ModulePipeline, feed_source.active_pipeline_id)
        if pipeline is None:
            pipeline = ModulePipeline(feed_source_id=feed_source_id,
                                      name=feed_source.name, version="1", definition={})
            session.add(pipeline)
            await session.flush()
            feed_source.active_pipeline_id = pipeline.id

        await session.execute(
            delete(ModuleInstance).where(ModuleInstance.pipeline_id == pipeline.id)
        )
        instances_out = []
        definition = []
        for position, item in enumerate(payload.instances):
            plugin = plugins[item.plugin_id]
            name = item.name or (plugin.manifest or {}).get("name") or plugin.name
            session.add(ModuleInstance(
                pipeline_id=pipeline.id, plugin_id=plugin.id, position=position,
                name=name, configuration=item.configuration,
            ))
            instances_out.append({"position": position, "plugin_id": item.plugin_id,
                                  "name": name, "configuration": item.configuration})
            definition.append({"plugin_id": item.plugin_id, "name": name,
                               "configuration": item.configuration})
        pipeline.definition = {"instances": definition}

    return {"instances": instances_out}
```

- [ ] **Step 5: Register the router** in `backend/app/main.py` (`pipeline_router`), run tests:

Run: `uv run pytest tests/test_pipeline_api.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/pipeline.py backend/app/routes/pipeline.py backend/app/main.py backend/tests/test_pipeline_api.py
git commit -m "feat(api): pipeline read/write endpoints (spec §8)"
```

---

### Task 6: `GET /plugins` usage count

**Files:**
- Modify: `backend/app/routes/plugins.py:96-113`
- Test: `backend/tests/test_plugins_api.py`

**Interfaces:**
- Consumes: `ModuleInstance`, `ModulePipeline` models.
- Produces: each `GET /plugins` item gains `used_by_feed_sources: int` — count of distinct feed sources whose pipeline references the plugin (design §1.7; powers the disable warning in the Pipeline Editor).

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_plugins_api.py` (this file already has an `app_factory` fixture, a `logged_in_client`-style helper or login flow, and a `make_manifest(**overrides)` helper):

```python
async def test_plugins_list_includes_usage_count(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)

    async with factory() as session:
        async with session.begin():
            used = Plugin(name="used_plugin", version="1.0.0", enabled=True,
                          manifest=make_manifest(id="used_plugin"))
            unused = Plugin(name="unused_plugin", version="1.0.0", enabled=True,
                            manifest=make_manifest(id="unused_plugin"))
            session.add_all([used, unused])
            await session.flush()
            acme = Client(name="Acme")
            session.add(acme)
            await session.flush()
            feed = FeedSource(client_id=acme.id, name="DE", source_format="wide_tsv")
            session.add(feed)
            await session.flush()
            pipeline = ModulePipeline(feed_source_id=feed.id, name="p", version="1", definition={})
            session.add(pipeline)
            await session.flush()
            # same plugin twice in the same feed's pipeline → still counts once
            session.add_all([
                ModuleInstance(pipeline_id=pipeline.id, plugin_id=used.id,
                               position=0, name="a", configuration={}),
                ModuleInstance(pipeline_id=pipeline.id, plugin_id=used.id,
                               position=1, name="b", configuration={}),
            ])

    resp = await client.get("/plugins")
    assert resp.status_code == 200
    by_id = {p["id"]: p for p in resp.json()}
    assert by_id["used_plugin"]["used_by_feed_sources"] == 1
    assert by_id["unused_plugin"]["used_by_feed_sources"] == 0
```

Add the import `from app.models.pipeline import ModuleInstance, ModulePipeline` at the top of the file. (`Plugin` has no `source_path` column in the implemented schema — do not pass one.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugins_api.py -k usage_count -v`
Expected: FAIL with `KeyError: 'used_by_feed_sources'`.

- [ ] **Step 3: Implement** — in `list_plugins` in `backend/app/routes/plugins.py`, before the return:

```python
    from ..models.pipeline import ModuleInstance, ModulePipeline

    usage = dict((await session.execute(
        select(ModuleInstance.plugin_id, func.count(func.distinct(ModulePipeline.feed_source_id)))
        .join(ModulePipeline, ModuleInstance.pipeline_id == ModulePipeline.id)
        .group_by(ModuleInstance.plugin_id)
    )).all())
```

(add `func` to the sqlalchemy import) and add `"used_by_feed_sources": usage.get(plugin.id, 0)` to each item.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugins_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/plugins.py backend/tests/test_plugins_api.py
git commit -m "feat(api): report plugin usage by feed sources on GET /plugins"
```

---

### Task 7: Cascade deletes (D5)

**Files:**
- Create: `backend/app/persistence/cascade.py`
- Modify: `backend/app/routes/clients.py` (rework `delete_feed_source`, add `delete_client`)
- Test: `backend/tests/test_cascade_api.py`

**Interfaces:**
- Consumes: all child models; `LockRegistry.is_locked(feed_source_id)` via `request.app.state.lock_registry`; `SchedulerService.unregister(feed_source_id)`; `ExportFileStore` for file cleanup.
- Produces: `delete_feed_source_cascade(session, feed_source_id)` and `delete_client_cascade(session, client_id)` (both `async`, expect an open transaction on `session`); `DELETE /clients/{id}` (204); reworked `DELETE /feed-sources/{id}` (204, no more 409-on-runs).

**FK-safe delete order** (verified against the models): quality findings → export versions → export runs → staging products (history cascades) → module instances → unset `active_pipeline_id` → module pipelines → ingestion runs → feed-scoped plugin config/data → feed source row. Client cascade additionally: client-scoped plugin config/data → client row.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_cascade_api.py`. Use the Task 3 fixtures, but add `export_dir=str(tmp_path / "exports")` and `public_base_url="http://test.public"` to `Settings` (as in `test_m9_acceptance.py`) and make the fixture `yield app, factory, settings`. Tests:

```python
async def _full_tree(factory, client):
    """Create client + feed source with rows in EVERY child table; return ids."""
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    async with factory() as session:
        async with session.begin():
            run = IngestionRun(feed_source_id=feed["id"], status="success",
                               started_at=datetime.now(timezone.utc))
            session.add(run); await session.flush()
            product = StagingProduct(feed_source_id=feed["id"], ingestion_run_id=run.id,
                                     product_id="p1", content_hash="h", config_hash="c",
                                     status="active", raw_data={"id": "p1"})
            session.add(product); await session.flush()
            session.add(StagingHistory(staging_product_id=product.id, snapshot={"id": "p1"}))
            session.add(QualityFinding(feed_source_id=feed["id"], ingestion_run_id=run.id,
                                       code="r", severity="warning", field="title",
                                       message="m", product_id="p1"))
            export_run = ExportRun(feed_source_id=feed["id"], ingestion_run_id=run.id,
                                   status="completed", product_count=1)
            session.add(export_run); await session.flush()
            version = ExportVersion(feed_source_id=feed["id"], export_run_id=export_run.id,
                                    version_number=1, file_hash="x" * 64, product_count=1)
            session.add(version); await session.flush()
            export_run.export_version_id = version.id
            pipeline = ModulePipeline(feed_source_id=feed["id"], name="p", version="1", definition={})
            session.add(pipeline); await session.flush()
            plugin = Plugin(name="example_upper", version="1.0.0", enabled=True,
                            manifest={"id": "example_upper", "extension_point": "pipeline_module"})
            session.add(plugin); await session.flush()
            session.add(ModuleInstance(pipeline_id=pipeline.id, plugin_id=plugin.id,
                                       position=0, name="i", configuration={}))
            session.add(PluginConfig(plugin_id=plugin.id, scope="feed_source",
                                     feed_source_id=feed["id"], key="default", config={"a": 1}))
            session.add(PluginConfig(plugin_id=plugin.id, scope="client",
                                     client_id=created["id"], key="default", config={"b": 2}))
            session.add(PluginData(plugin_id=plugin.id, scope="feed_source",
                                   feed_source_id=feed["id"], key="default", data={"c": 3}))
            fs = await session.get(FeedSource, feed["id"])
            fs.active_pipeline_id = pipeline.id
    return created["id"], feed["id"]
```

(Import `StagingHistory`, `QualityFinding`, `Plugin`, `PluginConfig`, `ModulePipeline`, `ModuleInstance`; check `QualityFinding`'s exact NOT NULL columns in `backend/app/models/quality.py` and supply them all.)

```python
async def test_delete_feed_source_cascades_everything(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    client_id, feed_id = await _full_tree(factory, client)
    resp = await client.delete(f"/feed-sources/{feed_id}")
    assert resp.status_code == 204
    async with factory() as session:
        for model in (StagingHistory, StagingProduct, QualityFinding, ExportVersion,
                      ExportRun, ModuleInstance, ModulePipeline, IngestionRun):
            count = (await session.execute(select(func.count()).select_from(model))).scalar_one()
            assert count == 0, model.__name__
        assert (await session.execute(select(func.count()).select_from(PluginConfig)
                .where(PluginConfig.feed_source_id == feed_id))).scalar_one() == 0
        assert await session.get(Client, client_id) is not None  # client survives


async def test_delete_client_cascades_all_feeds(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    client_id, feed_id = await _full_tree(factory, client)
    resp = await client.delete(f"/clients/{client_id}")
    assert resp.status_code == 204
    async with factory() as session:
        assert await session.get(Client, client_id) is None
        assert await session.get(FeedSource, feed_id) is None
        assert (await session.execute(select(func.count()).select_from(PluginConfig)
                .where(PluginConfig.client_id == client_id))).scalar_one() == 0


async def test_delete_feed_source_rejected_while_run_active(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    client_id, feed_id = await _full_tree(factory, client)
    lock = app.state.lock_registry.get(feed_id)
    async with lock:
        assert (await client.delete(f"/feed-sources/{feed_id}")).status_code == 409
        assert (await client.delete(f"/clients/{client_id}")).status_code == 409
    assert (await client.delete(f"/feed-sources/{feed_id}")).status_code == 204


async def test_delete_removes_published_files(app_factory):
    app, factory, settings = app_factory
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    store = ExportFileStore(Path(settings.export_dir))
    store.publish(feed["id"], b"<xml/>")
    store.write_version(feed["id"], 1, b"<xml/>")
    assert store.published_exists(feed["id"])

    assert (await client.delete(f"/feed-sources/{feed['id']}")).status_code == 204
    assert not store.published_exists(feed["id"])
    assert not (Path(settings.export_dir) / "versions" / str(feed["id"])).exists()
```

(Import `from pathlib import Path` and `from app.export.store import ExportFileStore`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cascade_api.py -v`
Expected: FAIL (client delete 404/405; feed delete 409 because runs exist).

- [ ] **Step 3: Implement the cascade service** — create `backend/app/persistence/cascade.py`:

```python
from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.export import ExportRun, ExportVersion
from ..models.feed_source import FeedSource
from ..models.ingestion import IngestionRun
from ..models.pipeline import ModuleInstance, ModulePipeline
from ..models.plugin import PluginConfig, PluginData
from ..models.quality import QualityFinding
from ..models.staging import StagingProduct


async def delete_feed_source_cascade(session: AsyncSession, feed_source_id: int) -> None:
    await session.execute(delete(QualityFinding).where(QualityFinding.feed_source_id == feed_source_id))
    await session.execute(delete(ExportVersion).where(ExportVersion.feed_source_id == feed_source_id))
    await session.execute(delete(ExportRun).where(ExportRun.feed_source_id == feed_source_id))
    await session.execute(delete(StagingProduct).where(StagingProduct.feed_source_id == feed_source_id))
    pipeline_ids = select(ModulePipeline.id).where(ModulePipeline.feed_source_id == feed_source_id)
    await session.execute(delete(ModuleInstance).where(ModuleInstance.pipeline_id.in_(pipeline_ids)))
    await session.execute(
        update(FeedSource).where(FeedSource.id == feed_source_id)
        .values(active_pipeline_id=None)
    )
    await session.execute(delete(ModulePipeline).where(ModulePipeline.feed_source_id == feed_source_id))
    await session.execute(delete(IngestionRun).where(IngestionRun.feed_source_id == feed_source_id))
    await session.execute(delete(PluginConfig).where(PluginConfig.feed_source_id == feed_source_id))
    await session.execute(delete(PluginData).where(PluginData.feed_source_id == feed_source_id))
    await session.execute(delete(FeedSource).where(FeedSource.id == feed_source_id))


async def delete_client_cascade(session: AsyncSession, client_id: int) -> list[int]:
    feed_ids = list((await session.execute(
        select(FeedSource.id).where(FeedSource.client_id == client_id)
    )).scalars())
    for feed_source_id in feed_ids:
        await delete_feed_source_cascade(session, feed_source_id)
    await session.execute(delete(PluginConfig).where(PluginConfig.client_id == client_id))
    await session.execute(delete(PluginData).where(PluginData.client_id == client_id))
    from ..models.client import Client
    await session.execute(delete(Client).where(Client.id == client_id))
    return feed_ids
```

- [ ] **Step 4: Rework the routes** — in `backend/app/routes/clients.py`:

Replace the body of `delete_feed_source` (keep signature/decorator):

```python
    session = _require_db(db_session)
    locks = _locks(request)
    if locks is not None and locks.is_locked(feed_source_id):
        raise HTTPException(status_code=409, detail="feed source has an active run")
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        await delete_feed_source_cascade(session, feed_source_id)
    scheduler = _scheduler(request)
    if scheduler is not None:
        scheduler.unregister(feed_source_id)
    if locks is not None:
        locks.discard(feed_source_id)
    settings = _resolve_settings(request)
    store = ExportFileStore(settings.export_dir)
    store.published_path(feed_source_id).unlink(missing_ok=True)
    versions_dir = Path(settings.export_dir) / "versions" / str(feed_source_id)
    if versions_dir.is_dir():
        import shutil
        shutil.rmtree(versions_dir, ignore_errors=True)
```

Add the client delete route (import `delete_client_cascade`):

```python
@router.delete("/clients/{client_id}", status_code=204)
async def delete_client(
    client_id: int,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> None:
    session = _require_db(db_session)
    locks = _locks(request)
    async with session.begin():
        client = await session.get(Client, client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="client not found")
        feed_ids = list((await session.execute(
            select(FeedSource.id).where(FeedSource.client_id == client_id)
        )).scalars())
        if locks is not None and any(locks.is_locked(fid) for fid in feed_ids):
            raise HTTPException(status_code=409, detail="client has a feed source with an active run")
        deleted_ids = await delete_client_cascade(session, client_id)
    scheduler = _scheduler(request)
    settings = _resolve_settings(request)
    store = ExportFileStore(settings.export_dir)
    for feed_source_id in deleted_ids:
        if scheduler is not None:
            scheduler.unregister(feed_source_id)
        if locks is not None:
            locks.discard(feed_source_id)
        store.published_path(feed_source_id).unlink(missing_ok=True)
        versions_dir = Path(settings.export_dir) / "versions" / str(feed_source_id)
        if versions_dir.is_dir():
            import shutil
            shutil.rmtree(versions_dir, ignore_errors=True)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cascade_api.py backend/tests/test_clients_api.py -v`
Expected: all PASS. Check existing feed-source-delete tests elsewhere (`grep -rn "delete.*feed-sources" backend/tests/`) — update any test that asserted the old 409-on-runs behavior.

- [ ] **Step 6: Commit**

```bash
git add backend/app/persistence/cascade.py backend/app/routes/clients.py backend/tests/test_cascade_api.py
git commit -m "feat(api): cascade deletes for clients and feed sources (D5)"
```

---

### Task 8: Dry-run endpoint (D4)

**Files:**
- Modify: `backend/app/pipeline/steps.py` (`RunState.dropped`; `PluginStep` records drops)
- Modify: `backend/app/main.py` (expose `app.state.fetcher`, `app.state.image_probe`)
- Create: `backend/app/pipeline/dry_run.py`
- Create: `backend/app/routes/dry_run.py`
- Test: `backend/tests/test_dry_run_api.py`

**Interfaces:**
- Consumes: `IngestStep`, `PluginStep`, `RunState`, `StepContext` (steps.py); `auto_match`, `apply_mapping`, `MappingDocument` (mapping applied in-memory — `MappingStep` persists the auto-map write-back, which a read-only dry-run must not); `resolve_config_bundle`; `run_engine` + rule classes (qc); `HttpFetcher`, `FetchError`; `load_registry()`.
- Produces: `run_dry_run(...) -> DryRunResult` and `POST /feed-sources/{id}/dry-run` (design §1.3).

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_dry_run_api.py`. Use the `test_m9_acceptance.py` pattern: `WIDE_TSV` bytes with baseline columns, `StubFetcher`, `Settings(export_dir=tmp_path…)`, `create_app(settings=…, db_session_factory=factory, fetcher=StubFetcher(WIDE_TSV))`. After creating the app, stub the image probe to avoid network:

```python
class _StubProbe:
    async def probe(self, url):
        return None, None, "unfetchable in tests"

app.state.image_probe = _StubProbe()
```

Tests (create client + feed via API, set `source_url` via `PUT /feed-sources/{id}`):

```python
WIDE_TSV = (
    "id\ttitle\tdescription\tlink\timage_link\tavailability\tprice\tcondition\tbrand\tgtin\n"
    "SKU-1\tRed Shirt\tA red shirt\thttp://shop.example/1\thttp://shop.example/1.jpg\tin_stock\t10.00 USD\tnew\tAcme\t0012345678905\n"
    "drop-me\tBlue Hat\tA blue hat\thttp://shop.example/2\thttp://shop.example/2.jpg\tin_stock\t5.00 USD\tnew\tAcme\t0012345678912\n"
    "SKU-3\tBad Row\t\t\thttp://shop.example/3\thttp://shop.example/3.jpg\tin_stock\t7.00 USD\tnew\tAcme\t0012345678929\n"
).encode("utf-8")
```

```python
async def _make_feed(client, source_url="http://source.example/feed.tsv"):
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    feed = (await client.post(f"/clients/{client_id}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv",
                                    "source_url": source_url, "currency": "USD"})).json()
    return feed["id"]


async def test_dry_run_full_pass_no_side_effects(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _make_feed(client)
    resp = await client.post(f"/feed-sources/{feed_id}/dry-run", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["processed"] == 3
    assert body["parse_errors"] == 0
    assert body["dropped"] == []
    assert set(body["findings"]) == {"critical", "warning", "info"}
    assert isinstance(body["sample"], list) and len(body["sample"]) == 3
    assert body["sample"][0]["id"] == "SKU-1"
    # no staging writes, no export runs/versions, no findings persisted
    async with factory() as session:
        assert (await session.execute(select(func.count()).select_from(StagingProduct))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(ExportRun))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(QualityFinding))).scalar_one() == 0


async def test_dry_run_limit_caps_rows(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _make_feed(client)
    body = (await client.post(f"/feed-sources/{feed_id}/dry-run", json={"limit": 1})).json()
    assert body["total"] == 1
    assert len(body["sample"]) == 1


async def test_dry_run_records_plugin_drops(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _make_feed(client)

    class _Upper:
        def validate_config(self, config):
            if "suffix" not in config:
                raise ValueError("suffix is required")

        def process(self, product, config, data, ctx):
            if product.get("id") == "drop-me":
                return None
            return product

    app.state.plugin_registry["example_upper"] = _Upper()
    async with factory() as session:
        async with session.begin():
            plugin = Plugin(name="example_upper", version="1.0.0", enabled=True,
                            manifest={"id": "example_upper", "name": "Example Upper",
                                      "version": "1.0.0", "extension_point": "pipeline_module",
                                      "config_schema": {"type": "object"},
                                      "data_schema": {"type": "object"}})
            session.add(plugin)
            await session.flush()
            pipeline = ModulePipeline(feed_source_id=feed_id, name="p", version="1", definition={})
            session.add(pipeline)
            await session.flush()
            session.add(ModuleInstance(pipeline_id=pipeline.id, plugin_id=plugin.id,
                                       position=0, name="upper", configuration={"suffix": "!"}))
            fs = await session.get(FeedSource, feed_id)
            fs.active_pipeline_id = pipeline.id

    body = (await client.post(f"/feed-sources/{feed_id}/dry-run", json={})).json()
    assert body["processed"] == 2
    assert body["dropped"] == [{"product_id": "drop-me", "plugin_id": "example_upper",
                                "reason": "example_upper dropped the product"}]


async def test_dry_run_findings_grouped_by_severity_and_rule(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _make_feed(client)
    resp = await client.post(f"/feed-sources/{feed_id}/dry-run", json={})
    critical = resp.json()["findings"]["critical"]
    assert any(entry["rule"] == "baseline_required" and entry["count"] > 0
               and entry["sample"] for entry in critical)
    entry = next(e for e in critical if e["rule"] == "baseline_required")
    assert set(entry["sample"][0]) == {"product_id", "field", "message"}


async def test_dry_run_source_failure_returns_422(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    # feed without source_url → IngestStep raises ValueError → 422
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    feed = (await client.post(f"/clients/{client_id}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    resp = await client.post(f"/feed-sources/{feed['id']}/dry-run", json={})
    assert resp.status_code == 422 and resp.json()["errors"]


async def test_dry_run_404_and_auth(app_factory):
    app, _, _ = app_factory
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anon.post("/feed-sources/1/dry-run", json={})).status_code == 401
    client = await logged_in_client(app_factory)
    assert (await client.post("/feed-sources/99999/dry-run", json={})).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dry_run_api.py -v`
Expected: FAIL with 404 (route missing).

- [ ] **Step 3: Record drops in PluginStep** — in `backend/app/pipeline/steps.py`:

`RunState` gains:

```python
    dropped: list[dict[str, Any]] = field(default_factory=list)
```

In `PluginStep.execute`, inside the `if drop:` branch (before `continue`):

```python
                ctx.run_state.dropped.append({
                    "product_id": str(pid) if pid is not None else "",
                    "plugin_id": instance["plugin"],
                })
```

Run the existing pipeline/plugin tests to confirm nothing broke (from `backend/`):
Run: `uv run pytest tests/test_ingest_step.py tests/test_m6_acceptance.py -v`
Expected: PASS.

- [ ] **Step 4: Expose fetcher and image probe on app.state** — in `backend/app/main.py`, inside the `if app.state.db_session_factory is not None:` block, replace the inline fetcher construction:

```python
        active_fetcher = fetcher if fetcher is not None else HttpFetcher()
        app.state.fetcher = active_fetcher
        image_probe = ImageProbeImpl(app.state.db_session_factory, image_http_client)
        app.state.image_probe = image_probe
        steps = default_steps(
            active_fetcher,          # was: fetcher if fetcher is not None else HttpFetcher()
            load_registry(),
            app.state.plugin_registry,
            clock=app.state.clock,
            image_probe=image_probe,
            export_dir=settings.export_dir if settings is not None else None,
            public_base_url=settings.public_base_url if settings is not None else None,
        )
```

(Only the two `app.state.*` assignments and the `active_fetcher` variable are new; the `default_steps(...)` arguments are unchanged apart from using the variable.)

- [ ] **Step 5: Implement the dry-run service** — create `backend/app/pipeline/dry_run.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.model import RegistryDocument

from ..clock import Clock
from ..ingest.fetch import HttpFetcher
from ..mapping.apply import apply_mapping
from ..mapping.document import MappingDocument
from ..mapping.matcher import auto_match
from ..models.export import ExportRun
from ..models.feed_source import FeedSource
from ..qc.engine import Finding, QcContext, run_engine
from ..staging.config_resolver import resolve_config_bundle
from .steps import IngestStep, PluginStep, RunState, StepContext

DRY_RUN_SAMPLE_CAP = 50


@dataclass
class DryRunResult:
    total: int = 0
    processed: int = 0
    parse_errors: int = 0
    dropped: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    sample: list[dict[str, Any]] = field(default_factory=list)


async def run_dry_run(
    *,
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
    fetcher: HttpFetcher,
    registry: RegistryDocument,
    plugin_registry: dict[str, Any],
    clock: Clock,
    image_probe: Any,
    limit: int | None = None,
) -> DryRunResult:
    logger = logging.getLogger("dry_run")
    run_state = RunState()
    ctx = StepContext(feed_source_id, session_factory, logger, run_state, 0)

    async with session_factory() as session:
        feed_source = await session.get(FeedSource, feed_source_id)
    if feed_source is None:
        raise LookupError(f"feed source {feed_source_id} not found")

    ingest = await IngestStep(fetcher, registry).execute(ctx)
    if limit is not None:
        run_state.products = run_state.products[:limit]
    total = len(run_state.products)

    doc = MappingDocument.from_json(feed_source.field_mapping)
    if not doc.auto_mapped:
        doc.mappings = auto_match(run_state.source_fields, registry, existing=doc.mappings)
    for index, product in enumerate(run_state.products):
        mapped, _ = apply_mapping(product, doc.mappings, registry)
        run_state.products[index] = mapped

    async with session_factory() as session:
        run_state.config_bundle = await resolve_config_bundle(session, feed_source)
    run_state.client_id = feed_source.client_id

    await PluginStep(plugin_registry).execute(ctx)
    processed = list(run_state.products)

    async with session_factory() as session:
        previous_export_run = (await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source_id)
            .order_by(desc(ExportRun.id)).limit(1)
        )).scalar_one_or_none()

    from ..qc.rules import (
        BaselineRequired, BrandRequired, CardinalityRule, ConditionalRequired,
        CurrencyConsistency, DateFormat, EnumValues, GtinMpn, ImageRequirements,
        LengthLimits, VariantConsistency, VolumeDrop,
    )

    qc_ctx = QcContext(
        feed_source_id=feed_source_id,
        currency=feed_source.currency,
        volume_drop_threshold_pct=feed_source.volume_drop_threshold_pct,
        registry=registry,
        clock=clock,
        image_probe=image_probe,
        previous_export_run=previous_export_run,
    )
    findings = await run_engine(
        processed,
        [str(p.get("id", "")) for p in processed],
        qc_ctx,
        [BaselineRequired(), BrandRequired(), GtinMpn(), EnumValues(),
         ConditionalRequired(), DateFormat(), LengthLimits(), CardinalityRule(),
         CurrencyConsistency(), ImageRequirements()],
        [VariantConsistency(), VolumeDrop()],
    )

    return DryRunResult(
        total=total,
        processed=len(processed),
        parse_errors=ingest.failed_count,
        dropped=list(run_state.dropped),
        findings=findings,
        sample=processed[:DRY_RUN_SAMPLE_CAP],
    )
```

- [ ] **Step 6: Implement the route** — create `backend/app/routes/dry_run.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from registry.loader import load_registry

from ..auth import require_user
from ..db.engine import get_db_session
from ..ingest.fetch import FetchError
from ..models.feed_source import FeedSource
from ..pipeline.dry_run import run_dry_run

router = APIRouter()

_FINDING_SAMPLE_CAP = 5


class DryRunRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1)


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _group_findings(findings) -> dict:
    grouped: dict[str, dict[str, dict]] = {"critical": {}, "warning": {}, "info": {}}
    for finding in findings:
        bucket = grouped[finding.severity].setdefault(
            finding.rule_id, {"rule": finding.rule_id, "count": 0, "sample": []})
        bucket["count"] += 1
        if len(bucket["sample"]) < _FINDING_SAMPLE_CAP:
            bucket["sample"].append({"product_id": finding.product_id,
                                     "field": finding.field,
                                     "message": finding.message})
    return {severity: list(rules.values()) for severity, rules in grouped.items()}


@router.post("/feed-sources/{feed_source_id}/dry-run")
async def dry_run(
    feed_source_id: int,
    request: Request,
    payload: DryRunRequest | None = None,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict | JSONResponse:
    session = _require_db(db_session)
    async with session.begin():
        if await session.get(FeedSource, feed_source_id) is None:
            raise HTTPException(status_code=404, detail="feed source not found")

    state = request.app.state
    fetcher = getattr(state, "fetcher", None)
    image_probe = getattr(state, "image_probe", None)
    if fetcher is None or image_probe is None:
        raise HTTPException(status_code=503, detail="pipeline unavailable")

    try:
        result = await run_dry_run(
            session_factory=state.db_session_factory,
            feed_source_id=feed_source_id,
            fetcher=fetcher,
            registry=load_registry(),
            plugin_registry=getattr(state, "plugin_registry", {}),
            clock=state.clock,
            image_probe=image_probe,
            limit=payload.limit if payload else None,
        )
    except (FetchError, ValueError) as exc:
        return JSONResponse(status_code=422, content={"errors": [str(exc)]})

    return {
        "total": result.total,
        "processed": result.processed,
        "parse_errors": result.parse_errors,
        "dropped": [
            {"product_id": d["product_id"], "plugin_id": d["plugin_id"],
             "reason": f"{d['plugin_id']} dropped the product"}
            for d in result.dropped
        ],
        "findings": _group_findings(result.findings),
        "sample": result.sample,
    }
```

- [ ] **Step 7: Register the router** in `backend/app/main.py` (`dry_run_router`), run tests:

Run: `uv run pytest tests/test_dry_run_api.py -v`
Expected: all PASS.

- [ ] **Step 8: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS (no regressions from the `RunState`/`PluginStep`/`main.py` changes).

- [ ] **Step 9: Commit**

```bash
git add backend/app/pipeline/steps.py backend/app/pipeline/dry_run.py backend/app/routes/dry_run.py backend/app/main.py backend/tests/test_dry_run_api.py
git commit -m "feat(api): read-only dry-run endpoint (D4)"
```

---

### Task 9: Ship `example_upper` demo plugin + decisions + final gate

**Files:**
- Create: `plugins/example_upper/plugin.json`, `plugins/example_upper/plugin.py`
- Create: `backend/tests/test_example_plugin_contract.py`
- Modify: `docs/decisions.md`

**Interfaces:**
- Consumes: `discover()` from `app.plugins.discovery`, `contract_violations` from `app.plugins.contract`.
- Produces: a discovered, contract-passing demo plugin with a `frontend` manifest section (menu item, no component → auto-rendered UI path in M10-b/d).

- [ ] **Step 1: Copy the fixture and extend the manifest**

```bash
mkdir -p plugins/example_upper
cp backend/tests/fixtures/example_plugin/plugin.py plugins/example_upper/plugin.py
```

Create `plugins/example_upper/plugin.json` (fixture content + `frontend` key):

```json
{
  "id": "example_upper",
  "name": "Example Upper",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "entry_point": "plugin:UpperPlugin",
  "config_scope": ["global", "client"],
  "data_scope": ["global"],
  "config_schema": {
    "type": "object",
    "properties": {"suffix": {"type": "string"}},
    "required": ["suffix"]
  },
  "data_schema": {"type": "object"},
  "frontend": {"menu_item": "Example Upper", "icon": "letter-e"}
}
```

- [ ] **Step 2: Write the contract test** — create `backend/tests/test_example_plugin_contract.py`:

```python
from pathlib import Path

from app.plugins.contract import contract_violations
from app.plugins.discovery import discover

PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"


def test_example_upper_passes_contract_suite():
    candidates, rejected = discover(PLUGINS_DIR)
    assert rejected == []
    assert [c.manifest.id for c in candidates] == ["example_upper"]
    assert contract_violations(candidates[0]) == []


def test_example_upper_declares_frontend_menu_item():
    candidates, _ = discover(PLUGINS_DIR)
    frontend = candidates[0].manifest.raw.get("frontend")
    assert frontend == {"menu_item": "Example Upper", "icon": "letter-e"}
```

- [ ] **Step 3: Run the test**

Run: `uv run pytest tests/test_example_plugin_contract.py -v`
Expected: PASS (if manifest validation rejects the unknown `frontend` key, fix the manifest parser to tolerate extra keys — check `backend/app/plugins/manifest.py`; extra keys must be preserved in `raw`).

- [ ] **Step 4: Record decisions** — append to `docs/decisions.md` under today's date (follow the existing entry format): M10-a endpoint decisions (D1–D5 implementation records per design §7), pipeline API semantics, dry-run drop reason + `parse_errors` + sample cap, cascade implementation (explicit order, no migration, 409 active-run guard), `POST /auth/password` verified pre-existing, mapping target grammar clarification, `example_upper` demo plugin shipped, rollback "not QC'd" badge, dry-run latency acceptance.

- [ ] **Step 5: Full verification gate**

Run (from `backend/`): `uv run pytest -q && uv run python -m compileall app`
Expected: all PASS.
Run: `git status` — confirm only intended files changed.

- [ ] **Step 6: Commit**

```bash
git add plugins/ backend/tests/test_example_plugin_contract.py docs/decisions.md
git commit -m "feat(plugins): ship example_upper demo plugin for M10 verification"
```

---

## Self-review notes (author)

- Spec coverage: design §1.1→Task 3, §1.2→Task 4, §1.3→Task 8, §1.4→Task 7, §1.5→Task 5, §1.6→Task 1, §1.7→Tasks 2+6, demo plugin §3→Task 9, §0.5 (no rebuild) honored, §0.6 (mapping grammar) untouched.
- Design §1.3 said "reuse MappingStep"; the plan applies `auto_match` + `apply_mapping` in-memory instead because `MappingStep` persists the auto-map write-back, which violates dry-run read-only semantics. Same observable behavior, no DB write.
- Type consistency: `DryRunResult` fields, `PipelineOut`/`PipelinePut` shapes, cascade function signatures, and `used_by_feed_sources` are used identically across tasks and match the design doc response shapes.
