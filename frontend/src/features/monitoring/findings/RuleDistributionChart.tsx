import { BarChart } from '@mantine/charts';
import { useTranslation } from 'react-i18next';
import type { QualityFinding } from '../../../api/types';
import { chartColors } from '../../../components/dashboard/dashboardColors';
import { ruleTitle } from './ruleCatalog';

type Props = {
  findings: QualityFinding[];
};

export function RuleDistributionChart({ findings }: Props) {
  const { t } = useTranslation('monitoring');
  const byCode = new Map<string, number>();
  for (const finding of findings) byCode.set(finding.code, (byCode.get(finding.code) ?? 0) + 1);
  const data = [...byCode.entries()]
    .map(([code, count]) => ({ name: ruleTitle(code, t), count }))
    .sort((a, b) => b.count - a.count);
  if (data.length === 0) return null;
  return (
    <BarChart
      orientation="horizontal"
      h={Math.max(160, data.length * 28)}
      data={data}
      dataKey="name"
      series={[{ name: 'count', color: chartColors.passed }]}
      tickLine="y"
    />
  );
}
