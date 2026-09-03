# Nested Source Sub-Field Mapping — Design

Date: 2026-09-03
Status: approved (user), pending implementation plan

## 1. Problem

The field-mapping interface currently maps whole source fields to whole
GMC attributes (`attr`) or to a single sub-field of a structured attribute
(`attr.subfield`). Two real-world needs are unsupported:

1. **Splitting a source struct across different GMC attributes.** A source
   field like `product_detail` (struct with `name`, `value`, `id`) may need
   `product_detail.name` → `title`-like scalars and `product_detail.id` →
   `item_group_id`, with each sub-field going to a different attribute.
2. **Cherry-picking / renaming sub-fields within the matching attribute.**
   A source `ship` struct with sub-fields `{country, price, service}` may
   need `ship.country` → `shipping.country` and `ship.price` →
   `shipping.price` while `service` is dropped — instead of relying on
   registry-known-sub-field filtering of the whole struct.

Today a structured source field can only be mapped whole-struct →
whole-attribute.

## 2. Scope decisions (confirmed with operator)

- **Source-side only.** Target grammar stays exactly as today: `attr` or
  `attr.subfield`. Full §5.7 positional target paths (`shipping.1.price`,
  `product_highlight.2`) are **out of scope** for this change.
- **Both use cases** (splitting across attributes AND sub-field
  cherry-picking) are in scope.
- **Exclusivity:** a whole-struct mapping (`ship → shipping`) and sub-field
  mappings (`ship.price → …`) are mutually exclusive for the same source
  field. Struct OR its sub-fields, never both.
- **Auto-mapper is extended** to match source sub-fields (not manual-only).
- **Repeated structured sources broadcast:** a sub-field mapping applies to
  every element of a repeated structured source. No positional source
  addressing (`ship.2.price`) in this change.
- **UI: expandable rows** in the existing mapping table; structured source
  field rows expand to reveal one row per sub-field, each with its own
  target Select.

## 3. Chosen representation — Approach A: dotted source keys

`MappingDocument.mappings` keys become source **paths**:
`"ship.price": {"target": "shipping.price", "origin": "manual"}`.

- No document schema change: mapping keys are already opaque strings;
  `from_json` / `to_json` in `backend/app/mapping/document.py` are
  untouched; document version stays 1; no DB migration; the
  `FieldMappingPut` payload shape (`{source: {target}}`) is unchanged.
- **Disambiguation rule** (for pathological names, e.g. a TSV column
  literally named `ship.price`): a mapping key that **exactly equals a
  source field name** is a whole-field mapping; only otherwise is the key
  resolved as `parent.sub`. This ordering is applied consistently in
  validation, apply, and the auto-matcher.

Rejected alternatives:

- **B — nested entry structure** (`MappingEntry.sub_mappings`): structurally
  explicit, no ambiguity, but requires a document version bump, v1→v2
  migration in `from_json`, changes to `to_json` and the PUT payload, and
  touches all 33 `MappingEntry` call sites for the same behavior.
- **C — parallel `sub_mappings` section**: no key ambiguity, but every
  consumer must cross-check both sections; exclusivity becomes a
  cross-dict rule; more API surface without structural clarity gained.

## 4. Backend changes

### 4.1 Validation — `backend/app/routes/field_mapping.py::_validate_mappings`

For each mapping key that is not an exact source-field name:

1. Split on the **first** dot: `parent, _, sub = key.partition(".")`. The
   key must have exactly one dot; anything else → 422
   `"{source}: invalid source path"`.
2. `parent` must be a source field with kind `structured` or
   `repeated_structured`; otherwise 422
   `"{source}: {parent!r} is not a structured source field"`.
3. `sub` must be in `parent.sub_fields`; otherwise 422
   `"{source}: unknown sub-field {sub!r} on {parent!r}"`.
4. **Exclusivity:** if a whole-field mapping for `parent` also exists → 422
   `"{source}: conflicts with whole-field mapping {parent!r}"`.
5. Target grammar unchanged: `attr` or `attr.subfield` (≤2 segments),
   registry-known attribute and sub-field, duplicate-target claim check
   exactly as today.
6. **Kind compatibility** — effective source kind for the compat check
   against `_COMPATIBLE_KINDS`:
   - sub of `structured` → behaves as `scalar`
   - sub of `repeated_structured` → behaves as `repeated_scalar`
   Target kind rules are unchanged (a scalar-typed value cannot target a
   structured attribute, etc. — a sub-field source value is a string, so
   it targets `scalar` attributes or `attr.subfield` of structured
   attributes).
7. 422 response shape unchanged (`{"errors": [...]}` with per-source
   `"key: message"` entries) so `parseRowErrors` in the frontend continues
   to work.

### 4.2 Apply — `backend/app/mapping/apply.py::apply_mapping`

Sub-path key resolution (exact-name-first, same rule):

- Parent value is a dict → sub value is `value.get(sub)`; a `str` flows
  through; an **absent** (`None`) or non-str value is **skipped** (no
  output, no error) per §5.7 read semantics.
- Parent value is a list (repeated structured) → sub value is the per-
  element list `[elem.get(sub) for elem in value]`; each element must be a
  dict (else `shape_mismatch` for the affected product); per-element
  absent (`None`) sub values are **skipped** (that element contributes
  nothing to the merge); non-str values count as `shape_mismatch`.

Target merge semantics:

