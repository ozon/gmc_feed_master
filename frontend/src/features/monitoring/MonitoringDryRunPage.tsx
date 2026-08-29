import { Stack } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { withLoadingNotification } from '../../app/notifications';
import { EmptyState } from '../../components/StateViews';
import { useRunDryRun } from '../../api/hooks';
import { DryRunForm } from './DryRunForm';
import { DryRunResults } from './DryRunResults';

export function MonitoringDryRunPage() {
  const { t } = useTranslation('monitoring');
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const [result, setResult] = useState<unknown>(null);
  const run = useRunDryRun(id);
  if (!feedSourceId) return null;
  return (
    <Stack gap="md" pt="md">
      <DryRunForm
        run={run}
        onResult={async (next) => {
          try {
            await withLoadingNotification(
              'dry-run',
              t('dryRun.running'),
              async () => {
                setResult(next);
                return next;
              },
              t('dryRun.success'),
              t('dryRun.failed'),
            );
          } catch {
            setResult(null);
          }
        }}
      />
      {result ? <DryRunResults result={result} /> : <EmptyState message={t('dryRun.empty')} />}
      {run.isError ? <div role="alert">{t('dryRun.failed')}</div> : null}
    </Stack>
  );
}