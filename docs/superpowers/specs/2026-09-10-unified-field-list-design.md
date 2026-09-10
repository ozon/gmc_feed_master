# Unified Field List (Mapping, Rules, Filter, Labelizer) — Design

Date: 2026-09-10
Status: approved (user, with 5 operator directives incorporated), pending
implementation plan

## 1. Problem

Four UI locations maintain four independent, partly inconsistent
implementations of a "field selection list":

- `frontend/src/features/setup/MappingTable.tsx` — target options built from
  registry attributes with local dot-path expansion and grouping.
- `frontend/src/features/customLabels/MatchFieldCombobox.tsx` — options built
  separately from registry attributes with duplicated expansion.
- `frontend/src/features/rules/RuleEditor.tsx` — flat `fields: string[]` via
  `useFeedSourceFields` → `GET /feed-sources/{id}/fields` (currently
  `{fields: string[]}`), no sub-fields.
- `frontend/src/features/filter/FilterUI.tsx` — same flat hook, same gaps.

There is no way to address individual repetitions of `repeated_structured`
(`product_detail` with per-item `section_name`/`attribute_name`/
`attribute_value`) or `repeated_scalar` (`additional_image_link`) attributes.

**Explicitly out of scope:** `RuleValuesEditor.tsx` / `RuleCard.tsx`
(Labelizer preview, `extraFields` / `PREVIEW_DEFAULT_FIELDS`) — data source
semantics untouched; only a mechanical response-shape adaptation (see §8).

## 2. Verified premise corrections (code, not assumptions)

Two premises in the task brief do not match the code and are corrected in the
design:

1. **"First observed wins" for sub-fields is already union.**
   `_infer_source_fields` (`backend/app/ingest/xml_reader.py:89`) accumulates
   `sub_field_order` across all products and all list elements. The recorded
   decision (docs/decisions.md 2026-08-25, "M4 XML kind inference") applies
   first-observed only to **kind** inference; sub-fields are already the union
   of observed keys. The ingest work is therefore: `max_repeats` computation
   plus a **regression test** pinning union behavior, plus a decisions.md
   clarification entry. No union re-implementation.
2. **Mantine `Select` cannot accept free-text values.** Official docs:
   "Unlike Autocomplete, Select does not allow entering custom values." The
   shared `FieldSelect` therefore builds on the **Combobox + InputBase**
   pattern (generalizing the existing `MatchFieldCombobox`), which already
   provides grouped options + free text. (User decision, 2026-09-10.)

Additional code facts shaping the design:

3. The 1-based positional path grammar already exists in QC
   (`additional_image_link.1` finding paths, `backend/app/qc/rules.py:232`);
   the new grammar aligns with it.
4. Indexed **target** paths contradict a recorded decision (2026-08-28:
   "positional paths (e.g. `shipping.1.price`) are rejected with 422"). This
   change **supersedes** that decision for `repeated_*` targets; documented in
   decisions.md (§9).
5. `RuleValuesEditor.tsx` (untouchable semantics) and `ProductsPage.tsx`
   (out of scope) consume `fieldsQuery.data?.fields` as `string[]` — the
   breaking route change forces a minimal mechanical adaptation in both
   (map descriptors → names locally). Nothing else changes for them.

## 3. Binding decisions (operator, this cycle)

1. **`FieldSelect` = Combobox + InputBase** (free text, grouped options,
   custom filter matching path OR label OR group; input shows the stored
   dot-path value). Rejected: Autocomplete (less control over custom-value
   UX), Select (cannot accept free text).
2. **Registry `max_repeats` computed per request** from the feed's live
   staged data (see §5.3). Rejected: precomputed/stored (staleness, new write
   path), static fallback (weak UX).
3. **`GET /registry/attributes?feed_source_id=N`** — optional query param.
   Without it, `max_repeats = 0` for repeated attributes (no indexed children
   generated; free text still possible). Back-compat for existing call sites
   without feed context. Rejected: new feed-scoped route (more surface, no
   shared cache key), mandatory param (big blast radius in out-of-scope
   files).
4. **`GET /feed-sources/{id}/fields` served from the persisted
   `MappingDocument.source_fields`** (kind-aware, maintained by every
   pipeline run via `MappingStep`), with `_BASELINE_FIELDS` merged as scalar
   descriptors. Rejected: live `raw_data` SQL scan (heavier, re-implements
   kind inference in SQL), doc-with-scan-fallback (most code, marginal gain).
