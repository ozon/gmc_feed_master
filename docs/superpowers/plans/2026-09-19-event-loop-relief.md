# Event-Loop Relief (B3, B4, B5, B9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move export rendering/file I/O, plugin hook execution, and image decoding off the single-worker event loop, with a hard plugin timeout and per-instance plugin run state.

**Architecture:** Use `asyncio.to_thread` to run the existing synchronous functions in the default executor, wrapped in `asyncio.wait_for` for plugin hooks. No renderer signature change, no streaming, no async plugin contract. Plugin run state is re-keyed from manifest id to per-instance identity (`position`).

**Tech Stack:** Python 3.11 (repo venv), asyncio, FastAPI, SQLAlchemy async, Pillow, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-19-event-loop-relief-design.md`.

## Global Constraints

- Backend-only change; **no new dependencies**.
- Deployment is exactly one uvicorn worker (`backend/AGENTS.md`), which is why loop blocking is the harm.
- Plugin contract stays synchronous: `def process(...) -> dict | None`. Do not change plugins or the contract checker.
- Plugin timeout is the module constant `PLUGIN_CALL_TIMEOUT_S = 30` (seconds) in `app/pipeline/steps.py`; it must be read **at call time** (not bound as a default arg) so tests can monkeypatch it.
- Offload only heavy work. `ExportFileStore.published_exists` (`is_file`) and `.delete_version_file` (`unlink`) stay on the loop deliberately — metadata-only syscalls.
- Run backend commands from `backend/`. DB-backed tests need:
  `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres`.
- Ruff (`uv run ruff check . ../plugins`) and mypy (`uv run mypy .`) are hard, exit-0 gates.
- Commit style matches the repo: `type(scope): summary` (e.g. `perf(plugins): ...`).
- Known, accepted caveat: `asyncio.wait_for` cancels the `await`, not the OS thread. A timed-out plugin hook keeps running; the affected product is errored and discarded, so it cannot corrupt survivors.

---

## File Structure

- `backend/app/pipeline/steps.py` — `PluginStep` keying and threaded hook execution. Modify.
- `backend/app/qc/image_probe.py` — off-loop Pillow decode. Modify.
- `backend/app/export/service.py` — off-loop render + store calls. Modify.
- `backend/tests/test_plugin_step.py` — `B4`/`B5` tests. Modify.
- `backend/tests/test_image_probe.py` — `B9` helper test. Modify.
- `backend/tests/test_export_service.py` — `B3` off-loop proof. Modify.
- `backend/AGENTS.md`, `backend/docs/plugins.md`, `backend/docs/architecture.md`, `docs/decisions.md` — docs. Modify.

---

### Task 1: Per-instance plugin run state (B5)

**Files:**
- Modify: `backend/app/pipeline/steps.py:215-262`
- Test: `backend/tests/test_plugin_step.py`

**Interfaces:**
- Consumes: `bundle["instances"]` entries that may carry `position` (int, set by `resolve_config_bundle`).
- Produces: `run_states` / `accepts_state` keyed by `instance.get("position", index)`; nothing else changes.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_plugin_step.py` (after the last test):

```python
class TagStatePlugin:
    def prepare_run(self, config, data, rctx):
        return {"tag": config["tag"]}

    def process(self, product, config, data, rctx, state=None):
        tags = list(product.get("tags", []))
        tags.append(state["tag"])
        return {**product, "tags": tags}


async def test_two_instances_of_same_plugin_keep_separate_run_state(
    isolated_database_url,
):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [{"id": "1", "title": "a"}]
    feed_source, pks = await _prepare(factory, products)
    bundle = {"instances": [
        {"position": 0, "plugin": "tag", "resolved_config": {"tag": "A"}, "resolved_data": {}},
        {"position": 1, "plugin": "tag", "resolved_config": {"tag": "B"}, "resolved_data": {}},
    ]}

    _result, rows, _ = await _run_plugin_step(
        factory, feed_source, products, pks, bundle, {"tag": TagStatePlugin()}
    )

    assert rows["1"].processed_data == {"id": "1", "title": "a", "tags": ["A", "B"]}
    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest tests/test_plugin_step.py::test_two_instances_of_same_plugin_keep_separate_run_state -q`
