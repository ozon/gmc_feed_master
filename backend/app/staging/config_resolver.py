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
            bucket.update(getattr(row, attribute))
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
