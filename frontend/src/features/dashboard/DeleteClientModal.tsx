import { useEffect, useState } from 'react';
import { Button, Group, Modal, Stack, Text, TextInput } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useDeleteClient } from '../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../app/notifications';
import type { ClientSummary } from '../../api/types';

export function DeleteClientModal({
  opened,
  client,
  onClose,
}: {
  opened: boolean;
  client: ClientSummary | null;
  onClose: () => void;
}) {
  const { t } = useTranslation('dashboard');
  const { t: tCommon } = useTranslation('common');
  const deleteClient = useDeleteClient();
  const [confirmText, setConfirmText] = useState('');

  useEffect(() => {
    if (opened) {
      setConfirmText('');
    }
  }, [opened]);

  const confirmed = client !== null && confirmText === client.name;

  function onConfirm() {
    if (!client) return;
    deleteClient.mutate(client.id, {
      onSuccess: () => {
        notifySuccess(t('saved'));
        onClose();
      },
      onError: (error) => notifyMutationError(error, t('deleteFailed')),
    });
  }

  return (
    <Modal opened={opened} onClose={onClose} title={t('delete')} centered>
      <Stack gap="md">
        <Text size="sm">{t('deleteCascade')}</Text>
        {client ? (
          <TextInput
            label={t('typeToConfirm', { name: client.name })}
            value={confirmText}
            onChange={(event) => setConfirmText(event.currentTarget.value)}
            withAsterisk
          />
        ) : null}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={deleteClient.isPending}>
            {tCommon('actions.cancel')}
          </Button>
          <Button
            color="red"
            disabled={!confirmed}
            loading={deleteClient.isPending}
            onClick={onConfirm}
          >
            {tCommon('actions.confirm')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
