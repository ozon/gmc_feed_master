import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { ExportVersionDiff } from './ExportVersionDiff';

beforeAll(async () => {
  await i18n.loadNamespaces('export');
  await i18n.loadNamespaces('monitoring');
});

const emptyFindings = {
  a_qc: true,
  b_qc: true,
  totals: { added: 0, fixed: 0, persisted: 0 },
  rules: [],
};

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
  findings: emptyFindings,
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
    const text = screen.getByTestId('findings-delta').textContent ?? '';
    expect(text).toContain('1 → 3');
    expect(text).toContain('0 → 2');
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
        diff={{
          version: 2,
          against: 1,
          added: [],
          removed: [],
          changed: [],
          findings: emptyFindings,
        }}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={null}
        findingsB={null}
      />,
    );
    expect(screen.getByText(/no changes/i)).toBeInTheDocument();
  });

  it('filters the changed-product list when a field badge is clicked', async () => {
    const user = userEvent.setup();
    render(
      <ExportVersionDiff
        diff={diff}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={null}
        findingsB={null}
      />,
    );
    expect(screen.getByText('p1')).toBeInTheDocument();
    expect(screen.getByText('p2')).toBeInTheDocument();

    await user.click(screen.getByText('price · 1'));

    expect(screen.queryByText('p1')).not.toBeInTheDocument();
    expect(screen.getByText('p2')).toBeInTheDocument();
  });

  it('clears the field filter when the compared versions change', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ExportVersionDiff
        diff={diff}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={null}
        findingsB={null}
      />,
    );
    await user.click(screen.getByText('price · 1'));
    expect(screen.queryByText('p1')).not.toBeInTheDocument();

    rerender(
      <ExportVersionDiff
        diff={{ ...diff, version: 4, against: 3 }}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={null}
        findingsB={null}
      />,
    );
    expect(screen.getByText('p1')).toBeInTheDocument();
    expect(screen.getByText('p2')).toBeInTheDocument();
  });

  it('renders the QC findings delta grouped by rule', () => {
    render(
      <ExportVersionDiff
        diff={{
          version: 3,
          against: 2,
          added: [],
          removed: [],
          changed: [],
          findings: {
            a_qc: true,
            b_qc: true,
            totals: { added: 1, fixed: 0, persisted: 1 },
            rules: [
              {
                code: 'enum_values',
                severity: 'critical',
                added: 1,
                fixed: 0,
                persisted: 1,
                sample_added: ['p9'],
                sample_fixed: [],
                sample_persisted: ['p1'],
              },
            ],
          },
        }}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={{ critical: 0, warning: 0, info: 0 }}
        findingsB={{ critical: 0, warning: 0, info: 0 }}
      />,
    );
    const section = screen.getByTestId('findings-diff');
    expect(screen.getByTestId('rule-label-enum_values')).toBeInTheDocument();
    expect(section.textContent).toContain('p9');
  });

  it('shows the not-QC notice when a compared version was not quality-checked', () => {
    render(
      <ExportVersionDiff
        diff={{
          version: 3,
          against: 2,
          added: [],
          removed: [],
          changed: [],
          findings: {
            a_qc: true,
            b_qc: false,
            totals: { added: 0, fixed: 0, persisted: 0 },
            rules: [],
          },
        }}
        isPending={false}
        isError={false}
        onRetry={() => {}}
        findingsA={{ critical: 0, warning: 0, info: 0 }}
        findingsB={{ critical: 0, warning: 0, info: 0 }}
      />,
    );
    expect(screen.getByTestId('findings-diff').textContent).toMatch(/not quality-checked/i);
  });
});
