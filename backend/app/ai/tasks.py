from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from . import schemas

# The authoritative variable set per task type. Templates (DB or builtin)
# may only reference these; anything else fails validation at write time.
CANONICAL_VARIABLES: dict[str, list[str]] = {
    "title_optimization": ["brand", "title"],
    "description_optimization": ["title", "description"],
    "category_classification": ["title", "description"],
    "policy_check": ["title", "description"],
    "attribute_enrichment": ["title", "description"],
    "image_quality": ["image_link"],
}


@dataclass(frozen=True)
class TaskSpec:
    system: str
    user: str
    response_model: type[BaseModel]


TASK_SPECS: dict[str, TaskSpec] = {
    "title_optimization": TaskSpec(
        system=(
            "You rewrite product titles for Google Merchant Center. "
            "Reply with the optimized title only, no explanations. "
            "Do not use promotional language or all capital letters."
        ),
        user=(
            "Brand: {{brand}}\nCurrent title: {{title}}\n"
            "Rewrite the title to be concise and search-friendly."
        ),
        response_model=schemas.OptimizedTitle,
    ),
    "description_optimization": TaskSpec(
        system=(
            "You rewrite product descriptions for Google Merchant Center. "
            "Reply with the optimized description only, no explanations."
        ),
        user=(
            "Title: {{title}}\nCurrent description: {{description}}\n"
            "Rewrite the description to be clear and complete."
        ),
        response_model=schemas.OptimizedDescription,
    ),
    "category_classification": TaskSpec(
        system=(
            "You classify products into Google product categories. "
            "Reply with the numeric taxonomy id only. "
            "Example: 2271 for Apparel & Accessories > Clothing > Dresses."
        ),
        user="Title: {{title}}\nDescription: {{description}}\nClassify.",
        response_model=schemas.CategoryAssignment,
    ),
    "policy_check": TaskSpec(
        system=(
            "You check product data against Google Merchant Center policies. "
            "Return the list of violations and a confidence between 0 and 1."
        ),
        user="Title: {{title}}\nDescription: {{description}}\nCheck for policy violations.",
        response_model=schemas.PolicyCheckResult,
    ),
    "attribute_enrichment": TaskSpec(
        system=(
            "You extract product attributes from free text. Extract color, "
            "size, material, gtin, gender, age_group, and up to five custom labels. "
            "gender is one of male, female, unisex. "
            "age_group is one of newborn, infant, toddler, kids, adult. "
            "Use custom_label_0 through custom_label_4. Omit anything unknown."
        ),
        user="Title: {{title}}\nDescription: {{description}}\nExtract the attributes.",
        response_model=schemas.EnrichedAttributes,
    ),
    "image_quality": TaskSpec(
        system=(
            "You assess product images for Google Merchant Center. "
            "Report watermark, text overlay, background, and confidence between 0 and 1."
        ),
        user="Image URL: {{image_link}}\nAssess the image.",
        response_model=schemas.ImageQualityResult,
    ),
}
