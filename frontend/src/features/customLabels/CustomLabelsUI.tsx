import { useMemo, useState } from 'react';
import {
  Badge, Button, Card, Group, Loader, Select, Stack, Switch, Tabs, Text, Textarea, TextInput,
} from '@mantine/core';
import {
  DndContext, PointerSensor, closestCenter, useSensor, useSensors,
} from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { useBlocker, useParams } from 'react-router';
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

// Manifest-declared scopes (plugins/core/custom_labels/plugin.json):
// config_scope: ["global", "client"] — slot templates are structural/shared.
// data_scope: ["client", "feed_source"] — ID lists are operational, per-market.
// The URL tier (most-specific) is used when declared for the payload kind;
// otherwise the component falls back to the most-specific declared tier
// reachable from the route context and marks the tab read-only/hidden.
const CONFIG_SCOPES = ['global', 'client'] as const;
const DATA_SCOPES = ['client', 'feed_source'] as const;

function tierOf(scope: PluginScope | undefined): 'global' | 'client' | 'feed_source' {
  if (!scope) return 'global';
  if (scope.feedSourceId !== undefined) return 'feed_source';
  if (scope.clientId !== undefined) return 'client';
  return 'global';
}

function tierValue(scope: PluginScope | undefined): number | undefined {
  return scope?.feedSourceId ?? scope?.clientId;
}

/**
 * Resolve the scope object for one payload kind (config/data) from the URL
 * scope. Falls back to a declared ancestor tier when the URL tier isn't
 * declared for that kind (e.g. feed-source URL + config: use client tier).
 * Returns undefined when no declared tier is reachable (e.g. global URL +
 * data): the request must not be sent.
 */
export function resolveKindScope(
  kindScopes: readonly string[],
  urlScope: PluginScope | undefined,
  routeContext: { clientId?: string; feedSourceId?: string },
): { scope?: PluginScope; fallback: boolean } {
  const urlTier = tierOf(urlScope);
  if (kindScopes.includes(urlTier)) {
    // Global tier is represented by the empty scope object ({}), never
    // undefined — undefined disables the query entirely.
    return { scope: urlTier === 'global' ? {} : urlScope, fallback: false };
  }
  // Fall back toward the most-specific declared tier reachable from the URL.
  if (urlTier === 'feed_source') {
    if (kindScopes.includes('client') && routeContext.clientId) {
      return { scope: { clientId: Number(routeContext.clientId) }, fallback: true };
    }
    if (kindScopes.includes('global')) return { scope: {}, fallback: true };
  }
  if (urlTier === 'client' && kindScopes.includes('global')) {
    return { scope: {}, fallback: true };
  }
  if (urlTier === 'global' && kindScopes.includes('client') && routeContext.clientId) {
    return { scope: { clientId: Number(routeContext.clientId) }, fallback: true };
  }
  return { scope: undefined, fallback: true };
}

export function CustomLabelsUI({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  const routeContext = useParams();

  const configResolved = resolveKindScope(CONFIG_SCOPES, scope, routeContext);
  const dataResolved = resolveKindScope(DATA_SCOPES, scope, routeContext);
  const configScope = configResolved.scope;
  const dataScope = dataResolved.scope;
  const rulesReadOnly = configResolved.fallback;
  const idsUnavailable = dataScope === undefined;

  const config = usePluginConfig(pluginId, configScope, configScope !== undefined);
  const saveConfig = useSavePluginConfig(pluginId, configScope);
  const data = usePluginData(pluginId, dataScope, dataScope !== undefined);
  const saveData = useSavePluginData(pluginId, dataScope);
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

  if (config.isPending || (dataScope !== undefined && data.isPending)) return <Loader />;
  // When the bulk-IDs payload has no reachable scope (global URL), default to
  // the slot-rules tab instead of a disabled bulk-IDs tab.
  const initialTab = idsUnavailable ? 'rules' : 'ids';

  return (
    <Tabs defaultValue={initialTab} keepMounted={false}>
      <Tabs.List>
        <Tabs.Tab value="ids" disabled={idsUnavailable}>{t('tabs.bulkIds')}</Tabs.Tab>
        <Tabs.Tab value="rules">{t('tabs.slotRules')}</Tabs.Tab>
      </Tabs.List>

      <Tabs.Panel value="ids" pt="sm">
        {idsUnavailable ? (
          <Text c="dimmed">{t('idsUnavailable')}</Text>
        ) : (
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
        )}
      </Tabs.Panel>

      <Tabs.Panel value="rules" pt="sm">
        <Stack gap="sm">
          {rulesReadOnly && (
            <Text data-testid="rules-readonly-hint" size="sm" c="dimmed">
              {t('rulesReadOnly')}
            </Text>
          )}
          <Group justify="space-between">
            {!rulesReadOnly && (
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
            )}
            {!rulesReadOnly && (
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
            )}
          </Group>
          <Group align="flex-start" gap="md" wrap="nowrap">
            <Card withBorder miw={320} w={320}>
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={({ active, over }) => {
                  if (rulesReadOnly) return;
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
                        disabled={rulesReadOnly}
                        onSelect={() => setSelectedId(rule.id)}
                        onToggleActive={(isActive) =>
                          setRules(
                            effectiveRules.map((r) =>
                              r.id === rule.id ? { ...r, isActive } : r,
                            ),
                          )
                        }
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
                    disabled={rulesReadOnly}
                    onChange={(e) => patchSelected({ name: e.currentTarget.value })}
                  />
                  <Switch
                    label={t('fields.isActive')}
                    checked={selected.isActive}
                    disabled={rulesReadOnly}
                    onChange={(e) => patchSelected({ isActive: e.currentTarget.checked })}
                  />
                  <Select
                    label={t('fields.targetSlot')}
                    data={TARGET_SLOTS}
                    value={selected.targetSlot}
                    disabled={rulesReadOnly}
                    onChange={(v) => patchSelected({ targetSlot: v ?? 'custom_label_0' })}
                  />
                  <TextInput
                    label={t('fields.matchField')}
                    value={selected.matchField}
                    disabled={rulesReadOnly}
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
                    disabled={rulesReadOnly}
                    onChange={(e) => patchSelected({ valueTemplate: e.currentTarget.value })}
                  />
                  <TextInput
                    label={t('fields.fallbackTemplate')}
                    description={t('fields.fallbackHint')}
                    value={selected.fallbackTemplate}
                    disabled={rulesReadOnly}
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
