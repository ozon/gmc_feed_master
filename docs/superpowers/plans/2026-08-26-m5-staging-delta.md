# M5 Staging + Delta Mechanics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert the staging stage between field mapping and the plugin pipeline: persist staged state per feed source, detect deltas via `content_hash`/`config_hash`, mark removals/reactivations, reduce downstream input to the changed set, and purge expired rows daily.

**Architecture:** New `app/staging/` package with focused modules (`hashing`, `config_resolver`, `delta`, `persistence`, `purge`). The step wrapper `StagingStep` lives in `app/pipeline/steps.py` next to `IngestStep`/`MappingStep` (established convention, avoids a circular import). Pure logic (hashing, merge, classification) is separated from persistence so the matrix is unit-testable; DB behavior is covered by PostgreSQL integration tests via the existing `isolated_database_url` fixture.

**Tech Stack:** FastAPI backend, SQLAlchemy 2.0.43 async + asyncpg, Alembic 1.16.4, APScheduler 3.11.3, pytest 8.4.2 + pytest-asyncio 1.1.0, uv. **No new dependencies.**

**Design doc:** `docs/superpowers/specs/2026-08-26-m5-staging-delta-design.md` (implements spec §4, §3, §5.3)

## Global Constraints

- Work in `backend/` only; frontend untouched this milestone.
- Exact pins locked (see `docs/decisions.md`): SQLAlchemy 2.0.43, asyncpg 0.30.0, Alembic 1.16.4, APScheduler 3.11.3, pytest 8.4.2, pytest-asyncio 1.1.0.
- Integration tests require `TEST_DATABASE_URL` (`postgresql+asyncpg://`); they fail without it by design. Start Postgres first: `docker compose up -d postgres`. Unit tests must not need PostgreSQL.
- Run commands from `backend/`: `uv run pytest ...`.
- Async tests use explicit `@pytest.mark.asyncio` (existing convention).
- Spec §4 is binding: unchanged products get "**only** update `last_seen_at`"; removed products are never deleted at run time; history entries only on content change (approved decision 2026-08-26).
- `_`-prefixed keys are stripped before hashing but stay inside stored snapshots (`raw_data`, history).
- Match repo style: minimal comments, `from __future__ import annotations`.
- Commit after every passing task (`feat:`/`test:` prefixes per repo history).
- Purge job id MUST be `system-staging-purge` — outside the `feed-source-{id}` namespace (decision recorded in `docs/decisions.md`).

---

### Task 1: Canonical hashing module

**Files:**
- Create: `backend/app/staging/__init__.py`
- Create: `backend/app/staging/hashing.py`
- Test: `backend/tests/test_staging_hashing.py`

**Interfaces:**
- Consumes: stdlib only.
- Produces: `strip_derived(value: Any) -> Any`, `canonical_json(value: Any) -> str`, `content_hash(value: dict[str, Any]) -> str` (SHA-256 hexdigest). All later tasks import from `app.staging.hashing`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_staging_hashing.py`:

```python
from app.staging.hashing import canonical_json, content_hash, strip_derived


class TestStripDerived:
    def test_removes_top_level_underscore_keys(self):
        assert strip_derived({"id": "1", "_prov": "x"}) == {"id": "1"}

    def test_removes_nested_and_inside_lists(self):
        value = {
            "shipping": [{"country": "US", "_i": "x"}, {"country": "DE"}],
            "meta": {"keep": 1, "_drop": 2},
        }
        assert strip_derived(value) == {
            "shipping": [{"country": "US"}, {"country": "DE"}],
            "meta": {"keep": 1},
        }

    def test_leaves_scalars_untouched(self):
        assert strip_derived("x") == "x"
        assert strip_derived(42) == 42
        assert strip_derived(None) is None


class TestCanonicalJson:
    def test_key_order_independent(self):
        assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})

    def test_nested_keys_sorted(self):
        assert canonical_json({"o": {"y": 1, "x": 2}}) == canonical_json({"o": {"x": 2, "y": 1}})

    def test_unicode_preserved_and_compact(self):
        assert canonical_json({"t": "schön"}) == '{"t":"schön"}'


