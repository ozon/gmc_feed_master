import { useTranslation } from 'react-i18next';
import { useExportVersionContent } from '../../api/hooks';
import { ApiError } from '../../api/client';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { FeedPreviewModal } from '../../components/FeedPreviewModal';
import { downloadVersionXml } from './download';

type Props = {
  feedSourceId: number | string;
  version: number | null;
  opened: boolean;
  onClose: () => void;
};

export function FeedVersionPreviewModal({ feedSourceId, version, opened, onClose }: Props) {
  const { t } = useTranslation('export');
  const content = useExportVersionContent(feedSourceId, version ?? undefined, opened);

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
    <FeedPreviewModal
      opened={opened}
      onClose={onClose}
      title={version !== null ? t('preview.title', { version }) : ''}
      isPending={content.isPending}
      isError={content.isError}
      notAvailable={content.error instanceof ApiError && content.error.status === 404}
      notAvailableMessage={t('preview.notRetained')}
      content={content.data}
      downloadLabel={t('download.version')}
      onRetry={() => void content.refetch()}
      onDownload={() => void handleDownload()}
    />
  );
}
