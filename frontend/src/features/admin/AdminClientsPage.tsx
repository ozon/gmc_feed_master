import { useState } from 'react';
import { Group, Stack, Table, Title } from '@mantine/core';
import { ActionIcon, Badge, Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useClients } from '../../api/hooks';
import { ClientModal } from '../dashboard/ClientModal';
import { DeleteClientModal } from '../dashboard/DeleteClientModal';
import { LoadingState, ErrorState } from '../../components/StateViews';
import type { ClientRow, ClientSummary } from '../../api/types';

function toSummary(row: ClientRow): ClientSummary {
  // ClientModal/DeleteClientModal consume id/name/status; feed_sources is unused there.
  return { id: row.id, name: row.name, status: row.status, feed_sources: [] };
}

export function AdminClientsPage() {
  const { t } = useTranslation('admin');
  const clientsQuery = useClients();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ClientSummary | null>(null);
  const [deleting, setDeleting] = useState<ClientSummary | null>(null);

  if (clientsQuery.isPending) return <LoadingState />;
  if (clientsQuery.isError) return <ErrorState onRetry={() => void clientsQuery.refetch()} />;

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('clients.title')}</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
          {t('clients.add')}
        </Button>
      </Group>
      <Table striped data-testid="admin-clients-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('clients.columns.name')}</Table.Th>
            <Table.Th>{t('clients.columns.status')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {clientsQuery.data.map((row) => (
            <Table.Tr key={row.id} data-testid={`client-row-${row.name}`}>
              <Table.Td>{row.name}</Table.Td>
              <Table.Td>
                <Badge variant="light" color={row.status === 'active' ? 'green' : 'gray'}>
                  {row.status}
                </Badge>
              </Table.Td>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  <Button variant="subtle" size="xs" onClick={() => setEditing(toSummary(row))}>
                    {t('clients.edit')}
                  </Button>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    aria-label={t('clients.delete')}
                    onClick={() => setDeleting(toSummary(row))}
                  >
                    <IconTrash size={16} />
                  </ActionIcon>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <ClientModal
        opened={creating || editing !== null}
        client={editing}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
      />
      <DeleteClientModal
        opened={deleting !== null}
        client={deleting}
        onClose={() => setDeleting(null)}
      />
    </Stack>
  );
}
