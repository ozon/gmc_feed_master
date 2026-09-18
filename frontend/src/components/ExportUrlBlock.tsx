import { useState } from 'react';
import { Button, Group, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconCheck, IconRotate } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useRotateExportToken, useSession, useSetExportToken } from '../api/hooks';
import { notifyMutationError, notifySuccess } from '../app/notifications';
import { ConfirmModal } from './ConfirmModal';
import { CopyField } from './CopyField';

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
  const [rotateOpened, setRotateOpened] = useState(false);
  const [saveOpened, setSaveOpened] = useState(false);

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
      {isAdmin ? (
        <>
          <TextInput
            label={t('customToken')}
            value={tokenValue}
            onChange={(event) => setTokenValue(event.currentTarget.value)}
            data-testid="token-input"
          />
          {isWeakToken(tokenValue) ? (
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
    </Stack>
  );
}
