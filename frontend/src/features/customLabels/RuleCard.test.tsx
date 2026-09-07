import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Accordion } from '@mantine/core';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { RuleCard } from './RuleCard';
import type { ScopedSlotRule } from './scopeMerge';

const RULE: ScopedSlotRule = {
  id: 'r1', name: 'Mid Funnel', isActive: true, targetSlot: 'custom_label_1',
  matchField: 'id', matchMode: 'values', valueTemplate: '{brand} - Mid',
  fallbackTemplate: '', origin: 'client',
};

function renderCard(over: Partial<Parameters<typeof RuleCard>[0]> = {}) {
  const onSetIds = vi.fn();
  render(
    <Accordion multiple>
      <RuleCard
        rule={RULE}
        priority={1}
        value=""
        dirty={false}
        inheritedFrom={null}
        editable={false}
        showLive={false}
        shadowedBy={new Map()}
        onSetIds={onSetIds}
        onPatchRule={() => {}}
        {...over}
      />
    </Accordion>,
  );
  return { onSetIds };
}

beforeAll(async () => {
  await i18n.loadNamespaces(['customLabels', 'common']);
});

describe('RuleCard', () => {
  it('collapsed header shows name and priority badge, hides the editor', () => {
    renderCard();
    expect(screen.getByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.getByText('#1 Priority')).toBeInTheDocument();
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

  it('shows a shadowed count badge and lists shadowed values with attribution tooltip', async () => {
    renderCard({
      value: '2,3,5',
      shadowedBy: new Map([['2', 'Bleeder'], ['3', 'Bleeder']]),
    });
    expect(screen.getByText('2 overridden')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(await screen.findByText(/overridden IDs/i)).toBeInTheDocument();
    const value2 = await screen.findByText('2', { exact: true });
    expect(value2).toHaveStyle({ textDecoration: 'line-through' });
    expect(screen.getByText('3', { exact: true })).toHaveStyle({
      textDecoration: 'line-through',
    });
    // unshadowed values are NOT struck through (they live in the textarea only)
    expect(screen.queryByText('5', { exact: true })).not.toBeInTheDocument();
    await userEvent.hover(value2);
    expect(await waitFor(() =>
      screen.getByText(/already matched by higher priority rule: bleeder/i),
      { timeout: 3000 })).toBeInTheDocument();
  });

  it('all-mode rules show the controlled-by summary instead of a textarea', async () => {
    renderCard({
      rule: { ...RULE, matchMode: 'all', valueTemplate: '{brand} - All' },
      editable: true,
    });
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(await screen.findByText(/every product gets: brand - all/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /switch to value list/i }),
    ).toBeInTheDocument();
  });

  it('inherited rules show the tier badge', () => {
    renderCard({ inheritedFrom: 'client' });
    expect(screen.getByText('Inherited from Client')).toBeInTheDocument();
  });
});
