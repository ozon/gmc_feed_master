import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, apiPut } from '../../api/client';
import { queryKeys } from '../../api/queryKeys';
import { useFeedSource } from '../../api/hooks';
import type { FeedSourceRow } from '../../api/types';

export type RuleAiTemplate = {
  id: number;
  name: string;
  task_type: string;
  client_id: number | null;
  version: number;
  is_active: boolean;
};

export type RuleAiPreviewResult = {
  messages: { role: string; content: string }[];
  used_variables: string[];
  warnings: string[];
  errors: string[];
};

export type RuleAiPreviewRequest = {
  feed_source_id: number;
  taskType: string;
  templateId?: number;
  system?: string;
  user?: string;
  variables?: string[];
  product_id?: string;
};

export type AiRulesConfig = { enabled: boolean; limit: number; budget: number };

export function useRuleAiTemplates(
  feedSourceId: number | undefined,
  taskType: string | undefined,
) {
  return useQuery({
    queryKey: ['rules', 'ai-templates', feedSourceId ?? 0, taskType ?? ''],
    enabled: Boolean(feedSourceId) && Boolean(taskType) && taskType !== 'rule_value',
    queryFn: () =>
      apiGet<{ items: RuleAiTemplate[] }>(
        `/plugins/rules/ai/templates?feed_source_id=${feedSourceId}` +
          `&task_type=${encodeURIComponent(taskType ?? '')}`,
      ),
  });
}

export function useRuleAiPreview() {
  return useMutation({
    mutationFn: (payload: RuleAiPreviewRequest) =>
      apiPost<RuleAiPreviewResult>('/plugins/rules/ai/preview', payload),
  });
}

export function useSaveAiRules(feedSourceId: number | undefined) {
  const queryClient = useQueryClient();
  const feed = useFeedSource(feedSourceId);
  return useMutation({
    mutationFn: (aiRules: AiRulesConfig) =>
      apiPut<FeedSourceRow>(`/feed-sources/${feedSourceId}`, {
        configuration: {
          ...((feed.data?.configuration ?? {}) as Record<string, unknown>),
          ai_rules: aiRules,
        },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(feedSourceId ?? 0).detail,
      });
    },
  });
}
