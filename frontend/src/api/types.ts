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
  kind?: string;
};

export type RegistryAttribute = {
  name: string;
  kind: string;
  required: string;
  baseline_required?: boolean;
  sub_fields: RegistrySubField[];
  enum_values: string[];
  max_repeats: number;
};

export type SourceField = {
  name: string;
  kind: string;
  sub_fields: string[];
  max_repeats: number;
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
  custom_fields?: string[];
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
  raw_data: Record<string, unknown>;
  processed?: boolean;
  excluded?: boolean;
  processed_data?: Record<string, unknown> | null;
};

export type ProductsPageResponse = {
  items: ProductListItem[];
  fields: string[];
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
  processed_data: Record<string, unknown> | null;
  excluded: boolean;
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

export type QualityHistoryRow = {
  id: number;
  started_at: string;
  product_count: number;
  critical: number;
  warning: number;
  info: number;
  fixed: number;
  new: number;
  remaining: number;
};

export type QualityFindingsResponse = {
  ingestion_run_id: number | null;
  counts: {
    critical: number;
    warning: number;
    info: number;
  };
  product_count: number;
  delta: { fixed: number; new: number; remaining: number };
  has_previous: boolean;
  prev_counts: { critical: number; warning: number; info: number } | null;
  findings: QualityFinding[];
};

export type PluginConfigResponse = Record<string, unknown>;

export type PipelineInstance = {
  id: number | null;
  position: number;
  plugin_id: string;
  name: string;
  configuration: Record<string, unknown>;
  enabled: boolean;
};

export type PipelineDoc = {
  instances: PipelineInstance[];
};

export type ExportVersionOut = {
  id: number;
  version_number: number;
  product_count: number;
  file_hash: string;
  source: 'scheduled' | 'manual' | 'rollback';
  source_version_id: number | null;
  created_at: string;
  findings?: { critical: number; warning: number; info: number } | null;
  url?: string | null;
};

export type DiffFieldOut = {
  field: string;
  old: unknown;
  new: unknown;
};

export type DiffProductOut = {
  product_id: string;
  fields: DiffFieldOut[];
};

export type DiffOut = {
  version: number;
  against: number;
  added: string[];
  removed: string[];
  changed: DiffProductOut[];
};

export type FeedSourceFieldsResponse = {
  fields: {
    name: string;
    kind: string;
    sub_fields: { name: string; kind?: string }[];
    max_repeats: number;
  }[];
};

export type ProductLookupSample = {
  product_id: string;
  status: string;
  excluded: boolean;
  title: string | null;
  brand: string | null;
  availability: string | null;
} & Record<string, unknown>;

export type ProductLookupMatch = { count: number; sample: ProductLookupSample | null };

export type ProductLookupResponse = { matches: Record<string, ProductLookupMatch> };

export type AdminUser = {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  client_ids: number[] | null;
};

export type GlobalSettings = {
  staging_removal_retention_days: number;
  staging_history_retention_days: number;
  ingestion_run_retention_days: number;
};

export type SchedulerJob = { id: string; trigger: string };

export type AiProvider = {
  id: number;
  name: string;
  provider_type: string;
  base_url: string;
  model: string;
  input_price_per_mtok: string | null;
  output_price_per_mtok: string | null;
  max_concurrency: number;
  timeout_s: number;
  enabled: boolean;
  is_default: boolean;
};

export type AiUsageGroupBy = 'client' | 'feed_source' | 'task_type' | 'day';

export type AiUsageParams = {
  group_by: AiUsageGroupBy;
  client_id?: number;
  feed_source_id?: number;
  task_type?: string;
  from?: string;
  to?: string;
};

export type AiUsageRow = {
  group_key: number | string | null;
  calls: number;
  cache_hits: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: string | null;
};

export type AiTestResult = {
  status: 'ok' | 'error';
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  error_code?: string;
};

export type PromptTemplate = {
  id: number;
  task_type: string;
  client_id: number | null;
  version: number;
  name: string;
  system_prompt: string;
  user_prompt: string;
  variables: string[];
  is_active: boolean;
  created_at: string;
  created_by: string | null;
};

export type PromptPreviewResult = {
  messages: { role: string; content: string }[];
  used_variables: string[];
  warnings: string[];
  errors: string[];
};

export type ChatMessage = { role: "user" | "assistant"; content: string };
