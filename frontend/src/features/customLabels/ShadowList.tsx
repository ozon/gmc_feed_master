import { Group, Stack, Text, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export function ShadowList({ shadowedBy }: { shadowedBy: ReadonlyMap<string, string> }) {
  const { t } = useTranslation('customLabels');
  if (shadowedBy.size === 0) return null;
  return (
    <Stack gap={4} data-testid="shadow-list">
      <Text size="xs" c="dimmed">{t('shadowListTitle')}</Text>
      <Group gap="xs" wrap="wrap">
        {[...shadowedBy].map(([value, ruleName]) => (
          <Tooltip
            key={value}
            label={t('shadowedBy', { name: ruleName })}
            withArrow
            position="top"
          >
            <Text size="xs" c="dimmed" style={{ textDecoration: 'line-through' }}>
              {value}
            </Text>
          </Tooltip>
        ))}
      </Group>
    </Stack>
  );
}
