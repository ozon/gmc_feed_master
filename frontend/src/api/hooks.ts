import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDelete, apiGet, apiPatch, apiPost, apiPut, changePassword, getCurrentUser, logout } from './client';
import { queryKeys } from './queryKeys';
import type {
  ClientRow,
  ClientSummary,
  DashboardSummary,
  DiffOut,
  ExportVersionOut,
  FeedSourceFieldsResponse,
  FeedSourceRow,
  FeedSourceSummary,
  FieldMappingDoc,
  IngestionRunRow,
  PipelineDoc,
  PluginConfigResponse,
  PluginInfo,
  ProductDetail,
  ProductsPageResponse,
  QualityFindingsResponse,
  RegistryAttribute,
} from './types';

export type {
  ClientRow,
  ClientSummary,
  DashboardSummary,
  DiffOut,
  ExportVersionOut,
  FeedSourceFieldsResponse,
  FeedSourceRow,
  FeedSourceSummary,
  FieldMappingDoc,
  IngestionRunRow,
  PipelineDoc,
  PluginConfigResponse,
  PluginInfo,
  ProductDetail,
  ProductsPageResponse,
  QualityFindingsResponse,
  RegistryAttribute,
} from './types';

type ProductListParams = {
  page: number;
  page_size: number;
  q?: string;
  status?: string;
  sort?: string;
  stage?: 'raw' | 'processed';
};

function buildProductsQuery(params: ProductListParams): string {
  const search = new URLSearchParams();
  search.set('page', String(params.page));
  search.set('page_size', String(params.page_size));
  if (params.q) search.set('q', params.q);
  if (params.status && params.status !== 'all') search.set('status', params.status);
  if (params.sort) search.set('sort', params.sort);
  if (params.stage && params.stage !== 'raw') search.set('stage', params.stage);
  return search.toString();
}

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
      const anyRunning = data?.clients?.some((client) =>
        client.feed_sources?.some((feed) => feed.last_run_status === 'running'),
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

export function useClients() {
  return useQuery({
    queryKey: queryKeys.clients,
    queryFn: () => apiGet<ClientRow[]>('/clients'),
  });
}

export function useFeedSource(id: number | string) {
  return useQuery({
    queryKey: queryKeys.feedSource(id).detail,
    queryFn: () => apiGet<FeedSourceRow>(`/feed-sources/${id}`),
  });
}

export function useFeedSourceFields(feedSourceId: number | string) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).fields,
    queryFn: () =>
      apiGet<FeedSourceFieldsResponse>(`/feed-sources/${feedSourceId}/fields`),
    enabled: Boolean(feedSourceId),
  });
}

export function useFieldMapping(feedSourceId: number | string) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).mapping,
    queryFn: () => apiGet<FieldMappingDoc>(`/feed-sources/${feedSourceId}/field-mapping`),
  });
}

export function useRegistryAttributes() {
  return useQuery({
    queryKey: queryKeys.registryAttributes,
    queryFn: () => apiGet<RegistryAttribute[]>('/registry/attributes'),
    staleTime: Infinity,
  });
}

export function useProductList(feedSourceId: number | string, params: ProductListParams) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).products(params),
    queryFn: () =>
      apiGet<ProductsPageResponse>(
        `/feed-sources/${feedSourceId}/products?${buildProductsQuery(params)}`,
      ),
    placeholderData: keepPreviousData,
  });
}

export function useProductDetail(feedSourceId: number | string, productId: string | null) {
  return useQuery({
    queryKey: queryKeys.productDetail(feedSourceId, productId ?? ''),
    queryFn: () =>
      apiGet<ProductDetail>(
        `/feed-sources/${feedSourceId}/products/${encodeURIComponent(productId!)}`,
      ),
    enabled: productId !== null,
  });
}

export function useIngestionRuns(feedSourceId: number | string, active: boolean) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).runs,
    queryFn: () => apiGet<IngestionRunRow[]>(`/feed-sources/${feedSourceId}/ingestion-runs?limit=50`),
    refetchInterval: active ? 5000 : false,
  });
}

export function useQualityFindings(feedSourceId: number | string, active: boolean) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).findings,
    queryFn: () =>
      apiGet<QualityFindingsResponse>(`/feed-sources/${feedSourceId}/quality-findings`),
    refetchInterval: active ? 5000 : false,
  });
}

export function useRunDryRun(feedSourceId: number | string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ limit }: { limit: number }) =>
      apiPost<unknown>(`/feed-sources/${feedSourceId}/dry-run`, { limit }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.feedSource(feedSourceId).runs });
      void queryClient.invalidateQueries({ queryKey: queryKeys.feedSource(feedSourceId).findings });
    },
  });
}

export function useTriggerRun(feedSourceId: number | string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<{ run_id: number }>(`/feed-sources/${feedSourceId}/run`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.feedSource(feedSourceId).runs });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSettled: () => {
      void queryClient.removeQueries({ queryKey: queryKeys.session });
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

export function useCreateClient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; status?: string }) => apiPost<ClientRow>('/clients', body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clients });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
    },
  });
}

export function useUpdateClient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; name?: string; status?: string }) =>
      apiPut<ClientRow>(`/clients/${id}`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clients });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
    },
  });
}

export function useDeleteClient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/clients/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clients });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
    },
  });
}

