# ADR-0005: Labelizer Scope Merge and Value Pinning

## Status
Accepted

## Context
The generic three-tier scope merge (`app/staging/config_resolver.py`) replaces
list values wholesale: a client-tier `slotRules` array would fully erase global
rules at run time, while the Labelizer UI needs to show global and client rules
merged. Spec review (2026-09-05) mandated a verification test proving the
frontend merge and the runtime resolution produce the same effective
`slotRules` (same ids, same per-slot winning order), with a backend
resolved-view endpoint as fallback if they diverge.

## Decision
1. **Manifest-declared list merge strategy.** Plugins may declare
   `"config_merge": {"<key>": {"strategy": "union_by_key", "key": "<id>"}}`.
   The resolver then unions lists by key: ancestor rules keep their positions,
   more-specific content wins by key, unseen entries are appended. Keys without
   a hint keep wholesale replacement.
2. **Equivalence gate.** Backend and frontend tests pin the same fixture
   (global + client rules) and assert identical merged id order and per-slot
   winning order. If the gate cannot be satisfied, the merge moves to a
   backend resolved-view endpoint instead of the frontend.
3. **Bulk-value pinning (owner-accepted trade-off).** The bulk-values tab saves
   the merged value dict to the current tier. Consequence: **ancestor-tier
   bulk-value edits stop propagating to a feed after its first save** — saved
   inherited values are pinned to the feed tier. Run-time overlay semantics make
   the effective values identical at save time.

## Consequences
- `custom_labels` with global + client configs now runs global rules
  (overridden per id) instead of dropping them; `config_hash` changes
  accordingly — intended behavior.
- The `config_merge` manifest key is a new, opt-in extension point validated by
  `parse_manifest`.
- Other plugins are unaffected (default semantics unchanged).
- Since ADR-0007 the Labelizer Plugin Page is data-only (bulk IDs); slot
  rules are edited in Pipeline Editor → Labelizer Setup at the tier chosen
  by the panel's switcher.
