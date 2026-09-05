import { useMemo, useState } from 'react';
import {
  Anchor, Badge, Button, Card, Group, SegmentedControl, Select, Stack, Switch, Tabs, Text, TextInput, Textarea,
} from '@mantine/core';
import {
  DndContext, PointerSensor, closestCenter, useSensor, useSensors,
} from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { Link, useBlocker, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  usePluginConfig, usePluginData, useRegistryAttributes, useSavePluginConfig,
  useSavePluginData, type PluginScope,
} from '../../api/hooks';
import { ErrorState, LoadingState } from '../../components/StateViews';
import { ScopeBadge } from '../../components/ScopeBadge';
import { ScopeContextBar } from '../../components/ScopeContextBar';
import { notifySuccess } from '../../app/notifications';
import { parseIdList, renderPreview } from './ids';
import { SortableRuleRow } from './SortableRuleRow';
import { MatchFieldCombobox } from './MatchFieldCombobox';
import {
  configTierChain, currentDataTier, dataTierChain, editableConfigTier,
  mergeSlotIds, mergeSlotRules, type ScopedSlotRule, type SlotRule, type Tier,
} from './scopeMerge';

const TARGET_SLOTS = [
  'custom_label_0', 'custom_label_1', 'custom_label_2', 'custom_label_3', 'custom_label_4',
];

function newRule(name: string, origin: Tier): ScopedSlotRule {
  return {
    id: typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `r_${Math.random().toString(36).slice(2)}`,
    name,
    isActive: true,
    targetSlot: 'custom_label_0',
    matchField: 'id',
    matchMode: 'values',
    valueTemplate: '',
    fallbackTemplate: '',
    origin,
  };
}

function slotRulesOf(payload: unknown): SlotRule[] {
  return (payload as { slotRules?: SlotRule[] } | undefined)?.slotRules ?? [];
}

function slotIdsOf(payload: unknown): Record<string, string> {
  return (payload as { slotIds?: Record<string, string> } | undefined)?.slotIds ?? {};
}

