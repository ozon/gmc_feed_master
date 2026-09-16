import { AreaChart, DonutChart } from '@mantine/charts';
import { Grid } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import {
  chartColors,
  donutPalette,
} from '../../components/dashboard/dashboardColors';
import { ChartCard } from '../../components/dashboard/ChartCard';
import { fillChartDates } from '../../api/hooks';
import type { DashboardSummary } from '../../api/types';

const MAX_SLICES = 8;

export function FleetCharts({ summary }: { summary: DashboardSummary }) {
  const { t } = useTranslation('dashboard');

  const feeds = summary.clients.flatMap((client) =>
    client.feed_sources.map((feed) => ({ name: `${client.name} / ${feed.name}`, value: feed.item_count })),
  );
  const sorted = [...feeds].sort((a, b) => b.value - a.value);
  const top = sorted.slice(0, MAX_SLICES);
  const rest = sorted.slice(MAX_SLICES);
  const donutData = [
    ...top.map((feed, i) => ({ ...feed, color: donutPalette[i % donutPalette.length] })),
    ...(rest.length > 0
      ? [{ name: t('charts.other'), value: rest.reduce((sum, f) => sum + f.value, 0), color: chartColors.other }]
      : []),
  ];
  const donutEmpty = donutData.every((slice) => slice.value === 0);

  const trend = fillChartDates(summary.runs_by_day, 14);

  return (
    <Grid>
      <Grid.Col span={{ base: 12, md: 5 }}>
        <ChartCard title={t('charts.volumeTitle')} isEmpty={donutEmpty} emptyMessage={t('charts.volumeEmpty')}>
          <DonutChart
            size={180}
            data={donutData}
            withTooltip
            mx="auto"
          />
        </ChartCard>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 7 }}>
        <ChartCard title={t('charts.healthTitle')} isEmpty={trend.length === 0} emptyMessage={t('charts.healthEmpty')}>
          <AreaChart
            h={220}
            data={trend}
            dataKey="date"
            type="stacked"
            curveType="natural"
            withLegend
            series={[
              { name: 'success', color: chartColors.success },
              { name: 'error', color: chartColors.error },
            ]}
          />
        </ChartCard>
      </Grid.Col>
    </Grid>
  );
}
