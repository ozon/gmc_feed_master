import { Fragment, useMemo, useState } from 'react';
import {
  Badge, Box, Button, Stack, Table, Text, TextInput, UnstyledButton,
} from '@mantine/core';
import { IconChevronDown, IconChevronRight, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { FieldSelect } from '../../components/FieldSelect';
import {
  buildFieldOptions,
  fromRegistryAttributes,
  CUSTOM_FIELD_NAME_REGEX,
  CUSTOM_FIELD_NAME_MAX_LEN,
} from '../../api/fieldOptions';
import type { RegistryAttribute, SourceField } from '../../api/types';

type MappingTableProps = {
  sourceFields: SourceField[];
  mappings: Record<string, { target: string | null; origin: string | null }>;
  registryAttributes: RegistryAttribute[];
  onChange: (source: string, target: string | null) => void;
  errors: Record<string, string>;
  customFields: string[];
  onAddCustom: (name: string, target: string) => void;
  onRemoveCustom: (name: string) => void;
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

function AddCustomRow({
  targetOptions,
  existingNames,
  onAdd,
}: {
  targetOptions: ReturnType<typeof buildFieldOptions>;
  existingNames: Set<string>;
  onAdd: (name: string, target: string) => void;
}) {
  const { t } = useTranslation('setup');
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');

  const grammarOk = CUSTOM_FIELD_NAME_REGEX.test(name);
  const tooLong = name.length > CUSTOM_FIELD_NAME_MAX_LEN;
  const duplicate = existingNames.has(name);
  const nameError = name === ''
    ? null
    : tooLong || !grammarOk
      ? t('mapping.custom.invalidName')
      : duplicate
        ? t('mapping.custom.duplicateName')
        : null;
  const canAdd = name !== '' && target !== '' && nameError === null;

  return (
    <Table.Tr data-testid="add-custom-row">
      <Table.Td>
        <Stack gap={4}>
          <TextInput
            aria-label={t('mapping.custom.addName')}
            placeholder={t('mapping.custom.addNamePlaceholder')}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            error={nameError}
            size="xs"
            w={220}
            data-testid="custom-name-input"
          />
          <Text size="xs" c="dimmed">{t('mapping.custom.addTargetHint')}</Text>
        </Stack>
      </Table.Td>
      <Table.Td>
        <FieldSelect
          value={target}
          onChange={(val) => setTarget(val)}
          options={targetOptions}
          placeholder={t('mapping.table.selectTarget')}
          clearable
          data-testid="add-custom-target"
        />
      </Table.Td>
      <Table.Td>
        <Button
          size="xs"
          variant="light"
          disabled={!canAdd}
          onClick={() => {
            onAdd(name, target);
            setName('');
            setTarget('');
          }}
          data-testid="add-custom-button"
        >
          {t('mapping.custom.add')}
        </Button>
      </Table.Td>
    </Table.Tr>
  );
}

export function MappingTable({
  sourceFields,
  mappings,
  registryAttributes,
  onChange,
  errors,
  customFields,
  onAddCustom,
  onRemoveCustom,
}: MappingTableProps) {
  const { t } = useTranslation('setup');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const targetOptions = useMemo(
    () => buildFieldOptions(fromRegistryAttributes(registryAttributes)),
    [registryAttributes],
  );
  const observedNames = useMemo(
    () => new Set(sourceFields.map((sf) => sf.name)),
    [sourceFields],
  );
  const existingNames = useMemo(
    () => new Set([...observedNames, ...customFields]),
    [observedNames, customFields],
  );
  const standaloneCustom = customFields.filter((n) => !observedNames.has(n));

  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('mapping.table.source')}</Table.Th>
          <Table.Th>{t('mapping.table.target')}</Table.Th>
          <Table.Th w={70} />
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
          const shadowedCustom = customFields.includes(sf.name);

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
                      {shadowedCustom && (
                        <Badge size="xs" variant="outline" color="violet" data-testid="shadow-indicator">
                          {t('mapping.custom.alsoCustom')}
                        </Badge>
                      )}
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
                <Table.Td>
                  {shadowedCustom && (
                    <UnstyledButton
                      aria-label={t('mapping.custom.remove')}
                      title={t('mapping.custom.remove')}
                      onClick={() => onRemoveCustom(sf.name)}
                      data-testid={`remove-custom-${sf.name}`}
                    >
                      <IconTrash size={16} />
                    </UnstyledButton>
                  )}
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
                      <Table.Td />
                    </Table.Tr>
                  );
                })}
            </Fragment>
          );
        })}
        {standaloneCustom.map((name) => {
          const mapping = mappings[name];
          const error = errors[name] ?? null;
          return (
            <Table.Tr key={`custom-${name}`} data-testid={`custom-row-${name}`}>
              <Table.Td>
                <Stack gap={4}>
                  <Box style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Text size="sm" fw={500}>{name}</Text>
                    <Badge size="xs" variant="light">custom</Badge>
                    <OriginBadge origin={mapping?.origin ?? 'manual'} />
                  </Box>
                  {error && <Text size="xs" c="red">{error}</Text>}
                </Stack>
              </Table.Td>
              <Table.Td>
                <FieldSelect
                  value={mapping?.target ?? ''}
                  onChange={(val) => onChange(name, val || null)}
                  options={targetOptions}
                  placeholder={t('mapping.table.selectTarget')}
                  error={!!error}
                  clearable
                  data-testid={`target-select-${name}`}
                />
              </Table.Td>
              <Table.Td>
                <UnstyledButton
                  aria-label={t('mapping.custom.remove')}
                  title={t('mapping.custom.remove')}
                  onClick={() => onRemoveCustom(name)}
                  data-testid={`remove-custom-${name}`}
                >
                  <IconTrash size={16} />
                </UnstyledButton>
              </Table.Td>
            </Table.Tr>
          );
        })}
        <AddCustomRow
          targetOptions={targetOptions}
          existingNames={existingNames}
          onAdd={onAddCustom}
        />
      </Table.Tbody>
    </Table>
  );
}
