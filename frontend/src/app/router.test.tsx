import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { stubFetch } from '../test/fetch';
import App from '../App';
import { queryClient } from '../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const emptySummary = {
  counts: { clients: 0, feed_sources: 0, active_products: 0, failed_last_exports: 0 },
  clients: [],
};

beforeEach(() => {
  queryClient.clear();
  window.history.replaceState({}, '', '/');
});

describe('auth route guard', () => {
  it('redirects unauthenticated users from a protected route to /login', async () => {
    stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ detail: 'Not authenticated' }, 401);
      return jsonResponse({});
    });

    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('renders the dashboard for an authenticated user', async () => {
    stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(emptySummary);
      if (url === '/plugins') return jsonResponse([]);
      return jsonResponse({});
    });

    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
  });

  it('restores the originally requested route after login', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    let authenticated = false;
    stubFetch((url) => {
      if (url === '/auth/me') {
        return authenticated
          ? jsonResponse({ username: 'operator' })
          : jsonResponse({ detail: 'Not authenticated' }, 401);
      }
      if (url === '/auth/login') {
        authenticated = true;
        return jsonResponse({ username: 'operator' });
      }
      if (url === '/dashboard/summary') return jsonResponse(emptySummary);
      if (url === '/plugins') return jsonResponse([]);
      return jsonResponse({});
    });

    const user = userEvent.setup();
    render(<App />);

    await screen.findByRole('heading', { name: 'Sign in' });
    await user.type(screen.getByLabelText(/username/i, { selector: 'input' }), 'operator');
    await user.type(screen.getByLabelText(/password/i, { selector: 'input' }), 'secret');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(window.location.pathname).toBe('/clients/1/feeds/2/products');
    });
  });
});
