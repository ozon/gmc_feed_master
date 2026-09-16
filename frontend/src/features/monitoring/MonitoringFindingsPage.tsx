import { Stack } from '@mantine/core';
import { useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { useQualityFindings, useQualityHistory } from '../../api/hooks';
import { ErrorState, LoadingState } from '../../components/StateViews';
import { ProductDrawer } from '../products/ProductDrawer';
import { FindingsExplorer } from './findings/FindingsExplorer';
import { FindingsSummary } from './findings/FindingsSummary';
import { QualityTrendChart } from './findings/QualityTrendChart';
import { RuleDistributionChart } from './findings/RuleDistributionChart';

export function MonitoringFindingsPage() {
  const { feedSourceId } = useParams();
  const id = feedSourceId ?? '';
  const { data, isPending, isError, refetch } = useQualityFindings(id, true);
  const { data: historyData } = useQualityHistory(id);
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);

  const findings = useMemo(() => data?.findings ?? [], [data]);

  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={() => void refetch()} />;

  return (
    <Stack gap="md" pt="md">
      <FindingsSummary
        counts={data?.counts ?? { critical: 0, warning: 0, info: 0 }}
        delta={data?.delta ?? { fixed: 0, new: 0, remaining: 0 }}
        hasPrevious={Boolean(data?.has_previous)}
        productCount={data?.product_count ?? 0}
      />
      <QualityTrendChart rows={historyData?.rows ?? []} />
      <RuleDistributionChart findings={findings} />
      <FindingsExplorer findings={findings} onOpenProduct={setSelectedProductId} />
      <ProductDrawer
        feedSourceId={id}
        productId={selectedProductId}
        onClose={() => setSelectedProductId(null)}
      />
    </Stack>
  );
}
