import { useEffect, useState } from 'react';
import { Badge, Button, Group, List, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useCategoryMatches } from './hooks';
import { ErrorState, LoadingState } from '../../components/StateViews';
import type { CategoryMatch } from './types';

const PAGE_SIZE = 50;

export function MatchesModal({
  feedSourceId,
  ruleId,
  opened,
  onClose,
}: {
  feedSourceId: number | undefined;
  ruleId: string;
  opened: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation('category');
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<CategoryMatch[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const query = useCategoryMatches(feedSourceId ?? 0, ruleId, PAGE_SIZE, offset);

  useEffect(() => {
    setOffset(0);
    setItems([]);
    setTotal(null);
  }, [ruleId]);

  useEffect(() => {
    if (!query.data) return;
    setTotal(query.data.total);
    setItems((current) => {
      if (offset === 0) return query.data!.items;
      const seen = new Set(current.map((item) => item.product_id));
      return [...current, ...query.data!.items.filter((item) => !seen.has(item.product_id))];
    });
  }, [query.data, offset]);

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('matches.modalTitle', { id: ruleId })}
      size="lg"
    >
      <Stack gap="sm">
        <Text size="xs" c="dimmed">{t('matches.stale')}</Text>
        {query.isLoading && <LoadingState />}
        {query.isError && <ErrorState onRetry={() => void query.refetch()} />}
        {total === 0 && !query.isLoading && <Text c="dimmed">{t('matches.empty')}</Text>}
        {items.length > 0 && (
          <List>
            {items.map((item) => (
              <List.Item key={item.product_id}>
                <Group gap="xs">
                  <Badge variant="light">{item.product_id}</Badge>
                  <Text size="sm">{item.title ?? ''}</Text>
                </Group>
              </List.Item>
            ))}
          </List>
        )}
        {total !== null && items.length < total && !query.isError && (
          <Button
            variant="subtle"
            loading={query.isFetching}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            {t('matches.loadMore')}
          </Button>
        )}
      </Stack>
    </Modal>
  );
}