Expected: FAIL — `processed_data` has `"tags": ["B", "B"]` (second instance overwrote the shared `run_states["tag"]`).

- [ ] **Step 3: Implement per-instance keying**

In `backend/app/pipeline/steps.py`, replace the prepare loop (currently `for instance in bundle.get("instances", []):` through the `run_states[instance["plugin"]] = prepare(...)` assignment) with:

```python
        # prepare_run: once per plugin instance per run (run-scoped state).
        run_states: dict[Any, Any] = {}
        accepts_state: dict[Any, bool] = {}
        for index, instance in enumerate(bundle.get("instances", [])):
            key = instance.get("position", index)
            plugin_obj = self._registry.get(instance["plugin"])
            if plugin_obj is None:
                continue
            accepts_state[key] = (
                "state" in inspect.signature(plugin_obj.process).parameters
            )
            prepare = getattr(plugin_obj, "prepare_run", None)
            if callable(prepare):
                rctx = RunContext(
                    client_id=ctx.run_state.client_id or 0,
                    feed_source_id=ctx.feed_source_id,
                    run_id=ctx.ingestion_run_id,
                    logger=ctx.logger,
                    run_state=ctx.run_state,
                )
                run_states[key] = prepare(
                    instance["resolved_config"], instance["resolved_data"], rctx
                )
```

Then replace the product loop's instance iteration (`for instance in bundle.get("instances", []):` and its `accepts_state.get(...)` / `run_states.get(...)` lookups) with:

```python
            for index, instance in enumerate(bundle.get("instances", [])):
                key = instance.get("position", index)
                plugin_obj = self._registry.get(instance["plugin"])
                if plugin_obj is None:
                    continue
                rctx = RunContext(
                    client_id=ctx.run_state.client_id or 0,
                    feed_source_id=ctx.feed_source_id,
                    run_id=ctx.ingestion_run_id,
                    logger=ctx.logger,
                    original_product=original,
                    run_state=ctx.run_state,
                )
                try:
                    if accepts_state.get(key):
                        result = plugin_obj.process(
                            current,
                            instance["resolved_config"],
                            instance["resolved_data"],
                            rctx,
                            state=run_states.get(key),
                        )
                    else:
                        result = plugin_obj.process(
                            current,
                            instance["resolved_config"],
                            instance["resolved_data"],
                            rctx,
                        )
                except Exception as exc:  # noqa: BLE001
                    ctx.logger.warning(
                        "plugin %s errored on product %s: %s",
                        instance["plugin"], pid, exc,
                    )
                    errored += 1
                    error = True
                    break
```

- [ ] **Step 4: Run the full plugin-step file to verify pass**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest tests/test_plugin_step.py -q`
Expected: PASS (all tests, including the six existing ones and the new one).

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/steps.py backend/tests/test_plugin_step.py
git commit -m "fix(plugins): key run state per pipeline instance, not plugin id"
```

---

### Task 2: Threaded plugin hooks with a hard timeout (B4)

**Files:**
- Modify: `backend/app/pipeline/steps.py`
- Test: `backend/tests/test_plugin_step.py`

**Interfaces:**
- Consumes: `PLUGIN_CALL_TIMEOUT_S` and `_call_plugin` defined in this task; sync plugin hooks.
- Produces: `_call_plugin(fn, *args, **kwargs)` → runs `fn` via `asyncio.to_thread`, bounded by `PLUGIN_CALL_TIMEOUT_S`; `PluginStep` uses it for `prepare_run` and both `process` branches.

- [ ] **Step 1: Write the failing test**

