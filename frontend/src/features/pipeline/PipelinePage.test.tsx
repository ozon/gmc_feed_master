import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { Notifications, notifications } from '@mantine/notifications';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { PipelinePage } from './PipelinePage';
import { queryClient } from '../../api/queryClient';

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

function renderAt() {
  const router = createMemoryRouter(
    [
      {
        path: '/clients/:clientId/feeds/:feedSourceId/pipeline',
        element: <PipelinePage />,
      },
    ],
    { initialEntries: ['/clients/1/feeds/1/pipeline'] },
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
});