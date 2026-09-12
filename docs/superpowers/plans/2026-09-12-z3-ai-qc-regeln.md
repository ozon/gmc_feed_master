# Z3: AI-QC-Regeln (policy_check) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `policy_check` as an AI-powered QC rule with per-run budget, cache-free progression, and re-validate-first ordering; configured per feed source in the setup form.

**Architecture:** One new CrossProductRule (`AiPolicyCheck`) that gathers AI calls internally with a budget of real (non-cache) calls. QcContext gains AI fields with defaults. QualityCheckStep reads `configuration["ai_qc"]` and loads previous AI findings before persist. No new endpoints, no schema changes.

**Tech Stack:** FastAPI, SQLAlchemy async; existing AiService (`run_task` with cache/breaker/usage).

**Spec:** `docs/superpowers/specs/2026-09-12-ai-qc-regeln-design.md`

## Global Constraints

- Same gates/i18n/logger/docs rules as the Z1 plan (see its Global Constraints).
- QC stays non-blocking: AI rule failures degrade to findings/counts, never abort runs.
- Budget counts only `AiResult.status == "ok"` calls; `cache_hit` is free; `fallback` counts as failed.
- Severity mapping fixed: violations → warning; confidence < 0.5 → info. Deterministic rules remain the only critical source.

---

### Task 1: CrossProductRule signature + QcContext AI fields

