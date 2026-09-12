import { LineChart } from '@mantine/charts';
import dayjs from 'dayjs';
import type { QualityHistoryRow } from '../../api/types';

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
        { name: 'critical', color: 'red.6' },
        { name: 'warning', color: 'yellow.6' },
        { name: 'info', color: 'blue.6' },
      ]}
      withLegend
    />
  );
}
