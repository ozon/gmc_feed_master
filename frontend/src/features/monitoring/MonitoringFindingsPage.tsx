import { Group, MultiSelect, Stack } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import { useQualityFindings } from '../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { FindingsTable } from './FindingsTable';

const SEVERITIES: string[] = ['critical', 'warning', 'info'];

export function MonitoringFindingsPage() {
  const { t, i18n } = useTranslation('monitoring');
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const { data, isPending, isError, refetch } = useQualityFindings(id, true);
  const [severityFilter, setSeverityFilter] = useState<string[]>([]);

  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={() => void refetch()} />;
  const findings = data?.findings ?? [];
  const filtered = severityFilter.length === 0
    ? findings
    : findings.filter((f) => severityFilter.includes(f.severity));
  if (findings.length === 0) return <EmptyState message={t('findings.empty')} />;

  return (
    <Stack gap="md" pt="md">
      <Group>
        <MultiSelect
          label={t('findings.severityFilter')}
          data={SEVERITIES}
          value={severityFilter}
          onChange={(v) => setSeverityFilter(v)}
          placeholder={t('findings.severityPlaceholder')}
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