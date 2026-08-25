# M4 Design: Field Mapping (Auto + Manual)

**Date:** 2026-08-25
**Status:** Approved
**Builds on:** M3 (commit `73cb22c` on `main`)
**Implements:** spec §6 (field mapping), §3 (Field Mapping stage), §5.7 (path grammar — sub-field subset), §8 (field-mapping endpoints)

> Numbering note: this is the project's fourth built milestone (M4) and
> corresponds to the AGENTS.md milestone-table row labeled "M3" (field
> mapping, auto + manual). The project sequence M0/M1/M2/M3 is already used
> for foundation, persistence+registry, scheduler/runner skeleton, and input
> readers.

## Scope

M4 delivers the field-mapping stage of the pipeline: after the readers produce
the canonical product model, a mapping step transforms source fields into
registry attributes using a stored per-feed-source mapping. The auto mapper
suggests mappings on first ingestion; operators refine them through the API.

**In scope:**
- `app/mapping/` package: document model, auto matcher, mapping application
- `MappingStep` pipeline step (between `IngestStep` and `PluginStep`)
- Source-field observation carried from readers through `IngestReport`/`RunState`
- API: `GET`/`PUT /feed-sources/{id}/field-mapping`, `POST .../field-mapping/auto`
- API: `GET /registry/attributes` (session-authenticated)
- First-ingestion auto-mapping with persistence in `FeedSource.field_mapping`

**Out of scope:**
- Frontend mapper UI (M10)
- Staging DB, delta mechanics (`content_hash`/`config_hash`) — next milestone
- Positional path indices (`shipping.1.price`) and wildcards in mapping targets
- Multi-column merges into one array target (one target per source field;
  GMC-shaped sources use single comma-separated columns — accepted limitation)
- Plugin execution, QC rules, XML export
- File-upload ingestion endpoint

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Auto-map new fields | Strict first-ingestion only; new source fields stay unmapped until the operator re-runs the auto mapper | Follows spec §6 wording exactly; avoids surprising operators with silent mapping changes |
| First-ingestion detection | `auto_mapped` marker inside the `field_mapping` JSONB document | No schema change; distinguishes "never mapped" from "operator deliberately unmapped everything" |
| Unmapped source fields | Dropped from the canonical product at the mapping step | §5.7: the addressable field universe is the Attribute Registry; plugins/QC/writer see a clean registry-only model; `content_hash` covers only export-relevant data |
| Mapping target granularity | `attr` and `attr.subfield` paths; no positional indices, no wildcards | §9.6 names sub-field paths for the manual mapper; positional/wildcard addressing deferred |
| Synonym knowledge | Curated in-code dict in `matcher.py` | MVP list: `ean`/`upc`/`barcode`/`isbn` → `gtin`; `sku`/`item_id`/`item_number` → `id`; `product_title` → `title`; `product_url` → `link`; `image_url` → `image_link`; `additional_images` → `additional_image_link`. Extendable without schema changes |
| Source fields for on-demand auto | Stored in the document (`source_fields`), observed at last successful ingest | No network fetch needed; same list feeds the future mapper UI |
| Registry API | `GET /registry/attributes` added now | Manual mapper UI (M10) needs the target dropdown; §8 is a rough shape, additive endpoint is spec-consistent |
| Mapping step placement | Separate `MappingStep` between `IngestStep` and `PluginStep` | Mirrors §3's data flow as a distinct stage; independently testable; `IngestStep` stays pure fetch+parse |
| Document shape | Entries with `origin` (`auto` \| `synonym` \| `manual`) | `synonym` marks §6's "marked as suggestions"; `manual` entries survive auto re-runs |
| Module layout | Dedicated `app/mapping/` package + thin step in `pipeline/steps.py` | Mirrors the `app/ingest/` pattern; matcher/apply/document independently testable without DB |

## field_mapping JSONB document

```json
{
  "version": 1,
  "auto_mapped": true,
  "source_fields": [
    {"name": "sku", "kind": "scalar", "sub_fields": []},
    {"name": "shipping", "kind": "repeated_structured", "sub_fields": ["country", "price"]}
  ],
  "mappings": {
    "sku": {"target": "id", "origin": "synonym"},
    "title": {"target": "title", "origin": "auto"}
  }
}
```

- `version` — document format version (1).
- `auto_mapped` — first-ingestion marker; once true, the auto mapper never
  runs automatically again.
- `source_fields` — fields observed at the last successful ingest (name, kind,
  sub-field names). Refreshed on every successful run.
- `mappings` — source field name → `{target, origin}`. `target` is a registry
  path (`attr` or `attr.subfield`). `origin` records how the entry was created.

An empty/missing document (or one without `auto_mapped`) means "never mapped".

## Source field observation (additive M3 change)

`IngestReport` gains `source_fields: list[SourceField]` where `SourceField` is
a frozen dataclass `(name, kind, sub_fields)`:

- Delimited readers: derived from the header plan (`ColumnSpec` → `SourceField`).
- XML reader: union of item keys; kind inferred from value shape
  (`str` → scalar, `list[str]` → repeated-scalar, `dict` → structured,
  `list[dict]` → repeated-structured; sub-fields are the union of observed
  dict keys). When items disagree on a field's shape, the first-observed
  shape wins for that field.

`RunState` gains `source_fields: list[SourceField]`; `IngestStep` copies them
from the report. `MappingStep` persists them into the document.

## Auto matcher (`app/mapping/matcher.py`)

