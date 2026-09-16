import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { RuleLabel } from './RuleLabel';

beforeAll(async () => {
  await i18n.loadNamespaces('monitoring');
});

describe('RuleLabel', () => {
  it('renders the friendly title for a known rule', () => {
    render(<RuleLabel code="gtin_mpn" />);
    expect(screen.getByText('Identifier problem')).toBeInTheDocument();
  });

  it('renders the raw code for an unknown rule', () => {
    render(<RuleLabel code="totally_unknown" />);
    expect(screen.getByText('Unrecognized rule: totally_unknown')).toBeInTheDocument();
  });
});
