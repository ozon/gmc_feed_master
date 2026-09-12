# Z4: Attributanreicherung (Attribute Enrichment) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Core plugin `enrichment`: AI scan fills missing attributes into pending suggestions, users accept per field into pinned values, the pipeline applies pins by product id.

**Architecture:** New core plugin (manifest + Python + React component). Suggestions and pins live in `PluginData` (feed_source scope, JSONB). Scan/accept/discard/unpin are plugin routes reusing the generic `_get_payload`/`_put_payload` helpers (optimistic locking for free). No new tables.

**Tech Stack:** Plugin runtime (validate_config/prepare_run/process/register_routes), AiService.run_task, PluginData + OL helpers; React plugin UI (Mantine + TanStack Query).

**Spec:** `docs/superpowers/specs/2026-09-12-attributanreicherung-design.md`

## Global Constraints

- Same gates/i18n/logger/docs rules as the Z1 plan (see its Global Constraints).
- Run the plugin contract suite: `uv run pytest tests/test_plugin_contract.py` after every plugin change.
- Plugin routes carry `feed_source_id` in the body → MUST call `ensure_feed_source_access` first (established pattern from custom_labels/filter).
- Read-modify-writes on PluginData go through `app.routes.plugins._get_payload` / `_put_payload` (they manage transactions and `expected_version` → 409). Never open a `session.begin()` around a `_put_payload` call.
- Don't hold a DB session open across the AI `gather` (backend AGENTS rule).
- Pinned values win over feed values (documented precedence).

---

### Task 1: Plugin skeleton — manifest, config validation, process()

**Files:**
- Create: `plugins/core/enrichment/plugin.json`, `plugins/core/enrichment/plugin.py`
- Test: `backend/tests/test_enrichment_plugin.py` (new)

**Interfaces:**
- Produces: `EnrichmentPlugin` with `validate_config(config)`, `prepare_run(config, data, ctx) -> {"pinned": dict}`, `process(product, config, data, ctx, state=None)`; data shape `{"suggestions": {pid: {field: value}}, "pinned": {pid: {field: value}}}`.
- Consumes: plugin runtime contract (see `plugins/core/custom_labels/plugin.py`).

- [ ] **Step 1: Write failing tests** — `backend/tests/test_enrichment_plugin.py`:

```python
import pytest

from plugins.core.enrichment.plugin import EnrichmentPlugin, validate_config


def test_validate_config_requires_nonempty_target_fields():
    with pytest.raises(ValueError):
        validate_config({"targetFields": []})
    with pytest.raises(ValueError):
        validate_config({"targetFields": ["ok", ""]})
    validate_config({"targetFields": ["color", "material"]})
    validate_config({})  # defaults apply


async def test_process_applies_pins_by_product_id():
    state = {"pinned": {"p1": {"color": "blue"}}}
    out = EnrichmentPlugin().process(
        {"id": "p1", "title": "T", "color": "red"}, {}, {}, None, state
    )
    assert out["color"] == "blue"  # pinned wins


async def test_process_passthrough_without_pin():
    product = {"id": "p2", "title": "T"}
    out = EnrichmentPlugin().process(product, {}, {}, None, {"pinned": {"p1": {}}})
    assert out == product
    assert out is product
```

- [ ] **Step 2: Run** `uv run pytest tests/test_enrichment_plugin.py -v` — FAIL (import error).

- [ ] **Step 3: Implement.** `plugins/core/enrichment/plugin.json`:

```json
{
  "id": "enrichment",
  "name": "Enrichment",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "entry_point": "plugin:EnrichmentPlugin",
  "config_scope": ["global", "client", "feed_source"],
  "data_scope": ["feed_source"],
  "config_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Enrichment",
    "properties": {
      "isActive": {"type": "boolean", "title": "Active", "default": true},
      "targetFields": {
        "type": "array",
        "title": "Target fields",
        "items": {"type": "string"},
        "minItems": 1,
        "default": ["color", "material", "size", "gtin"]
      }
    },
    "required": ["targetFields"]
  },
  "data_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Enrichment data",
    "properties": {
      "suggestions": {
        "type": "object",
        "title": "Pending suggestions",
        "additionalProperties": {"type": "object", "additionalProperties": {"type": "string"}}
      },
      "pinned": {
        "type": "object",
        "title": "Accepted values",
        "additionalProperties": {"type": "object", "additionalProperties": {"type": "string"}}
      }
    }
  },
  "frontend": {
    "menu_item": "Enrichment",
    "icon": "letter-e",
    "component": "component.tsx"
  }
}
```

