# Backend Data Model

## Entity Relationship Diagram

```mermaid
erDiagram
    USER ||--o{ SESSION : has
    CLIENT ||--o{ FEED_SOURCE : owns
    FEED_SOURCE ||--o{ MODULE_PIPELINE : has
    FEED_SOURCE ||--o{ INGESTION_RUN : generates
    FEED_SOURCE ||--o{ EXPORT_RUN : produces
    FEED_SOURCE ||--o{ EXPORT_VERSION : versions
    FEED_SOURCE ||--o{ STAGING_PRODUCT : stages
    FEED_SOURCE ||--o{ QUALITY_FINDING : finds
    MODULE_PIPELINE ||--o{ MODULE_INSTANCE : contains
    PLUGIN ||--o{ MODULE_INSTANCE : referenced_by
    PLUGIN ||--o{ PLUGIN_CONFIG : configured_by
    PLUGIN ||--o{ PLUGIN_DATA : operated_by
    CLIENT ||--o{ PLUGIN_CONFIG : scopes
    CLIENT ||--o{ PLUGIN_DATA : scopes
    FEED_SOURCE ||--o{ PLUGIN_CONFIG : scopes
    FEED_SOURCE ||--o{ PLUGIN_DATA : scopes
    STAGING_PRODUCT ||--o{ STAGING_HISTORY : history
```

## Core Entities

### User
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `username` | String(255) | Unique |
| `password_hash` | String(255) | Argon2 |
| `created_at` | DateTime | |

Seeded from `INITIAL_USERNAME` / `INITIAL_PASSWORD` env vars on first start.

### Client
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `name` | String(255) | |
| `status` | String(50) | `active` / `inactive` |
| `created_at` | DateTime | |

### FeedSource
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `client_id` | Integer | FK → Client, RESTRICT |
| `active_pipeline_id` | Integer | FK → ModulePipeline, RESTRICT, nullable |
| `name` | String(255) | |
| `source_format` | String(50) | `xml`, `tsv`, `csv`, `wide_tsv` |
| `cron_expression` | String(100) | UTC, nullable |
| `target_country` | String(10) | ISO 3166-1 alpha-2 |
| `target_language` | String(10) | ISO 639-1 |
| `currency` | String(3) | ISO 4217 |
| `feed_type` | String(20) | `primary` (MVP), `supplemental` (future) |
| `export_token` | String(64) | Unique, `secrets.token_urlsafe(32)` |
| `history_retention_count` | Integer | Default 30 |
| `source_url` | String(2048) | HTTP(S) fetch URL |
| `volume_drop_threshold_pct` | Integer | Default 20 |
| `field_mapping` | JSONB | Source field → registry attribute path |
| `configuration` | JSONB | Feed-specific config (e.g., basic_auth) |
| `created_at` / `updated_at` | DateTime | Auto |

### ModulePipeline
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `feed_source_id` | Integer | FK → FeedSource, RESTRICT |
| `name` | String(255) | |
| `version` | String(100) | Semantic version |
| `definition` | JSONB | Ordered list of module instances |
| `created_at` | DateTime | |

Unique constraint on `(name, version)`.

### ModuleInstance
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `pipeline_id` | Integer | FK → ModulePipeline, RESTRICT |
| `plugin_id` | Integer | FK → Plugin, RESTRICT |
| `position` | Integer | Order in pipeline |
| `enabled` | Boolean | Per-instance toggle, default true |
| `name` | String(255) | Display name |
| `configuration` | JSONB | Instance-specific config |

Unique constraint on `(pipeline_id, position)`.

### Plugin
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `name` | String(255) | Manifest `id` |
| `version` | String(100) | Manifest `version` |
| `manifest` | JSONB | Full parsed manifest |
| `enabled` | Boolean | Global toggle, default false (core=true) |
| `created_at` | DateTime | |

Unique constraint on `(name, version)`.

### PluginConfig / PluginData (identical structure)
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `plugin_id` | Integer | FK → Plugin, RESTRICT |
| `scope` | String(50) | `global` / `client` / `feed_source` |
| `client_id` | Integer | FK → Client, nullable |
| `feed_source_id` | Integer | FK → FeedSource, nullable |
| `key` | String(255) | Logical key (default `"default"`) |
| `config` / `data` | JSONB | Validated against manifest schema |
| `created_at` | DateTime | |

**Scope constraints** (enforced by DB):
- `global`: `client_id IS NULL AND feed_source_id IS NULL`
- `client`: `client_id NOT NULL AND feed_source_id IS NULL`
- `feed_source`: `client_id IS NULL AND feed_source_id NOT NULL`

### StagingProduct
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `feed_source_id` | Integer | FK → FeedSource |
| `ingestion_run_id` | Integer | FK → IngestionRun |
| `product_id` | String(255) | Source product ID |
| `content_hash` | String(64) | SHA-256 canonical product |
| `config_hash` | String(64) | SHA-256 resolved pipeline config |
| `status` | String(20) | `active` / `removed` |
| `last_seen_at` | DateTime | Updated every run |
| `removed_at` | DateTime | Set when status=removed |
| `raw_data` | JSONB | Post-mapping, pre-pipeline |
| `processed_data` | JSONB | Post-pipeline (export candidate) |
| `excluded` | Boolean | Dropped by plugin (Filter, etc.) |

