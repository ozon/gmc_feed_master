from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

from registry.model import AttributeKind, ExportStatus, RegistryAttribute, RegistryDocument


@dataclass(frozen=True)
class ChannelMetadata:
    title: str
    link: str
    description: str


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _scalar_element(name: str, value: Any) -> str:
    return f"<g:{name}>{escape(str(value))}</g:{name}>"


def _structured_body(attribute: RegistryAttribute, value: dict[str, Any]) -> str:
    parts: list[str] = []
    for sub_field in attribute.fields:
        sub_value = value.get(sub_field.name)
        if _is_empty(sub_value):
            continue
        parts.append(_scalar_element(sub_field.name, sub_value))
    return "".join(parts)


def _render_attribute(attribute: RegistryAttribute, value: Any) -> str:
    name = attribute.name
    if attribute.kind is AttributeKind.SCALAR:
        return _scalar_element(name, value) + "\n"
    if attribute.kind is AttributeKind.REPEATED_SCALAR:
        items = [item for item in value if not _is_empty(item)]
        return "".join(_scalar_element(name, item) + "\n" for item in items)
    if attribute.kind is AttributeKind.STRUCTURED:
        body = _structured_body(attribute, value)
        if not body:
            return ""
        return f"<g:{name}>{body}</g:{name}>\n"
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict) or _is_empty(item):
            continue
        body = _structured_body(attribute, item)
        if body:
            parts.append(f"<g:{name}>{body}</g:{name}>\n")
    return "".join(parts)


def render_feed(
    products: Sequence[dict[str, Any]],
    registry: RegistryDocument,
    channel: ChannelMetadata,
) -> bytes:
    chunks: list[str] = []
    chunks.append('<?xml version="1.0" encoding="UTF-8"?>\n')
    chunks.append('<rss version="2.0" xmlns:g="http://base.google.com/schemas/1.0">\n')
    chunks.append("<channel>\n")
    chunks.append(f"<title>{escape(channel.title)}</title>\n")
    chunks.append(f"<link>{escape(channel.link)}</link>\n")
    chunks.append(f"<description>{escape(channel.description)}</description>\n")
    for product in sorted(products, key=lambda p: str(p.get("id", ""))):
        chunks.append("<item>\n")
        for attribute in registry.attributes.values():
            if attribute.export_status is not ExportStatus.EXPORTABLE:
                continue
            value = product.get(attribute.name)
            if _is_empty(value):
                continue
            chunks.append(_render_attribute(attribute, value))
        chunks.append("</item>\n")
    chunks.append("</channel>\n")
    chunks.append("</rss>\n")
    return "".join(chunks).encode("utf-8")
