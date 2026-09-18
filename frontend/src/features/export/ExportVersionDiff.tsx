import { Accordion, Badge, Card, Code, Group, SimpleGrid, Stack, Table, Text } from '@mantine/core';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import type { DiffOut, ExportVersionOut, FindingsDiffOut } from '../../api/types';
import { RuleLabel } from '../monitoring/findings/RuleLabel';
import { SeverityBadge } from '../monitoring/findings/SeverityBadge';

type Props = {
  diff: DiffOut | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  findingsA: ExportVersionOut['findings'];
  findingsB: ExportVersionOut['findings'];
};

function ValueCell({ value }: { value: unknown }) {
  const { t } = useTranslation('export');
  if (value === null || value === undefined) {
    return (
      <Text component="span" c="dimmed" size="sm">
        {t('diff.emptyValue')}
      </Text>
    );
  }
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  const shown = text.length > 120 ? `${text.slice(0, 120)}…` : text;
  return <Code title={text}>{shown}</Code>;
}

function FindingsDelta({
  a,
  b,
}: {
  a: ExportVersionOut['findings'];
  b: ExportVersionOut['findings'];
}) {
  const { t } = useTranslation('export');
  if (!a || !b) {
    return (
      <Text c="dimmed" size="sm">
        {t('diff.notQcd')}
      </Text>
    );
  }
  const severities = ['critical', 'warning', 'info'] as const;
  return (
    <Group gap="lg">
      {severities.map((severity) => {
        const delta = b[severity] - a[severity];
        return (
          <Stack key={severity} gap={0}>
            <Text size="xs" c="dimmed">
              {t(`findings.${severity}_other`, { count: b[severity] })}
            </Text>
            <Text fw={600} c={delta > 0 ? 'red' : delta < 0 ? 'green' : undefined}>
              {a[severity]} → {b[severity]}
            </Text>
          </Stack>
        );
      })}
    </Group>
  );
}

