import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  apiGet,
  getCurrentUser,
  login,
  setUnauthorizedHandler,
} from './client';

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  setUnauthorizedHandler(null);
});

describe('api client', () => {
  it('sends credentials and parses JSON', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ username: 'operator' }));
    await expect(getCurrentUser()).resolves.toEqual({ username: 'operator' });
    expect(fetchMock).toHaveBeenCalledWith(
      '/auth/me',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('throws ApiError with the backend detail', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid credentials' }, 401));
    const error = await login('a', 'b').catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(401);
    expect(error.detail).toBe('Invalid credentials');
  });

  it('invokes the unauthorized handler on non-login 401', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Not authenticated' }, 401));
    await apiGet('/dashboard/summary').catch(() => undefined);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('does not invoke the handler for a failed login', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid credentials' }, 401));
    await login('a', 'b').catch(() => undefined);
    expect(handler).not.toHaveBeenCalled();
  });
});
