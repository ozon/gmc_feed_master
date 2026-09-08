import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { CONFIG_COMPONENTS } from './configComponents';
import { CUSTOM_COMPONENTS } from './customComponents';

beforeAll(async () => {
  await i18n.loadNamespaces(['common', 'customLabels', 'plugins']);
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  stubFetch((url) => jsonResponse({}));
});

function renderSurface(
  element: ReactNode,
  scope: { clientId?: number; feedSourceId?: number },
) {
  const url = scope.feedSourceId
    ? '/clients/1/feeds/1/plugins/custom_labels'
    : '/clients/1/plugins/custom_labels';
  const router = createMemoryRouter(
    [
      { path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId', element },
      { path: '/clients/:clientId/plugins/:pluginId', element },
      { path: '/plugins/:pluginId', element },
    ],
    { initialEntries: [url] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('plugin surface registries', () => {
  it('maps custom_labels page to the ids-only surface and setup to the rules-only surface', () => {
    expect(CONFIG_COMPONENTS.custom_labels).toBeDefined();
    expect(CUSTOM_COMPONENTS.custom_labels).toBeDefined();
    expect(CONFIG_COMPONENTS.custom_labels).not.toBe(CUSTOM_COMPONENTS.custom_labels);
  });

  it('LabelizerPage renders the bulk grid without rules UI', async () => {
    const Page = CUSTOM_COMPONENTS.custom_labels;
    renderSurface(<Page pluginId="custom_labels" scope={{ feedSourceId: 1 }} />, { feedSourceId: 1 });
    expect(await screen.findByTestId('slot-selector')).toBeInTheDocument();
    expect(screen.queryByTestId('rules-readonly-hint')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /slot rules/i })).not.toBeInTheDocument();
  });

  it('LabelizerSetup renders rules UI without the bulk grid', async () => {
    const Setup = CONFIG_COMPONENTS.custom_labels;
    renderSurface(<Setup pluginId="custom_labels" scope={{ clientId: 1 }} />, { clientId: 1 });
    // rules surface renders (Add rule button visible with zero rules); no slot grid, no tabs
    expect(await screen.findByRole('button', { name: /add rule/i })).toBeInTheDocument();
    expect(screen.queryByTestId('slot-grid')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /slot rules/i })).not.toBeInTheDocument();
  });
});
