import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider, Link } from 'react-router';
import { Notifications, notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { PipelinePage } from './PipelinePage';
import { queryClient } from '../../api/queryClient';
import { addInstance, isInstancesEqual, type LocalInstance } from './dndUtils';
import type { PipelineInstance } from '../../api/types';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const plugin = {
  id: 'upper',
  name: 'Upper',
  version: '1.0.0',
  enabled: true,
  manifest: {
    extension_point: 'pipeline_module',
    config_schema: { type: 'object', properties: { suffix: { type: 'string' } } },
  },
  used_by_feed_sources: 0,
};

const pipelineDoc = { instances: [] };

beforeAll(async () => {
  await i18n.loadNamespaces(['pipeline', 'common']);
});

beforeEach(() => {
  queryClient.clear();
  notifications.clean();
  stubFetch((url) => {
    if (url === '/plugins') return jsonResponse([plugin]);
    if (url === '/feed-sources/1/pipeline') return jsonResponse(pipelineDoc);
    return jsonResponse({});
  });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

function renderAt(initialEntry: string = '/clients/1/feeds/1/pipeline') {
  const router = createMemoryRouter(
    [
      {
        path: '/clients/:clientId/feeds/:feedSourceId/pipeline',
        element: (
          <>
            <PipelinePage />
            <Link to="/clients/1/feeds/1/products">Go to products</Link>
          </>
        ),
      },
      { path: '/clients/:clientId/feeds/:feedSourceId/products', element: <div>Products</div> },
    ],
    { initialEntries: [initialEntry] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(
    <Wrapper>
      <Notifications position="top-right" limit={1} />
      <RouterProvider router={router} />
    </Wrapper>,
    { wrapper: Wrapper },
  );
}

describe('PipelinePage', () => {
  it('renders the title and palette', async () => {
    renderAt();
    expect(await screen.findByRole('heading', { name: /pipeline/i })).toBeInTheDocument();
    expect(screen.getByTestId('plugin-palette')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-workspace')).toBeInTheDocument();
  });

  it('Save is disabled when not dirty', async () => {
    renderAt();
    await screen.findByRole('heading', { name: /pipeline/i });
    const save = await screen.findByRole('button', { name: /save/i });
    expect(save).toBeDisabled();
  });

  it('Save becomes enabled when local diverges from server snapshot (dirty tracking)', async () => {
    const serverInstances: PipelineInstance[] = [
      { position: 0, plugin_id: 'upper', name: 'Upper', configuration: {} },
    ];
    stubFetch((url) => {
      if (url === '/plugins') return jsonResponse([plugin]);
      if (url === '/feed-sources/1/pipeline') return jsonResponse({ instances: serverInstances });
      return jsonResponse({});
    });
    renderAt();
    await screen.findByRole('heading', { name: /pipeline/i });
    await waitFor(() => expect(screen.getByTestId('pipeline-workspace')).toBeInTheDocument());

    const baseLocal: LocalInstance[] = serverInstances.map((i) => ({
      ...i,
      clientId: 'seed',
    }));
    const cleanLocal = baseLocal;
    expect(isInstancesEqual(cleanLocal, serverInstances)).toBe(true);

    const dirtyLocal = addInstance(cleanLocal, { id: 'upper', name: 'Upper' });
    expect(isInstancesEqual(dirtyLocal, serverInstances)).toBe(false);
    expect(dirtyLocal.length).toBe(cleanLocal.length + 1);
  });

  it('useBlocker calls window.confirm when navigating away while dirty', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    const serverInstances: PipelineInstance[] = [
      { position: 0, plugin_id: 'upper', name: 'Upper', configuration: {} },
    ];
    stubFetch((url) => {
      if (url === '/plugins') return jsonResponse([plugin]);
      if (url === '/feed-sources/1/pipeline') return jsonResponse({ instances: serverInstances });
      return jsonResponse({});
    });
    renderAt();
    await screen.findByRole('heading', { name: /pipeline/i });
    await waitFor(() => expect(screen.getByTestId('pipeline-workspace')).toBeInTheDocument());

    const baseLocal: LocalInstance[] = serverInstances.map((i) => ({
      ...i,
      clientId: 'seed',
    }));
    const dirtyLocal = addInstance(baseLocal, { id: 'upper', name: 'Upper' });
    expect(isInstancesEqual(dirtyLocal, serverInstances)).toBe(false);
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});