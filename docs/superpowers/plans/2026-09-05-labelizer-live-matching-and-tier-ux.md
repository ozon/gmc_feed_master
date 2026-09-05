# Labelizer: Live Matching, Slot-Grouped Bulk Tab, and Tier UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Live rule matching against staged products, slot-grouped bulk tab with info boxes, rule duplicate/delete, override-at-client-level, and clickable tier navigation.

**Architecture:** Backend-first: a plugin-local `POST /plugins/custom_labels/preview` route (filter-plugin precedent, `register_routes`) evaluates the UI's current DRAFT rules+values against staged mapped products with the plugin's own engine. The frontend debounces draft changes (filter's `FilterUI` tick pattern), renders a per-slot grouped bulk tab with live info boxes, adds rule actions and tier navigation. No REST API changes outside the plugin-local route; no schema/migration changes.

**Tech Stack:** FastAPI/SQLAlchemy (backend), React 19 + Mantine 9 + TanStack Query + i18next + vitest (frontend), pytest.

**Spec:** `docs/superpowers/specs/2026-09-05-labelizer-live-matching-and-tier-ux-design.md`

## Global Constraints

- Preview route is plugin-local (`register_routes`, non-reserved subpath `/preview`) — mirrors `plugins/core/filter/plugin.py:127-176` exactly (auth, 404/503, 422 `{"errors": [...]}`).
- Evaluation must reuse the plugin's own primitives (`matches`, `render_template`, `_build_state`-shaped prep) — NO re-implementation of engine semantics.
- Live preview is **feed page only** (`feedSourceId` known); client/global pages show a dimmed hint, no request.
- `matched > 0 && labeled == 0` = "never applied" (shadowed or empty render) — derived client-side; fallback wins credit no rule's `labeled`.
- Rule actions (Duplicate/Delete/Override) apply to editable-origin rules only; Delete confirms via `ConfirmModal`; global-origin delete confirm mentions inheritance blast radius.
- Override = same-id client-origin copy (union-by-id ⇒ true runtime override); local state never holds duplicate ids.
- All user-facing strings in `frontend/public/locales/en/*.json` AND `de/*.json`.
- Backend commands (from `backend/`): `uv run pytest -n auto` with `export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres`; lint via `uvx ruff` / `uvx mypy` (NOT in venv; zero NEW findings in touched files).
- Frontend commands (from `frontend/`): `npm run test`, `npm run typecheck`, `npm run build`. Known AppShell/ProductsPage flakes are load-induced — re-run failed files solo.
- Plugin test preamble: importlib with a UNIQUE module name (house pattern from `backend/tests/test_filter_preview.py:23-30`); never bare `sys.path` + `from plugin import`.
- Preview hook uses the FilterUI live-preview precedent (debounced tick + `apiPost` + local state, `FilterUI.tsx:89-119`) — the documented exception to "server state in TanStack Query" for ephemeral previews.
- Docs updated in the same commit as behavior changes (repo rule).

---

### Task 1: Backend — `evaluate_rules` + plugin-local `POST /preview` route

**Files:**
- Modify: `plugins/core/custom_labels/plugin.py`
- Test: Create `backend/tests/test_custom_labels_preview.py`

**Interfaces:**
- Produces (module-level, pure): `evaluate_rules(rules, slot_ids, rows, sample_size=5) -> dict` where
  `rows: list[tuple[str, dict[str, Any]]]` are `(product_id, mapped product)` pairs. Return shape:
  `{"total": int, "rules": {id: {"matched": int, "labeled": int, "sample": [str]}}, "slots": {slot: {"labeled": int, "coverage": float, "rules": [str]}}}`.
- Produces (method): `CustomLabelsPlugin.register_routes(self, router)` mounting `POST /preview` (served at `POST /plugins/custom_labels/preview` — `backend/app/plugins/discovery.py:141` mounts plugin routers at `/plugins/{manifest.id}`).
- Request model: `{feed_source_id: int, rules: list, slotIds: dict[str, str], sample_size: int = 5 (ge=1, le=50)}`.
- Consumed by Task 4's frontend hook: `POST /plugins/custom_labels/preview`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_custom_labels_preview.py` (mirrors `test_filter_preview.py` scaffolding — app factory, login, staged-row seeding):

```python
"""Custom Labels preview endpoint tests: auth, 404, 422, live match counts."""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.staging import StagingProduct
from app.models.user import User
from app.persistence.users import seed_initial_user

_spec = importlib.util.spec_from_file_location(
    "custom_labels_plugin_preview",
    Path(__file__).resolve().parents[2] / "plugins/core/custom_labels/plugin.py",
)
assert _spec is not None and _spec.loader is not None
_labels_module = importlib.util.module_from_spec(_spec)
sys.modules["custom_labels_plugin_preview"] = _labels_module
_spec.loader.exec_module(_labels_module)

CustomLabelsPlugin = _labels_module.CustomLabelsPlugin
evaluate_rules = _labels_module.evaluate_rules


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
            await session.execute(delete(StagingProduct))
            await session.execute(delete(IngestionRun))
            await session.execute(delete(FeedSource))
            await session.execute(delete(Client))
            await session.execute(delete(Session))
            await session.execute(delete(User))
        await seed_initial_user(session, "operator", "pw")
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        initial_username="operator",
        initial_password="pw",
        database_url=url,
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _setup_feed(factory, client, products):
    """products: list of (product_id, raw_data, status, excluded) tuples."""
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (
        await client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": "DE", "source_format": "wide_tsv"},
        )
    ).json()
    async with factory() as session, session.begin():
        run = IngestionRun(feed_source_id=feed["id"], status="success",
                           started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()
        for pid, raw, status, excluded in products:
            session.add(
                StagingProduct(
                    feed_source_id=feed["id"], ingestion_run_id=run.id,
                    product_id=pid, content_hash="x", config_hash="x",
                    status=status, excluded=excluded, raw_data=raw,
                )
            )
    return feed


def _rule(rule_id, slot, **over):
    rule = {
        "id": rule_id, "name": rule_id, "isActive": True, "targetSlot": slot,
        "matchField": "id", "valueTemplate": "{brand} - " + rule_id,
        "fallbackTemplate": "",
    }
    rule.update(over)
    return rule


ROWS = [
    ("a1", {"id": "a1", "brand": "Acme"}, "active", False),
    ("a2", {"id": "a2", "brand": "Beta"}, "active", False),
    ("a3", {"id": "a3", "brand": "Acme"}, "removed", False),   # filtered: status
    ("a4", {"id": "a4", "brand": "Acme"}, "active", True),    # filtered: excluded
    ("nobrand", {"id": "nobrand", "brand": ""}, "active", False),
]


class TestPreviewRoute:
    async def test_mounted_route_returns_counts(self, app_factory):
        client = await logged_in_client(app_factory)
        app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            _rule("r1", "custom_label_0", matchField="brand"),
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {"r1": "Acme"},
        })
        assert resp.status_code == 200
        body = resp.json()
        # active, non-excluded rows only: a1, a2, nobrand
        assert body["total"] == 3
        assert body["rules"]["r1"] == {"matched": 1, "labeled": 1, "sample": ["a1"]}
        assert body["slots"]["custom_label_0"] == {
            "labeled": 1, "coverage": 33.3, "rules": ["r1"],
        }

    async def test_first_match_wins_and_token_skip(self, app_factory):
        client = await logged_in_client(app_factory)
        app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            # first rule matches a1 but its brand token renders; second matches too
            _rule("r1", "custom_label_1", matchField="brand"),
            _rule("r2", "custom_label_1", matchField="id"),
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {"r1": "Acme", "r2": "a2"},
        })
        body = resp.json()
        # r1 matches a1 (Acme) and wins it; r2 matches a2 and wins it.
        assert body["rules"]["r1"]["matched"] == 1
        assert body["rules"]["r1"]["labeled"] == 1
        assert body["rules"]["r2"]["matched"] == 1
        assert body["rules"]["r2"]["labeled"] == 1
        assert body["slots"]["custom_label_1"]["labeled"] == 2

    async def test_token_skip_shadowed_rule_is_matched_not_labeled(self, app_factory):
        client = await logged_in_client(app_factory)
        app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            # nobrand has empty brand -> token skips on BOTH rules
            _rule("r1", "custom_label_2", matchField="brand"),
            _rule("r2", "custom_label_2", matchField="brand",
                  valueTemplate="{brand} - r2"),
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {"r1": "", "r2": "nobrand"},
        })
        body = resp.json()
        # r1 matches nothing (empty value list); r2 matches nobrand but token skips.
        assert body["rules"]["r2"]["matched"] == 1
        assert body["rules"]["r2"]["labeled"] == 0
        assert body["slots"]["custom_label_2"]["labeled"] == 0

    async def test_match_all_counts_every_product(self, app_factory):
        client = await logged_in_client(app_factory)
        app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [_rule("all1", "custom_label_3", matchMode="all")]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {},
        })
        body = resp.json()
        assert body["total"] == 3
        assert body["rules"]["all1"]["matched"] == 3
        assert body["rules"]["all1"]["labeled"] == 2  # nobrand token-skips

    async def test_fallback_credits_slot_not_rule(self, app_factory):
        client = await logged_in_client(app_factory)
        app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [
            _rule("r1", "custom_label_4", matchField="brand",
                  valueTemplate="{brand} - r1", fallbackTemplate="NOBRAND"),
        ]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"],
            "rules": rules,
            "slotIds": {"r1": "nobrand"},
        })
        body = resp.json()
        # nobrand matches r1; template token-skips; fallback renders -> slot labeled
        assert body["rules"]["r1"]["labeled"] == 0
        assert body["slots"]["custom_label_4"]["labeled"] == 1

    async def test_inactive_rules_are_excluded(self, app_factory):
        client = await logged_in_client(app_factory)
        app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [_rule("off", "custom_label_0", isActive=False)]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"], "rules": rules, "slotIds": {},
        })
        body = resp.json()
        assert body["rules"] == {}
        assert body["slots"] == {}

    async def test_sample_cap(self, app_factory):
        client = await logged_in_client(app_factory)
        app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [_rule("all1", "custom_label_0", matchMode="all")]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"], "rules": rules,
            "slotIds": {}, "sample_size": 2,
        })
        assert resp.json()["rules"]["all1"]["sample"] == ["a1", "a2"]

    async def test_empty_feed_returns_zero_total(self, app_factory):
        client = await logged_in_client(app_factory)
        app, factory = app_factory
        feed = await _setup_feed(factory, client, [])
        rules = [_rule("r1", "custom_label_0", matchMode="all")]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"], "rules": rules, "slotIds": {},
        })
        body = resp.json()
        assert body["total"] == 0
        assert body["slots"]["custom_label_0"]["coverage"] == 0

    async def test_unknown_feed_404(self, app_factory):
        client = await logged_in_client(app_factory)
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": 99999, "rules": [], "slotIds": {},
        })
        assert resp.status_code == 404

    async def test_invalid_draft_422(self, app_factory, monkeypatch):
        monkeypatch.setattr("registry.loader.load_registry", lambda: _registry())
        client = await logged_in_client(app_factory)
        app, factory = app_factory
        feed = await _setup_feed(factory, client, ROWS)
        rules = [_rule("bad", "custom_label_9")]
        resp = await client.post("/plugins/custom_labels/preview", json={
            "feed_source_id": feed["id"], "rules": rules, "slotIds": {},
        })
        assert resp.status_code == 422
        assert any("targetSlot" in e for e in resp.json()["errors"])

    async def test_requires_auth(self, app_factory):
        app, _ = app_factory
        client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
        resp = await client.post("/plugins/custom_labels/preview", json={})
        assert resp.status_code in (401, 422)  # not logged in


def _registry():
    from registry.loader import RegistryDocument  # noqa: F401 — full helper below
    raise NotImplementedError
```

**Replace the `_registry` stub at the bottom with the real helper before running** — copy the `_registry()` helper style from `backend/tests/test_custom_labels_plugin.py:126-142` (`RegistryDocument` with `id`, `brand`, `item_group_id`, `price` attributes, `attr()` inner factory) verbatim, so `test_invalid_draft_422` validates against a controlled registry.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_custom_labels_preview.py -q` (from `backend/`, with `TEST_DATABASE_URL` exported)
Expected: FAIL — `AttributeError: module has no attribute 'evaluate_rules'` / route 404s.

- [ ] **Step 3: Implement**

In `plugins/core/custom_labels/plugin.py`, append after the `CustomLabelsPlugin.process` method — but BEFORE the class, insert the pure helper (place it right after `_build_state`, in the pure-primitives region):

```python
def evaluate_rules(
    rules: Any,
    slot_ids: Any,
    rows: list[tuple[str, dict[str, Any]]],
    sample_size: int = 5,
) -> dict[str, Any]:
    """Evaluate draft slot rules against staged (product_id, mapped product) rows.

    Mirrors process(): first-match-wins per slot with token skip and first-rule
    fallback. Per rule: matched counts every matching product (no short-circuit),
    labeled counts products whose final slot value came from that rule's
    template (fallback wins credit no rule), sample lists up to sample_size ids.
    """
    state = _build_state(
        {"slotRules": rules} if rules else {}, {"slotIds": slot_ids or {}}
    )
    prepared = state["rules"]
    per_rule: dict[str, dict[str, Any]] = {
        rule["id"]: {"matched": 0, "labeled": 0, "sample": []}
        for rule in prepared
    }
    by_slot: dict[str, list[dict[str, Any]]] = {}
    for rule in prepared:
        by_slot.setdefault(rule["targetSlot"], []).append(rule)
    total = len(rows)
    slots: dict[str, dict[str, Any]] = {
        slot: {"labeled": 0, "coverage": 0.0, "rules": [r["id"] for r in slot_rules]}
        for slot, slot_rules in by_slot.items()
    }

    for product_id, product in rows:
        product = product or {}
        for slot, slot_rules in by_slot.items():
            winner: str | None = None
            any_matched = False
            for rule in slot_rules:
                if not rule["matchAll"] and not matches(
                    product, rule["matchField"], rule["ids"]
                ):
                    continue
                any_matched = True
                stats = per_rule[rule["id"]]
                stats["matched"] += 1
                if len(stats["sample"]) < sample_size:
                    stats["sample"].append(product_id)
                if winner is None:
                    value = render_template(rule["template"], product)
                    if value is not None:
                        winner = rule["id"]
                        stats["labeled"] += 1
            if winner is None and any_matched and slot_rules[0]["fallback"]:
                fallback_value = render_template(slot_rules[0]["fallback"], product)
                if fallback_value:
                    winner = slot
            if winner is not None:
                slots[slot]["labeled"] += 1

    if total:
        for entry in slots.values():
            entry["coverage"] = round(entry["labeled"] / total * 100, 1)
    return {"total": total, "rules": per_rule, "slots": slots}
```

Then add the route-registration method to `CustomLabelsPlugin` (after `process`), mirroring filter:

```python
    def register_routes(self, router: Any) -> None:
        """Mount POST /preview — live match stats against staged products."""
        from fastapi import Depends, HTTPException
        from fastapi.responses import JSONResponse
        from pydantic import BaseModel, Field
        from sqlalchemy import select

        from app.auth import require_user
        from app.db.engine import get_db_session
        from app.models.feed_source import FeedSource
        from app.models.staging import StagingProduct

        class PreviewRequest(BaseModel):
            feed_source_id: int
            rules: list[dict[str, Any]] = Field(default_factory=list)
            slotIds: dict[str, str] = Field(default_factory=dict)
            sample_size: int = Field(default=5, ge=1, le=50)

        async def preview(
            payload: PreviewRequest,
            _user: str = Depends(require_user),
            db_session: Any = Depends(get_db_session),
        ) -> dict[str, Any] | JSONResponse:
            try:
                validate_config({"slotRules": payload.rules} if payload.rules else {})
            except ValueError as exc:
                return JSONResponse(status_code=422, content={"errors": [str(exc)]})
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            async with db_session.begin():
                if await db_session.get(FeedSource, payload.feed_source_id) is None:
                    raise HTTPException(status_code=404, detail="feed source not found")
                rows = (await db_session.execute(
                    select(StagingProduct.product_id, StagingProduct.raw_data).where(
                        StagingProduct.feed_source_id == payload.feed_source_id,
                        StagingProduct.status == "active",
                        StagingProduct.excluded.is_(False),
                    )
                )).all()
            return evaluate_rules(
                payload.rules,
                payload.slotIds,
                [(row.product_id, dict(row.raw_data) if row.raw_data else {}) for row in rows],
                payload.sample_size,
            )

        preview.__annotations__["payload"] = PreviewRequest
        router.post("/preview")(preview)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_custom_labels_preview.py tests/test_custom_labels_plugin.py tests/test_plugin_contract.py -q`
Expected: PASS (all new + existing plugin tests; contract test validates the manifest is untouched).

- [ ] **Step 5: Lint + full suite**

Run: `uvx ruff check ../plugins/core/custom_labels/plugin.py tests/test_custom_labels_preview.py && uvx mypy ../plugins/core/custom_labels/plugin.py` (zero NEW findings vs environmental baseline), then `uv run pytest -n auto -q` full suite.
Expected: all green (baseline was 871).

- [ ] **Step 6: Commit**

```bash
git add ../plugins/core/custom_labels/plugin.py tests/test_custom_labels_preview.py
git commit -m "feat(custom_labels): plugin-local preview route with live match counts"
```

---

### Task 2: Frontend — `usePreview` hook (debounced, stale-guarded)

**Files:**
- Create: `frontend/src/features/customLabels/usePreview.ts`
- Test: Create: `frontend/src/features/customLabels/usePreview.test.tsx`

**Interfaces:**
- Consumes: `POST /plugins/custom_labels/preview` (Task 1); `ApiError`/`apiPost` from `frontend/src/api/client.ts`; `SlotRule` from `./scopeMerge`.
- Produces (consumed by Task 4):
  - `type PreviewResult = { total: number; rules: Record<string, { matched: number; labeled: number; sample: string[] }>; slots: Record<string, { labeled: number; coverage: number; rules: string[] }> }`
  - `useLabelizerPreview({ enabled, feedSourceId, rules, slotIds }): { result: PreviewResult | null; isPending: boolean; errors: string[] | null; unavailable: boolean }`
  - `rules` accepts `ScopedSlotRule[]` too (assignable; the extra `origin` key is ignored by the backend pydantic model and `validate_config`).
- Pattern: mirrors the FilterUI live-preview precedent (`frontend/src/features/filter/FilterUI.tsx:89-119`: debounced tick + `apiPost` + local state) — the house exception to TanStack-only server state for ephemeral previews.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/customLabels/usePreview.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import type { SlotRule } from './scopeMerge';
import { useLabelizerPreview, type PreviewResult } from './usePreview';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const RULES: SlotRule[] = [
  { id: 'r1', name: 'R1', isActive: true, targetSlot: 'custom_label_0',
    matchField: 'id', valueTemplate: 'x', fallbackTemplate: '' },
];
const RESULT: PreviewResult = {
  total: 10,
  rules: { r1: { matched: 5, labeled: 4, sample: ['a1'] } },
  slots: { custom_label_0: { labeled: 4, coverage: 40, rules: ['r1'] } },
};

function Probe(props: { rules: SlotRule[]; slotIds?: Record<string, string>; enabled?: boolean }) {
  const state = useLabelizerPreview({
    enabled: props.enabled ?? true,
    feedSourceId: 1,
    rules: props.rules,
    slotIds: props.slotIds ?? {},
  });
  return (
    <div>
      <span data-testid="pending">{String(state.isPending)}</span>
      <span data-testid="errors">{state.errors?.join('|') ?? ''}</span>
      <span data-testid="unavailable">{String(state.unavailable)}</span>
      <span data-testid="total">{state.result?.total ?? ''}</span>
    </div>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('useLabelizerPreview', () => {
  it('fires one debounced preview request and renders the result', async () => {
    let calls = 0;
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        calls += 1;
        return jsonResponse(RESULT);
      }
      return jsonResponse({});
    });
    render(<Probe rules={RULES} slotIds={{ r1: 'a,b' }} />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('10'),
      { timeout: 2500 },
    )).toBeTruthy();
    expect(calls).toBe(1);
  });

  it('sends no request when disabled', async () => {
    const calls: string[] = [];
    stubFetch((url) => {
      calls.push(url);
      return jsonResponse({});
    });
    render(<Probe rules={RULES} enabled={false} />);
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(calls.some((u) => u.includes('/preview'))).toBe(false);
    expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('');
  });

  it('surfaces 422 validation errors', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        return jsonResponse({ errors: ['slotRules[0]: targetSlot must be one of ...'] }, 422);
      }
      return jsonResponse({});
    });
    render(<Probe rules={RULES} />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="errors"]')?.textContent)
        .toContain('targetSlot'),
      { timeout: 2500 },
    )).toBeTruthy();
  });

  it('discards stale responses (newest draft wins)', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        return new Promise<Response>((resolve) => {
          const body = { total: 1, rules: {}, slots: {} };
          // every response resolves slowly; the hook's sequence guard must
          // still end up consistent because each tick bumps seq
          setTimeout(() => resolve(jsonResponse(body)), 50);
        });
      }
      return jsonResponse({});
    });
    const { rerender } = render(<Probe rules={RULES} />);
    await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('1'),
      { timeout: 2500 },
    );
    // draft changes -> new debounced call; stale (slow) first response must be dropped
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        return jsonResponse({ total: 2, rules: {}, slots: {} });
      }
      return jsonResponse({});
    });
    rerender(<Probe rules={[{ ...RULES[0], valueTemplate: 'y' }]} />);
    expect(await waitFor(
      () => expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('2'),
      { timeout: 2500 },
    )).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(document.querySelector('[data-testid="total"]')?.textContent).toBe('2');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- usePreview` (from `frontend/`)
Expected: FAIL — module `./usePreview` does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/features/customLabels/usePreview.ts`:

```ts
import { useEffect, useRef, useState } from 'react';
import { ApiError, apiPost } from '../../api/client';
import type { SlotRule } from './scopeMerge';

export type PreviewRuleStats = { matched: number; labeled: number; sample: string[] };

export type PreviewResult = {
  total: number;
  rules: Record<string, PreviewRuleStats>;
  slots: Record<string, { labeled: number; coverage: number; rules: string[] }>;
};

export type PreviewState = {
  result: PreviewResult | null;
  isPending: boolean;
  errors: string[] | null;
  unavailable: boolean;
};

const DEBOUNCE_MS = 500;

/**
 * Live preview of draft rules+values against the feed's staged products.
 * Mirrors the FilterUI live-preview pattern: debounced tick, apiPost, local
 * state; only the newest response is applied (sequence guard).
 */
export function useLabelizerPreview(input: {
  enabled: boolean;
  feedSourceId: number | undefined;
  rules: SlotRule[];
  slotIds: Record<string, string>;
}): PreviewState {
  const { enabled, feedSourceId, rules, slotIds } = input;
  const [result, setResult] = useState<PreviewResult | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [errors, setErrors] = useState<string[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);

  const draftKey = JSON.stringify({ rules, slotIds });

  useEffect(() => {
    if (!enabled) {
      setResult(null);
      setErrors(null);
      setUnavailable(false);
      setIsPending(false);
      return;
    }
    const timer = setTimeout(() => setTick((n) => n + 1), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [enabled, draftKey]);

  useEffect(() => {
    if (!enabled || tick === 0) return;
    const mySeq = ++seq.current;
    setIsPending(true);
    void apiPost<PreviewResult>('/plugins/custom_labels/preview', {
      feed_source_id: feedSourceId,
      rules,
      slotIds,
      sample_size: 5,
    })
      .then((res) => {
        if (mySeq !== seq.current) return;
        setResult(res);
        setErrors(null);
        setUnavailable(false);
        setIsPending(false);
      })
      .catch((err: unknown) => {
        if (mySeq !== seq.current) return;
        if (err instanceof ApiError && err.status === 422) {
          setErrors(err.errors ?? [err.detail ?? 'Invalid rules']);
          setUnavailable(false);
        } else {
          setUnavailable(true);
        }
        setIsPending(false);
      });
  }, [tick]);
```

*(Note: the fetch effect intentionally keys on `tick` only, mirroring FilterUI's
`previewTick` pattern — `rules`/`slotIds` are captured from the render that
produced the tick. House pattern; the repo has no eslint exhaustive-deps gate.)*

Add the closing brace of the hook after the second `useEffect`:

```ts
  return { result, isPending, errors, unavailable };
}
```

- [ ] **Step 4: Run tests + typecheck to verify they pass**

Run: `npm run test -- usePreview && npm run typecheck`
Expected: PASS (4 new tests).

- [ ] **Step 5: Commit**

```bash
git add src/features/customLabels/usePreview.ts src/features/customLabels/usePreview.test.tsx
git commit -m "feat(frontend): labelizer live preview hook"
```

---

### Task 3: Frontend — bulk tab grouped by target slot (static info boxes)

**Files:**
- Create: `frontend/src/features/customLabels/SlotGroup.tsx`
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx`
- Modify: `frontend/public/locales/en/customLabels.json`, `de/customLabels.json`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Consumes: `parseIdList`, `renderPreview` from `./ids`; `SlotRule`, `ScopedSlotRule`, `Tier` from `./scopeMerge`; `ScopeBadge` NOT needed here (inherited badge uses plain Badge + `inheritedFrom` key, as today).
- Produces: `SlotGroup` with props (Task 3 version):
  ```ts
  export type SlotGroupProps = {
    slot: string;
    rules: ScopedSlotRule[];      // active rules targeting this slot, winning order
    values: Record<string, string>;
    inheritedFor: (id: string) => boolean;
    isRuleEditable: (rule: ScopedSlotRule) => boolean;
    editableTier: Tier | null;
    onSetSlotIds: (next: Record<string, string>) => void;
    onPatchRule: (id: string, patch: Partial<SlotRule>) => void;
  };
  ```
  Task 4 EXTENDS this type with preview props — keep these names stable.
- CustomLabelsUI: `slot-grid` testid moves to a vertical `Stack`; per-rule editor JSX MOVES OUT of CustomLabelsUI into SlotGroup.

- [ ] **Step 1: Add i18n keys**

`frontend/public/locales/en/customLabels.json` — add:

```json
  "noRulesYet": "no rules yet",
  "activeRulesCount": "{{count}} active rules",
  "slotExplanations": {
    "custom_label_0": "Top-level campaign grouping, e.g. bestsellers vs. long tail.",
    "custom_label_1": "Mid-funnel segmentation, e.g. margin or funnel stage.",
    "custom_label_2": "Seasonal or event labels, e.g. sale, winter.",
    "custom_label_3": "Product type or category grouping.",
    "custom_label_4": "Free reserve, e.g. price tier or supplier."
  },
```

`frontend/public/locales/de/customLabels.json` — add:

```json
  "noRulesYet": "noch keine Regeln",
  "activeRulesCount": "{{count}} aktive Regeln",
  "slotExplanations": {
    "custom_label_0": "Gruppierung auf Kampagnen-Ebene, z. B. Bestseller vs. Long Tail.",
    "custom_label_1": "Mid-Funnel-Segmentierung, z. B. Marge oder Funnel-Stufe.",
    "custom_label_2": "Saisonale oder Event-Labels, z. B. Sale, Winter.",
    "custom_label_3": "Produkttyp- oder Kategorie-Gruppierung.",
    "custom_label_4": "Freie Reserve, z. B. Preisstufe oder Lieferant."
  },
```

- [ ] **Step 2: Update the component tests (failing first)**

In `CustomLabelsUI.test.tsx`:
1. Replace the test `wraps the slot grid in a horizontally scrollable container` with:

```tsx
  it('groups the bulk tab by target slot in registry order', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    const grid = document.querySelector('[data-testid="slot-grid"]') as HTMLElement;
    const groups = grid.querySelectorAll('[data-testid^="slot-group-"]');
    expect(Array.from(groups).map((g) => g.getAttribute('data-testid'))).toEqual([
      'slot-group-custom_label_1', 'slot-group-custom_label_2',
    ]);
    expect(screen.getByTestId('slot-empty-custom_label_0')).toBeInTheDocument();
  });
```

2. Add a static-info-box test:

```tsx
  it('info boxes show slot explanation and active rule count', async () => {
    renderUI({ feedSourceId: 1 });
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(
      screen.getByText(/mid-funnel segmentation/i),
    ).toBeInTheDocument();
    // both groups have exactly one active rule
    expect(screen.getAllByText('1 active rules').length).toBe(2);
  });
```

(Existing bulk tests — merged-rule rendering, ID counts, mode-aware editors,
override gating — keep passing: SlotGroup preserves the same aria-labels,
testids (`all-mode-{id}`), and texts.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm run test -- CustomLabelsUI`
Expected: FAIL — no `slot-group-*` testids yet.

- [ ] **Step 4: Implement**

Create `frontend/src/features/customLabels/SlotGroup.tsx`:

```tsx
import { Badge, Button, Card, Collapse, Group, Paper, Stack, Text, Textarea } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { parseIdList, renderPreview } from './ids';
import type { ScopedSlotRule, SlotRule, Tier } from './scopeMerge';

export type SlotGroupProps = {
  slot: string;
  rules: ScopedSlotRule[];
  values: Record<string, string>;
  inheritedFor: (id: string) => boolean;
  isRuleEditable: (rule: ScopedSlotRule) => boolean;
  editableTier: Tier | null;
  onSetSlotIds: (next: Record<string, string>) => void;
  onPatchRule: (id: string, patch: Partial<SlotRule>) => void;
};

export function SlotGroup({
  slot, rules, values, inheritedFor, isRuleEditable, editableTier, onSetSlotIds, onPatchRule,
}: SlotGroupProps) {
  const { t } = useTranslation('customLabels');
  const { t: tCommon } = useTranslation('common');
  return (
    <Card withBorder p="sm" data-testid={`slot-group-${slot}`}>
      <Stack gap="xs">
        <Group gap="xs" justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <Badge variant="light" color="teal">{slot}</Badge>
            <Text size="xs" c="dimmed">{t(`slotExplanations.${slot}`)}</Text>
          </Group>
          <Text size="xs" c="dimmed">{t('activeRulesCount', { count: rules.length })}</Text>
        </Group>
        <Stack gap="md">
          {rules.map((rule) => {
            const allMode = rule.matchMode === 'all';
            const raw = values[rule.id] ?? '';
            const count = parseIdList(raw).size;
            const inherited = inheritedFor(rule.id);
            return (
              <Stack key={rule.id} gap={4}>
                <Group gap="xs" justify="space-between" wrap="nowrap">
                  <Group gap="xs" wrap="nowrap">
                    <Text size="sm" fw={600}>{rule.name}</Text>
                    {inherited && (
                      <Badge size="xs" variant="light" color="teal">
                        {t('inheritedFrom', { tier: tCommon('scope.client') })}
                      </Badge>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed">{rule.matchField}</Text>
                </Group>
                <Text size="xs" c="dimmed">{renderPreview(rule.valueTemplate)}</Text>
                <Collapse in={!allMode}>
                  <Stack gap={4}>
                    <Textarea
                      label={rule.matchField === 'id'
                        ? t('bulk.productIds')
                        : t('bulk.valuesFor', { field: rule.matchField })}
                      aria-label={rule.matchField === 'id'
                        ? `${rule.name} ids`
                        : `${rule.name} values`}
                      minRows={5}
                      autosize
                      value={raw}
                      onChange={(e) => onSetSlotIds({ ...values, [rule.id]: e.currentTarget.value })}
                      placeholder={t('idsPlaceholder')}
                    />
                    <Text size="xs" c="dimmed">{t('idCount', { count })}</Text>
                  </Stack>
                </Collapse>
                <Collapse in={allMode}>
                  <Paper withBorder p="xs" data-testid={`all-mode-${rule.id}`}>
                    <Stack gap={4}>
                      <Text size="sm" c="dimmed">{t('bulk.controlledByRule')}</Text>
                      <Text size="sm" fw={600}>
                        {t('bulk.allProductsGet', { preview: renderPreview(rule.valueTemplate) })}
                      </Text>
                      {isRuleEditable(rule) && (
                        <Button
                          variant="subtle"
                          size="xs"
                          onClick={() => onPatchRule(rule.id, { matchMode: 'values' })}
                        >
                          {t('bulk.switchToValueList')}
                        </Button>
                      )}
                    </Stack>
                  </Paper>
                </Collapse>
              </Stack>
            );
          })}
        </Stack>
      </Stack>
    </Card>
  );
}
```

Note: the override button is gated on `isRuleEditable(rule)` — preserving the
final-review fix `d4d78de` (never gate on `editableTier !== null`).

In `CustomLabelsUI.tsx`:

1. Import: `import { SlotGroup } from './SlotGroup';` — and REMOVE now-unused
   imports (`Collapse`, `Paper`, `Textarea`, `parseIdList`, `renderPreview` —
   verify each with a search before removing; `Badge` stays for the rules tab).
2. Replace the entire `<div data-testid="slot-grid" style={{ overflowX: 'auto' }}>…</div>`
   block (the Group + activeRules.map with the per-rule editor) with:

```tsx
              <Stack gap="md" data-testid="slot-grid">
                {TARGET_SLOTS.map((slot) => {
                  const slotRules = activeRules.filter((r) => r.targetSlot === slot);
                  if (slotRules.length === 0) {
                    return (
                      <Group key={slot} gap="xs" data-testid={`slot-empty-${slot}`}>
                        <Badge size="xs" variant="light">{slot}</Badge>
                        <Text size="sm" c="dimmed">{t('noRulesYet')}</Text>
                      </Group>
                    );
                  }
                  return (
                    <SlotGroup
                      key={slot}
                      slot={slot}
                      rules={slotRules}
                      values={effectiveIds}
                      inheritedFor={(id) =>
                        serverIds[id]?.inherited === true
                        && (effectiveIds[id] ?? '') === serverIds[id].value
                      }
                      isRuleEditable={ruleEditable}
                      editableTier={editableTier}
                      onSetSlotIds={setSlotIds}
                      onPatchRule={patchRule}
                    />
                  );
                })}
              </Stack>
```

- [ ] **Step 5: Run tests + typecheck**

Run: `npm run test -- CustomLabelsUI && npm run typecheck`
Expected: PASS (updated + new tests; existing bulk tests unchanged and green).

- [ ] **Step 6: Commit**

```bash
git add src/features/customLabels public/locales
git commit -m "feat(frontend): bulk tab grouped by target slot with info boxes"
```

---

### Task 4: Frontend — live stats in the slot info boxes

**Files:**
- Modify: `frontend/src/features/customLabels/SlotGroup.tsx`
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx`
- Modify: `frontend/public/locales/en/customLabels.json`, `de/customLabels.json`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Consumes: `useLabelizerPreview` (Task 2), `Link` from `react-router`, `Anchor`/`Loader`/`Tooltip` from `@mantine/core`.
- Produces: `SlotGroupProps` EXTENDED with:
  ```ts
    showLive: boolean;
    stats?: { labeled: number; coverage: number };
    ruleStats?: Record<string, PreviewRuleStats>;
    total?: number;
    previewPending: boolean;
    previewErrors: string[] | null;
    previewUnavailable: boolean;
    productsHref: string | null;
  ```
  (`PreviewRuleStats` imported from `./usePreview`.)

- [ ] **Step 1: Add i18n keys**

`en/customLabels.json` — add:

```json
  "openFromFeed": "Open this plugin from a feed to see live match stats.",
  "previewUnavailable": "Live preview unavailable.",
  "noStagedProducts": "No staged products yet — run the pipeline first.",
  "slotLabeled": "{{count}} products get this label",
  "coveragePct": "{{coverage}}% coverage",
  "freshnessHint": "based on the last run's {{count}} staged products",
  "matchedCount": "{{count}} match",
  "neverApplied": "never applied",
  "neverAppliedHint": "This rule matches products but never produces the label — an earlier rule on this slot wins, or its template always resolves empty.",
```

`de/customLabels.json` — add:

```json
  "openFromFeed": "Öffne dieses Plugin über einen Feed, um Live-Match-Statistiken zu sehen.",
  "previewUnavailable": "Live-Vorschau nicht verfügbar.",
  "noStagedProducts": "Noch keine gestagten Produkte — zuerst die Pipeline ausführen.",
  "slotLabeled": "{{count}} Produkte erhalten dieses Label",
  "coveragePct": "{{coverage}}% Abdeckung",
  "freshnessHint": "basierend auf den {{count}} gestagten Produkten des letzten Laufs",
  "matchedCount": "{{count}} Treffer",
  "neverApplied": "nie angewendet",
  "neverAppliedHint": "Diese Regel matcht Produkte, erzeugt aber nie das Label — eine frühere Regel dieses Slots gewinnt, oder ihre Vorlage löst immer leer auf.",
```

- [ ] **Step 2: Write the failing tests**

Add to `CustomLabelsUI.test.tsx` (the `renderFeedWithConfig` helper from the
mode-awareness tests is available for custom-config stubs):

```tsx
  const PREVIEW = {
    total: 3,
    rules: {
      r1: { matched: 2, labeled: 2, sample: ['a1', 'a2'] },
      r3: { matched: 1, labeled: 0, sample: ['z1'] },
    },
    slots: {
      custom_label_1: { labeled: 2, coverage: 66.7, rules: ['r1'] },
      custom_label_2: { labeled: 0, coverage: 0, rules: ['r3'] },
    },
  };

  it('renders live stats, sample links, and the shadowed marker on the feed page', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) return jsonResponse(PREVIEW);
      return jsonResponseFor(url);
    });
    renderUI({ feedSourceId: 1 });
    expect(await waitFor(() =>
      expect(screen.getByText(/2 products get this label/i)).toBeInTheDocument(),
      { timeout: 2500 })).toBeTruthy();
    expect(screen.getByText(/66\.7% coverage/i)).toBeInTheDocument();
    expect(screen.getByText(/based on the last run's 3 staged products/i)).toBeInTheDocument();
    const sample = screen.getByRole('link', { name: 'a1' });
    expect(sample).toHaveAttribute(
      'href', '/clients/1/feeds/1/products?q=a1',
    );
    // r3 matched but never labeled -> shadowed marker
    expect(screen.getByText(/never applied/i)).toBeInTheDocument();
  });

  it('total=0 shows the never-run hint instead of zero stats', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/preview')) {
        return jsonResponse({ total: 0, rules: {}, slots: {} });
      }
      return jsonResponseFor(url);
    });
    renderUI({ feedSourceId: 1 });
    expect(await waitFor(() =>
      expect(screen.getByText(/no staged products yet/i)).toBeInTheDocument(),
      { timeout: 2500 })).toBeTruthy();
  });

  it('client page sends no preview request and shows the open-from-feed hint', async () => {
    const calls: string[] = [];
    stubFetch((url) => {
      calls.push(url);
      return jsonResponseFor(url);
    });
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Client Only');
    expect(screen.getByText(/open this plugin from a feed/i)).toBeInTheDocument();
    expect(calls.some((u) => u.includes('/preview'))).toBe(false);
  });
```

(If `waitFor` is not yet imported in the test file, add it to the
`@testing-library/react` import.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm run test -- CustomLabelsUI`
Expected: FAIL — no stats/sample links/hints yet.

- [ ] **Step 4: Implement**

In `SlotGroup.tsx`:

1. Extend imports: `Anchor, Loader, Tooltip` into the `@mantine/core` import;
   `import { Link } from 'react-router';`;
   `import type { PreviewRuleStats } from './usePreview';`
2. Extend `SlotGroupProps` with the preview block (Step interfaces above) and
   destructure the new props.
3. Insert the stats section directly BELOW the slot header `Group` (above the
   rules `Stack`):

```tsx
        {!showLive ? (
          <Text size="xs" c="dimmed">{t('openFromFeed')}</Text>
        ) : previewUnavailable ? (
          <Text size="xs" c="dimmed">{t('previewUnavailable')}</Text>
        ) : previewErrors ? (
          <Stack gap={2}>
            {previewErrors.map((error) => (
              <Text key={error} size="xs" c="dimmed">{error}</Text>
            ))}
          </Stack>
        ) : total === undefined ? (
          previewPending ? <Loader size="xs" /> : null
        ) : total === 0 ? (
          <Text size="xs" c="dimmed">{t('noStagedProducts')}</Text>
        ) : (
          <Stack gap={4}>
            <Group gap="xs" wrap="nowrap">
              {previewPending && <Loader size="xs" />}
              <Text size="xs" c="dimmed">
                {t('slotLabeled', { count: stats?.labeled ?? 0 })}
              </Text>
              <Text size="xs" c="dimmed">
                {t('coveragePct', { coverage: stats?.coverage ?? 0 })}
              </Text>
              <Text size="xs" c="dimmed">{t('freshnessHint', { count: total })}</Text>
            </Group>
            {rules.map((rule) => {
              const rs = ruleStats?.[rule.id];
              const neverApplied = (rs?.matched ?? 0) > 0 && (rs?.labeled ?? 0) === 0;
              return (
                <Group key={rule.id} gap="xs" wrap="nowrap">
                  <Text size="xs" fw={500}>{rule.name}</Text>
                  <Text size="xs" c="dimmed">
                    {t('matchedCount', { count: rs?.matched ?? 0 })}
                  </Text>
                  {neverApplied && (
                    <Tooltip label={t('neverAppliedHint')} withArrow position="top">
                      <Badge size="xs" variant="light" color="gray">
                        {t('neverApplied')}
                      </Badge>
                    </Tooltip>
                  )}
                  {(rs?.sample ?? []).map((pid) => (
                    <Anchor
                      key={pid}
                      component={Link}
                      to={`${productsHref}?q=${encodeURIComponent(pid)}`}
                      size="xs"
                    >
                      {pid}
                    </Anchor>
                  ))}
                </Group>
              );
            })}
          </Stack>
        )}
```

In `CustomLabelsUI.tsx`:

1. Import `useLabelizerPreview` from `./usePreview`.
2. After the `sensors` line add:

```tsx
  const atFeed = scope.feedSourceId !== undefined;
  const preview = useLabelizerPreview({
    enabled: atFeed,
    feedSourceId: scope.feedSourceId,
    rules: effectiveRules,
    slotIds: effectiveIds,
  });
  const productsHref = atFeed && routeContext.clientId && routeContext.feedSourceId
    ? `/clients/${routeContext.clientId}/feeds/${routeContext.feedSourceId}/products`
    : null;
```

3. Pass the new props to every `<SlotGroup …>`:

```tsx
                      showLive={atFeed}
                      stats={preview.result?.slots[slot]}
                      ruleStats={preview.result?.rules}
                      total={preview.result?.total}
                      previewPending={preview.isPending}
                      previewErrors={preview.errors}
                      previewUnavailable={preview.unavailable}
                      productsHref={productsHref}
```

(`preview.result?.slots[slot]` matches `stats?: { labeled: number; coverage: number }`
structurally — the extra `rules` key is assignable structurally; if tsc's excess
property check fires on the inline member access it will not, since it's a
property access, not a fresh object literal.)

- [ ] **Step 5: Run tests + typecheck**

Run: `npm run test -- CustomLabelsUI && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/features/customLabels public/locales
git commit -m "feat(frontend): live match stats in slot info boxes"
```

---

### Task 5: Frontend — rule actions: Duplicate + Delete

**Files:**
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx`
- Modify: `frontend/public/locales/en/customLabels.json`, `de/customLabels.json`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Consumes: `ConfirmModal` (`frontend/src/components/ConfirmModal.tsx` — props `{opened, title, message, confirmLabel?, danger?, loading?, typeToConfirm?, onConfirm, onClose}`); `ruleEditable` from the component.
- Produces: `newRuleId(): string` helper (extracted from `newRule`); `duplicateSelected()`, `deleteSelected()` component functions; a `deleteOpen` disclosure state.

- [ ] **Step 1: Add i18n keys**

`en/customLabels.json` — add:

```json
  "duplicateRule": "Duplicate",
  "deleteRule": "Delete",
  "duplicateSuffix": "(copy)",
  "deleteConfirmTitle": "Delete rule",
  "deleteConfirmBody": "Delete rule \"{{name}}\"? You can still undo with Cancel until you save.",
  "deleteGlobalWarning": "Delete rule \"{{name}}\"? It is inherited by every client — deleting it affects all of them. You can still undo with Cancel until you save.",
```

`de/customLabels.json` — add:

```json
  "duplicateRule": "Duplizieren",
  "deleteRule": "Löschen",
  "duplicateSuffix": "(Kopie)",
  "deleteConfirmTitle": "Regel löschen",
  "deleteConfirmBody": "Regel \"{{name}}\" löschen? Bis zum Speichern kannst du es mit Abbrechen zurücknehmen.",
  "deleteGlobalWarning": "Regel \"{{name}}\" löschen? Sie wird von allen Mandanten geerbt — das Löschen betrifft alle. Bis zum Speichern kannst du es mit Abbrechen zurücknehmen.",
```

- [ ] **Step 2: Write the failing tests**

Add to `CustomLabelsUI.test.tsx`:

```tsx
  it('duplicates the selected rule with a fresh id and localized copy name', async () => {
    const puts: { body: unknown }[] = [];
    stubFetch((url, init) => {
      if (url.includes('/config?client_id=1') && init?.method === 'PUT') {
        puts.push({ body: JSON.parse(String(init.body)) });
        return jsonResponse(CLIENT_CONFIG);
      }
      return jsonResponseFor(url);
    });
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Client Only');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Client Only'));
    await userEvent.click(screen.getByRole('button', { name: /duplicate/i }));
    expect(screen.getByText('Client Only (copy)')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await screen.findByText(/saved/i);
    const payload = puts[0].body as { slotRules: { id: string; name: string }[] };
    const names = payload.slotRules.map((r) => r.name);
    expect(names).toContain('Client Only');
    expect(names).toContain('Client Only (copy)');
    expect(new Set(payload.slotRules.map((r) => r.id)).size).toBe(payload.slotRules.length);
  });

  it('delete asks for confirmation and removes the rule from the editable tier', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Client Only');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Client Only'));
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    expect(screen.getByText(/delete rule "client only"/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /delete/i, exact: false }));
    // the only remaining rule is the inherited global one — still listed
    expect(await screen.findByText('Mid Funnel')).toBeInTheDocument();
    expect(screen.queryByText('Client Only')).not.toBeInTheDocument();
  });

  it('rule actions are hidden for inherited rules', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(screen.queryByRole('button', { name: /duplicate/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
  });

  it('global-origin delete confirm mentions the inheritance blast radius', async () => {
    stubFetch((url) => {
      if (url.startsWith('/plugins/custom_labels/config') && url.includes('client_id=')) {
        return jsonResponse({ slotRules: [] });
      }
      return jsonResponseFor(url);
    });
    renderUI({}, '/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByText('Mid Funnel'));
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    expect(screen.getByText(/inherited by every client/i)).toBeInTheDocument();
  });
```

(For the delete-confirm test, the ConfirmModal's confirm button also matches
`/delete/i` — after opening the modal use `getByRole('button', { name: /^delete$/i })`
if the two buttons collide; adjust the exact matcher so the MODAL's confirm is
clicked, not the card's Delete. The Modal renders in a portal —
`within(screen.getByRole('dialog'))` scoping is the robust option.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm run test -- CustomLabelsUI`
Expected: FAIL — no action buttons yet.

- [ ] **Step 4: Implement**

In `CustomLabelsUI.tsx`:

1. Imports: add `ConfirmModal` from `../../components/ConfirmModal`;
   `useDisclosure` from `@mantine/hooks`.
2. Extract the id generator (replace the inline id in `newRule`):

```ts
function newRuleId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `r_${Math.random().toString(36).slice(2)}`;
}
```

   and `newRule` becomes:

```ts
function newRule(name: string, origin: Tier): ScopedSlotRule {
  return {
    id: newRuleId(),
    name,
    isActive: true,
    targetSlot: 'custom_label_0',
    matchField: 'id',
    matchMode: 'values',
    valueTemplate: '',
    fallbackTemplate: '',
    origin,
  };
}
```

3. In the component, next to the other state:

```tsx
  const [deleteOpen, { open: openDelete, close: closeDelete }] = useDisclosure(false);
```

4. Next to `patchRule` add:

```tsx
  function duplicateSelected() {
    if (!selected) return;
    const copy: ScopedSlotRule = {
      ...selected,
      id: newRuleId(),
      name: `${selected.name} ${t('duplicateSuffix')}`,
    };
    const index = effectiveRules.findIndex((r) => r.id === selected.id);
    const next = [...effectiveRules];
    next.splice(index + 1, 0, copy);
    setRules(next);
    setSelectedId(copy.id);
  }

  function deleteSelected() {
    if (!selected) return;
    setRules(effectiveRules.filter((r) => r.id !== selected.id));
    setSelectedId(null);
    closeDelete();
  }
```

5. In the editor card's `Stack`, directly BELOW the inherited-origin note block,
   insert the action row (only for editable-origin rules):

```tsx
                    {ruleEditable(selected) && (
                      <Group gap="xs">
                        <Button size="xs" variant="light" onClick={duplicateSelected}>
                          {t('duplicateRule')}
                        </Button>
                        <Button size="xs" variant="light" color="red" onClick={openDelete}>
                          {t('deleteRule')}
                        </Button>
                      </Group>
                    )}
```

6. At the end of the component's returned JSX (after the `</Tabs>`, inside the
   outer `Stack`), add the confirm modal:

```tsx
      <ConfirmModal
        opened={deleteOpen}
        onClose={closeDelete}
        onConfirm={deleteSelected}
        danger
        title={t('deleteConfirmTitle')}
        message={selected?.origin === 'global'
          ? t('deleteGlobalWarning', { name: selected.name })
          : t('deleteConfirmBody', { name: selected.name ?? '' })}
        confirmLabel={t('deleteRule')}
      />
```

- [ ] **Step 5: Run tests + typecheck**

Run: `npm run test -- CustomLabelsUI && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/features/customLabels public/locales
git commit -m "feat(frontend): duplicate and delete slot rules"
```

---

### Task 6: Frontend — reworded read-only hint + override at client level

**Files:**
- Modify: `frontend/public/locales/en/customLabels.json`, `de/customLabels.json`
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Consumes: `editableTier`, `ruleEditable`, `patchRule`-style local state helpers.
- Produces: `overrideSelected()` — flips the selected rule's `origin` to `'client'` in place (same id, same position).

- [ ] **Step 1: Reword the hint + add i18n keys**

`en/customLabels.json` — REPLACE the `rulesReadOnly` value:

```json
  "rulesReadOnly": "Slot rules are read-only here — they live at Global or Client level.",
```

and add:

```json
  "overrideAtClient": "Override at client level",
```

`de/customLabels.json` — REPLACE `rulesReadOnly`:

```json
  "rulesReadOnly": "Slot-Regeln sind hier schreibgeschützt — sie liegen auf Global- oder Client-Ebene.",
```

and add:

```json
  "overrideAtClient": "Auf Client-Ebene überschreiben",
```

(The `manageAtClient` link and the `rules-readonly-hint` testid stay as they are.)

- [ ] **Step 2: Write the failing tests**

Add to `CustomLabelsUI.test.tsx`:

```tsx
  it('feed page shows the short read-only hint with the client-level link', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    const hint = screen.getByTestId('rules-readonly-hint');
    expect(hint).toHaveTextContent(/read-only here — they live at global or client level/i);
    expect(screen.queryByText(/shared templates/i)).not.toBeInTheDocument();
  });

  it('override at client level flips an inherited rule editable and saves it to the client tier', async () => {
    const puts: { body: unknown }[] = [];
    stubFetch((url, init) => {
      if (url.includes('/config?client_id=1') && init?.method === 'PUT') {
        puts.push({ body: JSON.parse(String(init.body)) });
        return jsonResponse(CLIENT_CONFIG);
      }
      return jsonResponseFor(url);
    });
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Mid Funnel'));
    // inherited rule is read-only, but offers the override
    expect(screen.getByLabelText(/name/i, { selector: 'input' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: /override at client level/i }));
    expect(screen.getByLabelText(/name/i, { selector: 'input' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await screen.findByText(/saved/i);
    const payload = puts[0].body as { slotRules: { id: string }[] };
    // the overridden global rule (id r1) now saves to the client tier
    expect(payload.slotRules.map((r) => r.id)).toEqual(['r1', 'r3']);
  });

  it('no override action on the feed page (config read-only there)', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    await userEvent.click(screen.getByRole('tab', { name: /slot rules/i }));
    await userEvent.click(screen.getByText('Mid Funnel'));
    expect(
      screen.queryByRole('button', { name: /override at client level/i }),
    ).not.toBeInTheDocument();
  });
```

(Note the override test's expected PUT payload `['r1', 'r3']`: r1 is the
overridden global rule — client-origin now, same id — and r3 is the existing
client rule. GLOBAL_CONFIG's r2 is inactive and never appears.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm run test -- CustomLabelsUI`
Expected: FAIL — hint text mismatch, no override button.

- [ ] **Step 4: Implement**

In `CustomLabelsUI.tsx`, next to `duplicateSelected`/`deleteSelected` add:

```tsx
  function overrideSelected() {
    if (!selected) return;
    setRules(effectiveRules.map((r) =>
      r.id === selected.id ? { ...r, origin: 'client' } : r));
  }
```

In the editor card, the inherited-note block currently renders when
`!ruleEditable(selected)`. Extend it with the override button (client page only):

```tsx
                    {!ruleEditable(selected) && (
                      <Group gap="xs" wrap="nowrap">
                        <ScopeBadge tier={selected.origin} />
                        <Text size="xs" c="dimmed">
                          {t('ruleInherited', { tier: tCommon(`scope.${selected.origin}`) })}
                        </Text>
                        {editableTier === 'client' && (
                          <Button size="xs" variant="light" onClick={overrideSelected}>
                            {t('overrideAtClient')}
                          </Button>
                        )}
                      </Group>
                    )}
```

(Keep the existing `ruleInherited` text; only the Button is new. The feed page
has `editableTier === null` → no button there.)

- [ ] **Step 5: Run tests + typecheck**

Run: `npm run test -- CustomLabelsUI && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/features/customLabels public/locales
git commit -m "feat(frontend): override inherited rules at client level + hint reword"
```

---

### Task 7: Frontend — clickable tier navigation in `ScopeContextBar`

**Files:**
- Modify: `frontend/src/components/ScopeContextBar.tsx`
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx`
- Modify: `frontend/src/components/ScopeContextBar.test.tsx`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`

**Interfaces:**
- Produces: `ScopeContextBarProps` gains `hrefs?: Partial<Record<Tier, string>>`.
  Badges for tiers OTHER than `current` render as links (testid
  `scope-link-{tier}`) when an href exists; the current tier stays a static
  filled badge.

- [ ] **Step 1: Write the failing tests**

In `ScopeContextBar.test.tsx`, extend the existing test and add one:

```tsx
it('renders non-current tiers as links and the current tier as a static badge', () => {
  render(
    <ScopeContextBar
      current="feed_source"
      configTiers={['global', 'client']}
      dataTiers={['client', 'feed_source']}
      configLabel="Slot rules"
      dataLabel="Bulk values"
      hrefs={{
        global: '/plugins/custom_labels',
        client: '/clients/1/plugins/custom_labels',
      }}
    />,
  );
  expect(screen.getByTestId('scope-link-global')).toHaveAttribute(
    'href', '/plugins/custom_labels',
  );
  expect(screen.getByTestId('scope-link-client')).toHaveAttribute(
    'href', '/clients/1/plugins/custom_labels',
  );
  expect(screen.queryByTestId('scope-link-feed_source')).not.toBeInTheDocument();
  expect(screen.getAllByTestId('scope-badge-feed_source').length).toBeGreaterThan(0);
});
```

In `CustomLabelsUI.test.tsx`, add:

```tsx
  it('tier badges navigate: feed page links to global and client pages', async () => {
    renderUI({ feedSourceId: 1 });
    await screen.findByText('Mid Funnel');
    expect(screen.getByTestId('scope-link-global')).toHaveAttribute(
      'href', '/plugins/custom_labels',
    );
    expect(screen.getByTestId('scope-link-client')).toHaveAttribute(
      'href', '/clients/1/plugins/custom_labels',
    );
  });

  it('client page links to the global page only', async () => {
    renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels');
    await screen.findByText('Client Only');
    expect(screen.getByTestId('scope-link-global')).toHaveAttribute(
      'href', '/plugins/custom_labels',
    );
    expect(screen.queryByTestId('scope-link-client')).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- ScopeContextBar && npm run test -- CustomLabelsUI`
Expected: FAIL — no `scope-link-*` testids.

- [ ] **Step 3: Implement**

Rewrite `frontend/src/components/ScopeContextBar.tsx`:

```tsx
import { Anchor, Group, Paper, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ScopeBadge } from './ScopeBadge';
import type { Tier } from '../types/scope';

type Props = {
  current: Tier;
  configTiers: Tier[];
  dataTiers: Tier[];
  configLabel: string;
  dataLabel: string;
  hrefs?: Partial<Record<Tier, string>>;
};

function TierBadge({
  tier, filled, href,
}: { tier: Tier; filled: boolean; href?: string }) {
  if (!href) return <ScopeBadge tier={tier} filled={filled} />;
  return (
    <Anchor
      component={Link}
      to={href}
      underline="never"
      data-testid={`scope-link-${tier}`}
    >
      <ScopeBadge tier={tier} filled={filled} />
    </Anchor>
  );
}

export function ScopeContextBar({
  current, configTiers, dataTiers, configLabel, dataLabel, hrefs,
}: Props) {
  const { t } = useTranslation();
  const badgeFor = (tier: Tier, filled: boolean) => (
    <TierBadge tier={tier} filled={filled} href={tier !== current ? hrefs?.[tier] : undefined} />
  );
  return (
    <Paper
      withBorder
      p="xs"
      mb="sm"
      data-testid="scope-context-bar"
      style={{ position: 'sticky', top: 4, zIndex: 1 }}
    >
      <Group gap="lg" wrap="nowrap">
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" c="dimmed">{t('scope.viewing')}</Text>
          <ScopeBadge tier={current} filled />
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" c="dimmed">{configLabel}</Text>
          {configTiers.map((tier) => (
            <span key={`config-${tier}`}>{badgeFor(tier, tier === current)}</span>
          ))}
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" c="dimmed">{dataLabel}</Text>
          {dataTiers.length === 0 ? (
            <Text size="sm" c="dimmed">—</Text>
          ) : (
            dataTiers.map((tier) => (
              <span key={`data-${tier}`}>{badgeFor(tier, tier === current)}</span>
            ))
          )}
        </Group>
      </Group>
    </Paper>
  );
}
```

(The `key` spans exist because the same tier can appear in both groups — React
needs unique keys per list, and the testids still resolve via `getAllByTestId`.)

In `CustomLabelsUI.tsx`, compute the href map (after `viewingTier`) and pass it:

```tsx
  const tierHrefs: Partial<Record<Tier, string>> = {
    global: `/plugins/${pluginId}`,
    ...(routeContext.clientId
      ? { client: `/clients/${routeContext.clientId}/plugins/${pluginId}` }
      : {}),
    ...(routeContext.clientId && routeContext.feedSourceId
      ? {
        feed_source:
          `/clients/${routeContext.clientId}/feeds/${routeContext.feedSourceId}/plugins/${pluginId}`,
      }
      : {}),
  };
```

and extend the `<ScopeContextBar … />` call with:

```tsx
        hrefs={tierHrefs}
```

- [ ] **Step 4: Run tests + typecheck**

Run: `npm run test -- ScopeContextBar && npm run test -- CustomLabelsUI && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/ScopeContextBar.tsx src/components/ScopeContextBar.test.tsx src/features/customLabels
git commit -m "feat(frontend): clickable tier navigation in scope context bar"
```

---

### Task 8: Docs + full verification

**Files:**
- Modify: `backend/docs/plugins.md`
- Modify: `frontend/docs/plugin-uis.md`

**Interfaces:**
- Consumes: everything above.
- Produces: documentation of the preview route, grouped bulk tab, live stats,
  rule actions, tier navigation, override semantics, reworded hint.

- [ ] **Step 1: Backend docs**

Append to `backend/docs/plugins.md` (near the filter preview documentation; find
the section describing `POST /plugins/filter/preview` and add the sibling):

```markdown
### `POST /plugins/custom_labels/preview`

Live match statistics for a DRAFT rules+values state against the feed's staged
products (active, non-excluded, last successful run — `raw_data` is the mapped
product the plugin sees at run time). Body:
`{feed_source_id, rules, slotIds, sample_size? (1–50, default 5)}`. Draft rules
run through the plugin's own `validate_config` (422 `{"errors": [...]}` on
invalid drafts). Response: `{total, rules: {id: {matched, labeled, sample}},
slots: {slot: {labeled, coverage, rules}}}` — `labeled` per rule counts only
template-rendered wins; fallback wins credit the slot. Shadowed rules
(matched > 0, labeled == 0) are surfaced by the UI as "never applied".
```

- [ ] **Step 2: Frontend docs**

Append to `frontend/docs/plugin-uis.md` (in the custom_labels section added by
the previous cycle):

```markdown
### Live matching and slot-grouped bulk values

- **Preview:** the feed-page bulk tab debounce-posts the current DRAFT
  (rules + values, unsaved edits included) to the plugin-local
  `POST /plugins/custom_labels/preview` and renders per-slot live stats in the
  info boxes: labeled products, coverage %, per-rule match counts, sample
  product links (deep-link `?q=` into the Products page), a "never applied"
  marker for shadowed rules, and a distinct "no staged products yet" state.
  Client/global pages show a dimmed hint instead (no request).
- **Grouped by slot:** the bulk tab renders one group per `custom_label_0..4`
  (registry order) — info box header (slot explanation, active-rule count,
  live stats) with the slot's rule editors nested inside. Slots without active
  rules show slim "no rules yet" rows.
- **Rule actions:** the rule editor offers Duplicate (fresh id, "(copy)" name)
  and Delete (ConfirmModal; global-origin deletes warn about the inheritance
  blast radius) — editable-origin rules only.
- **Override at client level:** on the client page, an inherited global rule
  offers "Override at client level" — flips the rule to client-origin with the
  SAME id (union-by-id makes client content win at run time), editable
  immediately, saved to the client tier on Save.
- **Tier navigation:** ScopeContextBar badges for non-current tiers link to
  their pages (Global → `/plugins/{id}`, Client → `/clients/:c/plugins/{id}`),
  making the global page reachable from client/feed contexts.
- **Read-only hint:** shortened to "Slot rules are read-only here — they live
  at Global or Client level." plus the manage-at-client link.
```

- [ ] **Step 3: Full verification**

From `backend/`:

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
uvx ruff check .
uvx mypy .
uv run pytest -n auto -q
```

From `frontend/`:

```bash
npm run test
npm run typecheck
npm run build
```

Expected: all green (backend baseline 871 + new preview tests; frontend
baseline ~270 + new tests; zero NEW ruff/mypy findings in touched files;
known AppShell/ProductsPage flakes re-run solo).

- [ ] **Step 4: Commit**

```bash
git add ../backend/docs/plugins.md ../frontend/docs/plugin-uis.md
git commit -m "docs: labelizer live matching, slot groups, rule actions, tier nav"
```

---

## Plan self-review (executed 2026-09-05)

- **Spec coverage:** §1 preview endpoint → Task 1; §2 hook → Task 2; §3 slot
  groups + info boxes → Tasks 3+4; §4 non-feed pages → Tasks 3 (hint) + 4
  (openFromFeed); §5 rule actions → Task 5; §6 hint reword → Task 6; §7 tier
  navigation → Task 7; §8 override → Task 6; error handling → Tasks 1/2/4;
  testing + docs → every task + Task 8. The three review amendments (distinct
  never-run state, clickable samples, shadowed marker) are all in Task 4.
  No gaps.
- **Placeholder scan:** the one deliberate exception — Task 1's `_registry`
  stub — carries an explicit replace instruction pointing at the real helper's
  exact location; everything else is complete code. No TBDs.
- **Type consistency:** `PreviewResult`/`PreviewRuleStats` defined in Task 2,
  imported by Task 4; `SlotGroupProps` names fixed in Task 3 and extended
  (not renamed) in Task 4; `newRuleId` extracted in Task 5 (used by `newRule`
  and `duplicateSelected`); `Tier` consistently imported from `types/scope`
  via `scopeMerge` re-export; backend `evaluate_rules` return shape matches
  Task 2's `PreviewResult` exactly.
- **Known-correctness guards carried forward:** override button gating uses
  `isRuleEditable(rule)` (preserves fix `d4d78de`); Mantine 9 `Collapse` uses
  `expanded` (verified in the previous cycle).
