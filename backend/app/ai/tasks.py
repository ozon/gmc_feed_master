from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..staging.hashing import canonical_json


class TaskSpecError(ValueError):
    """Raised for unknown task types or invalid model output."""


@dataclass(frozen=True)
class TaskSpec:
    render: Callable[[dict[str, Any]], list[dict[str, str]]]
    validate: Callable[[str], Any]


def _render(system: str, user: str) -> Callable[[dict[str, Any]], list[dict[str, str]]]:
    def _renderer(variables: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user.format(**variables)},
        ]

    return _renderer


def _validate_json(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise TaskSpecError("model output is not valid JSON") from exc


def _validate_text(content: str) -> str:
    return content.strip()


# Builtin defaults — Feature 2 replaces these with versioned DB templates;
# the registry is the seam.
TASK_SPECS: dict[str, TaskSpec] = {
    "title_optimization": TaskSpec(
        render=_render(
            "You rewrite product titles for Google Merchant Center. "
            "Reply with the optimized title only, no explanations.",
            "Brand: {brand}\nCurrent title: {title}\n"
            "Rewrite the title to be concise and search-friendly.",
        ),
        validate=_validate_text,
    ),
    "category_classification": TaskSpec(
        render=_render(
            "You classify products into Google product categories. "
            "Reply with the category path only.",
            "Title: {title}\nDescription: {description}\nClassify.",
        ),
        validate=_validate_text,
    ),
    "policy_check": TaskSpec(
        render=_render(
            "You check product data against Google Merchant Center policies. "
            'Reply with JSON: {"violations": [{"rule": string, "reason": string}], '
            '"confidence": number between 0 and 1}. No other text.',
            "Title: {title}\nDescription: {description}\nCheck for policy violations.",
        ),
        validate=_validate_json,
    ),
    "attribute_enrichment": TaskSpec(
        render=_render(
            "You extract product attributes from free text. "
            'Reply with JSON: {"color": string|null, "material": string|null, '
            '"size": string|null, "gtin": string|null}. No other text.',
            "Title: {title}\nDescription: {description}\nExtract the attributes.",
        ),
        validate=_validate_json,
    ),
    "image_quality": TaskSpec(
        render=_render(
            "You assess product images for Google Merchant Center. "
            'Reply with JSON: {"watermark": boolean, "text_overlay": boolean, '
            '"background": string, "confidence": number}. No other text.',
            "Image URL: {image_link}\nAssess the image.",
        ),
        validate=_validate_json,
    ),
}


def render_task(task_type: str, variables: dict[str, Any]) -> list[dict[str, str]]:
    try:
        spec = TASK_SPECS[task_type]
    except KeyError as exc:
        raise TaskSpecError(f"unknown task type {task_type!r}") from exc
    try:
        return spec.render(variables)
    except KeyError as exc:
        raise TaskSpecError(f"missing variable {exc.args[0]!r} for task {task_type!r}") from exc


def validate_task(task_type: str, content: str) -> Any:
    try:
        spec = TASK_SPECS[task_type]
    except KeyError as exc:
        raise TaskSpecError(f"unknown task type {task_type!r}") from exc
    return spec.validate(content)


def input_hash(task_type: str, variables: dict[str, Any]) -> str:
    payload = canonical_json({"task_type": task_type, "variables": variables})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
