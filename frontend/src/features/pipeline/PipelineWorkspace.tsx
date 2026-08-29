import { Stack, Text } from '@mantine/core';
import { useDroppable } from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { useTranslation } from 'react-i18next';
import { PipelineInstanceCard } from './PipelineInstanceCard';
import type { LocalInstance } from './dndUtils';
import type { PluginInfo } from '../../api/types';
import type { JsonSchema } from '../../components/JsonSchemaForm';

type Props = {
  instances: LocalInstance[];
  plugins: PluginInfo[];
  onChangeInstance: (clientId: string, configuration: Record<string, unknown>) => void;
  onRemoveInstance: (clientId: string) => void;
};

export function PipelineWorkspace({
  instances,
  plugins,
  onChangeInstance,
  onRemoveInstance,
}: Props) {
  const { t } = useTranslation('pipeline');
  const { setNodeRef, isOver } = useDroppable({ id: 'workspace-droppable' });
  const schemaFor = (pluginId: string): JsonSchema | null => {
    const p = plugins.find((x) => x.id === pluginId);
    return (p?.manifest?.config_schema as JsonSchema | undefined) ?? null;
  };
  return (
    <Stack
      ref={setNodeRef}
      gap="sm"
      p="md"
      data-testid="pipeline-workspace"
      style={{ minHeight: 200, outline: isOver ? '2px dashed var(--mantine-color-blue-5)' : 'none' }}
    >
      {instances.length === 0 ? (
        <Text c="dimmed" ta="center" py="xl">
          {t('emptyWorkspace')}
        </Text>
      ) : (
        <SortableContext items={instances.map((i) => i.clientId)} strategy={verticalListSortingStrategy}>
          {instances.map((instance) => (
            <PipelineInstanceCard
              key={instance.clientId}
              instance={instance}
              schema={schemaFor(instance.plugin_id)}
              onChange={(next) => onChangeInstance(instance.clientId, next)}
              onRemove={() => onRemoveInstance(instance.clientId)}
            />
          ))}
        </SortableContext>
      )}
    </Stack>
  );
}