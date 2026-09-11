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
  { name: 'title', kind: 'scalar', sub_fields: [], max_repeats: 0 },
  { name: 'description', kind: 'scalar', sub_fields: [], max_repeats: 0 },
  { name: 'product_id', kind: 'scalar', sub_fields: [], max_repeats: 0 },
  { name: 'price_raw', kind: 'scalar', sub_fields: [], max_repeats: 0 },
  { name: 'installment_data', kind: 'structured', sub_fields: ['months', 'amount'], max_repeats: 0 },
  { name: 'synonym_field', kind: 'scalar', sub_fields: [], max_repeats: 0 },
];

const registryAttributes: RegistryAttribute[] = [
  { name: 'title', kind: 'scalar', required: 'required', sub_fields: [], enum_values: [], max_repeats: 1 },
  { name: 'description', kind: 'scalar', required: 'optional', sub_fields: [], enum_values: [], max_repeats: 1 },
  { name: 'id', kind: 'scalar', required: 'required', sub_fields: [], enum_values: [], max_repeats: 1 },
  { name: 'installment', kind: 'structured', required: 'optional', sub_fields: [
    { name: 'months', type: 'string', required: 'optional' },
    { name: 'amount', type: 'string', required: 'optional' },
  ], enum_values: [], max_repeats: 1 },
  { name: 'brand', kind: 'scalar', required: 'optional', sub_fields: [], enum_values: [], max_repeats: 1 },
];

function mappingsFixture() {
  return {
    title: { target: 'title', origin: 'auto' },
    synonym_field: { target: 'description', origin: 'synonym' },
  };
}

