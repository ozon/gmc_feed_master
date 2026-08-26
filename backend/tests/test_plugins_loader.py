"""Tests for plugin module loader (Task 3)."""

import sys
import textwrap

import pytest

from app.plugins.loader import PluginLoadError, load_plugin_class
from app.plugins.manifest import PluginManifest, parse_manifest


def make_manifest(**overrides) -> PluginManifest:
    doc = {
        "id": "my_plugin",
        "name": "My Plugin",
        "version": "1.0.0",
        "extension_point": "pipeline_module",
        "config_schema": {},
        "data_schema": {},
    }
    doc.update(overrides)
    return parse_manifest(doc)


def write_plugin(directory, content: str, filename: str = "plugin.py") -> None:
    (directory / filename).write_text(textwrap.dedent(content))


class GoodPlugin:
    def process(self, item):
        return item


class TestHappyPaths:
    def test_default_convention_loads_plugin_plugin(self, tmp_path):
        write_plugin(
            tmp_path,
            """
            class Plugin:
                def process(self, item):
                    return item * 2
            """,
        )
        plugin = load_plugin_class(tmp_path, make_manifest())
        assert plugin.process(3) == 6

    def test_explicit_entry_point_module_class(self, tmp_path):
        write_plugin(
            tmp_path,
            """
            class Widget:
                def process(self, item):
                    return f"widget:{item}"
            """,
            filename="widgets.py",
        )
        manifest = make_manifest()
        manifest.raw["entry_point"] = "widgets:Widget"
        plugin = load_plugin_class(tmp_path, manifest)
        assert plugin.process(1) == "widget:1"

    def test_two_plugins_with_different_ids_load_independently(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        write_plugin(
            dir_a,
            """
            class Plugin:
                def __init__(self):
                    self.tag = "a"
                def process(self, item):
                    return self.tag
            """,
        )
        write_plugin(
            dir_b,
            """
            class Plugin:
                def __init__(self):
                    self.tag = "b"
                def process(self, item):
                    return self.tag
            """,
        )
        plugin_a = load_plugin_class(dir_a, make_manifest(id="plugin_a"))
        plugin_b = load_plugin_class(dir_b, make_manifest(id="plugin_b"))
        assert plugin_a.process(None) == "a"
        assert plugin_b.process(None) == "b"
        assert "gmc_plugin_plugin_a" in sys.modules
        assert "gmc_plugin_plugin_b" in sys.modules


class TestFailureModes:
    def test_entry_point_missing_colon_raises(self, tmp_path):
        write_plugin(tmp_path, "")
        manifest = make_manifest()
        manifest.raw["entry_point"] = "no_colon_here"
        with pytest.raises(PluginLoadError, match="entry_point"):
            load_plugin_class(tmp_path, manifest)

    def test_entry_point_empty_parts_raise(self, tmp_path):
        write_plugin(tmp_path, "")
        manifest = make_manifest()
        manifest.raw["entry_point"] = ":ClassName"
        with pytest.raises(PluginLoadError, match="entry_point"):
            load_plugin_class(tmp_path, manifest)

    def test_module_file_missing_raises(self, tmp_path):
        with pytest.raises(PluginLoadError, match="not found"):
            load_plugin_class(tmp_path, make_manifest())

    def test_explicit_entry_point_file_missing_raises(self, tmp_path):
        write_plugin(tmp_path, "")  # only default plugin.py exists
        manifest = make_manifest()
        manifest.raw["entry_point"] = "elsewhere:Thing"
        with pytest.raises(PluginLoadError, match="not found"):
            load_plugin_class(tmp_path, manifest)

    def test_exec_raises_is_wrapped(self, tmp_path):
        write_plugin(
            tmp_path,
            """
            raise RuntimeError("boom at import")
            """,
        )
        with pytest.raises(PluginLoadError, match="boom at import"):
            load_plugin_class(tmp_path, make_manifest())

    def test_attribute_missing_raises(self, tmp_path):
        write_plugin(
            tmp_path,
            """
            class NotPlugin:
                pass
            """,
        )
        with pytest.raises(PluginLoadError, match="Plugin"):
            load_plugin_class(tmp_path, make_manifest())

    def test_instantiation_raises_is_wrapped(self, tmp_path):
        write_plugin(
            tmp_path,
            """
            class Plugin:
                def __init__(self):
                    raise ValueError("cannot construct")
                def process(self, item):
                    return item
            """,
        )
        with pytest.raises(PluginLoadError, match="cannot construct"):
            load_plugin_class(tmp_path, make_manifest())

    def test_process_not_callable_raises(self, tmp_path):
        write_plugin(
            tmp_path,
            """
            class Plugin:
                process = 42
            """,
        )
        with pytest.raises(PluginLoadError, match="process"):
            load_plugin_class(tmp_path, make_manifest())

    def test_process_missing_raises(self, tmp_path):
        write_plugin(
            tmp_path,
            """
            class Plugin:
                pass
            """,
        )
        with pytest.raises(PluginLoadError, match="process"):
            load_plugin_class(tmp_path, make_manifest())
