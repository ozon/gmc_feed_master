import { beforeAll, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../i18n';
import { MemoryRouter } from 'react-router';
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

it('renders non-current tiers as links and the current tier as a static badge', () => {
  render(
    <MemoryRouter>
      <ScopeContextBar
        current="feed_source"
        configTiers={['global', 'client']}
        dataTiers={['client', 'feed_source']}
        configLabel="Slot rules"
        dataLabel="Bulk values"
        hrefs={{
          global: '/plugins/custom_labels',
          client: '/clients/1/plugins/custom_labels',
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByTestId('scope-link-global')).toHaveAttribute(
    'href', '/plugins/custom_labels',
  );
  // client appears in both the config and data tier groups at the feed page
  const clientLinks = screen.getAllByTestId('scope-link-client');
  expect(clientLinks.length).toBe(2);
  for (const link of clientLinks) {
    expect(link).toHaveAttribute('href', '/clients/1/plugins/custom_labels');
  }
  expect(screen.queryByTestId('scope-link-feed_source')).not.toBeInTheDocument();
  expect(screen.getAllByTestId('scope-badge-feed_source').length).toBeGreaterThan(0);
});
