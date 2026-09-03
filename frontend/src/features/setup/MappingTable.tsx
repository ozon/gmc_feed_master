import { Fragment, useState } from 'react';
import { Badge, Box, Select, Stack, Table, Text, UnstyledButton } from '@mantine/core';
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { RegistryAttribute, SourceField } from '../../api/types';

type SelectOption = { value: string; label: string; group: string };

function buildTargetOptions(registryAttributes: RegistryAttribute[]): SelectOption[] {
  const options: SelectOption[] = [];
  for (const attr of registryAttributes) {
    const isStructured = attr.kind === 'structured' || attr.kind === 'repeated_structured';
    if (isStructured) {
      for (const sub of attr.sub_fields) {
        options.push({ value: `${attr.name}.${sub.name}`, label: `${attr.name}.${sub.name}`, group: attr.name });
      }
    } else {
      options.push({ value: attr.name, label: attr.name, group: attr.name });
    }
  }
  return options;
}

type MappingTableProps = {
  sourceFields: SourceField[];
  mappings: Record<string, { target: string | null; origin: string | null }>;
  registryAttributes: RegistryAttribute[];
  onChange: (source: string, target: string | null) => void;
  errors: Record<string, string>;
};

const originLabels: Record<string, string> = {
  auto: 'mapping.origins.auto',
  synonym: 'mapping.origins.synonym',
  manual: 'mapping.origins.manual',
};

const STRUCTURED_KINDS = new Set(['structured', 'repeated_structured']);

function isExpandable(sf: SourceField): boolean {
  return STRUCTURED_KINDS.has(sf.kind) && sf.sub_fields.length > 0;
}

function subFieldKind(parentKind: string): string {
  return parentKind === 'repeated_structured' ? 'repeated_scalar' : 'scalar';
}

function OriginBadge({ origin }: { origin: string | null }) {
  const { t } = useTranslation('setup');
  if (!origin) return null;
  return (
    <Badge
      size="xs"
      variant="outline"
      color={origin === 'auto' ? 'blue' : origin === 'synonym' ? 'yellow' : 'gray'}
    >
      {originLabels[origin] ? t(originLabels[origin] as 'mapping.origins.auto') : origin}
    </Badge>
  );
}

export function MappingTable({
  sourceFields,
  mappings,
  registryAttributes,
  onChange,
  errors,
}: MappingTableProps) {
  const { t } = useTranslation('setup');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const targetOptions = buildTargetOptions(registryAttributes);

  const grouped = new Map<string, SelectOption[]>();
  for (const opt of targetOptions) {
    const list = grouped.get(opt.group) ?? [];
    list.push(opt);
    grouped.set(opt.group, list);
  }

  const mantineData = Array.from(grouped.entries()).map(([group, items]) => ({
    group,
    items: items.map(({ value, label }) => ({ value, label })),
  }));

  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('mapping.table.source')}</Table.Th>
          <Table.Th>{t('mapping.table.target')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {sourceFields.map((sf) => {
          const mapping = mappings[sf.name];
          const origin = mapping?.origin ?? null;
          const targetValue = mapping?.target ?? null;
          const error = errors[sf.name] ?? null;
          const expandable = isExpandable(sf);
          const isOpen = expanded[sf.name] ?? false;

          return (
            <Fragment key={sf.name}>
              <Table.Tr>
                <Table.Td>
                  <Stack gap={4}>
                    <Box style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {expandable && (
                        <UnstyledButton
                          data-sub-toggle={sf.name}
                          aria-expanded={isOpen}
                          aria-label={t(
                            isOpen ? 'mapping.table.collapseSubFields' : 'mapping.table.expandSubFields',
                            { field: sf.name },
                          )}
                          onClick={() =>
                            setExpanded((prev) => ({ ...prev, [sf.name]: !prev[sf.name] }))
                          }
                        >
                          {isOpen ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
                        </UnstyledButton>
                      )}
                      <Text size="sm" fw={500}>
                        {sf.name}
                      </Text>
                      <Badge size="xs" variant="light">
                        {sf.kind}
                      </Badge>
                      <OriginBadge origin={origin} />
                    </Box>
                    {error && <Text size="xs" c="red">{error}</Text>}
                  </Stack>
                </Table.Td>
                <Table.Td>
                  <Select
                    data={mantineData}
                    value={targetValue}
                    onChange={(val) => onChange(sf.name, val)}
                    clearable
                    searchable
                    placeholder={t('mapping.table.selectTarget')}
                    size="sm"
                    error={!!error}
                  />
                </Table.Td>
              </Table.Tr>
              {expandable
                && isOpen
                && sf.sub_fields.map((sub) => {
                  const subKey = `${sf.name}.${sub}`;
                  const subMapping = mappings[subKey];
                  const subError = errors[subKey] ?? null;
                  return (
                    <Table.Tr key={subKey}>
                      <Table.Td>
                        <Stack gap={4}>
                          <Box style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 32 }}>
                            <Text size="sm" fw={500}>
                              {sub}
                            </Text>
                            <Badge size="xs" variant="light">
                              {subFieldKind(sf.kind)}
                            </Badge>
                            <OriginBadge origin={subMapping?.origin ?? null} />
                          </Box>
                          {subError && <Text size="xs" c="red">{subError}</Text>}
                        </Stack>
                      </Table.Td>
                      <Table.Td>
                        <Select
                          data={mantineData}
                          value={subMapping?.target ?? null}
                          onChange={(val) => onChange(subKey, val)}
                          clearable
                          searchable
                          placeholder={t('mapping.table.selectTarget')}
                          size="sm"
                          error={!!subError}
                        />
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
            </Fragment>
          );
        })}
      </Table.Tbody>
    </Table>
  );
}
