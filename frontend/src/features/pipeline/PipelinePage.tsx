import { Grid, Group, Button, Stack, Title } from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import { useBlocker, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../../api/queryKeys';
import { useFeedSourcePipeline, usePatchPipelineInstance, usePlugins, useSavePipeline } from '../../api/hooks';
import { ApiError } from '../../api/client';
import type { PipelineDoc, PipelineInstance } from '../../api/types';
import { ErrorState, LoadingState } from '../../components/StateViews';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { PluginConfigPanel } from './PluginConfigPanel';
import { PluginList } from './PluginList';
import { PipelineOverviewStrip } from './PipelineOverviewStrip';
import { addInstance, applyDragEnd, isInstancesEqual, removeInstance, type LocalInstance } from './dndUtils';

function toLocal(instances: PipelineInstance[]): LocalInstance[] {
  // clientId is position-based (matches addInstance's minted ids and keeps
  // testids stable in tests). Use index, not id: two unsaved rows of the same
  // plugin must not collide, and server ids may be null for new rows.
  const taken = new Set<string>();
  return instances.map((instance, index) => {
    let clientId = `${instance.plugin_id}-${index}`;
    while (taken.has(clientId)) clientId = `${clientId}x`;
    taken.add(clientId);
    return { ...instance, clientId };
  });
}

function toServer(instances: LocalInstance[]): PipelineDoc {
  return {
    instances: instances.map(({ clientId: _clientId, ...rest }, index) => ({
      ...rest,
      position: index,
    })),
  };
}

export function PipelinePage() {
  const { t } = useTranslation('pipeline');
  const { t: tCommon } = useTranslation('common');
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const pipeline = useFeedSourcePipeline(id);
  const savePipeline = useSavePipeline(id);
  const patchInstance = usePatchPipelineInstance(id);
  const { data: plugins } = usePlugins();
  const queryClient = useQueryClient();

  const [local, setLocal] = useState<LocalInstance[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);

  useEffect(() => {
    if (pipeline.data && !hydrated) {
      setLocal(toLocal(pipeline.data.instances));
      setHydrated(true);
    }
  }, [pipeline.data, hydrated]);

  const serverSnapshot: LocalInstance[] = useMemo(
    () => (pipeline.data ? toLocal(pipeline.data.instances) : []),
    [pipeline.data],
  );

  const dirty = !isInstancesEqual(local, serverSnapshot);
  const selected = local.find((i) => i.clientId === selectedClientId) ?? local[0] ?? null;

  useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty) return false;
    if (currentLocation.pathname === nextLocation.pathname) return false;
    return !window.confirm(t('unsavedChanges'));
  });

  async function onSave() {
    try {
      await savePipeline.mutateAsync(toServer(local));
      notifySuccess(t('saved'));
      setHydrated(false);
    } catch (error) {
      notifyApiError(
        error,
        t('saveFailed'),
        error instanceof ApiError && error.errors && error.errors.length > 0
          ? t('saveFailedWithErrors', { errors: error.errors.join('; ') })
          : undefined,
      );
    }
  }

  function onReset() {
    if (!pipeline.data) return;
    setLocal(toLocal(pipeline.data.instances));
    setHydrated(true);
  }

  function onToggleEnabled(clientId: string, next: boolean) {
    const instance = local.find((i) => i.clientId === clientId);
    if (!instance || instance.id === null) {
      // unsaved instance: flip locally only (persisted with Save)
      setLocal((prev) => prev.map((i) => (i.clientId === clientId ? { ...i, enabled: next } : i)));
      return;
    }
    const before = local;
    setLocal((prev) => prev.map((i) => (i.clientId === clientId ? { ...i, enabled: next } : i)));
    patchInstance.mutate(
      { instanceId: instance.id, enabled: next },
      {
        onError: (error) => {
          setLocal(before); // rollback
          notifyApiError(error, t('toggleFailed'));
          void queryClient.invalidateQueries({
            queryKey: queryKeys.feedSource(id).pipeline,
          }); // refetch — server state is source of truth after a failed PATCH
        },
      },
    );
  }

  function onAdd(pluginId: string) {
    const plugin = (plugins ?? []).find((p) => p.id === pluginId);
    if (!plugin) return;
    setLocal((prev) => addInstance(prev, { id: plugin.id, name: plugin.name }));
  }

  if (pipeline.isPending) return <LoadingState />;
  if (pipeline.isError) return <ErrorState onRetry={() => void pipeline.refetch()} />;

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={3}>{t('title')}</Title>
        <Group>
          <Button variant="default" onClick={onReset} disabled={!dirty}>
            {tCommon('actions.cancel')}
          </Button>
          <Button onClick={onSave} loading={savePipeline.isPending} disabled={!dirty}>
            {tCommon('actions.save')}
          </Button>
        </Group>
      </Group>
      <PipelineOverviewStrip instances={local} dirty={dirty} />
      <Grid>
        <Grid.Col span={4}>
          <PluginList
            instances={local}
            plugins={plugins ?? []}
            selectedClientId={selected?.clientId ?? null}
            onToggleEnabled={onToggleEnabled}
            onAdd={onAdd}
            onSelect={setSelectedClientId}
            onReorderDragEnd={(event) => {
              const next = applyDragEnd(local, event);
              if (next) setLocal(next);
            }}
          />
        </Grid.Col>
        <Grid.Col span={8}>
          <PluginConfigPanel
            key={selected?.clientId ?? 'none'}
            instance={selected}
            plugin={plugins?.find((p) => p.id === selected?.plugin_id)}
            onChange={(next) =>
              selected && setLocal((prev) => prev.map((i) =>
                i.clientId === selected.clientId ? { ...i, configuration: next } : i))
            }
            onRemove={() =>
              selected && setLocal((prev) => removeInstance(prev, selected.clientId))
            }
          />
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
