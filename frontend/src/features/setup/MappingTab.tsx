import { useTranslation } from 'react-i18next';
import { EmptyState } from '../../components/StateViews';

export function MappingTab() {
  const { t } = useTranslation('setup');
  return <EmptyState message={t('mappingPlaceholder')} />;
}
