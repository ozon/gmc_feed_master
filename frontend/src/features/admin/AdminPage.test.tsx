import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import App from '../../App';
import { queryClient } from '../../api/queryClient';
import { queryKeys } from '../../api/queryKeys';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const users = [
  { id: 1, username: 'alice', role: 'admin', is_active: true, client_ids: [] },
];
const clients = [
  { id: 3, name: 'Globex', contact_details: {}, status: 'active', created_at: '2026-01-01' },
];
const settings = {
  staging_removal_retention_days: 90,
  staging_history_retention_days: 90,
  ingestion_run_retention_days: 90,
};

function handler(url: string): Response {
  if (url === '/admin/users') return jsonResponse(users);
  if (url === '/admin/settings') return jsonResponse(settings);
  if (url === '/admin/scheduler') return jsonResponse([]);
  if (url === '/clients') return jsonResponse(clients);
  if (url === '/plugins') return jsonResponse([]);
  if (url === '/dashboard/summary')
    return jsonResponse({
      counts: { clients: 0, feed_sources: 0, active_products: 0, failed_last_exports: 0 },
      clients: [],
    });
  return jsonResponse({});
}

beforeEach(() => {
  queryClient.clear();
  stubFetch(handler);
  queryClient.setQueryData(queryKeys.session, {
    username: 'operator',
    role: 'admin',
    client_ids: null,
  });
});

describe('AdminPage', () => {
  it('defaults to the users tab at /admin', async () => {
    window.history.replaceState({}, '', '/admin');
    render(<App />);
    expect(await screen.findByTestId('admin-users-table')).toBeInTheDocument();
    expect(await screen.findByText('alice')).toBeInTheDocument();
    expect(screen.queryByTestId('admin-clients-table')).not.toBeInTheDocument();
  });

  it('activates the clients tab at /admin/clients', async () => {
    window.history.replaceState({}, '', '/admin/clients');
    render(<App />);
    expect(await screen.findByTestId('admin-clients-table')).toBeInTheDocument();
    expect(screen.queryByTestId('admin-users-table')).not.toBeInTheDocument();
  });

  it('activates the settings tab at /admin/settings', async () => {
    window.history.replaceState({}, '', '/admin/settings');
    render(<App />);
    expect(
      await screen.findByText('Removed-product retention (days)'),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('admin-users-table')).not.toBeInTheDocument();
  });

  it('navigates between tabs via the URL', async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, '', '/admin');
    render(<App />);
    expect(await screen.findByTestId('admin-users-table')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Clients' }));

    expect(await screen.findByTestId('admin-clients-table')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/admin/clients');
  });
});
