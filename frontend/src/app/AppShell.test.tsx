import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { stubFetch } from '../test/fetch';
import App from '../App';
import { queryClient } from '../api/queryClient';
import { queryKeys } from '../api/queryKeys';

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
    manifest: { frontend: { menu_item: 'Example Upper', icon: 'letter-e', component: 'component.tsx' } },
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
  {
    id: 'feed_rules',
    name: 'Feed Rules',
    version: '1.0.0',
    enabled: true,
    manifest: {
      frontend: { menu_item: 'Feed Rules', component: 'component.tsx' },
      config_scope: ['global', 'client', 'feed_source'],
      data_scope: ['global', 'client', 'feed_source'],
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
  it('renders navigation with plugin entries after Setup in feed context', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    expect(await screen.findByRole('link', { name: /example upper/i }))
      .toHaveAttribute('href', '/clients/1/feeds/2/plugins/example_upper');
    const labels = screen.getAllByRole('link').map((a) => a.textContent ?? '');
    const setupIdx = labels.findIndex((l) => l === 'Setup');
    const pluginIdx = labels.findIndex((l) => l.includes('Example Upper'));
    const productsIdx = labels.findIndex((l) => l === 'Products');
    expect(setupIdx).toBeGreaterThan(-1);
    expect(pluginIdx).toBeGreaterThan(setupIdx);
    expect(productsIdx).toBeGreaterThan(pluginIdx);
  });

  it('shows no plugin entries outside a feed context', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: 'Dashboard' });
    expect(screen.queryByText('Example Upper')).not.toBeInTheDocument();
    expect(screen.queryByText('Feed Rules')).not.toBeInTheDocument();
  });

  it('lists only custom-UI plugins in the nav', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    expect(await screen.findByRole('link', { name: /example upper/i })).toBeInTheDocument();
    expect(screen.queryByText('Global Tool')).not.toBeInTheDocument();
    expect(screen.queryByText('Client Widget')).not.toBeInTheDocument();
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

  it('shows a logoutFailed toast when the server rejects the logout', async () => {
    const user = userEvent.setup();
    let logoutAttempted = false;
    stubFetch((url) => {
      if (url === '/auth/logout') {
        logoutAttempted = true;
        return jsonResponse({}, 500);
      }
      if (url === '/auth/me') {
        return logoutAttempted
          ? jsonResponse({ detail: 'Not authenticated' }, 401)
          : jsonResponse({ username: 'operator' });
      }
      if (url === '/dashboard/summary') return jsonResponse(summary);
      if (url === '/plugins') return jsonResponse(plugins);
      return jsonResponse({});
    });
    render(<App />);

    await screen.findByRole('heading', { name: 'Dashboard' });
    queryClient.setQueryData(queryKeys.session, { username: 'operator' });
    await user.click(screen.getByRole('button', { name: 'operator' }));
    await user.click(await screen.findByText('Log out'));

    expect(await screen.findByText(/failed on the server/i)).toBeInTheDocument();
    expect(queryClient.getQueryData(queryKeys.session)).toBeUndefined();
  });

});
