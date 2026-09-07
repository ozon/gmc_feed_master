# Plugin Setup + Plugin Page (Two-Surface Model) — Design v2

Date: 2026-09-07
Status: Approved (brainstorming session; revises the 2026-09-07 config-hub design)

## Problem

The first config-hub cycle made the Pipeline Editor the configuration hub and
removed the per-plugin sidebar entries. Operator feedback refines the model:
every plugin has TWO user-facing surfaces, and the navigation must keep the
plugin pages reachable:

1. **Setup** — in the Pipeline Editor's config panel: where you configure the
   plugin instance.
2. **Plugin Page** — in the feed navigation: the plugin's working dashboard
   or tool.

Under this model the Labelizer's slot rules are configured in
Pipeline Editor → Labelizer Setup, while the Labelizer Plugin Page shows the
slot dashboard (bulk IDs). Rules has no special setup — its editor "does its
job" on the Rules Plugin Page, found in the navigation.

## Decision

### 1. Per-plugin split via a frontend static registry

A new `CONFIG_COMPONENTS` map in `frontend/src/features/plugin/` (same
static-map convention as `CUSTOM_COMPONENTS`, ADR-0002 — no manifest, backend,
or DB changes) decides what the Pipeline Editor panel shows:

| Plugin | Plugin Page (nav) | Pipeline panel (Setup) |
| --- | --- | --- |
| `custom_labels` | Bulk IDs only — Slot Rules tab removed at ALL tiers | `LabelizerSetup`: slot-rules editor with the Feed/Client/Global tier switcher and the actionable read-only alert (shipped in the config-hub cycle), restricted to rules |
| `rules`, `filter` | The tool itself (rule editor / filter UI), unchanged | Hint + "Open plugin page" link; NO raw JSON-schema instance form (editing raw rule arrays would be a footgun; nothing writes `instance.configuration` for these plugins) |
| schema-only plugins | no nav entry | Instance settings RJSF form (unchanged generic path) |

Panel selection order: `CONFIG_COMPONENTS[id]` → setup embed; else
`CUSTOM_COMPONENTS[id]` → hint + link; else RJSF instance settings.

### 2. Navigation

Sidebar (feed context): **Dashboard → Setup → plugin entries → Products →
Pipeline → Monitoring → Export**. Plugin entries render only for plugins with
`manifest.frontend.component` (Labelizer, Rules, Filter), link to the
feed-tier plugin page (`/clients/:c/feeds/:f/plugins/:id`), label via
`pluginNames.*` i18n, icon via the existing `PluginIconMap` helper
(`getPluginIcon`, shared with `PluginList`). Entries are hidden when no feed
source is in context (same rule as the other feed-scoped items).

### 3. Component refactor (minimal, additive)

- `CustomLabelsUI` gains `onlyTab?: 'ids' | 'rules'`:
  - `onlyTab="ids"` hides the Slot Rules tab (used by the page registry entry);
  - `onlyTab="rules"` hides the Bulk IDs tab (used by `LabelizerSetup`).
- New `frontend/src/features/customLabels/LabelizerSetup.tsx` — thin wrapper
  rendering `CustomLabelsUI` with `onlyTab="rules"`; registered in
  `CONFIG_COMPONENTS.custom_labels`.
- The existing rules-tab tests on the plugin page migrate to the
  `LabelizerSetup` surface (panel); the Bulk-IDs tests stay on the page.
- Tier switcher, `PluginErrorBoundary`, read-only alert with switch action,
  and key-remount semantics in `PluginConfigPanel` are reused unchanged.
- Removing the rules tab from the page makes the old feed-tier read-only
  hint ("manage slot rules at client level") obsolete — it disappears with
  the tab. The panel's alert ("managed at Client level — Switch to Client
  tier") remains the actionable path.

### 4. Docs/ADR

- New **ADR-0007**: "Plugin Setup + Plugin Page two-surface model" — records
  the registry-driven split and supersedes ADR-0006's sidebar-removal
  consequence (0006's panel-hub and boundary decisions stand).
- Update `frontend/docs/architecture.md` (navigation order, two surfaces) and
  `frontend/docs/plugin-uis.md` (page vs setup surfaces, `CONFIG_COMPONENTS`).
- Note in ADR-0005's consequences that the Labelizer page is data-only since
  this cycle (rules configured in Pipeline Editor).

## Scope

Pure frontend. No plugin manifests, backend routes, or DB changes. The
`frontend.menu_item`/`icon` manifest keys: `icon` already renders via
`getPluginIcon`; sidebar labels resolve through `pluginNames.*` i18n
(`menu_item` stays vestigial).

## Testing

- `PluginConfigPanel.test.tsx`: panel picks the surface per registry
  (`CONFIG_COMPONENTS` embed; `CUSTOM_COMPONENTS`-only → hint + link; neither
  → RJSF); link target points at the feed-tier plugin page.
- `CustomLabelsUI.test.tsx`: `onlyTab="ids"` renders no rules tab;
  `onlyTab="rules"` renders no ids tab; existing per-tier request-URL tests
  stay green.
- `LabelizerSetup` covered via the panel tests (wrapper is thin).
- `AppShell.test.tsx`: plugin entries after Setup in feed context, correct
  hrefs, hidden without feed context, only custom-UI plugins listed.
- Full suite + typecheck from `frontend/`.
