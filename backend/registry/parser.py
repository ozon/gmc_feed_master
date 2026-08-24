import re
from pathlib import Path

from .model import (
    AttributeKind, Cardinality, Constraints, ExportStatus, FeedDomain,
    RegistryAttribute, RegistryDocument, RequirementStatus, SubField,
)


class RegistryParseError(ValueError):
    pass


_PRIMITIVES = {"String", "URL", "Price", "Date", "Integer", "Boolean", "Enum"}
_HEADER = re.compile(r"^\|\s*Field\s*\|\s*(Required|Status)\s*\|\s*(?:Type/Syntax|Note)\s*\|", re.I)


def _clean(value: str) -> str:
    return re.sub(r"`([^`]*)`", r"\1", value).strip()


def _requirement(value: str) -> RequirementStatus:
    value = value.upper().replace("*", "")
    if "NOT A GMC ATTRIBUTE" in value:
        return RequirementStatus.REMOVED
    if "REMOVED" in value:
        return RequirementStatus.REMOVED
    if "DEPRECATED" in value:
        return RequirementStatus.DEPRECATED
    if "CONDITIONAL" in value:
        return RequirementStatus.CONDITIONAL
    if "REQUIRED" in value:
        return RequirementStatus.REQUIRED
    if "RECOMMENDED" in value:
        return RequirementStatus.RECOMMENDED
    if "OPTIONAL" in value:
        return RequirementStatus.OPTIONAL
    raise RegistryParseError(f"unsupported requirement status {value}")


def _constraints(description: str) -> Constraints:
    max_match = re.search(r"max\.?\s*(?:of\s*)?(\d+)\s*chars?", description, re.I)
    min_match = re.search(r"(?:min\.?|at least)\s*(\d+)\s*chars?", description, re.I)
    fmt = None
    if re.search(r"ISO\s*3166(?:-1)?", description, re.I):
        fmt = "ISO 3166-1"
    elif re.search(r"\bIANA\b", description, re.I):
        fmt = "IANA"
    elif re.search(r"\bpercent\b", description, re.I):
        fmt = "percent"
    elif re.search(r"ISO\s*8601", description, re.I):
        fmt = "ISO 8601"
    elif re.search(r"RFC\s*(?:2396|3986|1738)", description, re.I):
        fmt = "RFC URL"
    return Constraints(
        max_length=int(max_match.group(1)) if max_match else None,
        min_length=int(min_match.group(1)) if min_match else None,
        format=fmt,
    )


def _type_name(raw: str, line: int) -> str:
    text = _clean(raw).strip().rstrip(".")
    text = re.sub(r"^(?:req(?:uired)?|opt(?:ional)?|cond(?:itional)?)\.?\s+", "", text, flags=re.I)
    text = re.sub(r"\s*(?:>|≥|\+).*", "", text).strip()
    if text.lower() in {"number", "phone no", "phone", "percent"}:
        return "String"
    if text.lower() in {"as in primary feed"}:
        return "String"
    if text.lower().startswith("e.g."):
        return "String"
    if text.lower().startswith("iana"):
        return "String"
    if re.match(r"^\d+[- ]digit\b", text, re.I):
        return "String"
    if re.match(r"^(?:Integer|String)\s*\([^)]*\)\s+OR\s+(?:Integer|String)", text, re.I):
        return "String"
    prefix = re.match(r"^(String|URL|Price|Date|Integer|Boolean)\b", text, re.I)
    if prefix:
        return {"url": "URL", "price": "Price", "date": "Date", "integer": "Integer", "boolean": "Boolean", "string": "String"}[prefix.group(1).lower()]
    if re.match(r"^Enum\s+like\b", text, re.I):
        return "Enum"
    if re.match(r"^Enum(?:-like)?\s*:", text, re.I):
        return "Enum"
    if re.match(r"^Date\s+interval\b", text, re.I):
        return "Date"
    # These are documented representations of a primitive field, not new types.
    documented = (
        r"String(?:\s*\([^)]*\))?$", r"URL(?:\s+.*)?$",
        r"Price(?:\s*\([^)]*\))?$", r"Date(?:\s*\([^)]*\))?$",
        r"Integer(?:\s*\([^)]*\))?(?:\s+\+\s+unit)?$",
        r"Boolean(?:\s*\([^)]*\))?$", r"Enum(?:-like)?(?:\s*\([^)]*\))?$",
        r"Number\s*\+\s*unit(?:\s*\([^)]*\))?$", r"ISO\s+3166-1(?:\s+country\s+code)?$",
        r"String\s*/\s*URL\s*/\s*phone\s+no$", r"String\s*\(numeric\)$",
    )
    for pattern in documented:
        if re.match(pattern, text, re.I):
            if text.lower().startswith("enum"):
                return "Enum"
            if text.lower().startswith("url"):
                return "URL"
            if text.lower().startswith("price"):
                return "Price"
            if text.lower().startswith("date"):
                return "Date"
            if text.lower().startswith("integer"):
                return "Integer"
            if text.lower().startswith("boolean"):
                return "Boolean"
            return "String"
    raise RegistryParseError(f"line {line}: unsupported type {text}")


