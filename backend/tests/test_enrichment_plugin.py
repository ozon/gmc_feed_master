"""EnrichmentPlugin tests: config validation, pin application by product id."""

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "enrichment_plugin",
    Path(__file__).resolve().parents[2] / "plugins/core/enrichment/plugin.py",
)
assert _spec is not None and _spec.loader is not None
_enrichment_module = importlib.util.module_from_spec(_spec)
sys.modules["enrichment_plugin"] = _enrichment_module
_spec.loader.exec_module(_enrichment_module)

EnrichmentPlugin = _enrichment_module.EnrichmentPlugin
validate_config = _enrichment_module.validate_config

pytestmark = pytest.mark.asyncio


def test_validate_config_requires_nonempty_target_fields():
    with pytest.raises(ValueError):
        validate_config({"targetFields": []})
    with pytest.raises(ValueError):
        validate_config({"targetFields": ["ok", ""]})
    validate_config({"targetFields": ["color", "material"]})
    validate_config({})  # defaults apply


async def test_process_applies_pins_by_product_id():
    state = {"pinned": {"p1": {"color": "blue"}}}
    out = EnrichmentPlugin().process(
        {"id": "p1", "title": "T", "color": "red"}, {}, {}, None, state
    )
    assert out["color"] == "blue"  # pinned wins


async def test_process_passthrough_without_pin():
    product = {"id": "p2", "title": "T"}
    out = EnrichmentPlugin().process(product, {}, {}, None, {"pinned": {"p1": {}}})
    assert out == product
    assert out is product
