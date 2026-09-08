import { Badge, Box, Group, Skeleton, Stack, Text, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { RefObject } from 'react';
import type { ProductLookupMatch } from '../../api/types';
import { ROW_HEIGHT, VIEWPORT_ROWS, availabilityColor, windowRange } from './productPreview';
import type { ShadowOwnerInfo } from './shadowing';

export type ProductPreviewColumnProps = {
  field: string;
  /** One row per textarea line; line i = its comma-split IDs. */
  lines: string[][];
  matches: ReadonlyMap<string, ProductLookupMatch> | null;
  isFetching: boolean;
  isError: boolean;
  extraFields: string[];
  /** Value -> claiming rule (this rule's shadowedBy map). */
  shadowedBy: ReadonlyMap<string, ShadowOwnerInfo> | null;
  scrollTop: number;
  viewportRef: RefObject<HTMLDivElement | null>;
};

export function ProductPreviewColumn({
  field, lines, matches, isFetching, isError, extraFields, shadowedBy, scrollTop, viewportRef,
}: ProductPreviewColumnProps) {
  const { t } = useTranslation('customLabels');
  const total = lines.length;
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
            {lines.slice(start, end).map((ids, offset) => {
              const index = start + offset;
              const match = ids.length > 0 ? matches?.get(ids[0]) ?? null : null;
              return (
                <Group
                  key={`${index}-${ids.join(',')}`}
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
                  <PreviewRow
                    field={field}
                    ids={ids}
                    match={match}
                    isFetching={isFetching}
                    extraFields={extraFields}
                    shadowedBy={shadowedBy}
                  />
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
  field, ids, match, isFetching, extraFields, shadowedBy,
}: {
  field: string;
  ids: string[];
  match: ProductLookupMatch | null;
  isFetching: boolean;
  extraFields: string[];
  shadowedBy: ReadonlyMap<string, ShadowOwnerInfo> | null;
}) {
  const { t } = useTranslation('customLabels');
  if (ids.length === 0) {
    return <Text size="xs" c="dimmed">—</Text>;
  }
  const owner = shadowedBy?.get(ids[0]) ?? null;
  return (
    <Group gap="xs" wrap="nowrap" w="100%" style={{ minHeight: 0 }}>
      {owner !== null && (
        <Tooltip label={t('shadowedBy', { name: owner.name })} withArrow position="top">
          <Badge size="xs" variant="light" color="orange" data-testid="overridden-badge">
            {t('overriddenBy', { priority: owner.priority })}
          </Badge>
        </Tooltip>
      )}
      {ids.length > 1 && (
        <Badge size="xs" variant="light" color="gray" data-testid="more-ids-badge">
          {t('nMoreIds', { more: ids.length - 1 })}
        </Badge>
      )}
      <MatchBody field={field} value={ids[0]} match={match} isFetching={isFetching} extraFields={extraFields} />
    </Group>
  );
}

function MatchBody({
  field, value, match, isFetching, extraFields,
}: {
  field: string;
  value: string;
  match: ProductLookupMatch | null;
  isFetching: boolean;
  extraFields: string[];
}) {
  const { t } = useTranslation('customLabels');
  if (match === null && isFetching) {
    return (
      <Group gap="xs" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
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
    <>
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
    </>
  );
}
