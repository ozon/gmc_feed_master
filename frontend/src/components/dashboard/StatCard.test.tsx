import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../../test/render';
import { StatCard } from './StatCard';

describe('StatCard', () => {
  it('renders label and formatted value', () => {
    render(<StatCard label="Active products" value={12480} />);
    expect(screen.getByText('Active products')).toBeInTheDocument();
    expect(screen.getByText('12,480')).toBeInTheDocument();
  });

  it('applies critical variant color', () => {
    render(<StatCard label="Failed exports" value={3} variant="critical" />);
    expect(screen.getByText('3').closest('[data-variant]')).toHaveAttribute(
      'data-variant',
      'critical',
    );
  });
});
