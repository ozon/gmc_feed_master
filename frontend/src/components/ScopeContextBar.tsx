import { Anchor, Group, Paper, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ScopeBadge } from './ScopeBadge';
import type { Tier } from '../types/scope';

type Props = {
  current: Tier;
  configTiers: Tier[];
  dataTiers: Tier[];
  configLabel: string;
  dataLabel: string;
  hrefs?: Partial<Record<Tier, string>>;
};

function TierBadge({
  tier, filled, href,
}: { tier: Tier; filled: boolean; href?: string }) {
  if (!href) return <ScopeBadge tier={tier} filled={filled} />;
  return (
    <Anchor
      component={Link}
      to={href}
      underline="never"
      data-testid={`scope-link-${tier}`}
    >
      <ScopeBadge tier={tier} filled={filled} />
    </Anchor>
  );
}

export function ScopeContextBar({
  current, configTiers, dataTiers, configLabel, dataLabel, hrefs,
}: Props) {
  const { t } = useTranslation();
  const badgeFor = (tier: Tier, filled: boolean) => (
    <TierBadge tier={tier} filled={filled} href={tier !== current ? hrefs?.[tier] : undefined} />
  );
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
            <span key={`config-${tier}`}>{badgeFor(tier, tier === current)}</span>
          ))}
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" c="dimmed">{dataLabel}</Text>
          {dataTiers.length === 0 ? (
            <Text size="sm" c="dimmed">—</Text>
          ) : (
            dataTiers.map((tier) => (
              <span key={`data-${tier}`}>{badgeFor(tier, tier === current)}</span>
            ))
          )}
        </Group>
      </Group>
    </Paper>
  );
}
