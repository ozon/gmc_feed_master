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

const SOURCE_COLOR: Record<ExportVersionOut['source'], string> = {
  scheduled: 'blue',
  manual: 'teal',
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
          <Table.Th>{t('columns.findings')}</Table.Th>
          <Table.Th>{t('columns.diffA')}</Table.Th>
          <Table.Th>{t('columns.diffB')}</Table.Th>
          <Table.Th>{t('columns.rollback')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {versions.map((version) => (
          <Table.Tr key={version.version} data-testid={`version-row-${version.version}`}>
            <Table.Td>
              <Group gap="xs">
                <Text fw={500}>#{version.version}</Text>
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
              <Badge color={SOURCE_COLOR[version.source]} variant="light">
                {t(`source.${version.source}`)}
              </Badge>
            </Table.Td>
            <Table.Td>
              <Group gap={4}>
                <Badge size="sm" color={version.findings.critical > 0 ? 'red' : 'gray'} variant="light">
                  C {new Intl.NumberFormat(i18n.language).format(version.findings.critical)}
                </Badge>
                <Badge size="sm" color={version.findings.warning > 0 ? 'yellow' : 'gray'} variant="light">
                  W {new Intl.NumberFormat(i18n.language).format(version.findings.warning)}
                </Badge>
                <Badge size="sm" color={version.findings.info > 0 ? 'blue' : 'gray'} variant="light">
                  I {new Intl.NumberFormat(i18n.language).format(version.findings.info)}
                </Badge>
              </Group>
            </Table.Td>
            <Table.Td>
              <Radio
                name="diffA"
                checked={versionA === version.version}
                onChange={() => onSelectA(version.version)}
                aria-label={`${t('columns.diffA')} ${version.version}`}
              />
            </Table.Td>
            <Table.Td>
              <Radio
                name="diffB"
                checked={versionB === version.version}
                onChange={() => onSelectB(version.version)}
                aria-label={`${t('columns.diffB')} ${version.version}`}
              />
            </Table.Td>
            <Table.Td>
              <ActionIcon
                variant="subtle"
                onClick={() => onRollback(version.version)}
                aria-label={`${t('rollbackToVersion')} ${version.version}`}
                data-testid={`rollback-${version.version}`}
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