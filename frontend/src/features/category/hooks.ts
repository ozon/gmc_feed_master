import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from '../../api/client';
import { queryKeys } from '../../api/queryKeys';
import type { CategoryMatch, CategoryProductState, CategoryRule, CategoryStats } from './types';

export function useCategoryStats(feedSourceId: number | string | undefined) {
  return useQuery({
    queryKey: queryKeys.category.stats(feedSourceId ?? 0),
    queryFn: () => apiGet<CategoryStats>(`/plugins/category/stats?feed_source_id=${feedSourceId}`),
    enabled: Boolean(feedSourceId),
  });
}

export function useCategoryMatchesInfinite(
  feedSourceId: number | string,
  ruleId: string,
  limit: number,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.category.matches(feedSourceId, ruleId, limit),
    queryFn: ({ pageParam }) =>
      apiGet<{ total: number; items: CategoryMatch[] }>(
        `/plugins/category/matches?feed_source_id=${feedSourceId}` +
          `&rule_id=${encodeURIComponent(ruleId)}&limit=${limit}&offset=${pageParam}`,
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((count, page) => count + page.items.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
    enabled: Boolean(feedSourceId) && Boolean(ruleId),
  });
}

export function useCategoryProductState(
  feedSourceId: number | string,
  productId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.category.product(feedSourceId, productId ?? ''),
    queryFn: () =>
      apiGet<CategoryProductState>(
        `/plugins/category/product?feed_source_id=${feedSourceId}` +
          `&product_id=${encodeURIComponent(productId ?? '')}`,
      ),
    enabled: Boolean(feedSourceId) && Boolean(productId),
  });
}

export function useCategoryLanguages() {
  return useQuery({
    queryKey: queryKeys.category.languages,
    queryFn: () => apiGet<{ languages: string[] }>('/plugins/category/taxonomy/languages'),
  });
}

export function useFetchCategoryLanguage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (language: string) =>
      apiPost<{ status: string; language: string; entries: number }>(
        '/plugins/category/taxonomy/fetch',
        { language },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.category.languages });
    },
  });
}

export function useValidateCategoryRules() {
  return useMutation({
    mutationFn: (rules: CategoryRule[]) =>
      apiPost<{ status: string }>('/plugins/category/validate', { rules }),
  });
}
