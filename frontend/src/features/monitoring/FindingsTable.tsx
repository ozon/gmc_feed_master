import { Group, Pagination, Select, Table, Text, UnstyledButton } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useTable } from '@tanstack/react-table';
import {
  createPaginatedRowModel,
  createSortedRowModel,
  rowPaginationFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  tableFeatures,
} from '@tanstack/table-core';
import type { QualityFinding as ApiQualityFinding } from '../../api/types';
import { RuleLabel } from './findings/RuleLabel';
import { SeverityBadge } from './findings/SeverityBadge';

export type QualityFinding = ApiQualityFinding;

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric },
  rowPaginationFeature,
  paginatedRowModel: createPaginatedRowModel(),
});

type Props = {
  findings: QualityFinding[];
  onOpenProduct?: (productId: string) => void;
};

export function FindingsTable({ findings, onOpenProduct }: Props) {
  const { t } = useTranslation('monitoring');
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 25 });
  const table = useTable({
    features,
    columns: [
      {
        id: 'severity',
        header: t('columns.severity'),
        accessorFn: (row: QualityFinding) => row.severity,
      },
      { id: 'code', header: t('columns.code'), accessorFn: (row: QualityFinding) => row.code },
      {
        id: 'field',
        header: t('columns.field'),
        accessorFn: (row: QualityFinding) => row.field ?? '',
      },
      {
        id: 'message',
        header: t('columns.message'),
        accessorFn: (row: QualityFinding) => row.message,
      },
      {
        id: 'product_id',
        header: t('columns.productId'),
        accessorFn: (row: QualityFinding) => row.product_id,
      },
    ],
    data: findings,
    getRowId: (row: QualityFinding, index: number) =>
      `${row.code}-${row.product_id}-${row.field ?? ''}-${index}`,
    state: { pagination },
    onPaginationChange: setPagination,
    autoResetPageIndex: false,
    enableSortingRemoval: false,
  });

  const rows = table.getRowModel().rows;
  const { pageIndex, pageSize } = pagination;
  const pageCount = Math.max(1, Math.ceil(findings.length / pageSize));

  return (
    <div data-testid="findings-table">
      <Table striped>
        <Table.Thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <Table.Tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <Table.Th key={header.id}>
                  {header.column.getCanSort() ? (
                    <UnstyledButton
                      onClick={header.column.getToggleSortingHandler()}
                      style={{ cursor: 'pointer' }}
                    >
                      <Group gap={4} wrap="nowrap">
                        {header.column.columnDef.header as string}
                        {header.column.getIsSorted() === 'asc' && ' ▲'}
                        {header.column.getIsSorted() === 'desc' && ' ▼'}
                      </Group>
                    </UnstyledButton>
                  ) : (
                    (header.column.columnDef.header as string)
                  )}
                </Table.Th>
              ))}
            </Table.Tr>
          ))}
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => {
            const finding = row.original;
            return (
              <Table.Tr key={row.id} data-testid="finding-row">
                <Table.Td>
                  <SeverityBadge severity={finding.severity} />
                </Table.Td>
                <Table.Td>
                  <RuleLabel code={finding.code} />
                </Table.Td>
                <Table.Td>{finding.field}</Table.Td>
                <Table.Td>{finding.message}</Table.Td>
                <Table.Td>
                  {onOpenProduct && finding.product_id ? (
                    <UnstyledButton
                      onClick={() => onOpenProduct(finding.product_id)}
                      aria-label={t('findings.openProduct', { id: finding.product_id })}
                    >
                      <Text size="sm" c="blue">
                        {finding.product_id}
                      </Text>
                    </UnstyledButton>
                  ) : (
                    finding.product_id
                  )}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      <Group justify="space-between" mt="md" px="sm">
        <Text size="sm" c="dimmed">
          {t('findings.total', { count: findings.length })}
        </Text>
        <Group gap="xs">
          <Select
            value={String(pageSize)}
            onChange={(value) => {
              if (value) setPagination((current) => ({ pageIndex: 0, pageSize: Number(value) }));
            }}
            data={['25', '50', '100'].map((value) => ({ value, label: value }))}
            size="xs"
            w={80}
            aria-label={t('findings.pageSize')}
          />
          <Pagination
            total={pageCount}
            value={pageIndex + 1}
            onChange={(page) => setPagination((current) => ({ ...current, pageIndex: page - 1 }))}
          />
        </Group>
      </Group>
    </div>
  );
}
