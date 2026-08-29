import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { PipelineInstanceCard } from './PipelineInstanceCard';
import type { LocalInstance } from './dndUtils';
import type { JsonSchema } from '../../components/JsonSchemaForm';

const instance: LocalInstance = {
  clientId: 'abc',
  position: 0,
  plugin_id: 'upper',
  name: 'Upper',
  configuration: {},
};

const schema: JsonSchema = {
  type: 'object',
  properties: { suffix: { type: 'string', title: 'Suffix' } },
};

beforeAll(async () => {
  await i18n.loadNamespaces('pipeline');
});

describe('PipelineInstanceCard', () => {
  it('renders the instance name and renders the schema form when schema is provided', () => {
    render(
      <PipelineInstanceCard
        instance={instance}
        schema={schema}
        onChange={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByTestId(`pipeline-instance-${instance.clientId}`)).toBeInTheDocument();
    expect(screen.getByText('Upper')).toBeInTheDocument();
    expect(screen.getByLabelText(/suffix/i)).toBeInTheDocument();
  });

  it('calls onRemove when the trash icon is clicked', async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn();
    render(
      <PipelineInstanceCard
        instance={instance}
        schema={schema}
        onChange={() => {}}
        onRemove={onRemove}
      />,
    );
    await user.click(screen.getByTestId(`remove-${instance.clientId}`));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it('renders without a form when schema is null', () => {
    render(
      <PipelineInstanceCard
        instance={instance}
        schema={null}
        onChange={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByText('Upper')).toBeInTheDocument();
    expect(screen.queryByLabelText(/suffix/i)).not.toBeInTheDocument();
  });
});