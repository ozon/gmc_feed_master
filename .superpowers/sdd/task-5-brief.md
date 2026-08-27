### Task 5: QC Engine — Types and Core

**Goal:** Create the QC engine types (`QcContext`, `Finding`, rule protocols) and the `run_engine()` function.

**Files:**
- Create: `backend/app/qc/__init__.py`
- Create: `backend/app/qc/constants.py`
- Create: `backend/app/qc/engine.py`
- Create: `backend/tests/test_qc_engine.py`

#### Steps

- [ ] **Step 1: Create constants**

```python
# backend/app/qc/constants.py
from datetime import date

EXEMPT_TAXONOMY_IDS: frozenset[int] = frozenset({
    # Books
    784, 543541, 543542, 543543,
    # DVDs & Videos
    839, 543527, 543528, 543529,
    # Music & Sound Recordings
    855, 543522, 543523, 543524, 543525, 543526,
})

IMAGE_FORMATS: frozenset[str] = frozenset({
    "jpg", "jpeg", "webp", "png", "gif", "bmp", "tiff", "tif",
})

IMAGE_SIZE_ENFORCEMENT_DATE: date = date(2027, 1, 31)

IMAGE_FETCH_CAP_BYTES: int = 10 * 1024 * 1024  # 10 MB

IMAGE_CONCURRENCY: int = 8
```

- [ ] **Step 2: Create engine types and `run_engine()`**

```python
# backend/app/qc/engine.py
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from registry.model import RegistryDocument

from ..clock import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QcContext:
    feed_source_id: int
    currency: str | None
    volume_drop_threshold_pct: int
    registry: RegistryDocument
    clock: Clock
    image_probe: ImageProbe
    previous_export_run: ExportRun | None


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str  # "critical" | "warning" | "info"
    field: str | None
    message: str
    product_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PerProductRule(Protocol):
    rule_id: str

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]: ...


@runtime_checkable
class CrossProductRule(Protocol):
    rule_id: str

    async def check(self, products: list[dict], ctx: QcContext) -> list[Finding]: ...


@runtime_checkable
class ImageProbe(Protocol):
    async def probe(self, url: str) -> tuple[int | None, int | None, str | None]:
        """Return (width, height, error_message). error_message is None on success."""
        ...


@runtime_checkable
class ExportRun(Protocol):
    feed_source_id: int
    ingestion_run_id: int
    product_count: int
    critical_finding_count: int
    warning_finding_count: int
    info_finding_count: int


async def run_engine(
    products: list[dict],
    product_ids: list[str],
    ctx: QcContext,
    per_product_rules: list[PerProductRule],
    cross_product_rules: list[CrossProductRule],
) -> list[Finding]:
    findings: list[Finding] = []

    # Per-product rules — attach product_id to each finding
    for product, product_id in zip(products, product_ids):
        for rule in per_product_rules:
            try:
                rule_findings = await rule.check(product, ctx)
                for f in rule_findings:
                    findings.append(Finding(
                        rule_id=f.rule_id, severity=f.severity,
                        field=f.field, message=f.message,
                        product_id=product_id, details=f.details,
                    ))
            except Exception:
                logger.exception("rule %s failed on product %s", rule.rule_id, product_id)

    # Cross-product rules — no product_id (findings apply to the feed as a whole)
    for rule in cross_product_rules:
        try:
            rule_findings = await rule.check(products, ctx)
            findings.extend(rule_findings)
        except Exception:
            logger.exception("cross-product rule %s failed", rule.rule_id)

    return findings
```

- [ ] **Step 3: Create package init**

```python
# backend/app/qc/__init__.py
from .engine import QcContext, Finding, PerProductRule, CrossProductRule, ImageProbe, ExportRun, run_engine
from .constants import EXEMPT_TAXONOMY_IDS, IMAGE_FORMATS, IMAGE_SIZE_ENFORCEMENT_DATE

__all__ = [
    "QcContext", "Finding", "PerProductRule", "CrossProductRule",
    "ImageProbe", "ExportRun", "run_engine",
    "EXEMPT_TAXONOMY_IDS", "IMAGE_FORMATS", "IMAGE_SIZE_ENFORCEMENT_DATE",
]
```

- [ ] **Step 4: Write engine unit tests**

```python
# backend/tests/test_qc_engine.py
import pytest
from app.qc.engine import QcContext, Finding, PerProductRule, CrossProductRule, run_engine
from registry.model import RegistryDocument
from app.clock import TestClock

pytestmark = pytest.mark.asyncio


class StubImageProbe:
    async def probe(self, url):
        return (800, 600, None)


class StubPerProductRule:
    rule_id = "stub_per"

    async def check(self, product, ctx):
        if not product.get("title"):
            return [Finding(rule_id="stub_per", severity="warning", field="title", message="missing title")]
        return []


class StubCrossProductRule:
    rule_id = "stub_cross"

    async def check(self, products, ctx):
        if len(products) < 2:
            return [Finding(rule_id="stub_cross", severity="info", field=None, message="need more products")]
        return []


def _make_ctx(**overrides):
    defaults = dict(
        feed_source_id=1,
        currency="USD",
        volume_drop_threshold_pct=20,
        registry=RegistryDocument(attributes={}),
        clock=TestClock(__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)),
        image_probe=StubImageProbe(),
        previous_export_run=None,
    )
    defaults.update(overrides)
    return QcContext(**defaults)


async def test_per_product_rule_finds_issues():
    products = [{"id": "1"}, {"id": "2", "title": "Good"}]
    product_ids = ["1", "2"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [StubPerProductRule()], [])
    assert len(findings) == 1
    assert findings[0].rule_id == "stub_per"
    assert findings[0].field == "title"
    assert findings[0].product_id == "1"


async def test_cross_product_rule_finds_issues():
    products = [{"id": "1"}]
    product_ids = ["1"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [], [StubCrossProductRule()])
    assert len(findings) == 1
    assert findings[0].rule_id == "stub_cross"


async def test_no_findings_on_clean_data():
    products = [{"id": "1", "title": "Good"}, {"id": "2", "title": "Also good"}]
    product_ids = ["1", "2"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [StubPerProductRule()], [StubCrossProductRule()])
    assert findings == []


async def test_rule_exception_does_not_crash_engine():
    class BrokenRule:
        rule_id = "broken"
        async def check(self, product, ctx):
            raise RuntimeError("boom")

    products = [{"id": "1"}]
    product_ids = ["1"]
    ctx = _make_ctx()
    findings = await run_engine(products, product_ids, ctx, [BrokenRule()], [])
    assert findings == []
```

- [ ] **Step 5: Run engine tests**

Run: `cd backend && python -m pytest tests/test_qc_engine.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/qc/ backend/tests/test_qc_engine.py
git commit -m "feat(qc): engine types, protocols, and run_engine()"
```

---

