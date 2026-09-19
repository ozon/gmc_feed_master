import { Badge, Button, Group, List, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useCategoryMatchesInfinite } from './hooks';
import { ErrorState, LoadingState } from '../../components/StateViews';

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
  const query = useCategoryMatchesInfinite(feedSourceId ?? 0, ruleId, PAGE_SIZE);
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const total = query.data?.pages.at(-1)?.total ?? null;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('matches.modalTitle', { id: ruleId })}
      size="lg"
    >
      <Stack gap="sm">
        <Text size="xs" c="dimmed">
          {t('matches.stale')}
        </Text>
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
        {query.hasNextPage && !query.isError && (
          <Button
            variant="subtle"
            loading={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
          >
            {t('matches.loadMore')}
          </Button>
        )}
      </Stack>
    </Modal>
  );
}
