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
import { ProviderWizard, type ProviderWizardSubmitPayload } from './ProviderWizard';

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

/**
 * GFM-12: new providers go through the 3-step `ProviderWizard`
 * (Anbieter -> API-Key -> Modell); editing an existing row keeps the
 * original field-by-field `ProviderModal`, since legacy `openai_compatible`
 * rows may not map cleanly onto a single preset.
 */
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

  function handleWizardSubmit(payload: ProviderWizardSubmitPayload) {
    createProvider.mutate(
      {
        ...payload,
        enabled: true,
        input_price_per_mtok: payload.input_price_per_mtok,
        output_price_per_mtok: payload.output_price_per_mtok,
      },
      {
        onSuccess: () => {
          notifySuccess(t('ai.saved'));
          setCreating(false);
        },
        onError: (error) => notifyMutationError(error, t('ai.saveFailed')),
      },
    );
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('ai.providersTitle')}</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          data-testid="ai-add-provider"
          onClick={() => setCreating(true)}
        >
          {t('ai.add')}
        </Button>
      </Group>

      {providers.length === 0 ? (
        <EmptyState title={t('ai.noProviders')} />
      ) : (
        <Table>
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
              <Table.Tr key={provider.id}>
                <Table.Td>
                  <Group gap="xs">
                    {provider.name}
                    {provider.provider_type === 'openai_compatible' && (
                      <Badge size="xs" color="gray" variant="light">{t('ai.legacy', 'Legacy')}</Badge>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>{provider.model}</Table.Td>
                <Table.Td>
                  <Badge>{t(`ai.tier.${provider.tier}`)}</Badge>
                </Table.Td>
                <Table.Td>
                  <Switch
                    checked={provider.enabled}
                    onChange={(event) => updateProvider.mutate(
                      { id: provider.id, enabled: event.currentTarget.checked },
                      { onError: (error) => notifyMutationError(error, t('ai.saveFailed')) },
                    )}
                  />
                </Table.Td>
                <Table.Td>
                  <Group gap={4} justify="flex-end">
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
                    <ActionIcon variant="subtle" aria-label={t('ai.edit')} onClick={() => setEditing(provider)}>
                      <IconPencil size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={t('ai.delete')}
                      onClick={() => deleteProvider.mutate(provider.id, {
                        onSuccess: () => notifySuccess(t('ai.deleted')),
                        onError: (error) => notifyMutationError(error, t('ai.deleteFailed')),
                      })}
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

      {testResult ? <Badge color="gray">{testResult}</Badge> : null}

      <Modal opened={creating} onClose={() => setCreating(false)} title={t('ai.add')} size="lg">
        <ProviderWizard
          submitting={createProvider.isPending}
          onSubmit={handleWizardSubmit}
          onTestConnection={async (payload) => {
            const created = await createProvider.mutateAsync({
              ...payload,
              enabled: false,
              input_price_per_mtok: payload.input_price_per_mtok,
              output_price_per_mtok: payload.output_price_per_mtok,
            });
            return testProvider.mutateAsync(created.id);
          }}
        />
      </Modal>

      <ProviderModal
        opened={editing !== null}
        provider={editing}
        onClose={() => setEditing(null)}
        onSubmit={(payload) => {
          if (!editing) return;
          updateProvider.mutate(
            { id: editing.id, ...payload },
            {
              onSuccess: () => {
                notifySuccess(t('ai.saved'));
                setEditing(null);
              },
              onError: (error) => notifyMutationError(error, t('ai.saveFailed')),
            },
          );
        }}
      />
    </Stack>
  );
}

/**
 * Field-by-field edit modal, unchanged from the pre-wizard flow. Used only
 * for editing existing providers (including legacy `openai_compatible`
 * rows), which don't necessarily map onto a single wizard preset.
 */
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
  const [maxConcurrency, setMaxConcurrency] = useState(provider?.max_concurrency ?? 4);
  const [timeoutS, setTimeoutS] = useState(provider?.timeout_s ?? 30);

  return (
    <Modal opened={opened} onClose={onClose} title={provider ? t('ai.edit') : t('ai.add')}>
      <Stack>
        <TextInput
          label={t('ai.fields.name')}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          data-testid="ai-modal-name"
        />
        <Select
          label={t('ai.fields.providerType')}
          value={providerType}
          onChange={(value) => setProviderType((value ?? 'litellm') as AiProvider['provider_type'])}
          data-testid="ai-modal-provider-type"
          data={[
            { value: 'litellm', label: t('ai.providerTypeOptions.litellm') },
            { value: 'openai_compatible', label: t('ai.providerTypeOptions.openai_compatible') },
          ]}
        />
        <Select
          label={t('ai.fields.tier')}
          value={tier}
          onChange={(value) => setTier((value ?? 'bulk') as AiProvider['tier'])}
          data-testid="ai-modal-tier"
          data={[
            { value: 'bulk', label: t('ai.tier.bulk') },
            { value: 'precision', label: t('ai.tier.precision') },
          ]}
        />
        <TextInput
          label={t('ai.fields.baseUrl')}
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.currentTarget.value)}
        />
        <TextInput
          label={t('ai.fields.model')}
          value={model}
          onChange={(e) => setModel(e.currentTarget.value)}
          data-testid="ai-modal-model"
        />
        <TextInput
          label={t('ai.fields.apiKey')}
          value={apiKey}
          onChange={(e) => setApiKey(e.currentTarget.value)}
          placeholder={provider ? t('ai.fields.apiKeyUnchanged') : undefined}
        />
        <NumberInput
          label={t('ai.fields.maxConcurrency')}
          value={maxConcurrency}
          onChange={(value) => setMaxConcurrency(typeof value === 'number' ? value : 4)}
        />
        <NumberInput
          label={t('ai.fields.timeoutS')}
          value={timeoutS}
          onChange={(value) => setTimeoutS(typeof value === 'number' ? value : 30)}
        />
        <Group justify="flex-end">
          <Button
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
        </Group>
      </Stack>
    </Modal>
  );
}
