import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useFeedSourceFields, useRegistryAttributes, useTriggerRun } from './hooks';
import { stubFetch } from '../test/fetch';

let queryClient: QueryClient;
let fetchMock: ReturnType<typeof stubFetch>;

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

const registryFixture = [
  { name: 'title', kind: 'scalar', required: 'required', sub_fields: [],
    enum_values: [], baseline_required: true, max_repeats: 1 },
  { name: 'product_detail', kind: 'repeated_structured', required: 'optional',
    sub_fields: [
      { name: 'section_name', type: 'String', required: 'optional', kind: 'repeated_scalar' },
    ],
    enum_values: [], baseline_required: false, max_repeats: 2 },
];

const fieldsFixture = {
  fields: [
    { name: 'title', kind: 'scalar', sub_fields: [], max_repeats: 1 },
    { name: 'shipping', kind: 'repeated_structured',
      sub_fields: [{ name: 'country', kind: 'repeated_scalar' }], max_repeats: 3 },
  ],
};

beforeEach(() => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  fetchMock = stubFetch(() => jsonResponse({}));
});

describe('registry/fields hooks', () => {
  it('useRegistryAttributes passes feed_source_id and returns descriptors', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/registry/attributes?feed_source_id=5') return jsonResponse(registryFixture);
      return jsonResponse([]);
    });
    const { result } = renderHook(() => useRegistryAttributes(5), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data![1].max_repeats).toBe(2);
  });

  it('useRegistryAttributes without id keeps the bare URL', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/registry/attributes');
      return jsonResponse(registryFixture.map((a) => ({ ...a, max_repeats: 0 })));
    });
    const { result } = renderHook(() => useRegistryAttributes(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
  });

  it('useFeedSourceFields returns descriptor array', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/feed-sources/7/fields');
      return jsonResponse(fieldsFixture);
    });
    const { result } = renderHook(() => useFeedSourceFields(7), { wrapper });
    await waitFor(() => expect(result.current.data?.fields).toBeDefined());
    expect(result.current.data!.fields[1].max_repeats).toBe(3);
  });

  it('useTriggerRun invalidates the registry attributes prefix (directive 3)', async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/registry/attributes?feed_source_id=5') return jsonResponse(registryFixture);
      if (url === '/feed-sources/5/run') return jsonResponse({ run_id: 1 });
      return jsonResponse({});
    });
    const registry = renderHook(() => useRegistryAttributes(5), { wrapper });
    await waitFor(() => expect(registry.result.current.data).toBeDefined());
    const spy = vi.spyOn(queryClient, 'invalidateQueries');

    const run = renderHook(() => useTriggerRun(5), { wrapper });
    await run.result.current.mutateAsync();

    const called = spy.mock.calls.some((call) => {
      const key = (call[0] as { queryKey?: unknown[] }).queryKey;
      return Array.isArray(key) && key[0] === 'registry' && key[1] === 'attributes';
    });
    expect(called).toBe(true);
  });
});