def _enum_values(text: str) -> tuple[str, ...]:
    # Defaults and prose are metadata, not enum members.  Keep this cleanup
    # here so it applies equally to top-level and nested enum syntax.
    text = re.sub(r",?\s*default\s+(?:=\s*)?[^,;|]+", "", text, flags=re.I)
    text = re.sub(r"(?:\s*\.\.\.|\s*…)+\s*$", "", text).strip()
    text = re.sub(r"\s*[.;]\s*$", "", text).strip()
    values: list[str] = []
    for part in re.split(r"\s*,\s*|\s*\|\s*", text):
        part = part.strip().strip("`").strip("()[]{}").strip()
        part = part.replace("`", "")
        part = re.sub(r"\s*(?:\.\.\.|…)+\s*$", "", part).strip()
        if not part:
            continue
        if re.fullmatch(r"[^\s/]+(?:/[^\s/]+)+", part):
            values.extend(part.split("/"))
        else:
            values.append(part)
    return tuple(dict.fromkeys(values))


def _object_parts(value: str) -> list[tuple[str, str]]:
    parts: list[str] = []
    start = depth = 0
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    result: list[tuple[str, str]] = []
    expanded: list[str] = []
    for part in parts:
        alternatives = re.split(r"\s+OR\s+", part, flags=re.I)
        expanded.extend(alternatives if len(alternatives) > 1 else [part])
    for part in expanded:
        part = re.sub(r";\s*repeatable(?:\s*\([^)]*\))?\s*$", "", part, flags=re.I).strip()
        part = re.sub(r"\s+–\s+only one of the two.*$", "", part, flags=re.I).strip()
        match = re.fullmatch(r"`?([A-Za-z][\w]*)`?(?:\s*\((.*)\))?", part)
        if match:
            result.append((match.group(1), match.group(2) or ""))
            continue
        match = re.match(r"`?([A-Za-z][\w]*)`?\s*\((.*)\)\s*$", part, re.S)
        if match:
            result.append((match.group(1), match.group(2)))
    return result


def _object_payload(text: str) -> str | None:
    start = text.lower().find("object") + len("object")
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == ":" and depth == 0:
            return text[index + 1:].strip()
    return None


def _table_cells(line: str) -> list[str]:
    value = line.strip().strip("|")
    cells: list[str] = []
    start = 0
    in_code = False
    for index, char in enumerate(value):
        if char == "`":
            in_code = not in_code
        elif char == "|" and not in_code and (index == 0 or value[index - 1] != "\\"):
            cells.append(value[start:index].strip())
            start = index + 1
    cells.append(value[start:].strip())
    return [cell.replace("\\|", "|") for cell in cells]


def _field_spec(name: str, spec: str, description: str, line: int) -> SubField:
    required = RequirementStatus.OPTIONAL
    if re.search(r"\breq(?:uired)?\b", spec, re.I):
        required = RequirementStatus.REQUIRED
    elif re.search(r"\bcond(?:itional)?\b", spec, re.I):
        required = RequirementStatus.CONDITIONAL
    type_part = re.sub(r"^(?:req(?:uired)?|opt(?:ional)?|cond(?:itional)?)\.?\s*[,;:]?\s*", "", spec, flags=re.I).strip()
    type_part = re.sub(r"\s*[,;:]\s*(?:req(?:uired)?|opt(?:ional)?|cond(?:itional)?)\.?\s*$", "", type_part, flags=re.I).strip()
    enum_text = type_part
    is_enum = "|" in enum_text or re.fullmatch(r"[A-Za-z_]+(?:/[A-Za-z_]+)+", enum_text)
    type_name = "Enum" if is_enum else ("String" if not type_part else _type_name(type_part, line))
    enum_values = _enum_values(enum_text) if type_name == "Enum" else ()
    return SubField(name, type_name, required, _constraints(spec + " " + description), enum_values)


