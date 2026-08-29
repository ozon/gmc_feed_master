import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useUpdatePluginEnabled, usePluginConfig, useSavePluginConfig } from './hooks';
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

describe('useUpdatePluginEnabled', () => {
  it('PUTs /plugins/{id}/enabled and invalidates the plugins query', async () => {
    let captured: { url: string; body: unknown } | null = null;
    stubFetch((url, init) => {
      if (url === '/plugins/example_upper' && init?.method === 'PUT') {
        captured = { url, body: JSON.parse(String(init.body)) };
        return jsonResponse({ id: 'example_upper', enabled: false });
      }
      return jsonResponse({});
    });

    const { result } = renderHook(() => useUpdatePluginEnabled(), { wrapper: withClient() });
    result.current.mutate({ id: 'example_upper', enabled: false });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toEqual({ url: '/plugins/example_upper', body: { enabled: false } });
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
  it('PUTs /plugins/{id}/config with scope query params and body', async () => {
    let captured: { url: string; body: unknown } | null = null;
    stubFetch((url, init) => {
      if (url.startsWith('/plugins/example_upper/config') && init?.method === 'PUT') {
        captured = { url, body: JSON.parse(String(init.body)) };
        return jsonResponse({ suffix: 'X' });
      }
      return jsonResponse({});
    });

    const { result } = renderHook(
      () => useSavePluginConfig('example_upper', {}),
      { wrapper: withClient() },
    );
    result.current.mutate({ suffix: 'X' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toEqual({ url: '/plugins/example_upper/config', body: { suffix: 'X' } });
  });
});
