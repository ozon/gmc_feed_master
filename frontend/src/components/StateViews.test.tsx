import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { EmptyState, ErrorState, LoadingState } from './StateViews';

describe('StateViews', () => {
  it('renders a labelled loader', () => {
    render(<LoadingState />);
    expect(screen.getByRole('progressbar', { name: 'Loading…' })).toBeInTheDocument();
  });

  it('renders the default empty message', () => {
    render(<EmptyState />);
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument();
  });

  it('renders an error with a retry callback', async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorState onRetry={onRetry} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong.');
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