def _type_info(syntax: str, description: str, line: int):
    text = syntax.strip().replace("×", "x")
    repeated = bool(re.search(r"\brepeatable\b", text, re.I))
    count = re.search(r"up to\s+(\d+)", text, re.I)
    cardinality = Cardinality(int(count.group(1)) if count else None)
    enum_match = re.search(r"Enum(?:-like)?\s*:\s*(.*)", text, re.I)
    enums = _enum_values(enum_match.group(1)) if enum_match else ()
    if re.match(r"^Object\b", text, re.I):
        object_payload = _object_payload(text)
        object_match = re.match(r".*", object_payload) if object_payload is not None else None
        if not object_match:
            if re.match(r"Object\s+like\b", text, re.I):
                fields = (
                    SubField("digital_source_type", "Enum", RequirementStatus.OPTIONAL,
                             enum_values=("default", "trained_algorithmic_media")),
                    SubField("content", "String", RequirementStatus.REQUIRED,
                             constraints=_constraints(description)),
                )
                return (AttributeKind.REPEATED_STRUCTURED if repeated else AttributeKind.STRUCTURED,
                        "Object", fields, enums, cardinality)
            raise RegistryParseError(f"line {line}: ambiguous structured attribute order")
        fields = []
        for raw_name, spec in _object_parts(object_match.group(0)):
            fields.append(_field_spec(raw_name, spec, description, line) if spec else SubField(raw_name, "String", RequirementStatus.OPTIONAL, _constraints(description)))
        if not fields:
            names = re.findall(r"`([A-Za-z][\w]*)`", object_match.group(0))
            if not names:
                names = [n.strip() for n in object_match.group(0).split(",") if re.fullmatch(r"[A-Za-z_][\w]*", n.strip())]
            fields = [SubField(name, "String", RequirementStatus.OPTIONAL) for name in names]
        if not fields:
            raise RegistryParseError(f"line {line}: ambiguous structured attribute order")
        return (AttributeKind.REPEATED_STRUCTURED if repeated else AttributeKind.STRUCTURED,
                "Object", tuple(fields), enums, cardinality)
    base = _type_name(text.split(",", 1)[0], line)
    return (AttributeKind.REPEATED_SCALAR if repeated else AttributeKind.SCALAR,
            base, (), enums, cardinality)


def _row_domain(section: str) -> FeedDomain:
    if section == "vehicle":
        return FeedDomain.VEHICLE_LISTINGS
    if section == "local":
        return FeedDomain.LOCAL_INVENTORY
    return FeedDomain.PRIMARY


def parse_gmc_markdown(path: Path) -> RegistryDocument:
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    attributes: dict[str, RegistryAttribute] = {}
    attribute_sections: dict[str, str] = {}
    section = "primary"
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^##\s+9\.", line, re.I):
            section = "local"
        elif re.match(r"^##\s+10\.", line, re.I):
            section = "vehicle"
        elif re.match(r"^##\s+11\.", line, re.I):
            section = "deprecated"
        elif _HEADER.match(line):
            if i + 1 >= len(lines) or not lines[i + 1].lstrip().startswith("|---"):
                raise RegistryParseError(f"line {i + 1}: malformed table header")
            deprecated_table = "Status" in line
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                row_line = i + 1
                cells = _table_cells(lines[i])
                if deprecated_table and len(cells) == 3:
                    cells = [cells[0], cells[1], "String", cells[2]]
                if len(cells) != 4 or any(not c for c in cells):
                    raise RegistryParseError(f"line {row_line}: malformed table row")
                raw_names, requirement_text, syntax, description = cells
                requirement = _requirement(requirement_text)
                status = ExportStatus.NON_EXPORTABLE if section == "deprecated" or requirement in (RequirementStatus.DEPRECATED, RequirementStatus.REMOVED) else ExportStatus.EXPORTABLE
                domain = FeedDomain.VEHICLE_LISTINGS if section == "vehicle" else _row_domain(section)
                deprecated_vehicle = section == "deprecated" and re.search(r"vehicle|vehicle feeds", description, re.I)
                kind, type_name, fields, enums, cardinality = _type_info(syntax, description, row_line)
                qualifiers = tuple(x for x in ("alternative" if "alternative" in requirement_text.lower() or "alternative" in description.lower() else "",) if x)
                for name in (n.strip() for n in (re.findall(r"`([^`]+)`", raw_names) or [raw_names.strip()])):
                    if name in attributes:
                        old = attributes[name]
                        cross_section_repeat = domain in old.applicability or (not old.applicability and domain is old.domain)
                        intentional_deprecated_repeat = section == "deprecated" and old.export_status is ExportStatus.NON_EXPORTABLE
                        if attribute_sections[name] == section or (cross_section_repeat and not intentional_deprecated_repeat):
                            # GMC intentionally repeats deprecated definitions in the
                            # historical table. Preserve that applicability instead of
                            # pretending the second row is a new canonical field.
                            raise RegistryParseError(f"line {row_line}: duplicate attribute {name} (first occurrence line {old.source_line}, field {name})")
                        applicability = old.applicability or (old.domain,)
                        if deprecated_vehicle:
                            applicability = tuple(dict.fromkeys(applicability + (FeedDomain.VEHICLE_LISTINGS,)))
                        attributes[name] = RegistryAttribute(**{**old.__dict__, "source_lines": old.source_lines + (row_line,), "applicability": applicability + ((domain,) if domain not in applicability else ()), "qualifiers": tuple(dict.fromkeys(old.qualifiers + qualifiers))})
                    else:
                        applicability = (FeedDomain.VEHICLE_LISTINGS,) if deprecated_vehicle else ()
                        attributes[name] = RegistryAttribute(name, kind, type_name, requirement, domain, status, fields, enums, cardinality, _constraints(description), row_line, (row_line,), applicability, qualifiers, (("description", description),))
                        attribute_sections[name] = section
                i += 1
            continue
        i += 1
    if not attributes:
        raise RegistryParseError("no documented attribute tables found")
    return RegistryDocument(attributes=attributes, source=str(path))
