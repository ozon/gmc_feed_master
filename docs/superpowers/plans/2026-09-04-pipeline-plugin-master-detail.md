# Pipeline Plugin Master–Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the per-feed-source pipeline page into a master–detail layout: left = ordered plugin instance list (dnd reorder, per-instance enable switches, add-from-registry, global registry toggles), right = config form of the selected instance, top = overview strip; backed by a new `module_instances.enabled` column with a PATCH endpoint for immediate persist.

**Architecture:** Backend adds an `enabled` column + PATCH endpoint + upsert-by-id PUT; `resolve_config_bundle` excludes disabled instances so `PluginStep` and `config_hash` work without further changes. Frontend replaces `PluginPalette`/`PipelineWorkspace`/`PipelineInstanceCard`/`PluginRegistryPanel` with `PluginList` (master) + `PluginConfigPanel` (detail) + `PipelineOverviewStrip`, keeping dnd-kit for reorder and Save-based dirty semantics for everything except the enable switch.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic (backend); React 19 + Mantine 9 + @dnd-kit 6 + TanStack Query + vitest/RTL (frontend).

**Spec:** `docs/superpowers/specs/2026-09-04-pipeline-plugin-master-detail-design.md`

## Global Constraints

- Backend commands run from `backend/`: `uv run pytest -n auto` (needs `TEST_DATABASE_URL` in `.env`), `uv run ruff check .`, `uv run mypy .`.
- Frontend commands run from `frontend/`: `npm run test`, `npm run typecheck`, `npm run build`.
- Migrations only via Alembic autogenerate; never edit `module_instances` rows outside a migration.
- No new npm/pip dependencies (dnd-kit and Mantine already present).
- i18n: every user-visible string goes through `useTranslation('pipeline')`; keys must be added to BOTH `frontend/public/locales/en/pipeline.json` and `frontend/public/locales/de/pipeline.json`.
- Server state only via TanStack Query hooks in `src/api/hooks.ts` — no duplicate stores.
- Docs updated in the same commit as behavior changes: `backend/docs/api.md`, `backend/docs/data-model.md`, `backend/docs/architecture.md`, `frontend/docs/architecture.md`.
- All API payloads use snake_case (`plugin_id`, `used_by`), matching existing routes.
- Test ids: `plugin-row-<clientId>`, `plugin-toggle-<clientId>` (instance switches), `registry-toggle-<pluginId>` (global), `add-plugin-<pluginId>`, `config-panel`, `overview-strip`.
- Reserved plugin routes `/plugins/{id}/config` and `/plugins/{id}/data` must not be touched.

---

### Task 1: Backend — `module_instances.enabled` column + migration

**Files:**
- Modify: `backend/app/models/pipeline.py:32-40`
- Create: `backend/alembic/versions/20260905_0001_module_instance_enabled.py` (via autogenerate)
- Test: `backend/tests/test_m9_migration.py` (create, patterned on `test_m2_migration.py`)

**Interfaces:**
- Produces: `ModuleInstance.enabled: Mapped[bool]` (nullable=False, default True, server_default true) — later tasks rely on this attribute existing on the ORM model.

- [ ] **Step 1: Write the failing migration test**

Read `backend/tests/test_m2_migration.py` first and follow its pattern. Create `backend/tests/test_m9_migration.py`:

```python
"""module_instances.enabled column migration test (M9 master-detail pipeline page)."""

import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.conftest import run_migrations


@pytest.mark.asyncio
async def test_module_instances_enabled_column(isolated_database_url):
    # Migrations run once per test session by conftest; verify the column shape.
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(isolated_database_url)
    async with engine.connect() as conn:
        col = (await conn.execute(text(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'module_instances' AND column_name = 'enabled'"
        ))).first()
    await engine.dispose()
    assert col is not None, "module_instances.enabled column must exist"
    assert col[0] == "NO"
    assert col[1] == "true"
```

Note: before writing this step, read `backend/tests/conftest.py` and `backend/tests/test_m2_migration.py` and adapt to the actual migration-runner pattern used there (fixture names, how migrations are invoked). If conftest applies migrations automatically for `isolated_database_url`, keep the test as schema introspection; otherwise trigger migrations the way `test_m2_migration.py` does.

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `uv run pytest tests/test_m9_migration.py -v`
Expected: FAIL — column does not exist (`col is None`).

- [ ] **Step 3: Add the column to the model**

In `backend/app/models/pipeline.py`, change the `ModuleInstance` class (currently lines 32-40). Add to imports: `from sqlalchemy import Boolean` (merge into the existing sqlalchemy import line). Add the column after `position`:

```python
class ModuleInstance(Base):
    __tablename__ = "module_instances"
    __table_args__ = (Index("ix_module_instances_pipeline_id", "pipeline_id"), Index("ix_module_instances_plugin_id", "plugin_id"), UniqueConstraint("pipeline_id", "position", name="uq_module_instances_pipeline_position"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("module_pipelines.id", ondelete="RESTRICT"), nullable=False)
    plugin_id: Mapped[int] = mapped_column(ForeignKey("plugins.id", ondelete="RESTRICT"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
```

(`server_default=true()` is `sqlalchemy.true()`; import `true` from sqlalchemy or write `server_default=sa.true()` accordingly.)

- [ ] **Step 4: Generate the migration**

Run (from `backend/`, with postgres up and `DATABASE_URL` set as in AGENTS.md):
`DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed uv run alembic revision --autogenerate -m "module_instance_enabled"`

Verify the generated file contains `op.add_column('module_instances', sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))`. Edit revision metadata (revision id, `down_revision` = `'20260828_0001'` if that is the current head — check `uv run alembic heads` first) to follow repo style (`20260905_0001`).

- [ ] **Step 5: Apply migration and run test**

Run: `DATABASE_URL=... uv run alembic upgrade head && uv run pytest tests/test_m9_migration.py -v`
Expected: PASS.

- [ ] **Step 6: Run full backend suite, lint, typecheck**

Run: `uv run pytest -n auto && uv run ruff check . && uv run mypy .`
Expected: all pass (no existing behavior changed yet — `enabled` defaults to true everywhere).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/pipeline.py backend/alembic/versions/ backend/tests/test_m9_migration.py
git commit -m "feat(pipeline): module_instances.enabled column + migration"
```

---

### Task 2: Backend — GET/PUT pipeline API with `id`/`enabled` + upsert-by-id

**Files:**
- Modify: `backend/app/schemas/pipeline.py`
- Modify: `backend/app/routes/pipeline.py:28-126`
- Test: `backend/tests/test_pipeline_api.py`

**Interfaces:**
- Consumes: `ModuleInstance.enabled` from Task 1.
- Produces: `GET /feed-sources/{id}/pipeline` → `{"instances": [{"id": int, "position": int, "plugin_id": str, "name": str, "configuration": dict, "enabled": bool}]}`; `PUT` same shape with optional `id` on input; `PipelineInstanceIn/Out` pydantic models with these fields. Task 3's PATCH and the frontend rely on this exact response shape.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_pipeline_api.py` (reuse existing fixtures `app_factory`, `logged_in_client`, `_register_plugin`):

```python
async def test_get_pipeline_returns_id_and_enabled(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "name": "Upper",
                       "configuration": {"suffix": "!"}}]})
    assert resp.status_code == 200
    inst = resp.json()["instances"][0]
    assert isinstance(inst["id"], int)
    assert inst["enabled"] is True


async def test_put_pipeline_upsert_keeps_ids(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    first = (await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "name": "Upper",
                       "configuration": {"suffix": "!"}}]})).json()
    first_id = first["instances"][0]["id"]

    # Re-save: same instance (id passed back), reordered name edit, one new instance.
    second = (await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [
            {"id": first_id, "plugin_id": "example_upper", "name": "Upper v2",
             "configuration": {"suffix": "?"}, "enabled": False},
            {"plugin_id": "example_upper", "name": "Upper2",
             "configuration": {"suffix": "!"}},
        ]})).json()
    ids = [i["id"] for i in second["instances"]]
    assert ids[0] == first_id          # upsert preserved the row
    assert ids[1] != first_id          # new row got a new id
    assert second["instances"][0]["name"] == "Upper v2"
    assert second["instances"][0]["enabled"] is False

    # Save again dropping the second instance: row removed, first stays.
    third = (await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"id": first_id, "plugin_id": "example_upper",
                       "name": "Upper v2", "configuration": {"suffix": "?"}}] })).json()
    assert [i["id"] for i in third["instances"]] == [first_id]
    async with factory() as session:
        count = (await session.execute(select(func.count()).select_from(ModuleInstance))).scalar_one()
        assert count == 1


async def test_put_pipeline_rejects_foreign_instance_id(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    first = (await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "configuration": {"suffix": "!"}}]})).json()
    # Instance id belonging to another pipeline would be rejected; simulate with a bogus id.
    resp = await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"id": 999999, "plugin_id": "example_upper",
                       "configuration": {"suffix": "!"}}]})
    assert resp.status_code == 422
    assert any("unknown instance" in e for e in resp.json()["errors"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline_api.py -v`
