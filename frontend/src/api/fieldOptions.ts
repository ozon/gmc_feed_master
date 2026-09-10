import type { RegistryAttribute, SourceField } from './types';

export type FieldSubFieldDescriptor = { name: string; kind?: string };

export type FieldDescriptor = {
  name: string;
  kind: string;
  sub_fields: FieldSubFieldDescriptor[];
  max_repeats: number;
};

export type FieldOption = { value: string; label: string };

export type GroupedFieldOptions = { group: string; items: FieldOption[] }[];

/** Canonical indexed-path grammar (1-based indices) — mirrors the backend
 * parse_indexed_path; validates free-text input (operator directive 4). */
export const INDEXED_PATH_REGEX =
  /^[a-z_][a-z0-9_]*(\.([1-9]\d*))?(\.[a-z_][a-z0-9_]*)?$/;

export const FIELD_GROUP_LABEL = 'Field';

export function fromSourceFields(fields: SourceField[]): FieldDescriptor[] {
  return fields.map((f) => ({
    name: f.name,
    kind: f.kind,
    sub_fields: f.sub_fields.map((name) => ({ name })),
    max_repeats: f.max_repeats,
  }));
}

export function fromRegistryAttributes(attrs: RegistryAttribute[]): FieldDescriptor[] {
  return attrs.map((a) => ({
    name: a.name,
    kind: a.kind,
    sub_fields: a.sub_fields.map((s) => ({ name: s.name, kind: s.kind })),
    max_repeats: a.max_repeats,
  }));
}

/**
 * Build grouped, indexed options from unified descriptors.
 *
 * - scalar -> group "Field"; structured -> group attr: parent + attr.sub
 * - repeated_scalar -> group attr: parent + attr.i (#i)
 * - repeated_structured -> group attr: parent + attr.i.sub (#i · sub)
 * - max_repeats 0 -> no children (free text still allows typed indices)
 * - a literal dotted field name (scalar, never expanded) wins over a
 *   same-valued generated path (collision rule)
 */
export function buildFieldOptions(
  fields: FieldDescriptor[],
  opts?: { includeParent?: boolean },
): GroupedFieldOptions {
  const includeParent = opts?.includeParent ?? true;
  const literalNames = new Set(fields.filter((f) => f.name.includes('.')).map((f) => f.name));
  const groups = new Map<string, FieldOption[]>();

  const push = (group: string, option: FieldOption) => {
    if (
      group !== FIELD_GROUP_LABEL
      && !literalNames.has(group)
      && option.value.includes('.')
      && literalNames.has(option.value)
    ) {
      return; // generated path collides with a literal field name — literal wins
    }
    const list = groups.get(group) ?? [];
    if (!list.some((o) => o.value === option.value)) {
      list.push(option);
    }
    groups.set(group, list);
  };

  for (const field of fields) {
    const isScalar = field.kind === 'scalar';
    if (isScalar) {
      push(FIELD_GROUP_LABEL, { value: field.name, label: field.name });
      continue;
    }
    if (includeParent) {
      push(field.name, { value: field.name, label: field.name });
    }
    if (field.kind === 'structured') {
      for (const sub of field.sub_fields) {
        push(field.name, { value: `${field.name}.${sub.name}`, label: sub.name });
      }
      continue;
    }
    const max = Math.max(0, field.max_repeats);
    for (let i = 1; i <= max; i++) {
      if (field.kind === 'repeated_scalar') {
        push(field.name, { value: `${field.name}.${i}`, label: `#${i}` });
      } else {
        for (const sub of field.sub_fields) {
          push(field.name, {
            value: `${field.name}.${i}.${sub.name}`,
            label: `#${i} · ${sub.name}`,
          });
        }
      }
    }
  }

  return Array.from(groups.entries()).map(([group, items]) => ({ group, items }));
}
