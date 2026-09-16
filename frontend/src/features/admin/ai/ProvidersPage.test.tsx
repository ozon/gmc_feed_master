import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
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
    id: 1, name: 'primary', provider_type: 'litellm',
    base_url: '', model: 'openai/gpt-4o-mini',
    input_price_per_mtok: null, output_price_per_mtok: null,
    max_concurrency: 4, timeout_s: 30, enabled: true, tier: 'bulk',
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

describe('ProvidersPage', () => {
  it('renders the provider table with a tier and no default badge', async () => {
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByTestId('ai-providers-table')).toBeInTheDocument());
    expect(screen.getByText('primary')).toBeInTheDocument();
    expect(screen.getByText('openai/gpt-4o-mini')).toBeInTheDocument();
    expect(screen.getByTestId('ai-provider-row-1')).toHaveTextContent('Bulk');
    expect(screen.queryByText('Default')).not.toBeInTheDocument();
  });

  it('shows empty state when no providers exist', async () => {
    stubFetch((url) => {
      if (url === '/admin/ai/providers') return jsonResponse([]);
      return jsonResponse({});
    });
    render(<ProvidersPage />);
    await waitFor(() =>
      expect(screen.getByText('No AI providers configured')).toBeInTheDocument(),
    );
  });

  it('submits a provider with the selected tier', async () => {
    const posts: unknown[] = [];
    stubFetch((url, init) => {
      if (url === '/admin/ai/providers' && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        return jsonResponse({ ...providers[0], id: 2, tier: 'precision' }, 201);
      }
      if (url === '/admin/ai/providers') return jsonResponse(providers);
      return jsonResponse({});
    });
    render(<ProvidersPage />);
    await waitFor(() => expect(screen.getByTestId('ai-providers-table')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('ai-add-provider'));
    fireEvent.change(screen.getByTestId('ai-modal-name'), { target: { value: 'primary2' } });
    fireEvent.change(screen.getByTestId('ai-modal-model'), {
      target: { value: 'openai/gpt-4o-mini' },
    });
    fireEvent.change(screen.getByTestId('ai-modal-tier'), { target: { value: 'precision' } });
    fireEvent.click(screen.getByTestId('ai-modal-save'));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ tier: 'precision' });
  });
});
