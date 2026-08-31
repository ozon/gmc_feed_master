import { lazy, useEffect, useRef } from 'react';
import { Button, Center, Stack, Text } from '@mantine/core';
import { QueryClientProvider } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  createBrowserRouter,
  Navigate,
  Outlet,
  RouterProvider,
  useLocation,
  useRouteError,
} from 'react-router';
import { setUnauthorizedHandler, ApiError } from '../api/client';
import { queryClient } from '../api/queryClient';
import { queryKeys } from '../api/queryKeys';
import { useSession } from '../api/hooks';
import { ErrorState, LoadingState } from '../components/StateViews';
import { LoginPage } from '../features/auth/LoginPage';
import { AppShell } from './AppShell';

const DashboardPage = lazy(() =>
  import('../features/dashboard/DashboardPage').then((m) => ({ default: m.DashboardPage })),
);
const SetupPage = lazy(() =>
  import('../features/setup/SetupPage').then((m) => ({ default: m.SetupPage })),
);
const ProductsPage = lazy(() =>
  import('../features/products/ProductsPage').then((m) => ({ default: m.ProductsPage })),
);
const PipelinePage = lazy(() =>
  import('../features/pipeline/PipelinePage').then((m) => ({ default: m.PipelinePage })),
);
const MonitoringRunsPage = lazy(() =>
  import('../features/monitoring/MonitoringRunsPage').then((m) => ({
    default: m.MonitoringRunsPage,
  })),
);
const MonitoringFindingsPage = lazy(() =>
  import('../features/monitoring/MonitoringFindingsPage').then((m) => ({
    default: m.MonitoringFindingsPage,
  })),
);
const MonitoringDryRunPage = lazy(() =>
  import('../features/monitoring/MonitoringDryRunPage').then((m) => ({
    default: m.MonitoringDryRunPage,
  })),
);
const ExportPage = lazy(() =>
  import('../features/export/ExportPage').then((m) => ({ default: m.ExportPage })),
);
const PluginPage = lazy(() =>
  import('../features/plugin/PluginPage').then((m) => ({ default: m.PluginPage })),
);

export function RequireSession() {
  const location = useLocation();
  const { status, error, refetch } = useSession();

  if (status === 'pending') return <LoadingState />;
  if (status === 'error') {
    if (error instanceof ApiError && error.status === 401) {
      return (
        <Navigate
          to="/login"
          replace
          state={{ from: location.pathname + location.search }}
        />
      );
    }
    return <ErrorState onRetry={() => void refetch()} />;
  }
  return <Outlet />;
}

function isChunkLoadFailure(error: unknown): boolean {
  return (
    error instanceof TypeError &&
    /fetch.*import|import.*module|dynamically imported/i.test(error.message)
  );
}

export function RouteErrorBoundary() {
  const { t } = useTranslation();
  const error = useRouteError();
  const message = isChunkLoadFailure(error)
    ? t('errors.chunkLoadFailed')
    : t('errors.routeError');
  return (
    <Center px="md">
      <Stack align="center" gap="sm" mih="50vh" justify="center">
        <Text c="red" role="alert">
          {message}
        </Text>
        <Button
          variant="light"
          onClick={() => window.location.assign(window.location.href)}
        >
          {t('errors.reload')}
        </Button>
      </Stack>
    </Center>
  );
}

const routes = [
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireSession />,
    children: [
      {
        element: <AppShell />,
        errorElement: <RouteErrorBoundary />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: 'clients/:clientId/feeds/:feedSourceId/setup', element: <SetupPage /> },
          { path: 'clients/:clientId/feeds/:feedSourceId/products', element: <ProductsPage /> },
          { path: 'clients/:clientId/feeds/:feedSourceId/pipeline', element: <PipelinePage /> },
          {
            path: 'clients/:clientId/feeds/:feedSourceId/monitoring',
            element: <Navigate to="runs" replace />,
          },
          {
            path: 'clients/:clientId/feeds/:feedSourceId/monitoring/runs',
            element: <MonitoringRunsPage />,
          },
          {
            path: 'clients/:clientId/feeds/:feedSourceId/monitoring/findings',
            element: <MonitoringFindingsPage />,
          },
          {
            path: 'clients/:clientId/feeds/:feedSourceId/monitoring/dry-run',
            element: <MonitoringDryRunPage />,
          },
          { path: 'clients/:clientId/feeds/:feedSourceId/export', element: <ExportPage /> },
          { path: 'clients/:clientId/plugins/:pluginId', element: <PluginPage /> },
          { path: 'plugins/:pluginId', element: <PluginPage /> },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
];

type UnauthorizedRouter = {
  state: { location: Pick<Location, 'pathname' | 'search'> };
  navigate: (to: string, opts?: { state?: unknown }) => void | Promise<void>;
};

export function makeUnauthorizedHandler(router: UnauthorizedRouter): () => void {
  return () => {
    queryClient.removeQueries({ queryKey: queryKeys.session });
    const current = router.state.location;
    if (current.pathname !== '/login') {
      void router.navigate('/login', {
        state: { from: current.pathname + current.search },
      });
    }
  };
}

export function AppRouter() {
  const routerRef = useRef<ReturnType<typeof createBrowserRouter> | null>(null);
  if (routerRef.current === null) {
    routerRef.current = createBrowserRouter(routes);
  }
  const router = routerRef.current;

  useEffect(() => {
    setUnauthorizedHandler(makeUnauthorizedHandler(router));
    return () => setUnauthorizedHandler(null);
  }, [router]);

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
