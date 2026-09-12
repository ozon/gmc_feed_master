import { useState } from 'react';
import {
  ActionIcon, Badge, Button, Checkbox, Group, NumberInput, Paper, Stack, Text, Title,
} from '@mantine/core';
import { IconPinnedOff } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { apiGetWithHeaders, apiPost } from '../../api/client';
import { queryKeys } from '../../api/queryKeys';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import type { PluginScope } from '../../api/hooks';

type EnrichmentData = {
  suggestions: Record<string, Record<string, string>>;
  pinned: Record<string, Record<string, string>>;
};

type Item = { product_id: string; fields: string[] };

function useEnrichmentData(pluginId: string, feedSourceId: number | undefined) {
  return useQuery({
    queryKey: queryKeys.pluginData(pluginId, { feedSourceId }),
    enabled: feedSourceId !== undefined,
    queryFn: async () => {
      const { data, headers } = await apiGetWithHeaders<EnrichmentData>(
        `/plugins/${pluginId}/data?feed_source_id=${feedSourceId}`,
      );
      const raw = headers.get('X-Plugin-Data-Version');
      const version = raw && raw !== '' ? Number.parseInt(raw, 10) : null;
      const empty: EnrichmentData = { suggestions: {}, pinned: {} };
      return {
        payload: (data && typeof data === 'object' ? data : empty) as EnrichmentData,
        version,
      };
    },
  });
}

