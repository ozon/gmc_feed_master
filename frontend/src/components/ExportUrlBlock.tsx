import { useState } from 'react';
import { Button, Group, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconCheck, IconDownload, IconEye, IconRotate } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  usePublishedExportContent,
  useRotateExportToken,
  useSession,
  useSetExportToken,
} from '../api/hooks';
import { ApiError } from '../api/client';
import { notifyApiError, notifyMutationError, notifySuccess } from '../app/notifications';
import { ConfirmModal } from './ConfirmModal';
import { CopyField } from './CopyField';
import { FeedPreviewModal } from './FeedPreviewModal';
import { downloadLiveXml } from '../features/export/download';

function isWeakToken(value: string): boolean {
  return value.length < 8 || /^\d+$/.test(value);
}

export function ExportUrlBlock({
  feedSourceId,
  exportUrl,
  onRotated,
}: {
  feedSourceId: number | string;
  exportUrl: string;
  onRotated?: () => void;
}) {
  const { t } = useTranslation('export');
  const { data: session } = useSession();
  const isAdmin = session?.role === 'admin';
  const rotateToken = useRotateExportToken();
  const setToken = useSetExportToken(feedSourceId);
  const currentToken = exportUrl.split('/export/')[1]?.replace(/\.xml$/, '') ?? '';
  const [tokenValue, setTokenValue] = useState(currentToken);
  const [prevUrl, setPrevUrl] = useState(exportUrl);
  if (prevUrl !== exportUrl) {
    setPrevUrl(exportUrl);
    setTokenValue(currentToken);
  }
  const [rotateOpened, setRotateOpened] = useState(false);
  const [saveOpened, setSaveOpened] = useState(false);
  const [previewOpened, setPreviewOpened] = useState(false);
  const [liveDownloading, setLiveDownloading] = useState(false);
  const liveContent = usePublishedExportContent(exportUrl, previewOpened);

  async function handleDownloadLive() {
    setLiveDownloading(true);
    try {
      await downloadLiveXml(feedSourceId, exportUrl);
      notifySuccess(t('download.live'));
    } catch (error) {
      notifyApiError(error, t('download.failed'));
    } finally {
      setLiveDownloading(false);
    }
  }

  function handleRotate() {
    rotateToken.mutate(feedSourceId, {
      onSuccess: () => {
        notifySuccess(t('rotated'));
        setRotateOpened(false);
        onRotated?.();
      },
      onError: (error) => {
        notifyMutationError(error, t('rotateFailed'));
      },
    });
  }

  function handleSave() {
    setToken.mutate(tokenValue, {
      onSuccess: () => {
        notifySuccess(t('tokenSaved'));
        setSaveOpened(false);
        onRotated?.();
      },
      onError: (error) => {
        notifyMutationError(error, t('tokenSaveFailed'));
      },
    });
  }

  return (
    <Stack gap="md">
      <Title order={4}>{t('urlTitle')}</Title>
      <CopyField label={t('publicUrl')} value={exportUrl} />
      <Group>
        <Button
          variant="light"
          leftSection={<IconEye size={16} />}
          onClick={() => setPreviewOpened(true)}
          data-testid="live-preview"
        >
          {t('preview.openLive')}
        </Button>
        <Button
          variant="light"
          leftSection={<IconDownload size={16} />}
          onClick={() => void handleDownloadLive()}
          loading={liveDownloading}
          data-testid="live-download"
        >
          {t('download.live')}
        </Button>
      </Group>
      {isAdmin ? (
        <>
          <TextInput
            label={t('customToken')}
            value={tokenValue}
            onChange={(event) => setTokenValue(event.currentTarget.value)}
            data-testid="token-input"
          />
          {tokenValue.length > 0 && isWeakToken(tokenValue) ? (
            <Text size="xs" c="dimmed">
              {t('weakHint')}
            </Text>
          ) : null}
          <Group>
            <Button
              variant="light"
              leftSection={<IconCheck size={16} />}
              onClick={() => setSaveOpened(true)}
              disabled={tokenValue.length === 0}
              data-testid="token-save"
            >
              {t('changeToken')}
            </Button>
            <Button
              variant="light"
              color="orange"
              leftSection={<IconRotate size={16} />}
              onClick={() => setRotateOpened(true)}
            >
              {t('generateRandom')}
            </Button>
          </Group>
        </>
      ) : (
        <Button
          variant="light"
          color="orange"
          leftSection={<IconRotate size={16} />}
          onClick={() => setRotateOpened(true)}
        >
          {t('rotate')}
        </Button>
      )}
      <ConfirmModal
        opened={rotateOpened}
        title={t('rotate')}
        message={t('rotateWarning')}
        danger
        loading={rotateToken.isPending}
        onConfirm={handleRotate}
        onClose={() => setRotateOpened(false)}
      />
      <ConfirmModal
        opened={saveOpened}
        title={t('changeToken')}
        message={t('changeWarning')}
        danger
        loading={setToken.isPending}
        onConfirm={handleSave}
        onClose={() => setSaveOpened(false)}
      />
      <FeedPreviewModal
        opened={previewOpened}
        onClose={() => setPreviewOpened(false)}
        title={t('preview.liveTitle')}
        isPending={liveContent.isPending}
        isError={liveContent.isError}
        notAvailable={liveContent.error instanceof ApiError && liveContent.error.status === 404}
        notAvailableMessage={t('preview.notPublished')}
        content={liveContent.data}
        downloadLabel={t('download.live')}
        onRetry={() => void liveContent.refetch()}
        onDownload={() => void handleDownloadLive()}
      />
    </Stack>
  );
}
