import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useRunDryRun } from './hooks';
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

describe('useRunDryRun', () => {
  it('POSTs /feed-sources/{id}/dry-run with body {limit}', async () => {
    let captured: { url: string; body: unknown } | null = null;
    stubFetch((url, init) => {
      if (url === '/feed-sources/1/dry-run' && init?.method === 'POST') {
        captured = { url, body: JSON.parse(String(init.body)) };
        return jsonResponse({ dropped: 0, processed: 5, findings: [] });
      }
      return jsonResponse({});
    });

    const { result } = renderHook(() => useRunDryRun(1), { wrapper: withClient() });
    result.current.mutate({ limit: 100 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toEqual({ url: '/feed-sources/1/dry-run', body: { limit: 100 } });
  });

  it('invalidates runs and findings queries on success', async () => {
    stubFetch((url, init) => {
      if (url === '/feed-sources/1/dry-run' && init?.method === 'POST') {
        return jsonResponse({ dropped: 0, processed: 5, findings: [] });
      }
      return jsonResponse({});
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const runsSpy = vi.spyOn(client, 'invalidateQueries');
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useRunDryRun(1), { wrapper });
    result.current.mutate({ limit: 100 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const invalidated = runsSpy.mock.calls.map((c) => c[0]);
    const runsKey = queryKeys.feedSource(1).runs;
    const findingsKey = queryKeys.feedSource(1).findings;
    const hasRuns = invalidated.some((q) => JSON.stringify(q?.queryKey) === JSON.stringify(runsKey));
    const hasFindings = invalidated.some(
      (q) => JSON.stringify(q?.queryKey) === JSON.stringify(findingsKey),
    );
    expect(hasRuns).toBe(true);
    expect(hasFindings).toBe(true);
  });
});