import { useState } from 'react';
import {
  ActionIcon, Badge, Button, Group, Modal, Select, Stack, Table, Text, Title,
} from '@mantine/core';
import { IconEye, IconGitBranch, IconPencil, IconPlus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  useActivatePromptTemplate, useDashboardSummary, usePromptTemplates,
} from '../../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../../app/notifications';
import { EmptyState, ErrorState, LoadingState } from '../../../components/StateViews';
import type { PromptTemplate } from '../../../api/types';
import { TemplateEditor } from './TemplateEditor';
import { PreviewPanel } from './PreviewPanel';

export function PromptLibraryPage() {
  const { t } = useTranslation('admin');
  const templatesQuery = usePromptTemplates();
  const clientsQuery = useDashboardSummary();
  const activate = useActivatePromptTemplate();
  const [scope, setScope] = useState<string>('global');
  const [editing, setEditing] = useState<{ template: PromptTemplate | null } | null>(null);
  const [previewing, setPreviewing] = useState<PromptTemplate | null>(null);
  const [diffGroup, setDiffGroup] = useState<PromptTemplate[] | null>(null);

  if (templatesQuery.isPending || clientsQuery.isPending) return <LoadingState />;
  if (templatesQuery.isError) {
    return <ErrorState onRetry={() => void templatesQuery.refetch()} />;
  }

  const clients = clientsQuery.data?.clients ?? [];
  const all = templatesQuery.data ?? [];
  const scoped = scope === 'global'
    ? all.filter((t) => t.client_id === null)
    : all.filter((t) => t.client_id === Number(scope));
  const groups = new Map<string, PromptTemplate[]>();
  for (const template of scoped) {
    const rows = groups.get(template.task_type) ?? [];
    rows.push(template);
    groups.set(template.task_type, rows);
  }
  const feedOptions = clients.flatMap((c) =>
    c.feed_sources.map((f) => ({ value: String(f.id), label: `${c.name} / ${f.name}` })),
  );

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={4}>{t('promptLibrary.title')}</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing({ template: null })}>
          {t('promptLibrary.new')}
        </Button>
      </Group>
      <Select
        label={t('promptLibrary.scope')}
        w={300}
        data={[
          { value: 'global', label: t('promptLibrary.globalScope') },
          ...clients.map((c) => ({ value: String(c.id), label: c.name })),
        ]}
        value={scope}
        onChange={(v) => setScope(v ?? 'global')}
      />
      {groups.size === 0 ? (
        <EmptyState message={t('promptLibrary.empty')} />
      ) : (
        [...groups.entries()].map(([taskType, rows]) => (
          <Stack key={taskType} gap="xs">
            <Group justify="space-between">
              <Title order={5}>{taskType}</Title>
              <ActionIcon
                variant="subtle"
                aria-label={t('promptLibrary.diff.title')}
                title={t('promptLibrary.diff.title')}
                onClick={() => setDiffGroup(rows)}
              >
                <IconGitBranch size={16} />
              </ActionIcon>
            </Group>
            <Table data-testid={`template-group-${taskType}`} striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('promptLibrary.columns.version')}</Table.Th>
                  <Table.Th>{t('promptLibrary.columns.name')}</Table.Th>
                  <Table.Th>{t('promptLibrary.columns.status')}</Table.Th>
                  <Table.Th>{t('promptLibrary.columns.created')}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((row) => (
                  <Table.Tr key={row.id} data-testid={`template-row-${row.id}`}>
                    <Table.Td>v{row.version}</Table.Td>
                    <Table.Td>{row.name}</Table.Td>
                    <Table.Td>
                      {row.is_active ? (
                        <Badge variant="light" color="green">{t('promptLibrary.active')}</Badge>
                      ) : null}
                    </Table.Td>
                    <Table.Td>{row.created_by ?? '—'}</Table.Td>
                    <Table.Td>
                      <Group gap="xs" wrap="nowrap">
                        {!row.is_active ? (
                          <Button
                            size="compact-xs"
                            onClick={() =>
                              activate.mutate(row.id, {
                                onSuccess: () => notifySuccess(t('promptLibrary.activated')),
                                onError: (error) => notifyMutationError(error, t('promptLibrary.activateFailed')),
                              })
                            }
                          >
                            {t('promptLibrary.activate')}
                          </Button>
                        ) : null}
                        <ActionIcon
                          variant="subtle"
                          aria-label={t('promptLibrary.preview.title')}
                          onClick={() => setPreviewing(row)}
                        >
                          <IconEye size={16} />
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          aria-label={t('promptLibrary.edit')}
                          onClick={() => setEditing({ template: row })}
                        >
                          <IconPencil size={16} />
                        </ActionIcon>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Stack>
        ))
      )}
      <TemplateEditor
        opened={editing !== null}
        template={editing?.template ?? null}
        clientId={scope === 'global' ? null : Number(scope)}
        feedOptions={feedOptions}
        onClose={() => setEditing(null)}
      />
      <Modal
        opened={previewing !== null}
        onClose={() => setPreviewing(null)}
        title={t('promptLibrary.preview.title')}
        size="lg"
      >
        {previewing ? (
          <PreviewPanel
            feedOptions={feedOptions}
            base={{ task_type: previewing.task_type, template_id: previewing.id }}
          />
        ) : null}
      </Modal>
      <DiffModal templates={diffGroup ?? []} opened={diffGroup !== null} onClose={() => setDiffGroup(null)} />
    </Stack>
  );
}