**Files:**
- Modify: `backend/app/qc/engine.py`, `backend/app/qc/rules.py` (VariantConsistency, VolumeDrop)
- Test: `backend/tests/test_qc_engine.py` (extend; if the engine's tests live elsewhere, extend that file — locate with `rg -l "run_engine" tests/`)

**Interfaces:**
- Produces: `CrossProductRule.check(self, products: list[dict], product_ids: list[str], ctx: QcContext) -> list[Finding]`; `QcContext` gains `ai_service: Any = None`, `client_id: int | None = None`, `ai_budget: int = 0`, `previous_ai_product_ids: frozenset[str] = frozenset()` (all defaulted — existing constructors unaffected).

- [ ] **Step 1: Write failing test** — a dummy cross rule asserting it receives product_ids:

```python
class RecordingCrossRule:
    rule_id = "recording"
    def __init__(self):
        self.seen_ids = None
    async def check(self, products, product_ids, ctx):
        self.seen_ids = list(product_ids)
        return []
```

`run_engine(products, ["a", "b"], ctx, [], [rule])` → `rule.seen_ids == ["a", "b"]`.

- [ ] **Step 2: Run** — FAIL (TypeError: check() takes 3 positional args).

- [ ] **Step 3: Implement** — in `engine.py`: extend the Protocol and `run_engine`:

```python
@runtime_checkable
class CrossProductRule(Protocol):
    rule_id: str

    async def check(self, products: list[dict], product_ids: list[str], ctx: QcContext) -> list[Finding]: ...
```

```python
    for cross_rule in cross_product_rules:
        try:
            rule_findings = await cross_rule.check(products, product_ids, ctx)
```

Add `from typing import Any` if missing and extend QcContext:

```python
@dataclass(frozen=True)
class QcContext:
    feed_source_id: int
    currency: str | None
    volume_drop_threshold_pct: int
    registry: RegistryDocument
    clock: Clock
    image_probe: ImageProbe | None
    previous_export_run: ExportRun | None
    ai_service: Any = None
    client_id: int | None = None
    ai_budget: int = 0
    previous_ai_product_ids: frozenset[str] = frozenset()
```

In `rules.py`: change `VariantConsistency.check` and `VolumeDrop.check` signatures to `(self, products: list[dict], product_ids: list[str], ctx: QcContext)` (params otherwise unused).

- [ ] **Step 4: Run** `uv run pytest tests/ -k "qc or quality or volume or variant" -x` — pass (update any cross-rule test call sites to the new signature).

- [ ] **Step 5: Commit** `git add backend/app/qc && git commit -m "refactor: cross-product rules receive product_ids; qc context ai fields"`

---

### Task 2: AiPolicyCheck rule

**Files:**
- Create: `backend/app/qc/ai_rules.py`
- Test: `backend/tests/test_ai_policy_check.py` (new)

**Interfaces:**
- Consumes: `ctx.ai_service.run_task(task_type, variables, client_id=..., feed_source_id=...) -> AiResult` (status `ok|cache_hit|fallback`, `value` = parsed JSON).
- Produces: `AiPolicyCheck` with `rule_id = "ai_policy_check"`; findings `code="ai_policy_check"`, `details={ai_rule, confidence}`.

- [ ] **Step 1: Write failing tests** — create `backend/tests/test_ai_policy_check.py` with a fake service:

```python
from dataclasses import dataclass
from app.ai.service import AiResult
from app.qc.ai_rules import AiPolicyCheck
from app.qc.engine import QcContext


@dataclass
class FakeAi:
    scripted: dict  # product_id -> AiResult
    calls: list = None

    def __post_init__(self):
        self.calls = []

    async def run_task(self, task_type, variables, *, client_id=None, feed_source_id=None):
        pid = variables["title"]  # encode product id in title for the fake
        self.calls.append(pid)
        return self.scripted[pid]


def make_ctx(ai, budget=50, prev=frozenset()):
    return QcContext(
        feed_source_id=1, currency=None, volume_drop_threshold_pct=20,
        registry=object(), clock=object(), image_probe=None,
        previous_export_run=None, ai_service=ai, client_id=None,
        ai_budget=budget, previous_ai_product_ids=prev,
    )


async def test_maps_violations_to_warning_findings():
    ai = FakeAi({"p1": AiResult(
        value={"violations": [{"rule": "watermark", "reason": "has watermark"}], "confidence": 0.9},
        status="ok", error_code=None, prompt_tokens=1, completion_tokens=1,
    )})
    findings = await AiPolicyCheck().check(
        [{"title": "p1", "description": "d"}], ["p1"], make_ctx(ai))
    assert len(findings) == 1
    f = findings[0]
    assert (f.rule_id, f.severity, f.product_id) == ("ai_policy_check", "warning", "p1")
    assert f.details == {"ai_rule": "watermark", "confidence": 0.9}


async def test_low_confidence_downgrades_to_info():
    ai = FakeAi({"p1": AiResult(
        value={"violations": [{"rule": "r", "reason": "x"}], "confidence": 0.3},
        status="ok", error_code=None, prompt_tokens=1, completion_tokens=1,
    )})
    findings = await AiPolicyCheck().check([{"title": "p1"}], ["p1"], make_ctx(ai))
    assert findings[0].severity == "info"


async def test_budget_counts_only_real_calls_and_progresses():
    # 4 products, budget 2: first run checks p1,p2 (cache hits are free)
    cached = AiResult(value={"violations": []}, status="cache_hit", error_code=None,
                      prompt_tokens=0, completion_tokens=0)
    real = AiResult(value={"violations": []}, status="ok", error_code=None,
                    prompt_tokens=1, completion_tokens=1)
    ai = FakeAi({"p1": cached, "p2": cached, "p3": real, "p4": real})
    products = [{"title": pid} for pid in ["p1", "p2", "p3", "p4"]]
    findings = await AiPolicyCheck().check(products, ["p1", "p2", "p3", "p4"], make_ctx(ai, budget=2))
    assert ai.calls == ["p1", "p2", "p3", "p4"]  # cache hits free, so all four checked


async def test_revalidates_previous_findings_first():
    ai = FakeAi({"p2": AiResult(value={"violations": []}, status="ok", error_code=None,
                                prompt_tokens=1, completion_tokens=1),
                 "p1": AiResult(value={"violations": []}, status="ok", error_code=None,
                                prompt_tokens=1, completion_tokens=1)})
    await AiPolicyCheck().check([{"title": "p1"}, {"title": "p2"}], ["p1", "p2"],
                                make_ctx(ai, budget=1, prev=frozenset({"p2"})))
    assert ai.calls == ["p2"]


async def test_all_failed_emits_unavailable_finding():
    ai = FakeAi({"p1": AiResult(value=None, status="fallback", error_code="no_provider",
                                prompt_tokens=0, completion_tokens=0)})
    findings = await AiPolicyCheck().check([{"title": "p1"}], ["p1"], make_ctx(ai))
    assert len(findings) == 1
    assert findings[0].severity == "info"
    assert "unavailable" in findings[0].message


async def test_budget_exhausted_emits_coverage_finding():
    real = AiResult(value={"violations": []}, status="ok", error_code=None,
                    prompt_tokens=1, completion_tokens=1)
    ai = FakeAi({pid: real for pid in ["p1", "p2", "p3"]})
    products = [{"title": pid} for pid in ["p1", "p2", "p3"]]
    findings = await AiPolicyCheck().check(products, ["p1", "p2", "p3"], make_ctx(ai, budget=1))
    assert any("budget" in f.message and f.product_id == "" for f in findings)


async def test_disabled_when_no_service_or_budget():
    assert await AiPolicyCheck().check([{"title": "x"}], ["x"], make_ctx(None)) == []
```

- [ ] **Step 2: Run** `uv run pytest tests/test_ai_policy_check.py -v` — FAIL (module missing).

- [ ] **Step 3: Implement** `backend/app/qc/ai_rules.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .engine import CrossProductRule, Finding, QcContext

logger = logging.getLogger(__name__)

CHUNK_SIZE = 10
CONFIDENCE_FLOOR = 0.5


class AiPolicyCheck:
    """AI policy QC: budgeted, cache-aware, re-validates previous findings first.

    ponytail: synchronous in-run batching; background/async QC only if runs
    demonstratively suffer at budget 50.
    """

    rule_id = "ai_policy_check"

    async def check(
        self, products: list[dict], product_ids: list[str], ctx: QcContext
    ) -> list[Finding]:
        if ctx.ai_service is None or ctx.ai_budget <= 0:
            return []
        pairs = list(zip(product_ids, products))
        prev = ctx.previous_ai_product_ids
        ordered = [p for p in pairs if p[0] in prev] + [p for p in pairs if p[0] not in prev]

        findings: list[Finding] = []
        spent = 0
        checked = 0
        failed = 0
        index = 0
        while index < len(ordered) and spent < ctx.ai_budget:
            chunk = ordered[index:index + CHUNK_SIZE]
            index += len(chunk)
            results = await asyncio.gather(
                *[self._check_one(pid, product, ctx) for pid, product in chunk]
            )
            for (_pid, _product), (status, chunk_findings) in zip(chunk, results):
                checked += 1
                if status == "ok":
                    spent += 1
                elif status == "fallback":
                    failed += 1
                findings.extend(chunk_findings)

        if checked == 0:
            return []
        if failed == checked:
            return [Finding(
                rule_id=self.rule_id, severity="info", field=None,
                message="AI policy check unavailable for this run",
                details={"checked": checked, "failed": failed},
            )]
        if spent >= ctx.ai_budget and checked < len(ordered):
            findings.append(Finding(
                rule_id=self.rule_id, severity="info", field=None,
                message="AI policy check covered part of the catalog (budget)",
                details={"checked": checked, "total": len(ordered)},
            ))
        return findings

    async def _check_one(
        self, product_id: str, product: dict, ctx: QcContext
    ) -> tuple[str, list[Finding]]:
        try:
            result = await ctx.ai_service.run_task(
                "policy_check",
                {"title": product.get("title"), "description": product.get("description")},
                client_id=ctx.client_id,
                feed_source_id=ctx.feed_source_id,
            )
        except Exception:  # noqa: BLE001 — QC never aborts the run
            logger.exception("ai policy check failed for product %s", product_id)
            return "fallback", []
        if result.status == "fallback":
            return "fallback", []
        value = result.value if isinstance(result.value, dict) else {}
        confidence = value.get("confidence")
        severity = "warning"
        if isinstance(confidence, (int, float)) and confidence < CONFIDENCE_FLOOR:
            severity = "info"
        out = [
            Finding(
                rule_id=self.rule_id, severity=severity, field=None,
                message=str(v.get("reason") or "policy violation"),
                product_id=product_id,
                details={"ai_rule": v.get("rule"), "confidence": confidence},
            )
            for v in value.get("violations") or []
            if isinstance(v, dict)
        ]
        return result.status, out
```

- [ ] **Step 4: Run** `uv run pytest tests/test_ai_policy_check.py -v` — pass.

- [ ] **Step 5: Commit** `git add backend/app/qc/ai_rules.py backend/tests/test_ai_policy_check.py && git commit -m "feat: ai policy check rule (budget, progression, re-validation)"`

---

### Task 3: QualityCheckStep wiring

**Files:**
- Modify: `backend/app/pipeline/steps.py` (QualityCheckStep + default_steps), `backend/app/main.py` (AiService before steps)
- Test: `backend/tests/test_pipeline_steps.py` (extend)

**Interfaces:**
- Consumes: `AiPolicyCheck` from Task 2; `FeedSource.configuration["ai_qc"] = {enabled: bool, budget: int}`.
- Produces: `QualityCheckStep(registry, clock, image_probe, ai_service=None)`; `default_steps(..., ai_service=None)`.

- [ ] **Step 1: Write failing test** — in `test_pipeline_steps.py`, a test building `QualityCheckStep(registry, clock, ai_service=fake)` whose execute (against a seeded feed source with `configuration={"ai_qc": {"enabled": True, "budget": 5}}`) populates the QcContext passed to rules: assert via a recording cross rule injected... simpler: assert the step's `_load_ai_context` helper output. Prefer a small extracted helper:

```python
async def _ai_qc_context(session_factory, feed_source_id, ai_service) -> tuple[Any, int | None, int, frozenset[str]]:
    """Returns (ai_service_or_None, client_id, budget, previous_ai_product_ids)."""
```

Test the helper directly: enabled config → budget from config + previous ids loaded from seeded findings; disabled → `(None, client_id, 0, frozenset())`.

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement** in `steps.py`:

```python
class QualityCheckStep:
    name = "quality_check"

    def __init__(
        self,
        registry: RegistryDocument,
        clock: Clock,
        image_probe: ImageProbe | None = None,
        ai_service: Any = None,
    ) -> None:
        ...
        self._ai_service = ai_service
```

Add the helper (module level, after the class or before it):

```python
async def _ai_qc_context(
    session_factory: Callable[[], AsyncSession],
    feed_source: FeedSource,
    ai_service: Any,
) -> tuple[Any, int | None, int, frozenset[str]]:
    cfg = (feed_source.configuration or {}).get("ai_qc") or {}
    if not cfg.get("enabled") or ai_service is None:
        return None, feed_source.client_id, 0, frozenset()
    from sqlalchemy import select as sa_select

    from ..models.quality import QualityFinding

    async with session_factory() as session:
        ids = frozenset((await session.execute(
            sa_select(QualityFinding.product_id).where(
                QualityFinding.feed_source_id == feed_source.id,
                QualityFinding.code == "ai_policy_check",
            )
        )).scalars())
    budget = max(1, int(cfg.get("budget", 50)))
    return ai_service, feed_source.client_id, budget, ids
```

In `execute`, after loading `feed_source` and `previous_export_run`:

```python
        ai_service, client_id, ai_budget, previous_ai_ids = await _ai_qc_context(
            ctx.session_factory, feed_source, self._ai_service
        )
```

Pass into QcContext and append the rule:

```python
        cross_product_rules: list[CrossProductRule] = [VariantConsistency(), VolumeDrop()]
        if ai_service is not None:
            from ..qc.ai_rules import AiPolicyCheck

            cross_product_rules.append(AiPolicyCheck())
        qc_ctx = QcContext(
            ...,  # existing fields unchanged
            ai_service=ai_service,
            client_id=client_id,
            ai_budget=ai_budget,
            previous_ai_product_ids=previous_ai_ids,
        )
```

`default_steps` gains `ai_service: Any = None` (keyword, after `public_base_url`) and passes it: `QualityCheckStep(registry, clock, image_probe, ai_service)`.

In `backend/app/main.py`: the block at ~line 264 builds `steps = default_steps(...)` BEFORE `app.state.ai_service = AiService(...)` (~line 280). Move the AiService construction above the `default_steps` call and pass `ai_service=ai_service` to it (keep the later `app.state.ai_service = ai_service` assignment).

- [ ] **Step 4: Run** `uv run pytest tests/test_pipeline_steps.py tests/test_ai_policy_check.py -x` then the full backend suite.

- [ ] **Step 5: Commit** `git add backend/app/pipeline/steps.py backend/app/main.py backend/tests/test_pipeline_steps.py && git commit -m "feat: wire ai policy check into qc step with per-feed config"`

---

### Task 4: Setup form — AI-QC section

**Files:**
- Modify: `frontend/src/features/setup/FeedSettingsForm.tsx`
- Test: `frontend/src/features/setup/FeedSettingsForm.test.tsx` (extend)
- i18n: `frontend/public/locales/en/setup.json`, `de/setup.json`

**Interfaces:**
- Consumes: `useUpdateFeedSource` (already accepts `configuration`); FeedSourceRow.configuration.
- Produces: `configuration.ai_qc = {enabled: boolean, budget: number}` written on change.

- [ ] **Step 1: Write failing test** — render the form for a feed with `configuration: {}`; toggle the AI-QC switch, set budget 25, submit; assert the PUT body contains `configuration: {ai_qc: {enabled: true, budget: 25}}` (and that a pre-existing `basic_auth` key is preserved — mirror the existing test's fetch spy).

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement** in `FeedSettingsForm.tsx`:

```tsx
const aiQcCfg = (feed.configuration as Record<string, unknown> | undefined)?.ai_qc as Record<string, unknown> | undefined;
const [aiQcEnabled, setAiQcEnabled] = useState(Boolean(aiQcCfg?.enabled));
const [aiQcBudget, setAiQcBudget] = useState<number>(Number(aiQcCfg?.budget ?? 50));
```

In `onSubmit`, replace the configuration block with a merged builder:

```tsx
      const existingCfg = (feed.configuration ?? {}) as Record<string, unknown>;
      const cfgUpdate: Record<string, unknown> = {};
      const originalUsername = /* existing basic_auth username read, unchanged */;
      if (username !== originalUsername || password) {
        cfgUpdate.basic_auth = {
          ...((existingCfg.basic_auth ?? {}) as Record<string, unknown>),
          username,
          ...(password ? { password } : {}),
        };
      }
      if (aiQcEnabled !== Boolean(aiQcCfg?.enabled) || aiQcBudget !== Number(aiQcCfg?.budget ?? 50)) {
        cfgUpdate.ai_qc = { enabled: aiQcEnabled, budget: aiQcBudget };
      }
      if (Object.keys(cfgUpdate).length > 0) {
        payload.configuration = { ...existingCfg, ...cfgUpdate };
      }
```

UI in the form Stack (after the cron field):

```tsx
<Switch
  label={t('fields.aiQcEnabled')}
  checked={aiQcEnabled}
  onChange={(e) => setAiQcEnabled(e.currentTarget.checked)}
/>
<NumberInput
  label={t('fields.aiQcBudget')}
  value={aiQcBudget}
  onChange={(v) => setAiQcBudget(typeof v === 'number' ? v : 50)}
  min={1}
  max={1000}
  disabled={!aiQcEnabled}
/>
```

i18n en: `"aiQcEnabled": "AI quality check (policy)", "aiQcBudget": "AI calls per run"`; de: `"aiQcEnabled": "KI-Qualitätsprüfung (Richtlinien)", "aiQcBudget": "KI-Aufrufe pro Run"`.

- [ ] **Step 4: Run** `npx vitest run src/features/setup && npm run typecheck` — pass.

- [ ] **Step 5: Commit** `git add frontend/src/features/setup frontend/public/locales && git commit -m "feat: ai-qc config section in feed settings"`

---

### Task 5: Docs + full gates

**Files:**
- Modify: `backend/docs/architecture.md` (QC section: AI rules, budget/progression semantics), `backend/docs/data-model.md` (`configuration.ai_qc` key), `docs/decisions.md` (Z3 entry: cross-rule interface for per-product findings, image_quality deferral), `frontend/docs/architecture.md` (setup section).

- [ ] **Step 1: Docs** — dated decisions.md entry (Topic/Decision/Rationale).

- [ ] **Step 2: Full gates** — backend ruff/mypy/pytest; frontend typecheck/vitest/build. No migration this cycle: run `uv run alembic check` to prove it.

- [ ] **Step 3: Commit** `git add -A && git commit -m "docs: z3 ai qc rules cycle notes"`
