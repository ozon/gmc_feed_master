import { Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';

function Placeholder({ ns }: { ns: 'dashboard' | 'setup' | 'products' | 'pipeline' | 'monitoring' | 'export' }) {
  const { t } = useTranslation(ns);
  return <Title order={2}>{t('title')}</Title>;
}

export function DashboardPlaceholder() {
  return <Placeholder ns="dashboard" />;
}

export function SetupPlaceholder() {
  return <Placeholder ns="setup" />;
}

export function ProductsPlaceholder() {
  return <Placeholder ns="products" />;
}

export function PipelinePlaceholder() {
  return <Placeholder ns="pipeline" />;
}

export function MonitoringPlaceholder() {
  return <Placeholder ns="monitoring" />;
}

export function ExportPlaceholder() {
  return <Placeholder ns="export" />;
}

export function PluginPlaceholder() {
  return <Title order={2}>Plugin</Title>;
}
