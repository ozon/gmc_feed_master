# Mapping UI: Button-Only Auto-Mapper & Custom Source Fields — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the auto-mapper button-triggered only (no implicit automatch anywhere) and let operators add/remove custom source fields mapped to any registry target kind from the Mapping UI.

**Architecture:** Two backend changes — (1) delete the implicit `auto_match` blocks in `MappingStep` and `run_dry_run` so stored mappings are the only input to pipeline/dry-run mapping; (2) add a `custom_fields: list[str]` member to `MappingDocument` with full-replace PUT semantics and validation. Frontend: extend `MappingTab`/`MappingTable` with custom rows, an add-custom row, remove controls, and shadow indicators for observed/custom overlap.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async (backend), React 19 + Mantine + TanStack Query + vitest/RTL (frontend).

**Design spec:** `docs/superpowers/specs/2026-09-11-mapping-ui-button-only-automap-and-custom-fields-design.md`

## Global Constraints

- Custom-field name grammar: `^[a-z_][a-z0-9_]*$`, max length 64 (spec §4.1).
- `custom_fields` is additive on the document — NO version bump, NO migration/backfill (operator directive: feed sources are recreated from scratch).
- PUT is full-replace on `custom_fields` (like `mappings`).
- Custom mapping source keys must be flat (no dots). Dotted sources keep today's observed-parent rules (spec §4.2 rule 5).
- Flat mapping source keys must be in observed ∪ custom after this change (closes today's lenient fallthrough — spec §4.2 rule 4).
- A custom field name matching a `_BASELINE_FIELDS` entry (e.g. `title`, `id`) is PERMITTED and accepted — documented as accepted behavior, not a bug (implementation directive item 4).
- `POST /field-mapping/auto` must round-trip `custom_fields` unchanged (directive item 3).
- Backend gates: `uv run ruff check .` (no new errors vs `docs/ruff-baseline.txt` count 506), `uv run mypy .` (exit 0), `uv run pytest -n auto`. Frontend gates: `npm run test`, `npm run typecheck`, `npm run build`.
- Backend tests needing DB use the `isolated_database_url` fixture; async tests marked `@pytest.mark.asyncio` explicitly.
- All commands run from `backend/` or `frontend/` respectively.
- Commit docs updates in the same commit as the behavior change they describe.
- No comments in code unless replicating an existing documented pattern (the baseline-collision comment in Task 6 is explicitly required by the directive).

---

### Task 1: `MappingDocument.custom_fields` — model + round-trip

**Files:**
- Modify: `backend/app/mapping/document.py`
- Test: `backend/tests/test_mapping_document.py`

**Interfaces:**
- Produces: `MappingDocument.custom_fields: list[str]` (dataclass field, default `[]`); `to_json()` emits `"custom_fields": [...]` always; `from_json()` reads it tolerantly (missing → `[]`, corrupt → `MappingDocumentError`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_mapping_document.py`:

```python
def test_custom_fields_default_empty():
    doc = MappingDocument.empty()
    assert doc.custom_fields == []


def test_custom_fields_roundtrip():
    doc = MappingDocument.from_json({
        "version": 1,
        "auto_mapped": False,
        "source_fields": [],
        "mappings": {},
        "custom_fields": ["my_field", "other_field"],
    })
    assert doc.custom_fields == ["my_field", "other_field"]
    out = doc.to_json()
    assert out["custom_fields"] == ["my_field", "other_field"]


def test_custom_fields_missing_key_defaults_to_empty():
    doc = MappingDocument.from_json({
        "version": 1,
        "auto_mapped": False,
        "source_fields": [],
        "mappings": {},
    })
    assert doc.custom_fields == []


def test_custom_fields_always_emitted():
    doc = MappingDocument.empty()
    out = doc.to_json()
    assert out["custom_fields"] == []


def test_custom_fields_non_list_raises():
    with pytest.raises(MappingDocumentError, match="custom_fields"):
        MappingDocument.from_json({
            "version": 1,
            "auto_mapped": False,
            "source_fields": [],
            "mappings": {},
            "custom_fields": "my_field",
        })


def test_custom_fields_non_string_entry_raises():
    with pytest.raises(MappingDocumentError, match="custom_fields"):
        MappingDocument.from_json({
            "version": 1,
            "auto_mapped": False,
            "source_fields": [],
            "mappings": {},
            "custom_fields": ["ok_name", 42],
        })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_mapping_document.py -k custom_fields -v`
Expected: 6 FAIL (AttributeError: `custom_fields` / KeyError in assertions)

- [ ] **Step 3: Implement in `document.py`**

In the `MappingDocument` dataclass, add after `mappings`:

```python
    custom_fields: list[str] = field(default_factory=list)
```

In `from_json`, pass through parsing (add after the `mappings=` line in the `cls(...)` call):

```python
            custom_fields=_parse_custom_fields(raw.get("custom_fields", [])),
```

In `to_json`, add after the `"mappings"` entry:

```python
            "custom_fields": list(self.custom_fields),
```

Add the parser at module level (after `_parse_mappings`):

```python
def _parse_custom_fields(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise MappingDocumentError(
            f"'custom_fields' must be a list, got {type(raw).__name__}"
        )
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise MappingDocumentError(
                f"'custom_fields' entries must be strings, got {type(item).__name__}"
            )
        result.append(item)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_mapping_document.py -v`
Expected: all PASS (existing + 6 new)

- [ ] **Step 5: Check the existing round-trip test still passes and run gates**

Run: `cd backend && uv run pytest tests/test_mapping_document.py tests/test_mapping_step.py -q`
Expected: PASS (note: `test_mapping_step` still passes here — its `to_json` snapshots lack `custom_fields`; it asserts specific keys not full equality for `source_fields`, and `mappings` equality only — verify no exact-doc equality assertions break; if `test_m4_acceptance.py` doc comparisons break here, they are updated in Task 2)

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/mapping/document.py tests/test_mapping_document.py
git commit -m "feat: custom_fields member on MappingDocument with tolerant parsing"
```

---

### Task 2: D1 — remove implicit automatch from `MappingStep`

**Files:**
- Modify: `backend/app/pipeline/steps.py:114-135` (the `MappingStep.execute` DB block)
- Test: `backend/tests/test_mapping_step.py`

**Interfaces:**
- Produces: `MappingStep` no longer calls `auto_match`, never writes `doc.mappings` or `doc.auto_mapped`; still refreshes `doc.source_fields` and persists the document.

- [ ] **Step 1: Update the failing test (RED — invert existing expectation)**

In `backend/tests/test_mapping_step.py`, replace `TestFirstIngestion.test_auto_maps_persists_and_applies` with:

```python
class TestFirstIngestion:
    @pytest.mark.asyncio
    async def test_no_implicit_automap_persists_source_fields_only(self, registry):
        source_fields = [
            SourceField("id", "scalar"),
            SourceField("title", "scalar"),
            SourceField("ean", "scalar"),
            SourceField("margin", "scalar"),
        ]
        products = [{"id": "1", "title": "Shirt", "ean": "123", "margin": "10"}]
        run_state = RunState(products=products, source_fields=list(source_fields))
        feed_source = _feed_source()

        result = await MappingStep(registry).execute(_ctx(feed_source, run_state))

        assert feed_source.field_mapping["auto_mapped"] is False
        assert feed_source.field_mapping["mappings"] == {}
        assert feed_source.field_mapping["source_fields"] == [
            {"name": "id", "kind": "scalar", "sub_fields": [], "max_repeats": 0},
            {"name": "title", "kind": "scalar", "sub_fields": [], "max_repeats": 0},
            {"name": "ean", "kind": "scalar", "sub_fields": [], "max_repeats": 0},
            {"name": "margin", "kind": "scalar", "sub_fields": [], "max_repeats": 0},
        ]
        # unmapped products pass through unmapped (all keys dropped)
        assert run_state.products == [{}]
        assert result.processed_count == 1
        assert result.failed_count == 0
        assert result.statistics["mapping"]["dropped_unmapped_fields"] == 4

    @pytest.mark.asyncio
    async def test_stored_mappings_applied_without_automatch(self, registry):
        existing = {
            "version": 1,
            "auto_mapped": False,
            "mappings": {"ean": {"target": "gtin", "origin": "manual"}},
            "custom_fields": [],
        }
        feed_source = _feed_source(field_mapping=existing)
        run_state = RunState(
            products=[{"id": "1", "ean": "123"}],
            source_fields=[SourceField("id", "scalar"), SourceField("ean", "scalar")],
        )

        await MappingStep(registry).execute(_ctx(feed_source, run_state))

        # mappings and auto_mapped untouched by the run
        assert feed_source.field_mapping["auto_mapped"] is False
        assert feed_source.field_mapping["mappings"] == {
            "ean": {"target": "gtin", "origin": "manual"}
        }
        assert run_state.products == [{"gtin": ["123"]}]

    @pytest.mark.asyncio
    async def test_missing_feed_source_raises(self, registry):
        with pytest.raises(LookupError, match="feed source"):
            await MappingStep(registry).execute(_ctx(None))
```

Note: the `to_json` output now includes `"custom_fields": []` — the exact-dict assertions on `source_fields`/`mappings` keys are unaffected (they index keys, not the whole doc). The `_feed_source()` default `{}` parses via `from_json(None)` → `empty()` → `custom_fields == []`.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_mapping_step.py -v`
Expected: the two new tests FAIL (current code flips `auto_mapped` to True and fills mappings)

- [ ] **Step 3: Remove the implicit block in `steps.py`**

In `backend/app/pipeline/steps.py`, `MappingStep.execute`, replace:

```python
                doc = MappingDocument.from_json(feed_source.field_mapping)
                if not doc.auto_mapped:
                    doc.mappings = auto_match(
                        ctx.run_state.source_fields,
                        self._registry,
                        existing=doc.mappings,
                    )
                    doc.auto_mapped = True
                doc.source_fields = list(ctx.run_state.source_fields)
                feed_source.field_mapping = doc.to_json()
```

with:

```python
                doc = MappingDocument.from_json(feed_source.field_mapping)
                doc.source_fields = list(ctx.run_state.source_fields)
                feed_source.field_mapping = doc.to_json()
```

Then remove the now-unused import — in `steps.py` line 19 change:

```python
from ..mapping import MappingDocument, apply_mapping, auto_match
```

to:

```python
from ..mapping import MappingDocument, apply_mapping
```

- [ ] **Step 4: Run the mapping-step tests**

Run: `cd backend && uv run pytest tests/test_mapping_step.py -v`
Expected: all PASS

- [ ] **Step 5: Audit task 1 (directive item 1) — find every test relying on implicit automatch**

Run the audit greps (documenting each hit — these are ALL the hits, verified):

```bash
cd backend && grep -rn "auto_match\|auto_mapped" tests/ --include="*.py" | grep -v pycache
```

Verified hits and their disposition (each gets updated in this step):

1. `tests/test_m4_acceptance.py::test_field_mapping_end_to_end` — asserts `doc["auto_mapped"] is True`, auto/synonym origins, and mapped captured products after a first run. **Inverted**: becomes a pre-seeded-mapping e2e (seed manual mappings via PUT before the first run, assert they are preserved and applied). See Step 5a.
2. `tests/test_mapping_step.py` — handled in Steps 1–4.
3. `tests/test_dry_run_api.py` — all 5 dry-run tests call the endpoint on a fresh feed (no mappings). `sample[0]["id"] == "SKU-1"`, `processed == 3`, plugin-drop `product_id == "drop-me"`, and `baseline_required` findings all implicitly assumed automatch. **Inverted**: fixtures now seed explicit mappings before the dry-run POST. See Step 5b.
4. `tests/test_m6_acceptance.py::test_end_to_end_execution_through_runner`, `::test_error_isolation_preserves_last_known_good`, `::test_drop_then_pass_reactivation` — TSV is `sku/title/ean`; plugin keys on `id`/`title`; staging asserts `processed_data["title"] == "RED SHIRT"` and `product_id` lookups. These need mappings present. **Fixed** by pre-seeding `field_mapping` with the identity mappings on the feed source before `runner.execute`. See Step 5c.
5. `tests/test_custom_labels_plugin.py` (hash-stability e2e) — TSV `sku/title/ean`, plugin matchField `id`, staging keyed by `A1`. Pre-seed mappings like 5c. See Step 5d.
6. `tests/test_m3_acceptance.py` — TSV columns are `id/title/price`; registry has identity `id`,`title` attributes; captured products assert **raw** keys (`price` unmapped stays in payload? No — captured asserts `{"id", "title", "price"}` dicts). Actually `id`/`title` are registry attributes, `price` is not (registry has `price`? verified: registry `price` exists as scalar). Captured dicts showing `price: "19.99"` prove capture happens on **mapped** products where `price` maps to `price`. **Fixed** by pre-seeding identity mappings (`id→id`, `title→title`, `price→price`) before each runner execute. See Step 5e.
7. `tests/test_m4_acceptance.py::test_field_mapping_end_to_end` — covered in 1.
8. `tests/test_feed_fields_api.py`, `tests/test_field_mapping_api.py`, `tests/test_mapping_document.py`, `tests/test_mapping_matcher.py`, `tests/test_example_feed_chain.py` — do NOT run pipelines (matcher/direct calls or seeded docs only). No implicit-automatch reliance. No change.
9. `tests/test_pipeline_steps.py`, `tests/test_pipeline_runner.py` — use stub steps/`RecordingStep`, never `MappingStep` against real docs. No change.

- [ ] **Step 5a: Update `test_m4_acceptance.py::test_field_mapping_end_to_end`**

Replace the body between `fs_id = await _seed_feed_source(factory)` and the first `runner.execute` with:

```python
    # Pre-provision manual mappings via the API (button-only automap: the
    # pipeline never auto-matches anymore).
    client = await logged_in_client(app_factory)
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={
            "mappings": {
                "sku": {"target": "id"},
                "title": {"target": "title"},
                "ean": {"target": "gtin"},
            }
        },
    )
    assert resp.status_code == 200

    capture = CaptureProductsStep()
    runner = _build_runner(factory, capture, tmp_path)
    run_id = await runner.execute(fs_id)
```

And change the two `doc` assertions to reflect manual origins and no automap flip:

```python
    doc = await _get_field_mapping(factory, fs_id)
    assert doc["auto_mapped"] is False
    assert [field["name"] for field in doc["source_fields"]] == [
        "sku",
        "title",
        "ean",
        "margin",
    ]
    assert doc["mappings"] == {
        "sku": {"target": "id", "origin": "manual"},
        "title": {"target": "title", "origin": "manual"},
        "ean": {"target": "gtin", "origin": "manual"},
    }
```

Delete the mid-test PUT block (it is now the pre-seed above) and keep the rerun section, changing its final `doc` assertion `auto_mapped` to `False` and origins to `"manual"` (they already are, since the stored doc is what the rerun reads).

- [ ] **Step 5b: Update `tests/test_dry_run_api.py` — seed mappings in `_make_feed`**

Change `_make_feed` to seed explicit mappings right after creating the feed (the WIDE_TSV columns are registry attribute names already):

```python
async def _make_feed(client, source_url="http://source.example/feed.tsv"):
    client_id = (await client.post("/clients", json={"name": "Acme"})).json()["id"]
    feed = (await client.post(f"/clients/{client_id}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv",
                                    "source_url": source_url, "currency": "USD"})).json()
    resp = await client.put(
        f"/feed-sources/{feed['id']}/field-mapping",
        json={"mappings": {
            "id": {"target": "id"},
            "title": {"target": "title"},
            "description": {"target": "description"},
            "link": {"target": "link"},
            "image_link": {"target": "image_link"},
            "availability": {"target": "availability"},
            "price": {"target": "price"},
            "condition": {"target": "condition"},
            "brand": {"target": "brand"},
            "gtin": {"target": "gtin"},
        }},
    )
    assert resp.status_code == 200
    return feed["id"]
```

All existing dry-run assertions (`sample[0]["id"] == "SKU-1"`, plugin `drop-me` drop, `baseline_required` findings) stay green because the mapped sample carries `id`. `test_dry_run_full_pass_no_side_effects` additionally add after the POST assertions:

```python
    # button-only automap: dry-run must not auto-match or persist mappings
    async with factory() as session:
        fs = await session.get(FeedSource, feed_id)
        doc = fs.field_mapping
        assert doc["auto_mapped"] is False
        assert set(doc["mappings"]) == {
            "id", "title", "description", "link", "image_link",
            "availability", "price", "condition", "brand", "gtin",
        }
```

- [ ] **Step 5c: Update the three `test_m6_acceptance.py` pipeline tests**

Add a shared seed helper near the other helpers:

```python
async def _seed_mappings(factory, feed_source_id):
    async with factory() as session:
        async with session.begin():
            fs = await session.get(FeedSource, feed_source_id)
            fs.field_mapping = {
                "version": 1,
                "auto_mapped": False,
                "source_fields": [],
                "mappings": {
                    "sku": {"target": "id", "origin": "manual"},
                    "title": {"target": "title", "origin": "manual"},
                    "ean": {"target": "gtin", "origin": "manual"},
                },
                "custom_fields": [],
            }
```

Call `await _seed_mappings(factory, feed_source_id)` immediately after feed-source creation (before the first `runner.execute`) in:
- `test_end_to_end_execution_through_runner`
- `test_error_isolation_preserves_last_known_good`
- `test_drop_then_pass_reactivation`

Their downstream assertions (`processed_data["title"] == "RED SHIRT"`, `product_id == "A1"`, `title_suffix`) keep passing because mappings are present from the start.

- [ ] **Step 5d: Update `tests/test_custom_labels_plugin.py` hash-stability e2e**

In the e2e test (the one building `TSV = b"sku\ttitle\tean\nA1\tRed Shirt\t1234567890123\n"`), after the feed-source `session.add(feed_source); await session.flush()` and before pipeline construction, set:

```python
            feed_source.field_mapping = {
                "version": 1,
                "auto_mapped": False,
                "source_fields": [],
                "mappings": {
                    "sku": {"target": "id", "origin": "manual"},
                    "title": {"target": "title", "origin": "manual"},
                    "ean": {"target": "gtin", "origin": "manual"},
                },
                "custom_fields": [],
            }
```

(existing `hash1 == hash2` assertions unaffected — same mapping applied in both runs).

- [ ] **Step 5e: Update `tests/test_m3_acceptance.py`**

Add after `_seed_feed_source` in both tests (`test_happy_path_tsv_ingest_end_to_end`, `test_row_errors_skipped_but_run_succeeds`) — modify `_seed_feed_source` to accept and store mappings:

```python
IDENTITY_MAPPINGS = {
    "version": 1,
    "auto_mapped": False,
    "source_fields": [],
    "mappings": {
        "id": {"target": "id", "origin": "manual"},
        "title": {"target": "title", "origin": "manual"},
        "price": {"target": "price", "origin": "manual"},
    },
    "custom_fields": [],
}
```

```python
async def _seed_feed_source(session_factory, configuration):
    # ... existing client/feed_source creation ...
            feed_source = FeedSource(
                client_id=client.id,
                name="Main feed",
                source_format="tsv",
                source_url="http://test.local/feed.tsv",
                configuration=configuration,
                field_mapping=IDENTITY_MAPPINGS,
            )
```

For `test_row_errors_skipped_but_run_succeeds`, also add `shipping` mapping to `IDENTITY_MAPPINGS["mappings"]`:

```python
        "shipping": {"target": "shipping", "origin": "manual"},
```

(verify `shipping` is a registry `repeated_structured` attribute — the TSV produces `shipping` as list-of-dicts via flat notation; the captured assertion expects `shipping` key present, so the target must accept list[dict]).

- [ ] **Step 5f: Run the full backend suite (audit assertion — directive item 1)**

Run: `cd backend && uv run pytest -n auto -q`
Expected: ALL PASS — no test anywhere relies on implicit automatch by accident. If any other test fails with mapping-related assertions, apply the same pre-seed pattern and re-run; keep going until green.

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/pipeline/steps.py tests/
git commit -m "feat!: MappingStep no longer auto-matches; stored mappings only (D1)"
```

---

### Task 3: D1 — remove implicit automatch from `run_dry_run`

**Files:**
- Modify: `backend/app/pipeline/dry_run.py:61-63`
- Test: `backend/tests/test_dry_run_api.py` (already updated in Task 2 Step 5b; add one explicit no-automap test here)

**Interfaces:**
- Produces: `run_dry_run` maps with stored mappings only; never calls `auto_match`; `auto_match` import removed from `dry_run.py`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_dry_run_api.py` (uses the Task 2 `_make_feed`, which seeds mappings):

```python
async def test_dry_run_unmapped_source_flags_baseline_no_automap(app_factory):
    app, factory, _ = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _make_feed(client)
    # wipe mappings: simulate a fresh, unmapped source
    async with factory() as session:
        async with session.begin():
            fs = await session.get(FeedSource, feed_id)
            fs.field_mapping = {
                "version": 1, "auto_mapped": False,
                "source_fields": [], "mappings": {}, "custom_fields": [],
            }
    resp = await client.post(f"/feed-sources/{feed_id}/dry-run", json={})
    assert resp.status_code == 200
    body = resp.json()
    # unmapped products render empty samples — no implicit automatch
    assert body["sample"][0] == {}
    critical = body["findings"]["critical"]
    assert any(e["rule"] == "baseline_required" for e in critical)
    async with factory() as session:
        fs = await session.get(FeedSource, feed_id)
        assert fs.field_mapping["auto_mapped"] is False
        assert fs.field_mapping["mappings"] == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_dry_run_api.py::test_dry_run_unmapped_source_flags_baseline_no_automap -v`
Expected: FAIL — sample contains automapped keys (current code auto-matches in memory)

- [ ] **Step 3: Remove the implicit block in `dry_run.py`**

Replace:

```python
    doc = MappingDocument.from_json(feed_source.field_mapping)
    if not doc.auto_mapped:
        doc.mappings = auto_match(run_state.source_fields, registry, existing=doc.mappings)
```

with:

```python
    doc = MappingDocument.from_json(feed_source.field_mapping)
```

Remove the import `from ..mapping.matcher import auto_match` (line 16).

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_dry_run_api.py -v`
Expected: all PASS (Task 2's seeded fixtures + the new test)

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/pipeline/dry_run.py tests/test_dry_run_api.py
git commit -m "feat!: dry-run maps with stored mappings only; no implicit automatch"
```

---

### Task 4: PUT/GET API — `custom_fields` payload + validation

**Files:**
- Modify: `backend/app/schemas/field_mapping.py` (`FieldMappingPut`, `FieldMappingOut`)
- Modify: `backend/app/routes/field_mapping.py` (PUT handler + `_validate_custom_fields` + flat-key closure)
- Test: `backend/tests/test_field_mapping_api.py`

**Interfaces:**
- Consumes: `MappingDocument.custom_fields` (Task 1).
- Produces: PUT body `{"mappings": {...}, "custom_fields": [...]}`; GET response includes `custom_fields: list[str]`; 422 errors in existing `{"errors": ["<name>: message"]}` shape.
- Validation rules (spec §4.2): grammar `^[a-z_][a-z0-9_]*$` ≤ 64; no duplicates; no observed-field collision; flat mapping keys must be observed ∪ custom (dotted keys unchanged); **baseline-name collision permitted** (directive item 4).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_field_mapping_api.py`:

```python
async def test_put_custom_fields_persists_and_get_roundtrips(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        {
            "version": 1, "auto_mapped": False,
            "source_fields": [source_field("title", "scalar")],
            "mappings": {},
        },
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={
            "mappings": {
                "title": {"target": "title"},
                "my_custom_field": {"target": "product_detail.2.attribute_value"},
            },
            "custom_fields": ["my_custom_field"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["custom_fields"] == ["my_custom_field"]
    assert body["mappings"]["my_custom_field"] == {
        "target": "product_detail.2.attribute_value", "origin": "manual",
    }
    persisted = (await client.get(f"/feed-sources/{fs_id}/field-mapping")).json()
    assert persisted["custom_fields"] == ["my_custom_field"]


async def test_put_custom_fields_default_empty(app_factory):
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping", json={"mappings": {}},
    )
    assert resp.status_code == 200
    assert resp.json()["custom_fields"] == []


async def test_put_custom_fields_bad_grammar_422(app_factory):
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    for bad in ["has.dot", "Has-Upper", "1starts_digit", "a" * 65, ""]:
        resp = await client.put(
            f"/feed-sources/{fs_id}/field-mapping",
            json={"mappings": {}, "custom_fields": [bad]},
        )
        assert resp.status_code == 422, bad
        assert any(bad in e for e in resp.json()["errors"])


async def test_put_custom_fields_duplicate_422(app_factory):
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {}, "custom_fields": ["dup", "dup"]},
    )
    assert resp.status_code == 422
    assert any("dup" in e and "duplicate" in e for e in resp.json()["errors"])


async def test_put_custom_fields_observed_collision_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        {
            "version": 1, "auto_mapped": False,
            "source_fields": [source_field("title", "scalar")],
            "mappings": {},
        },
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {}, "custom_fields": ["title"]},
    )
    assert resp.status_code == 422
    assert any("title" in e and "already an observed source field" in e
               for e in resp.json()["errors"])


async def test_put_flat_mapping_key_requires_custom_or_observed_422(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        {
            "version": 1, "auto_mapped": False,
            "source_fields": [source_field("title", "scalar")],
            "mappings": {},
        },
    )
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={"mappings": {"mystery_field": {"target": "title"}}},
    )
    assert resp.status_code == 422
    assert any("mystery_field" in e and "unknown source field" in e
               for e in resp.json()["errors"])


async def test_put_custom_field_named_like_baseline_accepted(app_factory):
    # Directive item 4: baseline-name collision (e.g. 'title') is permitted —
    # accepted behavior, not a bug.
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={
            "mappings": {"title": {"target": "title"}},
            "custom_fields": ["title"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["custom_fields"] == ["title"]
    assert body["mappings"]["title"] == {"target": "title", "origin": "manual"}
```

Also update the two existing tests that assert full-document equality to include `custom_fields`:

- `test_get_field_mapping_never_ingested_returns_empty_document`: expected body gains `"custom_fields": []`.
- `test_put_field_mapping_stores_manual_entries`: this test currently maps `mystery_field` (a flat key NOT in observed fields) — **it violates new rule §4.2(4)**. Change its mapping payload to declare it custom:

```python
    resp = await client.put(
        f"/feed-sources/{fs_id}/field-mapping",
        json={
            "mappings": {
                "product_name": {"target": "title"},
                "mystery_field": {"target": "shipping.country"},
            },
            "custom_fields": ["mystery_field"],
        },
    )
```

and the two body assertions gain `assert body["custom_fields"] == ["mystery_field"]`.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_field_mapping_api.py -k "custom or never_ingested or stores_manual" -v`
Expected: new tests FAIL (`custom_fields` unknown to schema); `never_ingested` FAILs on missing key.

- [ ] **Step 3: Implement schemas**

In `backend/app/schemas/field_mapping.py`:

```python
class MappingEntryIn(BaseModel):
    target: str = Field(min_length=1)


class FieldMappingPut(BaseModel):
    mappings: dict[str, MappingEntryIn]
    custom_fields: list[str] = Field(default_factory=list)
```

```python
class FieldMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    auto_mapped: bool
    source_fields: list[SourceFieldOut]
    mappings: dict[str, MappingEntryOut]
    custom_fields: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Implement route validation + persistence**

In `backend/app/routes/field_mapping.py`:

Add constants + validator after `_STRUCTURED_KINDS`:

```python
import re

_CUSTOM_FIELD_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_CUSTOM_FIELD_MAX_LEN = 64


def _validate_custom_fields(
    custom_fields: list[str],
    document: MappingDocument,
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    observed = {field.name for field in document.source_fields}
    for name in custom_fields:
        if (
            len(name) > _CUSTOM_FIELD_MAX_LEN
            or _CUSTOM_FIELD_RE.fullmatch(name) is None
        ):
            errors.append(
                f"{name}: custom field names must match "
                f"'[a-z_][a-z0-9_]*' (max {_CUSTOM_FIELD_MAX_LEN} chars)"
            )
            continue
        if name in seen:
            errors.append(f"{name}: duplicate custom field")
            continue
        seen.add(name)
        # Note: a custom field named like a _BASELINE_FIELDS entry
        # (e.g. 'title', 'id') is permitted and behaves as any other
        # custom entry — accepted behavior, documented in docs/decisions.md.
        if name in observed:
            errors.append(
                f"{name}: already an observed source field"
            )
    return errors
```

In `_validate_mappings` (whose signature becomes `mappings: dict[str, str], document: MappingDocument, custom_fields: list[str]`), extend the flat-key branch. Current code:

```python
    for source, target in mappings.items():
        if source in known_fields:
            check_target(source, target, known_fields[source].kind)
            continue
        parent, dot, sub = source.partition(".")
        if not dot or not sub:
            check_target(source, target, None)
            continue
```

becomes:

```python
    for source, target in mappings.items():
        if source in known_fields:
            check_target(source, target, known_fields[source].kind)
            continue
        parent, dot, sub = source.partition(".")
        if not dot or not sub:
            if source not in custom_fields:
                errors.append(f"{source}: unknown source field")
                continue
            check_target(source, target, None)
            continue
```

In `update_field_mapping`, apply both validators and persist:

```python
        document = _load_document(feed_source)
        custom_errors = _validate_custom_fields(payload.custom_fields, document)
        if custom_errors:
            return _validation_error(custom_errors)
        errors = _validate_mappings(
            {source: entry.target for source, entry in payload.mappings.items()},
            document,
            payload.custom_fields,
        )
        if errors:
            return _validation_error(errors)
        document.mappings = {
            source: MappingEntry(target=entry.target, origin="manual")
            for source, entry in payload.mappings.items()
        }
        document.custom_fields = list(payload.custom_fields)
        feed_source.field_mapping = document.to_json()
        return document
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/test_field_mapping_api.py -v`
Expected: all PASS (existing 32 + new 7, with the two updated)

- [ ] **Step 6: Run the wider backend suite for the GET-shape change**

Run: `cd backend && uv run pytest -n auto -q`
Expected: ALL PASS. (`test_m4_acceptance.py`, `test_feed_fields_api.py`, `test_mapping_step.py` assert doc sub-dicts, not full equality — verify; `test_dry_run_api.py` was updated in Task 2.)

- [ ] **Step 7: Commit**

```bash
cd backend && git add app/schemas/field_mapping.py app/routes/field_mapping.py tests/test_field_mapping_api.py
git commit -m "feat: custom_fields on field-mapping PUT/GET with validation"
```

---

### Task 5: `POST /auto` round-trips `custom_fields` (directive item 3)

**Files:**
- Test: `backend/tests/test_field_mapping_api.py`
- Modify (only if RED): `backend/app/routes/field_mapping.py` — `auto_map_fields`

**Interfaces:**
- Produces: POST `/feed-sources/{id}/field-mapping/auto` preserves `document.custom_fields` untouched while rebuilding mappings.

- [ ] **Step 1: Write the failing test**

```python
async def test_post_auto_roundtrips_custom_fields_unchanged(app_factory):
    _, factory = app_factory
    client = await logged_in_client(app_factory)
    fs_id = await create_feed_source(client)
    await seed_field_mapping(
        factory,
        fs_id,
        {
            "version": 1, "auto_mapped": False,
            "source_fields": [
                source_field("product_name", "scalar"),
                source_field("ean", "scalar"),
            ],
            "mappings": {"product_name": {"target": "id", "origin": "manual"}},
            "custom_fields": ["my_custom_field"],
        },
    )
    resp = await client.post(f"/feed-sources/{fs_id}/field-mapping/auto")
    assert resp.status_code == 200
    body = resp.json()
    assert body["custom_fields"] == ["my_custom_field"]
    persisted = (await client.get(f"/feed-sources/{fs_id}/field-mapping")).json()
    assert persisted["custom_fields"] == ["my_custom_field"]
```

- [ ] **Step 2: Run to verify outcome**

Run: `cd backend && uv run pytest tests/test_field_mapping_api.py::test_post_auto_roundtrips_custom_fields_unchanged -v`

The endpoint does `document.mappings = auto_match(...)` and `feed_source.field_mapping = document.to_json()` without touching `custom_fields` — since `to_json` now emits it (Task 1), this test is expected to PASS immediately. That is fine: it pins the directive-3 contract against future regressions. If it FAILS, fix `auto_map_fields` to not reset `custom_fields` before proceeding.

- [ ] **Step 3: Commit**

```bash
cd backend && git add tests/test_field_mapping_api.py
git commit -m "test: pin POST /auto round-trips custom_fields unchanged"
```

---

### Task 6: Apply semantics — dormant custom rows (pin + doc)

**Files:**
- Test: `backend/tests/test_mapping_apply.py`
- Docs: `backend/docs/api.md`, `backend/docs/architecture.md`, `docs/decisions.md`

**Interfaces:**
- Consumes: `apply_mapping(product, mappings, registry)` — unchanged.
- Produces: pinned contract — custom mapping keys absent from the product are no-ops; present keys behave like observed-field mappings. No production code change expected.

- [ ] **Step 1: Write the pinning tests**

Append to `backend/tests/test_mapping_apply.py` (reuses the file's existing module-scoped `registry` fixture, `MappingEntry`, and `apply_mapping` imports):

```python
def test_custom_field_mapping_dormant_when_key_absent(registry):
    product = {"title": "Shirt"}
    mappings = {
        "title": MappingEntry("title", "manual"),
        "my_custom_field": MappingEntry("brand", "manual"),
    }
    mapped, stats = apply_mapping(product, mappings, registry)
    assert mapped == {"title": "Shirt"}
    assert stats == ApplyStats(dropped_unmapped=1, shape_mismatches=0)


def test_custom_field_mapping_activates_when_key_present(registry):
    product = {"my_custom_field": "Acme"}
    mappings = {"my_custom_field": MappingEntry("brand", "manual")}
    mapped, stats = apply_mapping(product, mappings, registry)
    assert mapped == {"brand": "Acme"}
    assert stats == ApplyStats(dropped_unmapped=0, shape_mismatches=0)
```

- [ ] **Step 2: Run**

Run: `cd backend && uv run pytest tests/test_mapping_apply.py -k "dormant or activates" -v`
Expected: PASS already (key-driven apply: absent keys never enter the product loop, so they never drop; only present-but-unmapped keys drop). If not, STOP and investigate `apply_mapping` — do not force-fit.

- [ ] **Step 3: Update docs**

`backend/docs/api.md` — field-mapping endpoints section:

```
PUT /feed-sources/{id}/field-mapping
  Body: { "mappings": { <source>: { "target": <attr[.N][.sub]> } },
          "custom_fields": [ "<flat name>", ... ] }
  Full replace. custom_fields: flat names ([a-z_][a-z0-9_]*, <= 64),
  no duplicates, no overlap with observed source_fields. Flat mapping
  source keys must be observed or custom (422 otherwise). Custom fields
  are dormant in the pipeline until the ingested feed supplies the key.

POST /feed-sources/{id}/field-mapping/auto
  Only trigger for auto-matching (pipeline runs and dry-runs never
  auto-match). Preserves manual entries and custom_fields.

GET /feed-sources/{id}/field-mapping
  Returns { version, auto_mapped, source_fields, mappings, custom_fields }.
```

`backend/docs/architecture.md` — pipeline/mapping step description: replace any "auto-matches on first run / when not yet auto-mapped" wording with "applies stored mappings only; `MappingStep` refreshes observed source_fields, never writes mappings; auto-matching is operator-triggered via POST /field-mapping/auto only".

`docs/decisions.md` — append (follow the existing dated entry format):

```
2026-09-11 — Button-only auto-mapper & custom mapping source fields
Topic: Mapping auto-match trigger; manual mapping rows
Decision:
1. Implicit auto_match removed from MappingStep and run_dry_run.
   POST /field-mapping/auto (the UI button) is the only trigger. Fresh
   feed sources stay unmapped until the operator acts; QC
   BaselineRequired findings flag the gap. Supersedes the M4-era
   implicit-automatch behavior.
2. MappingDocument gains custom_fields: list[str] (flat grammar
   [a-z_][a-z0-9_]*, <=64, additive, no migration). PUT is full-replace;
   flat mapping source keys must be observed or custom (422 otherwise).
   Custom rows are dormant in apply_mapping until the feed supplies the
   key. Observed keys shadow custom twins in the UI (shadow indicator +
   reachable remove control); no kind-revalidation when ingest later
   observes a custom key.
3. Accepted: a custom field named like a _BASELINE_FIELDS entry
   (e.g. 'title', 'id') is permitted and maps like any custom entry —
   _BASELINE_FIELDS only feeds GET /feed-sources/{id}/fields defaults,
   it reserves no names on the mapping document.
Rationale: operator control and auditability — no surprise mappings after
pipeline runs; manual pre-provisioning of targets for fields the input
feed does not (yet) supply.
```

- [ ] **Step 4: Run gates + commit**

Run: `cd backend && uv run ruff check . && uv run mypy . && uv run pytest tests/test_mapping_apply.py -q`
Expected: ruff count matches baseline (506), mypy exit 0, tests PASS.

```bash
cd /home/ozon/gmc_feed_master && git add backend/docs/api.md backend/docs/architecture.md docs/decisions.md backend/tests/test_mapping_apply.py
git commit -m "docs+test: button-only automap, custom_fields contract, dormant-row pin"
```

---

### Task 7: Frontend types, hook payload, i18n, name regex

**Files:**
- Modify: `frontend/src/api/types.ts` (`FieldMappingDoc`)
- Modify: `frontend/src/api/fieldOptions.ts` (add `CUSTOM_FIELD_NAME_REGEX` + `MAX_CUSTOM_FIELD_NAME_LEN`)
- Modify: `frontend/src/api/hooks.ts` (`useSaveFieldMapping` payload type)
- Modify: `frontend/public/locales/en/setup.json`, `frontend/public/locales/de/setup.json`
- Test: `frontend/src/api/fieldOptions.test.ts`

**Interfaces:**
- Produces: `FieldMappingDoc.custom_fields: string[]`; `useSaveFieldMapping` mutation arg `mappings: Record<string, { target: string }>; customFields?: string[]`; `CUSTOM_FIELD_NAME_REGEX = /^[a-z_][a-z0-9_]*$/` and `CUSTOM_FIELD_NAME_MAX_LEN = 64` exported from `fieldOptions.ts`; i18n keys `mapping.custom.*`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/api/fieldOptions.test.ts`:

```typescript
import { CUSTOM_FIELD_NAME_REGEX, CUSTOM_FIELD_NAME_MAX_LEN } from './fieldOptions';

describe('CUSTOM_FIELD_NAME_REGEX', () => {
  it.each(['my_field', 'a', 'field2', 'a_b_9'])('accepts %s', (name) => {
    expect(CUSTOM_FIELD_NAME_REGEX.test(name)).toBe(true);
  });
  it.each([
    'has.dot',
    'Has-Upper',
    '1starts_digit',
    '',
    ' spaced ',
    'ünïcode',
  ])('rejects %s', (name) => {
    expect(CUSTOM_FIELD_NAME_REGEX.test(name)).toBe(false);
  });
  it('accepts a 64-char name and rejects 65', () => {
    expect('a'.repeat(CUSTOM_FIELD_NAME_MAX_LEN)).toMatch(CUSTOM_FIELD_NAME_REGEX);
    expect('a'.repeat(CUSTOM_FIELD_NAME_MAX_LEN + 1).length).toBe(65);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/api/fieldOptions.test.ts`
Expected: FAIL (exports missing)

- [ ] **Step 3: Implement**

`types.ts` — extend `FieldMappingDoc`:

```typescript
export type FieldMappingDoc = {
  version: number;
  auto_mapped: boolean;
  source_fields: SourceField[];
  mappings: Record<string, MappingEntry>;
  custom_fields?: string[];
};
```

(Optional key so existing fixtures without it stay valid; `MappingTab` treats absent as `[]`.)

`fieldOptions.ts` — add after `INDEXED_PATH_REGEX`:

```typescript
/** Custom mapping source-field name grammar (mirrors backend
 * _CUSTOM_FIELD_RE: flat, single segment, <= 64 chars). */
export const CUSTOM_FIELD_NAME_REGEX = /^[a-z_][a-z0-9_]*$/;
export const CUSTOM_FIELD_NAME_MAX_LEN = 64;
```

`hooks.ts` — `useSaveFieldMapping`:

```typescript
export function useSaveFieldMapping() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      mappings,
      customFields,
    }: {
      id: number | string;
      mappings: Record<string, { target: string }>;
      customFields?: string[];
    }) =>
      apiPut<FieldMappingDoc>(
        `/feed-sources/${id}/field-mapping`,
        { mappings, custom_fields: customFields ?? [] },
      ),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(variables.id).mapping,
      });
    },
  });
}
```

`public/locales/en/setup.json` — add inside `"mapping"`:

```json
    "custom": {
      "add": "Add custom field",
      "addName": "Field name",
      "addNamePlaceholder": "e.g. my_custom_field",
      "addTargetHint": "Map any target — scalar, structured, repeated, indexed",
      "invalidName": "Names must be lowercase letters, digits, underscores (no dots), max 64 characters",
      "duplicateName": "Field already exists",
      "remove": "Remove custom field",
      "alsoCustom": "also declared as custom field",
      "title": "Custom fields"
    },
