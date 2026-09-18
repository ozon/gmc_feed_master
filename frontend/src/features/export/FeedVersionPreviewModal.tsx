import { Alert, Button, Group, Modal, ScrollArea } from '@mantine/core';
import { IconDownload } from '@tabler/icons-react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useExportVersionContent } from '../../api/hooks';
import { ApiError } from '../../api/client';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';
import { XmlHighlight, prettifyXml, sliceXmlLines } from '../../components/XmlHighlight';
import { downloadVersionXml } from './download';

const MAX_PREVIEW_LINES = 5000;

type Props = {
  feedSourceId: number | string;
  version: number | null;
  opened: boolean;
  onClose: () => void;
};

export function FeedVersionPreviewModal({ feedSourceId, version, opened, onClose }: Props) {
  const { t } = useTranslation('export');
  const content = useExportVersionContent(feedSourceId, version ?? undefined, opened);

  const formatted = useMemo(() => prettifyXml(content.data ?? ''), [content.data]);
  const sliced = useMemo(() => sliceXmlLines(formatted, MAX_PREVIEW_LINES), [formatted]);

  async function handleDownload() {
    if (version === null) return;
    try {
      await downloadVersionXml(feedSourceId, version, content.data);
      notifySuccess(t('download.version'));
    } catch (error) {
      notifyApiError(error, t('download.failed'));
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="xl"
      title={version !== null ? t('preview.title', { version }) : ''}
    >
      {content.isPending ? <LoadingState /> : null}
      {content.isError ? (
        content.error instanceof ApiError && content.error.status === 404 ? (
          <EmptyState message={t('preview.notRetained')} />
        ) : (
          <ErrorState onRetry={() => void content.refetch()} />
        )
      ) : null}
      {content.data ? (
        <>
          {sliced.truncated ? (
            <Alert color="yellow" mb="sm">
              {t('preview.truncated', { shown: MAX_PREVIEW_LINES, total: sliced.totalLines })}
            </Alert>
          ) : null}
          <ScrollArea.Autosize mah="70vh">
            <XmlHighlight xml={sliced.text} />
          </ScrollArea.Autosize>
          <Group justify="flex-end" mt="md">
            <Button leftSection={<IconDownload size={16} />} onClick={() => void handleDownload()}>
              {t('download.version')}
            </Button>
          </Group>
        </>
      ) : null}
    </Modal>
  );
}