function DiffModal({
  templates, opened, onClose,
}: {
  templates: PromptTemplate[];
  opened: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation('admin');
  const sorted = [...templates].sort((a, b) => a.version - b.version);
  const [idA, setIdA] = useState<string | null>(null);
  const [idB, setIdB] = useState<string | null>(null);
  const a = sorted.find((t) => String(t.id) === idA) ?? sorted[sorted.length - 2];
  const b = sorted.find((t) => String(t.id) === idB) ?? sorted[sorted.length - 1];

  if (sorted.length < 2) {
    return (
      <Modal opened={opened} onClose={onClose} title={t('promptLibrary.diff.title')}>
        <Text>{t('promptLibrary.diff.needTwo')}</Text>
      </Modal>
    );
  }
  return (
    <Modal opened={opened} onClose={onClose} title={t('promptLibrary.diff.title')} size="xl">
      <Stack gap="sm">
        <Group grow>
          <Select
            label={t('promptLibrary.diff.versionA')}
            data={sorted.map((t) => ({ value: String(t.id), label: `v${t.version} — ${t.name}` }))}
            value={a ? String(a.id) : null}
            onChange={setIdA}
          />
          <Select
            label={t('promptLibrary.diff.versionB')}
            data={sorted.map((t) => ({ value: String(t.id), label: `v${t.version} — ${t.name}` }))}
            value={b ? String(b.id) : null}
            onChange={setIdB}
          />
        </Group>
        {a && b ? (
          // ponytail: raw side-by-side, no diff algorithm — eyeball it; add a line-diff when prompts grow past a screen
          <Group grow align="start" wrap="nowrap">
            <Stack gap="xs">
              <Text fw={500}>v{a.version} — {a.name}</Text>
              <Text size="sm" fw={500}>System</Text>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{a.system_prompt}</pre>
              <Text size="sm" fw={500}>User</Text>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{a.user_prompt}</pre>
            </Stack>
            <Stack gap="xs">
              <Text fw={500}>v{b.version} — {b.name}</Text>
              <Text size="sm" fw={500}>System</Text>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{b.system_prompt}</pre>
              <Text size="sm" fw={500}>User</Text>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{b.user_prompt}</pre>
            </Stack>
          </Group>
        ) : null}
      </Stack>
    </Modal>
  );
}
