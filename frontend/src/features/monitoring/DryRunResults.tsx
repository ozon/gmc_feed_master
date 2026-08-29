import { Card, Code, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { FindingsTable, type QualityFinding } from './FindingsTable';

type Props = {
  result: unknown;
};

type DryRunResult = {
  processed?: number;
  dropped?: number;
  findings?: QualityFinding[];
  error_message?: string;
};

export function DryRunResults({ result }: Props) {
  const { t } = useTranslation('monitoring');
  const r = result as DryRunResult;
  if (!r) return null;
  return (
    <Card withBorder p="md" data-testid="dry-run-results">
      <Stack gap="sm">
        <Title order={5}>{t('dryRun.results')}</Title>
        <Text size="sm">{t('dryRun.processed', { count: r.processed ?? 0 })}</Text>
        <Text size="sm" c={r.dropped ? 'red' : undefined}>
          {t('dryRun.dropped', { count: r.dropped ?? 0 })}
        </Text>
        {r.error_message ? (
          <Code block>{r.error_message}</Code>
        ) : null}
        {r.findings && r.findings.length > 0 ? <FindingsTable findings={r.findings} /> : null}
      </Stack>
    </Card>
  );
}