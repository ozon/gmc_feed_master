import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Notifications, notifications } from '@mantine/notifications';
import {QueryClient} from '@tanstack/react-query';
import i18n from '../../i18n';
import { queryClient } from '../../api/queryClient';
import { render } from '../../test/render';
import { AdminSettingsPage } from './AdminSettingsPage';
import { ApiError } from '../../api/client';

vi.mock('../../api/hooks', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useAdminSettings: () => ({
    data: {
      staging_removal_retention_days: 90,
      staging_history_retention_days: 90,
      ingestion_run_retention_days: 90,
    },
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useSchedulerJobs: () => ({ data: [], isPending: false, isError: false, refetch: vi.fn() }),
  usePlugins: () => ({
    data: [
      {
        id: 'filter',
        name: 'Filter',
        version: '1.0.0',
        enabled: true,
        manifest: {},
        used_by_feed_sources: 2,
      },
    ],
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useUpdatePluginEnabled: () => ({
    mutate: (_payload: unknown, opts?: { onError?: (error: unknown) => void }) => {
      opts?.onError?.(new ApiError(409, 'plugin in use by 2 feed sources'));
    },
    isPending: false,
  }),
  useSaveAdminSettings: () => ({ mutate: vi.fn(), isPending: false }),
}));

beforeEach(async () => {
  queryClient.clear();
  window.history.replaceState({}, '', '/');
  await i18n.loadNamespaces(['admin', 'pipeline', 'plugins']);
  notifications.clean();
});

function renderPage() {
  return render(
    <>
      <Notifications position="top-right" limit={1} />
      <AdminSettingsPage />
    </>,
  );
}

describe('AdminSettingsPage', () => {
  it('toasts disableBlocked with the cached count when toggling an in-use plugin fails with 409', async () => {
    const user = userEvent.setup();
    renderPage();
    const toggle = await screen.findByRole('switch');
    await user.click(toggle);
    expect(await screen.findByText(/in use by 2 feed sources/i)).toBeInTheDocument();
  });
});
