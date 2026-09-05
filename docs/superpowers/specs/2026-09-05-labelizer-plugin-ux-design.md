# Labelizer (Custom Labels plugin) UX Overhaul — Design

Date: 2026-09-05
Status: Approved (design review with operator; amended after spec review — see §1.1)
Scope: Pipeline Frontend + `plugins/core/custom_labels` (config schema + runtime) +
`backend/app/staging/config_resolver.py` (opt-in list merge) + docs

## Problem

1. **Slots invisible on the feed page.** The Custom Labels nav item only appears inside a
   feed context. On that page (`/clients/:c/feeds/:f/plugins/custom_labels`) slot rules are
   fetched at the **client** tier (fallback), but `GET /plugins/{id}/config` returns only the
   exact-tier payload — no merge. Rules saved at **global** tier never appear, and the Bulk IDs
   tab then reports "No active slot rules". The same asymmetry applies to data (bulk values).
2. **No visual distinction between Global and Feed-specific settings.** Users cannot tell
   which tier they are viewing/editing.
3. **Match field is a raw text input** (with a datalist); `id` is not required to be the match
   field but nothing presents the available product fields.
4. **Active switch has unclear effect.**
5. **Rule-based grouping makes the explicit ID textarea redundant** — the UI must adapt to the
   rule mode instead of always showing a value-list textarea.
6. **No description or user guide** on the plugin page.
7. **Rename:** the UI should say "Labelizer" everywhere, without touching plugin id or backend.

## Decisions (approved by operator)

- Merged scope view: **frontend multi-fetch + client-side merge** (Approach A). No backend
  GET/PUT API changes.
- Labelizer rename: **i18n display-name override** (Approach A). Plugin id `custom_labels`,
  manifest `name`, backend names untouched.
