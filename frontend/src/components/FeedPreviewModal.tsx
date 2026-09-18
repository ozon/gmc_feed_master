import { Alert, Button, Group, Modal, ScrollArea } from '@mantine/core';
import { IconDownload } from '@tabler/icons-react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { EmptyState, ErrorState, LoadingState } from './StateViews';
import { XmlHighlight, prettifyXml, sliceXmlLines } from './XmlHighlight';

const MAX_PREVIEW_LINES = 5000;

type Props = {
  opened: boolean;
  onClose: () => void;
  title: string;
  isPending: boolean;
  isError: boolean;
  notAvailable: boolean;
  notAvailableMessage: string;
  content: string | undefined;
  downloadLabel: string;
  onRetry: () => void;
  onDownload: () => void;
};

export function FeedPreviewModal({
  opened,
  onClose,
  title,
  isPending,
  isError,
  notAvailable,
  notAvailableMessage,
  content,
  downloadLabel,
  onRetry,
  onDownload,
}: Props) {
  const { t } = useTranslation('export');
  const formatted = useMemo(() => prettifyXml(content ?? ''), [content]);
  const sliced = useMemo(() => sliceXmlLines(formatted, MAX_PREVIEW_LINES), [formatted]);

  return (
    <Modal opened={opened} onClose={onClose} size="xl" title={title}>
      {isPending ? <LoadingState /> : null}
      {!isPending && isError ? (
        notAvailable ? (
          <EmptyState message={notAvailableMessage} />
        ) : (
          <ErrorState onRetry={onRetry} />
        )
      ) : null}
      {content ? (
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
            <Button leftSection={<IconDownload size={16} />} onClick={onDownload}>
              {downloadLabel}
            </Button>
          </Group>
        </>
      ) : null}
    </Modal>
  );
}
