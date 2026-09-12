import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useQualityHistory } from './hooks';
import { queryClient as defaultClient } from './queryClient';
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

describe('useQualityHistory', () => {
  it('fetches quality-history with limit and returns rows', async () => {
    const rows = [
      {
        id: 1,
        started_at: '2026-09-01T10:00:00',
        product_count: 10,
        critical: 1,
        warning: 2,
        info: 3,
        fixed: 0,
        new: 1,
        remaining: 2,
      },
    ];
    let capturedUrl = '';
    stubFetch((url) => {
      capturedUrl = url;
      if (url === '/feed-sources/1/quality-history?limit=30') return jsonResponse({ rows });
      return jsonResponse({});
    });

    const { result } = renderHook(() => useQualityHistory(1), { wrapper: withClient() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toBe('/feed-sources/1/quality-history?limit=30');
    expect(result.current.data?.rows).toEqual(rows);
  });
});
