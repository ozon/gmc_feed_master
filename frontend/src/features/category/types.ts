export type CategoryOperator = 'eq' | 'ne' | 'contains' | 'regex' | 'in';

export type CategoryRule = {
  id: string;
  source_field: string;
  operator: CategoryOperator;
  source_value: string | string[];
  taxonomy_id: string;
  is_excluded?: boolean;
};

export type Tier = 'global' | 'client';

export type ScopedCategoryRule = CategoryRule & { origin: Tier };

export type CategoryStats = {
  total: number;
  buckets: { manual: number; auto: number; excluded: number; uncategorized: number };
  rules: Record<string, number>;
};

export type CategoryMatch = { product_id: string; title: string | null };

export type TaxonomyEntry = { id: string; path: string };

export type CategoryProductState = {
  product_id: string;
  title: string | null;
  provenance: 'manual' | 'auto' | 'excluded' | null;
  rule_id: string | null;
  google_product_category: string | null;
  status: string;
};
