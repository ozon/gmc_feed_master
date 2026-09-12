from dataclasses import dataclass

import pytest

from app.ai.service import AiResult
from app.qc.ai_rules import AiPolicyCheck
from app.qc.engine import QcContext

pytestmark = pytest.mark.asyncio


@dataclass
class FakeAi:
    scripted: dict  # product_id -> AiResult
    calls: list | None = None

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
    await AiPolicyCheck().check(products, ["p1", "p2", "p3", "p4"], make_ctx(ai, budget=2))
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