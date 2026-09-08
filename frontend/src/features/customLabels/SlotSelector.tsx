import { Group, Indicator, SegmentedControl, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export function SlotSelector({
  slots, value, onChange, dirty, activeCount,
}: {
  slots: ReadonlyArray<string>;
  value: string;
  onChange: (slot: string) => void;
  dirty: boolean;
  activeCount: number;
}) {
  const { t } = useTranslation('customLabels');
  return (
    <Stack gap={4}>
      <Indicator color="orange" size={8} offset={-2} position="top-end" disabled={!dirty}>
        <SegmentedControl
          aria-label={t('slotSelectorLabel')}
          data={slots.map((slot) => ({ value: slot, label: slot.toUpperCase() }))}
          value={value}
          onChange={onChange}
          data-testid="slot-selector"
        />
      </Indicator>
      <Group gap="xs" wrap="wrap">
        <Text size="xs" c="dimmed">
          {t(`slotExplanations.${value}` as 'slotExplanations.custom_label_0')}
        </Text>
        <Text size="xs" c="dimmed">
          {t('activeRulesCount', { count: activeCount })}
        </Text>
      </Group>
    </Stack>
  );
}
