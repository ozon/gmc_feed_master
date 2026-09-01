# M11d Micro-batch Design (TODO 1.5, 1.6)

**Date:** 2026-09-01 · **Branch:** `m11d-micro` (from main `2203ab9`) · **Scope decided by owner:** P2 export-hooks pair 1.5 + 1.6, frontend-only, 2-task cycle.

## §1 Task 1 — `useExportVersionDiff` queryKey sentinels (TODO 1.5)

### §1.1 Problem
`hooks.ts:404-407` builds the query key as `exportDiff({ version: version ?? -1, against: against ?? -1 })`. The hook's `enabled` is `version !== undefined && against !== undefined`, so the `-1` key is never used to fetch — but the sentinel is arbitrary and collides with a hypothetical real `version: -1`, and the disabled-query key shape lies about what was requested.

### §1.2 Design (binding)
The key factory becomes **union-typed** — it accepts both the concrete params and `undefined`, and produces a **stable, explicit disabled key** instead of a sentinel:

```ts
exportDiff: (params: { version: number; against: number } | undefined) =>
  ['feed-source', id, 'export-diff', params ?? { disabled: true }] as const,
```

`useExportVersionDiff` calls it with the params object only when BOTH are defined, else `undefined`:

```ts
queryKey: queryKeys.feedSource(feedSourceId).exportDiff(
  version !== undefined && against !== undefined ? { version, against } : undefined,
),
```

Behavior contract:
- Both defined → key `['feed-source', id, 'export-diff', { version, against }]` (UNCHANGED — existing cache entries and the m11a/m11b tests keep matching).
- Either undefined → key `['feed-source', id, 'export-diff', { disabled: true }]` — same key for every disabled state, no `-1` collision possible.
- The hook's `enabled` and `queryFn` are untouched.
- No comment is added (repo convention); the union type itself documents the shape.

### §1.3 Doc-sync
`frontend/docs/architecture.md` Query Key Structure block (line 54) shows `exportDiff: (params) => [...]`; update that line to show the union signature. `architecture.md:71` documents `useRollbackToVersion` invalidation — updated in §2.

### §1.4 Test changes
`hooks.export.test.tsx` (44-52) "does not fetch when version is undefined" — unchanged, still passes (RED baseline for 1.6's rollback test is separate). One new test asserts the disabled key materializes without error and stays stable across renders with mixed undefined args (e.g. render `useExportVersionDiff(1, undefined, 2)` and `(1, 3, undefined)` — both share the same disabled key, observable via `queryClient.getQueryData`/query cache contents or by asserting no fetch and no distinct keys). Simpler, assertion-based form (preferred, less coupled to cache internals):

```ts
it('uses the shared disabled key when either version is undefined', () => {
  stubFetch(() => jsonResponse({}));
  const { unmount } = renderHook(() => useExportVersionDiff(1, undefined, 2), { wrapper: withClient() });
  unmount();
  renderHook(() => useExportVersionDiff(1, 3, undefined), { wrapper: withClient() });
  expect(screen).toBeDefined();
});
```

The above shape is weak (asserts nothing observable). Implementer: instead assert on the query cache — `new QueryClient()` captured from the wrapper, after both renders, exactly ONE query exists in `client.getQueryCache().getAll()` and its `queryKey` equals `['feed-source', 1, 'export-diff', { disabled: true }]` (matched with `toEqual` on the serialized key array or `query.queryKey[3]` deep-equal). This is the RED-capable assertion: today the two renders produce two DIFFERENT sentinel keys ({version:-1,against:2} vs {version:3,against:-1}).

## §2 Task 2 — `useRollbackToVersion` also invalidates the diff query (TODO 1.6)

### §2.1 Problem
`hooks.ts:421-423`: rollback's `onSuccess` invalidates only `exportHistory`. After a rollback a new version is prepended; the user's currently-displayed diff (selected by version numbers) may be stale until refetch.

### §2.2 Design (binding)
`onSuccess` invalidates BOTH keys — history as today, plus the diff via **prefix match** on the shared 3-element prefix `['feed-source', feedSourceId, 'export-diff']` (TanStack Query treats the key as a prefix — no predicate needed):

```ts
onSuccess: () => {
  void queryClient.invalidateQueries({ queryKey: queryKeys.feedSource(feedSourceId).exportHistory });
  void queryClient.invalidateQueries({ queryKey: ['feed-source', feedSourceId, 'export-diff'] });
},
```

The literal prefix is used because the `exportDiff` factory requires concrete params (or `undefined` → `{disabled: true}` — wrong key for prefix matching). Note: invalidating the prefix also invalidates the disabled-placeholder key, which is harmless (a disabled query refetches nothing when inactive, and `invalidateQueries` on an inactive query just marks it stale).

### §2.3 Test changes
`hooks.export.test.tsx` rollback test (56-70): pre-seed one cached diff query (e.g. `client.setQueryData(queryKeys.feedSource(1).exportDiff({ version: 3, against: 2 }), ...)`) then mutate and assert BOTH invalidations happened — `client.getQueryData(...)` returns `undefined` (cache cleared) after the rollback mutation, or `invalidateQueries` spy form. Preferred: real `QueryClient` semantics via `withClient()` capturing the client, `setQueryData` seed, mutate, then `await waitFor(() => expect(client.getQueryData(diffKey)).toBeUndefined())`. Also assert exportHistory cache cleared (seed + gone) in the same test.

## §3 Order & rationale
Task 1 (1.5) first: it changes the key factory the Task 2 test seeds with. Task 2 (1.6) builds on the final key shape. Both tasks touch `hooks.ts` + `hooks.export.test.tsx` only (+1 line of architecture.md in Task 1) — same-file sequencing, no parallel implementers.

## §4 Gates (both tasks)
- Frontend only: `npm test -- --run` (expected 168 after Task 1 if a new test is added; Task 2 may extend the rollback test rather than add one — final count 169 or stays 168 with extended coverage; the plan will pin this), `npm run typecheck`, `npm run build`, `git diff --check`.
- Backend untouched.
- No new i18n keys; hooks.ts stays i18n-free (no notifications added in this cycle — TODO 1.6 is invalidation-only per its acceptance).
