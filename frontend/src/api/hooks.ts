import { useMemo } from 'react';
import {
  keepPreviousData, useMutation, useQuery, useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';
import {
  ApiError, apiDelete, apiGet, apiGetWithHeaders, apiPatch, apiPost, apiPut,
  changePassword, getCurrentUser, logout,
} from './client';
import { queryKeys } from './queryKeys';
import type {
  AdminUser,
  AiProvider,
  AiTestResult,
  AiUsageParams,
  AiUsageRow,
  ChatMessage,
  ClientRow,
  ClientSummary,
  DashboardSummary,
  DiffOut,
  ExportVersionOut,
  FeedSourceFieldsResponse,
  FeedSourceRow,
  FeedSourceSummary,
  FieldMappingDoc,
  GlobalSettings,
  IngestionRunRow,
  PipelineDoc,
  PluginConfigResponse,
  PluginInfo,
  ProductDetail,
  ProductLookupResponse,
  ProductsPageResponse,
  PromptPreviewResult,
  PromptTemplate,
  QualityFindingsResponse,
  QualityHistoryRow,
  RegistryAttribute,
  SchedulerJob,
} from './types';

export type {
  AdminUser,
  ChatMessage,
  ClientRow,
  ClientSummary,
  DashboardSummary,
  DiffOut,
  ExportVersionOut,
  FeedSourceFieldsResponse,
  FeedSourceRow,
  FeedSourceSummary,
  FieldMappingDoc,
  GlobalSettings,
  IngestionRunRow,
  PipelineDoc,
  PluginConfigResponse,
  PluginInfo,
  ProductDetail,
  ProductsPageResponse,
  QualityFindingsResponse,
  QualityHistoryRow,
  RegistryAttribute,
  SchedulerJob,
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

export function useFeedSource(id: number | string | undefined) {
  return useQuery({
    queryKey: queryKeys.feedSource(id ?? 0).detail,
    queryFn: () => apiGet<FeedSourceRow>(`/feed-sources/${id}`),
    enabled: Boolean(id),
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

export function useRegistryAttributes(feedSourceId?: number | string) {
  return useQuery({
    queryKey: queryKeys.registryAttributes(feedSourceId),
    queryFn: () => apiGet<RegistryAttribute[]>(
      feedSourceId === undefined
        ? '/registry/attributes'
        : `/registry/attributes?feed_source_id=${feedSourceId}`,
    ),
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

export function useQualityHistory(feedSourceId: number | string, limit = 30) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).qualityHistory,
    queryFn: () =>
      apiGet<{ rows: QualityHistoryRow[] }>(
        `/feed-sources/${feedSourceId}/quality-history?limit=${limit}`,
      ),
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
      void queryClient.invalidateQueries({ queryKey: ['registry', 'attributes'] });
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
      void queryClient.invalidateQueries({ queryKey: ['registry', 'attributes'] });
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
    mutationFn: ({
      id,
      mappings,
      customFields,
    }: {
      id: number | string;
      mappings: Record<string, { target: string }>;
      customFields?: string[];
    }) =>
      apiPut<FieldMappingDoc>(
        `/feed-sources/${id}/field-mapping`,
        { mappings, custom_fields: customFields ?? [] },
      ),
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

type PluginPayloadCache = {
  payload: unknown;
  version: number | null;
};

function pluginVersionFromHeaders(headers: Headers): number | null {
  const raw = headers.get('X-Plugin-Data-Version');
  if (raw === null || raw === '') return null;
  const parsed = Number.parseInt(raw, 10);
  return Number.isNaN(parsed) ? null : parsed;
}

function pluginQuerySelect<T>(cache: PluginPayloadCache | undefined): T | undefined {
  return (cache?.payload as T | undefined) ?? undefined;
}

async function putPluginPayloadWithRetry(
  queryClient: QueryClient,
  key: readonly unknown[],
  url: string,
  buildPayload: (current: unknown) => unknown,
): Promise<unknown> {
  const base = url.includes('?') ? url : `${url}?`;
  const cached = queryClient.getQueryData<PluginPayloadCache>(key);
  if (cached === undefined) {
    return apiPut(url, buildPayload(undefined));
  }
  const suffix = `expected_version=${cached.version === null ? 'null' : cached.version}`;
  const payload = buildPayload(cached.payload);
  try {
    return await apiPut(`${base}${base.endsWith('?') ? '' : '&'}${suffix}`, payload);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 409) throw error;
    await queryClient.fetchQuery({
      queryKey: key,
      queryFn: async () => {
        const { data: freshData, headers } = await apiGetWithHeaders<unknown>(url);
        return { payload: freshData, version: pluginVersionFromHeaders(headers) };
      },
      staleTime: 0,
    });
    const fresh = queryClient.getQueryData<PluginPayloadCache>(key);
    if (fresh === undefined) throw error;
    const freshSuffix = `expected_version=${fresh.version === null ? 'null' : fresh.version}`;
    return apiPut(
      `${base}${base.endsWith('?') ? '' : '&'}${freshSuffix}`,
      buildPayload(fresh.payload),
    );
  }
}

export function usePluginConfig(pluginId: string, scope?: PluginScope, enabled = true) {
  const key = queryKeys.pluginConfig(pluginId, scope);
  return useQuery({
    queryKey: key,
    enabled: Boolean(pluginId) && enabled,
    queryFn: async () => {
      const { data, headers } = await apiGetWithHeaders<unknown>(
        `/plugins/${pluginId}/config${buildScopeQuery(scope)}`,
      );
      return { payload: data, version: pluginVersionFromHeaders(headers) };
    },
    select: (cache: PluginPayloadCache) => pluginQuerySelect<PluginConfigResponse>(cache),
  });
}

export function useSavePluginConfig(pluginId: string, scope?: PluginScope) {
  const queryClient = useQueryClient();
  const key = queryKeys.pluginConfig(pluginId, scope);
  return useMutation({
    mutationFn: (buildConfig: (current: unknown) => PluginConfigResponse) =>
      putPluginPayloadWithRetry(
        queryClient,
        key,
        `/plugins/${pluginId}/config${buildScopeQuery(scope)}`,
        buildConfig,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: key });
    },
  });
}

export function usePluginData(pluginId: string, scope?: PluginScope, enabled = true) {
  const key = queryKeys.pluginData(pluginId, scope);
  return useQuery({
    queryKey: key,
    enabled: Boolean(pluginId) && enabled,
    queryFn: async () => {
      const { data, headers } = await apiGetWithHeaders<unknown>(
        `/plugins/${pluginId}/data${buildScopeQuery(scope)}`,
      );
      return { payload: data, version: pluginVersionFromHeaders(headers) };
    },
    select: (cache: PluginPayloadCache) =>
      pluginQuerySelect<Record<string, unknown>>(cache) as Record<string, unknown> | undefined,
  });
}

export function useSavePluginData(pluginId: string, scope?: PluginScope) {
  const queryClient = useQueryClient();
  const key = queryKeys.pluginData(pluginId, scope);
  return useMutation({
    mutationFn: (buildData: (current: unknown) => Record<string, unknown>) =>
      putPluginPayloadWithRetry(
        queryClient,
        key,
        `/plugins/${pluginId}/data${buildScopeQuery(scope)}`,
        buildData,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: key });
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

export function useProductLookup(
  feedSourceId: number | undefined,
  field: string,
  values: string[],
  extraFields: string[],
) {
  // Sort for the cache key and body so reordered lists hit the same entry
  // (the response is a value-keyed map — order-insensitive).
  const sortedValues = useMemo(() => [...values].sort(), [values]);
  const sortedExtraFields = useMemo(() => [...extraFields].sort(), [extraFields]);
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId ?? 0)
      .productLookup({ field, values: sortedValues, extraFields: sortedExtraFields }),
    queryFn: () =>
      apiPost<ProductLookupResponse>(
        `/feed-sources/${feedSourceId}/products/lookup`,
        { field, values: sortedValues, extraFields: sortedExtraFields },
      ),
    enabled: feedSourceId !== undefined && values.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useAdminUsers() {
  return useQuery({
    queryKey: queryKeys.adminUsers,
    queryFn: () => apiGet<AdminUser[]>('/admin/users'),
  });
}

export function useCreateAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      username: string;
      password: string;
      role: 'admin' | 'user';
      client_ids: number[];
    }) => apiPost<AdminUser>('/admin/users', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers });
    },
  });
}

