"""Plugin manifest parsing and validation."""

import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

_ID_RE: re.Pattern = re.compile(r"^[a-z][a-z0-9_]*$")

_ALLOWED_SCOPES: frozenset[str] = frozenset({"global", "client", "feed_source"})

_REQUIRED_KEYS = ("id", "name", "version", "extension_point", "config_schema", "data_schema")


class ManifestError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    extension_point: str
    config_schema: dict[str, Any]
    data_schema: dict[str, Any]
    config_scope: tuple[str, ...]
    data_scope: tuple[str, ...]
    raw: dict[str, Any]


def _parse_scope(doc: dict[str, Any], key: str) -> tuple[str, ...]:
    value = doc.get(key)
    if value is None:
        return ("global",)
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        if not value:
            raise ManifestError(f"{key} must not be empty")
        items = list(value)
    else:
        raise ManifestError(f"{key} must be a string or a list of strings")
    for item in items:
        if item not in _ALLOWED_SCOPES:
            raise ManifestError(
                f"{key} contains undeclared scope {item!r}; "
                f"allowed scopes are {sorted(_ALLOWED_SCOPES)}"
            )
    return tuple(items)


def _parse_config_merge(data: dict[str, Any]) -> None:
    value = data.get("config_merge")
    if value is None:
        return
    if not isinstance(value, dict) or not value:
        raise ManifestError("config_merge must be a non-empty object")
    for key, hint in value.items():
        if not isinstance(key, str) or not key:
            raise ManifestError("config_merge keys must be non-empty strings")
        if not isinstance(hint, dict) or hint.get("strategy") != "union_by_key":
            raise ManifestError(
                f"config_merge.{key}: strategy must be 'union_by_key'"
            )
        merge_key = hint.get("key", "id")
        if not isinstance(merge_key, str) or not merge_key:
            raise ManifestError(f"config_merge.{key}.key must be a non-empty string")
        hint.setdefault("key", merge_key)


def parse_manifest(data: Any) -> PluginManifest:
    if not isinstance(data, dict):
        raise ManifestError("manifest document must be a JSON object")

    missing = [key for key in _REQUIRED_KEYS if key not in data]
    if missing:
        raise ManifestError(f"manifest is missing required keys: {', '.join(missing)}")

    plugin_id = data["id"]
    if not isinstance(plugin_id, str) or not _ID_RE.fullmatch(plugin_id):
        raise ManifestError(
            f"manifest id {plugin_id!r} must match {_ID_RE.pattern}"
        )

    for field in ("name", "version"):
        value = data[field]
        if not isinstance(value, str) or not value:
            raise ManifestError(f"manifest {field} must be a non-empty string")

    extension_point = data["extension_point"]
    if extension_point != "pipeline_module":
        raise ManifestError(
            f"unsupported extension_point {extension_point!r}; "
            "only 'pipeline_module' is allowed"
        )

    schemas: dict[str, dict[str, Any]] = {}
    for field in ("config_schema", "data_schema"):
        schema = data[field]
        if not isinstance(schema, dict):
            raise ManifestError(f"manifest {field} must be an object")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ManifestError(
                f"manifest {field} is not a valid 2020-12 JSON Schema: {exc.message}"
            ) from exc
        schemas[field] = schema

    _parse_config_merge(data)

    return PluginManifest(
        id=plugin_id,
        name=data["name"],
        version=data["version"],
        extension_point=extension_point,
        config_schema=schemas["config_schema"],
        data_schema=schemas["data_schema"],
        config_scope=_parse_scope(data, "config_scope"),
        data_scope=_parse_scope(data, "data_scope"),
        raw=data,
    )
