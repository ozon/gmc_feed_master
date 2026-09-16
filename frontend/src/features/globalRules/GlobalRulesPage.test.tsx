import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { GlobalRulesPage } from './GlobalRulesPage';

beforeAll(async () => {
  await i18n.loadNamespaces(['globalRules']);
});

describe('GlobalRulesPage', () => {
  it('renders the coming-soon empty state', () => {
    render(<GlobalRulesPage />);
    expect(screen.getByRole('heading', { name: /global rules/i })).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });
});
