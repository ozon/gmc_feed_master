# Mapping UI: Button-Only Auto-Mapper & Custom Source Fields — Design

Date: 2026-09-11
Status: pending user review

## 1. Problem

Two operator complaints about the Mapping tab (`SetupPage` → Mapping tab):

1. **Surprise auto-mappings.** Opening the page or running the pipeline
   produces mappings the operator never asked for. Root cause is not the
   page — it is implicit `auto_match()` on every pipeline run
   (`MappingStep`, `backend/app/pipeline/steps.py:127`) and every dry-run
   (`run_dry_run`, `backend/app/pipeline/dry_run.py:62`) whenever
   `doc.auto_mapped` is false. The UI button (`POST
   /feed-sources/{id}/field-mapping/auto`) is merely an additional trigger.
2. **Cannot map targets the feed does not (yet) provide.** The mapping table
   renders only feed-observed `source_fields` as rows. There is no way to
   pre-provision a target mapping for a field the input feed will supply
   later (or that a plugin/reader path produces), and no way to add a row
   by hand. The backend already accepts arbitrary free-text source keys on
   PUT (validation only checks the target side) — the gap is the UI plus
   persistence of unmapped custom rows (an unmapped key would silently
   vanish on next GET, since rows are derived from `source_fields` ∪
   mapping keys that have a target).

Operator decisions (2026-09-11):

- **D1 — Button-only everywhere.** The POST auto endpoint is the *only*
  trigger for `auto_match`. Implicit automatch is removed from
  `MappingStep` and `run_dry_run`. Fresh feed sources stay unmapped (QC
  baseline alerts flag missing coverage) until the operator clicks
  Auto-map or saves manual mappings.
- **D2 — Add-custom-field row in the table.** A dedicated add row at the
  end of the mapping table: free-text source name + registry target
  picker. Self-added rows are removable. Feed-observed fields stay
  read-only rows (clearing the target remains their "remove").
- **D3 — Source-name only, no constants.** A mapping entry names a source
  field. No literal/constant values in mapping entries (target always gets
  value X) — out of scope; plugins remain the mechanism for synthesized
  values.

## 2. Verified code premises

1. `MappingTab` itself never auto-maps on mount — it only GETs the
   document. The surprise comes from backend runs (see §1.1). The
   "don't run automapper when I open the page" complaint is therefore
   satisfied by D1, plus one UI nuance: the **badge**
   (`doc.auto_mapped`) tells the operator *why* mappings exist, and the
   Auto-map button remains explicit.
2. `auto_match` preserves manual entries: both implicit call sites pass
   `existing=` (manual-origin entries survive); the POST endpoint
   likewise keeps `origin == "manual"` entries
   (`backend/app/routes/field_mapping.py:224-232`). D1 does not change
   the button's semantics.
3. PUT validation (`_validate_mappings`) checks targets against the
   registry and source keys against `document.source_fields` — but a
   free-text source key with no observed parent only passes today by
   falling into the "unknown source field" branch when dotted, or the
   kind-less `check_target(source, target, None)` branch when flat
   (field_mapping.py:141-142). So flat arbitrary keys are already
   accepted; the design makes this explicit and validated (§4.2).
4. `apply_mapping` is key-driven: a mapping whose source key is absent
   from the product is a natural no-op (no value to move). "Dormant"
   custom rows need no apply-side change (§5).
5. `MappingDocument` is additive-tolerant on read (precedent:
   `max_repeats`, no version bump, `raw.get(key, default)`), JSONB on
   `FeedSource.field_mapping` — a new `custom_fields` key rides the same
   document without migration.
6. The export renderer iterates registry attributes only
   (`backend/app/export/renderer.py:72`); an unmapped/never-written
   target simply produces no XML — nothing renders for a dormant custom
   row. QC `BaselineRequired` flags uncovered required attributes, which
   is the operator's signal to map or run Auto-map.
7. `FieldSelect` (shared picker) already offers every registry attribute
   kind — scalar, structured (`attr.sub`), repeated_scalar /
   repeated_structured (incl. indexed `attr.N[.sub]`) — with free-text
   fallback. The custom row's target picker reuses it unchanged
   (`frontend/src/components/FieldSelect.tsx`, options from
   `buildFieldOptions(fromRegistryAttributes(...))`, the exact wiring
   `MappingTable` already uses for target selects).
