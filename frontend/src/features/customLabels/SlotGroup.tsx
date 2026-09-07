import { Anchor, Badge, Button, Card, Collapse, Group, Loader, Paper, Stack, Text, Textarea, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
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
  onSetSlotIds: (next: Record<string, string>) => void;
  onPatchRule: (id: string, patch: Partial<SlotRule>) => void;
  showLive: boolean;
  stats?: { labeled: number; coverage: number };
  ruleStats?: Record<string, PreviewRuleStats>;
  total?: number;
  previewPending: boolean;
  previewErrors: string[] | null;
  previewUnavailable: boolean;
  productsHref: string | null;
};

export function SlotGroup({
  slot, rules, values, inheritedFor, isRuleEditable, editableTier, onSetSlotIds, onPatchRule,
  showLive, stats, ruleStats, total, previewPending, previewErrors, previewUnavailable, productsHref,
}: SlotGroupProps) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  return (
    <Card withBorder p="sm" data-testid={`slot-group-${slot}`}>
      <Stack gap="xs">
        <Group gap="xs" justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <Badge variant="light" color="teal">{slot}</Badge>
            <Text size="xs" c="dimmed">{t(`slotExplanations.${slot}` as 'slotExplanations.custom_label_0')}</Text>
          </Group>
          <Text size="xs" c="dimmed">{t('activeRulesCount', { count: rules.length })}</Text>
        </Group>
        {!showLive ? (
          <Text size="xs" c="dimmed">{t('openFromFeed')}</Text>
        ) : previewUnavailable ? (
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
                {t('slotLabeled', { count: stats?.labeled ?? 0 })}
              </Text>
              <Text size="xs" c="dimmed">
                {t('coveragePct', { coverage: stats?.coverage ?? 0 })}
              </Text>
              <Text size="xs" c="dimmed">{t('freshnessHint', { count: total })}</Text>
            </Group>
            {rules.map((rule) => {
              const rs = ruleStats?.[rule.id];
              const neverApplied = (rs?.matched ?? 0) > 0 && (rs?.labeled ?? 0) === 0;
              return (
                <Group key={rule.id} gap="xs" wrap="nowrap">
                  <Text size="xs" fw={500}>{rule.name}</Text>
                  <Text size="xs" c="dimmed">
                    {t('matchedCount', { count: rs?.matched ?? 0 })}
                  </Text>
                  {neverApplied && (
                    <Tooltip label={t('neverAppliedHint')} withArrow position="top">
                      <Badge size="xs" variant="light" color="gray">
                        {t('neverApplied')}
                      </Badge>
                    </Tooltip>
                  )}
                  {(rs?.sample ?? []).map((pid) => (
                    <Anchor
                      key={pid}
                      component={Link}
                      to={`${productsHref}?q=${encodeURIComponent(pid)}`}
                      size="xs"
                    >
                      {pid}
                    </Anchor>
                  ))}
                </Group>
              );
            })}
          </Stack>
        )}
        <Stack gap="md">
          {rules.map((rule) => {
            const allMode = rule.matchMode === 'all';
            const raw = values[rule.id] ?? '';
            const count = parseIdList(raw).size;
            const inheritedFrom = inheritedFor(rule.id);
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
                  </Group>
                  <Text size="xs" c="dimmed">{rule.matchField}</Text>
                </Group>
                <Text size="xs" c="dimmed">{renderPreview(rule.valueTemplate)}</Text>
                <Collapse expanded={!allMode} keepMounted={false}>
                  <Stack gap={4}>
                    <Textarea
                      label={rule.matchField === 'id'
                        ? t('bulk.productIds')
                        : t('bulk.valuesFor', { field: rule.matchField })}
                      aria-label={rule.matchField === 'id'
                        ? `${rule.name} ids`
                        : `${rule.name} values`}
                      minRows={5}
                      autosize
                      value={raw}
                      onChange={(e) => onSetSlotIds({ ...values, [rule.id]: e.currentTarget.value })}
                      placeholder={t('idsPlaceholder')}
                    />
                    <Text size="xs" c="dimmed">{t('idCount', { count })}</Text>
                  </Stack>
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
        </Stack>
      </Stack>
    </Card>
  );
}