```

`public/locales/de/setup.json` — same structure:

```json
    "custom": {
      "add": "Eigenes Feld hinzufügen",
      "addName": "Feldname",
      "addNamePlaceholder": "z. B. mein_feld",
      "addTargetHint": "Beliebiges Ziel — skalare, strukturierte, wiederholte, indizierte",
      "invalidName": "Namen dürfen aus Kleinbuchstaben, Ziffern und Unterstrichen bestehen (keine Punkte), max. 64 Zeichen",
      "duplicateName": "Feld existiert bereits",
      "remove": "Eigenes Feld entfernen",
      "alsoCustom": "auch als eigenes Feld deklariert",
      "title": "Eigene Felder"
    },
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/api/fieldOptions.test.ts && npm run typecheck`
Expected: PASS, typecheck clean

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/api/types.ts src/api/fieldOptions.ts src/api/hooks.ts public/locales/en/setup.json public/locales/de/setup.json src/api/fieldOptions.test.ts
git commit -m "feat: frontend custom_fields types, name regex, i18n, save payload"
```

---

### Task 8: `MappingTable` — custom rows, add row, remove, shadow indicator

**Files:**
- Modify: `frontend/src/features/setup/MappingTable.tsx`
- Test: `frontend/src/features/setup/MappingTable.test.tsx`

