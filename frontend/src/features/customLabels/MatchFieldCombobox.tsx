import { useEffect, useMemo, useState } from 'react';
import { Combobox, InputBase, useCombobox } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { RegistryAttribute } from '../../api/types';

export function MatchFieldCombobox({
  value,
  onChange,
  attributes,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  attributes: RegistryAttribute[];
  disabled?: boolean;
}) {
  const { t } = useTranslation('customLabels');
  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
  });
  const [search, setSearch] = useState(value);
  useEffect(() => setSearch(value), [value]);

  const groups = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const attr of attributes) {
      const items = [attr.name, ...(attr.sub_fields ?? []).map((s) => `${attr.name}.${s.name}`)];
      map.set(attr.name, items);
    }
    return map;
  }, [attributes]);

  const query = search.trim().toLowerCase();
  const exact = [...groups.values()].some((items) => items.includes(search));
  const visibleGroups = [...groups.entries()]
    .map(([attr, items]) => [attr, items.filter((i) => i.toLowerCase().includes(query))] as const)
    .filter(([, items]) => items.length > 0);

  return (
    <Combobox
      store={combobox}
      onOptionSubmit={(val) => {
        onChange(val);
        combobox.closeDropdown();
      }}
    >
      <Combobox.Target>
        <InputBase
          label={t('fields.matchField')}
          description={t('fields.matchFieldHint')}
          placeholder={t('fields.matchFieldPlaceholder')}
          disabled={disabled}
          value={search}
          rightSection={<Combobox.Chevron />}
          rightSectionPointerEvents="none"
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            onChange(event.currentTarget.value);
            combobox.openDropdown();
            combobox.updateSelectedOptionIndex();
          }}
          onClick={() => combobox.openDropdown()}
          onFocus={() => combobox.openDropdown()}
          onBlur={() => {
            combobox.closeDropdown();
            setSearch(value);
          }}
        />
      </Combobox.Target>
      <Combobox.Dropdown>
        <Combobox.Options mah={280} style={{ overflowY: 'auto' }}>
          {visibleGroups.map(([attr, items]) => (
            <Combobox.Group key={attr} label={attr}>
              {items.map((item) => (
                <Combobox.Option key={item} value={item} active={item === value}>
                  {item}
                </Combobox.Option>
              ))}
            </Combobox.Group>
          ))}
          {!exact && (
            <Combobox.Empty>{t('fields.matchFieldCustom', { value: search })}</Combobox.Empty>
          )}
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}
