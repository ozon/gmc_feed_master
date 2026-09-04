import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it } from 'vitest';
import { queryKeys } from './queryKeys';
import { useAutoMap, useClients, useCreateClient, useFeedSourceFields, useProductList } from './hooks';
import { stubFetch } from '../test/fetch';
import type { FieldMappingDoc } from './types';

let queryClient: QueryClient;
let fetchMock: ReturnType<typeof stubFetch>;

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

function callCount(url: string): number {
  return fetchMock.mock.calls.filter(([input]) => String(input) === url).length;
}

const clientFixture = [
  { id: 1, name: 'Old', contact_details: {}, status: 'active', created_at: '2026-01-01T00:00:00' },
];

beforeEach(() => {
  queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  fetchMock = stubFetch(() => jsonResponse({}));
});

describe('m10-c hooks', () => {
  it('useCreateClient posts a new client and invalidates the clients key', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/clients') return jsonResponse(clientFixture);
      if (url === '/dashboard/summary') {
        return jsonResponse({
          counts: { clients: 0, feed_sources: 0, active_products: 0, failed_last_exports: 0 },
          clients: [],
        });
      }
      return jsonResponse({
        id: 2,
        name: 'Acme',
        contact_details: {},
        status: 'active',
        created_at: '2026-01-02T00:00:00',
      });
    });
    const { result: clientsQuery } = renderHook(() => useClients(), { wrapper });
    await waitFor(() => expect(clientsQuery.current.isSuccess).toBe(true));
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) => String(input) === '/clients' && init?.method === undefined,
      ).length,
    ).toBe(1);

    const { result } = renderHook(() => useCreateClient(), { wrapper });
    result.current.mutate({ name: 'Acme', status: 'active' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledWith(
      '/clients',
      expect.objectContaining({ method: 'POST' }),
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([input, init]) => String(input) === '/clients' && init?.method === undefined,
        ).length,
      ).toBe(2),
    );
  });

  it('useProductList fetches with the exact raw-stage query string', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/feed-sources/2/products?page=2&page_size=50&q=sock&status=removed') {
        return jsonResponse({ items: [], total: 0, page: 2, page_size: 50 });
      }
      throw new Error(`Unexpected fetch in test: ${url}`);
    });
    const { result } = renderHook(
      () => useProductList(2, { page: 2, page_size: 50, q: 'sock', status: 'removed' }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledWith(
      '/feed-sources/2/products?page=2&page_size=50&q=sock&status=removed',
      expect.anything(),
    );
  });

  it('useAutoMap posts to the auto endpoint and invalidates the mapping key', async () => {
    const mappingKey = queryKeys.feedSource(2).mapping;
    const doc: FieldMappingDoc = { version: 1, auto_mapped: false, source_fields: [], mappings: {} };
    await queryClient.prefetchQuery({
      queryKey: mappingKey,
      queryFn: () => Promise.resolve(doc),
    });
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/feed-sources/2/field-mapping/auto') {
        return jsonResponse({ version: 2, auto_mapped: true, source_fields: [], mappings: {} });
      }
      throw new Error(`Unexpected fetch in test: ${url}`);
    });
    const { result } = renderHook(() => useAutoMap(), { wrapper });
    result.current.mutate(2);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledWith(
      '/feed-sources/2/field-mapping/auto',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(queryClient.getQueryState(mappingKey)?.isInvalidated).toBe(true);
  });

  it('useFeedSourceFields does not fetch when feedSourceId is empty', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      throw new Error(`Unexpected fetch in test: ${String(input)}`);
    });
    const { result } = renderHook(() => useFeedSourceFields(''), { wrapper });

    await waitFor(() => expect(result.current.fetchStatus).toBe('idle'));
    expect(result.current.data).toBeUndefined();
    expect(callCount('/feed-sources//fields')).toBe(0);
  });
});
