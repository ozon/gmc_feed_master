import { useState } from 'react';
import { Badge, Group, Select, Stack, Tabs, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { PluginScope } from '../../api/hooks';
import { useCategoryLanguages, useFetchCategoryLanguage } from './hooks';
import { editableTier } from './scope';
import { DashboardTab } from './DashboardTab';
import { RulesTab } from './RulesTab';
import { ManualTab } from './ManualTab';

export default function CategoryUI({
  pluginId,
  scope,
}: {
  pluginId: string;
  scope: PluginScope;
}) {
  const { t } = useTranslation('category');
  const tier = editableTier(scope);
  const [feedSourceId, setFeedSourceId] = useState<number | undefined>(undefined);
  const [language, setLanguage] = useState('en-US');
  const languages = useCategoryLanguages();
  const fetchLanguage = useFetchCategoryLanguage();
  const available = languages.data?.languages ?? ['en-US'];
  const deMissing = !available.includes('de-DE');

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Badge variant="light" color="gray">{tier}</Badge>
        <Group gap="xs">
          <Select
            label={t('language')}
            w={200}
            data={available.map((code) => ({ value: code, label: code }))}
            value={available.includes(language) ? language : available[0]}
            onChange={(value) => value && setLanguage(value)}
          />
          {deMissing && (
            <Select
              placeholder={t('fetchLanguage')}
              w={220}
              data={[{ value: 'de-DE', label: 'de-DE' }]}
              value={null}
              onChange={(value) =>
                value && fetchLanguage.mutate(value, {
                  onSuccess: () => setLanguage(value),
                })
              }
            />
          )}
        </Group>
      </Group>
      <Tabs defaultValue="dashboard">
        <Tabs.List>
          <Tabs.Tab value="dashboard">{t('tabs.dashboard')}</Tabs.Tab>
          <Tabs.Tab value="rules">{t('tabs.rules')}</Tabs.Tab>
          <Tabs.Tab value="manual">{t('tabs.manual')}</Tabs.Tab>
          <Tooltip label={t('placeholders.aiDisabled')} position="bottom">
            <Tabs.Tab value="ai" disabled>{t('tabs.ai')}</Tabs.Tab>
          </Tooltip>
          <Tooltip label={t('placeholders.uncategorizedDisabled')} position="bottom">
            <Tabs.Tab value="uncategorized" disabled>{t('tabs.uncategorized')}</Tabs.Tab>
          </Tooltip>
        </Tabs.List>
        <Tabs.Panel value="dashboard" pt="md">
          <DashboardTab
            clientId={scope.clientId}
            feedSourceId={feedSourceId}
            onSelectFeedSource={setFeedSourceId}
          />
        </Tabs.Panel>
        <Tabs.Panel value="rules" pt="md">
          <RulesTab
            pluginId={pluginId}
            scope={scope}
            language={language}
            feedSourceId={feedSourceId}
          />
        </Tabs.Panel>
        <Tabs.Panel value="manual" pt="md">
          <ManualTab
            pluginId={pluginId}
            scope={scope}
            language={language}
            feedSourceId={feedSourceId}
          />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
