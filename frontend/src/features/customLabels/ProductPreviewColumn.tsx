import { Badge, Box, Group, Skeleton, Stack, Text, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { RefObject } from 'react';
import type { ProductLookupMatch } from '../../api/types';
import { ROW_HEIGHT, VIEWPORT_ROWS, availabilityColor, windowRange } from './productPreview';

export type ProductPreviewColumnProps = {
  field: string;
  entries: string[];
  matches: ReadonlyMap<string, ProductLookupMatch> | null;
  isPending: boolean;
  isError: boolean;
  extraFields: string[];
  scrollTop: number;
  viewportRef: RefObject<HTMLDivElement | null>;
};

export function ProductPreviewColumn({
  field, entries, matches, isPending, isError, extraFields, scrollTop, viewportRef,
}: ProductPreviewColumnProps) {
  const { t } = useTranslation('customLabels');
  const total = entries.length;
  const [start, end] = windowRange(scrollTop, total);

  return (
    <Stack gap={4} data-testid="product-preview-column">
      {isError ? (
        <Text size="xs" c="red" data-testid="preview-error">{t('previewError')}</Text>
      ) : null}
      <Box
        ref={viewportRef}
        data-testid="product-preview-viewport"
        style={{
          height: VIEWPORT_ROWS * ROW_HEIGHT,
          overflowY: 'auto',
          border: 'calc(0.0625rem * var(--mantine-scale)) solid var(--mantine-color-default-border)',
          borderRadius: 'var(--mantine-radius-sm)',
        }}
      >
        {total === 0 ? (
          <Text size="xs" c="dimmed" px="xs" data-testid="preview-empty">{t('previewEmpty')}</Text>
        ) : (
          <div style={{ height: total * ROW_HEIGHT, position: 'relative' }}>
            {entries.slice(start, end).map((value, offset) => {
              const index = start + offset;
              const match = matches?.get(value) ?? null;
              return (
                <Group
                  key={`${index}-${value}`}
                  gap="xs"
                  wrap="nowrap"
                  px="xs"
                  style={{
                    position: 'absolute',
                    top: index * ROW_HEIGHT,
                    height: ROW_HEIGHT,
                    left: 0,
                    right: 0,
                    alignItems: 'center',
                  }}
                  data-testid={`preview-row-${index}`}
                >
                  <PreviewRow field={field} value={value} match={match} isPending={isPending} extraFields={extraFields} />
                </Group>
              );
            })}
          </div>
        )}
      </Box>
    </Stack>
  );
}

function PreviewRow({
  field, value, match, isPending, extraFields,
}: {
  field: string;
  value: string;
  match: ProductLookupMatch | null;
  isPending: boolean;
  extraFields: string[];
}) {
  const { t } = useTranslation('customLabels');
  if (match === null && isPending) {
    return (
      <Group gap="xs" wrap="nowrap" w="100%">
        <Skeleton height={14} width="45%" />
        <Skeleton height={14} width="20%" />
      </Group>
    );
  }
  if (match === null || match.count === 0) {
    return (
      <Badge size="xs" variant="light" color="red">
        {field === 'id' ? t('idNotFoundInFeed') : t('noMatchInFeed')}
      </Badge>
    );
  }
  const sample = match.sample;
  if (sample === null) return null;
  const title = sample.title === null ? value : sample.title;
  return (
    <Group gap="xs" wrap="nowrap" w="100%" style={{ minHeight: 0 }}>
      {match.count > 1 && (
        <Badge size="xs" variant="light" color="gray">
          {t('nProducts', { count: match.count })}
        </Badge>
      )}
      <Tooltip label={title} withArrow position="top" openDelay={300}>
        <Text size="xs" truncate style={{ flex: 1, minWidth: 0 }}>{title}</Text>
      </Tooltip>
      <Text size="xs" c="dimmed" truncate maw={120}>
        {sample.brand ?? '—'}
      </Text>
      <Badge size="xs" variant="light" color={availabilityColor(sample.availability)}>
        {sample.availability ?? '—'}
      </Badge>
      {extraFields.map((fieldName) => (
        <Text key={fieldName} size="xs" c="dimmed" truncate maw={160}>
          {sample[fieldName] == null ? '' : String(sample[fieldName])}
        </Text>
      ))}
      {sample.status === 'removed' && (
        <Badge size="xs" variant="light" color="gray">{t('stateRemoved')}</Badge>
      )}
      {sample.excluded && (
        <Badge size="xs" variant="light" color="gray">{t('stateExcluded')}</Badge>
      )}
    </Group>
  );
}
