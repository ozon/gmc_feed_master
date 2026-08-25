from __future__ import annotations

import xml.etree.ElementTree as ET

from registry.model import RegistryDocument

from .report import IngestReport, RowError


class XmlParseError(Exception):
    pass


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _element_to_dict(elem: ET.Element) -> dict[str, object]:
    result: dict[str, object] = {}
    for child in elem:
        key = _strip_ns(child.tag)
        if child.text and child.text.strip() and len(child) == 0:
            value: object = child.text.strip()
        elif len(child) > 0:
            value = _element_to_dict(child)
        else:
            continue

        if key in result:
            existing = result[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                result[key] = [existing, value]
        else:
            result[key] = value
    return result


def _parse_item(item: ET.Element) -> dict[str, object]:
    product: dict[str, object] = {}
    for child in item:
        key = _strip_ns(child.tag)

        has_text = child.text is not None and child.text.strip()
        has_children = len(child) > 0

        if has_text and has_children:
            raise ValueError(
                f"Element '{key}' has mixed content (text and children)"
            )

        if has_children:
            value: object = _element_to_dict(child)
        elif has_text:
            value = child.text.strip()
        else:
            continue

        if key in product:
            existing = product[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                product[key] = [existing, value]
        else:
            product[key] = value
    return product


def _find_items(root: ET.Element) -> list[ET.Element]:
    tag = _strip_ns(root.tag)
    if tag == "rss":
        channel = root.find("channel")
        if channel is None:
            return []
        return channel.findall("item")
    if tag == "feed":
        ns = ""
        if "}" in root.tag:
            ns = root.tag.split("}")[0] + "}"
        return root.findall(f"{ns}entry")
    return []


def parse_xml(data: bytes, registry: RegistryDocument) -> IngestReport:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise XmlParseError(str(exc)) from exc

    items = _find_items(root)
    products: list[dict[str, object]] = []
    row_errors: list[RowError] = []

    for idx, item in enumerate(items, start=1):
        try:
            product = _parse_item(item)
            products.append(product)
        except Exception as exc:
            row_errors.append(RowError(line=idx, message=str(exc)))

    return IngestReport(products=products, row_errors=row_errors)
