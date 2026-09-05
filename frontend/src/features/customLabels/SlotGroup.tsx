import { Badge, Button, Card, Collapse, Group, Paper, Stack, Text, Textarea } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { parseIdList, renderPreview } from './ids';
import type { ScopedSlotRule, SlotRule, Tier } from './scopeMerge';

export type SlotGroupProps = {
  slot: string;
  rules: ScopedSlotRule[];
  values: Record<string, string>;
  inheritedFor: (id: string) => boolean;
  isRuleEditable: (rule: ScopedSlotRule) => boolean;
  editableTier: Tier | null;
  onSetSlotIds: (next: Record<string, string>) => void;
  onPatchRule: (id: string, patch: Partial<SlotRule>) => void;
};

export function SlotGroup({
  slot, rules, values, inheritedFor, isRuleEditable, editableTier, onSetSlotIds, onPatchRule,
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
        <Stack gap="md">
          {rules.map((rule) => {
            const allMode = rule.matchMode === 'all';
            const raw = values[rule.id] ?? '';
            const count = parseIdList(raw).size;
            const inherited = inheritedFor(rule.id);
            return (
              <Stack key={rule.id} gap={4}>
                <Group gap="xs" justify="space-between" wrap="nowrap">
                  <Group gap="xs" wrap="nowrap">
                    <Text size="sm" fw={600}>{rule.name}</Text>
                    {inherited && (
                      <Badge size="xs" variant="light" color="teal">
                        {t('inheritedFrom', { tier: tCommon('scope.client') })}
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
