"""Contract + discovery tests for the filter core plugin (mirrors rules contract test)."""

from pathlib import Path

PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"


def _filters_of(candidates):
    return [c for c in candidates if c.manifest.id == "filter"]


def test_filter_discovered_as_core():
    from app.plugins.discovery import discover

    candidates, rejected = discover(PLUGINS_DIR)
    filters = _filters_of(candidates)
    assert filters and filters[0].core is True
    assert all("filter" not in r for r in rejected)


def test_filter_manifest_fields():
    from app.plugins.discovery import discover

    candidates, _ = discover(PLUGINS_DIR)
    filters = _filters_of(candidates)
    assert filters, "filter plugin not discovered"
    manifest = filters[0].manifest
    assert manifest.config_scope == ("global", "client", "feed_source")
    assert manifest.data_scope == ("global", "client", "feed_source")
    frontend = manifest.raw.get("frontend")
    assert frontend and frontend.get("menu_item")
    assert frontend.get("component") == "component.tsx"


def test_filter_passes_contract():
    from app.plugins.contract import contract_violations
    from app.plugins.discovery import discover

    candidates, _ = discover(PLUGINS_DIR)
    filters = _filters_of(candidates)
    assert filters, "filter plugin not discovered"
    assert contract_violations(filters[0]) == []
