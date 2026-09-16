import { LineChart } from '@mantine/charts';
import dayjs from 'dayjs';
import type { QualityHistoryRow } from '../../../api/types';
import { chartColors } from '../../../components/dashboard/dashboardColors';

type Props = {
  rows: QualityHistoryRow[];
};

export function QualityTrendChart({ rows }: Props) {
  if (rows.length === 0) return null;
  return (
    <LineChart
      h={280}
      data={rows.map((r) => ({
        date: dayjs(r.started_at).format('MM-DD HH:mm'),
        critical: r.critical,
        warning: r.warning,
        info: r.info,
      }))}
      dataKey="date"
      series={[
        { name: 'critical', color: chartColors.error },
        { name: 'warning', color: chartColors.warning },
        { name: 'info', color: chartColors.info },
      ]}
      withLegend
    />
  );
}
