import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { requestBody, stubFetch } from '../../../test/fetch';
import { ProvidersPage } from './ProvidersPage';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const providers = [
  {
    id: 1,
    name: 'primary',
    provider_type: 'litellm',
    base_url: '',
    model: 'openai/gpt-4o-mini',
    input_price_per_mtok: null,
    output_price_per_mtok: null,
    max_concurrency: 4,
    timeout_s: 30,
    enabled: true,
    tier: 'bulk',
  },
];

const presets = [
  {
    vendor_key: 'openai',
    label: 'OpenAI',
    model_prefix: 'openai',
    default_base_url: '',
    requires_base_url: false,
    api_key_env_hint: 'OPENAI_API_KEY',
    docs_url: 'https://docs',
    supports_catalog: true,
  },
];

const catalog = {
  entries: [
    {
      model_id: 'openai/gpt-4o',
      vendor: 'openai',
      display_name: 'gpt-4o',
      context_window: 128000,
      max_output_tokens: 16384,
      input_price_per_mtok: '2.500000',
      output_price_per_mtok: '10.000000',
      supports_vision: true,
      supports_function_calling: true,
      is_recommended: true,
    },
  ],
  sync: { last_attempt_at: null, last_success_at: null, last_error: null, source: 'bundled' },
};

const legacyProviders = [
  {
    id: 9,
    name: 'legacy',
    provider_type: 'openai_compatible',
    base_url: 'http://localhost:11434/v1',
    model: 'llama3',
    input_price_per_mtok: null,
    output_price_per_mtok: null,
    max_concurrency: 4,
    timeout_s: 30,
    enabled: true,
    tier: 'bulk',
  },
];

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

beforeEach(() => {
  stubFetch((url) => {
    if (url === '/admin/ai/providers') return jsonResponse(providers);
    if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
    if (url.startsWith('/admin/ai/model-catalog')) return jsonResponse(catalog);
    return jsonResponse({});
  });
});

describe('ProvidersPage', () => {
  it('renders the provider table', async () => {
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByTestId('ai-providers-table')).toBeInTheDocument());
    expect(screen.getByText('primary')).toBeInTheDocument();
    expect(screen.getByTestId('ai-provider-row-1')).toHaveTextContent('Bulk');
  });

  it('shows empty state when no providers exist', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/providers') return jsonResponse([]);
      if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
      return jsonResponse({});
    });
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByText('No AI providers configured')).toBeInTheDocument());
  });

  it('creates a provider through the wizard', async () => {
    const posts: unknown[] = [];
    stubFetch((url, init) => {
      if (url === '/admin/ai/providers' && init?.method === 'POST') {
        posts.push(JSON.parse(requestBody(init)));
        return jsonResponse({ ...providers[0], id: 2, model: 'openai/gpt-4o' }, 201);
      }
      if (url === '/admin/ai/providers/2/test')
        return jsonResponse({ status: 'ok', latency_ms: 9 });
      if (url === '/admin/ai/providers') return jsonResponse(providers);
      if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
      if (url.startsWith('/admin/ai/model-catalog')) return jsonResponse(catalog);
      return jsonResponse({});
    });
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByTestId('ai-providers-table')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('ai-add-provider'));
    fireEvent.click(await screen.findByTestId('ai-wizard-preset-openai'));
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    fireEvent.change(screen.getByTestId('ai-wizard-api-key'), { target: { value: 'sk-test' } });
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    await waitFor(() => expect(screen.getByTestId('ai-wizard-model-select')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('ai-wizard-finish'));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ model: 'openai/gpt-4o', provider_type: 'litellm' });
  });

  it('marks legacy providers and opens the wizard with the custom preset', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/providers') return jsonResponse(legacyProviders);
      if (url === '/admin/ai/provider-presets')
        return jsonResponse([
          ...presets,
          {
            vendor_key: 'custom',
            label: 'OpenAI-kompatibel (custom)',
            model_prefix: 'openai',
            default_base_url: '',
            requires_base_url: true,
            api_key_env_hint: '',
            docs_url: '',
            supports_catalog: false,
          },
        ]);
      if (url.startsWith('/admin/ai/model-catalog')) return jsonResponse(catalog);
      return jsonResponse({});
    });
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByTestId('ai-legacy-badge-9')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('ai-edit-provider-9'));
    await waitFor(() => expect(screen.getByTestId('ai-wizard')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    expect(await screen.findByTestId('ai-wizard-model-custom')).toBeInTheDocument();
  });

  it('renders the catalog status and triggers a refresh', async () => {
    const refreshes: string[] = [];
    stubFetch((url, init) => {
      if (url === '/admin/ai/providers') return jsonResponse(providers);
      if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
      if (url === '/admin/ai/model-catalog/refresh' && init?.method === 'POST') {
        refreshes.push(url);
        return jsonResponse({
          last_attempt_at: null,
          last_success_at: null,
          last_error: null,
          source: 'github',
        });
      }
      if (url.startsWith('/admin/ai/model-catalog')) {
        return jsonResponse({
          entries: [],
          sync: {
            last_attempt_at: null,
            last_success_at: null,
            last_error: 'boom',
            source: 'bundled',
          },
        });
      }
      return jsonResponse({});
    });
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByTestId('ai-catalog-status')).toBeInTheDocument());
    expect(screen.getByTestId('ai-catalog-status')).toHaveTextContent('Catalog refresh failed');
    fireEvent.click(screen.getByTestId('ai-catalog-refresh'));
    await waitFor(() => expect(refreshes).toHaveLength(1));
  });
});