- Rule modes: **two modes** — `values` (explicit value list, today's behavior) and `all`
  (every product matches, label derived from the value template; no list needed).
- Help content: **inline description + "How it works" accordion + full user guide in a Drawer**.
- Rename applies to **every UI mention** (nav, title, tabs/fields wording).
- Active switch: **clarify the effect** (description + visual state), no auto-save.
- **Spec review amendment (operator):** the frontend union-by-id merge is only truthful if the
  runtime does the same union. The generic three-tier merge replaces list values wholesale
  (`test_config_merge.py` pins `{"rules": [1,2,3]} + {"rules": [9]} == {"rules": [9]}`), so
  `slotRules` gets a **plugin-specific, manifest-declared union-by-id merge at runtime** (§1.1),
  pinned by a **mandatory equivalence test** (§1.2). If the equivalence cannot be established,
  the merge moves to a **backend resolved-view endpoint** instead of the frontend.

## 1. Merged scope view

### Config (slot rules)

- `CustomLabelsUI` resolves the **tier chain** for config: every declared config tier reachable
  from the URL — `global` (`{}`) always; `client` (`{clientId}`) when the route has `clientId`.
  Each tier is fetched with its own `usePluginConfig` query, in parallel.
- Merge `slotRules` **exactly as the runtime does after §1.1** (union by rule `id` in runtime
  order — see §1.1 for the ordering definition). Each merged rule carries
  `origin: 'global' | 'client'`. The old wording "client-before-global conflict, global-first
  display" is superseded: **content from the more specific tier wins; list order follows the
  runtime order (global positions first, client-only rules appended)**, so display order and
  per-slot winning order are the same in UI and runs.
- Editability per URL tier:
  - **Global page** (`/plugins/custom_labels`): all rules editable; Save writes the global tier.
  - **Client page** (`/clients/:c/plugins/custom_labels`): global-origin rules read-only with a
    `[Global]` ScopeBadge; client-origin rules editable. **Save writes only client-origin rules**
    (plus newly created ones) to the client tier — global rules are never copied downward.
  - **Feed page** (`/clients/:c/feeds/:f/plugins/custom_labels`): merged view is fully
    read-only (config_scope has no feed tier); every rule badged with its origin; the existing
    read-only hint gains a link "Manage slot rules at client level" →
    `/clients/:c/plugins/custom_labels`.
- Draggable reordering is disabled for read-only/inherited rules (unchanged rule: drag only
  reorders the editable tier's rules).

### Data (bulk values)

- Same tier-chain pattern for data: current URL tier + declared ancestor tiers reachable
  (`client` when at feed scope). Merge `slotIds` per rule id for display; values inherited from
  an ancestor tier get an "inherited" ScopeBadge and remain editable.
- **Save writes the merged dict to the current tier.** Trade-off (accepted, ADR 0005): saved
  inherited values are pinned to the current tier — ancestor-tier edits stop propagating to a
  feed after its first save. The run-time overlay merge
  (`backend/app/staging/config_resolver.py`) makes this behaviorally identical.

### Error handling

- Any tier query in error → `ErrorState` with retry (existing component). All-or-nothing
  loading: `Loader` until every enabled tier query resolves.

## 1.1 Runtime merge semantics (union-by-id for `slotRules`)

**Problem being fixed:** the generic three-tier merge (`config_resolver._merge_dicts`) replaces
list values wholesale. With global + client configs both present, the client `slotRules` array
would fully erase the global list at run time — the merged UI view would be a fiction, and
list ordering would be undefined.

- **Manifest-declared merge strategy (new, opt-in extension point):**
  `plugins/core/custom_labels/plugin.json` adds
  `"config_merge": {"slotRules": {"strategy": "union_by_key", "key": "id"}}`.
- `config_resolver._resolve_declared` consults the plugin manifest's `config_merge` when
  merging declared tiers: for a key with the `union_by_key` strategy, the merged list starts
  from the ancestor (global) list **in its original order**; a same-id rule from a more
  specific tier **replaces it in place**; ids not seen before are **appended** in the more
  specific tier's order. (Identical to the existing per-key dict-merge order — that is what
  makes the UI's "global rules first" display truthful.)
- Keys without a declared strategy keep today's wholesale-replacement semantics —
  `test_config_merge.py` stays green, no behavior change for other plugins.
- `slotIds` (data) is already an id-keyed object, so the generic per-key dict merge unions it
  naturally (`test_custom_labels_delta.py` pins this) — no data-side runtime change.
- This adds a manifest extension point and changes effective run behavior for
  `custom_labels` when client-tier config exists (global rules now run alongside/overridden
  instead of being erased). `config_hash` changes accordingly — that is the intended product
  behavior, directed by the operator in spec review.

## 1.2 Mandatory equivalence verification (gate)

- A **shared fixture**: global rules `[g1, g2]` and client rules `[c1 (overrides g1's id), c2
  (client-only), c3 (same target slot as g2)]`.
- **Backend test** (next to `test_config_bundle.py` / `test_config_merge.py`): assert
  `config_resolver`'s effective `slotRules` for the fixture — exact id sequence and order
  (`[g1→c1 content, g2, c2, c3]`) and the per-slot winning rule under first-match-wins
  (`process()` iterates `by_slot` in list order).
- **Frontend test** (merge helper unit test, same fixture): assert the frontend merge produces
  the **same id list in the same order** and the same per-slot winner.
- **Decision rule:** if either mismatch ((a) conflict/display ordering or (b) wholesale list
  replacement) cannot be eliminated, the merge moves to a **backend resolved-view endpoint**
  instead of the frontend — the UI then renders exactly what the runtime computes.

## 2. Scope distinction UX (reusable pattern)

New shared components (usable by any settings screen):

- `frontend/src/components/ScopeBadge.tsx` — Mantine `Badge` + `Tooltip`.
  Colors: Global = violet, Client = blue, Feed = teal. Labels via i18n (`common` namespace).
- `frontend/src/components/ScopeContextBar.tsx` — persistent context strip rendered at the top
  of the plugin page: "Viewing: `[Feed]` — Slot rules: `[Global]`/`[Client]` · Bulk values:
  `[Client]`/`[Feed]`", making the editable tier obvious at a glance. Uses `Paper` with subtle
  background tinting; sticky within the content area.

Rule rows show an origin ScopeBadge when the rule is inherited from another tier. Inherited
inputs are disabled with a Tooltip "Managed at [Global] level".

## 3. Match field dropdown

Replace the `TextInput` + `<datalist>` with a searchable Mantine `Combobox`:

- Options grouped with `Combobox.Group` (group label = registry attribute name; options =
  `attr` and `attr.sub_field`), sourced from `useRegistryAttributes()`.
- **Free-text custom entry**: typing any value and pressing Enter submits it (Combobox
  `onOptionSubmit` + `TextInput` target pattern from Mantine docs; dropdown hidden when the
  search matches nothing, the typed value is kept).
- The field is not restricted to `id`; new rules still default to `id` (sensible default, not a
  requirement).

## 4. Rule modes

- New optional field on each slot rule: `matchMode: 'values' | 'all'`, default `'values'`
  (backward compatible — existing configs behave exactly as today).
- Editor: `SegmentedControl` with the two modes:
  - **values**: current behavior. In the Bulk values tab the textarea label adapts to the match
    field ("Product IDs" when match field is `id`, otherwise "Values for {field}").
  - **all**: no value list. In the Bulk values tab the textarea is replaced by a summary chip:
    "Controlled by rule — every product gets: `{template preview}`" with a one-click
    "Switch to value list" override button (returns to `values` mode).
- Transitions between the two states use Mantine `Collapse` for smooth show/hide.
- Fallback-template mechanics unchanged (first rule of a slot declares it); `all` rules may
  also declare a fallback for the token-skip case.

### Backend changes (plugin-local + opt-in resolver strategy)

- `plugins/core/custom_labels/plugin.json`:
  - `config_schema`: add `matchMode: {enum: ["values","all"], default: "values"}`.
  - `config_merge`: add the `slotRules` union-by-id strategy (§1.1). No other manifest change.
- `plugins/core/custom_labels/plugin.py`:
  - `_build_state`: carry `match_mode` into prepared rules.
  - `process`: a rule with `match_mode == 'all'` always matches (value list ignored/absent);
    template rendering and fallback logic unchanged.
  - `validate_config`: unchanged requirements (the rule `id` remains required — it is the
    internal stable key for bulk-value lists; "ID is not required" refers to the match field,
    which the dropdown addresses).
- Config-hash impact: editing rules changes `config_hash` as usual; adding the optional
  `matchMode` field to existing configs is not required and does not change behavior.

## 5. Active switch clarity

- `description` under the switch: "Inactive rules are skipped during runs and hidden from
  bulk value lists." (i18n, en + de).
- Inactive rule rows render dimmed (opacity) with an "inactive" Badge.
- No auto-save — Save button flow unchanged.

## 6. Description + user guide

Inside `CustomLabelsUI` (so it follows the plugin UI everywhere):

- Short inline `Text c="dimmed"` description under the page title: what Labelizer does
  (assigns `custom_label_0`–`custom_label_4` from slot rules).
- Collapsible "How it works" `Accordion` (3–4 short items: rules & slots, match modes,
  templates, scope tiers).
- `ActionIcon` "?" in the header opening a `Drawer` (right side, scrollable) with the full
  guide: concepts, slot rules, match modes + examples, value templates & token skip,
  fallback templates, bulk values, scope tiers, and a short "getting started" walkthrough.

## 7. Labelizer rename (UI only)

- `common.json` (en + de): `pluginNames.custom_labels: "Labelizer"`.
- `AppShell` nav label and `PluginPage` title resolve via
  `t(`pluginNames.${plugin.id}`, { defaultValue: <manifest name> })`.
- All `customLabels.json` strings reworded to "Labelizer" where the plugin name appears;
  GMC field names (`custom_label_0`–`4`) keep their technical wording.

## 8. Nav entries for multi-scope plugins (documentation-only)

Document (in `frontend/docs/plugin-uis.md`) how nav entries are derived, since custom_labels
is feed+client scoped and therefore only appears inside a feed context today: `AppShell` reads
`manifest.config_scope`/`data_scope`; feed-scoped plugins link to
`` ${feedBase}/plugins/{id} `` (hidden without a feed selected), client-scoped plugins link to
`/clients/:c/plugins/{id}`, otherwise `/plugins/{id}`. `manifest.frontend.menu_item` supplies
the label (now overridden by `pluginNames` i18n).

## Testing

- **Mandatory equivalence tests (§1.2)** — backend (`config_resolver` fixture: exact id
  sequence, order, per-slot winner) and frontend (same fixture against the merge helper); these
  gate the frontend-merge architecture.
- Frontend (`vitest` + RTL): extend `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
  — merged view (global rules visible + badged + read-only on client/feed pages), save filters
  to editable tier only, match-mode SegmentedControl switching, bulk tab dynamic
  relabeling/summary state, Combobox selection + custom entry, help Drawer, ScopeBadge
  rendering. `i18n.test.tsx` gains a `pluginNames` key check.
- Backend: plugin tests for `matchMode: 'all'` (match-all, template render, fallback), default
  `values` behavior unchanged; `uv run pytest tests/test_plugin_contract.py`; existing
  `test_config_merge.py` / `test_custom_labels_delta.py` stay green.
- Verification commands: `npm run test`, `npm run typecheck`, `npm run build`,
  `uv run pytest -n auto`, `uv run ruff check .`, `uv run mypy .`.

## Documentation (same commit)

- `frontend/docs/plugin-uis.md` — custom component behaviors: merged scope view, rule modes,
  help UI, ScopeBadge/ScopeContextBar pattern, nav-entry derivation for multi-scope plugins (§8).
- `backend/docs/plugins.md` — custom_labels example updated for `matchMode` and the
  manifest-declared `config_merge` union-by-id strategy; `backend/docs/architecture.md`
  three-tier-merge section extended with the opt-in list-merge strategy.
- New ADR `docs/decisions/0005-labelizer-scope-merge-and-value-pinning.md` — records (a) the
  union-by-id runtime merge decision and equivalence-test gate (with the resolved-view-endpoint
  fallback), and (b) the owner-accepted trade-off that **ancestor-tier bulk-value edits stop
  propagating to a feed after its first save** (pin-on-save). Update the AGENTS.md
  documentation map with ADR 0005.
- No REST API/data-model changes → `backend/docs/api.md`, `data-model.md` unaffected.

## Out of scope

- A backend merged GET endpoint — **fallback only** if the §1.2 equivalence gate fails.
- Auto-save for the Active switch.
- Renaming the plugin id, manifest name, or any backend identifier.
- Applying ScopeContextBar to non-plugin settings screens (pattern is reusable; adoption
  happens separately).
