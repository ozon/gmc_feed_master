import { ActionIcon, Badge, Button, Group, Paper, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useBlocker } from 'react-router';
import { apiPost } from '../../api/client';
import { useFeedSourceFields, usePluginConfig, useSavePluginConfig, type PluginScope } from '../../api/hooks';
import { notifyApiError, notifySuccess } from '../../app/notifications';

type FilterOp = 'equals' | 'not_equals' | 'contains' | 'not_contains' | 'exists' | 'empty';

type Condition = {
  field: string;
  op: FilterOp;
  arg?: string;
  caseSensitive?: boolean;
};

type FilterConfig = {
  isActive: boolean;
  conditions: Condition[];
};

type PreviewResult = { total: number; pass: number; fail: number };

const OPS: FilterOp[] = ['equals', 'not_equals', 'contains', 'not_contains', 'exists', 'empty'];
const TEXT_OPS: FilterOp[] = ['equals', 'not_equals', 'contains', 'not_contains'];

export type FilterUIProps = { pluginId: string; scope: PluginScope };

function normalizeConfig(value: unknown): FilterConfig {
  if (typeof value !== 'object' || value === null) return { isActive: true, conditions: [] };
  const raw = value as Record<string, unknown>;
  const conditions: Condition[] = [];
  if (Array.isArray(raw.conditions)) {
    for (const entry of raw.conditions) {
      if (typeof entry !== 'object' || entry === null) continue;
      const c = entry as Record<string, unknown>;
      if (typeof c.field !== 'string' || !c.field) continue;
      if (typeof c.op !== 'string' || !OPS.includes(c.op as FilterOp)) continue;
      const condition: Condition = { field: c.field, op: c.op as FilterOp };
      if (typeof c.arg === 'string') condition.arg = c.arg;
      if (typeof c.caseSensitive === 'boolean') condition.caseSensitive = c.caseSensitive;
      conditions.push(condition);
    }
  }
  return { isActive: raw.isActive !== false, conditions };
}

