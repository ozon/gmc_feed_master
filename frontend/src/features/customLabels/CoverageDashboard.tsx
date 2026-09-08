import { Badge, Card, Group, Loader, Progress, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { PreviewRuleStats } from './usePreview';

export type CoverageDashboardProps = {
  total: number | undefined;
  labeledAny: number | undefined;
  activeRules: number;
  pending: boolean;
  errors: string[] | null;
  unavailable: boolean;
  slotRules: ReadonlyArray<{ id: string; name: string }>;
  ruleStats: Readonly<Record<string, PreviewRuleStats>> | undefined;
};

export function CoverageDashboard({
  total, labeledAny, activeRules, pending, errors, unavailable, slotRules, ruleStats,
}: CoverageDashboardProps) {
  const { t } = useTranslation('customLabels');
  if (unavailable) {
    return <Text size="xs" c="dimmed">{t('previewUnavailable')}</Text>;
  }
  if (errors) {
    return (
      <Stack gap={2}>
        {errors.map((error) => (
          <Text key={error} size="xs" c="dimmed">{error}</Text>
        ))}
      </Stack>
    );
  }
  if (total === 0) {
    return <Text size="xs" c="dimmed">{t('noStagedProducts')}</Text>;
  }
  if (total === undefined || labeledAny === undefined) {
    return pending ? <Loader size="xs" /> : null;
  }
  const pct = Math.min(100, Math.max(0, Math.round((labeledAny / total) * 100)));
  return (
    <Card withBorder p="sm" data-testid="coverage-dashboard">
      <Stack gap="xs">
        <Group gap="xs" wrap="nowrap">
          {pending && <Loader size="xs" />}
          <Text size="sm" fw={600}>
            {t('coverage.labeledOf', { count: labeledAny, total })}
          </Text>
        </Group>
        <Progress.Root size="sm" data-testid="coverage-progress">
          <Progress.Section value={pct} color="green" />
        </Progress.Root>
        {ruleStats !== undefined && slotRules.length > 0 && (
          <Group gap="xs" wrap="wrap" data-testid="coverage-rule-hits">
            {slotRules.map((rule, index) => (
              <Badge
                key={rule.id}
                size="xs"
                variant="light"
                data-testid={`coverage-rule-hit-${rule.id}`}
              >
                {t('coverage.ruleHits', {
                  priority: index + 1,
                  name: rule.name,
                  hits: ruleStats[rule.id]?.labeled ?? 0,
                })}
              </Badge>
            ))}
          </Group>
        )}
        <Group gap="lg" wrap="wrap">
          {([
            ['totalProducts', total, 'coverage-stat-total'],
            ['labeled', labeledAny, 'coverage-stat-labeled'],
            ['unlabeled', total - labeledAny, 'coverage-stat-unlabeled'],
            ['activeRules', activeRules, 'coverage-stat-active-rules'],
          ] as const).map(([label, count, testId]) => (
            <Stack key={testId} gap={0}>
              <Text size="xs" c="dimmed">{t(`coverage.${label}`)}</Text>
              <Text size="sm" fw={600} data-testid={testId}>{count}</Text>
            </Stack>
          ))}
        </Group>
      </Stack>
    </Card>
  );
}