export function useUpdateAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: {
      id: number;
      role?: 'admin' | 'user';
      is_active?: boolean;
      client_ids?: number[];
    }) => apiPatch<AdminUser>(`/admin/users/${id}`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers });
    },
  });
}

export function useResetUserPassword() {
  return useMutation({
    mutationFn: ({ id, newPassword }: { id: number; newPassword: string }) =>
      apiPost<void>(`/admin/users/${id}/password`, { new_password: newPassword }),
  });
}

export function useAdminSettings() {
  return useQuery({
    queryKey: queryKeys.adminSettings,
    queryFn: () => apiGet<GlobalSettings>('/admin/settings'),
  });
}

export function useSaveAdminSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: GlobalSettings) => apiPut<GlobalSettings>('/admin/settings', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminSettings });
    },
  });
}

export function useSchedulerJobs() {
  return useQuery({
    queryKey: queryKeys.adminScheduler,
    queryFn: () => apiGet<SchedulerJob[]>('/admin/scheduler'),
    retry: false,
  });
}

export function useAiProviders() {
  return useQuery({
    queryKey: queryKeys.ai.providers,
    queryFn: () => apiGet<AiProvider[]>('/admin/ai/providers'),
  });
}

export function useCreateAiProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Omit<AiProvider, 'id'> & { api_key?: string }) =>
      apiPost<AiProvider>('/admin/ai/providers', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers });
    },
  });
}

