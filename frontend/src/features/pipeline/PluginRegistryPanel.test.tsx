import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications, Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { PluginRegistryPanel } from './PluginRegistryPanel';
import { queryClient } from '../../api/queryClient';
import type { PluginInfo } from '../../api/types';

const pluginInUse: PluginInfo = {
  id: 'upper',
  name: 'Upper',
  version: '1.0.0',
  enabled: true,
  manifest: { extension_point: 'pipeline_module', frontend: { icon: 'letter-a' } },
  used_by_feed_sources: 2,
};

const pluginUnused: PluginInfo = {
  ...pluginInUse,
  id: 'lower',
  name: 'Lower',
  used_by_feed_sources: 0,
};

beforeAll(async () => {
  await i18n.loadNamespaces('pipeline');
});

beforeEach(() => {
  queryClient.clear();
  notifications.clean();
  stubFetch(() => new Response(JSON.stringify({}), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }));
});

function withQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function renderAt(plugins: PluginInfo[]) {
  return render(
    <>
      <Notifications position="top-right" limit={1} />
      <PluginRegistryPanel plugins={plugins} />
    </>,
    { wrapper: withQueryClient() },
  );
}

describe('PluginRegistryPanel', () => {
  it('renders the panel header', () => {
    renderAt([pluginUnused]);
    expect(screen.getByTestId('registry-panel-control')).toBeInTheDocument();
  });

  it('shows "in use" badge for plugins in use', async () => {
    const user = userEvent.setup();
    renderAt([pluginInUse]);
    await user.click(screen.getByTestId('registry-panel-control'));
    expect(screen.getByText(/used by 2 feed sources/i)).toBeInTheDocument();
  });

  it('opens a ConfirmModal when disabling a plugin that is in use', async () => {
    const user = userEvent.setup();
    renderAt([pluginInUse]);
    await user.click(screen.getByTestId('registry-panel-control'));
    const toggle = screen.getByTestId(`plugin-toggle-${pluginInUse.id}`);
    await user.click(toggle);
    expect(await screen.findByText(/used by feed sources/i)).toBeInTheDocument();
  });

  it('calls toggleEnabled directly when disabling an unused plugin', async () => {
    const user = userEvent.setup();
    let putUrl: string | null = null;
    let putBody: unknown = null;
    stubFetch((url, init) => {
      if (url.startsWith(`/plugins/${pluginUnused.id}/enabled`) && init?.method === 'PUT') {
        putUrl = url;
        putBody = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ ...pluginUnused, enabled: false }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    renderAt([pluginUnused]);
    await user.click(screen.getByTestId('registry-panel-control'));
    await user.click(screen.getByTestId(`plugin-toggle-${pluginUnused.id}`));
    await waitFor(() => {
      expect(putUrl).toBe(`/plugins/${pluginUnused.id}/enabled`);
      expect(putBody).toEqual({ enabled: false });
    });
  });
});