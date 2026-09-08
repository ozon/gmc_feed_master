# Labelizer Priority Indicators & Synchronized Product Preview — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `#N` priority indicators to the slot selector and rule cards, and a synchronized, windowed product-preview column beside each rule card's value list, backed by a new batch lookup endpoint.

**Architecture:** New general backend route `POST /feed-sources/{id}/products/lookup` matches values against `raw_data[field]` (plugin `matches()` semantics, status-agnostic) and returns per-value count + lowest-`product_id` sample. Frontend: `useProductLookup` (TanStack Query, 300 ms debounce in the consumer), a pure `productPreview.ts` (fixed-row windowing + bidirectional scroll sync), a presentational `ProductPreviewColumn`, and a `RuleValuesEditor` that owns the 35/65 split inside `RuleCard`. No new npm dependencies.

**Tech Stack:** React 19, TypeScript, Mantine 9.5.2, TanStack Query, i18next (en/de), vitest + React Testing Library; FastAPI + SQLAlchemy async + pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-08-labelizer-product-preview-design.md` (read it first).
- Mantine 9.5.2 only; **no new npm dependencies** (no `@tanstack/react-virtual`).
- Matching must mirror the plugin's `matches()`/`resolve_path()` semantics: scalar → `[str(value)]` when non-empty; repeated/array → every non-empty element; `attr.sub` on dict → subfield when non-empty; `attr.sub` on list → only when exactly one dict element; dict without sub → no candidates. Status-agnostic.
- Lookup response: `{"matches": {"<value>": {"count": int, "sample": {...} | null}}}`; sample projected to `product_id, status, excluded, title, brand, availability` + requested `extraFields` (missing → `null`).
- Values limit: **1–10 000** after server-side dedupe (amend the spec's "2–10 000" line in Task 1 — controller-approved typo fix); `extraFields` limit 0–20.
- Row height is exactly `34` px; viewport `10` rows; overscan `5`; split is `Grid cols={20}` spans 7/13 (35 % / 65 %).
- Priority indicators: slot selector items labeled `#1 CUSTOM_LABEL_0` … `#5 CUSTOM_LABEL_4` (registry order); rule card header shows a dimmed `#N` Text BEFORE the rule name; the `#N Priority` Badge and i18n key `priority` are removed from both locales.
- Every user-visible string through i18next `customLabels` namespace; every new key in BOTH `en` and `de`.
- Frontend commands from `frontend/` (`npm run test -- --run <file>`, `npm run typecheck`); backend commands from `backend/` (`uv run pytest ...`; backend tests need `export TEST_DATABASE_URL=...` — a local PostgreSQL is running; ask the controller for the value file if missing).
- The custom_labels plugin runtime, its preview endpoint, scope merge, and save semantics are untouched.
- Commit style: conventional commits with scope.

---

### Task 1: Backend — batch product lookup endpoint

**Files:**
- Modify: `backend/app/routes/products.py` (append route + helpers)
- Test: `backend/tests/test_products_api.py` (append tests)
- Modify: `backend/docs/api.md` (append endpoint entry)
- Modify: `docs/superpowers/specs/2026-09-08-labelizer-product-preview-design.md` (typo fix: 2→1 minimum values)

**Interfaces:**
- Consumes: existing `_require_db`, `_require_feed_source` helpers in `backend/app/routes/products.py`; `StagingProduct` model.
- Produces: `POST /feed-sources/{feed_source_id}/products/lookup` with request `{field: str = "id", values: list[str], extraFields: list[str] = []}` and response `{"matches": {value: {"count": int, "sample": {...} | None}}}`. Task 2's frontend types consume this JSON shape exactly.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_products_api.py` (after the last test; reuse the file's existing `app_factory`, `logged_in_client`, `_setup_feed` fixtures and `_BASE` constant):

```python
LOOKUP_ROWS = [
    ("a1", {"id": "a1", **_BASE, "title": "Alpha", "brand": "Acme"}, "active"),
    ("a2", {"id": "a2", **_BASE, "title": "Beta", "brand": "Beta"}, "active"),
    ("arr1", {"id": "arr1", **_BASE, "title": "Array", "brand": ["Acme", "Beta"]}, "active"),
    ("b1", {"id": "b1", **_BASE, "title": "Clone", "brand": "Acme"}, "removed"),
    ("x1", {"id": "x1", **_BASE, "title": "Excl", "brand": "Acme"}, "active"),
    ("sub1", {"id": "sub1", **_BASE, "title": "Sub", "price": {"value": "10", "currency": "EUR"}}, "active"),
]


async def test_lookup_matches_by_field_counts_and_lowest_sample(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(factory, client, LOOKUP_ROWS)
    resp = await client.post(f"/feed-sources/{feed_id}/products/lookup", json={
        "field": "brand", "values": ["Acme", "Beta", "Gamma"],
        "extraFields": ["price"],
    })
    assert resp.status_code == 200
    matches = resp.json()["matches"]
    # Acme: a1 + arr1 (array element) + b1 (removed) + x1 (excluded) -> 4
    assert matches["Acme"] == {
        "count": 4,
        "sample": {
            "product_id": "a1", "status": "active", "excluded": False,
            "title": "Alpha", "brand": "Acme", "availability": "in_stock",
            "price": None,
        },
    }
    # Beta: a2 + arr1 -> 2, lowest product_id a2
    assert matches["Beta"]["count"] == 2
    assert matches["Beta"]["sample"]["product_id"] == "a2"
    assert matches["Gamma"] == {"count": 0, "sample": None}


async def test_lookup_default_field_is_id_and_dedupes_values(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(factory, client, LOOKUP_ROWS)
    resp = await client.post(f"/feed-sources/{feed_id}/products/lookup", json={
        "values": ["a1", "a1", "missing"],
    })
    assert resp.status_code == 200
    matches = resp.json()["matches"]
    assert set(matches) == {"a1", "missing"}
    assert matches["a1"]["sample"]["title"] == "Alpha"
    assert matches["missing"] == {"count": 0, "sample": None}


async def test_lookup_removed_sample_carries_status_and_excluded_flag(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(factory, client, [
        ("z9", {"id": "z9", **_BASE, "title": "Only", "brand": "Solo"}, "removed"),
        ("z10", {"id": "z10", **_BASE, "title": "Ex", "brand": "Solo2", "excluded": True}, "active"),
    ])
    resp = await client.post(f"/feed-sources/{feed_id}/products/lookup", json={
        "values": ["Solo", "Solo2"],
    })
    matches = resp.json()["matches"]
    assert matches["Solo"]["sample"]["status"] == "removed"
    assert matches["Solo"]["sample"]["excluded"] is False
    assert matches["Solo2"]["sample"]["excluded"] is True


async def test_lookup_subfield_path(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    feed_id = await _setup_feed(factory, client, LOOKUP_ROWS)
    resp = await client.post(f"/feed-sources/{feed_id}/products/lookup", json={
        "field": "price.value", "values": ["10"],
    })
    assert resp.json()["matches"]["10"]["count"] == 1


async def test_lookup_requires_auth_404_and_422(app_factory):
    app, _ = app_factory
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anon.post("/feed-sources/1/products/lookup", json={"values": ["a"]})).status_code == 401
    client = await logged_in_client(app_factory)
    assert (await client.post("/feed-sources/99999/products/lookup", json={"values": ["a"]})).status_code == 404
    assert (await client.post("/feed-sources/1/products/lookup", json={"values": []})).status_code == 422
    assert (await client.post("/feed-sources/1/products/lookup", json={
        "values": ["a"] * 10001,
    })).status_code == 422
    assert (await client.post("/feed-sources/1/products/lookup", json={
        "values": ["a"], "extraFields": [f"f{i}" for i in range(21)],
    })).status_code == 422
```

