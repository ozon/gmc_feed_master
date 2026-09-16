from __future__ import annotations

from functools import lru_cache
from typing import Any

from registry.loader import load_registry


@lru_cache(maxsize=1)
def _attributes() -> dict[str, Any]:
    return load_registry().attributes


def max_length(attr: str) -> int | None:
    info = _attributes().get(attr)
    constraints = getattr(info, "constraints", None)
    return getattr(constraints, "max_length", None)


def enum_values(attr: str) -> tuple[str, ...]:
    info = _attributes().get(attr)
    values = getattr(info, "enum_values", None)
    return tuple(values) if values else ()
