import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import RulesUI from '../../../../../plugins/core/rules/frontend/component';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeAll(async () => {
  await i18n.loadNamespaces(['rules', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

function renderUI() {
  stubFetch((url, init) => {
    if (url.startsWith('/plugins/rules/config')) {
      if (init?.method === 'PUT') return jsonResponse({ rules: [] });
      return jsonResponse({
        rules: [
          {
            id: 'r1',
            name: 'Remove HTML',
            isMasterRule: true,
            isActive: true,
            when: { op: 'all' },
            then: [{ op: 'set', field: 'condition', value: 'new' }],
          },
        ],
      });
    }
    if (url.startsWith('/feed-sources/1/fields')) {
      return jsonResponse({ fields: ['title', 'condition'] });
    }
    return jsonResponse({});
  });
  const router = createMemoryRouter(
    [
      {
        path: '/clients/:clientId/feeds/:feedSourceId/plugins/:pluginId',
        element: <RulesUI pluginId="rules" scope={{ feedSourceId: 1 }} />,
      },
    ],
    { initialEntries: ['/clients/1/feeds/1/plugins/rules'] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(
    <Wrapper>
      <RouterProvider router={router} />
    </Wrapper>,
    { wrapper: Wrapper },
  );
}

describe('RulesUI', () => {
  it('loads rules from plugin config and renders the list', async () => {
    renderUI();
    expect(await screen.findByText('Remove HTML')).toBeInTheDocument();
    expect(screen.getByTestId('rules-list')).toBeInTheDocument();
  });

  it('shows master badge on master rules', async () => {
    renderUI();
    expect(await screen.findByText('Remove HTML')).toBeInTheDocument();
    expect(screen.getByTestId('master-badge-r1')).toBeInTheDocument();
  });

  it('selecting a row populates the editor', async () => {
    const user = userEvent.setup();
    renderUI();
    await user.click(await screen.findByText('Remove HTML'));
    expect(await screen.findByTestId('rule-editor')).toBeInTheDocument();
    expect(screen.getByTestId('rule-name-input')).toHaveValue('Remove HTML');
  });

  it('create rule button adds a new rule', async () => {
    const user = userEvent.setup();
    renderUI();
    await user.click(await screen.findByRole('button', { name: /create rule/i }));
    const editor = await screen.findByTestId('rule-editor');
    expect(editor).toBeInTheDocument();
    expect(screen.getByTestId('rule-name-input')).toHaveValue('');
  });

  it('editor renders THEN row with field and operation selects', async () => {
    const user = userEvent.setup();
    renderUI();
    await user.click(await screen.findByText('Remove HTML'));
    expect(await screen.findByTestId('then-row-0')).toBeInTheDocument();
    expect(screen.getByTestId('then-field-0')).toBeInTheDocument();
    expect(screen.getByTestId('then-op-0')).toBeInTheDocument();
    expect(screen.getByTestId('then-value-0')).toHaveValue('new');
  });

  it('add action appends a THEN row', async () => {
    const user = userEvent.setup();
    renderUI();
    await user.click(await screen.findByText('Remove HTML'));
    await user.click(await screen.findByTestId('then-add-0'));
    expect(await screen.findByTestId('then-row-1')).toBeInTheDocument();
  });

  it('new rule without THEN rows can add its first action via the footer button', async () => {
    const user = userEvent.setup();
    renderUI();
    await user.click(await screen.findByRole('button', { name: /create rule/i }));
    expect(screen.queryByTestId('then-row-0')).not.toBeInTheDocument();
    await user.click(await screen.findByTestId('then-add-footer'));
    expect(await screen.findByTestId('then-row-0')).toBeInTheDocument();
  });
});
