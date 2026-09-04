import { Badge, Group, Switch, Text, UnstyledButton } from '@mantine/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useTranslation } from 'react-i18next';

export type SlotRuleSummary = {
  id: string;
  name: string;
  targetSlot: string;
  isActive: boolean;
};

export function SortableRuleRow({
  rule,
  selected,
  onSelect,
  onToggleActive,
}: {
  rule: SlotRuleSummary;
  selected: boolean;
  onSelect: () => void;
  onToggleActive: (isActive: boolean) => void;
}) {
  const { t } = useTranslation('customLabels');
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({
    id: rule.id,
  });
  return (
    <Group
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      gap="xs"
      px="xs"
      py={4}
      onClick={onSelect}
      data-selected={selected || undefined}
    >
      <UnstyledButton
        {...attributes}
        {...listeners}
        aria-label={t('dragHandle')}
        style={{ cursor: 'grab' }}
      >
        ⠿
      </UnstyledButton>
      <Text size="sm" style={{ flex: 1 }}>
        {rule.name}
      </Text>
      <Badge size="xs" variant="light">
        {rule.targetSlot}
      </Badge>
      <Switch
        checked={rule.isActive}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onToggleActive(e.currentTarget.checked)}
      />
    </Group>
  );
}
