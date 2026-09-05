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

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
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

const serverDoc = {
  instances: [
    { id: 11, position: 0, plugin_id: 'upper', name: 'Upper',
      configuration: { suffix: '!' }, enabled: true },
  ],
};

beforeAll(async () => {
  await i18n.loadNamespaces(['pipeline', 'common']);
});

beforeEach(() => {
  queryClient.clear();
  notifications.clean();
  stubFetch((url) => {
    if (url === '/plugins') return jsonResponse([plugin]);
    if (url === '/feed-sources/1/pipeline') return jsonResponse(serverDoc);
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
  it('renders title, overview strip and instance rows', async () => {
    renderAt();
    expect(await screen.findByRole('heading', { name: /pipeline/i })).toBeInTheDocument();
    expect(screen.getByTestId('overview-strip')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-row-upper-0')).toBeInTheDocument(); // clientId = `upper-0`
  });

  it('selects first instance by default and shows its config form', async () => {
    renderAt();
    await screen.findByTestId('config-panel');
    expect(await screen.findByLabelText(/suffix/i)).toBeInTheDocument();
  });

  it('clicking a row selects it; config edits update only local state', async () => {
    const user = userEvent.setup();
    renderAt();
    const row = await screen.findByTestId('plugin-row-upper-0');
    await user.click(row);
    const input = await screen.findByLabelText(/suffix/i);
    await user.clear(input);
    await user.type(input, '?');
    // Save enabled => dirty tracking works
    await waitFor(() => expect(screen.getByRole('button', { name: /save/i })).toBeEnabled());
  });

  it('flipping the per-instance switch PATCHes immediately and rolls back on failure', async () => {
    const user = userEvent.setup();
    let patchFailed = false;
    stubFetch((url, init) => {
      if (url === '/plugins') return jsonResponse([plugin]);
      if (url === '/feed-sources/1/pipeline') return jsonResponse(serverDoc);
      if (url === '/feed-sources/1/pipeline/instances/11' && init?.method === 'PATCH') {
        patchFailed = true;
        return jsonResponse({ detail: 'boom' }, 500);
      }
      return jsonResponse({});
    });
    renderAt();
    await screen.findByTestId('plugin-toggle-upper-0');
    await user.click(screen.getByTestId('plugin-toggle-upper-0'));
    await waitFor(() => expect(patchFailed).toBe(true));
    // rolled back to checked after failure
    await waitFor(() => expect(screen.getByTestId('plugin-toggle-upper-0')).toBeChecked());
  });

  it('add from registry marks the page dirty', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/plugins') return jsonResponse([plugin, { ...plugin, id: 'fresh', name: 'Fresh' }]);
      if (url === '/feed-sources/1/pipeline') return jsonResponse(serverDoc);
      return jsonResponse({});
    });
    renderAt();
    await user.click(await screen.findByTestId('add-plugin-fresh'));
    await waitFor(() => expect(screen.getByRole('button', { name: /save/i })).toBeEnabled());
  });

  it('drag reorders rows and Save PUTs the new order with stable ids', async () => {
    const user = userEvent.setup();
    const twoInstanceDoc = {
      instances: [
        { id: 11, position: 0, plugin_id: 'upper', name: 'First',
          configuration: {}, enabled: true },
        { id: 12, position: 1, plugin_id: 'upper', name: 'Second',
          configuration: {}, enabled: true },
      ],
    };
    let putBody: unknown = null;
    stubFetch((url, init) => {
      if (url === '/plugins') return jsonResponse([plugin]);
      if (url === '/feed-sources/1/pipeline' && init?.method === 'PUT') {
        putBody = JSON.parse(String(init.body));
        return jsonResponse(twoInstanceDoc);
      }
      if (url === '/feed-sources/1/pipeline') return jsonResponse(twoInstanceDoc);
      return jsonResponse({});
    });
    renderAt();
    await screen.findByTestId('plugin-row-upper-0');
    await screen.findByTestId('plugin-row-upper-1');

    const handle = screen.getByTestId('drag-handle-upper-0');
    const draggedRow = screen.getByTestId('plugin-row-upper-0');
    const secondRow = screen.getByTestId('plugin-row-upper-1');
    const rowBox = { left: 0, top: 0, width: 300, height: 48 };
    const secondBox = { left: 0, top: 60, width: 300, height: 48 };
    // dnd-kit collision-detects against the ACTIVE row Card's rect (not the
    // handle) — mock it too, else the jsdom all-zero rect never intersects.
    vi.spyOn(draggedRow, 'getBoundingClientRect').mockReturnValue({
      ...rowBox, right: rowBox.left + rowBox.width, bottom: rowBox.top + rowBox.height,
      x: rowBox.left, y: rowBox.top, toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(handle, 'getBoundingClientRect').mockReturnValue({
      ...rowBox, right: rowBox.left + rowBox.width, bottom: rowBox.top + rowBox.height,
      x: rowBox.left, y: rowBox.top, toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(secondRow, 'getBoundingClientRect').mockReturnValue({
      ...secondBox, right: secondBox.left + secondBox.width,
      bottom: secondBox.top + secondBox.height,
      x: secondBox.left, y: secondBox.top, toJSON: () => ({}),
    } as DOMRect);

    // activationConstraint distance: 4 — move ≥4px to activate, then drop on row 2
    await user.pointer([
      { keys: '[MouseLeft>]', target: handle, coords: { clientX: 10, clientY: 10 } },
      { target: handle, coords: { clientX: 10, clientY: 20 } },
      { target: secondRow, coords: { clientX: 150, clientY: 80 } },
      { keys: '[/MouseLeft]', target: secondRow, coords: { clientX: 150, clientY: 80 } },
    ]);

    // Row order flipped: the row that was at index 0 now holds "Second"
    const firstRow = await screen.findByTestId('plugin-row-upper-1');
    expect(firstRow).toHaveTextContent('Second');

    await user.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(putBody).not.toBeNull());
    const saved = putBody as { instances: Array<{ id: number; name: string }> };
    expect(saved.instances[0]).toMatchObject({ id: 12, name: 'Second' });
    expect(saved.instances[1]).toMatchObject({ id: 11, name: 'First' });
  });

  it('remove button deletes the instance locally and enables Save', async () => {
    const user = userEvent.setup();
    renderAt();
    await user.click(await screen.findByRole('button', { name: /remove/i }));
    expect(screen.queryByTestId('plugin-row-upper-0')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /save/i })).toBeEnabled());
  });

  it('useBlocker prompts on navigation when dirty', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/plugins') return jsonResponse([plugin]);
      if (url === '/feed-sources/1/pipeline') return jsonResponse(serverDoc);
      return jsonResponse({});
    });
    renderAt();
    const input = await screen.findByLabelText(/suffix/i);
    await user.clear(input);
    await user.type(input, '?');
    await user.click(screen.getByRole('link', { name: /go to products/i }));
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
  });
});