const mappings = mappingsFixture();

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
    customFields: [],
    onAddCustom: vi.fn(),
    onRemoveCustom: vi.fn(),
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

    // labels show bare sub names, grouped under the attribute
    expect(await screen.findByRole('option', { name: /^months$/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /^amount$/ })).toBeInTheDocument();
  });

  it('displays row-level errors', async () => {
    const errors = { title: 'invalid target' };
    render(<MappingTable {...defaultProps({ errors })} />);
    await waitFor(() => {
      expect(screen.getByText('invalid target')).toBeInTheDocument();
    });
  });

  it('shows no expand toggle for scalar rows', async () => {
    render(<MappingTable {...defaultProps()} />);
    await waitFor(() => {
      expect(screen.getByText('product_id')).toBeInTheDocument();
    });
    const scalarRow = screen.getByText('product_id').closest('tr')!;
    expect(scalarRow.querySelector('[data-sub-toggle]')).toBeNull();
  });

  it('expands a structured row to show sub-field rows', async () => {
    const user = userEvent.setup();
    render(<MappingTable {...defaultProps()} />);
    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const toggle = document.querySelector('[data-sub-toggle="installment_data"]') as HTMLElement;
    expect(toggle).not.toBeNull();
    await user.click(toggle);
    const monthsRow = (await screen.findByText('months', { selector: 'td p' })).closest('tr')!;
    expect(monthsRow).not.toBeNull();
    expect(screen.getByText('amount', { selector: 'td p' })).toBeInTheDocument();
    expect(monthsRow.querySelectorAll('td').length).toBe(3);
  });

  it('sub-row select calls onChange with dotted key', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MappingTable {...defaultProps({ onChange })} />);
    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const toggle = document.querySelector('[data-sub-toggle="installment_data"]') as HTMLElement;
    await user.click(toggle);
    const subRow = (await screen.findByText('months', { selector: 'td p' })).closest('tr')!;
    const select = subRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^months$/ });
    await user.click(option);
    expect(onChange).toHaveBeenCalledWith('installment_data.months', 'installment.months');
  });

  it('sub-row shows error text for its dotted key', async () => {
    const user = userEvent.setup();
    render(
      <MappingTable {...defaultProps({ errors: { 'installment_data.months': 'unknown sub-field' } })} />,
    );
    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const toggle = document.querySelector('[data-sub-toggle="installment_data"]') as HTMLElement;
    await user.click(toggle);
    expect(await screen.findByText('unknown sub-field')).toBeInTheDocument();
  });

  it('sub-row shows origin badge from dotted-key mapping', async () => {
    const user = userEvent.setup();
    render(
      <MappingTable
        {...defaultProps({
          mappings: {
            ...mappingsFixture(),
            'installment_data.months': { target: 'installment.months', origin: 'auto' },
          },
        })}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const toggle = document.querySelector('[data-sub-toggle="installment_data"]') as HTMLElement;
    await user.click(toggle);
    const subRow = (await screen.findByText('months', { selector: 'td p' })).closest('tr')!;
    expect(subRow.textContent).toContain('auto');
  });

  it('clearing a sub-row select calls onChange with null', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MappingTable
        {...defaultProps({
          mappings: {
            ...mappingsFixture(),
            'installment_data.months': { target: 'installment.months', origin: 'manual' },
          },
          onChange,
        })}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText('installment_data')).toBeInTheDocument();
    });
    const toggle = document.querySelector('[data-sub-toggle="installment_data"]') as HTMLElement;
    await user.click(toggle);
    const subRow = (await screen.findByText('months', { selector: 'td p' })).closest('tr')!;
    const clearButton = subRow.querySelector('.mantine-CloseButton-root');
    expect(clearButton).not.toBeNull();
    await user.click(clearButton!);
    expect(onChange).toHaveBeenCalledWith('installment_data.months', null);
  });

  it('offers indexed target options for repeated attributes', async () => {
    const repeated: RegistryAttribute[] = [
      ...registryAttributes,
      { name: 'product_detail', kind: 'repeated_structured', required: 'optional',
        sub_fields: [
          { name: 'section_name', type: 'string', required: 'optional' },
          { name: 'attribute_name', type: 'string', required: 'optional' },
        ], enum_values: [], max_repeats: 2 },
    ];
    render(<MappingTable {...defaultProps({ registryAttributes: repeated })} />);
    const user = userEvent.setup();
    const select = screen.getAllByRole('combobox')[0];
    await user.click(select);
    await waitFor(() => {
      expect(screen.getByText('#2 · section_name')).toBeInTheDocument();
    });
  });

  it('renders custom field rows with remove controls', async () => {
    const onRemoveCustom = vi.fn();
    render(
      <MappingTable
        {...defaultProps({
          customFields: ['my_custom_field'],
          onAddCustom: vi.fn(),
          onRemoveCustom,
        })}
      />,
    );
    expect(await screen.findByText('my_custom_field')).toBeInTheDocument();
    const removeBtn = screen.getByRole('button', {
      name: /remove custom field/i,
    });
    expect(removeBtn).toBeInTheDocument();
  });

  it('remove control calls onRemoveCustom with the name', async () => {
    const user = userEvent.setup();
    const onRemoveCustom = vi.fn();
    render(
      <MappingTable
        {...defaultProps({
          customFields: ['my_custom_field'],
          onAddCustom: vi.fn(),
          onRemoveCustom,
        })}
      />,
    );
    const removeBtn = await screen.findByRole('button', {
      name: /remove custom field/i,
    });
    await user.click(removeBtn);
    expect(onRemoveCustom).toHaveBeenCalledWith('my_custom_field');
  });

  it('add row: Add disabled until valid name and target chosen', async () => {
    render(
      <MappingTable
        {...defaultProps({ customFields: [], onAddCustom: vi.fn(), onRemoveCustom: vi.fn() })}
      />,
    );
    const addBtn = await screen.findByRole('button', { name: /add custom field/i });
    expect(addBtn).toBeDisabled();
  });

  it('add row: invalid name shows inline error and keeps Add disabled', async () => {
    const user = userEvent.setup();
    render(
      <MappingTable
        {...defaultProps({ customFields: [], onAddCustom: vi.fn(), onRemoveCustom: vi.fn() })}
      />,
    );
    const nameInput = await screen.findByRole('textbox', { name: /field name/i });
    await user.type(nameInput, 'Bad.Name');
    expect(
      await screen.findByText(/names must be lowercase/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add custom field/i })).toBeDisabled();
  });

  it('add row: valid name + target enables Add and calls onAddCustom', async () => {
    const user = userEvent.setup();
    const onAddCustom = vi.fn();
    render(
      <MappingTable
        {...defaultProps({ customFields: [], onAddCustom, onRemoveCustom: vi.fn() })}
      />,
    );
    const nameInput = await screen.findByRole('textbox', { name: /field name/i });
    await user.type(nameInput, 'my_custom_field');

    const addRow = nameInput.closest('tr')!;
    const select = addRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^brand$/ });
    await user.click(option);

    const addBtn = screen.getByRole('button', { name: /add custom field/i });
    await waitFor(() => expect(addBtn).toBeEnabled());
    await user.click(addBtn);
    expect(onAddCustom).toHaveBeenCalledWith('my_custom_field', 'brand');
  });

  it('add row: duplicate name (custom or observed) shows inline error', async () => {
    const user = userEvent.setup();
    render(
      <MappingTable
        {...defaultProps({ customFields: ['taken'], onAddCustom: vi.fn(), onRemoveCustom: vi.fn() })}
      />,
    );
    const nameInput = await screen.findByRole('textbox', { name: /field name/i });
    await user.type(nameInput, 'taken');
    expect(await screen.findByText(/field already exists/i)).toBeInTheDocument();
    // observed name too
    await user.clear(nameInput);
    await user.type(nameInput, 'title');
    expect(await screen.findByText(/field already exists/i)).toBeInTheDocument();
  });

  it('custom row target select calls onChange with the custom name', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MappingTable
        {...defaultProps({
          customFields: ['my_custom_field'],
          mappings: {
            ...mappingsFixture(),
            my_custom_field: { target: 'title', origin: 'manual' },
          },
          onChange,
          onAddCustom: vi.fn(),
          onRemoveCustom: vi.fn(),
        })}
      />,
    );
    const row = (await screen.findByText('my_custom_field')).closest('tr')!;
    const select = row.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^description$/ });
    await user.click(option);
    expect(onChange).toHaveBeenCalledWith('my_custom_field', 'description');
  });

  it('observed/custom shadow: exactly one row with indicator, remove still reachable', async () => {
    const user = userEvent.setup();
    const onRemoveCustom = vi.fn();
    render(
      <MappingTable
        {...defaultProps({
          customFields: ['title'],
          onAddCustom: vi.fn(),
          onRemoveCustom,
        })}
      />,
    );
    await waitFor(() => {
      expect(screen.getAllByText('title')).toHaveLength(1);
    });
    expect(
      screen.getByText(/also declared as custom field/i),
    ).toBeInTheDocument();
    const removeBtn = screen.getByRole('button', { name: /remove custom field/i });
    await user.click(removeBtn);
    expect(onRemoveCustom).toHaveBeenCalledWith('title');
  });

  it('renders the custom section even with zero observed fields', async () => {
    render(
      <MappingTable
        {...defaultProps({
          sourceFields: [],
          customFields: ['solo_custom'],
          onAddCustom: vi.fn(),
          onRemoveCustom: vi.fn(),
        })}
      />,
    );
    expect(await screen.findByText('solo_custom')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add custom field/i })).toBeInTheDocument();
  });
});
