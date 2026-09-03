import { useCallback, useMemo, useState } from 'react';
import { Alert, Badge, Button, Group, Stack, Text, Title } from '@mantine/core';
import { IconWand } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router';
import {
  useAutoMap,
  useFieldMapping,
  useRegistryAttributes,
  useSaveFieldMapping,
} from '../../api/hooks';
import { ApiError } from '../../api/client';
import { ErrorState, LoadingState } from '../../components/StateViews';
import { withLoadingNotification, notifyMutationError, notifySuccess } from '../../app/notifications';
import { MappingTable } from './MappingTable';

function parseRowErrors(errors: string[]): Record<string, string> {
  const map: Record<string, string> = {};
  for (const err of errors) {
    const colonIdx = err.indexOf(':');
    if (colonIdx > 0) {
      const source = err.slice(0, colonIdx);
      const message = err.slice(colonIdx + 2);
      map[source] = message;
    }
  }
  return map;
}

function deepEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function MappingTab() {
  const { t: tSetup } = useTranslation('setup');
  const { t: tNotifications } = useTranslation('notifications');
  const { feedSourceId } = useParams<{ feedSourceId: string }>();
  const id = feedSourceId!;

  const mappingQuery = useFieldMapping(id);
  const registryQuery = useRegistryAttributes();
  const saveMutation = useSaveFieldMapping();
  const autoMapMutation = useAutoMap();

  const [localEdits, setLocalEdits] = useState<Record<string, string | null>>({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});

  const effectiveMappings = useMemo(() => {
    const base: Record<string, { target: string | null; origin: string | null }> = {};
    const serverMappings = mappingQuery.data?.mappings ?? {};
    for (const [source, entry] of Object.entries(serverMappings)) {
      base[source] = { target: entry.target, origin: entry.origin };
    }
    for (const [source, target] of Object.entries(localEdits)) {
      if (base[source]) {
        base[source] = { ...base[source], target };
      } else {
        base[source] = { target, origin: 'manual' };
      }
    }
    return base;
  }, [mappingQuery.data, localEdits]);

  const isDirty = useMemo(() => {
    return !deepEqual(localEdits, {});
  }, [localEdits]);

  const coveredTargets = useMemo(() => {
    const targets = new Set<string>();
    for (const entry of Object.values(effectiveMappings)) {
      if (entry.target) {
        const parts = entry.target.split('.');
        targets.add(parts[0]);
        if (parts.length > 1) targets.add(entry.target);
      }
    }
    return targets;
  }, [effectiveMappings]);

  const requiredUncovered = useMemo(() => {
    if (!Array.isArray(registryQuery.data)) return [];
    const baselineAttrs = registryQuery.data.filter((attr) => attr.baseline_required === true);
    const alternativePairs: Array<[string, string]> = [
      ['title', 'structured_title'],
      ['description', 'structured_description'],
    ];
    const uncovered: string[] = [];
    for (const attr of baselineAttrs) {
      const pair = alternativePairs.find(([a, b]) => a === attr.name || b === attr.name);
      if (pair) {
        if (coveredTargets.has(pair[0]) || coveredTargets.has(pair[1])) continue;
        if (uncovered.includes(pair[0])) continue;
        uncovered.push(pair[0], pair[1]);
        continue;
      }
      if (!coveredTargets.has(attr.name)) uncovered.push(attr.name);
    }
    return uncovered;
  }, [registryQuery.data, coveredTargets]);

  const handleTargetChange = useCallback(
    (source: string, target: string | null) => {
      setLocalEdits((prev) => ({ ...prev, [source]: target }));
    },
    [],
  );

  const handleSave = useCallback(async () => {
    const mappingsPayload: Record<string, { target: string }> = {};
    for (const [source, target] of Object.entries(localEdits)) {
      if (target !== null && target !== undefined) {
        mappingsPayload[source] = { target };
      }
    }
    try {
      await saveMutation.mutateAsync({ id, mappings: mappingsPayload });
      setLocalEdits({});
      setRowErrors({});
      notifySuccess(tSetup('mapping.saved'));
    } catch (error) {
      if (error instanceof ApiError && error.errors) {
        setRowErrors(parseRowErrors(error.errors));
      }
      notifyMutationError(error, tSetup('mapping.saveFailed'));
    }
  }, [localEdits, id, saveMutation, tSetup]);

  const handleAutoMap = useCallback(async () => {
    try {
      await withLoadingNotification(
        'auto-map',
        tNotifications('autoMappingRunning'),
        () => autoMapMutation.mutateAsync(id),
        tNotifications('autoMappingDone'),
        tNotifications('autoMappingFailed'),
      );
      setLocalEdits({});
      setRowErrors({});
    } catch {
      // notification handles failure
    }
  }, [autoMapMutation, id, tNotifications]);

  if (mappingQuery.isPending || registryQuery.isPending) return <LoadingState />;
  if (mappingQuery.isError) {
    return <ErrorState message={mappingQuery.error?.message} onRetry={() => void mappingQuery.refetch()} />;
  }
  if (registryQuery.isError) {
    return <ErrorState message={registryQuery.error?.message} onRetry={() => void registryQuery.refetch()} />;
  }

  const sourceFields = mappingQuery.data.source_fields ?? [];

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Group gap="sm">
          <Title order={4}>{tSetup('mapping.title')}</Title>
          {mappingQuery.data.auto_mapped && (
            <Badge color="blue" variant="light">
              {tSetup('mapping.autoMapped')}
            </Badge>
          )}
        </Group>
        <Group gap="sm">
          <Button
            leftSection={<IconWand size={16} />}
            variant="light"
            onClick={() => void handleAutoMap()}
            loading={autoMapMutation.isPending}
          >
            {tSetup('mapping.autoMapper')}
          </Button>
          <Button
            onClick={() => void handleSave()}
            disabled={!isDirty}
            loading={saveMutation.isPending}
          >
            {tSetup('mapping.save')}
          </Button>
        </Group>
      </Group>

      {requiredUncovered.length > 0 && (
        <Alert color="orange" title={tSetup('mapping.requiredUncovered')}>
          {tSetup('mapping.requiredUncoveredList', {
            names: new Intl.ListFormat(undefined, { style: 'long', type: 'conjunction' }).format(requiredUncovered),
          })}
        </Alert>
      )}

      {sourceFields.length === 0 ? (
        <Text c="dimmed" ta="center" py="xl">
          {tSetup('mapping.noSourceFields')}
        </Text>
      ) : (
        <MappingTable
          sourceFields={sourceFields}
          mappings={effectiveMappings}
          registryAttributes={Array.isArray(registryQuery.data) ? registryQuery.data : []}
          onChange={handleTargetChange}
          errors={rowErrors}
        />
      )}
    </Stack>
  );
}