Note: `_setup_feed` accepts 3-tuples `(pid, raw, status)` (its `*rest` handling covers 3–5 elements) — `excluded` defaults to `False`.

Also append a candidate-extraction equivalence test (imports the plugin's `resolve_path` via the existing test loader):

```python
from tests.labels_plugin_module import labels_plugin as _labels_module


def test_lookup_candidates_mirror_plugin_resolve_path():
    resolve_path = _labels_module.resolve_path
    cases = [
        ({"a": "v"}, "a"),
        ({"a": ""}, "a"),
        ({"a": ["x", "", None, "y"]}, "a"),
        ({"a": {"s": "v"}}, "a.s"),
        ({"a": [{"s": "v"}]}, "a.s"),
        ({"a": [{"s": "v"}, {"s": "w"}]}, "a.s"),
        ({"a": {"s": ""}}, "a.s"),
        ({"a": 5}, "a"),
        ({}, "a"),
        ({"a": {"s": 1}}, "a.s"),
    ]
    for raw, path in cases:
        assert _product_field_candidates(raw, path) == resolve_path(raw, path), (raw, path)
```

(`_product_field_candidates` is imported at the top of the test file: `from app.routes.products import _product_field_candidates`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`, with `TEST_DATABASE_URL` exported): `uv run pytest tests/test_products_api.py -k lookup -q`
Expected: FAIL — route 404s (`Not Found`), `_product_field_candidates` import error.

- [ ] **Step 3: Implement the route**

Append to `backend/app/routes/products.py` (new imports at top: `from pydantic import BaseModel, Field`; `from fastapi import APIRouter, Depends, HTTPException, Query` already present):

```python
class _LookupRequest(BaseModel):
    field: str = "id"
    values: list[str] = Field(min_length=1, max_length=10_000)
    extraFields: list[str] = Field(default_factory=list, max_length=20)


def _product_field_candidates(raw: dict, path: str) -> list[str]:
    """Candidate values of a registry path in raw_data — mirrors the
    custom_labels plugin's resolve_path() semantics (scalar / repeated /
    attr.sub). Keep in sync with plugins/core/custom_labels/plugin.py."""
    head, _, sub = path.partition(".")
    value = raw.get(head)
    if value is None:
        return []
    if sub:
        if isinstance(value, dict):
            item = value.get(sub)
            return [str(item)] if item not in (None, "") else []
        if isinstance(value, list):
            if len(value) != 1 or not isinstance(value[0], dict):
                return []
            item = value[0].get(sub)
            return [str(item)] if item not in (None, "") else []
        return []
    if isinstance(value, str):
        return [value] if value != "" else []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _lookup_sample(row: StagingProduct, extra_fields: list[str]) -> dict:
    raw = row.raw_data or {}
    sample = {
        "product_id": row.product_id,
        "status": row.status,
        "excluded": row.excluded,
        "title": raw.get("title"),
        "brand": raw.get("brand"),
        "availability": raw.get("availability"),
    }
    for field in extra_fields:
        sample[field] = raw.get(field)
    return sample


@router.post("/feed-sources/{feed_source_id}/products/lookup")
async def lookup_products(
    feed_source_id: int,
    payload: _LookupRequest,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
        rows = (await session.execute(
            select(StagingProduct.product_id, StagingProduct.status,
                   StagingProduct.excluded, StagingProduct.raw_data)
            .where(StagingProduct.feed_source_id == feed_source_id)
        )).all()
        matches: dict[str, dict] = {
            value: {"count": 0, "sample_id": None}
            for value in dict.fromkeys(payload.values)
        }
        for product_id, _status, _excluded, raw in rows:
            for candidate in set(_product_field_candidates(raw or {}, payload.field)):
                entry = matches.get(candidate)
                if entry is None:
                    continue
                entry["count"] += 1
                if entry["sample_id"] is None or product_id < entry["sample_id"]:
                    entry["sample_id"] = product_id
        sample_ids = sorted(
            {entry["sample_id"] for entry in matches.values() if entry["sample_id"] is not None}
        )
        sample_rows: dict[str, StagingProduct] = {}
        if sample_ids:
            sample_rows = {
                row.product_id: row
                for row in (await session.execute(
                    select(StagingProduct).where(
                        StagingProduct.feed_source_id == feed_source_id,
                        StagingProduct.product_id.in_(sample_ids),
                    )
                )).scalars()
            }
    return {
        "matches": {
            value: {
                "count": entry["count"],
                "sample": (
                    _lookup_sample(sample_rows[entry["sample_id"]], payload.extraFields)
                    if entry["sample_id"] is not None else None
                ),
            }
            for value, entry in matches.items()
        }
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_products_api.py -q` then `uv run pytest tests/test_plugin_contract.py -q`
Expected: all PASS.

- [ ] **Step 5: Update docs + fix the spec typo**

In `backend/docs/api.md`, after the `GET /feed-sources/{id}/fields` entry, add:

```
- `POST /feed-sources/{id}/products/lookup` — batch value lookup over staged products. Body: `{field (registry attribute path, default "id"), values (1–10 000, deduped server-side), extraFields (0–20)}`. Response `{matches: {<value>: {count, sample: {product_id, status, excluded, title, brand, availability, <extraFields…>} | null}}}` — `count` = staged products (any status) whose `raw_data[field]` contains the value (scalar equality, repeated fields match any element, `attr.sub` subfields resolve; mirrors the custom_labels plugin's match semantics); `sample` = the match with the lowest `product_id`. 404 unknown feed source; 422 invalid body; 503 database unavailable.
```

In `docs/superpowers/specs/2026-09-08-labelizer-product-preview-design.md`, change `values: string[] (2–10 000 after dedupe)` to `values: string[] (1–10 000 after dedupe)` (controller-approved typo fix).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/products.py backend/tests/test_products_api.py backend/docs/api.md docs/superpowers/specs/2026-09-08-labelizer-product-preview-design.md
git commit -m "feat(backend): batch product lookup endpoint for value lists"
```

---

### Task 2: Frontend — lookup types, query key, and `useProductLookup`

**Files:**
- Modify: `frontend/src/api/types.ts` (append types)
- Modify: `frontend/src/api/queryKeys.ts:9-21` (add `productLookup` key)
- Modify: `frontend/src/api/hooks.ts` (append hook)
- Test: `frontend/src/features/customLabels/useProductLookup.test.tsx` (create)

**Interfaces:**
- Consumes: the Task 1 JSON shape; existing `apiPost` (`apiPost<T>(url, body)`) and `queryKeys.feedSource(id)` pattern.
- Produces: `ProductLookupSample`, `ProductLookupMatch = { count: number; sample: ProductLookupSample | null }`, `ProductLookupResponse`; `useProductLookup(feedSourceId: number | undefined, field: string, values: string[], extraFields: string[])` returning the TanStack Query result of `ProductLookupResponse` (debounce is the consumer's job — Task 7).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/customLabels/useProductLookup.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { useProductLookup } from '../../api/hooks';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const RESPONSE = {
  matches: {
    a1: {
      count: 1,
      sample: {
        product_id: 'a1', status: 'active', excluded: false,
        title: 'Alpha', brand: 'Acme', availability: 'in_stock',
      },
    },
    zz: { count: 0, sample: null },
  },
};

function Probe(props: { feedSourceId?: number; field?: string; values?: string[]; extraFields?: string[] }) {
  const query = useProductLookup(
    props.feedSourceId,
    props.field ?? 'id',
    props.values ?? [],
    props.extraFields ?? [],
  );
  return (
    <div>
      <span data-testid="pending">{String(query.isPending)}</span>
      <span data-testid="count">{query.data?.matches.a1?.count ?? ''}</span>
    </div>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('useProductLookup', () => {
  it('posts the lookup body and returns the mapped response', async () => {
    const bodies: unknown[] = [];
    stubFetch((url, init) => {
      if (url.includes('/products/lookup')) {
        bodies.push(JSON.parse(String(init?.body)));
        return jsonResponse(RESPONSE);
      }
      return jsonResponse({});
    });
    render(<Probe feedSourceId={3} values={['a1', 'zz']} extraFields={['price']} />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="count"]')?.textContent).toBe('1'),
      { timeout: 5000 },
    )).toBeTruthy();
    expect(bodies).toEqual([
      { field: 'id', values: ['a1', 'zz'], extraFields: ['price'] },
    ]);
  });

  it('sends no request without a feed source or with no values', async () => {
    const calls: string[] = [];
    stubFetch((url) => {
      calls.push(url);
      return jsonResponse({});
    });
    render(<Probe values={['a1']} />);
    render(<Probe feedSourceId={3} values={[]} />);
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(calls.some((u) => u.includes('/products/lookup'))).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm run test -- --run src/features/customLabels/useProductLookup.test.tsx`
Expected: FAIL — `useProductLookup` is not exported.

- [ ] **Step 3: Implement types, key, and hook**

1. Append to `frontend/src/api/types.ts`:

```ts
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
```

2. In `frontend/src/api/queryKeys.ts`, inside the `feedSource: (id) => ({ ... })` object add after the `fields:` line:

```ts
    productLookup: (params: unknown) => ['feed-source', id, 'product-lookup', params] as const,
```

3. Append to `frontend/src/api/hooks.ts` (add `ProductLookupResponse` to the existing `./types` import list):

```ts
export function useProductLookup(
  feedSourceId: number | undefined,
  field: string,
  values: string[],
  extraFields: string[],
) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId ?? 0)
      .productLookup({ field, values, extraFields }),
    queryFn: () =>
      apiPost<ProductLookupResponse>(
        `/feed-sources/${feedSourceId}/products/lookup`,
        { field, values, extraFields },
      ),
    enabled: feedSourceId !== undefined && values.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm run test -- --run src/features/customLabels/useProductLookup.test.tsx && npm run typecheck`
Expected: 2 tests PASS, typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/queryKeys.ts frontend/src/api/hooks.ts frontend/src/features/customLabels/useProductLookup.test.tsx
git commit -m "feat(frontend): useProductLookup hook with query caching"
```

---

### Task 3: Frontend — `parseIdEntries` (ordered, non-deduped)

**Files:**
- Modify: `frontend/src/features/customLabels/ids.ts` (append function)
- Test: `frontend/src/features/customLabels/ids.test.ts` (append tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `parseIdEntries(raw: string | undefined | null): string[]` — ordered, trimmed, empty-dropped, duplicates preserved. Task 7 relies on row *i* = `entries[i]`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/features/customLabels/ids.test.ts`:

```ts
describe('parseIdEntries', () => {
  it('preserves order and duplicates, drops empties', () => {
    expect(parseIdEntries('b, a\n\n a \nc,\n')).toEqual(['b', 'a', 'a', 'c']);
  });

  it('returns an empty array for empty input', () => {
    expect(parseIdEntries('')).toEqual([]);
    expect(parseIdEntries(undefined)).toEqual([]);
    expect(parseIdEntries(null)).toEqual([]);
  });
});
```

(Add `parseIdEntries` to the existing import from `./ids` in that file.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- --run src/features/customLabels/ids.test.ts`
Expected: FAIL — `parseIdEntries` is not exported.

- [ ] **Step 3: Implement**

Append to `frontend/src/features/customLabels/ids.ts`:

```ts
/** Ordered, trimmed, empty-dropped entries WITHOUT dedupe — row i of the
 * product preview aligns with entry i. */
export function parseIdEntries(raw: string | undefined | null): string[] {
  if (!raw) return [];
  const entries: string[] = [];
  for (const part of raw.split(/[\n,]+/)) {
    const trimmed = part.trim();
    if (trimmed) entries.push(trimmed);
  }
  return entries;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm run test -- --run src/features/customLabels/ids.test.ts`
Expected: all PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/ids.ts frontend/src/features/customLabels/ids.test.ts
git commit -m "feat(frontend): parseIdEntries for ordered preview rows"
```

---

### Task 4: i18n keys (en + de)

**Files:**
- Modify: `frontend/public/locales/en/customLabels.json`
- Modify: `frontend/public/locales/de/customLabels.json`

**Interfaces:**
- Produces (consumed by Tasks 6–8): `idNotFoundInFeed`, `noMatchInFeed`, `nProducts_one`, `nProducts_other`, `previewTitle`, `previewFieldsLabel`, `previewEmpty`, `previewError`, `previewPending`, `stateRemoved`, `stateExcluded`. Removes `priority` (Task 7 deletes its only usage).

- [ ] **Step 1: Add keys to the en locale**

In `frontend/public/locales/en/customLabels.json`, add these top-level keys (e.g. directly after the `"shadowedBy"` key) and DELETE the existing `"priority": "#{{index}} Priority",` line:

```json
  "idNotFoundInFeed": "ID not found in feed",
  "noMatchInFeed": "No match in feed",
  "nProducts_one": "{{count}} product",
  "nProducts_other": "{{count}} products",
  "previewTitle": "Matched products",
  "previewFieldsLabel": "Additional fields",
  "previewEmpty": "No values yet — the preview follows the list on the left.",
  "previewError": "Product lookup failed.",
  "previewPending": "Looking up products…",
  "stateRemoved": "removed",
  "stateExcluded": "excluded",
```

- [ ] **Step 2: Add keys to the de locale**

In `frontend/public/locales/de/customLabels.json`, mirror the same placement; add:

```json
  "idNotFoundInFeed": "ID nicht im Feed gefunden",
  "noMatchInFeed": "Kein Treffer im Feed",
  "nProducts_one": "{{count}} Produkt",
  "nProducts_other": "{{count}} Produkte",
  "previewTitle": "Passende Produkte",
  "previewFieldsLabel": "Zusätzliche Felder",
  "previewEmpty": "Noch keine Werte — die Vorschau folgt der Liste links.",
  "previewError": "Produkt-Suche fehlgeschlagen.",
  "previewPending": "Suche Produkte…",
  "stateRemoved": "entfernt",
  "stateExcluded": "ausgeschlossen",
```

and DELETE the `"priority"` line there too.

- [ ] **Step 3: Verify parity and validity**

Run (from the repo root): `node -e "const en=require('./frontend/public/locales/en/customLabels.json');const de=require('./frontend/public/locales/de/customLabels.json');const flat=(o,p='')=>Object.entries(o).flatMap(([k,v])=>typeof v==='object'?flat(v,p+k+'.'):[p+k]);const ek=new Set(flat(en)),dk=new Set(flat(de));const miss=[...ek].filter(k=>!dk.has(k)).concat([...dk].filter(k=>!ek.has(k)));if(miss.length)throw new Error('parity miss: '+miss);console.log('keys ok:',ek.size)"`
Expected: `keys ok: <N>`, no error.

- [ ] **Step 4: Commit**

```bash
git add frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json
git commit -m "feat(frontend): labelizer product preview i18n keys"
```

---

### Task 5: Frontend — windowing + scroll-sync primitives (`productPreview.ts`)

**Files:**
- Create: `frontend/src/features/customLabels/productPreview.ts`
- Test: `frontend/src/features/customLabels/productPreview.test.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ROW_HEIGHT = 34`, `VIEWPORT_ROWS = 10`, `OVERSCAN = 5`; `windowRange(scrollTop: number, totalRows: number): [number, number]`; `availabilityColor(availability: string | null | undefined): 'green' | 'red' | 'gray'`; `useSyncedScroll(textareaRef, previewRef, onScrollTopChange)` — native bidirectional `scrollTop` sync with a rAF-released guard flag. Tasks 6 and 7 consume these exact names.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/customLabels/productPreview.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { OVERSCAN, ROW_HEIGHT, VIEWPORT_ROWS, availabilityColor, windowRange } from './productPreview';

describe('windowRange', () => {
  it('starts at 0 and covers the viewport plus overscan', () => {
    expect(windowRange(0, 1000)).toEqual([0, VIEWPORT_ROWS + OVERSCAN]);
  });

  it('shifts with scrollTop in row-height steps', () => {
    const top = 5 * ROW_HEIGHT; // scrolled past 5 rows
    const [start, end] = windowRange(top, 1000);
    expect(start).toBe(5 - OVERSCAN);
    expect(end).toBe(5 + VIEWPORT_ROWS + OVERSCAN);
  });

  it('clamps to the total', () => {
    expect(windowRange(10_000 * ROW_HEIGHT, 12)).toEqual([12, 12]);
  });

  it('handles zero rows without a negative start', () => {
    expect(windowRange(0, 0)).toEqual([0, 0]);
  });
});

describe('availabilityColor', () => {
  it('maps in_stock green, out_of_stock red, everything else gray', () => {
    expect(availabilityColor('in_stock')).toBe('green');
    expect(availabilityColor('out_of_stock')).toBe('red');
    expect(availabilityColor('preorder')).toBe('gray');
    expect(availabilityColor(null)).toBe('gray');
    expect(availabilityColor(undefined)).toBe('gray');
  });
});
```

The clamp test's exact expectation: with `totalRows = 12`, `scrollTop = 10_000 * ROW_HEIGHT`: `first = max(0, floor(scrollTop/34) - 5)` is huge, so `start` must clamp to `12 - ...`? No — write the implementation so `first = Math.min(totalRows, Math.max(0, floor(scrollTop/ROW_HEIGHT) - OVERSCAN))` and `last = Math.min(totalRows, first + VIEWPORT_ROWS + 2 * OVERSCAN)`. With totalRows 12 and huge scrollTop: first = 12, last = 12 → range [12, 12]. Fix the test expectation to `toEqual([12, 12])` before implementing (use this version):

```ts
  it('clamps to the total', () => {
    expect(windowRange(10_000 * ROW_HEIGHT, 12)).toEqual([12, 12]);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm run test -- --run src/features/customLabels/productPreview.test.ts`
Expected: FAIL — cannot resolve `./productPreview`.

- [ ] **Step 3: Implement**

Create `frontend/src/features/customLabels/productPreview.ts`:

```ts
import { useEffect, useRef, type RefObject } from 'react';

export const ROW_HEIGHT = 34;
export const VIEWPORT_ROWS = 10;
export const OVERSCAN = 5;

/** [start, end) slice of rows to render for a scrollTop, fixed-row windowing. */
export function windowRange(scrollTop: number, totalRows: number): [number, number] {
  const firstRow = Math.floor(scrollTop / ROW_HEIGHT);
  const first = Math.min(totalRows, Math.max(0, firstRow - OVERSCAN));
  const last = Math.min(totalRows, firstRow + VIEWPORT_ROWS + OVERSCAN);
  return [first, Math.max(first, last)];
}

export function availabilityColor(
  availability: string | null | undefined,
): 'green' | 'red' | 'gray' {
  if (availability === 'in_stock') return 'green';
  if (availability === 'out_of_stock') return 'red';
  return 'gray';
}

/**
 * Bidirectional scrollTop sync between the values textarea and the preview
 * viewport. A guard flag (released on the next animation frame) stops the
 * programmatic set on the target from re-triggering the handler.
 */
export function useSyncedScroll(
  textareaRef: RefObject<HTMLTextAreaElement | null>,
  previewRef: RefObject<HTMLDivElement | null>,
  onScrollTopChange: (top: number) => void,
): void {
  const callbackRef = useRef(onScrollTopChange);
  callbackRef.current = onScrollTopChange;
  useEffect(() => {
    const textarea = textareaRef.current;
    const preview = previewRef.current;
    if (!textarea || !preview) return;
    let syncing = false;
    const release = () => requestAnimationFrame(() => { syncing = false; });
    const onTextareaScroll = () => {
      if (syncing) return;
      syncing = true;
      preview.scrollTop = textarea.scrollTop;
      callbackRef.current(textarea.scrollTop);
      release();
    };
    const onPreviewScroll = () => {
      if (syncing) return;
      syncing = true;
      textarea.scrollTop = preview.scrollTop;
      callbackRef.current(preview.scrollTop);
      release();
    };
    textarea.addEventListener('scroll', onTextareaScroll);
    preview.addEventListener('scroll', onPreviewScroll);
    return () => {
      textarea.removeEventListener('scroll', onTextareaScroll);
      preview.removeEventListener('scroll', onPreviewScroll);
    };
  }, [textareaRef, previewRef]);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm run test -- --run src/features/customLabels/productPreview.test.ts && npm run typecheck`
Expected: 5 tests PASS, typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/productPreview.ts frontend/src/features/customLabels/productPreview.test.ts
git commit -m "feat(frontend): labelizer preview windowing and scroll-sync primitives"
```

---

### Task 6: Frontend — `ProductPreviewColumn` component

**Files:**
- Create: `frontend/src/features/customLabels/ProductPreviewColumn.tsx`
- Test: `frontend/src/features/customLabels/ProductPreviewColumn.test.tsx`

**Interfaces:**
- Consumes: `windowRange`, `ROW_HEIGHT`, `VIEWPORT_ROWS`, `availabilityColor` from `./productPreview` (Task 5); `ProductLookupMatch` from `../../api/types` (Task 2); i18n keys (Task 4).
- Produces: `ProductPreviewColumn` with props `{ field: string; entries: string[]; matches: ReadonlyMap<string, ProductLookupMatch> | null; isPending: boolean; isError: boolean; extraFields: string[]; scrollTop: number; viewportRef: RefObject<HTMLDivElement | null> }`; testids `product-preview-viewport`, `preview-row-${index}`, `preview-empty`, `preview-error`. Task 7 renders it inside `RuleValuesEditor`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/customLabels/ProductPreviewColumn.test.tsx`:

```tsx
import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { createRef } from 'react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { ProductPreviewColumn } from './ProductPreviewColumn';
import type { ProductLookupMatch, ProductLookupSample } from '../../api/types';

function match(count: number, sample: Partial<ProductLookupSample> | null): ProductLookupMatch {
  return {
    count,
    sample: sample === null ? null : {
      product_id: 'p1', status: 'active', excluded: false,
      title: 'T', brand: 'B', availability: 'in_stock', ...sample,
    },
  };
}

function renderColumn(over: Partial<Parameters<typeof ProductPreviewColumn>[0]> = {}) {
  const viewportRef = createRef<HTMLDivElement>();
  render(
    <ProductPreviewColumn
      field="id"
      entries={['a1', 'zz', 'a1']}
      matches={new Map([
        ['a1', match(1, { title: 'Alpha', brand: 'Acme', availability: 'in_stock' })],
        ['zz', match(0, null)],
      ])}
      isPending={false}
      isError={false}
      extraFields={['price']}
      scrollTop={0}
      viewportRef={viewportRef}
      {...over}
    />,
  );
  return { viewportRef };
}

beforeAll(async () => {
  await i18n.loadNamespaces(['customLabels']);
});

describe('ProductPreviewColumn', () => {
  it('renders one row per entry in order, aligned by index', () => {
    renderColumn();
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Alpha');
    expect(screen.getByTestId('preview-row-1')).toHaveTextContent('ID not found in feed');
    // duplicates render duplicated rows
    expect(screen.getByTestId('preview-row-2')).toHaveTextContent('Alpha');
  });

  it('renders availability and status badges on the sample', () => {
    renderColumn();
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('in_stock');
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('Acme');
  });

  it('shows a count badge when one value matches several products', () => {
    renderColumn({
      entries: ['a1'],
      matches: new Map([['a1', match(7, { title: 'First' })]]),
    });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('7 products');
  });

  it('renders extra fields inline', () => {
    renderColumn({
      entries: ['a1'],
      matches: new Map([['a1', match(1, { price: '9.99 EUR' })]]),
    });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('9.99 EUR');
  });

  it('dims removed and excluded samples with a status badge', () => {
    renderColumn({
      entries: ['r1', 'e1'],
      matches: new Map([
        ['r1', match(1, { status: 'removed', title: 'Gone' })],
        ['e1', match(1, { excluded: true, title: 'Hidden' })],
      ]),
    });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('removed');
    expect(screen.getByTestId('preview-row-1')).toHaveTextContent('excluded');
  });

  it('uses the no-match label for non-id fields', () => {
    renderColumn({ field: 'brand', entries: ['zz'] });
    expect(screen.getByTestId('preview-row-0')).toHaveTextContent('No match in feed');
  });

  it('windows rows: renders only the slice for the given scrollTop', () => {
    const entries = Array.from({ length: 1000 }, (_, i) => `v${i}`);
    renderColumn({ entries, matches: null, isPending: false, scrollTop: 34 * 500 });
    expect(screen.getByTestId('preview-row-495')).toBeInTheDocument();
    expect(screen.queryByTestId('preview-row-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('preview-row-600')).not.toBeInTheDocument();
  });

  it('shows the empty hint for an empty list', () => {
    renderColumn({ entries: [] });
    expect(screen.getByTestId('preview-empty')).toBeInTheDocument();
  });

  it('shows the error line when the lookup failed', () => {
    renderColumn({ isError: true, matches: null, entries: ['a1'] });
    expect(screen.getByTestId('preview-error')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm run test -- --run src/features/customLabels/ProductPreviewColumn.test.tsx`
Expected: FAIL — cannot resolve `./ProductPreviewColumn`.

- [ ] **Step 3: Implement**

Create `frontend/src/features/customLabels/ProductPreviewColumn.tsx`:

```tsx
import { Badge, Box, Group, Skeleton, Stack, Text, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { RefObject } from 'react';
import type { ProductLookupMatch } from '../../api/types';
import { ROW_HEIGHT, VIEWPORT_ROWS, availabilityColor, windowRange } from './productPreview';

export type ProductPreviewColumnProps = {
  field: string;
  entries: string[];
  matches: ReadonlyMap<string, ProductLookupMatch> | null;
  isPending: boolean;
  isError: boolean;
  extraFields: string[];
  scrollTop: number;
  viewportRef: RefObject<HTMLDivElement | null>;
};

export function ProductPreviewColumn({
  field, entries, matches, isPending, isError, extraFields, scrollTop, viewportRef,
}: ProductPreviewColumnProps) {
  const { t } = useTranslation('customLabels');
  const total = entries.length;
  const [start, end] = windowRange(scrollTop, total);

  return (
    <Stack gap={4} data-testid="product-preview-column">
      {isError ? (
        <Text size="xs" c="red" data-testid="preview-error">{t('previewError')}</Text>
      ) : null}
      {total === 0 ? (
        <Text size="xs" c="dimmed" data-testid="preview-empty">{t('previewEmpty')}</Text>
      ) : (
        <Box
          ref={viewportRef}
          data-testid="product-preview-viewport"
          style={{
            height: VIEWPORT_ROWS * ROW_HEIGHT,
            overflowY: 'auto',
            border: 'calc(0.0625rem * var(--mantine-scale)) solid var(--mantine-color-default-border)',
            borderRadius: 'var(--mantine-radius-sm)',
          }}
        >
          <div style={{ height: total * ROW_HEIGHT, position: 'relative' }}>
            {entries.slice(start, end).map((value, offset) => {
              const index = start + offset;
              const match = matches?.get(value) ?? null;
              return (
                <Group
                  key={`${index}-${value}`}
                  gap="xs"
                  wrap="nowrap"
                  px="xs"
                  style={{
                    position: 'absolute',
                    top: index * ROW_HEIGHT,
                    height: ROW_HEIGHT,
                    left: 0,
                    right: 0,
                    alignItems: 'center',
                  }}
                  data-testid={`preview-row-${index}`}
                >
                  <PreviewRow field={field} value={value} match={match} isPending={isPending} extraFields={extraFields} />
                </Group>
              );
            })}
          </div>
        </Box>
      )}
    </Stack>
  );
}

function PreviewRow({
  field, value, match, isPending, extraFields,
}: {
  field: string;
  value: string;
  match: ProductLookupMatch | null;
  isPending: boolean;
  extraFields: string[];
}) {
  const { t } = useTranslation('customLabels');
  if (match === null && isPending) {
    return (
      <Group gap="xs" wrap="nowrap" w="100%">
        <Skeleton height={14} width="45%" />
        <Skeleton height={14} width="20%" />
      </Group>
    );
  }
  if (match === null || match.count === 0) {
    return (
      <Badge size="xs" variant="light" color="red">
        {field === 'id' ? t('idNotFoundInFeed') : t('noMatchInFeed')}
      </Badge>
    );
  }
  const sample = match.sample;
  if (sample === null) return null;
  const title = sample.title === null ? value : sample.title;
  return (
    <Group gap="xs" wrap="nowrap" w="100%" style={{ minHeight: 0 }}>
      {match.count > 1 && (
        <Badge size="xs" variant="light" color="gray">
          {t('nProducts', { count: match.count })}
        </Badge>
      )}
      <Tooltip label={title} withArrow position="top" openDelay={300}>
        <Text size="xs" truncate style={{ flex: 1, minWidth: 0 }}>{title}</Text>
      </Tooltip>
      <Text size="xs" c="dimmed" truncate maw={120}>
        {sample.brand ?? '—'}
      </Text>
      <Badge size="xs" variant="light" color={availabilityColor(sample.availability)}>
        {sample.availability ?? '—'}
      </Badge>
      {extraFields.map((fieldName) => (
        <Text key={fieldName} size="xs" c="dimmed" truncate maw={160}>
          {sample[fieldName] == null ? '' : String(sample[fieldName])}
        </Text>
      ))}
      {sample.status === 'removed' && (
        <Badge size="xs" variant="light" color="gray">{t('stateRemoved')}</Badge>
      )}
      {sample.excluded && (
        <Badge size="xs" variant="light" color="gray">{t('stateExcluded')}</Badge>
      )}
    </Group>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm run test -- --run src/features/customLabels/ProductPreviewColumn.test.tsx && npm run typecheck`
Expected: all PASS, typecheck clean. (Mantine `Group` accepts `px` and `data-testid` via the factory; if the `px` style prop on Group warns, move it into `style={{ paddingLeft/Right: 'var(--mantine-spacing-xs)' }}` — assertion-neutral.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/ProductPreviewColumn.tsx frontend/src/features/customLabels/ProductPreviewColumn.test.tsx
git commit -m "feat(frontend): labelizer product preview column"
```

---

### Task 7: Frontend — `RuleValuesEditor` + RuleCard integration

**Files:**
- Create: `frontend/src/features/customLabels/RuleValuesEditor.tsx`
- Modify: `frontend/src/features/customLabels/RuleCard.tsx` (priority indicator; values branch delegates to `RuleValuesEditor`; new props)
- Test: `frontend/src/features/customLabels/RuleCard.test.tsx` (update + extend)

**Interfaces:**
- Consumes: `useProductLookup` (Task 2), `parseIdEntries` (Task 3), `useSyncedScroll`/`ROW_HEIGHT`/`VIEWPORT_ROWS` (Task 5), `ProductPreviewColumn` (Task 6), `useFeedSourceFields` from `../../api/hooks`, i18n keys (Task 4).
- Produces: `RuleValuesEditorProps = { rule: ScopedSlotRule; value: string; feedSourceId: number | undefined; extraFields: string[]; onExtraFieldsChange: (fields: string[]) => void; onSetIds: (value: string) => void }`. `RuleCardProps` gains `feedSourceId?: number`, `extraFields: string[]`, `onExtraFieldsChange: (fields: string[]) => void`. Task 8 passes these from `CustomLabelsUI`; the rule card header priority badge testid `priority-badge` now contains just `#N`.

- [ ] **Step 1: Update RuleCard tests (failing first)**

In `frontend/src/features/customLabels/RuleCard.test.tsx`:

1. Change the collapsed-header assertion `expect(screen.getByText('#1 Priority')).toBeInTheDocument();` to `expect(screen.getByText('#1')).toBeInTheDocument();`.
2. Extend `renderCard` to pass the new props (defaults: `feedSourceId: undefined`, `extraFields: []`, `onExtraFieldsChange: () => {}`).
3. Append two new tests:

```tsx
  it('header shows the compact #N before the rule name', () => {
    renderCard();
    const badge = screen.getByTestId('priority-badge');
    expect(badge).toHaveTextContent('#1');
    // #N precedes the name in DOM order
    expect(badge.compareDocumentPosition(screen.getByText('Mid Funnel')))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('with a feed source renders the split editor and preview rows', async () => {
    stubFetch((url) => {
      if (url.includes('/products/lookup')) {
        return jsonResponse({
          matches: {
            a1: {
              count: 1,
              sample: {
                product_id: 'a1', status: 'active', excluded: false,
                title: 'Alpha', brand: 'Acme', availability: 'in_stock',
              },
            },
          },
        });
      }
      return jsonResponse({});
    });
    renderCard({
      feedSourceId: 5,
      value: 'a1,zz',
    });
    await userEvent.click(screen.getByText('Mid Funnel'));
    const viewport = await screen.findByTestId('product-preview-viewport');
    expect(viewport).toBeInTheDocument();
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(await screen.findByText('ID not found in feed')).toBeInTheDocument();
  });
```

Add `stubFetch` and `jsonResponse` imports to the test file (`import { stubFetch } from '../../test/fetch';` plus the local `jsonResponse` helper identical to other test files).

4. After implementing (Step 3), the existing type-into-textarea test still passes because `feedSourceId: undefined` renders the full-width editor.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm run test -- --run src/features/customLabels/RuleCard.test.tsx`
Expected: FAIL — `#1` text missing (still `#1 Priority`), `RuleValuesEditor`/split not implemented.

- [ ] **Step 3: Implement `RuleValuesEditor` and rewire `RuleCard`**

Create `frontend/src/features/customLabels/RuleValuesEditor.tsx`:

```tsx
import { useCallback, useMemo, useRef, useState } from 'react';
import { CloseButton, Grid, Group, MultiSelect, Stack, Text, Textarea } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { useFeedSourceFields, useProductLookup } from '../../api/hooks';
import { parseIdEntries, parseIdList } from './ids';
import { ProductPreviewColumn } from './ProductPreviewColumn';
import { useSyncedScroll } from './productPreview';
import type { ScopedSlotRule } from './scopeMerge';

export type RuleValuesEditorProps = {
  rule: ScopedSlotRule;
  value: string;
  feedSourceId: number | undefined;
  extraFields: string[];
  onExtraFieldsChange: (fields: string[]) => void;
  onSetIds: (value: string) => void;
};

const PREVIEW_DEFAULT_FIELDS = new Set(['title', 'brand', 'availability']);

export function RuleValuesEditor({
  rule, value, feedSourceId, extraFields, onExtraFieldsChange, onSetIds,
}: RuleValuesEditorProps) {
  const { t } = useTranslation('customLabels');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const onScrollTopChange = useCallback((top: number) => setScrollTop(top), []);
  useSyncedScroll(textareaRef, previewRef, onScrollTopChange);

  const entries = useMemo(() => parseIdEntries(value), [value]);
  const uniqueValues = useMemo(() => Array.from(new Set(entries)), [entries]);
  const debouncedValues = useDebouncedValue(uniqueValues, 300);
  const lookup = useProductLookup(feedSourceId, rule.matchField, debouncedValues, extraFields);
  const matches = useMemo(
    () => (lookup.data ? new Map(Object.entries(lookup.data.matches)) : null),
    [lookup.data],
  );

  const fieldsQuery = useFeedSourceFields(String(feedSourceId ?? ''));
  const fieldOptions = useMemo(
    () => (fieldsQuery.data?.fields ?? []).filter((f) => !PREVIEW_DEFAULT_FIELDS.has(f)),
    [fieldsQuery.data],
  );

  const count = parseIdList(value).size;
  const label = rule.matchField === 'id'
    ? t('bulk.productIds')
    : t('bulk.valuesFor', { field: rule.matchField });
  const ariaLabel = rule.matchField === 'id'
    ? `${t('bulk.productIds')} — ${rule.name}`
    : `${t('bulk.valuesFor', { field: rule.matchField })} — ${rule.name}`;

  const textarea = (
    <Textarea
      label={label}
      aria-label={ariaLabel}
      ref={textareaRef}
      minRows={10}
      maxRows={10}
      autosize
      wrap="off"
      styles={{
        input: {
          lineHeight: '34px',
          fontFamily: 'var(--mantine-font-family-monospace)',
          overflowX: 'auto',
        },
      }}
      value={value}
      onChange={(e) => onSetIds(e.currentTarget.value)}
      placeholder={t('idsPlaceholder')}
    />
  );

  const footer = (
    <Group gap="xs" justify="space-between" wrap="nowrap">
      <Text size="xs" c="dimmed" data-testid={`id-count-${rule.id}`}>
        {t('idCount', { count })}
      </Text>
      <Group gap={6} wrap="nowrap">
        <Text size="xs" c="dimmed">{rule.matchField}</Text>
        {value !== '' && (
          <CloseButton
            size="xs"
            aria-label={`${t('clearValues')} — ${rule.name}`}
            onClick={() => onSetIds('')}
          />
        )}
      </Group>
    </Group>
  );

  if (feedSourceId === undefined) {
    return (
      <Stack gap={4}>
        {textarea}
        {footer}
      </Stack>
    );
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between" wrap="wrap">
        <Text size="sm" fw={600}>{t('previewTitle')}</Text>
        <MultiSelect
          size="xs"
          w={260}
          clearable
          searchable
          aria-label={t('previewFieldsLabel')}
          data={fieldOptions}
          value={extraFields}
          onChange={(v) => onExtraFieldsChange(v ?? [])}
          placeholder={t('previewFieldsLabel')}
          data-testid={`preview-fields-${rule.id}`}
        />
      </Group>
      <Grid cols={20} gutter="xs">
        <Grid.Col span={7}>{textarea}</Grid.Col>
        <Grid.Col span={13}>
          <ProductPreviewColumn
            field={rule.matchField}
            entries={entries}
            matches={matches}
            isPending={lookup.isPending}
            isError={lookup.isError}
            extraFields={extraFields}
            scrollTop={scrollTop}
            viewportRef={previewRef}
          />
        </Grid.Col>
      </Grid>
      {footer}
    </Stack>
  );
}
```

Then edit `frontend/src/features/customLabels/RuleCard.tsx`:

1. Extend `RuleCardProps` with:

```ts
  feedSourceId?: number;
  extraFields: string[];
  onExtraFieldsChange: (fields: string[]) => void;
```

(destructure them in the component signature) and import `RuleValuesEditor`:

```ts
import { RuleValuesEditor } from './RuleValuesEditor';
```

2. Replace the priority Badge in the header (lines 45-47) with a compact indicator BEFORE the name — move it in front of the `Indicator`:

```tsx
        <Group gap="xs" wrap="nowrap">
          <Text size="xs" c="dimmed" component="span" data-testid="priority-badge">
            {`#${priority}`}
          </Text>
          <Indicator color="orange" size={8} offset={-4} position="top-end" disabled={!dirty}>
            <Text size="sm" fw={600} component="span">{rule.name}</Text>
          </Indicator>
```

3. Replace the entire values-mode branch (the `<Stack gap={4}>` holding the Textarea + counter row, lines ~99-135) with:

```tsx
            <RuleValuesEditor
              rule={rule}
              value={value}
              feedSourceId={feedSourceId}
              extraFields={extraFields}
              onExtraFieldsChange={onExtraFieldsChange}
              onSetIds={onSetIds}
            />
```

The all-mode branch and `ShadowList` stay unchanged. The now-unused imports (`Textarea`, `parseIdList`, `CloseButton`) move with the code into `RuleValuesEditor` — remove them from `RuleCard.tsx` (`renderPreview` stays for the template preview text; `parseIdList` import goes, `parseIdEntries` is not needed in RuleCard).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm run test -- --run src/features/customLabels/RuleCard.test.tsx && npm run typecheck`
Expected: all PASS (existing 5 + 2 new), typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/RuleValuesEditor.tsx frontend/src/features/customLabels/RuleCard.tsx frontend/src/features/customLabels/RuleCard.test.tsx
git commit -m "feat(frontend): rule values editor with synchronized product preview"
```

---

### Task 8: Frontend — SlotSelector `#N` labels + CustomLabelsUI wiring + integration tests

**Files:**
- Modify: `frontend/src/features/customLabels/SlotSelector.tsx:22` (labels)
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx` (extra-fields state; pass-through props on `RuleCard`)
- Test: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx` (label updates + new integration tests)

**Interfaces:**
- Consumes: `RuleCard`'s new props (Task 7).
- Produces: slot labels `#1 CUSTOM_LABEL_0` … `#5 CUSTOM_LABEL_4`; per-rule extra-field selections stored in `CustomLabelsUI` local state (survives accordion collapse).

- [ ] **Step 1: Update the failing tests first**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`:

1. Slot-label replacements (exact five sites):
   - line ~100: `within(selector).getByText('CUSTOM_LABEL_1')` → `within(selector).getByText('#2 CUSTOM_LABEL_1')`
   - line ~104: `within(selector).getByText('CUSTOM_LABEL_2')` → `within(selector).getByText('#3 CUSTOM_LABEL_2')`
   - line ~126: same → `'#3 CUSTOM_LABEL_2'`
   - line ~134: `within(selector).getByText('CUSTOM_LABEL_0')` → `within(selector).getByText('#1 CUSTOM_LABEL_0')`
   - line ~638: same → `'#3 CUSTOM_LABEL_2'`
2. Append two integration tests to the `CustomLabelsUI live preview stats` describe (or a new `describe('CustomLabelsUI product preview')`):

```tsx
  it('at feed tier renders the split editor with preview rows from the lookup endpoint', async () => {
    renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', (url) => {
      if (url.includes('/products/lookup')) return jsonResponse({
        matches: {
          a: { count: 1, sample: { product_id: 'a', status: 'active', excluded: false, title: 'Alpha', brand: 'Acme', availability: 'in_stock' } },
          b: { count: 1, sample: { product_id: 'b', status: 'active', excluded: false, title: 'Bravo', brand: 'Beta', availability: 'out_of_stock' } },
        },
      });
      return jsonResponseFor(url);
    });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    expect(await screen.findByText('Matched products')).toBeInTheDocument();
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(await screen.findByText('Bravo')).toBeInTheDocument();
  });

  it('at client tier the preview column is absent (no feed context)', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel')); // expand
    expect(
      await screen.findByRole('textbox', { name: 'Product IDs — Mid Funnel' }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('product-preview-viewport')).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm run test -- --run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
Expected: FAIL — slot labels still plain, preview props not wired.

- [ ] **Step 3: Implement**

1. `frontend/src/features/customLabels/SlotSelector.tsx` — change the SegmentedControl `data` mapping:

```tsx
          data={slots.map((slot, index) => ({
            value: slot,
            label: `#${index + 1} ${slot.toUpperCase()}`,
          }))}
```

2. `frontend/src/features/customLabels/CustomLabelsUI.tsx`:
   - Add state next to the other `useState` calls (before the early returns):

```tsx
  const [previewFields, setPreviewFields] = useState<Record<string, string[]>>({});
```

   - In the `idsPanel`'s `RuleCard` map, add three props (keep every existing prop unchanged):

```tsx
            feedSourceId={scope.feedSourceId}
            extraFields={previewFields[rule.id] ?? []}
            onExtraFieldsChange={(fields) =>
              setPreviewFields((prev) => ({ ...prev, [rule.id]: fields }))
            }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm run test -- --run src/features/customLabels/__tests__/CustomLabelsUI.test.tsx && npm run typecheck`
Expected: all PASS (existing suite + 2 new), typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/SlotSelector.tsx frontend/src/features/customLabels/CustomLabelsUI.tsx frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx
git commit -m "feat(frontend): slot priority labels and product preview wiring"
```

---

### Task 9: Frontend docs + full gates

**Files:**
- Modify: `frontend/docs/plugin-uis.md` (Labelizer section)
- Modify: `frontend/docs/architecture.md` (custom_labels bullet)

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: docs matching shipped behavior; all gates green.

- [ ] **Step 1: Update `frontend/docs/plugin-uis.md`**

In the "Custom component scope behavior (custom_labels / Labelizer)" section, after the "**Slot-selected view:**" bullet, add:

```
- **Synchronized product preview:** at feed tier each expanded rule card
  splits its value editor 35/65: the monospace value textarea (fixed
  10-row height, no soft-wrap) beside a windowed preview column whose row
  i mirrors parsed entry i. Scrolling either side drives the other
  (bidirectional scrollTop sync). Rows come from
  `POST /feed-sources/{id}/products/lookup` (300 ms debounced, TanStack
  Query cached per value-set): per value it shows the sample product's
  title (truncated + tooltip), brand, availability badge
  (in_stock/out_of_stock), a gray "N products" badge when a value matches
  several products, dimmed removed/excluded badges, and a red
  "ID not found in feed" / "No match in feed" badge for dead values. A
  per-card MultiSelect adds extra raw-data fields inline (options from
  the feed's field list minus title/brand/availability; selection is
  session-local and survives collapse). Lookups are status-agnostic and
  match by the rule's match field, mirroring run-time semantics. Slot
  selector items are numbered `#1..#5`, and rule card headers show a
  compact `#N` before the rule name (evaluation order).
```

- [ ] **Step 2: Update `frontend/docs/architecture.md`**

Extend the `custom_labels` bullet (the sentence ends with `i18n (`customLabels` namespace)`): insert before that final clause:

```
; expanded rule cards add a synchronized, windowed product preview column beside the value list (batch lookup via `POST /feed-sources/{id}/products/lookup`)
```

- [ ] **Step 3: Run all gates**

From `frontend/`: `npm run typecheck && npm run test -- --run && npm run build`
From `backend/` (TEST_DATABASE_URL exported): `uv run pytest -n auto` and `uv run pytest tests/test_plugin_contract.py -q`
Expected: all PASS. (Ruff/mypy remain blocked by pre-existing repo debt — record that in the report, do not attempt repo-wide fixes.)

- [ ] **Step 4: Commit**

```bash
git add frontend/docs/plugin-uis.md frontend/docs/architecture.md
git commit -m "docs(frontend): labelizer product preview and priority indicators"
```

---

## Self-Review Notes (resolved during planning)

- Spec coverage: §1 priority indicators → Tasks 7 (card `#N`) + 8 (slot `#N`); §2 endpoint → Task 1; §3 hook + `parseIdEntries` → Tasks 2-3; §4 layout/sync/windowing → Tasks 5-7; §5 row rendering → Task 6; §6 i18n/errors → Tasks 4-6; §7 testing → every task's test steps; docs → Tasks 1 + 9. The spec's "2–10 000" values minimum is a typo — amended to 1–10 000 in Task 1 (noted to the operator).
- Mantine v9 API verified via docs: `MultiSelect` (`searchable`, `clearable`), `Textarea` (`autosize` + `minRows`/`maxRows` for fixed height, `wrap="off"`), `ScrollArea` not used (plain synced `div` chosen for exact scrollTop control).
- Type consistency: `ProductLookupMatch`/`ProductLookupSample`/`ProductLookupResponse` (Task 2) are consumed verbatim by Tasks 6-7; `windowRange`/`ROW_HEIGHT`/`VIEWPORT_ROWS`/`availabilityColor`/`useSyncedScroll` (Task 5) by Tasks 6-7; `parseIdEntries` (Task 3) by Task 7; `RuleCard` new props (Task 7) consumed by Task 8's wiring.
