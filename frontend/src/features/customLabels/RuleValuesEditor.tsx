import { useCallback, useMemo, useRef, useState } from 'react';
import {
  ActionIcon, Grid, Group, MultiSelect, Stack, Text, Textarea, Tooltip,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { IconTrash, IconWand } from '@tabler/icons-react';
import { useFeedSourceFields, useProductLookup } from '../../api/hooks';
import { formatIdList, parseIdList, parsePreviewLines } from './ids';
import { ProductPreviewColumn } from './ProductPreviewColumn';
import { ROW_HEIGHT, useSyncedScroll } from './productPreview';
import type { ShadowOwnerInfo } from './shadowing';
import type { ScopedSlotRule } from './scopeMerge';

const PREVIEW_DEFAULT_FIELDS = new Set(['title', 'brand', 'availability']);

export type RuleValuesEditorProps = {
  rule: ScopedSlotRule;
  value: string;
  feedSourceId: number | undefined;
  extraFields: string[];
  onExtraFieldsChange: (fields: string[]) => void;
  onSetIds: (value: string) => void;
  shadowedBy: ReadonlyMap<string, ShadowOwnerInfo>;
};

export function RuleValuesEditor({
  rule, value, feedSourceId, extraFields, onExtraFieldsChange, onSetIds, shadowedBy,
}: RuleValuesEditorProps) {
  const { t } = useTranslation('customLabels');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const onScrollTopChange = useCallback((top: number) => setScrollTop(top), []);
  useSyncedScroll(textareaRef, previewRef, onScrollTopChange, feedSourceId);

  const lines = useMemo(() => parsePreviewLines(value), [value]);
  const lookupValues = useMemo(() => Array.from(new Set(lines.flat())), [lines]);
  const [debouncedValues] = useDebouncedValue(lookupValues, 300);
  const lookup = useProductLookup(feedSourceId, rule.matchField, debouncedValues, extraFields);
  const matches = useMemo(
    () => (lookup.data?.matches ? new Map(Object.entries(lookup.data.matches)) : null),
    [lookup.data],
  );

  const fieldsQuery = useFeedSourceFields(String(feedSourceId ?? ''));
  const fieldOptions = useMemo(
    () => (fieldsQuery.data?.fields ?? []).filter((f) => !PREVIEW_DEFAULT_FIELDS.has(f)),
    [fieldsQuery.data],
  );

  const count = parseIdList(value).size;
  const label = rule.matchField === 'id'
    ? t('bulk.productIds')
    : t('bulk.valuesFor', { field: rule.matchField });
  const ariaLabel = rule.matchField === 'id'
    ? `${t('bulk.productIds')} — ${rule.name}`
    : `${t('bulk.valuesFor', { field: rule.matchField })} — ${rule.name}`;

  const textarea = (
    <Textarea
      label={label}
      aria-label={ariaLabel}
      ref={textareaRef}
      minRows={10}
      maxRows={10}
      autosize
      wrap="off"
      styles={{
        input: {
          lineHeight: `${ROW_HEIGHT}px`,
          fontFamily: 'var(--mantine-font-family-monospace)',
          overflowX: 'auto',
        },
      }}
      value={value}
      onChange={(e) => onSetIds(e.currentTarget.value)}
      placeholder={t('idsPlaceholder')}
    />
  );

  const toolbar = (
    <Group justify="space-between" wrap="nowrap" gap="xs">
      <Group gap={4} wrap="nowrap">
        <Tooltip label={t('clearValues')} withArrow position="top" openDelay={300}>
          <ActionIcon
            variant="default"
            size="sm"
            aria-label={`${t('clearValues')} — ${rule.name}`}
            disabled={value === ''}
            onClick={() => onSetIds('')}
            data-testid={`clear-ids-${rule.id}`}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t('formatDedupe')} withArrow position="top" openDelay={300}>
          <ActionIcon
            variant="default"
            size="sm"
            aria-label={`${t('formatDedupe')} — ${rule.name}`}
            disabled={value === ''}
            onClick={() => onSetIds(formatIdList(value))}
            data-testid={`format-ids-${rule.id}`}
          >
            <IconWand size={16} />
          </ActionIcon>
        </Tooltip>
      </Group>
      {feedSourceId !== undefined && (
        <MultiSelect
          size="xs"
          w={220}
          clearable
          searchable
          aria-label={t('previewFieldsLabel')}
          data={fieldOptions}
          value={extraFields}
          onChange={(v) => onExtraFieldsChange(v ?? [])}
          placeholder={t('previewFieldsLabel')}
          data-testid={`preview-fields-${rule.id}`}
        />
      )}
    </Group>
  );

  const footer = (
    <Group gap="xs" justify="space-between" wrap="nowrap">
      <Text size="xs" c="dimmed" data-testid={`id-count-${rule.id}`}>
        {t('idCount', { count })}
      </Text>
      <Text size="xs" c="dimmed">{rule.matchField}</Text>
    </Group>
  );

  if (feedSourceId === undefined) {
    return (
      <Stack gap={4}>
        {toolbar}
        {textarea}
        {footer}
      </Stack>
    );
  }

  return (
    <Stack gap="xs">
      {toolbar}
      <Grid columns={20} gap="xs">
        <Grid.Col span={7}>{textarea}</Grid.Col>
        <Grid.Col span={13}>
          <ProductPreviewColumn
            field={rule.matchField}
            lines={lines}
            matches={matches}
            isFetching={lookup.isFetching}
            isError={lookup.isError}
            extraFields={extraFields}
            shadowedBy={shadowedBy}
            scrollTop={scrollTop}
            viewportRef={previewRef}
          />
        </Grid.Col>
      </Grid>
      {footer}
    </Stack>
  );
}
