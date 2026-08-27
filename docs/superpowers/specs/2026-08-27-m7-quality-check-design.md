# M7 Design: Quality Check Engine

**Date:** 2026-08-27
**Status:** Approved
**Builds on:** M6 (commit `61b3034` on `main`)
**Implements:** spec §7 (QC rule set), §4 (QualityFinding/ExportRun semantics), §8 (`GET /feed-sources/{id}/quality-findings`)

> Numbering note: this is the project's seventh built milestone (M7) and
> corresponds to the AGENTS.md milestone-table row labeled "M7" (Quality
> Check engine). The four core plugins (AGENTS.md row "M6") are deferred by
> owner decision and remain out of scope.

## Scope

The QC engine evaluates the export-bound product set after the plugin stage
and before the (still no-op) export stage. It is evaluative and non-blocking:
findings are persisted and counted, but never prevent a run from completing.
Only infrastructure errors (DB failure, unhandled exception in the engine
itself) fail the run.

**In scope:**
- `app/qc/` package: rule engine, rule implementations, image probe,
  persistence
- `QualityCheckStep` replacing the no-op stub in the pipeline
- Registry extension: `Cardinality.min_items` + parser fixes for item counts
  and per-value lengths; regenerated `attributes.json`
- Migrations: severity-count rename, `image_dimensions` table,
  `feed_sources.volume_drop_threshold_pct`, `quality_findings` display
  columns
- API: `GET /feed-sources/{id}/quality-findings`
- New pinned dependency: Pillow (image dimension parsing)
- Acceptance gate `test_m7_acceptance.py`