5. **All three plugins read indexed paths** (Rules conditions+actions,
   Filter conditions, Labelizer matchField). Rejected: mapping/export only
   (pickers would promise what engines can't do), per-consumer subsets
   (violates identical-lists criterion).
6. **Rules THEN-actions support index-addressed writes** (`set
   product_detail.2.attribute_value = 'x'`). Non-indexed behavior
   byte-identical to today.
7. **One-shot cutover** for the breaking response change (single-deployment
   reality, coordinated frontend rework in the same cycle). Rejected:
   dual-shape transition period (code to delete later).
8. **`max_repeats = 0` means "no indexed children"**; free text still
   permits e.g. `product_detail.7.section_name`. Matches decision 1 of the
   task brief (`0` default, `1` for scalar/structured).
9. **Unified descriptor sub_fields carry an optional `kind`** (set when
   known; absent otherwise). Matches decision 5's `kind?: string`.
10. **TS types: adapters, not literal collapse.** One shared
    `FieldDescriptor` input type family; `SourceField` and
    `RegistryAttribute` remain as their routes' response types (each gains
    `max_repeats`), with small adapters normalizing both into the shared
    shape. Rejected: single literal type (loses response fidelity or pollutes
    the shared type).
11. **Dot-name collision: the opaque literal wins.** A source field
    literally named `a.b` is a scalar: no generated children, its option
    value is the raw name. Real feed fields from ingest never carry
    `sub_fields`, so no generated path can collide; backend keeps the
    existing exact-name-first rule so `parse_indexed_path` is never applied
    to a whole-field mapping key. Pinned by unit test. Rejected: escaping
    (machinery in every consumer, no known real feeds need it).

**Supersession note (answers an earlier "registry grammar only" answer for
the Mapping target side):** the acceptance criterion "identical option lists
in all four pickers" is binding and includes MappingTable's target picker.
All four pickers therefore use the same FieldSelect with the same options.
The "registry grammar only" intent survives in a narrower form: **indexed
children are generated only for `repeated_*` kinds** — scalar and structured
attributes never get indices.

## 4. Backend data model & API surface

### 4.1 `SourceField.max_repeats`

`backend/app/ingest/report.py`: `max_repeats: int = 0`. Semantics: `0` =
not repeated/unknown; `scalar`/`structured` → `1`; `repeated_scalar`/
`repeated_structured` → largest observed array length across all products.

### 4.2 Ingest

- `xml_reader.py::_infer_source_fields`: kind stays first-observed;
  sub-fields stay union (already implemented — regression test only);
  `max_repeats` = `max(len(value))` over all list-valued observations per
  key (`max(existing, current)` per product).
- `flat_notation.py`/`delimited.py`: `ColumnSpec` gains `max_repeats`
  (`repeated_structured` → `arity`; `repeated_scalar` → max observed
  comma-split length across parsed rows, computed in `parse_delimited` after
  `split_row`; `scalar`/`structured`/`generic` → `1`; sub-kind for
  non-repeated → 1).

### 4.3 Mapping document & schemas

`document.py` `to_json`/`from_json` and `SourceFieldOut` carry
`max_repeats` (tolerant read: missing → 0). No document version bump —
additive key; existing stored documents remain valid.

### 4.4 Unified response shape

```
FieldDescriptor = { name: str, kind: str,
                    sub_fields: [{ name: str, kind?: str }],
                    max_repeats: int }
```

- `GET /feed-sources/{id}/fields` → `{ fields: FieldDescriptor[] }`
  (breaking, one-shot). Sub-field kinds: `structured`→`scalar`,
  `repeated_structured`→`repeated_scalar` (mirrors `_SUB_EFFECTIVE_KINDS`).
- `GET /registry/attributes?feed_source_id=N` — unchanged fields plus
  `max_repeats` per attribute, computed per request (§5.3 below).

## 5. Index grammar & backend reassembly

### 5.1 Central utility

`backend/app/mapping/indexed_path.py`:

```python
@dataclass(frozen=True)
class IndexedPath:
    attr: str
    index: int | None   # 1-based
    sub: str | None

def parse_indexed_path(path: str) -> IndexedPath
```

