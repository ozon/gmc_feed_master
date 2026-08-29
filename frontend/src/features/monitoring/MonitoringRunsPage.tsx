import { Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { useIngestionRuns } from '../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { IngestionRunsTable } from './IngestionRunsTable';

export function MonitoringRunsPage() {
  const { t } = useTranslation('monitoring');
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const { data, isPending, isError, refetch } = useIngestionRuns(id, true);
  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={() => void refetch()} />;
  const runs = data ?? [];
  if (runs.length === 0) return <EmptyState message={t('runs.empty')} />;
  return (
    <Stack gap="md" pt="md">
      <IngestionRunsTable runs={runs} />
    </Stack>
  );
}