import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { PluginErrorBoundary } from './PluginErrorBoundary';

beforeAll(async () => {
  await i18n.loadNamespaces(['plugins']);
});

function Boom(): never {
  throw new Error('boom');
}

describe('PluginErrorBoundary', () => {
  it('renders children when nothing throws', () => {
    render(
      <PluginErrorBoundary pluginName="Upper">
        <div data-testid="healthy-child" />
      </PluginErrorBoundary>,
    );
    expect(screen.getByTestId('healthy-child')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-error-boundary')).not.toBeInTheDocument();
  });

  it('shows the fallback with the plugin name and error message when the child throws', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <PluginErrorBoundary pluginName="Upper">
        <Boom />
      </PluginErrorBoundary>,
    );
    expect(screen.getByTestId('plugin-error-boundary')).toBeInTheDocument();
    expect(screen.getByText('Upper')).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
    spy.mockRestore();
  });

  it('retry button clears the error and re-renders children', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const user = userEvent.setup();
    let shouldThrow = true;
    function MaybeBoom() {
      if (shouldThrow) throw new Error('boom');
      return <div data-testid="healthy-child" />;
    }
    render(
      <PluginErrorBoundary pluginName="Upper">
        <MaybeBoom />
      </PluginErrorBoundary>,
    );
    shouldThrow = false;
    await user.click(screen.getByTestId('plugin-error-retry'));
    expect(screen.getByTestId('healthy-child')).toBeInTheDocument();
    spy.mockRestore();
  });
});
