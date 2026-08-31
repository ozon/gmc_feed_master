import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { stubFetch } from '../test/fetch';
import App from '../App';
import { queryClient } from '../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const summary = {
  counts: { clients: 1, feed_sources: 1, active_products: 5, failed_last_exports: 0 },
  clients: [
    {
      id: 1,
      name: 'Acme',
      status: 'active',
      feed_sources: [
        {
          id: 2,
          client_id: 1,
          name: 'Main Feed',
          source_format: 'xml',
          item_count: 5,
          last_export_at: null,
          last_export_status: null,
          last_run_at: null,
          last_run_status: null,
        },
        {
          id: 3,
          client_id: 1,
          name: 'Secondary Feed',
          source_format: 'csv',
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

const plugins = [
  {
    id: 'example_upper',
    name: 'Example Upper',
    version: '1.0.0',
    enabled: true,
    manifest: { frontend: { menu_item: 'Example Upper', icon: 'letter-e' } },
    used_by_feed_sources: 0,
  },
  {
    id: 'disabled_plugin',
    name: 'Disabled',
    version: '1.0.0',
    enabled: false,
    manifest: { frontend: { menu_item: 'Hidden' } },
    used_by_feed_sources: 0,
  },
  {
    id: 'global_tool',
    name: 'Global Tool',
    version: '1.0.0',
    enabled: true,
    manifest: {
      frontend: { menu_item: 'Global Tool' },
      config_scope: ['global'],
      data_scope: 'global',
    },
    used_by_feed_sources: 0,
  },
  {
    id: 'client_widget',
    name: 'Client Widget',
    version: '1.0.0',
    enabled: true,
    manifest: {
      frontend: { menu_item: 'Client Widget' },
      config_scope: ['client'],
    },
    used_by_feed_sources: 0,
  },
  {
    id: 'data_scoped_widget',
    name: 'Data Widget',
    version: '1.0.0',
    enabled: true,
    manifest: {
      frontend: { menu_item: 'Data Widget' },
      data_scope: 'client',
    },
    used_by_feed_sources: 0,
  },
];

function authenticatedHandler(url: string) {
  if (url === '/auth/me') return jsonResponse({ username: 'operator' });
  if (url === '/dashboard/summary') return jsonResponse(summary);
  if (url === '/plugins') return jsonResponse(plugins);
  if (url.startsWith('/feed-sources/') && url.includes('/products')) {
    return jsonResponse({ items: [], total: 0, page: 1, page_size: 50 });
  }
  return jsonResponse({});
}

beforeEach(() => {
  queryClient.clear();
  window.history.replaceState({}, '', '/');
  stubFetch(authenticatedHandler);
});

describe('AppShell', () => {
  it('renders the fixed navigation and only enabled plugin menu items', async () => {
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.getByText('Setup')).toBeInTheDocument();
    expect(screen.getByText('Products')).toBeInTheDocument();
    expect(screen.getByText('Pipeline Editor')).toBeInTheDocument();
    expect(screen.getByText('Monitoring')).toBeInTheDocument();
    expect(screen.getByText('Export')).toBeInTheDocument();
    expect(await screen.findByText('Example Upper')).toBeInTheDocument();
    expect(screen.queryByText('Hidden')).not.toBeInTheDocument();
  });

  it('disables feed-scoped nav items until a feed source is selected', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: 'Dashboard' });
    expect(screen.getByText('Setup').closest('a,button')).toHaveAttribute('data-disabled', 'true');
  });

  it('shows the client and feed breadcrumb on a feed route', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    expect(await screen.findByText('Acme')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Acme' })).toHaveAttribute('href', '/');
    expect(await screen.findByText('Main Feed')).toBeInTheDocument();
  });

  it('keeps the current area when switching feeds from the breadcrumb dropdown', async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    await screen.findByText('Main Feed');
    await user.click(screen.getByRole('button', { name: 'Select feed' }));
    const secondary = await screen.findByRole('menuitem', { name: 'Secondary Feed' });
    expect(secondary).toHaveAttribute('href', '/clients/1/feeds/3/products');
  });

  it('logs out and returns to the login page', async () => {
    let loggedIn = true;
    stubFetch((url) => {
      if (url === '/auth/me') {
        return loggedIn
          ? jsonResponse({ username: 'operator' })
          : jsonResponse({ detail: 'Not authenticated' }, 401);
      }
      if (url === '/auth/logout') {
        loggedIn = false;
        return jsonResponse({ status: 'ok' });
      }
      if (url === '/dashboard/summary') return jsonResponse(summary);
      if (url === '/plugins') return jsonResponse(plugins);
      return jsonResponse({});
    });
    const user = userEvent.setup();
    render(<App />);

    await screen.findByRole('heading', { name: 'Dashboard' });
    await user.click(screen.getByRole('button', { name: 'operator' }));
    await user.click(await screen.findByText('Log out'));

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('links a global-scoped plugin to the global plugin route', async () => {
    render(<App />);
    expect(await screen.findByText('Global Tool')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Global Tool' })).toHaveAttribute(
      'href',
      '/plugins/global_tool',
    );
  });

  it('links a client-scoped plugin to the client route while on a client page', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    expect(await screen.findByText('Client Widget')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Client Widget' })).toHaveAttribute(
      'href',
      '/clients/1/plugins/client_widget',
    );
  });

  it('hides a client-scoped plugin from the nav when no client is selected', async () => {
    render(<App />);
    expect(await screen.findByText('Global Tool')).toBeInTheDocument();
    expect(screen.queryByText('Client Widget')).not.toBeInTheDocument();
  });

  it('treats a plugin with client data_scope as client-scoped', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    expect(await screen.findByText('Data Widget')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Data Widget' })).toHaveAttribute(
      'href',
      '/clients/1/plugins/data_scoped_widget',
    );
  });

  it('defaults a manifest without scope fields to the global route on a client page', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    expect(await screen.findByText('Example Upper')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Example Upper' })).toHaveAttribute(
      'href',
      '/plugins/example_upper',
    );
  });
});
