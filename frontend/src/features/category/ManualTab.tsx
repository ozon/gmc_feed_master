import { useState } from 'react';
import { Badge, Button, Group, Paper, Stack, Text, TextInput, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { usePluginData, useSavePluginData, type PluginScope } from '../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { useCategoryProductState } from './hooks';
import { TaxonomyCombobox } from './TaxonomyCombobox';

function assignmentsOf(payload: unknown): Record<string, string> {
  return (payload as { assignments?: Record<string, string> } | undefined)?.assignments ?? {};
}

export function ManualTab({
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
  const clientId = scope.clientId;
  const dataScope = clientId !== undefined ? { clientId } : {};
  const data = usePluginData(pluginId, dataScope, clientId !== undefined);
  const save = useSavePluginData(pluginId, dataScope);
  const [productIdInput, setProductIdInput] = useState('');
  const [productId, setProductId] = useState<string | undefined>(undefined);
  const [pendingTaxonomy, setPendingTaxonomy] = useState<string | null>(null);
  const product = useCategoryProductState(feedSourceId ?? 0, productId);

  if (clientId === undefined) {
    return <EmptyState message={t('manual.needsClient')} />;
  }
  if (data.isLoading) return <LoadingState />;
  if (data.isError) return <ErrorState onRetry={() => void data.refetch()} />;

  const assignments = assignmentsOf(data.data);
  const currentAssignment = productId ? assignments[productId] : undefined;

  function persist(next: Record<string, string>) {
    save.mutate(
      { assignments: next },
      {
        onSuccess: () => notifySuccess(t('manual.saved')),
        onError: (error) => notifyApiError(error, t('manual.saveFailed')),
      },
    );
  }

  return (
    <Stack gap="md">
      <Title order={4}>{t('tabs.manual')}</Title>
      <Group align="flex-end">
        <TextInput
          label={t('manual.productId')}
          value={productIdInput}
          onChange={(event) => setProductIdInput(event.currentTarget.value)}
          w={280}
        />
        <Button
          disabled={feedSourceId === undefined || !productIdInput}
          onClick={() => setProductId(productIdInput || undefined)}
        >
          {t('manual.lookup')}
        </Button>
        {feedSourceId === undefined && (
          <Text size="xs" c="dimmed">{t('manual.selectFeedSource')}</Text>
        )}
      </Group>
      {productId && product.isError && (
        <Text c="red" size="sm">{t('manual.notFound')}</Text>
      )}
      {productId && product.data && (
        <Paper withBorder p="md">
          <Stack gap="xs">
            <Text fw={600}>{product.data.title ?? product.data.product_id}</Text>
            <Group gap="xs">
              <Text size="sm" c="dimmed">{t('manual.provenanceLabel')}</Text>
              <Badge variant="light">
                {product.data.provenance
                  ? t(`manual.provenance.${product.data.provenance}`, {
                      rule: product.data.rule_id ?? '',
                    })
                  : t('manual.provenance.null')}
              </Badge>
            </Group>
            <Group gap="xs">
              <Text size="sm" c="dimmed">{t('manual.categoryLabel')}</Text>
              <Text size="sm">
                {product.data.google_product_category || t('manual.none')}
              </Text>
            </Group>
            {currentAssignment !== undefined && (
              <Group gap="xs">
                <Text size="sm" c="dimmed">{t('manual.assignmentLabel')}</Text>
                <Badge color="green" variant="light">{currentAssignment}</Badge>
                <Button
                  size="xs"
                  color="red"
                  variant="light"
                  loading={save.isPending}
                  onClick={() => {
                    const next = { ...assignments };
                    delete next[productId];
                    persist(next);
                  }}
                >
                  {t('manual.unassign')}
                </Button>
              </Group>
            )}
            <Group grow align="flex-start">
              <TaxonomyCombobox
                language={language}
                value={pendingTaxonomy}
                onChange={setPendingTaxonomy}
              />
              <Button
                mt={22}
                disabled={!pendingTaxonomy}
                loading={save.isPending}
                onClick={() =>
                  persist({ ...assignments, [productId]: pendingTaxonomy ?? '' })
                }
              >
                {t('manual.assign')}
              </Button>
            </Group>
          </Stack>
        </Paper>
      )}
      {!productId && <EmptyState message={t('manual.empty')} />}
    </Stack>
  );
}
