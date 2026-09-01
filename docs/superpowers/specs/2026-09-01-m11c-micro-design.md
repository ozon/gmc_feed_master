# M11c Micro-batch — Design

**Date:** 2026-09-01
**Cycle branch:** `m11c-micro` (off main `9b2513e`; merge to main at cycle end)
**Workflow:** subagent-driven development (2 tasks, per-task review), final whole-branch review before merge
**Source:** TODO 1.9 and 1.10, both filed from the m11b cycle's final whole-branch review (carried minors a and b).

## §0 Context

The m11b cycle's final review triaged two UX/quality gaps into TODO entries rather than pre-merge fixes. This micro-cycle closes both. Both are frontend-only, single-component changes with no backend surface.

Owner decision (2026-09-01): scope is exactly 1.9 + 1.10; nothing else pulled in.

## §1 Task 1 — TODO 1.9: Fast-path toggle onError

### §1.1 Problem

`PluginRegistryPanel.tsx` has two disable/enable mutate paths:
- `confirmToggle` (lines 30-46): per-call `onError` — 409 → `notifyError(t('disableBlocked', { count }))`, else `notifyMutationError(error, t('disableFailed'))`. Landed in m11b.
- `onChange`'s fast path (line 27): `toggleEnabled.mutate({ id, enabled })` with NO error handling — taken when enabling, or when the cached `used_by_feed_sources` is 0.

If the plugins query is stale (plugin became used since fetch), the fast-path disable hits the backend 409 (added in m11b) and the error is silently swallowed: the Switch stays correct (server-state-driven, no optimistic update) but the user gets no feedback. Same for any 500 on enable.

### §1.2 Change

Unify both paths through one mutate function so the error handler exists exactly once:

```tsx
  function mutateToggle(plugin: PluginInfo, enabled: boolean) {
    toggleEnabled.mutate(
      { id: plugin.id, enabled },
      {
        onError: (error) => {
          if (error instanceof ApiError && error.status === 409) {
            notifyError(t('disableBlocked', { count: plugin.used_by_feed_sources }));
          } else {
            notifyMutationError(error, t('disableFailed'));
          }
        },
      },
    );
  }

  function onChange(plugin: PluginInfo, next: boolean) {
    if (!next && plugin.used_by_feed_sources > 0) {
      setPendingToggle(plugin);
      return;
    }
    mutateToggle(plugin, next);
  }

  function confirmToggle() {
    if (!pendingToggle) return;
    const plugin = pendingToggle;
    setPendingToggle(null);
    mutateToggle(plugin, false);
  }
```

Notes:
- `confirmToggle` clears `pendingToggle` BEFORE mutating now (ordering swap vs. m11b's mutate-then-clear). Rationale: identical behavior (the modal closes either way; the mutation is fire-and-forget with per-call callbacks) and it removes the captured-`pendingToggle`-vs-`plugin` subtlety the m11b code carried.
- No new i18n keys — reuses `disableBlocked`/`disableFailed`.
- No test changes to the existing 7 panel tests (their assertions are behavior-level: toast text + switch state + PUT payload; the refactor preserves all of them).

### §1.3 Tests (PluginRegistryPanel.test.tsx)

One new test — the stale-cache fast-path 409:

- Fixture: a plugin with `used_by_feed_sources: 0` (no ConfirmModal appears), switch ON.
- Stub PUT `/plugins/{id}/enabled` → 409 `{"detail": "plugin in use by 2 feed sources"}`.
- Click the switch (disable attempt goes straight to mutate).
- Assert the `disableBlocked` toast text appears — regex `/in use by 0 feed sources/i` (the count comes from the panel's stale cache: 0). Binding: the toast MUST fire; the count shown is the panel's cached value by design (no detail-string parsing, per the m11b decision).

### §1.4 Acceptance

- Both mutate call sites share one error handler (single source of truth).
- New test green; all 8 existing panel tests green; full frontend gate green.

## §2 Task 2 — TODO 1.10: Findings badge aria-labels

### §2.1 Problem

The m11b findings badges (ExportVersionList.tsx:75-101) carry severity via color + `title` only. Per the accessible-name computation, `title` on a non-interactive element is not reliably announced; a screen reader gets "2", "0", "5" with no severity. The m10 design sketch (§3) called for `aria-label`; the m11b spec's binding decision dropped it — this task restores the cue.

### §2.2 Change

Each of the three badges gains `aria-label={t('findings.<severity>', { count })}` — the SAME i18n expression already used for `title`. Zero new i18n strings, zero new files, no behavior change for sighted users.

### §2.3 Tests (ExportPage.test.tsx)

One new test (or extend the existing findings tests — binding: extend, don't duplicate):
- Assert `findings-critical-3` has `aria-label` `"2 critical"`, `findings-warning-3` → `"0 warning"`, `findings-info-3` → `"5 info"` (values from the existing fixture; en locale in tests).

### §2.4 Acceptance

- All three badges carry severity-naming aria-labels on every render path (the JSX is one block; the attribute is unconditional within it).
- Existing 3 findings tests stay green (assertions are testid-based, unaffected); full frontend gate green.

## §3 Order of work

1. Branch `m11c-micro` off main.
2. Task 1 (1.9): TDD → review → 1 commit.
3. Task 2 (1.10): TDD → review → 1 commit.
4. Final whole-branch review → merge to main → TODO.md + progress.md → push (owner will confirm).

## §4 Gates

Frontend only: `npm test -- --run && npm run typecheck && npm run build`; `git diff --check` clean. No backend gate needed (no backend files touched) — but the backend suite must not be affected (zero backend changes).

## §5 Out of scope

- The remaining P2 pool (1.3-1.6, 2.2, 3.5, 6.1, 6.2), ruff/mypy ops decision, M11+ planning (8.1), German tooltip pluralization (noted in TODO working notes).
