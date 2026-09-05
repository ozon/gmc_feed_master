import { Badge, Group, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { LocalInstance } from './dndUtils';

type Props = {
  instances: LocalInstance[];
  dirty: boolean;
};

export function PipelineOverviewStrip({ instances, dirty }: Props) {
  const { t } = useTranslation('pipeline');
  const enabled = instances.filter((i) => i.enabled).length;
  return (
    <Group gap="md" data-testid="overview-strip">
      <Text size="sm" c="dimmed">{t('overviewTotal', { count: instances.length })}</Text>
      <Text size="sm" c="dimmed">{t('overviewEnabled', { count: enabled })}</Text>
      <Text size="sm" c="dimmed">{t('overviewDisabled', { count: instances.length - enabled })}</Text>
      {dirty ? <Badge color="orange" variant="light">{t('overviewDirty')}</Badge> : null}
    </Group>
  );
}
