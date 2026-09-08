import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { waitFor } from '@testing-library/react';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import App from '../../App';
import { queryClient } from '../../api/queryClient';
import { queryKeys } from '../../api/queryKeys';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const clients = [
  { id: 3, name: 'Globex', contact_details: {}, status: 'active', created_at: '2026-01-01' },
];

beforeEach(() => {
  queryClient.clear();
  window.history.replaceState({}, '', '/admin/clients');
});

describe('AdminClientsPage', () => {
  it('lists clients and deletes with type-to-confirm', async () => {
    const user = userEvent.setup();
    let deleted = false;
    const fetchMock = stubFetch((url, init) => {
      if (init?.method === 'DELETE' && url === '/clients/3') {
        deleted = true;
        return new Response(null, { status: 204 });
      }
      if (url === '/clients')
        return jsonResponse(deleted ? [] : clients);
      if (url === '/dashboard/summary')
        return jsonResponse({
          counts: { clients: 0, feed_sources: 0, active_products: 0, failed_last_exports: 0 },
          clients: [],
        });
      if (url === '/plugins') return jsonResponse([]);
      return jsonResponse({});
    });
    void fetchMock;

    queryClient.setQueryData(queryKeys.session, {
      username: 'operator',
      role: 'admin',
      client_ids: null,
    });
    render(<App />);

    expect(await screen.findByText('Globex')).toBeInTheDocument();

    const deleteButton = screen.getByRole('button', { name: 'Delete client' });
    await user.click(deleteButton);

    const confirm = await screen.findByRole('button', { name: 'Confirm' });
    expect(confirm).toBeDisabled();

    const confirmInput = screen.getByLabelText(/type globex to confirm/i);
    await user.type(confirmInput, 'Globex');
    expect(confirm).toBeEnabled();

    await user.click(confirm);

    await waitFor(() => expect(screen.queryByText('Globex')).not.toBeInTheDocument());
  });
});
