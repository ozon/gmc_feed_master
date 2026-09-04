import { useEffect, useMemo, useState } from 'react';
import { Button, Checkbox, Group, Popover, SegmentedControl, Select, Stack, TextInput, Tooltip } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconColumns3, IconSearch } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router';
import { useProductList, useFeedSourceFields } from '../../api/hooks';
import { LoadingState, ErrorState } from '../../components/StateViews';
import {
  DEFAULT_COLUMNS,
  GMC_BASELINE_COLUMNS,
  SYSTEM_COLUMNS,
  type ProductColumnId,
  useProductColumns,
  loadColumnConfig,
  saveColumnConfig,
} from './columns';
import { ProductsTable } from './ProductsTable';
import { ProductDrawer } from './ProductDrawer';

type SortState = { id: string; desc: boolean } | null;

export function ProductsPage() {
  const { t } = useTranslation('products');
  const { feedSourceId } = useParams<{ feedSourceId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const qParam = searchParams.get('q') ?? '';
  const statusParam = searchParams.get('status') ?? 'all';
  const sortParam = searchParams.get('sort') ?? '';
  const pageParam = Number(searchParams.get('page') ?? '1');
  const pageSizeParam = Number(searchParams.get('page_size') ?? '50');

  const [searchInput, setSearchInput] = useState(qParam);
  const [debouncedQ] = useDebouncedValue(searchInput, 300);

  const query = useProductList(feedSourceId ?? '', {
    page: pageParam,
    page_size: pageSizeParam,
    q: debouncedQ || undefined,
    status: statusParam || undefined,
    sort: sortParam || undefined,
  });

  const fieldsQuery = useFeedSourceFields(feedSourceId ?? '');
  const allFields = fieldsQuery.data?.fields ?? [];
  const dataFields = query.data?.fields ?? [];
  const mergedFields = useMemo(
    () => [...new Set([...allFields, ...dataFields])],
    [allFields, dataFields],
  );
  const columns = useProductColumns(t, mergedFields);
  const availableColumnIds = useMemo(
    () => new Set([...SYSTEM_COLUMNS, ...GMC_BASELINE_COLUMNS, ...mergedFields]),
    [mergedFields],
  );

  const sortState: SortState = useMemo(() => {
    if (!sortParam) return null;
    const desc = sortParam.startsWith('-');
    const id = desc ? sortParam.slice(1) : sortParam;
    return { id, desc };
  }, [sortParam]);

  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);

  const savedColumns = useMemo(
    () => (feedSourceId ? loadColumnConfig(feedSourceId) : null),
    [feedSourceId],
  );
  const [visibleColumnIds, setVisibleColumnIds] = useState<ProductColumnId[]>(
    savedColumns ?? DEFAULT_COLUMNS,
  );

  const updateParams = (updates: Record<string, string | null>) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [key, value] of Object.entries(updates)) {
        if (value === null) {
          next.delete(key);
        } else {
          next.set(key, value);
        }
      }
      return next;
    }, { replace: true });
  };

  const handleSearchChange = (value: string) => {
    setSearchInput(value);
  };

  useEffect(() => {
    updateParams({ q: debouncedQ || null, page: null });
  }, [debouncedQ]);

  const handleStatusChange = (value: string | null) => {
    updateParams({ status: value === 'all' ? null : value, page: null });
  };

  const handleSortChange = (sort: SortState) => {
    if (!sort) {
      updateParams({ sort: null });
    } else {
      const param = sort.desc ? `-${sort.id}` : sort.id;
      updateParams({ sort: param });
    }
  };

  const handlePaginationChange = (page: number, pageSize: number) => {
    updateParams({
      page: page === 0 ? null : String(page + 1),
      page_size: pageSize === 50 ? null : String(pageSize),
    });
  };

  const handleColumnToggle = (columnId: ProductColumnId, checked: boolean) => {
    const next = checked
      ? [...visibleColumnIds, columnId]
      : visibleColumnIds.filter((id) => id !== columnId);
    setVisibleColumnIds(next);
    if (feedSourceId) {
      saveColumnConfig(feedSourceId, next);
    }
  };

  if (!feedSourceId) return <ErrorState />;
  if (query.isPending) return <LoadingState />;
  if (query.isError) {
    return <ErrorState onRetry={() => void query.refetch()} />;
  }

  // Saved column ids absent from the current data stay persisted (so they
  // return when data has them again) but are not rendered as columns.
  const renderableColumnIds = visibleColumnIds.filter((id) =>
    availableColumnIds.has(id),
  );

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <Group gap="sm">
          <TextInput
            leftSection={<IconSearch size={16} />}
            placeholder={t('searchPlaceholder')}
            value={searchInput}
            onChange={(e) => handleSearchChange(e.currentTarget.value)}
            w={280}
          />
          <Select
            value={statusParam}
            onChange={handleStatusChange}
            data={[
              { value: 'all', label: t('all') },
              { value: 'active', label: t('active') },
              { value: 'removed', label: t('removed') },
            ]}
            w={120}
            aria-label={t('colStatus')}
          />
          <Tooltip label={t('processedTooltip')}>
            <SegmentedControl
              value="raw"
              data={[
                { value: 'raw', label: t('stageRaw') },
                { value: 'processed', label: t('stageProcessed') },
              ]}
              disabled
            />
          </Tooltip>
        </Group>
        <Popover width={220} position="bottom-end" shadow="md">
          <Popover.Target>
            <Button variant="default" leftSection={<IconColumns3 size={16} />}>
              {t('columns')}
            </Button>
          </Popover.Target>
          <Popover.Dropdown>
            <Stack gap="xs">
              {columns.map((col) => (
                <Checkbox
                  key={col.id}
                  label={col.label}
                  checked={visibleColumnIds.includes(col.id)}
                  onChange={(e) => handleColumnToggle(col.id, e.currentTarget.checked)}
                />
              ))}
            </Stack>
          </Popover.Dropdown>
        </Popover>
      </Group>
      <ProductsTable
        response={query.data}
        visibleColumns={renderableColumnIds}
        sort={sortState}
        onSortChange={handleSortChange}
        pageIndex={pageParam - 1}
        pageSize={pageSizeParam}
        onPaginationChange={handlePaginationChange}
        onRowClick={setSelectedProductId}
      />
      <ProductDrawer
        feedSourceId={feedSourceId}
        productId={selectedProductId}
        onClose={() => setSelectedProductId(null)}
      />
    </Stack>
  );
}