Expected: new tests FAIL (no `id`/`enabled` in responses; PUT is delete-all-reinsert).

- [ ] **Step 3: Update schemas**

Replace `backend/app/schemas/pipeline.py` content:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PipelineInstanceIn(BaseModel):
    id: int | None = Field(default=None, ge=1)
    plugin_id: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    configuration: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class PipelinePut(BaseModel):
    instances: list[PipelineInstanceIn] = Field(default_factory=list)


class PipelineInstanceOut(BaseModel):
    id: int
    position: int
    plugin_id: str
    name: str
    configuration: dict[str, Any]
    enabled: bool


class PipelineOut(BaseModel):
    instances: list[PipelineInstanceOut]
```

- [ ] **Step 4: Rewrite GET and PUT handlers**

In `backend/app/routes/pipeline.py`:

GET (`get_pipeline`) — replace the comprehension at lines 47-53:

```python
    return {"instances": [
        {"id": instance.id,
         "position": instance.position,
         "plugin_id": (plugin.manifest or {}).get("id") or plugin.name,
         "name": instance.name,
         "configuration": instance.configuration,
         "enabled": instance.enabled}
        for instance, plugin in rows
    ]}
```

PUT (`put_pipeline`) — after the validation loop (unchanged) and pipeline fetch (unchanged), replace the delete-all/reinsert block (lines 108-124) with upsert-by-id:

```python
        existing_rows = (await session.execute(
            select(ModuleInstance).where(ModuleInstance.pipeline_id == pipeline.id)
        )).scalars().all()
        existing_by_id = {row.id: row for row in existing_rows}

        # Reject ids that do not belong to this pipeline.
        for index, item in enumerate(payload.instances):
            if item.id is not None and item.id not in existing_by_id:
                errors.append(f"instance {index}: unknown instance id {item.id}")
        if errors:
            return _validation_error(errors)

        kept_ids = {item.id for item in payload.instances if item.id is not None}
        for row in existing_rows:
            if row.id not in kept_ids:
                await session.delete(row)

        instances_out = []
        definition = []
        for position, item in enumerate(payload.instances):
            plugin = plugins[item.plugin_id]
            name = item.name or (plugin.manifest or {}).get("name") or plugin.name
            if item.id is not None:
                row = existing_by_id[item.id]
                row.position = position
                row.name = name
                row.configuration = item.configuration
                row.enabled = item.enabled
                instance_id = row.id
            else:
                row = ModuleInstance(
                    pipeline_id=pipeline.id, plugin_id=plugin.id, position=position,
                    name=name, configuration=item.configuration, enabled=item.enabled,
                )
                session.add(row)
                await session.flush()
                instance_id = row.id
            instances_out.append({"id": instance_id, "position": position,
                                  "plugin_id": item.plugin_id, "name": name,
                                  "configuration": item.configuration,
                                  "enabled": item.enabled})
            definition.append({"plugin_id": item.plugin_id, "name": name,
                               "configuration": item.configuration,
                               "enabled": item.enabled})
        pipeline.definition = {"instances": definition}
```

Note: `errors` must be initialized before the id check — it already is (line 73). The old `errors` collection loop for unknown plugins etc. stays. Keep the module imports (`select` already imported; add nothing new except `ModuleInstance` is already imported).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_pipeline_api.py -v`
Expected: ALL pass — including the pre-existing tests. `test_put_pipeline_roundtrip` asserts `body["instances"] == [{...}]` without `id`/`enabled` — update it to include `"id": body["instances"][0]["id"]` and `"enabled": True` (read the actual first instance id from the PUT response) and keep the GET roundtrip assertion.

- [ ] **Step 5b: Fix old test expectations**

In `test_put_pipeline_roundtrip`, change:
```python
    assert body["instances"] == [{"position": 0, "plugin_id": "example_upper",
                                  "name": "Upper", "configuration": {"suffix": "!"}}]
```
to:
```python
    assert body["instances"] == [{"id": body["instances"][0]["id"], "position": 0,
                                  "plugin_id": "example_upper", "name": "Upper",
                                  "configuration": {"suffix": "!"}, "enabled": True}]
```

- [ ] **Step 6: Lint + typecheck + full suite**

Run: `uv run ruff check . && uv run mypy . && uv run pytest -n auto`
Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/pipeline.py backend/app/routes/pipeline.py backend/tests/test_pipeline_api.py
git commit -m "feat(pipeline): instance id/enabled in pipeline API, upsert-by-id PUT"
```

---

### Task 3: Backend — PATCH endpoint for instance enable

**Files:**
- Modify: `backend/app/schemas/pipeline.py` (add `InstancePatch`)
- Modify: `backend/app/routes/pipeline.py`
- Test: `backend/tests/test_pipeline_api.py`

**Interfaces:**
- Consumes: upsert-by-id PUT from Task 2 (needed so PATCHed ids survive re-saves).
- Produces: `PATCH /feed-sources/{fs_id}/pipeline/instances/{instance_id}` body `{"enabled": bool}` → `200 {"id": int, "enabled": bool}`; 404 unknown feed source/instance. Task 5's `usePatchPipelineInstance` calls exactly this.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_pipeline_api.py`:

```python
async def test_patch_instance_enabled(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    await _register_plugin(factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    put = (await client.put(f"/feed-sources/{feed['id']}/pipeline", json={
        "instances": [{"plugin_id": "example_upper", "configuration": {"suffix": "!"}}]})).json()
    inst_id = put["instances"][0]["id"]

    resp = await client.patch(f"/feed-sources/{feed['id']}/pipeline/instances/{inst_id}",
                              json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json() == {"id": inst_id, "enabled": False}

    got = (await client.get(f"/feed-sources/{feed['id']}/pipeline")).json()
    assert got["instances"][0]["enabled"] is False

    # definition JSONB mirrors rows
    async with factory() as session:
        fs = await session.get(FeedSource, feed["id"])
        pipeline = await session.get(ModulePipeline, fs.active_pipeline_id)
        assert pipeline.definition["instances"][0]["enabled"] is False


async def test_patch_instance_not_found(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    resp = await client.patch(f"/feed-sources/{feed['id']}/pipeline/instances/999999",
                              json={"enabled": True})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline_api.py -k patch -v`
