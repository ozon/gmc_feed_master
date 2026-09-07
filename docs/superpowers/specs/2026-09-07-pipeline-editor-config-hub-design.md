# Pipeline Editor as Plugin Config Hub — Design

Date: 2026-09-07
Status: Approved (brainstorming session)

## Problem

Users on a feed's product page (`/clients/1/feeds/9/products`) who navigate to plugin
configuration hit a dead end: on the feed-tier Labelizer page the Slot Rules tab shows
"Slot rules are read-only here — they live at Global or Client level. Manage slot rules
at client level". The root causes:

1. **Two config surfaces.** Per-instance settings are edited in the Pipeline Editor
   (`.../pipeline`, `PluginConfigPanel`, RJSF form, saved with the pipeline), while the
   rich scoped plugin UIs (`RulesUI`, `CustomLabelsUI`, `FilterUI`) live on separate
   plugin pages (`.../plugins/:pluginId`) with the 3-tier scope merge.
2. **Tier opacity.** The sidebar links each plugin by its most specific manifest scope
   (`isFeedScoped` → feed-tier page). For `custom_labels`, `config_scope` is
   `["global", "client"]`, so that link lands on a page where the main tab is read-only.
3. **Poor instance config UX.** In the Pipeline Editor, rich plugins degrade to the raw
   JSON-schema form (or nothing) — Rules "has no settings" there.

## Decision

The Pipeline Editor becomes the single hub for configuring a feed's plugins.
Slot-rule tiering stays as designed (ADR 0005): `custom_labels` manifest scopes are
unchanged; no backend, API, or manifest changes. Pure frontend.

1. **Sidebar (`AppShell.tsx`)**: the "Plugins" section is removed. Navigation is
   Dashboard + per-feed items (Setup, Products, Pipeline, Monitoring, Export).
   Plugin routes (`/plugins/:id`, `/clients/:c/plugins/:id`,
   `/clients/:c/feeds/:f/plugins/:id`) remain as deep links (ScopeContextBar hrefs,
   bookmarks) but are no longer advertised.
2. **`PluginConfigPanel` becomes the config hub.** With an instance selected:
   - A **tier switcher** (Feed / Client / Global) derived from manifest scopes ∩ route
     context; default Feed. It maps to existing `PluginScope`s: Feed →
     `{feedSourceId}`, Client → `{clientId}`, Global → `{}`.
   - A **PLUGIN CONFIG** section rendered when `manifest.frontend.component` exists:
     the registered custom component (from `CUSTOM_COMPONENTS`) is embedded with
     `scope` = selected tier, re-mounted via `key={scope}` so local state resets
     between tiers. Wrapped in the same plugin error boundary `PluginPage` uses
     (ADR 0004) so a crashing plugin UI cannot take down the editor.
   - An **INSTANCE SETTINGS** section, always present: the existing RJSF form over
     `instance.configuration`, saved with the pipeline Save (unchanged).
   - Sections are labeled and save independently: scoped config via
     `/plugins/:id/config` at the selected tier (its own save button and dirty state),
     instance settings via pipeline Save. No mixed transactions.
3. **Read-only becomes actionable.** When the manifest's `config_scope` does not include
   `feed_source` (Labelizer at Feed tier), the panel shows an alert — "Slot rules are
   managed at Client level" — with a **Switch to Client tier** button that flips the
   switcher. The dead-end sentence remains only on the standalone deep-link pages,
   where its client-level link is correct. Plugin components themselves are unchanged.

## Data flow

- No new client stores. Embedded components keep using `usePluginConfig` /
  `useSavePluginConfig` / `usePluginData` / `useSavePluginData` (TanStack Query, ADR
  0001); query keys are per-scope, so tier switching just changes the query input.
- `PluginConfigPanel` reads `clientId` / `feedSourceId` from route params to build the
  tier scopes; it does not own scoped-config state.
- Pipeline dirty tracking (`useBlocker` in `PipelinePage`) still guards instance
  changes; each embedded component keeps its own unsaved-changes guard.

## Components touched

| File | Change |
| --- | --- |
| `frontend/src/features/pipeline/PluginConfigPanel.tsx` | Tier switcher, embedded custom component + error boundary, section labels, read-only alert with switch action |
| `frontend/src/features/pipeline/PipelinePage.tsx` | Pass route context / plugin manifests needed by the panel (if not already available) |
| `frontend/src/app/AppShell.tsx` | Remove Plugins nav section (`pluginItems` block, `isClientScoped`/`isFeedScoped` if unused) |
| `frontend/src/i18n/**` | New `pipeline` namespace strings: section labels, tier names, read-only alert |
| `frontend/docs/architecture.md`, `frontend/docs/plugin-uis.md` | Navigation + embedding changes |
| `docs/decisions/0006-pipeline-editor-config-hub.md` | New ADR recording the decision |

Untouched: `CustomLabelsUI`, `RulesUI`, `FilterUI`, all plugin manifests, backend
routes, DB schema.

## Testing

- `PluginConfigPanel.test.tsx`: tier options derived from manifest scopes; switching
  re-renders the embedded component with the right scope prop; read-only alert +
  switch action for `custom_labels` at Feed tier; instance-settings form still calls
  `onChange`; component absent when no `frontend.component`.
- `PipelinePage.test.tsx`: panel receives route context; pipeline Save unchanged.
- `AppShell` test: Plugins section absent from the sidebar.
- Existing `CustomLabelsUI` / `RulesUI` tests remain green (components unchanged).
- Verify: `npm run test`, `npm run typecheck` from `frontend/`.

## Risks / notes

- Embedded rich UIs (dnd rule list, slot grid) inside the panel's 8-col layout are
  narrower than the standalone pages; acceptable — the standalone pages remain as
  deep links for comfortable full-width editing.
- Global-tier editing is now reachable from any feed's Pipeline Editor (switcher →
  Global); previously it required the global plugin route. The routes stay anyway.
- Plugin contract tests unaffected (no plugin API/manifest change).
