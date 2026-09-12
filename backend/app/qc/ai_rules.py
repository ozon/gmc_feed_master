from __future__ import annotations

import logging
from typing import Any

from .engine import Finding, QcContext

logger = logging.getLogger(__name__)

CHUNK_SIZE = 10


class AiPolicyCheck:
    """AI-powered policy check. Budget counts real (non-cache) calls only."""

    rule_id = "ai_policy_check"

    async def check(
        self, products: list[dict], product_ids: list[str], ctx: QcContext
    ) -> list[Finding]:
        if ctx.ai_service is None or ctx.ai_budget <= 0:
            return []

        by_id = dict(zip(product_ids, products))
        ordered = [
            pid for pid in ctx.previous_ai_product_ids if pid in by_id
        ] + [pid for pid in product_ids if pid not in ctx.previous_ai_product_ids]

        findings: list[Finding] = []
        checked = 0
        spent = 0
        failed = 0

        for pid in ordered:
            if spent >= ctx.ai_budget:
                break
            result = await ctx.ai_service.run_task(
                "policy_check",
                {"title": by_id[pid].get("title", ""), "description": by_id[pid].get("description", "")},
                client_id=ctx.client_id,
                feed_source_id=ctx.feed_source_id,
            )
            checked += 1
            if result.status == "ok":
                spent += 1
                findings.extend(_violation_findings(pid, result.value))
            elif result.status == "fallback":
                failed += 1

        if checked and failed == checked:
            findings.append(Finding(
                rule_id=self.rule_id, severity="info", field=None,
                message="AI policy check unavailable",
            ))
        elif checked < len(ordered):
            findings.append(Finding(
                rule_id=self.rule_id, severity="info", field=None,
                message=f"AI policy budget exhausted, {len(ordered) - checked} products unchecked",
            ))
        return findings


def _violation_findings(pid: str, value: Any) -> list[Finding]:
    if not isinstance(value, dict):
        return []
    violations = value.get("violations") or []
    confidence = value.get("confidence")
    findings = []
    for v in violations:
        severity = "warning" if confidence is None or confidence >= 0.5 else "info"
        findings.append(Finding(
            rule_id="ai_policy_check", severity=severity,
            field="ai_policy", product_id=pid,
            message=f"AI policy violation: {v.get('rule', 'unknown')} — {v.get('reason', '')}",
            details={"ai_rule": v.get("rule"), "confidence": confidence},
        ))
    return findings
