import { Button, Group, Modal, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export type ConfirmModalProps = {
  opened: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  loading?: boolean;
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
  onConfirm,
  onClose,
}: ConfirmModalProps) {
  const { t } = useTranslation();
  return (
    <Modal opened={opened} onClose={onClose} title={title} centered>
      <Text>{message}</Text>
      <Group mt="lg" justify="flex-end">
        <Button variant="default" onClick={onClose} disabled={loading}>
          {t('actions.cancel')}
        </Button>
        <Button color={danger ? 'red' : undefined} loading={loading} onClick={onConfirm}>
          {confirmLabel ?? t('actions.confirm')}
        </Button>
      </Group>
    </Modal>
  );
}
