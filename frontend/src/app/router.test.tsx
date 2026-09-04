import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { notifications } from '@mantine/notifications';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { render } from '../test/render';
import { stubFetch } from '../test/fetch';
import App from '../App';
import { makeUnauthorizedHandler, RouteErrorBoundary } from './router';
import { queryClient } from '../api/queryClient';
import { queryKeys } from '../api/queryKeys';

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

describe('unauthorized handler', () => {
  function stubRouter(pathname: string, search = '') {
    return {
      state: {
        location: {
          pathname,
          search,
          hash: '',
          state: null,
          key: 'default',
        },
      },
      navigate: vi.fn(),
    };
  }

beforeEach(() => {
  queryClient.clear();
  notifications.clean();
  window.history.replaceState({}, '', '/');
});

  it('removes the session query before navigating to /login', () => {
    queryClient.setQueryData(queryKeys.session, { username: 'operator' });
    const removeSpy = vi.spyOn(queryClient, 'removeQueries');
    const router = stubRouter('/clients/1/feeds/2/products');

    makeUnauthorizedHandler(router)();

    expect(removeSpy).toHaveBeenCalledWith({ queryKey: queryKeys.session });
    expect(removeSpy.mock.invocationCallOrder[0]).toBeLessThan(
      router.navigate.mock.invocationCallOrder[0],
    );
    expect(router.navigate).toHaveBeenCalledWith('/login', {
      state: { from: '/clients/1/feeds/2/products' },
    });
  });

  it('resets the session query even when already on /login', () => {
    queryClient.setQueryData(queryKeys.session, { username: 'operator' });
    const removeSpy = vi.spyOn(queryClient, 'removeQueries');
    const router = stubRouter('/login');

    makeUnauthorizedHandler(router)();

    expect(removeSpy).toHaveBeenCalledWith({ queryKey: queryKeys.session });
    expect(queryClient.getQueryData(queryKeys.session)).toBeUndefined();
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('clears cached session data when a request 401s after authentication', async () => {
    let authed = true;
    stubFetch((url) => {
      if (url === '/auth/me') {
        return jsonResponse(
          authed ? { username: 'operator' } : { detail: 'Not authenticated' },
          authed ? 200 : 401,
        );
      }
      if (url === '/dashboard/summary') {
        return authed
          ? jsonResponse(emptySummary)
          : jsonResponse({ detail: 'Not authenticated' }, 401);
      }
      if (url === '/plugins') return jsonResponse([]);
      return jsonResponse({});
    });

    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(queryClient.getQueryData(queryKeys.session)).toEqual({ username: 'operator' });

    authed = false;
    await queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(queryClient.getQueryData(queryKeys.session)).toBeUndefined();
    expect(window.location.pathname).toBe('/login');
  });
});

describe('RequireSession non-401 session errors', () => {
  it('shows ErrorState with retry instead of redirecting when the session probe returns 503', async () => {
    stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ detail: 'Service unavailable' }, 503);
      return jsonResponse({});
    });

    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong.');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Sign in' })).not.toBeInTheDocument();
    expect(window.location.pathname).toBe('/');
  });

  it('shows ErrorState with retry when the session probe rejects (network offline)', async () => {
    stubFetch((url) => {
      if (url === '/auth/me') throw new TypeError('Failed to fetch');
      return jsonResponse({});
    });

    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong.');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Sign in' })).not.toBeInTheDocument();
  });

  it('still redirects to /login when the session probe returns 401', async () => {
    stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ detail: 'Not authenticated' }, 401);
      return jsonResponse({});
    });

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('refetches the session and renders the guarded content after clicking retry', async () => {
    let sessionAvailable = false;
    stubFetch((url) => {
      if (url === '/auth/me') {
        return sessionAvailable
          ? jsonResponse({ username: 'operator' })
          : jsonResponse({ detail: 'Service unavailable' }, 503);
      }
      if (url === '/dashboard/summary') return jsonResponse(emptySummary);
      if (url === '/plugins') return jsonResponse([]);
      return jsonResponse({});
    });

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong.');
    expect(screen.queryByRole('heading', { name: 'Dashboard' })).not.toBeInTheDocument();

    sessionAvailable = true;
    await user.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('feed-scoped plugin route', () => {
  const schemaPlugin = {
    id: 'example_upper',
    name: 'Example Upper',
    version: '1.0.0',
    enabled: true,
    manifest: {
      config_schema: {
        type: 'object',
        properties: { suffix: { type: 'string', title: 'Suffix' } },
      },
    },
    used_by_feed_sources: 0,
  };

  it('renders PluginPage at /clients/:clientId/feeds/:feedSourceId/plugins/:pluginId', async () => {
    let captured: string | null = null;
    stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(emptySummary);
      if (url === '/plugins') return jsonResponse([schemaPlugin]);
      if (url.startsWith('/plugins/example_upper/config')) {
        captured = url;
        return jsonResponse({ suffix: '!' });
      }
      return jsonResponse({});
    });

    window.history.replaceState({}, '', '/clients/1/feeds/2/plugins/example_upper');
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Example Upper' })).toBeInTheDocument();
    await waitFor(() => expect(captured).toBe('/plugins/example_upper/config?feed_source_id=2'));
  });
});

describe('route error boundary', () => {
  const chunkError = new TypeError('Failed to fetch dynamically imported module');

  function renderRouterWithFailingLazyRoute(errorToThrow: Error) {
    const router = createMemoryRouter(
      [
        {
          path: '/',
          element: <div>Home</div>,
          errorElement: <RouteErrorBoundary />,
        },
        {
          path: '/boom',
          errorElement: <RouteErrorBoundary />,
          lazy: async () => {
            throw errorToThrow;
          },
        },
      ],
      { initialEntries: ['/boom'] },
    );
    render(<RouterProvider router={router} />);
  }

  it('renders a friendly reload state when a lazy chunk fails to load', async () => {
    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      value: { ...window.location, assign: assign },
      writable: true,
    });

    renderRouterWithFailingLazyRoute(chunkError);

    expect(
      await screen.findByText('A new version of the app is available. Reload to continue.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Unexpected Application Error/i)).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: 'Reload' }));
    expect(assign).toHaveBeenCalledWith(window.location.href);
  });

  it('renders the same friendly boundary with reload for a non-chunk render error', async () => {
    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      value: { ...window.location, assign: assign },
      writable: true,
    });

    renderRouterWithFailingLazyRoute(new Error('random render failure'));

    expect(await screen.findByText('Something went wrong.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
    expect(screen.queryByText(/Unexpected Application Error/i)).not.toBeInTheDocument();
  });
});
