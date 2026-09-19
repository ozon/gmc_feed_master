# Event-Loop Relief (B3, B4, B5, B9) — Design

**Date:** 2026-09-19
**Status:** Approved (design), pending implementation plan
**Scope:** Backend only. Move blocking work off the event loop: export render + file I/O (`B3`), plugin execution with a hard timeout (`B4`) and per-instance run-state keying (`B5`), and image decode (`B9`). Source findings: `docs/reports/2026-09-17-01-backend.md`. Out of scope: `B8` (image-dimension insert race) and the sync `unlink` in `app/routes/clients.py`.

## Problem

The production deployment is a single uvicorn worker (`backend/AGENTS.md`: "backend runs exactly one worker/replica"). Any synchronous work inside an `async def` therefore stalls every concurrent request **and** the in-process APScheduler.

- **B3 — export.** `render_feed` (`app/export/renderer.py:63-87`) accumulates the entire feed as a list of strings and joins it into one `bytes`. `ExportFileStore` (`app/export/store.py`) does blocking `write_bytes` / `read_bytes` / `os.replace`, and `ExportService` (`app/export/service.py`) calls it — plus `render_feed` itself — directly from `async` methods, including inside an open DB transaction. This both blocks the loop and holds one full copy of the feed in memory (plus the temp write).
- **B4 — plugins.** `PluginStep.execute` (`app/pipeline/steps.py:206-298`) calls synchronous `prepare_run(...)` and `plugin_obj.process(...)` directly, with no `asyncio.wait_for`. AGENTS.md explicitly requires "a per-plugin `asyncio.wait_for` timeout so a hanging plugin can't stall the per-feed-source lock"; it does not exist.
- **B5 — plugin state.** `run_states` and `accepts_state` (`app/pipeline/steps.py:216-217`) are keyed by `instance["plugin"]` (manifest id). Two instances of the same plugin in one pipeline overwrite each other's `prepare_run` state.
- **B9 — image decode.** `Image.open(BytesIO(body)).size` (`app/qc/image_probe.py:51`) decodes on the loop.

Correction to the record: AGENTS.md's claim that export "streams output rather than building the full feed in memory above the threshold documented in `docs/architecture.md`" is false — `docs/architecture.md` defines no threshold. `B3` is real and the doc line is itself a bug fixed by this design.

## Decision

| Topic | Decision |
|-------|----------|
| Export scope | Offload heavy work to the default executor with `asyncio.to_thread`; **no** streaming renderer, **no** size threshold, no renderer signature change |
| Which export calls offload | `render_feed`, `ExportFileStore.write_version`, `.publish`, `.read_version` |
| Which stay on-loop | Cheap metadata ops: `.published_exists` (`is_file()` stat) and `.delete_version_file` (`unlink()`) |
| Plugin contract | Stays synchronous (`def process(...) -> dict \| None`); no plugin changes |
| Plugin execution | `asyncio.to_thread` + `asyncio.wait_for`, one hard timeout per call |
| Plugin timeout source | Module constant `PLUGIN_CALL_TIMEOUT_S = 30` in `app/pipeline/steps.py` |
| Plugin run state | Keyed by instance identity — `instance.get("position", index)` — not manifest id |
| Image decode | `asyncio.to_thread` around a small `_image_size(body)` helper |

Rationale: the harm being fixed is **event-loop stall** on a one-worker deployment, not peak memory. `asyncio.to_thread` moves the blocking work to the default thread pool (smallest correct change) without touching the renderer/store APIs or any caller. Threading plugins preserves the published, tested synchronous plugin contract and needs no plugin or contract-test changes. The timeout location (`steps.py`) is the single choke point both `PipelineRunner` and `dry_run` go through.

## Alternatives considered

