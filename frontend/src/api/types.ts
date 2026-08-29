export type FeedSourceSummary = {
  id: number;
  client_id: number;
  name: string;
  source_format: string;
  item_count: number;
  last_export_at: string | null;
  last_export_status: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
};

export type ClientSummary = {
  id: number;
  name: string;
  status: string;
  feed_sources: FeedSourceSummary[];
};

export type DashboardSummary = {
  counts: {
    clients: number;
    feed_sources: number;
    active_products: number;
    failed_last_exports: number;
  };
  clients: ClientSummary[];
};

export type PluginManifestFrontend = {
  menu_item?: string;
  icon?: string;
  component?: string;
};

export type PluginInfo = {
  id: string;
  name: string;
  version: string;
  enabled: boolean;
  manifest: { frontend?: PluginManifestFrontend; [key: string]: unknown } | null;
  used_by_feed_sources: number;
};

export type ClientRow = {
  id: number;
  name: string;
  contact_details: Record<string, unknown>;
  status: string;
  created_at: string;
};

export type FeedSourceRow = {
  id: number;
  client_id: number;
  name: string;
  source_format: string;
  cron_expression: string | null;
  target_country: string | null;
  target_language: string | null;
  currency: string | null;
  source_url: string | null;
  feed_type: string;
  history_retention_count: number;
  volume_drop_threshold_pct: number;
  configuration: Record<string, unknown>;
  export_url: string;
  created_at: string;
  updated_at: string;
};

export type RegistrySubField = {
  name: string;
  type: string;
  required: string;
};

export type RegistryAttribute = {
  name: string;
  kind: string;
  required: string;
  sub_fields: RegistrySubField[];
  enum_values: string[];
};

export type SourceField = {
  name: string;
  kind: string;
  sub_fields: string[];
};

export type MappingEntry = {
  target: string;
  origin: string;
};

export type FieldMappingDoc = {
  version: number;
  auto_mapped: boolean;
  source_fields: SourceField[];
  mappings: Record<string, MappingEntry>;
};

export type ProductListItem = {
  product_id: string;
  id: string;
  status: string;
  last_seen_at: string;
  title: string | null;
  description: string | null;
  link: string | null;
  image_link: string | null;
  availability: string | null;
  price: string | null;
  condition: string | null;
};

export type ProductsPageResponse = {
  items: ProductListItem[];
  total: number;
  page: number;
  page_size: number;
};

export type ProductDetail = {
  product_id: string;
  status: string;
  content_hash: string;
  config_hash: string;
  last_seen_at: string;
  removed_at: string | null;
  raw_data: Record<string, unknown>;
};

export type IngestionRunRow = {
  id: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  processed_count: number;
  failed_count: number;
  error_message: string | null;
  statistics: Record<string, unknown>;
};

export type QualityFinding = {
  severity: string;
  code: string;
  field: string | null;
  message: string;
  product_id: string;
  details: Record<string, unknown>;
};

export type QualityFindingsResponse = {
  ingestion_run_id: number | null;
  counts: {
    critical: number;
    warning: number;
    info: number;
  };
  findings: QualityFinding[];
};

export type PluginConfigResponse = Record<string, unknown>;