Add `import time` to the top import block of `backend/tests/test_plugin_step.py` (it currently starts `import logging`; make it `import logging` then `import time`). Then append to the end of the file:

```python
class SlowOnOnePlugin:
    def process(self, product, config, data, rctx):
        if product["id"] == "1":
            time.sleep(0.2)
        return {**product, "touched": True}


async def test_plugin_call_timeout_errors_product_and_continues(
    isolated_database_url, monkeypatch,
):
    monkeypatch.setattr("app.pipeline.steps.PLUGIN_CALL_TIMEOUT_S", 0.05)
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    products = [{"id": "1", "title": "a"}, {"id": "2", "title": "b"}]
    feed_source, pks = await _prepare(factory, products)
    bundle = {"instances": [
        {"position": 0, "plugin": "slow", "resolved_config": {}, "resolved_data": {}},
    ]}

    result, rows, _ = await _run_plugin_step(
        factory, feed_source, products, pks, bundle, {"slow": SlowOnOnePlugin()}
    )

    assert result.failed_count == 1
    assert result.processed_count == 1
    assert rows["1"].processed_data is None
    assert rows["2"].processed_data == {"id": "2", "title": "b", "touched": True}
    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest tests/test_plugin_step.py::test_plugin_call_timeout_errors_product_and_continues -q`
Expected: FAIL — `failed_count` is 0 and `processed_count` is 2 (no timeout exists; `slow` succeeds).

- [ ] **Step 3: Add the executor helper and route hooks through it**

In `backend/app/pipeline/steps.py`, add `import asyncio` as the first import (before `import inspect`).

Immediately above `class PluginStep:`, add:

```python
PLUGIN_CALL_TIMEOUT_S = 30


async def _call_plugin(fn, *args, **kwargs):
    """Run a sync plugin hook in a worker thread under a hard timeout.

    ponytail: wait_for cancels the await, not the OS thread. A timed-out hook
    keeps running in the background; the product it was handling is marked
    errored and discarded, so it cannot corrupt survivors. A subprocess
    sandbox is the escape hatch if a hook ever needs true cancellation.
    """
    return await asyncio.wait_for(
        asyncio.to_thread(fn, *args, **kwargs), PLUGIN_CALL_TIMEOUT_S
    )
```

Replace `run_states[key] = prepare(...)` with:

```python
                run_states[key] = await _call_plugin(
                    prepare,
                    instance["resolved_config"],
                    instance["resolved_data"],
                    rctx,
                )
```

Replace the two `result = plugin_obj.process(...)` branches with:

```python
                try:
                    if accepts_state.get(key):
                        result = await _call_plugin(
                            plugin_obj.process,
                            current,
                            instance["resolved_config"],
                            instance["resolved_data"],
                            rctx,
                            state=run_states.get(key),
                        )
                    else:
                        result = await _call_plugin(
                            plugin_obj.process,
                            current,
                            instance["resolved_config"],
                            instance["resolved_data"],
                            rctx,
                        )
                except asyncio.TimeoutError:
                    ctx.logger.warning(
                        "plugin %s timed out on product %s after %ss",
                        instance["plugin"], pid, PLUGIN_CALL_TIMEOUT_S,
                    )
                    errored += 1
                    error = True
                    break
                except Exception as exc:  # noqa: BLE001
                    ctx.logger.warning(
                        "plugin %s errored on product %s: %s",
                        instance["plugin"], pid, exc,
                    )
                    errored += 1
                    error = True
                    break
```

- [ ] **Step 4: Run tests and the static gates**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest tests/test_plugin_step.py -q`
Expected: PASS (all tests).

Run: `uv run ruff check . ../plugins && uv run mypy .`
Expected: both exit 0.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/steps.py backend/tests/test_plugin_step.py
git commit -m "perf(plugins): run sync hooks in a thread under a hard timeout"
```

---

### Task 3: Off-loop image decode (B9)

**Files:**
- Modify: `backend/app/qc/image_probe.py:51-52`
- Test: `backend/tests/test_image_probe.py`

