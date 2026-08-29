import { useState } from 'react';
import { Button, Group, Modal, Stack, Text, TextInput } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export type ConfirmModalProps = {
  opened: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  loading?: boolean;
  typeToConfirm?: string;
  onConfirm: () => void;
  onClose: () => void;
};

export function ConfirmModal({
  opened,
  title,
  message,
  confirmLabel,
  danger = false,
  loading = false,
  typeToConfirm,
  onConfirm,
  onClose,
}: ConfirmModalProps) {
  const { t } = useTranslation();
  const [confirmText, setConfirmText] = useState('');

  const matchesType = typeToConfirm ? confirmText === typeToConfirm : true;

  return (
    <Modal opened={opened} onClose={onClose} title={title} centered>
      <Stack gap="md">
        <Text>{message}</Text>
        {typeToConfirm !== undefined && (
          <TextInput
            label={t('actions.typeToConfirm', { name: typeToConfirm })}
            value={confirmText}
            onChange={(event) => setConfirmText(event.currentTarget.value)}
            withAsterisk
          />
        )}
        <Group mt="lg" justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={loading}>
            {t('actions.cancel')}
          </Button>
          <Button
            color={danger ? 'red' : undefined}
            loading={loading}
            disabled={!matchesType}
            onClick={onConfirm}
          >
            {confirmLabel ?? t('actions.confirm')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