Expected: FAIL — 405 Method Not Allowed (route doesn't exist).

- [ ] **Step 3: Add schema + route**

Append to `backend/app/schemas/pipeline.py`:

```python
class InstancePatch(BaseModel):
    enabled: bool
```

Append to `backend/app/routes/pipeline.py` (after `put_pipeline`):

```python
@router.patch("/feed-sources/{feed_source_id}/pipeline/instances/{instance_id}")
async def patch_pipeline_instance(
    feed_source_id: int,
    instance_id: int,
    payload: InstancePatch,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None or feed_source.active_pipeline_id is None:
            raise HTTPException(status_code=404, detail="instance not found")
        instance = await session.get(ModuleInstance, instance_id)
        if instance is None or instance.pipeline_id != feed_source.active_pipeline_id:
            raise HTTPException(status_code=404, detail="instance not found")
        instance.enabled = payload.enabled

        pipeline = await session.get(ModulePipeline, feed_source.active_pipeline_id)
        definition = pipeline.definition or {"instances": []}
        for row in definition.get("instances", []):
            pass  # definition rows are keyed by position, id-less; rebuild below
        rows = (await session.execute(
            select(ModuleInstance)
            .where(ModuleInstance.pipeline_id == pipeline.id)
            .order_by(ModuleInstance.position)
        )).scalars().all()
        pipeline.definition = {"instances": [
            {"plugin_id": r.plugin_id, "name": r.name,
             "configuration": r.configuration, "enabled": r.enabled}
            for r in rows
        ]}
    return {"id": instance_id, "enabled": payload.enabled}
```

Import `InstancePatch` in the route module's schema import line. Remove the placeholder `for row in ...: pass` loop before committing (it exists only to show definition rebuild; final code goes straight to rebuilding from rows).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_pipeline_api.py -v`
Expected: pass.

- [ ] **Step 5: Lint + typecheck**

Run: `uv run ruff check . && uv run mypy .`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/pipeline.py backend/app/routes/pipeline.py backend/tests/test_pipeline_api.py
git commit -m "feat(pipeline): PATCH instance enabled endpoint"
```

---

### Task 4: Backend — `resolve_config_bundle` excludes disabled instances

**Files:**
- Modify: `backend/app/staging/config_resolver.py:66-73`
- Test: `backend/tests/test_config_bundle.py`

**Interfaces:**
- Consumes: `ModuleInstance.enabled` from Task 1.
- Produces: `resolve_config_bundle` output `bundle["instances"]` contains only enabled instances. `PluginStep` and `content_hash(bundle)` need no changes (they consume the bundle as-is). This is the run-time semantics the frontend switch drives.

- [ ] **Step 1: Write the failing test**

Read `backend/tests/test_config_bundle.py` first and follow its fixture pattern (it builds pipeline rows directly). Append a test that:

```python
async def test_bundle_excludes_disabled_instances(...):  # keep the module's existing fixture args
    # ...create pipeline + two ModuleInstance rows (same plugin ok), one enabled=True,
    # one enabled=False, following the existing tests' row-creation pattern...
    bundle = await resolve_config_bundle(session, feed_source)
    positions = [i["position"] for i in bundle["instances"]]
    assert positions == [0]  # only the enabled instance is in the bundle
```

Follow the file's existing fixture/row-creation code verbatim — the exact test must be written against the real fixtures in that file (it has helpers creating `ModulePipeline`/`ModuleInstance` rows; mirror `test_config_bundle.py`'s existing "instances" test and add `enabled=False` to one row).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_bundle.py -k disabled -v`
Expected: FAIL — bundle currently includes both instances.

- [ ] **Step 3: Implement the filter**

In `backend/app/staging/config_resolver.py`, change lines 66-71 from:

```python
    result = await session.execute(
        select(ModuleInstance)
        .where(ModuleInstance.pipeline_id == pipeline.id)
        .order_by(ModuleInstance.position)
    )
    instances = list(result.scalars())
```

to:

```python
    result = await session.execute(
        select(ModuleInstance)
        .where(ModuleInstance.pipeline_id == pipeline.id)
        .where(ModuleInstance.enabled.is_(True))
        .order_by(ModuleInstance.position)
    )
    instances = list(result.scalars())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config_bundle.py tests/test_plugin_step.py tests/test_pipeline_steps.py -v`
Expected: pass (existing tests create rows without `enabled`, ORM default True applies).

- [ ] **Step 5: Full suite + lint + typecheck**

Run: `uv run pytest -n auto && uv run ruff check . && uv run mypy .`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/staging/config_resolver.py backend/tests/test_config_bundle.py
git commit -m "feat(pipeline): config bundle excludes disabled instances"
```

---

### Task 5: Frontend — types, api client, hook

**Files:**
- Modify: `frontend/src/api/types.ts:175-180`
- Modify: `frontend/src/api/client.ts:57-79`
- Modify: `frontend/src/api/hooks.ts` (after `useSavePipeline`, line ~469)
- Test: `frontend/src/api/hooks.pipeline.test.tsx` (new)

**Interfaces:**
- Consumes: PATCH endpoint from Task 3.
- Produces: `PipelineInstance = { id: number | null; position: number; plugin_id: string; name: string; configuration: Record<string, unknown>; enabled: boolean }`; `apiPatch<T>(url, body)`; `usePatchPipelineInstance(feedSourceId)` → mutation of `{ instanceId: number; enabled: boolean }` returning `{ id: number; enabled: boolean }`, invalidating `queryKeys.feedSource(id).pipeline` on success. Tasks 6-8 consume these.

- [ ] **Step 1: Write the failing hook test**

Create `frontend/src/api/hooks.pipeline.test.tsx` (pattern from `hooks.plugin.test.tsx` — read it first for its QueryClient + stubFetch setup):

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { render, renderHook, waitFor as waitForHook } from '@testing-library/react';
import { usePatchPipelineInstance } from './hooks';
import { stubFetch } from '../test/fetch';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('usePatchPipelineInstance', () => {
  beforeEach(() => {
    stubFetch((url, init) => {
      if (url === '/feed-sources/7/pipeline/instances/42' && init?.method === 'PATCH') {
        return jsonResponse({ id: 42, enabled: false });
      }
      return jsonResponse({});
    });
  });

  it('PATCHes the instance and invalidates the pipeline query', async () => {
    let pipelineRefetched = false;
    stubFetch((url) => {
      if (url === '/feed-sources/7/pipeline') {
        pipelineRefetched = true;
        return jsonResponse({ instances: [] });
      }
      return jsonResponse({});
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    client.setQueryData(['feed-source', 7, 'pipeline'], { instances: [] });

    const { result } = renderHook(() => usePatchPipelineInstance('7'), { wrapper });
    result.current.mutate({ instanceId: 42, enabled: false });
    await waitForHook(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ id: 42, enabled: false });
    await waitForHook(() => expect(pipelineRefetched).toBe(true));
  });
});
```

Adapt to the actual helpers the repo's test setup exports (`renderHook` availability in the RTL version used; if not available, mount a tiny probe component instead — check how `hooks.plugin.test.tsx` tests mutations).

- [ ] **Step 2: Run test to verify it fail**

Run (from `frontend/`): `npm run test -- hooks.pipeline`
Expected: FAIL — `usePatchPipelineInstance` is not exported.

- [ ] **Step 3: Implement types, apiPatch, hook**

`frontend/src/api/types.ts` — replace `PipelineInstance`:

```typescript
export type PipelineInstance = {
  id: number | null;
  position: number;
  plugin_id: string;
  name: string;
  configuration: Record<string, unknown>;
  enabled: boolean;
};
```

`frontend/src/api/client.ts` — add next to `apiPut`:

```typescript
export function apiPatch<T>(url: string, body?: unknown): Promise<T> {
  return request<T>(url, jsonInit('PATCH', body));
}
```

`frontend/src/api/hooks.ts` — add import `apiPatch` to the client import line, and after `useSavePipeline`:

```typescript
export function usePatchPipelineInstance(feedSourceId: number | string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ instanceId, enabled }: { instanceId: number; enabled: boolean }) =>
      apiPatch<{ id: number; enabled: boolean }>(
        `/feed-sources/${feedSourceId}/pipeline/instances/${instanceId}`,
        { enabled },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(feedSourceId).pipeline,
      });
    },
  });
}
```

Note: typecheck will now fail in `dndUtils.ts` / `PipelinePage.tsx` / tests because `PipelineInstance` gained required `id`/`enabled` — that is expected and will be fixed in Task 6. To keep this task green in isolation, EITHER do steps of Task 6 that touch `dndUtils.ts` (types only) in the same task, OR accept the temporary typecheck failure and run only `npm run test -- hooks.pipeline` here (full `npm run typecheck` becomes green again in Task 6). Prefer: include `dndUtils.ts` type updates (below) in THIS task so typecheck stays green.

`frontend/src/features/pipeline/dndUtils.ts` — update `addInstance` to set `id: null, enabled: true` on new instances and remove the palette branch from `applyDragEnd`:

```typescript
export function addInstance(
  instances: LocalInstance[],
  plugin: { id: string; name: string },
): LocalInstance[] {
  const taken = new Set(instances.map((i) => i.clientId));
  let index = instances.length;
  while (taken.has(`${plugin.id}-${index}`)) index += 1;
  const clientId = `${plugin.id}-${index}`;
  return [
    ...instances,
    {
      id: null,
      enabled: true,
      clientId,
      position: instances.length,
      plugin_id: plugin.id,
      name: plugin.name,
      configuration: {},
    },
  ];
}
```

And `applyDragEnd` (remove palette branch):

```typescript
export function applyDragEnd(
  instances: LocalInstance[],
  event: {
    active: { id: string | number; data?: { current?: unknown } };
    over: { id: string | number } | null;
  },
): LocalInstance[] | null {
  const activeData = event.active.data?.current as { source?: string } | undefined;
  if (activeData?.source === 'workspace' && event.over) {
    const fromIdx = instances.findIndex((i) => i.clientId === event.active.id);
    const toIdx = instances.findIndex((i) => i.clientId === event.over!.id);
    if (fromIdx >= 0 && toIdx >= 0) return reorderInstances(instances, fromIdx, toIdx);
  }
  return null;
}
```

Update `dndUtils.test.ts` accordingly: instances gain `id: null, enabled: true` in fixtures; remove palette-drop tests; add a case asserting `addInstance` sets `enabled: true` and `id: null`.

- [ ] **Step 4: Run tests**

Run: `npm run test -- hooks.pipeline dndUtils`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/hooks.ts frontend/src/api/hooks.pipeline.test.tsx frontend/src/features/pipeline/dndUtils.ts frontend/src/features/pipeline/dndUtils.test.ts
git commit -m "feat(frontend): pipeline instance patch hook + typed instances"
```

---

### Task 6: Frontend — `PipelineOverviewStrip` + `PluginConfigPanel`

**Files:**
- Create: `frontend/src/features/pipeline/PipelineOverviewStrip.tsx`
- Create: `frontend/src/features/pipeline/PluginConfigPanel.tsx`
- Create: `frontend/src/features/pipeline/PipelineOverviewStrip.test.tsx`
- Create: `frontend/src/features/pipeline/PluginConfigPanel.test.tsx`

**Interfaces:**
- Consumes: `LocalInstance` (with `id`, `enabled`) from Task 5; `JsonSchemaForm` + `JsonSchema` from `src/components/JsonSchemaForm.tsx`.
- Produces: `<PipelineOverviewStrip instances={LocalInstance[]} dirty={boolean} />` and `<PluginConfigPanel instance={LocalInstance | null} plugin={PluginInfo | undefined} onChange={(next: Record<string, unknown>) => void} onRemove={() => void} />`. Task 7 composes both.

- [ ] **Step 1: Write failing tests**

`PipelineOverviewStrip.test.tsx`:

```tsx
import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { PipelineOverviewStrip } from './PipelineOverviewStrip';
import type { LocalInstance } from './dndUtils';

beforeAll(async () => {
  await i18n.loadNamespaces(['pipeline', 'common']);
});

const instances: LocalInstance[] = [
  { id: 1, position: 0, plugin_id: 'upper', name: 'Upper', configuration: {}, enabled: true, clientId: 'upper-0' },
  { id: 2, position: 1, plugin_id: 'lower', name: 'Lower', configuration: {}, enabled: false, clientId: 'lower-1' },
];

describe('PipelineOverviewStrip', () => {
  it('shows total, enabled and disabled counts', () => {
    render(<PipelineOverviewStrip instances={instances} dirty={false} />);
    expect(screen.getByTestId('overview-strip')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();       // total (see i18n: "{{count}} instances")
    expect(screen.getByText('1')).toBeInTheDocument();       // enabled
  });

  it('shows a dirty badge when dirty', () => {
    render(<PipelineOverviewStrip instances={instances} dirty={true} />);
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();
  });
});
```

Careful: counting text "1"/"2" is ambiguous if badges render counts alone — assert on the full i18n strings instead (e.g. `screen.getByText(/^2 instances$/i)` and `/^1 enabled$/i`, `/^1 disabled$/i`) with the i18n keys defined in Step 3.

`PluginConfigPanel.test.tsx`:

```tsx
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { PluginConfigPanel } from './PluginConfigPanel';
import type { LocalInstance } from './dndUtils';
import type { PluginInfo } from '../../api/types';

beforeAll(async () => {
  await i18n.loadNamespaces(['pipeline', 'common']);
});

const instance: LocalInstance = {
  id: 1, position: 0, plugin_id: 'upper', name: 'Upper',
  configuration: { suffix: '!' }, enabled: true, clientId: 'upper-0',
};
const plugin: PluginInfo = {
  id: 'upper', name: 'Upper', version: '2.1.0', enabled: true,
  manifest: {
    extension_point: 'pipeline_module',
    config_schema: {
      type: 'object',
      properties: { suffix: { type: 'string', title: 'Suffix' } },
    },
  },
  used_by_feed_sources: 0,
};

describe('PluginConfigPanel', () => {
  it('renders header with instance name, version and remove button', () => {
    render(<PluginConfigPanel instance={instance} plugin={plugin} onChange={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText('Upper')).toBeInTheDocument();
    expect(screen.getByText(/v2\.1\.0/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument();
  });

  it('shows a disabled banner when the instance is disabled', () => {
    render(<PluginConfigPanel instance={{ ...instance, enabled: false }} plugin={plugin} onChange={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByTestId('config-panel')).toBeInTheDocument();
    expect(screen.getByText(/does not run/i)).toBeInTheDocument();
  });

  it('edits configuration through the form', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PluginConfigPanel instance={instance} plugin={plugin} onChange={onChange} onRemove={vi.fn()} />);
    const input = await screen.findByLabelText(/suffix/i);
    await user.clear(input);
    await user.type(input, '?');
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ suffix: '?' }));
  });

  it('renders an empty state when no instance is selected', () => {
    render(<PluginConfigPanel instance={null} plugin={plugin} onChange={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText(/select a plugin/i)).toBeInTheDocument();
  });
});
```

(The last `onChange` call receives the FULL form value — verify against `JsonSchemaForm`'s actual onChange payload when writing; the assertion uses `expect.objectContaining`.)

- [ ] **Step 2: Add i18n keys**

`frontend/public/locales/en/pipeline.json` — add:

```json
{
  "overview": {
    "total": "{{count}} instances",
    "enabled": "{{count}} enabled",
    "disabled": "{{count}} disabled",
    "dirty": "Unsaved changes"
  },
  "configPanel": {
    "selectPlugin": "Select a plugin from the list to configure it.",
    "disabledInfo": "This instance is disabled and does not run.",
    "noSchema": "This plugin has no configuration options.",
    "remove": "Remove"
  }
}
```

Merge these into the existing flat file (the file is flat today — either keep flat keys `overviewTotal`, `overviewEnabled`, `overviewDisabled`, `overviewDirty`, `configSelectPlugin`, `configDisabledInfo`, `configNoSchema`, `configRemove` OR introduce nesting; react-i18next supports both with `keySeparator: false` behavior differing — SAFEST: flat keys, e.g. `"overviewTotal": "{{count}} instances"`, and `t('overviewTotal', {count})`. Check how existing keys like `inUse` are used — they are flat). Use flat keys to match the file's existing style.

Do the same for `de/pipeline.json`:
`"overviewTotal": "{{count}} Instanzen"`, `"overviewEnabled": "{{count}} aktiv"`, `"overviewDisabled": "{{count}} deaktiviert"`, `"overviewDirty": "Ungespeicherte Änderungen"`, `"configSelectPlugin": "Wählen Sie ein Plugin aus der Liste, um es zu konfigurieren."`, `"configDisabledInfo": "Diese Instanz ist deaktiviert und wird nicht ausgeführt."`, `"configNoSchema": "Dieses Plugin hat keine Konfigurationsoptionen."`, `"configRemove": "Entfernen"`.

Also remove now-dead keys (Task 8 cleans the rest): none yet.

- [ ] **Step 3: Implement components**

`PipelineOverviewStrip.tsx`:

```tsx
import { Badge, Group, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { LocalInstance } from './dndUtils';

type Props = {
  instances: LocalInstance[];
  dirty: boolean;
};

export function PipelineOverviewStrip({ instances, dirty }: Props) {
  const { t } = useTranslation('pipeline');
  const enabled = instances.filter((i) => i.enabled).length;
  return (
    <Group gap="md" data-testid="overview-strip">
      <Text size="sm" c="dimmed">{t('overviewTotal', { count: instances.length })}</Text>
      <Text size="sm" c="dimmed">{t('overviewEnabled', { count: enabled })}</Text>
      <Text size="sm" c="dimmed">{t('overviewDisabled', { count: instances.length - enabled })}</Text>
      {dirty ? <Badge color="orange" variant="light">{t('overviewDirty')}</Badge> : null}
    </Group>
  );
}
```

`PluginConfigPanel.tsx`:

```tsx
import { Alert, Badge, Button, Group, Stack, Text, Title } from '@mantine/core';
import { IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { JsonSchemaForm, type JsonSchema } from '../../components/JsonSchemaForm';
import type { PluginInfo } from '../../api/types';
import type { LocalInstance } from './dndUtils';

type Props = {
  instance: LocalInstance | null;
  plugin: PluginInfo | undefined;
  onChange: (next: Record<string, unknown>) => void;
  onRemove: () => void;
};

export function PluginConfigPanel({ instance, plugin, onChange, onRemove }: Props) {
  const { t } = useTranslation('pipeline');
  if (!instance) {
    return (
      <Text c="dimmed" data-testid="config-panel" ta="center" py="xl">
        {t('configSelectPlugin')}
      </Text>
    );
  }
  const schema = (plugin?.manifest?.config_schema as JsonSchema | undefined) ?? null;
  return (
    <Stack gap="md" data-testid="config-panel">
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={4}>{instance.name}</Title>
          {plugin ? <Badge size="sm" variant="light">v{plugin.version}</Badge> : null}
        </Group>
        <Button
          variant="light"
          color="red"
          leftSection={<IconTrash size={14} />}
          onClick={onRemove}
        >
          {t('configRemove')}
        </Button>
      </Group>
      {!instance.enabled ? (
        <Alert color="yellow">{t('configDisabledInfo')}</Alert>
      ) : null}
      {schema ? (
        <JsonSchemaForm
          schema={schema}
          value={instance.configuration}
          onChange={(next) => onChange((next ?? {}) as Record<string, unknown>)}
        />
      ) : (
        <Text c="dimmed" size="sm">{t('configNoSchema')}</Text>
      )}
    </Stack>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `npm run test -- PipelineOverviewStrip PluginConfigPanel`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/pipeline/PipelineOverviewStrip.tsx frontend/src/features/pipeline/PipelineOverviewStrip.test.tsx frontend/src/features/pipeline/PluginConfigPanel.tsx frontend/src/features/pipeline/PluginConfigPanel.test.tsx frontend/public/locales/en/pipeline.json frontend/public/locales/de/pipeline.json
git commit -m "feat(frontend): pipeline overview strip + plugin config panel"
```

---

### Task 7: Frontend — `PluginList` (master list with switches, add, registry)

**Files:**
- Create: `frontend/src/features/pipeline/PluginList.tsx`
- Create: `frontend/src/features/pipeline/PluginList.test.tsx`

**Interfaces:**
- Consumes: `LocalInstance`, `addInstance` from `dndUtils`; `useUpdatePluginEnabled`, `usePatchPipelineInstance` (Task 5); `ConfirmModal`; `getPluginIcon`.
- Produces: `<PluginList instances={LocalInstance[]} plugins={PluginInfo[]} selectedClientId={string | null} onSelect={(clientId: string) => void} onToggleEnabled={(clientId: string, next: boolean) => void} onAdd={(pluginId: string) => void} onReorderDragEnd={(event: DragEndEvent) => void} />` — rendered inside `DndContext` + `SortableContext` provided by `PipelinePage` (Task 8 wires it; but for testability PluginList owns its `DndContext` internally wrapping the SortableContext, like PipelineWorkspace did with its droppable — decide: PluginList renders `DndContext` itself so it is self-contained; PipelinePage must NOT wrap another DndContext around it).

RESOLVED: `PluginList` owns `DndContext` (sensors: PointerSensor with `activationConstraint: { distance: 4 }`) and `SortableContext` with `verticalListSortingStrategy` over `instances.map(i => i.clientId)`. Callback `onReorderDragEnd` receives the raw DragEndEvent; PipelinePage applies `applyDragEnd`.

- [ ] **Step 1: Write failing tests**

`PluginList.test.tsx` (pattern: `PipelinePage.test.tsx` for router-free render — but PluginList needs no router; pattern from `PluginRegistryPanel.test.tsx`):

```tsx
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { notifications, Notifications } from '@mantine/notifications';
import type { ReactNode } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { PluginList } from './PluginList';
import type { LocalInstance } from './dndUtils';
import type { PluginInfo } from '../../api/types';

const instances: LocalInstance[] = [
  { id: 1, position: 0, plugin_id: 'upper', name: 'Upper', configuration: {}, enabled: true, clientId: 'upper-0' },
  { id: 2, position: 1, plugin_id: 'lower', name: 'Lower', configuration: {}, enabled: false, clientId: 'lower-1' },
];

const plugins: PluginInfo[] = [
  { id: 'upper', name: 'Upper', version: '1.0.0', enabled: true,
    manifest: { extension_point: 'pipeline_module' }, used_by_feed_sources: 0 },
  { id: 'lower', name: 'Lower', version: '1.0.0', enabled: true,
    manifest: { extension_point: 'pipeline_module' }, used_by_feed_sources: 3 },
  { id: 'fresh', name: 'Fresh', version: '1.0.0', enabled: true,
    manifest: { extension_point: 'pipeline_module' }, used_by_feed_sources: 0 },
];

beforeAll(async () => {
  await i18n.loadNamespaces(['pipeline', 'common']);
});

beforeEach(() => {
  stubFetch(() => jsonResponse({}));
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

function renderAt(overrides?: Partial<Parameters<typeof PluginList>[0]>) {
  const props = {
    instances,
    plugins,
    selectedClientId: 'upper-0',
    onSelect: vi.fn(),
    onToggleEnabled: vi.fn(),
    onAdd: vi.fn(),
    onReorderDragEnd: vi.fn(),
    ...overrides,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(
    <>
      <Notifications position="top-right" limit={1} />
      <PluginList {...props} />
    </>,
    { wrapper: Wrapper },
  );
}

describe('PluginList', () => {
  it('renders ordered instance rows with switches and drag handles', () => {
    renderAt();
    expect(screen.getByTestId('plugin-row-upper-0')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-row-lower-1')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-toggle-upper-0')).toBeInTheDocument();
    expect(screen.getByTestId('drag-handle-upper-0')).toBeInTheDocument();
  });

  it('highlights the selected row', () => {
    renderAt();
    const row = screen.getByTestId('plugin-row-upper-0');
    expect(row).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('plugin-row-lower-1')).toHaveAttribute('data-selected', 'false');
  });

  it('calls onToggleEnabled when the per-instance switch flips', async () => {
    const user = userEvent.setup();
    const onToggleEnabled = vi.fn();
    renderAt({ onToggleEnabled });
    await user.click(screen.getByTestId('plugin-toggle-lower-1'));
    expect(onToggleEnabled).toHaveBeenCalledWith('lower-1', true);
  });

  it('lists only pipeline_module plugins not already in the pipeline under add-from-registry', () => {
    renderAt();
    expect(screen.getByTestId('add-plugin-fresh')).toBeInTheDocument();
    expect(screen.queryByTestId('add-plugin-upper')).not.toBeInTheDocument();
  });

  it('calls onAdd with the plugin id', async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    renderAt({ onAdd });
    await user.click(screen.getByTestId('add-plugin-fresh'));
    expect(onAdd).toHaveBeenCalledWith('fresh');
  });

  it('opens ConfirmModal when disabling an in-use plugin via registry switch', async () => {
    const user = userEvent.setup();
    renderAt();
    await user.click(screen.getByTestId('registry-toggle-lower'));
    expect(await screen.findByText(/type 3 to confirm/i)).toBeInTheDocument();
  });

  it('registry toggle shows disableBlocked toast on 409', async () => {
    const user = userEvent.setup();
    stubFetch((url, init) => {
      if (url === '/plugins/lower/enabled' && init?.method === 'PUT') {
        return jsonResponse({ detail: 'plugin in use by 3 feed sources' }, 409);
      }
      return jsonResponse({});
    });
    renderAt();
    await user.click(screen.getByTestId('registry-toggle-lower'));
    await user.type(screen.getByLabelText(/type 3 to confirm/i), '3');
    await user.click(await screen.findByRole('button', { name: /disable/i }));
    expect(await screen.findByText(/in use by 3 feed sources/i)).toBeInTheDocument();
  });
});
```

(`typeToConfirm` modal text comes from `ConfirmModal`'s type-to-confirm label — check its i18n usage and adjust the matcher.)

- [ ] **Step 2: Add i18n keys**

`en/pipeline.json` add (flat): `"addFromRegistry": "Add from registry"`, `"registry": "Registry"`, `"registryToggleHelp": "Global switch — affects every client and feed source."`, `"instances": "Plugin instances"`, `"addPlugin": "Add {{name}}"`, `"registryInUse": "Used by {{count}} feed sources"` (already have `inUse` — reuse `inUse`).
`de/pipeline.json` add: `"addFromRegistry": "Aus der Registry hinzufügen"`, `"registry": "Registry"`, `"registryToggleHelp": "Globaler Schalter — betrifft alle Mandanten und Feed-Quellen."`, `"instances": "Plugin-Instanzen"`, `"addPlugin": "{{name}} hinzufügen"`.

- [ ] **Step 3: Implement PluginList**

```tsx
import { ActionIcon, Badge, Box, Card, Group, Stack, Switch, Text, UnstyledButton } from '@mantine/core';
import { IconGripVertical } from '@tabler/icons-react';
import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { usePatchPipelineInstance, useUpdatePluginEnabled } from '../../api/hooks';
import { notifyError, notifyMutationError } from '../../app/notifications';
import { ConfirmModal } from '../../components/ConfirmModal';
import { getPluginIcon } from '../../components/PluginIconMap';
import type { PluginInfo } from '../../api/types';
import type { LocalInstance } from './dndUtils';

type Props = {
  instances: LocalInstance[];
  plugins: PluginInfo[];
  selectedClientId: string | null;
  onSelect: (clientId: string) => void;
  onToggleEnabled: (clientId: string, next: boolean) => void;
  onAdd: (pluginId: string) => void;
  onReorderDragEnd: (event: DragEndEvent) => void;
  feedSourceId: number | string;
};

export function PluginList({
  instances, plugins, selectedClientId, onSelect, onToggleEnabled, onAdd,
  onReorderDragEnd, feedSourceId,
}: Props) {
  const { t } = useTranslation('pipeline');
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  return (
    <Stack gap="md" data-testid="plugin-list">
      <Text fw={600} size="sm">{t('instances')}</Text>
      <DndContext sensors={sensors} onDragEnd={onReorderDragEnd}>
        <SortableContext items={instances.map((i) => i.clientId)} strategy={verticalListSortingStrategy}>
          {instances.map((instance) => (
            <InstanceRow
              key={instance.clientId}
              instance={instance}
              plugin={plugins.find((p) => p.id === instance.plugin_id)}
              selected={instance.clientId === selectedClientId}
              onSelect={() => onSelect(instance.clientId)}
              onToggleEnabled={(next) => onToggleEnabled(instance.clientId, next)}
            />
          ))}
        </SortableContext>
      </DndContext>
      <AddFromRegistry instances={instances} plugins={plugins} onAdd={onAdd} />
      <RegistrySection plugins={plugins} feedSourceId={feedSourceId} />
    </Stack>
  );
}

function InstanceRow({
  instance, plugin, selected, onSelect, onToggleEnabled,
}: {
  instance: LocalInstance;
  plugin: PluginInfo | undefined;
  selected: boolean;
  onSelect: () => void;
  onToggleEnabled: (next: boolean) => void;
}) {
  const { t } = useTranslation('pipeline');
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: instance.clientId,
    data: { source: 'workspace' },
  });
  const Icon = getPluginIcon(plugin?.manifest?.frontend?.icon);
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 };
  return (
    <Card
      ref={setNodeRef}
      style={style}
      withBorder
      p="xs"
      data-testid={`plugin-row-${instance.clientId}`}
      data-selected={selected}
      onClick={onSelect}
    >
      <Group gap="xs" wrap="nowrap">
        <ActionIcon
          variant="subtle"
          {...attributes}
          {...listeners}
          aria-label={t('dragHandle')}
          data-testid={`drag-handle-${instance.clientId}`}
        >
          <IconGripVertical size={16} />
        </ActionIcon>
        <Icon size={16} />
        <Text size="sm" fw={selected ? 600 : 400} style={{ flex: 1 }}>{instance.name}</Text>
        <Switch
          checked={instance.enabled}
          onChange={(e) => onToggleEnabled(e.currentTarget.checked)}
          data-testid={`plugin-toggle-${instance.clientId}`}
        />
      </Group>
    </Card>
  );
}

function AddFromRegistry({
  instances, plugins, onAdd,
}: {
  instances: LocalInstance[];
  plugins: PluginInfo[];
  onAdd: (pluginId: string) => void;
}) {
  const { t } = useTranslation('pipeline');
  const pipelineModules = plugins.filter(
    (p) => p.manifest?.extension_point === 'pipeline_module' && p.enabled,
  );
  const present = new Set(instances.map((i) => i.plugin_id));
  const available = pipelineModules.filter((p) => !present.has(p.id));
  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed" tt="uppercase">{t('addFromRegistry')}</Text>
      {available.length === 0 ? (
        <Text size="xs" c="dimmed">{t('paletteEmpty')}</Text>
      ) : (
        available.map((plugin) => {
          const Icon = getPluginIcon(plugin.manifest?.frontend?.icon);
          return (
            <UnstyledButton
              key={plugin.id}
              onClick={() => onAdd(plugin.id)}
              data-testid={`add-plugin-${plugin.id}`}
            >
              <Group gap="xs" wrap="nowrap">
                <Icon size={14} />
                <Text size="sm">{t('addPlugin', { name: plugin.name })}</Text>
              </Group>
            </UnstyledButton>
          );
        })
      )}
    </Stack>
  );
}

function RegistrySection({
  plugins, feedSourceId,
}: {
  plugins: PluginInfo[];
  feedSourceId: number | string;
}) {
  const { t } = useTranslation('pipeline');
  const [pendingToggle, setPendingToggle] = useState<PluginInfo | null>(null);
  const toggleEnabled = useUpdatePluginEnabled();
  // PATCH hook is used by InstanceRow's parent (PipelinePage) — this section only
  // handles the GLOBAL registry toggle.

  function mutateToggle(plugin: PluginInfo, enabled: boolean) {
    toggleEnabled.mutate(
      { id: plugin.id, enabled },
      {
        onError: (error) => {
          if (error instanceof ApiError && error.status === 409) {
            notifyError(t('disableBlocked', { count: plugin.used_by_feed_sources }));
          } else {
            notifyMutationError(error, t('disableFailed'));
          }
        },
      },
    );
  }

  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed" tt="uppercase">{t('registry')}</Text>
      <Text size="xs" c="dimmed">{t('registryToggleHelp')}</Text>
      {plugins.map((plugin) => {
        const Icon = getPluginIcon(plugin.manifest?.frontend?.icon);
        return (
          <Group key={plugin.id} justify="space-between" wrap="nowrap">
            <Group gap="xs" wrap="nowrap">
              <Icon size={14} />
              <Stack gap={0}>
                <Text size="sm">{plugin.name}</Text>
                <Group gap={4}>
                  <Badge size="xs" variant="light">v{plugin.version}</Badge>
                  {plugin.used_by_feed_sources > 0 ? (
                    <Badge size="xs" color="orange" variant="light">
                      {t('inUse', { count: plugin.used_by_feed_sources })}
                    </Badge>
                  ) : null}
                </Group>
              </Stack>
            </Group>
            <Switch
              checked={plugin.enabled}
              onChange={(event) => {
                const next = event.currentTarget.checked;
                if (!next && plugin.used_by_feed_sources > 0) {
                  setPendingToggle(plugin);
                  return;
                }
                mutateToggle(plugin, next);
              }}
              data-testid={`registry-toggle-${plugin.id}`}
            />
          </Group>
        );
      })}
      <ConfirmModal
        opened={Boolean(pendingToggle)}
        onClose={() => setPendingToggle(null)}
        title={t('disableConfirmTitle', { name: pendingToggle?.name ?? '' })}
        message={t('disableConfirmBody', { name: pendingToggle?.name ?? '' })}
        confirmLabel={t('disable')}
        danger
        typeToConfirm={pendingToggle ? String(pendingToggle.used_by_feed_sources) : undefined}
        onConfirm={() => {
          if (!pendingToggle) return;
          const plugin = pendingToggle;
          setPendingToggle(null);
          mutateToggle(plugin, false);
        }}
      />
    </Stack>
  );
}
```

Note: `Box` import may be unused — drop it. Verify `usePatchPipelineInstance` is NOT needed inside PluginList (the per-instance switch calls the `onToggleEnabled` prop; PipelinePage performs the optimistic flip + PATCH + rollback).

- [ ] **Step 4: Run tests**

Run: `npm run test -- PluginList`
Expected: pass. If `renderAt`'s type helper `Parameters<typeof PluginList>[0]` causes TS issues in the test, type props explicitly.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/pipeline/PluginList.tsx frontend/src/features/pipeline/PluginList.test.tsx frontend/public/locales/en/pipeline.json frontend/public/locales/de/pipeline.json
git commit -m "feat(frontend): plugin master list with switches, add-from-registry, registry toggles"
```

---

### Task 8: Frontend — rewire `PipelinePage`, delete old components

**Files:**
- Modify: `frontend/src/features/pipeline/PipelinePage.tsx` (full rewrite)
- Delete: `frontend/src/features/pipeline/PluginPalette.tsx`, `PluginPalette.test.tsx`, `PipelineWorkspace.tsx` (no test), `PipelineInstanceCard.tsx`, `PipelineInstanceCard.test.tsx`, `PluginRegistryPanel.tsx`, `PluginRegistryPanel.test.tsx`, `registryPanelState.ts`
- Test: `frontend/src/features/pipeline/PipelinePage.test.tsx` (rewrite)

**Interfaces:**
- Consumes: `PluginList` (Task 7), `PluginConfigPanel` + `PipelineOverviewStrip` (Task 6), `usePatchPipelineInstance` (Task 5), `addInstance`/`applyDragEnd`/`removeInstance`/`isInstancesEqual` from `dndUtils`.
- Produces: final page. Route unchanged (`clients/:clientId/feeds/:feedSourceId/pipeline`).

- [ ] **Step 1: Rewrite PipelinePage.test.tsx**

Keep the router-based `renderAt` harness (it tests `useBlocker`). Rewrite the test body:

```tsx
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider, Link } from 'react-router';
import { notifications, Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { PipelinePage } from './PipelinePage';
import { queryClient } from '../../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

const plugin = {
  id: 'upper',
  name: 'Upper',
  version: '1.0.0',
  enabled: true,
  manifest: {
    extension_point: 'pipeline_module',
    config_schema: { type: 'object', properties: { suffix: { type: 'string' } } },
  },
  used_by_feed_sources: 0,
};

const serverDoc = {
  instances: [
    { id: 11, position: 0, plugin_id: 'upper', name: 'Upper',
      configuration: { suffix: '!' }, enabled: true },
  ],
};

beforeAll(async () => {
  await i18n.loadNamespaces(['pipeline', 'common']);
});

beforeEach(() => {
  queryClient.clear();
  notifications.clean();
  stubFetch((url) => {
    if (url === '/plugins') return jsonResponse([plugin]);
    if (url === '/feed-sources/1/pipeline') return jsonResponse(serverDoc);
    return jsonResponse({});
  });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

function renderAt(initialEntry = '/clients/1/feeds/1/pipeline') {
  // ... identical router/QueryClient harness as the current file (path
  // clients/:clientId/feeds/:feedSourceId/pipeline, products sibling route,
  // <Notifications/>) — copy it verbatim from the current PipelinePage.test.tsx ...
}

describe('PipelinePage', () => {
  it('renders title, overview strip and instance rows', async () => {
    renderAt();
    expect(await screen.findByRole('heading', { name: /pipeline/i })).toBeInTheDocument();
    expect(screen.getByTestId('overview-strip')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-row-upper-0')).toBeInTheDocument(); // clientId = `upper-0`
  });

  it('selects first instance by default and shows its config form', async () => {
    renderAt();
    await screen.findByTestId('config-panel');
    expect(await screen.findByLabelText(/suffix/i)).toBeInTheDocument();
  });

  it('clicking a row selects it; config edits update only local state', async () => {
    const user = userEvent.setup();
    renderAt();
    const input = await screen.findByLabelText(/suffix/i);
    await user.clear(input);
    await user.type(input, '?');
    // Save enabled => dirty tracking works
    await waitFor(() => expect(screen.getByRole('button', { name: /save/i })).toBeEnabled());
  });

  it('flipping the per-instance switch PATCHes immediately and rolls back on failure', async () => {
    const user = userEvent.setup();
    let patchFailed = false;
    stubFetch((url, init) => {
      if (url === '/plugins') return jsonResponse([plugin]);
      if (url === '/feed-sources/1/pipeline') return jsonResponse(serverDoc);
      if (url === '/feed-sources/1/pipeline/instances/11' && init?.method === 'PATCH') {
        patchFailed = true;
        return jsonResponse({ detail: 'boom' }, 500);
      }
      return jsonResponse({});
    });
    renderAt();
    await screen.findByTestId('plugin-toggle-upper-0');
    await user.click(screen.getByTestId('plugin-toggle-upper-0'));
    await waitFor(() => expect(patchFailed).toBe(true));
    // rolled back to checked after failure
    await waitFor(() => expect(screen.getByTestId('plugin-toggle-upper-0')).toBeChecked());
  });

  it('add from registry marks the page dirty', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/plugins') return jsonResponse([plugin, { ...plugin, id: 'fresh', name: 'Fresh' }]);
      if (url === '/feed-sources/1/pipeline') return jsonResponse(serverDoc);
      return jsonResponse({});
    });
    renderAt();
    await user.click(await screen.findByTestId('add-plugin-fresh'));
    await waitFor(() => expect(screen.getByRole('button', { name: /save/i })).toBeEnabled());
  });

  it('Save sends PUT with ids and reordering applies after drag', async () => {
    // two server instances; drag row 0 handle onto row 1 using the pointer
    // sequence pattern from the current test file, then Save; assert the
    // captured PUT body has the reordered instances with stable ids.
    // (Copy the pointer-drag mechanics from the existing
    // 'dragging a palette plugin onto the workspace' test, adjusted to
    // drag-handle → plugin-row targets.)
  });

  it('remove button deletes the instance locally and enables Save', async () => {
    const user = userEvent.setup();
    renderAt();
    await user.click(await screen.findByRole('button', { name: /remove/i }));
    expect(screen.queryByTestId('plugin-row-upper-0')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /save/i })).toBeEnabled());
  });

  it('useBlocker prompts on navigation when dirty', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/plugins') return jsonResponse([plugin]);
      if (url === '/feed-sources/1/pipeline') return jsonResponse(serverDoc);
      return jsonResponse({});
    });
    renderAt();
    const input = await screen.findByLabelText(/suffix/i);
    await user.clear(input);
    await user.type(input, '?');
    await user.click(screen.getByRole('link', { name: /go to products/i }));
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
  });
});
```

Write out the drag test fully (do not leave a comment-only step): simulate the existing pointer pattern on `drag-handle-upper-0` → `plugin-row-lower-1` with mocked `getBoundingClientRect` (rows stacked: first row {left:0,top:0,w:300,h:48}, second {left:0,top:60,w:300,h:48}), assert order via `onReorderDragEnd`-driven state: after drag, first row shows the second instance's name; capture the PUT on Save with stubFetch and assert `instances[0].id === 12` (or whichever got dragged where). Update `serverDoc` for this test to two instances with ids 11 and 12.

- [ ] **Step 2: Rewrite PipelinePage.tsx**

```tsx
import { Grid, Group, Button, Stack, Title } from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import { useBlocker, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useFeedSourcePipeline, usePatchPipelineInstance, usePlugins, useSavePipeline } from '../../api/hooks';
import { ApiError } from '../../api/client';
import type { PipelineDoc, PipelineInstance } from '../../api/types';
import { ErrorState, LoadingState } from '../../components/StateViews';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { PluginConfigPanel } from './PluginConfigPanel';
import { PluginList } from './PluginList';
import { PipelineOverviewStrip } from './PipelineOverviewStrip';
import { addInstance, applyDragEnd, isInstancesEqual, removeInstance, type LocalInstance } from './dndUtils';

function toLocal(instances: PipelineInstance[]): LocalInstance[] {
  return instances.map((instance, index) => ({
    ...instance,
    clientId: `${instance.plugin_id}-${instance.id ?? `new-${index}`}`,
  }));
}

function toServer(instances: LocalInstance[]): PipelineDoc {
  return {
    instances: instances.map(({ clientId: _clientId, ...rest }, index) => ({
      ...rest,
      position: index,
    })),
  };
}

export function PipelinePage() {
  const { t } = useTranslation('pipeline');
  const { t: tCommon } = useTranslation('common');
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const pipeline = useFeedSourcePipeline(id);
  const savePipeline = useSavePipeline(id);
  const patchInstance = usePatchPipelineInstance(id);
  const { data: plugins } = usePlugins();

  const [local, setLocal] = useState<LocalInstance[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);

  useEffect(() => {
    if (pipeline.data && !hydrated) {
      setLocal(toLocal(pipeline.data.instances));
      setHydrated(true);
    }
  }, [pipeline.data, hydrated]);

  const serverSnapshot: LocalInstance[] = useMemo(
    () => (pipeline.data ? toLocal(pipeline.data.instances) : []),
    [pipeline.data],
  );

  const dirty = !isInstancesEqual(local, serverSnapshot);
  const selected = local.find((i) => i.clientId === selectedClientId) ?? local[0] ?? null;

  useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty) return false;
    if (currentLocation.pathname === nextLocation.pathname) return false;
    return !window.confirm(t('unsavedChanges'));
  });

  async function onSave() {
    try {
      await savePipeline.mutateAsync(toServer(local));
      notifySuccess(t('saved'));
      setHydrated(false);
    } catch (error) {
      notifyApiError(
        error,
        t('saveFailed'),
        error instanceof ApiError && error.errors && error.errors.length > 0
          ? t('saveFailedWithErrors', { errors: error.errors.join('; ') })
          : undefined,
      );
    }
  }

  function onReset() {
    if (!pipeline.data) return;
    setLocal(toLocal(pipeline.data.instances));
    setHydrated(true);
  }

  function onToggleEnabled(clientId: string, next: boolean) {
    const instance = local.find((i) => i.clientId === clientId);
    if (!instance || instance.id === null) {
      // unsaved instance: flip locally only (persisted with Save)
      setLocal((prev) => prev.map((i) => (i.clientId === clientId ? { ...i, enabled: next } : i)));
      return;
    }
    const before = local;
    setLocal((prev) => prev.map((i) => (i.clientId === clientId ? { ...i, enabled: next } : i)));
    patchInstance.mutate(
      { instanceId: instance.id, enabled: next },
      {
        onError: (error) => {
          setLocal(before); // rollback
          notifyApiError(error, t('toggleFailed'));
        },
      },
    );
  }

  function onAdd(pluginId: string) {
    const plugin = (plugins ?? []).find((p) => p.id === pluginId);
    if (!plugin) return;
    setLocal((prev) => addInstance(prev, { id: plugin.id, name: plugin.name }));
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={3}>{t('title')}</Title>
        <Group>
          <Button variant="default" onClick={onReset} disabled={!dirty}>
            {tCommon('actions.cancel')}
          </Button>
          <Button onClick={onSave} loading={savePipeline.isPending} disabled={!dirty}>
            {tCommon('actions.save')}
          </Button>
        </Group>
      </Group>
      <PipelineOverviewStrip instances={local} dirty={dirty} />
      <Grid>
        <Grid.Col span={4}>
          <PluginList
            instances={local}
            plugins={plugins ?? []}
            selectedClientId={selected?.clientId ?? null}
            onSelect={setSelectedClientId}
            onToggleEnabled={onToggleEnabled}
            onAdd={onAdd}
            onReorderDragEnd={(event) => {
              const next = applyDragEnd(local, event);
              if (next) setLocal(next);
            }}
            feedSourceId={id}
          />
        </Grid.Col>
        <Grid.Col span={8}>
          <PluginConfigPanel
            instance={selected}
            plugin={plugins?.find((p) => p.id === selected?.plugin_id)}
            onChange={(next) =>
              selected && setLocal((prev) => prev.map((i) =>
                i.clientId === selected.clientId ? { ...i, configuration: next } : i))
            }
            onRemove={() =>
              selected && setLocal((prev) => removeInstance(prev, selected.clientId))
            }
          />
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
```

Notes:
- `DndContext` is now owned by `PluginList` (Task 7) — PipelinePage no longer wraps one.
- i18n key `toggleFailed` must be added to both locale files in this task: en `"toggleFailed": "Could not change plugin state."`, de `"toggleFailed": "Plugin-Status konnte nicht geändert werden."`.
- Delete the files listed above (`git rm`), including `registryPanelState.ts` and all their tests. Remove dead i18n keys from both locale files: `palette`, `dragToAdd`, `emptyWorkspace`, `registryPanel`, `registryHelp` (keep `paletteEmpty` — reused in AddFromRegistry; rename it to `noModulesAvailable` and update usage, or keep the key; keeping `paletteEmpty` is fine but rename in a follow-up — plan: KEEP `paletteEmpty` as-is to avoid churn).
  Keep: `title`, `dragHandle`, `remove` (used by ConfirmModal? no — configRemove replaces it in panel; `remove` still used? PluginConfigPanel uses `configRemove` — remove the old `remove` key if unused elsewhere in the namespace; grep before deleting), `unsavedChanges`, `inUse`, `disableConfirmTitle`, `disableConfirmBody`, `disable`, `disableBlocked`, `disableFailed`, `saved`, `saveFailed`, `saveFailedWithErrors`.
  Final deletion set (both locales): `palette`, `dragToAdd`, `emptyWorkspace`, `registryPanel`, `registryHelp`, and `remove` (after grep confirms nothing else uses it).
- The old test's `beforeEach` stubFetch must also answer `/feed-sources/1/pipeline` GETs after PATCH failures (invalidations) — the default stub already does.

- [ ] **Step 3: Run all pipeline tests + typecheck + build**

Run: `npm run test -- pipeline && npm run typecheck && npm run build`
Expected: pass. Also run the full suite: `npm run test` (other features must be unaffected).

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src/features/pipeline frontend/public/locales
git commit -m "feat(frontend): pipeline page master-detail layout"
```

---

### Task 9: Docs update + final verification

**Files:**
- Modify: `backend/docs/api.md`
- Modify: `backend/docs/data-model.md`
- Modify: `backend/docs/architecture.md`
- Modify: `frontend/docs/architecture.md`

**Interfaces:**
- Consumes: everything from Tasks 1-8.
- Produces: docs consistent with the new behavior (AGENTS.md requirement: same commit as behavior change — backend/docs and frontend/docs updates land with their respective feature commits in Tasks 2-4 would be ideal; this task exists as the final sweep to reconcile everything and is the commit that satisfies the rule for the frontend page rework since docs can also be updated in a single final commit per repo practice of feature-docs-together).

- [ ] **Step 1: Update backend docs**

Read each doc, find the pipeline endpoints / data model sections, and update:

`backend/docs/api.md` — in the endpoints reference:
- GET pipeline: instance objects now include `id`, `enabled`.
- PUT pipeline: request accepts optional `id` per instance; upsert semantics (id present = update, absent = insert, missing = delete); response includes `id`/`enabled`.
- New: `PATCH /feed-sources/{id}/pipeline/instances/{instance_id}` — `{"enabled": bool}` → `{"id", "enabled"}`; 404s.

`backend/docs/data-model.md` — `module_instances` table: add `enabled` boolean (default true), purpose: per-feed-source per-instance enable, excluded from config bundle when false; note the `definition` JSONB mirrors rows.

`backend/docs/architecture.md` — Module Runner stage: instances with `enabled=false` are skipped (not in the config bundle → not executed, and config_hash changes so the next run reprocesses).

- [ ] **Step 2: Update frontend docs**

`frontend/docs/architecture.md` — pipeline page section: describe master–detail layout (PluginList left / PluginConfigPanel right / PipelineOverviewStrip top), per-instance enable via PATCH (immediate persist, optimistic with rollback), Save covers reorder/add/remove/config edits, dnd-kit reorder lives in PluginList, registry toggles global.

- [ ] **Step 3: Full verification**

Run backend: `uv run pytest -n auto && uv run ruff check . && uv run mypy .`
Run frontend: `npm run test && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/docs frontend/docs
git commit -m "docs: pipeline master-detail API, enabled column, page architecture"
```

---

## Self-Review notes (already applied)

- Spec coverage: schema (T1), GET/PUT + upsert (T2), PATCH (T3), bundle exclusion (T4), frontend types/hook (T5), overview strip + config panel (T6), master list (T7), page rewire + deletions (T8), docs (T9). Registry toggles in left list: T7. Immediate-persist switch: T5+T8. Dirty/save semantics unchanged: T8. i18n both locales: T6/T7/T8.
- Type consistency: `LocalInstance = PipelineInstance & { clientId }` with `id: number | null`, `enabled: boolean` everywhere; `usePatchPipelineInstance(feedSourceId)` takes `{ instanceId, enabled }`; PluginList props match PipelinePage call site; testids consistent (`plugin-row-*`, `plugin-toggle-*` per-instance vs `registry-toggle-*` global vs `add-plugin-*`).
- Known intentional deviations: (a) `paletteEmpty` i18n key reused for empty add-from-registry (avoiding churn); (b) PluginList owns DndContext (self-contained, testable); (c) per-instance PATCH rollback replaces the whole `local` array snapshot (simple, correct since single-flight toggles).
