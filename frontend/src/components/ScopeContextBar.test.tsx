import { beforeAll, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../i18n';
import { render } from '../test/render';
import { ScopeContextBar } from './ScopeContextBar';

beforeAll(async () => {
  await i18n.loadNamespaces(['common']);
});

it('shows the viewing tier plus declared config and data tiers', () => {
  render(
    <ScopeContextBar
      current="feed_source"
      configTiers={['global', 'client']}
      dataTiers={['client', 'feed_source']}
      configLabel="Slot rules"
      dataLabel="Bulk values"
    />,
  );
  const bar = screen.getByTestId('scope-context-bar');
  expect(bar).toHaveTextContent('Viewing');
  expect(bar).toHaveTextContent('Slot rules');
  expect(bar).toHaveTextContent('Bulk values');
  expect(screen.getAllByTestId('scope-badge-feed_source').length).toBeGreaterThan(0);
});
