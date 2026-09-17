import { Button, Group, Modal, MultiSelect, Select, Stack, Text, Textarea } from '@mantine/core';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FieldSelect } from '../../components/FieldSelect';
import type { GroupedFieldOptions } from '../../api/fieldOptions';
import type { RuleAction } from '../../../../plugins/core/rules/frontend/ast';
import { useRuleAiPreview, useRuleAiTemplates } from './hooks';

const STRUCTURED_TASKS = [
  'title_optimization',
  'description_optimization',
  'category_classification',
  'attribute_enrichment',
] as const;

const OUTPUT_FIELDS: Record<string, string[]> = {
  title_optimization: ['title'],
  description_optimization: ['description'],
  category_classification: ['google_product_category'],
  attribute_enrichment: [
    'color', 'size', 'material', 'gtin', 'gender', 'age_group',
    'custom_label_0', 'custom_label_1', 'custom_label_2', 'custom_label_3', 'custom_label_4',
  ],
};

export type RuleAiActionEditorProps = {
  action: RuleAction;
  fieldOptions: GroupedFieldOptions;
  feedSourceId?: number;
  onChange: (next: RuleAction) => void;
};

export function RuleAiActionEditor({
  action, fieldOptions, feedSourceId, onChange,
}: RuleAiActionEditorProps) {
  const { t } = useTranslation('rules');
  const source = action.promptSource ?? 'template';
  const [previewOpen, setPreviewOpen] = useState(false);

  const templates = useRuleAiTemplates(
    feedSourceId,
    source === 'template' ? action.taskType : undefined,
  );
  const preview = useRuleAiPreview();

  const knownFields = useMemo(
    () => fieldOptions.flatMap((group) => group.items.map((item) => item.value)),
    [fieldOptions],
  );
  const templateOptions = useMemo(
    () => (templates.data?.items ?? []).map((item) => ({ value: String(item.id), label: item.name })),
    [templates.data],
  );

  function switchSource(next: 'template' | 'custom') {
    if (next === 'custom') {
      onChange({
        op: 'ai', promptSource: 'custom', taskType: 'rule_value',
        field: action.field || '', system: '', user: '', variables: [],
      });
    } else {
      onChange({
        op: 'ai', promptSource: 'template',
        taskType: STRUCTURED_TASKS[0], field: action.field || '',
      });
    }
  }

  function previewPayload() {
    if (source === 'custom') {
      return {
        feed_source_id: feedSourceId ?? 0, taskType: 'rule_value',
        system: action.system ?? '', user: action.user ?? '',
        variables: action.variables ?? [],
      };
    }
    return {
      feed_source_id: feedSourceId ?? 0, taskType: action.taskType ?? '',
      templateId: action.templateId,
    };
  }

  function runPreview() {
    if (!feedSourceId) return;
    preview.mutate(previewPayload(), { onSuccess: () => setPreviewOpen(true) });
  }

  return (
    <Stack gap="xs" data-testid="ai-action-editor">
      <Group gap="xs" align="flex-end" wrap="wrap">
        <Select
          aria-label={t('ai.source')}
          data={[
            { value: 'template', label: t('ai.template') },
            { value: 'custom', label: t('ai.custom') },
          ]}
          value={source}
          onChange={(v) => switchSource(v === 'custom' ? 'custom' : 'template')}
          data-testid="ai-source"
          w={140}
        />
        {source === 'template' ? (
          <>
            <Select
              aria-label={t('ai.task')}
              data={STRUCTURED_TASKS.map((task) => ({ value: task, label: t(`ai.tasks.${task}`) }))}
              value={action.taskType ?? STRUCTURED_TASKS[0]}
              onChange={(v) => onChange({
                ...action, taskType: v ?? STRUCTURED_TASKS[0], templateId: undefined,
              })}
              w={200}
            />
            <Select
              aria-label={t('ai.templatePick')}
              data={templateOptions}
              value={action.templateId === undefined ? null : String(action.templateId)}
              onChange={(v) => onChange({
                ...action, templateId: v === null ? undefined : Number(v),
              })}
              w={200}
            />
          </>
        ) : (
          <FieldSelect
            aria-label={t('ai.targetField')}
            value={action.field}
            onChange={(v) => onChange({ ...action, field: v })}
            options={fieldOptions}
            w={200}
          />
        )}
        <Button variant="light" size="xs" onClick={runPreview} loading={preview.isPending}>
          {t('ai.preview')}
        </Button>
      </Group>

      {source === 'template' ? (
        <Text size="xs" c="dimmed">
          {t('ai.outputFields', {
            fields: (OUTPUT_FIELDS[action.taskType ?? ''] ?? []).join(', '),
          })}
        </Text>
      ) : (
        <Stack gap="xs">
          <Textarea
            aria-label={t('ai.system')}
            placeholder={t('ai.system')}
            value={action.system ?? ''}
            onChange={(e) => onChange({ ...action, system: e.currentTarget.value })}
            minRows={2}
          />
          <Textarea
            aria-label={t('ai.user')}
            placeholder={t('ai.user')}
            value={action.user ?? ''}
            onChange={(e) => onChange({ ...action, user: e.currentTarget.value })}
            minRows={3}
          />
          <MultiSelect
            aria-label={t('ai.variables')}
            data={knownFields}
            value={action.variables ?? []}
            onChange={(values) => onChange({ ...action, variables: values })}
            searchable
          />
        </Stack>
      )}

      <Modal
        opened={previewOpen}
        onClose={() => setPreviewOpen(false)}
        title={t('ai.previewTitle')}
        size="lg"
      >
        <Stack gap="xs" data-testid="ai-preview">
          {(preview.data?.messages ?? []).map((message, index) => (
            <Text key={index} size="xs" style={{ whiteSpace: 'pre-wrap' }}>
              <strong>{message.role}</strong>: {message.content}
            </Text>
          ))}
          {(preview.data?.warnings ?? []).map((warning, index) => (
            <Text key={`w-${index}`} size="xs" c="orange">{warning}</Text>
          ))}
          {preview.isError ? <Text size="xs" c="red">{String(preview.error)}</Text> : null}
        </Stack>
      </Modal>
    </Stack>
  );
}