**Interfaces:**
- Produces: `_image_size(body: bytes) -> tuple[int, int]` in `app/qc/image_probe.py`; `probe()` awaits it via `asyncio.to_thread`.

- [ ] **Step 1: Write the failing test**

Change the existing import line in `backend/tests/test_image_probe.py` from
`from app.qc.image_probe import ImageProbeImpl` to
`from app.qc.image_probe import ImageProbeImpl, _image_size`. Then append:

```python
async def test_image_size_helper_reads_dimensions():
    assert _image_size(_make_jpeg_bytes(300, 120)) == (300, 120)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_image_probe.py::test_image_size_helper_reads_dimensions -q`
Expected: FAIL — `ImportError: cannot import name '_image_size'`.

- [ ] **Step 3: Implement the helper and offload the decode**

In `backend/app/qc/image_probe.py`, add below the imports (before `logger = ...`):

```python
def _image_size(body: bytes) -> tuple[int, int]:
    return Image.open(BytesIO(body)).size
```

Replace:

```python
                img = Image.open(BytesIO(body))
                width, height = img.size
```

with:

```python
                width, height = await asyncio.to_thread(_image_size, body)
```

- [ ] **Step 4: Run the file to verify pass**

Run: `uv run pytest tests/test_image_probe.py -q`
Expected: PASS (all image-probe tests, including the existing success/corrupt/too-large cases).

- [ ] **Step 5: Commit**

```bash
git add backend/app/qc/image_probe.py backend/tests/test_image_probe.py
git commit -m "perf(qc): decode probe images off the event loop"
```

---

### Task 4: Off-loop export render and file I/O (B3)

**Files:**
- Modify: `backend/app/export/service.py`
- Test: `backend/tests/test_export_service.py`

**Interfaces:**
- Consumes: `ExportFileStore.write_version` / `.publish` / `.read_version`; `render_feed` (all synchronous, unchanged signatures).
- Produces: same `ExportService` public methods (all already `async`); `_load_version_products` becomes `async`.

- [ ] **Step 1: Write the failing test**

Add `import threading` as the first import of `backend/tests/test_export_service.py` (before `from datetime import ...`). Then append:

```python
async def test_export_render_and_file_writes_run_off_the_event_loop(env, monkeypatch):
    from app.export import service as export_service

    run_id = await _start_run(env)
    loop_thread = threading.get_ident()
    seen: list[int] = []

    original_render = export_service.render_feed
    original_write = env["store"].write_version
    original_publish = env["store"].publish

    def recording_render(*args, **kwargs):
        seen.append(threading.get_ident())
        return original_render(*args, **kwargs)

    def recording_write(*args, **kwargs):
        seen.append(threading.get_ident())
        return original_write(*args, **kwargs)

    def recording_publish(*args, **kwargs):
        seen.append(threading.get_ident())
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(export_service, "render_feed", recording_render)
    monkeypatch.setattr(env["store"], "write_version", recording_write)
    monkeypatch.setattr(env["store"], "publish", recording_publish)

    await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)

    assert len(seen) == 3
    assert all(thread_id != loop_thread for thread_id in seen)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest tests/test_export_service.py::test_export_render_and_file_writes_run_off_the_event_loop -q`
Expected: FAIL — `assert all(...)` fails because the recorded thread id equals the loop thread.

- [ ] **Step 3: Offload render and store calls**

In `backend/app/export/service.py`, add `import asyncio` as the first import.

In `export_for_run`, replace:

```python
            channel = channel_metadata_for(feed_source, client_name, self._public_base_url)
            data = render_feed(products, registry, channel)
```

with:

```python
            channel = channel_metadata_for(feed_source, client_name, self._public_base_url)
            data = await asyncio.to_thread(render_feed, products, registry, channel)
```

Replace `self._store.write_version(feed_source_id, version_number, data)` with:

```python
                    await asyncio.to_thread(
                        self._store.write_version, feed_source_id, version_number, data
                    )
```

Replace `self._store.publish(feed_source_id, data)` with:

```python
                await asyncio.to_thread(self._store.publish, feed_source_id, data)
```

Make `_load_version_products` async and offload the read — replace:

```python
    def _load_version_products(
        self, feed_source_id: int, version_number: int, registry: RegistryDocument
    ) -> dict[str, dict[str, Any]]:
        data = self._store.read_version(feed_source_id, version_number)
```

with:

```python
    async def _load_version_products(
        self, feed_source_id: int, version_number: int, registry: RegistryDocument
    ) -> dict[str, dict[str, Any]]:
        data = await asyncio.to_thread(
            self._store.read_version, feed_source_id, version_number
        )
```

Update its two call sites in `diff`:

```python
        new_products = await self._load_version_products(feed_source_id, version_number, registry)
        old_products = await self._load_version_products(feed_source_id, against, registry)
```

In `version_content`, replace `data = self._store.read_version(feed_source_id, version_number)` with:

```python
        data = await asyncio.to_thread(
            self._store.read_version, feed_source_id, version_number
        )
```

In `rollback`, replace its three store/render calls:

```python
        data = self._store.read_version(feed_source_id, version_number)
```
→
```python
        data = await asyncio.to_thread(
            self._store.read_version, feed_source_id, version_number
        )
```
```python
        rendered = render_feed(products, registry, channel)
```
→
```python
        rendered = await asyncio.to_thread(render_feed, products, registry, channel)
```
```python
                self._store.write_version(feed_source_id, new_number, rendered)
```
→
```python
                await asyncio.to_thread(
                    self._store.write_version, feed_source_id, new_number, rendered
                )
```
```python
            self._store.publish(feed_source_id, rendered)
```
→
```python
            await asyncio.to_thread(self._store.publish, feed_source_id, rendered)
```

Leave `published_exists` and `delete_version_file` calls synchronous.

- [ ] **Step 4: Run the export tests and static gates**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest tests/test_export_service.py tests/test_export_store.py tests/test_export_renderer.py tests/test_export_history_api.py tests/test_export_rollback_api.py tests/test_export_public.py tests/test_export_publish_audit.py -q`
Expected: PASS (new test plus all existing export behavior).

Run: `uv run ruff check . ../plugins && uv run mypy .`
Expected: both exit 0.

- [ ] **Step 5: Commit**

```bash
git add backend/app/export/service.py backend/tests/test_export_service.py
git commit -m "perf(export): render and write feed files off the event loop"
```

---

### Task 5: Documentation and decision log

**Files:**
- Modify: `backend/AGENTS.md:108`
- Modify: `backend/docs/plugins.md`
- Modify: `backend/docs/architecture.md`
- Modify: `docs/decisions.md`

**Interfaces:**
- Consumes: the code from Tasks 1–4.
- Produces: docs only.

- [ ] **Step 1: Correct the false AGENTS.md export claim**

In `backend/AGENTS.md`, replace:

```
- `app/export/service.py` streams output rather than building the full feed in memory above the threshold documented in `docs/architecture.md`.
```

with:

```
- `app/export/service.py` renders the feed in memory but runs `render_feed` and the version/publish file writes off the event loop via `asyncio.to_thread` (single-worker deployment); streaming to file is future work if peak memory becomes a problem.
```

- [ ] **Step 2: Document plugin threading/timeout and per-instance state**

In `backend/docs/plugins.md`, immediately after the `### prepare_run(...)` paragraph, add:

```markdown
Both `prepare_run` and `process` run in a worker thread under a hard
`PLUGIN_CALL_TIMEOUT_S = 30` ceiling (`app/pipeline/steps.py`). A hook that
exceeds it is recorded as a product error and the run continues; the worker
thread is abandoned, not killed (Python cannot cancel a running thread). Run
state is keyed per pipeline instance (position), so two instances of the same
plugin never share it.
```