**Interfaces:**
- Consumes: `CUSTOM_FIELD_NAME_REGEX`, `CUSTOM_FIELD_NAME_MAX_LEN` (Task 7); `FieldSelect` + `buildFieldOptions` (existing).
- Produces — new props on `MappingTable`:

```typescript
type MappingTableProps = {
  sourceFields: SourceField[];
  mappings: Record<string, { target: string | null; origin: string | null }>;
  registryAttributes: RegistryAttribute[];
  onChange: (source: string, target: string | null) => void;
  errors: Record<string, string>;
  customFields: string[];                                   // NEW
  onAddCustom: (name: string, target: string) => void;      // NEW
  onRemoveCustom: (name: string) => void;                   // NEW
};
```

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/features/setup/MappingTable.test.tsx` (inside the top-level `describe`, after existing tests):

```typescript
  it('renders custom field rows with remove controls', async () => {
    const onRemoveCustom = vi.fn();
    render(
      <MappingTable
        {...defaultProps({
          customFields: ['my_custom_field'],
          onAddCustom: vi.fn(),
          onRemoveCustom,
        })}
      />,
    );
    expect(await screen.findByText('my_custom_field')).toBeInTheDocument();
    const removeBtn = screen.getByRole('button', {
      name: /remove custom field/i,
    });
    expect(removeBtn).toBeInTheDocument();
  });

  it('remove control calls onRemoveCustom with the name', async () => {
    const user = userEvent.setup();
    const onRemoveCustom = vi.fn();
    render(
      <MappingTable
        {...defaultProps({
          customFields: ['my_custom_field'],
          onAddCustom: vi.fn(),
          onRemoveCustom,
        })}
      />,
    );
    const removeBtn = await screen.findByRole('button', {
      name: /remove custom field/i,
    });
    await user.click(removeBtn);
    expect(onRemoveCustom).toHaveBeenCalledWith('my_custom_field');
  });

  it('add row: Add disabled until valid name and target chosen', async () => {
    render(
      <MappingTable
        {...defaultProps({ customFields: [], onAddCustom: vi.fn(), onRemoveCustom: vi.fn() })}
      />,
    );
    const addBtn = await screen.findByRole('button', { name: /add custom field/i });
    expect(addBtn).toBeDisabled();
  });

  it('add row: invalid name shows inline error and keeps Add disabled', async () => {
    const user = userEvent.setup();
    render(
      <MappingTable
        {...defaultProps({ customFields: [], onAddCustom: vi.fn(), onRemoveCustom: vi.fn() })}
      />,
    );
    const nameInput = await screen.findByRole('textbox', { name: /field name/i });
    await user.type(nameInput, 'Bad.Name');
    expect(
      await screen.findByText(/names must be lowercase/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add custom field/i })).toBeDisabled();
  });

  it('add row: valid name + target enables Add and calls onAddCustom', async () => {
    const user = userEvent.setup();
    const onAddCustom = vi.fn();
    render(
      <MappingTable
        {...defaultProps({ customFields: [], onAddCustom, onRemoveCustom: vi.fn() })}
      />,
    );
    const nameInput = await screen.findByRole('textbox', { name: /field name/i });
    await user.type(nameInput, 'my_custom_field');

    const addRow = nameInput.closest('tr')!;
    const select = addRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^brand$/ });
    await user.click(option);

    const addBtn = screen.getByRole('button', { name: /add custom field/i });
    await waitFor(() => expect(addBtn).toBeEnabled());
    await user.click(addBtn);
    expect(onAddCustom).toHaveBeenCalledWith('my_custom_field', 'brand');
  });

  it('add row: duplicate name (custom or observed) shows inline error', async () => {
    const user = userEvent.setup();
    render(
      <MappingTable
        {...defaultProps({ customFields: ['taken'], onAddCustom: vi.fn(), onRemoveCustom: vi.fn() })}
      />,
    );
    const nameInput = await screen.findByRole('textbox', { name: /field name/i });
    await user.type(nameInput, 'taken');
    expect(await screen.findByText(/field already exists/i)).toBeInTheDocument();
    // observed name too
    await user.clear(nameInput);
    await user.type(nameInput, 'title');
    expect(await screen.findByText(/field already exists/i)).toBeInTheDocument();
  });

  it('custom row target select calls onChange with the custom name', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MappingTable
        {...defaultProps({
          customFields: ['my_custom_field'],
          mappings: {
            ...mappingsFixture(),
            my_custom_field: { target: 'title', origin: 'manual' },
          },
          onChange,
          onAddCustom: vi.fn(),
          onRemoveCustom: vi.fn(),
        })}
      />,
    );
    const row = (await screen.findByText('my_custom_field')).closest('tr')!;
    const select = row.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^description$/ });
    await user.click(option);
    expect(onChange).toHaveBeenCalledWith('my_custom_field', 'description');
  });

  it('observed/custom shadow: exactly one row with indicator, remove still reachable', async () => {
    const user = userEvent.setup();
    const onRemoveCustom = vi.fn();
    render(
      <MappingTable
        {...defaultProps({
          customFields: ['title'],
          onAddCustom: vi.fn(),
          onRemoveCustom,
        })}
      />,
    );
    await waitFor(() => {
      expect(screen.getAllByText('title')).toHaveLength(1);
    });
    expect(
      screen.getByText(/also declared as custom field/i),
    ).toBeInTheDocument();
    const removeBtn = screen.getByRole('button', { name: /remove custom field/i });
    await user.click(removeBtn);
    expect(onRemoveCustom).toHaveBeenCalledWith('title');
  });

  it('renders the custom section even with zero observed fields', async () => {
    render(
      <MappingTable
        {...defaultProps({
          sourceFields: [],
          customFields: ['solo_custom'],
          onAddCustom: vi.fn(),
          onRemoveCustom: vi.fn(),
        })}
      />,
    );
    expect(await screen.findByText('solo_custom')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add custom field/i })).toBeInTheDocument();
  });
