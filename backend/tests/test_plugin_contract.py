"""Tests for plugin contract checker (Task 7)."""

import copy
import json
import shutil

import pytest

from app.plugins.contract import contract_violations
from app.plugins.discovery import Candidate, discover
from app.plugins.loader import load_plugin_class
from app.plugins.manifest import PluginManifest, parse_manifest
from app.plugins.runtime import RunContext


FIXTURE_DIR = (
    __import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "example_plugin"
)


def _make_candidate(tmp_path, manifest_override=None, code=None):
    """Build a single-candidate directory in tmp_path and return the candidate."""
    dest = tmp_path / "example_plugin"
    shutil.copytree(FIXTURE_DIR, dest)
    if manifest_override is not None:
        (dest / "plugin.json").write_text(json.dumps(manifest_override))
    if code is not None:
        (dest / "plugin.py").write_text(code)
    candidates, _ = discover(tmp_path)
    assert len(candidates) == 1, f"expected 1 candidate, got {len(candidates)}"
    return candidates[0]


def _make_direct_candidate(tmp_path, manifest_dict, code=None):
    """Build a Candidate directly, bypassing parse_manifest validation."""
    dest = tmp_path / "example_plugin"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "plugin.json").write_text(json.dumps(manifest_dict))
    if code is not None:
        (dest / "plugin.py").write_text(code)
    else:
        shutil.copy(FIXTURE_DIR / "plugin.py", dest / "plugin.py")

    manifest = PluginManifest(
        id=manifest_dict["id"],
        name=manifest_dict["name"],
        version=manifest_dict["version"],
        extension_point=manifest_dict["extension_point"],
        config_schema=manifest_dict.get("config_schema", {}),
        data_schema=manifest_dict.get("data_schema", {}),
        config_scope=tuple(manifest_dict.get("config_scope", ["global"])),
        data_scope=tuple(manifest_dict.get("data_scope", ["global"])),
        raw=manifest_dict,
    )
    instance = load_plugin_class(dest, manifest)
    return Candidate(
        manifest=manifest,
        directory=dest,
        instance=instance,
        core=False,
        router=None,
    )


# --- positive ---------------------------------------------------------------


class TestExamplePluginPassesContract:
    def test_valid_plugin_no_violations(self, tmp_path):
        candidate = _make_candidate(tmp_path)
        violations = contract_violations(candidate)
        assert violations == []


# --- negative: one targeted violation each -----------------------------------


class TestMetaSchemaViolation:
    def test_invalid_config_schema_returns_violation(self, tmp_path):
        manifest = json.loads((FIXTURE_DIR / "plugin.json").read_text())
        manifest["config_schema"] = {"type": "nope"}
        candidate = _make_direct_candidate(tmp_path, manifest)
        violations = contract_violations(candidate)
        assert len(violations) == 1
        assert "config_schema" in violations[0].lower() or "meta" in violations[0].lower()

    def test_invalid_data_schema_returns_violation(self, tmp_path):
        manifest = json.loads((FIXTURE_DIR / "plugin.json").read_text())
        manifest["data_schema"] = {"type": "nope"}
        candidate = _make_direct_candidate(tmp_path, manifest)
        violations = contract_violations(candidate)
        assert len(violations) == 1
        assert "data_schema" in violations[0].lower() or "meta" in violations[0].lower()


class TestProcessContractViolation:
    def test_process_returns_non_dict_non_none_returns_violation(self, tmp_path):
        code = """
class UpperPlugin:
    def validate_config(self, config):
        pass
    def process(self, product, config, data, ctx):
        return "unexpected string"
"""
        candidate = _make_candidate(tmp_path, code=code)
        violations = contract_violations(candidate)
        assert any("process" in v.lower() for v in violations)

    def test_process_raises_exception_returns_violation(self, tmp_path):
        code = """
class UpperPlugin:
    def validate_config(self, config):
        pass
    def process(self, product, config, data, ctx):
        raise RuntimeError("kaboom")
"""
        candidate = _make_candidate(tmp_path, code=code)
        violations = contract_violations(candidate)
        assert any("process" in v.lower() for v in violations)


class TestOriginalProductMutationViolation:
    def test_process_mutates_original_product_returns_violation(self, tmp_path):
        code = """
class UpperPlugin:
    def validate_config(self, config):
        pass
    def process(self, product, config, data, ctx):
        product["mutated"] = True
        return product
"""
        candidate = _make_candidate(tmp_path, code=code)
        violations = contract_violations(candidate)
        assert any(
            "mutat" in v.lower() or "original" in v.lower() for v in violations
        )


class TestValidateConfigViolation:
    def test_required_property_not_rejected_returns_violation(self, tmp_path):
        """Use the real fixture plugin (validate_config raises on empty) + manifest
        with required. The no-op validate_config in a custom plugin will not raise
        on empty, so config_gating is off and _check_validate_config runs."""
        code = """
class UpperPlugin:
    def validate_config(self, config):
        pass
    def process(self, product, config, data, ctx):
        return product
"""
        candidate = _make_candidate(tmp_path, code=code)
        violations = contract_violations(candidate)
        assert any(
            "validate_config" in v.lower() or "required" in v.lower()
            for v in violations
        )


class TestReservedRouteViolation:
    def test_plugin_with_reserved_config_route_returns_violation(self, tmp_path):
        manifest = json.loads((FIXTURE_DIR / "plugin.json").read_text())
        code = """
from fastapi import APIRouter

class UpperPlugin:
    def validate_config(self, config):
        pass
    def process(self, product, config, data, ctx):
        return product
    def register_routes(self, router: APIRouter):
        router.add_api_route("/config/thing", lambda: {})
"""
        candidate = _make_direct_candidate(tmp_path, manifest, code=code)
        violations = contract_violations(candidate)
        assert any(
            "route" in v.lower() or "config" in v.lower() for v in violations
        )

    def test_plugin_with_reserved_data_route_returns_violation(self, tmp_path):
        manifest = json.loads((FIXTURE_DIR / "plugin.json").read_text())
        code = """
from fastapi import APIRouter

class UpperPlugin:
    def validate_config(self, config):
        pass
    def process(self, product, config, data, ctx):
        return product
    def register_routes(self, router: APIRouter):
        router.add_api_route("/data/export", lambda: {})
"""
        candidate = _make_direct_candidate(tmp_path, manifest, code=code)
        violations = contract_violations(candidate)
        assert any(
            "route" in v.lower() or "data" in v.lower() for v in violations
        )
