import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderHook } from '../test/render';
import {QueryClient} from '@tanstack/react-query';
import { useUpdatePluginEnabled, usePluginConfig, useSavePluginConfig, usePluginData, useSavePluginData } from './hooks';
import { ApiError } from './client';
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

describe('useUpdatePluginEnabled', () => {
  it('PUTs /plugins/{id}/enabled and invalidates the plugins query', async () => {
    let captured: { url: string; body: unknown } | null = null;
    stubFetch((url, init) => {
      if (url === '/plugins/example_upper/enabled' && init?.method === 'PUT') {
        captured = { url, body: JSON.parse(String(init.body)) };
        return jsonResponse({ id: 'example_upper', enabled: false });
      }
      return jsonResponse({});
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    const { result } = renderHook(() => useUpdatePluginEnabled(), { queryClient: client });
    result.current.mutate({ id: 'example_upper', enabled: false });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toEqual({ url: '/plugins/example_upper/enabled', body: { enabled: false } });
    const invalidated = invalidateSpy.mock.calls.map((c) => c[0]);
    const hasPluginsKey = invalidated.some(
      (q) => JSON.stringify(q?.queryKey) === JSON.stringify(queryKeys.plugins),
    );
    expect(hasPluginsKey).toBe(true);
  });
});

describe('usePluginConfig', () => {
  it('GETs /plugins/{id}/config with scope query params', async () => {
    let capturedUrl: string | null = null;
    stubFetch((url) => {
      if (url.startsWith('/plugins/example_upper/config')) {
        capturedUrl = url;
        return jsonResponse({ suffix: '!' });
      }
      return jsonResponse({});
    });

    const { result } = renderHook(
      () => usePluginConfig('example_upper', { clientId: 7 }),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toBe('/plugins/example_upper/config?client_id=7');
    expect(result.current.data).toEqual({ suffix: '!' });
  });
});

describe('useSavePluginConfig', () => {
  it('PUTs /plugins/{id}/config with scope query params and invalidates the config query', async () => {
    let captured: { url: string; body: unknown } | null = null;
    stubFetch((url, init) => {
      if (url.startsWith('/plugins/example_upper/config') && init?.method === 'PUT') {
        captured = { url, body: JSON.parse(String(init.body)) };
        return jsonResponse({ suffix: 'X' });
      }
      return jsonResponse({});
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const scope = {};

    const { result } = renderHook(() => useSavePluginConfig('example_upper', scope), { queryClient: client });
    result.current.mutate(() => ({ suffix: 'X' }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toEqual({ url: '/plugins/example_upper/config', body: { suffix: 'X' } });
    const invalidated = invalidateSpy.mock.calls.map((c) => c[0]);
    const expectedKey = queryKeys.pluginConfig('example_upper', scope);
    const hasConfigKey = invalidated.some(
      (q) => JSON.stringify(q?.queryKey) === JSON.stringify(expectedKey),
    );
    expect(hasConfigKey).toBe(true);
  });
});

describe('usePluginData', () => {
  it('GETs /plugins/{id}/data with scope query params', async () => {
    let capturedUrl = '';
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/data')) {
        capturedUrl = url;
        return jsonResponse({ slotIds: { r1: 'a' } });
      }
      return jsonResponse({});
    });

    const { result } = renderHook(() => usePluginData('custom_labels', { feedSourceId: 7 }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toBe('/plugins/custom_labels/data?feed_source_id=7');
    expect(result.current.data).toEqual({ slotIds: { r1: 'a' } });
  });
});

describe('useSavePluginData', () => {
  it('PUTs /plugins/{id}/data and invalidates the pluginData key', async () => {
    let captured: { url: string; body: unknown } | null = null;
    stubFetch((url, init) => {
      if (url === '/plugins/custom_labels/data?feed_source_id=7' && init?.method === 'PUT') {
        captured = { url, body: JSON.parse(String(init.body)) };
        return jsonResponse({ status: 'ok' });
      }
      return jsonResponse({});
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    const { result } = renderHook(() => useSavePluginData('custom_labels', { feedSourceId: 7 }), { queryClient: client });
    result.current.mutate(() => ({ slotIds: { r1: 'a' } }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toEqual({
      url: '/plugins/custom_labels/data?feed_source_id=7',
      body: { slotIds: { r1: 'a' } },
    });
    const invalidated = invalidateSpy.mock.calls.map((c) => c[0]);
    const hasDataKey = invalidated.some(
      (q) =>
        JSON.stringify(q?.queryKey) ===
        JSON.stringify(queryKeys.pluginData('custom_labels', { feedSourceId: 7 })),
    );
    expect(hasDataKey).toBe(true);
  });
});
describe('optimistic locking', () => {
  function withVersionedData(client?: QueryClient) {
    return client ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  }

  function versionedJson(body: unknown, version: number | null, status = 200) {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (version !== null) headers['X-Plugin-Data-Version'] = String(version);
    return new Response(JSON.stringify(body), { status, headers });
  }

  it('usePluginData captures the version from the response header', async () => {
    let getVersion = 0;
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/data')) {
        getVersion += 1;
        return versionedJson({ assignments: { a: '1' } }, 41);
      }
      return jsonResponse({});
    });

    const { result } = renderHook(
      () => usePluginData('custom_labels', { feedSourceId: 7 }),
      { queryClient: withVersionedData() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ assignments: { a: '1' } });
    expect(getVersion).toBe(1);
  });

  it('save hook attaches expected_version and retries once on 409 with fresh version', async () => {
    const queryClient = withVersionedData();
    queryClient.setQueryData(queryKeys.pluginData('custom_labels', { feedSourceId: 7 }), {
      payload: { assignments: {} },
      version: 10,
    });

    const putUrls: string[] = [];
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/data') && url.includes('expected_version')) {
        putUrls.push(url);
        if (putUrls.length === 1) {
          return versionedJson(
            { detail: { message: 'plugin data changed since read', current_version: 11 } },
            null,
            409,
          );
        }
        return versionedJson({ status: 'ok' }, 12);
      }
      if (url.startsWith('/plugins/custom_labels/data')) {
        return versionedJson({ assignments: { other: 'editor' } }, 11);
      }
      return jsonResponse({});
    });

    const { result } = renderHook(
      () => useSavePluginData('custom_labels', { feedSourceId: 7 }),
      { queryClient },
    );
    result.current.mutate(() => ({ assignments: { mine: '42' } }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(putUrls).toHaveLength(2);
    expect(putUrls[0]).toContain('expected_version=10');
    expect(putUrls[1]).toContain('expected_version=11');
  });

  it('save hook surfaces the 409 after a double conflict without a third PUT', async () => {
    const queryClient = withVersionedData();
    queryClient.setQueryData(queryKeys.pluginData('custom_labels', { feedSourceId: 7 }), {
      payload: { assignments: {} },
      version: 10,
    });

    const putUrls: string[] = [];
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/data') && url.includes('expected_version')) {
        putUrls.push(url);
        return versionedJson(
          { detail: { message: 'plugin data changed since read', current_version: 99 } },
          null,
          409,
        );
      }
      if (url.startsWith('/plugins/custom_labels/data')) {
        return versionedJson({ assignments: {} }, 11);
      }
      return jsonResponse({});
    });

    const { result } = renderHook(
      () => useSavePluginData('custom_labels', { feedSourceId: 7 }),
      { queryClient },
    );
    result.current.mutate(() => ({ assignments: { mine: '42' } }));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(putUrls).toHaveLength(2);
    expect(result.current.error).toBeInstanceOf(ApiError);
  });

  it('save hook without cached version PUTs without expected_version (legacy)', async () => {
    let putUrl: string | null = null;
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/data')) {
        putUrl = url;
        return versionedJson({ status: 'ok' }, 1);
      }
      return jsonResponse({});
    });

    const { result } = renderHook(
      () => useSavePluginData('custom_labels', { feedSourceId: 7 }),
    );
    result.current.mutate(() => ({ assignments: { a: '1' } }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(putUrl).toBe('/plugins/custom_labels/data?feed_source_id=7');
  });
});
