import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { MatchesModal } from './MatchesModal';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function pageItems(prefix: string, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    product_id: `${prefix}-${i}`,
    title: `${prefix} product ${i}`,
  }));
}

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MatchesModal feedSourceId={7} ruleId="g1" opened onClose={() => {}} />
    </QueryClientProvider>,
  );
}

beforeAll(async () => {
  await i18n.loadNamespaces(['category', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
  notifications.clean();
});

describe('MatchesModal', () => {
  it('appends the next page on load-more and keeps earlier items visible', async () => {
    const fetchMock = stubFetch((url: string) => {
      const params = new URL(url, 'https://testserver').searchParams;
      const offset = Number(params.get('offset') ?? '0');
      if (offset === 0) {
        return jsonResponse({ total: 8, items: pageItems('p1', 5) });
      }
      return jsonResponse({ total: 8, items: pageItems('p2', 3) });
    });
    renderModal();

    expect(await screen.findByText('p1 product 0')).toBeInTheDocument();
    expect(screen.getByText('p1-4')).toBeInTheDocument();
    expect(screen.queryByText('p2-0')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Load more' }));

    expect(await screen.findByText('p2 product 0')).toBeInTheDocument();
    expect(screen.getByText('p2-2')).toBeInTheDocument();
    expect(screen.getByText('p1-0')).toBeInTheDocument();
    expect(screen.getByText('p1-4')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument(),
    );
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/plugins/category/matches'))).toHaveLength(2);
  });

  it('shows the empty state when a rule matches nothing', async () => {
    stubFetch(() => jsonResponse({ total: 0, items: [] }));
    renderModal();
    expect(await screen.findByText('No staged products matched this rule yet.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });
});
