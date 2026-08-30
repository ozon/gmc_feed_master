# ADR-0001: TanStack Query for Server State

## Status
Accepted

## Context
The frontend needs to manage server state (data fetched from the backend API) including caching, polling for live run status, and invalidation after mutations (run trigger, rollback, token rotation). The alternative considered was SWR.

## Decision
Use **TanStack Query (React Query) v5** as the single server-state management library.

### Key reasons:
1. **`refetchInterval` polling** — Native support for configurable polling intervals (used for live run status at 5s, dashboard at 30s) without custom timers.
2. **Hierarchical query-key invalidation** — Structured query keys (`queryKeys.ts`) enable precise invalidation after mutations (e.g., `queryClient.invalidateQueries({ queryKey: queryKeys.feedSource(id).runs })`) instead of broad cache clearing.
3. **Ecosystem consistency** — TanStack Table and TanStack Form are already adopted; TanStack Query shares the same design philosophy and TypeScript ergonomics.
4. **DevTools** — First-class React DevTools integration for debugging cache state.
5. **Parallel queries, deduplication, retry control** — Built-in and well-tested.

## Consequences
- **Positive**: Single source of truth for server state; predictable cache behavior; excellent TypeScript support; consistent patterns across data fetching, tables, and forms.
- **Negative**: Larger bundle than SWR (~13 kB gzipped); learning curve for developers unfamiliar with the TanStack ecosystem.
- **Forbidden**: Parallel use of two server-state caches (e.g., TanStack Query + SWR or Zustand for server data). All server state must flow through TanStack Query.

## Rejected Alternative
**SWR** — Rejected because: no built-in hierarchical invalidation (requires manual key management), polling API less flexible for conditional intervals, and ecosystem fragmentation with TanStack Table/Form already chosen.