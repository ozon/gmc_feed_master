import { useState } from 'react';
import {
  ActionIcon, Badge, Button, Group, Stack, Switch, Table, Title,
} from '@mantine/core';
import { IconBolt, IconPencil, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  useAiProviders, useDeleteAiProvider, useTestAiProvider, useUpdateAiProvider,
} from '../../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../../app/notifications';
import { EmptyState, ErrorState, LoadingState } from '../../../components/StateViews';
import type { AiProvider } from '../../../api/types';
import { ProviderWizard } from './ProviderWizard';

function presetForProvider(provider: AiProvider): string {
  if (provider.provider_type === 'openai_compatible') return 'custom';
  if (provider.model.startsWith('anthropic/')) return 'anthropic';
  if (provider.model.startsWith('gemini/')) return 'google';
  if (provider.model.startsWith('openrouter/')) return 'openrouter';
  if (provider.model.startsWith('mistral/')) return 'mistral';
  if (provider.model.startsWith('groq/')) return 'groq';
  return 'openai';
}

export function ProvidersPage() {
  const { t } = useTranslation('admin');
  const providersQuery = useAiProviders();
  const updateProvider = useUpdateAiProvider();
  const deleteProvider = useDeleteAiProvider();
  const testProvider = useTestAiProvider();
  const [editing, setEditing] = useState<AiProvider | null>(null);
  const [creating, setCreating] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  if (providersQuery.isPending) return <LoadingState />;
  if (providersQuery.isError) {
    return <ErrorState onRetry={() => void providersQuery.refetch()} />;
  }
  const providers = providersQuery.data ?? [];

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={4}>{t('ai.providersTitle')}</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          data-testid="ai-add-provider"
          onClick={() => setCreating(true)}
        >
          {t('ai.add')}
        </Button>
      </Group>
      {providers.length === 0 ? (
        <EmptyState message={t('ai.empty')} />
      ) : (
        <Table data-testid="ai-providers-table" striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('ai.columns.name')}</Table.Th>
              <Table.Th>{t('ai.columns.model')}</Table.Th>
              <Table.Th>{t('ai.columns.tier')}</Table.Th>
              <Table.Th>{t('ai.columns.enabled')}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {providers.map((provider) => (
              <Table.Tr key={provider.id} data-testid={`ai-provider-row-${provider.id}`}>
                <Table.Td>{provider.name}</Table.Td>
                <Table.Td>{provider.model}</Table.Td>
                <Table.Td>
                  <Badge variant="light" color={provider.tier === 'precision' ? 'grape' : 'blue'}>
                    {t(`ai.tier.${provider.tier}`)}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Switch
                    aria-label={t('ai.columns.enabled')}
                    checked={provider.enabled}
                    onChange={(event) =>
                      updateProvider.mutate(
                        { id: provider.id, enabled: event.currentTarget.checked },
                        { onError: (error) => notifyMutationError(error, t('ai.saveFailed')) },
                      )
                    }
                  />
                </Table.Td>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap">
                    <ActionIcon
                      variant="subtle"
                      aria-label={t('ai.test')}
                      onClick={() => {
                        testProvider.mutate(provider.id, {
                          onSuccess: (result) =>
                            setTestResult(
                              result.status === 'ok'
                                ? t('ai.testOk', { latency: result.latency_ms ?? 0 })
                                : t('ai.testFailed', { code: result.error_code ?? 'unknown' }),
                            ),
                        });
                      }}
                    >
                      <IconBolt size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      aria-label={t('ai.edit')}
                      onClick={() => setEditing(provider)}
                    >
                      <IconPencil size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={t('ai.delete')}
                      onClick={() =>
                        deleteProvider.mutate(provider.id, {
                          onSuccess: () => notifySuccess(t('ai.deleted')),
                          onError: (error) => notifyMutationError(error, t('ai.deleteFailed')),
                        })
                      }
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {testResult ? <div data-testid="ai-test-result">{testResult}</div> : null}
      <ProviderWizard
        key={editing?.id ?? (creating ? 'create' : 'closed')}
        opened={creating || editing !== null}
        provider={editing}
        presetKey={editing ? presetForProvider(editing) : 'openai'}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
      />
    </Stack>
  );
}
