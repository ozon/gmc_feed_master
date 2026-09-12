import { BarChart } from '@mantine/charts';
import type { QualityFinding } from '../../api/types';

type Props = {
  findings: QualityFinding[];
};

export function RuleDistributionChart({ findings }: Props) {
  const byCode = new Map<string, number>();
  for (const f of findings) byCode.set(f.code, (byCode.get(f.code) ?? 0) + 1);
  const data = [...byCode.entries()]
    .map(([code, count]) => ({ code, count }))
    .sort((a, b) => b.count - a.count);
  if (data.length === 0) return null;
  return (
    <BarChart
      orientation="horizontal"
      h={Math.max(160, data.length * 28)}
      data={data}
      dataKey="code"
      series={[{ name: 'count', color: 'blue.4' }]}
      tickLine="y"
    />
  );
}
