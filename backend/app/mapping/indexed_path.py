"""Central authority for the 1-based indexed path grammar.

Grammar: attr | attr.sub | attr.N | attr.N.sub  (1 <= N <= MAX_INDEX)

QC finding paths (additional_image_link.1) already use this grammar. UI and
stored values are always 1-based; translation to 0-based array indices
happens only in consumers of IndexedPath.index, never in the stored string.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_INDEX = 10_000
"""Upper bound for N in attr.N / attr.N.sub. Bounds the auto-extend
allocation in mapping apply ("" / {} slot fill) so a typo'd stored index
cannot blow up pipeline memory. Reads beyond the bound also fail parsing,
keeping the grammar uniform across validation, reads, and writes."""


@dataclass(frozen=True)
class IndexedPath:
    attr: str
    index: int | None  # 1-based
    sub: str | None


def parse_indexed_path(path: str) -> IndexedPath:
    parts = path.split(".")
    if not parts or not parts[0]:
        raise ValueError(f"invalid indexed path {path!r}: empty attribute")
    attr = parts[0]
    if len(parts) > 3:
        raise ValueError(f"invalid indexed path {path!r}: at most 3 segments")
    if len(parts) == 1:
        return IndexedPath(attr=attr, index=None, sub=None)

    second = parts[1]
    index: int | None = None
    sub: str | None = None
    if second.isdigit():
        index = int(second)
        if index < 1:
            raise ValueError(f"invalid index in {path!r}: indices are 1-based")
        if index > MAX_INDEX:
            raise ValueError(
                f"invalid index in {path!r}: N must be <= {MAX_INDEX}"
            )
        if len(parts) == 3:
            sub = parts[2]
            if not sub:
                raise ValueError(f"invalid indexed path {path!r}: empty sub-field")
    else:
        if len(parts) == 3:
            raise ValueError(
                f"invalid indexed path {path!r}: at most attr.sub or attr.N.sub"
            )
        if not second:
            raise ValueError(f"invalid indexed path {path!r}: empty sub-field")
        sub = second
    if index is None and second.startswith("-"):
        raise ValueError(f"invalid index in {path!r}: indices are 1-based")
    return IndexedPath(attr=attr, index=index, sub=sub)