export function CustomLabelsUI({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  const routeContext = useParams();

  const editableTier = editableConfigTier(scope);
  const rulesReadOnly = editableTier === null;
  const configChain = configTierChain(scope, routeContext);
  const dataChain = dataTierChain(scope, routeContext);
  const viewingTier: Tier = scope.feedSourceId !== undefined
    ? 'feed_source'
    : scope.clientId !== undefined
      ? 'client'
      : 'global';

  const clientConfigScope = configChain.find((c) => c.tier === 'client')?.scope;
  const clientDataScope = dataChain.find((c) => c.tier === 'client')?.scope;
  const feedDataScope = dataChain.find((c) => c.tier === 'feed_source')?.scope;
  const saveConfigScope: PluginScope = editableTier === 'client'
    ? { clientId: scope.clientId! }
    : {};
  const saveDataScope = feedDataScope ?? clientDataScope;

  const globalConfig = usePluginConfig(pluginId, {});
  const clientConfig = usePluginConfig(pluginId, clientConfigScope, clientConfigScope !== undefined);
  const clientData = usePluginData(pluginId, clientDataScope, clientDataScope !== undefined);
  const feedData = usePluginData(pluginId, feedDataScope, feedDataScope !== undefined);
  const saveConfig = useSavePluginConfig(pluginId, saveConfigScope);
  const saveData = useSavePluginData(pluginId, saveDataScope);
  const attributes = useRegistryAttributes();

  const [rules, setRules] = useState<ScopedSlotRule[] | null>(null);
  const [slotIds, setSlotIds] = useState<Record<string, string> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const serverRules = useMemo(
    () =>
      mergeSlotRules(
        configChain.map(({ tier }) => ({
          tier,
          rules: tier === 'global' ? slotRulesOf(globalConfig.data) : slotRulesOf(clientConfig.data),
        })),
      ),
    [configChain, globalConfig.data, clientConfig.data],
  );
  const serverIds = useMemo(
    () =>
      mergeSlotIds(
        dataChain.map(({ tier }) => ({
          tier,
          ids: tier === 'client' ? slotIdsOf(clientData.data) : slotIdsOf(feedData.data),
        })),
      ),
    [dataChain, clientData.data, feedData.data],
  );

  const effectiveRules = rules ?? serverRules;
  const effectiveIds = slotIds
    ?? Object.fromEntries(Object.entries(serverIds).map(([id, v]) => [id, v.value]));
  const dirtyRules = rules !== null;
  const dirtyIds = slotIds !== null;
  const dirty = dirtyRules || dirtyIds;

  const activeRules = effectiveRules.filter((r) => r.isActive);
  const selected = effectiveRules.find((r) => r.id === selectedId) ?? null;
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

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
    if (editableTier === null) return;
    const payloadRules = effectiveRules
      .filter((r) => r.origin === editableTier)
      .map(({ origin: _origin, ...rest }) => rest);
    await saveConfig.mutateAsync({ slotRules: payloadRules });
    setRules(null);
    notifySuccess(t('configSaved'));
  }

  async function saveIds() {
    if (saveDataScope === undefined) return;
    await saveData.mutateAsync({ slotIds: effectiveIds });
    setSlotIds(null);
    notifySuccess(t('idsSaved'));
  }

  const configPending = globalConfig.isPending
    || (clientConfigScope !== undefined && clientConfig.isPending);
  const dataPending = dataChain.length > 0
    && ((clientDataScope !== undefined && clientData.isPending)
      || (feedDataScope !== undefined && feedData.isPending));
  if (configPending || dataPending) return <LoadingState />;
  const anyError = globalConfig.isError
    || (clientConfigScope !== undefined && clientConfig.isError)
    || (clientDataScope !== undefined && clientData.isError)
    || (feedDataScope !== undefined && feedData.isError);
  if (anyError) {
    return (
      <ErrorState
        onRetry={() => {
          void globalConfig.refetch();
          if (clientConfigScope !== undefined) void clientConfig.refetch();
          if (clientDataScope !== undefined) void clientData.refetch();
          if (feedDataScope !== undefined) void feedData.refetch();
        }}
      />
    );
  }

  const idsUnavailable = dataChain.length === 0;
  const initialTab = idsUnavailable ? 'rules' : 'ids';
  const ruleEditable = (rule: ScopedSlotRule) => !rulesReadOnly && rule.origin === editableTier;

  return (
    <Stack gap="sm">
      <ScopeContextBar
        current={viewingTier}
        configTiers={configChain.map((c) => c.tier)}
        dataTiers={dataChain.map((c) => c.tier)}
        configLabel={t('tabs.slotRules')}
        dataLabel={t('tabs.bulkIds')}
      />
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
                    const inherited = serverIds[rule.id]?.inherited === true
                      && raw === serverIds[rule.id].value;
                    return (
                      <Stack key={rule.id} gap={4} miw={280} w={280}>
                        <Group gap="xs">
                          <Text size="sm" fw={600}>{rule.name}</Text>
                          <Badge size="xs" variant="light">{rule.targetSlot}</Badge>
                        </Group>
                        <Group gap={4}>
                          <Text size="xs" c="dimmed">{rule.matchField}</Text>
                          {inherited && (
                            <Badge size="xs" variant="light" color="teal">
                              {t('inheritedFrom', { tier: tCommon('scope.client') })}
                            </Badge>
                          )}
                        </Group>
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
                {t('rulesReadOnly')}{' '}
                {routeContext.clientId && (
                  <Anchor
                    component={Link}
                    to={`/clients/${routeContext.clientId}/plugins/${pluginId}`}
                  >
                    {t('manageAtClient')}
                  </Anchor>
                )}
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
                    const rule = newRule(t('newRuleName'), editableTier!);
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
                          disabled={!ruleEditable(rule)}
                          badge={rule.origin !== editableTier
                            ? <ScopeBadge tier={rule.origin} />
                            : undefined}
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
                    {!ruleEditable(selected) && (
                      <Group gap="xs">
                        <ScopeBadge tier={selected.origin} />
                        <Text size="xs" c="dimmed">
                          {t('ruleInherited', { tier: tCommon(`scope.${selected.origin}`) })}
                        </Text>
                      </Group>
                    )}
                    <TextInput
                      label={t('fields.name')}
                      value={selected.name}
                      disabled={!ruleEditable(selected)}
                      onChange={(e) => patchSelected({ name: e.currentTarget.value })}
                    />
                    <Switch
                      label={t('fields.isActive')}
                      description={t('fields.isActiveHint')}
                      checked={selected.isActive}
                      disabled={!ruleEditable(selected)}
                      onChange={(e) => patchSelected({ isActive: e.currentTarget.checked })}
                    />
                    <Select
                      label={t('fields.targetSlot')}
                      data={TARGET_SLOTS}
                      value={selected.targetSlot}
                      disabled={!ruleEditable(selected)}
                      onChange={(v) => patchSelected({ targetSlot: v ?? 'custom_label_0' })}
                    />
                    <SegmentedControl
                      aria-label={t('matchMode.label')}
                      value={selected.matchMode ?? 'values'}
                      onChange={(mode) => patchSelected({ matchMode: mode as 'values' | 'all' })}
                      disabled={!ruleEditable(selected)}
                      data={[
                        { value: 'values', label: t('matchMode.values') },
                        { value: 'all', label: t('matchMode.all') },
                      ]}
                    />
                    <MatchFieldCombobox
                      value={selected.matchField}
                      onChange={(matchField) => patchSelected({ matchField })}
                      attributes={attributes.data ?? []}
                      disabled={!ruleEditable(selected)}
                    />
                    <TextInput
                      label={t('fields.valueTemplate')}
                      description={t('fields.valueTemplateHint')}
                      value={selected.valueTemplate}
                      disabled={!ruleEditable(selected)}
                      onChange={(e) => patchSelected({ valueTemplate: e.currentTarget.value })}
                    />
                    <TextInput
                      label={t('fields.fallbackTemplate')}
                      description={t('fields.fallbackHint')}
                      value={selected.fallbackTemplate}
                      disabled={!ruleEditable(selected)}
                      onChange={(e) => patchSelected({ fallbackTemplate: e.currentTarget.value })}
                    />
                  </Stack>
                </Card>
              )}
            </Group>
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

export default CustomLabelsUI;
