"""Single shared load of plugins/core/custom_labels/plugin.py for tests."""

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "custom_labels_plugin",
    Path(__file__).resolve().parents[2] / "plugins/core/custom_labels/plugin.py",
)
assert _spec is not None and _spec.loader is not None
labels_plugin = importlib.util.module_from_spec(_spec)
sys.modules["custom_labels_plugin"] = labels_plugin
_spec.loader.exec_module(labels_plugin)
