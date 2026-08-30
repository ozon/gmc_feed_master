# ADR-0004: Plugin Frontend Error Isolation

## Status
Accepted

## Context
Plugin components (custom or schema-rendered) are dynamically loaded and rendered in the dashboard. A bug in one plugin's UI must not crash the entire application or the build pipeline.

## Decision
**Every plugin component renders inside a React Error Boundary.** Additionally, a **build-time contract test** asserts that `manifest.frontend.component` paths exist and export a valid React component.

### Implementation:
1. **Error Boundary wrapper** — A generic `PluginErrorBoundary` component wraps each plugin's rendered output (config form, data editor, custom page). On error, it shows a fallback UI with the plugin name and error details, logs to console, and isolates the crash.
2. **Build-time contract test** — Vite build scans `plugins/*/frontend/`; a test verifies:
   - `manifest.frontend.component` path resolves to a file
   - The file exports a valid React component (default or named `Component`)
   - TypeScript compilation succeeds for the plugin's frontend code
3. **Mirroring backend isolation** — Backend `PluginStep` catches exceptions per-product, marks product as errored, continues run. Frontend error boundary mirrors this: one broken plugin UI doesn't crash the dashboard or other plugins.

## Consequences
- **Positive**: Resilient dashboard — operator can still use other plugins and core features; clear error attribution per plugin; build fails fast on missing/invalid plugin frontends.
- **Negative**: Slight wrapper overhead; contract test adds CI time; custom plugin components must be valid React (no Vue/Svelte/etc.).
- **Fallback UI**: Shows plugin name, error message, "Reload plugin" button (triggers key remount), and link to plugin settings.

## Rejected Alternative
**No isolation / try-catch in render** — Rejected because: React errors during render cannot be caught by try-catch (they bubble to nearest error boundary); a single plugin crash would unmount the entire `AppShell` or route; poor operator experience.