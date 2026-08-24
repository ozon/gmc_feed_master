import hashlib
import json
from pathlib import Path

from .model import RegistryDocument
from .parser import parse_gmc_markdown


def _as_json(document: RegistryDocument, source_bytes: bytes) -> bytes:
    attributes = {}
    for name in sorted(document.attributes):
        item = document.attributes[name]
        value = {
            "kind": item.kind.value, "type": item.type, "required": item.required,
            "domain": item.domain.value, "export_status": item.export_status.value,
            "enum_values": list(item.enum_values),
            "cardinality": {"max_items": item.cardinality.max_items},
            "constraints": {"max_length": item.constraints.max_length, "format": item.constraints.format},
            "fields": [
                {"name": f.name, "type": f.type, "required": f.required,
                 "enum_values": list(f.enum_values),
                 "constraints": {"max_length": f.constraints.max_length, "format": f.constraints.format}}
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
