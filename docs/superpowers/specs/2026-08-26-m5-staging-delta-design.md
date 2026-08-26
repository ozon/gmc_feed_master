# M5 Design: Staging + Delta Mechanics

**Date:** 2026-08-26
**Status:** Approved
**Builds on:** M4 (commit `8513f91` on `main`)
**Implements:** spec §4 (data model delta mechanics), §3 (staging stage of the data flow), §5.3 (three-tier scope merge — resolver pulled forward minimally), §2 (rows: removed products, export history prerequisites)

> Numbering note: this is the project's fifth built milestone (M5) and
> corresponds to the AGENTS.md milestone-table row labeled "M4" (staging +
> delta mechanics). The project sequence M0–M4 is already used for foundation,
> persistence+registry, scheduler/runner skeleton, input readers, and field
> mapping.

## Scope

M5 inserts the staging stage between field mapping and the plugin pipeline.
Each run compares the mapped products against the staged state per feed source
using two hashes (`content_hash`, `config_hash`), persists new/changed state,
marks disappeared products as removed, and reduces the in-memory product list
to exactly those products that downstream stages must process.

**In scope:**
- `app/staging/` package: canonicalization + hashing, config resolution
  (three-tier merge), delta classifier
- `StagingStep` pipeline step between `MappingStep` and `PluginStep`
- Alembic migration: `staging_products.removed_at`, FK cascade change, purge index
- Daily purge maintenance job on the existing `SchedulerService`
- Run statistics for staging class counts

**Out of scope:**
- Plugin host, manifest validation, runtime contract (next milestone)
- Per-product plugin execution (plugins consume the staged/changed set later)
- XML writer reading the full active set from staging (export milestone)
- Volume-drop QC rule (QC milestone; it will read staging counts)
- IngestionRun retention cleanup
- Any API endpoints (spec §8 defines none for staging)

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Architecture | `StagingStep` inside the step chain | Mirrors the M2/M4 `PipelineStep` pattern and spec §3's data flow; downstream steps unchanged |
| History trigger | Entries written only when `content_hash` changes | Config-only changes re-run the pipeline but leave the staged normalized product byte-identical; identical snapshots would be noise. Approved during brainstorming 2026-08-26 |
| `config_hash` timing | Computed now over existing tables, generic | Milestone done criterion requires both hashes to behave per spec §4; with empty plugin tables the hash is a stable constant, and the plugin-host milestone needs no changes here |
| Three-tier merge location | Pure function in `app/staging/config_resolver.py`, shared future use by plugin host | Spec §4 defines `config_hash` over *resolved* configs incl. merge (§5.3); pulling ~30 lines forward avoids a spec-violating intermediate hash |
| Canonical form | `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` → SHA-256, UTF-8 | Deterministic, nested-structure-safe, matches "sorted keys; includes nested structures" (§4) |
| Derived metadata | All `_`-prefixed keys stripped recursively before hashing | Generalizes §5.9's `_category_provenance` rule ("stripped before content hashing"); sidecars never trigger reprocessing or reach staging snapshots |
| Reactivation | Always enqueued, even with equal hashes | Spec §4: a reappeared removed product "flips back to active and is reprocessed" |
| Duplicate ids in one source run | First occurrence wins; later occurrences logged as row errors and counted failed | Deterministic; silent last-wins would hide broken feeds |
| Products without usable `id` | Not staged, not enqueued, counted failed | Staging identity is `(feed_source_id, product_id)`; an unstorable row is an ingestion failure like any other |
| Removed-product purge tracking | New nullable `removed_at` column set at removal time | Spec §4 purges "90 days after removal"; no existing column records removal time |
| History lifetime | FK `staging_history.staging_product_id` switched to `ON DELETE CASCADE` | Spec §4: removed products' history rows are "purged together with the product"; cascade makes that atomic from one DELETE |
| Purge scheduling | Fixed daily UTC maintenance job on `SchedulerService` | Same mechanism as feed-source cron jobs; retention is background hygiene, not operator work |

## Pipeline placement & flow

```
IngestStep ──► MappingStep ──► StagingStep ──► PluginStep (NoOp) ──► QualityCheckStep (NoOp) ──► ExportStep (NoOp)
                                   │
                                   ├─ persists staged state (new/changed/touched/removed/reactivated)
                                   ├─ writes StagingHistory entries on new/content-change only
                                   └─ run_state.products := products needing processing only
```

After `StagingStep`, `run_state.products` contains exactly the enqueue set
(new, changed, reactivated) as mapped canonical dicts. Unchanged products are
not carried downstream. Class counts land in
`IngestionRun.statistics["staging"]`.

## Hashing

### `content_hash`

SHA-256 over the mapped product serialized as canonical JSON: object keys
sorted recursively, compact separators, `ensure_ascii=False`. Before hashing,
all `_`-prefixed keys are stripped at every nesting level. The hashed value is
the post-mapping canonical product (registry attributes only — the mapping
step already drops unmapped fields).

