import { Accordion, Badge, Group, Stack, Switch, Text } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useUpdatePluginEnabled } from '../../api/hooks';
import { ConfirmModal } from '../../components/ConfirmModal';
import { getPluginIcon } from '../../components/PluginIconMap';
import type { PluginInfo } from '../../api/types';
import { loadRegistryPanelOpen, saveRegistryPanelOpen } from './registryPanelState';

type Props = {
  plugins: PluginInfo[];
};

export function PluginRegistryPanel({ plugins }: Props) {
  const { t } = useTranslation('pipeline');
  const [open, setOpen] = useState<boolean>(() => loadRegistryPanelOpen());
  const [pendingToggle, setPendingToggle] = useState<PluginInfo | null>(null);
  const toggleEnabled = useUpdatePluginEnabled();

  function onChange(plugin: PluginInfo, next: boolean) {
    if (!next && plugin.used_by_feed_sources > 0) {
      setPendingToggle(plugin);
      return;
    }
    toggleEnabled.mutate({ id: plugin.id, enabled: next });
  }

  function confirmToggle() {
    if (!pendingToggle) return;
    toggleEnabled.mutate({ id: pendingToggle.id, enabled: false });
    setPendingToggle(null);
  }

  return (
    <>
      <Accordion
        variant="separated"
        value={open ? 'registry' : null}
        onChange={(value) => {
          const next = value === 'registry';
          setOpen(next);
          saveRegistryPanelOpen(next);
        }}
      >
        <Accordion.Item value="registry">
          <Accordion.Control data-testid="registry-panel-control">
            <Group justify="space-between">
              <Text fw={600}>{t('registryPanel')}</Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="xs">
              <Text size="xs" c="dimmed">
                {t('registryHelp')}
              </Text>
              {plugins.map((plugin) => {
                const Icon = getPluginIcon(plugin.manifest?.frontend?.icon);
                return (
                  <Group key={plugin.id} justify="space-between" wrap="nowrap">
                    <Group gap="xs" wrap="nowrap">
                      <Icon size={16} />
                      <Stack gap={0}>
                        <Text size="sm">{plugin.name}</Text>
                        <Group gap="xs">
                          <Badge size="xs" variant="light">
                            v{plugin.version}
                          </Badge>
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
                      onChange={(event) => onChange(plugin, event.currentTarget.checked)}
                      data-testid={`plugin-toggle-${plugin.id}`}
                    />
                  </Group>
                );
              })}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
      <ConfirmModal
        opened={Boolean(pendingToggle)}
        onClose={() => setPendingToggle(null)}
        title={t('disableConfirmTitle', { name: pendingToggle?.name ?? '' })}
        message={t('disableConfirmBody', { name: pendingToggle?.name ?? '' })}
        confirmLabel={t('disable')}
        danger
        typeToConfirm={pendingToggle ? String(pendingToggle.used_by_feed_sources) : undefined}
        onConfirm={confirmToggle}
      />
    </>
  );
}