- [ ] **Step 3: Add the event-loop-safety note to architecture.md**

In `backend/docs/architecture.md`, after the `## Pipeline Stages (Fixed Order)` table (immediately before `### Ingest Details`), add:

```markdown
### Event-loop safety (single-worker deployment)

- **Export:** `render_feed` and the `ExportFileStore` version/publish writes run via `asyncio.to_thread`; `is_file`/`unlink` metadata ops stay on the loop.
- **Plugins:** synchronous `prepare_run`/`process` hooks run in the executor under `PLUGIN_CALL_TIMEOUT_S = 30`; a timeout marks the product errored and abandons the thread (it cannot be killed).
- **QC image probe:** the Pillow decode runs via `asyncio.to_thread`.
```

- [ ] **Step 4: Record the decisions**

In `docs/decisions.md`, append under the existing `## 2026-09-19` section (after the frontend-remediation entry):

```markdown
### Event-loop relief (B3/B4/B5/B9)

**Topic:** Fix the 2026-09-17 backend review's event-loop findings.

**Decision:** Export keeps its in-memory renderer but `render_feed` and the version/publish file writes run via `asyncio.to_thread`; metadata ops (`is_file`, `unlink`) stay on the loop. The synchronous plugin contract is unchanged, but every `prepare_run`/`process` call now runs in the executor under `PLUGIN_CALL_TIMEOUT_S = 30` (`app/pipeline/steps.py`), and plugin run state is keyed per instance (`position`) instead of manifest id. Pillow image decode runs via `asyncio.to_thread`. No streaming renderer, threshold, async plugin contract, or schema change.

**Rationale:** The deployment runs one uvicorn worker, so any sync work in an async path stalls requests and the scheduler. `to_thread` is the smallest change that removes the stall without touching the renderer/store APIs or the plugin contract. A timed-out call abandons its thread (Python cannot kill it); this is safe because the product is errored and discarded and plugin calls are sequential, so the executor is not starved. Streaming export stays deferred until peak memory is measured as a problem.

**Non-goals:** `B8` image-dimension insert race, `routes/clients.py` sync unlink, `B6`/`B7` write/scan amplification.
```

- [ ] **Step 5: Verify docs build/consistency and commit**

Run: `uv run ruff check . ../plugins`
Expected: exit 0 (docs don't affect it, but confirms the tree is otherwise clean).

```bash
git add backend/AGENTS.md backend/docs/plugins.md backend/docs/architecture.md docs/decisions.md
git commit -m "docs: record event-loop relief decisions and behavior"
```

---

## Final Verification

- [ ] `cd backend && uv run ruff check . ../plugins` → exit 0.
- [ ] `cd backend && uv run mypy .` → success from 30x source files.
- [ ] `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/postgres uv run pytest -q` → all pass (compare against the pre-change count; it must not drop).
- [ ] Confirm `app/export/service.py` no longer calls `render_feed`/`write_version`/`publish`/`read_version` without `asyncio.to_thread`.
- [ ] Confirm `app/pipeline/steps.py` has `PLUGIN_CALL_TIMEOUT_S`, `_call_plugin`, and no unkeyed `run_states[instance["plugin"]]`.

## Self-Review (completed by plan author)

- **Spec coverage:** B3 → Task 4 + Task 5 docs; B4 → Task 2 + Task 5 docs; B5 → Task 1 + Task 5 docs; B9 → Task 3 + Task 5 docs. Non-goals are stated in Task 5. All covered.
- **Placeholder scan:** no TBD/TODO; every code step shows the exact replacement.
- **Type consistency:** `_call_plugin`/`PLUGIN_CALL_TIMEOUT_S` names are identical across Tasks 1–2 and Task 5; `_image_size` is used only in Task 3; `_load_version_products` is made `async` and both call sites are awaited in the same task; `run_states`/`accepts_state` key name `key` is consistent within Task 1's blocks.
