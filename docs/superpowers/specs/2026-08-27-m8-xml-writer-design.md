# M8 Design: XML Writer, Versioning, Atomic Publish, Export Endpoint

**Date:** 2026-08-27
**Implements:** spec §2 (feed delivery, export history, export endpoint security,
removed products), §4 (ExportRun/ExportVersion entities, retention), §5.5
(pass-through fidelity), §5.6 (registry drives the writer), §5.7 (empty-element
stripping), §7 (QC runs sequentially before the writer, never blocks it),
§8 (export-history, diff, rollback, token rotation, public fetch endpoints).
Resolves the M7 carry-forward: wiring `ExportRun.export_version_id`.

Owner-approved decisions from brainstorming (2026-08-27):

1. Version content lives as XML files on disk; diff/rollback parse stored XML
   via the existing ingest `parse_xml`.
2. RSS channel metadata is per-feed-source configurable with fallbacks.
3. Rollback creates a new ExportVersion AND a new ExportRun row.
4. Layered `app/export/` package (renderer / store / service), thin ExportStep.

## 1. Module structure

New package `backend/app/export/`:

| Module | Responsibility |
|---|---|
| `renderer.py` | Pure function: canonical products + registry + channel metadata → XML bytes. Streaming emitter, deterministic output. |
| `store.py` | File layout, atomic writes (temp + `os.replace`), version files, published file, file-level retention prune. |
| `service.py` | DB bookkeeping: version allocation, ExportRun wiring, rollback, diff orchestration, row-level retention prune. |
| `steps.py` integration | `ExportStep` in `app/pipeline/steps.py` becomes a thin caller of the service. |

Routes:

| Module | Endpoints |
|---|---|
| `app/routes/export_public.py` | `GET /export/{token}.xml` (unauthenticated) |
| `app/routes/export_history.py` | export-history list, diff, rollback, token rotation (session auth) |

## 2. XML renderer

`render_feed(products, registry, channel) -> bytes`

- Document shape: RSS 2.0 with the GMC namespace:
  `<rss version="2.0" xmlns:g="http://base.google.com/schemas/1.0">` →
  `<channel>` containing `<title>`, `<link>`, `<description>`, then one
  `<item>` per product.
- Channel metadata comes from `FeedSource.configuration` keys
  `channel_title`, `channel_link`, `channel_description`. Fallbacks when a
  key is absent/empty: title = feed source name, link = `public_base_url`
  setting, description = client name.
- Items are sorted by product `id` (string sort). Within an item, elements
  are emitted in registry order (the `attributes.json` insertion order the
  loader preserves).
- An attribute is emitted only when it is registry-known, has
  `export_status == exportable`, and its value is non-empty. Unknown keys —
  including plugin sidecars such as `_category_provenance` — are never
  emitted.
- Kind rendering (spec §5.5):
  - scalar → `<g:attr>value</g:attr>`
  - repeated scalar → one element per item, order preserved
  - structured → `<g:attr>` with `<g:sub>` children in registry sub-field
    order; sub-fields absent from the value are skipped
  - repeated structured → repeated `<g:attr>` elements, each with nested
    sub-field children
- Empty handling (spec §5.7): `None`, `""`, `[]`, `{}` values are skipped;
  empty elements inside repeated fields are stripped before emission.
- Text is escaped with `xml.sax.saxutils.escape`; output is UTF-8 with an
  XML declaration. The emitter streams (writes per product, no full tree in
  memory).
- Determinism: identical input produces byte-identical output — no
  timestamps or run-specific data inside the XML. Consequently a rollback
  republish of an unchanged product set is byte-identical to the original
  version file.
- Zero products yields a valid document with an empty `<channel>` body
  (snapshot semantics; the volume-drop QC rule already warns about this).

## 3. File layout and atomic publish

New `Settings` fields:

- `export_dir: str` — default `<repo_root>/exports`.
- `public_base_url: str` — default `http://localhost:8000`; used to build
  the displayed export URL and as channel-link fallback.

