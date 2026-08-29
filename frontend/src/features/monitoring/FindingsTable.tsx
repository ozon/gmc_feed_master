import { Badge, Table } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { QualityFinding as ApiQualityFinding } from '../../api/types';

export type QualityFinding = ApiQualityFinding;

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red',
  warning: 'yellow',
  info: 'blue',
};

type Props = {
  findings: QualityFinding[];
};

export function FindingsTable({ findings }: Props) {
  const { t } = useTranslation('monitoring');
  return (
    <Table data-testid="findings-table" striped>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('columns.severity')}</Table.Th>
          <Table.Th>{t('columns.code')}</Table.Th>
          <Table.Th>{t('columns.field')}</Table.Th>
          <Table.Th>{t('columns.message')}</Table.Th>
          <Table.Th>{t('columns.productId')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {findings.map((finding, idx) => (
          <Table.Tr key={`${finding.code}-${finding.product_id}-${idx}`} data-testid={`finding-row-${idx}`}>
            <Table.Td>
              <Badge color={SEVERITY_COLOR[finding.severity] ?? 'gray'}>{finding.severity}</Badge>
            </Table.Td>
            <Table.Td>{finding.code}</Table.Td>
            <Table.Td>{finding.field}</Table.Td>
            <Table.Td>{finding.message}</Table.Td>
            <Table.Td>{finding.product_id}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}