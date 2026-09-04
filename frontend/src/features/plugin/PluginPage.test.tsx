import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications, Notifications } from '@mantine/notifications';
import { createMemoryRouter, MemoryRouter, Route, Routes, RouterProvider } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { PluginPage } from './PluginPage';
import { queryClient } from '../../api/queryClient';
import type { ReactNode } from 'react';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const plugin = {
  id: 'example_upper',
  name: 'Example Upper',
  version: '1.0.0',
  enabled: true,
  manifest: {
    config_schema: {
      type: 'object',
      properties: { suffix: { type: 'string', title: 'Suffix' } },
      required: ['suffix'],
    },
  },
  used_by_feed_sources: 0,
};

beforeAll(async () => {
  await i18n.loadNamespaces(['plugins', 'rules', 'common']);
});

beforeEach(() => {
  queryClient.clear();
  notifications.clean();
});

function withQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Notifications position="top-right" limit={1} />
      <Routes>
        <Route path="/plugins/:pluginId" element={<PluginPage />} />
        <Route path="/clients/:clientId/plugins/:pluginId" element={<PluginPage />} />
      </Routes>
    </MemoryRouter>,
    { wrapper: withQueryClient() },
  );
}

function renderWithDataRouter(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/plugins/:pluginId', element: <PluginPage /> },
      { path: '/clients/:clientId/plugins/:pluginId', element: <PluginPage /> },
      { path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId', element: <PluginPage /> },
    ],
    { initialEntries: [path] },
  );
  return render(
    <>
      <Notifications position="top-right" limit={1} />
      <RouterProvider router={router} />
    </>,
    { wrapper: withQueryClient() },
  );
}

