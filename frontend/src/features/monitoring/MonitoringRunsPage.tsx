import { Button, Stack } from '@mantine/core';
import { IconPlayerPlay } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { useIngestionRuns, useTriggerRun } from '../../api/hooks';
import { withLoadingNotification } from '../../app/notifications';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { IngestionRunsTable } from './IngestionRunsTable';

export function MonitoringRunsPage() {
  const { t } = useTranslation('monitoring');
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const { data, isPending, isError, refetch } = useIngestionRuns(id, true);
  const triggerRun = useTriggerRun(id);

  function handleTriggerRun() {
    void withLoadingNotification(
      'trigger-run',
      t('runs.triggerRunning'),
      () => triggerRun.mutateAsync(),
      t('runs.triggerSuccess'),
      t('runs.triggerFailed'),
    ).catch(() => undefined);
  }

  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={() => void refetch()} />;
  const runs = data ?? [];
  return (
    <Stack gap="md" pt="md">
      <Button
        leftSection={<IconPlayerPlay size={16} />}
        variant="light"
        onClick={() => void handleTriggerRun()}
        loading={triggerRun.isPending}
      >
        {t('runs.trigger')}
      </Button>
      {runs.length === 0 ? (
        <EmptyState message={t('runs.empty')} />
      ) : (
        <IngestionRunsTable runs={runs} />
      )}
    </Stack>
  );
}
