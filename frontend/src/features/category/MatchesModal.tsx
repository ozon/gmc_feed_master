import { useState } from 'react';
import { Badge, Button, Group, List, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useCategoryMatches } from './hooks';
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
  const [offset, setOffset] = useState(0);
  const query = useCategoryMatches(feedSourceId ?? 0, ruleId, PAGE_SIZE, offset);

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
        {query.data && query.data.items.length === 0 && (
          <Text c="dimmed">{t('matches.empty')}</Text>
        )}
        {query.data && query.data.items.length > 0 && (
          <List>
            {query.data.items.map((item) => (
              <List.Item key={item.product_id}>
                <Group gap="xs">
                  <Badge variant="light">{item.product_id}</Badge>
                  <Text size="sm">{item.title ?? ''}</Text>
                </Group>
              </List.Item>
            ))}
          </List>
        )}
        {query.data && offset + PAGE_SIZE < query.data.total && (
          <Button variant="subtle" onClick={() => setOffset(offset + PAGE_SIZE)}>
            {t('matches.loadMore')}
          </Button>
        )}
      </Stack>
    </Modal>
  );
}
