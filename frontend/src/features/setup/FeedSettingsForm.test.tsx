import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { Notifications, notifications } from '@mantine/notifications';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { FeedSettingsForm } from './FeedSettingsForm';
import { queryClient } from '../../api/queryClient';
import type { FeedSourceRow } from '../../api/types';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const feed: FeedSourceRow = {
  id: 1,
  client_id: 1,
  name: 'Acme Feed',
  source_format: 'xml',
  cron_expression: '0 9 * * *',
  target_country: 'DE',
  target_language: 'de',
  currency: 'EUR',
  source_url: 'https://example.com/feed.xml',
  feed_type: 'full',
  history_retention_count: 30,
  volume_drop_threshold_pct: 20,
  configuration: { basic_auth: { username: 'admin' } },
  export_url: 'http://localhost/export/1/abc',
  created_at: '2026-01-01T00:00:00',
  updated_at: '2026-01-01T00:00:00',
};

let fetchMock: ReturnType<typeof stubFetch>;

function putCalls(url: string): number {
  return fetchMock.mock.calls.filter(
    ([input, init]) => String(input) === url && init?.method === 'PUT',
  ).length;
}

function putBody(url: string): Record<string, unknown> | undefined {
  const call = fetchMock.mock.calls.find(
    ([input, init]) => String(input) === url && init?.method === 'PUT',
  );
  if (!call || !call[1]?.body) return undefined;
  return JSON.parse(String(call[1].body)) as Record<string, unknown>;
}

beforeEach(async () => {
  queryClient.clear();
  notifications.clean();
  window.history.replaceState({}, '', '/');
  await i18n.loadNamespaces('setup');
});

function renderWithQuery(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={queryClient}>
      <Notifications position="top-right" limit={5} />
      {ui}
    </QueryClientProvider>,
  );
}

describe('FeedSettingsForm', () => {
  it('renders all fields with initial values from feed', async () => {
    fetchMock = stubFetch((url) => jsonResponse({}));

    renderWithQuery(<FeedSettingsForm feed={feed} />);

    expect(await screen.findByDisplayValue('Acme Feed')).toBeInTheDocument();
    expect(screen.getByDisplayValue('https://example.com/feed.xml')).toBeInTheDocument();
    expect(screen.getByDisplayValue('0 9 * * *')).toBeInTheDocument();
    expect(screen.getByDisplayValue('DE')).toBeInTheDocument();
    expect(screen.getByDisplayValue('de')).toBeInTheDocument();
    expect(screen.getByDisplayValue('EUR')).toBeInTheDocument();
    expect(screen.getByDisplayValue('20')).toBeInTheDocument();
    expect(screen.getByDisplayValue('30')).toBeInTheDocument();
    expect(screen.getByDisplayValue('admin')).toBeInTheDocument();
  });

  it('sends only changed keys on save', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => jsonResponse({}));

    renderWithQuery(<FeedSettingsForm feed={feed} />);

    const nameInput = await screen.findByDisplayValue('Acme Feed');
    await user.clear(nameInput);
    await user.type(nameInput, 'New Name');

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());

    await user.click(saveBtn);

    await waitFor(() => expect(putCalls('/feed-sources/1')).toBe(1));
    const body = putBody('/feed-sources/1');
    expect(body).toEqual({ name: 'New Name' });
  });

  it('includes configuration.basic_auth when password is touched', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => jsonResponse({}));

    renderWithQuery(<FeedSettingsForm feed={feed} />);

    const nameInput = await screen.findByDisplayValue('Acme Feed');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated');

    const passwordInput = screen.getByPlaceholderText(/enter new password/i);
    await user.type(passwordInput, 'newpass');

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());

    await user.click(saveBtn);

    await waitFor(() => expect(putCalls('/feed-sources/1')).toBe(1));
    const body = putBody('/feed-sources/1');
    expect(body?.configuration).toEqual({
      basic_auth: { username: 'admin', password: 'newpass' },
    });
  });

  it('cron preset sets cron input', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => jsonResponse({}));

    renderWithQuery(<FeedSettingsForm feed={feed} />);

    await screen.findByDisplayValue('Acme Feed');

    const presetSelect = screen.getByRole('combobox', { name: /utc/i });
    await user.click(presetSelect);
    await user.click(screen.getByRole('option', { name: /daily/i }));

    const matches = screen.getAllByDisplayValue('0 0 * * *');
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it('shows error on 422 cron validation', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1') {
        return jsonResponse({ detail: 'invalid cron' }, 422);
      }
      return jsonResponse({});
    });

    renderWithQuery(<FeedSettingsForm feed={feed} />);

    const nameInput = await screen.findByDisplayValue('Acme Feed');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated');

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());

    await user.click(saveBtn);

    expect(screen.getAllByText('invalid cron').length).toBeGreaterThanOrEqual(2);
  });

  it('save is disabled until dirty', async () => {
    fetchMock = stubFetch((url) => jsonResponse({}));

    renderWithQuery(<FeedSettingsForm feed={feed} />);

    await screen.findByDisplayValue('Acme Feed');

    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
  });

  it('reset restores server values', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => jsonResponse({}));

    renderWithQuery(<FeedSettingsForm feed={feed} />);

    const nameInput = await screen.findByDisplayValue('Acme Feed');
    await user.clear(nameInput);
    await user.type(nameInput, 'Changed');

    expect(screen.getByDisplayValue('Changed')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /cancel/i }));

    expect(await screen.findByDisplayValue('Acme Feed')).toBeInTheDocument();
  });
});
