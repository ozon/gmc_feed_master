import { describe, expect, it, vi } from 'vitest';

vi.mock('./client', async () => {
  const actual = await vi.importActual<typeof import('./client')>('./client');
  return {
    ...actual,
    apiGet: vi.fn(),
    apiPost: vi.fn(),
    apiPatch: vi.fn(),
  };
});

import { apiGet } from './client';
import { useAdminUsers, useAdminSettings } from './hooks';

import { waitFor } from '@testing-library/react';
import { renderHook } from '../test/render';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const mockedApiGet = vi.mocked(apiGet);

describe('admin hooks', () => {
  it('useAdminUsers fetches /admin/users', async () => {
    mockedApiGet.mockResolvedValue([
      { id: 1, username: 'operator', role: 'admin', is_active: true, client_ids: [] },
    ]);
    const { result } = renderHook(() => useAdminUsers());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApiGet).toHaveBeenCalledWith('/admin/users');
    expect(result.current.data?.[0].username).toBe('operator');
  });

  it('useAdminSettings fetches /admin/settings', async () => {
    mockedApiGet.mockResolvedValue({
      staging_removal_retention_days: 90,
      staging_history_retention_days: 90,
      ingestion_run_retention_days: 90,
    });
    const { result } = renderHook(() => useAdminSettings());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApiGet).toHaveBeenCalledWith('/admin/settings');
  });
});
