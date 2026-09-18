import { Group, NumberInput, Stack, Switch, Text } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { useFeedSource } from '../../api/hooks';
import { useSaveAiRules, type AiRulesConfig } from './hooks';

const DEFAULTS: AiRulesConfig = { enabled: false, limit: 50, budget: 50 };

export function RuleAiBudget({ feedSourceId }: { feedSourceId?: number }) {
  const { t } = useTranslation('rules');
  const feed = useFeedSource(feedSourceId);
  const save = useSaveAiRules(feedSourceId);
  const [value, setValue] = useState<AiRulesConfig>(DEFAULTS);
  const [prevFeedData, setPrevFeedData] = useState<typeof feed.data>(undefined);
  if (prevFeedData !== feed.data) {
    setPrevFeedData(feed.data);
    const stored = feed.data?.configuration?.ai_rules;
    if (stored && typeof stored === 'object') {
      setValue({ ...DEFAULTS, ...(stored as Partial<AiRulesConfig>) });
    }
  }

  function commit(next: AiRulesConfig) {
    setValue(next);
    if (!feedSourceId) return;
    save.mutate(next, {
      onSuccess: () => notifySuccess(t('ai.budget.saved')),
      onError: (error) => notifyApiError(error, t('ai.budget.saveFailed')),
    });
  }

  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        {t('ai.budget.title')}
      </Text>
      <Group gap="md">
        <Switch
          aria-label={t('ai.budget.enabled')}
          label={t('ai.budget.enabled')}
          checked={value.enabled}
          onChange={(e) => commit({ ...value, enabled: e.currentTarget.checked })}
        />
        <NumberInput
          aria-label={t('ai.budget.limit')}
          value={value.limit}
          min={1}
          onChange={(v) => setValue({ ...value, limit: typeof v === 'number' ? v : 1 })}
          onBlur={() => commit(value)}
          w={140}
          label={t('ai.budget.limit')}
        />
        <NumberInput
          aria-label={t('ai.budget.budget')}
          value={value.budget}
          min={1}
          onChange={(v) => setValue({ ...value, budget: typeof v === 'number' ? v : 1 })}
          onBlur={() => commit(value)}
          w={140}
          label={t('ai.budget.budget')}
        />
      </Group>
    </Stack>
  );
}