class TestContentHash:
    def test_is_sha256_hexdigest(self):
        digest = content_hash({"id": "1"})
        assert len(digest) == 64
        int(digest, 16)

    def test_sidecars_do_not_change_hash(self):
        plain = {"id": "1", "title": "Shirt"}
        decorated = {**plain, "_category_provenance": "auto"}
        assert content_hash(plain) == content_hash(decorated)

    def test_content_change_changes_hash(self):
        assert content_hash({"title": "a"}) != content_hash({"title": "b"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_staging_hashing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.staging'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/staging/__init__.py` (empty file, package marker only).

Create `backend/app/staging/hashing.py`:

```python
from __future__ import annotations

import hashlib
import json
from typing import Any


def strip_derived(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_derived(item)
            for key, item in value.items()
            if not (isinstance(key, str) and key.startswith("_"))
        }
    if isinstance(value, list):
        return [strip_derived(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        strip_derived(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def content_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_staging_hashing.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add app/staging tests/test_staging_hashing.py
git commit -m "feat: canonical product hashing with derived-key stripping"
```

---

### Task 2: Three-tier scope merge (pure function)

**Files:**
- Create: `backend/app/staging/config_resolver.py`
- Test: `backend/tests/test_config_merge.py`

**Interfaces:**
- Consumes: nothing yet (pure).
- Produces: `merge_scopes(global_payload: dict, client_payload: dict | None, feed_source_payload: dict | None) -> dict` implementing spec §5.3 (per key: dicts merge recursively, everything else replaces wholesale). Task 3 builds on it — do not rename.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_config_merge.py`:

```python
from app.staging.config_resolver import merge_scopes


class TestMergeScopes:
    def test_global_only(self):
        assert merge_scopes({"a": 1}, None, None) == {"a": 1}

    def test_client_overrides_global_per_key(self):
        assert merge_scopes({"a": 1, "b": 2}, {"b": 3}, None) == {"a": 1, "b": 3}

    def test_feed_source_wins(self):
        merged = merge_scopes({"a": 1, "b": 2, "c": 3}, {"c": 30}, {"a": 10})
        assert merged == {"a": 10, "b": 2, "c": 30}

    def test_non_dict_values_replace_wholesale(self):
        assert merge_scopes({"rules": [1, 2, 3]}, {"rules": [9]}, None) == {"rules": [9]}

    def test_dict_values_merge_recursively(self):
        merged = merge_scopes(
            {"limits": {"title": 150, "desc": 5000}},
            {"limits": {"title": 100}},
            None,
        )
        assert merged == {"limits": {"title": 100, "desc": 5000}}

    def test_missing_at_specific_scope_falls_through(self):
        assert merge_scopes({"a": 1}, {}, {"b": 2}) == {"a": 1, "b": 2}

    def test_type_flip_replaces(self):
        assert merge_scopes({"a": {"nested": 1}}, {"a": "flat"}, None) == {"a": "flat"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.staging.config_resolver'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/staging/config_resolver.py`:

```python
from __future__ import annotations

from typing import Any


def _merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_scopes(
    global_payload: dict[str, Any],
    client_payload: dict[str, Any] | None,
    feed_source_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = dict(global_payload)
    if client_payload is not None:
        resolved = _merge_dicts(resolved, client_payload)
    if feed_source_payload is not None:
        resolved = _merge_dicts(resolved, feed_source_payload)
    return resolved
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_merge.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/staging/config_resolver.py tests/test_config_merge.py
git commit -m "feat: three-tier scope merge per spec 5.3"
```

---

### Task 3: Config bundle resolution from DB

**Files:**
- Modify: `backend/app/staging/config_resolver.py` (append)
- Test: `backend/tests/test_config_bundle.py`

**Interfaces:**
- Consumes: `merge_scopes` (Task 2); models `ModulePipeline`/`ModuleInstance` (`app.models.pipeline`), `Plugin`/`PluginConfig`/`PluginData` (`app.models.plugin`), `FeedSource` (`app.models.feed_source`; fields `client_id: int`, `active_pipeline_id: int | None`).
- Produces: `async def resolve_config_bundle(session, feed_source) -> dict`. Bundle shape (Task 6 hashes exactly this structure):

```python
{
    "pipeline": {"name": str, "version": str} | None,
    "instances": [
        {
            "position": int,
            "plugin": str,            # manifest["id"], falling back to Plugin.name
            "plugin_version": str,
            "instance_config": dict,
            "resolved_config": dict,
            "resolved_data": dict,
        },
    ],
}
```

Scope rules (spec §5.2): `manifest["config_scope"]` is a list; `manifest["data_scope"]` may be a list or a single string — normalize strings to one-element lists. Missing scope declarations default to `["global"]`. Only declared scopes contribute; order global → client → feed_source over `{row.key: row.payload}` maps. Payload attribute is `.config` for `PluginConfig`, `.data` for `PluginData`. Ownership filters: `client` rows must match `feed_source.client_id`, `feed_source` rows must match `feed_source.id`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_config_bundle.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.pipeline import ModuleInstance, ModulePipeline
from app.models.plugin import Plugin, PluginConfig, PluginData
from app.staging.config_resolver import resolve_config_bundle

pytestmark = pytest.mark.asyncio


async def _seed(session):
    client = Client(name="Acme")
    session.add(client)
    await session.flush()
    plugin = Plugin(
        name="labelizer",
        version="1.0.0",
        manifest={
            "id": "labelizer",
            "config_scope": ["global", "client"],
            "data_scope": "client",
        },
    )
    session.add(plugin)
    await session.flush()
    feed_source = FeedSource(client_id=client.id, name="US feed", source_format="tsv")
    session.add(feed_source)
    await session.flush()
    pipeline = ModulePipeline(
        feed_source_id=feed_source.id, name="pipe", version="1", definition={}
    )
    session.add(pipeline)
    await session.flush()
    feed_source.active_pipeline_id = pipeline.id
    instance = ModuleInstance(
        pipeline_id=pipeline.id,
        plugin_id=plugin.id,
        position=0,
        name="lbl",
        configuration={"slot": "custom_label_0"},
    )
    session.add(instance)
    session.add_all([
        PluginConfig(plugin_id=plugin.id, scope="global", key="dims",
                     config={"min_price": "10"}),
        PluginConfig(plugin_id=plugin.id, scope="client", client_id=client.id,
                     key="dims", config={"min_price": "20"}),
        PluginData(plugin_id=plugin.id, scope="client", client_id=client.id,
                   key="ids", data={"list": ["1"]}),
    ])
    await session.flush()
    return client, plugin, feed_source


async def _engine(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_bundle_resolves_instances_and_merge(isolated_database_url):
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            _, _, feed_source = await _seed(session)
        bundle = await resolve_config_bundle(session, feed_source)

    assert bundle["pipeline"] == {"name": "pipe", "version": "1"}
    entry = bundle["instances"][0]
    assert entry["position"] == 0
    assert entry["plugin"] == "labelizer"
    assert entry["plugin_version"] == "1.0.0"
    assert entry["instance_config"] == {"slot": "custom_label_0"}
    assert entry["resolved_config"] == {"min_price": "20"}
    assert entry["resolved_data"] == {"ids": {"list": ["1"]}}
    await engine.dispose()


async def test_bundle_without_active_pipeline_is_stable(isolated_database_url):
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(client_id=client.id, name="US", source_format="tsv")
            session.add(feed_source)
            await session.flush()
        bundle = await resolve_config_bundle(session, feed_source)

    assert bundle == {"pipeline": None, "instances": []}
    await engine.dispose()


async def test_client_scope_of_other_client_is_ignored(isolated_database_url):
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            _, plugin, feed_source = await _seed(session)
            other = Client(name="Other")
            session.add(other)
            await session.flush()
            session.add(PluginConfig(
                plugin_id=plugin.id, scope="client", client_id=other.id,
                key="dims", config={"min_price": "999"},
            ))
        bundle = await resolve_config_bundle(session, feed_source)

    assert bundle["instances"][0]["resolved_config"] == {"min_price": "20"}
    await engine.dispose()


async def test_undeclared_feed_source_scope_never_applies(isolated_database_url):
    engine, factory = _make(isolated_database_url)
    async with factory() as session:
        async with session.begin():
            _, plugin, feed_source = await _seed(session)
            session.add(PluginConfig(
                plugin_id=plugin.id, scope="feed_source",
                feed_source_id=feed_source.id, key="dims",
                config={"min_price": "999"},
            ))
        bundle = await resolve_config_bundle(session, feed_source)

    assert bundle["instances"][0]["resolved_config"] == {"min_price": "20"}
    await engine.dispose()
```

At the top of the file (after the imports), add the helper all tests use:

```python
def _make(url):
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
```

and delete the now-unused `_engine` coroutine. Verify the `Client` model path with `grep -rn "class Client" app/models/` and adjust the import if it differs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_bundle.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_config_bundle'`

- [ ] **Step 3: Write the implementation**

Append to `backend/app/staging/config_resolver.py`:

```python
_SCOPE_ORDER = ("global", "client", "feed_source")


def _normalize_scopes(raw: Any) -> list[str]:
    if raw is None:
        return ["global"]
    if isinstance(raw, str):
        return [raw]
    return [str(scope) for scope in raw]


def _resolve_declared(
    scopes: list[str], maps: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for scope in _SCOPE_ORDER:
        if scope not in scopes:
            continue
        resolved = _merge_dicts(resolved, maps.get(scope) or {})
    return resolved


async def resolve_config_bundle(session: Any, feed_source: Any) -> dict[str, Any]:
    from sqlalchemy import select

    from ..models.pipeline import ModuleInstance, ModulePipeline
    from ..models.plugin import Plugin, PluginConfig, PluginData

    bundle: dict[str, Any] = {"pipeline": None, "instances": []}
    if feed_source.active_pipeline_id is None:
        return bundle

    pipeline = await session.get(ModulePipeline, feed_source.active_pipeline_id)
    if pipeline is None:
        return bundle
    bundle["pipeline"] = {"name": pipeline.name, "version": pipeline.version}

    result = await session.execute(
        select(ModuleInstance)
        .where(ModuleInstance.pipeline_id == pipeline.id)
        .order_by(ModuleInstance.position)
    )
    instances = list(result.scalars())
    if not instances:
        return bundle

    plugin_result = await session.execute(
        select(Plugin).where(Plugin.id.in_([i.plugin_id for i in instances]))
    )
    plugins = {plugin.id: plugin for plugin in plugin_result.scalars()}

    configs_by_plugin: dict[int, list[Any]] = {}
    for row in (await session.execute(select(PluginConfig))).scalars():
        configs_by_plugin.setdefault(row.plugin_id, []).append(row)
    datas_by_plugin: dict[int, list[Any]] = {}
    for row in (await session.execute(select(PluginData))).scalars():
        datas_by_plugin.setdefault(row.plugin_id, []).append(row)

    def scoped_rows(rows: list[Any], attribute: str) -> dict[str, dict[str, Any]]:
        scoped: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.scope == "global":
                bucket = scoped.setdefault("global", {})
            elif row.scope == "client" and row.client_id == feed_source.client_id:
                bucket = scoped.setdefault("client", {})
            elif row.scope == "feed_source" and row.feed_source_id == feed_source.id:
                bucket = scoped.setdefault("feed_source", {})
            else:
                continue
            bucket[row.key] = getattr(row, attribute)
        return scoped

    for instance in instances:
        plugin = plugins[instance.plugin_id]
        manifest = plugin.manifest or {}
        bundle["instances"].append({
            "position": instance.position,
            "plugin": manifest.get("id") or plugin.name,
            "plugin_version": plugin.version,
            "instance_config": instance.configuration,
            "resolved_config": _resolve_declared(
                _normalize_scopes(manifest.get("config_scope")),
                scoped_rows(configs_by_plugin.get(plugin.id, []), "config"),
            ),
            "resolved_data": _resolve_declared(
                _normalize_scopes(manifest.get("data_scope")),
                scoped_rows(datas_by_plugin.get(plugin.id, []), "data"),
            ),
        })

    return bundle
```

Implementation notes:
- Function-local model imports avoid module-load cycles (same trick `SchedulerService.register_all` uses).
- Loading all `PluginConfig`/`PluginData` rows is fine at MVP scale (near-empty until M6); tighten queries later without contract changes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_merge.py tests/test_config_bundle.py -v`
Expected: PASS (11 tests; integration ones need `TEST_DATABASE_URL` per Global Constraints)

- [ ] **Step 5: Commit**

```bash
git add app/staging/config_resolver.py tests/test_config_bundle.py
git commit -m "feat: resolve output-relevant config bundle per feed source"
```

---

### Task 4: Delta classifier (pure)

**Files:**
- Create: `backend/app/staging/delta.py`
- Test: `backend/tests/test_staging_delta.py`

**Interfaces:**
- Consumes: `content_hash` (Task 1).
- Produces (exact names — Task 6 depends on them):

```python
@dataclass(frozen=True)
class StoredRow:
    pk: int
    product_id: str
    content_hash: str
    config_hash: str
    status: str                      # "active" | "removed"
    snapshot: dict[str, Any]

@dataclass(frozen=True)
class RowUpsert:
    product_id: str
    product: dict[str, Any]
    content_hash: str
    config_hash: str
    insert: bool                     # True -> INSERT, False -> UPDATE existing row
    write_history: bool

@dataclass(frozen=True)
class StagingCounts:
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    reactivated: int = 0
    removed: int = 0
    failed: int = 0

@dataclass
class StagingDelta:
    enqueue: list[dict[str, Any]]
    upserts: list[RowUpsert]
    reactivations: list[int]         # pks flipped active without a content write
    removals: list[int]              # pks flipped removed
    touches: list[int]               # pks getting last_seen_at only
    counts: StagingCounts

def classify(products: list[Any], stored: dict[str, StoredRow], config_hash: str) -> StagingDelta
```

Binding matrix (approved design):

| Situation | Action |
|---|---|
| invalid product (not dict / missing / empty / non-str `id`) | `counts.failed += 1`, skip |
| duplicate `id` within run | first wins; later `counts.failed += 1` |
| no stored row | insert upsert, history, enqueue, `new` |
| active row, either hash differs | update upsert, `write_history=(content differs)`, enqueue, `changed` |
| active row, both equal | touch pk, `unchanged` |
| removed row reappears, any hash differs | update upsert (flips active via persistence), `write_history=(content differs)`, enqueue, `reactivated` |
| removed row reappears, both equal | `reactivations.append(pk)`, enqueue, `reactivated` |
| active stored row absent | `removals.append(pk)`, `removed` |
| removed stored row absent | no-op |

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_staging_delta.py`:

```python
from app.staging.delta import StoredRow, StagingCounts, classify
from app.staging.hashing import content_hash

CFG = "cfg0"


def _stored(pid, ch, status="active", pk=1):
    return StoredRow(pk=pk, product_id=pid, content_hash=ch, config_hash=CFG,
                     status=status, snapshot={})


def _products(*items):
    return [{"id": pid, "title": t} for pid, t in items]


class TestClassify:
    def test_first_run_inserts_everything(self):
        products = _products(("1", "A"), ("2", "B"))
        delta = classify(products, {}, CFG)
        assert [u.product_id for u in delta.upserts] == ["1", "2"]
        assert all(u.insert and u.write_history for u in delta.upserts)
        assert delta.enqueue == products
        assert delta.counts.new == 2

    def test_identical_rerun_only_touches(self):
        products = _products(("1", "A"))
        stored = {"1": _stored("1", content_hash(products[0]), pk=7)}
        delta = classify(products, stored, CFG)
        assert delta.upserts == [] and delta.enqueue == []
        assert delta.touches == [7]
        assert delta.counts.unchanged == 1

    def test_content_change_enqueues_with_history(self):
        old = {"id": "1", "title": "A"}
        new = {"id": "1", "title": "B"}
        delta = classify([new], {"1": _stored("1", content_hash(old), pk=7)}, CFG)
        assert delta.upserts[0].write_history is True
        assert delta.enqueue == [new]
        assert delta.counts.changed == 1

    def test_config_only_change_enqueues_without_history(self):
        product = {"id": "1", "title": "A"}
        delta = classify([product], {"1": _stored("1", content_hash(product), pk=7)}, "cfgNEW")
        assert delta.upserts[0].write_history is False
        assert delta.upserts[0].config_hash == "cfgNEW"
        assert delta.counts.changed == 1

    def test_removal_when_active_row_absent(self):
        stored = {"1": _stored("1", "x", pk=7), "2": _stored("2", "y", pk=8)}
        delta = classify([], stored, CFG)
        assert delta.removals == [7, 8]
        assert delta.counts.removed == 2

    def test_removed_row_absent_again_is_noop(self):
        stored = {"1": _stored("1", "x", status="removed", pk=7)}
        delta = classify([], stored, CFG)
        assert delta.removals == []
        assert delta.counts.removed == 0

    def test_reactivation_with_equal_hashes_flips_only(self):
        product = {"id": "1", "title": "A"}
        stored = {
            "1": StoredRow(pk=7, product_id="1", content_hash=content_hash(product),
                           config_hash=CFG, status="removed", snapshot={}),
        }
        delta = classify([product], stored, CFG)
        assert delta.upserts == []
        assert delta.reactivations == [7]
        assert delta.enqueue == [product]
        assert delta.counts.reactivated == 1

    def test_reactivation_with_changed_content_upserts_with_history(self):
        old = {"id": "1", "title": "A"}
        new = {"id": "1", "title": "B"}
        stored = {
            "1": StoredRow(pk=7, product_id="1", content_hash=content_hash(old),
                           config_hash=CFG, status="removed", snapshot=old),
        }
        delta = classify([new], stored, CFG)
        assert len(delta.upserts) == 1
        assert delta.upserts[0].write_history is True
        assert delta.reactivations == []
        assert delta.counts.reactivated == 1

    def test_missing_or_invalid_ids_fail(self):
        delta = classify([{"title": "no id"}, {"id": "", "t": 1}, [1, 2]], {}, CFG)
        assert delta.counts.failed == 3
        assert delta.enqueue == []

    def test_duplicate_ids_first_wins_rest_fail(self):
        products = _products(("1", "A")) + [{"id": "1", "title": "dup"}]
        delta = classify(products, {}, CFG)
        assert delta.enqueue == [products[0]]
        assert delta.counts.failed == 1
        assert delta.counts.new == 1

    def test_counts_default_zero(self):
        assert StagingCounts().new == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_staging_delta.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.staging.delta'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/staging/delta.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .hashing import content_hash


@dataclass(frozen=True)
class StoredRow:
    pk: int
    product_id: str
    content_hash: str
    config_hash: str
    status: str
    snapshot: dict[str, Any]


@dataclass(frozen=True)
class RowUpsert:
    product_id: str
    product: dict[str, Any]
    content_hash: str
    config_hash: str
    insert: bool
    write_history: bool


@dataclass(frozen=True)
class StagingCounts:
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    reactivated: int = 0
    removed: int = 0
    failed: int = 0


@dataclass
class StagingDelta:
    enqueue: list[dict[str, Any]] = field(default_factory=list)
    upserts: list[RowUpsert] = field(default_factory=list)
    reactivations: list[int] = field(default_factory=list)
    removals: list[int] = field(default_factory=list)
    touches: list[int] = field(default_factory=list)
    counts: StagingCounts = field(default_factory=StagingCounts)


def _product_id(product: Any) -> str | None:
    if not isinstance(product, dict):
        return None
    pid = product.get("id")
    if not isinstance(pid, str) or not pid:
        return None
    return pid


def classify(
    products: list[Any],
    stored: dict[str, StoredRow],
    config_hash: str,
) -> StagingDelta:
    delta = StagingDelta()
    seen: set[str] = set()

    for product in products:
        pid = _product_id(product)
        if pid is None or pid in seen:
            delta.counts.failed += 1
            continue
        seen.add(pid)

        ch = content_hash(product)
        row = stored.get(pid)

        if row is None:
            delta.upserts.append(RowUpsert(
                product_id=pid, product=product, content_hash=ch,
                config_hash=config_hash, insert=True, write_history=True,
            ))
            delta.enqueue.append(product)
            delta.counts.new += 1
        elif row.status == "active":
            if ch != row.content_hash or config_hash != row.config_hash:
                delta.upserts.append(RowUpsert(
                    product_id=pid, product=product, content_hash=ch,
                    config_hash=config_hash, insert=False,
                    write_history=ch != row.content_hash,
                ))
                delta.enqueue.append(product)
                delta.counts.changed += 1
            else:
                delta.touches.append(row.pk)
                delta.counts.unchanged += 1
        else:
            content_changed = ch != row.content_hash
            if content_changed or config_hash != row.config_hash:
                delta.upserts.append(RowUpsert(
                    product_id=pid, product=product, content_hash=ch,
                    config_hash=config_hash, insert=False,
                    write_history=content_changed,
                ))
            else:
                delta.reactivations.append(row.pk)
            delta.enqueue.append(product)
            delta.counts.reactivated += 1

    for pid, row in stored.items():
        if pid not in seen and row.status == "active":
            delta.removals.append(row.pk)
            delta.counts.removed += 1

    return delta
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_staging_delta.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add app/staging/delta.py tests/test_staging_delta.py
git commit -m "feat: staging delta classifier"
```

---

### Task 5: Migration — `removed_at`, cascade FK, purge index

**Files:**
- Modify: `backend/app/models/staging.py`
- Create: `backend/alembic/versions/20260826_0001_m5_staging_delta.py`
- Test: `backend/tests/test_m5_migration.py`

**Interfaces:**
- Consumes: current head revision `20260825_0001`. The baseline created the FK unnamed, so PostgreSQL named it `staging_history_staging_product_id_fkey` (default `table_column_fkey` pattern).
- Produces: `StagingProduct.removed_at: Mapped[datetime | None]`; `staging_history.staging_product_id` with `ON DELETE CASCADE`; partial index `ix_staging_products_removed_purge ON staging_products (removed_at) WHERE status = 'removed'`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_m5_migration.py`:

```python
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


def _alembic_config(url):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


async def _inspect_schema(url):
    engine = create_async_engine(url)

    def _run(connection):
        inspector = inspect(connection)
        return (
            {c["name"] for c in inspector.get_columns("staging_products")},
            {i["name"]: i for i in inspector.get_indexes("staging_products")},
            inspector.get_foreign_keys("staging_history"),
        )

    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_run)
    finally:
        await engine.dispose()


async def test_upgrade_adds_removed_at_cascade_and_index(isolated_database_url):
    columns, indexes, fks = await _inspect_schema(isolated_database_url)

    assert "removed_at" in columns
    assert "ix_staging_products_removed_purge" in indexes
    history_fk = [fk for fk in fks if fk["constrained_columns"] == ["staging_product_id"]]
    assert history_fk and history_fk[0].get("ondelete") == "CASCADE"


async def test_downgrade_reverses_all_three(isolated_database_url):
    command.downgrade(_alembic_config(isolated_database_url), "20260825_0001")

    columns, indexes, fks = await _inspect_schema(isolated_database_url)
    assert "removed_at" not in columns
    assert "ix_staging_products_removed_purge" not in indexes
    history_fk = [fk for fk in fks if fk["constrained_columns"] == ["staging_product_id"]]
    assert history_fk and history_fk[0].get("ondelete") == "RESTRICT"

    command.upgrade(_alembic_config(isolated_database_url), "head")


async def test_removal_deletes_history_via_cascade(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            client = (await session.execute(
                text("INSERT INTO clients (name) VALUES ('C') RETURNING id")
            )).scalar_one()
            fs = (await session.execute(
                text(
                    "INSERT INTO feed_sources (client_id, name, source_format) "
                    "VALUES (:cid, 'F', 'tsv') RETURNING id"
                ),
                {"cid": client},
            )).scalar_one()
            run = (await session.execute(
                text(
                    "INSERT INTO ingestion_runs (feed_source_id, status) "
                    "VALUES (:fid, 'running') RETURNING id"
                ),
                {"fid": fs},
            )).scalar_one()
            await session.execute(
                text(
                    "INSERT INTO staging_products "
                    "(feed_source_id, ingestion_run_id, product_id, content_hash, "
                    "config_hash, status, raw_data) "
                    "VALUES (:fid, :rid, 'p1', 'h', 'c', 'active', '{}')"
                ),
                {"fid": fs, "rid": run},
            )
            await session.execute(text(
                "INSERT INTO staging_history (staging_product_id, snapshot) "
                "SELECT id, '{}' FROM staging_products"
            ))

    async with factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM staging_products"))

    async with factory() as session:
        remaining = (await session.execute(
            text("SELECT count(*) FROM staging_history")
        )).scalar_one()
    assert remaining == 0
    await engine.dispose()
```

Note: if the `feed_sources` INSERT fails on additional NOT NULL columns, check `app/models/feed_source.py` and extend the column list accordingly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_m5_migration.py -v`
Expected: FAIL — `removed_at` column missing on the upgraded database

- [ ] **Step 3: Update the models**

In `backend/app/models/staging.py` make exactly three changes:
1. Add after the `last_seen_at` line of `StagingProduct`:

```python
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

2. In `StagingHistory`, change the FK line from `ondelete="RESTRICT"` to:

```python
    staging_product_id: Mapped[int] = mapped_column(ForeignKey("staging_products.id", ondelete="CASCADE"), nullable=False)
```

3. Nothing else changes in the file.

- [ ] **Step 4: Write the migration**

Create `backend/alembic/versions/20260826_0001_m5_staging_delta.py`:

```python
"""M5 staging delta support

Revision ID: 20260826_0001
Revises: 20260825_0001
Create Date: 2026-08-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '20260826_0001'
down_revision: Union[str, Sequence[str], None] = '20260825_0001'
branch_labels: Union[str, Sequence[str], None] = None

_PURGE_INDEX = 'ix_staging_products_removed_purge'
_HISTORY_FK = 'staging_history_staging_product_id_fkey'


def upgrade() -> None:
    op.add_column(
        'staging_products',
        sa.Column('removed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        _PURGE_INDEX,
        'staging_products',
        ['removed_at'],
        unique=False,
        postgresql_where=sa.text("status = 'removed'"),
    )
    op.drop_constraint(_HISTORY_FK, 'staging_history', type_='foreignkey')
    op.create_foreign_key(
        _HISTORY_FK,
        'staging_history',
        'staging_products',
        ['staging_product_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint(_HISTORY_FK, 'staging_history', type_='foreignkey')
    op.create_foreign_key(
        _HISTORY_FK,
        'staging_history',
        'staging_products',
        ['staging_product_id'],
        ['id'],
        ondelete='RESTRICT',
    )
    op.drop_index(_PURGE_INDEX, table_name='staging_products')
    op.drop_column('staging_products', 'removed_at')
```

If `drop_constraint` reports the name does not exist, query the real name against the test database (`SELECT conname FROM pg_constraint WHERE conrelid = 'staging_history'::regclass AND contype = 'fkey';`) and use it verbatim in `_HISTORY_FK`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_m5_migration.py tests/test_migrations.py tests/test_models.py -v`
Expected: PASS — new tests green; existing migration/model suites unaffected

- [ ] **Step 6: Commit**

```bash
git add app/models/staging.py alembic/versions/20260826_0001_m5_staging_delta.py tests/test_m5_migration.py
git commit -m "feat: staging removed_at column, history cascade, purge index"
```

---

### Task 6: StagingStep + runner wiring

**Files:**
- Create: `backend/app/staging/persistence.py`
- Modify: `backend/app/pipeline/steps.py` (extend `StepContext`, add `StagingStep`, wire `default_steps`)
- Modify: `backend/app/pipeline/runner.py` (pass `ingestion_run_id`)
- Modify: `backend/app/pipeline/__init__.py` (export `StagingStep`)
- Test: `backend/tests/test_staging_step.py`

**Interfaces:**
- Consumes: Tasks 1–4 outputs; models `StagingProduct`/`StagingHistory`; `RunState`.
- Produces:
  - `StepContext` gains keyword field `ingestion_run_id: int = 0` (existing constructions unaffected).
  - `load_stored_rows(session_factory, feed_source_id: int) -> dict[str, StoredRow]`
  - `apply_staging_delta(session_factory, feed_source_id: int, ingestion_run_id: int, delta: StagingDelta, config_hash: str, *, chunk_size: int = 1000) -> dict[str, int]` returning `product_id -> staging_products.pk` for every enqueued product.
  - `StagingStep(chunk_size: int = 1000)` with `name = "staging"`, placed between `MappingStep` and `PluginStep` in `default_steps()`.
  - Statistics key `"staging"` = `{"new", "changed", "unchanged", "reactivated", "removed", "failed"}`; `processed_count = len(enqueue)`; `failed_count = counts.failed`.

Persistence actions per delta list (each chunk wrapped in its own transaction):
- upserts `insert=True` → INSERT `{feed_source_id, ingestion_run_id, product_id, content_hash, config_hash, status="active", last_seen_at=now, removed_at=None, raw_data=product}`, flush chunk for pks.
- upserts `insert=False` → UPDATE by `(feed_source_id, product_id)`: `raw_data`, hashes, `status="active"`, `removed_at=None`, `ingestion_run_id`, `last_seen_at=now`.
- `reactivations` pks → UPDATE `status="active"`, `removed_at=None`, `last_seen_at=now`, `ingestion_run_id`.
- `removals` pks → UPDATE `status="removed"`, `removed_at=now`, `ingestion_run_id`.
- `touches` pks → UPDATE `last_seen_at=now` ONLY (spec §4).
- History: INSERT `StagingHistory(staging_product_id=pk_map[product_id], snapshot=product)` for each upsert with `write_history=True`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_staging_step.py`:

```python
import logging

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.staging import StagingHistory, StagingProduct
from app.pipeline import RunState, StepContext
from app.pipeline.steps import StagingStep
from app.staging.delta import StoredRow
from app.staging.hashing import content_hash
from app.staging.persistence import load_stored_rows

pytestmark = pytest.mark.asyncio


class FactoryAdapter:
    def __init__(self, factory):
        self._factory = factory

    def __call__(self):
        return self._factory()


async def _seed(session):
    client = Client(name="Acme")
    session.add(client)
    await session.flush()
    feed_source = FeedSource(client_id=client.id, name="US", source_format="tsv")
    session.add(feed_source)
    await session.flush()
    return feed_source


def _ctx(factory, feed_source_id, products, run_id=1):
    state = RunState(products=list(products))
    return StepContext(
        feed_source_id=feed_source_id,
        session_factory=FactoryAdapter(factory),
        logger=logging.getLogger("test"),
        run_state=state,
        ingestion_run_id=run_id,
    )


async def _staged_rows(factory):
    async with factory() as session:
        result = await session.execute(select(StagingProduct))
        return {row.product_id: row for row in result.scalars()}


async def test_first_run_stages_all_products(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]

    result = await StagingStep().execute(_ctx(factory, feed_source.id, products))

    assert result.statistics["staging"]["new"] == 2
    assert result.processed_count == 2
    rows = await _staged_rows(factory)
    assert set(rows) == {"1", "2"}
    assert all(r.status == "active" for r in rows.values())
    assert rows["1"].raw_data == products[0]
    await engine.dispose()


async def test_identical_rerun_touches_only(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=1))

    result = await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=2))

    assert result.statistics["staging"]["unchanged"] == 1
    assert result.processed_count == 0
    async with factory() as session:
        row = (await session.execute(select(StagingProduct))).scalar_one()
        assert row.ingestion_run_id == 1
    await engine.dispose()


async def test_run_state_replaced_with_enqueue_set(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    first = [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, first, run_id=1))

    second = [{"id": "1", "title": "CHANGED"}, {"id": "2", "title": "B"}]
    ctx = _ctx(factory, feed_source.id, second, run_id=2)
    await StagingStep().execute(ctx)

    assert [p["id"] for p in ctx.run_state.products] == ["1"]
    async with factory() as session:
        histories = (await session.execute(select(StagingHistory))).scalars().all()
    assert len(histories) == 3
    await engine.dispose()


async def test_config_only_change_no_new_history(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=1))

    async with factory() as session:
        async with session.begin():
            row = (await session.execute(select(StagingProduct))).scalar_one()
            row.config_hash = "different"

    ctx = _ctx(factory, feed_source.id, products, run_id=2)
    result = await StagingStep().execute(ctx)

    assert result.statistics["staging"]["changed"] == 1
    async with factory() as session:
        histories = (await session.execute(select(StagingHistory))).scalars().all()
    assert len(histories) == 1
    await engine.dispose()


async def test_removal_then_reactivation_round_trip(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}]
    await StagingStep().execute(_ctx(factory, feed_source.id, products, run_id=1))

    await StagingStep().execute(_ctx(factory, feed_source.id, products[:1], run_id=2))
    rows = await _staged_rows(factory)
    assert rows["2"].status == "removed"
    assert rows["2"].removed_at is not None

    ctx = _ctx(factory, feed_source.id, products, run_id=3)
    result = await StagingStep().execute(ctx)

    assert result.statistics["staging"]["reactivated"] == 1
    assert [p["id"] for p in ctx.run_state.products] == ["2"]
    rows = await _staged_rows(factory)
    assert rows["2"].status == "active"
    assert rows["2"].removed_at is None
    await engine.dispose()


async def test_invalid_and_duplicate_ids_counted_failed(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    products = [
        {"title": "no id"},
        {"id": "1", "title": "first"},
        {"id": "1", "title": "dup"},
    ]

    result = await StagingStep().execute(_ctx(factory, feed_source.id, products))

    assert result.failed_count == 2
    assert result.statistics["staging"]["failed"] == 2
    rows = await _staged_rows(factory)
    assert set(rows) == {"1"}
    assert rows["1"].raw_data["title"] == "first"
    await engine.dispose()


async def test_load_stored_rows_maps_snapshots(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)
    await StagingStep().execute(
        _ctx(factory, feed_source.id, [{"id": "1", "title": "A"}], run_id=1)
    )

    stored = await load_stored_rows(FactoryAdapter(factory), feed_source.id)

    assert set(stored) == {"1"}
    row = stored["1"]
    assert isinstance(row, StoredRow)
    assert row.snapshot == {"id": "1", "title": "A"}
    assert row.content_hash == content_hash({"id": "1", "title": "A"})
    await engine.dispose()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_staging_step.py -v`
Expected: FAIL with `ImportError: cannot import name 'StagingStep'`

- [ ] **Step 3: Write the persistence helper**

Create `backend/app/staging/persistence.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.staging import StagingHistory, StagingProduct
from .delta import StagingDelta, StoredRow


async def load_stored_rows(
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
) -> dict[str, StoredRow]:
    async with session_factory() as session:
        result = await session.execute(
            select(StagingProduct).where(
                StagingProduct.feed_source_id == feed_source_id
            )
        )
        return {
            row.product_id: StoredRow(
                pk=row.id,
                product_id=row.product_id,
                content_hash=row.content_hash,
                config_hash=row.config_hash,
                status=row.status,
                snapshot=row.raw_data or {},
            )
            for row in result.scalars()
        }


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def apply_staging_delta(
    session_factory: Callable[[], AsyncSession],
    feed_source_id: int,
    ingestion_run_id: int,
    delta: StagingDelta,
    config_hash: str,
    *,
    chunk_size: int = 1000,
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    pk_map: dict[str, int] = {}

    inserts = [u for u in delta.upserts if u.insert]
    updates = [u for u in delta.upserts if not u.insert]

    for group in _chunks(inserts, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                rows = [
                    StagingProduct(
                        feed_source_id=feed_source_id,
                        ingestion_run_id=ingestion_run_id,
                        product_id=u.product_id,
                        content_hash=u.content_hash,
                        config_hash=config_hash,
                        status="active",
                        last_seen_at=now,
                        removed_at=None,
                        raw_data=u.product,
                    )
                    for u in group
                ]
                session.add_all(rows)
                await session.flush()
                for u, row in zip(group, rows):
                    pk_map[u.product_id] = row.id

    for group in _chunks(updates, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                for u in group:
                    await session.execute(
                        update(StagingProduct)
                        .where(
                            StagingProduct.feed_source_id == feed_source_id,
                            StagingProduct.product_id == u.product_id,
                        )
                        .values(
                            raw_data=u.product,
                            content_hash=u.content_hash,
                            config_hash=config_hash,
                            status="active",
                            removed_at=None,
                            ingestion_run_id=ingestion_run_id,
                            last_seen_at=now,
                        )
                    )
                    pk_map[u.product_id] = (
                        await session.execute(
                            select(StagingProduct.id).where(
                                StagingProduct.feed_source_id == feed_source_id,
                                StagingProduct.product_id == u.product_id,
                            )
                        )
                    ).scalar_one()

    for group in _chunks(delta.reactivations, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                for pk in group:
                    await session.execute(
                        update(StagingProduct)
                        .where(StagingProduct.id == pk)
                        .values(
                            status="active",
                            removed_at=None,
                            ingestion_run_id=ingestion_run_id,
                            last_seen_at=now,
                        )
                    )

    for group in _chunks(delta.removals, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                for pk in group:
                    await session.execute(
                        update(StagingProduct)
                        .where(StagingProduct.id == pk)
                        .values(
                            status="removed",
                            removed_at=now,
                            ingestion_run_id=ingestion_run_id,
                        )
                    )

    for group in _chunks(delta.touches, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(StagingProduct)
                    .where(StagingProduct.id.in_(group))
                    .values(last_seen_at=now)
                )

    history_rows = [
        (pk_map[u.product_id], u.product) for u in delta.upserts if u.write_history
    ]
    for group in _chunks(history_rows, chunk_size):
        async with session_factory() as session:
            async with session.begin():
                session.add_all([
                    StagingHistory(staging_product_id=pk, snapshot=snapshot)
                    for pk, snapshot in group
                ])

    return pk_map
```

- [ ] **Step 4: Add StagingStep and wire the pipeline**

In `backend/app/pipeline/steps.py`:

1. Extend the top-level imports:

```python
from dataclasses import asdict, dataclass, field
```

and add below the existing model imports:

```python
from ..staging.config_resolver import resolve_config_bundle
from ..staging.delta import classify
from ..staging.hashing import content_hash
from ..staging.persistence import apply_staging_delta, load_stored_rows
```

2. Change `StepContext` to add the field:

```python
@dataclass(frozen=True)
class StepContext:
    feed_source_id: int
    session_factory: Callable[[], AsyncSession]
    logger: logging.Logger
    run_state: RunState
    ingestion_run_id: int = 0
```

3. Insert this class directly after `MappingStep` ends (before `PluginStep`):

```python
class StagingStep:
    name = "staging"

    def __init__(self, chunk_size: int = 1000) -> None:
        self._chunk_size = chunk_size

    async def execute(self, ctx: StepContext) -> StepResult:
        async with ctx.session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, ctx.feed_source_id)
        if feed_source is None:
            raise LookupError(f"feed source {ctx.feed_source_id} not found")

        async with ctx.session_factory() as session:
            bundle = await resolve_config_bundle(session, feed_source)
        config_hash_value = content_hash(bundle)

        stored = await load_stored_rows(ctx.session_factory, ctx.feed_source_id)
        delta = classify(ctx.run_state.products, stored, config_hash_value)
        if delta.counts.failed:
            ctx.logger.warning(
                "staging: %d unusable products (missing/duplicate id)",
                delta.counts.failed,
            )

        await apply_staging_delta(
            ctx.session_factory,
            ctx.feed_source_id,
            ctx.ingestion_run_id,
            delta,
            config_hash_value,
            chunk_size=self._chunk_size,
        )

        ctx.run_state.products = list(delta.enqueue)
        return StepResult(
            processed_count=len(delta.enqueue),
            failed_count=delta.counts.failed,
            statistics={"staging": asdict(delta.counts)},
        )
```

4. Update `default_steps` at the end of the file:

```python
def default_steps(
    fetcher: HttpFetcher, registry: RegistryDocument
) -> tuple[PipelineStep, ...]:
    return (
        IngestStep(fetcher, registry),
        MappingStep(registry),
        StagingStep(),
        PluginStep(),
        QualityCheckStep(),
        ExportStep(),
    )
```

5. In `backend/app/pipeline/runner.py`, pass the run id into the context inside the step loop:

```python
ctx = StepContext(
    feed_source_id=feed_source_id,
    session_factory=self._session_factory,
    logger=logger,
    run_state=run_state,
    ingestion_run_id=run_id,
)
```

6. In `backend/app/pipeline/__init__.py`, add `StagingStep` to the steps import/export list following how `MappingStep` appears there.

- [ ] **Step 5: Run new tests plus affected suites**

Run: `uv run pytest tests/test_staging_step.py tests/test_mapping_step.py tests/test_ingest_step.py tests/test_pipeline_steps.py tests/test_pipeline_runner.py -v`
Expected: PASS. If an existing test asserts the exact tuple length of `default_steps()`, update that one assertion to 6 and mention it in the commit message.

- [ ] **Step 6: Commit**

```bash
git add app/pipeline/steps.py app/pipeline/runner.py app/pipeline/__init__.py app/staging/persistence.py tests/test_staging_step.py
git commit -m "feat: StagingStep persists staged state and reduces run to delta set"
```

---

### Task 7: Purge job + scheduler system-job namespace

**Files:**
- Create: `backend/app/staging/purge.py`
- Modify: `backend/app/pipeline/scheduler.py` (system-job support)
- Modify: `backend/app/main.py` (lifespan registration)
- Test: `backend/tests/test_staging_purge.py`
- Modify: `backend/tests/test_scheduler_service.py` (append system-job tests)

**Interfaces:**
- Consumes: models `StagingProduct`/`StagingHistory`; `validate_cron` (exists in scheduler.py).
- Produces:
  - `REMOVAL_RETENTION_DAYS = 90`, `HISTORY_RETENTION_DAYS = 90`, `PurgeCounts(removed_products: int, history_rows: int)`, `async def purge_expired(session_factory, now: datetime) -> PurgeCounts` in `app.staging.purge`.
  - `SYSTEM_PURGE_JOB_ID = "system-staging-purge"`, `PURGE_CRON = "0 3 * * *"` in `app.pipeline.scheduler`.
  - `SchedulerService.register_system_job(job_id: str, cron_expression: str, func, *args) -> None` — same `add_job` parameters as feed-source jobs (`misfire_grace_time=None`, `replace_existing=True`) but keyed by the caller-supplied id.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_staging_purge.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.staging import StagingHistory, StagingProduct
from app.staging.purge import purge_expired

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


class FactoryAdapter:
    def __init__(self, factory):
        self._factory = factory

    def __call__(self):
        return self._factory()


async def _seed(session):
    client = Client(name="Acme")
    session.add(client)
    await session.flush()
    feed_source = FeedSource(client_id=client.id, name="US", source_format="tsv")
    session.add(feed_source)
    await session.flush()
    return feed_source


async def _product(factory, feed_source, pid, status, removed_at, recorded_at=NOW):
    async with factory() as session:
        async with session.begin():
            row = StagingProduct(
                feed_source_id=feed_source.id,
                ingestion_run_id=1,
                product_id=pid,
                content_hash="h",
                config_hash="c",
                status=status,
                raw_data={},
            )
            session.add(row)
            await session.flush()
            history = StagingHistory(staging_product_id=row.id, snapshot={})
            session.add(history)
            await session.flush()
            pk, history_pk = row.id, history.id
        if status == "removed":
            await session.execute(
                text(
                    "UPDATE staging_products SET removed_at = :ra WHERE id = :pk"
                ),
                {"ra": removed_at, "pk": pk},
            )
        await session.execute(
            text("UPDATE staging_history SET recorded_at = :t WHERE id = :pk"),
            {"t": recorded_at, "pk": history_pk},
        )
    return pk, history_pk


async def test_purge_removes_expired_rows_only(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            feed_source = await _seed(session)

    expired_pk, expired_hist = await _product(
        factory, feed_source, "old", "removed", NOW - timedelta(days=91)
    )
    fresh_pk, fresh_hist = await _product(
        factory, feed_source, "recent", "removed", NOW - timedelta(days=10)
    )
    active_pk, aged_hist = await _product(
        factory, feed_source, "active", "active", None,
        recorded_at=NOW - timedelta(days=91),
    )

    counts = await purge_expired(FactoryAdapter(factory), NOW)

    assert counts.removed_products == 1
    assert counts.history_rows == 2
    async with factory() as session:
        remaining_products = {
            row.product_id
            for row in (await session.execute(select(StagingProduct))).scalars()
        }
        remaining_history = {
            row.id for row in (await session.execute(select(StagingHistory))).scalars()
        }
    assert remaining_products == {"recent", "active"}
    assert remaining_history == {fresh_hist}
    await engine.dispose()


async def test_purge_on_empty_tables_is_zero(isolated_database_url):
    engine = create_async_engine(isolated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    counts = await purge_expired(FactoryAdapter(factory), NOW)

    assert counts == (0, 0) or counts.removed_products == 0 and counts.history_rows == 0
    await engine.dispose()
```

Append to `backend/tests/test_scheduler_service.py`:

```python
class TestSystemJobs:
    def test_register_system_job_uses_given_id(self):
        from app.pipeline.scheduler import SYSTEM_PURGE_JOB_ID, SchedulerService

        service = SchedulerService(runner=_runner_stub())
        service.register_system_job(SYSTEM_PURGE_JOB_ID, "0 3 * * *", lambda: None)
        jobs = service._scheduler.get_jobs()
        assert [job.id for job in jobs] == [SYSTEM_PURGE_JOB_ID]

    def test_feed_source_lifecycle_never_touches_system_job(self):
        from types import SimpleNamespace

        from app.pipeline.scheduler import SYSTEM_PURGE_JOB_ID, SchedulerService

        service = SchedulerService(runner=_runner_stub())
        service.register_system_job(SYSTEM_PURGE_JOB_ID, "0 3 * * *", lambda: None)
        service.register(SimpleNamespace(id=1, cron_expression="0 * * * *"))
        service.unregister(1)

        assert service._scheduler.get_job(SYSTEM_PURGE_JOB_ID) is not None
```

Adapt `_runner_stub()` to whatever helper the existing tests in that file use to build the runner (mirror them exactly; if they construct `PipelineRunner(...)` inline, do the same). The key point: neither new call touches the runner.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_staging_purge.py tests/test_scheduler_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'purge_expired'`; `AttributeError: 'SchedulerService' object has no attribute 'register_system_job'`

- [ ] **Step 3: Implement the purge module**

Create `backend/app/staging/purge.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.staging import StagingHistory, StagingProduct

REMOVAL_RETENTION_DAYS = 90
HISTORY_RETENTION_DAYS = 90


@dataclass(frozen=True)
class PurgeCounts:
    removed_products: int
    history_rows: int


async def purge_expired(
    session_factory: Callable[[], AsyncSession],
    now: datetime,
) -> PurgeCounts:
    removal_cutoff = now - timedelta(days=REMOVAL_RETENTION_DAYS)
    history_cutoff = now - timedelta(days=HISTORY_RETENTION_DAYS)

    async with session_factory() as session:
        async with session.begin():
            removed = await session.execute(
                delete(StagingProduct)
                .where(
                    StagingProduct.status == "removed",
                    StagingProduct.removed_at < removal_cutoff,
                )
                .returning(StagingProduct.id)
            )
            history = await session.execute(
                delete(StagingHistory)
                .where(StagingHistory.recorded_at < history_cutoff)
                .returning(StagingHistory.id)
            )
            return PurgeCounts(
                removed_products=len(removed.scalars().all()),
                history_rows=len(history.scalars().all()),
            )
```

- [ ] **Step 4: Extend the scheduler**

In `backend/app/pipeline/scheduler.py`, add next to `job_id` at module level:

```python
SYSTEM_PURGE_JOB_ID = "system-staging-purge"
PURGE_CRON = "0 3 * * *"
```

Add this method to `SchedulerService` after `reschedule`:

```python
    def register_system_job(
        self,
        job_id: str,
        cron_expression: str,
        func,
        *args,
    ) -> None:
        trigger = validate_cron(cron_expression)
        self._scheduler.add_job(
            func,
            trigger,
            args=list(args),
            id=job_id,
            replace_existing=True,
            misfire_grace_time=None,
        )
```

- [ ] **Step 5: Wire startup in main.py**

In `backend/app/main.py`, inside the lifespan right before `await scheduler_service.register_all(session)` (keep `register_all` as-is), add:

```python
                from datetime import datetime, timezone

                from .pipeline.scheduler import PURGE_CRON, SYSTEM_PURGE_JOB_ID
                from .staging.purge import purge_expired

                async def run_staging_purge() -> None:
                    counts = await purge_expired(
                        application.state.db_session_factory,
                        datetime.now(timezone.utc),
                    )
                    logging.getLogger(__name__).info(
                        "staging purge: %s removed products, %s history rows",
                        counts.removed_products,
                        counts.history_rows,
                    )

                scheduler_service.register_system_job(
                    SYSTEM_PURGE_JOB_ID, PURGE_CRON, run_staging_purge
                )
```

Implementation notes:
- APScheduler's AsyncIOScheduler awaits coroutine functions natively, so the job callable is async.
- Ensure `logging` is imported at the top of `main.py` (check; add if missing).
- Registration order relative to `register_all` does not matter — the two job-id namespaces are disjoint by construction.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_staging_purge.py tests/test_scheduler_service.py tests/test_scheduler_startup.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/staging/purge.py app/pipeline/scheduler.py app/main.py tests/test_staging_purge.py tests/test_scheduler_service.py
git commit -m "feat: daily staging purge as namespaced system scheduler job"
```

---

### Task 8: M5 acceptance gate

**Files:**
- Create: `backend/tests/test_m5_acceptance.py`

**Interfaces:**
- Consumes: everything above; `create_app(settings=..., db_session_factory=factory)` pattern from `test_m4_acceptance.py`; `HttpFetcher` injection point of `create_app`.

- [ ] **Step 1: Write the acceptance test**

Create `backend/tests/test_m5_acceptance.py`. Structure it exactly like `test_m4_acceptance.py` (read that file first): same fixtures/helpers for engine/factory/login via the API, same stub-fetcher approach serving TSV bytes, but asserting staging behavior. Required scenarios (each is one test):

```python
SCENARIOS = [
    # (name, description of what is asserted)
]
```

1. `test_first_run_stages_everything` — two products ingested through the full runner; `GET /clients/{id}/feed-sources/{fid}/ingestion-runs` statistics contain `"staging": {..., "new": 2}`; both rows exist with `status="active"`.
2. `test_identical_second_run_enqueues_nothing` — rerun via `POST /feed-sources/{id}/run`; latest run statistics show `unchanged: 2, new: 0`; history row count still 2.
3. `test_content_change_reprocesses_with_history` — change one product title in the stubbed source; rerun; statistics show `changed: 1`; history count 3.
4. `test_config_change_reprocesses_without_history` — seed an active pipeline (Plugin row + ModulePipeline + ModuleInstance per Task 3 seeding), run once so hashes incorporate it, then mutate the instance `configuration` JSON directly in the DB; rerun; statistics show `changed: 2` while history count stays at 3.
5. `test_removed_product_flips_status_and_returns` — serve a one-product source; rerun (`removed: 1`, row status `removed`, `removed_at` set); serve the original two-product source again; rerun (`reactivated: 1`, row active again, `removed_at` cleared).
6. `test_purge_clears_expired_rows_end_to_end` — remove a product, backdate its `removed_at` by 91 days via SQL, run `purge_expired(factory, now)` directly, assert product and its history are gone.
7. `test_invalid_ids_do_not_block_run` — include a row without an `id` column value; run completes `success` with `failed_count >= 1` and the invalid row is absent from `staging_products`.
8. `test_migration_head_matches_models` — alembic upgrade head on a fresh database then `inspect()` shows `removed_at` and CASCADE FK (guards CI drift like prior milestones).

Each scenario asserts through public surfaces where possible (API endpoints, DB state via SQL), never through internals of `app.staging.*`.

- [ ] **Step 2: Run the acceptance suite**

Run: `uv run pytest tests/test_m5_acceptance.py -v`
Expected: PASS (all scenarios). Debug failures through the specific unit suites from Tasks 1–7.

- [ ] **Step 3: Full milestone gate**

Run all of:

```bash
uv run compileall app
uv run pytest
uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check
git diff --check
cd ../frontend && npm run test -- --run && npm run typecheck && npm run build && cd ../backend
```

Expected: backend suite green (prior ~155+ tests plus new ones), registry artifact unchanged, frontend untouched-and-green. This is the done criterion: "`content_hash`/`config_hash` behave exactly as specified, incl. reactivation & purge."

- [ ] **Step 4: Record final verification in docs/decisions.md**

Append under `## 2026-08-26` an entry `### M5 final verification` following the M1/M2 template: milestone complete statement, test counts, resolved dependency versions (unchanged pins), any deviations from this plan encountered during execution.

- [ ] **Step 5: Commit**

```bash
git add tests/test_m5_acceptance.py ../docs/decisions.md
git commit -m "feat: M5 acceptance gate — staging delta verified"
```

---

## Self-Review Checklist (completed during planning)

- Spec coverage: §4 delta mechanics (Tasks 4/6), reactivation (Task 4 matrix), purge (Task 7), config_hash over resolved configs incl. three-tier merge §5.3 (Tasks 2/3), content_hash canonical form incl. sidecar stripping (Task 1), history-on-content-change-only (Tasks 4/6), StepContext/run-state reduction (Task 6), system-job namespace decision (Task 7).
- Type consistency: `StoredRow`/`RowUpsert`/`StagingDelta`/`PurgeCounts` field names identical across definition and consumer tasks; `resolve_config_bundle(session, feed_source)` signature matches Task 6 usage.
- No placeholders: every code step contains full code or exact edit instructions.



