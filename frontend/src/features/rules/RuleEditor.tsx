import {
  ActionIcon,
  Badge,
  Group,
  Menu,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { IconCopy, IconPlus, IconSettings, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import {
  CONDITION_NUMERIC_OPS,
  CONDITION_TEXT_OPS,
  type Rule,
  type RuleAction,
  type RuleCondition,
} from '../../../../plugins/core/rules/frontend/ast';

const TEXT_OPS: readonly string[] = ['exists', 'empty', ...CONDITION_TEXT_OPS];
const NUMERIC_OPS: readonly string[] = CONDITION_NUMERIC_OPS;
const LEAF_OPS: readonly string[] = [...TEXT_OPS, ...NUMERIC_OPS];
const GROUP_OPS: readonly string[] = ['and', 'or'];
const ALL_CONDITION_OPS: readonly string[] = [...GROUP_OPS, ...LEAF_OPS];
const ACTION_OPS: readonly string[] = ['set', 'replace', 'append', 'prepend', 'remove', 'clear'];

export type RuleEditorProps = {
  rule: Rule | null;
  fields: string[];
  onPatch: (patch: Partial<Rule>) => void;
  onPatchWhen: (when: RuleCondition) => void;
  onPatchThen: (then: RuleAction[]) => void;
  onToggleMaster: () => void;
  onToggleActive: () => void;
  onDelete: () => void;
  onRename: () => void;
};

type Option = { value: string; label: string };

const OP_KEY_PREFIX = 'ops.';
const OP_KEYS = [
  'ops.all',
  'ops.and',
  'ops.or',
  'ops.equals',
  'ops.contains',
  'ops.starts_with',
  'ops.ends_with',
  'ops.regex',
  'ops.exists',
  'ops.empty',
  'ops.gt',
  'ops.lt',
  'ops.gte',
  'ops.lte',
  'ops.between',
  'ops.set',
  'ops.replace',
  'ops.append',
  'ops.prepend',
  'ops.remove',
  'ops.clear',
] as const;
type OpKey = (typeof OP_KEYS)[number];

function opKey(op: string): OpKey {
  const key = `${OP_KEY_PREFIX}${op}` as OpKey;
  return key;
}

function opOptions(t: TFunction<'rules'>, ops: readonly string[]): Option[] {
  return ops.map((op) => ({
    value: op,
    label: t(opKey(op)),
  }));
}

export function RuleEditor({
  rule,
  fields,
  onPatch,
  onPatchWhen,
  onPatchThen,
  onToggleMaster,
  onToggleActive,
  onDelete,
  onRename,
}: RuleEditorProps) {
  const { t } = useTranslation('rules');
  if (!rule) {
    return (
      <Stack data-testid="rule-editor" mih={200} justify="center" align="center">
        <Text c="dimmed">{t('editor.noSelection')}</Text>
      </Stack>
    );
  }

  const fieldData: Option[] = fields.map((f) => ({ value: f, label: f }));
  const when = rule.when;

  return (
    <Stack gap="md" data-testid="rule-editor">
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" wrap="nowrap" style={{ flex: 1 }}>
          <TextInput
            aria-label={t('editor.name')}
            placeholder={t('editor.name')}
            value={rule.name}
            onChange={(e) => onPatch({ name: e.currentTarget.value })}
            data-testid="rule-name-input"
            style={{ flex: 1 }}
          />
          {rule.isMasterRule ? (
            <Badge variant="filled" color="orange">
              {t('list.master')}
            </Badge>
          ) : null}
        </Group>
        <Menu shadow="md" width={180}>
          <Menu.Target>
            <ActionIcon variant="default" aria-label={t('editor.settings')}>
              <IconSettings size={14} />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={onRename}>{t('actions.rename')}</Menu.Item>
            <Menu.Item onClick={onToggleMaster}>{t('actions.toggleMaster')}</Menu.Item>
            <Menu.Item onClick={onToggleActive}>{t('actions.toggleActive')}</Menu.Item>
            <Menu.Item color="red" onClick={onDelete}>
              {t('actions.delete')}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>

      {/* IF block */}
      <Stack gap="xs">
        <Text size="sm" fw={500}>
          {t('editor.if')}
        </Text>
        <Group gap="xs" wrap="nowrap" align="flex-start">
          <Select
            aria-label={t('editor.conditionType')}
            data={[
              { value: 'all', label: t('ops.all') },
              { value: 'where', label: t('editor.where') },
            ]}
            value={when.op === 'all' ? 'all' : 'where'}
            onChange={(v) => {
              if (v === 'all') onPatchWhen({ op: 'all' });
              else onPatchWhen({ op: 'equals', field: fields[0] ?? '', arg: '' });
            }}
            data-testid="condition-type"
            w={180}
          />
          {when.op !== 'all' ? (
            <ConditionNodeEditor node={when} fields={fieldData} onChange={onPatchWhen} t={t} />
          ) : null}
        </Group>
      </Stack>

      {/* THEN block */}
      <Stack gap="xs">
        <Text size="sm" fw={500}>
          {t('editor.then')}
        </Text>
        {rule.then.map((action, index) => (
          <Group key={index} gap="xs" wrap="nowrap" align="flex-start" data-testid={`then-row-${index}`}>
            <Text size="sm" c="dimmed">
              {t('editor.take')}
            </Text>
            <Select
              aria-label={t('editor.addField')}
              data={fieldData}
              value={action.field || null}
              onChange={(v) => {
                const next = [...rule.then];
                next[index] = { ...action, field: v ?? '' };
                onPatchThen(next);
              }}
              searchable
              data-testid={`then-field-${index}`}
              w={160}
            />
            <Text size="sm" c="dimmed">
              {t('editor.and')}
            </Text>
            <Select
              aria-label={t('editor.operation')}
              data={opOptions(t, ACTION_OPS)}
              value={action.op}
              onChange={(v) => {
                const next = [...rule.then];
                next[index] = { ...action, op: (v ?? 'set') as RuleAction['op'] };
                onPatchThen(next);
              }}
              data-testid={`then-op-${index}`}
              w={180}
            />
            {action.op === 'replace' ? (
              <>
                <TextInput
                  aria-label={t('fields.find')}
                  placeholder={t('fields.find')}
                  value={action.find ?? ''}
                  onChange={(e) => {
                    const next = [...rule.then];
                    next[index] = { ...action, find: e.currentTarget.value };
                    onPatchThen(next);
                  }}
                  data-testid={`then-find-${index}`}
                  w={120}
                />
                <TextInput
                  aria-label={t('fields.with')}
                  placeholder={t('fields.with')}
                  value={action.with ?? ''}
                  onChange={(e) => {
                    const next = [...rule.then];
                    next[index] = { ...action, with: e.currentTarget.value };
                    onPatchThen(next);
                  }}
                  data-testid={`then-with-${index}`}
                  w={120}
                />
                <Switch
                  aria-label={t('fields.caseSensitive')}
                  label={t('fields.caseSensitive')}
                  checked={action.caseSensitive !== false}
                  onChange={(e) => {
                    const next = [...rule.then];
                    next[index] = { ...action, caseSensitive: e.currentTarget.checked };
                    onPatchThen(next);
                  }}
                />
              </>
            ) : action.op === 'set' || action.op === 'append' || action.op === 'prepend' ? (
              <TextInput
                aria-label={t('fields.value')}
                placeholder={t('fields.value')}
                value={action.value ?? ''}
                onChange={(e) => {
                  const next = [...rule.then];
                  next[index] = { ...action, value: e.currentTarget.value };
                  onPatchThen(next);
                }}
                data-testid={`then-value-${index}`}
                w={160}
              />
            ) : null}
            <Group gap={2} wrap="nowrap">
              <ActionIcon
                variant="subtle"
                color="red"
                aria-label={t('actions.deleteAction')}
                onClick={() => onPatchThen(rule.then.filter((_, i) => i !== index))}
              >
                <IconTrash size={14} />
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                aria-label={t('actions.cloneAction')}
                onClick={() => {
                  const next = [...rule.then];
                  next.splice(index + 1, 0, { ...action });
                  onPatchThen(next);
                }}
              >
                <IconCopy size={14} />
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                aria-label={t('actions.addAction')}
                onClick={() => {
                  const next = [...rule.then];
                  next.splice(index + 1, 0, { op: 'set', field: '', value: '' });
                  onPatchThen(next);
                }}
                data-testid={`then-add-${index}`}
              >
                <IconPlus size={14} />
              </ActionIcon>
            </Group>
          </Group>
        ))}
      </Stack>
    </Stack>
  );
}

function ConditionNodeEditor({
  node,
  fields,
  onChange,
  t,
}: {
  node: RuleCondition;
  fields: Option[];
  onChange: (node: RuleCondition) => void;
  t: TFunction<'rules'>;
}) {
  if (node.op === 'and' || node.op === 'or') {
    const children = node.children ?? [];
    const patchChild = (index: number, child: RuleCondition) => {
      const next = [...children];
      next[index] = child;
      onChange({ ...node, children: next });
    };
    return (
      <Stack gap={4}>
        {children.map((child, index) => (
          <Group key={index} gap="xs" wrap="nowrap" align="flex-start">
            {index > 0 ? (
              <Select
                aria-label={t('editor.conditionType')}
                data={opOptions(t, GROUP_OPS)}
                value={node.op}
                onChange={(v) => {
                  if (v === 'and' || v === 'or') onChange({ ...node, op: v });
                }}
                w={110}
              />
            ) : null}
            <ConditionNodeEditor
              node={child}
              fields={fields}
              onChange={(nextChild) => patchChild(index, nextChild)}
              t={t}
            />
            <Group gap={2} wrap="nowrap">
              <ActionIcon
                variant="subtle"
                color="red"
                aria-label={t('actions.deleteSection')}
                onClick={() =>
                  onChange({ ...node, children: children.filter((_, i) => i !== index) })
                }
              >
                <IconTrash size={14} />
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                aria-label={t('actions.cloneSection')}
                onClick={() => {
                  const next = [...children];
                  next.splice(index + 1, 0, { ...child });
                  onChange({ ...node, children: next });
                }}
              >
                <IconCopy size={14} />
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                aria-label={t('actions.addSection')}
                onClick={() => {
                  const next = [...children];
                  next.splice(index + 1, 0, { op: 'equals', field: fields[0]?.value ?? '', arg: '' });
                  onChange({ ...node, children: next });
                }}
              >
                <IconPlus size={14} />
              </ActionIcon>
            </Group>
          </Group>
        ))}
        <Select
          aria-label={t('editor.addSection')}
          data={opOptions(t, GROUP_OPS)}
          value={node.op}
          onChange={(v) => {
            if (v === 'and' || v === 'or') onChange({ ...node, op: v });
          }}
          w={110}
        />
      </Stack>
    );
  }

  // Leaf: [Field Select][Operator Select][Value Input]
  const isNumeric = (NUMERIC_OPS as readonly string[]).includes(node.op);
  const isBetween = node.op === 'between';
  const hasValueInput = !(node.op === 'exists' || node.op === 'empty');
  const patch = (partial: Partial<RuleCondition>) => onChange({ ...node, ...partial });

  return (
    <Group gap="xs" wrap="nowrap" align="flex-end">
      <Select
        aria-label={t('editor.addField')}
        data={fields}
        value={node.field ?? null}
        onChange={(v) => patch({ field: v ?? '' })}
        searchable
        w={160}
      />
      <Select
        aria-label={t('editor.operation')}
        data={opOptions(t, [...TEXT_OPS, ...NUMERIC_OPS])}
        value={TEXT_OPS.includes(node.op) || NUMERIC_OPS.includes(node.op) ? node.op : null}
        onChange={(v) => {
          if (!v) return;
          if ((NUMERIC_OPS as readonly string[]).includes(v)) patch({ op: v as RuleCondition['op'], arg: 0 });
          else patch({ op: v as RuleCondition['op'], arg: '' });
        }}
        w={160}
      />
      {hasValueInput && isNumeric ? (
        isBetween ? (
          <>
            <NumberInput
              aria-label={t('fields.min')}
              value={typeof node.arg === 'number' ? node.arg : 0}
              onChange={(value) => patch({ arg: typeof value === 'number' ? value : 0 })}
              w={110}
            />
            <NumberInput
              aria-label={t('fields.max')}
              value={typeof node.arg2 === 'number' ? node.arg2 : 0}
              onChange={(value) => patch({ arg2: typeof value === 'number' ? value : 0 })}
              w={110}
            />
          </>
        ) : (
          <NumberInput
            aria-label={t('fields.value')}
            value={typeof node.arg === 'number' ? node.arg : 0}
            onChange={(value) => patch({ arg: typeof value === 'number' ? value : 0 })}
            w={110}
          />
        )
      ) : hasValueInput ? (
        <TextInput
          aria-label={t('fields.value')}
          value={typeof node.arg === 'string' ? node.arg : ''}
          onChange={(e) => patch({ arg: e.currentTarget.value })}
          w={140}
        />
      ) : null}
    </Group>
  );
}
