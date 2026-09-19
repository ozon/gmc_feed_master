import { useState } from 'react';
import { Select } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { apiGet } from '../../api/client';
import { queryKeys } from '../../api/queryKeys';
import type { TaxonomyEntry } from './types';

const DEBOUNCE_MS = 300;

export function TaxonomyCombobox({
  language,
  value,
  onChange,
  disabled = false,
}: {
  language: string;
  value: string | null;
  onChange: (taxonomyId: string | null) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation('category');
  const [query, setQuery] = useState('');
  const [debouncedQuery] = useDebouncedValue(query, DEBOUNCE_MS);
  const trimmedQuery = debouncedQuery.trim();

  const searchQuery = useQuery({
    queryKey: queryKeys.category.taxonomySearch(language, trimmedQuery),
    queryFn: () =>
      apiGet<{ items: TaxonomyEntry[] }>(
        `/plugins/category/taxonomy/search?language=${encodeURIComponent(language)}` +
          `&q=${encodeURIComponent(trimmedQuery)}&limit=50&offset=0`,
      ),
    enabled: !disabled && trimmedQuery !== '',
  });

  const visibleEntries = disabled || !query.trim() ? [] : (searchQuery.data?.items ?? []);

  return (
    <Select
      label={t('rules.taxonomy')}
      searchable
      clearable
      disabled={disabled}
      filter={({ options }) => options}
      data={visibleEntries.map((entry) => ({
        value: entry.id,
        label: `${entry.id} — ${entry.path}`,
      }))}
      value={value}
      searchValue={query}
      onSearchChange={setQuery}
      onChange={(next) => onChange(next)}
      placeholder={t('taxonomy.search')}
      nothingFoundMessage={
        searchQuery.isError ? t('taxonomy.searchFailed') : t('taxonomy.noResults')
      }
    />
  );
}
