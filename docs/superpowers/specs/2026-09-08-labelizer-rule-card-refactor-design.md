# Labelizer Rule Card Refactor — Dashboard Breakdown, Toolbar, Toggleable Preview & Footer Cleanup — Design

Date: 2026-09-08
Status: Approved (brainstorming session 2026-09-08)
Scope: Labelizer **data page** rule cards + coverage dashboard (frontend only; supersedes parts of the 2026-09-08 product-preview design's layout section, ADR-0008 §2).

## Problem

The shipped rule-card editor (2026-09-08) has four shortcomings:

1. The Coverage Dashboard shows only aggregate totals — users can't see which rule contributes how many *net* label wins.
2. The value Textarea has no quick utilities (clear, normalize/format) — users manually groom large pasted lists.
3. The preview column is always visible at feed tier and the 7/13 Grid resizes the textarea; row alignment is by parsed-entry index (commas split, blanks dropped), so raw pastes misalign lines vs. rows, and a vertical padding offset shifts the textarea's first line against preview row 0.
4. The card footer duplicates shadow information as a struck-through "Overridden IDs" list even though the header badge already summarizes it.

## Decisions (from brainstorming)

1. **Virtualization:** keep the existing custom fixed-row windowing (`windowRange` in `productPreview.ts`). `@tanstack/react-virtual` stays rejected (ADR-0008 §2) — the windowing already renders only the visible slice ± overscan; no new dependency.
2. **Line alignment:** preview row *i* = textarea **line** *i* (split on `\n` only; blank lines render blank rows so alignment always holds). A line holding several comma-separated IDs shows the **first ID's match** plus a dimmed `+{{count}} more` badge; the lookup still covers the union of all IDs. The Format button normalizes commas to one ID per line.
3. **Toggle scope:** one shared preview-visibility toggle lifted to `CustomLabelsUI` (collapsed by default, applies to all cards, survives accordion collapse).
4. **Shadow attribution:** `computeShadowing` now emits the owner rule id alongside the name (already tracked internally, previously discarded); `CustomLabelsUI` resolves owner id → slot priority for the inline `OVERRIDDEN BY #N` badge.

## 1. Coverage Dashboard per-rule breakdown

`CoverageDashboard` (`frontend/src/features/customLabels/CoverageDashboard.tsx`) keeps its current aggregate stats (feed-wide `total` / `labeledAny` from the existing preview endpoint) and gains:

- `slotRules: ReadonlyArray<{ id: string; name: string }>` — the selected slot's active rules in evaluation order (the same list that renders the cards below it).
- `ruleStats: Readonly<Record<string, PreviewRuleStats>> | undefined` — from `useLabelizerPreview`'s result.

Directly beneath the `Progress` bar it renders a `Group` (wrapping) of `Badge variant="light"` chips:

- Format: `#1 Bleeder: 18x` — i18n key `coverage.ruleHits` = `#{{priority}} {{name}}: {{count}}×` (`#{{priority}} {{name}}: {{count}}×` for de).
- Count = `ruleStats[rule.id].labeled` — the backend's `evaluate_rules` already increments `labeled` only for the **net winner** per product (shadowed matches only increment `matched`), so this is the post-shadowing assignment count. **No backend change.**
- Badges render only while `ruleStats` is populated; the pending state keeps the existing `Loader`.
- Inactive rules are excluded (they never win). `all`-mode rules participate with their `labeled` stats.
- Priority is the index within the passed `slotRules` array + 1 — identical to the rule-card `#N` and the dashboard-beneath card order.

## 2. Toolbar above the Textarea

Inside `RuleValuesEditor`, a `Group justify="space-between" wrap="nowrap"` row directly above the `Textarea`:

- **Left — `ActionIcon.Group`** (with `aria-label`, `Tooltip` on each):
  1. **Clear** — `IconTrash`, label reuses existing `clearValues` key ("Clear value list"); calls `onSetIds('')`; disabled when `value === ''`.
  2. **Format & dedupe** — `IconWand`, new key `formatDedupe` ("Format & remove duplicates"); calls `onSetIds(formatIdList(value))` (§4); disabled when `value === ''`.
  3. **Toggle preview** — `IconEye` (collapsed) / `IconEyeOff` (open), new key `togglePreview` ("Show/hide product preview"); rendered **only at feed tier** (`feedSourceId !== undefined`); flips the shared `previewOpen` disclosure.
- **Right:** the existing extra-fields `MultiSelect` moves from the deleted "Matched products" header row into the toolbar, visible only while the preview is open (it configures the preview).
- **Footer:** keeps `N unique IDs` + match-field text; the `CloseButton` is removed (the toolbar trash replaces it). The `previewTitle` i18n key is retired with the header row.

## 3. Layout & fixed width

The `Grid` (cols 20, spans 7/13) is replaced by a single `Group align="stretch" gap="xs" wrap="nowrap"`:

- **Textarea wrapper:** `flex: 0 0 380px` — bounded width in **both** states (collapsed and expanded).
- **Preview wrapper:** `flex: 1 1 auto`, rendered only when `previewOpen && feedSourceId !== undefined`; collapsed by default.
- **Flush edges:** `ROW_HEIGHT = 44` and `VIEWPORT_ROWS = 10` (constants in `productPreview.ts`). Textarea: `minRows={10} maxRows={10} autosize`, `wrap="off"`, monospace, `styles.input: { lineHeight: '44px', paddingTop: 0, paddingBottom: 0, paddingInline: 8 }`. Zero vertical padding makes textarea line *i*'s top exactly `i × 44`, matching absolutely-positioned preview rows (this also removes the constant top offset the 34px layout carried). Textarea input and preview viewport each carry a 1px border → both boxes 442px tall; top and bottom edges align flush. Preview rows keep `px="xs"` for matching horizontal rhythm.
- Without a feed source (client/global tier): no toolbar toggle, no preview column, no MultiSelect — full-width editor as today, width no longer forced.

## 4. Strict 1:1 rows, formatting, scroll sync

- **`parsePreviewLines(raw): string[][]`** in `ids.ts` (replaces and deletes `parseIdEntries`): split on `\n` only; row *i* = line *i* trimmed and comma-split into ID tokens (empty tokens dropped). A blank line yields `[]` and renders a blank dimmed row — line↔row alignment never breaks. Row content is driven by the line's **first ID**; a line with several IDs shows the first ID's match plus a dimmed `+{{count}} more` badge (new key `nMoreIds`). The debounced lookup still sends the union of all IDs (`useProductLookup` unchanged).
- **`formatIdList(raw): string`** in `ids.ts`: trims each token, strips empty lines, splits comma groups to one ID per line, removes duplicate IDs preserving first-occurrence order, joins with `\n`. After formatting the list is canonical 1:1. Pure and unit-tested.
- **Inline badges (fixed 44px rows, `nowrap`, truncation — no flex displacement):**
  - `ID NOT FOUND IN FEED` — existing red `Badge` (field `id`) / `No match in feed` (other fields), unchanged semantics.
  - **`OVERRIDDEN BY #N`** — new orange `Badge` at the row's left when the line's first ID is shadowed for this rule; tooltip shows the owner rule name (existing `shadowedBy` key). Renders alongside the product match (a shadowed ID can still show its product info).
- **Shadow data:** `computeShadowing` (`shadowing.ts`) output changes to `shadowedBy: Map<string, { id: string; name: string }>` (owner id no longer discarded). `CustomLabelsUI` enriches it: owner priority = index of the owner rule in the selected slot's active rule list + 1 (the same numbering shown everywhere else), then passes per-rule `ReadonlyMap<string, { ownerName: string; ownerPriority: number }>` through `RuleCard` → `RuleValuesEditor` → `ProductPreviewColumn`. The header badge (`N overridden`) switches to the same map's `size` — visually unchanged.
- **Scroll sync:** unchanged `useSyncedScroll` bidirectional `scrollTop` copy (plain-div viewport is the scroll container); `rebindKey` extends to include `previewOpen` so listeners re-attach when the preview column mounts/unmounts. Windowing stays custom (`windowRange`, 44px rows, overscan 5).

## 5. Footer cleanup

- `ShadowList.tsx` and its render in `RuleCard` are deleted; i18n key `shadowListTitle` removed (en + de).
- Shadowed status survives only via the card header badge (`8 OVERRIDDEN`, `shadowedCount`) and the inline `OVERRIDDEN BY #N` row badges.

## 6. i18n changes (en + de, `customLabels` ns)

- **Add:** `coverage.ruleHits`, `formatDedupe`, `togglePreview`, `overriddenBy` ("Overridden by #{{priority}}"), `nMoreIds` ("+{{count}} more").
- **Remove:** `shadowListTitle`, `previewTitle`.
- **Reused unchanged:** `clearValues`, `shadowedBy`, `idNotFoundInFeed`, `noMatchInFeed`, `nProducts`, `shadowedCount`, `idCount`.

## 7. Testing

- `ids.test.ts`: `parsePreviewLines` (line rows, blank lines, comma lines, trimming) and `formatIdList` (strip empties, comma split, order-preserving dedupe); `parseIdEntries` tests removed.
- `shadowing.test.ts`: enriched `shadowedBy` map shape (id + name).
- `RuleCard.test.tsx`: footer shadow list gone; inline `OVERRIDDEN BY #2` badge with tooltip; toolbar clear/format/toggle wired to `onSetIds`/toggle; preview absent by default at feed tier and present after toggle; no-feed-tier card shows no toggle.
- `ProductPreviewColumn.test.tsx`: rows by line index, blank rows, first-ID match + `+N more` badge, override badge, 44px positioning.
- `CustomLabelsUI.test.tsx`: dashboard `#1 …: 18x` badges (net `labeled`), shared toggle across cards, footer cleanup.
- `productPreview.test.ts`: `windowRange` against `ROW_HEIGHT = 44`.
- Gates: `npm run test`, `npm run typecheck`, `npm run build` (frontend only — no backend/plugin code touched; contract tests unaffected).

## 8. Documentation

ADR-0008 (`docs/decisions/0008-labelizer-product-preview-and-batch-lookup.md`) is updated in the same commit: §2's 35/65 Grid split, always-visible preview, 34px rows and parsed-entry alignment are superseded by the 380px fixed-width flex split, collapsed-by-default toggle, 44px line-index alignment, inline override badges, and the footer removal. Backend endpoint and semantics (§1, §3) unchanged.

## Out of scope

- Backend changes of any kind (preview endpoint, lookup endpoint, `evaluate_rules`).
- `@tanstack/react-virtual` (no new dependencies).
- Persisting the preview toggle or extra-field selections (session-local state only).
- Clickable dashboard badges / rule navigation.
- The Slot rules tab, scope merge, or plugin runtime.
