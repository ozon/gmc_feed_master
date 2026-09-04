import { Button, Group, Stack, Title } from '@mantine/core';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { usePluginConfig, useSavePluginConfig, usePlugins, type PluginScope } from '../../api/hooks';
import { JsonSchemaForm, type JsonSchema } from '../../components/JsonSchemaForm';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { notifySuccess, mapFieldErrors, notifyApiError } from '../../app/notifications';
import { ApiError } from '../../api/client';
// MVP wiring: static import of the core rules plugin component (the plugin stub is the seam).
// Full build-time discovery of plugin components is a follow-up — see ADR 0002.
import RulesUI from '../../../../plugins/core/rules/frontend/component';

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
  const hasSeededRef = useRef(false);

  useEffect(() => {
    hasSeededRef.current = false;
  }, [pluginId]);

  useEffect(() => {
    if (config.data && !hasSeededRef.current) {
      setFormValue(config.data as Record<string, unknown>);
      hasSeededRef.current = true;
    }
  }, [config.data]);

  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={() => void refetch()} />;

  const plugin = (plugins ?? []).find((p) => p.id === pluginId);
  if (!plugin) return <EmptyState message={t('notFound')} />;

  const schema = plugin.manifest?.config_schema as JsonSchema | undefined;
  const customComponent = plugin.manifest?.frontend?.component;
  const CustomComponent = customComponent === 'component.tsx' ? RulesUI : null;
  if (!schema && !CustomComponent) return <EmptyState message={t('noSchema')} />;

  async function onSubmit(value: unknown) {
    if (!pluginId) return;
    try {
      const saved = (await saveConfig.mutateAsync((value ?? {}) as Record<string, unknown>)) as Record<string, unknown>;
      setFormValue(saved);
      hasSeededRef.current = true;
      notifySuccess(t('configSaved'));
    } catch (error) {
      notifyApiError(
        error,
        t('saveFailed'),
        error instanceof ApiError && error.errors && error.errors.length > 0
          ? t('saveFailedWithErrors', { count: error.errors.length })
          : undefined,
      );
    }
  }

  return (
    <Stack gap="md">
      <Title order={3}>{plugin.name}</Title>
      {config.isPending ? (
        <LoadingState />
      ) : config.isError ? (
        <ErrorState onRetry={() => void config.refetch()} />
      ) : CustomComponent ? (
        <CustomComponent pluginId={plugin.id} scope={scope} />
      ) : (
        <JsonSchemaForm
          schema={schema!}
          value={formValue}
          onChange={(next) => setFormValue((next ?? {}) as Record<string, unknown>)}
          errors={saveConfig.error instanceof ApiError ? mapFieldErrors(saveConfig.error.errors) : {}}
        />
      )}
      {!CustomComponent && (
        <Group justify="flex-end">
          <Button onClick={() => void onSubmit(formValue)} loading={saveConfig.isPending}>
            {t('save')}
          </Button>
        </Group>
      )}
    </Stack>
  );
}
