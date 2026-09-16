import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications } from '@mantine/notifications';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { FindingsTable, type QualityFinding } from './FindingsTable';

const findings: QualityFinding[] = [
  { severity: 'critical', code: 'gtin_mpn', field: 'gtin', message: 'Bad GTIN', product_id: 'p1', details: {} },
  { severity: 'warning', code: 'brand_required', field: 'brand', message: 'brand empty', product_id: 'p2', details: {} },
];

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

beforeEach(() => {
  notifications.clean();
});

describe('FindingsTable', () => {
  it('renders one row per finding', () => {
    render(<FindingsTable findings={findings} />);
    expect(screen.getAllByTestId('finding-row')).toHaveLength(2);
  });

  it('renders localized severity and rule titles', () => {
    render(<FindingsTable findings={findings} />);
    expect(screen.getByText('Critical')).toBeInTheDocument();
    expect(screen.getByText('Identifier problem')).toBeInTheDocument();
    expect(screen.getByText('Missing brand')).toBeInTheDocument();
  });

  it('calls onOpenProduct when a product is clicked', async () => {
    const user = userEvent.setup();
    const onOpenProduct = vi.fn();
    render(<FindingsTable findings={findings} onOpenProduct={onOpenProduct} />);
    await user.click(screen.getByRole('button', { name: 'Open product p1' }));
    expect(onOpenProduct).toHaveBeenCalledWith('p1');
  });
});