function configsEqual(a: FilterConfig, b: FilterConfig): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export default function FilterUI({ pluginId, scope }: FilterUIProps) {
  const { t } = useTranslation('filter');
  const { t: tCommon } = useTranslation('common');
  const config = usePluginConfig(pluginId, scope);
  const saveConfig = useSavePluginConfig(pluginId, scope);
  const fieldsQuery = useFeedSourceFields(String(scope.feedSourceId ?? ''));
  const fields = useMemo(() => fieldsQuery.data?.fields ?? [], [fieldsQuery.data]);

  const [draft, setDraft] = useState<FilterConfig>({ isActive: true, conditions: [] });
  const lastConfigRef = useRef<unknown>(null);

  useEffect(() => {
    if (config.data !== undefined && config.data !== lastConfigRef.current) {
      lastConfigRef.current = config.data;
      setDraft(normalizeConfig(config.data));
    }
  }, [config.data]);

  const serverDraft = useMemo(
    () => (config.data !== undefined ? normalizeConfig(config.data) : null),
    [config.data],
  );
  const dirty = serverDraft !== null && !configsEqual(draft, serverDraft);

  useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty) return false;
    if (currentLocation.pathname === nextLocation.pathname) return false;
    return !window.confirm(t('unsavedChanges'));
  });

  const fieldData = fields.map((f) => ({ value: f, label: f }));
  const hasIncomplete = draft.conditions.some(
    (c) => !c.field || (TEXT_OPS.includes(c.op) && (c.arg === undefined || c.arg === '')),
  );

  async function refreshPreview(): Promise<PreviewResult | null> {
    if (hasIncomplete) return null;
    try {
      return await apiPost<PreviewResult>('/plugins/filter/preview', {
        feed_source_id: scope.feedSourceId,
        conditions: draft.conditions,
      });
    } catch {
      return null;
    }
  }

  const draftKey = JSON.stringify(draft.conditions);
  const configLoaded = config.data !== undefined;
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewTick, setPreviewTick] = useState(0);

  // Live preview: one debounced (400ms) refetch after the config loads or the draft settles.
  useEffect(() => {
    if (!configLoaded || hasIncomplete) {
      setPreview(null);
      return;
    }
    const timer = setTimeout(() => setPreviewTick((n) => n + 1), 400);
    return () => clearTimeout(timer);
  }, [configLoaded, draftKey, hasIncomplete]);

  useEffect(() => {
    if (previewTick === 0) return;
    void refreshPreview().then((result) => setPreview(result));
  }, [previewTick]);

  async function onSave() {
    const payload: FilterConfig = {
      isActive: draft.isActive,
      conditions: draft.conditions.map(({ field, op, arg, caseSensitive }) =>
        TEXT_OPS.includes(op)
          ? { field, op, arg: arg ?? '', caseSensitive: caseSensitive ?? true }
          : { field, op },
      ),
    };
    try {
      await saveConfig.mutateAsync(payload);
      notifySuccess(t('saved'));
    } catch (error) {
      notifyApiError(error, t('saveFailed'));
    }
  }

  function patchCondition(index: number, patch: Partial<Condition>) {
    setDraft((prev) => ({
      ...prev,
      conditions: prev.conditions.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    }));
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text fw={500} size="lg">{t('title')}</Text>
        <Group>
          <Button variant="default" onClick={() => serverDraft && setDraft(serverDraft)} disabled={!dirty}>
            {tCommon('actions.cancel')}
          </Button>
          <Button onClick={() => void onSave()} loading={saveConfig.isPending} disabled={!dirty}>
            {tCommon('actions.save')}
          </Button>
        </Group>
      </Group>
      <Switch
        label={t('active')}
        checked={draft.isActive}
        onChange={(e) => setDraft((prev) => ({ ...prev, isActive: e.currentTarget.checked }))}
      />
      <Stack gap="xs" data-testid="filter-editor">
        {draft.conditions.map((condition, index) => (
          <Group key={index} gap="xs" wrap="nowrap" align="flex-start" data-testid={`condition-row-${index}`}>
            <Select
              aria-label={t('field')}
              data={fieldData}
              value={condition.field || null}
              onChange={(v) => patchCondition(index, { field: v ?? '' })}
              searchable
              w={180}
            />
            <Select
              aria-label={t('operator')}
              data={OPS.map((op) => ({ value: op, label: t(`ops.${op}`) }))}
              value={condition.op}
              onChange={(v) => patchCondition(index, { op: (v ?? 'equals') as FilterOp })}
              w={180}
            />
            {TEXT_OPS.includes(condition.op) ? (
              <>
                <TextInput
                  aria-label={t('value')}
                  value={condition.arg ?? ''}
                  onChange={(e) => patchCondition(index, { arg: e.currentTarget.value })}
                  w={160}
                />
                <Switch
                  aria-label={t('caseSensitive')}
                  label={t('caseSensitive')}
                  checked={condition.caseSensitive !== false}
                  onChange={(e) => patchCondition(index, { caseSensitive: e.currentTarget.checked })}
                />
              </>
            ) : null}
            <ActionIcon
              variant="subtle"
              color="red"
              aria-label={t('deleteCondition')}
              onClick={() => setDraft((prev) => ({
                ...prev,
                conditions: prev.conditions.filter((_, i) => i !== index),
              }))}
              data-testid={`condition-delete-${index}`}
            >
              <IconTrash size={14} />
            </ActionIcon>
          </Group>
        ))}
        <Button
          variant="light"
          size="xs"
          leftSection={<IconPlus size={14} />}
          onClick={() => setDraft((prev) => ({
            ...prev,
            conditions: [...prev.conditions, { field: '', op: 'equals', arg: '' }],
          }))}
          data-testid="condition-add"
          w="fit-content"
        >
          {t('addCondition')}
        </Button>
      </Stack>
      <Paper withBorder p="sm">
        {hasIncomplete ? (
          <Text size="sm" c="dimmed">{t('incomplete')}</Text>
        ) : preview ? (
          <Text size="sm">
            {t('previewPass', { pass: preview.pass, total: preview.total })}{' '}
            <Badge size="xs" variant="light" color="gray">{preview.fail}</Badge>
          </Text>
        ) : (
          <Text size="sm" c="dimmed">…</Text>
        )}
      </Paper>
    </Stack>
  );
}
