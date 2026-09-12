import { Group, MultiSelect, Select, Stack } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { useQualityFindings, useQualityHistory } from '../../api/hooks';
import { ErrorState, LoadingState } from '../../components/StateViews';
import { FindingsTable } from './FindingsTable';
import { QualitySummaryCards } from './QualitySummaryCards';
import { QualityTrendChart } from './QualityTrendChart';
import { RuleDistributionChart } from './RuleDistributionChart';

const SEVERITIES: string[] = ['critical', 'warning', 'info'];

export function MonitoringFindingsPage() {
  const { t, i18n } = useTranslation('monitoring');
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const { data, isPending, isError, refetch } = useQualityFindings(id, true);
  const { data: historyData } = useQualityHistory(id);
  const [severityFilter, setSeverityFilter] = useState<string[]>([]);
  const [codeFilter, setCodeFilter] = useState<string | null>(null);

  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={() => void refetch()} />;
  const findings = data?.findings ?? [];
  const filtered = findings.filter(
    (f) =>
      (severityFilter.length === 0 || severityFilter.includes(f.severity)) &&
      (codeFilter === null || codeFilter === '' || f.code === codeFilter),
  );
  const codes = [...new Set(findings.map((f) => f.code))];

  return (
    <Stack gap="md" pt="md">
      <QualitySummaryCards
        counts={data?.counts ?? { critical: 0, warning: 0, info: 0 }}
        delta={data?.delta ?? { fixed: 0, new: 0, remaining: 0 }}
        hasPrevious={Boolean(data?.has_previous)}
        productCount={data?.product_count ?? 0}
      />
      <QualityTrendChart rows={historyData?.rows ?? []} />
      <RuleDistributionChart findings={findings} />
      <Group>
        <MultiSelect
          label={t('findings.severityFilter')}
          data={SEVERITIES.map((severity) => ({
            value: severity,
            label: t(`severity.${severity}`, { defaultValue: severity }),
          }))}
          value={severityFilter}
          onChange={(v) => setSeverityFilter(v)}
          placeholder={t('findings.severityPlaceholder')}
          clearable
        />
        <Select
          label={t('findings.codeFilter')}
          data={codes}
          value={codeFilter}
          onChange={setCodeFilter}
          placeholder={t('findings.codePlaceholder')}
          clearable
        />
      </Group>
      <FindingsTable findings={filtered} />
      <Group justify="flex-end">
        <span>{t('findings.total', { count: new Intl.NumberFormat(i18n.language).format(filtered.length) })}</span>
      </Group>
    </Stack>
  );
}
