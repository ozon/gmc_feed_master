import { useDeleteClient } from '../../api/hooks';
import { notifyMutationError, notifySuccess } from '../../app/notifications';
import type { ClientSummary } from '../../api/types';
import { useTranslation } from 'react-i18next';
import { ConfirmModal } from '../../components/ConfirmModal';

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
  const deleteClient = useDeleteClient();

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
    <ConfirmModal
      opened={opened}
      title={t('delete')}
      message={t('deleteCascade')}
      danger
      typeToConfirm={client?.name}
      loading={deleteClient.isPending}
      onConfirm={onConfirm}
      onClose={onClose}
    />
  );
}
