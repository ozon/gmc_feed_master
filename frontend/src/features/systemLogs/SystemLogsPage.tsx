import { Fragment, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Code,
  Group,
  Select,
  Stack,
  Table,
  TextInput,
  Title,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useEventLogs } from '../../api/hooks';
import type { EventLogEntry } from '../../api/types';
import { ErrorState, LoadingState } from '../../components/StateViews';

const LEVELS = ['debug', 'info', 'warning', 'error', 'critical'];
const CATEGORIES = ['audit', 'server_error', 'client_error'];
const SOURCES = ['backend', 'frontend'];

export function SystemLogsPage() {
  const { t } = useTranslation('systemLogs');
  const [category, setCategory] = useState<string | null>(null);
  const [level, setLevel] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [actor, setActor] = useState('');
  const [requestId, setRequestId] = useState('');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<number | null>(null);

  const filters = useMemo(
    () => ({
      category: category ?? undefined,
      level: level ?? undefined,
      source: source ?? undefined,
      actor: actor || undefined,
      request_id: requestId || undefined,
      q: search || undefined,
      limit: 50,
    }),
    [category, level, source, actor, requestId, search],
  );

  const query = useEventLogs(filters);

  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState onRetry={() => void query.refetch()} />;

  const items = query.data.pages.flatMap((page) => page.items);

  const renderRow = (entry: EventLogEntry) => (
    <Fragment key={entry.id}>
      <Table.Tr onClick={() => setExpanded(expanded === entry.id ? null : entry.id)}>
        <Table.Td>{new Date(entry.created_at).toLocaleString()}</Table.Td>
        <Table.Td>
          <Badge color={entry.level === 'error' ? 'red' : 'gray'}>{entry.level}</Badge>
        </Table.Td>
        <Table.Td>{entry.category}</Table.Td>
        <Table.Td>{entry.source}</Table.Td>
        <Table.Td>{entry.actor ?? ''}</Table.Td>
        <Table.Td>{entry.message}</Table.Td>
      </Table.Tr>
      {expanded === entry.id ? (
        <Table.Tr>
          <Table.Td colSpan={6}>
            <Code block>{JSON.stringify(entry, null, 2)}</Code>
          </Table.Td>
        </Table.Tr>
      ) : null}
    </Fragment>
  );

  return (
    <Stack pt="md">
      <Title order={3}>{t('title')}</Title>
      <Group align="flex-end">
        <Select
          label={t('filters.category')}
          data={CATEGORIES}
          value={category}
          onChange={setCategory}
          clearable
        />
        <Select
          label={t('filters.level')}
          data={LEVELS}
          value={level}
          onChange={setLevel}
          clearable
        />
        <Select
          label={t('filters.source')}
          data={SOURCES}
          value={source}
          onChange={setSource}
          clearable
        />
        <TextInput
          label={t('filters.actor')}
          value={actor}
          onChange={(event) => setActor(event.currentTarget.value)}
        />
        <TextInput
          label={t('filters.requestId')}
          value={requestId}
          onChange={(event) => setRequestId(event.currentTarget.value)}
        />
        <TextInput
          label={t('filters.search')}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
        />
      </Group>
      <Table highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('columns.time')}</Table.Th>
            <Table.Th>{t('columns.level')}</Table.Th>
            <Table.Th>{t('columns.category')}</Table.Th>
            <Table.Th>{t('columns.source')}</Table.Th>
            <Table.Th>{t('columns.actor')}</Table.Th>
            <Table.Th>{t('columns.message')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>{items.map(renderRow)}</Table.Tbody>
      </Table>
      {query.hasNextPage ? (
        <Button
          variant="light"
          loading={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {t('loadMore')}
        </Button>
      ) : null}
    </Stack>
  );
}
