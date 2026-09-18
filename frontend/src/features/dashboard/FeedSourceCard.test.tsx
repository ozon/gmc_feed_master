import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { FeedSourceCard } from './FeedSourceCard';
import type { FeedSourceSummary } from '../../api/types';

const feed: FeedSourceSummary = {
  id: 2,
  client_id: 1,
  name: 'Main Feed',
  source_format: 'tsv',
  item_count: 900,
  last_export_at: null,
  last_export_status: null,
  last_run_at: null,
  last_run_status: null,
  quality: { critical: 0, warning: 0, info: 0 },
};

beforeAll(async () => {
  await i18n.loadNamespaces(['dashboard']);
});

describe('FeedSourceCard', () => {
  it('exposes the feed URL as a real href so new-tab/middle-click work', () => {
    render(
      <MemoryRouter>
        <FeedSourceCard clientId={1} feed={feed} />
      </MemoryRouter>,
    );
    const card = screen.getByRole('button', { name: /Main Feed/ });
    expect(card).toHaveAttribute('href', '/clients/1/feeds/2');
  });
});
