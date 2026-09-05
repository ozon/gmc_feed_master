import { beforeAll, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../i18n';
import { render } from '../test/render';
import { ScopeBadge } from './ScopeBadge';

beforeAll(async () => {
  await i18n.loadNamespaces(['common']);
});

it('renders one badge per tier with its color and tooltip label', () => {
  render(
    <div>
      <ScopeBadge tier="global" />
      <ScopeBadge tier="client" />
      <ScopeBadge tier="feed_source" filled />
    </div>,
  );
  expect(screen.getByTestId('scope-badge-global')).toHaveTextContent('Global');
  expect(screen.getByTestId('scope-badge-client')).toHaveTextContent('Client');
  expect(screen.getByTestId('scope-badge-feed_source')).toHaveTextContent('Feed');
});
