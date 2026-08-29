import { Button, Group, Stack, Title } from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { usePluginConfig, useSavePluginConfig, usePlugins, type PluginScope } from '../../api/hooks';
import { JsonSchemaForm, type JsonSchema } from '../../components/JsonSchemaForm';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { notifyMutationError, notifySuccess } from '../../app/notifications';
import { ApiError } from '../../api/client';

export function PluginPage() {
  const { t } = useTranslation('plugins');
  const { pluginId, clientId, feedSourceId } = useParams();
  const { data: plugins, isPending, isError, refetch } = usePlugins();

  const scope: PluginScope = useMemo(() => {
    const s: PluginScope = {};
    if (clientId) s.clientId = Number(clientId);
    if (feedSourceId) s.feedSourceId = Number(feedSourceId);
    return s;
  }, [clientId, feedSourceId]);

  const config = usePluginConfig(pluginId ?? '', scope);
  const saveConfig = useSavePluginConfig(pluginId ?? '', scope);

  const [formValue, setFormValue] = useState<Record<string, unknown>>({});

  useEffect(() => {
    if (config.data) {
      setFormValue((config.data ?? {}) as Record<string, unknown>);
    }
  }, [config.data]);

  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={() => void refetch()} />;

  const plugin = (plugins ?? []).find((p) => p.id === pluginId);
  if (!plugin) return <EmptyState message={t('notFound')} />;

  const schema = plugin.manifest?.config_schema as JsonSchema | undefined;
  if (!schema) return <EmptyState message={t('noSchema')} />;

  async function onSubmit(value: unknown) {
    if (!pluginId) return;
    try {
      await saveConfig.mutateAsync((value ?? {}) as Record<string, unknown>);
      notifySuccess(t('configSaved'));
    } catch (error) {
      notifyMutationError(error, t('saveFailed'));
    }
  }

  return (
    <Stack gap="md">
      <Title order={3}>{plugin.name}</Title>
      {config.isPending ? (
        <LoadingState />
      ) : config.isError ? (
        <ErrorState onRetry={() => void config.refetch()} />
      ) : (
        <JsonSchemaForm
          schema={schema}
          value={formValue}
          onChange={(next) => setFormValue((next ?? {}) as Record<string, unknown>)}
          errors={saveConfig.error instanceof ApiError ? mapErrors(saveConfig.error.errors) : {}}
        />
      )}
      <Group justify="flex-end">
        <Button onClick={() => void onSubmit(formValue)} loading={saveConfig.isPending}>
          {t('save')}
        </Button>
      </Group>
    </Stack>
  );
}

function mapErrors(errors: string[] | null): Record<string, string> {
  if (!errors) return {};
  const out: Record<string, string> = {};
  for (const e of errors) {
    const idx = e.indexOf(':');
    if (idx > 0) {
      out[e.slice(0, idx).trim()] = e.slice(idx + 1).trim();
    } else {
      out._form = e;
    }
  }
  return out;
}
