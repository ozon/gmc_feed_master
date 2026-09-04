import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Group,
  Menu,
  Stack,
  Text,
  TextInput,
  UnstyledButton,
} from '@mantine/core';
import {
  IconDotsVertical,
  IconGripVertical,
  IconPlus,
  IconSearch,
  IconX,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { Rule } from '../../../../plugins/core/rules/frontend/ast';

export type RuleListProps = {
  rules: Rule[];
  selectedId: string | null;
  selectedIds: Set<string>;
  searchOpen: boolean;
  searchValue: string;
  onToggleSearch: () => void;
  onSearchChange: (value: string) => void;
  onSelect: (id: string) => void;
  onToggleSelected: (id: string, checked: boolean) => void;
  onToggleSelectAll: (checked: boolean) => void;
  onCreate: () => void;
  onEdit: (id: string) => void;
  onRename: (id: string) => void;
  onDuplicate: (id: string) => void;
  onToggleActive: (id: string) => void;
  onToggleMaster: (id: string) => void;
  onDelete: (id: string) => void;
  onBulkActivate: (active: boolean) => void;
  onBulkDelete: () => void;
};

export function RuleList(props: RuleListProps) {
  const { t } = useTranslation('rules');
  const {
    rules,
    selectedId,
    selectedIds,
    searchOpen,
    searchValue,
    onToggleSearch,
    onSearchChange,
    onSelect,
    onToggleSelected,
    onToggleSelectAll,
    onCreate,
    onEdit,
    onRename,
    onDuplicate,
    onToggleActive,
    onToggleMaster,
    onDelete,
    onBulkActivate,
    onBulkDelete,
  } = props;

  const filtered = searchValue
    ? rules.filter((r) => r.name.toLowerCase().includes(searchValue.toLowerCase()))
    : rules;
  const allSelected = filtered.length > 0 && filtered.every((r) => selectedIds.has(r.id));

  return (
    <Stack gap="sm" data-testid="rules-list">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm" fw={500}>
          {t('title')}
        </Text>
        <Group gap={4} wrap="nowrap">
          {searchOpen ? (
            <TextInput
              size="xs"
              placeholder={t('searchPlaceholder')}
              value={searchValue}
              onChange={(e) => onSearchChange(e.currentTarget.value)}
              data-testid="rules-search"
              rightSection={
                <ActionIcon
                  size="xs"
                  variant="transparent"
                  aria-label={t('search')}
                  onClick={onToggleSearch}
                >
                  <IconX size={12} />
                </ActionIcon>
              }
            />
          ) : (
            <ActionIcon variant="default" size="sm" aria-label={t('search')} onClick={onToggleSearch}>
              <IconSearch size={14} />
            </ActionIcon>
          )}
          <Button size="xs" variant="default" leftSection={<IconPlus size={14} />} onClick={onCreate}>
            {t('createRule')}
          </Button>
        </Group>
      </Group>
      <Group gap="xs" wrap="nowrap">
        <Checkbox
          aria-label={t('select-all')}
          checked={allSelected}
          indeterminate={selectedIds.size > 0 && !allSelected}
          onChange={(e) => onToggleSelectAll(e.currentTarget.checked)}
          data-testid="select-all"
        />
        {selectedIds.size > 0 ? (
          <Group gap={4}>
            <BulkButton onClick={() => onBulkActivate(true)}>{t('actions.activateSelected')}</BulkButton>
            <BulkButton onClick={() => onBulkActivate(false)}>
              {t('actions.deactivateSelected')}
            </BulkButton>
            <BulkButton onClick={onBulkDelete}>{t('actions.deleteSelectedTitle')}</BulkButton>
          </Group>
        ) : null}
      </Group>
      <Stack gap={6}>
        {filtered.length === 0 ? (
          <Text size="sm" c="dimmed" data-testid="rules-list-empty">
            {searchValue ? t('list.noResults') : t('list.empty')}
          </Text>
        ) : null}
        {filtered.map((rule) => (
          <RuleRow
            key={rule.id}
            rule={rule}
            selected={rule.id === selectedId}
            checked={selectedIds.has(rule.id)}
            onSelect={() => onSelect(rule.id)}
            onToggleChecked={(checked) => onToggleSelected(rule.id, checked)}
            onEdit={() => onEdit(rule.id)}
            onRename={() => onRename(rule.id)}
            onDuplicate={() => onDuplicate(rule.id)}
            onToggleActive={() => onToggleActive(rule.id)}
            onToggleMaster={() => onToggleMaster(rule.id)}
            onDelete={() => onDelete(rule.id)}
          />
        ))}
      </Stack>
    </Stack>
  );
}

function BulkButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <Button
      size="compact-xs"
      variant="default"
      onClick={onClick}
      style={{ cursor: 'pointer', background: 'transparent' }}
    >
      {children}
    </Button>
  );
}

function RuleRow({
  rule,
  selected,
  checked,
  onSelect,
  onToggleChecked,
  onEdit,
  onRename,
  onDuplicate,
  onToggleActive,
  onToggleMaster,
  onDelete,
}: {
  rule: Rule;
  selected: boolean;
  checked: boolean;
  onSelect: () => void;
  onToggleChecked: (checked: boolean) => void;
  onEdit: () => void;
  onRename: () => void;
  onDuplicate: () => void;
  onToggleActive: () => void;
  onToggleMaster: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation('rules');
  return (
    <Group
      wrap="nowrap"
      gap="xs"
      px="sm"
      py={6}
      component={UnstyledButton}
      onClick={onSelect}
      data-testid={`rule-row-${rule.id}`}
      style={{
        borderRadius: 'var(--mantine-radius-sm)',
        width: '100%',
        textAlign: 'left',
        background: selected ? 'var(--mantine-color-blue-light)' : undefined,
      }}
    >
      <IconGripVertical
        size={16}
        style={{ color: 'var(--mantine-color-dimmed-text)', flexShrink: 0 }}
        aria-hidden
      />
      <Checkbox
        aria-label={rule.name}
        checked={checked}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onToggleChecked(e.currentTarget.checked)}
        style={{ flexShrink: 0 }}
      />
      <Text size="sm" truncate style={{ flex: 1 }}>
        {rule.name}
      </Text>
      {!rule.isActive ? (
        <Badge size="xs" variant="light" color="gray">
          {t('editor.inactive')}
        </Badge>
      ) : null}
      {rule.isMasterRule ? (
        <Badge size="xs" variant="filled" color="orange" data-testid={`master-badge-${rule.id}`}>
          {t('list.master')}
        </Badge>
      ) : null}
      <Menu shadow="md" width={180} withinPortal position="bottom-end">
        <Menu.Target>
          <ActionIcon
            variant="subtle"
            aria-label={`${rule.name} menu`}
            onClick={(e) => e.stopPropagation()}
          >
            <IconDotsVertical size={14} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown onClick={(e) => e.stopPropagation()}>
          <Menu.Item onClick={onEdit}>{t('actions.edit')}</Menu.Item>
          <Menu.Item onClick={onRename}>{t('actions.rename')}</Menu.Item>
          <Menu.Item onClick={onDuplicate}>{t('actions.duplicate')}</Menu.Item>
          <Menu.Item onClick={onToggleActive}>{t('actions.toggleActive')}</Menu.Item>
          <Menu.Item onClick={onToggleMaster}>{t('actions.toggleMaster')}</Menu.Item>
          <Menu.Item color="red" onClick={onDelete}>
            {t('actions.delete')}
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
}
