import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { JsonSchemaForm, type JsonSchema } from './JsonSchemaForm';

const schema: JsonSchema = {
  type: 'object',
  properties: {
    suffix: { type: 'string', title: 'Suffix' },
    retries: { type: 'integer', title: 'Retries' },
    enabled: { type: 'boolean', title: 'Enabled' },
    mode: { type: 'string', title: 'Mode', enum: ['strict', 'lenient'] },
    tags: { type: 'array', title: 'Tags', items: { type: 'string' } },
  },
};

describe('JsonSchemaForm', () => {
  it('renders one control per schema type', () => {
    render(
      <JsonSchemaForm schema={schema} value={{}} onChange={() => undefined} />,
    );
    expect(screen.getByLabelText('Suffix')).toBeInTheDocument();
    expect(screen.getByLabelText('Retries')).toBeInTheDocument();
    expect(screen.getByLabelText('Enabled')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Mode' })).toBeInTheDocument();
    expect(screen.getByText('Tags')).toBeInTheDocument();
  });

  it('emits changed values through onChange', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    function Harness() {
      const [value, setValue] = useState<Record<string, unknown>>({});
      return (
        <JsonSchemaForm
          schema={schema}
          value={value}
          onChange={(next) => {
            onChange(next);
            setValue(next as Record<string, unknown>);
          }}
        />
      );
    }
    render(<Harness />);

    await user.type(screen.getByLabelText('Suffix'), '_UP');
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ suffix: '_UP' }));
  });

  it('adds and removes array items', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <JsonSchemaForm schema={schema} value={{ tags: ['a'] }} onChange={onChange} />,
    );

    expect(screen.getByDisplayValue('a')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ tags: ['a', undefined] }));

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ tags: [] }));
  });

  it('shows per-field validation errors by path', () => {
    render(
      <JsonSchemaForm
        schema={schema}
        value={{}}
        onChange={() => undefined}
        errors={{ suffix: 'required' }}
      />,
    );
    expect(screen.getByLabelText('Suffix')).toHaveAttribute('aria-invalid', 'true');
  });
});
