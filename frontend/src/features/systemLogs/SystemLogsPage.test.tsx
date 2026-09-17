import { beforeAll, describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { SystemLogsPage } from './SystemLogsPage';

const fetchMock = vi.fn<typeof fetch>();

beforeAll(async () => {
  await i18n.loadNamespaces(['systemLogs']);
});

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
});

describe('SystemLogsPage', () => {
  it('renders log rows from the API', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [
            {
              id: 2,
              created_at: '2026-09-17T10:00:00Z',
              category: 'audit',
              level: 'info',
              source: 'backend',
              logger: null,
              actor: 'operator',
              actor_role: 'admin',
              client_id: null,
              feed_source_id: null,
              request_id: 'req-1',
              run_id: null,
              message: 'user.create',
              context: { target_type: 'user' },
            },
          ],
          next_cursor: null,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    render(<SystemLogsPage />);
    await waitFor(() => expect(screen.getByText('user.create')).toBeInTheDocument());
    expect(screen.getByText('operator')).toBeInTheDocument();
  });
});
