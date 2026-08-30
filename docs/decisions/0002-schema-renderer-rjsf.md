# ADR-0002: RJSF for Schema-Rendered Plugin UIs

## Status
Accepted

## Context
Plugin configuration and data UIs need to be rendered from JSON Schema manifests (Pydantic v2 output, JSON Schema draft 2020-12). Options: custom JSON Schema renderer vs. `@rjsf/core` with `@rjsf/mantine` theme.

## Decision
Use **`@rjsf/core` + `@rjsf/mantine`** for schema-rendered plugin configuration/data forms.

### Key reasons:
1. **JSON Schema draft 2020-12 compliance** — Pydantic v2 emits 2020-12 schemas; RJSF supports this draft via AJV configuration.
2. **Mantine theme integration** — `@rjsf/mantine` provides native Mantine component mapping (TextInput, Select, Switch, NumberInput) without wrapper code.
3. **Client-side validation via AJV** — Configured for 2020-12 draft; immediate feedback before submit.
4. **Server-side validation stays authoritative** — Backend returns 422 with `{"errors":[...]}`; frontend surfaces these in the form via `notifyApiError` → `mapFieldErrors`.
5. **Optional `uischema` support** — Plugins may declare layout hints (order, grouping, custom widgets) in `manifest.frontend.uischema` without forking the renderer.
6. **Maintenance** — Battle-tested library (10k+ stars) vs. custom renderer maintenance burden.

## Consequences
- **Positive**: Zero custom form code for standard plugins; consistent UX across plugins; schema changes auto-propagate to UI; leverages existing Mantine design system.
- **Negative**: Additional dependency (~45 kB gzipped for core + Mantine theme); AJV configuration complexity for 2020-12 draft; advanced layouts require `uischema` knowledge.
- **Migration path**: Custom plugin components (`manifest.frontend.component`) bypass RJSF entirely for complex UIs (Labelizer dimension editor, Category rule builder).

## Rejected Alternative
**Custom JSON Schema renderer** — Rejected because: duplicating RJSF's feature set (conditional fields, arrays, enums, validation, themes) would take significant effort; ongoing maintenance for schema spec updates; inconsistent UX risk.