Grammar: `attr` | `attr.N` | `attr.N.sub` | `attr.sub`. Purely syntactic:
a digits-only second segment ⇒ index; otherwise ⇒ sub. `attr.sub` keeps
today's broadcast semantics (index `None`). Rejects index `0` (ValueError).
1-based everywhere in storage/UI (QC grammar alignment); 0-based
translation only inside this utility and its callers — the single authority
(task decision 3).

### 5.2 Mapping validation & apply

- `_validate_mappings` target grammar extends to `attr.N` / `attr.N.sub`
  **only for registry attributes of `repeated_*` kind** (indexed targets on
  scalar/structured still 422 — preserves the superseded decision's intent
  for non-repeated attributes). No index upper bound (free-text
  future-proofing).
- Source-side mapping keys stay `parent` | `parent.sub` (no source indices;
  broadcast semantics unchanged).
- `apply.py::_apply_entry` resolves indexed targets via
  `parse_indexed_path`:
  - `attr.N` on `repeated_scalar` → set/replace element N-1, auto-extending
    with `""`;
  - `attr.N.sub` on `repeated_structured` → `result[attr][N-1][sub]`,
    auto-extending with `{}`;
  - multiple indexed mappings into the same attribute merge by explicit
    index — an extension of `_merge_elementwise` with index addressing
    instead of positional append;
  - out-of-range source reads skip with `shape_mismatches` counting,
    consistent with today.
- Auto-matcher unchanged (broadcast-based); indexed targets are a
  manual/free-text capability.
- **Indexed/broadcast coexistence and precedence (operator directive,
  2026-09-10):** an indexed target mapping (`attr.N`, `attr.N.sub`) may
  coexist with a whole/broadcast claim on the same attribute.
  `_validate_mappings` must not block an indexed sub-path because the
  parent attribute is claimed (kind compatibility still enforced) — in
  either direction (adding an indexed claim over a whole claim, or a
  whole claim over existing indexed ones). Exact duplicate indexed
  targets remain blocked. The existing whole-`attr` vs
  broadcast-`attr.sub` exclusivity for non-indexed targets is unchanged
  (2026-09-03 decision). In `apply_mapping`, precedence is
  deterministic: whole/broadcast target assignments evaluate first,
  indexed assignments second (sorted by target path), so an explicit
  indexed assignment overrides the broadcast value for its specific
  index/sub-field slot. Dedicated tests: `test_field_mapping_api.py`
  (coexistence accepted, compatible kinds) and `test_mapping_apply.py`
  (slot-level override).
- Export renderer: reassembly happens at `apply_mapping` time;
  `render_feed` sees well-formed lists. **Sparse array sanitization
  (operator directive, 2026-09-10):** index-addressed auto-extension must
  never yield empty XML blocks. Verified against current code —
  `_render_attribute` skips `_is_empty` items and `_structured_body`
  suppresses an empty body — so `product_detail = [{}, {},
  {"attribute_value": "Val"}]` renders exactly one `<g:product_detail>`
  containing `<g:attribute_value>Val</g:attribute_value>`, never
  `<g:product_detail></g:product_detail>`. Pinned by a dedicated
  regression test in `test_export_renderer.py` alongside the golden-XML
  end-to-end test.

### 5.3 Registry `max_repeats` derivation

Per request in `routes/registry.py`: for each `repeated_*` attribute, scan
staged products' `processed_data` (fallback `raw_data` when null — QC
precedent) for the feed source and take the max observed list length;
`scalar`/`structured` → 1; no rows / unknown → 0. Feed source existence is
validated (404).

**Query efficiency (operator directive, 2026-09-10):** never load full
`StagingProduct` model instances. Select only the two JSON columns and
stream the result set:

```python
stmt = (
    select(StagingProduct.processed_data, StagingProduct.raw_data)
    .where(StagingProduct.feed_source_id == feed_source_id)
    .execution_options(yield_per=1000)
)
```

Max observed array lengths per repeated attribute are computed during the
stream iteration. This caps memory usage and keeps the endpoint latency
flat on large feeds (no thousands of JSON blobs in memory).

## 6. Plugin runtime semantics for indexed paths

Plugins stay import-isolated: each carries a small local
`parse`/resolve helper (established pattern — the category plugin already
duplicates `resolve_path` rather than importing across plugins). Grammar and
semantics are identical across the three, pinned by mirrored tests.

### 6.1 Shared read semantics

