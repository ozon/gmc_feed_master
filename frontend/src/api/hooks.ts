import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, changePassword, getCurrentUser, logout } from './client';
import { queryKeys } from './queryKeys';

export type FeedSourceSummary = {
  id: number;
  client_id: number;
  name: string;
  source_format: string;
  item_count: number;
  last_export_at: string | null;
  last_export_status: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
};

export type ClientSummary = {
  id: number;
  name: string;
  status: string;
  feed_sources: FeedSourceSummary[];
};

export type DashboardSummary = {
  counts: {
    clients: number;
    feed_sources: number;
    active_products: number;
    failed_last_exports: number;
  };
  clients: ClientSummary[];
};

export type PluginManifestFrontend = {
  menu_item?: string;
  icon?: string;
  component?: string;
};

export type PluginInfo = {
  id: string;
  name: string;
  version: string;
  enabled: boolean;
  manifest: { frontend?: PluginManifestFrontend; [key: string]: unknown } | null;
  used_by_feed_sources: number;
};

export function useSession() {
  return useQuery({
    queryKey: queryKeys.session,
    queryFn: getCurrentUser,
    retry: false,
    staleTime: Infinity,
  });
}

export function useDashboardSummary() {
  return useQuery({
    queryKey: queryKeys.dashboardSummary,
    queryFn: () => apiGet<DashboardSummary>('/dashboard/summary'),
    refetchInterval: (query) => {
      const data = query.state.data as DashboardSummary | undefined;
      const anyRunning = data?.clients.some((client) =>
        client.feed_sources.some((feed) => feed.last_run_status === 'running'),
      );
      return anyRunning ? 5000 : 30000;
    },
  });
}

export function usePlugins() {
  return useQuery({
    queryKey: queryKeys.plugins,
    queryFn: () => apiGet<PluginInfo[]>('/plugins'),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSuccess: () => {
      void queryClient.resetQueries({ queryKey: queryKeys.session });
    },
  });
}

export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ currentPassword, newPassword }: { currentPassword: string; newPassword: string }) =>
      changePassword(currentPassword, newPassword),
    onSuccess: () => {
      void queryClient.resetQueries({ queryKey: queryKeys.session });
    },
  });
}
