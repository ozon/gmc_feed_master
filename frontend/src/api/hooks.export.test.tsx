import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderHook } from '../test/render';
import { QueryClient } from '@tanstack/react-query';
import {
  useExportVersionContent,
  useExportVersionDiff,
  useRollbackToVersion,
  useSetExportToken,
} from './hooks';
import { queryClient as defaultClient } from './queryClient';
import { queryKeys } from './queryKeys';
import { stubFetch } from '../test/fetch';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
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
        return jsonResponse({
          version: 3,
          against: 2,
          added: [],
          removed: [],
          changed: [],
          findings: {
            a_qc: true,
            b_qc: true,
            totals: { added: 0, fixed: 0, persisted: 0 },
            rules: [],
          },
        });
      }
      return jsonResponse({});
    });

    const { result } = renderHook(() => useExportVersionDiff(1, 3, 2));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toBe('/feed-sources/1/export-history/3/diff?against=2');
  });

  it('does not fetch when version is undefined', () => {
    let called = false;
    stubFetch((url) => {
      if (url.includes('/diff')) called = true;
      return jsonResponse({});
    });
    renderHook(() => useExportVersionDiff(1, undefined, 2));
    expect(called).toBe(false);
  });

  it('shares one disabled key across undefined-argument states', async () => {
    stubFetch(() => jsonResponse({}));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = renderHook(() => useExportVersionDiff(1, undefined, 2), { queryClient: client });
    first.unmount();
    renderHook(() => useExportVersionDiff(1, 3, undefined), { queryClient: client });

    const keys = client
      .getQueryCache()
      .getAll()
      .map((q) => q.queryKey);
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
    const { result } = renderHook(() => useRollbackToVersion(1), { queryClient: client });
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

describe('useExportVersionContent', () => {
  it('fetches raw XML text for a version', async () => {
    stubFetch((url) =>
      url === '/feed-sources/1/export-history/2/content'
        ? new Response('<g:id>A</g:id>', {
            status: 200,
            headers: { 'Content-Type': 'application/xml' },
          })
        : new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    const { result } = renderHook(() => useExportVersionContent(1, 2, true));
    await waitFor(() => expect(result.current.data).toBe('<g:id>A</g:id>'));
  });

  it('does not fetch when disabled', () => {
    const fetchMock = stubFetch(() => new Response('', { status: 200 }));
    renderHook(() => useExportVersionContent(1, undefined, false));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('useSetExportToken', () => {
  it('PUTs the token and invalidates the feed source detail query', async () => {
    let capturedUrl: string | null = null;
    let capturedMethod: string | undefined;
    let capturedBody: string | null = null;
    stubFetch((url, init) => {
      if (url === '/feed-sources/1/export-token') {
        capturedUrl = url;
        capturedMethod = init?.method;
        capturedBody = typeof init?.body === 'string' ? init.body : null;
        return jsonResponse({ export_token: 'tok-1', export_url: 'https://example.test/feed.xml' });
      }
      return jsonResponse({});
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useSetExportToken(1), { queryClient: client });
    result.current.mutate('tok-1');
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(capturedUrl).toBe('/feed-sources/1/export-token');
    expect(capturedMethod).toBe('PUT');
    expect(capturedBody).toBe(JSON.stringify({ export_token: 'tok-1' }));
    const invalidated = invalidateSpy.mock.calls.map((c) => c[0]);
    expect(
      invalidated.some(
        (q) => JSON.stringify(q?.queryKey) === JSON.stringify(queryKeys.feedSource(1).detail),
      ),
    ).toBe(true);
  });
});