**Out of scope:**
- XML writer / export (M8)
- Frontend dashboard (M10)
- The four core plugins (deferred by owner)
- User-configurable QC rules (spec's rule set is closed)

## Decisions

Owner-approved during brainstorming (2026-08-27):

1. **Input set:** QC evaluates ALL active staged products for the feed
   source (`status='active'`, `excluded=false`) — the same set the M8 writer
   will export — not just this run's plugin survivors. Cross-product rules
   (variant consistency, volume drop) require the full set, and findings must
   reflect what Google fetches.
2. **Image dimensions:** Pillow (pinned) parses bytes fetched via httpx;
   no hand-rolled header parsers.
3. **Severity vocabulary:** `ExportRun.error_finding_count` renamed to
   `critical_finding_count` to match spec §7 severities
   (`critical`/`warning`/`info`).
4. **Registry-driven cardinality:** the registry gains `min_items` (and
   per-value length constraints); `gmc_def.md` parser fixed so e.g.
   `product_highlight` carries `min_items=2, max_items=100`, per-value max
   150. QC reads all limits from the registry — no QC-local override table.
5. **Volume-drop baseline:** compare against the previous `ExportRun` row's
   `product_count` for the feed source; rule skipped when no prior ExportRun
   exists. Fires automatically once M8 writes ExportRun rows; tests seed one.
6. **ExportRun rows:** QC writes the ExportRun row this milestone
   (`product_count`, per-severity counts, `export_version_id=NULL`, status
   `completed`). M8 decides how to attach versions.
7. **`processed_data` NULL fallback:** evaluate `raw_data` when
   `processed_data` is NULL (e.g. plugin exception on first run).
8. **Image cache:** persistent DB table `image_dimensions` keyed by URL;
   survives restarts, shared across runs and feed sources.
9. **Findings API:** included this milestone (latest run per feed source).
10. **Engine structure:** rule registry with two rule shapes (per-product,
    cross-product); registry-driven rules generated from `RegistryDocument`;
    hand-written rules register alongside. No declarative DSL.

**Owner amendments on approval (2026-08-27):**

11. **Findings are feed-scoped, not staging-row-scoped:** `quality_findings`
    gains `feed_source_id` (FK → `feed_sources.id`, NOT NULL). The
    replace-delete is strictly feed-keyed (`DELETE … WHERE feed_source_id =
    ?`), so purged staging rows cannot orphan stale findings. Each finding
    also persists `ingestion_run_id` (already on the model) — not only on the
    ExportRun.
12. **Brand exemption is a hardcoded taxonomy-ID list:** the Category plugin
    is deferred, so `brand_required` must not depend on it. The exempt set
    (movies/books/music) is a constant in the QC module, derived from
    `gmc_def.md` and the Google Product Taxonomy (see Rule set below).
13. **Image checks cover all image fields:** `image_requirements` applies to
    `image_link` AND every element of `additional_image_link[*]`. Findings
    address repeated-field positions via path grammar (e.g.
    `additional_image_link.2`).

## Input set & product resolution

`QualityCheckStep.execute(ctx)`:

1. Load feed source (currency, `volume_drop_threshold_pct`).
2. Load all staging rows: `feed_source_id = ctx.feed_source_id`,
   `status = 'active'`, `excluded = false`. Select `id`, `product_id`,
   `processed_data`, `raw_data`.
3. Per row: `product = processed_data if processed_data is not None else
   raw_data`.
4. Load latest prior `ExportRun` for the feed source (for volume drop), if
   any.
5. Run engine; persist findings + ExportRun in one transaction.
6. Return `StepResult` with statistics: `{"qc": {"products": N,
   "critical": n, "warning": n, "info": n}}`. Never raises on findings.

## Rule engine

```python
@dataclass(frozen=True)
class QcContext:
    feed_source_id: int
    currency: str | None
    volume_drop_threshold_pct: int
    registry: RegistryDocument
    clock: Clock
    image_probe: ImageProbe
    previous_export_run: ExportRun | None

@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str          # "critical" | "warning" | "info"
    field: str | None
    message: str
    details: dict[str, Any]

class PerProductRule(Protocol):
    rule_id: str
    async def check(self, product: dict, ctx: QcContext) -> list[Finding]: ...

class CrossProductRule(Protocol):
    rule_id: str
    async def check(self, products: list[dict], ctx: QcContext) -> list[Finding]: ...
```

The engine holds two ordered lists. Per-product rules run for each product;
cross-product rules run once over the full list. Findings accumulate; the
engine attaches `product_id` (from the staging row) to each finding at
persistence time.

## Rule set (spec §7, complete)

| rule_id | shape | source | severity |
|---|---|---|---|
| `baseline_required` | per-product | hand-written field list: `id`, `title`/`structured_title`, `description`/`structured_description`, `link`, `image_link`, `availability`, `price`, `condition` | critical |
| `brand_required` | per-product | hand-written; exempt when `google_product_category` (ID form) is in the hardcoded media taxonomy set: Books {784, 543541, 543542, 543543}, DVDs & Videos {839, 543527, 543528, 543529}, Music & Sound Recordings {855, 543522, 543523, 543524, 543525, 543526} (Google Product Taxonomy 2021-09-21; string-path values are not exempted — ID preferred per `gmc_def.md`) | warning |
| `gtin_mpn` | per-product | hand-written: missing `gtin` → `mpn`+`brand` required; present `gtin` → GS1 mod-10 checksum | critical |
| `enum_values` | per-product | registry-driven: every attribute with `enum_values`, case-sensitive | critical |
| `conditional_required` | per-product | hand-written table: `availability=preorder` → `availability_date`; `unit_pricing_base_measure` requires `unit_pricing_measure` | warning |
| `date_format` | per-product | hand-written field list, strict ISO 8601 incl. timezone | critical |
| `variant_consistency` | cross-product | group by `item_group_id`; shared base attrs, ≥1 differing variant attr | warning |
| `length_limits` | per-product | registry-driven: `constraints.max_length` | warning |
| `cardinality` | per-product | registry-driven: `cardinality.min_items`/`max_items` + per-value lengths | warning |
| `currency_consistency` | per-product | `price`/`sale_price` currency vs `FeedSource.currency` | critical |
| `image_requirements` | per-product | format check + async dimension probe (cached); see below | mixed |
| `volume_drop` | cross-product | active count vs previous `ExportRun.product_count`; skipped when no prior ExportRun | warning |

### Image requirements detail

- Applies to `image_link` and every element of `additional_image_link[*]`.
  Findings carry the path-grammar field address, e.g. `image_link` or
  `additional_image_link.2`.
- Format: check the URL extension against the GMC-allowed list (jpg/jpeg,
  webp, png, gif, bmp, tiff/tif); if the URL has no recognizable extension,
  sniff the fetched bytes' magic numbers. Disallowed format → warning.
- Dimensions via `ImageProbe`: httpx streaming GET with ~10 MB cap,
  `Pillow Image.open(BytesIO).size`.
- Cache: `image_dimensions` table (`url` unique, `width`/`height` nullable,
  `fetch_error` nullable, `fetched_at`). Cache hit → no re-fetch.
- Concurrency bounded by `asyncio.Semaphore(8)`.
- Severity by size and clock (`clock.now()` vs `IMAGE_SIZE_ENFORCEMENT_DATE
  = 2027-01-31`):
  - unfetchable → info
  - < 500×500 → warning before 2027-01-31, critical on/after
  - ≥ 500×500 but < 1500×1500 → info
  - ≥ 1500×1500 → no finding

## Registry extension

- `Cardinality` gains `min_items: int | None = None` and
  `item_max_length: int | None = None` (per-value length for repeated
  attributes).
- `registry/generate.py` parser: capture "min. 2, max. 100" item counts and
  per-value char limits (e.g. `product_highlight`: 1–150 chars each, min 2,
  max 100 → `min_items=2, max_items=100, item_max_length=150`).
- Regenerate `backend/registry/attributes.json`; `registry_check.py` gate
  green; M1 registry tests updated where the corrected values change
  expectations.

## Schema changes (migrations)

1. Rename `export_runs.error_finding_count` → `critical_finding_count`.
2. Create `image_dimensions`: `id` PK, `url` String(2048) UNIQUE,
   `width`/`height` Integer nullable, `fetch_error` String nullable,
   `fetched_at` timestamptz.
3. `feed_sources.volume_drop_threshold_pct` Integer NOT NULL default 20.
4. `quality_findings`: add `feed_source_id` Integer NOT NULL (FK →
   `feed_sources.id`, ondelete CASCADE — findings are feed-scoped and die
   with the feed source), `product_id` String(255) NOT NULL,
   `field` String(255) nullable. Index on `feed_source_id`. Drop
   `staging_product_id` (and its index): with feed-scoped replace semantics
   the RESTRICT FK would block staging purge of rows referenced by findings;
   the denormalized `product_id` carries the reference instead.

## Persistence

- Findings: replace-previous semantics, strictly feed-keyed —
  `DELETE FROM quality_findings WHERE feed_source_id = ?`, then insert this
  run's findings (each carrying `feed_source_id`, `ingestion_run_id`,
  `product_id`, severity, code, field, message, details), then write the
  ExportRun — all in one transaction. Spec: "latest run per feed source
  only". Feed-keyed delete means purged staging rows cannot orphan findings.