Layout under `export_dir`:

```
published/{feed_source_id}.xml          # the file Google fetches
versions/{feed_source_id}/{version_number}.xml   # version archive
```

Every file write goes to a temp file in the same directory followed by
`os.replace()` (spec §2 atomic publish). Directories are created on demand.

Retention (spec §2/§4): after a new version N is stored, versions beyond the
feed source's `history_retention_count` (newest kept) are deleted — DB rows
and files together. Rollback-created versions are subject to the same rule
(no special treatment).

## 4. Schema changes (one Alembic revision)

- `feed_sources.export_token` — `String`, NOT NULL, unique index. Generated
  with `secrets.token_urlsafe(32)` at feed source creation. Existing rows
  are backfilled with fresh tokens in the migration. Stored plaintext: the
  UI must display and copy the full export URL at any time (spec §9.3).
- `feed_sources.history_retention_count` — `Integer`, NOT NULL, default and
  server_default 30 (spec §4).
- `export_versions.product_count` — `Integer`, NOT NULL (default 0 for the
  migration of any pre-existing rows).
- `export_versions.source` — `String`, NOT NULL: `'run'` or `'rollback'`.
- `export_versions.source_version_id` — nullable self-FK
  (`export_versions.id`, ondelete SET NULL); set only for rollback versions,
  pointing at the restored version.
- `export_versions.export_run_id` stays NOT NULL: rollback creates its
  ExportRun row first, so every version references a run.

## 5. Run lifecycle wiring (M7 carry-forward)

- `persist_findings` (QC) writes the ExportRun row with status
  `pending_export` instead of `completed`. M7 tests asserting
  `completed` are updated.
- `ExportStep` finalizes the row for the current `ingestion_run_id`:
  - success → set `export_version_id`, status `completed`, `completed_at`
  - writer failure → best-effort set status `failed`, then re-raise so the
    runner marks the IngestionRun `error`
- QC findings never block the export (spec §7): the writer runs whenever QC
  finishes, regardless of finding counts.

## 6. ExportStep flow

Replaces the `_NoOpStep` subclass; positioned after `QualityCheckStep` in
`default_steps` (unchanged position).

1. Load the export-bound set: staging products with `status='active'` and
   `excluded=false`, value = `processed_data` falling back to `raw_data`.
   This query is extracted into a shared helper used by both
   `QualityCheckStep` and `ExportStep` so the two cannot diverge.
2. Load feed source + client (channel metadata, retention count).
3. Render XML bytes.
4. Allocate `version_number = max + 1` under `SELECT ... FOR UPDATE` on the
   feed source row (serializes version allocation against concurrent
   rollback API calls; the per-feed-source pipeline lock already prevents
   concurrent runs).
5. Write the version file (temp + `os.replace`).
6. One transaction: insert `ExportVersion` (`source='run'`,
   `export_run_id`, `product_count`, `file_hash` = SHA-256 of the bytes) →
   update the ExportRun row (see §5). If this commit fails, the
   just-written version file is deleted best-effort.
7. Atomically publish the same bytes to
   `published/{feed_source_id}.xml`.
8. Prune retention (rows + files).
9. Return `StepResult(statistics={"export": {"products": n, "version": v}})`.

Products always carry `id` at this point (staging rejects id-less rows as
failed).

## 7. Export token and public endpoint

- Token generation happens in the feed source creation route
  (`routes/clients.py`).
- `GET /export/{token}.xml` — unauthenticated, no session dependency.
  Looks up the feed source by `export_token`; serves
  `published/{feed_source_id}.xml` via `FileResponse` with media type
  `application/xml`. 404 when the token is unknown, no export has been
  published yet, or the file is missing. No internal feed-source ID appears
  in the URL (spec §8).
- `POST /feed-sources/{id}/export-token/rotate` (session auth) — replaces
  the token and returns the new `export_url`. Because serving resolves the
  token via DB lookup, the old URL is invalid immediately (spec §2/§8).
