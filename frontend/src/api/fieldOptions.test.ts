import { describe, expect, it } from 'vitest';
import {
  CUSTOM_FIELD_NAME_MAX_LEN, CUSTOM_FIELD_NAME_REGEX,
  INDEXED_PATH_REGEX, buildFieldOptions, fromRegistryAttributes,
  fromSourceFields, type FieldDescriptor,
} from './fieldOptions';
import type { RegistryAttribute, SourceField } from './types';

const scalar: FieldDescriptor = { name: 'title', kind: 'scalar', sub_fields: [], max_repeats: 0 };
const structured: FieldDescriptor = {
  name: 'installment', kind: 'structured',
  sub_fields: [{ name: 'months', kind: 'scalar' }, { name: 'amount', kind: 'scalar' }],
  max_repeats: 0,
};
const repeatedScalar: FieldDescriptor = {
  name: 'additional_image_link', kind: 'repeated_scalar', sub_fields: [], max_repeats: 3,
};
const repeatedStructured: FieldDescriptor = {
  name: 'product_detail', kind: 'repeated_structured',
  sub_fields: [
    { name: 'section_name', kind: 'repeated_scalar' },
    { name: 'attribute_name', kind: 'repeated_scalar' },
    { name: 'attribute_value', kind: 'repeated_scalar' },
  ],
  max_repeats: 2,
};

describe('buildFieldOptions', () => {
  it('puts scalars under the "Field" group', () => {
    expect(buildFieldOptions([scalar])).toEqual([
      { group: 'Field', items: [{ value: 'title', label: 'title' }] },
    ]);
  });

  it('expands structured attributes into sub items', () => {
    expect(buildFieldOptions([structured])).toEqual([
      {
        group: 'installment',
        items: [
          { value: 'installment', label: 'installment' },
          { value: 'installment.months', label: 'months' },
          { value: 'installment.amount', label: 'amount' },
        ],
      },
    ]);
  });

  it('expands repeated_scalar into #i indexed items up to max_repeats', () => {
    expect(buildFieldOptions([repeatedScalar])).toEqual([
      {
        group: 'additional_image_link',
        items: [
          { value: 'additional_image_link', label: 'additional_image_link' },
          { value: 'additional_image_link.1', label: '#1' },
          { value: 'additional_image_link.2', label: '#2' },
          { value: 'additional_image_link.3', label: '#3' },
        ],
      },
    ]);
  });

  it('expands repeated_structured into #i · sub items', () => {
    const groups = buildFieldOptions([repeatedStructured]);
    expect(groups[0].items).toEqual([
      { value: 'product_detail', label: 'product_detail' },
      { value: 'product_detail.1.section_name', label: '#1 · section_name' },
      { value: 'product_detail.1.attribute_name', label: '#1 · attribute_name' },
      { value: 'product_detail.1.attribute_value', label: '#1 · attribute_value' },
      { value: 'product_detail.2.section_name', label: '#2 · section_name' },
      { value: 'product_detail.2.attribute_name', label: '#2 · attribute_name' },
      { value: 'product_detail.2.attribute_value', label: '#2 · attribute_value' },
    ]);
  });

  it('emits no children when max_repeats is 0', () => {
    const groups = buildFieldOptions([{ ...repeatedScalar, max_repeats: 0 }]);
    expect(groups[0].items).toEqual([
      { value: 'additional_image_link', label: 'additional_image_link' },
    ]);
  });

  it('includeParent: false drops the parent option', () => {
    const groups = buildFieldOptions([repeatedScalar], { includeParent: false });
    expect(groups[0].items.every((i) => i.value !== 'additional_image_link')).toBe(true);
  });

  it('literal dotted field name wins over generated path (collision)', () => {
    const dotted: FieldDescriptor = {
      name: 'a.b', kind: 'scalar', sub_fields: [], max_repeats: 0,
    };
    const parent: FieldDescriptor = {
      name: 'a', kind: 'structured', sub_fields: [{ name: 'b' }], max_repeats: 0,
    };
    const groups = buildFieldOptions([dotted, parent]);
    const fieldGroup = groups.find((g) => g.group === 'Field')!;
    expect(fieldGroup.items).toContainEqual({ value: 'a.b', label: 'a.b' });
    const aGroup = groups.find((g) => g.group === 'a')!;
    expect(aGroup.items.map((i) => i.value)).not.toContain('a.b');
  });
});

describe('adapters', () => {
  it('fromSourceFields maps SourceField to FieldDescriptor', () => {
    const sf: SourceField = {
      name: 'shipping', kind: 'repeated_structured',
      sub_fields: ['country', 'price'], max_repeats: 3,
    };
    expect(fromSourceFields([sf])).toEqual([{
      name: 'shipping', kind: 'repeated_structured',
      sub_fields: [{ name: 'country' }, { name: 'price' }], max_repeats: 3,
    }]);
  });

  it('fromRegistryAttributes maps RegistryAttribute to FieldDescriptor', () => {
    const attr: RegistryAttribute = {
      name: 'product_detail', kind: 'repeated_structured',
      required: 'optional',
      sub_fields: [
        { name: 'section_name', type: 'String', required: 'optional', kind: 'repeated_scalar' },
      ],
      enum_values: [], max_repeats: 2,
    };
    expect(fromRegistryAttributes([attr])).toEqual([{
      name: 'product_detail', kind: 'repeated_structured',
      sub_fields: [{ name: 'section_name', kind: 'repeated_scalar' }],
      max_repeats: 2,
    }]);
  });
});

describe('INDEXED_PATH_REGEX (directive 4)', () => {
  const valid = [
    'title', 'shipping.price', 'additional_image_link.1',
    'additional_image_link.12', 'product_detail.2.attribute_value',
    'a_1.b_2', 'product_detail.7.section_name',
    'additional_image_link.10000', 'product_detail.10000.section_name',
  ];
  const invalid = [
    'product_detail.0.attribute_name', 'product_detail.0',
    '.title', 'title.', '', 'a..b',
    'Product_Detail', 'product_detail.-1.section_name', 'a.b.c.d',
    'additional_image_link.10001', 'product_detail.10001.section_name',
    'additional_image_link.999999999',
  ];
  it.each(valid.map((v) => [v]))('accepts %s', (path) => {
    expect(INDEXED_PATH_REGEX.test(path)).toBe(true);
  });
  it.each(invalid.map((v) => [v]))('rejects %s', (path) => {
    expect(INDEXED_PATH_REGEX.test(path)).toBe(false);
  });
});

describe('CUSTOM_FIELD_NAME_REGEX', () => {
  it.each(['my_field', 'a', 'field2', 'a_b_9'])('accepts %s', (name) => {
    expect(CUSTOM_FIELD_NAME_REGEX.test(name)).toBe(true);
  });
  it.each([
    'has.dot',
    'Has-Upper',
    '1starts_digit',
    '',
    ' spaced ',
    'ünïcode',
  ])('rejects %s', (name) => {
    expect(CUSTOM_FIELD_NAME_REGEX.test(name)).toBe(false);
  });
  it('accepts a 64-char name and rejects 65', () => {
    expect('a'.repeat(CUSTOM_FIELD_NAME_MAX_LEN)).toMatch(CUSTOM_FIELD_NAME_REGEX);
    expect(CUSTOM_FIELD_NAME_REGEX.test('a'.repeat(CUSTOM_FIELD_NAME_MAX_LEN + 1))).toBe(false);
  });
});
