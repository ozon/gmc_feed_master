import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../test/render';
import { stubFetch } from '../test/fetch';
import App from '../App';
import { queryClient } from '../api/queryClient';
import { queryKeys } from '../api/queryKeys';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, setUnauthorizedHandler: vi.fn() };
});

const summary = {
  counts: { clients: 0, feed_sources: 0, active_products: 0, failed_last_exports: 0 },
  clients: [],
};

function handler(url: string): Response {
  const body =
    url === '/plugins' ? [] :
    url === '/dashboard/summary' ? summary :
    { detail: 'not found' };
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('AppShell admin nav', () => {
  beforeEach(() => {
    queryClient.clear();
  });

  it('shows administration links for admins', async () => {
    queryClient.setQueryData(queryKeys.session, {
      username: 'op',
      role: 'admin',
      client_ids: null,
    });
    stubFetch(handler);
    render(<App />);
    expect(await screen.findByText('Users')).toBeDefined();
    expect(screen.getByText('Clients')).toBeDefined();
    expect(screen.getByText('Settings')).toBeDefined();
  });

  it('hides administration links for non-admins', async () => {
    queryClient.setQueryData(queryKeys.session, {
      username: 'bob',
      role: 'user',
      client_ids: [1],
    });
    stubFetch(handler);
    render(<App />);
    expect(await screen.findByText('Dashboard')).toBeDefined();
    expect(screen.queryByText('Administration')).toBeNull();
    expect(screen.queryByText('Users')).toBeNull();
  });
});
