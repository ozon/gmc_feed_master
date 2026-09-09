import { useEffect, useState } from 'react';
import { Badge, Button, Group, NumberInput, Stack, Switch, Table, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import {
  useAdminSettings,
  usePlugins,
  useSaveAdminSettings,
  useSchedulerJobs,
  useUpdatePluginEnabled,
} from '../../api/hooks';
import { LoadingState, ErrorState } from '../../components/StateViews';
import { notifyError, notifyMutationError, notifySuccess } from '../../app/notifications';
import { ApiError } from '../../api/client';

export function AdminSettingsPage() {
  const { t } = useTranslation('admin');
  const { t: tPlugins } = useTranslation('plugins');
  const { t: tPipeline } = useTranslation('pipeline');
  const settingsQuery = useAdminSettings();
  const schedulerQuery = useSchedulerJobs();
  const pluginsQuery = usePlugins();
  const saveSettings = useSaveAdminSettings();
  const updatePluginEnabled = useUpdatePluginEnabled();
  const [removal, setRemoval] = useState(90);
  const [history, setHistory] = useState(90);
  const [ingestion, setIngestion] = useState(90);

  useEffect(() => {
    if (settingsQuery.data) {
      setRemoval(settingsQuery.data.staging_removal_retention_days);
      setHistory(settingsQuery.data.staging_history_retention_days);
      setIngestion(settingsQuery.data.ingestion_run_retention_days);
    }
  }, [settingsQuery.data]);

  if (settingsQuery.isPending) return <LoadingState />;
  if (settingsQuery.isError) return <ErrorState onRetry={() => void settingsQuery.refetch()} />;

  return (
    <Stack>
      <Title order={3}>{t('settings.title')}</Title>

      <Stack gap="md" maw={420}>
        <NumberInput
          label={t('settings.removalRetention')}
          value={removal}
          min={1}
          onChange={(v) => setRemoval(Number(v) || 1)}
        />
        <NumberInput
          label={t('settings.historyRetention')}
          value={history}
          min={1}
          onChange={(v) => setHistory(Number(v) || 1)}
        />
        <NumberInput
          label={t('settings.ingestionRetention')}
          value={ingestion}
          min={1}
          onChange={(v) => setIngestion(Number(v) || 1)}
        />
        <Button
          loading={saveSettings.isPending}
          onClick={() =>
            saveSettings.mutate(
              {
                staging_removal_retention_days: removal,
                staging_history_retention_days: history,
                ingestion_run_retention_days: ingestion,
              },
              {
                onSuccess: () => notifySuccess(t('settings.saved')),
                onError: (error) => notifyMutationError(error, t('settings.saveFailed')),
              },
            )
          }
        >
          {t('settings.save')}
        </Button>
      </Stack>

      <Title order={4}>{t('settings.scheduler')}</Title>
      {schedulerQuery.isPending ? (
        <Text size="sm" c="dimmed">…</Text>
      ) : schedulerQuery.isError ? (
        <Text size="sm" c="dimmed">{t('settings.schedulerUnavailable')}</Text>
      ) : (
        <Table striped data-testid="admin-scheduler-table" maw={600}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('settings.jobId')}</Table.Th>
              <Table.Th>{t('settings.trigger')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {schedulerQuery.data.map((job) => (
              <Table.Tr key={job.id}>
                <Table.Td><Badge variant="light">{job.id}</Badge></Table.Td>
                <Table.Td>{job.trigger}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Title order={4}>{t('settings.plugins')}</Title>
      <Table striped maw={600} data-testid="admin-plugins-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('settings.pluginName')}</Table.Th>
            <Table.Th>{t('settings.pluginEnabled')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(pluginsQuery.data ?? []).map((plugin) => (
            <Table.Tr key={plugin.id}>
              <Table.Td>{tPlugins(`pluginNames.${plugin.id}`, { defaultValue: plugin.name })}</Table.Td>
              <Table.Td>
                <Switch
                  aria-label={t('settings.pluginEnabled')}
                  checked={plugin.enabled}
                  onChange={(event) =>
                    updatePluginEnabled.mutate(
                      { id: plugin.id, enabled: event.currentTarget.checked },
                      {
                        onError: (error) => {
                          if (error instanceof ApiError && error.status === 409) {
                            notifyError(
                              tPipeline('disableBlocked', {
                                count: plugin.used_by_feed_sources,
                              }),
                            );
                          } else {
                            notifyMutationError(error, t('settings.saveFailed'));
                          }
                        },
                      },
                    )
                  }
                />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