```

Also update `defaultProps` at the top of the test file:

```typescript
function defaultProps(overrides?: Partial<React.ComponentProps<typeof MappingTable>>) {
  return {
    sourceFields,
    mappings,
    registryAttributes,
    onChange: vi.fn(),
    errors: {},
    customFields: [],
    onAddCustom: vi.fn(),
    onRemoveCustom: vi.fn(),
    ...overrides,
  };
}
```

And the registry fixture needs a `brand` attribute for the add-row test — extend `registryAttributes`:

```typescript
  { name: 'brand', kind: 'scalar', required: 'optional', sub_fields: [], enum_values: [], max_repeats: 1 },
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/features/setup/MappingTable.test.tsx`
Expected: new tests FAIL (props/rows/controls missing)

- [ ] **Step 3: Implement `MappingTable`**

Full replacement of the component body. Key design: a `customVisible` list = `customFields.filter((n) => !observedNames.has(n))` for standalone rows; observed rows whose name ∈ customFields get the shadow indicator + their own remove control; the add row sits last with name input + target FieldSelect + Add button.

```tsx
import { Fragment, useMemo, useState } from 'react';
import {
  Badge, Box, Button, Stack, Table, Text, TextInput, UnstyledButton,
} from '@mantine/core';
import { IconChevronDown, IconChevronRight, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { FieldSelect } from '../../components/FieldSelect';
import {
  buildFieldOptions,
  fromRegistryAttributes,
  CUSTOM_FIELD_NAME_REGEX,
  CUSTOM_FIELD_NAME_MAX_LEN,
} from '../../api/fieldOptions';
import type { RegistryAttribute, SourceField } from '../../api/types';

type MappingTableProps = {
  sourceFields: SourceField[];
  mappings: Record<string, { target: string | null; origin: string | null }>;
  registryAttributes: RegistryAttribute[];
  onChange: (source: string, target: string | null) => void;
  errors: Record<string, string>;
  customFields: string[];
  onAddCustom: (name: string, target: string) => void;
  onRemoveCustom: (name: string) => void;
};

const originLabels: Record<string, string> = {
  auto: 'mapping.origins.auto',
  synonym: 'mapping.origins.synonym',
  manual: 'mapping.origins.manual',
};

const STRUCTURED_KINDS = new Set(['structured', 'repeated_structured']);

function isExpandable(sf: SourceField): boolean {
  return STRUCTURED_KINDS.has(sf.kind) && sf.sub_fields.length > 0;
}

function subFieldKind(parentKind: string): string {
  return parentKind === 'repeated_structured' ? 'repeated_scalar' : 'scalar';
}

function OriginBadge({ origin }: { origin: string | null }) {
  const { t } = useTranslation('setup');
  if (!origin) return null;
  return (
    <Badge
      size="xs"
      variant="outline"
      color={origin === 'auto' ? 'blue' : origin === 'synonym' ? 'yellow' : 'gray'}
    >
      {originLabels[origin] ? t(originLabels[origin] as 'mapping.origins.auto') : origin}
    </Badge>
  );
}

function AddCustomRow({
  targetOptions,
  existingNames,
  onAdd,
}: {
  targetOptions: ReturnType<typeof buildFieldOptions>;
  existingNames: Set<string>;
  onAdd: (name: string, target: string) => void;
}) {
  const { t } = useTranslation('setup');
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');

  const grammarOk = CUSTOM_FIELD_NAME_REGEX.test(name);
  const tooLong = name.length > CUSTOM_FIELD_NAME_MAX_LEN;
  const duplicate = existingNames.has(name);
  const nameError = name === ''
    ? null
    : tooLong || !grammarOk
      ? t('mapping.custom.invalidName')
      : duplicate
        ? t('mapping.custom.duplicateName')
        : null;
  const canAdd = name !== '' && target !== '' && nameError === null;

  return (
    <Table.Tr data-testid="add-custom-row">
      <Table.Td>
        <Stack gap={4}>
          <TextInput
            aria-label={t('mapping.custom.addName')}
            placeholder={t('mapping.custom.addNamePlaceholder')}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            error={nameError}
            size="xs"
            w={220}
            data-testid="custom-name-input"
          />
          <Text size="xs" c="dimmed">{t('mapping.custom.addTargetHint')}</Text>
        </Stack>
      </Table.Td>
      <Table.Td>
        <FieldSelect
          value={target}
          onChange={(val) => setTarget(val)}
          options={targetOptions}
          placeholder={t('mapping.table.selectTarget')}
          clearable
          data-testid="add-custom-target"
        />
      </Table.Td>
      <Table.Td>
        <Button
          size="xs"
          variant="light"
          disabled={!canAdd}
          onClick={() => {
            onAdd(name, target);
            setName('');
            setTarget('');
          }}
          data-testid="add-custom-button"
        >
          {t('mapping.custom.add')}
        </Button>
      </Table.Td>
    </Table.Tr>
  );
}

export function MappingTable({
  sourceFields,
  mappings,
  registryAttributes,
  onChange,
  errors,
  customFields,
  onAddCustom,
  onRemoveCustom,
}: MappingTableProps) {
  const { t } = useTranslation('setup');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const targetOptions = useMemo(
    () => buildFieldOptions(fromRegistryAttributes(registryAttributes)),
    [registryAttributes],
  );
  const observedNames = useMemo(
    () => new Set(sourceFields.map((sf) => sf.name)),
    [sourceFields],
  );
  const existingNames = useMemo(
    () => new Set([...observedNames, ...customFields]),
    [observedNames, customFields],
  );
  const standaloneCustom = customFields.filter((n) => !observedNames.has(n));

  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('mapping.table.source')}</Table.Th>
          <Table.Th>{t('mapping.table.target')}</Table.Th>
          <Table.Th w={70} />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {sourceFields.map((sf) => {
          const mapping = mappings[sf.name];
          const origin = mapping?.origin ?? null;
          const targetValue = mapping?.target ?? null;
          const error = errors[sf.name] ?? null;
          const expandable = isExpandable(sf);
          const isOpen = expanded[sf.name] ?? false;
          const shadowedCustom = customFields.includes(sf.name);

          return (
            <Fragment key={sf.name}>
              <Table.Tr>
                <Table.Td>
                  <Stack gap={4}>
                    <Box style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {expandable && (
                        <UnstyledButton
                          data-sub-toggle={sf.name}
                          aria-expanded={isOpen}
                          aria-label={t(
                            isOpen ? 'mapping.table.collapseSubFields' : 'mapping.table.expandSubFields',
                            { field: sf.name },
                          )}
                          onClick={() =>
                            setExpanded((prev) => ({ ...prev, [sf.name]: !prev[sf.name] }))
                          }
                        >
                          {isOpen ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
                        </UnstyledButton>
                      )}
                      <Text size="sm" fw={500}>
                        {sf.name}
                      </Text>
                      <Badge size="xs" variant="light">
                        {sf.kind}
                      </Badge>
                      <OriginBadge origin={origin} />
                      {shadowedCustom && (
                        <Badge size="xs" variant="outline" color="violet" data-testid="shadow-indicator">
                          {t('mapping.custom.alsoCustom')}
                        </Badge>
                      )}
                    </Box>
                    {error && <Text size="xs" c="red">{error}</Text>}
                  </Stack>
                </Table.Td>
                <Table.Td>
                  <FieldSelect
                    value={targetValue ?? ''}
                    onChange={(val) => onChange(sf.name, val || null)}
                    options={targetOptions}
                    placeholder={t('mapping.table.selectTarget')}
                    error={!!error}
                    clearable
                    data-testid={`target-select-${sf.name}`}
                  />
                </Table.Td>
                <Table.Td>
                  {shadowedCustom && (
                    <UnstyledButton
                      aria-label={t('mapping.custom.remove')}
                      title={t('mapping.custom.remove')}
                      onClick={() => onRemoveCustom(sf.name)}
                      data-testid={`remove-custom-${sf.name}`}
                    >
                      <IconTrash size={16} />
                    </UnstyledButton>
                  )}
                </Table.Td>
              </Table.Tr>
              {expandable
                && isOpen
                && sf.sub_fields.map((sub) => {
                  const subKey = `${sf.name}.${sub}`;
                  const subMapping = mappings[subKey];
                  const subError = errors[subKey] ?? null;
                  return (
                    <Table.Tr key={subKey}>
                      <Table.Td>
                        <Stack gap={4}>
                          <Box style={{ display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 32 }}>
                            <Text size="sm" fw={500}>
                              {sub}
                            </Text>
                            <Badge size="xs" variant="light">
                              {subFieldKind(sf.kind)}
                            </Badge>
                            <OriginBadge origin={subMapping?.origin ?? null} />
                          </Box>
                          {subError && <Text size="xs" c="red">{subError}</Text>}
                        </Stack>
                      </Table.Td>
                      <Table.Td>
                        <FieldSelect
                          value={subMapping?.target ?? ''}
                          onChange={(val) => onChange(subKey, val || null)}
                          options={targetOptions}
                          placeholder={t('mapping.table.selectTarget')}
                          error={!!subError}
                          clearable
                          data-testid={`target-select-${subKey}`}
                        />
                      </Table.Td>
                      <Table.Td />
                    </Table.Tr>
                  );
                })}
            </Fragment>
          );
        })}
        {standaloneCustom.map((name) => {
          const mapping = mappings[name];
          const error = errors[name] ?? null;
          return (
            <Table.Tr key={`custom-${name}`} data-testid={`custom-row-${name}`}>
              <Table.Td>
                <Stack gap={4}>
                  <Box style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Text size="sm" fw={500}>{name}</Text>
                    <Badge size="xs" variant="light">custom</Badge>
                    <OriginBadge origin={mapping?.origin ?? 'manual'} />
                  </Box>
                  {error && <Text size="xs" c="red">{error}</Text>}
                </Stack>
              </Table.Td>
              <Table.Td>
                <FieldSelect
                  value={mapping?.target ?? ''}
                  onChange={(val) => onChange(name, val || null)}
                  options={targetOptions}
                  placeholder={t('mapping.table.selectTarget')}
                  error={!!error}
                  clearable
                  data-testid={`target-select-${name}`}
                />
              </Table.Td>
              <Table.Td>
                <UnstyledButton
                  aria-label={t('mapping.custom.remove')}
                  title={t('mapping.custom.remove')}
                  onClick={() => onRemoveCustom(name)}
                  data-testid={`remove-custom-${name}`}
                >
                  <IconTrash size={16} />
                </UnstyledButton>
              </Table.Td>
            </Table.Tr>
          );
        })}
        <AddCustomRow
          targetOptions={targetOptions}
          existingNames={existingNames}
          onAdd={onAddCustom}
        />
      </Table.Tbody>
    </Table>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/features/setup/MappingTable.test.tsx`
Expected: all PASS (existing + 8 new)

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/features/setup/MappingTable.tsx src/features/setup/MappingTable.test.tsx
git commit -m "feat: MappingTable custom rows, add row, remove, shadow indicator"
```

---

### Task 9: `MappingTab` — custom-field state, save payload, empty-state

**Files:**
- Modify: `frontend/src/features/setup/MappingTab.tsx`
- Test: `frontend/src/features/setup/MappingTab.test.tsx`

**Interfaces:**
- Consumes: `MappingTable` new props (Task 8); `useSaveFieldMapping` with `customFields` (Task 7); `FieldMappingDoc.custom_fields?`.
- Produces: MappingTab owns `customEdits: Record<string, string | null>` (local target edits for custom names) and `customList: string[] | null` (null = server state untouched); Save sends `mappings` (full effective set incl. custom rows) + `customFields` (effective custom list).

- [ ] **Step 1: Write the failing tests**

Append inside `describe('MappingTab', ...)` in `frontend/src/features/setup/MappingTab.test.tsx`. Extend the top fixtures first — `mappingDoc` gains `custom_fields: ['my_custom_field']` and `registryAttrs` gains a `brand` scalar (same fixture line as Task 8).

```typescript
  it('renders custom rows from server custom_fields', async () => {
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(mappingDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });
    renderTab();
    expect(await screen.findByText('my_custom_field')).toBeInTheDocument();
    expect(screen.getByText('custom')).toBeInTheDocument();
  });

  it('adding a custom field then saving PUTs custom_fields', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') {
        if (fetchMock.mock.calls.some(
          ([input, init]) => String(input) === url && init?.method === 'PUT',
        )) {
          return jsonResponse({ ...mappingDoc, custom_fields: ['brand_extra'] });
        }
        return jsonResponse({ ...mappingDoc, custom_fields: [] });
      }
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();
    await waitFor(() => {
      expect(screen.getByTestId('custom-name-input')).toBeInTheDocument();
    });
    await user.type(screen.getByTestId('custom-name-input'), 'brand_extra');
    const addRow = screen.getByTestId('custom-name-input').closest('tr')!;
    const select = addRow.querySelector('[role="combobox"]') as HTMLElement;
    await user.click(select);
    const option = await screen.findByRole('option', { name: /^brand$/ });
    await user.click(option);
    const addBtn = screen.getByTestId('add-custom-button');
    await waitFor(() => expect(addBtn).toBeEnabled());
    await user.click(addBtn);

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    await user.click(saveBtn);

    await waitFor(() => {
      const body = putBody('/feed-sources/1/field-mapping');
      expect(body).toBeDefined();
      expect(body?.custom_fields).toEqual(['brand_extra']);
      expect(body?.mappings).toEqual(
        expect.objectContaining({ brand_extra: { target: 'brand' } }),
      );
    });
  });

  it('removing a custom field excludes it from the PUT payload', async () => {
    const user = userEvent.setup();
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') {
        if (fetchMock.mock.calls.some(
          ([input, init]) => String(input) === url && init?.method === 'PUT',
        )) {
          return jsonResponse({ ...mappingDoc, custom_fields: [] });
        }
        return jsonResponse(mappingDoc);
      }
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();
    const removeBtn = await screen.findByTestId('remove-custom-my_custom_field');
    await user.click(removeBtn);

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    await user.click(saveBtn);

    await waitFor(() => {
      const body = putBody('/feed-sources/1/field-mapping');
      expect(body?.custom_fields).toEqual([]);
      expect(body?.mappings?.my_custom_field).toBeUndefined();
    });
  });

  it('shadowed custom entry on an observed row stays removable', async () => {
    const user = userEvent.setup();
    const shadowDoc: FieldMappingDoc = {
      ...mappingDoc,
      custom_fields: ['title'],
    };
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(shadowDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });

    renderTab();
    expect(await screen.findByTestId('shadow-indicator')).toBeInTheDocument();
    expect(screen.getAllByText('title').length).toBe(1); // one row, shadowed
    const removeBtn = screen.getByTestId('remove-custom-title');
    await user.click(removeBtn);
    const saveBtn = screen.getByRole('button', { name: /save/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    await user.click(saveBtn);
    await waitFor(() => {
      const body = putBody('/feed-sources/1/field-mapping');
      expect(body?.custom_fields).toEqual([]);
      // title is observed: its mapping must survive the custom removal
      expect(body?.mappings?.title).toEqual({ target: 'title' });
    });
  });

  it('shows the custom add row even when no source fields are observed', async () => {
    const emptyDoc: FieldMappingDoc = {
      ...mappingDoc,
      source_fields: [],
      mappings: {},
      custom_fields: [],
    };
    fetchMock = stubFetch((url) => {
      if (url === '/feed-sources/1/field-mapping') return jsonResponse(emptyDoc);
      if (url === '/registry/attributes') return jsonResponse(registryAttrs);
      return jsonResponse({});
    });
    renderTab();
    expect(await screen.findByText(/no source fields observed yet/i)).toBeInTheDocument();
    expect(screen.getByTestId('add-custom-button')).toBeInTheDocument();
  });
```

Note: existing tests construct `FieldMappingDoc` without `custom_fields` — the optional type (Task 7) keeps them valid.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/features/setup/MappingTab.test.tsx`
Expected: new tests FAIL

- [ ] **Step 3: Implement in `MappingTab.tsx`**

Add state and derived values:

```tsx
  const serverCustomFields = useMemo(
    () => mappingQuery.data?.custom_fields ?? [],
    [mappingQuery.data],
  );
  const [customList, setCustomList] = useState<string[] | null>(null);
  const effectiveCustomFields = customList ?? serverCustomFields;
```

Extend `effectiveMappings` to overlay custom-row target edits — after the `localEdits` loop, add:

```tsx
    for (const name of effectiveCustomFields) {
      if (!base[name]) {
        base[name] = { target: null, origin: 'manual' };
      }
    }
```

(inside the same `useMemo`, appending to the existing body before `return base`).

Extend `isDirty`:

```tsx
  const isDirty = useMemo(() => {
    if (!deepEqual(localEdits, {})) return true;
    if (customList !== null && !deepEqual(customList, serverCustomFields)) return true;
    return false;
  }, [localEdits, customList, serverCustomFields]);
```

Handlers:

```tsx
  const handleAddCustom = useCallback(
    (name: string, target: string) => {
      setCustomList((prev) => {
        const next = prev ?? [...serverCustomFields];
        if (!next.includes(name)) next.push(name);
        return [...next];
      });
      setLocalEdits((prev) => ({ ...prev, [name]: target }));
    },
    [serverCustomFields],
  );

  const handleRemoveCustom = useCallback(
    (name: string) => {
      setCustomList((prev) => {
        const next = prev ?? [...serverCustomFields];
        return next.filter((n) => n !== name);
      });
      setLocalEdits((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    },
    [serverCustomFields],
  );
```

Update `handleSave` payload:

```tsx
    try {
      await saveMutation.mutateAsync({
        id,
        mappings: mappingsPayload,
        customFields: effectiveCustomFields,
      });
      setLocalEdits({});
      setCustomList(null);
      setRowErrors({});
      notifySuccess(tSetup('mapping.saved'));
    } catch (error) {
      if (error instanceof ApiError && error.errors) {
        setRowErrors(parseRowErrors(error.errors));
      }
      notifyMutationError(error, tSetup('mapping.saveFailed'));
    }
  }, [effectiveMappings, effectiveCustomFields, id, saveMutation, tSetup]);
```

Replace the empty-state block — the table always renders (its add row makes the page usable for fresh, never-ingested sources), and the muted hint stays above it:

```tsx
      {sourceFields.length === 0 && (
        <Text c="dimmed" ta="center" py="xl">
          {tSetup('mapping.noSourceFields')}
        </Text>
      )}
      <MappingTable
        sourceFields={sourceFields}
        mappings={effectiveMappings}
        registryAttributes={Array.isArray(registryQuery.data) ? registryQuery.data : []}
        onChange={handleTargetChange}
        errors={rowErrors}
        customFields={effectiveCustomFields}
        onAddCustom={handleAddCustom}
        onRemoveCustom={handleRemoveCustom}
      />
```

(The MappingTable renders just the add row when both lists are empty; the muted hint stays above it.)

**Note:** the new test `it('shows the custom add row even when no source fields are observed')` asserts the muted hint (`/no source fields observed yet/i`) coexists with the add-row button — this shape satisfies it.

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/features/setup/MappingTab.test.tsx src/features/setup/MappingTable.test.tsx src/features/setup/SetupPage.test.tsx`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/features/setup/MappingTab.tsx src/features/setup/MappingTab.test.tsx
git commit -m "feat: MappingTab custom-field state and save payload with shadow handling"
```

---

### Task 10: Full gates + frontend docs

**Files:**
- Modify: `frontend/docs/architecture.md` (only if it describes mapping rows as observed-only — check and update)
- Docs: `backend/docs/api.md` already updated (Task 6); verify `docs/decisions.md` entry present.

**Interfaces:**
- Produces: green gate suite, docs consistent.

- [ ] **Step 1: Backend gates**

Run: `cd backend && uv run ruff check . && uv run mypy . && uv run pytest -n auto --report-log=.report.jsonl -q`
Expected: ruff count matches `docs/ruff-baseline.txt` (506) exactly, mypy exit 0, all tests pass. `.report.jsonl` is gitignored — never commit it.

- [ ] **Step 2: Frontend gates**

Run: `cd frontend && npm run test && npm run typecheck && npm run build`
Expected: all PASS

- [ ] **Step 3: Docs check**

- `frontend/docs/architecture.md`: if it documents the mapping table rows, add: observed rows + custom rows (add/remove, flat-name grammar, dormant until feed supplies key, observed shadows custom with indicator).
- `backend/docs/api.md`, `backend/docs/architecture.md`, `docs/decisions.md`: verify entries from Task 6 exist and mention: button-only automap (pipeline + dry-run never auto-match), `custom_fields` PUT/GET contract, baseline-name collision acceptance, observed/custom shadow rule.
- Spec cross-check: `docs/superpowers/specs/2026-09-11-...-design.md` §6 list is fully covered.

- [ ] **Step 4: Commit**

```bash
cd /home/ozon/gmc_feed_master && git add frontend/docs/architecture.md backend/docs/api.md backend/docs/architecture.md docs/decisions.md
git commit -m "docs: mapping UI custom fields and button-only automap documentation"
```

---

## Acceptance criteria (from spec §9 + directives)

1. Opening the Mapping tab never runs the auto-mapper; a fresh source stays empty until Auto-map or manual save. (Task 2/3 + no UI automap call on mount)
2. Pipeline runs and dry-runs produce no mappings and no `auto_mapped` flip on unmapped sources. (Tasks 2, 3; audit assertion in Task 2 Step 5f)
3. Custom source fields can be added (grammar-validated) and mapped to any registry target kind via FieldSelect, incl. indexed paths like `product_detail.2.attribute_value`. (Tasks 4, 7, 8, 9)
4. Custom rows are removable; observed fields remain read-only rows (clearing target = unmapping). (Task 8)
5. Custom rows persist across reloads and survive pipeline runs unchanged; activate automatically once the feed supplies the key. (Tasks 1, 4, 6)
6. Save sends mappings + custom_fields as one atomic PUT; 422 errors map to offending rows incl. custom names. (Tasks 4, 9)
7. Shadowed custom entries (observed name also custom) render one row with the indicator and a reachable remove control; removal removes the custom entry, not the observed mapping. (Tasks 8, 9)
8. `POST /auto` round-trips `custom_fields` unchanged. (Task 5)
9. A custom field named like a baseline field is accepted (documented accepted behavior). (Task 4 + Task 6 docs)
10. Full gate suite green at every milestone. (per-task runs + Task 10)
