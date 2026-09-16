import { Badge, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import type { FeedDashboardData } from '../../api/types';

const STATUS_COLOR: Record<string, string> = {
  success: 'green',
  error: 'red',
  running: 'blue',
  pending: 'gray',
  skipped: 'gray',
};

export function RecentRunsTable({ runs }: { runs: FeedDashboardData['recent_runs'] }) {
  const { t, i18n } = useTranslation('feedDashboard');
  if (runs.length === 0) {
    return <Text c="dimmed" size="sm">{t('runs.empty')}</Text>;
  }
  return (
    <Table striped data-testid="recent-runs-table">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('runs.started')}</Table.Th>
          <Table.Th>{t('runs.status')}</Table.Th>
          <Table.Th>{t('runs.duration')}</Table.Th>
          <Table.Th>{t('runs.failed')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {runs.map((run) => (
          <Table.Tr key={run.id} data-testid={`run-row-${run.id}`}>
            <Table.Td>
              <Text size="sm">{dayjs(run.started_at).locale(i18n.language).format('L LTS')}</Text>
            </Table.Td>
            <Table.Td>
              <Badge color={STATUS_COLOR[run.status] ?? 'gray'}>{run.status}</Badge>
            </Table.Td>
            <Table.Td>
              {run.duration_s !== null ? t('runs.duration', { seconds: run.duration_s }) : '—'}
            </Table.Td>
            <Table.Td>{run.failed_count}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
