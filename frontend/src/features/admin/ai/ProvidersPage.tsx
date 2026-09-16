import { useState } from 'react';
import {
  ActionIcon, Badge, Button, Group, Modal, NumberInput, Select, Stack, Switch, Table, TextInput, Title,
} from '@mantine/core';
import { IconBolt, IconPencil, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  useAiProviders, useCreateAiProvider, useDeleteAiProvider, useTestAiProvider, useUpdateAiProvider,
} from '../../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../../app/notifications';
import { EmptyState, ErrorState, LoadingState } from '../../../components/StateViews';
import type { AiProvider } from '../../../api/types';

type ProviderPayload = {
  name: string;
  provider_type: AiProvider['provider_type'];
  tier: AiProvider['tier'];
  base_url: string;
  model: string;
  max_concurrency: number;
  timeout_s: number;
  api_key?: string;
};

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
        key={editing?.id ?? (creating ? 'create' : 'closed')}
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
              { ...payload, enabled: true, input_price_per_mtok: null, output_price_per_mtok: null },
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
  onSubmit: (payload: ProviderPayload) => void;
}) {
  const { t } = useTranslation('admin');
  const [name, setName] = useState(provider?.name ?? '');
  const [providerType, setProviderType] = useState<AiProvider['provider_type']>(
    provider?.provider_type ?? 'litellm',
  );
  const [tier, setTier] = useState<AiProvider['tier']>(provider?.tier ?? 'bulk');
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? '');
  const [model, setModel] = useState(provider?.model ?? '');
  const [apiKey, setApiKey] = useState('');
  const [maxConcurrency, setMaxConcurrency] = useState<number>(provider?.max_concurrency ?? 4);
  const [timeoutS, setTimeoutS] = useState<number>(provider?.timeout_s ?? 30);

  return (
    <Modal opened={opened} onClose={onClose} title={provider ? t('ai.edit') : t('ai.add')}>
      <Stack>
        <TextInput
          label={t('ai.columns.name')}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          data-testid="ai-modal-name"
        />
        <Select
          label={t('ai.providerType')}
          value={providerType}
          onChange={(value) => setProviderType((value ?? 'litellm') as AiProvider['provider_type'])}
          data-testid="ai-modal-provider-type"
          data={[
            { value: 'litellm', label: t('ai.providerTypeOptions.litellm') },
            { value: 'openai_compatible', label: t('ai.providerTypeOptions.openai_compatible') },
          ]}
        />
        <Select
          label={t('ai.columns.tier')}
          value={tier}
          onChange={(value) => setTier((value ?? 'bulk') as AiProvider['tier'])}
          data-testid="ai-modal-tier"
          data={[
            { value: 'bulk', label: t('ai.tier.bulk') },
            { value: 'precision', label: t('ai.tier.precision') },
          ]}
        />
        <TextInput
          label={t('ai.baseUrl')}
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.currentTarget.value)}
        />
        <TextInput
          label={t('ai.columns.model')}
          value={model}
          onChange={(e) => setModel(e.currentTarget.value)}
          data-testid="ai-modal-model"
        />
        <TextInput
          label={t('ai.apiKey')}
          placeholder={provider ? t('ai.apiKeyUnchanged') : ''}
          value={apiKey}
          onChange={(e) => setApiKey(e.currentTarget.value)}
        />
        <NumberInput
          label={t('ai.maxConcurrency')}
          value={maxConcurrency}
          min={1}
          max={64}
          onChange={(value) => setMaxConcurrency(typeof value === 'number' ? value : 4)}
        />
        <NumberInput
          label={t('ai.timeoutS')}
          value={timeoutS}
          min={1}
          max={600}
          onChange={(value) => setTimeoutS(typeof value === 'number' ? value : 30)}
        />
        <Button
          disabled={!name || !model}
          data-testid="ai-modal-save"
          onClick={() => onSubmit({
            name,
            provider_type: providerType,
            tier,
            base_url: baseUrl,
            model,
            max_concurrency: maxConcurrency,
            timeout_s: timeoutS,
            ...(apiKey !== '' ? { api_key: apiKey } : {}),
          })}
        >
          {t('ai.save')}
        </Button>
      </Stack>
    </Modal>
  );
}