| Effective sub value | Target | Result |
|---|---|---|
| `str` | `attr` (scalar) | `result[attr] = value` (as today) |
| `str` | `attr.subfield` | `result[attr][subfield] = value` |
| `list[str]` (repeated source) | `attr` (repeated_scalar) | `result[attr] = value` (as today) |
| `list[str]` (repeated source) | `attr.subfield` (of structured attr) | **element-wise merge**: `result[attr][i][subfield] = v[i]`, auto-extending `result[attr]` (intermediate slots stay absent); multiple sub-mappings into the same repeated attribute merge by index; sparse elements are left absent |

- When **any** sub-key of a parent is mapped, the parent itself no longer
  counts as `dropped_unmapped` (only unmapped keys do). Unmapped parent
  structs are dropped exactly as today.
- Empty/absent sub values: skipped (no output), not an error — matching
  §5.7 "reading a non-existent position yields empty, not an error".
- `shape_mismatches` accounting extended to cover sub-value shape errors.
- `ApplyStats` fields unchanged.

### 4.3 Auto-mapper — `backend/app/mapping/matcher.py::auto_match`

Second pass over source fields with kind `structured` or
`repeated_structured`:

- Each sub-field name is normalized and matched against the registry
  exactly like whole fields (case-insensitive, separator-insensitive;
  **no sub-level synonyms in v1**): first against whole attribute names
  (`ship.country` → `country`-named scalar attr), then against
  `attr.subfield` paths whose sub-field matches (`ship.price` →
  `shipping.price`). Ambiguity between the two resolution orders resolves
  to the whole-attribute match, mirroring the exact-name-first rule.
- Matches produce `parent.sub → attr` or `parent.sub → attr.subfield`
  entries with origin `auto`.
- Sub-matching only proposes targets whose grammar is compatible with the
  effective sub kind (`scalar` / `repeated_scalar` behavior per §4.1).
- **Exclusivity respected:** a whole-field mapping for the parent (manual
  or auto) suppresses the sub pass for that parent; existing manual
  sub-mappings block auto whole-field mapping of the parent.
- Existing `existing=` preserve-manual semantics carry over unchanged.

## 5. Frontend changes

### 5.1 `frontend/src/features/setup/MappingTable.tsx`

- Rows for source fields with kind `structured` / `repeated_structured`
  and non-empty `sub_fields` render an expand chevron (Mantine
  `UnstyledButton` + `IconChevronDown`/`IconChevronRight`, aria-expanded).
- Expanded state renders one indented sub-row per `sf.sub_fields`:
  sub-field name + `scalar`/`repeated_scalar` kind badge, own target
  Select (existing option list), same error/origin badge treatment.
- Scalar rows unchanged.
- **UI exclusivity:** choosing a target on a sub-row clears the parent's
  target; choosing a target on the parent row clears all of its sub-row
  targets. (Backend remains the authority; the UI avoids sending
  conflicting payloads.)
- Sub-row keys are the dotted paths (`ship.price`), identical to the
  mapping keys — `localEdits` and `parseRowErrors` in `MappingTab.tsx`
  work unchanged (422 messages split on first colon as today).
- `coveredTargets` logic in `MappingTab.tsx` already handles dotted
  targets (`attr.sub` covers `attr`); no change needed there.

### 5.2 Types — `frontend/src/api/types.ts`

- No type changes (`SourceField.sub_fields: string[]` already present;
  `MappingEntry`/`FieldMappingDoc` unchanged).

### 5.3 i18n

- New keys in the `setup` namespace for: expand/collapse sub-fields
  (aria-labels), sub-row kind badges if labeled, exclusivity hint text.
  Translations for every language already shipped in the i18n setup.

## 6. Testing

Backend (`uv run pytest -n auto` from `backend/`):

- `test_mapping_apply.py` — new cases: dict sub extraction; repeated
  broadcast; element-wise merge into `attr.subfield` with auto-extend;
  multiple sub-mappings merging by index; sub mapped ⇒ parent not
  `dropped_unmapped`; sub shape mismatch counting; exact-name-wins
  disambiguation.
- `backend/tests/test_field_mapping_api.py` — 422 cases: unknown parent, non-structured parent,
  unknown sub-field, two-dot source path, exclusivity conflict; success
  cases: sub→scalar attr, sub→attr.subfield, save + reload round-trip
  with dotted keys.
- `test_mapping_matcher.py` — sub-pass matching, normalization, no
  sub-level synonyms, exclusivity suppression both directions.

Frontend (`npm run test`, `npm run typecheck` from `frontend/`):

- `MappingTable.test.tsx` — expandable rows render sub-rows; per-sub
  Select; exclusivity clear behavior.
- `MappingTab.test.tsx` — save payload includes dotted keys; 422 errors
  map to sub-rows.

## 7. Documentation (same commit)

- `backend/docs/architecture.md` — mapping stage: nested source paths,
  disambiguation rule, exclusivity.
- `backend/docs/api.md` — `PUT /feed-sources/{id}/field-mapping`: dotted
  source keys, validation rules.
- `docs/decisions.md` — record the dotted-key decision and rejected
  alternatives B/C.
- `gmc-feed-engine-spec.md` — no change (spec §5.7/§6 already permit
  sub-field addressing in the path grammar; this design extends the
  implemented subset without contradicting it). Any doc/spec conflict
  found during implementation is flagged to the operator, per AGENTS.md.

## 8. Out of scope (explicit)

- Positional target paths (`shipping.1.price`) and wildcards (§5.7
  v1.1).
- Positional source addressing (`ship.2.price`).
- Sub-level synonyms in the auto-matcher.
- Mapping templates (spec §6: none, permanently).
- Document format migration (none needed).
