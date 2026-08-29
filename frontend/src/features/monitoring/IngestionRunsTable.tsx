import { Badge, Table, Text } from '@mantine/core';
import { IconAlertCircle, IconCheck, IconLoader, IconPlayerSkipForward } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';

export type IngestionRun = {
  id: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  processed_count: number;
  failed_count: number;
  error_message: string | null;
  statistics: Record<string, unknown>;
};

type Props = {
  runs: IngestionRun[];
};

const STATUS_COLOR: Record<string, string> = {
  success: 'green',
  error: 'red',
  running: 'blue',
  pending: 'gray',
  skipped: 'gray',
};

function StatusBadge({ status }: { status: string }) {
  const Icon =
    status === 'success' ? IconCheck
    : status === 'error' ? IconAlertCircle
    : status === 'running' ? IconLoader
    : IconPlayerSkipForward;
  return (
    <Badge color={STATUS_COLOR[status] ?? 'gray'} leftSection={<Icon size={12} />}>
      {status}
    </Badge>
  );
}

export function IngestionRunsTable({ runs }: Props) {
  const { t, i18n } = useTranslation('monitoring');
  return (
    <Table data-testid="ingestion-runs-table" striped>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('columns.startedAt')}</Table.Th>
          <Table.Th>{t('columns.status')}</Table.Th>
          <Table.Th>{t('columns.processed')}</Table.Th>
          <Table.Th>{t('columns.failed')}</Table.Th>
          <Table.Th>{t('columns.error')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {runs.map((run) => (
          <Table.Tr key={run.id} data-testid={`run-row-${run.id}`}>
            <Table.Td>
              <Text size="sm">{dayjs(run.started_at).locale(i18n.language).format('L LTS')}</Text>
            </Table.Td>
            <Table.Td>
              <StatusBadge status={run.status} />
            </Table.Td>
            <Table.Td>{new Intl.NumberFormat(i18n.language).format(run.processed_count)}</Table.Td>
            <Table.Td>
              {run.failed_count > 0 ? (
                <Text c="red" fw={500}>
                  {new Intl.NumberFormat(i18n.language).format(run.failed_count)}
                </Text>
              ) : (
                new Intl.NumberFormat(i18n.language).format(run.failed_count)
              )}
            </Table.Td>
            <Table.Td>
              {run.error_message ? (
                <Text size="sm" c="red" lineClamp={1} title={run.error_message}>
                  {run.error_message}
                </Text>
              ) : (
                <Text c="dimmed" size="sm">—</Text>
              )}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}