8. Mapping run lock, atomic publish, and delta hashing are untouched by
   both changes: mappings content feeds `config_hash` only through the
   resolved pipeline config bundle; mapping-document changes behave
   like any mapping edit today (no hash-computation change).

## 3. Part 1 — Auto-mapper becomes button-only

### 3.1 `MappingStep` (backend/app/pipeline/steps.py)

Remove the implicit block:

```python
# deleted:
if not doc.auto_mapped:
    doc.mappings = auto_match(...)
    doc.auto_mapped = True
```

The step still: loads the feed source, refreshes
`doc.source_fields = list(ctx.run_state.source_fields)` after ingest, and
persists the document — keeping `GET /feed-sources/{id}/fields` and the
mapping page's observed-field rows current. Mappings are only read
(`apply_mapping`), never written.

### 3.2 `run_dry_run` (backend/app/pipeline/dry_run.py)

Remove the in-memory automatch (`if not doc.auto_mapped: doc.mappings =
auto_match(...)`). A dry-run previews exactly the stored mapping state —
matching pipeline behavior is the point of a dry-run. Fresh sources
show unmapped fields (dropped stats) and QC findings, which is honest
feedback, not noise.

### 3.3 Route, badge, UI

- `POST /feed-sources/{id}/field-mapping/auto` unchanged — the single
  trigger, preserving manual entries, setting `auto_mapped = True`.