`plugins/core/enrichment/plugin.py`:

```python
from __future__ import annotations

from typing import Any

DEFAULT_TARGET_FIELDS = ["color", "material", "size", "gtin"]


def validate_config(config: Any) -> None:
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    fields = config.get("targetFields", DEFAULT_TARGET_FIELDS)
    if (
        not isinstance(fields, list)
        or not fields
        or not all(isinstance(f, str) and f for f in fields)
    ):
        raise ValueError("targetFields must be a non-empty list of non-empty strings")


class EnrichmentPlugin:
    """Pipeline module applying accepted AI enrichment values (pins) by product id."""

    def validate_config(self, config: Any) -> None:
        validate_config(config)

    def prepare_run(self, config: Any, data: Any, ctx: Any) -> dict[str, Any]:
        return {"pinned": (data or {}).get("pinned") or {}}

    def process(
        self,
        product: dict[str, Any],
        config: Any,
        data: Any,
        ctx: Any,
        state: Any = None,
    ) -> dict[str, Any]:
        pinned = (state or {}).get("pinned") or {}
        values = pinned.get(str(product.get("id", "")))
        if not values:
            return product
        result = dict(product)
        for field, value in values.items():
            result[field] = value  # pinned wins over feed values (spec: explicit user decision)
        return result
```

- [ ] **Step 4: Run** `uv run pytest tests/test_enrichment_plugin.py tests/test_plugin_contract.py -v` — pass.

- [ ] **Step 5: Commit** `git add plugins/core/enrichment backend/tests/test_enrichment_plugin.py && git commit -m "feat: enrichment plugin skeleton (manifest, config, pin application)"`

---

### Task 2: Scan route

**Files:**
- Modify: `plugins/core/enrichment/plugin.py` (add `register_routes`)
- Test: `backend/tests/test_enrichment_routes.py` (new)

**Interfaces:**
- Consumes: `app.routes.plugins._get_payload` / `_put_payload` (signatures: see `backend/app/routes/plugins.py:249` and `:321`); `AiService.run_task("attribute_enrichment", {title, description}, client_id, feed_source_id)`; `ensure_feed_source_access`.
- Produces: `POST /plugins/enrichment/scan {feed_source_id, limit}` → `{scanned, with_suggestions, failed}`; writes `suggestions[product_id]` into PluginData.

- [ ] **Step 1: Write failing tests** — `backend/tests/test_enrichment_routes.py`, mirroring the app/client fixture setup of `backend/tests/test_custom_labels_preview.py` plus a fake `ai_service` on `app.state` (scripted `run_task` returning `AiResult(value={"color": "blue"}, status="ok", ...)`). Tests:
  1. Seed a feed source + staging products where `color` missing in raw_data; POST scan → 200, plugin data `suggestions` contains the product with `{"color": "blue"}`; response counts right.
  2. Product whose missing fields are all pinned → skipped (`scanned` excludes it).
  3. AI fallback for a product → `failed: 1`, no suggestion stored.
  4. No `app.state.ai_service` → 503.
  5. Client user without scope on the feed source → 404 (ensure_feed_source_access).

- [ ] **Step 2: Run** — FAIL (route missing).

- [ ] **Step 3: Implement** — add to `EnrichmentPlugin`:

