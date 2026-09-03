from __future__ import annotations

from fastapi import APIRouter, Depends

from registry.loader import load_registry

from ..auth import require_user
from ..qc.constants import BASELINE_ALTERNATIVE_PAIRS, BASELINE_REQUIRED
from ..schemas.field_mapping import RegistryAttributeOut, RegistrySubFieldOut

router = APIRouter()


@router.get("/registry/attributes", response_model=list[RegistryAttributeOut])
async def list_registry_attributes(_user: str = Depends(require_user)) -> list[RegistryAttributeOut]:
    registry = load_registry()
    baseline_names = set(BASELINE_REQUIRED)
    for pair in BASELINE_ALTERNATIVE_PAIRS:
        baseline_names.update(pair)
    return [
        RegistryAttributeOut(
            name=attribute.name,
            kind=attribute.kind.value,
            required=attribute.required.value,
            baseline_required=attribute.name in baseline_names,
            sub_fields=[
                RegistrySubFieldOut(
                    name=sub.name,
                    type=sub.type,
                    required=sub.required.value,
                )
                for sub in attribute.fields
            ],
            enum_values=list(attribute.enum_values),
        )
        for attribute in sorted(registry.attributes.values(), key=lambda attr: attr.name)
    ]
