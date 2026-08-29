import { Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';

function Placeholder({ ns }: { ns: 'monitoring' | 'export' }) {
  const { t } = useTranslation(ns);
  return <Title order={2}>{t('title')}</Title>;
}

export function MonitoringPlaceholder() {
  return <Placeholder ns="monitoring" />;
}

export function ExportPlaceholder() {
  return <Placeholder ns="export" />;
}
