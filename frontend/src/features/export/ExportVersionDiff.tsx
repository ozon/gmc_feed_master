import { Accordion, Alert, Code, Group, Stack, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import type { DiffOut } from '../../api/types';

type Props = {
  diff: DiffOut | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
};

export function ExportVersionDiff({ diff, isPending, isError, onRetry }: Props) {
  const { t } = useTranslation('export');
  if (isPending) return <LoadingState />;
  if (isError) return <ErrorState onRetry={onRetry} />;
  if (!diff) return <EmptyState message={t('selectVersions')} />;
  const hasChanges = diff.added.length > 0 || diff.removed.length > 0 || diff.changed.length > 0;
  if (!hasChanges) return <EmptyState message={t('noChanges')} />;
  return (
    <Stack gap="md" data-testid="export-version-diff">
      <Text fw={600}>
        {t('diffTitle', { version: diff.version, against: diff.against })}
      </Text>
      {diff.added.length > 0 ? (
        <Alert color="green" title={t('added')}>
          <Code block>{diff.added.join(', ')}</Code>
        </Alert>
      ) : null}
      {diff.removed.length > 0 ? (
        <Alert color="red" title={t('removed')}>
          <Code block>{diff.removed.join(', ')}</Code>
        </Alert>
      ) : null}
      {diff.changed.length > 0 ? (
        <Accordion variant="separated" multiple>
          {diff.changed.map((product) => (
            <Accordion.Item key={product.product_id} value={product.product_id}>
              <Accordion.Control>
                <Group justify="space-between">
                  <Text fw={500}>{product.product_id}</Text>
                  <Text size="sm" c="dimmed">
                    {t('fieldsChanged', { count: product.fields.length })}
                  </Text>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Table withTableBorder>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('columns.field')}</Table.Th>
                      <Table.Th>{t('columns.old')}</Table.Th>
                      <Table.Th>{t('columns.new')}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {product.fields.map((field, idx) => (
                      <Table.Tr key={`${field.field}-${idx}`}>
                        <Table.Td>{field.field}</Table.Td>
                        <Table.Td>
                          <Code>{JSON.stringify(field.old)}</Code>
                        </Table.Td>
                        <Table.Td>
                          <Code>{JSON.stringify(field.new)}</Code>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      ) : null}
    </Stack>
  );
}