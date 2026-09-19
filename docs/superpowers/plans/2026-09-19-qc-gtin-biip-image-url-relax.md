# QC GTIN (biip) + Image URL Relaxation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate GTINs with `biip` (check digit + valid length, all repeatable values) and stop flagging image URLs that carry query strings or fragments.

**Architecture:** Two targeted changes inside `backend/app/qc/rules.py` plus their unit tests and docs. No schema, API, or pipeline-order change.

**Tech Stack:** Python 3.10+, `biip==5.0.0`, pytest 8.4.2, ruff 0.16.6, mypy 2.3.1, uv.

**Spec:** `docs/superpowers/specs/2026-09-19-qc-gtin-biip-image-url-relax-design.md`.

## Global Constraints

- New runtime dependency is exactly `biip==5.0.0` (approved in spec); no other dependency changes.
- `gtin` is a REPEATED_SCALAR registry field — the rule must accept a scalar **or** a list.
- biip ships `py.typed`; do not add a mypy override.
- `uv run ruff check . ../plugins` and `uv run mypy .` must stay exit-0 after every task (run from `backend/`).
- Commit style: `type(scope): summary`. Do not commit unless the operator asks.
- Per-value invalid GTIN (bad check digit, bad length, non-numeric) → `severity="critical"`, `field="gtin"`.

---

## File Structure

- `backend/pyproject.toml`, `backend/uv.lock` — add `biip==5.0.0`.
- `backend/app/qc/rules.py` — rewrite `GtinMpn`; fix extension extraction in `ImageRequirements`.
- `backend/tests/test_qc_rules.py` — new GTIN + image cases.
- `docs/decisions.md` — dated entry for the biip dependency and length enforcement.
- `docs/superpowers/specs/2026-08-27-m7-quality-check-design.md` — §7 `gtin_mpn` row.

---

### Task 1: GTIN validation via biip

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock`
- Modify: `backend/app/qc/rules.py:61-86`
- Test: `backend/tests/test_qc_rules.py:123-158`

**Interfaces:**
- Consumes: `Finding`, `QcContext` from `backend/app/qc/engine.py`; `product: dict`.
- Produces: `GtinMpn` (unchanged `rule_id = "gtin_mpn"`, async `check(product, ctx) -> list[Finding]`). Verified valid GTINs for tests: GTIN-8 `96385074`, GTIN-12 `036000291452`, GTIN-13 `4006381333931`, GTIN-14 `10614141000415`.

- [ ] **Step 1: Add the dependency**

Run from `backend/`:

```bash
uv add "biip==5.0.0"
```

Expected: `pyproject.toml` gains `"biip==5.0.0"` in `[project].dependencies`; `uv.lock` updates.

- [ ] **Step 2: Write the failing tests**

Append after `test_gtin_missing_mpn_only_warns` in `backend/tests/test_qc_rules.py`:

```python
async def test_gtin_valid_all_lengths():
    rule = GtinMpn()
    for value in ("96385074", "036000291452", "4006381333931", "10614141000415"):
        findings = await rule.check({"gtin": value}, _make_ctx())
        assert findings == [], value


