import { useState } from 'react';
import { AreaChart } from '@mantine/charts';
import { Group, Select, SimpleGrid, Stack, Table, Title } from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { useTranslation } from 'react-i18next';
import { useAiUsage, useAiUsageSummary, useAiUsageTimeseries } from '../../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../../components/StateViews';
import { ChartCard } from '../../../components/dashboard/ChartCard';
import { StatCard } from '../../../components/dashboard/StatCard';
import { chartColors } from '../../../components/dashboard/dashboardColors';
import type { AiUsageGroupBy } from '../../../api/types';
import { usageDateParams } from './usageDates';

const GROUP_OPTIONS: { value: AiUsageGroupBy; label: string }[] = [
  { value: 'client', label: 'Client' },
  { value: 'feed_source', label: 'Feed Source' },
  { value: 'task_type', label: 'Task Type' },
  { value: 'day', label: 'Day' },
];

export function UsagePage() {
  const { t } = useTranslation('admin');
  const [groupBy, setGroupBy] = useState<AiUsageGroupBy>('client');
  const [fromDate, setFromDate] = useState<Date | null>(null);
  const [toDate, setToDate] = useState<Date | null>(null);
  const filters = usageDateParams(fromDate, toDate);
  const usageQuery = useAiUsage({ group_by: groupBy, ...filters });
  const summaryQuery = useAiUsageSummary(filters);
  const timeseriesQuery = useAiUsageTimeseries(filters);

  if (usageQuery.isPending) return <LoadingState />;
  if (usageQuery.isError) return <ErrorState onRetry={() => void usageQuery.refetch()} />;
  const rows = usageQuery.data?.rows ?? [];
  const summary = summaryQuery.data;
  const trendRows = timeseriesQuery.data?.rows ?? [];

  return (
    <Stack gap="md">
      <Title order={4}>{t('ai.usage.title')}</Title>
      {summaryQuery.isPending ? (
        <LoadingState />
      ) : summaryQuery.isError ? (
        <ErrorState onRetry={() => void summaryQuery.refetch()} />
      ) : summary ? (
        <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} data-testid="ai-usage-kpi">
          <StatCard label={t('ai.usage.kpiCalls')} value={summary.calls} />
          <StatCard
            label={t('ai.usage.kpiCacheHitRate')}
            value={Math.round(summary.hit_ratio * 100)}
            suffix="%"
          />
          <StatCard label={t('ai.usage.kpiCost')} value={Number(summary.cost_usd ?? 0)} />
          <StatCard
            label={t('ai.usage.kpiCostSaved')}
            value={Number(summary.cost_saved_usd ?? 0)}
          />
        </SimpleGrid>
      ) : null}
      <Group align="end">
        <Select
          label={t('ai.usage.groupBy')}
          data={GROUP_OPTIONS}
          value={groupBy}
          onChange={(v) => setGroupBy((v as AiUsageGroupBy) ?? 'client')}
        />
        <DateInput
          label={t('ai.usage.from')}
          clearable
          value={fromDate}
          onChange={(v) => setFromDate(v ? new Date(v) : null)}
        />
        <DateInput
          label={t('ai.usage.to')}
          clearable
          value={toDate}
          onChange={(v) => setToDate(v ? new Date(v) : null)}
        />
      </Group>
      {rows.length === 0 ? (
        <EmptyState message={t('ai.usage.empty')} />
      ) : (
        <Table data-testid="ai-usage-table" striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('ai.usage.groupKey')}</Table.Th>
              <Table.Th>{t('ai.usage.calls')}</Table.Th>
              <Table.Th>{t('ai.usage.cacheHits')}</Table.Th>
              <Table.Th>{t('ai.usage.promptTokens')}</Table.Th>
              <Table.Th>{t('ai.usage.completionTokens')}</Table.Th>
              <Table.Th>{t('ai.usage.cost')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row, idx) => (
              <Table.Tr key={`${row.group_key}-${idx}`} data-testid={`ai-usage-row-${idx}`}>
                <Table.Td>{String(row.group_key)}</Table.Td>
                <Table.Td>{row.calls}</Table.Td>
                <Table.Td>{row.cache_hits}</Table.Td>
                <Table.Td>{row.prompt_tokens}</Table.Td>
                <Table.Td>{row.completion_tokens}</Table.Td>
                <Table.Td>{row.cost_usd ?? '—'}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <ChartCard
        title={t('ai.usage.trendTitle')}
        isEmpty={trendRows.length === 0}
        emptyMessage={t('ai.usage.empty')}
      >
        <AreaChart
          h={220}
          data={trendRows}
          dataKey="group_key"
          series={[
            { name: 'calls', label: t('ai.usage.trendCalls'), color: chartColors.info },
            {
              name: 'cache_hits',
              label: t('ai.usage.trendCacheHits'),
              color: chartColors.success,
            },
          ]}
          curveType="monotone"
        />
      </ChartCard>
    </Stack>
  );
}