- `attr.N` where value is `list` → element N-1 (`""`/no candidate when out
  of range, matching each plugin's empty semantics).
- `attr.N.sub` where value is `list[dict]` → `list[N-1].get(sub)`.
- Non-indexed paths behave exactly as today (backward compatible for every
  existing config).

### 6.2 Rules plugin (`plugins/core/rules/plugin.py`)

- `_field_value` (conditions) resolves indexed paths per §6.1.
- THEN-actions, index-addressed writes (copy-on-write preserved):
  - `set` `attr.N` → replace/append element N-1 (auto-extend `""`);
    `attr.N.sub` → `result[attr][N-1][sub] = value` (auto-extend `{}`).
  - `append`/`prepend` `attr.N` → string concat onto element N-1
    (auto-extend).
  - `replace` `attr.N[.sub]` → regex-replace within that element.
  - `remove`/`clear` `attr.N` → pop/clear element N-1; `attr.N.sub` →
    delete sub-key from element N-1 (missing element/key = no-op, as today).
- Non-indexed fields: byte-identical behavior (existing
  `test_rules_plugin.py` passes unchanged).
- Registry-unknown sub-fields written by rules: harmless garbage in
  `processed_data`; the renderer iterates registry sub-fields only, so
  invented sub-fields never export — consistent with the lenient-TSV
  precedent. Noted as accepted behavior.

### 6.3 Filter plugin

`evaluate_condition`'s `product.get(field)` becomes resolver-based (indexed
reads only; conditions never write). `attr.N` on `list` compares element
N-1 as text.

### 6.4 Labelizer (custom_labels)

`resolve_path` gains the indexed branches — `matchField =
product_detail.2.attribute_value` matches that exact element instead of
today's ambiguous→empty dead end. `_product_field_candidates` in
`routes/products.py` (the documented "keep in sync" mirror) is updated in
lockstep, with a sync test.

## 7. Frontend

### 7.1 Types & adapters

- `api/types.ts`: `FieldDescriptor = { name: string; kind: string;
  sub_fields: { name: string; kind?: string }[]; max_repeats: number }`;
  `SourceField` gains `max_repeats: number` (default 0 when absent);
  `RegistryAttribute` gains `max_repeats: number`; registry sub-fields gain
  optional `kind`.
- `api/fieldOptions.ts`: `fromSourceFields(SourceField[]): FieldDescriptor[]`
  and `fromRegistryAttributes(RegistryAttribute[]): FieldDescriptor[]`
  adapters + `buildFieldOptions(fields: FieldDescriptor[], opts?)`.

### 7.2 `buildFieldOptions(fields, { includeParent = true })`

→ `{ group: string; items: { value: string; label: string }[] }[]`

- scalar → group **"Field"**, item `name`;
- `structured` → group `name`: parent (if includeParent) + `attr.sub`
  items (label = sub name);
- `repeated_scalar` → group `name`: parent + `attr.i` items (label `#i`),
  `i = 1..max_repeats`;
- `repeated_structured` → group `name`: parent + `attr.i.sub` items (label
  `#i · sub`);
- `max_repeats = 0` → no children; free text still allows `attr.7`;
- collision rule: values dedupe by full path; a literal dotted field name
  (never expanded — no sub_fields/children) wins over a same-valued
  generated path; pinned by unit test;
- one nesting level only (Mantine group limit); item label encodes index +
  sub-field (`#1 · section_name`); value is always the full dot path.

### 7.3 `components/FieldSelect.tsx`

Generalizes the accepted Combobox+InputBase pattern: grouped options from
`buildFieldOptions`, custom filter (matches value path OR label OR group),
free-text submit ("use custom value …" hint; new shared i18n keys, en+de),
optional clear (emits `onChange('')`), label/description/placeholder/
disabled/error/size/width passthrough. Input shows the stored dot-path
value. No local duplicate option-building.

**Client-side syntax validation of free text (operator directive,
2026-09-10):** custom values are validated before submission against the
canonical path grammar (mirrors the backend `parse_indexed_path` rules —
1-based indices only):

```typescript
export const INDEXED_PATH_REGEX =
  /^[a-z_][a-z0-9_]*(\.([1-9]\d*))?(\.[a-z_][a-z0-9_]*)?$/;
```

