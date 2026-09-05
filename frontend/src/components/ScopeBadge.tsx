import { Badge, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { Tier } from '../types/scope';

const TIER_COLORS: Record<Tier, string> = {
  global: 'violet',
  client: 'blue',
  feed_source: 'teal',
};

export function ScopeBadge({ tier, filled = false }: { tier: Tier; filled?: boolean }) {
  const { t } = useTranslation();
  return (
    <Tooltip label={t(`scope.${tier}Hint`)} position="top" withArrow>
      <Badge
        size="xs"
        variant={filled ? 'filled' : 'light'}
        color={TIER_COLORS[tier]}
        data-testid={`scope-badge-${tier}`}
      >
        {t(`scope.${tier}`)}
      </Badge>
    </Tooltip>
  );
}
