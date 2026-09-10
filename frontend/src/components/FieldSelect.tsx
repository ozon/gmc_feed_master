import { useEffect, useMemo, useState } from 'react';
import { CloseButton, Combobox, InputBase, useCombobox } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { INDEXED_PATH_REGEX, type FieldOption, type GroupedFieldOptions } from '../api/fieldOptions';

export type FieldSelectProps = {
  value: string;
  onChange: (value: string) => void;   // clear emits ''
  options: GroupedFieldOptions;
  label?: React.ReactNode;
  description?: React.ReactNode;
  placeholder?: string;
  disabled?: boolean;
  error?: React.ReactNode;
  clearable?: boolean;
  size?: 'xs' | 'sm' | 'md' | 'lg';
  w?: number | string;
  'aria-label'?: string;
  'data-testid'?: string;
};

function matchesQuery(option: FieldOption, group: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    option.value.toLowerCase().includes(q)
    || option.label.toLowerCase().includes(q)
    || group.toLowerCase().includes(q)
  );
}

export function FieldSelect({
  value,
  onChange,
  options,
  label,
  description,
  placeholder,
  disabled = false,
  error,
  clearable = false,
  size = 'sm',
  w,
  'aria-label': ariaLabel,
  'data-testid': dataTestId,
}: FieldSelectProps) {
  const { t } = useTranslation('common');
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const combobox = useCombobox({
    onDropdownOpen: () => setDropdownOpen(true),
    onDropdownClose: () => {
      setDropdownOpen(false);
      combobox.resetSelectedOption();
    },
  });
  const [search, setSearch] = useState(value);
  const [showAll, setShowAll] = useState(true);
  useEffect(() => setSearch(value), [value]);

  const query = showAll ? '' : search.trim().toLowerCase();
  const isKnown = useMemo(
    () => options.some((g) => g.items.some((i) => i.value === search)),
    [options, search],
  );
  const isValidSyntax = search === '' || INDEXED_PATH_REGEX.test(search);
  const showCustom = !isKnown && search !== '' && isValidSyntax;
  const showInvalid = search !== '' && !isValidSyntax;

  const visibleGroups = useMemo(
    () => options
      .map((g) => ({
        group: g.group,
        items: g.items.filter((i) => matchesQuery(i, g.group, query)),
      }))
      .filter((g) => g.items.length > 0),
    [options, query],
  );

  return (
    <Combobox
      store={combobox}
      onOptionSubmit={(val) => {
        if (val === '__custom__') {
          onChange(search);
        } else {
          onChange(val);
        }
        combobox.closeDropdown();
      }}
    >
      <Combobox.Target>
        <InputBase
          data-testid={dataTestId}
          aria-label={ariaLabel}
          role="combobox"
          aria-haspopup="listbox"
          label={label}
          description={description}
          placeholder={placeholder}
          disabled={disabled}
          error={showInvalid ? t('fieldSelect.invalidPath') : error}
          value={search}
          rightSection={
            clearable && value !== '' ? (
              <CloseButton
                size="sm"
                aria-label={t('fieldSelect.clear')}
                onClick={() => onChange('')}
              />
            ) : (
              <Combobox.Chevron />
            )
          }
          rightSectionPointerEvents={clearable && value !== '' ? 'all' : 'none'}
          size={size}
          w={w}
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            setShowAll(false);
            combobox.openDropdown();
            combobox.updateSelectedOptionIndex();
          }}
          onClick={() => {
            setShowAll(true);
            combobox.openDropdown();
          }}
          onFocus={() => {
            setShowAll(true);
            combobox.openDropdown();
          }}
          onBlur={() => {
            combobox.closeDropdown();
            setSearch(value);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !isKnown) {
              event.preventDefault();
              if (isValidSyntax && search !== '') {
                onChange(search);
                combobox.closeDropdown();
              }
            }
          }}
        />
      </Combobox.Target>
      {dropdownOpen && (
        <Combobox.Dropdown>
          <Combobox.Options mah={280} style={{ overflowY: 'auto' }}>
            {visibleGroups.map((g) => (
              <Combobox.Group key={g.group} label={g.group}>
                {g.items.map((item) => (
                  <Combobox.Option key={item.value} value={item.value} active={item.value === value}>
                    {item.label}
                  </Combobox.Option>
                ))}
              </Combobox.Group>
            ))}
            {showCustom && (
              <Combobox.Option value="__custom__">
                {t('fieldSelect.customValue', { value: search })}
              </Combobox.Option>
            )}
            {showInvalid && (
              <Combobox.Empty>{t('fieldSelect.invalidPath')}</Combobox.Empty>
            )}
          </Combobox.Options>
        </Combobox.Dropdown>
      )}
    </Combobox>
  );
}
