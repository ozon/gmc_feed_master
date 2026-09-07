import {
  Badge, Button, Card, CloseButton, Collapse, Group, Indicator, Loader, Paper, Progress,
  SimpleGrid, Stack, Text, Textarea, Tooltip,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { parseIdList, renderPreview } from './ids';
import type { ScopedSlotRule, SlotRule, Tier } from './scopeMerge';
import type { PreviewRuleStats } from './usePreview';

export type SlotGroupProps = {
  slot: string;
  rules: ScopedSlotRule[];
  values: Record<string, string>;
  inheritedFor: (id: string) => Tier | null;
  isRuleEditable: (rule: ScopedSlotRule) => boolean;
  editableTier: Tier | null;
  dirty: boolean;
  onSetSlotIds: (next: Record<string, string>) => void;
  onPatchRule: (id: string, patch: Partial<SlotRule>) => void;
  showLive: boolean;
  stats?: { labeled: number; coverage: number };
  ruleStats?: Record<string, PreviewRuleStats>;
  total?: number;
  previewPending: boolean;
  previewErrors: string[] | null;
  previewUnavailable: boolean;
};

export function SlotGroup({
  slot, rules, values, inheritedFor, isRuleEditable, editableTier, dirty, onSetSlotIds, onPatchRule,
  showLive, stats, ruleStats, total, previewPending, previewErrors, previewUnavailable,
}: SlotGroupProps) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  return (
    <Card withBorder p="sm" data-testid={`slot-group-${slot}`}>
      <Stack gap="xs">
        <Group gap="xs" justify="space-between" wrap="wrap">
          <Group gap="xs" wrap="nowrap">
            <Indicator color="orange" size={8} offset={-4} position="top-end" disabled={!dirty}>
              <Badge variant="light" color="teal">{slot}</Badge>
            </Indicator>
            <Text size="xs" c="dimmed">{t(`slotExplanations.${slot}` as 'slotExplanations.custom_label_0')}</Text>
          </Group>
          <Text size="xs" c="dimmed">{t('activeRulesCount', { count: rules.length })}</Text>
        </Group>
        {!showLive ? null : previewUnavailable ? (
          <Text size="xs" c="dimmed">{t('previewUnavailable')}</Text>
        ) : previewErrors ? (
          <Stack gap={2}>
            {previewErrors.map((error) => (
              <Text key={error} size="xs" c="dimmed">{error}</Text>
            ))}
          </Stack>
        ) : total === undefined ? (
          previewPending ? <Loader size="xs" /> : null
        ) : total === 0 ? (
          <Text size="xs" c="dimmed">{t('noStagedProducts')}</Text>
        ) : (
          <Stack gap={4}>
            <Group gap="xs" wrap="nowrap">
              {previewPending && <Loader size="xs" />}
              <Text size="xs" c="dimmed">
                {t('slotLabeledOf', { count: stats?.labeled ?? 0, total })}
              </Text>
            </Group>
            <Progress value={Math.min(100, Math.max(0, stats?.coverage ?? 0))} size="sm" />
          </Stack>
        )}
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md" verticalSpacing="sm">
          {rules.map((rule) => {
            const allMode = rule.matchMode === 'all';
            const raw = values[rule.id] ?? '';
            const count = parseIdList(raw).size;
            const inheritedFrom = inheritedFor(rule.id);
            const rs = ruleStats?.[rule.id];
            const neverApplied = showLive && rs !== undefined && rs.matched > 0 && rs.labeled === 0;
            return (
              <Stack key={rule.id} gap={4}>
                <Group gap="xs" justify="space-between" wrap="nowrap">
                  <Group gap="xs" wrap="nowrap">
                    <Text size="sm" fw={600}>{rule.name}</Text>
                    {inheritedFrom !== null && (
                      <Badge size="xs" variant="light" color="teal">
                        {t('inheritedFrom', { tier: tCommon(`scope.${inheritedFrom}`) })}
                      </Badge>
                    )}
                    {showLive && rs ? (
                      neverApplied ? (
                        <Tooltip
                          label={`${t('neverApplied')} — ${t('neverAppliedHint')}`}
                          withArrow
                          position="top"
                        >
                          <Badge size="xs" variant="light" color="gray">
                            {t('matchedCount', { count: rs.matched })}
                          </Badge>
                        </Tooltip>
                      ) : (
                        <Badge size="xs" variant="light">
                          {t('matchedCount', { count: rs.matched })}
                        </Badge>
                      )
                    ) : null}
                  </Group>
                  <Group gap={6} wrap="nowrap">
                    <Text size="xs" c="dimmed">{rule.matchField}</Text>
                    {!allMode && raw !== '' && (
                      <CloseButton
                        size="xs"
                        aria-label={`${t('clearValues')} — ${rule.name}`}
                        onClick={() => onSetSlotIds({ ...values, [rule.id]: '' })}
                      />
                    )}
                  </Group>
                </Group>
                <Text size="xs" c="dimmed">{renderPreview(rule.valueTemplate)}</Text>
                <Collapse expanded={!allMode} keepMounted={false}>
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
                    bottomSection={<Text size="xs" c="dimmed">{t('idCount', { count })}</Text>}
                    value={raw}
                    onChange={(e) => onSetSlotIds({ ...values, [rule.id]: e.currentTarget.value })}
                    placeholder={t('idsPlaceholder')}
                  />
                </Collapse>
                <Collapse expanded={allMode} keepMounted={false}>
                  <Paper withBorder p="xs" data-testid={`all-mode-${rule.id}`}>
                    <Stack gap={4}>
                      <Text size="sm" c="dimmed">{t('bulk.controlledByRule')}</Text>
                      <Text size="sm" fw={600}>
                        {t('bulk.allProductsGet', { preview: renderPreview(rule.valueTemplate) })}
                      </Text>
                      {isRuleEditable(rule) && (
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
                </Collapse>
              </Stack>
            );
          })}
        </SimpleGrid>
      </Stack>
    </Card>
  );
}
