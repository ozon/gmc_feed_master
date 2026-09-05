import { ActionIcon, Badge, Card, Group, Stack, Switch, Text, UnstyledButton } from '@mantine/core';
import { IconGripVertical } from '@tabler/icons-react';
import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { useUpdatePluginEnabled } from '../../api/hooks';
import { notifyError, notifyMutationError } from '../../app/notifications';
import { ConfirmModal } from '../../components/ConfirmModal';
import { getPluginIcon } from '../../components/PluginIconMap';
import type { PluginInfo } from '../../api/types';
import type { LocalInstance } from './dndUtils';

type Props = {
  instances: LocalInstance[];
  plugins: PluginInfo[];
  selectedClientId: string | null;
  onSelect: (clientId: string) => void;
  onToggleEnabled: (clientId: string, next: boolean) => void;
  onAdd: (pluginId: string) => void;
  onReorderDragEnd: (event: DragEndEvent) => void;
};

export function PluginList({
  instances, plugins, selectedClientId, onSelect, onToggleEnabled, onAdd,
  onReorderDragEnd,
}: Props) {
  const { t } = useTranslation('pipeline');
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  return (
    <Stack gap="md" data-testid="plugin-list">
      <Text fw={600} size="sm">{t('instances')}</Text>
      <DndContext sensors={sensors} onDragEnd={onReorderDragEnd}>
        <SortableContext items={instances.map((i) => i.clientId)} strategy={verticalListSortingStrategy}>
          {instances.map((instance) => (
            <InstanceRow
              key={instance.clientId}
              instance={instance}
              plugin={plugins.find((p) => p.id === instance.plugin_id)}
              selected={instance.clientId === selectedClientId}
              onSelect={() => onSelect(instance.clientId)}
              onToggleEnabled={(next) => onToggleEnabled(instance.clientId, next)}
            />
          ))}
        </SortableContext>
      </DndContext>
      <AddFromRegistry instances={instances} plugins={plugins} onAdd={onAdd} />
      <RegistrySection plugins={plugins} />
    </Stack>
  );
}

function InstanceRow({
  instance, plugin, selected, onSelect, onToggleEnabled,
}: {
  instance: LocalInstance;
  plugin: PluginInfo | undefined;
  selected: boolean;
  onSelect: () => void;
  onToggleEnabled: (next: boolean) => void;
}) {
  const { t } = useTranslation('pipeline');
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: instance.clientId,
    data: { source: 'workspace' },
  });
  const Icon = getPluginIcon(plugin?.manifest?.frontend?.icon);
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 };
  return (
    <Card
      ref={setNodeRef}
      style={style}
      withBorder
      p="xs"
      data-testid={`plugin-row-${instance.clientId}`}
      data-selected={selected}
      onClick={onSelect}
    >
      <Group gap="xs" wrap="nowrap">
        <ActionIcon
          variant="subtle"
          {...attributes}
          {...listeners}
          aria-label={t('dragHandle')}
          data-testid={`drag-handle-${instance.clientId}`}
        >
          <IconGripVertical size={16} />
        </ActionIcon>
        <Icon size={16} />
        <Text size="sm" fw={selected ? 600 : 400} style={{ flex: 1 }}>{instance.name}</Text>
        <Switch
          checked={instance.enabled}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => {
            e.stopPropagation();
            onToggleEnabled(e.currentTarget.checked);
          }}
          data-testid={`plugin-toggle-${instance.clientId}`}
        />
      </Group>
    </Card>
  );
}

function AddFromRegistry({
  instances, plugins, onAdd,
}: {
  instances: LocalInstance[];
  plugins: PluginInfo[];
  onAdd: (pluginId: string) => void;
}) {
  const { t } = useTranslation('pipeline');
  const pipelineModules = plugins.filter(
    (p) => p.manifest?.extension_point === 'pipeline_module' && p.enabled,
  );
  const present = new Set(instances.map((i) => i.plugin_id));
  const available = pipelineModules.filter((p) => !present.has(p.id));
  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed" tt="uppercase">{t('addFromRegistry')}</Text>
      {available.length === 0 ? (
        <Text size="xs" c="dimmed">{t('paletteEmpty')}</Text>
      ) : (
        available.map((plugin) => {
          const Icon = getPluginIcon(plugin.manifest?.frontend?.icon);
          return (
            <UnstyledButton
              key={plugin.id}
              onClick={() => onAdd(plugin.id)}
              data-testid={`add-plugin-${plugin.id}`}
            >
              <Group gap="xs" wrap="nowrap">
                <Icon size={14} />
                <Text size="sm">{t('addPlugin', { name: plugin.name })}</Text>
              </Group>
            </UnstyledButton>
          );
        })
      )}
    </Stack>
  );
}

function RegistrySection({ plugins }: { plugins: PluginInfo[] }) {
  const { t } = useTranslation('pipeline');
  const [pendingToggle, setPendingToggle] = useState<PluginInfo | null>(null);
  const toggleEnabled = useUpdatePluginEnabled();

  function mutateToggle(plugin: PluginInfo, enabled: boolean) {
    toggleEnabled.mutate(
      { id: plugin.id, enabled },
      {
        onError: (error) => {
          if (error instanceof ApiError && error.status === 409) {
            notifyError(t('disableBlocked', { count: plugin.used_by_feed_sources }));
          } else {
            notifyMutationError(error, t('disableFailed'));
          }
        },
      },
    );
  }

  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed" tt="uppercase">{t('registry')}</Text>
      <Text size="xs" c="dimmed">{t('registryToggleHelp')}</Text>
      {plugins.map((plugin) => {
        const Icon = getPluginIcon(plugin.manifest?.frontend?.icon);
        return (
          <Group key={plugin.id} justify="space-between" wrap="nowrap">
            <Group gap="xs" wrap="nowrap">
              <Icon size={14} />
              <Stack gap={0}>
                <Text size="sm">{plugin.name}</Text>
                <Group gap={4}>
                  <Badge size="xs" variant="light">v{plugin.version}</Badge>
                  {plugin.used_by_feed_sources > 0 ? (
                    <Badge size="xs" color="orange" variant="light">
                      {t('inUse', { count: plugin.used_by_feed_sources })}
                    </Badge>
                  ) : null}
                </Group>
              </Stack>
            </Group>
            <Switch
              checked={plugin.enabled}
              onChange={(event) => {
                const next = event.currentTarget.checked;
                if (!next && plugin.used_by_feed_sources > 0) {
                  setPendingToggle(plugin);
                  return;
                }
                mutateToggle(plugin, next);
              }}
              data-testid={`registry-toggle-${plugin.id}`}
            />
          </Group>
        );
      })}
      <ConfirmModal
        opened={Boolean(pendingToggle)}
        onClose={() => setPendingToggle(null)}
        title={t('disableConfirmTitle', { name: pendingToggle?.name ?? '' })}
        message={t('disableConfirmBody', { name: pendingToggle?.name ?? '' })}
        confirmLabel={t('disable')}
        danger
        typeToConfirm={pendingToggle ? String(pendingToggle.used_by_feed_sources) : undefined}
        onConfirm={() => {
          if (!pendingToggle) return;
          const plugin = pendingToggle;
          setPendingToggle(null);
          mutateToggle(plugin, false);
        }}
      />
    </Stack>
  );
}
