import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { Notifications, notifications } from '@mantine/notifications';
import i18n from '../i18n';
import { render } from '../test/render';
import { stubFetch } from '../test/fetch';
import { ExportUrlBlock } from './ExportUrlBlock';
import { ExportUrlCard } from '../features/setup/ExportUrlCard';
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
    renderWithQuery(
      <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/abc.xml" />,
    );

    expect(screen.getByDisplayValue('http://localhost/export/abc.xml')).toHaveAttribute('readonly');
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
          export_url: 'http://localhost/export/new123.xml',
        });
      }
      return jsonResponse({});
    });

    renderWithQuery(
      <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/abc.xml" />,
    );

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

    renderWithQuery(
      <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/abc.xml" />,
    );

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

    renderWithQuery(
      <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/abc.xml" />,
    );

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
    renderWithQuery(
      <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/abc.xml" />,
    );
    expect(await screen.findByTestId('token-input')).toHaveValue('abc');
    expect(screen.getByTestId('token-save')).toBeInTheDocument();
  });

  it('updates the token field after a rotate refreshes the parent feed source', async () => {
    const user = userEvent.setup();
    let detailFetches = 0;
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me')
        return jsonResponse({ username: 'u', role: 'admin', client_ids: null });
      if (url === '/feed-sources/1') {
        detailFetches += 1;
        const token = detailFetches > 1 ? 'new123' : 'abc';
        return jsonResponse({ export_url: `http://localhost/export/${token}.xml` });
      }
      if (url === '/feed-sources/1/export-token/rotate') {
        return jsonResponse({
          export_token: 'new123',
          export_url: 'http://localhost/export/new123.xml',
        });
      }
      return jsonResponse({});
    });
    renderWithQuery(<ExportUrlCard feedSourceId={1} />);

    expect(await screen.findByTestId('token-input')).toHaveValue('abc');

    await user.click(screen.getByRole('button', { name: /generate random/i }));
    const confirm = await screen.findByRole('button', { name: 'Confirm' });
    await user.click(confirm);

    await waitFor(() => expect(screen.getByTestId('token-input')).toHaveValue('new123'));
  });

  it('hides the token editor for non-admins', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'u', role: 'user', client_ids: [1] });
      return jsonResponse({});
    });
    renderWithQuery(
      <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/abc.xml" />,
    );
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
    renderWithQuery(
      <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/abc.xml" />,
    );

    const input = await screen.findByTestId('token-input');
    await user.clear(input);
    await user.type(input, 'my-shop');
    await user.click(screen.getByTestId('token-save'));
    const confirm = await screen.findByRole('button', { name: 'Confirm' });
    await user.click(confirm);

    await waitFor(() => expect(body).toBe(JSON.stringify({ export_token: 'my-shop' })));
  });

  it('opens the live feed preview from the public URL', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me')
        return jsonResponse({ username: 'u', role: 'user', client_ids: null });
      if (url === 'http://localhost/export/abc.xml')
        return new Response('<g:id>A</g:id>', {
          status: 200,
          headers: { 'Content-Type': 'application/xml' },
        });
      return jsonResponse({});
    });
    renderWithQuery(
      <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/abc.xml" />,
    );

    await user.click(await screen.findByTestId('live-preview'));

    expect(await screen.findByTestId('xml-preview')).toHaveTextContent(/<g:id>\s*A\s*<\/g:id>/);
  });

  it('shows the not-published state when the live feed 404s', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me')
        return jsonResponse({ username: 'u', role: 'user', client_ids: null });
      if (url === 'http://localhost/export/abc.xml')
        return new Response('missing', { status: 404 });
      return jsonResponse({});
    });
    renderWithQuery(
      <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/abc.xml" />,
    );

    await user.click(await screen.findByTestId('live-preview'));

    expect(await screen.findByText(/no published feed yet/i)).toBeInTheDocument();
  });

  it('downloads the live feed via the public URL', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me')
        return jsonResponse({ username: 'u', role: 'user', client_ids: null });
      if (url === 'http://localhost/export/abc.xml')
        return new Response('<g:id>A</g:id>', {
          status: 200,
          headers: { 'Content-Type': 'application/xml' },
        });
      return jsonResponse({});
    });
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    let anchor: HTMLAnchorElement | undefined;
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation(
      (tagName: string, options?: ElementCreationOptions) => {
        const element = originalCreateElement(tagName, options);
        if (element instanceof HTMLAnchorElement) anchor = element;
        return element;
      },
    );
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    renderWithQuery(
      <ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/abc.xml" />,
    );

    await user.click(await screen.findByTestId('live-download'));

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledOnce());
    expect(anchor?.download).toBe('feed-1.xml');
  });
});
