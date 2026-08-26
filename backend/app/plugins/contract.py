"""Plugin contract checker — validates a Candidate against contract rules."""

from __future__ import annotations

import copy
import logging
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.plugins.discovery import Candidate, collect_router
from app.plugins.loader import PluginLoadError
from app.plugins.runtime import RunContext


def _check_meta_schema(candidate: Candidate) -> list[str]:
    violations: list[str] = []
    for field in ("config_schema", "data_schema"):
        schema = getattr(candidate.manifest, field)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            violations.append(f"{field} failed meta-schema: {exc.message}")
    return violations


def _check_process(candidate: Candidate) -> list[str]:
    product = {"id": "contract-check", "title": "hello"}
    original = copy.deepcopy(product)
    rctx = RunContext(
        client_id=0,
        feed_source_id=0,
        run_id=0,
        logger=logging.getLogger("contract"),
        original_product=copy.deepcopy(product),
    )
    config: dict[str, Any] = {}
    data: dict[str, Any] = {}
    try:
        result = candidate.instance.process(product, config, data, rctx)
    except Exception:
        return ["process() raised an unexpected exception"]

    if result is not None and not isinstance(result, dict):
        return [f"process() returned {type(result).__name__}, expected dict or None"]

    if product != original:
        return ["process() mutated the original product dict"]

    return []


def _check_validate_config(candidate: Candidate) -> list[str]:
    schema = candidate.manifest.config_schema
    required: list[str] = schema.get("required", [])
    if not required:
        return []
    for name in required:
        payload = {k: "x" for k in schema.get("properties", {}) if k != name}
        try:
            candidate.instance.validate_config(payload)
        except Exception:
            continue
        return [f"validate_config() did not reject missing required property {name!r}"]
    return []


def _check_reserved_routes(candidate: Candidate) -> list[str]:
    try:
        router = collect_router(candidate)
    except PluginLoadError as exc:
        return [str(exc)]
    if router is None:
        return []
    violations: list[str] = []
    for route in router.routes:
        path = getattr(route, "path", "")
        if path.startswith("/config") or path.startswith("/data"):
            violations.append(f"reserved route path {path!r}")
    return violations


def contract_violations(candidate: Candidate) -> list[str]:
    """Return human-readable violations (empty list = pass)."""
    violations: list[str] = []

    violations.extend(_check_meta_schema(candidate))

    config_gated = False
    try:
        candidate.instance.validate_config({})
    except Exception:
        config_gated = True

    if not config_gated:
        violations.extend(_check_process(candidate))
        violations.extend(_check_validate_config(candidate))

    violations.extend(_check_reserved_routes(candidate))

    return violations
