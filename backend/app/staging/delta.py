from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .hashing import content_hash


@dataclass(frozen=True)
class StoredRow:
    pk: int
    product_id: str
    content_hash: str
    config_hash: str
    status: str
    snapshot: dict[str, Any]


@dataclass(frozen=True)
class RowUpsert:
    product_id: str
    product: dict[str, Any]
    content_hash: str
    config_hash: str
    insert: bool
    write_history: bool
    pk: int | None = None


@dataclass
class StagingCounts:
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    reactivated: int = 0
    removed: int = 0
    failed: int = 0


@dataclass
class StagingDelta:
    enqueue: list[dict[str, Any]] = field(default_factory=list)
    upserts: list[RowUpsert] = field(default_factory=list)
    reactivations: list[int] = field(default_factory=list)
    removals: list[int] = field(default_factory=list)
    touches: list[int] = field(default_factory=list)
    counts: StagingCounts = field(default_factory=StagingCounts)


def _product_id(product: Any) -> str | None:
    if not isinstance(product, dict):
        return None
    pid = product.get("id")
    if not isinstance(pid, str) or not pid:
        return None
    return pid


def classify(
    products: list[Any],
    stored: dict[str, StoredRow],
    config_hash: str,
) -> StagingDelta:
    delta = StagingDelta()
    seen: set[str] = set()

    for product in products:
        pid = _product_id(product)
        if pid is None or pid in seen:
            delta.counts.failed += 1
            continue
        seen.add(pid)

        ch = content_hash(product)
        row = stored.get(pid)

        if row is None:
            delta.upserts.append(RowUpsert(
                product_id=pid, product=product, content_hash=ch,
                config_hash=config_hash, insert=True, write_history=True,
            ))
            delta.enqueue.append(product)
            delta.counts.new += 1
        elif row.status == "active":
            if ch != row.content_hash or config_hash != row.config_hash:
                delta.upserts.append(RowUpsert(
                    product_id=pid, product=product, content_hash=ch,
                    config_hash=config_hash, insert=False,
                    write_history=ch != row.content_hash, pk=row.pk,
                ))
                delta.enqueue.append(product)
                delta.counts.changed += 1
            else:
                delta.touches.append(row.pk)
                delta.counts.unchanged += 1
        else:
            content_changed = ch != row.content_hash
            if content_changed or config_hash != row.config_hash:
                delta.upserts.append(RowUpsert(
                    product_id=pid, product=product, content_hash=ch,
                    config_hash=config_hash, insert=False,
                    write_history=content_changed, pk=row.pk,
                ))
            else:
                delta.reactivations.append(row.pk)
            delta.enqueue.append(product)
            delta.counts.reactivated += 1

    for pid, row in stored.items():
        if pid not in seen and row.status == "active":
            delta.removals.append(row.pk)
            delta.counts.removed += 1

    return delta
