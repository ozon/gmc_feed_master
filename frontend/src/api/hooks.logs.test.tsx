import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { renderHook } from '../test/render';
import { useEventLogs } from './hooks';

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
});

describe('useEventLogs', () => {
  it('passes filters as query params', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const { result } = renderHook(() => useEventLogs({ category: 'audit', q: 'login' }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledWith(
      '/logs/entries?category=audit&q=login',
      expect.objectContaining({ credentials: 'include' }),
    );
  });
});
