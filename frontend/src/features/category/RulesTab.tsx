import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ActionIcon, Badge, Button, Card, Group, Select, Stack, Switch, Text,
  Textarea, TextInput, Title,
} from '@mantine/core';
import { IconGripVertical, IconTrash, IconEye } from '@tabler/icons-react';
import { CSS } from '@dnd-kit/utilities';
import {
  DndContext, PointerSensor, closestCenter, useSensor, useSensors,
} from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy, useSortable } from '@dnd-kit/sortable';
import { useBlocker } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  usePluginConfig, useRegistryAttributes, useSavePluginConfig, type PluginScope,
} from '../../api/hooks';
import { ConfirmModal } from '../../components/ConfirmModal';
import { ScopeBadge } from '../../components/ScopeBadge';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { useCategoryStats, useValidateCategoryRules } from './hooks';
import { MatchesModal } from './MatchesModal';
import { TaxonomyCombobox } from './TaxonomyCombobox';
import { applyRulesDragEnd } from './rulesDnd';
import { editableTier, mergeRules } from './scope';
import type { CategoryOperator, CategoryRule, ScopedCategoryRule } from './types';

const OPERATORS: CategoryOperator[] = ['eq', 'ne', 'contains', 'regex', 'in'];

function rulesOf(payload: unknown): CategoryRule[] {
  return (payload as { rules?: CategoryRule[] } | undefined)?.rules ?? [];
}

function newRuleId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `r_${Math.random().toString(36).slice(2)}`;
}

function SortableRuleRow({
  rule,
  editable,
  matchCount,
  language,
  sourceFieldOptions,
  onUpdate,
  onShowMatches,
  onDelete,
}: {
  rule: ScopedCategoryRule;
  editable: boolean;
  matchCount: number | undefined;
  language: string;
  sourceFieldOptions: { value: string; label: string }[];
  onUpdate: (patch: Partial<CategoryRule>) => void;
  onShowMatches: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation('category');
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({
    id: rule.id,
    disabled: !editable,
  });
  const isIn = rule.operator === 'in';
  const rawValue = Array.isArray(rule.source_value)
    ? rule.source_value.join('\n')
    : (rule.source_value ?? '');

  return (
    <Card
      ref={setNodeRef}
      withBorder
      radius="md"
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: editable ? undefined : 0.7,
      }}
    >
      <Group justify="space-between" mb="sm">
        <Group gap="xs">
          <ActionIcon
            {...attributes}
            {...listeners}
            variant="subtle"
            color="gray"
            aria-label={t('rules.dragHandle', { defaultValue: 'drag' })}
            style={{ cursor: editable ? 'grab' : 'default' }}
          >
            <IconGripVertical size={16} />
          </ActionIcon>
          <Text size="sm" fw={600}>{rule.id}</Text>
          {!editable && (
            <>
              <ScopeBadge tier={rule.origin} />
              <Badge size="sm" variant="light" color="gray">
                {t('rules.inherited')}
              </Badge>
            </>
          )}
          {matchCount !== undefined && (
            <Badge size="sm" variant="light" color="blue">
              {t('rules.matchesCount', { count: matchCount })}
            </Badge>
          )}
        </Group>
        <Group gap="xs">
          {matchCount !== undefined && (
            <ActionIcon
              variant="subtle"
              aria-label={t('rules.showMatches')}
              onClick={onShowMatches}
            >
              <IconEye size={16} />
            </ActionIcon>
          )}
          <ActionIcon
            variant="subtle"
            color="red"
            aria-label={t('rules.delete')}
            data-testid={`delete-${rule.id}`}
            disabled={!editable}
            onClick={onDelete}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Group>
      </Group>
      <Stack gap="sm">
        <Group grow align="flex-start">
          <Select
            label={t('rules.sourceField')}
            data={sourceFieldOptions}
            value={rule.source_field}
            onChange={(next) => next && onUpdate({ source_field: next })}
            disabled={!editable}
            searchable
          />
          <Select
            label={t('rules.operator')}
            data={OPERATORS.map((op) => ({ value: op, label: t(`rules.operators.${op}`) }))}
            value={rule.operator}
            onChange={(next) => next && onUpdate({ operator: next as CategoryOperator })}
            disabled={!editable}
          />
        </Group>
        {isIn ? (
          <Textarea
            label={t('rules.sourceValueIn')}
            minRows={3}
            value={rawValue}
            onChange={(event) =>
              onUpdate({ source_value: event.currentTarget.value.split('\n') })
            }
            disabled={!editable}
          />
        ) : (
          <TextInput
            label={t('rules.sourceValue')}
            value={rawValue}
            onChange={(event) => onUpdate({ source_value: event.currentTarget.value })}
            disabled={!editable}
          />
        )}
        <Switch
          label={t('rules.excluded')}
          checked={!!rule.is_excluded}
          onChange={(event) => onUpdate({ is_excluded: event.currentTarget.checked })}
          disabled={!editable}
        />
        <TaxonomyCombobox
          language={language}
          value={rule.taxonomy_id || null}
          onChange={(taxonomyId) => onUpdate({ taxonomy_id: taxonomyId ?? '' })}
          disabled={!editable || !!rule.is_excluded}
        />
      </Stack>
    </Card>
  );
}

