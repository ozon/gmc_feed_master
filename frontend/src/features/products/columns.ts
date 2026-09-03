import { useMemo } from 'react';
import type { TFunction } from 'i18next';
import dayjs from 'dayjs';
import type { ProductListItem } from '../../api/types';

export type ProductColumnId = string;

export type ProductColumn = {
  id: ProductColumnId;
  label: string;
};

export const SYSTEM_COLUMNS: ProductColumnId[] = [
  'product_id',
  'status',
  'last_seen_at',
];

export const DEFAULT_COLUMNS: ProductColumnId[] = [
  'id',
  'title',
  'description',
  'link',
  'image_link',
  'availability',
  'price',
  'condition',
  'status',
];

const BASELINE_LABEL_KEYS: Record<string, string> = {
  product_id: 'colProductId',
  id: 'colId',
  title: 'colTitle',
  description: 'colDescription',
  link: 'colLink',
  image_link: 'colImageLink',
  availability: 'colAvailability',
  price: 'colPrice',
  condition: 'colCondition',
  status: 'colStatus',
  last_seen_at: 'colLastSeenAt',
};

export function columnLabel(id: ProductColumnId, t: TFunction<'products'>): string {
  const key = BASELINE_LABEL_KEYS[id];
  return key ? t(key as 'colId') : id;
}

export function useProductColumns(
  t: TFunction<'products'>,
  fields: string[],
): ProductColumn[] {
  return useMemo<ProductColumn[]>(
    () => {
      const ids = [...SYSTEM_COLUMNS, ...fields];
      return ids.map((id) => ({ id, label: columnLabel(id, t) }));
    },
    [t, fields],
  );
}

export function loadColumnConfig(feedSourceId: number | string): ProductColumnId[] | null {
  try {
    const raw = localStorage.getItem(`products.columns.${feedSourceId}`);
    if (!raw) return null;
    return JSON.parse(raw) as ProductColumnId[];
  } catch {
    return null;
  }
}

export function saveColumnConfig(
  feedSourceId: number | string,
  ids: ProductColumnId[],
): void {
  localStorage.setItem(`products.columns.${feedSourceId}`, JSON.stringify(ids));
}

export function formatCellValue(
  id: ProductColumnId,
  row: ProductListItem,
): string {
  if (id === 'last_seen_at') {
    return dayjs(row.last_seen_at).format('L LTS');
  }
  if (id in row && id !== 'raw_data') {
    const value = row[id as keyof ProductListItem];
    if (value == null) return '';
    return String(value);
  }
  const raw = row.raw_data?.[id];
  if (raw == null) return '';
  if (typeof raw === 'string') return raw;
  return JSON.stringify(raw);
}
