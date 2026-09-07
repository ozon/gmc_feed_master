# Labelizer UI Improvements — Design

Date: 2026-09-07
Scope: frontend only (`frontend/src/features/customLabels/`, locales, tests). No backend/API changes.

## Problem

The Labelizer "Bulk IDs" tab is cluttered and vertically unwieldy:

1. Value-list textareas stack vertically inside each slot card and grow without
   limit (`autosize`, no cap) — long ID lists make the page extremely tall.
2. Each slot card carries a live-preview stats header ("X products get this
   label · Y% coverage · based on the last run's N staged products", per-rule
   "N match" lines, sample product links, "never applied" badges) that the
   operator wants removed.
3. Slot cards with and without rules are all stacked in one long column; empty
   slots each take a full row for a "no rules yet" line.

## Approved Changes

### 1. Side-by-side bulk ID inputs, capped at 400px (SlotGroup.tsx)

- Wrap the per-rule blocks (name row + textarea / all-mode paper) in a
  `SimpleGrid` with `cols={{ base: 1, sm: 2 }}` so rule inputs sit side-by-side,
  equal width, top-aligned.
- `Textarea`: keep `autosize minRows={5}`; add
  `styles={{ input: { maxHeight: 400, overflowY: 'auto' } }}` — hard 400px cap
  with native scrollbar (Mantine `maxRows` caps by row count only, not px).
- Monospace font for ID lists:
  `fontFamily: 'var(--mantine-font-family-monospace)'` on the input style.

### 2. Redesigned stats header over each slot (SlotGroup.tsx)

Replace the current multi-line stats text block with a compact header per
slot card:

- **Slot-level header line:** "X of N products labeled" (`X` = slot labeled
  count, `N` = total staged products) followed by a slim `Progress` bar
  filled to the coverage %. Rendered only at feed level (`showLive`) with a
  preview result; nothing rendered at client level.
- **Per-rule stats move out of the header** into each rule's input block: a
  small light Badge next to the rule name ("N matched"). When
  `matched > 0 && labeled === 0`, the badge gets the existing "never applied"
  tooltip explaining shadowing/empty renders.
- **Sample product links are dropped** entirely (no deep-links into the
  Products page); the preview response's `sample` field is simply not
  rendered. `productsHref` prop is removed.
- Minimal state lines remain in the header area, only at feed level:
  - `previewUnavailable` → "Live preview unavailable."
  - `previewErrors` → the 422 validation error lines (otherwise broken rules
    fail silently)
  - `total === 0` → "No staged products yet — run the pipeline first."
  - `previewPending` → small inline `Loader` next to the header stats
- Remove the `openFromFeed` hint ("Open this plugin from a feed to see live
  match stats") — the client-level page shows no header stats.
- `SlotGroupProps`: drop `stats` shape in favor of the preview fields
  (`labeled`, `coverage`, `total`, per-rule `matched`/`labeled`), keep
  `previewPending`, `previewErrors`, `previewUnavailable`, `showLive`; drop
  `productsHref`.
- `CustomLabelsUI.tsx`: stop passing `productsHref`; delete its computation.
  `Link` import stays (used by the rules tab).
- The `useLabelizerPreview` hook and the backend preview endpoint are
  unchanged — the response is just rendered differently.

### 3. Compact slot layout (CustomLabelsUI.tsx)

- Slot cards that have rules go into a `SimpleGrid cols={{ base: 1, lg: 2 }}`
  (two columns on wide screens).
- Slots without rules collapse into a single summary row below the grid:
  dimmed text + one small badge per empty slot (instead of five separate
  full-width rows). Uses a new `emptySlots` lead-in key; the per-slot
  `noRulesYet` key is removed.

### 4. Per-textarea clear button + unsaved-changes indicator

- Rule header row gets a `CloseButton` (visible only when the value list is
  non-empty, localized `aria-label`) that empties that rule's textarea.
- Slot badge gets an orange `Indicator` dot while the slot has unsaved edits
  (any of the slot's rule values differs from the merged server value and
  `dirtyIds` is true). Computed in `CustomLabelsUI` and passed down as a
  `dirty` boolean prop.

### 5. i18n (en + de)

- Remove unused keys: `openFromFeed`, `slotLabeled`, `coveragePct`,
  `freshnessHint`.
- Rework/add: `slotLabeledOf` ("{{count}} of {{total}} staged products
  labeled"), `matchedCount` becomes "{{count}} matched" (badge).
- Keep: `previewUnavailable`, `noStagedProducts`, `idCount`,
  `neverApplied`, `neverAppliedHint`.
- Add: `clearValues` (clear-button aria label), `emptySlots` (summary row
  lead-in) in both locales.

### 6. ID counter inline

- Move the "{{count}} unique IDs" line into the textarea's `bottomSection`
  (renders inside the input border), removing the separate line below.

## Testing / Verification

- Update `CustomLabelsUI.test.tsx`:
  - "live preview stats" describe: rework assertions for the new header —
    "X of N staged products labeled" text + Progress bar, per-rule "N matched"
    badge with "never applied" tooltip; no sample product links. Keep the
    total=0 → "no staged products" test; keep "no preview request on client
    page" (drop the removed hint assertion).
  - New tests: clear button empties the textarea; bottomSection counter
    renders; dirty indicator appears only with unsaved edits; preview error
    lines render.
- `npm run test`, `npm run typecheck` from `frontend/`.
- Docs (same change set, per AGENTS.md):
  - `frontend/docs/plugin-uis.md` (~line 224): update the Labelizer
    description — stats header is now "X of N labeled" + coverage progress
    bar, per-rule "N matched" badges on the input blocks, sample product
    links removed.
  - `frontend/docs/architecture.md` (~line 161): update the `custom_labels`
    entry to match the redesigned stats header.
  - Backend docs (`backend/docs/api.md`, `backend/docs/plugins.md`) unchanged:
    they document the preview endpoint's response shape, which is untouched.

## Out of scope

- Backend preview endpoint shape (unchanged; response fields still returned).
- The "Slot rules" tab layout.
- Chip/tag-based ID entry, file import.
