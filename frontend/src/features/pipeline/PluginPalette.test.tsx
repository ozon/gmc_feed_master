import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { PluginPalette } from './PluginPalette';
import type { PluginInfo } from '../../api/types';

const palettePlugin: PluginInfo = {
  id: 'upper',
  name: 'Upper',
  version: '1.0.0',
  enabled: true,
  manifest: { extension_point: 'pipeline_module', frontend: { icon: 'letter-a' } },
  used_by_feed_sources: 0,
};

beforeAll(async () => {
  await i18n.loadNamespaces('pipeline');
});

beforeEach(() => {});

function withQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe('PluginPalette', () => {
  it('renders palette heading and a card for each plugin', () => {
    render(<PluginPalette plugins={[palettePlugin]} />, { wrapper: withQueryClient() });
    expect(screen.getByTestId('plugin-palette')).toBeInTheDocument();
    expect(screen.getByTestId(`palette-card-${palettePlugin.id}`)).toBeInTheDocument();
    expect(screen.getByText(palettePlugin.name)).toBeInTheDocument();
  });

  it('shows an empty message when no plugins are available', () => {
    render(<PluginPalette plugins={[]} />, { wrapper: withQueryClient() });
    expect(screen.getByTestId('plugin-palette')).toBeInTheDocument();
    expect(screen.getByText(/no pipeline modules/i)).toBeInTheDocument();
  });
});