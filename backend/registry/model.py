from dataclasses import dataclass, field
from enum import Enum


class AttributeKind(str, Enum):
    SCALAR = "scalar"
    REPEATED_SCALAR = "repeated_scalar"
    STRUCTURED = "structured"
    REPEATED_STRUCTURED = "repeated_structured"


class ExportStatus(str, Enum):
    EXPORTABLE = "exportable"
    NON_EXPORTABLE = "non_exportable"


class FeedDomain(str, Enum):
    PRIMARY = "primary"
    LOCAL_INVENTORY = "local_inventory"
    VEHICLE_LISTINGS = "vehicle_listings"


class RequirementStatus(str, Enum):
    REQUIRED = "required"
    CONDITIONAL = "conditional"
    OPTIONAL = "optional"
    RECOMMENDED = "recommended"
    DEPRECATED = "deprecated"
    REMOVED = "removed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Cardinality:
    max_items: int | None = None
    min_items: int | None = None
    item_max_length: int | None = None


@dataclass(frozen=True)
class Constraints:
    max_length: int | None = None
    min_length: int | None = None
    format: str | None = None


@dataclass(frozen=True)
class SubField:
    name: str
    type: str
    required: RequirementStatus
    constraints: Constraints = field(default_factory=Constraints)
    enum_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegistryAttribute:
    name: str
    kind: AttributeKind
    type: str
    required: RequirementStatus
    domain: FeedDomain
    export_status: ExportStatus
    fields: tuple[SubField, ...] = ()
    enum_values: tuple[str, ...] = ()
    cardinality: Cardinality = field(default_factory=Cardinality)
    constraints: Constraints = field(default_factory=Constraints)
    source_line: int = 0
    source_lines: tuple[int, ...] = ()
    applicability: tuple[FeedDomain, ...] = ()
    qualifiers: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RegistryDocument:
    attributes: dict[str, RegistryAttribute]
    source: str = ""
    version: int = 1
