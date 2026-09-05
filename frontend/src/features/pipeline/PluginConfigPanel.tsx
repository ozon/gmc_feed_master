import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Group, Stack, Text, Title } from '@mantine/core';
import { IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { JsonSchemaForm, type JsonSchema } from '../../components/JsonSchemaForm';
import type { PluginInfo } from '../../api/types';
import type { LocalInstance } from './dndUtils';

type Props = {
  instance: LocalInstance | null;
  plugin: PluginInfo | undefined;
  onChange: (next: Record<string, unknown>) => void;
  onRemove: () => void;
};

export function PluginConfigPanel({ instance, plugin, onChange, onRemove }: Props) {
  const { t } = useTranslation('pipeline');
  const [draft, setDraft] = useState<Record<string, unknown>>(instance?.configuration ?? {});
  useEffect(() => {
    setDraft(instance?.configuration ?? {});
  }, [instance?.configuration]);
  if (!instance) {
    return (
      <Text c="dimmed" data-testid="config-panel" ta="center" py="xl">
        {t('configSelectPlugin')}
      </Text>
    );
  }
  const schema = (plugin?.manifest?.config_schema as JsonSchema | undefined) ?? null;
  return (
    <Stack gap="md" data-testid="config-panel">
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={4}>{instance.name}</Title>
          {plugin ? <Badge size="sm" variant="light">v{plugin.version}</Badge> : null}
        </Group>
        <Button
          variant="light"
          color="red"
          leftSection={<IconTrash size={14} />}
          onClick={onRemove}
        >
          {t('configRemove')}
        </Button>
      </Group>
      {!instance.enabled ? (
        <Alert color="yellow">{t('configDisabledInfo')}</Alert>
      ) : null}
      {schema ? (
        <JsonSchemaForm
          schema={schema}
          value={draft}
          onChange={(next) => {
            const merged = (next ?? {}) as Record<string, unknown>;
            setDraft(merged);
            onChange(merged);
          }}
        />
      ) : (
        <Text c="dimmed" size="sm">{t('configNoSchema')}</Text>
      )}
    </Stack>
  );
}
