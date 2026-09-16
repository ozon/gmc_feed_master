import { Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { severityColor } from './severity';

export function SeverityBadge({ severity }: { severity: string }) {
  const { t } = useTranslation('monitoring');
  return (
    <Badge color={severityColor(severity)} data-testid={`severity-badge-${severity}`}>
      {t(`severity.${severity}`, { defaultValue: severity })}
    </Badge>
  );
}
