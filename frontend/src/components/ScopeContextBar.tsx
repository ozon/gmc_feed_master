import { Group, Paper, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ScopeBadge } from './ScopeBadge';
import type { Tier } from '../types/scope';

type Props = {
  current: Tier;
  configTiers: Tier[];
  dataTiers: Tier[];
  configLabel: string;
  dataLabel: string;
};

export function ScopeContextBar({ current, configTiers, dataTiers, configLabel, dataLabel }: Props) {
  const { t } = useTranslation();
  return (
    <Paper
      withBorder
      p="xs"
      mb="sm"
      data-testid="scope-context-bar"
      style={{ position: 'sticky', top: 4, zIndex: 1 }}
    >
      <Group gap="lg" wrap="nowrap">
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" c="dimmed">{t('scope.viewing')}</Text>
          <ScopeBadge tier={current} filled />
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" c="dimmed">{configLabel}</Text>
          {configTiers.map((tier) => (
            <ScopeBadge key={tier} tier={tier} filled={tier === current} />
          ))}
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" c="dimmed">{dataLabel}</Text>
          {dataTiers.length === 0 ? (
            <Text size="sm" c="dimmed">—</Text>
          ) : (
            dataTiers.map((tier) => (
              <ScopeBadge key={tier} tier={tier} filled={tier === current} />
            ))
          )}
        </Group>
      </Group>
    </Paper>
  );
}
