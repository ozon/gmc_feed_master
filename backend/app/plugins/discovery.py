"""Plugin discovery, database registration, and route mounting."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from fastapi import APIRouter, FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plugin import Plugin
from app.plugins.loader import PluginLoadError, load_plugin_class
from app.plugins.manifest import ManifestError, PluginManifest, parse_manifest

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "plugin.json"
_RESERVED_SUBPATHS = ("/config", "/data")


@dataclass
class Candidate:
    manifest: PluginManifest
    directory: Path
    instance: Any
    core: bool
    router: APIRouter | None


def _iter_plugin_dirs(plugins_dir: Path) -> Sequence[tuple[Path, bool]]:
    found: list[tuple[Path, bool]] = []
    if not plugins_dir.is_dir():
        return found
    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == "core":
            for sub in sorted(entry.iterdir()):
                if sub.is_dir():
                    found.append((sub, True))
        else:
            found.append((entry, False))
    return found


def collect_router(candidate: Candidate) -> APIRouter | None:
    register = getattr(candidate.instance, "register_routes", None)
    if not callable(register):
        return None
    router = APIRouter()
    register(router)
    for route in router.routes:
        path = getattr(route, "path", "")
        for reserved in _RESERVED_SUBPATHS:
            if path == reserved or path.startswith(reserved + "/"):
                raise PluginLoadError(
                    f"plugin {candidate.manifest.id}: route path {path!r} collides "
                    f"with the reserved prefix {reserved!r}"
                )
    return router


def discover(plugins_dir: Path) -> tuple[list[Candidate], list[str]]:
    plugins_dir = Path(plugins_dir)
    candidates: list[Candidate] = []
    reasons: list[str] = []
    for directory, core in _iter_plugin_dirs(plugins_dir):
        manifest_path = directory / MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        label = directory.name
        try:
            manifest = parse_manifest(json.loads(manifest_path.read_text()))
        except ManifestError as exc:
            reasons.append(f"plugin {label}: invalid manifest: {exc.reason}")
            continue
        except (OSError, json.JSONDecodeError) as exc:
            reasons.append(f"plugin {label}: unreadable manifest: {exc}")
            continue
        try:
            instance = load_plugin_class(directory, manifest)
            candidate = Candidate(
                manifest=manifest,
                directory=directory,
                instance=instance,
                core=core,
                router=None,
            )
            candidate.router = collect_router(candidate)
        except PluginLoadError as exc:
            reasons.append(str(exc))
            continue
        candidates.append(candidate)
    return candidates, reasons


async def register_candidates(
    session: AsyncSession, candidates: Sequence[Candidate]
) -> dict[str, int]:
    pk_by_id: dict[str, int] = {}
    for candidate in candidates:
        result = await session.execute(
            select(Plugin).where(Plugin.name == candidate.manifest.id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = Plugin(
                name=candidate.manifest.id,
                version=candidate.manifest.version,
                manifest=candidate.manifest.raw,
                enabled=candidate.core,
            )
            session.add(row)
            await session.flush()
        else:
            row.version = candidate.manifest.version
            row.manifest = candidate.manifest.raw
            await session.flush()
        pk_by_id[candidate.manifest.id] = row.id
    return pk_by_id


async def discover_and_mount(app: FastAPI) -> None:
    plugins_dir = app.state.plugins_dir
    candidates, rejected = discover(Path(plugins_dir))

    factory = getattr(app.state, "db_session_factory", None)
    if factory is not None and candidates:
        async with factory() as session:
            async with session.begin():
                await register_candidates(session, candidates)

    registry: dict[str, Any] = app.state.plugin_registry
    for candidate in candidates:
        registry[candidate.manifest.id] = candidate.instance
        if candidate.router is not None:
            app.include_router(candidate.router, prefix=f"/plugins/{candidate.manifest.id}")

    logger.info("plugins: %d registered, %d rejected", len(candidates), len(rejected))
    for reason in rejected:
        logger.warning("plugin rejected: %s", reason)
