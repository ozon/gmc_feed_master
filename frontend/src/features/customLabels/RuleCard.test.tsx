import { useState, type ReactNode } from 'react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Accordion } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { RuleCard } from './RuleCard';
import type { ScopedSlotRule } from './scopeMerge';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const RULE: ScopedSlotRule = {
  id: 'r1', name: 'Mid Funnel', isActive: true, targetSlot: 'custom_label_1',
  matchField: 'id', matchMode: 'values', valueTemplate: '{brand} - Mid',
  fallbackTemplate: '', origin: 'client',
};

function renderCard(over: Partial<Parameters<typeof RuleCard>[0]> = {}) {
  const onSetIds = vi.fn();
  const initialValue = over.value ?? '';
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Harness() {
    const [value, setValue] = useState(initialValue);
    return (
      <QueryClientProvider client={client}>
        <Accordion multiple>
          <RuleCard
            rule={RULE}
            priority={1}
            dirty={false}
            inheritedFrom={null}
            editable={false}
            showLive={false}
            shadowedBy={new Map()}
            feedSourceId={undefined}
            extraFields={[]}
            onExtraFieldsChange={() => {}}
            onSetIds={(next) => {
              onSetIds(next);
              setValue(next);
            }}
            onPatchRule={() => {}}
            {...over}
            value={value}
          />
        </Accordion>
      </QueryClientProvider>
    );
  }
  render(<Harness />);
  return { onSetIds };
}

beforeAll(async () => {
  await i18n.loadNamespaces(['customLabels', 'common']);
});

describe('RuleCard', () => {
  it('collapsed header shows name and priority badge, hides the editor', () => {
    renderCard();
    expect(screen.getByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(
      screen.queryByRole('textbox', { name: /product ids — mid funnel/i }),
    ).not.toBeInTheDocument();
  });

  it('expanding reveals the textarea with the ID counter below it (no overlap)', async () => {
    const { onSetIds } = renderCard();
    await userEvent.click(screen.getByText('Mid Funnel'));
    const textarea = await screen.findByRole('textbox', { name: /product ids — mid funnel/i });
    expect(textarea).toBeInTheDocument();
    // the counter is NOT inside the textarea (the old bottomSection overlap bug)
    expect(textarea.tagName).toBe('TEXTAREA');
    expect(await screen.findByText('0 unique IDs')).toBeInTheDocument();
    expect(screen.queryByText('3 unique IDs')).not.toBeInTheDocument();
    await userEvent.type(textarea, 'a,b, c');
    expect(onSetIds).toHaveBeenLastCalledWith('a,b, c');
    expect(screen.getByText('3 unique IDs')).toBeInTheDocument();
  });

  it('shows a shadowed count badge; the footer overridden list is gone', async () => {
    renderCard({
      value: '2,3,5',
      shadowedBy: new Map([
        ['2', { id: 'r0', name: 'Bleeder', priority: 1 }],
        ['3', { id: 'r0', name: 'Bleeder', priority: 1 }],
      ]),
    });
    expect(screen.getByText('2 overridden')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(screen.queryByText(/overridden IDs/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId('shadow-list')).not.toBeInTheDocument();
  });

  it('all-mode rules show the controlled-by summary instead of a textarea', async () => {
    renderCard({
      rule: { ...RULE, matchMode: 'all', valueTemplate: '{brand} - All' },
      editable: true,
    });
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(await screen.findByText(/every product gets: brand - all/i)).toBeInTheDocument();
    expect(
      await screen.findByRole('button', { name: /switch to value list/i }),
    ).toBeInTheDocument();
  });

  it('inherited rules show the tier badge', () => {
    renderCard({ inheritedFrom: 'client' });
    expect(screen.getByText('Inherited from Client')).toBeInTheDocument();
  });

  it('header shows the compact #N before the rule name', () => {
    renderCard();
    const badge = screen.getByTestId('priority-badge');
    expect(badge).toHaveTextContent('#1');
    // #N precedes the name in DOM order
    expect(badge.compareDocumentPosition(screen.getByText('Mid Funnel')))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('with a feed source renders the split editor and preview rows', async () => {
    stubFetch((url) => {
      if (url.includes('/products/lookup')) {
        return jsonResponse({
          matches: {
            a1: {
              count: 1,
              sample: {
                product_id: 'a1', status: 'active', excluded: false,
                title: 'Alpha', brand: 'Acme', availability: 'in_stock',
              },
            },
          },
        });
      }
      return jsonResponse({});
    });
    renderCard({
      feedSourceId: 5,
      value: 'a1\nzz',
    });
    await userEvent.click(screen.getByText('Mid Funnel'));
    const viewport = await screen.findByTestId('product-preview-viewport');
    expect(viewport).toBeInTheDocument();
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(await screen.findByText('ID not found in feed')).toBeInTheDocument();
  });
});
