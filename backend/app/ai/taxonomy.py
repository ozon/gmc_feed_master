from __future__ import annotations

from functools import lru_cache
from pathlib import Path

TAXONOMY_CSV = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "core"
    / "category"
    / "taxonomy-with-ids.en-US.csv"
)


@lru_cache(maxsize=1)
def known_taxonomy_ids() -> frozenset[int]:
    if not TAXONOMY_CSV.exists():
        return frozenset()
    ids: set[int] = set()
    with TAXONOMY_CSV.open(encoding="utf-8") as handle:
        for line in handle:
            head = line.split(",", 1)[0].strip()
            if head.isdigit():
                ids.add(int(head))
    return frozenset(ids)
