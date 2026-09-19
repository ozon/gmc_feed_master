import {
  Accordion,
  Badge,
  Button,
  Group,
  MultiSelect,
  SegmentedControl,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { QualityFinding } from '../../../api/types';
import { FindingsTable } from '../FindingsTable';
import {
  FEED_LEVEL_KEY,
  filterFindings,
  groupByAttribute,
  groupByRule,
  type FindingGroup,
} from './groupFindings';
import { RuleLabel } from './RuleLabel';
import { SeverityBadge } from './SeverityBadge';
import { ruleTitle } from './ruleCatalog';
import { SEVERITIES, severityColor } from './severity';

const GROUP_PREVIEW_SIZE = 20;

type GroupMode = 'rule' | 'attribute' | 'flat';

type Props = {
  findings: QualityFinding[];
  onOpenProduct: (productId: string) => void;
};

function groupLabel(key: string, mode: GroupMode, t: TFunction<'monitoring'>): string {
  if (mode === 'rule') return ruleTitle(key, t);
  return key === FEED_LEVEL_KEY ? t('findings.feedLevel') : key;
}

function GroupCounts({ group }: { group: FindingGroup }) {
  const { t } = useTranslation('monitoring');
  return (
    <Group gap="xs">
      {SEVERITIES.filter((severity) => group.counts[severity] > 0).map((severity) => (
        <Badge key={severity} size="sm" variant="light" color={severityColor(severity)}>
          {t(`severity.${severity}`)}: {group.counts[severity]}
        </Badge>
      ))}
    </Group>
  );
}

function GroupRows({
  group,
  onOpenProduct,
}: {
  group: FindingGroup;
  onOpenProduct: (id: string) => void;
}) {
  const { t } = useTranslation('monitoring');
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? group.findings : group.findings.slice(0, GROUP_PREVIEW_SIZE);
  const hidden = group.findings.length - visible.length;

  return (
    <Stack gap="xs">
      <Table striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('columns.severity')}</Table.Th>
            <Table.Th>{t('columns.field')}</Table.Th>
            <Table.Th>{t('columns.message')}</Table.Th>
            <Table.Th>{t('columns.productId')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {visible.map((finding, index) => (
            <Table.Tr
              key={`${finding.product_id}-${finding.field ?? ''}-${index}`}
              data-testid="finding-row"
            >
              <Table.Td>
                <SeverityBadge severity={finding.severity} />
              </Table.Td>
              <Table.Td>{finding.field ?? t('findings.feedLevel')}</Table.Td>
              <Table.Td>{finding.message}</Table.Td>
              <Table.Td>
                {finding.product_id ? (
                  <Button
                    variant="subtle"
                    size="xs"
                    onClick={() => onOpenProduct(finding.product_id)}
                    aria-label={t('findings.openProduct', { id: finding.product_id })}
                  >
                    {finding.product_id}
                  </Button>
                ) : (
                  <Text size="sm" c="dimmed">
                    —
                  </Text>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {hidden > 0 ? (
        <Button variant="subtle" size="xs" onClick={() => setExpanded(true)}>
          {t('findings.showMore', { count: hidden })}
        </Button>
      ) : null}
    </Stack>
  );
}

export function FindingsExplorer({ findings, onOpenProduct }: Props) {
  const { t } = useTranslation('monitoring');
  const [mode, setMode] = useState<GroupMode>('rule');
  const [search, setSearch] = useState('');
  const [severities, setSeverities] = useState<string[]>([]);
  const [rules, setRules] = useState<string[]>([]);

  const codes = useMemo(() => [...new Set(findings.map((finding) => finding.code))], [findings]);
  const filtered = useMemo(
    () => filterFindings(findings, { severities, rules, search }),
    [findings, severities, rules, search],
  );
  const groups = useMemo(
    () => (mode === 'attribute' ? groupByAttribute(filtered) : groupByRule(filtered)),
    [mode, filtered],
  );

  return (
    <Stack gap="md">
      <Group align="flex-end">
        <SegmentedControl
          value={mode}
          onChange={(value) => setMode(value)}
          data={[
            { value: 'rule', label: t('findings.groupRule') },
            { value: 'attribute', label: t('findings.groupAttribute') },
            { value: 'flat', label: t('findings.groupFlat') },
          ]}
          aria-label={t('findings.groupBy')}
        />
        <TextInput
          label={t('findings.search')}
          placeholder={t('findings.searchPlaceholder')}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
        />
        <MultiSelect
          label={t('findings.severityFilter')}
          data={SEVERITIES.map((severity) => ({
            value: severity,
            label: t(`severity.${severity}`),
          }))}
          value={severities}
          onChange={setSeverities}
          placeholder={t('findings.severityPlaceholder')}
          clearable
        />
        {mode !== 'rule' ? (
          <MultiSelect
            label={t('findings.ruleFilter')}
            data={codes.map((code) => ({ value: code, label: ruleTitle(code, t) }))}
            value={rules}
            onChange={setRules}
            placeholder={t('findings.rulePlaceholder')}
            clearable
          />
        ) : null}
      </Group>

      {filtered.length === 0 ? (
        <Text c="dimmed" data-testid="findings-empty">
          {t('findings.empty')}
        </Text>
      ) : mode === 'flat' ? (
        <FindingsTable findings={filtered} onOpenProduct={onOpenProduct} />
      ) : (
        <Accordion multiple variant="separated" data-testid="findings-groups">
          {groups.map((group) => (
            <Accordion.Item key={group.key} value={group.key}>
              <Accordion.Control>
                <Group justify="space-between" wrap="nowrap">
                  <Text fw={500}>
                    {mode === 'rule' ? (
                      <RuleLabel code={group.key} />
                    ) : (
                      groupLabel(group.key, mode, t)
                    )}
                  </Text>
                  <GroupCounts group={group} />
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <GroupRows group={group} onOpenProduct={onOpenProduct} />
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      )}
    </Stack>
  );
}
