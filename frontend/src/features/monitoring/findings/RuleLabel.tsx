import { Text, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ruleInfo, ruleTitle } from './ruleCatalog';

export function RuleLabel({ code }: { code: string }) {
  const { t } = useTranslation('monitoring');
  const info = ruleInfo(code);
  return (
    <Tooltip label={t(info.descriptionKey as 'rules.unknown.description')} withinPortal>
      <Text size="sm" component="span" data-testid={`rule-label-${code}`}>
        {ruleTitle(code, t)}
      </Text>
    </Tooltip>
  );
}
