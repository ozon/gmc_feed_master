import { Button, Grid, Group, Stack, Text } from '@mantine/core';
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useBlocker } from 'react-router';
import { useFeedSourceFields, usePluginConfig, useSavePluginConfig, type PluginScope } from '../../api/hooks';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import {
  enforcePinning,
  newRule,
  normalizeConfig,
  rulesEqual,
  sortRulesPinned,
  type Rule,
  type RulesConfig,
} from '../../../../plugins/core/rules/frontend/ast';
import { RuleList } from './RuleList';
import { RuleEditor } from './RuleEditor';
import { applyDragEnd } from './dndUtils';

export type RulesUIProps = { pluginId: string; scope: PluginScope };

export default function RulesUI({ pluginId, scope }: RulesUIProps) {
  const { t } = useTranslation('rules');
  const { t: tCommon } = useTranslation('common');
  const config = usePluginConfig(pluginId, scope);
  const saveConfig = useSavePluginConfig(pluginId, scope);
  const fieldsQuery = useFeedSourceFields(String(scope.feedSourceId ?? ''));
  const fields = useMemo(() => fieldsQuery.data?.fields ?? [], [fieldsQuery.data]);

  const [rules, setRules] = useState<Rule[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchValue, setSearchValue] = useState('');

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const lastConfigRef = useRef<unknown>(null);
  useEffect(() => {
    if (config.data !== undefined && config.data !== lastConfigRef.current) {
      lastConfigRef.current = config.data;
      setRules(normalizeConfig(config.data).rules);
    }
  }, [config.data]);

  const serverRules = useMemo(
    () => (config.data ? sortRulesPinned(normalizeConfig(config.data).rules) : []),
    [config.data],
  );
  const localRules = useMemo(() => sortRulesPinned(rules), [rules]);
  const dirty = !rulesEqual({ rules: localRules }, { rules: serverRules });

  useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty) return false;
    if (currentLocation.pathname === nextLocation.pathname) return false;
    return !window.confirm(t('unsavedChanges'));
  });

  const selected = rules.find((r) => r.id === selectedId) ?? null;

  function patchRule(id: string, patch: Partial<Rule>) {
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }

  function createRule() {
    const rule = newRule('');
    setRules((prev) => [...prev, rule]);
    setSelectedId(rule.id);
  }

  function confirmDeleteRule(rule: Rule) {
    if (!window.confirm(t('actions.deleteRuleBody', { name: rule.name }))) return;
    setRules((prev) => prev.filter((r) => r.id !== rule.id));
    if (selectedId === rule.id) setSelectedId(null);
  }

  function confirmDeleteSelected() {
    const count = selectedIds.size;
    if (count === 0) return;
    if (!window.confirm(t('actions.deleteSelectedBody', { count }))) return;
    setRules((prev) => prev.filter((r) => !selectedIds.has(r.id)));
    if (selectedId && selectedIds.has(selectedId)) setSelectedId(null);
    setSelectedIds(new Set());
  }

  async function onSave() {
    const payload: RulesConfig = {
      rules: localRules.map(({ id, name, isMasterRule, isActive, when, then }) => ({
        id,
        name,
        isMasterRule,
        isActive,
        when,
        then,
      })),
    };
    try {
      await saveConfig.mutateAsync(payload);
      notifySuccess(t('saved'));
    } catch (error) {
      notifyApiError(error, t('saveFailed'));
    }
  }

  function onReset() {
    setRules(normalizeConfig(config.data ?? {}).rules);
  }

  function onDragEnd(event: DragEndEvent) {
    const next = applyDragEnd(rules, event);
    if (next) setRules(next);
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text fw={500} size="lg">
          {t('title')}
        </Text>
        <Group>
          <Button variant="default" onClick={onReset} disabled={!dirty}>
            {tCommon('actions.cancel')}
          </Button>
          <Button onClick={() => void onSave()} loading={saveConfig.isPending} disabled={!dirty}>
            {tCommon('actions.save')}
          </Button>
        </Group>
      </Group>
      <Grid>
        <Grid.Col span={5}>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={localRules.map((r) => r.id)} strategy={verticalListSortingStrategy}>
              <RuleList
            rules={localRules}
            selectedId={selectedId}
            selectedIds={selectedIds}
            searchOpen={searchOpen}
            searchValue={searchValue}
            onToggleSearch={() => {
              setSearchOpen((v) => !v);
              if (searchOpen) setSearchValue('');
            }}
            onSearchChange={setSearchValue}
            onSelect={(id) => setSelectedId(id)}
            onToggleSelected={(id, checked) =>
              setSelectedIds((prev) => {
                const next = new Set(prev);
                if (checked) next.add(id);
                else next.delete(id);
                return next;
              })
            }
            onToggleSelectAll={(checked) =>
              setSelectedIds(checked ? new Set(localRules.map((r) => r.id)) : new Set())
            }
            onCreate={createRule}
            onEdit={(id) => setSelectedId(id)}
            onRename={(id) => setSelectedId(id)}
            onDuplicate={(id) =>
              setRules((prev) => {
                const source = prev.find((r) => r.id === id);
                if (!source) return prev;
                const copy = { ...source, id: newRule('').id, name: `${source.name} ${t('duplicateSuffix')}` };
                return enforcePinning([...prev, copy]);
              })
            }
            onToggleActive={(id) =>
              setRules((prev) =>
                prev.map((r) => (r.id === id ? { ...r, isActive: !r.isActive } : r)),
              )
            }
            onToggleMaster={(id) =>
              setRules((prev) =>
                enforcePinning(
                  prev.map((r) => (r.id === id ? { ...r, isMasterRule: !r.isMasterRule } : r)),
                ),
              )
            }
            onDelete={(id) => {
              const rule = rules.find((r) => r.id === id);
              if (rule) confirmDeleteRule(rule);
            }}
            onBulkActivate={(active) =>
              setRules((prev) =>
                prev.map((r) => (selectedIds.has(r.id) ? { ...r, isActive: active } : r)),
              )
            }
            onBulkDelete={confirmDeleteSelected}
              />
            </SortableContext>
          </DndContext>
        </Grid.Col>
        <Grid.Col span={7}>
          <RuleEditor
            rule={selected}
            fields={fields}
            onPatch={(patch) => {
              if (selected) patchRule(selected.id, patch);
            }}
            onPatchWhen={(when) => {
              if (selected) patchRule(selected.id, { when });
            }}
            onPatchThen={(then) => {
              if (selected) patchRule(selected.id, { then });
            }}
            onToggleMaster={() => {
              if (!selected) return;
              setRules((prev) =>
                enforcePinning(
                  prev.map((r) => (r.id === selected.id ? { ...r, isMasterRule: !r.isMasterRule } : r)),
                ),
              );
            }}
            onToggleActive={() => {
              if (selected) patchRule(selected.id, { isActive: !selected.isActive });
            }}
            onDelete={() => {
              if (selected) confirmDeleteRule(selected);
            }}
            onRename={() => {
              if (selected) setSelectedId(selected.id);
            }}
          />
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
