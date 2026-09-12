from __future__ import annotations

from typing import Any

DEFAULT_TARGET_FIELDS = ["color", "material", "size", "gtin"]


def validate_config(config: Any) -> None:
    if not isinstance(config, dict):
        raise TypeError("config must be an object")
    fields = config.get("targetFields", DEFAULT_TARGET_FIELDS)
    if (
        not isinstance(fields, list)
        or not fields
        or not all(isinstance(f, str) and f for f in fields)
    ):
        raise ValueError("targetFields must be a non-empty list of non-empty strings")


class EnrichmentPlugin:
    """Pipeline module applying accepted AI enrichment values (pins) by product id."""

    def validate_config(self, config: Any) -> None:
        validate_config(config)

    def prepare_run(self, config: Any, data: Any, ctx: Any) -> dict[str, Any]:
        return {"pinned": (data or {}).get("pinned") or {}}

    def process(
        self,
        product: dict[str, Any],
        config: Any,
        data: Any,
        ctx: Any,
        state: Any = None,
    ) -> dict[str, Any]:
        pinned = (state or {}).get("pinned") or {}
        values = pinned.get(str(product.get("id", "")))
        if not values:
            return product
        result = dict(product)
        for field, value in values.items():
            result[field] = value  # pinned wins over feed values (spec: explicit user decision)
        return result
