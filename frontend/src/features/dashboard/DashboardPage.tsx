import { useState } from 'react';
import {
  Accordion,
  Badge,
  Button,
  Group,
  Modal,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { IconPencil, IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { useCreateFeedSource, useDashboardSummary } from '../../api/hooks';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { notifyMutationError, notifySuccess } from '../../app/notifications';
import type { ClientSummary } from '../../api/types';
import { ClientModal } from './ClientModal';
import { DeleteClientModal } from './DeleteClientModal';
import { FeedSourceCard } from './FeedSourceCard';

const FEED_FORMATS = ['xml', 'tsv', 'csv', 'wide_tsv'] as const;
const CLIENT_STATUSES = ['active', 'paused'] as const;

type ClientStatus = (typeof CLIENT_STATUSES)[number];
type ClientStatusKey = `clientStatus.${ClientStatus}`;

function clientStatusKey(status: string): ClientStatusKey {
  const known = CLIENT_STATUSES.includes(status as ClientStatus);
  return `clientStatus.${known ? (status as ClientStatus) : 'active'}`;
}

function StatCard({ label, value }: { label: string; value: number }) {
  const { i18n } = useTranslation('dashboard');
  return (
    <Paper withBorder p="md">
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text ff="monospace" size="xl" style={{ fontVariantNumeric: 'tabular-nums' }}>
        {new Intl.NumberFormat(i18n.language).format(value)}
      </Text>
    </Paper>
  );
}

function ClientSection({ client }: { client: ClientSummary }) {
  const { t } = useTranslation('dashboard');
  const navigate = useNavigate();
  const createFeedSource = useCreateFeedSource();
  const [addFeedOpened, setAddFeedOpened] = useState(false);
  const [feedName, setFeedName] = useState('');
  const [feedFormat, setFeedFormat] = useState<string>('xml');

  function createFeed() {
    createFeedSource.mutate(
      {
        clientId: client.id,
        name: feedName,
        source_format: feedFormat,
      },
      {
        onSuccess: (feed) => {
          notifySuccess(t('saved'));
          setAddFeedOpened(false);
          setFeedName('');
          navigate(`/clients/${client.id}/feeds/${feed.id}/setup`);
        },
        onError: (error) => notifyMutationError(error, t('saveFailed')),
      },
    );
  }

  return (
    <Accordion.Item value={String(client.id)}>
      <Accordion.Control>
        <Group gap="sm" wrap="nowrap">
          <Text fw={500}>{client.name}</Text>
          <Badge
            size="sm"
            variant="light"
            color={client.status === 'active' ? 'green' : 'gray'}
          >
            {t(clientStatusKey(client.status))}
          </Badge>
        </Group>
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap="sm">
          {client.feed_sources.map((feed) => (
            <FeedSourceCard key={feed.id} clientId={client.id} feed={feed} />
          ))}
          <Group gap="xs">
            <Button
              size="xs"
              variant="light"
              leftSection={<IconPlus size={14} />}
              onClick={() => setAddFeedOpened(true)}
            >
              {t('addFeed')}
            </Button>
            <EditClientButton client={client} />
            <DeleteClientButton client={client} />
          </Group>
          <Modal
            opened={addFeedOpened}
            onClose={() => setAddFeedOpened(false)}
            title={t('addFeedModal.title')}
            centered
          >
            <Stack gap="md">
              <TextInput
                label={t('addFeedModal.name')}
                value={feedName}
                onChange={(event) => setFeedName(event.currentTarget.value)}
                withAsterisk
              />
              <Select
                label={t('addFeedModal.format')}
                data={FEED_FORMATS.map((format) => ({
                  value: format,
                  label: format.toUpperCase(),
                }))}
                value={feedFormat}
                onChange={(value) => setFeedFormat(value ?? 'xml')}
                allowDeselect={false}
              />
              <Group justify="flex-end">
                <Button onClick={createFeed} loading={createFeedSource.isPending}>
                  {t('addFeedModal.create')}
                </Button>
              </Group>
            </Stack>
          </Modal>
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
}

function EditClientButton({ client }: { client: ClientSummary }) {
  const { t } = useTranslation('dashboard');
  const [opened, setOpened] = useState(false);
  return (
    <>
      <Button size="xs" variant="light" leftSection={<IconPencil size={14} />} onClick={() => setOpened(true)}>
        {t('edit')}
      </Button>
      <ClientModal opened={opened} client={client} onClose={() => setOpened(false)} />
    </>
  );
}

function DeleteClientButton({ client }: { client: ClientSummary }) {
  const { t } = useTranslation('dashboard');
  const [opened, setOpened] = useState(false);
  return (
    <>
      <Button size="xs" variant="light" color="red" leftSection={<IconTrash size={14} />} onClick={() => setOpened(true)}>
        {t('delete')}
      </Button>
      <DeleteClientModal opened={opened} client={client} onClose={() => setOpened(false)} />
    </>
  );
}

export function DashboardPage() {
  const { t } = useTranslation('dashboard');
  const summaryQuery = useDashboardSummary();
  const [createOpened, setCreateOpened] = useState(false);

  if (summaryQuery.isPending) return <LoadingState />;
  if (summaryQuery.isError) {
    return <ErrorState onRetry={() => void summaryQuery.refetch()} />;
  }

  const summary = summaryQuery.data;
  const hasClients = summary.clients.length > 0;

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('title')}</Title>
        <Button onClick={() => setCreateOpened(true)}>{t('addClient')}</Button>
      </Group>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
        <StatCard label={t('stats.clients')} value={summary.counts.clients} />
        <StatCard label={t('stats.feeds')} value={summary.counts.feed_sources} />
        <StatCard label={t('stats.products')} value={summary.counts.active_products} />
        <StatCard label={t('stats.failedExports')} value={summary.counts.failed_last_exports} />
      </SimpleGrid>
      {hasClients ? (
        <Accordion
          multiple={false}
          chevronPosition="right"
          defaultValue={String(summary.clients[0].id)}
        >
          {summary.clients.map((client) => (
            <ClientSection key={client.id} client={client} />
          ))}
        </Accordion>
      ) : (
        <EmptyState message={t('empty')} />
      )}
      <ClientModal opened={createOpened} client={null} onClose={() => setCreateOpened(false)} />
    </Stack>
  );
}
