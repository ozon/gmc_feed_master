import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { notifications, Notifications } from '@mantine/notifications';
import type { ComponentProps, ReactNode } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { PluginList } from './PluginList';
import type { LocalInstance } from './dndUtils';
import type { PluginInfo } from '../../api/types';

const instances: LocalInstance[] = [
  { id: 1, position: 0, plugin_id: 'upper', name: 'Upper', configuration: {}, enabled: true, clientId: 'upper-0' },
  { id: 2, position: 1, plugin_id: 'lower', name: 'Lower', configuration: {}, enabled: false, clientId: 'lower-1' },
];

const plugins: PluginInfo[] = [
  { id: 'upper', name: 'Upper', version: '1.0.0', enabled: true,
    manifest: { extension_point: 'pipeline_module' }, used_by_feed_sources: 0 },
  { id: 'lower', name: 'Lower', version: '1.0.0', enabled: true,
    manifest: { extension_point: 'pipeline_module' }, used_by_feed_sources: 3 },
  { id: 'fresh', name: 'Fresh', version: '1.0.0', enabled: true,
    manifest: { extension_point: 'pipeline_module' }, used_by_feed_sources: 0 },
];

beforeAll(async () => {
  await i18n.loadNamespaces(['pipeline', 'common']);
});

beforeEach(() => {
  notifications.clean();
  stubFetch(() => jsonResponse({}));
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

function renderAt(overrides?: Partial<ComponentProps<typeof PluginList>>) {
  const props: ComponentProps<typeof PluginList> = {
    instances,
    plugins,
    selectedClientId: 'upper-0',
    onSelect: vi.fn(),
    onToggleEnabled: vi.fn(),
    onAdd: vi.fn(),
    onReorderDragEnd: vi.fn(),
    ...overrides,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(
    <>
      <Notifications position="top-right" limit={1} />
      <PluginList {...props} />
    </>,
    { wrapper: Wrapper },
  );
}

describe('PluginList', () => {
  it('renders ordered instance rows with switches and drag handles', () => {
    renderAt();
    expect(screen.getByTestId('plugin-row-upper-0')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-row-lower-1')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-toggle-upper-0')).toBeInTheDocument();
    expect(screen.getByTestId('drag-handle-upper-0')).toBeInTheDocument();
  });

  it('highlights the selected row', () => {
    renderAt();
    const row = screen.getByTestId('plugin-row-upper-0');
    expect(row).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('plugin-row-lower-1')).toHaveAttribute('data-selected', 'false');
  });

  it('calls onToggleEnabled when the per-instance switch flips', async () => {
    const user = userEvent.setup();
    const onToggleEnabled = vi.fn();
    renderAt({ onToggleEnabled });
    await user.click(screen.getByTestId('plugin-toggle-lower-1'));
    expect(onToggleEnabled).toHaveBeenCalledWith('lower-1', true);
  });

  it('does not select the row when toggling its switch', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderAt({ onSelect });
    await user.click(screen.getByTestId('plugin-toggle-lower-1'));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('lists only pipeline_module plugins not already in the pipeline under add-from-registry', () => {
    renderAt();
    expect(screen.getByTestId('add-plugin-fresh')).toBeInTheDocument();
    expect(screen.queryByTestId('add-plugin-upper')).not.toBeInTheDocument();
  });

  it('calls onAdd with the plugin id', async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    renderAt({ onAdd });
    await user.click(screen.getByTestId('add-plugin-fresh'));
    expect(onAdd).toHaveBeenCalledWith('fresh');
  });

  it('opens ConfirmModal when disabling an in-use plugin via registry switch', async () => {
    const user = userEvent.setup();
    renderAt();
    await user.click(screen.getByTestId('registry-toggle-lower'));
    expect(await screen.findByText(/type 3 to confirm/i)).toBeInTheDocument();
  });

  it('registry toggle shows disableBlocked toast on 409', async () => {
    const user = userEvent.setup();
    stubFetch((url, init) => {
      if (url === '/plugins/lower/enabled' && init?.method === 'PUT') {
        return jsonResponse({ detail: 'plugin in use by 3 feed sources' }, 409);
      }
      return jsonResponse({});
    });
    renderAt();
    await user.click(screen.getByTestId('registry-toggle-lower'));
    await user.type(screen.getByLabelText(/type 3 to confirm/i), '3');
    await user.click(await screen.findByRole('button', { name: /disable/i }));
    expect(await screen.findByText(/in use by 3 feed sources/i)).toBeInTheDocument();
  });
});
