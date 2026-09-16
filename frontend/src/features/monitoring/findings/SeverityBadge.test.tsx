import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { SeverityBadge } from './SeverityBadge';

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

describe('SeverityBadge', () => {
  it('renders the localized severity', () => {
    render(<SeverityBadge severity="critical" />);
    expect(screen.getByText('Critical')).toBeInTheDocument();
  });

  it('falls back to the raw value for unknown severities', () => {
    render(<SeverityBadge severity="weird" />);
    expect(screen.getByText('weird')).toBeInTheDocument();
  });
});
