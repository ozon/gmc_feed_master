# ADR-0003: Rolldown as Optional Bundler Evaluation

## Status
Accepted (Evaluation)

## Context
Vite 6+ uses Rolldown (Rust-based bundler) internally for production builds. The question: adopt `rolldown-vite` explicitly or stay with standard Vite (esbuild dev, Rollup build) as MVP baseline.

## Decision
**Standard Vite remains the supported MVP baseline.** `rolldown-vite` may be evaluated behind CI but is not a hard dependency.

### Evaluation criteria (must all pass before switching):
1. **Production build** — `npm run build` completes without errors, outputs valid assets.
2. **Typecheck** — `npm run typecheck` (tsc -b) passes on Rolldown output.
3. **Plugin discovery** — Build-time scan of `plugins/*/frontend/` works (Vite plugin API compatibility).
4. **Code splitting** — Vendor chunking (`rolldownOptions.output.codeSplitting.groups` in `vite.config.ts`) produces expected chunks.
5. **HMR with external plugin editor** — At least one external plugin's React component (`manifest.frontend.component`) hot-reloads correctly during `npm run dev`.

## Consequences
- **Positive**: Zero risk to MVP timeline; Vite's esbuild dev server is fast and stable; Rollup production builds are proven; evaluation can happen incrementally without blocking features.
- **Negative**: Miss potential Rust-bundler performance gains (faster builds, lower memory) until evaluation completes; dual maintenance of CI configs during evaluation.
- **Rollback**: Trivial — remove `rolldownOptions` from `vite.config.ts` and revert to standard Vite.

## Rejected Alternative
**Mandate Rolldown now** — Rejected because: Rolldown is pre-1.0; Vite's Rolldown integration is experimental; plugin ecosystem (especially `@vitejs/plugin-react`) has known edge cases with Rolldown; no user-facing benefit for MVP scope.