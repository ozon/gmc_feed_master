import { useMemo, useState } from 'react';
import {
  Accordion, Alert, Badge, Button, Group, NumberInput, PasswordInput,
  Select, Stack, Stepper, Text, TextInput, Anchor,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import {
  useProviderPresets, useModelCatalog, type ProviderPreset, type ModelCatalogEntry,
} from '../../../api/modelCatalog';

export type ProviderWizardSubmitPayload = {
  name: string;
  provider_type: 'litellm';
  base_url: string;
  api_key: string;
  model: string;
  tier: 'bulk' | 'precision';
  max_concurrency: number;
  timeout_s: number;
  input_price_per_mtok: number | null;
  output_price_per_mtok: number | null;
  azure_deployment_name?: string;
  azure_api_version?: string;
};

type Props = {
  onSubmit: (payload: ProviderWizardSubmitPayload) => void;
  onTestConnection?: (payload: ProviderWizardSubmitPayload) => Promise<{ status: 'ok' | 'error'; error_code?: string; latency_ms?: number }>;
  submitting?: boolean;
};

const DEFAULT_TIER: ProviderWizardSubmitPayload['tier'] = 'bulk';
const DEFAULT_MAX_CONCURRENCY = 4;
const DEFAULT_TIMEOUT_S = 30;

/**
 * 3-step "Anbieter auswaehlen -> API-Key hinterlegen -> Modell auswaehlen"
 * wizard for creating an AI provider. Advanced options (tier, concurrency,
 * timeout, pricing overrides) are collapsed by default.
 *
 * See itsaplan GFM-12 for the full spec. Not yet wired into ProvidersPage.tsx
 * (see docs/ai-provider-wizard-design.md for the remaining integration steps).
 */
export function ProviderWizard({ onSubmit, onTestConnection, submitting }: Props) {
  const { t } = useTranslation();
  const { data: presets = [], isLoading: presetsLoading } = useProviderPresets();

  const [step, setStep] = useState(0);
  const [preset, setPreset] = useState<ProviderPreset | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [azureDeploymentName, setAzureDeploymentName] = useState('');
  const [azureApiVersion, setAzureApiVersion] = useState('');
  const [model, setModel] = useState('');
  const [customModel, setCustomModel] = useState('');
  const [name, setName] = useState('');
  const [tier, setTier] = useState<ProviderWizardSubmitPayload['tier']>(DEFAULT_TIER);
  const [maxConcurrency, setMaxConcurrency] = useState(DEFAULT_MAX_CONCURRENCY);
  const [timeoutS, setTimeoutS] = useState(DEFAULT_TIMEOUT_S);
  const [inputPrice, setInputPrice] = useState<number | ''>('');
  const [outputPrice, setOutputPrice] = useState<number | ''>('');
  const [testResult, setTestResult] = useState<{ status: 'ok' | 'error'; error_code?: string } | null>(null);

  const { data: catalog = [], isLoading: catalogLoading } = useModelCatalog(preset?.vendor_key);

  const selectedModelEntry = useMemo(
    () => catalog.find((m) => m.model_id === model),
    [catalog, model],
  );

  function handleSelectPreset(vendorKey: string | null) {
    const found = presets.find((p) => p.vendor_key === vendorKey) ?? null;
    setPreset(found);
    setBaseUrl(found?.default_base_url ?? '');
    setModel('');
    setTestResult(null);
    if (found) {
      const recommended = catalog.find((m) => m.is_recommended);
      setName(`${found.label}${recommended ? ` (${recommended.display_name})` : ''}`);
    }
  }

  function buildPayload(): ProviderWizardSubmitPayload {
    const effectiveModel = preset?.is_custom ? customModel : model;
    return {
      name: name || effectiveModel,
      provider_type: 'litellm',
      base_url: baseUrl,
      api_key: apiKey,
      model: preset?.is_custom
        ? effectiveModel
        : (selectedModelEntry?.model_id ?? effectiveModel),
      tier,
      max_concurrency: maxConcurrency,
      timeout_s: timeoutS,
      input_price_per_mtok: inputPrice === '' ? (selectedModelEntry?.input_price_per_mtok ?? null) : inputPrice,
      output_price_per_mtok: outputPrice === '' ? (selectedModelEntry?.output_price_per_mtok ?? null) : outputPrice,
      ...(preset?.vendor_key === 'azure'
        ? { azure_deployment_name: azureDeploymentName, azure_api_version: azureApiVersion }
        : {}),
    };
  }

  async function handleTest() {
    if (!onTestConnection) return;
    const result = await onTestConnection(buildPayload());
    setTestResult(result);
  }

  const step2Valid = apiKey.length > 0 && (!preset?.requires_base_url || baseUrl.length > 0)
    && (!preset?.requires_api_version || azureApiVersion.length > 0);
  const step3Valid = preset?.is_custom ? customModel.length > 0 : model.length > 0;

  return (
    <Stack>
      <Stepper active={step} onStepClick={setStep} allowNextStepsSelect={false}>
        <Stepper.Step label={t('ai.wizard.stepProvider', 'Anbieter')} description={t('ai.wizard.stepProviderDesc', 'Auswaehlen')}>
          <Stack mt="md">
            <Select
              label={t('ai.wizard.providerLabel', 'AI-Anbieter')}
              placeholder={t('ai.wizard.providerPlaceholder', 'Anbieter waehlen...')}
              data={presets.map((p) => ({ value: p.vendor_key, label: p.label }))}
              value={preset?.vendor_key ?? null}
              onChange={handleSelectPreset}
              disabled={presetsLoading}
              searchable
            />
            {preset && (
              <Stack gap={4}>
                <Text size="sm" c="dimmed">{preset.description}</Text>
                {preset.api_key_docs_url && (
                  <Anchor size="sm" href={preset.api_key_docs_url} target="_blank" rel="noreferrer">
                    {t('ai.wizard.getApiKey', 'API-Key erstellen')}
                  </Anchor>
                )}
              </Stack>
            )}
            <Group justify="flex-end">
              <Button disabled={!preset} onClick={() => setStep(1)}>
                {t('common.next', 'Weiter')}
              </Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label={t('ai.wizard.stepKey', 'API-Key')} description={t('ai.wizard.stepKeyDesc', 'Hinterlegen')}>
          <Stack mt="md">
            <PasswordInput
              label={t('ai.wizard.apiKeyLabel', 'API-Key')}
              value={apiKey}
              onChange={(e) => setApiKey(e.currentTarget.value)}
              required
            />
            {preset?.requires_base_url && (
              <TextInput
                label={t('ai.wizard.baseUrlLabel', 'Base URL')}
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.currentTarget.value)}
                placeholder={preset.vendor_key === 'azure' ? 'https://<resource>.openai.azure.com' : 'https://...'}
                required
              />
            )}
            {preset?.requires_api_version && (
              <TextInput
                label={t('ai.wizard.apiVersionLabel', 'API Version')}
                value={azureApiVersion}
                onChange={(e) => setAzureApiVersion(e.currentTarget.value)}
                placeholder="2024-10-21"
                required
              />
            )}
            {onTestConnection && (
              <Group>
                <Button variant="light" onClick={handleTest} disabled={!step2Valid}>
                  {t('ai.wizard.testConnection', 'Verbindung testen')}
                </Button>
                {testResult && (
                  <Badge color={testResult.status === 'ok' ? 'green' : 'red'}>
                    {testResult.status === 'ok' ? t('ai.wizard.testOk', 'OK') : testResult.error_code}
                  </Badge>
                )}
              </Group>
            )}
            <Group justify="space-between">
              <Button variant="subtle" onClick={() => setStep(0)}>{t('common.back', 'Zurueck')}</Button>
              <Button disabled={!step2Valid} onClick={() => setStep(2)}>{t('common.next', 'Weiter')}</Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label={t('ai.wizard.stepModel', 'Modell')} description={t('ai.wizard.stepModelDesc', 'Auswaehlen')}>
          <Stack mt="md">
            {preset?.is_custom ? (
              <TextInput
                label={t('ai.wizard.customModelLabel', 'Model-ID')}
                value={customModel}
                onChange={(e) => setCustomModel(e.currentTarget.value)}
                placeholder="llama-3.1-70b-instruct"
                required
              />
            ) : (
              <Select
                label={t('ai.wizard.modelLabel', 'Modell')}
                placeholder={t('ai.wizard.modelPlaceholder', 'Modell waehlen...')}
                data={catalog.map((m: ModelCatalogEntry) => ({
                  value: m.model_id,
                  label: `${m.display_name}${m.is_recommended ? ' \u2b50' : ''}`,
                }))}
                value={model}
                onChange={(v) => setModel(v ?? '')}
                disabled={catalogLoading}
                searchable
                required
              />
            )}
            {selectedModelEntry && (
              <Group gap="xs">
                {selectedModelEntry.context_window && (
                  <Badge variant="light">{selectedModelEntry.context_window.toLocaleString()} tok context</Badge>
                )}
                {selectedModelEntry.supports_vision && <Badge variant="light" color="grape">Vision</Badge>}
                {selectedModelEntry.supports_function_calling && <Badge variant="light" color="blue">Function calling</Badge>}
              </Group>
            )}
            <TextInput
              label={t('ai.wizard.nameLabel', 'Name')}
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              required
            />

            <Accordion variant="contained">
              <Accordion.Item value="advanced">
                <Accordion.Control>{t('ai.wizard.advancedOptions', 'Erweiterte Optionen')}</Accordion.Control>
                <Accordion.Panel>
                  <Stack>
                    <Select
                      label={t('ai.tier', 'Tier')}
                      data={[
                        { value: 'bulk', label: t('ai.tierBulk', 'Bulk') },
                        { value: 'precision', label: t('ai.tierPrecision', 'Precision') },
                      ]}
                      value={tier}
                      onChange={(v) => setTier((v as ProviderWizardSubmitPayload['tier']) ?? DEFAULT_TIER)}
                    />
                    <NumberInput
                      label={t('ai.maxConcurrency', 'Max. Concurrency')}
                      value={maxConcurrency}
                      onChange={(v) => setMaxConcurrency(Number(v) || DEFAULT_MAX_CONCURRENCY)}
                      min={1}
                    />
                    <NumberInput
                      label={t('ai.timeoutS', 'Timeout (s)')}
                      value={timeoutS}
                      onChange={(v) => setTimeoutS(Number(v) || DEFAULT_TIMEOUT_S)}
                      min={1}
                    />
                    <NumberInput
                      label={t('ai.inputPrice', 'Input-Preis / MTok')}
                      value={inputPrice}
                      onChange={(v) => setInputPrice(v === '' ? '' : Number(v))}
                      placeholder={selectedModelEntry?.input_price_per_mtok?.toString()}
                      decimalScale={4}
                    />
                    <NumberInput
                      label={t('ai.outputPrice', 'Output-Preis / MTok')}
                      value={outputPrice}
                      onChange={(v) => setOutputPrice(v === '' ? '' : Number(v))}
                      placeholder={selectedModelEntry?.output_price_per_mtok?.toString()}
                      decimalScale={4}
                    />
                    {preset?.vendor_key === 'azure' && (
                      <TextInput
                        label={t('ai.azureDeploymentName', 'Azure Deployment Name')}
                        value={azureDeploymentName}
                        onChange={(e) => setAzureDeploymentName(e.currentTarget.value)}
                      />
                    )}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            </Accordion>

            {!catalogLoading && !preset?.is_custom && catalog.length === 0 && (
              <Alert color="yellow">
                {t('ai.wizard.emptyCatalog', 'Model-Katalog fuer diesen Anbieter ist leer. Bitte Katalog aktualisieren oder "OpenAI-kompatibel (custom)" verwenden.')}
              </Alert>
            )}

            <Group justify="space-between">
              <Button variant="subtle" onClick={() => setStep(1)}>{t('common.back', 'Zurueck')}</Button>
              <Button
                disabled={!step3Valid || submitting}
                loading={submitting}
                onClick={() => onSubmit(buildPayload())}
              >
                {t('ai.wizard.createProvider', 'Provider anlegen')}
              </Button>
            </Group>
          </Stack>
        </Stepper.Step>
      </Stepper>
    </Stack>
  );
}
