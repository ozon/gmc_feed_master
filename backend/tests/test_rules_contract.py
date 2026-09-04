"""Contract + discovery tests for the rules core plugin."""

from pathlib import Path

PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"


def _candidate():
    from app.plugins.discovery import discover

    candidates, _rejected = discover(PLUGINS_DIR)
    rules = [c for c in candidates if c.manifest.id == "rules"]
    assert rules, "rules plugin not discovered"
    return rules[0]


def test_rules_discovered_as_core():
    from app.plugins.discovery import discover

    candidates, rejected = discover(PLUGINS_DIR)
    rules = [c for c in candidates if c.manifest.id == "rules"]
    assert rules and rules[0].core is True
    assert all("rules" not in r for r in rejected)


def test_rules_manifest_fields():
    from app.plugins.discovery import discover

    candidates, _ = discover(PLUGINS_DIR)
    rules = next(c for c in candidates if c.manifest.id == "rules")
    assert rules.manifest.config_scope == ("global", "client", "feed_source")
    assert rules.manifest.data_scope == ("global", "client", "feed_source")
    frontend = rules.manifest.raw.get("frontend")
    assert frontend and frontend.get("menu_item")
    assert frontend.get("component") == "component.tsx"


def test_rules_passes_contract():
    from app.plugins.contract import contract_violations

    violations = contract_violations(_candidate())
    assert violations == []
