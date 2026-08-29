import { ActionIcon, Card, Group, Stack, Text } from '@mantine/core';
import { IconGripVertical, IconTrash } from '@tabler/icons-react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useTranslation } from 'react-i18next';
import { JsonSchemaForm, type JsonSchema } from '../../components/JsonSchemaForm';
import type { LocalInstance } from './dndUtils';

type Props = {
  instance: LocalInstance;
  schema: JsonSchema | null;
  onChange: (next: Record<string, unknown>) => void;
  onRemove: () => void;
};

export function PipelineInstanceCard({ instance, schema, onChange, onRemove }: Props) {
  const { t } = useTranslation('pipeline');
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: instance.clientId,
    data: { source: 'workspace' },
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  return (
    <Card
      ref={setNodeRef}
      style={style}
      withBorder
      p="sm"
      data-testid={`pipeline-instance-${instance.clientId}`}
    >
      <Stack gap="sm">
        <Group justify="space-between">
          <Group gap="xs">
            <ActionIcon
              variant="subtle"
              {...attributes}
              {...listeners}
              aria-label={t('dragHandle')}
              data-testid={`drag-handle-${instance.clientId}`}
            >
              <IconGripVertical size={16} />
            </ActionIcon>
            <Text fw={500}>{instance.name}</Text>
          </Group>
          <ActionIcon
            variant="subtle"
            color="red"
            onClick={onRemove}
            aria-label={t('remove')}
            data-testid={`remove-${instance.clientId}`}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Group>
        {schema ? (
          <JsonSchemaForm
            schema={schema}
            value={instance.configuration}
            onChange={(next) => onChange((next ?? {}) as Record<string, unknown>)}
          />
        ) : null}
      </Stack>
    </Card>
  );
}