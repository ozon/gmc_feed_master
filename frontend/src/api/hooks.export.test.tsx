import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useExportVersionDiff, useRollbackToVersion } from './hooks';
import { queryClient as defaultClient } from './queryClient';
import { queryKeys } from './queryKeys';
import { stubFetch } from '../test/fetch';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function withClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  defaultClient.clear();
  vi.restoreAllMocks();
});

describe('useExportVersionDiff', () => {
  it('GETs /export-history/{version}/diff?against={n}', async () => {
    let captured: string | null = null;
    stubFetch((url) => {
      if (url.startsWith('/feed-sources/1/export-history/3/diff')) {
        captured = url;
        return jsonResponse({ version: 3, against: 2, added: [], removed: [], changed: [] });
      }
      return jsonResponse({});
    });

    const { result } = renderHook(() => useExportVersionDiff(1, 3, 2), { wrapper: withClient() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toBe('/feed-sources/1/export-history/3/diff?against=2');
  });

  it('does not fetch when version is undefined', () => {
    let called = false;
    stubFetch((url) => {
      if (url.includes('/diff')) called = true;
      return jsonResponse({});
    });
    renderHook(() => useExportVersionDiff(1, undefined, 2), { wrapper: withClient() });
    expect(called).toBe(false);
  });

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
    expect(keys).toEqual([['feed-source', 1, 'export-diff', { disabled: true }]]);
  });
});

describe('useRollbackToVersion', () => {
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
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useRollbackToVersion(1), { wrapper });
    result.current.mutate(5);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toBe('/feed-sources/1/export-history/5/rollback');
    const invalidated = invalidateSpy.mock.calls.map((c) => c[0]);
    const hasHistory = invalidated.some(
      (q) => JSON.stringify(q?.queryKey) === JSON.stringify(queryKeys.feedSource(1).exportHistory),
    );
    const hasDiff = invalidated.some(
      (q) => JSON.stringify(q?.queryKey) === JSON.stringify(['feed-source', 1, 'export-diff']),
    );
    expect(hasHistory).toBe(true);
    expect(hasDiff).toBe(true);
  });
});
