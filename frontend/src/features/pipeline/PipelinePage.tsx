import { Button, Grid, Group, Stack, Title } from '@mantine/core';
import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  useFeedSourcePipeline,
  usePlugins,
  useSavePipeline,
} from '../../api/hooks';
import type { PipelineInstance } from '../../api/types';
import { ErrorState, LoadingState } from '../../components/StateViews';
import { notifySuccess, notifyApiError } from '../../app/notifications';
import { ApiError } from '../../api/client';
import { useBlocker } from 'react-router';
import { PluginPalette } from './PluginPalette';
import { PipelineWorkspace } from './PipelineWorkspace';
import { PluginRegistryPanel } from './PluginRegistryPanel';
import { applyDragEnd, isInstancesEqual, removeInstance, type LocalInstance } from './dndUtils';

function toLocal(instances: PipelineInstance[]): LocalInstance[] {
  return instances.map((instance) => ({
    ...instance,
    clientId: `${instance.plugin_id}-${instance.position}`,
  }));
}

function toServer(instances: LocalInstance[]): PipelineInstance[] {
  return instances.map(({ clientId: _clientId, ...rest }, index) => ({ ...rest, position: index }));
}

export function PipelinePage() {
  const { t } = useTranslation('pipeline');
  const { t: tCommon } = useTranslation('common');
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const pipeline = useFeedSourcePipeline(id);
  const savePipeline = useSavePipeline(id);
  const { data: plugins } = usePlugins();

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const [local, setLocal] = useState<LocalInstance[]>([]);
  const [hydrated, setHydrated] = useState(false);

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

  useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty) return false;
    if (currentLocation.pathname === nextLocation.pathname) return false;
    return !window.confirm(t('unsavedChanges'));
  });

  const pipelineModules = (plugins ?? []).filter(
    (p) => p.manifest?.extension_point === 'pipeline_module' && p.enabled,
  );

  function onDragEnd(event: DragEndEvent) {
    const next = applyDragEnd(local, event);
    if (next) setLocal(next);
  }

  async function onSave() {
    try {
      await savePipeline.mutateAsync({ instances: toServer(local) });
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

  if (pipeline.isPending) return <LoadingState />;
  if (pipeline.isError) return <ErrorState onRetry={() => void pipeline.refetch()} />;

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
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
        <Grid>
          <Grid.Col span={3}>
            <PluginPalette plugins={pipelineModules} />
          </Grid.Col>
          <Grid.Col span={9}>
            <PipelineWorkspace
              instances={local}
              plugins={plugins ?? []}
              onChangeInstance={(clientId, configuration) =>
                setLocal((prev) =>
                  prev.map((i) => (i.clientId === clientId ? { ...i, configuration } : i)),
                )
              }
              onRemoveInstance={(clientId) => setLocal((prev) => removeInstance(prev, clientId))}
            />
          </Grid.Col>
        </Grid>
        <PluginRegistryPanel plugins={plugins ?? []} />
      </Stack>
    </DndContext>
  );
}
