# GMC Feed Master — Frontend Agent Instructions

## WHAT
React 19 + TypeScript + Vite. Mantine UI, TanStack Query (server state), TanStack Table (data grids), TanStack Form (core forms), dnd-kit (pipeline builder), i18next (i18n).

## HOW
```bash
# From frontend/
npm install
npm run dev              # Vite dev server (copy .env.example to .env.local; certs for HTTPS)
npm run build            # typecheck + production build
npm run test             # vitest
npm run typecheck        # tsc -b
npm run lint             # oxlint (type-aware); errors fail, warnings capped
npm run format:check     # oxfmt check; npm run format to write
```

## Key conventions
- **Server state only in TanStack Query** — `queryClient` in `src/api/queryClient.ts`, keys in `src/api/queryKeys.ts`, hooks in `src/api/hooks.ts`. No duplicate stores.
- **Client state** — React built-ins only (`useState`/`useReducer`/Context).
- **Plugin UIs** — build-time discovery via Vite scan of `plugins/*/frontend/`; auto-rendered from JSON Schema (Mantine-themed `JsonSchemaForm` in `src/components/JsonSchemaForm.tsx`); custom components via `manifest.frontend.component`.
- **Pipeline builder** — dnd-kit in `src/features/pipeline/`; workspace state is local React state.
- **Routing** — `src/app/router.tsx` with lazy-loaded pages; session guard via `RequireSession`.
- **Error handling** — `notifyApiError` in `src/app/notifications.ts` maps 422 field errors to form fields.
- **Logging** — `src/logging/logger.ts`. Use `createLogger(scope)`; `debug`/`info` stay in the console, `warn`/`error` are also batched and shipped to `POST /logs/client` (redacted client-side). Report unexpected throws with `captureException(error, { scope, ...context })`. Never use bare `console.error` for shipped errors, and never log secrets/PII (the denylist is a backstop, not a licence).
- **Error boundaries** — `AppErrorBoundary` (`src/app/AppErrorBoundary.tsx`) wraps the app and reports render errors; `PluginErrorBoundary` keeps per-plugin isolation (ADR-0004) and also reports. Add a boundary around any new independent surface rather than letting a throw unmount the app.
- **Correlation** — `src/api/client.ts` attaches an `X-Request-ID` per request and logs failed calls with it; don't create raw `fetch` calls that bypass `client.ts` (they lose correlation and auth handling).
- **Lint & format** — formatting is owned by `oxfmt` (`src` only) and lint by `oxlint` (type-aware via `oxlint-tsgolint`); do not add ESLint or Prettier. Use a narrow `// oxlint-disable-next-line <rule> -- <reason>` only when a rule is genuinely wrong for a line; new warnings are not allowed (the baseline is pinned in `.oxlintrc.json`).

## Testing
- Unit: `src/**/*.test.tsx` with vitest + React Testing Library
- Setup: `src/test/setup.ts`

## Documentation map
- `docs/architecture.md` — Stack, server-state strategy, routing, state boundaries
- `docs/plugin-uis.md` — Build-time discovery, custom JsonSchemaForm schema rendering, error boundaries

## Documentation
Any change to behavior, API surface, data model, or commands MUST update the affected docs and ADRs in the same commit. Documentation that contradicts `gmc-feed-engine-spec.md` is a bug: fix the doc, never the spec, and flag the conflict to the operator.