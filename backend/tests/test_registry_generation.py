import json

from registry.generate import check_registry, generate_registry


def test_generation_is_deterministic_and_check_detects_stale(tmp_path, request):
    source = request.fspath.dirname + "/fixtures/registry/valid.md"
    output = tmp_path / "attributes.json"
    generate_registry(source, output)
    first = output.read_bytes()
    generate_registry(source, output)
    assert output.read_bytes() == first
    assert check_registry(source, output)
    output.write_bytes(first.replace(b'"title"', b'"z_title"', 1))
    assert not check_registry(source, output)


def test_generated_document_has_version_fingerprint_and_sorted_attributes(tmp_path, request):
    output = tmp_path / "attributes.json"
    generate_registry(request.fspath.dirname + "/fixtures/registry/valid.md", output)
    data = json.loads(output.read_text())
    assert data["version"] == 1
    assert data["source_fingerprint"]
    assert list(data["attributes"]) == sorted(data["attributes"])
