from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..staging.hashing import canonical_json
from .templates import TaskSpecError

# The authoritative variable set per task type. Templates (DB or builtin)
# may only reference these; anything else fails validation at write time.
CANONICAL_VARIABLES: dict[str, list[str]] = {
    "title_optimization": ["brand", "title"],
    "category_classification": ["title", "description"],
    "policy_check": ["title", "description"],
    "attribute_enrichment": ["title", "description"],
    "image_quality": ["image_link"],
}


@dataclass(frozen=True)
class TaskSpec:
    system: str
    user: str
    validate: Callable[[str], Any]


def _validate_json(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise TaskSpecError("model output is not valid JSON") from exc


def _validate_text(content: str) -> str:
    return content.strip()


# Builtin defaults — DB templates (Feature 2) override these via the
# resolution chain in AiService; the registry remains the fallback.
TASK_SPECS: dict[str, TaskSpec] = {
    "title_optimization": TaskSpec(
        system=(
            "You rewrite product titles for Google Merchant Center. "
            "Reply with the optimized title only, no explanations."
        ),
        user=(
            "Brand: {{brand}}\nCurrent title: {{title}}\n"
            "Rewrite the title to be concise and search-friendly."
        ),
        validate=_validate_text,
    ),
    "category_classification": TaskSpec(
        system=(
            "You classify products into Google product categories. "
            "Reply with the category path only."
        ),
        user="Title: {{title}}\nDescription: {{description}}\nClassify.",
        validate=_validate_text,
    ),
    "policy_check": TaskSpec(
        system=(
            "You check product data against Google Merchant Center policies. "
            'Reply with JSON: {"violations": [{"rule": string, "reason": string}], '
            '"confidence": number between 0 and 1}. No other text.'
        ),
        user="Title: {{title}}\nDescription: {{description}}\nCheck for policy violations.",
        validate=_validate_json,
    ),
    "attribute_enrichment": TaskSpec(
        system=(
            "You extract product attributes from free text. "
            'Reply with JSON: {"color": string|null, "material": string|null, '
            '"size": string|null, "gtin": string|null}. No other text.'
        ),
        user="Title: {{title}}\nDescription: {{description}}\nExtract the attributes.",
        validate=_validate_json,
    ),
    "image_quality": TaskSpec(
        system=(
            "You assess product images for Google Merchant Center. "
            'Reply with JSON: {"watermark": boolean, "text_overlay": boolean, '
            '"background": string, "confidence": number}. No other text.'
        ),
        user="Image URL: {{image_link}}\nAssess the image.",
        validate=_validate_json,
    ),
}


def validate_task(task_type: str, content: str) -> Any:
    try:
        spec = TASK_SPECS[task_type]
    except KeyError as exc:
        raise TaskSpecError("unknown task type %r" % task_type) from exc  # noqa: UP031 — %-style avoids f-string brace-escaping
    return spec.validate(content)


def input_hash(task_type: str, variables: dict[str, Any]) -> str:
    payload = canonical_json({"task_type": task_type, "variables": variables})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
