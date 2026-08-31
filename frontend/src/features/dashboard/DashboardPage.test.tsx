import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications } from '@mantine/notifications';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import App from '../../App';
import { queryClient } from '../../api/queryClient';
import type { DashboardSummary } from '../../api/types';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const summary: DashboardSummary = {
  counts: { clients: 2, feed_sources: 3, active_products: 12480, failed_last_exports: 1 },
  clients: [
    {
      id: 1,
      name: 'Acme',
      status: 'active',
      feed_sources: [
        {
          id: 2,
          client_id: 1,
          name: 'Acme DE',
          source_format: 'xml',
          item_count: 4200,
          last_export_at: '2026-08-27T10:00:00Z',
          last_export_status: 'failed',
          last_run_at: '2026-08-27T09:00:00Z',
          last_run_status: 'error',
        },
        {
          id: 5,
          client_id: 1,
          name: 'Acme CSV',
          source_format: 'csv',
          item_count: 120,
          last_export_at: '2026-08-27T11:00:00Z',
          last_export_status: 'completed',
          last_run_at: '2026-08-27T09:30:00Z',
          last_run_status: 'success',
        },
      ],
    },
    {
      id: 3,
      name: 'Globex',
      status: 'paused',
      feed_sources: [
        {
          id: 4,
          client_id: 3,
          name: 'Globex TSV',
          source_format: 'tsv',
          item_count: 0,
          last_export_at: null,
          last_export_status: null,
          last_run_at: null,
          last_run_status: null,
        },
      ],
    },
  ],
};

const deletedSummary: DashboardSummary = {
  counts: { clients: 1, feed_sources: 1, active_products: 4200, failed_last_exports: 0 },
  clients: [summary.clients[0]],
};

const emptySummary: DashboardSummary = {
  counts: { clients: 0, feed_sources: 0, active_products: 0, failed_last_exports: 0 },
  clients: [],
};

const plugins = [
  {
    id: 'example_upper',
    name: 'Example Upper',
    version: '1.0.0',
    enabled: true,
    manifest: { frontend: { menu_item: 'Example Upper', icon: 'letter-e' } },
    used_by_feed_sources: 0,
  },
];

let fetchMock: ReturnType<typeof stubFetch>;

function postCalls(url: string): number {
  return fetchMock.mock.calls.filter(
    ([input, init]) => String(input) === url && init?.method === 'POST',
  ).length;
}

function deleteCalls(url: string): number {
  return fetchMock.mock.calls.filter(
    ([input, init]) => String(input) === url && init?.method === 'DELETE',
  ).length;
}

beforeEach(() => {
  queryClient.clear();
  notifications.clean();
  window.history.replaceState({}, '', '/');
  localStorage.clear();
});

