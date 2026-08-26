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

