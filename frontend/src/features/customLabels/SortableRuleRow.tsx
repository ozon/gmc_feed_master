import { Badge, Group, Switch, Text, UnstyledButton } from '@mantine/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';

export type SlotRuleSummary = {
  id: string;
  name: string;
  targetSlot: string;
  isActive: boolean;
};

export function SortableRuleRow({
  rule,
  selected,
  disabled = false,
  badge,
  onSelect,
  onToggleActive,
}: {
  rule: SlotRuleSummary;
  selected: boolean;
  disabled?: boolean;
  badge?: ReactNode;
  onSelect: () => void;
  onToggleActive: (isActive: boolean) => void;
}) {
  const { t } = useTranslation('customLabels');
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({
    id: rule.id,
    disabled,
  });
  return (
    <Group
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: rule.isActive ? undefined : 0.55,
      }}
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
        style={{ cursor: disabled ? 'default' : 'grab' }}
      >
        ⠿
      </UnstyledButton>
      <Text size="sm" style={{ flex: 1 }}>
        {rule.name}
      </Text>
      {badge}
      <Badge size="xs" variant="light">
        {rule.targetSlot}
      </Badge>
      {!rule.isActive && (
        <Badge size="xs" variant="light" color="gray">
          {t('inactive')}
        </Badge>
      )}
      <Switch
        checked={rule.isActive}
        disabled={disabled}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onToggleActive(e.currentTarget.checked)}
      />
    </Group>
  );
}
