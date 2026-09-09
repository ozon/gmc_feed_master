import { Group, Paper, Progress, Select, Stack, Text } from '@mantine/core';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDashboardSummary } from '../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { useCategoryStats } from './hooks';

const BUCKET_KEYS = ['manual', 'auto', 'excluded', 'uncategorized'] as const;

export function DashboardTab({
  clientId,
  feedSourceId,
  onSelectFeedSource,
}: {
  clientId: number | undefined;
  feedSourceId: number | undefined;
  onSelectFeedSource: (id: number) => void;
}) {
  const { t } = useTranslation('category');
  const summary = useDashboardSummary();
  const stats = useCategoryStats(feedSourceId);

  const client = summary.data?.clients?.find((c) => c.id === clientId);
  const feedSources = client?.feed_sources ?? [];

  useEffect(() => {
    if (feedSourceId === undefined && feedSources.length > 0) {
      onSelectFeedSource(feedSources[0].id);
    }
  }, [feedSourceId, feedSources, onSelectFeedSource]);

  if (clientId === undefined) {
    return <EmptyState message={t('manual.needsClient')} />;
  }
  if (summary.isLoading) return <LoadingState />;
  if (summary.isError) return <ErrorState onRetry={() => void summary.refetch()} />;
  if (feedSources.length === 0) return <EmptyState message={t('dashboard.noFeedSources')} />;

  const labeled = stats.data ? stats.data.buckets.manual + stats.data.buckets.auto : 0;

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Select
          label={t('dashboard.feedSource')}
          w={280}
          data={feedSources.map((feed) => ({ value: String(feed.id), label: feed.name }))}
          value={feedSourceId !== undefined ? String(feedSourceId) : null}
          onChange={(value) => value && onSelectFeedSource(Number(value))}
        />
        <Text size="xs" c="dimmed">{t('dashboard.asOfLastRun')}</Text>
      </Group>
      {stats.isLoading && <LoadingState />}
      {stats.isError && <ErrorState onRetry={() => void stats.refetch()} />}
      {stats.data && stats.data.total === 0 && (
        <EmptyState message={t('dashboard.noProducts')} />
      )}
      {stats.data && stats.data.total > 0 && (
        <Stack gap="xs">
          <Text size="sm" c="dimmed">
            {t('dashboard.progress', {
              labeled,
              total: stats.data.total,
            })}
          </Text>
          <Progress
            value={(labeled / stats.data.total) * 100}
            size="lg"
          />
          <Group gap="md" mt="xs" align="flex-start">
            {BUCKET_KEYS.map((bucket) => (
              <Paper withBorder p="sm" key={bucket}>
                <Stack gap={2}>
                  <Text size="xs" c="dimmed">{t(`dashboard.buckets.${bucket}`)}</Text>
                  <Text fw={700} fz="lg">{stats.data!.buckets[bucket]}</Text>
                </Stack>
              </Paper>
            ))}
            <Paper withBorder p="sm">
              <Stack gap={2}>
                <Text size="xs" c="dimmed">{t('dashboard.total')}</Text>
                <Text fw={700} fz="lg">{stats.data.total}</Text>
              </Stack>
            </Paper>
          </Group>
        </Stack>
      )}
    </Stack>
  );
}
