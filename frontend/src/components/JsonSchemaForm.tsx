import {
  ActionIcon,
  Button,
  Group,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

export type JsonSchema = {
  type?: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array';
  title?: string;
  description?: string;
  enum?: string[];
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
  required?: string[];
};

export type JsonSchemaFormProps = {
  schema: JsonSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  errors?: Record<string, string>;
  path?: string;
};

function joinPath(path: string | undefined, key: string): string {
  return path ? `${path}.${key}` : key;
}

export function JsonSchemaForm({ schema, value, onChange, errors = {}, path }: JsonSchemaFormProps) {
  const { t } = useTranslation();
  const error = path ? errors[path] : undefined;
  const label = schema.title ?? path?.split('.').pop();

  if (schema.type === 'object') {
    const record = (value ?? {}) as Record<string, unknown>;
    return (
      <Stack gap="sm">
        {Object.entries(schema.properties ?? {}).map(([key, propertySchema]) => (
          <JsonSchemaForm
            key={key}
            schema={propertySchema}
            value={record[key]}
            onChange={(next) => onChange({ ...record, [key]: next })}
            errors={errors}
            path={joinPath(path, key)}
          />
        ))}
      </Stack>
    );
  }

  if (schema.type === 'array') {
    const items = Array.isArray(value) ? value : [];
    return (
      <Stack gap="xs">
        {label ? <Text size="sm">{label}</Text> : null}
        {items.map((item, index) => (
          <Group key={index} gap="xs" wrap="nowrap" align="flex-start">
            <div style={{ flex: 1 }}>
              <JsonSchemaForm
                schema={schema.items ?? {}}
                value={item}
                onChange={(next) =>
                  onChange(items.map((existing, i) => (i === index ? next : existing)))
                }
                errors={errors}
                path={joinPath(path, String(index))}
              />
            </div>
            <ActionIcon
              variant="subtle"
              color="red"
              aria-label={t('actions.remove')}
              onClick={() => onChange(items.filter((_, i) => i !== index))}
            >
              <IconTrash size={16} />
            </ActionIcon>
          </Group>
        ))}
        <Button
          variant="light"
          size="xs"
          leftSection={<IconPlus size={14} />}
          onClick={() => onChange([...items, undefined])}
        >
          {t('actions.add')}
        </Button>
      </Stack>
    );
  }

  if (schema.enum) {
    return (
      <Select
        label={label}
        description={schema.description}
        data={schema.enum}
        value={(value as string | undefined) ?? null}
        onChange={(next) => onChange(next)}
        error={error}
      />
    );
  }

  switch (schema.type) {
    case 'number':
    case 'integer':
      return (
        <NumberInput
          label={label}
          description={schema.description}
          value={typeof value === 'number' ? value : ''}
          onChange={(next) => onChange(next === '' ? undefined : Number(next))}
          error={error}
        />
      );
    case 'boolean':
      return (
        <Switch
          label={label}
          description={schema.description}
          checked={value === true}
          onChange={(event) => onChange(event.currentTarget.checked)}
          error={error}
        />
      );
    default:
      return (
        <TextInput
          label={label}
          description={schema.description}
          value={(value as string | undefined) ?? ''}
          onChange={(event) => onChange(event.currentTarget.value)}
          error={error}
        />
      );
  }
}