- ExportRun: `feed_source_id`, `ingestion_run_id`, `status='completed'`,
  `product_count`, `critical_finding_count`, `warning_finding_count`,
  `info_finding_count`, `export_version_id=NULL`.

## API

`GET /feed-sources/{id}/quality-findings` (session-authenticated):

```json
{
  "ingestion_run_id": 12,
  "counts": {"critical": 2, "warning": 5, "info": 1},
  "findings": [
    {"severity": "critical", "code": "enum_values", "field": "availability",
     "message": "...", "product_id": "SKU-1", "details": {}}
  ]
}
```

- 404 if feed source missing.
- Empty result (`counts` zeroed, `findings: []`) if no QC run yet.

## Wiring

- `create_app` builds the QC engine with the app's injectable `Clock`
  (already on `app.state.clock`) and an `ImageProbe` (httpx client lifecycle
  tied to app lifespan).
- `QualityCheckStep` replaces the no-op in the step list, after
  `PluginStep`, before `ExportStep`.

## Testing strategy

- **Unit:** each rule category in isolation. Registry-driven rules tested
  against a synthetic `RegistryDocument`. Image rule with stubbed probe +
  `TestClock` for the 2027-01-31 escalation boundary.
- **Image probe:** httpx `MockTransport`; cache hit/miss; fetch error;
  size-cap abort.
- **Integration:** QC step in pipeline — findings persisted, ExportRun
  counts, non-blocking on findings, blocking only on infra error;
  `processed_data` NULL → `raw_data` fallback.
- **API:** findings endpoint incl. 404 and empty.
- **Acceptance gate** (`test_m7_acceptance.py`, M5/M6 pattern): end-to-end
  run producing findings across all categories; ExportRun counts verified;
  volume-drop fires with seeded prior ExportRun; image escalation verified
  with injected clock.
- Contract suite unaffected (no plugin changes).

## Done when (AGENTS row M7)

- All rule categories fire.
- Image-size escalation uses the injectable clock.
- ExportRun carries counts.