- `auto_mapped` badge semantics unchanged ("this document was last
  produced by Auto-map"). A subsequent manual PUT still rewrites all
  entries as `origin: manual`; `auto_mapped` stays true until reset —
  acceptable (no reset path is added; the badge is informational).
- `MappingTab` needs no automap-related change for D1 (it already only
  triggers on button click).

### 3.4 Consequences

- Fresh feed source → first pipeline run exports only what plugins
  synthesize; QC `BaselineRequired` findings flag the gaps. Operator
  accepts this (D1).
- `existing=` args of `auto_match` remain in use by the POST route; no
  matcher change.
- Tests asserting implicit automatch after a pipeline run / dry-run are
  inverted to assert *no* implicit automatch; new tests pin that mappings
  and `auto_mapped` are untouched by runs (§7).

## 4. Part 2 — Custom source fields

### 4.1 Document model (backend/app/mapping/document.py)

- `MappingDocument.custom_fields: list[str]` (default `[]`).
- `to_json`: emits `custom_fields` when non-empty (or always — emitting
  always is simpler and harmless; **decision: always emit**).
- `from_json`: tolerant read — missing → `[]`; non-list or non-string
  entries → `MappingDocumentError` (corrupt document is a 500, same as
  other shape violations).
- Name grammar (both ends): `^[a-z_][a-z0-9_]*$` — single flat segment,
  no dots (dotted custom names would collide with observed sub-path
  semantics `parent.sub`). Max length 64 (cheap guard).
- No version bump; stored documents without the key parse fine.

### 4.2 PUT endpoint (backend/app/routes/field_mapping.py)

`FieldMappingPut` gains `custom_fields: list[str] = []`. PUT is a
full-replace on `custom_fields` (mirrors mappings semantics — the UI
always sends the complete set).

Validation (new `_validate_custom_fields`, errors in the same 422
`{"errors": [...]}` shape, `"source: message"` rows):

1. grammar + length per name (as §4.1);
2. no duplicates within `custom_fields`;
3. no collision with observed `source_fields` names (an observed field is
   already a row; a duplicate custom row would be shadow);
4. every flat mapping source key ∈ observed ∪ custom (422 "unknown
   source field" otherwise — today's lenient fallthrough for arbitrary
   flat keys is closed: typos and stray keys should fail loudly now that
   adding custom fields is a first-class flow);
5. dotted mapping source keys (`parent.sub`) keep today's rules
   unchanged (parent must be observed+structured; sub must be declared)
   — custom fields are flat-only, so no new dotted-source paths open.

After validation, `document.custom_fields` is set from the payload
alongside mappings; GET returns it (see §4.3).

### 4.3 Schemas (backend/app/schemas/field_mapping.py)

- `FieldMappingOut` / `FieldMappingDoc` (frontend) gain
  `custom_fields: list[str]`.
- New i18n keys (en+de): `mapping.custom.*` — add-row label, name-input
  label/placeholder, invalid-name inline error, remove-tooltip; plus 422
  error passthrough is unchanged (row errors keyed by source name).

### 4.4 Frontend — `MappingTab` / `MappingTable`

- `MappingTab` state gains `customFields: string[]` (local copy, dirty
  vs. server) and `removedCustom: Set`-equivalent via the same
  full-replace payload pattern already used for mappings: on Save, send
  `mappings` + `custom_fields` (complete effective set).
- `MappingTable` renders, below observed-field rows:
  1. **Custom rows** (one per `customFields` entry): name (text, no
     edit — renaming = remove+add, keeps payloads unambiguous), target
     `FieldSelect` (same options as observed rows, incl. structured /
     repeated / indexed targets), origin badge "manual", and a **trash
     icon button** removing the row (local state only until Save).
  2. **Add-custom row**: name `TextInput` (client-side grammar+length
     validation with inline error, `^[a-z_][a-z0-9_]*$` ≤ 64 — mirror of
     `INDEXED_PATH_REGEX` style constants in `fieldOptions.ts`; new
     `CUSTOM_FIELD_NAME_REGEX` lives there too) + target `FieldSelect`.
     "Add" button appends to local `customFields` and a
     `customEdits[name] = target` mapping entry; both go through the
     same dirty-tracking and Save path.
- Validation UX: the add row's Add button is disabled until name valid +
  non-empty target; name uniqueness vs. observed ∪ custom checked
  client-side with inline error (server 422 is the backstop).
- Dirty-tracking: `isDirty` covers mappings edits, added/removed custom
  fields, and custom-row target edits.
- Observed fields remain read-only rows; clearing a target = unmapping
  (unchanged semantics).
- Empty-state nuance: "No source fields observed yet" should not hide
  the custom-field section — a fresh feed can be fully pre-provisioned
  by hand. The custom section renders even when observed rows are
  empty.

### 4.5 Pipeline semantics — dormant custom rows

- A custom mapping row is a **no-op in `apply_mapping` until its source
  key actually appears in an ingested product** (e.g. feed starts
  supplying `my_custom_field`, or a reader path produces it). Then it
  behaves exactly like an observed field's mapping: value moves to the
  target, kind compatibility enforced by the same `check_target`
  rules on PUT (custom rows are kind-less on the source side — same as
  today's flat free-text keys, `source_kind=None`, so any target kind is
  attachable; the operator picks sensible targets).
- Once a feed *does* supply the key, ingest observes it as a
  `SourceField` and it appears as an observed row too — the custom row
  and the observed row are the same key; validation rule §4.2(3)
  applies only to PUT-time overlap, so GET will show it in both lists
  (observed row from `source_fields`, custom row from `custom_fields`).
- **Observed/custom overlap (edge, accepted):** when ingest later observes
  a key that is also custom (`x`, kind `repeated_scalar`), the mapping
  still applies kind-less (source kinds are never recorded for custom
  rows). A kind-incompatible target would then shape-mismatch at apply
  time exactly like any bad mapping. Accepted behavior: no
  kind-revalidation of custom rows on ingest.
- **UI dedupe rule:** the mapping table renders one row per key — an
  observed name shadows its custom twin (the observed row carries the
  mapping select and badges; the custom list keeps the name for
  persistence, removable via the custom row's trash button). PUT-time
  rule §4.2(3) prevents creating the overlap deliberately, but an
  ingest observation can create it after the fact; GET may return the
  name in both lists and the UI must handle it.
- Custom fields are NOT injected into `GET /feed-sources/{id}/fields`
  (that route serves fields with data behind them — observed fields and
  `_BASELINE_FIELDS`). Plugins/readers that want to reference the key
  by name can; the fields route remains ingest-driven.

### 4.6 Data flow summary

- GET doc → render observed rows + custom rows + add row.
- Operator adds `my_field` → target `product_detail.2.attribute_value`
  (free-text indexed path, registry-validated on save).
- Save: PUT `{ mappings: {...all effective...}, custom_fields:
  [...names...] }` → 422 row errors map back to rows (incl. custom
  names); 200 → local state reset, server state invalidated.
- Pipeline run: `my_field` absent in products → no-op row, `auto_mapped`
  untouched, mappings untouched; run statistics show it as a normal
  mapped field once present.

## 5. Error handling

- All PUT validation errors: existing 422 `{"errors": ["source:
  message", ...]}` shape; `MappingTab.parseRowErrors` already maps them
  to per-row errors, keyed by source name — custom names key the same
  way.
- Corrupt stored document (bad `custom_fields` shape): `from_json`
  raises → 500 "field mapping document corrupt" (unchanged path).
- Frontend inline validation prevents malformed names from ever
  reaching the backend (grammar, length, duplicates, observed
  collision).

## 6. Documentation updates (same commit)

- `backend/docs/api.md`: PUT/GET field-mapping payloads gain
  `custom_fields`; note that implicit automatch is gone from pipeline
  and dry-run, POST `/auto` is the only trigger.
- `backend/docs/architecture.md`: MappingStep description — mappings
  read-only during runs; auto-match is operator-triggered only.
- `docs/decisions.md` entries:
  1. **Supersede implicit automatch** (2026-09-11): pipeline/dry-run no
     longer auto-match; button-only. Fresh sources rely on QC baseline
     findings until mapped.
  2. **Custom source fields** (2026-09-11): `custom_fields` on the
     mapping document, flat-name grammar, full-replace PUT, dormant
     until observed in ingest; flat source keys must be observed ∪
     custom (closes today's lenient flat-key fallthrough).
- `frontend/docs/architecture.md`: only if it names the mapping table
  rows (observed-only) — update to observed + custom.

## 7. Test strategy

Backend (RED→GREEN):
- `test_mapping_document.py`: `custom_fields` round-trip, tolerant default
  `[]`, corrupt shapes raise.
- `test_field_mapping_api.py`:
  - PUT with `custom_fields` persists + GET returns them;
  - 422s: bad grammar, duplicate, observed-collision, flat mapping key
    in neither observed nor custom;
  - dotted sources keep old rules (existing tests cover);
  - custom field mapping to any registry kind accepted (kind-less
    source);
  - **run-scoped**: pipeline run does not write mappings /
    `auto_mapped` on a fresh source (inverts today's implicit-automatch
    expectation in `test_mapping_step.py`);
  - dry-run does not auto-match (same inversion in dry-run tests);
  - POST `/auto` still preserves manual entries (existing tests).
- `test_mapping_apply.py`: custom-row no-op when key absent; applies
  normally when key present (should already pass — pins the dormant
  contract).

Frontend (vitest + RTL):
- `MappingTab.test.tsx` / `MappingTable.test.tsx`:
  - custom section renders with empty observed fields;
  - add flow: invalid name blocked inline, valid add appears as row;
  - remove flow: row gone, dirty, saved payload excludes it;
  - save payload includes `custom_fields`;
  - 422 row error keyed on custom name shows on that row;
  - observed name shadows duplicate custom row (UI dedupe).
- `fieldOptions.test.ts`: `CUSTOM_FIELD_NAME_REGEX` accept/reject table
  (incl. dotted names rejected — they must use observed sub-fields, not
  custom).

Gates: `uv run ruff check .` (no new errors vs baseline), `uv run mypy
.`, `uv run pytest -n auto`, `npm run test`, `npm run typecheck`,
`npm run build`.

## 8. Out of scope

- Constant/literal mapping values (D3).
- Editing a custom field's name in place (remove+add instead).
- Kind inference/re-validation for custom rows when ingest later
  observes the key.
- Any change to `GET /feed-sources/{id}/fields` output.
- Any change to matcher synonyms/quality; `auto_match` internals
  untouched.

## 9. Acceptance criteria

- Opening the Mapping tab never runs the auto-mapper; a fresh source
  stays empty until the operator clicks Auto-map or saves manual
  mappings.
- A pipeline run or dry-run on an unmapped source produces no mappings,
  no `auto_mapped` flip, QC baseline findings flagging the gaps.
- The operator can add a custom source field (grammar-validated name)
  and map it to any registry target — scalar, structured sub-field,
  repeated, indexed (`product_detail.2.attribute_value`) — from the
  shared FieldSelect.
- Custom rows are removable; observed fields remain read-only rows.
- Custom rows persist across reloads (stored in the document), survive
  pipeline runs unchanged, and activate automatically once the feed
  supplies the key.
- Save sends mappings + custom_fields as one atomic PUT; 422 errors map
  back to the offending rows incl. custom names.
