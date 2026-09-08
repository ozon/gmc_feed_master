import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { createRef } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { ProductPreviewColumn } from './ProductPreviewColumn';
import { ROW_HEIGHT } from './productPreview';
import type { ProductLookupMatch, ProductLookupSample } from '../../api/types';

function match(count: number, sample: Partial<ProductLookupSample> | null): ProductLookupMatch {
  return {
    count,
    sample: sample === null ? null : {
      product_id: 'p1', status: 'active', excluded: false,
      title: 'T', brand: 'B', availability: 'in_stock', ...sample,
    },
  };
}

function owner(priority: number, name = 'Bleeder', id = 'r0') {
  return { id, name, priority };
}

function renderColumn(over: Partial<Parameters<typeof ProductPreviewColumn>[0]> = {}) {
  const viewportRef = createRef<HTMLDivElement>();
  render(
    <ProductPreviewColumn
      field="id"
      lines={[['a1'], ['zz'], ['a1']]}
      matches={new Map([
        ['a1', match(1, { title: 'Alpha', brand: 'Acme', availability: 'in_stock' })],
        ['zz', match(0, null)],
      ])}
      isFetching={false}
      isError={false}
      extraFields={['price']}
      shadowedBy={null}
      scrollTop={0}
      viewportRef={viewportRef}
      {...over}
    />,
  );
  return { viewportRef };
}

beforeAll(async () => {
  await i18n.loadNamespaces(['customLabels']);
});

describe('ProductPreviewColumn', () => {
  it('renders one row per line in order, aligned by index', () => {
    renderColumn();
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Alpha');
    expect(screen.getByTestId('preview-row-1')).toHaveTextContent('ID not found in feed');
    // duplicated IDs on separate lines render duplicated rows
    expect(screen.getByTestId('preview-row-2')).toHaveTextContent('Alpha');
  });

  it('renders blank rows for blank textarea lines', () => {
    renderColumn({ lines: [['a1'], [], ['zz']] });
    expect(screen.getByTestId('preview-row-1')).toHaveTextContent('—');
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Alpha');
    expect(screen.getByTestId('preview-row-2')).toHaveTextContent('ID not found in feed');
  });

  it('shows the first ID match plus a +N badge for multi-ID lines', () => {
    renderColumn({ lines: [['a1', 'zz', 'q1']] });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Alpha');
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('+2 more');
    // zz is not the line's first ID — its dead-ID badge stays hidden
    expect(screen.getByTestId('preview-row-0')).not.toHaveTextContent('ID not found in feed');
  });

  it('renders an inline overridden-by badge with the claiming rule priority', () => {
    renderColumn({ shadowedBy: new Map([['a1', owner(1)]]) });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Overridden by #1');
    expect(screen.getByTestId('preview-row-1')).not.toHaveTextContent('Overridden by');
  });

  it('renders availability and status badges on the sample', () => {
    renderColumn();
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('in_stock');
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Acme');
  });

  it('shows a count badge when one value matches several products', () => {
    renderColumn({
      lines: [['a1']],
      matches: new Map([['a1', match(7, { title: 'First' })]]),
    });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('7 products');
  });

  it('renders extra fields inline', () => {
    renderColumn({
      lines: [['a1']],
      matches: new Map([['a1', match(1, { price: '9.99 EUR' })]]),
    });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('9.99 EUR');
  });

  it('dims removed and excluded samples with a status badge', () => {
    renderColumn({
      lines: [['r1'], ['e1']],
      matches: new Map([
        ['r1', match(1, { status: 'removed', title: 'Gone' })],
        ['e1', match(1, { excluded: true, title: 'Hidden' })],
      ]),
    });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('removed');
    expect(screen.getByTestId('preview-row-1')).toHaveTextContent('excluded');
  });

  it('uses the no-match label for non-id fields', () => {
    renderColumn({ field: 'brand', lines: [['zz']] });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('No match in feed');
  });

  it('windows rows: renders only the slice for the given scrollTop', () => {
    const lines = Array.from({ length: 1000 }, (_, i) => [`v${i}`]);
    renderColumn({ lines, matches: null, isFetching: false, scrollTop: ROW_HEIGHT * 500 });
    expect(screen.getByTestId('preview-row-495')).toBeInTheDocument();
    expect(screen.queryByTestId('preview-row-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('preview-row-600')).not.toBeInTheDocument();
  });

  it('shows the empty hint inside the always-mounted viewport for an empty list', () => {
    renderColumn({ lines: [] });
    expect(screen.getByTestId('preview-empty')).toBeInTheDocument();
    // the viewport stays mounted when empty so the scroll-sync ref never detaches
    expect(screen.getByTestId('product-preview-viewport')).toBeInTheDocument();
  });

  it('shows the error line when the lookup failed', () => {
    renderColumn({ isError: true, matches: null, lines: [['a1']] });
    expect(screen.getByTestId('preview-error')).toBeInTheDocument();
  });
});
