import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from './client';

export type ProviderPreset = {
  vendor_key: string;
  label: string;
  model_prefix: string;
  default_base_url: string;
  requires_base_url: boolean;
  requires_api_version: boolean;
  api_key_docs_url: string;
  description: string;
  is_custom: boolean;
};

export type ModelCatalogEntry = {
  model_id: string;
  vendor: string;
  display_name: string;
  context_window: number | null;
  max_output_tokens: number | null;
  input_price_per_mtok: number | null;
  output_price_per_mtok: number | null;
  supports_vision: boolean;
  supports_function_calling: boolean;
  is_recommended: boolean;
};

export type ModelCatalogStatus = {
  source: string;
  last_synced_at: string | null;
};

export function useProviderPresets() {
  return useQuery({
    queryKey: ['ai', 'provider-presets'],
    queryFn: async () => {
      const { data } = await apiClient.get<ProviderPreset[]>('/admin/ai/providers/presets');
      return data;
    },
    staleTime: Infinity,
  });
}

export function useModelCatalog(vendor?: string) {
  return useQuery({
    queryKey: ['ai', 'model-catalog', vendor ?? 'all'],
    queryFn: async () => {
      const { data } = await apiClient.get<ModelCatalogEntry[]>('/admin/ai/model-catalog', {
        params: vendor ? { vendor } : undefined,
      });
      return data;
    },
    enabled: Boolean(vendor),
  });
}

export function useModelCatalogStatus() {
  return useQuery({
    queryKey: ['ai', 'model-catalog', 'status'],
    queryFn: async () => {
      const { data } = await apiClient.get<ModelCatalogStatus>('/admin/ai/model-catalog/status');
      return data;
    },
  });
}

export function useRefreshModelCatalog() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.post('/admin/ai/model-catalog/refresh');
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai', 'model-catalog'] });
    },
  });
}
