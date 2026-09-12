import { useState } from 'react';
import { Button, Divider, Modal, Select, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useCreatePromptTemplate } from '../../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../../app/notifications';
import type { PromptTemplate } from '../../../api/types';
import { PreviewPanel, previewDetailErrors } from './PreviewPanel';

export const TASK_TYPES = [
  'title_optimization',
  'category_classification',
  'policy_check',
  'attribute_enrichment',
  'image_quality',
] as const;

// ponytail: client-side mirror of backend CANONICAL_VARIABLES for instant UX warnings;
// server validation stays authoritative — if these drift, saves 422 and tell us.
export const CANONICAL_VARIABLES: Record<string, string[]> = {
  title_optimization: ['brand', 'title'],
  category_classification: ['title', 'description'],
  policy_check: ['title', 'description'],
  attribute_enrichment: ['title', 'description'],
  image_quality: ['image_link'],
};

const PLACEHOLDER_RE = /\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}/g;

function placeholders(text: string): Set<string> {
  return new Set([...text.matchAll(PLACEHOLDER_RE)].map((m) => m[1]));
}

type Props = {
  opened: boolean;
  template: PromptTemplate | null;
  clientId: number | null;
  feedOptions: { value: string; label: string }[];
  onClose: () => void;
};

export function TemplateEditor({ opened, template, clientId, feedOptions, onClose }: Props) {
  const { t } = useTranslation('admin');
  const create = useCreatePromptTemplate();
  const [taskType, setTaskType] = useState<string | null>(template?.task_type ?? null);
  const [name, setName] = useState(template?.name ?? '');
  const [system, setSystem] = useState(template?.system_prompt ?? '');
  const [user, setUser] = useState(template?.user_prompt ?? '');
  const [variables, setVariables] = useState(template?.variables.join(', ') ?? '');

  const declared = variables.split(',').map((v) => v.trim()).filter(Boolean);
  const used = new Set([...placeholders(system), ...placeholders(user)]);
  const canonical = taskType ? CANONICAL_VARIABLES[taskType] ?? [] : [];
  const unknown = [...used].filter((v) => !canonical.includes(v));
  const unusedDeclared = declared.filter((v) => !used.has(v));

  const canSave = Boolean(taskType && name && system && user && unknown.length === 0);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={template ? t('promptLibrary.edit') : t('promptLibrary.new')}
      size="lg"
    >
      <Stack gap="sm">
        <Select
          label={t('promptLibrary.editor.taskType')}
          data={TASK_TYPES.map((v) => ({ value: v, label: v }))}
          value={taskType}
          onChange={setTaskType}
          disabled={template !== null}
        />
        <TextInput
          label={t('promptLibrary.editor.name')}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <Textarea
          label={t('promptLibrary.editor.systemPrompt')}
          autosize
          minRows={3}
          value={system}
          onChange={(e) => setSystem(e.currentTarget.value)}
        />
        <Textarea
          label={t('promptLibrary.editor.userPrompt')}
          autosize
          minRows={3}
          value={user}
          onChange={(e) => setUser(e.currentTarget.value)}
        />
        <TextInput
          label={t('promptLibrary.editor.variables')}
          placeholder="title, description"
          value={variables}
          onChange={(e) => setVariables(e.currentTarget.value)}
        />
        {unknown.map((v) => (
          <Text key={v} c="red" size="sm">
            {t('promptLibrary.editor.unknownPlaceholder', { variable: v })}
          </Text>
        ))}
        {unusedDeclared.map((v) => (
          <Text key={v} c="orange" size="sm" data-testid={`unused-variable-${v}`}>
            {t('promptLibrary.editor.unusedVariable', { variable: v })}
          </Text>
        ))}
        {create.error ? (
          previewDetailErrors(create.error).map((e) => (
            <Text key={e} c="red" size="sm">{e}</Text>
          ))
        ) : null}
        <Button
          disabled={!canSave || create.isPending}
          onClick={() =>
            create.mutate(
              {
                task_type: taskType ?? '',
                client_id: template ? template.client_id : clientId,
                name,
                system_prompt: system,
                user_prompt: user,
                variables: declared,
              },
              {
                onSuccess: () => {
                  notifySuccess(t('promptLibrary.editor.saved'));
                  onClose();
                },
                onError: (error) => notifyMutationError(error, t('promptLibrary.editor.saveFailed')),
              },
            )
          }
        >
          {t('promptLibrary.editor.save')}
        </Button>
        <Divider label={t('promptLibrary.preview.dryRun')} labelPosition="left" />
        {taskType ? (
          <PreviewPanel
            feedOptions={feedOptions}
            base={{ task_type: taskType, system_prompt: system, user_prompt: user, variables: declared }}
          />
        ) : (
          <Text size="sm" c="dimmed">{t('promptLibrary.editor.pickTaskType')}</Text>
        )}
      </Stack>
    </Modal>
  );
}
