import { useEffect, useState } from 'react';
import { Select } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { apiGet } from '../../api/client';
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
  const [entries, setEntries] = useState<TaxonomyEntry[]>([]);

  useEffect(() => {
    if (disabled || !query.trim()) {
      setEntries([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      void apiGet<{ items: TaxonomyEntry[] }>(
        `/plugins/category/taxonomy/search?language=${language}` +
          `&q=${encodeURIComponent(query)}&limit=50&offset=0`,
      )
        .catch(() => ({ items: [] as TaxonomyEntry[] }))
        .then((result) => {
          if (!cancelled) setEntries(result.items);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, language, disabled]);

  return (
    <Select
      label={t('rules.taxonomy')}
      searchable
      clearable
      disabled={disabled}
      data={entries.map((entry) => ({
        value: entry.id,
        label: `${entry.id} — ${entry.path}`,
      }))}
      value={value}
      searchValue={query}
      onSearchChange={setQuery}
      onChange={(next) => onChange(next)}
      placeholder={t('taxonomy.search')}
      nothingFoundMessage={t('taxonomy.noResults')}
    />
  );
}
