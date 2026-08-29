import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Notifications } from '@mantine/notifications';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import App from '../../App';
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
  configuration: {},
  export_url: 'http://localhost/export/1/abc',
  created_at: '2026-01-01T00:00:00',
  updated_at: '2026-01-01T00:00:00',
};

let fetchMock: ReturnType<typeof stubFetch>;

beforeEach(() => {
  queryClient.clear();
  window.history.replaceState({}, '', '/clients/1/feeds/1/setup');
});

describe('SetupPage', () => {
  it('renders settings tab by default', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/feed-sources/1') return jsonResponse(feed);
      return jsonResponse({});
    });

    render(<App />);

    expect(await screen.findByRole('tab', { name: /settings/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /mapping/i })).toBeInTheDocument();
    expect(screen.getByDisplayValue('Acme Feed')).toBeInTheDocument();
  });

  it('switches to mapping tab and updates search param', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/feed-sources/1') return jsonResponse(feed);
      return jsonResponse({});
    });

    render(<App />);

    await screen.findByRole('tab', { name: /settings/i });

    await user.click(screen.getByRole('tab', { name: /mapping/i }));

    await waitFor(() => {
      expect(window.location.search).toContain('tab=mapping');
    });

    expect(await screen.findByText(/mapping configuration will be available/i)).toBeInTheDocument();
  });
});