- **True streaming export** (renderer yields chunks, written incrementally to the temp file). Lower peak memory and still off-loop, but rewrites `render_feed`'s signature and `ExportFileStore`, and changes every export/renderer test. Rejected: memory is not the measured harm; defer until a real large-catalog memory problem appears.
- **Threshold-gated hybrid** (stream above N products). Requires inventing and documenting the threshold that does not exist today. Rejected as speculative.
- **Require async plugins** (`async def process`). `wait_for` would then truly cancel. Rejected: breaking plugin-contract change to 6 built-in plugins, the contract checker, docs, and tests, for no benefit over threads at this scale.
- **Hybrid sync/async detection.** Supports both calling conventions at the cost of two execution paths and more branching. Rejected: current contract is sync-only; adding a second path is unused flexibility.
- **Manifest/global-setting timeout.** Per-plugin tuning via `plugin.json` or `GlobalSetting`. Rejected: schema/migration surface for a value that does not vary in practice; a constant is tunable in code and can be promoted later if a plugin ever needs more.
- **DB advisory lock for timeouts / running plugins in a subprocess.** Out of scope; a thread boundary fixes the loop stall. A leaked thread is accepted and documented (see Risks).

## Design

### 1. Export off-loop (`B3`)

File: `app/export/service.py`.

- Offload every heavy call with `asyncio.to_thread(...)`:
  - `export_for_run`: `render_feed(...)`, `self._store.write_version(...)` (inside the transaction), `self._store.publish(...)`. The exception-path `delete_version_file` and `published_exists` stay synchronous (metadata ops).
  - `rollback`: `render_feed(...)`, `write_version`, `publish`, and the `read_version` used to re-parse the source version.
  - `_load_version_products`: becomes `async def` so it can `await asyncio.to_thread(self._store.read_version, ...)`; its two call sites in `diff` are awaited.
  - `version_content`: `read_version` offloaded.
- Leave `published_exists` and `delete_version_file` synchronous: `is_file()`/`unlink()` are metadata-only and the `to_thread` hop would cost more than the syscall. This is a deliberate line, not an oversight.
- Error/rollback semantics, dedup logic, retention pruning, and the atomic `temp → os.replace` sequence are unchanged. Only the execution context moves.
- Note: `render_feed` runs before the `with_for_update()` lock is taken, exactly as today, so the lock hold time is unaffected.

### 2. Plugin execution (`B4`) and per-instance state (`B5`)

File: `app/pipeline/steps.py`.

- Add `import asyncio` and module constant `PLUGIN_CALL_TIMEOUT_S = 30`.
- Add one helper used by both call sites (reading the module constant at call time so tests can monkeypatch it):

  ```python
  async def _call_plugin(fn, *args, **kwargs):
      return await asyncio.wait_for(
          asyncio.to_thread(fn, *args, **kwargs), PLUGIN_CALL_TIMEOUT_S
      )
  ```

- `prepare_run(...)` → `await _call_plugin(prepare, config, data, rctx)`.
- `process(...)` → `await _call_plugin(plugin_obj.process, current, config, data, rctx, [state=...])` in both the accepts-state and no-state branches.
- The existing `except Exception` around `process` catches `TimeoutError` (an `Exception` subclass on Python 3.11) and records the product as `errored`, preserving current abort semantics; a distinct timeout log line is added for operators. `prepare_run` failures keep propagating as today.
- **B5 keying:** iterate `for index, instance in enumerate(bundle.get("instances", []))` and compute `key = instance.get("position", index)`. Use that same key for `accepts_state`/`run_states` at both `prepare_run` (warm) and `process` (read). Production `resolve_config_bundle` always sets `position`; the index fallback keeps hand-built test bundles working.
- `dry_run` benefits automatically: it invokes the same `PluginStep`.

Caveat (documented in code and docs): `asyncio.wait_for` cancels the `await`, not the OS thread. A timed-out plugin call keeps running in the background. This is safe here because the affected product is marked errored and excluded from survivors, and `current` is run-local; the only shared object a leaked call could touch is `RunContext.run_state` (`rule_ai_pending`). The default executor bounds concurrency; PluginStep calls plugins sequentially, so contention is low.

### 3. Image decode (`B9`)

File: `app/qc/image_probe.py`.

- Add module helper:

  ```python
  def _image_size(body: bytes) -> tuple[int, int]:
      return Image.open(BytesIO(body)).size
  ```

- Replace the inline decode with `width, height = await asyncio.to_thread(_image_size, body)`.
- Semaphore, size cap, cache read/write, and error caching are unchanged.

