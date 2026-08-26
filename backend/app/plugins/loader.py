"""Plugin module loading from a validated manifest and plugin directory."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

from app.plugins.manifest import PluginManifest

DEFAULT_MODULE = "plugin"
DEFAULT_ATTRIBUTE = "Plugin"


class PluginLoadError(Exception):
    pass


def _entry_point_parts(manifest: PluginManifest) -> tuple[str, str]:
    raw_entry_point = manifest.raw.get("entry_point")
    if raw_entry_point is None:
        return DEFAULT_MODULE, DEFAULT_ATTRIBUTE
    if not isinstance(raw_entry_point, str):
        raise PluginLoadError(
            f"plugin {manifest.id}: entry_point must be a string formatted "
            "'module:ClassName'"
        )
    parts = raw_entry_point.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise PluginLoadError(
            f"plugin {manifest.id}: malformed entry_point {raw_entry_point!r}; "
            "expected 'module:ClassName' with non-empty module and class parts"
        )
    return parts[0], parts[1]


def load_plugin_class(directory: Path, manifest: PluginManifest) -> Any:
    directory = Path(directory)
    module_name, attribute_name = _entry_point_parts(manifest)

    file_path = directory / f"{module_name}.py"
    if not file_path.is_file():
        raise PluginLoadError(
            f"plugin {manifest.id}: module file not found: {file_path}"
        )

    unique_module = f"gmc_plugin_{manifest.id}"
    spec = importlib.util.spec_from_file_location(unique_module, file_path)
    if spec is None or spec.loader is None:
        raise PluginLoadError(
            f"plugin {manifest.id}: cannot create import spec for {file_path}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_module] = module
    try:
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise PluginLoadError(
                f"plugin {manifest.id}: error executing module {file_path}: {exc}"
            ) from exc

        plugin_class = getattr(module, attribute_name, None)
        if plugin_class is None:
            raise PluginLoadError(
                f"plugin {manifest.id}: attribute {attribute_name!r} not found "
                f"in {file_path}"
            )

        try:
            instance = plugin_class()
        except Exception as exc:
            raise PluginLoadError(
                f"plugin {manifest.id}: error instantiating {attribute_name!r} "
                f"from {file_path}: {exc}"
            ) from exc

        process = getattr(instance, "process", None)
        if not callable(process):
            raise PluginLoadError(
                f"plugin {manifest.id}: instance of {attribute_name!r} does not "
                "provide a callable 'process' method"
            )
    except BaseException:
        del sys.modules[unique_module]
        raise

    return instance
