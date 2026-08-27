import hashlib
import json
import difflib
from pathlib import Path

from .model import RegistryDocument
from .parser import parse_gmc_markdown


def _as_json(document: RegistryDocument, source_bytes: bytes) -> bytes:
    attributes = {}
    for name in sorted(document.attributes):
        item = document.attributes[name]
        value = {
            "kind": item.kind.value, "type": item.type, "required": item.required.value,
            "domain": item.domain.value, "export_status": item.export_status.value,
            "source_line": item.source_line, "source_lines": list(item.source_lines),
            "applicability": [domain.value for domain in item.applicability],
            "qualifiers": list(item.qualifiers), "metadata": dict(item.metadata),
            "enum_values": list(item.enum_values),
            "cardinality": {
                key: value
                for key, value in {
                    "max_items": item.cardinality.max_items,
                    "min_items": item.cardinality.min_items,
                    "item_max_length": item.cardinality.item_max_length,
                }.items()
                if value is not None
            } if item.cardinality.max_items is not None or item.cardinality.min_items is not None or item.cardinality.item_max_length is not None else None,
            "constraints": {"max_length": item.constraints.max_length, "min_length": item.constraints.min_length, "format": item.constraints.format},
            "fields": [
                {"name": f.name, "type": f.type, "required": f.required.value,
                 "enum_values": list(f.enum_values),
                  "constraints": {"max_length": f.constraints.max_length, "min_length": f.constraints.min_length, "format": f.constraints.format}}
                for f in item.fields
            ],
        }
        attributes[name] = value
    payload = {"version": document.version,
               "source_fingerprint": hashlib.sha256(source_bytes).hexdigest(),
               "attributes": attributes}
    return (json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n").encode()


def generate_registry(source: Path, output: Path) -> None:
    source = Path(source)
    output = Path(output)
    rendered = _as_json(parse_gmc_markdown(source), source.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(rendered)


def check_registry(source: Path, output: Path) -> bool:
    source = Path(source)
    output = Path(output)
    if not output.exists():
        return False
    return output.read_bytes() == _as_json(parse_gmc_markdown(source), source.read_bytes())


def registry_diff(source: Path, output: Path) -> str:
    expected = _as_json(parse_gmc_markdown(Path(source)), Path(source).read_bytes()).decode().splitlines(keepends=True)
    actual = Path(output).read_text(encoding="utf-8").splitlines(keepends=True) if Path(output).exists() else []
    return "".join(difflib.unified_diff(actual, expected, fromfile=str(output), tofile="regenerated"))
