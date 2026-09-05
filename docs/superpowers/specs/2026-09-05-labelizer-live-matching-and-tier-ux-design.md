# Labelizer: Live Matching, Slot-Grouped Bulk Tab, and Tier UX — Design

Date: 2026-09-05
Status: Approved (brainstorm with operator)
Scope: `plugins/core/custom_labels` (plugin-local preview route) + Pipeline Frontend
(`frontend/src/features/customLabels`, `frontend/src/components/ScopeContextBar`) + docs
Builds on: `2026-09-05-labelizer-plugin-ux-design.md` (merged view, rule modes, rename)

## Problem

1. The Bulk values tab is a flat row of rule columns with no context: no per-slot
   information, no idea how many feed products a rule or slot actually labels.
2. No live feedback while editing: users must save and run the pipeline to see
   whether their IDs/templates match anything.
3. Slot rules can be added but never duplicated or deleted from the UI.
4. The feed-page read-only hint ("Slot rules are shared templates managed at
   global or client scope…") is abstract and confuses users.
5. Global/Client tier UX is a dead end: tier badges are static (no navigation,
   the global page is URL-only), and an inherited global rule cannot be
   overridden from the client page.

## Decisions (operator-approved in brainstorm)

- **Live matching: plugin-local preview endpoint** (Approach A — filter-plugin
  precedent). The UI sends its current merged DRAFT state; the backend evaluates
  it against staged products with the plugin's own engine. No TS engine port,
  no dry-run reuse (dry-run only sees saved config).
- **Bulk tab grouped by target slot** (`custom_label_0..4`), each group headed by
  an info box: static slot explanation + live stats (labeled products, coverage,
  per-rule breakdown) + nested rule editors.
- **Info box content: all of** live stats + short slot explanation + per-rule
  breakdown (operator picked all).
- **Rule actions:** Duplicate (new id, "name (copy)") and Delete (confirm) —
  editable-origin rules only.
- **Read-only hint reworded** to a short, action-oriented sentence with the
  existing client-level link.
- **Clickable tier navigation** via `hrefs` on ScopeContextBar badges.
- **Override at client level** for inherited rules: same-id client-origin copy
  (union-by-id makes it a true runtime override).

## 1. Preview endpoint (plugin-local route)

- `plugins/core/custom_labels/plugin.py` gains `register_routes(self, router)`
  mounting `POST /preview` → served at `POST /plugins/custom_labels/preview`
  (non-reserved subpath; mirrors `plugins/core/filter/plugin.py:127-176`).
- **Request** (pydantic model, function-local like filter's):
  ```json
  {
    "feed_source_id": 1,
    "rules": [ { ...slotRule draft objects, matchMode included } ],
    "slotIds": { "<rule-id>": "value list text" },
    "sample_size": 5
  }
  ```
  `sample_size` optional, `ge=1 le=50`, default 5.
- **Validation:** `validate_config({"slotRules": rules})` — invalid drafts return
  `422 {"errors": [...]}` exactly like the plugin's config PUT; unknown feed → 404;
  db unavailable → 503 (filter precedent).
- **Evaluation:** one query over staged products for the feed
  (`StagingProduct` where `feed_source_id`, `status == "active"`,
  `excluded.is_(False)`) selecting `(product_id, raw_data)`. `raw_data` is the
  mapped, registry-shaped product — the same shape the plugin sees at run time
  (`backend/app/staging/persistence.py:78` writes `raw_data=u.product` post-mapping).
  A new pure helper `evaluate_rules(rules, slot_ids, rows, sample_size)` in
  plugin.py reuses the plugin's primitives (`_build_state`-shaped preparation,
  `matches`, `render_template`) and the process() decision order (first-match-wins
  per slot, `matchAll`, token-skip, first-rule fallback).
- **Response:**
  ```json
  {
    "total": 1234,
    "rules": { "<id>": { "matched": 10, "labeled": 8, "sample": ["a1", "b2"] } },
    "slots": {
      "custom_label_1": {
        "labeled": 45, "coverage": 3.6,
        "rules": ["g1", "c3"]
      }
    }
  }
  ```
  - `rules[id].matched` — products the rule matches (matchAll counts every
    product); `labeled` — products for which this rule produced the final slot
    value; `sample` — up to `sample_size` matching `product_id`s.
  - `slots[slot].rules` — rule ids in winning order; `coverage` — labeled/total
    percent, `0` when `total == 0`.
- Inactive rules are excluded (same as `_build_state`). Rules referencing slots
  with no staged matches still appear in `rules`/`slots` with zero counts.

## 2. Frontend preview hook

- New `frontend/src/features/customLabels/usePreview.ts`:
  - `useLabelizerPreview()` returns `{ preview, isPending, result, error }`
    wrapping a TanStack mutation calling
    `apiPost('/plugins/custom_labels/preview', payload)`.
  - Debounced (~500 ms) on changes to the merged DRAFT rules + slotIds; only
    active when the URL tier is a feed (`feedSourceId` known) — the only tier
    with staged products in context.
  - Stale guard: a sequence number per call; only the newest response is applied.
  - 422 → per-rule/field error list surfaced inline under the group info box;
    404/503/network → dimmed "Live preview unavailable" line, non-blocking,
    retried on next edit.
- TanStack Query only (no client stores) — the preview is server state.

## 3. Bulk tab: grouped by target slot

- The flat `Group wrap="nowrap"` rule-column row is replaced by a vertical
  `Stack` of slot groups, ordered `custom_label_0..4`.
- **Slot group = info box card + nested rule editors.**
  - Info box (Card header): slot name (`custom_label_1`), short static
    explanation (en + de — what the slot is for in Google Shopping campaign
    structuring, generic wording), rules-targeting count, live stats
    (labeled products, coverage %, per-rule breakdown like
    "Mid Funnel · 120 match"), freshness hint
    ("based on the last run's N staged products").
  - Nested under it: the existing per-rule editors (values textarea with dynamic
    label, or all-mode "controlled by rule" summary + override button), stacked
    with their inherited badges and editability unchanged.
- Slots with no active rules render as slim dimmed rows
  ("custom_label_2 — no rules yet"). All five slots always visible.
- Live stats render from the preview response; per-rule breakdown lines live in
  the info box (this is where "infos above the slots" land — the info box IS the
  group header).

## 4. Non-feed pages (client/global)

- Info boxes render with the static explanation + rules count; the live-stats
  section is replaced by a dimmed hint: "Open this plugin from a feed to see
  live match stats." No preview request is sent.

## 5. Rule actions (Slot rules tab)

- In the rule editor card, a compact action row:
  - **Duplicate** (editable-origin rules only): copies the selected rule with a
    fresh id, `name (copy)`, same slot, inserted immediately after the
    original; selects the copy; dirty until Save.
  - **Delete** (editable-origin rules only): ConfirmModal confirmation, then
    removes the rule from the editable tier's list; dirty until Save (Cancel
    still reverts).
  - Both hidden for inherited rules and on the feed page.

