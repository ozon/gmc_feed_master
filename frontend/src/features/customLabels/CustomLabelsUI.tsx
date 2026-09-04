import { useMemo, useState } from 'react';
import {
  Badge, Button, Card, Group, Loader, Select, Stack, Switch, Tabs, Text, Textarea, TextInput,
} from '@mantine/core';
import {
  DndContext, PointerSensor, closestCenter, useSensor, useSensors,
} from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { useBlocker } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  usePluginConfig, usePluginData, useRegistryAttributes, useSavePluginConfig,
  useSavePluginData, type PluginScope,
} from '../../api/hooks';
import { notifySuccess } from '../../app/notifications';
import { parseIdList, renderPreview } from './ids';
import { SortableRuleRow } from './SortableRuleRow';

const TARGET_SLOTS = [
  'custom_label_0', 'custom_label_1', 'custom_label_2', 'custom_label_3', 'custom_label_4',
];

type SlotRule = {
  id: string;
  name: string;
  isActive: boolean;
  targetSlot: string;
  matchField: string;
  valueTemplate: string;
  fallbackTemplate: string;
};

function newRule(name: string): SlotRule {
  return {
    id: typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `r_${Math.random().toString(36).slice(2)}`,
    name,
    isActive: true,
    targetSlot: 'custom_label_0',
    matchField: 'id',
    valueTemplate: '',
    fallbackTemplate: '',
  };
}

