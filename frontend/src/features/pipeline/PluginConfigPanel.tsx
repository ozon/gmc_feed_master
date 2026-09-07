import { useEffect, useState } from 'react';
import {
  Alert, Anchor, Badge, Button, Divider, Group, SegmentedControl, Stack, Text, Title,
} from '@mantine/core';
import { IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { JsonSchemaForm, type JsonSchema } from '../../components/JsonSchemaForm';
import type { PluginInfo } from '../../api/types';
import { CUSTOM_COMPONENTS } from '../plugin/customComponents';
import { CONFIG_COMPONENTS } from '../plugin/configComponents';
import { PluginErrorBoundary } from '../plugin/PluginErrorBoundary';
import {
  configEditableAtFeed, highestEditableConfigTier, scopeForTier, tierOptions,
  type ConfigTier,
} from './tierUtils';
import type { LocalInstance } from './dndUtils';

type Props = {
  instance: LocalInstance | null;
  plugin: PluginInfo | undefined;
  clientId?: string;
  feedSourceId?: string;
  onChange: (next: Record<string, unknown>) => void;
  onRemove: () => void;
};

export function PluginConfigPanel({
  instance, plugin, clientId, feedSourceId, onChange, onRemove,
}: Props) {
  const { t } = useTranslation('pipeline');
  const { t: tCommon } = useTranslation('common');
  const [draft, setDraft] = useState<Record<string, unknown>>(instance?.configuration ?? {});
  const [selectedTier, setSelectedTier] = useState<ConfigTier>('feed_source');

  useEffect(() => {
    setDraft(instance?.configuration ?? {});
  }, [instance?.configuration]);

  // Reset the tier when switching instances — each plugin starts at Feed scope.
  useEffect(() => {
    setSelectedTier('feed_source');
  }, [instance?.clientId]);

  if (!instance) {
    return (
      <Text c="dimmed" data-testid="config-panel" ta="center" py="xl">
        {t('configSelectPlugin')}
      </Text>
    );
  }

  const schema = (plugin?.manifest?.config_schema as JsonSchema | undefined) ?? null;
  const SetupComponent = plugin
    ? CONFIG_COMPONENTS[plugin.id] ?? null
    : null;
  const PageComponent = plugin?.manifest?.frontend?.component
    ? CUSTOM_COMPONENTS[plugin.id] ?? null
    : null;
  const pageOnly = PageComponent !== null && SetupComponent === null;
  const declaredTiers = SetupComponent && plugin
    ? tierOptions(plugin.manifest, {
        hasFeedSource: Boolean(feedSourceId),
        hasClient: Boolean(clientId),
      })
    : [];
  const tiers: ConfigTier[] = declaredTiers.length > 0 ? declaredTiers : ['global'];
  const tier = tiers.includes(selectedTier) ? selectedTier : tiers[0];
  const readOnlyTarget = SetupComponent && plugin && tier === 'feed_source'
    && !configEditableAtFeed(plugin.manifest)
    ? highestEditableConfigTier(plugin.manifest)
    : null;

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
      {SetupComponent && plugin ? (
        <>
          <Group justify="space-between" wrap="nowrap">
            <Title order={5}>{t('configPluginSection')}</Title>
            <SegmentedControl
              size="xs"
              data={tiers.map((value) => ({ value, label: tCommon(`scope.${value}`) }))}
              value={tier}
              onChange={(value) => setSelectedTier(value as ConfigTier)}
              data-testid="config-tier-switcher"
            />
          </Group>
          {readOnlyTarget !== null ? (
            <Alert color="blue" data-testid="config-readonly-alert">
              <Group justify="space-between" wrap="nowrap">
                <Text size="sm">
                  {t('configReadOnlyBody', { tier: tCommon(`scope.${readOnlyTarget}`) })}
                </Text>
                <Button
                  size="xs"
                  variant="light"
                  onClick={() => setSelectedTier(readOnlyTarget)}
                >
                  {t('configSwitchTier', { tier: tCommon(`scope.${readOnlyTarget}`) })}
                </Button>
              </Group>
            </Alert>
          ) : null}
          <PluginErrorBoundary pluginName={plugin.name}>
            <SetupComponent
              key={`${instance.plugin_id}-${tier}`}
              pluginId={instance.plugin_id}
              scope={scopeForTier(tier, { clientId, feedSourceId })}
            />
          </PluginErrorBoundary>
          <Divider />
        </>
      ) : null}
      {pageOnly && plugin ? (
        <Group justify="space-between" wrap="nowrap" data-testid="config-plugin-page-hint">
          <Text size="sm" c="dimmed">{t('configOnPluginPage')}</Text>
          {clientId && feedSourceId ? (
            <Anchor
              component={Link}
              to={`/clients/${clientId}/feeds/${feedSourceId}/plugins/${plugin.id}`}
              underline="never"
            >
              <Button size="xs" variant="light">{t('configOpenPluginPage')}</Button>
            </Anchor>
          ) : null}
        </Group>
      ) : null}
      {!pageOnly ? (
        <>
          <Title order={5}>{t('configInstanceSection')}</Title>
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
        </>
      ) : null}
    </Stack>
  );
}