- `FeedSourceOut` gains `export_url` (built from `public_base_url` +
  token) and `history_retention_count`. `FeedSourceUpdate` accepts
  `history_retention_count` (positive integer).

## 8. History API (session auth)

- `GET /feed-sources/{id}/export-history` — versions descending by
  `version_number`: `version_number`, `created_at`, `product_count`,
  `file_hash`, `source`, `source_version_id`.
- `GET /feed-sources/{id}/export-history/{v}/diff?against={v2}` —
  field-based diff (spec §8), not line-based. Both version files are parsed
  with the existing ingest `parse_xml`; products are keyed by `id`.
  `against` is optional and defaults to the immediately preceding version
  number (404 if none exists). Response shape:

  ```json
  {
    "version": 7,
    "against": 6,
    "added": ["id1"],
    "removed": ["id2"],
    "changed": [
      {"product_id": "id3",
       "fields": [{"field": "price", "old": "9.99 EUR", "new": "8.99 EUR"}]}
    ]
  }
  ```

  One entry per changed top-level GMC attribute; `old`/`new` are the
  canonical values (may be nested structures or lists). A missing version
  or version file yields 404.
- `POST /feed-sources/{id}/export-history/{v}/rollback` — append-only
  (spec §2/§8): parse version v's XML → render → write the new version file
  (temp + `os.replace`) → in one transaction create ExportRun
  (`status='rollback'`, `product_count` from v, all finding counts 0,
  `ingestion_run_id=NULL`) and the new ExportVersion (`source='rollback'`,
  `source_version_id=v`, `export_run_id` = the new run; if the commit
  fails, the just-written file is deleted best-effort) → atomic publish →
  retention prune. Response: the new version object. The rollback keeps the
  feed source's current channel metadata (it re-renders rather than copying
  bytes, so channel edits apply; item content is byte-stable per §2
  determinism).

## 9. Concurrency & failure semantics

- Pipeline runs hold the per-feed-source lock; rollback API calls serialize
  version allocation via the feed source row lock (§6.4). Both publish
  paths end in `os.replace()`, so Google never sees a partial file.
- Render or version-file write fails → nothing committed; ExportRun set to
  `failed` (best effort), IngestionRun finishes `error` with the stack
  trace, temp files cleaned up.
- DB commit fails after the version file was written → the file is deleted
  best-effort; run statuses as above.
- Publish fails after the commit → the version row and file remain (a valid
  history entry, diffable), ExportRun is set to `failed`, and the published
  file stays at the previous version; the next successful run republishes.
- Retention prune failures are logged and do not fail the run.

## 10. Testing

- **Renderer units:** all four attribute kinds; registry element order;
  escaping; empty-value skipping and repeated-field empty stripping;
  non-exportable and unknown-key (sidecar) skipping; shipping/tax
  pass-through fidelity (spec §5.5); determinism (two renders, identical
  bytes); empty product list.
- **Store units:** atomic publish (temp + replace), version file write,
  file retention prune.
- **Service integration (PostgreSQL):** version allocation and ExportRun
  wiring; rollback round-trip (republished bytes identical to the restored
  version's item content); diff correctness including added/removed
  products and nested-value changes; retention enforcement at N; rotation
  invalidates the old token immediately.
- **API tests:** public endpoint 200 with valid token, 404 with
  unknown/rotated token and before first export; export-history list;
  diff default-against behavior; rollback response shape.
- **M8 acceptance:** full pipeline run on a wide-format TSV fixture →
  GMC-compliant XML served at the token URL, versioned, with working
  rollback.
- **M7 updates:** assertions on ExportRun status change from `completed`
  to `pending_export` where QC wrote the row.
- Plugin contract suite untouched (no plugin host changes).

## 11. Out of scope

- Frontend export-history UI (M10).
- Core plugins (deferred by owner, 2026-08-27).
- Supplemental feeds, wildcard paths, price normalization (spec §2).
