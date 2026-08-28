from pathlib import Path

from app.plugins.contract import contract_violations
from app.plugins.discovery import discover

PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"


def test_example_upper_passes_contract_suite():
    candidates, rejected = discover(PLUGINS_DIR)
    assert rejected == []
    assert [c.manifest.id for c in candidates] == ["example_upper"]
    assert contract_violations(candidates[0]) == []


def test_example_upper_declares_frontend_menu_item():
    candidates, _ = discover(PLUGINS_DIR)
    frontend = candidates[0].manifest.raw.get("frontend")
    assert frontend == {"menu_item": "Example Upper", "icon": "letter-e"}