export function RulesTab({
  pluginId,
  scope,
  language,
  feedSourceId,
}: {
  pluginId: string;
  scope: PluginScope;
  language: string;
  feedSourceId: number | undefined;
}) {
  const { t } = useTranslation('category');
  const tier = editableTier(scope);
  const hasClient = scope.clientId !== undefined;
  const globalConfig = usePluginConfig(pluginId);
  const clientConfig = usePluginConfig(
    pluginId, hasClient ? { clientId: scope.clientId } : undefined, hasClient,
  );
  const save = useSavePluginConfig(
    pluginId, hasClient ? { clientId: scope.clientId } : undefined,
  );
  const validate = useValidateCategoryRules();
  const stats = useCategoryStats(feedSourceId);
  const registry = useRegistryAttributes();

  const [draft, setDraft] = useState<ScopedCategoryRule[] | null>(null);
  const [matchesRule, setMatchesRule] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const savingRef = useRef(false);
  const sensors = useSensors(useSensor(PointerSensor));

  const baseline = useMemo(
    () => mergeRules(
      rulesOf(globalConfig.data),
      hasClient ? rulesOf(clientConfig.data) : [],
    ),
    [globalConfig.data, clientConfig.data, hasClient],
  );

  useEffect(() => {
    if (draft === null && !globalConfig.isLoading && !clientConfig.isLoading) {
      setDraft(baseline);
    }
  }, [baseline, globalConfig.isLoading, clientConfig.isLoading, draft]);

  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(baseline);
  const blocker = useBlocker(dirty);

  if (draft === null) {
    if (globalConfig.isLoading || clientConfig.isLoading) return <LoadingState />;
    if (globalConfig.isError || clientConfig.isError) {
      return (
        <ErrorState
          onRetry={() => {
            void globalConfig.refetch();
            void clientConfig.refetch();
          }}
        />
      );
    }
  }

  const editableRules = (draft ?? []).filter((rule) => rule.origin === tier);

  function updateRule(id: string, patch: Partial<CategoryRule>) {
    setDraft((current) =>
      (current ?? []).map((rule) => (rule.id === id ? { ...rule, ...patch } : rule)),
    );
  }

  function addRule() {
    setDraft((current) => [
      ...(current ?? []),
      {
        id: newRuleId(), source_field: 'product_type', operator: 'eq',
        source_value: '', taxonomy_id: '', is_excluded: false, origin: tier,
      },
    ]);
  }

  function saveRules() {
    if (savingRef.current) return;
    savingRef.current = true;
    const payload: CategoryRule[] = editableRules.map(({ origin: _origin, ...rule }) => rule);
    validate.mutate(payload, {
      onSuccess: () => {
        save.mutate(
          () => ({ rules: payload }),
          {
            onSuccess: () => {
              savingRef.current = false;
              notifySuccess(t('rules.saved'));
            },
            onError: (error) => {
              savingRef.current = false;
              notifyApiError(error, t('rules.saveFailed'));
            },
          },
        );
      },
      onError: (error) => {
        savingRef.current = false;
        notifyApiError(error, t('rules.validateFailed'));
      },
    });
  }

  return (
    <Stack gap="md">
      {blocker.state === 'blocked' && (
        <ConfirmModal
          opened
          title={t('rules.confirmLeaveTitle')}
          message={t('rules.confirmLeave')}
          onConfirm={blocker.proceed}
          onClose={blocker.reset}
        />
      )}
      <Group justify="space-between">
        <Title order={4}>{t('tabs.rules')}</Title>
        <Group>
          <Button variant="default" disabled={!dirty} onClick={() => setDraft(baseline)}>
            {t('rules.reset')}
          </Button>
          <Button disabled={!dirty} loading={save.isPending || validate.isPending} onClick={saveRules}>
            {t('rules.save')}
          </Button>
          <Button variant="light" onClick={addRule}>{t('rules.add')}</Button>
        </Group>
      </Group>
      {(draft ?? []).length === 0 && <EmptyState message={t('rules.empty')} />}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={(event) => {
          const overIndex = event.over
            ? (draft ?? []).findIndex((rule) => rule.id === event.over!.id)
            : null;
          setDraft((current) =>
            applyRulesDragEnd(current ?? [], String(event.active.id), overIndex),
          );
        }}
      >
        <SortableContext
          items={(draft ?? []).map((rule) => rule.id)}
          strategy={verticalListSortingStrategy}
        >
          <Stack gap="sm">
            {(draft ?? []).map((rule) => (
              <SortableRuleRow
                key={rule.id}
                rule={rule}
                editable={rule.origin === tier}
                matchCount={stats.data?.rules?.[rule.id]}
                language={language}
                sourceFieldOptions={
                  registry.data?.map((attribute) => ({
                    value: attribute.name,
                    label: attribute.name,
                  })) ?? []
                }
                onUpdate={(patch) => updateRule(rule.id, patch)}
                onShowMatches={() => setMatchesRule(rule.id)}
                onDelete={() => setDeleting(rule.id)}
              />
            ))}
          </Stack>
        </SortableContext>
      </DndContext>
      {matchesRule !== null && (
        <MatchesModal
          feedSourceId={feedSourceId}
          ruleId={matchesRule}
          opened
          onClose={() => setMatchesRule(null)}
        />
      )}
      <ConfirmModal
        opened={deleting !== null}
        title={t('rules.deleteConfirmTitle')}
        message={t('rules.deleteConfirmBody', { id: deleting ?? '' })}
        danger
        onConfirm={() => {
          setDraft((current) => (current ?? []).filter((rule) => rule.id !== deleting));
          setDeleting(null);
        }}
        onClose={() => setDeleting(null)}
      />
    </Stack>
  );
}
