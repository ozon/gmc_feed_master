import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { Notifications } from '@mantine/notifications';
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
    fetchMock = stubFetch((url) => jsonResponse({}));
    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);

    expect(screen.getByDisplayValue('http://localhost/export/1/abc')).toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: /rotate/i })).toBeInTheDocument();
  });

  it('calls rotate endpoint on confirm and shows success notification', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/export-token/rotate') {
        return jsonResponse({ export_token: 'new123', export_url: 'http://localhost/export/1/new123' });
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
    fetchMock = stubFetch((url) => jsonResponse({}));

    renderWithQuery(<ExportUrlBlock feedSourceId={1} exportUrl="http://localhost/export/1/abc" />);

    await user.click(screen.getByRole('button', { name: /rotate/i }));
    await screen.findByRole('button', { name: 'Confirm' });
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(postCalls('/feed-sources/1/export-token/rotate')).toBe(0));
  });
});
