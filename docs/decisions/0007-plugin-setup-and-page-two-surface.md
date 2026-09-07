# ADR-0007: Plugin Setup + Plugin Page Two-Surface Model

## Status
Accepted (supersedes the sidebar-removal consequence of ADR-0006; 0006's
panel-hub, tier-switcher, and error-boundary decisions stand)

## Context
After the config-hub cycle (ADR-0006) removed per-plugin sidebar entries,
operator feedback clarified that each plugin has TWO user-facing surfaces:
a Setup surface (Pipeline Editor config panel) and a working Plugin Page that
must stay reachable in the feed navigation — e.g. the Labelizer page shows
the slot dashboard (bulk IDs) while slot rules are configured in Pipeline
Editor → Labelizer Setup; Rules has no special setup and "does its job" on
its plugin page.

## Decision
1. Per-plugin split via the frontend static registry `CONFIG_COMPONENTS`
   (`src/features/plugin/configComponents.ts`, ADR-0002 convention; no
   manifest or backend changes):
   - plugin in `CONFIG_COMPONENTS` → the Pipeline panel embeds its Setup
     component with the Feed/Client/Global tier switcher and the actionable
     read-only alert (ADR-0006 machinery), plus Instance settings;
   - plugin only in `CUSTOM_COMPONENTS` (manifest `frontend.component`) →
     panel shows a hint + "Open plugin page" link to the feed-tier plugin
     page; no raw JSON-schema instance form;
   - neither → generic RJSF instance settings.
2. `custom_labels` splits via `CustomLabelsUI`'s additive `onlyTab` prop:
   `LabelizerPage` (ids-only) on the plugin page; `LabelizerSetup`
   (rules-only) in the panel. The feed-tier rules read-only hint is removed
   — the panel's alert is the actionable path.
3. Sidebar (feed context): Dashboard → Setup → plugin entries (enabled
   plugins with `frontend.component`) → Products → Pipeline → Monitoring →
   Export. Plugin routes remain the same URLs.

## Consequences
- The Labelizer Plugin Page is data-only at every tier; rule editing happens
  in the Pipeline Editor at the tier chosen by the switcher (client/global).
- `rules`/`filter` instance-level RJSF forms are no longer rendered in the
  panel (their `instance.configuration` remains whatever it was; both
  plugins operate through scoped PluginConfig, not instance configuration).
- ADR-0005's merge/value-pinning semantics are unchanged; only the surface
  exposing them moved.
