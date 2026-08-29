import { Card, Group, Stack, Text } from '@mantine/core';
import { useDraggable } from '@dnd-kit/core';
import { useTranslation } from 'react-i18next';
import type { PluginInfo } from '../../api/types';
import { getPluginIcon } from '../../components/PluginIconMap';

type Props = {
  plugins: PluginInfo[];
};

export function PluginPalette({ plugins }: Props) {
  const { t } = useTranslation('pipeline');
  return (
    <Stack gap="xs" data-testid="plugin-palette">
      <Text fw={600} size="sm">
        {t('palette')}
      </Text>
      {plugins.length === 0 ? (
        <Text c="dimmed" size="sm">
          {t('paletteEmpty')}
        </Text>
      ) : (
        plugins.map((plugin) => <PaletteCard key={plugin.id} plugin={plugin} />)
      )}
    </Stack>
  );
}

function PaletteCard({ plugin }: { plugin: PluginInfo }) {
  const { t } = useTranslation('pipeline');
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `palette-${plugin.id}`,
    data: { source: 'palette', plugin },
  });
  const Icon = getPluginIcon(plugin.manifest?.frontend?.icon);
  return (
    <Card
      ref={setNodeRef}
      withBorder
      p="sm"
      style={{ cursor: 'grab', opacity: isDragging ? 0.5 : 1 }}
      {...attributes}
      {...listeners}
      data-testid={`palette-card-${plugin.id}`}
    >
      <Group gap="xs">
        <Icon size={16} />
        <Stack gap={0}>
          <Text size="sm" fw={500}>
            {plugin.name}
          </Text>
          <Text size="xs" c="dimmed">
            {t('dragToAdd')}
          </Text>
        </Stack>
      </Group>
    </Card>
  );
}