import { Tabs } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useSearchParams, useParams } from 'react-router';
import { useFeedSource } from '../../api/hooks';
import { LoadingState, ErrorState } from '../../components/StateViews';
import { FeedSettingsForm } from './FeedSettingsForm';
import { ExportUrlCard } from './ExportUrlCard';
import { MappingTab } from './MappingTab';
import { Stack } from '@mantine/core';

export function SetupPage() {
  const { t } = useTranslation('setup');
  const [searchParams, setSearchParams] = useSearchParams();
  const { feedSourceId } = useParams<{ feedSourceId: string }>();
  const tab = searchParams.get('tab') === 'mapping' ? 'mapping' : 'settings';

  if (!feedSourceId) {
    return <ErrorState onRetry={() => {}} />;
  }

  const feedSource = useFeedSource(feedSourceId);

  if (feedSource.isPending) return <LoadingState />;
  if (feedSource.isError) {
    return <ErrorState onRetry={() => void feedSource.refetch()} />;
  }

  return (
    <Stack gap="md">
      <Tabs
        value={tab}
        onChange={(v) => {
          if (v) {
            setSearchParams((prev) => {
              const next = new URLSearchParams(prev);
              next.set('tab', v);
              return next;
            }, { replace: true });
          }
        }}
        keepMounted={false}
      >
        <Tabs.List>
          <Tabs.Tab value="settings">{t('tabs.settings')}</Tabs.Tab>
          <Tabs.Tab value="mapping">{t('tabs.mapping')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="settings" pt="md">
          <Stack gap="lg">
            <FeedSettingsForm feed={feedSource.data} />
            <ExportUrlCard feedSourceId={feedSourceId} />
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="mapping" pt="md">
          <MappingTab />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