### StagingHistory
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `staging_product_id` | Integer | FK → StagingProduct |
| `snapshot` | JSONB | Full product snapshot at change |
| `created_at` | DateTime | |

Written only when `content_hash` changes.

### IngestionRun
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `feed_source_id` | Integer | FK → FeedSource |
| `status` | String(20) | `running` / `success` / `error` / `skipped` |
| `processed_count` | Integer | |
| `failed_count` | Integer | Row errors + plugin errors |
| `statistics` | JSONB | Per-step stats |
| `error_message` | String(4000) | Truncated |
| `error_stack_trace` | String(20000) | Truncated |
| `started_at` | DateTime | |
| `completed_at` | DateTime | Nullable |

Retention: 90 days.

### ExportRun
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `feed_source_id` | Integer | FK → FeedSource |
| `ingestion_run_id` | Integer | FK → IngestionRun |
| `product_count` | Integer | Exported products |
| `critical_finding_count` | Integer | |
| `warning_finding_count` | Integer | |
| `info_finding_count` | Integer | |
| `created_at` | DateTime | |

### ExportVersion
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `feed_source_id` | Integer | FK → FeedSource |
| `export_run_id` | Integer | FK → ExportRun |
| `version_number` | Integer | Sequential per feed source |
| `xml_path` | String(512) | Relative to export_dir |
| `created_at` | DateTime | |

Retention: Last N per feed source (default 30, includes rollback versions).

### QualityFinding
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `feed_source_id` | Integer | FK → FeedSource |
| `ingestion_run_id` | Integer | FK → IngestionRun |
| `product_id` | String(255) | Empty for cross-product rules |
| `rule_id` | String(100) | QC rule identifier |
| `severity` | String(20) | `critical` / `warning` / `info` |
| `field` | String(255) | Affected attribute path |
| `message` | String(1000) | |
| `details` | JSONB | Additional context |
| `created_at` | DateTime | |

**Retention**: Detail rows for latest run only; counts persisted in `ExportRun`.

### Session
| Column | Type | Notes |
|--------|------|-------|
| `id` | String(64) | PK, random token |
| `user_id` | Integer | FK → User |
| `created_at` | DateTime | |
| `last_accessed_at` | DateTime | Sliding expiration |
| `expires_at` | DateTime | Absolute expiration |

Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`.

### ImageDimension
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `url` | String(2048) | Unique |
| `width` | Integer | Nullable |
| `height` | Integer | Nullable |
| `error_message` | String(500) | Nullable |
| `fetched_at` | DateTime | Cache key by URL |

Used by QC ImageRequirements rule; re-fetched only when URL changes.

## Delta Mechanics Detail

### Content Hash
```
content_hash = SHA256(json_dumps(canonical_product, sort_keys=True))
```
- Canonical product: post-mapping, pre-pipeline normalized form
- Includes all nested structures (shipping, tax, installment, etc.)
- Field-mapping changes → different normalized data → different hash

### Config Hash
```
config_hash = SHA256(json_dumps({
    "pipeline": [{"plugin": id, "version": ver, "instance_config": {...}, "resolved_config": {...}, "resolved_data": {...}} ...],
    "plugin_versions": {plugin_id: version}
}, sort_keys=True))
```
- Captures: ordered pipeline, instance configs, resolved PluginConfig/PluginData (three-tier merge), plugin versions
- Any change → full reprocessing of affected feed source products

### Removed Product Lifecycle
```
Source feed has product X
    │
    ▼ (next ingestion)
StagingProduct status=active, last_seen_at updated
    │
    ▼ (product missing from source)
StagingProduct status=removed, removed_at=now, omitted from XML
    │
    ▼ (90 days later)
Purged by purge_expired() (StagingProduct + StagingHistory rows)
    │
    ▼ (product reappears in source)
New StagingProduct row (status=active), full reprocess (no prior hash)
```

## Retention Summary

| Table | Policy |
|-------|--------|
| `ExportVersion` | Last N per feed_source (configurable, default 30) |
| `IngestionRun` | 90 days |
| `StagingHistory` | 90 days (cascades with StagingProduct purge) |
| `StagingProduct` (removed) | 90 days after `removed_at` |
| `QualityFinding` (detail) | Latest run per feed_source only |
| `ExportRun` counts | Persist indefinitely (small) |
| `Session` | Sliding (configurable idle) + absolute (configurable) |
| `ImageDimension` | No auto-expiry; keyed by URL |

## Key Files
- `app/models/*.py` — SQLAlchemy 2.0 mapped classes
- `app/staging/delta.py` — `classify()` hash comparison logic
- `app/staging/persistence.py` — `apply_staging_delta()`, `apply_plugin_outcomes()`, `load_export_bound()`
- `app/staging/purge.py` — `purge_expired()`, `purge_expired_ingestion_runs()`