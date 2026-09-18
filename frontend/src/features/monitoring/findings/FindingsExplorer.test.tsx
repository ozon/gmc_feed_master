import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import type { QualityFinding } from '../../../api/types';
import { FindingsExplorer } from './FindingsExplorer';

const findings: QualityFinding[] = [
  {
    severity: 'critical',
    code: 'gtin_mpn',
    field: 'gtin',
    message: 'Bad GTIN',
    product_id: 'p1',
    details: {},
  },
  {
    severity: 'warning',
    code: 'gtin_mpn',
    field: 'gtin',
    message: 'No GTIN',
    product_id: 'p2',
    details: {},
  },
  {
    severity: 'warning',
    code: 'volume_drop',
    field: null,
    message: 'Catalog dropped',
    product_id: '',
    details: {},
  },
];

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

describe('FindingsExplorer', () => {
  it('groups by rule and shows per-group counts', async () => {
    render(<FindingsExplorer findings={findings} onOpenProduct={() => undefined} />);
    const groups = await screen.findByTestId('findings-groups');
    expect(within(groups).getByText('Identifier problem')).toBeInTheDocument();
    expect(within(groups).getByText('Catalog volume drop')).toBeInTheDocument();
    expect(within(groups).getByText('Critical: 1')).toBeInTheDocument();
  });

  it('groups by attribute and buckets feed-level findings', async () => {
    const user = userEvent.setup();
    render(<FindingsExplorer findings={findings} onOpenProduct={() => undefined} />);
    await user.click(screen.getByRole('radio', { name: 'Attribute' }));
    expect((await screen.findAllByText('Feed level')).length).toBeGreaterThan(0);
  });

  it('filters by free text search', async () => {
    const user = userEvent.setup();
    render(<FindingsExplorer findings={findings} onOpenProduct={() => undefined} />);
    await user.type(screen.getByLabelText('Search'), 'dropped');
    const groups = await screen.findByTestId('findings-groups');
    expect(within(groups).queryByText('Identifier problem')).not.toBeInTheDocument();
    expect(within(groups).getByText('Catalog volume drop')).toBeInTheDocument();
  });

  it('shows the flat sortable table and opens a product', async () => {
    const user = userEvent.setup();
    const onOpenProduct = vi.fn<() => void>();
    render(<FindingsExplorer findings={findings} onOpenProduct={onOpenProduct} />);
    await user.click(screen.getByRole('radio', { name: 'Flat' }));
    const table = await screen.findByTestId('findings-table');
    await user.click(within(table).getByRole('button', { name: 'Open product p1' }));
    expect(onOpenProduct).toHaveBeenCalledWith('p1');
  });

  it('shows an empty state when filters match nothing', async () => {
    const user = userEvent.setup();
    render(<FindingsExplorer findings={findings} onOpenProduct={() => undefined} />);
    await user.type(screen.getByLabelText('Search'), 'zzzz-no-match');
    expect(await screen.findByTestId('findings-empty')).toBeInTheDocument();
  });
});
