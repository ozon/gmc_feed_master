import { beforeAll, describe, expect, it } from 'vitest';
import { waitFor } from '@testing-library/react';
import i18n from '../i18n';
import { renderHook } from '../test/render';
import { stubFetch } from '../test/fetch';
import { useModelCatalog, useProviderPresets } from './hooks';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

describe('AI catalog hooks', () => {
  it('loads provider presets', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/provider-presets') {
        return jsonResponse([
          {
            vendor_key: 'openai', label: 'OpenAI', model_prefix: 'openai',
            default_base_url: '', requires_base_url: false,
            api_key_env_hint: 'OPENAI_API_KEY', docs_url: 'https://x', supports_catalog: true,
          },
        ]);
      }
      return jsonResponse({});
    });
    const { result } = renderHook(() => useProviderPresets());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].vendor_key).toBe('openai');
  });

  it('loads the model catalog for a vendor', async () => {
    stubFetch((url) => {
      if (url.startsWith('/admin/ai/model-catalog')) {
        return jsonResponse({
          entries: [
            {
              model_id: 'openai/gpt-4o', vendor: 'openai', display_name: 'gpt-4o',
              context_window: 128000, max_output_tokens: 16384,
              input_price_per_mtok: '2.500000', output_price_per_mtok: '10.000000',
              supports_vision: true, supports_function_calling: true, is_recommended: true,
            },
          ],
          sync: { last_attempt_at: null, last_success_at: null, last_error: null, source: 'bundled' },
        });
      }
      return jsonResponse({});
    });
    const { result } = renderHook(() => useModelCatalog('openai'));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.entries[0].model_id).toBe('openai/gpt-4o');
    expect(result.current.data?.sync.source).toBe('bundled');
  });

  it('does not fetch when vendor is null', () => {
    const fetchMock = stubFetch(() => jsonResponse({}));
    renderHook(() => useModelCatalog(null));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
