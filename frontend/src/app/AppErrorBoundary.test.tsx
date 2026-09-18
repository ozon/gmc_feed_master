import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../test/render';
import { captureException } from '../logging/logger';
import { AppErrorBoundary } from './AppErrorBoundary';

vi.mock('../logging/logger', () => ({ captureException: vi.fn<() => void>() }));

function Boom(): never {
  throw new Error('kaboom');
}

describe('AppErrorBoundary', () => {
  it('renders a fallback when a child throws', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(
      <AppErrorBoundary>
        <Boom />
      </AppErrorBoundary>,
    );
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
  });

  it('reports the render error via captureException', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(
      <AppErrorBoundary>
        <Boom />
      </AppErrorBoundary>,
    );
    expect(vi.mocked(captureException)).toHaveBeenCalledWith(expect.any(Error), {
      scope: 'boundary',
    });
  });
});
