import {
  Badge,
  Group,
  Pagination,
  Select,
  Table as MantineTable,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useTable } from '@tanstack/react-table';
import { rowPaginationFeature, rowSortingFeature, columnVisibilityFeature } from '@tanstack/table-core';
import type { ProductListItem, ProductsPageResponse } from '../../api/types';
import type { ProductColumnId } from './columns';
import { columnLabel, formatCellValue } from './columns';
import { EmptyState } from '../../components/StateViews';

type SortState = { id: string; desc: boolean } | null;

type ProductsTableProps = {
  response: ProductsPageResponse;
  visibleColumns: ProductColumnId[];
  sort: SortState;
  onSortChange: (sort: SortState) => void;
  pageIndex: number;
  pageSize: number;
  onPaginationChange: (page: number, pageSize: number) => void;
  onRowClick: (productId: string) => void;
};

// Mirrors backend _SORTS (app/routes/products.py) — the only ids the
// backend accepts for the `sort` query param.
const SORTABLE_COLUMN_IDS = new Set(['product_id', 'title', 'status', 'last_seen_at']);

export function ProductsTable({
  response,
  visibleColumns,
  sort,
  onSortChange,
  pageIndex,
  pageSize,
  onPaginationChange,
  onRowClick,
}: ProductsTableProps) {
  const { t } = useTranslation('products');
  const { items, total } = response;

  const columns = visibleColumns.map((colId) => ({
    id: colId,
    header: columnLabel(colId, t),
    accessorFn: (row: ProductListItem) => formatCellValue(colId, row),
    // Only ids with backend SQL sort support are sortable; dynamic raw_data
    // fields would produce a 422 from the list endpoint.
    enableSorting: SORTABLE_COLUMN_IDS.has(colId),
  }));

  const columnVisibility: Record<string, boolean> = {};
  for (const col of columns) {
    columnVisibility[col.id] = true;
  }

  const table = useTable(
    {
      columns,
      data: items,
      features: {
        rowPaginationFeature,
        rowSortingFeature,
        columnVisibilityFeature,
      },
      getRowId: (row: ProductListItem) => row.product_id,
      manualPagination: true,
      rowCount: total,
      state: {
        pagination: { pageIndex, pageSize },
        sorting: sort ? [{ id: sort.id, desc: sort.desc }] : [],
      },
      onPaginationChange: (updater) => {
        const next = typeof updater === 'function'
          ? updater({ pageIndex, pageSize })
          : updater;
        onPaginationChange(next.pageIndex, next.pageSize);
      },
      enableSorting: true,
      enableSortingRemoval: true,
      manualSorting: true,
      onSortingChange: (updater) => {
        const current = sort ? [{ id: sort.id, desc: sort.desc }] : [];
        const next = typeof updater === 'function' ? updater(current) : updater;
        if (next.length === 0) {
          onSortChange(null);
        } else {
          onSortChange({ id: next[0].id, desc: next[0].desc });
        }
      },
    },
    (state) => ({
      pagination: state.pagination,
    }),
  );

  const pageCount = Math.ceil(total / pageSize) || 1;

  if (items.length === 0) {
    return <EmptyState message={t('noResults')} />;
  }

  return (
    <div>
      <MantineTable.ScrollContainer minWidth={800}>
        <MantineTable striped highlightOnHover>
          <MantineTable.Thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <MantineTable.Tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const canSort = header.column.getCanSort();
                  const sorted = header.column.getIsSorted();
                  return (
                    <MantineTable.Th key={header.id}>
                      {canSort ? (
                        <UnstyledButton
                          onClick={header.column.getToggleSortingHandler()}
                          style={{ cursor: 'pointer' }}
                        >
                          <Group gap={4} wrap="nowrap">
                            {header.column.columnDef.header as string}
                            {sorted === 'asc' && ' ▲'}
                            {sorted === 'desc' && ' ▼'}
                          </Group>
                        </UnstyledButton>
                      ) : (
                        (header.column.columnDef.header as string)
                      )}
                    </MantineTable.Th>
                  );
                })}
              </MantineTable.Tr>
            ))}
          </MantineTable.Thead>
          <MantineTable.Tbody>
            {table.getRowModel().rows.map((row) => (
              <MantineTable.Tr
                key={row.id}
                onClick={() => onRowClick(row.original.product_id)}
                style={{ cursor: 'pointer' }}
              >
                {row.getVisibleCells().map((cell) => {
                  const colId = cell.column.id as ProductColumnId;
                  const value = cell.getValue() as string;
                  if (colId === 'status') {
                    return (
                      <MantineTable.Td key={cell.id}>
                        <Badge
                          color={value === 'removed' ? 'red' : 'green'}
                          variant="light"
                          size="sm"
                        >
                          {value}
                        </Badge>
                      </MantineTable.Td>
                    );
                  }
                  return <MantineTable.Td key={cell.id}>{value}</MantineTable.Td>;
                })}
              </MantineTable.Tr>
            ))}
          </MantineTable.Tbody>
        </MantineTable>
      </MantineTable.ScrollContainer>
      <Group justify="space-between" mt="md" px="sm">
        <Text size="sm" c="dimmed">
          {t('totalItems', { total: new Intl.NumberFormat().format(total) })}
        </Text>
        <Group gap="xs">
          <Select
            value={String(pageSize)}
            onChange={(v) => {
              if (v) onPaginationChange(0, Number(v));
            }}
            data={['25', '50', '100', '200'].map((v) => ({
              value: v,
              label: v,
            }))}
            size="xs"
            w={80}
            aria-label={t('rowsPerPage')}
          />
          <Pagination
            total={pageCount}
            value={pageIndex + 1}
            onChange={(p) => onPaginationChange(p - 1, pageSize)}
            component="nav"
            aria-label="pagination"
          />
        </Group>
      </Group>
    </div>
  );
}
