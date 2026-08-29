import { Drawer, Table, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import { useProductDetail } from '../../api/hooks';
import { LoadingState, ErrorState } from '../../components/StateViews';

type ProductDrawerProps = {
  feedSourceId: number | string;
  productId: string | null;
  onClose: () => void;
};

export function ProductDrawer({ feedSourceId, productId, onClose }: ProductDrawerProps) {
  const { t } = useTranslation('products');
  const detail = useProductDetail(feedSourceId, productId);

  return (
    <Drawer opened={productId !== null} onClose={onClose} title={t('drawerTitle')} size="lg">
      {productId === null && null}
      {detail.isPending && <LoadingState />}
      {detail.isError && <ErrorState />}
      {detail.data && (
        <>
          <Table>
            <Table.Tbody>
              <Table.Tr>
                <Table.Td fw={500}>{t('drawerStatus')}</Table.Td>
                <Table.Td>{detail.data.status}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td fw={500}>{t('drawerContentHash')}</Table.Td>
                <Table.Td>
                  <Text ff="monospace" size="sm" truncate>
                    {detail.data.content_hash}
                  </Text>
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td fw={500}>{t('drawerConfigHash')}</Table.Td>
                <Table.Td>
                  <Text ff="monospace" size="sm" truncate>
                    {detail.data.config_hash}
                  </Text>
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td fw={500}>{t('drawerLastSeenAt')}</Table.Td>
                <Table.Td>{dayjs(detail.data.last_seen_at).format('L LTS')}</Table.Td>
              </Table.Tr>
              {detail.data.removed_at && (
                <Table.Tr>
                  <Table.Td fw={500}>{t('drawerRemovedAt')}</Table.Td>
                  <Table.Td>{dayjs(detail.data.removed_at).format('L LTS')}</Table.Td>
                </Table.Tr>
              )}
            </Table.Tbody>
          </Table>
          <Title order={5} mt="md" mb="xs">
            raw_data
          </Title>
          <pre
            style={{
              background: 'var(--mantine-color-gray-0)',
              padding: 'var(--mantine-spacing-sm)',
              borderRadius: 'var(--mantine-radius-sm)',
              overflow: 'auto',
              maxHeight: 500,
              fontSize: 'var(--mantine-font-size-xs)',
            }}
          >
            {JSON.stringify(detail.data.raw_data, null, 2)}
          </pre>
        </>
      )}
    </Drawer>
  );
}