export function useCreateFeedSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clientId, ...body }: {
      clientId: number | string;
      name: string;
      source_format: string;
      cron_expression?: string | null;
      target_country?: string | null;
      target_language?: string | null;
      currency?: string | null;
      source_url?: string | null;
    }) => apiPost<FeedSourceRow>(`/clients/${clientId}/feed-sources`, body),
    onSuccess: (feedSource) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clients });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(feedSource.id).detail,
      });
    },
  });
}

export function useUpdateFeedSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: {
      id: number | string;
      name?: string;
      source_format?: string;
      cron_expression?: string | null;
      target_country?: string | null;
      target_language?: string | null;
      currency?: string | null;
      source_url?: string | null;
      history_retention_count?: number;
      volume_drop_threshold_pct?: number;
      configuration?: Record<string, unknown>;
    }) => apiPut<FeedSourceRow>(`/feed-sources/${id}`, body),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(variables.id).detail,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
    },
  });
}

export function useDeleteFeedSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number | string) => apiDelete(`/feed-sources/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clients });
    },
  });
}

export function useRotateExportToken() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number | string) =>
      apiPost<{ export_token: string; export_url: string }>(
        `/feed-sources/${id}/export-token/rotate`,
      ),
    onSuccess: (_data, id) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(id).detail,
      });
    },
  });
}

export function useSaveFieldMapping() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, mappings }: { id: number | string; mappings: Record<string, { target: string }> }) =>
      apiPut<FieldMappingDoc>(`/feed-sources/${id}/field-mapping`, { mappings }),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(variables.id).mapping,
      });
    },
  });
}

export function useAutoMap() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number | string) =>
      apiPost<FieldMappingDoc>(`/feed-sources/${id}/field-mapping/auto`),
    onSuccess: (_data, id) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(id).mapping,
      });
    },
  });
}

export function useUpdatePluginEnabled() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiPut<PluginInfo>(`/plugins/${id}/enabled`, { enabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.plugins });
    },
  });
}

export type PluginScope = { clientId?: number; feedSourceId?: number };

function buildScopeQuery(scope?: PluginScope): string {
  if (!scope) return '';
  const params = new URLSearchParams();
  if (scope.clientId !== undefined) params.set('client_id', String(scope.clientId));
  if (scope.feedSourceId !== undefined) params.set('feed_source_id', String(scope.feedSourceId));
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export function usePluginConfig(pluginId: string, scope?: PluginScope, enabled = true) {
  return useQuery({
    queryKey: queryKeys.pluginConfig(pluginId, scope),
    enabled: Boolean(pluginId) && enabled,
    queryFn: () =>
      apiGet<PluginConfigResponse>(`/plugins/${pluginId}/config${buildScopeQuery(scope)}`),
  });
}

export function useSavePluginConfig(pluginId: string, scope?: PluginScope) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (config: PluginConfigResponse) =>
      apiPut<PluginConfigResponse>(
        `/plugins/${pluginId}/config${buildScopeQuery(scope)}`,
        config,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.pluginConfig(pluginId, scope) });
    },
  });
}

export function usePluginData(pluginId: string, scope?: PluginScope, enabled = true) {
  return useQuery({
    queryKey: queryKeys.pluginData(pluginId, scope),
    enabled: Boolean(pluginId) && enabled,
    queryFn: () =>
      apiGet<Record<string, unknown>>(`/plugins/${pluginId}/data${buildScopeQuery(scope)}`),
  });
}

export function useSavePluginData(pluginId: string, scope?: PluginScope) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiPut<Record<string, unknown>>(`/plugins/${pluginId}/data${buildScopeQuery(scope)}`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.pluginData(pluginId, scope) });
    },
  });
}

export function useFeedSourcePipeline(feedSourceId: number | string) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).pipeline,
    queryFn: () => apiGet<PipelineDoc>(`/feed-sources/${feedSourceId}/pipeline`),
    enabled: Boolean(feedSourceId),
  });
}

export function useExportHistory(feedSourceId: number | string) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).exportHistory,
    queryFn: () => apiGet<ExportVersionOut[]>(`/feed-sources/${feedSourceId}/export-history`),
    enabled: Boolean(feedSourceId),
  });
}

export function useExportVersionDiff(
  feedSourceId: number | string,
  version: number | undefined,
  against: number | undefined,
) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).exportDiff(
      version !== undefined && against !== undefined ? { version, against } : undefined,
    ),
    queryFn: () => {
      const qs = against !== undefined ? `?against=${against}` : '';
      return apiGet<DiffOut>(`/feed-sources/${feedSourceId}/export-history/${version}/diff${qs}`);
    },
    enabled: version !== undefined && against !== undefined,
  });
}

export function useRollbackToVersion(feedSourceId: number | string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (version: number) =>
      apiPost<unknown>(`/feed-sources/${feedSourceId}/export-history/${version}/rollback`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.feedSource(feedSourceId).exportHistory });
      void queryClient.invalidateQueries({ queryKey: ['feed-source', feedSourceId, 'export-diff'] });
    },
  });
}

export function useSavePipeline(feedSourceId: number | string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (doc: PipelineDoc) =>
      apiPut<PipelineDoc>(`/feed-sources/${feedSourceId}/pipeline`, doc),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.feedSource(feedSourceId).pipeline });
    },
  });
}

export function usePatchPipelineInstance(feedSourceId: number | string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ instanceId, enabled }: { instanceId: number; enabled: boolean }) =>
      apiPatch<{ id: number; enabled: boolean }>(
        `/feed-sources/${feedSourceId}/pipeline/instances/${instanceId}`,
        { enabled },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(feedSourceId).pipeline,
      });
    },
  });
}
