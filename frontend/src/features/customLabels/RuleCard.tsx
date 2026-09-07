import {
  Accordion, Badge, Button, CloseButton, Group, Indicator, Paper, Stack, Text, Textarea, Tooltip,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { parseIdList, renderPreview } from './ids';
import { ShadowList } from './ShadowList';
import type { ScopedSlotRule, SlotRule, Tier } from './scopeMerge';
import type { PreviewRuleStats } from './usePreview';

export type RuleCardProps = {
  rule: ScopedSlotRule;
  /** 1-based evaluation position within the selected slot. */
  priority: number;
  value: string;
  dirty: boolean;
  inheritedFrom: Tier | null;
  editable: boolean;
  matchedStats?: PreviewRuleStats;
  showLive: boolean;
  shadowedBy: ReadonlyMap<string, string>;
  onSetIds: (value: string) => void;
  onPatchRule: (id: string, patch: Partial<SlotRule>) => void;
};

export function RuleCard({
  rule, priority, value, dirty, inheritedFrom, editable, matchedStats,
  showLive, shadowedBy, onSetIds, onPatchRule,
}: RuleCardProps) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  const allMode = rule.matchMode === 'all';
  const count = parseIdList(value).size;
  const neverApplied = showLive
    && matchedStats !== undefined
    && matchedStats.matched > 0
    && matchedStats.labeled === 0;

  return (
    <Accordion.Item value={rule.id} data-testid={`rule-card-${rule.id}`}>
      <Accordion.Control>
        <Group gap="xs" wrap="nowrap">
          <Indicator color="orange" size={8} offset={-4} position="top-end" disabled={!dirty}>
            <Text size="sm" fw={600} component="span">{rule.name}</Text>
          </Indicator>
          <Badge size="xs" variant="light" color="blue" data-testid="priority-badge">
            {t('priority', { index: priority })}
          </Badge>
          {inheritedFrom !== null && (
            <Badge size="xs" variant="light" color="teal">
              {t('inheritedFrom', { tier: tCommon(`scope.${inheritedFrom}`) })}
            </Badge>
          )}
          {showLive && matchedStats ? (
            neverApplied ? (
              <Tooltip
                label={`${t('neverApplied')} — ${t('neverAppliedHint')}`}
                withArrow
                position="top"
              >
                <Badge size="xs" variant="light" color="gray">
                  {t('matchedCount', { count: matchedStats.matched })}
                </Badge>
              </Tooltip>
            ) : (
              <Badge size="xs" variant="light">
                {t('matchedCount', { count: matchedStats.matched })}
              </Badge>
            )
          ) : null}
          {shadowedBy.size > 0 && (
            <Badge size="xs" variant="light" color="orange" data-testid="shadowed-badge">
              {t('shadowedCount', { count: shadowedBy.size })}
            </Badge>
          )}
        </Group>
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap="xs">
          <Text size="xs" c="dimmed">{renderPreview(rule.valueTemplate)}</Text>
          {allMode ? (
            <Paper withBorder p="xs" data-testid={`all-mode-${rule.id}`}>
              <Stack gap={4}>
                <Text size="sm" c="dimmed">{t('bulk.controlledByRule')}</Text>
                <Text size="sm" fw={600}>
                  {t('bulk.allProductsGet', { preview: renderPreview(rule.valueTemplate) })}
                </Text>
                {editable && (
                  <Button
                    variant="subtle"
                    size="xs"
                    onClick={() => onPatchRule(rule.id, { matchMode: 'values' })}
                  >
                    {t('bulk.switchToValueList')}
                  </Button>
                )}
              </Stack>
            </Paper>
          ) : (
            <Stack gap={4}>
              <Textarea
                label={rule.matchField === 'id'
                  ? t('bulk.productIds')
                  : t('bulk.valuesFor', { field: rule.matchField })}
                aria-label={rule.matchField === 'id'
                  ? `${t('bulk.productIds')} — ${rule.name}`
                  : `${t('bulk.valuesFor', { field: rule.matchField })} — ${rule.name}`}
                minRows={5}
                autosize
                styles={{
                  input: {
                    maxHeight: 400,
                    overflowY: 'auto',
                    fontFamily: 'var(--mantine-font-family-monospace)',
                  },
                }}
                value={value}
                onChange={(e) => onSetIds(e.currentTarget.value)}
                placeholder={t('idsPlaceholder')}
              />
              <Group gap="xs" justify="space-between" wrap="nowrap">
                <Text size="xs" c="dimmed" data-testid={`id-count-${rule.id}`}>
                  {t('idCount', { count })}
                </Text>
                <Group gap={6} wrap="nowrap">
                  <Text size="xs" c="dimmed">{rule.matchField}</Text>
                  {value !== '' && (
                    <CloseButton
                      size="xs"
                      aria-label={`${t('clearValues')} — ${rule.name}`}
                      onClick={() => onSetIds('')}
                    />
                  )}
                </Group>
              </Group>
            </Stack>
          )}
          <ShadowList shadowedBy={shadowedBy} />
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
}
