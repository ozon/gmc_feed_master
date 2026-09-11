import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { ProvidersPage } from './ProvidersPage';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const providers = [
  {
    id: 1, name: 'primary', provider_type: 'openai_compatible',
    base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini',
    input_price_per_mtok: null, output_price_per_mtok: null,
    max_concurrency: 4, timeout_s: 30, enabled: true, is_default: true,
  },
];

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

beforeEach(() => {
  stubFetch((url) => {
    if (url === '/admin/ai/providers') return jsonResponse(providers);
    return jsonResponse({});
  });
});

function withQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe('ProvidersPage', () => {
  it('renders the provider table with rows and default badge', async () => {
    render(<ProvidersPage />, { wrapper: withQueryClient() });
    await waitFor(() => expect(screen.getByTestId('ai-providers-table')).toBeInTheDocument());
    expect(screen.getByText('primary')).toBeInTheDocument();
    expect(screen.getByText('gpt-4o-mini')).toBeInTheDocument();
    expect(screen.getByTestId('ai-provider-row-1')).toHaveTextContent('Default');
  });

  it('shows empty state when no providers exist', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/providers') return jsonResponse([]);
      return jsonResponse({});
    });
    render(<ProvidersPage />, { wrapper: withQueryClient() });
    await waitFor(() =>
      expect(screen.getByText('No AI providers configured')).toBeInTheDocument(),
    );
  });
});
