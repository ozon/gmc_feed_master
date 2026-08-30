# GMC Feed Master — Frontend Agent Instructions

## WHAT
React 19 + TypeScript + Vite. Mantine UI, TanStack Query (server state), TanStack Table (data grids), TanStack Form (core forms), dnd-kit (pipeline builder), i18next (i18n).

## HOW
```bash
# From frontend/
npm install
npm run dev              # Vite dev server (needs .env.local with certs for HTTPS)
npm run build            # typecheck + production build
npm run test             # vitest
npm run typecheck        # tsc -b
```

## Key conventions
- **Server state only in TanStack Query** — `queryClient` in `src/api/queryClient.ts`, keys in `src/api/queryKeys.ts`, hooks in `src/api/hooks.ts`. No duplicate stores.
- **Client state** — React built-ins only (`useState`/`useReducer`/Context).
- **Plugin UIs** — build-time discovery via Vite scan of `plugins/*/frontend/`; auto-rendered from JSON Schema (Mantine-themed `JsonSchemaForm` in `src/components/JsonSchemaForm.tsx`); custom components via `manifest.frontend.component`.
- **Pipeline builder** — dnd-kit in `src/features/pipeline/`; workspace state is local React state.
- **Routing** — `src/app/router.tsx` with lazy-loaded pages; session guard via `RequireSession`.
- **Error handling** — `notifyApiError` in `src/app/notifications.ts` maps 422 field errors to form fields.

## Testing
- Unit: `src/**/*.test.tsx` with vitest + React Testing Library
- Setup: `src/test/setup.ts`

## Documentation map
- `docs/architecture.md` — Stack, server-state strategy, routing, state boundaries
- `docs/plugin-uis.md` — Build-time discovery, RJSF schema rendering, error boundaries

## Documentation
Any change to behavior, API surface, data model, or commands MUST update the affected docs and ADRs in the same commit. Documentation that contradicts `gmc-feed-engine-spec.md` is a bug: fix the doc, never the spec, and flag the conflict to the operator.