async def test_gtin_invalid_length_is_critical():
    rule = GtinMpn()
    findings = await rule.check({"gtin": "1234567890"}, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "critical"


async def test_gtin_non_numeric_is_critical():
    rule = GtinMpn()
    findings = await rule.check({"gtin": "abc"}, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "critical"


async def test_gtin_repeated_valid_list():
    rule = GtinMpn()
    product = {"gtin": ["4006381333931", "036000291452"]}
    findings = await rule.check(product, _make_ctx())
    assert findings == []


async def test_gtin_repeated_one_invalid():
    rule = GtinMpn()
    product = {"gtin": ["4006381333931", "0012345678900"]}
    findings = await rule.check(product, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "critical"
    assert "check digit" in findings[0].message


async def test_gtin_empty_list_treated_as_missing():
    rule = GtinMpn()
    findings = await rule.check({"gtin": []}, _make_ctx())
    assert len(findings) == 1
    assert findings[0].severity == "warning"
```

- [ ] **Step 3: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_qc_rules.py -k gtin -v`
Expected: `test_gtin_repeated_valid_list` FAILS (old `str(list)` path returns a critical finding); the others may already pass. This red test is the anchor for the rewrite.

- [ ] **Step 4: Rewrite `GtinMpn`**

In `backend/app/qc/rules.py`, add at the top (after `from datetime import datetime`):

```python
import biip
```

Ruff orders stdlib before third-party, so the import block becomes:

```python
from __future__ import annotations

from datetime import datetime

import biip

from .constants import (
    ...
)
```

Replace the whole `GtinMpn` class (current lines 61-86) with:

```python
class GtinMpn:
    rule_id = "gtin_mpn"

    @staticmethod
    def _values(raw: object) -> list[str]:
        items = raw if isinstance(raw, (list, tuple)) else [raw]
        values = [str(v).strip() for v in items]
        return [v for v in values if v]

    async def check(self, product: dict, ctx: QcContext) -> list[Finding]:
        values = self._values(product.get("gtin"))
        if not values:
            if not product.get("mpn") or not product.get("brand"):
                return [Finding(
                    rule_id=self.rule_id, severity="warning",
                    field="gtin", message="missing gtin requires mpn and brand",
                )]
            return []
        findings = []
        for value in values:
            result = biip.parse(value)
            if result.gtin is None:
                findings.append(Finding(
                    rule_id=self.rule_id, severity="critical",
                    field="gtin",
                    message=result.gtin_error or f"invalid GTIN: {value}",
                ))
        return findings
```

- [ ] **Step 5: Run the GTIN tests**

Run: `uv run pytest tests/test_qc_rules.py -k gtin -v`
Expected: PASS (all 11 GTIN tests).

- [ ] **Step 6: Update docs**

In `docs/superpowers/specs/2026-08-27-m7-quality-check-design.md`, change the `gtin_mpn` row (line 147) to:

```markdown
| `gtin_mpn` | per-product | hand-written: missing `gtin` → `mpn`+`brand` required; present `gtin` → each value parsed with `biip` (GS1 check digit + valid length 8/12/13/14, repeatable-aware) | critical |
```

Append to `docs/decisions.md` under a new `## 2026-09-19` section:

```markdown
### QC GTIN validation uses biip

- **Topic:** GTIN check implementation in the quality-check engine
- **Decision:** Validate GTINs with `biip==5.0.0` (`biip.parse(v).gtin`)
  instead of the hand-rolled GS1 mod-10 helper, and validate every value of
  the repeatable `gtin` field. Invalid check digit, invalid length (not 8,
  12, 13, or 14), or non-numeric input → `critical`.
- **Rationale:** The hand-rolled helper accepted meaningless lengths and
  coerced list values to `str(list)`, producing false findings. biip applies
  the same GS1 mod-10 weighting and additionally enforces the GTIN lengths
  documented in `gmc_def.md`. `gmc-feed-engine-spec.md` §"GTIN/MPN logic"
  (mod-10, "no special cases") is not contradicted: biip uses the standard
  GS1 weighting.
```

- [ ] **Step 7: Run the gates**

Run from `backend/`:

```bash
uv run ruff check . ../plugins && uv run mypy .
```

Expected: both exit 0.

- [ ] **Step 8: Commit (only if operator asks)**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/qc/rules.py \
  backend/tests/test_qc_rules.py docs/decisions.md \
  docs/superpowers/specs/2026-08-27-m7-quality-check-design.md
git commit -m "feat(qc): validate GTINs with biip across repeatable values"
```

---

### Task 2: Allow query strings and fragments in image URLs

**Files:**
- Modify: `backend/app/qc/rules.py` (`ImageRequirements`, current lines 232-238)
- Test: `backend/tests/test_qc_rules.py` (ImageRequirements section, current lines 324-370)

**Interfaces:**
- Consumes: `ImageRequirements` and `ImageProbe.probe(url) -> (width, height, error)`.
- Produces: same class/`rule_id = "image_requirements"`; only the extension check changes.

- [ ] **Step 1: Write the failing tests**

Append after `test_image_requirements_probe_error` in `backend/tests/test_qc_rules.py`:

```python
async def test_image_requirements_allows_query_parameter():
    probe = AsyncMock()
    probe.probe.return_value = (1600, 1600, None)
    rule = ImageRequirements()
    findings = await rule.check(
        {"image_link": "https://example.com/img.jpg?v=1243"}, _make_ctx(image_probe=probe)
    )
    assert findings == []


async def test_image_requirements_allows_fragment():
    probe = AsyncMock()
    probe.probe.return_value = (1600, 1600, None)
    rule = ImageRequirements()
    findings = await rule.check(
        {"image_link": "https://example.com/img.webp#frag"}, _make_ctx(image_probe=probe)
    )
    assert findings == []


async def test_image_requirements_allows_multiple_parameters():
    probe = AsyncMock()
    probe.probe.return_value = (1600, 1600, None)
    rule = ImageRequirements()
    findings = await rule.check(
        {"image_link": "https://example.com/img.png?size=large&x=1"},
        _make_ctx(image_probe=probe),
    )
    assert findings == []


async def test_image_requirements_extensionless_still_warns():
    probe = AsyncMock()
    probe.probe.return_value = (1600, 1600, None)
    rule = ImageRequirements()
    findings = await rule.check(
        {"image_link": "https://example.com/image?v=1"}, _make_ctx(image_probe=probe)
    )
    assert len(findings) == 1
    assert "unrecognized image format" in findings[0].message


async def test_image_requirements_directory_dot_not_extension():
    probe = AsyncMock()
    probe.probe.return_value = (1600, 1600, None)
    rule = ImageRequirements()
    findings = await rule.check(
        {"image_link": "https://example.com/v1.2/image?v=1"}, _make_ctx(image_probe=probe)
    )
    assert len(findings) == 1
    assert "unrecognized image format" in findings[0].message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_qc_rules.py -k "image_requirements_allows" -v`
Expected: FAIL — `img.jpg?v=1243` is parsed as extension `jpg?v=1243`, producing a false format warning.

- [ ] **Step 3: Fix the extension extraction**

In `backend/app/qc/rules.py`, add `from urllib.parse import urlsplit` after `from datetime import datetime` (stdlib block, after `datetime`), so the top reads:

```python
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

import biip
```

In `ImageRequirements.check`, replace:

```python
        for field_name, url in urls:
            ext = url.rsplit(".", 1)[-1].lower() if "." in url else ""
```

with:

```python
        for field_name, url in urls:
            filename = urlsplit(url).path.rsplit("/", 1)[-1]
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
```

- [ ] **Step 4: Run the image tests**

Run: `uv run pytest tests/test_qc_rules.py -k image_requirements -v`
Expected: PASS (all image tests, old and new).

- [ ] **Step 5: Run the full QC rule module + gates**

Run from `backend/`:

```bash
uv run pytest tests/test_qc_rules.py -v
uv run ruff check . ../plugins && uv run mypy .
```

Expected: all pass, both gates exit 0.

- [ ] **Step 6: Commit (only if operator asks)**

```bash
git add backend/app/qc/rules.py backend/tests/test_qc_rules.py
git commit -m "fix(qc): ignore query strings and fragments in image URL format check"
```

---

## Self-Review

- **Spec coverage:** biip dependency + per-value validation → Task 1; `urlsplit` path/fragment handling → Task 2; spec/decisions doc updates → Task 1 Step 6. Follow-ups in the spec (magic-byte sniffing, GS1 prefix hints, lengths-in-constants, raw value in `details`) are explicitly out of scope, matching the spec.
- **Placeholder scan:** none — every step has runnable code or an exact command.
- **Type consistency:** `GtinMpn.check(product, ctx) -> list[Finding]` and `ImageRequirements.check` signatures are unchanged, so `QualityCheckStep` needs no edit. `biip.parse` returns an object with `.gtin` / `.gtin_error` (verified against biip 5.0.0).
