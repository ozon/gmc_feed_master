### Task 3: Module loader

**Files:**
- Create: `backend/app/plugins/loader.py`
- Test: `backend/tests/test_plugins_loader.py`

**Interfaces:**
- Consumes: `PluginManifest`.
- Produces: `class PluginLoadError(Exception)`; `def load_plugin_class(directory: Path, manifest: PluginManifest) -> Any` — returns an instantiated plugin object.

Behavior:
- Explicit entry point: `manifest.raw.get("entry_point")` formatted `"module:ClassName"` → loads `<directory>/<module>.py` and gets `ClassName`.
- Default: `plugin.py` / attribute `Plugin`.
- Registers under unique module name `gmc_plugin_{manifest.id}` in `sys.modules` before exec.
- Failure modes → `PluginLoadError`: malformed entry_point, file missing, exec raises, attribute missing, instantiation raises, result lacks callable `process`.

Tests build real temp plugin dirs (write `plugin.py` files with `pathlib`), covering: default convention happy path; explicit entry point; each failure mode; two plugins with different ids loading independently (unique sys.modules names).

TDD: RED → implement → GREEN → commit `feat: plugin module loader with entry-point convention`.

---
