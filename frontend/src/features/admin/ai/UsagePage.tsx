import { useState } from 'react';
import { Group, Select, Stack, Table, Title } from '@mantine/core';
import { DateInput } from '@mantine/dates';
import { useTranslation } from 'react-i18next';
import { useAiUsage } from '../../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../../components/StateViews';
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
  const usageQuery = useAiUsage({ group_by: groupBy, ...usageDateParams(fromDate, toDate) });

  if (usageQuery.isPending) return <LoadingState />;
  if (usageQuery.isError) return <ErrorState onRetry={() => void usageQuery.refetch()} />;
  const rows = usageQuery.data?.rows ?? [];

  return (
    <Stack gap="md">
      <Title order={4}>{t('ai.usage.title')}</Title>
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
    </Stack>
  );
}
