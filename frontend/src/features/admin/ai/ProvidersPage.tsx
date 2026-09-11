import { useState } from 'react';
import {
  ActionIcon, Badge, Button, Group, Modal, Stack, Switch, Table, TextInput, Title,
} from '@mantine/core';
import { IconBolt, IconPencil, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  useAiProviders, useCreateAiProvider, useDeleteAiProvider, useTestAiProvider, useUpdateAiProvider,
} from '../../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../../app/notifications';
import { EmptyState, ErrorState, LoadingState } from '../../../components/StateViews';
import type { AiProvider } from '../../../api/types';

export function ProvidersPage() {
  const { t } = useTranslation('admin');
  const providersQuery = useAiProviders();
  const createProvider = useCreateAiProvider();
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
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
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
              <Table.Th>{t('ai.columns.enabled')}</Table.Th>
              <Table.Th>{t('ai.columns.default')}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {providers.map((provider) => (
              <Table.Tr key={provider.id} data-testid={`ai-provider-row-${provider.id}`}>
                <Table.Td>{provider.name}</Table.Td>
                <Table.Td>{provider.model}</Table.Td>
                <Table.Td>
                  <Switch
                    aria-label={t('ai.columns.enabled')}
                    checked={provider.enabled}
                    onChange={(event) =>
                      updateProvider.mutate({ id: provider.id, enabled: event.currentTarget.checked })
                    }
                  />
                </Table.Td>
                <Table.Td>
                  {provider.is_default ? (
                    <Badge variant="light" color="grape">{t('ai.default')}</Badge>
                  ) : null}
                </Table.Td>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap">
                    <ActionIcon
                      variant="subtle"
                      aria-label={t('ai.test')}
                      onClick={() => {
                        testProvider.mutate(provider.id, {
                          onSuccess: (result) => setTestResult(
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
      <ProviderModal
        opened={creating || editing !== null}
        provider={editing}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
        onSubmit={(payload) => {
          const close = () => {
            setCreating(false);
            setEditing(null);
          };
          if (editing) {
            updateProvider.mutate(
              { id: editing.id, ...payload },
              {
                onSuccess: () => {
                  notifySuccess(t('ai.saved'));
                  close();
                },
                onError: (error) => notifyMutationError(error, t('ai.saveFailed')),
              },
            );
          } else {
            createProvider.mutate(
              {
                name: String(payload.name ?? ''),
                provider_type: 'openai_compatible',
                base_url: String(payload.base_url ?? ''),
                model: String(payload.model ?? ''),
                input_price_per_mtok: null,
                output_price_per_mtok: null,
                max_concurrency: 4,
                timeout_s: 30,
                enabled: true,
                is_default: Boolean(payload.is_default),
                ...(payload.api_key !== undefined ? { api_key: String(payload.api_key) } : {}),
              },
              {
                onSuccess: () => {
                  notifySuccess(t('ai.saved'));
                  close();
                },
                onError: (error) => notifyMutationError(error, t('ai.saveFailed')),
              },
            );
          }
        }}
      />
    </Stack>
  );
}

function ProviderModal({
  opened, provider, onClose, onSubmit,
}: {
  opened: boolean;
  provider: AiProvider | null;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation('admin');
  const [name, setName] = useState(provider?.name ?? '');
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? '');
  const [model, setModel] = useState(provider?.model ?? '');
  const [apiKey, setApiKey] = useState('');
  const [isDefault, setIsDefault] = useState(provider?.is_default ?? false);

  return (
    <Modal opened={opened} onClose={onClose} title={provider ? t('ai.edit') : t('ai.add')}>
      <Stack>
        <TextInput
          label={t('ai.columns.name')}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          data-testid="ai-modal-name"
        />
        <TextInput
          label="Base URL"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.currentTarget.value)}
        />
        <TextInput
          label="Model"
          value={model}
          onChange={(e) => setModel(e.currentTarget.value)}
        />
        <TextInput
          label={t('ai.apiKey')}
          placeholder={provider ? t('ai.apiKeyUnchanged') : ''}
          value={apiKey}
          onChange={(e) => setApiKey(e.currentTarget.value)}
        />
        <Switch
          label={t('ai.columns.default')}
          checked={isDefault}
          onChange={(e) => setIsDefault(e.currentTarget.checked)}
        />
        <Button
          disabled={!name || !baseUrl || !model}
          onClick={() => onSubmit({
            name, base_url: baseUrl, model,
            ...(apiKey !== '' ? { api_key: apiKey } : {}),
            is_default: isDefault,
          })}
        >
          {t('ai.save')}
        </Button>
      </Stack>
    </Modal>
  );
}
