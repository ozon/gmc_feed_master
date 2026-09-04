from pathlib import Path

from app.plugins.contract import contract_violations
from app.plugins.discovery import discover

PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"


def test_example_upper_passes_contract_suite():
    candidates, rejected = discover(PLUGINS_DIR)
    assert rejected == []
    example = next(c for c in candidates if c.manifest.id == "example_upper")
    assert contract_violations(example) == []


def test_example_upper_declares_frontend_menu_item():
    candidates, _ = discover(PLUGINS_DIR)
    example = next(c for c in candidates if c.manifest.id == "example_upper")
    frontend = example.manifest.raw.get("frontend")
    assert frontend == {"menu_item": "Example Upper", "icon": "letter-e"}