```python
    def register_routes(self, router: Any) -> None:
        import asyncio

        from fastapi import Depends, HTTPException, Request
        from pydantic import BaseModel, Field
        from sqlalchemy import or_, select

        from app.access import CurrentUser, ensure_feed_source_access, get_current_user
        from app.db.engine import get_db_session
        from app.models.feed_source import FeedSource
        from app.models.plugin import PluginConfig, PluginData
        from app.models.staging import StagingProduct
        from app.routes.plugins import _get_payload, _put_payload

        class ScanRequest(BaseModel):
            feed_source_id: int
            limit: int = Field(default=20, ge=1, le=50)

        async def scan(payload: ScanRequest, request: Request,
                       user: CurrentUser = Depends(get_current_user),
                       db_session: Any = Depends(get_db_session)) -> dict[str, Any]:
            service = getattr(request.app.state, "ai_service", None)
            if service is None:
                raise HTTPException(status_code=503, detail="ai service unavailable")
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            await ensure_feed_source_access(db_session, user, payload.feed_source_id)

            # -- read phase (own transaction via helpers/short block) ------------
            config, _version = await _get_payload(
                "enrichment", None, payload.feed_source_id,
                PluginConfig, "config", "config_scope", db_session, user,
            )
            target_fields = list((config or {}).get("targetFields") or DEFAULT_TARGET_FIELDS)
            data, version = await _get_payload(
                "enrichment", None, payload.feed_source_id,
                PluginData, "data", "data_scope", db_session, user,
            )
            async with db_session.begin():
                feed_source = await db_session.get(FeedSource, payload.feed_source_id)
                if feed_source is None:
                    raise HTTPException(status_code=404, detail="feed source not found")
                conditions = []
                for field_name in target_fields:
                    col = StagingProduct.raw_data[field_name].astext
                    conditions.append(col.is_(None))
                    conditions.append(col == "")
                rows = (await db_session.execute(
                    select(StagingProduct.product_id, StagingProduct.raw_data)
                    .where(
                        StagingProduct.feed_source_id == payload.feed_source_id,
                        StagingProduct.status == "active",
                        StagingProduct.excluded.is_(False),
                        or_(*conditions),
                    )
                    .order_by(StagingProduct.id)
                    .limit(payload.limit)
                )).all()

            # -- AI phase (no session held) ---------------------------------------
            candidates = []
            for product_id, raw in rows:
                raw_dict = dict(raw) if raw else {}
                pinned_values = ((data or {}).get("pinned") or {}).get(product_id) or {}
                missing = [f for f in target_fields if not str(raw_dict.get(f) or "")]
                if missing and all(f in pinned_values for f in missing):
                    continue
                candidates.append((product_id, raw_dict))

            results = await asyncio.gather(*[
                service.run_task(
                    "attribute_enrichment",
                    {"title": raw.get("title"), "description": raw.get("description")},
                    client_id=feed_source.client_id,
                    feed_source_id=payload.feed_source_id,
                )
                for _pid, raw in candidates
            ])

            suggestions = dict((data or {}).get("suggestions") or {})
            failed = 0
            with_suggestions = 0
            for (product_id, _raw), result in zip(candidates, results):
                if result.status == "fallback" or not isinstance(result.value, dict):
                    failed += 1
                    continue
                values = {k: str(v) for k, v in result.value.items() if v not in (None, "")}
                if values:
                    suggestions[product_id] = values
                    with_suggestions += 1

            # -- write phase (helper manages its own transaction) ------------------
            new_data = {"suggestions": suggestions, "pinned": (data or {}).get("pinned") or {}}
            outcome = await _put_payload(
                "enrichment", new_data, None, payload.feed_source_id,
                PluginData, "data", "data_scope", "data_schema",
                str(version) if version is not None else None,
                db_session, user,
            )
            from fastapi.responses import JSONResponse

            if isinstance(outcome, JSONResponse):
                return outcome
            return {
                "scanned": len(candidates),
                "with_suggestions": with_suggestions,
                "failed": failed,
            }

        scan.__annotations__.update({
            "payload": ScanRequest, "user": CurrentUser, "return": dict[str, Any],
        })
        router.post("/scan", response_model=None)(scan)
```

