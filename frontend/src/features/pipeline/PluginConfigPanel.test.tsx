import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { PluginConfigPanel } from './PluginConfigPanel';
import type { LocalInstance } from './dndUtils';
import type { PluginInfo } from '../../api/types';

beforeAll(async () => {
  await i18n.loadNamespaces(['pipeline', 'common']);
});

const instance: LocalInstance = {
  id: 1, position: 0, plugin_id: 'upper', name: 'Upper',
  configuration: { suffix: '!' }, enabled: true, clientId: 'upper-0',
};
const plugin: PluginInfo = {
  id: 'upper', name: 'Upper', version: '2.1.0', enabled: true,
  manifest: {
    extension_point: 'pipeline_module',
    config_schema: {
      type: 'object',
      properties: { suffix: { type: 'string', title: 'Suffix' } },
    },
  },
  used_by_feed_sources: 0,
};

describe('PluginConfigPanel', () => {
  it('renders header with instance name, version and remove button', () => {
    render(<PluginConfigPanel instance={instance} plugin={plugin} onChange={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText('Upper')).toBeInTheDocument();
    expect(screen.getByText(/v2\.1\.0/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument();
  });

  it('shows a disabled banner when the instance is disabled', () => {
    render(<PluginConfigPanel instance={{ ...instance, enabled: false }} plugin={plugin} onChange={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByTestId('config-panel')).toBeInTheDocument();
    expect(screen.getByText(/does not run/i)).toBeInTheDocument();
  });

  it('edits configuration through the form', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PluginConfigPanel instance={instance} plugin={plugin} onChange={onChange} onRemove={vi.fn()} />);
    const input = await screen.findByLabelText(/suffix/i);
    await user.clear(input);
    await user.type(input, '?');
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ suffix: '?' }));
  });

  it('renders an empty state when no instance is selected', () => {
    render(<PluginConfigPanel instance={null} plugin={plugin} onChange={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText(/select a plugin/i)).toBeInTheDocument();
  });
});
