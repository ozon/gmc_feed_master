import { useTranslation } from 'react-i18next';
import { ConfirmModal } from '../../components/ConfirmModal';

type Props = {
  opened: boolean;
  version: number | null;
  onClose: () => void;
  onConfirm: (version: number) => void;
  pending: boolean;
};

export function RollbackConfirmModal({ opened, version, onClose, onConfirm, pending }: Props) {
  const { t } = useTranslation('export');
  if (!version) return null;
  return (
    <ConfirmModal
      opened={opened}
      onClose={onClose}
      title={t('rollbackConfirmTitle', { version })}
      message={t('rollbackConfirmBody', { version })}
      confirmLabel={t('rollback')}
      danger
      typeToConfirm={String(version)}
      loading={pending}
      onConfirm={() => onConfirm(version)}
    />
  );
}