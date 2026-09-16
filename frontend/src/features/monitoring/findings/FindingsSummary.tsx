import { Badge, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { SEVERITIES } from './severity';

type Props = {
  counts: { critical: number; warning: number; info: number };
  delta: { fixed: number; new: number; remaining: number };
  hasPrevious: boolean;
  productCount: number;
};

export function FindingsSummary({ counts, delta, hasPrevious, productCount }: Props) {
  const { t } = useTranslation('monitoring');
  return (
    <SimpleGrid cols={{ base: 1, sm: 3 }}>
      {SEVERITIES.map((severity) => (
        <Paper key={severity} p="md" radius="md" withBorder data-testid={`card-${severity}`}>
          <Stack gap={4}>
            <Text size="sm" c="dimmed">
              {t(`severity.${severity}`)}
            </Text>
            <Text size="xl" fw={700}>
              {counts[severity]}
            </Text>
            {hasPrevious && (
              <Group gap="xs">
                <Badge color="green" data-testid="delta-fixed">↓ {delta.fixed}</Badge>
                <Badge color="red" data-testid="delta-new">↑ {delta.new}</Badge>
              </Group>
            )}
          </Stack>
        </Paper>
      ))}
      <Text size="sm" c="dimmed" data-testid="of-products">
        {t('quality.ofProducts', { count: productCount })}
      </Text>
    </SimpleGrid>
  );
}
