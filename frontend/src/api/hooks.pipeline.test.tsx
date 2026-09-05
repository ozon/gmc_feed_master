import { beforeEach, describe, expect, it } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { usePatchPipelineInstance } from './hooks';
import { stubFetch } from '../test/fetch';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let pipelineGets = 0;

function Probe() {
  // Active observer so invalidateQueries actually refetches the pipeline.
  const q = useQuery({
    queryKey: ['feed-source', 7, 'pipeline'],
    queryFn: () => fetch('/feed-sources/7/pipeline').then((r) => r.json()),
  });
  return <div data-testid="probe">{q.dataUpdatedAt}</div>;
}

describe('usePatchPipelineInstance', () => {
  beforeEach(() => {
    pipelineGets = 0;
    stubFetch((url, init) => {
      if (url === '/feed-sources/7/pipeline' && (!init || init.method === 'GET')) {
        pipelineGets += 1;
        return jsonResponse({ instances: [{ id: 42, position: 0, plugin_id: 'p',
          name: 'P', configuration: {}, enabled: true }] });
      }
      if (url === '/feed-sources/7/pipeline/instances/42' && init?.method === 'PATCH') {
        return jsonResponse({ id: 42, enabled: false });
      }
      return jsonResponse({});
    });
  });

  it('PATCHes the instance and invalidates the pipeline query', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <Probe />
        {children}
      </QueryClientProvider>
    );

    // Number 7 on BOTH the hook and the Probe's query key so the keys hash identically.
    const { result } = renderHook(() => usePatchPipelineInstance(7), { wrapper });
    result.current.mutate({ instanceId: 42, enabled: false });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ id: 42, enabled: false });
    // Initial mount = 1 GET; onSuccess invalidation refetches the observed query → ≥2.
    await waitFor(() => expect(pipelineGets).toBeGreaterThanOrEqual(2), { timeout: 2000 });
  });
});