describe('PluginPage', () => {
  it('renders the auto-form from manifest.config_schema (global route)', async () => {
    let captured: string | null = null;
    stubFetch((url, init) => {
      if (url === '/plugins') {
        return jsonResponse([plugin]);
      }
      if (url.startsWith('/plugins/example_upper/config') && (!init || init.method === undefined)) {
        captured = url;
        return jsonResponse({ suffix: '!' });
      }
      return jsonResponse({});
    });

    renderAt('/plugins/example_upper');
    expect(await screen.findByRole('heading', { name: 'Example Upper' })).toBeInTheDocument();
    const input = await screen.findByLabelText(/suffix/i);
    expect(input).toHaveValue('!');
    expect(captured).toBe('/plugins/example_upper/config');
  });

  it('passes client_id scope from /clients/:clientId/plugins/:pluginId', async () => {
    let captured: string | null = null;
    stubFetch((url) => {
      if (url === '/plugins') return jsonResponse([plugin]);
      if (url.startsWith('/plugins/example_upper/config')) {
        captured = url;
        return jsonResponse({});
      }
      return jsonResponse({});
    });

    renderAt('/clients/7/plugins/example_upper');
    await screen.findByRole('heading', { name: 'Example Upper' });
    await waitFor(() => expect(captured).toBe('/plugins/example_upper/config?client_id=7'));
  });

  it('saves the form via PUT and shows a success notification', async () => {
    const user = userEvent.setup();
    let putBody: unknown = null;
    stubFetch((url, init) => {
      if (url === '/plugins') return jsonResponse([plugin]);
      if (url.startsWith('/plugins/example_upper/config') && init?.method === 'PUT') {
        putBody = JSON.parse(String(init.body));
        return jsonResponse({ suffix: 'X' });
      }
      if (url.startsWith('/plugins/example_upper/config')) {
        return jsonResponse({ suffix: '!' });
      }
      return jsonResponse({});
    });

    renderAt('/plugins/example_upper');
    const input = await screen.findByLabelText(/suffix/i);
    await user.clear(input);
    await user.type(input, 'X');
    await user.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(putBody).toEqual({ suffix: 'X' }));
    expect(await screen.findByText(/settings saved|config saved|saved/i)).toBeInTheDocument();
  });

  it('renders EmptyState when manifest has no config_schema and no data_schema', async () => {
    const dataOnly = { ...plugin, manifest: { data_schema: { type: 'object' } } };
    stubFetch((url) => {
      if (url === '/plugins') return jsonResponse([dataOnly]);
      if (url.startsWith('/plugins/example_upper/config')) return jsonResponse({});
      return jsonResponse({});
    });

    renderAt('/plugins/example_upper');
    expect(await screen.findByText(/no schema|no configuration/i)).toBeInTheDocument();
  });

  it('renders a custom component when manifest.frontend.component is set', async () => {
    const rulesPlugin = {
      ...plugin,
      id: 'rules',
      name: 'Rules',
      manifest: {
        ...plugin.manifest,
        frontend: { menu_item: 'Rules', icon: 'list-check', component: 'component.tsx' },
      },
    };
    let capturedConfigUrl: string | null = null;
    stubFetch((url, init) => {
      if (url === '/plugins') return jsonResponse([rulesPlugin]);
      if (url.startsWith('/plugins/rules/config')) {
        if (init?.method === 'PUT') return jsonResponse({ rules: [] });
        capturedConfigUrl = url;
        return jsonResponse({
          rules: [
            {
              id: 'r1',
              name: 'Remove HTML',
              isMasterRule: true,
              isActive: true,
              when: { op: 'all' },
              then: [{ op: 'set', field: 'condition', value: 'new' }],
            },
          ],
        });
      }
      if (url.startsWith('/feed-sources/1/fields')) return jsonResponse({ fields: ['title', 'condition'] });
      return jsonResponse({});
    });
    renderWithDataRouter('/clients/1/feeds/1/plugins/rules');
    expect(await screen.findByTestId('rules-list')).toBeInTheDocument();
    // Custom components fetch their own config; PluginPage's generic config
    // fetch is skipped (asymmetric-scope plugins like custom_labels would 422
    // at undeclared tiers). Feed scope wins (most-specific): the custom
    // component's own config fetch targets the feed tier only.
    await waitFor(() => expect(capturedConfigUrl).toBe('/plugins/rules/config?feed_source_id=1'));
    expect(capturedConfigUrl).not.toContain('client_id');
    // Generic Save is hidden with a custom component; the only "Save" button is RulesUI's own, disabled until dirty.
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled();
  });

  it('renders the filter custom component for the filter plugin', async () => {
    const filterPlugin = {
      ...plugin,
      id: 'filter',
      name: 'Filter',
      manifest: {
        frontend: { menu_item: 'Filter', icon: 'filter', component: 'component.tsx' },
      },
    };
    stubFetch((url, init) => {
      if (url === '/plugins') return jsonResponse([filterPlugin]);
      if (url.startsWith('/plugins/filter/config')) {
        if (init?.method === 'PUT') return jsonResponse({ isActive: true, conditions: [] });
        return jsonResponse({ isActive: true, conditions: [] });
      }
      if (url.startsWith('/feed-sources/1/fields')) return jsonResponse({ fields: ['brand'] });
      if (url.startsWith('/plugins/filter/preview')) return jsonResponse({ total: 2, pass: 1, fail: 1 });
      return jsonResponse({});
    });
    renderWithDataRouter('/clients/1/feeds/1/plugins/filter');
    expect(await screen.findByTestId('filter-editor')).toBeInTheDocument();
    expect(screen.queryByText(/no configuration schema/i)).not.toBeInTheDocument();
  });

  it('renders a custom component even when config_schema is absent', async () => {
    const schemalessRules = {
      ...plugin,
      id: 'rules',
      name: 'Rules',
      manifest: {
        frontend: { menu_item: 'Rules', icon: 'list-check', component: 'component.tsx' },
      },
    };
    stubFetch((url, init) => {
      if (url === '/plugins') return jsonResponse([schemalessRules]);
      if (url.startsWith('/plugins/rules/config')) {
        if (init?.method === 'PUT') return jsonResponse({ rules: [] });
        return jsonResponse({ rules: [] });
      }
      if (url.startsWith('/feed-sources/1/fields')) return jsonResponse({ fields: ['title'] });
      return jsonResponse({});
    });
    renderWithDataRouter('/clients/1/feeds/1/plugins/rules');
    expect(await screen.findByTestId('rules-list')).toBeInTheDocument();
    expect(screen.queryByText(/no configuration schema/i)).not.toBeInTheDocument();
  });

  it('renders the custom_labels component at feed scope without a 422 on the generic config fetch', async () => {
    const customLabelsPlugin = {
      ...plugin,
      id: 'custom_labels',
      name: 'Custom Labels',
      manifest: {
        config_scope: ['global', 'client'],
        data_scope: ['client', 'feed_source'],
        frontend: { menu_item: 'Custom Labels', icon: 'tag', component: 'component.tsx' },
      },
    };
    const captured: string[] = [];
    stubFetch((url) => {
      captured.push(url);
      if (url === '/plugins') return jsonResponse([customLabelsPlugin]);
      // Backend would 422 a feed-scoped config request; if the buggy generic
      // fetch fires, this stub returns the error and the page must not die.
      if (url.startsWith('/plugins/custom_labels/config')) {
        return url.includes('feed_source_id')
          ? jsonResponse({ errors: ['scope not declared for this plugin'] }, 422)
          : jsonResponse({ slotRules: [] });
      }
      if (url.startsWith('/plugins/custom_labels/data')) return jsonResponse({ slotIds: {} });
      if (url.startsWith('/registry/attributes')) return jsonResponse([]);
      return jsonResponse({});
    });
    renderWithDataRouter('/clients/1/feeds/1/plugins/custom_labels');
    // The component renders (its own config fetch resolves at client tier).
    expect(await screen.findByRole('tab', { name: /bulk ids/i })).toBeInTheDocument();
    // PluginPage never issued the feed-scoped generic config request.
    expect(captured).not.toContain('/plugins/custom_labels/config?feed_source_id=1');
  });
});
