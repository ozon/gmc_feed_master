import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { requestBody, stubFetch } from '../../../test/fetch';
import { ProviderWizard } from './ProviderWizard';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

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

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

beforeEach(() => {
  stubFetch((url, init) => {
    if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
    if (url.startsWith('/admin/ai/model-catalog')) return jsonResponse(catalog);
    if (url === '/admin/ai/providers' && init?.method === 'POST') {
      return jsonResponse(
        { ...catalog.entries[0], id: 5, name: 'x', tier: 'bulk', enabled: true },
        201,
      );
    }
    if (url === '/admin/ai/providers/5/test') {
      return jsonResponse({ status: 'ok', latency_ms: 12 });
    }
    return jsonResponse({});
  });
});

describe('ProviderWizard', () => {
  it('creates a provider in 3 steps and auto-tests it', async () => {
    const posts: unknown[] = [];
    stubFetch((url, init) => {
      if (url === '/admin/ai/provider-presets') return jsonResponse(presets);
      if (url.startsWith('/admin/ai/model-catalog')) return jsonResponse(catalog);
      if (url === '/admin/ai/providers' && init?.method === 'POST') {
        posts.push(JSON.parse(requestBody(init)));
        return jsonResponse({ ...catalog.entries[0], id: 5 }, 201);
      }
      if (url === '/admin/ai/providers/5/test') {
        return jsonResponse({ status: 'ok', latency_ms: 12 });
      }
      return jsonResponse({});
    });

    render(<ProviderWizard opened provider={null} presetKey="openai" onClose={() => {}} />);
    fireEvent.click(await screen.findByTestId('ai-wizard-preset-openai'));
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    fireEvent.change(screen.getByTestId('ai-wizard-api-key'), { target: { value: 'sk-test' } });
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    await waitFor(() => expect(screen.getByTestId('ai-wizard-model-select')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('ai-wizard-finish'));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      provider_type: 'litellm',
      model: 'openai/gpt-4o',
      api_key: 'sk-test',
      tier: 'bulk',
    });
    await waitFor(() => expect(screen.getByTestId('ai-wizard-result')).toBeInTheDocument());
  });

  it('requires base_url and a free model for the custom preset', async () => {
    render(<ProviderWizard opened provider={null} presetKey="custom" onClose={() => {}} />);
    fireEvent.click(await screen.findByTestId('ai-wizard-preset-custom'));
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    fireEvent.change(screen.getByTestId('ai-wizard-api-key'), { target: { value: 'k' } });
    expect(screen.getByTestId('ai-wizard-next')).toBeDisabled();
    fireEvent.change(screen.getByTestId('ai-wizard-base-url'), {
      target: { value: 'http://localhost:11434/v1' },
    });
    fireEvent.click(screen.getByTestId('ai-wizard-next'));
    expect(await screen.findByTestId('ai-wizard-model-custom')).toBeInTheDocument();
  });
});
