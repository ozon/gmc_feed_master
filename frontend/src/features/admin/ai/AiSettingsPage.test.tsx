import { beforeAll, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { AiSettingsPage } from './AiSettingsPage';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const settings = {
  ai_cache_type: 'local',
  ai_cache_namespace: 'gmc-ai',
  ai_cache_ttl_taxonomy_s: 2592000,
  ai_cache_ttl_content_s: 604800,
  ai_router_timeout_s: 30,
  ai_router_num_retries: 2,
  ai_router_allowed_fails: 3,
  ai_router_cooldown_s: 30,
  ai_instructor_max_retries: 2,
  ai_usage_retention_days: 90,
  redis_from_env: false,
  effective_cache_backend: 'local',
};
const status = {
  effective_backend: 'local',
  redis_from_env: false,
  healthy: true,
  namespace: 'gmc-ai',
  entries: 3,
};
const stats = {
  calls: 10,
  cache_hits: 4,
  hit_ratio: 0.4,
  prompt_tokens: 100,
  completion_tokens: 20,
  cost_usd: '0.01',
  saved_prompt_tokens: 40,
  saved_completion_tokens: 8,
  cost_saved_usd: '0.004',
};

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

describe('AiSettingsPage', () => {
  it('renders settings, cache status and stats', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/settings') return jsonResponse(settings);
      if (url === '/admin/ai/cache') return jsonResponse(status);
      if (url === '/admin/ai/cache/stats') return jsonResponse(stats);
      return jsonResponse({});
    });
    render(<AiSettingsPage />);
    await waitFor(() => expect(screen.getByTestId('ai-settings-form')).toBeInTheDocument());
    expect(screen.getByTestId('ai-cache-backend')).toHaveTextContent('local');
    expect(screen.getByTestId('ai-cache-entries')).toHaveTextContent('3');
    expect(screen.getByTestId('ai-cache-hit-ratio')).toHaveTextContent('40');
  });

  it('saves settings via PUT', async () => {
    const puts: unknown[] = [];
    stubFetch((url, init) => {
      if (url === '/admin/ai/settings' && init?.method === 'PUT') {
        puts.push(JSON.parse(String(init.body)));
        return jsonResponse({ ...settings, ai_router_num_retries: 7 });
      }
      if (url === '/admin/ai/settings') return jsonResponse(settings);
      if (url === '/admin/ai/cache') return jsonResponse(status);
      if (url === '/admin/ai/cache/stats') return jsonResponse(stats);
      return jsonResponse({});
    });
    render(<AiSettingsPage />);
    await waitFor(() => expect(screen.getByTestId('ai-settings-form')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('ai-num-retries'), { target: { value: '7' } });
    fireEvent.click(screen.getByTestId('ai-settings-save'));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toMatchObject({ ai_router_num_retries: 7 });
  });

  it('shows the redis override and disables the backend selector', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/settings') {
        return jsonResponse({
          ...settings,
          redis_from_env: true,
          effective_cache_backend: 'redis',
        });
      }
      if (url === '/admin/ai/cache') {
        return jsonResponse({ ...status, redis_from_env: true, effective_backend: 'redis' });
      }
      if (url === '/admin/ai/cache/stats') return jsonResponse(stats);
      return jsonResponse({});
    });
    render(<AiSettingsPage />);
    await waitFor(() => expect(screen.getByTestId('ai-settings-form')).toBeInTheDocument());
    expect(screen.getByTestId('ai-cache-backend')).toHaveTextContent('redis');
    expect(screen.getByTestId('ai-cache-backend-select')).toBeDisabled();
  });
});
