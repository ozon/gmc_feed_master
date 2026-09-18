import { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  NumberInput,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import {
  useAiCacheStats,
  useAiCacheStatus,
  useAiSettings,
  useClearAiCache,
  useUpdateAiSettings,
} from '../../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../../app/notifications';
import { ErrorState, LoadingState } from '../../../components/StateViews';
import type { AiSettings } from '../../../api/types';

export function AiSettingsPage() {
  const { t } = useTranslation('admin');
  const settingsQuery = useAiSettings();
  const statusQuery = useAiCacheStatus();
  const statsQuery = useAiCacheStats();
  const updateSettings = useUpdateAiSettings();
  const clearCache = useClearAiCache();
  const [draft, setDraft] = useState<AiSettings | null>(null);
  const [prevSettingsData, setPrevSettingsData] = useState(settingsQuery.data);
  if (settingsQuery.data && settingsQuery.data !== prevSettingsData) {
    setPrevSettingsData(settingsQuery.data);
    setDraft(settingsQuery.data);
  }

  if (settingsQuery.isPending) return <LoadingState />;
  if (settingsQuery.isError) {
    return <ErrorState onRetry={() => void settingsQuery.refetch()} />;
  }
  if (!draft) return null;

  const patch = (patchValue: Partial<AiSettings>) => setDraft({ ...draft, ...patchValue });
  const redisOverride = draft.redis_from_env;
  const status = statusQuery.data;
  const stats = statsQuery.data;

  return (
    <Stack data-testid="ai-settings-form">
      <Card withBorder>
        <Title order={4}>{t('ai.settings.cacheTitle')}</Title>
        <Stack mt="sm">
          {redisOverride ? (
            <Alert color="blue" data-testid="ai-cache-redis-note">
              {t('ai.settings.redisOverride')}
            </Alert>
          ) : null}
          <Select
            label={t('ai.settings.cacheType')}
            data-testid="ai-cache-backend-select"
            disabled={redisOverride}
            value={draft.ai_cache_type}
            onChange={(value) => patch({ ai_cache_type: value ?? 'local' })}
            data={[
              { value: 'local', label: t('ai.settings.cacheTypeOptions.local') },
              { value: 'disk', label: t('ai.settings.cacheTypeOptions.disk') },
            ]}
          />
          <TextInput
            label={t('ai.settings.namespace')}
            value={draft.ai_cache_namespace}
            onChange={(event) => patch({ ai_cache_namespace: event.currentTarget.value })}
          />
          <Group grow>
            <NumberInput
              label={t('ai.settings.ttlTaxonomy')}
              value={draft.ai_cache_ttl_taxonomy_s}
              min={1}
              onChange={(value) => patch({ ai_cache_ttl_taxonomy_s: Number(value) || 1 })}
            />
            <NumberInput
              label={t('ai.settings.ttlContent')}
              value={draft.ai_cache_ttl_content_s}
              min={1}
              onChange={(value) => patch({ ai_cache_ttl_content_s: Number(value) || 1 })}
            />
          </Group>
          <Group>
            <Text data-testid="ai-cache-backend">
              {t('ai.settings.backend')}:{' '}
              {status?.effective_backend ?? draft.effective_cache_backend}
            </Text>
            <Badge color={status?.healthy ? 'green' : 'red'}>
              {status?.healthy ? t('ai.settings.healthy') : t('ai.settings.unhealthy')}
            </Badge>
            <Text data-testid="ai-cache-entries">
              {t('ai.settings.entries')}: {status?.entries ?? '—'}
            </Text>
            <Text data-testid="ai-cache-hit-ratio">
              {t('ai.settings.hitRatio')}: {Math.round((stats?.hit_ratio ?? 0) * 100)}%
            </Text>
            <Text>
              {t('ai.settings.costSaved')}: {String(stats?.cost_saved_usd ?? 0)}
            </Text>
          </Group>
          <Group>
            <Button
              variant="light"
              color="red"
              onClick={() =>
                clearCache.mutate(undefined, {
                  onSuccess: () => notifySuccess(t('ai.settings.cacheCleared')),
                  onError: (error) => notifyMutationError(error, t('ai.settings.saveFailed')),
                })
              }
            >
              {t('ai.settings.clearCache')}
            </Button>
          </Group>
        </Stack>
      </Card>
      <Card withBorder>
        <Title order={4}>{t('ai.settings.routerTitle')}</Title>
        <Stack mt="sm">
          <Group grow>
            <NumberInput
              label={t('ai.settings.timeout')}
              value={draft.ai_router_timeout_s}
              min={1}
              max={600}
              onChange={(value) => patch({ ai_router_timeout_s: Number(value) || 1 })}
            />
            <NumberInput
              label={t('ai.settings.numRetries')}
              data-testid="ai-num-retries"
              value={draft.ai_router_num_retries}
              min={0}
              max={10}
              onChange={(value) => patch({ ai_router_num_retries: Number(value) || 0 })}
            />
          </Group>
          <Group grow>
            <NumberInput
              label={t('ai.settings.allowedFails')}
              value={draft.ai_router_allowed_fails}
              min={0}
              max={100}
              onChange={(value) => patch({ ai_router_allowed_fails: Number(value) || 0 })}
            />
            <NumberInput
              label={t('ai.settings.cooldown')}
              value={draft.ai_router_cooldown_s}
              min={0}
              max={3600}
              onChange={(value) => patch({ ai_router_cooldown_s: Number(value) || 0 })}
            />
          </Group>
          <Group grow>
            <NumberInput
              label={t('ai.settings.instructorRetries')}
              value={draft.ai_instructor_max_retries}
              min={0}
              max={10}
              onChange={(value) => patch({ ai_instructor_max_retries: Number(value) || 0 })}
            />
            <NumberInput
              label={t('ai.settings.usageRetention')}
              value={draft.ai_usage_retention_days}
              min={1}
              onChange={(value) => patch({ ai_usage_retention_days: Number(value) || 1 })}
            />
          </Group>
          <Button
            data-testid="ai-settings-save"
            onClick={() =>
              updateSettings.mutate(draft, {
                onSuccess: () => notifySuccess(t('ai.saved')),
                onError: (error) => notifyMutationError(error, t('ai.settings.saveFailed')),
              })
            }
          >
            {t('ai.save')}
          </Button>
        </Stack>
      </Card>
    </Stack>
  );
}