export function useUpdateAiProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: {
      id: number;
      api_key?: string;
      name?: string;
      base_url?: string;
      model?: string;
      input_price_per_mtok?: string | null;
      output_price_per_mtok?: string | null;
      max_concurrency?: number;
      timeout_s?: number;
      enabled?: boolean;
      is_default?: boolean;
    }) => apiPatch<AiProvider>(`/admin/ai/providers/${id}`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers });
    },
  });
}

export function useDeleteAiProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete<void>(`/admin/ai/providers/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.providers });
    },
  });
}

export function useTestAiProvider() {
  return useMutation({
    mutationFn: (id: number) =>
      apiPost<AiTestResult>(`/admin/ai/providers/${id}/test`),
  });
}

export function useAiUsage(params: AiUsageParams) {
  const search = new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, String(v)]),
  ).toString();
  return useQuery({
    queryKey: queryKeys.ai.usage(params),
    queryFn: () => apiGet<{ rows: AiUsageRow[] }>(`/admin/ai/usage?${search}`),
  });
}

export function usePromptTemplates() {
  return useQuery({
    queryKey: queryKeys.ai.promptTemplates,
    queryFn: () => apiGet<PromptTemplate[]>('/admin/ai/prompt-templates'),
  });
}

export function useCreatePromptTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      task_type: string;
      client_id?: number | null;
      name: string;
      system_prompt: string;
      user_prompt: string;
      variables: string[];
      activate?: boolean;
    }) => apiPost<PromptTemplate>('/admin/ai/prompt-templates', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.promptTemplates });
    },
  });
}

export function useActivatePromptTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiPost<PromptTemplate>(`/admin/ai/prompt-templates/${id}/activate`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.promptTemplates });
    },
  });
}

export function usePreviewPromptTemplate() {
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiPost<PromptPreviewResult>('/admin/ai/prompt-templates/preview', payload),
  });
}

export function useChat() {
  return useMutation({
    mutationFn: (messages: ChatMessage[]) =>
      apiPost<{ content: string }>('/chat', { messages }),
  });
}
