# ADR-0006: Pipeline Editor as Plugin Config Hub

## Status
Accepted

## Context
Plugin configuration lived on two surfaces: per-instance settings in the
Pipeline Editor (RJSF form over `instance.configuration`) and the rich scoped
UIs (Rules, Filter, Labelizer) on dedicated plugin pages with the three-tier
scope merge. The sidebar linked each plugin by its most specific manifest
scope, which for `custom_labels` (config_scope `["global", "client"]`) landed
users on a feed-tier page whose Slot Rules tab is read-only — a dead end that
sent them elsewhere to manage rules.

## Decision
1. The Pipeline Editor is the single hub for configuring a feed's plugins.
   `PluginConfigPanel` embeds the plugin's registered custom component
   (`CUSTOM_COMPONENTS`) inside a tier switcher (Feed / Client / Global,
   derived from manifest scopes, default Feed) and re-renders it with the
   selected `PluginScope`. Tier semantics stay exactly as designed (ADR 0005):
   Labelizer slot rules remain editable only at Global/Client tier; at Feed
   tier an actionable alert switches to the highest editable tier instead of
   the old dead-end hint.
2. Instance settings remain a separate, labeled section (RJSF over
   `instance.configuration`, saved with pipeline Save). Scoped config saves
   via `/plugins/{id}/config` stay independent transactions.
3. The sidebar "Plugins" section is removed; plugin routes remain as deep
   links (ScopeContextBar tier hrefs, bookmarks).
4. Embedded plugin UIs are wrapped in `PluginErrorBoundary` (ADR 0004
   follow-up now implemented), also used by `PluginPage`.

## Consequences
- Plugin components (`CustomLabelsUI`, `RulesUI`, `FilterUI`), manifests,
  backend routes, and DB schema are unchanged.
- Global-tier config is now reachable from any feed's Pipeline Editor via the
  switcher (previously only via the global plugin route, which still exists).
- The sidebar shows Dashboard + feed items only.
