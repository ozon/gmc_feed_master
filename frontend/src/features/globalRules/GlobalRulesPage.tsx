import { Stack, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { EmptyState } from '../../components/StateViews';

export function GlobalRulesPage() {
  const { t } = useTranslation('globalRules');
  return (
    <Stack pt="md">
      <Title order={3}>{t('title')}</Title>
      <EmptyState message={t('comingSoon')} />
    </Stack>
  );
}
