"""Single shared load of plugins/core/category/plugin.py for tests."""

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "category_plugin",
    Path(__file__).resolve().parents[2] / "plugins/core/category/plugin.py",
)
assert _spec is not None and _spec.loader is not None
category_plugin = importlib.util.module_from_spec(_spec)
sys.modules["category_plugin"] = category_plugin
_spec.loader.exec_module(category_plugin)