Note: `_get_payload` reads config at the feed_source tier only (`ponytail:` global/client config tiers resolve later via the pipeline's config resolver; the scan route uses the feed tier or defaults).

- [ ] **Step 4: Run** `uv run pytest tests/test_enrichment_routes.py tests/test_plugin_contract.py -v` — pass.

- [ ] **Step 5: Commit** `git add plugins/core/enrichment backend/tests/test_enrichment_routes.py && git commit -m "feat: enrichment scan route (missing-field query, batched ai, ol write)"`

---

### Task 3: Accept / discard / unpin routes

**Files:**
- Modify: `plugins/core/enrichment/plugin.py` (extend `register_routes`)
- Test: `backend/tests/test_enrichment_routes.py` (extend)

**Interfaces:**
- Produces: `POST /plugins/enrichment/{accept,discard,unpin}` with `{feed_source_id, expected_version, items: [{product_id, fields: [str]}]}` → `{"status": "ok"}` or 409/422 from the shared helpers.

- [ ] **Step 1: Write failing tests**:
  1. accept moves selected fields suggestions→pinned and clears them from suggestions (empty product keys dropped)
  2. discard deletes selected suggestion fields
  3. unpin deletes selected pinned fields
  4. stale `expected_version` → 409
  5. accept for unknown product/field → no crash, no change

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement** — inside `register_routes`, after `scan`:

```python
        class ItemsRequest(BaseModel):
            feed_source_id: int
            expected_version: str | None = None
            items: list[dict[str, Any]] = Field(default_factory=list)

        def _apply_items(data: dict[str, Any], items: list[dict[str, Any]], mode: str) -> None:
            for item in items:
                pid = str(item.get("product_id", ""))
                fields = set(item.get("fields") or [])
                if not pid or not fields:
                    continue
                if mode in ("accept", "discard"):
                    sug = dict(data["suggestions"].get(pid) or {})
                    if mode == "accept":
                        pin = dict(data["pinned"].get(pid) or {})
                        for f in fields:
                            if f in sug:
                                pin[f] = sug.pop(f)
                        if pin:
                            data["pinned"][pid] = pin
                    else:
                        for f in fields:
                            sug.pop(f, None)
                    if sug:
                        data["suggestions"][pid] = sug
                    else:
                        data["suggestions"].pop(pid, None)
                else:  # unpin
                    pin = dict(data["pinned"].get(pid) or {})
                    for f in fields:
                        pin.pop(f, None)
                    if pin:
                        data["pinned"][pid] = pin
                    else:
                        data["pinned"].pop(pid, None)

        async def _mutate(payload: ItemsRequest, mode: str,
                          user: CurrentUser, db_session: Any) -> dict[str, Any]:
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            await ensure_feed_source_access(db_session, user, payload.feed_source_id)
            data, version = await _get_payload(
                "enrichment", None, payload.feed_source_id,
                PluginData, "data", "data_scope", db_session, user,
            )
            new_data = {
                "suggestions": dict((data or {}).get("suggestions") or {}),
                "pinned": dict((data or {}).get("pinned") or {}),
            }
            _apply_items(new_data, payload.items, mode)
            outcome = await _put_payload(
                "enrichment", new_data, None, payload.feed_source_id,
                PluginData, "data", "data_scope", "data_schema",
                payload.expected_version, db_session, user,
            )
            if isinstance(outcome, JSONResponse):
                return outcome
            return {"status": "ok"}

        for mode in ("accept", "discard", "unpin"):
            async def endpoint(payload: ItemsRequest,
                               user: CurrentUser = Depends(get_current_user),
                               db_session: Any = Depends(get_db_session),
                               _mode: str = mode):
                return await _mutate(payload, _mode, user, db_session)

            endpoint.__annotations__.update({
                "payload": ItemsRequest, "user": CurrentUser, "return": dict[str, Any],
            })
            router.post(f"/{mode}", response_model=None)(endpoint)
```

(Import `JSONResponse` once at the top of `register_routes` together with the other route imports.)

- [ ] **Step 4: Run** `uv run pytest tests/test_enrichment_routes.py tests/test_plugin_contract.py -v` — pass.

- [ ] **Step 5: Commit** `git add plugins/core/enrichment backend/tests/test_enrichment_routes.py && git commit -m "feat: enrichment accept/discard/unpin routes with ol"`

---

### Task 4: Frontend — EnrichmentUI component

**Files:**
- Create: `plugins/core/enrichment/frontend/component.tsx`
- Modify: `frontend/src/i18n/i18next.d.ts` (register `enrichment` namespace), locale files `frontend/public/locales/{en,de}/enrichment.json` (new)
- Test: `backend/../frontend/src/features/plugin/` — follow the existing plugin-component test location; create `frontend/src/features/enrichment/EnrichmentUI.test.tsx` if the build-time discovery makes testing via PluginPage awkward (check how `CategoryUI` is tested and mirror it)

**Interfaces:**
- Consumes: plugin component prop contract — READ `plugins/core/category/frontend/component.tsx` FIRST and mirror its props exactly (plugin id + scope); `apiGetWithHeaders`/`apiPost` from `frontend/src/api/client.ts`; `queryKeys.pluginData`, `buildScopeQuery` (export from `frontend/src/api/hooks.ts` if not exported — it is module-private, so either request export or inline the 6-line helper in the component; inline it).
- Produces: `EnrichmentUI` — scan button + limit, suggestion checkboxes per product, accept selected / accept all / discard per field, pinned list with unpin.

- [ ] **Step 1: Study the contract** — read `plugins/core/category/frontend/component.tsx` and its registration in the plugin-page discovery (`frontend/src/features/plugin/PluginPage.tsx` + `frontend/docs/plugin-uis.md`). Note the exact props (likely `{ pluginId, scope }`-shaped) and the i18n namespace pattern.

- [ ] **Step 2: Write failing test** — mirror the CategoryUI test setup: render `EnrichmentUI` with stubbed `GET /plugins/enrichment/data` (returning `{suggestions: {p1: {color: "blue"}}, pinned: {p2: {size: "42"}}}` + version header) and stubbed POST routes; assert:
  - suggestion row renders `color: blue` with a checkbox
  - checking it and clicking accept posts `{items: [{product_id: "p1", fields: ["color"]}], expected_version: ...}` to `/plugins/enrichment/accept?feed_source_id=...`
  - pinned row shows `size: 42` with an unpin action
  - i18n parity en/de

- [ ] **Step 3: Implement** `component.tsx`:

```tsx
import { useState } from 'react';
// Mantine imports (Button, Checkbox, Group, NumberInput, Paper, Select, Stack, Text, Title)
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { apiGetWithHeaders, apiPost } from '../../../frontend/src/api/client';
import { queryKeys } from '../../../frontend/src/api/queryKeys';
```

(Adjust the import paths to the category component's actual relative paths — mirror `plugins/core/category/frontend/component.tsx`.)

Component body:
- local data hook (keeps the version for `expected_version`):

```tsx
function useEnrichmentData(pluginId: string, feedSourceId: number | undefined) {
  return useQuery({
    queryKey: queryKeys.pluginData(pluginId, { feedSourceId }),
    enabled: feedSourceId !== undefined,
    queryFn: async () => {
      const { data, headers } = await apiGetWithHeaders<Record<string, unknown>>(
        `/plugins/${pluginId}/data?feed_source_id=${feedSourceId}`);
      const raw = headers.get('X-Plugin-Data-Version');
      return { payload: data, version: raw && raw !== '' ? Number.parseInt(raw, 10) : null };
    },
  });
}
```

- scan mutation: `apiPost(`/plugins/${pluginId}/scan?feed_source_id=${feedSourceId}`, { feed_source_id: feedSourceId, limit })`, on success invalidate the data key + toast with `scanned/with_suggestions/failed`
- selection state: `const [selected, setSelected] = useState<Record<string, string[]>>({})` (product_id → fields)
- accept: POST `/accept` with `{feed_source_id, expected_version: version === null ? 'null' : String(version), items: Object.entries(selected).map(([product_id, fields]) => ({ product_id, fields }))}`; "accept all" sends every suggestion field; discard/unpin analogous per-field actions
- render: scan controls, suggestions grouped by product (Checkbox per field, label `{field}: {value}`), pinned list (Text + unpin ActionIcon)
- i18n: create `enrichment.json` for en+de with keys `title, scan, scanLimit, suggestions, pinned, acceptSelected, acceptAll, discard, unpin, empty`; register the namespace in `i18next.d.ts` exactly like `category`

- [ ] **Step 4: Run** `npx vitest run` (new test + full suite) and `npm run typecheck` — pass. Also `npm run build` (build-time plugin discovery must pick the component up).

- [ ] **Step 5: Commit** `git add plugins/core/enrichment/frontend frontend/src frontend/public/locales && git commit -m "feat: enrichment plugin ui (scan, review, accept, unpin)"`

---

### Task 5: Docs + full gates

**Files:**
- Modify: `backend/docs/plugins.md` (new core plugin + its 4 routes), `backend/docs/api.md` (plugin routes under the reserved-routes section), `docs/decisions.md` (Z4 entry: plugin architecture, pinned precedence, synchronous scan ceiling), `frontend/docs/plugin-uis.md` (new component).

- [ ] **Step 1: Docs updates** (same commit rule).

- [ ] **Step 2: Full gates** — backend ruff/mypy/pytest incl. `tests/test_plugin_contract.py`; frontend typecheck/vitest/build. `uv run alembic check` (no migration expected).

- [ ] **Step 3: Commit** `git add -A && git commit -m "docs: z4 attribute enrichment cycle notes"`
