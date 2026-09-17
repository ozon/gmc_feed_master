from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from .constraints import max_length
from .taxonomy import known_taxonomy_ids

_PROMO_RE = re.compile(
    r"\b("
    r"free shipping|best price|lowest price|buy now|hot deal|limited offer|"
    r"sale|discount|cheap"
    r")\b"
)
_LETTER_RE = re.compile(r"[A-Za-z]")


class OptimizedTitle(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=max_length("title") or 150)]

    @field_validator("title")
    @classmethod
    def _no_promotional_text(cls, value: str) -> str:
        match = _PROMO_RE.search(value.lower())
        if match:
            raise ValueError(f"title contains promotional text: {match.group(0)!r}")
        return value

    @field_validator("title")
    @classmethod
    def _no_all_caps(cls, value: str) -> str:
        letters = _LETTER_RE.findall(value)
        if len(letters) >= 4 and all(ch.isupper() for ch in letters):
            raise ValueError("title must not be all caps")
        return value


class OptimizedDescription(BaseModel):
    description: Annotated[
        str, Field(min_length=1, max_length=max_length("description") or 5000)
    ]


class Violation(BaseModel):
    rule: str
    reason: str


class PolicyCheckResult(BaseModel):
    violations: list[Violation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class CategoryAssignment(BaseModel):
    google_product_category: int

    @field_validator("google_product_category")
    @classmethod
    def _known_taxonomy_id(cls, value: int) -> int:
        known = known_taxonomy_ids()
        if known and value not in known:
            raise ValueError(f"unknown taxonomy id {value}")
        return value


_Gender = Literal["male", "female", "unisex"]
_AgeGroup = Literal["newborn", "infant", "toddler", "kids", "adult"]


class EnrichedAttributes(BaseModel):
    color: str | None = None
    size: str | None = None
    material: str | None = None
    gtin: str | None = None
    gender: _Gender | None = None
    age_group: _AgeGroup | None = None
    custom_label_0: Annotated[str | None, Field(max_length=100)] = None
    custom_label_1: Annotated[str | None, Field(max_length=100)] = None
    custom_label_2: Annotated[str | None, Field(max_length=100)] = None
    custom_label_3: Annotated[str | None, Field(max_length=100)] = None
    custom_label_4: Annotated[str | None, Field(max_length=100)] = None


class ImageQualityResult(BaseModel):
    watermark: bool
    text_overlay: bool
    background: str
    confidence: float = Field(ge=0.0, le=1.0)


class RuleValueResult(BaseModel):
    value: str


RESPONSE_MODELS: dict[str, type[BaseModel]] = {
    "title_optimization": OptimizedTitle,
    "description_optimization": OptimizedDescription,
    "category_classification": CategoryAssignment,
    "policy_check": PolicyCheckResult,
    "attribute_enrichment": EnrichedAttributes,
    "image_quality": ImageQualityResult,
}
