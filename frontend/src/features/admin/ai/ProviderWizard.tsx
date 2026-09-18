import { useMemo, useState } from 'react';
import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  NumberInput,
  Radio,
  Select,
  Stack,
  Stepper,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { IconExternalLink } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  useCreateAiProvider,
  useModelCatalog,
  useProviderPresets,
  useTestAiProvider,
  useUpdateAiProvider,
} from '../../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../../app/notifications';
import type { AiProvider } from '../../../api/types';

type ProviderPayload = {
  name: string;
  provider_type: 'litellm';
  tier: 'bulk' | 'precision';
  base_url: string;
  model: string;
  max_concurrency: number;
  timeout_s: number;
  input_price_per_mtok: string | null;
  output_price_per_mtok: string | null;
  enabled: boolean;
  api_key?: string;
};

const CUSTOM = 'custom';

export function ProviderWizard({
  opened,
  provider,
  presetKey,
  onClose,
}: {
  opened: boolean;
  provider: AiProvider | null;
  presetKey: string;
  onClose: () => void;
}) {
  const { t } = useTranslation('admin');
  const presetsQuery = useProviderPresets();
  const createProvider = useCreateAiProvider();
  const updateProvider = useUpdateAiProvider();
  const testProvider = useTestAiProvider();

  const presets = presetsQuery.data ?? [];
  const [active, setActive] = useState(0);
  const [vendor, setVendor] = useState(presetKey);
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? '');
  const [model, setModel] = useState(provider?.model ?? '');
  const [name, setName] = useState(provider?.name ?? '');
  const [tier, setTier] = useState<'bulk' | 'precision'>(provider?.tier ?? 'bulk');
  const [maxConcurrency, setMaxConcurrency] = useState(provider?.max_concurrency ?? 4);
  const [timeoutS, setTimeoutS] = useState(provider?.timeout_s ?? 30);
  const [inputPrice, setInputPrice] = useState<string | null>(
    provider?.input_price_per_mtok ?? null,
  );
  const [outputPrice, setOutputPrice] = useState<string | null>(
    provider?.output_price_per_mtok ?? null,
  );
  const [enabled, setEnabled] = useState(provider?.enabled ?? true);
  const [sortBy, setSortBy] = useState<'price' | 'context'>('price');
  const [testResult, setTestResult] = useState<string | null>(null);

  const preset = presets.find((item) => item.vendor_key === vendor);
  const isCustom = preset?.vendor_key === CUSTOM;
  const baseUrlRequired = preset?.requires_base_url ?? false;
  const catalogQuery = useModelCatalog(preset && preset.supports_catalog ? vendor : null);
  const entries = useMemo(() => catalogQuery.data?.entries ?? [], [catalogQuery.data]);

  const sortedEntries = useMemo(() => {
    const copy = [...entries];
    if (sortBy === 'price') {
      copy.sort(
        (a, b) => Number(a.input_price_per_mtok ?? 1e9) - Number(b.input_price_per_mtok ?? 1e9),
      );
    } else {
      copy.sort((a, b) => (b.context_window ?? 0) - (a.context_window ?? 0));
    }
    return copy;
  }, [entries, sortBy]);

  const recommended = useMemo(
    () => entries.find((entry) => entry.is_recommended) ?? entries[0] ?? null,
    [entries],
  );
  const effectiveModel = model || recommended?.model_id || '';
  const selectedEntry = entries.find((entry) => entry.model_id === effectiveModel) ?? null;
  const autoName =
    preset && effectiveModel ? `${preset.label} ${effectiveModel.split('/').pop()}` : '';
  const displayName = name || autoName;

  const canAdvance =
    active === 0
      ? Boolean(preset)
      : active === 1
        ? (apiKey !== '' || provider !== null) && (!baseUrlRequired || baseUrl !== '')
        : effectiveModel !== '';

  function submit() {
    const payload: ProviderPayload = {
      name: displayName || preset?.label || 'Provider',
      provider_type: 'litellm',
      tier,
      base_url: baseUrl,
      model: effectiveModel,
      max_concurrency: maxConcurrency,
      timeout_s: timeoutS,
      input_price_per_mtok: inputPrice,
      output_price_per_mtok: outputPrice,
      enabled,
      ...(apiKey !== '' ? { api_key: apiKey } : {}),
    };
    const runTest = (id: number) =>
      testProvider.mutate(id, {
        onSuccess: (result) =>
          setTestResult(
            result.status === 'ok'
              ? t('ai.wizard.testOk', { latency: result.latency_ms ?? 0 })
              : t('ai.wizard.testFailed', { code: result.error_code ?? 'unknown' }),
          ),
      });
    if (provider) {
      updateProvider.mutate(
        { id: provider.id, ...payload },
        {
          onSuccess: () => {
            notifySuccess(t('ai.saved'));
            runTest(provider.id);
          },
          onError: (error) => notifyMutationError(error, t('ai.saveFailed')),
        },
      );
    } else {
      createProvider.mutate(payload, {
        onSuccess: (created) => {
          notifySuccess(t('ai.saved'));
          runTest(created.id);
        },
        onError: (error) => notifyMutationError(error, t('ai.saveFailed')),
      });
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="lg"
      title={provider ? t('ai.wizard.editTitle') : t('ai.wizard.title')}
    >
      <Stepper active={active} onStepClick={setActive} data-testid="ai-wizard">
        <Stepper.Step label={t('ai.wizard.steps.provider')}>
          <Radio.Group value={vendor} onChange={setVendor} mt="md">
            <Stack>
              {presets.map((item) => (
                <Card
                  key={item.vendor_key}
                  withBorder
                  data-testid={`ai-wizard-preset-${item.vendor_key}`}
                  onClick={() => setVendor(item.vendor_key)}
                  style={{ cursor: 'pointer' }}
                >
                  <Group justify="space-between">
                    <Radio value={item.vendor_key} label={item.label} />
                    {item.docs_url ? (
                      <Anchor
                        href={item.docs_url}
                        target="_blank"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {t('ai.wizard.docsHint')} <IconExternalLink size={14} />
                      </Anchor>
                    ) : null}
                  </Group>
                </Card>
              ))}
            </Stack>
          </Radio.Group>
        </Stepper.Step>

        <Stepper.Step label={t('ai.wizard.steps.key')}>
          <Stack mt="md">
            <TextInput
              type="password"
              label={t('ai.apiKey')}
              placeholder={provider ? t('ai.apiKeyUnchanged') : ''}
              value={apiKey}
              onChange={(event) => setApiKey(event.currentTarget.value)}
              data-testid="ai-wizard-api-key"
            />
            {baseUrlRequired ? (
              <TextInput
                label={t('ai.wizard.baseUrl')}
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.currentTarget.value)}
                data-testid="ai-wizard-base-url"
              />
            ) : null}
          </Stack>
        </Stepper.Step>

        <Stepper.Step label={t('ai.wizard.steps.model')}>
          <Stack mt="md">
            {isCustom ? (
              <TextInput
                label={t('ai.wizard.modelCustom')}
                value={model}
                onChange={(event) => setModel(event.currentTarget.value)}
                data-testid="ai-wizard-model-custom"
              />
            ) : (
              <>
                <Select
                  searchable
                  label={t('ai.wizard.modelHeading')}
                  data={sortedEntries.map((entry) => ({
                    value: entry.model_id,
                    label: entry.display_name,
                  }))}
                  value={effectiveModel || null}
                  onChange={(value) => setModel(value ?? '')}
                  data-testid="ai-wizard-model-select"
                />
                <Select
                  label={t('ai.wizard.sortBy')}
                  value={sortBy}
                  onChange={(value) => setSortBy(value === 'context' ? 'context' : 'price')}
                  data={[
                    { value: 'price', label: t('ai.wizard.sortPrice') },
                    { value: 'context', label: t('ai.wizard.sortContext') },
                  ]}
                />
              </>
            )}
            {selectedEntry ? (
              <Group gap="xs">
                {selectedEntry.is_recommended ? (
                  <Badge color="green">{t('ai.wizard.recommended')}</Badge>
                ) : null}
                {selectedEntry.supports_vision ? (
                  <Badge variant="light">{t('ai.wizard.vision')}</Badge>
                ) : null}
                {selectedEntry.supports_function_calling ? (
                  <Badge variant="light">{t('ai.wizard.tools')}</Badge>
                ) : null}
                {selectedEntry.context_window ? (
                  <Text size="xs">{selectedEntry.context_window.toLocaleString()} tokens</Text>
                ) : null}
              </Group>
            ) : null}
          </Stack>
        </Stepper.Step>
      </Stepper>

      <Accordion variant="separated" mt="md" data-testid="ai-wizard-advanced">
        <Accordion.Item value="advanced">
          <Accordion.Control>{t('ai.wizard.advanced')}</Accordion.Control>
          <Accordion.Panel>
            <Stack>
              <TextInput
                label={t('ai.columns.name')}
                value={displayName}
                onChange={(event) => setName(event.currentTarget.value)}
                data-testid="ai-wizard-name"
              />
              <Select
                label={t('ai.columns.tier')}
                value={tier}
                onChange={(value) => setTier(value === 'precision' ? 'precision' : 'bulk')}
                data={[
                  { value: 'bulk', label: t('ai.tier.bulk') },
                  { value: 'precision', label: t('ai.tier.precision') },
                ]}
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
              <NumberInput
                label={t('ai.wizard.inputPrice')}
                value={inputPrice ?? ''}
                min={0}
                decimalScale={6}
                onChange={(value) =>
                  setInputPrice(value === '' || value === undefined ? null : String(value))
                }
              />
              <NumberInput
                label={t('ai.wizard.outputPrice')}
                value={outputPrice ?? ''}
                min={0}
                decimalScale={6}
                onChange={(value) =>
                  setOutputPrice(value === '' || value === undefined ? null : String(value))
                }
              />
              <Switch
                label={t('ai.columns.enabled')}
                checked={enabled}
                onChange={(event) => setEnabled(event.currentTarget.checked)}
              />
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      <Group justify="space-between" mt="md">
        <Button
          variant="default"
          disabled={active === 0}
          onClick={() => setActive((step) => step - 1)}
        >
          {t('ai.wizard.back')}
        </Button>
        {active < 2 ? (
          <Button
            disabled={!canAdvance}
            onClick={() => setActive((step) => step + 1)}
            data-testid="ai-wizard-next"
          >
            {t('ai.wizard.next')}
          </Button>
        ) : (
          <Button
            loading={createProvider.isPending || updateProvider.isPending}
            disabled={!canAdvance}
            onClick={submit}
            data-testid="ai-wizard-finish"
          >
            {t('ai.wizard.finish')}
          </Button>
        )}
      </Group>

      {testResult ? (
        <Alert mt="md" data-testid="ai-wizard-result">
          {testResult}
        </Alert>
      ) : null}
    </Modal>
  );
}
