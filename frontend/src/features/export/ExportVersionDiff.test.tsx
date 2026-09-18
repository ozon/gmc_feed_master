import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { ExportVersionDiff } from './ExportVersionDiff';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
});

const diff = {
  version: 3,
  against: 2,
  added: ['p3'],
  removed: ['p4'],
  changed: [
    { product_id: 'p1', fields: [{ field: 'title', old: 'Old', new: 'New' }] },
    {
      product_id: 'p2',
      fields: [
        { field: 'title', old: 'A', new: 'B' },
        { field: 'price', old: null, new: '9 USD' },
      ],
    },
  ],
};

describe('ExportVersionDiff', () => {
  it('renders summary cards and the field breakdown', () => {
    render(
      <ExportVersionDiff
        diff={diff}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={{ critical: 1, warning: 0, info: 0 }}
        findingsB={{ critical: 3, warning: 2, info: 0 }}
      />,
    );
    expect(screen.getByTestId('summary-added')).toHaveTextContent('1');
    expect(screen.getByTestId('summary-removed')).toHaveTextContent('1');
    expect(screen.getByTestId('summary-changed')).toHaveTextContent('2');
    expect(screen.getByTestId('summary-fields')).toHaveTextContent('3');
    expect(screen.getByTestId('field-breakdown').textContent).toContain('title');
    expect(screen.getByTestId('field-breakdown').textContent).toContain('2');
  });

  it('shows the findings delta', () => {
    render(
      <ExportVersionDiff
        diff={diff}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={{ critical: 1, warning: 0, info: 0 }}
        findingsB={{ critical: 3, warning: 2, info: 0 }}
      />,
    );
    expect(screen.getByTestId('findings-delta').textContent).toContain('3');
  });

  it('shows not-QCd when a compared side has no findings', () => {
    render(
      <ExportVersionDiff
        diff={diff}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={null}
        findingsB={{ critical: 3, warning: 2, info: 0 }}
      />,
    );
    expect(screen.getByTestId('findings-delta').textContent).toMatch(/not qc/i);
  });

  it('renders the empty state when no changes', () => {
    render(
      <ExportVersionDiff
        diff={{ version: 2, against: 1, added: [], removed: [], changed: [] }}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={null}
        findingsB={null}
      />,
    );
    expect(screen.getByText(/no changes/i)).toBeInTheDocument();
  });
});
