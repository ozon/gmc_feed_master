import { Fragment, useMemo, useState } from 'react';
import { Badge, Box, Stack, Table, Text, UnstyledButton } from '@mantine/core';
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { FieldSelect } from '../../components/FieldSelect';
import { buildFieldOptions, fromRegistryAttributes } from '../../api/fieldOptions';
import type { RegistryAttribute, SourceField } from '../../api/types';

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
  const targetOptions = useMemo(
    () => buildFieldOptions(fromRegistryAttributes(registryAttributes)),
    [registryAttributes],
  );

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
                  <FieldSelect
                    value={targetValue ?? ''}
                    onChange={(val) => onChange(sf.name, val || null)}
                    options={targetOptions}
                    placeholder={t('mapping.table.selectTarget')}
                    error={!!error}
                    clearable
                    data-testid={`target-select-${sf.name}`}
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
                        <FieldSelect
                          value={subMapping?.target ?? ''}
                          onChange={(val) => onChange(subKey, val || null)}
                          options={targetOptions}
                          placeholder={t('mapping.table.selectTarget')}
                          error={!!subError}
                          clearable
                          data-testid={`target-select-${subKey}`}
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
