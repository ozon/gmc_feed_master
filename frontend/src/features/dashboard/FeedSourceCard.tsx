import { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  Paper,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { IconSettings, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router';
import dayjs from 'dayjs';
import { useDeleteFeedSource } from '../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../app/notifications';
import type { FeedSourceSummary } from '../../api/types';

const RUN_DOT_COLORS: Record<string, string> = {
  success: 'var(--mantine-color-green-6)',
  error: 'var(--mantine-color-red-6)',
  running: 'var(--mantine-color-blue-6)',
};

const RUN_STATUSES = ['success', 'error', 'skipped', 'running', 'pending'] as const;
const EXPORT_STATUSES = ['completed', 'failed', 'rollback'] as const;

type RunStatus = (typeof RUN_STATUSES)[number];
type ExportStatus = (typeof EXPORT_STATUSES)[number];
type RunStatusKey = `runStatus.${RunStatus}`;
type ExportStatusKey = `exportStatus.${ExportStatus}`;

function runStatusKey(status: string | null): RunStatusKey {
  const known = RUN_STATUSES.includes(status as RunStatus);
  return `runStatus.${known ? (status as RunStatus) : 'pending'}`;
}

function exportStatusKey(status: string | null): ExportStatusKey {
  const known = EXPORT_STATUSES.includes(status as ExportStatus);
  return `exportStatus.${known ? (status as ExportStatus) : 'failed'}`;
}

export function FeedSourceCard({
  clientId,
  feed,
}: {
  clientId: number | string;
  feed: FeedSourceSummary;
}) {
  const { t, i18n } = useTranslation('dashboard');
  const { t: tCommon } = useTranslation('common');
  const navigate = useNavigate();
  const location = useLocation();
  const deleteFeedSource = useDeleteFeedSource();
  const [deleteOpened, setDeleteOpened] = useState(false);
  const [confirmText, setConfirmText] = useState('');

  const runColor =
    feed.last_run_status && feed.last_run_status in RUN_DOT_COLORS
      ? RUN_DOT_COLORS[feed.last_run_status]
      : 'var(--mantine-color-gray-6)';
  const numberFormat = new Intl.NumberFormat(i18n.language);

  function confirmDelete() {
    deleteFeedSource.mutate(feed.id, {
      onSuccess: () => {
        notifySuccess(t('saved'));
        setDeleteOpened(false);
        setConfirmText('');
        if (location.pathname.startsWith(`/clients/${clientId}/feeds/${feed.id}`)) {
          navigate('/');
        }
      },
      onError: (error) => notifyMutationError(error, t('deleteFailed')),
    });
  }

  return (
    <Paper withBorder p="md">
      <Group justify="space-between" wrap="nowrap">
        <Group gap="sm" wrap="nowrap" miw={0}>
          <Text fw={500} truncate="end">
            {feed.name}
          </Text>
          <Badge variant="light">{feed.source_format.toUpperCase()}</Badge>
        </Group>
        <Group gap="xs" wrap="nowrap">
          <ActionIcon
            variant="subtle"
            aria-label={t('openSettings')}
            onClick={() => navigate(`/clients/${clientId}/feeds/${feed.id}/setup`)}
          >
            <IconSettings size={16} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            color="red"
            aria-label={t('deleteFeed')}
            onClick={() => setDeleteOpened(true)}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Group>
      </Group>
      <Stack gap={4} mt="sm">
        <Group gap="xs" wrap="nowrap">
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              flex: '0 0 auto',
              background: runColor,
              ...(feed.last_run_status === 'running'
                ? { animation: 'gmc-run-pulse 1s ease-in-out infinite' }
                : {}),
            }}
          />
          <Text size="sm" c="dimmed">
            {feed.last_run_at
              ? `${dayjs(feed.last_run_at).locale(i18n.language).fromNow()} — ${t(runStatusKey(feed.last_run_status))}`
              : t('neverRun')}
          </Text>
        </Group>
        <Text size="sm" c="dimmed">
          {feed.last_export_at
            ? `${dayjs(feed.last_export_at).locale(i18n.language).fromNow()} — ${t(exportStatusKey(feed.last_export_status))}`
            : t('neverExported')}
        </Text>
        <Text size="sm" c="dimmed">
          {numberFormat.format(feed.item_count)}
        </Text>
      </Stack>
      <style>{`@keyframes gmc-run-pulse{from{opacity:1}to{opacity:.3}}`}</style>
      <Modal
        opened={deleteOpened}
        onClose={() => setDeleteOpened(false)}
        title={t('deleteFeed')}
        centered
      >
        <Stack gap="md">
          <Text size="sm">{t('deleteFeedCascade', { name: feed.name })}</Text>
          <TextInput
            label={t('typeToConfirm', { name: feed.name })}
            value={confirmText}
            onChange={(event) => setConfirmText(event.currentTarget.value)}
            withAsterisk
          />
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setDeleteOpened(false)}
              disabled={deleteFeedSource.isPending}
            >
              {tCommon('actions.cancel')}
            </Button>
            <Button
              color="red"
              disabled={confirmText !== feed.name}
              loading={deleteFeedSource.isPending}
              onClick={confirmDelete}
            >
              {t('delete')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
}