Input: observed source fields + registry. Output: mapping entries.

1. **Exact/normalized match** — source name compared case-insensitively with
   separators (`_`, `-`, `.`, space) stripped, against registry attribute
   names (normalized the same way). Match → `origin: auto`. Only if kinds are
   compatible.
2. **Synonyms** — curated dict applied to the normalized source name. Match →
   `origin: synonym` (these are §6's "marked as suggestions").
3. **Conflict rule** — a target may be claimed by at most one source field.
   Priority: exact > synonym. Among equal-priority matches, the source field
   that appears first in `source_fields` order wins. A losing match stays
   unmapped.
4. Everything else stays unmapped.

Kind compatibility (source kind → allowed target kinds):

| Source kind | Allowed targets |
|---|---|
| scalar | scalar, repeated-scalar (wrap), sub-field of structured |
| repeated-scalar | repeated-scalar |
| structured | structured, repeated-structured (wrap) |
| repeated-structured | repeated-structured |

## Mapping application (`app/mapping/apply.py`)

Per product, build a new dict containing registry attributes only (unmapped
source fields dropped). Rules by runtime value shape:

| Value shape | Target | Behavior |
|---|---|---|
| `str` | scalar | assign |
| `str` | sub-field (`installment.months`) | assign into the struct (struct created if absent) |
| `str` | repeated-scalar | wrap in list |
| `list[str]` | repeated-scalar | copy |
| `dict` | structured | copy sub-fields by name; source sub-fields without a matching target sub-field are dropped |
| `dict` | repeated-structured | wrap in list |
| `list[dict]` | repeated-structured | copy |

Shape mismatch (e.g. list → scalar target): field dropped for that product,
logged, counted in step statistics. The run continues.

Fields already named as registry attributes pass through when they appear as
source fields with an identity mapping (the auto mapper produces these).

## MappingStep (`pipeline/steps.py`)

Replaces the no-op between `IngestStep` and `PluginStep`:

1. Load `FeedSource` (session from `ctx.session_factory`).
2. If the document has no `auto_mapped` marker → run the auto matcher against
   `run_state.source_fields`, persist the document (`auto_mapped: true`,
   `source_fields`, `mappings` with auto/synonym origins). First ingestion only.
3. Else: refresh `source_fields` from this run's observation (persist), keep
   mappings untouched.
4. Apply the stored mapping to every product in `run_state.products` (replace
   each dict in place).
5. `StepResult`: `processed_count` = products mapped; `statistics` =
   `{"mapping": {"applied": n, "dropped_unmapped_fields": n, "shape_mismatches": n}}`.

No DB writes beyond the `field_mapping` JSONB update. No new tables, no
migration (the column exists since the M1 baseline).

Error handling:
- Per-product issues (shape mismatch) never fail the run.
- A corrupt stored document (unparseable JSONB) fails the run with a clear
  message (fail-fast; operator fixes via PUT).

## API

All endpoints session-authenticated, following existing route patterns.

### `GET /feed-sources/{id}/field-mapping`

Returns the document. 404 if the feed source does not exist. A feed source
that was never ingested returns an empty document
(`{"version": 1, "auto_mapped": false, "source_fields": [], "mappings": {}}`).

### `PUT /feed-sources/{id}/field-mapping`

Body: `{"mappings": {"<source>": {"target": "<path>"}, ...}}`. Full-replace of
`mappings` only; `auto_mapped` and `source_fields` untouched. Entries written
with `origin: manual`.

Validation (422 `{"errors": [...]}` on failure, nothing persisted):
- Target must be a valid registry path: `attr` or `attr.subfield`; the
  attribute must exist; the sub-field must exist on the attribute.
- Kind compatibility enforced when the source field is known (present in
  `source_fields`); unknown source fields are accepted (operator may map
  fields not yet observed) — only target path existence is validated, since
  the source kind cannot be checked.
- A target may be claimed by at most one source field.

### `POST /feed-sources/{id}/field-mapping/auto`

Re-runs the auto matcher against stored `source_fields` (no fetch). Preserves
`manual` entries; auto/synonym entries are recomputed. Conflict priority:
manual > auto > synonym. Returns the updated document. 422 if no
`source_fields` observed yet (never ingested). 404 if the feed source does not
exist.

### `GET /registry/attributes`

Returns the loaded registry as a list of
`{name, kind, required, sub_fields: [{name, type, required}], enum_values}`.
Session-authenticated.

## Testing

**Unit (no PostgreSQL):**
- `matcher`: exact/normalized matches, synonyms marked, conflict resolution,
  kind compatibility, unknown fields unmapped.
- `apply`: all value-shape rules, sub-field targets, structured sub-field
  copy-by-name with drop, shape-mismatch drop, unmapped fields dropped,
  identity pass-through.
- `document`: validation round-trip, corrupt document detection.
- `MappingStep` with stub session: first-ingestion auto-map + persist, second
  run preserves manual entries, `source_fields` refresh.

**Integration (PostgreSQL via `isolated_database_url`):**
- Runner with real `IngestStep` (stub fetcher) + `MappingStep`: products in
  run state are registry-only; document persisted; PUT then re-run applies the
  manual mapping.
- API tests: GET/PUT/auto endpoints, 404s, 422 validation, registry endpoint.

**Acceptance:** auto mapper suggests from registry; manual edits persist per
feed source; full backend suite green; compileall clean.

## Dependencies

None new.
