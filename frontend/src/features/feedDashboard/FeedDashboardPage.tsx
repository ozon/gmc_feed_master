import { AreaChart, BarChart, DonutChart } from '@mantine/charts';
import {
  Anchor,
  Badge,
  Breadcrumbs,
  Button,
  CopyButton,
  Group,
  SimpleGrid,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { IconPlayerPlay, IconSettings } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';
import {
  fillDates,
  useDashboardSummary,
  useFeedDashboard,
  useFeedSource,
  useTriggerRun,
} from '../../api/hooks';
import type { FeedDashboardData } from '../../api/types';
import { withLoadingNotification } from '../../app/notifications';
import { ChartCard } from '../../components/dashboard/ChartCard';
import { StatCard } from '../../components/dashboard/StatCard';
import { chartColors } from '../../components/dashboard/dashboardColors';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { RecentRunsTable } from './RecentRunsTable';

export function FeedDashboardPage() {
  const { t } = useTranslation('feedDashboard');
  const { t: tMonitoring } = useTranslation('monitoring');
  const { clientId, feedSourceId } = useParams();
  const id = feedSourceId ?? '';

  const dashboardQuery = useFeedDashboard(id);
  const feedQuery = useFeedSource(id);
  const summaryQuery = useDashboardSummary();
  const triggerRun = useTriggerRun(id);

  if (dashboardQuery.isPending) return <LoadingState />;
  if (dashboardQuery.isError) {
    return <ErrorState onRetry={() => void dashboardQuery.refetch()} />;
  }

  const data = dashboardQuery.data;
  const feed = feedQuery.data;
  const client = summaryQuery.data?.clients?.find((c) => String(c.id) === clientId);
  const feedName = feed?.name ?? client?.feed_sources?.find((f) => String(f.id) === id)?.name ?? id;
  const readinessPct = Math.round(data.kpi.readiness_rate * 100);

  function handleRun() {
    void withLoadingNotification(
      'feed-dashboard-trigger',
      tMonitoring('runs.triggerRunning'),
      () => triggerRun.mutateAsync(),
      tMonitoring('runs.triggerSuccess'),
      tMonitoring('runs.triggerFailed'),
    ).catch(() => undefined);
  }

  return (
    <Stack gap="md" pt="md">
      <Group justify="space-between" wrap="nowrap">
        <Stack gap={4}>
          <Breadcrumbs>
            <Anchor component={Link} to="/" size="sm" c="dimmed">
              {client?.name ?? t('breadcrumbClients')}
            </Anchor>
            <Text size="sm" fw={500}>{feedName}</Text>
          </Breadcrumbs>
          <Group gap="xs">
            <Badge variant="light">{(feed?.source_format ?? '').toUpperCase()}</Badge>
            <Badge variant="light" color="green">{t('badge.active')}</Badge>
            <Badge variant="light" color="gray">{t('badge.target')}</Badge>
          </Group>
        </Stack>
        <Group gap="xs" wrap="nowrap">
          <Button
            leftSection={<IconPlayerPlay size={16} />}
            onClick={handleRun}
            loading={triggerRun.isPending}
          >
            {t('runPipeline')}
          </Button>
          <Button
            variant="light"
            leftSection={<IconSettings size={16} />}
            component={Link}
            to={`/clients/${clientId}/feeds/${id}/pipeline`}
          >
            {t('editPipeline')}
          </Button>
          {feed?.export_url ? (
            <CopyButton value={feed.export_url} timeout={2000}>
              {({ copied, copy }) => (
                <Tooltip label={copied ? t('copied') : t('copyExportUrl')}>
                  <Button variant="light" color={copied ? 'teal' : undefined} onClick={copy}>
                    {t('copyExportUrl')}
                  </Button>
                </Tooltip>
              )}
            </CopyButton>
          ) : null}
        </Group>
      </Group>

      <SimpleGrid cols={{ base: 1, xs: 2, md: 5 }}>
        <StatCard label={t('kpi.rawItems')} value={data.kpi.raw_items} />
        <StatCard label={t('kpi.validItems')} value={data.kpi.valid_items} />
        <StatCard
          label={t('kpi.excludedItems')}
          value={data.kpi.excluded_items}
          variant={data.kpi.excluded_items > 0 ? 'warning' : 'neutral'}
        />
        <StatCard label={t('kpi.duration')} value={data.kpi.last_duration_s ?? 0} suffix="s" />
        <StatCard
          label={t('kpi.readiness')}
          value={readinessPct}
          variant={readinessPct < 90 ? 'critical' : 'neutral'}
        />
      </SimpleGrid>

      <ChartCard title={t('charts.volumeTitle')} isEmpty={data.volume_trend.length === 0} emptyMessage={t('charts.volumeEmpty')}>
        <AreaChart
          h={240}
          data={fillDates(data.volume_trend, 30, (date) => ({ date, raw: 0, exportable: 0 }))}
          dataKey="date"
          curveType="natural"
          withLegend
          series={[
            { name: 'raw', color: chartColors.raw },
            { name: 'exportable', color: chartColors.exportable },
          ]}
        />
      </ChartCard>

      <ChartCard title={t('charts.funnelTitle')} isEmpty={data.stage_funnel.length === 0} emptyMessage={t('charts.funnelEmpty')}>
        <BarChart
          h={200}
          orientation="horizontal"
          type="stacked"
          data={data.stage_funnel}
          dataKey="stage"
          series={[
            { name: 'passed', color: chartColors.passed },
            { name: 'dropped', color: chartColors.dropped },
          ]}
        />
      </ChartCard>

      <ChartCard title={t('charts.qualityTitle')} isEmpty={data.quality.critical + data.quality.warning + data.quality.info === 0} emptyMessage={t('charts.qualityEmpty')}>
        <DonutChart
          size={180}
          chartLabel={`${readinessPct}%`}
          data={[
            { name: tMonitoring('severity.critical'), value: data.quality.critical, color: chartColors.error },
            { name: tMonitoring('severity.warning'), value: data.quality.warning, color: chartColors.warning },
            { name: tMonitoring('severity.info'), value: data.quality.info, color: chartColors.info },
          ]}
          withTooltip
          mx="auto"
        />
        <Group justify="center" mt="sm">
          <Anchor component={Link} to={`/clients/${clientId}/feeds/${id}/monitoring/findings`} size="sm">
            {t('viewFindings')}
          </Anchor>
        </Group>
      </ChartCard>

      <Stack gap="xs">
        <Title order={5}>{t('runs.title')}</Title>
        <RecentRunsTable runs={data.recent_runs} />
      </Stack>
    </Stack>
  );
}
