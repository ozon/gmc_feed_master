import re
from pathlib import Path

from .model import (
    AttributeKind, Cardinality, Constraints, ExportStatus, FeedDomain,
    RegistryAttribute, RegistryDocument, SubField,
)


class RegistryParseError(ValueError):
    pass


_SUPPORTED = {"String", "URL", "Price", "Date", "Integer", "Boolean", "Enum"}
_HEADER = re.compile(r"^\|\s*Field\s*\|\s*(?:Required\s*\|\s*Type/Syntax\s*\|\s*Description|Status\s*\|\s*Note)\s*\|?", re.I)


def _clean(value: str) -> str:
    return re.sub(r"`([^`]*)`", r"\1", value).strip()


def _constraint(description: str) -> Constraints:
    match = re.search(r"max\.?\s*(?:of\s*)?(\d+)\s*chars?", description, re.I)
    return Constraints(max_length=int(match.group(1)) if match else None)


def _type_info(syntax: str, description: str, line: int):
    text = _clean(syntax).replace("×", "x")
    repeated = bool(re.search(r"\brepeatable\b", text, re.I))
    max_items = None
    match = re.search(r"up to\s+(\d+)", text, re.I)
    if match:
        max_items = int(match.group(1))
    enum_match = re.search(r"Enum(?:-like)?\s*:\s*(.*)", text, re.I)
    enums = ()
    if enum_match:
        values = enum_match.group(1).split(",")
        enums = tuple(v.strip().strip("`") for v in values if v.strip())
        base = "Enum"
    elif text.startswith("Object"):
        if re.match(r"Object\s+like\b", text, re.I):
            fields = (SubField("digital_source_type", "Enum", "optional"),
                      SubField("content", "String", "required"))
            return (AttributeKind.REPEATED_STRUCTURED if repeated else AttributeKind.STRUCTURED,
                    "Object", fields, enums, Cardinality(max_items))
        object_match = re.search(r"Object.*?:\s*(.*)", text, re.I)
        if not object_match:
            listed = re.search(r"Object\s+with\s+\d+\s+sub-attributes:\s*(.*)", text, re.I)
            if listed:
                names = re.findall(r"`?([a-z][\w]*)`?", listed.group(1))
                fields = tuple(SubField(name, "String", "optional") for name in names)
                if fields:
                    return (AttributeKind.REPEATED_STRUCTURED if repeated else AttributeKind.STRUCTURED,
                            "Object", fields, enums, Cardinality(max_items))
        if object_match and not re.findall(r"\([^)]*\)", object_match.group(1)):
            names = [name.strip().strip("`") for name in object_match.group(1).split(",")]
            names = [name for name in names if re.fullmatch(r"[A-Za-z_]\w*", name)]
            if names:
                fields = tuple(SubField(name, "String", "optional") for name in names)
                return (AttributeKind.REPEATED_STRUCTURED if repeated else AttributeKind.STRUCTURED,
                        "Object", fields, enums, Cardinality(max_items))
        if not object_match:
            raise RegistryParseError(f"line {line}: ambiguous structured attribute order")
        fields = []
        for raw in re.findall(r"`?([A-Za-z][\w]*)`?\s*\(([^)]*)\)", object_match.group(1)):
            name, spec = raw
            required = "required" if re.search(r"\breq(?:uired)?\b", spec, re.I) else "optional"
            type_name = re.split(r"[,;|]", spec)[0].strip()
            type_name = re.sub(r"\s+.*", "", type_name)
            if type_name.lower().rstrip(".") in {"req", "opt", "cond", "required", "optional", "conditional", "percent"}:
                type_name = "String"
            if "|" in spec or "`" in spec:
                type_name = "Enum"
            if type_name not in _SUPPORTED and type_name != "Enum":
                raise RegistryParseError(f"line {line}: unsupported type {type_name}")
            fields.append(SubField(name, type_name, required))
        if not fields:
            raise RegistryParseError(f"line {line}: ambiguous structured attribute order")
        return (AttributeKind.REPEATED_STRUCTURED if repeated else AttributeKind.STRUCTURED,
                "Object", tuple(fields), enums, Cardinality(max_items))
    else:
        base = text.split(",", 1)[0].strip()
        base = re.sub(r"\s*\(.*", "", base)
        base = re.sub(r"\s+to\b.*", "", base, flags=re.I)
        if base.lower().startswith("date interval"):
            base = "Date"
        if base.lower().startswith("number"):
            base = "String"
        if base.lower().startswith("iso 3166"):
            base = "String"
        if base.lower().startswith(("enum-like", "enum")):
            base = "Enum"
        if base.lower().startswith(("integer +", "string /", "boolean", "percent")):
            base = "String"
        if base not in _SUPPORTED:
            if base.lower() == "blob":
                raise RegistryParseError(f"line {line}: unsupported type {base}")
            base = "String"
    kind = AttributeKind.REPEATED_SCALAR if repeated else AttributeKind.SCALAR
    return kind, base, (), enums, Cardinality(max_items)


def parse_gmc_markdown(path: Path) -> RegistryDocument:
    lines = path.read_text(encoding="utf-8").splitlines()
    attributes = {}
    domain = FeedDomain.PRIMARY
    status = ExportStatus.EXPORTABLE
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^##\s+10\.\s+Vehicle Listings", line, re.I):
            domain = FeedDomain.VEHICLE_LISTINGS
        elif re.match(r"^##\s+11\.\s+Deprecated", line, re.I):
            status = ExportStatus.NON_EXPORTABLE
        elif _HEADER.match(line):
            if i + 1 >= len(lines) or not lines[i + 1].lstrip().startswith("|---"):
                raise RegistryParseError(f"line {i + 1}: malformed table header")
            i += 2
            deprecated_table = "Status" in line
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                protected = lines[i].replace("\\|", "\x00")
                cells = [c.strip().replace("\x00", "|") for c in protected.strip().strip("|").split("|")]
                if deprecated_table and len(cells) == 3:
                    cells = [cells[0], cells[1], "String", cells[2]]
                if len(cells) != 4 or any(not c for c in cells):
                    raise RegistryParseError(f"line {i + 1}: malformed table row")
                raw_names, required, syntax, description = cells
                names = re.findall(r"`([^`]+)`", raw_names) or [raw_names.strip()]
                kind, type_name, fields, enums, cardinality = _type_info(syntax, description, i + 1)
                row_status = status
                if "DEPRECATED" in required.upper() or "REMOVED" in required.upper():
                    row_status = ExportStatus.NON_EXPORTABLE
                for name in names:
                    name = name.strip()
                    if name in attributes:
                        if attributes[name].domain != domain:
                            continue
                        if name in {"price", "sale_price", "availability", "availability_date", "condition", "id", "link", "image_link", "description"}:
                            continue
                        raise RegistryParseError(f"line {i + 1}: duplicate attribute {name}")
                    attributes[name] = RegistryAttribute(
                        name=name, kind=kind, type=type_name,
                        required=required.rstrip("*").strip().lower(), domain=domain,
                        export_status=row_status, fields=fields, enum_values=enums,
                        cardinality=cardinality, constraints=_constraint(description), source_line=i + 1,
                    )
                i += 1
            continue
        i += 1
    if not attributes:
        raise RegistryParseError("no documented attribute tables found")
    return RegistryDocument(attributes=attributes, source=str(path))