describe('DashboardPage', () => {
  it('renders stat cards, client sections, badges and status lines', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(summary);
      if (url === '/plugins') return jsonResponse(plugins);
      return jsonResponse({});
    });

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.getByText('Clients')).toBeInTheDocument();
    expect(screen.getByText('Feed sources')).toBeInTheDocument();
    expect(screen.getByText('Active products')).toBeInTheDocument();
    expect(screen.getByText('Failed exports')).toBeInTheDocument();
    expect(screen.getByText('12,480')).toBeInTheDocument();
    expect(screen.getByText('4,200')).toBeInTheDocument();

    expect(screen.getByText('Acme')).toBeInTheDocument();
    expect(screen.getByText('Globex')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('Paused')).toBeInTheDocument();
    expect(screen.getByText('XML')).toBeInTheDocument();
    expect(screen.getByText(/— Error/)).toBeInTheDocument();
    expect(screen.getByText(/— Failed/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /globex/i }));
    expect(await screen.findByText('TSV')).toBeInTheDocument();
    expect(screen.getByText('Never run')).toBeInTheDocument();
    expect(screen.getByText('Never exported')).toBeInTheDocument();
    expect(screen.getByText('4,200')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
  });

  it('creates a client from the modal and notifies', async () => {
    const user = userEvent.setup();
    let created = false;
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(created ? summary : emptySummary);
      if (url === '/clients' && !created) {
        created = true;
        return jsonResponse(
          { id: 1, name: 'Acme 2', contact_details: {}, status: 'active', created_at: '2026-01-01' },
          201,
        );
      }
      if (url === '/plugins') return jsonResponse(plugins);
      return jsonResponse({});
    });

    render(<App />);
    expect(
      await screen.findByText('No clients yet. Create the first client to get started.'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Add client' }));
    await user.type(await screen.findByLabelText(/^name/i), 'Acme 2');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(postCalls('/clients')).toBe(1));
    expect(await screen.findByText('Saved')).toBeInTheDocument();
  });

  it('creates a feed source and navigates to its setup page', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(summary);
      if (url === '/plugins') return jsonResponse(plugins);
      if (url === '/clients/1/feed-sources') {
        return jsonResponse(
          {
            id: 9,
            client_id: 1,
            name: 'New Feed',
            source_format: 'xml',
            cron_expression: null,
            target_country: null,
            target_language: null,
            currency: null,
            source_url: null,
            feed_type: 'full',
            history_retention_count: 10,
            volume_drop_threshold_pct: 30,
            configuration: {},
            export_url: '/export/9/token',
            created_at: '2026-08-29T00:00:00',
            updated_at: '2026-08-29T00:00:00',
          },
          201,
        );
      }
      return jsonResponse({});
    });

    render(<App />);
    await screen.findByRole('heading', { name: 'Dashboard' });

    await user.click(screen.getAllByRole('button', { name: 'Add feed' })[0]);
    await user.type(await screen.findByLabelText(/^name/i), 'New Feed');
    await user.click(await screen.findByRole('combobox', { name: 'Format' }));
    await user.click(await screen.findByRole('option', { name: 'XML' }));
    await user.type(await screen.findByLabelText(/source url/i), 'https://example.com/feed.xml');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(postCalls('/clients/1/feed-sources')).toBe(1));
    await waitFor(() => {
      expect(window.location.pathname).toBe('/clients/1/feeds/9/setup');
    });
  });

  it('shows a generic error notification when feed creation fails', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(summary);
      if (url === '/plugins') return jsonResponse(plugins);
      if (url === '/clients/1/feed-sources') return new Response('boom', { status: 500 });
      return jsonResponse({});
    });

    render(<App />);
    await screen.findByRole('heading', { name: 'Dashboard' });

    await user.click(screen.getAllByRole('button', { name: 'Add feed' })[0]);
    await user.type(await screen.findByLabelText(/^name/i), 'Broken Feed');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    expect(await screen.findByText('Could not be saved.')).toBeInTheDocument();
    expect(screen.queryByText('Saved')).not.toBeInTheDocument();
    expect(window.location.pathname).toBe('/');
  });

  it('requires typing the client name to confirm deletion', async () => {
    const user = userEvent.setup();
    let deleted = false;
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(deleted ? deletedSummary : summary);
      if (url === '/clients/3') {
        deleted = true;
        return new Response(null, { status: 204 });
      }
      if (url === '/plugins') return jsonResponse(plugins);
      return jsonResponse({});
    });

    render(<App />);
    expect(await screen.findByText('Globex')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /globex/i }));

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
    expect(deleteButtons.length).toBe(1);
    await user.click(deleteButtons[0]);

    const confirm = await screen.findByRole('button', { name: 'Confirm' });
    expect(confirm).toBeDisabled();

    const confirmInput = screen.getByLabelText(/type globex to confirm/i);
    await user.type(confirmInput, 'Glob');
    expect(confirm).toBeDisabled();

    await user.type(confirmInput, 'ex');
    expect(confirm).toBeEnabled();

    await user.click(confirm);

    await waitFor(() => expect(deleteCalls('/clients/3')).toBe(1));
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText('Globex TSV')).not.toBeInTheDocument();
    });
  });

  it('renders the empty state and the error state with retry', async () => {
    const user = userEvent.setup();
    let failing = true;
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') {
        if (failing) return jsonResponse({ detail: 'Database unavailable' }, 503);
        return jsonResponse(emptySummary);
      }
      if (url === '/plugins') return jsonResponse(plugins);
      return jsonResponse({});
    });

    render(<App />);

    const retry = await screen.findByRole('button', { name: 'Retry' });
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong.');

    failing = false;
    await user.click(retry);

    expect(
      await screen.findByText('No clients yet. Create the first client to get started.'),
    ).toBeInTheDocument();
  });
});