A malformed custom value (e.g. `product_detail.0.attribute_name`) is not
submitted; an inline validation message is shown instead (e.g. "Indices
are 1-based (e.g. .1, .2)" — new shared i18n key, en+de), so a malformed
value can never reach the backend and produce a 422. The regex lives in
`fieldOptions.ts` next to `buildFieldOptions` (single client-side
authority, unit-tested there).

### 7.4 Hooks

- `useFeedSourceFields` returns `{ fields: FieldDescriptor[] }` (one-shot
  cutover).
- `useRegistryAttributes(feedSourceId?)` — optional param; query key
  `['registry', 'attributes', id]` when present, existing key otherwise
  (shared namespace, no duplicate caching).
- **Cache invalidation (operator directive, 2026-09-10):** any action that
  mutates feed products or reruns the pipeline (ingest completion, mapping
  run, dry-run, plugin apply, trigger-run) must invalidate the
  `['registry', 'attributes']` **prefix** so every feed-scoped instance
  refreshes without a page reload:

  ```typescript
  await queryClient.invalidateQueries({ queryKey: ['registry', 'attributes'] });
  ```

  Concretely: `useTriggerRun` and `useDryRun` (and any future run-triggering
  mutation) gain this invalidation alongside their existing ones; a hooks
  test asserts the prefix invalidation fires.

### 7.5 Data-source alignment

The four pickers switch to **`useRegistryAttributes(feedSourceId)`** —
their plugins resolve registry paths on the *mapped* product, so
registry-with-feed-context is the correct universe, and it is what makes the
lists literally identical across all four. `useFeedSourceFields` remains
for its two raw-data consumers (ProductsPage, RuleValuesEditor).

### 7.6 Migrations (each removes its own option-building logic)

1. `MappingTable.tsx` — parent + sub-row target Selects → FieldSelect fed
   by `buildFieldOptions(fromRegistryAttributes(...))` with feed context;
   `buildTargetOptions` + grouping code deleted.
2. `MatchFieldCombobox.tsx` — thin wrapper around FieldSelect (keeps its
   label/hint i18n); `groups` useMemo deleted.
3. `RulesUI.tsx`/`RuleEditor.tsx` — `fields: string[]` prop → options from
   `useRegistryAttributes(scope.feedSourceId)` built once in RulesUI;
   RuleEditor's `fieldData` mapping deleted; all when/then pickers use
   FieldSelect (indexed writes per §6.2).
4. `FilterUI.tsx` — condition-field Selects → FieldSelect, same source;
   `fieldData` deleted.

### 7.7 Out-of-scope call sites (mechanical only)

- `ProductsPage.tsx`: `fieldsQuery.data?.fields ?? []` →
  `(fieldsQuery.data?.fields ?? []).map((d) => d.name)`.
- `RuleValuesEditor.tsx` (explicitly untouched semantics): same mechanical
  mapping applied to its `fieldOptions` memo; `PREVIEW_DEFAULT_FIELDS` set
  and preview logic unchanged.

## 8. Breaking-change coordination

`GET /feed-sources/{id}/fields` response changes `{fields: string[]}` →
`{fields: FieldDescriptor[]}` in the same cycle as the frontend hook
rework (one-shot cutover, user decision). Consumers: the four pickers
(migrated), ProductsPage + RuleValuesEditor (mechanical adaptation). The
registry route is additive (optional query param + new field), so its other
consumers (MappingTab, category RulesTab, PluginPage tests) stay green
without `max_repeats` until they opt in.

## 9. Documentation & decisions entries

- `docs/decisions.md` (same commit as the code):
  1. indexed path grammar (1-based, `attr.N[.sub]`, QC-grammar alignment,
     `parse_indexed_path` single authority) **superseding** the 2026-08-28
     "positional paths rejected" decision;
  2. sub-field union clarification (already implemented; only kind
     inference is first-observed) — correcting the task premise;
  3. `/feed-sources/{id}/fields` breaking reshaping + one-shot cutover;
  4. registry route optional `feed_source_id` + per-request `max_repeats`;
  5. supersession of the "registry grammar only" answer by the
     identical-lists acceptance criterion.
- `backend/docs/architecture.md`, `backend/docs/api.md`: unified descriptor
  shape, indexed target grammar, per-request registry `max_repeats`.
- `frontend/docs/architecture.md`: `fieldOptions.ts` + `FieldSelect` as the
  shared field picker; data-source alignment rationale.

## 10. Test strategy (RED→GREEN per step)

Backend:
- `max_repeats` in `test_source_fields.py` / `test_delimited_reader.py` /
  `test_xml_reader.py` (fixture: products with varying `product_detail`
  lengths);
- union-sub-fields regression test (first item missing keys later items
  have);
- `test_field_mapping_api.py`: indexed-target validation (accept on
  `repeated_*`, still-reject on scalar/structured) **plus the
  coexistence test** (whole/broadcast claim + indexed claim on the same
  attribute accepted when kinds compatible — operator directive 5);
- `test_mapping_apply.py`: index reassembly incl. sparse/auto-extend/
  out-of-range **plus the precedence test** (indexed assignment overrides
  the broadcast value for its slot — operator directive 5);
- golden-XML in `test_export_renderer.py`: `product_detail.N.section_name`
  mappings → clean `<g:product_detail>` blocks (no flat/wrong nesting),
  **plus the sparse-sanitization regression test** (`[{}, {},
  {"attribute_value": "Val"}]` → exactly one non-empty
  `<g:product_detail>` block, zero empty blocks — operator directive 2);
- plugin tests: rules indexed read+write, filter indexed reads, labelizer
  indexed matchField, `_product_field_candidates` sync test;
- route tests: both new response shapes (`test_registry_api.py`, new
  `test_feed_fields_api.py`), and the registry `max_repeats` scan uses
  the column-only `yield_per` statement (asserted via the statement's
  execution options / by test inspection — operator directive 1).

Frontend:
- new `fieldOptions.test.ts` (scalar, structured, repeated_scalar,
  repeated_structured, 0-repeats, dot-name collision, and the
  `INDEXED_PATH_REGEX` accept/reject table incl. `.0` rejection —
  operator directive 4);
- new `FieldSelect.test.tsx` (grouping, filter, free-text, clear, and the
  inline 1-based validation message on malformed custom input);
- updated `MappingTable.test.tsx`, `CustomLabelsUI.test.tsx`,
  `RulesUI.test.tsx`, `FilterUI.test.tsx`, `hooks.m10c.test.tsx`, plus the
  two mechanical call-site fixtures;
- hooks test asserting the `['registry', 'attributes']` prefix
  invalidation on run-triggering mutations (operator directive 3).

Gates: `uv run ruff check .` (no new errors vs baseline), `uv run mypy .`,
`uv run pytest -n auto`, `npm run test`, `npm run typecheck`,
`npm run build`.

## 11. Implementation order (TDD, RED→GREEN)

1. Backend ingest: `max_repeats` (report, XML reader, delimited/flat
   notation) + union regression test.
2. Backend document/schema `max_repeats` + registry route
   (`?feed_source_id`, per-request `max_repeats`).
3. Backend `/feed-sources/{id}/fields` unified shape (breaking tests
   updated; ProductsPage/RuleValuesEditor mechanical fixes ride along to
   keep the tree green).
4. Backend `indexed_path.py` + mapping validation + apply reassembly +
   golden XML; plugin read/write semantics (rules, filter,
   custom_labels, products.py mirror).
5. Frontend types/adapters + `fieldOptions.ts` + unit tests.
6. Frontend `FieldSelect.tsx` + component test.
7–10. Migrations: MappingTable → MatchFieldCombobox → RulesUI/RuleEditor →
   FilterUI (option-building code deleted in each).
11. Full gates + docs/decisions updates.

Sequencing deviations vs the task's 11-step list, both deliberate: step 4
bundles the brief's steps 3–4 (the indexed-path utility lands before the
breaking route work finishes so validation is complete rather than
half-covered), and the two mechanical call-site fixes ride with step 3's
hook change to keep the tree green throughout.

## 12. Acceptance criteria

- All four UI locations show identical option lists for the same feed
  (same groups, sub-fields, indices).
- `product_detail.1.section_name` … `product_detail.<max_repeats>.
  attribute_value` and `additional_image_link.1` … `.<max_repeats>` are
  selectable in all four pickers.
- Scalar top-level fields appear under the group "Field".
- An indexed path selected/created via the UI results in a correctly
  structured `<g:product_detail>` block in the export XML (golden-XML
  test).
- None of the four migrated files retains its own options-building/
  dot-path logic.
- `RuleValuesEditor.tsx` / `RuleCard.tsx` semantics unchanged (only the
  mechanical response-shape adaptation).
