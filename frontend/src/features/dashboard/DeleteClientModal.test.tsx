import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Notifications, notifications } from '@mantine/notifications';
import { QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { DeleteClientModal } from './DeleteClientModal';
import { queryClient } from '../../api/queryClient';
import type { ClientSummary } from '../../api/types';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const client: ClientSummary = { id: 1, name: 'Acme', status: 'active', feed_sources: [] };

let fetchMock: ReturnType<typeof stubFetch>;

function deleteCalls(url: string): number {
  return fetchMock.mock.calls.filter(
    ([input, init]) => String(input) === url && init?.method === 'DELETE',
  ).length;
}

beforeAll(async () => {
  await i18n.loadNamespaces(['dashboard', 'common']);
});

beforeEach(() => {
  queryClient.clear();
  notifications.clean();
});

function renderWithQuery(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={queryClient}>
      <Notifications position="top-right" limit={5} />
      {ui}
    </QueryClientProvider>,
  );
}

describe('DeleteClientModal', () => {
  it('calls DELETE on confirm and toasts the deleted confirmation', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/clients/1') return new Response(null, { status: 204 });
      return jsonResponse({});
    });

    renderWithQuery(<DeleteClientModal opened client={client} onClose={() => {}} />);

    await screen.findByRole('dialog');
    const input = await screen.findByLabelText(/type/i);
    await user.type(input, 'Acme');
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }));

    await waitFor(() => expect(deleteCalls('/clients/1')).toBe(1));
    expect(await screen.findByText('Deleted')).toBeInTheDocument();
  });
});
