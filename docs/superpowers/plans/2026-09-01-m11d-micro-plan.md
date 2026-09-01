# M11d Micro-batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close TODO 1.5 (drop the `-1` queryKey sentinels in `useExportVersionDiff`) and TODO 1.6 (`useRollbackToVersion` also invalidates the diff query) — both frontend-only hooks changes in `src/api/`.

**Architecture:** Two sequential tasks in the same two files. Task 1 makes the `exportDiff` key factory union-typed (concrete params or `undefined` → `{ disabled: true }`), keeping the enabled-key shape byte-identical. Task 2 adds a prefix invalidation of `['feed-source', id, 'export-diff']` to rollback's `onSuccess`. Task 1 runs first because Task 2's test seeds the cache with the post-Task-1 key factory.

**Tech Stack:** React 19 + TanStack Query v5; vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-09-01-m11d-micro-design.md`

## Global Constraints

- No comments in code (repo convention, binding).
- NO new i18n keys; no notifications added in this cycle (TODO 1.6 is invalidation-only per its acceptance; a rollback-error toast is NOT in scope).
- `hooks.ts` stays i18n-free.
- Frontend gate per task: `cd /home/ozon/gmc_feed_master/frontend && npm test -- --run && npm run typecheck && npm run build` (re-run solo if flaked by a concurrent backend suite).
- `git diff --check` clean (trailing newlines on all touched files).
- Work on branch `m11d-micro`. Do not touch main.
- No backend files touched; no backend gate needed.
- Test-count expectations: file `hooks.export.test.tsx` currently has 3 tests; suite is 168. After Task 1: suite 169 (3→4 in file). After Task 2: suite 169 (Task 2 EXTENDS the existing rollback test, no new test).

---

### Task 1: exportDiff key sentinels → union-typed disabled key (TODO 1.5)

**Files:**
- Modify: `frontend/src/api/queryKeys.ts:16-17` (union type)
- Modify: `frontend/src/api/hooks.ts:398-414` (`useExportVersionDiff` key expression)
- Modify: `frontend/docs/architecture.md:54` (key signature in the Query Key Structure block)
- Test: `frontend/src/api/hooks.export.test.tsx` (add 1 test)

**Interfaces:**
- Consumes: `useExportVersionDiff(feedSourceId, version, against)` signature unchanged; `enabled: version !== undefined && against !== undefined` unchanged; `queryFn` unchanged.
- Produces: `exportDiff(params | undefined)` — union-typed factory. Key contract: both defined → `['feed-source', id, 'export-diff', { version, against }]` (byte-identical to today's enabled key); otherwise → `['feed-source', id, 'export-diff', { disabled: true }]` (one shared disabled key, no `-1` anywhere).

- [ ] **Step 1.1: Write the failing test (RED)**

Append inside `describe('useExportVersionDiff', ...)` in `frontend/src/api/hooks.export.test.tsx`. The `withClient()` helper currently constructs its client inline — modify it to return the client too (e.g. construct `const client = new QueryClient(...)` inside a fresh function per test, or keep `withClient()` and add a sibling helper `withClientAndSpy()` that exposes the client via the wrapper). The test needs access to the SAME QueryClient the hook renders with:

```tsx
  it('shares one disabled key across undefined-argument states', async () => {
    stubFetch(() => jsonResponse({}));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const first = renderHook(() => useExportVersionDiff(1, undefined, 2), { wrapper });
    first.unmount();
    renderHook(() => useExportVersionDiff(1, 3, undefined), { wrapper });

    const keys = client.getQueryCache().getAll().map((q) => q.queryKey);
    expect(keys).toEqual([[`feed-source`, 1, `export-diff`, { disabled: true }]]);
  });
```

Notes: `ReactNode` is already imported in the file. The two renders today produce TWO different sentinel keys (`{version:-1,against:2}` and `{version:3,against:-1}`), so this assertion is RED now. Do NOT refactor the existing `withClient()` if the test above constructs its own wrapper — a local wrapper inside the test is self-contained and matches the file's minimal-helper style.

- [ ] **Step 1.2: Run (verify RED)**

```bash
cd /home/ozon/gmc_feed_master/frontend
npm test -- --run src/api/hooks.export.test.tsx
```

Expected: the new test FAILS — `keys` contains two distinct `-1`-sentinel keys, not one shared `{ disabled: true }` key.

- [ ] **Step 1.3: Implement**

In `frontend/src/api/queryKeys.ts`, change the `exportDiff` factory (lines 16-17):

```ts
    exportDiff: (params: { version: number; against: number } | undefined) =>
      ['feed-source', id, 'export-diff', params ?? { disabled: true }] as const,
```

In `frontend/src/api/hooks.ts`, change the `queryKey` expression in `useExportVersionDiff` (lines 404-407) — `queryFn` and `enabled` stay untouched:

```ts
    queryKey: queryKeys.feedSource(feedSourceId).exportDiff(
      version !== undefined && against !== undefined ? { version, against } : undefined,
    ),
```

No comment lines added.

- [ ] **Step 1.4: Run (verify GREEN)**

```bash
npm test -- --run src/api/hooks.export.test.tsx
```

Expected: all 4 file tests pass — the two existing (concrete key `{version:3,against:2}` key unchanged, so the GET test and "does not fetch" test stay green) + the new shared-disabled-key test.

- [ ] **Step 1.5: architecture.md doc-sync**

In `frontend/docs/architecture.md`, Query Key Structure block (line 54), update the signature to reflect the union:

```
    exportDiff: (params | undefined) => ['feed-source', id, 'export-diff', params ?? { disabled: true }],
