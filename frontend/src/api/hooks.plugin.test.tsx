import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useUpdatePluginEnabled, usePluginConfig, useSavePluginConfig, usePluginData, useSavePluginData } from './hooks';
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
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useUpdatePluginEnabled(), { wrapper });
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
      { wrapper: withClient() },
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
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useSavePluginConfig('example_upper', scope), { wrapper });
    result.current.mutate({ suffix: 'X' });

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

    const { result } = renderHook(() => usePluginData('custom_labels', { feedSourceId: 7 }), {
      wrapper: withClient(),
    });

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
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useSavePluginData('custom_labels', { feedSourceId: 7 }), {
      wrapper,
    });
    result.current.mutate({ slotIds: { r1: 'a' } });

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