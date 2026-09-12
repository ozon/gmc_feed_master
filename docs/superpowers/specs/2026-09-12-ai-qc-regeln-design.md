# Z3: AI-QC-Regeln (policy_check) — Design

Date: 2026-09-12
Status: Approved in brainstorming (operator)
Baseline: main at d58bcfb (Z1, Z2, Z4 specs committed, not yet implemented)
Roadmap: `2026-09-12-ai-restarbeiten-design.md` — this is cycle Z3.

## Decisions (operator)
- **Scope: `policy_check` only.** `image_quality` is deferred: it requires multimodal messages in the AIProvider protocol (content parts with `image_url` — today `AiRequest.messages` is text-only) and a vision-capable provider. The builtin spec passing a URL as text was a stub. The existing `ImageProbe` (resolution check) is unaffected.
- **Cost model: per-run AI-call budget with progression.** Budget counts only real AI calls (`AiResult.status == "ok"`); cache hits are free, so each run works further through the catalog.
- **Config per feed source** in `FeedSource.configuration["ai_qc"] = {enabled: bool, budget: int}` (default: disabled, budget 50). Setup form: Switch + NumberInput in FeedSettingsForm.

## Rule design

### Interface: CrossProductRule with per-product findings
`AiPolicyCheck` implements `CrossProductRule` — it receives the full product list, can `asyncio.gather` internally (chunk size ~10; AiService's per-provider semaphore throttles), and drives the budget logic. It emits **per-product findings with `product_id` set** (the engine passes cross-rule findings through unchanged; `persist_findings` stores the product_id). A PerProductRule interface would be sequential — 50 × 2s pipeline stall under the feed lock.

### Ordering: re-validate before progressing
1. First: products whose `product_id` appears in the **previous run's `ai_policy_check` findings** (loaded by QualityCheckStep before persist's feed-keyed delete). Unchanged products are cache hits — free.
2. Then: remaining products in list order until the budget of real AI calls is exhausted.

Rationale: the Z2 delta counts "fixed" as snapshot-difference. Without re-validation a finding would show as fixed merely because the budget ran out before its product — a false quality improvement. With re-validate-first, "fixed" is honest, and stays free thanks to the AI cache.

### QcContext extension
New fields with defaults (existing rule tests untouched): `ai_service`, `client_id`, `ai_budget`, `previous_ai_product_ids`. `QualityCheckStep` reads `feed_source.configuration["ai_qc"]`, resolves `client_id`, loads previous AI findings, and instantiates the rule only when enabled.

### Severity mapping (fixed, documented)
- AI violation → **warning** (deterministic rules remain the only critical source; AI is advisory).
- `confidence < 0.5` → downgraded to **info**.
- Finding shape: `field=None`, `message=reason`, `details={ai_rule, confidence}`, `code="ai_policy_check"`.
- No violations → no findings.

### Failure visibility (never silent)
- AI unavailable (no provider, circuit open, invalid response) → **one** info-level feed-wide finding "AI policy check unavailable" with the error code in details.
- Budget exhausted before all products → one info-level finding "N of M products checked (budget)" with counters in details.

### Usage attribution
`run_task("policy_check", {title, description}, client_id, feed_source_id)` — costs per feed source appear in the admin usage page for free.

## Latency ceiling
Budget 50 / provider concurrency 4 ≈ 25–30s added to a run in the worst case (all cache misses). Deliberate ceiling (`ponytail:` background/async QC only if runs demonstrably suffer).

## Testing
- Rule unit tests: violation mapping, confidence downgrade, budget stop, re-validate ordering, unavailable finding, coverage finding.
- Step wiring: config read (enabled/disabled), QcContext population, rule not instantiated when disabled.
- Persistence: findings carry `code="ai_policy_check"` and correct product_id.
- Z2 interplay: a finding disappears from the delta only after its product was actually re-checked clean (or vanished from the feed).

## Docs (same commit)
`backend/docs/architecture.md` (QC section: AI rules), `backend/docs/data-model.md` (configuration key), `docs/decisions.md` (Z3: cross-rule interface for per-product findings, budget+progression, image_quality deferral), `frontend/docs/architecture.md` (setup form section). No new endpoints.

## Out of scope
image_quality (multimodal provider protocol + vision model — own cycle); configurable severity; per-client QC config; AI-rule onboarding UI (prompt customizable via the existing template library).
