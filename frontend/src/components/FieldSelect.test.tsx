import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../i18n';
import { render } from '../test/render';
import { buildFieldOptions, type FieldDescriptor } from '../api/fieldOptions';
import { FieldSelect } from './FieldSelect';

const fields: FieldDescriptor[] = [
  { name: 'title', kind: 'scalar', sub_fields: [], max_repeats: 1 },
  { name: 'product_detail', kind: 'repeated_structured',
    sub_fields: [
      { name: 'section_name', kind: 'repeated_scalar' },
      { name: 'attribute_value', kind: 'repeated_scalar' },
    ], max_repeats: 2 },
];

const options = buildFieldOptions(fields);

function setup(overrides?: Partial<React.ComponentProps<typeof FieldSelect>>) {
  const onChange = vi.fn();
  render(
    <FieldSelect
      value=""
      onChange={onChange}
      options={options}
      aria-label="field"
      data-testid="field-select"
      {...overrides}
    />,
  );
  return { onChange };
}

beforeEach(async () => {
  await i18n.loadNamespaces('common');
});

describe('FieldSelect', () => {
  it('renders grouped options when opened', async () => {
    setup();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('field-select'));
    await waitFor(() => {
      // parent option + its group label both carry the attr name
      expect(screen.getAllByText('product_detail').length).toBeGreaterThan(0);
      expect(screen.getByText('#1 · section_name')).toBeInTheDocument();
    });
  });

  it('filters by label', async () => {
    setup();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('field-select'));
    await user.type(screen.getByTestId('field-select'), 'attribute_value');
    await waitFor(() => {
      expect(screen.getByText('#2 · attribute_value')).toBeInTheDocument();
    });
  });

  it('submits a picked option with the full dot path', async () => {
    const { onChange } = setup();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('field-select'));
    const opt = await screen.findByText('#2 · attribute_value');
    await user.click(opt);
    expect(onChange).toHaveBeenCalledWith('product_detail.2.attribute_value');
  });

  it('accepts valid free text beyond max_repeats (directive 4 happy path)', async () => {
    const { onChange } = setup();
    const user = userEvent.setup();
    const input = screen.getByTestId('field-select');
    await user.click(input);
    await user.type(input, 'product_detail.9.section_name');
    await user.keyboard('{Enter}');
    expect(onChange).toHaveBeenCalledWith('product_detail.9.section_name');
  });

  it('rejects 0-based free text with an inline message and does not submit (directive 4)', async () => {
    const { onChange } = setup();
    const user = userEvent.setup();
    const input = screen.getByTestId('field-select');
    await user.click(input);
    await user.type(input, 'product_detail.0.section_name');
    await user.keyboard('{Enter}');
    expect(onChange).not.toHaveBeenCalled();
    await waitFor(() => {
      // error hint below the input and dropdown notice both show the message
      expect(screen.getAllByText(/1-based/).length).toBeGreaterThan(0);
    });
  });

  it('clear emits empty string when clearable', async () => {
    const { onChange } = setup({ value: 'title', clearable: true });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /clear/i }));
    expect(onChange).toHaveBeenCalledWith('');
  });
});
