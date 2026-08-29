import { useMemo } from 'react';
import type { TFunction } from 'i18next';
import dayjs from 'dayjs';
import type { ProductListItem } from '../../api/types';

export type ProductColumnId =
  | 'product_id'
  | 'id'
  | 'title'
  | 'description'
  | 'link'
  | 'image_link'
  | 'availability'
  | 'price'
  | 'condition'
  | 'status'
  | 'last_seen_at';

export type ProductColumn = {
  id: ProductColumnId;
  label: string;
};

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

export function useProductColumns(t: TFunction<'products'>): ProductColumn[] {
  return useMemo<ProductColumn[]>(
    () => [
      { id: 'product_id', label: t('colProductId') },
      { id: 'id', label: t('colId') },
      { id: 'title', label: t('colTitle') },
      { id: 'description', label: t('colDescription') },
      { id: 'link', label: t('colLink') },
      { id: 'image_link', label: t('colImageLink') },
      { id: 'availability', label: t('colAvailability') },
      { id: 'price', label: t('colPrice') },
      { id: 'condition', label: t('colCondition') },
      { id: 'status', label: t('colStatus') },
      { id: 'last_seen_at', label: t('colLastSeenAt') },
    ],
    [t],
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
  const value = row[id as keyof ProductListItem];
  if (value == null) return '';
  if (id === 'last_seen_at') {
    return dayjs(value as string).format('L LTS');
  }
  return String(value);
}
