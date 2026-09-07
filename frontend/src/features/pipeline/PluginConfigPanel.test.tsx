import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { PluginConfigPanel } from './PluginConfigPanel';
import type { LocalInstance } from './dndUtils';
import type { PluginInfo } from '../../api/types';
import { ProbeComponent, resetProbe, setCrashOnRender } from '../../test/probeComponent';

vi.mock('../plugin/customComponents', async () => {
  const { ProbeComponent: Probe } = await import('../../test/probeComponent');
  return { CUSTOM_COMPONENTS: { probe: Probe } };
});

vi.mock('../plugin/configComponents', async () => {
  const { ProbeComponent: Probe } = await import('../../test/probeComponent');
  return { CONFIG_COMPONENTS: { setup: Probe } };
});

beforeAll(async () => {
  await i18n.loadNamespaces(['pipeline', 'common', 'plugins']);
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

const labelizerInstance: LocalInstance = {
  id: 2, position: 0, plugin_id: 'probe', name: 'Probe',
  configuration: {}, enabled: true, clientId: 'probe-0',
};
const labelizerPlugin: PluginInfo = {
  id: 'probe', name: 'Probe', version: '1.0.0', enabled: true,
  manifest: {
    extension_point: 'pipeline_module',
    frontend: { component: 'component.tsx' },
    config_scope: ['global', 'client'],
    data_scope: ['client', 'feed_source'],
  },
  used_by_feed_sources: 0,
};
const setupInstance: LocalInstance = {
  id: 3, position: 0, plugin_id: 'setup', name: 'Setup Probe',
  configuration: {}, enabled: true, clientId: 'setup-0',
};
const setupPlugin: PluginInfo = {
  id: 'setup', name: 'Setup Probe', version: '1.0.0', enabled: true,
  manifest: {
    extension_point: 'pipeline_module',
    frontend: { component: 'component.tsx' },
    config_scope: ['global', 'client'],
    data_scope: ['client', 'feed_source'],
  },
  used_by_feed_sources: 0,
};
const feedEditablePlugin: PluginInfo = {
  ...setupPlugin,
  manifest: {
    ...setupPlugin.manifest,
    config_scope: ['global', 'client', 'feed_source'],
  },
};

describe('PluginConfigPanel', () => {
  beforeEach(() => resetProbe());

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

  it('renders the plugin-config section with a tier switcher defaulting to Feed scope', () => {
    render(
      <PluginConfigPanel
        instance={setupInstance} plugin={setupPlugin}
        clientId="3" feedSourceId="9"
        onChange={vi.fn()} onRemove={vi.fn()}
      />,
    );
    const probe = screen.getByTestId('probe-component');
    expect(probe).toHaveAttribute('data-plugin-id', 'setup');
    expect(probe).toHaveAttribute('data-scope', JSON.stringify({ feedSourceId: 9 }));
  });

  it('switching the tier re-renders the embedded component with the new scope', async () => {
    const user = userEvent.setup();
    render(
      <PluginConfigPanel
        instance={setupInstance} plugin={setupPlugin}
        clientId="3" feedSourceId="9"
        onChange={vi.fn()} onRemove={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('radio', { name: /client/i }));
    const probe = screen.getByTestId('probe-component');
    expect(probe).toHaveAttribute('data-scope', JSON.stringify({ clientId: 3 }));
  });

  it('shows an actionable read-only alert at Feed tier and switches to Client', async () => {
    const user = userEvent.setup();
    render(
      <PluginConfigPanel
        instance={setupInstance} plugin={setupPlugin}
        clientId="3" feedSourceId="9"
        onChange={vi.fn()} onRemove={vi.fn()}
      />,
    );
    const alert = screen.getByTestId('config-readonly-alert');
    expect(alert).toHaveTextContent(/managed at Client level/i);
    await user.click(screen.getByRole('button', { name: /switch to client tier/i }));
    expect(screen.getByTestId('probe-component'))
      .toHaveAttribute('data-scope', JSON.stringify({ clientId: 3 }));
  });

  it('shows no read-only alert for a plugin editable at feed tier', () => {
    render(
      <PluginConfigPanel
        instance={setupInstance} plugin={feedEditablePlugin}
        clientId="3" feedSourceId="9"
        onChange={vi.fn()} onRemove={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('config-readonly-alert')).not.toBeInTheDocument();
  });

  it('shows no plugin-config section or switcher when the plugin has no custom component', () => {
    render(<PluginConfigPanel instance={instance} plugin={plugin} onChange={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.queryByTestId('config-tier-switcher')).not.toBeInTheDocument();
    expect(screen.queryByTestId('probe-component')).not.toBeInTheDocument();
  });

  it('CUSTOM-only plugin shows the plugin-page hint and link, no instance form', () => {
    render(
      <PluginConfigPanel
        instance={labelizerInstance} plugin={labelizerPlugin}
        clientId="3" feedSourceId="9"
        onChange={vi.fn()} onRemove={vi.fn()}
      />,
      { wrapper: ({ children }) => <MemoryRouter>{children}</MemoryRouter> },
    );
    expect(screen.getByText(/configured on its plugin page/i)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /open plugin page/i });
    expect(link).toHaveAttribute('href', '/clients/3/feeds/9/plugins/probe');
    expect(screen.queryByTestId('config-tier-switcher')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/suffix/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/instance settings/i)).not.toBeInTheDocument();
  });

  it('schema-only plugin still renders the instance settings form', () => {
    render(<PluginConfigPanel instance={instance} plugin={plugin} onChange={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByLabelText(/suffix/i)).toBeInTheDocument();
    expect(screen.queryByText(/configured on its plugin page/i)).not.toBeInTheDocument();
  });

  it('isolates a crashing embedded component; instance settings survive', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    setCrashOnRender(true);
    render(
      <PluginConfigPanel
        instance={setupInstance} plugin={setupPlugin}
        clientId="3" feedSourceId="9"
        onChange={vi.fn()} onRemove={vi.fn()}
      />,
    );
    expect(screen.getByTestId('plugin-error-boundary')).toBeInTheDocument();
    expect(screen.getByText(/no configuration options/i)).toBeInTheDocument();
    spy.mockRestore();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });
});