## 6. Read-only hint reword

- en: "Slot rules are read-only here — they live at Global or Client level. →"
  followed by the existing "Manage at client level" link. The ScopeContextBar
  above already communicates which tiers apply.
- de: „Slot-Regeln sind hier schreibgeschützt — sie liegen auf Global- oder
  Client-Ebene. →" + „Auf Client-Ebene verwalten".
- Key `rulesReadOnly` replaced in both locales; the `rules-readonly-hint`
  testid stays.

## 7. Clickable tier navigation (ScopeContextBar)

- `ScopeContextBar` gains an optional `hrefs?: Partial<Record<Tier, string>>`
  prop. Badges for tiers present in `hrefs` render as links (Mantine polymorphic
  `Badge component={Link}`), except the current tier (static filled badge, no
  self-link).
- `CustomLabelsUI` computes the map from route context:
  `{ global: `/plugins/${pluginId}`, client: routeContext.clientId ? `/clients/${clientId}/plugins/${pluginId}` : undefined, feed_source: feed page URL }`
  filtered so the current tier is excluded.
- Effect: the client page links to Global; the feed page links to both Global
  and Client; the previously URL-only global page becomes reachable.
- Component stays generic: no Labelizer-specific logic inside.

## 8. Override at client level

- On the **client page**, the editor card of a global-origin rule shows
  "Override at client level" (where the read-only note sits now).
- Action: replaces the rule in the local list with a client-origin copy at the
  same position, **same id** (union-by-id ⇒ client content wins at runtime — a
  true override, not an additional rule), immediately editable, dirty until
  Save. Cancel reverts to the global-origin view. After saving, the rule is
  client-origin: badge gone, Duplicate/Delete available.
- Local state never holds two entries with the same id (the override swaps
  origin in place); `mergeSlotRules`'s first-seen order is untouched.
- Feed page: no override action (config read-only there; the hint links to the
  client page). Global page: nothing to override (all rules already global).

## Error handling

- Preview: 422 inline (draft invalid), 404/503 dimmed non-blocking, stale
  responses discarded. Preview failures never block editing or saving.
- Override/Duplicate/Delete are pure local-state operations guarded by the
  existing unsaved-changes blocker; Delete adds a confirm.
- Tier navigation is pure routing (react-router `Link`).

## Testing

- Backend: new `backend/tests/test_custom_labels_preview.py` — route mounted at
  `/plugins/custom_labels/preview`; 404 unknown feed; 422 invalid draft; counts
  against seeded staged rows (plain match, matchAll, first-match-wins per slot,
  token-skip + fallback, excluded/inactive product filtering, sample cap,
  coverage math incl. total=0).
- Frontend: `usePreview` hook tests (debounce, stale guard, 422 surfacing);
  component tests — slot groups render in order with info boxes, live stats
  render from a stubbed preview, slim empty-slot rows, non-feed hint, duplicate/
  delete actions (visible/editable-origin only), override flips origin and
  saves only client rules, ScopeContextBar link badges + current-tier static.
- i18n: all new strings in en + de (slot explanations ×5, stats labels, action
  labels, reworded hints).
- Gates: `uv run pytest -n auto`, `uvx ruff/mypy` (zero new in touched files),
  `npm run test`, `npm run typecheck`, `npm run build`, plugin contract test.

## Documentation (same commit)

- `backend/docs/plugins.md` — custom_labels preview route (extend the filter
  preview precedent section).
- `frontend/docs/plugin-uis.md` — grouped bulk tab, live stats, rule actions,
  tier navigation, override semantics.
- No API/data-model changes beyond the plugin-local route → `backend/docs/api.md`
  gains only the preview endpoint if plugin routes are listed there.

## Out of scope

- Client-side TS port of the match engine.
- Live stats on client/global pages (no feed products in context there).
- Blast-radius info ("inherited by N clients") — deferred.
- Reordering/visual regrouping of the merged rules list beyond existing badges.