```

(Keep the block's pseudo-code style — match the surrounding lines, one line only.)

- [ ] **Step 1.6: Full frontend gate**

```bash
npm test -- --run && npm run typecheck && npm run build
git diff --check
```

Expected: 169 tests (168 + 1), typecheck + build clean. (Re-run solo if flaked by a concurrent backend suite.)

- [ ] **Step 1.7: Commit**

```bash
git add frontend/src/api/queryKeys.ts frontend/src/api/hooks.ts \
  frontend/src/api/hooks.export.test.tsx frontend/docs/architecture.md
git commit -m "fix(api): explicit disabled key for export diff query (TODO 1.5)"
```

---

### Task 2: rollback invalidates the diff query too (TODO 1.6)

**Files:**
- Modify: `frontend/src/api/hooks.ts:421-423` (`useRollbackToVersion` onSuccess)
- Test: `frontend/src/api/hooks.export.test.tsx` (EXTEND the existing rollback test)

**Interfaces:**
- Consumes: `queryKeys.feedSource(id).exportDiff` (post-Task-1 union factory — call it with concrete params `{ version: 3, against: 2 }` when seeding); `QueryClient.invalidateQueries` prefix semantics (a shorter key array matches all keys that START with it — no predicate needed).
- Produces: rollback `onSuccess` invalidates BOTH `['feed-source', id, 'export-history']` AND the prefix `['feed-source', id, 'export-diff']`.

- [ ] **Step 2.1: Extend the rollback test (RED)**

Rewrite the existing `it('POSTs /export-history/{version}/rollback', ...)` in `frontend/src/api/hooks.export.test.tsx` to also cover invalidation. The current test uses `withClient()` (client not exposed) — rewrite it to construct its own client + wrapper exactly like Task 1's test. Seed both caches, mutate, assert both cleared:

```tsx
  it('POSTs rollback and invalidates export history and diff queries', async () => {
    let captured: string | null = null;
    stubFetch((url, init) => {
      if (url === '/feed-sources/1/export-history/5/rollback' && init?.method === 'POST') {
        captured = url;
        return new Response(null, { status: 204 });
      }
      return jsonResponse({});
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const diffKey = queryKeys.feedSource(1).exportDiff({ version: 3, against: 2 });
    client.setQueryData(diffKey, { version: 3, against: 2, added: [], removed: [], changed: [] });
    client.setQueryData(queryKeys.feedSource(1).exportHistory, []);
    const { result } = renderHook(() => useRollbackToVersion(1), { wrapper });
    result.current.mutate(5);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toBe('/feed-sources/1/export-history/5/rollback');
    expect(client.getQueryData(diffKey)).toBeUndefined();
    expect(client.getQueryData(queryKeys.feedSource(1).exportHistory)).toBeUndefined();
  });
```

Notes: import `queryKeys` from `'./queryKeys'` (extend the file's existing import from `'./hooks'` line area). `setQueryData` with a populated array marks the query fresh; `invalidateQueries` removes inactive-but-fresh queries from the cache — that is why the post-mutate `getQueryData` assertions expect `undefined`. The diff assertion is RED today (rollback invalidates only history). If `queryKeys` isn't currently imported in this test file, add it to the imports.

- [ ] **Step 2.2: Run (verify RED)**

```bash
npm test -- --run src/api/hooks.export.test.tsx
```

Expected: the extended test FAILS on the diff-key assertion (`getQueryData(diffKey)` still returns the seeded data) while the history assertion already passes.

- [ ] **Step 2.3: Implement**

In `frontend/src/api/hooks.ts`, `useRollbackToVersion` (lines 416-425), add the diff prefix invalidation:

```ts
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.feedSource(feedSourceId).exportHistory });
      void queryClient.invalidateQueries({ queryKey: ['feed-source', feedSourceId, 'export-diff'] });
    },
```

The literal 3-element prefix is used because the `exportDiff` factory requires concrete params (or `undefined` → `{ disabled: true }`, which is not the prefix form). No comment lines added.

- [ ] **Step 2.4: Run (verify GREEN)**

```bash
npm test -- --run src/api/hooks.export.test.tsx
```

Expected: all 4 file tests pass.

- [ ] **Step 2.5: architecture.md doc-sync**

`frontend/docs/architecture.md:71` — the Polling & Invalidation table row currently reads `| useRollbackToVersion | — | Invalidates feedSource.exportHistory |`. Update it to `Invalidates feedSource.exportHistory + export-diff (prefix)`.

- [ ] **Step 2.6: Full frontend gate**

```bash
npm test -- --run && npm run typecheck && npm run build
git diff --check
```

Expected: 169 tests (Task 2 extends an existing test — count unchanged from Task 1), typecheck + build clean.

- [ ] **Step 2.7: Commit**

```bash
git add frontend/src/api/hooks.ts frontend/src/api/hooks.export.test.tsx frontend/docs/architecture.md
git commit -m "fix(api): rollback invalidates export diff queries (TODO 1.6)"
```

---

## Session Close (controller)

- [ ] **Step C.1: Whole-branch review** — `scripts/review-package $(git merge-base main HEAD) HEAD`; final reviewer (small diff — one reviewer pass).
- [ ] **Step C.2: Update TODO.md** — mark 1.5, 1.6 `[x]` with Done entries; cycle log entry.
- [ ] **Step C.3: Update `.superpowers/sdd/progress.md`.**
- [ ] **Step C.4: Merge to main** — `git checkout main && git merge --ff-only m11d-micro`.
- [ ] **Step C.5: Ask the owner about pushing.**