export default function EnrichmentUI({
  pluginId,
  scope,
}: {
  pluginId: string;
  scope: PluginScope;
}) {
  const { t } = useTranslation('enrichment');
  const queryClient = useQueryClient();
  const feedSourceId = scope.feedSourceId;
  const dataQuery = useEnrichmentData(pluginId, feedSourceId);
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [limit, setLimit] = useState<number | ''>(20);

  const dataKey = queryKeys.pluginData(pluginId, { feedSourceId });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: dataKey });

  const mutate = <T,>(action: 'scan' | 'accept' | 'discard' | 'unpin', body: unknown) =>
    apiPost<T>(`/plugins/${pluginId}/${action}?feed_source_id=${feedSourceId}`, body);

  const scan = useMutation({
    mutationFn: () =>
      mutate<{ scanned: number; with_suggestions: number; failed: number }>(
        'scan', { feed_source_id: feedSourceId, limit: limit === '' ? 20 : limit },
      ),
    onSuccess: (result: { scanned: number; with_suggestions: number; failed: number }) => {
      void invalidate();
      notifySuccess(t('scanDone', {
        scanned: result.scanned,
        with_suggestions: result.with_suggestions,
        failed: result.failed,
      }));
    },
    onError: (error) => notifyApiError(error, t('scan')),
  });

  const acceptOrDiscard = useMutation({
    mutationFn: (vars: { action: 'accept' | 'discard'; items: Item[] }) =>
      mutate(vars.action, {
        feed_source_id: feedSourceId,
        expected_version:
          dataQuery.data?.version === null || dataQuery.data?.version === undefined
            ? 'null'
            : String(dataQuery.data.version),
        items: vars.items,
      }),
    onSuccess: () => {
      setSelected({});
      void invalidate();
    },
    onError: (error) => notifyApiError(error, t('acceptSelected')),
  });

  const unpin = useMutation({
    mutationFn: (item: Item) =>
      mutate('unpin', {
        feed_source_id: feedSourceId,
        expected_version:
          dataQuery.data?.version === null || dataQuery.data?.version === undefined
            ? 'null'
            : String(dataQuery.data.version),
        items: [item],
      }),
    onSuccess: () => void invalidate(),
    onError: (error) => notifyApiError(error, t('unpin')),
  });

  if (feedSourceId === undefined) {
    return (
      <Stack gap="md">
        <Title order={3}>{t('title')}</Title>
        <Badge variant="light" color="gray">feed_source</Badge>
      </Stack>
    );
  }

  const suggestions = dataQuery.data?.payload.suggestions ?? {};
  const pinned = dataQuery.data?.payload.pinned ?? {};
  const suggestionEntries = Object.entries(suggestions);
  const allItems: Item[] = suggestionEntries.map(([product_id, fields]) => ({
    product_id,
    fields: Object.keys(fields),
  }));

  const toggle = (productId: string, field: string, checked: boolean) => {
    setSelected((prev) => {
      const current = prev[productId] ?? [];
      const next = checked
        ? [...current, field]
        : current.filter((f) => f !== field);
      return { ...prev, [productId]: next };
    });
  };

  const selectedItems: Item[] = Object.entries(selected)
    .map(([product_id, fields]) => ({ product_id, fields }))
    .filter((item) => item.fields.length > 0);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={3}>{t('title')}</Title>
        <Group gap="xs">
          <NumberInput
            w={160}
            min={1}
            max={50}
            value={limit}
            onChange={(value) => setLimit(typeof value === 'number' ? value : '')}
            label={t('scanLimit')}
          />
          <Button loading={scan.isPending} onClick={() => scan.mutate()}>
            {t('scan')}
          </Button>
        </Group>
      </Group>

      <Paper withBorder p="md">
        <Title order={4}>{t('suggestions')}</Title>
        {suggestionEntries.length === 0 ? (
          <Text c="dimmed" mt="sm">{t('empty')}</Text>
        ) : (
          <Stack gap="xs" mt="sm">
            {suggestionEntries.map(([productId, fields]) => (
              <Group key={productId} justify="space-between" wrap="nowrap" w="100%">
                <Group gap="xs">
                  <Badge variant="light">{productId}</Badge>
                  {Object.entries(fields).map(([field, value]) => (
                    <Checkbox
                      key={field}
                      label={`${field}: ${value}`}
                      checked={(selected[productId] ?? []).includes(field)}
                      onChange={(event) => toggle(productId, field, event.currentTarget.checked)}
                    />
                  ))}
                </Group>
                <Group gap="xs">
                  {Object.keys(fields).map((field) => (
                    <Button
                      key={field}
                      size="xs"
                      variant="light"
                      color="red"
                      onClick={() =>
                        acceptOrDiscard.mutate({
                          action: 'discard',
                          items: [{ product_id: productId, fields: [field] }],
                        })
                      }
                    >
                      {t('discard')} {field}
                    </Button>
                  ))}
                </Group>
              </Group>
            ))}
            <Group gap="xs" mt="sm">
              <Button
                disabled={selectedItems.length === 0}
                loading={acceptOrDiscard.isPending}
                onClick={() => acceptOrDiscard.mutate({ action: 'accept', items: selectedItems })}
              >
                {t('acceptSelected')}
              </Button>
              <Button
                variant="light"
                disabled={allItems.length === 0}
                onClick={() => acceptOrDiscard.mutate({ action: 'accept', items: allItems })}
              >
                {t('acceptAll')}
              </Button>
            </Group>
          </Stack>
        )}
      </Paper>

      <Paper withBorder p="md">
        <Title order={4}>{t('pinned')}</Title>
        {Object.entries(pinned).length === 0 ? (
          <Text c="dimmed" mt="sm">{t('empty')}</Text>
        ) : (
          <Stack gap="xs" mt="sm">
            {Object.entries(pinned).map(([productId, fields]) => (
              <Group key={productId} justify="space-between" wrap="nowrap" w="100%">
                <Group gap="xs">
                  <Badge variant="light" color="green">{productId}</Badge>
                  {Object.entries(fields).map(([field, value]) => (
                    <Text key={field} size="sm">{field}: {value}</Text>
                  ))}
                </Group>
                <ActionIcon
                  variant="light"
                  color="red"
                  title={t('unpin')}
                  aria-label={t('unpin')}
                  onClick={() =>
                    unpin.mutate({ product_id: productId, fields: Object.keys(fields) })
                  }
                >
                  <IconPinnedOff size={16} />
                </ActionIcon>
              </Group>
            ))}
          </Stack>
        )}
      </Paper>
    </Stack>
  );
}
