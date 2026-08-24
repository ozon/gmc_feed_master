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
    VEHICLE_LISTINGS = "vehicle_listings"


@dataclass(frozen=True)
class Cardinality:
    max_items: int | None = None


@dataclass(frozen=True)
class Constraints:
    max_length: int | None = None
    format: str | None = None


@dataclass(frozen=True)
class SubField:
    name: str
    type: str
    required: str
    constraints: Constraints = field(default_factory=Constraints)
    enum_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegistryAttribute:
    name: str
    kind: AttributeKind
    type: str
    required: str
    domain: FeedDomain
    export_status: ExportStatus
    fields: tuple[SubField, ...] = ()
    enum_values: tuple[str, ...] = ()
    cardinality: Cardinality = field(default_factory=Cardinality)
    constraints: Constraints = field(default_factory=Constraints)
    source_line: int = 0


@dataclass(frozen=True)
class RegistryDocument:
    attributes: dict[str, RegistryAttribute]
    source: str = ""
    version: int = 1
