import { useEffect, useRef } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import {
  createBrowserRouter,
  Navigate,
  Outlet,
  RouterProvider,
  useLocation,
} from 'react-router';
import { setUnauthorizedHandler } from '../api/client';
import { queryClient } from '../api/queryClient';
import { useSession } from '../api/hooks';
import { LoadingState } from '../components/StateViews';
import { LoginPage } from '../features/auth/LoginPage';
import { DashboardPage } from '../features/dashboard/DashboardPage';
import { SetupPage } from '../features/setup/SetupPage';
import { ExportPage } from '../features/export/ExportPage';
import { PluginPage } from '../features/plugin/PluginPage';
import { PipelinePage } from '../features/pipeline/PipelinePage';
import { ProductsPage } from '../features/products/ProductsPage';
import { MonitoringRunsPage } from '../features/monitoring/MonitoringRunsPage';
import { MonitoringFindingsPage } from '../features/monitoring/MonitoringFindingsPage';
import { MonitoringDryRunPage } from '../features/monitoring/MonitoringDryRunPage';
import { AppShell } from './AppShell';

export function RequireSession() {
  const location = useLocation();
  const { status } = useSession();

  if (status === 'pending') return <LoadingState />;
  if (status === 'error') {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }
  return <Outlet />;
}

const routes = [
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireSession />,
    children: [
      {
        element: <AppShell />,
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

export function AppRouter() {
  const routerRef = useRef<ReturnType<typeof createBrowserRouter> | null>(null);
  if (routerRef.current === null) {
    routerRef.current = createBrowserRouter(routes);
  }
  const router = routerRef.current;

  useEffect(() => {
    setUnauthorizedHandler(() => {
      const current = router.state.location;
      if (current.pathname !== '/login') {
        void router.navigate('/login', {
          state: { from: current.pathname + current.search },
        });
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [router]);

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
