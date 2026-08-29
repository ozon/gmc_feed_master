import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications, Notifications } from '@mantine/notifications';
import { MemoryRouter, Route, Routes } from 'react-router';
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
  await i18n.loadNamespaces('plugins');
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
});