function FindingsDiffSection({ findings }: { findings: FindingsDiffOut }) {
  const { t } = useTranslation('export');
  if (!findings.a_qc || !findings.b_qc) {
    return (
      <Text c="dimmed" size="sm" data-testid="findings-diff">
        {t('findingsDiff.notQcd')}
      </Text>
    );
  }
  const hasChanges =
    findings.totals.added > 0 || findings.totals.fixed > 0 || findings.totals.persisted > 0;
  if (!hasChanges) {
    return (
      <Text c="dimmed" size="sm" data-testid="findings-diff">
        {t('findingsDiff.noChanges')}
      </Text>
    );
  }
  const buckets = ['added', 'fixed', 'persisted'] as const;
  return (
    <Stack gap="xs" data-testid="findings-diff">
      <Group gap="sm">
        <Badge color="red" variant="light">
          +{findings.totals.added} {t('findingsDiff.added')}
        </Badge>
        <Badge color="green" variant="light">
          -{findings.totals.fixed} {t('findingsDiff.fixed')}
        </Badge>
        <Badge color="gray" variant="light">
          ={findings.totals.persisted} {t('findingsDiff.persisted')}
        </Badge>
      </Group>
      <Accordion variant="contained">
        {findings.rules.map((rule) => (
          <Accordion.Item key={rule.code} value={rule.code}>
            <Accordion.Control>
              <Group justify="space-between">
                <Group gap="xs">
                  <RuleLabel code={rule.code} />
                  <SeverityBadge severity={rule.severity} />
                </Group>
                <Group gap="xs">
                  {rule.added > 0 ? (
                    <Text size="xs" c="red">
                      +{rule.added}
                    </Text>
                  ) : null}
                  {rule.fixed > 0 ? (
                    <Text size="xs" c="green">
                      -{rule.fixed}
                    </Text>
                  ) : null}
                  {rule.persisted > 0 ? (
                    <Text size="xs" c="dimmed">
                      ={rule.persisted}
                    </Text>
                  ) : null}
                </Group>
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap={4}>
                {buckets.map((bucket) => {
                  const samples: Record<(typeof buckets)[number], string[]> = {
                    added: rule.sample_added,
                    fixed: rule.sample_fixed,
                    persisted: rule.sample_persisted,
                  };
                  const ids = samples[bucket];
                  if (ids.length === 0) return null;
                  return (
                    <Group key={bucket} gap={4}>
                      <Text size="xs" c="dimmed">
                        {t(`findingsDiff.${bucket}`)}:
                      </Text>
                      {ids.map((id) => (
                        <Badge key={id} size="xs" variant="light">
                          {id}
                        </Badge>
                      ))}
                    </Group>
                  );
                })}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
    </Stack>
  );
}

export function ExportVersionDiff({
  diff,
  isPending,
  isError,
  onRetry,
  findingsA,
  findingsB,
}: Props) {
  const { t } = useTranslation('export');
  const [selectedField, setSelectedField] = useState<string | null>(null);
  const [prevDiff, setPrevDiff] = useState(diff);
  if (prevDiff !== diff) {
    setPrevDiff(diff);
    setSelectedField(null);
  }

  const fieldCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const product of diff?.changed ?? []) {
      for (const field of product.fields) {
        counts.set(field.field, (counts.get(field.field) ?? 0) + 1);
      }
    }
    // oxlint-disable-next-line unicorn/no-array-sort -- ES2022 target; toSorted() requires ES2023
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [diff?.changed]);

  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={onRetry} />;
  if (!diff) return <EmptyState message={t('selectVersions')} />;
  const findingsTotals = diff.findings?.totals ?? { added: 0, fixed: 0, persisted: 0 };
  const hasChanges =
    diff.added.length > 0 ||
    diff.removed.length > 0 ||
    diff.changed.length > 0 ||
    findingsTotals.added > 0 ||
    findingsTotals.fixed > 0 ||
    findingsTotals.persisted > 0 ||
    (diff.findings !== undefined && (!diff.findings.a_qc || !diff.findings.b_qc));
  if (!hasChanges) return <EmptyState message={t('noChanges')} />;

  const totalFields = diff.changed.reduce((sum, product) => sum + product.fields.length, 0);
  const visibleChanged = selectedField
    ? diff.changed.filter((product) => product.fields.some((f) => f.field === selectedField))
    : diff.changed;

  return (
    <Stack gap="md" data-testid="export-version-diff">
      <Text fw={600}>{t('diffTitle', { version: diff.version, against: diff.against })}</Text>

      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <Card withBorder padding="sm">
          <Text fw={700} data-testid="summary-added">
            {diff.added.length}
          </Text>
          <Text size="xs" c="dimmed">
            {t('diff.summary.added')}
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text fw={700} data-testid="summary-removed">
            {diff.removed.length}
          </Text>
          <Text size="xs" c="dimmed">
            {t('diff.summary.removed')}
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text fw={700} data-testid="summary-changed">
            {diff.changed.length}
          </Text>
          <Text size="xs" c="dimmed">
            {t('diff.summary.changed')}
          </Text>
        </Card>
        <Card withBorder padding="sm">
          <Text fw={700} data-testid="summary-fields">
            {totalFields}
          </Text>
          <Text size="xs" c="dimmed">
            {t('diff.summary.fields')}
          </Text>
        </Card>
      </SimpleGrid>

      <Card withBorder padding="sm" data-testid="findings-delta">
        <Text size="sm" fw={600} mb={4}>
          {t('diff.findingsDelta')}
        </Text>
        <FindingsDelta a={findingsA} b={findingsB} />
      </Card>

      <Card withBorder padding="sm">
        <Text size="sm" fw={600} mb={4}>
          {t('findingsDiff.title')}
        </Text>
        {diff.findings ? <FindingsDiffSection findings={diff.findings} /> : null}
      </Card>

      {diff.added.length > 0 ? (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {t('added')} ({diff.added.length})
          </Text>
          <Group gap={4}>
            {diff.added.map((id) => (
              <Badge key={id} color="green" variant="light">
                {id}
              </Badge>
            ))}
          </Group>
        </Stack>
      ) : null}
      {diff.removed.length > 0 ? (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {t('removed')} ({diff.removed.length})
          </Text>
          <Group gap={4}>
            {diff.removed.map((id) => (
              <Badge key={id} color="red" variant="light">
                {id}
              </Badge>
            ))}
          </Group>
        </Stack>
      ) : null}

      {fieldCounts.length > 0 ? (
        <Stack gap={4}>
          <Group justify="space-between">
            <Text size="sm" fw={500}>
              {t('diff.byField')}
            </Text>
            {selectedField ? (
              <Badge
                variant="light"
                style={{ cursor: 'pointer' }}
                onClick={() => setSelectedField(null)}
              >
                {t('diff.allFields')}
              </Badge>
            ) : null}
          </Group>
          <Group gap={4} data-testid="field-breakdown">
            {fieldCounts.map(([field, count]) => (
              <Badge
                key={field}
                variant={selectedField === field ? 'filled' : 'light'}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelectedField(selectedField === field ? null : field)}
              >
                {field} · {count}
              </Badge>
            ))}
          </Group>
        </Stack>
      ) : null}

      {visibleChanged.length > 0 ? (
        <Accordion variant="separated" multiple>
          {visibleChanged.map((product) => (
            <Accordion.Item key={product.product_id} value={product.product_id}>
              <Accordion.Control>
                <Group justify="space-between">
                  <Text fw={500}>{product.product_id}</Text>
                  <Text size="sm" c="dimmed">
                    {t('fieldsChanged', { count: product.fields.length })}
                  </Text>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Table withTableBorder>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('columns.field')}</Table.Th>
                      <Table.Th>{t('columns.old')}</Table.Th>
                      <Table.Th>{t('columns.new')}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {product.fields.map((field, idx) => (
                      <Table.Tr key={`${field.field}-${idx}`}>
                        <Table.Td>{field.field}</Table.Td>
                        <Table.Td>
                          <ValueCell value={field.old} />
                        </Table.Td>
                        <Table.Td>
                          <ValueCell value={field.new} />
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      ) : null}
    </Stack>
  );
}