export function CustomLabelsUI({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  const config = usePluginConfig(pluginId, scope);
  const saveConfig = useSavePluginConfig(pluginId, scope);
  const data = usePluginData(pluginId, scope);
  const saveData = useSavePluginData(pluginId, scope);
  const attributes = useRegistryAttributes();

  const [rules, setRules] = useState<SlotRule[] | null>(null);
  const [slotIds, setSlotIds] = useState<Record<string, string> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const serverRules = (config.data as { slotRules?: SlotRule[] } | undefined)?.slotRules ?? [];
  const serverIds =
    (data.data as { slotIds?: Record<string, string> } | undefined)?.slotIds ?? {};
  const effectiveRules = rules ?? serverRules;
  const effectiveIds = slotIds ?? serverIds;
  const dirtyRules = rules !== null;
  const dirtyIds = slotIds !== null;
  const dirty = dirtyRules || dirtyIds;

  const activeRules = effectiveRules.filter((r) => r.isActive);
  const selected = effectiveRules.find((r) => r.id === selectedId) ?? null;
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const matchSuggestions = useMemo(() => {
    const list: string[] = [];
    for (const attr of attributes.data ?? []) {
      list.push(attr.name);
      for (const sub of attr.sub_fields ?? []) list.push(`${attr.name}.${sub.name}`);
    }
    return list;
  }, [attributes.data]);

  function patchSelected(patch: Partial<SlotRule>) {
    if (!selected) return;
    setRules(effectiveRules.map((r) => (r.id === selected.id ? { ...r, ...patch } : r)));
  }

  useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty) return false;
    if (currentLocation.pathname === nextLocation.pathname) return false;
    return !window.confirm(t('unsavedChanges'));
  });

  async function saveRules() {
    await saveConfig.mutateAsync({ slotRules: effectiveRules });
    setRules(null);
    notifySuccess(t('configSaved'));
  }

  async function saveIds() {
    await saveData.mutateAsync({ slotIds: effectiveIds });
    setSlotIds(null);
    notifySuccess(t('idsSaved'));
  }

  if (config.isPending || data.isPending) return <Loader />;

  return (
    <Tabs defaultValue="ids" keepMounted={false}>
      <Tabs.List>
        <Tabs.Tab value="ids">{t('tabs.bulkIds')}</Tabs.Tab>
        <Tabs.Tab value="rules">{t('tabs.slotRules')}</Tabs.Tab>
      </Tabs.List>

      <Tabs.Panel value="ids" pt="sm">
        <Stack gap="sm">
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setSlotIds(null)} disabled={!dirtyIds}>
              {tCommon('actions.cancel')}
            </Button>
            <Button onClick={() => void saveIds()} loading={saveData.isPending} disabled={!dirtyIds}>
              {tCommon('actions.save')}
            </Button>
          </Group>
          <div data-testid="slot-grid" style={{ overflowX: 'auto' }}>
            <Group gap="md" wrap="nowrap" align="flex-start">
              {activeRules.map((rule) => {
                const raw = effectiveIds[rule.id] ?? '';
                const count = parseIdList(raw).size;
                return (
                  <Stack key={rule.id} gap={4} miw={280} w={280}>
                    <Group gap="xs">
                      <Text size="sm" fw={600}>{rule.name}</Text>
                      <Badge size="xs" variant="light">{rule.targetSlot}</Badge>
                    </Group>
                    <Text size="xs" c="dimmed">{rule.matchField}</Text>
                    <Text size="xs" c="dimmed">{renderPreview(rule.valueTemplate)}</Text>
                    <Textarea
                      aria-label={`${rule.name} ids`}
                      minRows={10}
                      autosize
                      value={raw}
                      onChange={(e) =>
                        setSlotIds({ ...effectiveIds, [rule.id]: e.currentTarget.value })}
                      placeholder={t('idsPlaceholder')}
                    />
                    <Text size="xs" c="dimmed">{t('idCount', { count })}</Text>
                  </Stack>
                );
              })}
              {activeRules.length === 0 && <Text c="dimmed">{t('noActiveRules')}</Text>}
            </Group>
          </div>
        </Stack>
      </Tabs.Panel>

      <Tabs.Panel value="rules" pt="sm">
        <Stack gap="sm">
          <Group justify="space-between">
            <Group>
              <Button variant="default" onClick={() => setRules(null)} disabled={!dirtyRules}>
                {tCommon('actions.cancel')}
              </Button>
              <Button
                onClick={() => void saveRules()}
                loading={saveConfig.isPending}
                disabled={!dirtyRules}
              >
                {tCommon('actions.save')}
              </Button>
            </Group>
            <Button
              variant="light"
              onClick={() => {
                const rule = newRule(t('newRuleName'));
                setRules([...effectiveRules, rule]);
                setSelectedId(rule.id);
              }}
            >
              {t('addRule')}
            </Button>
          </Group>
          <Group align="flex-start" gap="md" wrap="nowrap">
            <Card withBorder miw={320} w={320}>
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={({ active, over }) => {
                  if (!over || active.id === over.id) return;
                  const from = effectiveRules.findIndex((r) => r.id === active.id);
                  const to = effectiveRules.findIndex((r) => r.id === over.id);
                  const next = [...effectiveRules];
                  const [moved] = next.splice(from, 1);
                  next.splice(to, 0, moved);
                  setRules(next);
                }}
              >
                <SortableContext
                  items={effectiveRules.map((r) => r.id)}
                  strategy={verticalListSortingStrategy}
                >
                  <Stack gap={4}>
                    {effectiveRules.map((rule) => (
                      <SortableRuleRow
                        key={rule.id}
                        rule={rule}
                        selected={rule.id === selectedId}
                        onSelect={() => setSelectedId(rule.id)}
                        onToggleActive={(isActive) =>
                          setRules(
                            effectiveRules.map((r) =>
                              r.id === rule.id ? { ...r, isActive } : r,
                            ),
                          )}
                      />
                    ))}
                  </Stack>
                </SortableContext>
              </DndContext>
            </Card>
            {selected && (
              <Card withBorder style={{ flex: 1 }}>
                <Stack gap="sm">
                  <TextInput
                    label={t('fields.name')}
                    value={selected.name}
                    onChange={(e) => patchSelected({ name: e.currentTarget.value })}
                  />
                  <Switch
                    label={t('fields.isActive')}
                    checked={selected.isActive}
                    onChange={(e) => patchSelected({ isActive: e.currentTarget.checked })}
                  />
                  <Select
                    label={t('fields.targetSlot')}
                    data={TARGET_SLOTS}
                    value={selected.targetSlot}
                    onChange={(v) => patchSelected({ targetSlot: v ?? 'custom_label_0' })}
                  />
                  <TextInput
                    label={t('fields.matchField')}
                    value={selected.matchField}
                    onChange={(e) => patchSelected({ matchField: e.currentTarget.value })}
                    list="match-field-suggestions"
                  />
                  <datalist id="match-field-suggestions">
                    {matchSuggestions.map((s) => (
                      <option key={s} value={s} />
                    ))}
                  </datalist>
                  <TextInput
                    label={t('fields.valueTemplate')}
                    description={t('fields.valueTemplateHint')}
                    value={selected.valueTemplate}
                    onChange={(e) => patchSelected({ valueTemplate: e.currentTarget.value })}
                  />
                  <TextInput
                    label={t('fields.fallbackTemplate')}
                    description={t('fields.fallbackHint')}
                    value={selected.fallbackTemplate}
                    onChange={(e) => patchSelected({ fallbackTemplate: e.currentTarget.value })}
                  />
                </Stack>
              </Card>
            )}
          </Group>
        </Stack>
      </Tabs.Panel>
    </Tabs>
  );
}

export default CustomLabelsUI;
