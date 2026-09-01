import { ActionIcon, Badge, Group, Radio, Table, Text } from '@mantine/core';
import { IconArrowBackUp } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import type { ExportVersionOut } from '../../api/types';

type Props = {
  versions: ExportVersionOut[];
  versionA: number | undefined;
  versionB: number | undefined;
  onSelectA: (v: number) => void;
  onSelectB: (v: number) => void;
  onRollback: (v: number) => void;
};

const SOURCE_COLOR: Record<string, string> = {
  run: 'blue',
  rollback: 'orange',
};

export function ExportVersionList({
  versions,
  versionA,
  versionB,
  onSelectA,
  onSelectB,
  onRollback,
}: Props) {
  const { t, i18n } = useTranslation('export');
  return (
    <Table data-testid="export-version-list" striped>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('columns.version')}</Table.Th>
          <Table.Th>{t('columns.createdAt')}</Table.Th>
          <Table.Th>{t('columns.source')}</Table.Th>
          <Table.Th>{t('columns.products')}</Table.Th>
          <Table.Th>{t('columns.findings')}</Table.Th>
          <Table.Th>{t('columns.diffA')}</Table.Th>
          <Table.Th>{t('columns.diffB')}</Table.Th>
          <Table.Th>{t('columns.rollback')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {versions.map((version) => (
          <Table.Tr key={version.version_number} data-testid={`version-row-${version.version_number}`}>
            <Table.Td>
              <Group gap="xs">
                <Text fw={500}>#{version.version_number}</Text>
                {version.source === 'rollback' ? (
                  <Badge color="gray" variant="light" data-testid="not-qcd-badge">
                    {t('notQcd')}
                  </Badge>
                ) : null}
              </Group>
            </Table.Td>
            <Table.Td>
              <Text size="sm">
                {dayjs(version.created_at).locale(i18n.language).format('L LTS')}
              </Text>
            </Table.Td>
            <Table.Td>
              <Badge color={SOURCE_COLOR[version.source] ?? 'gray'} variant="light">
                {t(`source.${version.source}` as 'source.run' | 'source.rollback')}
              </Badge>
            </Table.Td>
            <Table.Td>
              <Badge variant="light" color="gray">
                {new Intl.NumberFormat(i18n.language).format(version.product_count)} {t('productsLabel')}
              </Badge>
            </Table.Td>
            <Table.Td>
              {version.source !== 'rollback' && version.findings != null ? (
                <Group gap={4} wrap="nowrap">
                  <Badge
                    size="xs"
                    variant="light"
                    color={version.findings.critical ? 'red' : 'gray'}
                    title={t('findings.critical', { count: version.findings.critical })}
                    aria-label={t('findings.critical', { count: version.findings.critical })}
                    data-testid={`findings-critical-${version.version_number}`}
                  >
                    {version.findings.critical}
                  </Badge>
                  <Badge
                    size="xs"
                    variant="light"
                    color={version.findings.warning ? 'yellow' : 'gray'}
                    title={t('findings.warning', { count: version.findings.warning })}
                    aria-label={t('findings.warning', { count: version.findings.warning })}
                    data-testid={`findings-warning-${version.version_number}`}
                  >
                    {version.findings.warning}
                  </Badge>
                  <Badge
                    size="xs"
                    variant="light"
                    color={version.findings.info ? 'blue' : 'gray'}
                    title={t('findings.info', { count: version.findings.info })}
                    aria-label={t('findings.info', { count: version.findings.info })}
                    data-testid={`findings-info-${version.version_number}`}
                  >
                    {version.findings.info}
                  </Badge>
                </Group>
              ) : null}
            </Table.Td>
            <Table.Td>
              <Radio
                name="diffA"
                checked={versionA === version.version_number}
                onChange={() => onSelectA(version.version_number)}
                aria-label={`${t('columns.diffA')} ${version.version_number}`}
              />
            </Table.Td>
            <Table.Td>
              <Radio
                name="diffB"
                checked={versionB === version.version_number}
                onChange={() => onSelectB(version.version_number)}
                aria-label={`${t('columns.diffB')} ${version.version_number}`}
              />
            </Table.Td>
            <Table.Td>
              <ActionIcon
                variant="subtle"
                onClick={() => onRollback(version.version_number)}
                aria-label={`${t('rollbackToVersion')} ${version.version_number}`}
                data-testid={`rollback-${version.version_number}`}
              >
                <IconArrowBackUp size={16} />
              </ActionIcon>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
