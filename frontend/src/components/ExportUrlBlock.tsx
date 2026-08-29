import { useState } from 'react';
import { Button, Stack, Title } from '@mantine/core';
import { IconRotate } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useRotateExportToken } from '../api/hooks';
import { ApiError } from '../api/client';
import { notifyMutationError, notifySuccess } from '../app/notifications';
import { ConfirmModal } from './ConfirmModal';
import { CopyField } from './CopyField';

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
  const { t: tCommon } = useTranslation('common');
  const rotateToken = useRotateExportToken();
  const [rotateOpened, setRotateOpened] = useState(false);

  function handleRotate() {
    rotateToken.mutate(feedSourceId, {
      onSuccess: () => {
        notifySuccess(t('rotated'));
        setRotateOpened(false);
        onRotated?.();
      },
      onError: (error) => {
        if (error instanceof ApiError) {
          notifyMutationError(error, t('rotated'));
        } else {
          notifyMutationError(error, t('rotated'));
        }
      },
    });
  }

  return (
    <Stack gap="md">
      <Title order={4}>{t('urlTitle')}</Title>
      <CopyField label={t('publicUrl')} value={exportUrl} />
      <Button
        variant="light"
        color="orange"
        leftSection={<IconRotate size={16} />}
        onClick={() => setRotateOpened(true)}
      >
        {t('rotate')}
      </Button>
      <ConfirmModal
        opened={rotateOpened}
        title={t('rotate')}
        message={t('rotateWarning')}
        danger
        loading={rotateToken.isPending}
        onConfirm={handleRotate}
        onClose={() => setRotateOpened(false)}
      />
    </Stack>
  );
}
