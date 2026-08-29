import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { queryClient } from '../../api/queryClient';
import { MappingTable } from './MappingTable';
import type { RegistryAttribute, SourceField } from '../../api/types';

const sourceFields: SourceField[] = [
  { name: 'title', kind: 'scalar', sub_fields: [] },
  { name: 'description', kind: 'scalar', sub_fields: [] },
  { name: 'product_id', kind: 'scalar', sub_fields: [] },
  { name: 'price_raw', kind: 'scalar', sub_fields: [] },
  { name: 'installment_data', kind: 'structured', sub_fields: ['months', 'amount'] },
  { name: 'synonym_field', kind: 'scalar', sub_fields: [] },
];

const registryAttributes: RegistryAttribute[] = [
  { name: 'title', kind: 'scalar', required: 'required', sub_fields: [], enum_values: [] },
  { name: 'description', kind: 'scalar', required: 'optional', sub_fields: [], enum_values: [] },
  { name: 'id', kind: 'scalar', required: 'required', sub_fields: [], enum_values: [] },
  { name: 'installment', kind: 'structured', required: 'optional', sub_fields: [
    { name: 'months', type: 'string', required: 'optional' },
    { name: 'amount', type: 'string', required: 'optional' },
  ], enum_values: [] },
];

const mappings: Record<string, { target: string | null; origin: string | null }> = {
  title: { target: 'title', origin: 'auto' },
  synonym_field: { target: 'description', origin: 'synonym' },
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function defaultProps(overrides?: Partial<React.ComponentProps<typeof MappingTable>>) {
  return {
    sourceFields,
    mappings,
    registryAttributes,
    onChange: vi.fn(),
    errors: {},
    ...overrides,
  };
}

beforeEach(async () => {
  queryClient.clear();
  stubFetch(() => jsonResponse({}));
  await i18n.loadNamespaces('setup');
});

describe('MappingTable', () => {
  it('renders all source fields as rows', async () => {
    render(<MappingTable {...defaultProps()} />);
    await waitFor(() => {
      expect(screen.getAllByText('title').length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getAllByText('description').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('product_id')).toBeInTheDocument();
    expect(screen.getByText('price_raw')).toBeInTheDocument();
    expect(screen.getByText('installment_data')).toBeInTheDocument();
    expect(screen.getByText('synonym_field')).toBeInTheDocument();
  });

  it('shows kind badges for each source field', async () => {
    render(<MappingTable {...defaultProps()} />);
    await waitFor(() => {
      expect(screen.getAllByText('scalar').length).toBeGreaterThanOrEqual(1);
    });
    const scalarBadges = screen.getAllByText('scalar');
    expect(scalarBadges.length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText('structured')).toBeInTheDocument();
  });

  it('shows origin badges', async () => {
    render(<MappingTable {...defaultProps()} />);
    await waitFor(() => {
      expect(screen.getAllByText('auto').length).toBeGreaterThanOrEqual(1);
    });
    const autoBadges = screen.getAllByText('auto');
    expect(autoBadges.length).toBeGreaterThanOrEqual(1);
    const suggestionBadges = screen.getAllByText('suggestion');
    expect(suggestionBadges.length).toBeGreaterThanOrEqual(1);
  });

  it('calls onChange when a target is selected', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MappingTable {...defaultProps({ onChange })} />);

    await waitFor(() => {
      expect(screen.getByText('product_id')).toBeInTheDocument();
    });
    const productRow = screen.getByText('product_id').closest('tr')!;
    const select = productRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^id$/ });
    await user.click(option);

    expect(onChange).toHaveBeenCalledWith('product_id', 'id');
  });

  it('does not show positional paths in options', async () => {
    const user = userEvent.setup();
    render(<MappingTable {...defaultProps()} />);

    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const installmentRow = screen.getByText('installment_data').closest('tr')!;
    const select = installmentRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);

    const options = screen.getAllByRole('option');
    const optionTexts = options.map((o) => o.textContent);
    expect(optionTexts).not.toContainEqual(expect.stringContaining('shipping'));
    expect(optionTexts).not.toContainEqual(expect.stringMatching(/\d+\.\d+/));
  });

  it('shows installment.months and installment.amount as options', async () => {
    const user = userEvent.setup();
    render(<MappingTable {...defaultProps()} />);

    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const installmentRow = screen.getByText('installment_data').closest('tr')!;
    const select = installmentRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);

    expect(await screen.findByRole('option', { name: 'installment.months' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'installment.amount' })).toBeInTheDocument();
  });

  it('displays row-level errors', async () => {
    const errors = { title: 'invalid target' };
    render(<MappingTable {...defaultProps({ errors })} />);
    await waitFor(() => {
      expect(screen.getByText('invalid target')).toBeInTheDocument();
    });
  });
});
