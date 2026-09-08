import { useCallback, useMemo, useRef, useState } from 'react';
import { CloseButton, Grid, Group, MultiSelect, Stack, Text, Textarea } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { useFeedSourceFields, useProductLookup } from '../../api/hooks';
import { parseIdEntries, parseIdList } from './ids';
import { ProductPreviewColumn } from './ProductPreviewColumn';
import { useSyncedScroll } from './productPreview';
import type { ScopedSlotRule } from './scopeMerge';

export type RuleValuesEditorProps = {
  rule: ScopedSlotRule;
  value: string;
  feedSourceId: number | undefined;
  extraFields: string[];
  onExtraFieldsChange: (fields: string[]) => void;
  onSetIds: (value: string) => void;
};

const PREVIEW_DEFAULT_FIELDS = new Set(['title', 'brand', 'availability']);

export function RuleValuesEditor({
  rule, value, feedSourceId, extraFields, onExtraFieldsChange, onSetIds,
}: RuleValuesEditorProps) {
  const { t } = useTranslation('customLabels');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const onScrollTopChange = useCallback((top: number) => setScrollTop(top), []);
  useSyncedScroll(textareaRef, previewRef, onScrollTopChange, feedSourceId);

  const entries = useMemo(() => parseIdEntries(value), [value]);
  const uniqueValues = useMemo(() => Array.from(new Set(entries)), [entries]);
  const [debouncedValues] = useDebouncedValue(uniqueValues, 300);
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
          lineHeight: '34px',
          fontFamily: 'var(--mantine-font-family-monospace)',
          overflowX: 'auto',
        },
      }}
      value={value}
      onChange={(e) => onSetIds(e.currentTarget.value)}
      placeholder={t('idsPlaceholder')}
    />
  );

  const footer = (
    <Group gap="xs" justify="space-between" wrap="nowrap">
      <Text size="xs" c="dimmed" data-testid={`id-count-${rule.id}`}>
        {t('idCount', { count })}
      </Text>
      <Group gap={6} wrap="nowrap">
        <Text size="xs" c="dimmed">{rule.matchField}</Text>
        {value !== '' && (
          <CloseButton
            size="xs"
            aria-label={`${t('clearValues')} — ${rule.name}`}
            onClick={() => onSetIds('')}
          />
        )}
      </Group>
    </Group>
  );

  if (feedSourceId === undefined) {
    return (
      <Stack gap={4}>
        {textarea}
        {footer}
      </Stack>
    );
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between" wrap="wrap">
        <Text size="sm" fw={600}>{t('previewTitle')}</Text>
        <MultiSelect
          size="xs"
          w={260}
          clearable
          searchable
          aria-label={t('previewFieldsLabel')}
          data={fieldOptions}
          value={extraFields}
          onChange={(v) => onExtraFieldsChange(v ?? [])}
          placeholder={t('previewFieldsLabel')}
          data-testid={`preview-fields-${rule.id}`}
        />
      </Group>
      <Grid columns={20} gap="xs">
        <Grid.Col span={7}>{textarea}</Grid.Col>
        <Grid.Col span={13}>
          <ProductPreviewColumn
            field={rule.matchField}
            entries={entries}
            matches={matches}
            isFetching={lookup.isFetching}
            isError={lookup.isError}
            extraFields={extraFields}
            scrollTop={scrollTop}
            viewportRef={previewRef}
          />
        </Grid.Col>
      </Grid>
      {footer}
    </Stack>
  );
}
