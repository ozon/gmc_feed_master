import json

import pytest

from registry.loader import RegistryLoadError, load_registry
from registry.model import AttributeKind


def test_loader_rejects_missing_artifact(tmp_path):
    with pytest.raises(RegistryLoadError, match="missing"):
        load_registry(tmp_path / "missing.json")


def test_loader_rejects_invalid_json(tmp_path):
    artifact = tmp_path / "corrupt.json"
    artifact.write_text("{not valid json")
    with pytest.raises(RegistryLoadError, match="invalid JSON"):
        load_registry(artifact)


def test_loader_rejects_unsupported_version(tmp_path):
    artifact = tmp_path / "v99.json"
    artifact.write_text(json.dumps({
        "version": 99,
        "source_fingerprint": "abc",
        "attributes": {},
    }))
    with pytest.raises(RegistryLoadError, match="unsupported version"):
        load_registry(artifact)


def test_loader_rejects_missing_attributes_key(tmp_path):
    artifact = tmp_path / "no_attrs.json"
    artifact.write_text(json.dumps({
        "version": 1,
        "source_fingerprint": "abc",
    }))
    with pytest.raises(RegistryLoadError, match="missing.*attributes"):
        load_registry(artifact)


def test_loader_default_path_resolves_to_checked_in_artifact():
    registry = load_registry()
    assert registry.version == 1
    assert registry.attributes


def test_loader_exposes_representative_attribute(artifact_path):
    registry = load_registry(artifact_path)
    assert registry.attributes["shipping"].kind == AttributeKind.REPEATED_STRUCTURED
    assert registry.attributes["shipping"].fields[0].name == "country"
