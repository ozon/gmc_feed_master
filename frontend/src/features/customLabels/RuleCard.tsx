import {
  Accordion, Badge, Button, Group, Indicator, Paper, Stack, Text, Tooltip,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { renderPreview } from './ids';
import { RuleValuesEditor } from './RuleValuesEditor';
import type { ShadowOwnerInfo } from './shadowing';
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
  shadowedBy: ReadonlyMap<string, ShadowOwnerInfo>;
  feedSourceId?: number;
  extraFields: string[];
  onExtraFieldsChange: (fields: string[]) => void;
  onSetIds: (value: string) => void;
  onPatchRule: (id: string, patch: Partial<SlotRule>) => void;
  previewOpen: boolean;
  onTogglePreview: () => void;
};

export function RuleCard({
  rule, priority, value, dirty, inheritedFrom, editable, matchedStats,
  showLive, shadowedBy, feedSourceId, extraFields, onExtraFieldsChange,
  onSetIds, onPatchRule, previewOpen, onTogglePreview,
}: RuleCardProps) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  const allMode = rule.matchMode === 'all';
  const neverApplied = showLive
    && matchedStats !== undefined
    && matchedStats.matched > 0
    && matchedStats.labeled === 0;

  return (
    <Accordion.Item value={rule.id} data-testid={`rule-card-${rule.id}`}>
      <Accordion.Control>
        <Group gap="xs" wrap="nowrap">
          <Text size="xs" c="dimmed" component="span" data-testid="priority-badge">
            {`#${priority}`}
          </Text>
          <Indicator color="orange" size={8} offset={-4} position="top-end" disabled={!dirty}>
            <Text size="sm" fw={600} component="span">{rule.name}</Text>
          </Indicator>
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
            <RuleValuesEditor
              rule={rule}
              value={value}
              feedSourceId={feedSourceId}
              extraFields={extraFields}
              onExtraFieldsChange={onExtraFieldsChange}
              onSetIds={onSetIds}
              shadowedBy={shadowedBy}
              previewOpen={previewOpen}
              onTogglePreview={onTogglePreview}
            />
          )}
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
}
