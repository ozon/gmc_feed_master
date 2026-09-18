import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { Notifications, notifications } from '@mantine/notifications';
import i18n from '../i18n';
import { render } from '../test/render';
import { stubFetch } from '../test/fetch';
import { ExportUrlBlock } from './ExportUrlBlock';
import { queryClient } from '../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let fetchMock: ReturnType<typeof stubFetch>;

function postCalls(url: string): number {
  return fetchMock.mock.calls.filter(
    ([input, init]) => String(input) === url && init?.method === 'POST',
  ).length;
}

beforeEach(async () => {
  queryClient.clear();
  notifications.clean();
  window.history.replaceState({}, '', '/');
  await i18n.loadNamespaces('export');
});

function renderWithQuery(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={queryClient}>
      <Notifications position="top-right" limit={5} />
      {ui}
    </QueryClientProvider>,
  );
}

describe('ExportUrlBlock', () => {
  it('renders the export URL and rotate button', () => {
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me')
        return jsonResponse({ username: 'u', role: 'user', client_ids: null });
      return jsonResponse({});
    });
    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);

    expect(screen.getByDisplayValue('http://localhost/export/1/abc')).toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: /rotate/i })).toBeInTheDocument();
  });

  it('calls rotate endpoint on confirm and shows success notification', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me')
        return jsonResponse({ username: 'u', role: 'user', client_ids: null });
      if (url === '/feed-sources/1/export-token/rotate') {
        return jsonResponse({
          export_token: 'new123',
          export_url: 'http://localhost/export/1/new123',
        });
      }
      return jsonResponse({});
    });

    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);

    await user.click(screen.getByRole('button', { name: /rotate/i }));

    const confirm = await screen.findByRole('button', { name: 'Confirm' });
    await user.click(confirm);

    await waitFor(() => expect(postCalls('/feed-sources/1/export-token/rotate')).toBe(1));
    expect(await screen.findByText('Export token rotated successfully')).toBeInTheDocument();
  });

  it('does not POST when rotate is cancelled', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me')
        return jsonResponse({ username: 'u', role: 'user', client_ids: null });
      return jsonResponse({});
    });

    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);

    await user.click(screen.getByRole('button', { name: /rotate/i }));
    await screen.findByRole('button', { name: 'Confirm' });
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(postCalls('/feed-sources/1/export-token/rotate')).toBe(0));
  });

  it('toasts rotateFailed when rotation fails without a server detail', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me')
        return jsonResponse({ username: 'u', role: 'user', client_ids: null });
      if (url === '/feed-sources/1/export-token/rotate') {
        return new Response(null, { status: 500 });
      }
      return jsonResponse({});
    });

    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);

    await user.click(screen.getByRole('button', { name: /rotate/i }));
    const confirm = await screen.findByRole('button', { name: 'Confirm' });
    await user.click(confirm);

    expect(await screen.findByText('Could not rotate the export token.')).toBeInTheDocument();
  });

  it('shows the token editor for admins', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me')
        return jsonResponse({ username: 'u', role: 'admin', client_ids: null });
      return jsonResponse({});
    });
    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);
    expect(await screen.findByTestId('token-input')).toBeInTheDocument();
    expect(screen.getByTestId('token-save')).toBeInTheDocument();
  });

  it('hides the token editor for non-admins', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'u', role: 'user', client_ids: [1] });
      return jsonResponse({});
    });
    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);
    expect(await screen.findByRole('button', { name: /rotate/i })).toBeInTheDocument();
    expect(screen.queryByTestId('token-input')).not.toBeInTheDocument();
  });

  it('PUTs the custom token as admin', async () => {
    const user = userEvent.setup();
    let body: string | null = null;
    fetchMock = stubFetch((url, init) => {
      if (url === '/auth/me')
        return jsonResponse({ username: 'u', role: 'admin', client_ids: null });
      if (url === '/feed-sources/1/export-token' && init?.method === 'PUT') {
        body = typeof init.body === 'string' ? init.body : null;
        return jsonResponse({
          export_token: 'my-shop',
          export_url: 'http://localhost/export/my-shop.xml',
        });
      }
      return jsonResponse({});
    });
    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);

    const input = await screen.findByTestId('token-input');
    await user.clear(input);
    await user.type(input, 'my-shop');
    await user.click(screen.getByTestId('token-save'));
    const confirm = await screen.findByRole('button', { name: 'Confirm' });
    await user.click(confirm);

    await waitFor(() => expect(body).toBe(JSON.stringify({ export_token: 'my-shop' })));
  });
});