### `config_hash`

Resolved once per feed source per run, then hashed with the same canonical
JSON form. The resolved bundle contains, in order:

1. For each `ModuleInstance` of the feed source's active pipeline ordered by
   `position`: `{position, plugin_id (string id), plugin_version, instance_config}`.
2. For each referenced plugin: its `PluginConfig` and `PluginData` payloads
   after three-tier resolution across all scopes the plugin declares.

A missing active pipeline resolves to an empty structure (stable constant
hash). With no plugins registered today this is deterministic from day one;
registering plugins or editing their configs/data/pipelines changes the hash
and triggers reprocessing via the normal delta path (§4).

### Three-tier merge (generic, §5.3)

For a plugin declaring scopes among `global`, `client`, `feed_source`:
resolution starts from `global` as base, overlays `client`, then
`feed_source`. Merge is per key: dict values merge recursively; non-dict
values (including lists) replace wholesale. Keys absent at a more specific
scope fall through to the less specific one. Plugins declaring a single scope
resolve to just that payload.

## Classification matrix

Existing staged rows for the feed source are loaded once per run into an
id-keyed map. Per product and per staged-but-absent id:

| Class | Condition | Persisted action | Enqueued |
|---|---|---|---|
| new | no staged row for `product_id` | insert `active` row (+history) | yes |
| changed | content ≠ stored **or** config-hash ≠ stored | update `raw_data`, hashes, `ingestion_run_id` (+history iff content changed) | yes |
| unchanged | both hashes equal, status `active` | touch `last_seen_at` only (§4 wording) | no |
| reactivated | staged `removed`, id present in source | `status=active`, clear `removed_at`, update row (+history iff content changed vs stored snapshot) | always |
| removed | staged `active`, id absent from source | `status=removed`, set `removed_at=now()` | n/a |

Notes:
- Reactivation compares incoming content against the stored snapshot; if it
  differs, a history entry documents the change alongside the status flip.
- Staged `removed` products absent again: no-op (purge job owns their lifecycle).
- `ingestion_run_id` is updated whenever a row's content or status is written
  (new/changed/reactivated/removed); unchanged rows keep the run that last
  wrote them, matching §4's "only update `last_seen_at`".

## Migration

One Alembic revision:

1. `ALTER TABLE staging_products ADD COLUMN removed_at TIMESTAMPTZ NULL`.
2. Drop and recreate `staging_history.staging_product_id` FK with
   `ON DELETE CASCADE` (was `RESTRICT`).
3. Create partial index
   `ix_staging_products_removed_purge ON staging_products (removed_at) WHERE status = 'removed'`.

Downgrade reverses all three.

## Purge job

Registered once at startup on the existing `SchedulerService` as a fixed daily
UTC cron (03:00):

- Delete `staging_products WHERE status='removed' AND removed_at < now() - interval '90 days'`
  (history rows go via cascade).
- Delete `staging_history WHERE recorded_at < now() - interval '90 days'`
  (live products' aged history).

Deletion counts are logged. No catch-up semantics beyond APScheduler's own
behavior; a missed day simply purges more the next day.

## Error handling

- Product without `id`, non-scalar `id`, or empty `id`: skipped, counted in
  `failed_count`, logged with row context where available.
- Duplicate `product_id` within one run: first occurrence processed, later
  occurrences logged as row errors and counted failed.
- DB writes chunked (~1000 rows per transaction) to bound memory on large
  feeds; a failed chunk propagates and fails the run through the runner's
  existing exception path (`status="error"` with stack trace).
- Empty source feed (0 valid products): every previously active product flips
  to `removed` — correct snapshot semantics; the volume-drop safeguard arrives
  with QC.

## Testing

**Unit (no PostgreSQL):**
- Canonicalization/hashing: key-order independence, nested structs, repeated
  values, unicode, `_`-prefix stripping at depth.
- Classifier: full matrix including reactivation-with-equal-hash enqueues,
  duplicate-id and missing-id handling.
- Three-tier merge: recursive dict merge vs wholesale replacement of non-dict
  values, fallthrough across declared scopes, single-scope plugins.

**Integration (PostgreSQL via `isolated_database_url`):**
- `StagingStep` against real DB: first run inserts everything; identical
  second run touches only (`last_seen_at`) and enqueues nothing; modified
  product enqueues and writes one history entry; config-only change (edited
  instance config) re-enqueues without a history entry; removal and
  reactivation round-trip clears `removed_at`.
- Purge job: expired removed rows deleted with history, fresh ones kept; old
  live history deleted, recent kept.
- Migration upgrade/downgrade produces/reverses the three changes.

**Acceptance:** `test_m5_acceptance.py` following the M2–M4 gate pattern —
full backend suite green, compileall clean, done criterion "hashes behave
exactly as specified, incl. reactivation & purge" demonstrated end-to-end.
