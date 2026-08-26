### Task 4: Delta classifier (pure)

**Files:**
- Create: `backend/app/staging/delta.py`
- Test: `backend/tests/test_staging_delta.py`

**Interfaces:**
- Consumes: `content_hash` (Task 1).
- Produces (exact names — Task 6 depends on them):

```python
@dataclass(frozen=True)
class StoredRow:
    pk: int
    product_id: str
    content_hash: str
    config_hash: str
    status: str                      # "active" | "removed"
    snapshot: dict[str, Any]

@dataclass(frozen=True)
class RowUpsert:
    product_id: str
    product: dict[str, Any]
    content_hash: str
    config_hash: str
    insert: bool                     # True -> INSERT, False -> UPDATE existing row
    write_history: bool

@dataclass(frozen=True)
class StagingCounts:
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    reactivated: int = 0
    removed: int = 0
    failed: int = 0

@dataclass
class StagingDelta:
    enqueue: list[dict[str, Any]]
    upserts: list[RowUpsert]
    reactivations: list[int]         # pks flipped active without a content write
    removals: list[int]              # pks flipped removed
    touches: list[int]               # pks getting last_seen_at only
    counts: StagingCounts

def classify(products: list[Any], stored: dict[str, StoredRow], config_hash: str) -> StagingDelta
```

Binding matrix (approved design):

| Situation | Action |
|---|---|
| invalid product (not dict / missing / empty / non-str `id`) | `counts.failed += 1`, skip |
| duplicate `id` within run | first wins; later `counts.failed += 1` |
| no stored row | insert upsert, history, enqueue, `new` |
| active row, either hash differs | update upsert, `write_history=(content differs)`, enqueue, `changed` |
| active row, both equal | touch pk, `unchanged` |
| removed row reappears, any hash differs | update upsert (flips active via persistence), `write_history=(content differs)`, enqueue, `reactivated` |
| removed row reappears, both equal | `reactivations.append(pk)`, enqueue, `reactivated` |
| active stored row absent | `removals.append(pk)`, `removed` |
| removed stored row absent | no-op |

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_staging_delta.py`:

```python
from app.staging.delta import StoredRow, StagingCounts, classify
from app.staging.hashing import content_hash

CFG = "cfg0"


def _stored(pid, ch, status="active", pk=1):
    return StoredRow(pk=pk, product_id=pid, content_hash=ch, config_hash=CFG,
                     status=status, snapshot={})


def _products(*items):
    return [{"id": pid, "title": t} for pid, t in items]


class TestClassify:
    def test_first_run_inserts_everything(self):
        products = _products(("1", "A"), ("2", "B"))
        delta = classify(products, {}, CFG)
        assert [u.product_id for u in delta.upserts] == ["1", "2"]
        assert all(u.insert and u.write_history for u in delta.upserts)
        assert delta.enqueue == products
        assert delta.counts.new == 2

    def test_identical_rerun_only_touches(self):
        products = _products(("1", "A"))
        stored = {"1": _stored("1", content_hash(products[0]), pk=7)}
        delta = classify(products, stored, CFG)
        assert delta.upserts == [] and delta.enqueue == []
        assert delta.touches == [7]
        assert delta.counts.unchanged == 1

    def test_content_change_enqueues_with_history(self):
        old = {"id": "1", "title": "A"}
        new = {"id": "1", "title": "B"}
        delta = classify([new], {"1": _stored("1", content_hash(old), pk=7)}, CFG)
        assert delta.upserts[0].write_history is True
        assert delta.enqueue == [new]
        assert delta.counts.changed == 1

    def test_config_only_change_enqueues_without_history(self):
        product = {"id": "1", "title": "A"}
        delta = classify([product], {"1": _stored("1", content_hash(product), pk=7)}, "cfgNEW")
        assert delta.upserts[0].write_history is False
        assert delta.upserts[0].config_hash == "cfgNEW"
        assert delta.counts.changed == 1

    def test_removal_when_active_row_absent(self):
        stored = {"1": _stored("1", "x", pk=7), "2": _stored("2", "y", pk=8)}
        delta = classify([], stored, CFG)
        assert delta.removals == [7, 8]
        assert delta.counts.removed == 2

    def test_removed_row_absent_again_is_noop(self):
        stored = {"1": _stored("1", "x", status="removed", pk=7)}
        delta = classify([], stored, CFG)
        assert delta.removals == []
        assert delta.counts.removed == 0

    def test_reactivation_with_equal_hashes_flips_only(self):
        product = {"id": "1", "title": "A"}
        stored = {
            "1": StoredRow(pk=7, product_id="1", content_hash=content_hash(product),
                           config_hash=CFG, status="removed", snapshot={}),
        }
        delta = classify([product], stored, CFG)
        assert delta.upserts == []
        assert delta.reactivations == [7]
        assert delta.enqueue == [product]
        assert delta.counts.reactivated == 1

    def test_reactivation_with_changed_content_upserts_with_history(self):
        old = {"id": "1", "title": "A"}
        new = {"id": "1", "title": "B"}
        stored = {
            "1": StoredRow(pk=7, product_id="1", content_hash=content_hash(old),
                           config_hash=CFG, status="removed", snapshot=old),
        }
        delta = classify([new], stored, CFG)
        assert len(delta.upserts) == 1
        assert delta.upserts[0].write_history is True
        assert delta.reactivations == []
        assert delta.counts.reactivated == 1

    def test_missing_or_invalid_ids_fail(self):
        delta = classify([{"title": "no id"}, {"id": "", "t": 1}, [1, 2]], {}, CFG)
        assert delta.counts.failed == 3
        assert delta.enqueue == []

    def test_duplicate_ids_first_wins_rest_fail(self):
        products = _products(("1", "A")) + [{"id": "1", "title": "dup"}]
        delta = classify(products, {}, CFG)
        assert delta.enqueue == [products[0]]
        assert delta.counts.failed == 1
        assert delta.counts.new == 1

    def test_counts_default_zero(self):
        assert StagingCounts().new == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_staging_delta.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.staging.delta'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/staging/delta.py`:

```python
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


@dataclass(frozen=True)
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
                    write_history=ch != row.content_hash,
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
                    write_history=content_changed,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_staging_delta.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add app/staging/delta.py tests/test_staging_delta.py
git commit -m "feat: staging delta classifier"
```

---