## Tests

- `tests/test_plugin_step.py`
  - **B5:** two instances of one plugin, both declaring `prepare_run` state (e.g. a counter/handle), receive distinct state; assert instance two does not see instance one's state. Give each bundle entry a distinct `position`.
  - **B4:** monkeypatch `steps.PLUGIN_CALL_TIMEOUT_S` to a small value and use a plugin whose `process` sleeps beyond it on one product; assert that product counts as `errored`, other products still process, and no survivor carries the timed-out mutation. (Tiny patch `time.sleep`-based; runs in the thread, so the loop stays responsive.)
- `tests/test_export_service.py`
  - Off-loop proof: a fake store whose `write_version`/`publish` records `threading.get_ident()`; capture the loop's own `threading.get_ident()` before the call and assert the recorded id differs (the write ran in a worker thread). Deterministic, no timing.
  - Existing export for-run/rollback/diff tests remain the behavior guard.
- `tests/test_image_probe.py`
  - Add a `_image_size` unit (valid JPEG bytes → expected dimensions). Existing probe paths already exercise the offloaded decode end to end.

## Verification

- `uv run ruff check . ../plugins` → exit 0; `uv run mypy .` → clean (both hard gates).
- Targeted: `uv run pytest tests/test_plugin_step.py tests/test_export_service.py tests/test_export_store.py tests/test_image_probe.py tests/test_export_renderer.py tests/test_export_history_api.py tests/test_export_rollback_api.py tests/test_export_public.py`.
- Full: `TEST_DATABASE_URL=… uv run pytest` green (no count regression).
- Manual smoke (optional): a `process` that blocks does not prevent a concurrent trivial coroutine from completing within the timeout window.

## Docs

Required by the repo's "docs in the same commit" rule:

- `backend/AGENTS.md` — remove/replace the false "streams output … above the threshold documented in `docs/architecture.md`" line with the actual behavior: export renders in memory but runs render + file writes via `asyncio.to_thread`; plugin calls run in the executor under `PLUGIN_CALL_TIMEOUT_S`. (The plugin-timeout sentence is already there and becomes true.)
- `backend/docs/plugins.md` — note the enforced per-call timeout (and that a timed-out thread is abandoned, not killed) and that `prepare_run` state is per **instance**, not per plugin id.
- `backend/docs/architecture.md` — short note under the Export step / pipeline stage on off-loop rendering and file I/O, plugin timeout, and off-loop image decode.
- `docs/decisions.md` — dated entry recording the four decisions (to_thread offload, thread+timeout sync plugin contract, per-instance keying, `PLUGIN_CALL_TIMEOUT_S = 30`) and the known leaked-thread limitation.

## Risks and non-goals

- **Leaked thread on timeout.** The OS thread cannot be cancelled. Impact is bounded: the product is errored, `current` is discarded, and the executor caps concurrency. Documented; a subprocess/`multiprocessing` sandbox is the escape hatch if a plugin ever hangs destructively.
- **Default executor sizing.** `asyncio.to_thread` uses the default `ThreadPoolExecutor` (default max workers grows with CPU). Export does one render at a time per run; PluginStep is sequential per product, so no starvation is expected. If concurrent runs ever saturate it, give the export/plugin work a dedicated executor.
- **`to_thread` overhead** on many small reads (e.g. `diff` over two small versions) is a few context switches — negligible versus blocking the loop.
- **Non-goals:** streaming export, size thresholds, async plugin contract, manifest/schema changes, `B8`, `routes/clients.py` sync unlink, and any performance work covered by `B6`/`B7`.

## References

- `docs/reports/2026-09-17-01-backend.md` findings `B3`, `B4`, `B5`, `B9`; overview `docs/reports/2026-09-17-00-review-overview.md`.
- `app/export/service.py`, `app/export/renderer.py`, `app/export/store.py`, `app/pipeline/steps.py`, `app/pipeline/dry_run.py`, `app/qc/image_probe.py`.
- `backend/AGENTS.md` (async conventions, plugin timeout requirement), `backend/docs/plugins.md`, `backend/docs/architecture.md`.
