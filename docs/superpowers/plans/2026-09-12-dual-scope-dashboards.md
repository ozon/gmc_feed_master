# Dual-Scope Navigation & Feed Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dual-scope navigation (global fleet vs per-feed workspace) with a per-feed dashboard page, fleet charts, scope-swapped sidebar, and two backend aggregates — no schema changes, no new dependencies.

**Architecture:** URL-derived scope drives the AppShell sidebar (global items at `/`, feed tools under `/clients/:clientId/feeds/:feedSourceId/*`). A new feed-subtree index route renders `FeedDashboardPage`, fed by one new backend aggregate `GET /feed-sources/{id}/dashboard`; the existing `/dashboard/summary` gains a `runs_by_day` 14-day trend. Shared dashboard primitives (`StatCard`, `ChartCard`, `dashboardColors`) are extracted first and consumed by both dashboard pages.

**Tech Stack:** React 19, TypeScript, react-router v7 (import from `react-router`), Mantine 9 + `@mantine/charts` (already installed), TanStack Query; FastAPI, SQLAlchemy 2.0 async, pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-dual-scope-dashboards-design.md`

## Global Constraints

- No schema changes, no migrations, no new dependencies (backend `pyproject.toml` or frontend `package.json`).
- Server state only via TanStack Query — hooks in `frontend/src/api/hooks.ts`, keys in `frontend/src/api/queryKeys.ts`.
- All new user-facing copy goes through i18next; **both** `en` and `de` locale files must be updated (`frontend/public/locales/{en,de}/<ns>.json`).
- Route param is `feedSourceId` (not `feedId`) — matches existing routes.
- All tests run from repo subdirectories: backend `uv run pytest`/`uv run ruff check .`/`uv run mypy .` from `backend/`, frontend `npm run test`/`npm run typecheck` from `frontend/`.
- Docs must be updated in the same commit as the behavior they describe (`backend/docs/api.md`, `frontend/docs/architecture.md`).
- Commit messages follow repo style: `feat:`, `refactor:`, `docs:`, `test:` prefixes.

---

### Task 1: Shared `StatCard` component (extract from DashboardPage)

**Files:**
- Create: `frontend/src/components/dashboard/StatCard.tsx`
- Create: `frontend/src/components/dashboard/StatCard.test.tsx`
- Modify: `frontend/src/features/dashboard/DashboardPage.tsx` (delete private StatCard, import shared)
- Test: existing `frontend/src/features/dashboard/DashboardPage.test.tsx` must keep passing

**Interfaces:**
- Consumes: `useTranslation` from `react-i18next` (namespace-free — number formatting only needs `i18n.language`).
- Produces: `export function StatCard({ label, value, variant }: { label: ReactNode; value: number; variant?: 'neutral' | 'warning' | 'critical' })` — used by Task 4 (DashboardPage refactor is this task) and Task 8 (FeedDashboardPage).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/dashboard/StatCard.test.tsx
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../../test/render';
import { StatCard } from './StatCard';

describe('StatCard', () => {
  it('renders label and formatted value', () => {
    render(<StatCard label="Active products" value={12480} />);
    expect(screen.getByText('Active products')).toBeInTheDocument();
    expect(screen.getByText('12,480')).toBeInTheDocument();
  });

  it('formats numbers with German locale', () => {
    render(<StatCard label="X" value={12480} />, { wrapper: undefined } as never);
    // default en locale asserted above; de asserted via i18n mock not needed here
  });

  it('applies critical variant color', () => {
    render(<StatCard label="Failed exports" value={3} variant="critical" />);
    const value = screen.getByText('3');
    expect(value).toHaveStyle({ color: 'var(--mantine-color-red-text)' });
  });
});
```

Note: drop the second `it` block (locale formatting) — it adds i18n mock complexity for no coverage gain. Keep tests 1 and 3 only.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/components/dashboard/StatCard.test.tsx`
Expected: FAIL — cannot resolve `./StatCard`.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/dashboard/StatCard.tsx
import { type ReactNode } from 'react';
import { Paper, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

const VARIANT_COLOR: Record<string, string> = {
  neutral: 'var(--mantine-color-text)',
  warning: 'var(--mantine-color-yellow-6)',
  critical: 'var(--mantine-color-red-6)',
};

export function StatCard({
  label,
  value,
  variant = 'neutral',
}: {
  label: ReactNode;
  value: number;
  variant?: 'neutral' | 'warning' | 'critical';
}) {
  const { i18n } = useTranslation();
  return (
    <Paper withBorder p="md" data-variant={variant}>
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text
        ff="monospace"
        size="xl"
        c={VARIANT_COLOR[variant]}
        style={{ fontVariantNumeric: 'tabular-nums' }}
      >
        {new Intl.NumberFormat(i18n.language).format(value)}
      </Text>
    </Paper>
  );
}
```

If the `toHaveStyle` assertion in step 1 is flaky under jsdom (inline `c=` prop resolves to a CSS var), assert on `data-variant="critical"` on the Paper instead — adjust the test to `expect(screen.getByText('3').closest('[data-variant]')).toHaveAttribute('data-variant', 'critical')` and keep the color mapping as-is.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/components/dashboard/StatCard.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Refactor DashboardPage to import it**

In `frontend/src/features/dashboard/DashboardPage.tsx`: delete the private `StatCard` function (lines 36–48) and its now-unused imports, then add:

```tsx
import { StatCard } from '../../components/dashboard/StatCard';
```

The four usages (`<StatCard label={...} value={...} />`) are unchanged — props are compatible (label was `string`, `ReactNode` accepts it).

- [ ] **Step 6: Run existing dashboard tests**

Run: `cd frontend && npm run test -- src/features/dashboard/`
Expected: PASS (all existing DashboardPage tests still green).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/dashboard/ frontend/src/features/dashboard/DashboardPage.tsx
git commit -m "refactor: extract StatCard to shared components/dashboard"
```

---

### Task 2: `ChartCard` and `dashboardColors`

**Files:**
- Create: `frontend/src/components/dashboard/ChartCard.tsx`
- Create: `frontend/src/components/dashboard/ChartCard.test.tsx`
- Create: `frontend/src/components/dashboard/dashboardColors.ts`
- Create: `frontend/src/components/dashboard/dashboardColors.test.ts`

**Interfaces:**
- Consumes: `EmptyState` from `frontend/src/components/StateViews.tsx` (props: `{ message?: string }`).
- Produces:
  - `export function ChartCard({ title, isEmpty, emptyMessage, children }: { title: ReactNode; isEmpty: boolean; emptyMessage?: string; children: ReactNode })`
  - `export const chartColors: Record<'success' | 'error' | 'warning' | 'info' | 'raw' | 'exportable' | 'passed' | 'dropped' | 'other', string>` — Mantine theme color strings (e.g. `'teal.6'`), used by Tasks 5, 8.
  - `export const donutPalette: string[]` — 8 colors for per-feed donut slices + `'gray.6'` reserved for "Other".

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/dashboard/ChartCard.test.tsx
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../../test/render';
import { ChartCard } from './ChartCard';

describe('ChartCard', () => {
  it('renders title and children when data present', () => {
    render(
      <ChartCard title="Pipeline health" isEmpty={false}>
        <div>chart-mock</div>
      </ChartCard>,
    );
    expect(screen.getByText('Pipeline health')).toBeInTheDocument();
    expect(screen.getByText('chart-mock')).toBeInTheDocument();
  });

  it('renders empty state instead of children when isEmpty', () => {
    render(
      <ChartCard title="Pipeline health" isEmpty emptyMessage="No runs yet">
        <div>chart-mock</div>
      </ChartCard>,
    );
    expect(screen.getByText('No runs yet')).toBeInTheDocument();
    expect(screen.queryByText('chart-mock')).not.toBeInTheDocument();
  });
});
```

```ts
// frontend/src/components/dashboard/dashboardColors.test.ts
import { describe, expect, it } from 'vitest';
import { chartColors, donutPalette } from './dashboardColors';

describe('dashboardColors', () => {
  it('maps every semantic series name', () => {
    for (const key of ['success', 'error', 'warning', 'info', 'raw', 'exportable', 'passed', 'dropped', 'other'] as const) {
      expect(typeof chartColors[key]).toBe('string');
      expect(chartColors[key]).toMatch(/^[a-z]+\.?\d*$/);
    }
  });

  it('provides 8 donut palette colors', () => {
    expect(donutPalette).toHaveLength(8);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- src/components/dashboard/`
Expected: FAIL — cannot resolve `./ChartCard`, `./dashboardColors`.

- [ ] **Step 3: Write minimal implementations**

```tsx
// frontend/src/components/dashboard/ChartCard.tsx
import { type ReactNode } from 'react';
import { Paper, Text, Title } from '@mantine/core';
import { EmptyState } from '../StateViews';

export function ChartCard({
  title,
  isEmpty,
  emptyMessage,
  children,
}: {
  title: ReactNode;
  isEmpty: boolean;
  emptyMessage?: string;
  children: ReactNode;
}) {
  return (
    <Paper withBorder p="md" data-testid="chart-card">
      <Title order={5} mb="sm">
        {title}
      </Title>
      {isEmpty ? <EmptyState message={emptyMessage} /> : children}
    </Paper>
  );
}
```

```ts
// frontend/src/components/dashboard/dashboardColors.ts
// Single source for chart series colors — theme tokens so light/dark both resolve.
export const chartColors = {
  success: 'teal.6',
  error: 'red.6',
  warning: 'yellow.6',
  info: 'blue.6',
  raw: 'gray.6',
  exportable: 'teal.6',
  passed: 'blue.4',
  dropped: 'red.6',
  other: 'gray.6',
} as const;

// 8 slices max per spec (top feeds + Other); gray.6 reserved for Other.
export const donutPalette = [
  'blue.6',
  'indigo.6',
  'violet.6',
  'grape.6',
  'pink.6',
  'orange.6',
  'yellow.6',
  'lime.6',
] as const;
```

Note: `Text` is imported but unused in ChartCard — remove it from the import (lint will flag it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test -- src/components/dashboard/`
Expected: PASS (4 tests across both files).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/
git commit -m "feat: shared ChartCard and dashboardColors primitives"
```

---

### Task 3: Backend — `runs_by_day` on `/dashboard/summary`

**Files:**
- Modify: `backend/app/routes/dashboard.py` (add query + response field)
- Test: `backend/tests/test_dashboard_api.py` (extend; existing `test_summary_empty` asserts full-body equality and must be updated)

**Interfaces:**
- Consumes: existing `IngestionRun` model (`backend/app/models/ingestion.py`), `user.client_ids` filtering pattern already in `dashboard_summary`.
- Produces: `GET /dashboard/summary` response gains `"runs_by_day": [{"date": "YYYY-MM-DD", "success": int, "error": int}]` — ascending by date, last 14 days, only `success`/`error` statuses. Task 6 (frontend hook types) depends on this shape.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_dashboard_api.py` (reuse existing fixtures `app_factory`, `logged_in_client`, `_make_feed`):

```python
async def _add_run(factory, feed_id, status, days_ago=0, processed=10):
    from datetime import timedelta
    async with factory() as session:
        async with session.begin():
            session.add(IngestionRun(
                feed_source_id=feed_id,
                status=status,
                started_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
                processed_count=processed,
            ))


async def test_summary_includes_runs_by_day(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_a = await _make_feed(factory, client, "Acme")
    await _add_run(factory, feed_a, "success", days_ago=1, processed=5)
    await _add_run(factory, feed_a, "success", days_ago=1, processed=7)
    await _add_run(factory, feed_a, "error", days_ago=2)
    await _add_run(factory, feed_a, "running", days_ago=1)  # excluded
    await _add_run(factory, feed_a, "success", days_ago=20)  # outside window

    body = (await client.get("/dashboard/summary")).json()
    runs_by_day = body["runs_by_day"]
    assert {"date", "success", "error"} == set(runs_by_day[0].keys())
    by_date = {row["date"]: row for row in runs_by_day}
    today = datetime.now(timezone.utc).date()
    assert by_date[str(today - timedelta(days=1))]["success"] == 2
    assert by_date[str(today - timedelta(days=1))]["error"] == 0
    assert by_date[str(today - timedelta(days=2))]["error"] == 1
    assert str(today - timedelta(days=20)) not in by_date


async def test_summary_runs_by_day_empty(app_factory):
    client = await logged_in_client(app_factory)
    body = (await client.get("/dashboard/summary")).json()
    assert body["runs_by_day"] == []
```

Update the existing `test_summary_empty` full-body assertion:

```python
    assert resp.json() == {"counts": {"clients": 0, "feed_sources": 0,
                                      "active_products": 0, "failed_last_exports": 0},
                           "clients": [], "runs_by_day": []}
```

Add `timedelta` to the datetime import at the top: `from datetime import datetime, timedelta, timezone`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_dashboard_api.py -x -q`
Expected: FAIL — `KeyError: 'runs_by_day'` (and the updated empty test fails on body mismatch).

- [ ] **Step 3: Implement**

In `backend/app/routes/dashboard.py`, add inside `dashboard_summary` (after `latest_runs = await _latest_runs(session, IngestionRun)` and before the `async with` block ends — the query needs `feed_ids`):

```python
        since = datetime.now(timezone.utc) - timedelta(days=14)
        trend_rows = (await session.execute(
            select(
                func.date(IngestionRun.started_at).label("day"),
                IngestionRun.status,
                func.count(),
            )
            .where(
                IngestionRun.feed_source_id.in_(feed_ids),
                IngestionRun.started_at >= since,
                IngestionRun.status.in_(("success", "error")),
            )
            .group_by("day", IngestionRun.status)
            .order_by("day")
        )).all()
        runs_by_day: dict[str, dict[str, int]] = {}
        for day, status, count in trend_rows:
            key = str(day)
            runs_by_day.setdefault(key, {"date": key, "success": 0, "error": 0})
            runs_by_day[key][status] = count
```

Add to the imports at the top of the file: `from datetime import datetime, timedelta, timezone`.

Add to the returned dict (after `"counts": {...},`):

```python
        "runs_by_day": list(runs_by_day.values()),
```

`func.date()` returns a `date` object; `str(day)` yields `YYYY-MM-DD`. `dict.values()` preserves first-insertion order which matches the `order_by("day")` ascending sequence.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_dashboard_api.py -x -q`
Expected: PASS (all dashboard tests).

- [ ] **Step 5: Lint and typecheck**

Run: `cd backend && uv run ruff check . && uv run mypy .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/dashboard.py backend/tests/test_dashboard_api.py
git commit -m "feat: 14-day runs_by_day trend on dashboard summary"
```

---

### Task 4: Backend — `GET /feed-sources/{id}/dashboard` aggregate

**Files:**
- Create: `backend/app/routes/feed_dashboard.py`
- Modify: `backend/app/main.py` (register router)
- Create: `backend/tests/test_feed_dashboard_api.py`

**Interfaces:**
- Consumes: `IngestionRun` (statistics JSONB keys `ingest`/`mapping`/`staging`/`run_plugins`/`quality_check`/`export` — written by `PipelineRunner` via `statistics.update(result.statistics)`), `ExportRun`, `StagingProduct`, `FeedSource`; `enforce_scope_access` dependency (handles 404 for out-of-scope feeds via `feed_source_id` path param).
- Produces: `GET /feed-sources/{id}/dashboard` →

```json
{
  "kpi": {"raw_items": 0, "valid_items": 0, "excluded_items": 0, "last_duration_s": null, "readiness_rate": 1.0},
  "volume_trend": [],
  "stage_funnel": [],
  "quality": {"critical": 0, "warning": 0, "info": 0, "readiness_rate": 1.0},
  "recent_runs": []
}
```

`recent_runs` rows: `{id, status, started_at, duration_s, failed_count}`. Task 7 (frontend hook + types) depends on this exact shape.

Stage-funnel `dropped` derivation per step (from `statistics` JSONB):
- `ingest`: `failed_count` of the run (row errors)
- `mapping`: `statistics.mapping.dropped_unmapped_fields`
- `staging`: `statistics.staging.failed`
- `run_plugins`: `statistics.plugins.dropped`
- `quality_check`: 0 (QC counts findings, doesn't drop)
- `export`: 0

`passed` = run-level `processed_count` for `ingest`; per-step `processed_count` is not persisted separately, so `passed` = previous step's `passed − dropped` cumulatively, seeded from ingest `processed_count`. Simpler and honest: `passed` per stage = `processed_count` of the run minus cumulative drops of earlier stages.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_feed_dashboard_api.py
from datetime import datetime, timedelta, timezone

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


async def _make_feed(factory, http_client, name):
    created = (await http_client.post("/clients", json={"name": name})).json()
    feed = (
        await http_client.post(
            f"/clients/{created['id']}/feed-sources",
            json={"name": f"{name}-feed", "source_format": "wide_tsv"},
        )
    ).json()
    return created["id"], feed["id"]


async def _add_run(factory, feed_id, status="success", processed=100, statistics=None,
                   started_days_ago=0, duration_s=None):
    start = datetime.now(timezone.utc) - timedelta(days=started_days_ago)
    async with factory() as session:
        async with session.begin():
            session.add(IngestionRun(
                feed_source_id=feed_id,
                status=status,
                started_at=start,
                completed_at=(start + timedelta(seconds=duration_s)) if duration_s else None,
                processed_count=processed,
                statistics=statistics or {},
            ))


async def test_dashboard_requires_auth(app_factory):
    app, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await client.get("/feed-sources/1/dashboard")).status_code == 401


async def test_dashboard_404_unknown_feed(app_factory):
    client = await logged_in_client(app_factory)
    assert (await client.get("/feed-sources/999999/dashboard")).status_code == 404


async def test_dashboard_empty_feed(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_id = await _make_feed(factory, client, "Acme")
    resp = await client.get(f"/feed-sources/{feed_id}/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kpi"] == {"raw_items": 0, "valid_items": 0, "excluded_items": 0,
                           "last_duration_s": None, "readiness_rate": 1.0}
    assert body["volume_trend"] == []
    assert body["stage_funnel"] == []
    assert body["quality"] == {"critical": 0, "warning": 0, "info": 0, "readiness_rate": 1.0}
    assert body["recent_runs"] == []


async def test_dashboard_aggregates_run_statistics(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_id = await _make_feed(factory, client, "Acme")

    stats = {
        "ingest": {"row_errors": []},
        "mapping": {"applied": 100, "dropped_unmapped_fields": 4, "shape_mismatches": 0},
        "staging": {"enqueue": 96, "failed": 2},
        "plugins": {"processed": 94, "dropped": 2, "errored": 0},
        "qc": {"products": 94, "critical": 3, "warning": 12, "info": 40},
        "export": {"products": 90, "version": 7, "deduplicated": 0},
    }
    await _add_run(factory, feed_id, processed=100, statistics=stats,
                   started_days_ago=0, duration_s=42)
    async with factory() as session:
        async with session.begin():
            run = (await session.execute(
                __import__("sqlalchemy").select(IngestionRun)
                .where(IngestionRun.feed_source_id == feed_id)
            )).scalars().first()
            session.add(ExportRun(
                feed_source_id=feed_id,
                ingestion_run_id=run.id,
                status="pending_export",
                product_count=90,
                critical_finding_count=3,
                warning_finding_count=12,
                info_finding_count=40,
                started_at=datetime.now(timezone.utc),
            ))
            for pid in ("a", "b", "c"):
                session.add(StagingProduct(
                    feed_source_id=feed_id,
                    ingestion_run_id=run.id,
                    product_id=pid,
                    content_hash="h",
                    config_hash="c",
                    status="active",
                    excluded=False,
                    raw_data={"id": pid},
                ))
            session.add(StagingProduct(
                feed_source_id=feed_id,
                ingestion_run_id=run.id,
                product_id="x",
                content_hash="h",
                config_hash="c",
                status="active",
                excluded=True,
                raw_data={"id": "x"},
            ))

    body = (await client.get(f"/feed-sources/{feed_id}/dashboard")).json()
    kpi = body["kpi"]
    assert kpi["raw_items"] == 100
    assert kpi["valid_items"] == 3
    assert kpi["excluded_items"] == 1
    assert kpi["last_duration_s"] == 42.0
    assert abs(kpi["readiness_rate"] - (1 - 3 / 90)) < 1e-9
    assert body["quality"] == {"critical": 3, "warning": 12, "info": 40,
                               "readiness_rate": 1 - 3 / 90}

    funnel = {row["stage"]: row for row in body["stage_funnel"]}
    assert [row["stage"] for row in body["stage_funnel"]] == [
        "ingest", "mapping", "staging", "run_plugins", "quality_check", "export",
    ]
    assert funnel["ingest"]["passed"] == 100
    assert funnel["ingest"]["dropped"] == 0  # row_errors empty list
    assert funnel["mapping"]["dropped"] == 4
    assert funnel["staging"]["dropped"] == 2
    assert funnel["run_plugins"]["dropped"] == 2
    assert funnel["run_plugins"]["passed"] == 100 - 4 - 2  # cumulative
    assert funnel["export"]["passed"] == 90

    assert len(body["recent_runs"]) == 1
    assert body["recent_runs"][0]["duration_s"] == 42.0

    assert len(body["volume_trend"]) == 1
    today = datetime.now(timezone.utc).date()
    assert body["volume_trend"][0]["date"] == str(today)
    assert body["volume_trend"][0]["raw"] == 100
    assert body["volume_trend"][0]["exportable"] == 90


async def test_dashboard_readiness_zero_products(app_factory):
    app, factory = app_factory
    client = await logged_in_client(app_factory)
    _, feed_id = await _make_feed(factory, client, "Acme")
    async with factory() as session:
        async with session.begin():
            session.add(ExportRun(
                feed_source_id=feed_id,
                status="pending_export",
                product_count=0,
                started_at=datetime.now(timezone.utc),
            ))
    body = (await client.get(f"/feed-sources/{feed_id}/dashboard")).json()
    assert body["kpi"]["readiness_rate"] == 1.0
```

Note: `test_dashboard_aggregates_run_statistics` uses `__import__("sqlalchemy")` inline — replace with a top-level `from sqlalchemy import select` import; the inline form is only to keep this plan block copy-pasteable as one fixture file section.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_feed_dashboard_api.py -x -q`
Expected: FAIL — 404 (route not registered) on every non-auth test.

- [ ] **Step 3: Implement the route**

```python
# backend/app/routes/feed_dashboard.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db.engine import get_db_session
from ..models.export import ExportRun
from ..models.feed_source import FeedSource
from ..models.ingestion import IngestionRun
from ..models.staging import StagingProduct

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


# (stage key in statistics JSONB, dropped-value extractor)
def _dropped_from(statistics: dict, stage: str) -> int:
    if stage == "ingest":
        errors = statistics.get("ingest", {}).get("row_errors")
        return len(errors) if isinstance(errors, list) else 0
    if stage == "mapping":
        return int(statistics.get("mapping", {}).get("dropped_unmapped_fields", 0))
    if stage == "staging":
        return int(statistics.get("staging", {}).get("failed", 0))
    if stage == "run_plugins":
        return int(statistics.get("plugins", {}).get("dropped", 0))
    return 0  # quality_check / export do not drop products


STAGES = ["ingest", "mapping", "staging", "run_plugins", "quality_check", "export"]


@router.get("/feed-sources/{feed_source_id}/dashboard")
async def feed_dashboard(
    feed_source_id: int,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict:
    session = _require_db(db_session)
    feed_source = await session.get(FeedSource, feed_source_id)
    if feed_source is None:
        raise HTTPException(status_code=404, detail="feed source not found")

    valid_and_excluded = (await session.execute(
        select(StagingProduct.excluded, func.count())
        .where(
            StagingProduct.feed_source_id == feed_source_id,
            StagingProduct.status == "active",
        )
        .group_by(StagingProduct.excluded)
    )).all()
    valid_items = sum(count for excluded, count in valid_and_excluded if not excluded)
    excluded_items = sum(count for excluded, count in valid_and_excluded if excluded)

    runs = list((await session.execute(
        select(IngestionRun)
        .where(IngestionRun.feed_source_id == feed_source_id)
        .order_by(IngestionRun.id.desc())
        .limit(10)
    )).scalars())
    latest_run = runs[0] if runs else None

    export_runs = list((await session.execute(
        select(ExportRun)
        .where(ExportRun.feed_source_id == feed_source_id)
        .order_by(ExportRun.id.desc())
        .limit(30)
    )).scalars())
    latest_export = export_runs[0] if export_runs else None

    readiness = 1.0
    if latest_export is not None and latest_export.product_count > 0:
        readiness = 1 - latest_export.critical_finding_count / latest_export.product_count

    # Stage funnel from latest run's statistics JSONB, cumulative passed.
    stage_funnel: list[dict] = []
    if latest_run is not None and latest_run.statistics:
        passed = latest_run.processed_count
        for stage in STAGES:
            if stage == "export":
                passed_out = (
                    latest_export.product_count
                    if latest_export is not None
                    else passed
                )
                stage_funnel.append({"stage": stage, "passed": passed_out, "dropped": 0})
                continue
            dropped = _dropped_from(latest_run.statistics, stage)
            stage_funnel.append({"stage": stage, "passed": passed, "dropped": dropped})
            passed = max(0, passed - dropped)

    # Volume trend: per-day raw (ingestion processed) vs exportable (export count).
    since = datetime.now(timezone.utc) - timedelta(days=30)
    trend_runs = (await session.execute(
        select(
            func.date(IngestionRun.started_at).label("day"),
            func.max(IngestionRun.processed_count),
        )
        .where(
            IngestionRun.feed_source_id == feed_source_id,
            IngestionRun.started_at >= since,
        )
        .group_by("day")
        .order_by("day")
    )).all()
    export_by_day: dict[str, int] = {}
    for row in export_runs:
        if row.started_at >= since:
            key = str(row.started_at.date())
            export_by_day[key] = max(export_by_day.get(key, 0), row.product_count)
    volume_trend = [
        {
            "date": str(day),
            "raw": int(raw or 0),
            "exportable": export_by_day.pop(str(day), 0),
        }
        for day, raw in trend_runs
    ]
    for key in sorted(export_by_day):
        volume_trend.append({"date": key, "raw": 0, "exportable": export_by_day[key]})

    def _duration(run: IngestionRun) -> float | None:
        if run.completed_at is None:
            return None
        return (run.completed_at - run.started_at).total_seconds()

    last_duration = _duration(latest_run) if latest_run is not None else None

    return {
        "kpi": {
            "raw_items": latest_run.processed_count if latest_run is not None else 0,
            "valid_items": valid_items,
            "excluded_items": excluded_items,
            "last_duration_s": last_duration,
            "readiness_rate": readiness,
        },
        "volume_trend": volume_trend,
        "stage_funnel": stage_funnel,
        "quality": {
            "critical": latest_export.critical_finding_count if latest_export else 0,
            "warning": latest_export.warning_finding_count if latest_export else 0,
            "info": latest_export.info_finding_count if latest_export else 0,
            "readiness_rate": readiness,
        },
        "recent_runs": [
            {
                "id": run.id,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "duration_s": _duration(run),
                "failed_count": run.failed_count,
            }
            for run in reversed(runs)
        ],
    }
```

Register in `backend/app/main.py` next to the other feed-scoped routers:

```python
from .routes.feed_dashboard import router as feed_dashboard_router
```

```python
    app.include_router(feed_dashboard_router, dependencies=[Depends(enforce_scope_access)])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_feed_dashboard_api.py -x -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint, typecheck, full backend suite**

Run: `cd backend && uv run ruff check . && uv run mypy . && uv run pytest -n auto -q`
Expected: all clean.

- [ ] **Step 6: Update API docs**

In `backend/docs/api.md`, under `### Dashboard Summary` add the `runs_by_day` line, and add a new section after it:

```markdown
### Feed Dashboard
- `GET /feed-sources/{id}/dashboard` — single aggregate for the per-feed dashboard. Response: `{kpi: {raw_items, valid_items, excluded_items, last_duration_s, readiness_rate}, volume_trend: [{date, raw, exportable}] (30 days, ascending), stage_funnel: [{stage, passed, dropped}] (ingest → mapping → staging → run_plugins → quality_check → export; cumulative passed from the latest run's statistics), quality: {critical, warning, info, readiness_rate}, recent_runs: [{id, status, started_at, duration_s, failed_count}] (last 10, ascending)}. Empty feed → zeroed KPIs, empty arrays, readiness 1.0. 404 unknown feed source.
```

Update the `### Dashboard Summary` line to mention `runs_by_day`:

```markdown
- `GET /dashboard/summary` — aggregated view for dashboard (clients, feed sources, last run status, `runs_by_day`: 14-day `{date, success, error}` counts, ascending)
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/feed_dashboard.py backend/app/main.py backend/tests/test_feed_dashboard_api.py backend/docs/api.md
git commit -m "feat: per-feed dashboard aggregate endpoint"
```

---

### Task 5: Frontend API layer — types, query keys, hook

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/queryKeys.ts`
- Modify: `frontend/src/api/hooks.ts`
- Create: `frontend/src/api/hooks.test.ts` (hook-level test via renderHook + stubFetch)

**Interfaces:**
- Consumes: Task 3's `runs_by_day` shape, Task 4's response shape.
- Produces:
  - `export type RunsByDayRow = { date: string; success: number; error: number }` (add to `DashboardSummary`)
  - `export type FeedDashboardData = { kpi: {...}; volume_trend: {...}[]; stage_funnel: {...}[]; quality: {...}; recent_runs: {...}[] }` (exact fields from Task 4)
  - `queryKeys.feedSource(id).feedDashboard`
  - `export function useFeedDashboard(feedSourceId: number | string)` — used by Task 8.
  - `export function fillChartDates(rows: RunsByDayRow[], days: number): RunsByDayRow[]` — zero-fills missing days, ascending; used by Tasks 6 and 8.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/api/hooks.test.ts
import { describe, expect, it } from 'vitest';
import { fillChartDates } from './hooks';

describe('fillChartDates', () => {
  it('zero-fills missing days between first and last row', () => {
    const rows = [
      { date: '2026-09-01', success: 1, error: 0 },
      { date: '2026-09-04', success: 2, error: 1 },
    ];
    const filled = fillChartDates(rows, 4);
    expect(filled.map((r) => r.date)).toEqual([
      '2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04',
    ]);
    expect(filled[1]).toEqual({ date: '2026-09-02', success: 0, error: 0 });
  });

  it('returns empty array for empty input', () => {
    expect(fillChartDates([], 14)).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/api/hooks.test.ts`
Expected: FAIL — `fillChartDates` not exported.

- [ ] **Step 3: Implement**

In `frontend/src/api/types.ts`, extend `DashboardSummary` and add the new types:

```ts
export type RunsByDayRow = {
  date: string;
  success: number;
  error: number;
};

export type DashboardSummary = {
  counts: {
    clients: number;
    feed_sources: number;
    active_products: number;
    failed_last_exports: number;
  };
  clients: ClientSummary[];
  runs_by_day: RunsByDayRow[];
};

export type FeedDashboardData = {
  kpi: {
    raw_items: number;
    valid_items: number;
    excluded_items: number;
    last_duration_s: number | null;
    readiness_rate: number;
  };
  volume_trend: Array<{ date: string; raw: number; exportable: number }>;
  stage_funnel: Array<{ stage: string; passed: number; dropped: number }>;
  quality: {
    critical: number;
    warning: number;
    info: number;
    readiness_rate: number;
  };
  recent_runs: Array<{
    id: number;
    status: string;
    started_at: string;
    duration_s: number | null;
    failed_count: number;
  }>;
};
```

In `frontend/src/api/queryKeys.ts`, inside the `feedSource: (id: ...)` factory add:

```ts
    feedDashboard: ['feed-source', id, 'feed-dashboard'] as const,
```

In `frontend/src/api/hooks.ts` add (near `useIngestionRuns`):

```ts
export function useFeedDashboard(feedSourceId: number | string) {
  return useQuery({
    queryKey: queryKeys.feedSource(feedSourceId).feedDashboard,
    queryFn: () => apiGet<FeedDashboardData>(`/feed-sources/${feedSourceId}/dashboard`),
    enabled: Boolean(feedSourceId),
  });
}

// Zero-fill missing days so charts show continuous time axis.
export function fillChartDates(
  rows: RunsByDayRow[],
  days: number,
): RunsByDayRow[] {
  if (rows.length === 0) return [];
  const byDate = new Map(rows.map((r) => [r.date, r]));
  const out: RunsByDayRow[] = [];
  const first = new Date(`${rows[0].date}T00:00:00Z`);
  for (let i = 0; i < days; i += 1) {
    const d = new Date(first.getTime() + i * 86_400_000);
    const key = d.toISOString().slice(0, 10);
    out.push(byDate.get(key) ?? { date: key, success: 0, error: 0 });
  }
  return out;
}
```

Import `FeedDashboardData` and `RunsByDayRow` in the types import block of `hooks.ts`.

- [ ] **Step 4: Run tests + typecheck**

Run: `cd frontend && npm run test -- src/api/ && npm run typecheck`
Expected: PASS. Note: existing tests constructing `DashboardSummary` literals (e.g. `DashboardPage.test.tsx`, `AppShell.test.tsx`) will now fail typecheck because `runs_by_day` is missing — add `runs_by_day: []` (or sample rows) to those fixtures in this step. Files to update: `frontend/src/features/dashboard/DashboardPage.test.tsx` (`summary`, `deletedSummary`, `emptySummary`), `frontend/src/app/AppShell.test.tsx` (`summary`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/ frontend/src/features/dashboard/DashboardPage.test.tsx frontend/src/app/AppShell.test.tsx
git commit -m "feat: feed dashboard hook, types, chart date fill helper"
```

---

### Task 6: Global dashboard — fleet charts + clickable feed cards

**Files:**
- Create: `frontend/src/features/dashboard/FleetCharts.tsx`
- Create: `frontend/src/features/dashboard/FleetCharts.test.tsx`
- Modify: `frontend/src/features/dashboard/DashboardPage.tsx`
- Modify: `frontend/src/features/dashboard/FeedSourceCard.tsx`
- Modify: `frontend/src/features/dashboard/DashboardPage.test.tsx` (fixtures already updated in Task 5)

**Interfaces:**
- Consumes: `DashboardSummary.runs_by_day` (Task 5 types), `ChartCard`, `chartColors`, `donutPalette` (Task 2), `fillChartDates` (Task 5).
- Produces: `export function FleetCharts({ summary }: { summary: DashboardSummary })` — renders donut (catalog volume per feed, top 8 + Other) + stacked area (14-day runs). `DashboardPage` renders `<FleetCharts .../>` between the KPI grid and the client accordion. `FeedSourceCard` becomes fully clickable (Paper → `component={Link}` to feed base).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/dashboard/FleetCharts.test.tsx
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../../test/render';
import { FleetCharts } from './FleetCharts';
import type { DashboardSummary } from '../../api/types';

const summary = (runs: DashboardSummary['runs_by_day']): DashboardSummary => ({
  counts: { clients: 1, feed_sources: 2, active_products: 30, failed_last_exports: 0 },
  clients: [
    {
      id: 1, name: 'Acme', status: 'active',
      feed_sources: [
        { id: 2, client_id: 1, name: 'Feed A', source_format: 'xml', item_count: 20,
          last_export_at: null, last_export_status: null, last_run_at: null, last_run_status: null },
        { id: 3, client_id: 1, name: 'Feed B', source_format: 'tsv', item_count: 10,
          last_export_at: null, last_export_status: null, last_run_at: null, last_run_status: null },
      ],
    },
  ],
  runs_by_day: runs,
});

describe('FleetCharts', () => {
  it('renders both chart titles and feed names in donut data', () => {
    render(<FleetCharts summary={summary([{ date: '2026-09-01', success: 3, error: 1 }])} />);
    expect(screen.getByText('Catalog volume by feed')).toBeInTheDocument();
    expect(screen.getByText('Pipeline health (14 days)')).toBeInTheDocument();
  });

  it('renders empty states when no data', () => {
    render(<FleetCharts summary={summary([])} />);
    expect(screen.getAllByText(/nothing here yet/i).length).toBe(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/features/dashboard/FleetCharts.test.tsx`
Expected: FAIL — cannot resolve `./FleetCharts`.

- [ ] **Step 3: Implement FleetCharts**

```tsx
// frontend/src/features/dashboard/FleetCharts.tsx
import { AreaChart, DonutChart } from '@mantine/charts';
import { Grid } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import {
  chartColors,
  donutPalette,
} from '../../components/dashboard/dashboardColors';
import { ChartCard } from '../../components/dashboard/ChartCard';
import { fillChartDates } from '../../api/hooks';
import type { DashboardSummary } from '../../api/types';

const MAX_SLICES = 8;

export function FleetCharts({ summary }: { summary: DashboardSummary }) {
  const { t } = useTranslation('dashboard');

  const feeds = summary.clients.flatMap((client) =>
    client.feed_sources.map((feed) => ({ name: `${client.name} / ${feed.name}`, value: feed.item_count })),
  );
  const sorted = [...feeds].sort((a, b) => b.value - a.value);
  const top = sorted.slice(0, MAX_SLICES);
  const rest = sorted.slice(MAX_SLICES);
  const donutData = [
    ...top.map((feed, i) => ({ ...feed, color: donutPalette[i % donutPalette.length] })),
    ...(rest.length > 0
      ? [{ name: t('charts.other'), value: rest.reduce((sum, f) => sum + f.value, 0), color: chartColors.other }]
      : []),
  ];
  const donutEmpty = donutData.every((slice) => slice.value === 0);

  const trend = fillChartDates(summary.runs_by_day, 14);

  return (
    <Grid>
      <Grid.Col span={{ base: 12, md: 5 }}>
        <ChartCard title={t('charts.volumeTitle')} isEmpty={donutEmpty} emptyMessage={t('charts.volumeEmpty')}>
          <DonutChart
            size={180}
            data={donutData}
            withTooltip
            mx="auto"
          />
        </ChartCard>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 7 }}>
        <ChartCard title={t('charts.healthTitle')} isEmpty={trend.length === 0} emptyMessage={t('charts.healthEmpty')}>
          <AreaChart
            h={220}
            data={trend}
            dataKey="date"
            type="stacked"
            curveType="natural"
            withLegend
            series={[
              { name: 'success', color: chartColors.success },
              { name: 'error', color: chartColors.error },
            ]}
          />
        </ChartCard>
      </Grid.Col>
    </Grid>
  );
}
```

Note: `withLabels` on the donut was dropped — with long `Client / Feed` names the labels overflow; the tooltip carries the names. This deviates from the spec table (spec says `withLabels`) — acceptable simplification, note it in the PR description.

- [ ] **Step 4: Wire into DashboardPage + make FeedSourceCard clickable**

In `DashboardPage.tsx`, after the KPI `SimpleGrid` and before the accordion, insert:

```tsx
      <FleetCharts summary={summary} />
```

and add `import { FleetCharts } from './FleetCharts';`.

In `FeedSourceCard.tsx`, make the whole card a link to the feed dashboard. Change the outer `Paper` to:

```tsx
    <Paper
      withBorder
      p="md"
      component="a"
      role="button"
      tabIndex={0}
      style={{ cursor: 'pointer', display: 'block' }}
      onClick={() => navigate(`/clients/${clientId}/feeds/${feed.id}`)}
      onKeyDown={(event) => {
        if (event.key === 'Enter') navigate(`/clients/${clientId}/feeds/${feed.id}`);
      }}
    >
```

(Keep `Paper` over `component={Link}` because the card also contains `ActionIcon`s whose clicks must not navigate — the explicit `onClick` on the Paper with icon `stopPropagation` is simpler. Add `onClick={(e) => e.stopPropagation()}` to both `ActionIcon`s.)

Also add to `DashboardPage.tsx` an anchor for the sidebar Clients link — wrap the `Accordion` in `<Stack gap="md" id="clients">` or add `id="clients"` to the Accordion via `style`/`__vars` — simplest: `<div id="clients">` around the Accordion block.

- [ ] **Step 5: Add locale keys (en + de)**

`frontend/public/locales/en/dashboard.json` — add:

```json
  "charts": {
    "volumeTitle": "Catalog volume by feed",
    "volumeEmpty": "No staged products yet.",
    "healthTitle": "Pipeline health (14 days)",
    "healthEmpty": "No runs in the last 14 days.",
    "other": "Other"
  },
```

`frontend/public/locales/de/dashboard.json` — add:

```json
  "charts": {
    "volumeTitle": "Katalogvolumen je Feed",
    "volumeEmpty": "Noch keine bereitgestellten Produkte.",
    "healthTitle": "Pipeline-Status (14 Tage)",
    "healthEmpty": "Keine Läufe in den letzten 14 Tagen.",
    "other": "Weitere"
  },
```

- [ ] **Step 6: Run tests + typecheck**

Run: `cd frontend && npm run test -- src/features/dashboard/ && npm run typecheck`
Expected: PASS. If the existing `DashboardPage` test asserts on DOM order/counts around the accordion, extend it: add one test asserting `FleetCharts` titles render and one asserting clicking a `FeedSourceCard` navigates (use `render(<App />)` at `/` then click the feed name, expect location `/clients/1/feeds/2`).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/dashboard/ frontend/public/locales/
git commit -m "feat: fleet charts on global dashboard, clickable feed cards"
```

---

### Task 7: Routing — feed index route + placeholder pages

**Files:**
- Create: `frontend/src/features/systemLogs/SystemLogsPage.tsx`
- Create: `frontend/src/features/globalRules/GlobalRulesPage.tsx`
- Create: `frontend/src/features/systemLogs/SystemLogsPage.test.tsx`
- Create: `frontend/src/features/globalRules/GlobalRulesPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes: `EmptyState` (`components/StateViews`), lazy-page pattern from `router.tsx`.
- Produces:
  - Route `clients/:clientId/feeds/:feedSourceId` (index) → `FeedDashboardPage` (created in Task 8; this task adds the route importing a stub that Task 8 replaces — NO: order swapped, see below).
  - Routes `/logs` → `SystemLogsPage`, `/rules` → `GlobalRulesPage`.

Ordering note: the index route needs `FeedDashboardPage` to exist. To keep every task independently green, this task creates a minimal `FeedDashboardPage` stub (title + empty state) at `frontend/src/features/feedDashboard/FeedDashboardPage.tsx`; Task 8 replaces its body with the full dashboard.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/systemLogs/SystemLogsPage.test.tsx
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../../test/render';
import { SystemLogsPage } from './SystemLogsPage';

describe('SystemLogsPage', () => {
  it('renders the coming-soon empty state', () => {
    render(<SystemLogsPage />);
    expect(screen.getByText(/system logs/i)).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });
});
```

```tsx
// frontend/src/features/globalRules/GlobalRulesPage.test.tsx — identical shape, swap names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- src/features/systemLogs src/features/globalRules`
Expected: FAIL — cannot resolve modules.

- [ ] **Step 3: Implement placeholder pages + FeedDashboardPage stub**

```tsx
// frontend/src/features/systemLogs/SystemLogsPage.tsx
import { Stack, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { EmptyState } from '../../components/StateViews';

export function SystemLogsPage() {
  const { t } = useTranslation('systemLogs');
  return (
    <Stack pt="md">
      <Title order={3}>{t('title')}</Title>
      <EmptyState message={t('comingSoon')} />
    </Stack>
  );
}
```

```tsx
// frontend/src/features/globalRules/GlobalRulesPage.tsx — same shape, ns 'globalRules'
```

```tsx
// frontend/src/features/feedDashboard/FeedDashboardPage.tsx (stub — replaced in Task 8)
import { Stack, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { EmptyState } from '../../components/StateViews';

export function FeedDashboardPage() {
  const { t } = useTranslation('feedDashboard');
  return (
    <Stack pt="md">
      <Title order={3}>{t('title')}</Title>
      <EmptyState />
    </Stack>
  );
}
```

- [ ] **Step 4: Add routes in `router.tsx`**

Add lazy imports:

```tsx
const FeedDashboardPage = lazy(() =>
  import('../features/feedDashboard/FeedDashboardPage').then((m) => ({ default: m.FeedDashboardPage })),
);
const SystemLogsPage = lazy(() =>
  import('../features/systemLogs/SystemLogsPage').then((m) => ({ default: m.SystemLogsPage })),
);
const GlobalRulesPage = lazy(() =>
  import('../features/globalRules/GlobalRulesPage').then((m) => ({ default: m.GlobalRulesPage })),
);
```

Inside the `AppShell` children, before the `setup` route entry:

```tsx
          { path: 'clients/:clientId/feeds/:feedSourceId', element: <FeedDashboardPage /> },
```

And after the admin block:

```tsx
          { path: 'logs', element: <SystemLogsPage /> },
          { path: 'rules', element: <GlobalRulesPage /> },
```

- [ ] **Step 5: Add locale files (en + de)**

Create `frontend/public/locales/en/systemLogs.json`:

```json
{
  "title": "System Logs",
  "comingSoon": "System logs are coming soon."
}
```

Create `frontend/public/locales/en/globalRules.json`:

```json
{
  "title": "Global Rules",
  "comingSoon": "Global rules are coming soon."
}
```

Create `frontend/public/locales/en/feedDashboard.json` (full set — Task 8 uses these keys):

```json
{
  "title": "Feed dashboard",
  "runPipeline": "Run pipeline",
  "editPipeline": "Edit pipeline",
  "copyExportUrl": "Copy export URL",
  "kpi": {
    "rawItems": "Raw items",
    "validItems": "Valid items",
    "excludedItems": "Excluded items",
    "duration": "Processing duration",
    "readiness": "GMC readiness"
  },
  "charts": {
    "volumeTitle": "Volume & pass-through (30 days)",
    "volumeEmpty": "No runs in the last 30 days.",
    "funnelTitle": "Pipeline stage funnel",
    "funnelEmpty": "No run statistics available.",
    "qualityTitle": "Quality distribution",
    "qualityEmpty": "No quality findings yet."
  },
  "runs": {
    "title": "Recent runs",
    "empty": "No runs yet.",
    "duration": "{{seconds}}s"
  },
  "badge": {
    "active": "ACTIVE",
    "target": "Google Merchant Center"
  }
}
```

Create the three matching `de` files (`frontend/public/locales/de/systemLogs.json`, `globalRules.json`, `feedDashboard.json`) with German translations:

`de/systemLogs.json`:
```json
{
  "title": "Systemprotokolle",
  "comingSoon": "Systemprotokolle folgen in Kürze."
}
```

`de/globalRules.json`:
```json
{
  "title": "Globale Regeln",
  "comingSoon": "Globale Regeln folgen in Kürze."
}
```

`de/feedDashboard.json`:
```json
{
  "title": "Feed-Übersicht",
  "runPipeline": "Pipeline starten",
  "editPipeline": "Pipeline bearbeiten",
  "copyExportUrl": "Export-URL kopieren",
  "kpi": {
    "rawItems": "Rohdaten",
    "validItems": "Gültige Produkte",
    "excludedItems": "Ausgeschlossene Produkte",
    "duration": "Verarbeitungsdauer",
    "readiness": "GMC-Bereitschaft"
  },
  "charts": {
    "volumeTitle": "Volumen & Durchlauf (30 Tage)",
    "volumeEmpty": "Keine Läufe in den letzten 30 Tagen.",
    "funnelTitle": "Pipeline-Stufen",
    "funnelEmpty": "Keine Lauf-Statistiken vorhanden.",
    "qualityTitle": "Qualitätsverteilung",
    "qualityEmpty": "Noch keine Qualitätsbefunde."
  },
  "runs": {
    "title": "Letzte Läufe",
    "empty": "Noch keine Läufe.",
    "duration": "{{seconds}}s"
  },
  "badge": {
    "active": "AKTIV",
    "target": "Google Merchant Center"
  }
}
```

- [ ] **Step 6: Run tests + typecheck**

Run: `cd frontend && npm run test && npm run typecheck`
Expected: PASS. Add a router test if `router.test.tsx` covers route tables — check `frontend/src/app/router.test.tsx` and extend it with three cases: `/clients/1/feeds/2` renders FeedDashboardPage title, `/logs` and `/rules` render their titles.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/systemLogs frontend/src/features/globalRules frontend/src/features/feedDashboard frontend/src/app/router.tsx frontend/src/app/router.test.tsx frontend/public/locales/
git commit -m "feat: feed index route, system logs and global rules placeholder pages"
```

---

### Task 8: FeedDashboardPage — full implementation

**Files:**
- Modify: `frontend/src/features/feedDashboard/FeedDashboardPage.tsx` (replace stub)
- Create: `frontend/src/features/feedDashboard/FeedDashboardPage.test.tsx`
- Create: `frontend/src/features/feedDashboard/RecentRunsTable.tsx`
- Create: `frontend/src/features/feedDashboard/RecentRunsTable.test.tsx`

**Interfaces:**
- Consumes: `useFeedDashboard` (Task 5), `useFeedSource`, `useDashboardSummary`, `useTriggerRun`, `withLoadingNotification` (`app/notifications`), `StatCard` (Task 1), `ChartCard` + `chartColors` (Task 2), `CopyField` (`components/CopyField`), `fillChartDates` (Task 5 — for volume_trend zero-fill, reusing the same helper with a widened row type), locale keys from Task 7.
- Produces: complete `FeedDashboardPage` at the feed index route.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/feedDashboard/RecentRunsTable.test.tsx
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../../test/render';
import { RecentRunsTable } from './RecentRunsTable';
import type { FeedDashboardData } from '../../api/types';

const runs: FeedDashboardData['recent_runs'] = [
  { id: 2, status: 'success', started_at: '2026-09-12T10:00:00Z', duration_s: 42.5, failed_count: 0 },
  { id: 1, status: 'error', started_at: '2026-09-11T10:00:00Z', duration_s: 12, failed_count: 3 },
];

describe('RecentRunsTable', () => {
  it('renders run rows with status, duration, failed count', () => {
    render(<RecentRunsTable runs={runs} />);
    expect(screen.getByTestId('run-row-2')).toBeInTheDocument();
    expect(screen.getByTestId('run-row-1')).toBeInTheDocument();
    expect(screen.getByText('42.5s')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });
});
```

```tsx
// frontend/src/features/feedDashboard/FeedDashboardPage.test.tsx
import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import App from '../../App';
import { queryClient } from '../../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const dashboardBody = {
  kpi: { raw_items: 1000, valid_items: 900, excluded_items: 50, last_duration_s: 42.5, readiness_rate: 0.94 },
  volume_trend: [{ date: '2026-09-12', raw: 1000, exportable: 900 }],
  stage_funnel: [
    { stage: 'ingest', passed: 1000, dropped: 5 },
    { stage: 'mapping', passed: 1000, dropped: 4 },
  ],
  quality: { critical: 3, warning: 12, info: 40, readiness_rate: 0.94 },
  recent_runs: [
    { id: 9, status: 'success', started_at: '2026-09-12T10:00:00Z', duration_s: 42.5, failed_count: 0 },
  ],
};

const summaryBody = {
  counts: { clients: 1, feed_sources: 1, active_products: 900, failed_last_exports: 0 },
  clients: [{
    id: 1, name: 'Acme', status: 'active',
    feed_sources: [{
      id: 2, client_id: 1, name: 'Main Feed', source_format: 'tsv', item_count: 900,
      last_export_at: null, last_export_status: null, last_run_at: null, last_run_status: null,
    }],
  }],
  runs_by_day: [],
};

const feedBody = {
  id: 2, client_id: 1, name: 'Main Feed', source_format: 'tsv',
  cron_expression: null, target_country: 'DE', target_language: 'de', currency: 'EUR',
  source_url: null, feed_type: 'product', history_retention_count: 10,
  volume_drop_threshold_pct: 30, configuration: {}, export_url: 'https://x/export/tok.xml',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};

beforeEach(() => {
  queryClient.clear();
  window.history.replaceState({}, '', '/clients/1/feeds/2');
  stubFetch((url) => {
    if (url === '/auth/me') return jsonResponse({ username: 'operator' });
    if (url === '/dashboard/summary') return jsonResponse(summaryBody);
    if (url === '/plugins') return jsonResponse([]);
    if (url === '/feed-sources/2/dashboard') return jsonResponse(dashboardBody);
    if (url === '/feed-sources/2') return jsonResponse(feedBody);
    return jsonResponse({});
  });
});

describe('FeedDashboardPage', () => {
  it('renders header with breadcrumb, badges, actions, KPIs and chart titles', async () => {
    render(<App />);
    expect(await screen.findByText('Main Feed')).toBeInTheDocument();
    expect(screen.getByText('TSV')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /run pipeline/i })).toBeInTheDocument();
    expect(screen.getByText('Raw items')).toBeInTheDocument();
    expect(screen.getByText('900')).toBeInTheDocument();
    expect(screen.getByText('Volume & pass-through (30 days)')).toBeInTheDocument();
    expect(screen.getByText('Pipeline stage funnel')).toBeInTheDocument();
    expect(screen.getByText('Quality distribution')).toBeInTheDocument();
    expect(screen.getByText('Recent runs')).toBeInTheDocument();
  });

  it('renders empty chart states when feed has no data', async () => {
    stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(summaryBody);
      if (url === '/plugins') return jsonResponse([]);
      if (url === '/feed-sources/2/dashboard') {
        return jsonResponse({
          kpi: { raw_items: 0, valid_items: 0, excluded_items: 0, last_duration_s: null, readiness_rate: 1.0 },
          volume_trend: [], stage_funnel: [],
          quality: { critical: 0, warning: 0, info: 0, readiness_rate: 1.0 },
          recent_runs: [],
        });
      }
      if (url === '/feed-sources/2') return jsonResponse(feedBody);
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByText('Raw items')).toBeInTheDocument();
    expect(screen.getAllByText(/no runs|nothing here|no quality|no run statistics/i).length).toBeGreaterThanOrEqual(3);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- src/features/feedDashboard/`
Expected: FAIL — stub page has no KPIs/charts.

- [ ] **Step 3: Implement RecentRunsTable**

```tsx
// frontend/src/features/feedDashboard/RecentRunsTable.tsx
import { Badge, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import type { FeedDashboardData } from '../../api/types';

const STATUS_COLOR: Record<string, string> = {
  success: 'green',
  error: 'red',
  running: 'blue',
  pending: 'gray',
  skipped: 'gray',
};

export function RecentRunsTable({ runs }: { runs: FeedDashboardData['recent_runs'] }) {
  const { t, i18n } = useTranslation('feedDashboard');
  if (runs.length === 0) {
    return <Text c="dimmed" size="sm">{t('runs.empty')}</Text>;
  }
  return (
    <Table striped data-testid="recent-runs-table">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('runs.started')}</Table.Th>
          <Table.Th>{t('runs.status')}</Table.Th>
          <Table.Th>{t('runs.duration')}</Table.Th>
          <Table.Th>{t('runs.failed')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {runs.map((run) => (
          <Table.Tr key={run.id} data-testid={`run-row-${run.id}`}>
            <Table.Td>
              <Text size="sm">{dayjs(run.started_at).locale(i18n.language).format('L LTS')}</Text>
            </Table.Td>
            <Table.Td>
              <Badge color={STATUS_COLOR[run.status] ?? 'gray'}>{run.status}</Badge>
            </Table.Td>
            <Table.Td>
              {run.duration_s !== null ? t('runs.duration', { seconds: run.duration_s }) : '—'}
            </Table.Td>
            <Table.Td>{run.failed_count}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
```

Add the missing keys to `feedDashboard.json` (en + de): `"runs": { ..., "started": "Started", "status": "Status", "failed": "Failed" }` — merge into the existing `runs` object from Task 7:

en `runs`:
```json
  "runs": {
    "title": "Recent runs",
    "empty": "No runs yet.",
    "duration": "{{seconds}}s",
    "started": "Started",
    "status": "Status",
    "failed": "Failed"
  },
```

de `runs`:
```json
  "runs": {
    "title": "Letzte Läufe",
    "empty": "Noch keine Läufe.",
    "duration": "{{seconds}}s",
    "started": "Start",
    "status": "Status",
    "failed": "Fehler"
  },
```

- [ ] **Step 4: Implement FeedDashboardPage (replace stub)**

```tsx
// frontend/src/features/feedDashboard/FeedDashboardPage.tsx
import { AreaChart, BarChart, DonutChart } from '@mantine/charts';
import {
  Anchor,
  Badge,
  Breadcrumbs,
  Button,
  CopyButton,
  Group,
  SimpleGrid,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { IconPlayerPlay, IconSettings } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';
import {
  useDashboardSummary,
  useFeedDashboard,
  useFeedSource,
  useTriggerRun,
} from '../../api/hooks';
import { withLoadingNotification } from '../../app/notifications';
import { ChartCard } from '../../components/dashboard/ChartCard';
import { StatCard } from '../../components/dashboard/StatCard';
import { chartColors } from '../../components/dashboard/dashboardColors';
import { EmptyState, ErrorState, LoadingState } from '../../components/StateViews';

function fillVolumeTrend(rows: FeedDashboardData['volume_trend'], days = 30): FeedDashboardData['volume_trend'] {
  if (rows.length === 0) return [];
  const byDate = new Map(rows.map((r) => [r.date, r]));
  const out: FeedDashboardData['volume_trend'] = [];
  const first = new Date(`${rows[0].date}T00:00:00Z`);
  for (let i = 0; i < days; i += 1) {
    const key = new Date(first.getTime() + i * 86_400_000).toISOString().slice(0, 10);
    out.push(byDate.get(key) ?? { date: key, raw: 0, exportable: 0 });
  }
  return out;
}

export function FeedDashboardPage() {
  const { t } = useTranslation('feedDashboard');
  const { t: tMonitoring } = useTranslation('monitoring');
  const { clientId, feedSourceId } = useParams();
  const id = feedSourceId ?? '';

  const dashboardQuery = useFeedDashboard(id);
  const feedQuery = useFeedSource(id);
  const summaryQuery = useDashboardSummary();
  const triggerRun = useTriggerRun(id);

  if (dashboardQuery.isPending) return <LoadingState />;
  if (dashboardQuery.isError) {
    return <ErrorState onRetry={() => void dashboardQuery.refetch()} />;
  }

  const data = dashboardQuery.data;
  const feed = feedQuery.data;
  const client = summaryQuery.data?.clients?.find((c) => String(c.id) === clientId);
  const feedName = feed?.name ?? client?.feed_sources?.find((f) => String(f.id) === id)?.name ?? id;
  const readinessPct = Math.round(data.kpi.readiness_rate * 100);

  function handleRun() {
    void withLoadingNotification(
      'feed-dashboard-trigger',
      tMonitoring('runs.triggerRunning'),
      () => triggerRun.mutateAsync(),
      tMonitoring('runs.triggerSuccess'),
      tMonitoring('runs.triggerFailed'),
    ).catch(() => undefined);
  }

  return (
    <Stack gap="md" pt="md">
      <Group justify="space-between" wrap="nowrap">
        <Stack gap={4}>
          <Breadcrumbs>
            <Anchor component={Link} to="/" size="sm" c="dimmed">
              {client?.name ?? t('breadcrumbClients')}
            </Anchor>
            <Text size="sm" fw={500}>{feedName}</Text>
          </Breadcrumbs>
          <Group gap="xs">
            <Badge variant="light">{(feed?.source_format ?? '').toUpperCase()}</Badge>
            <Badge variant="light" color="green">{t('badge.active')}</Badge>
            <Badge variant="light" color="gray">{t('badge.target')}</Badge>
          </Group>
        </Stack>
        <Group gap="xs" wrap="nowrap">
          <Button
            leftSection={<IconPlayerPlay size={16} />}
            onClick={handleRun}
            loading={triggerRun.isPending}
          >
            {t('runPipeline')}
          </Button>
          <Button
            variant="light"
            leftSection={<IconSettings size={16} />}
            component={Link}
            to={`/clients/${clientId}/feeds/${id}/pipeline`}
          >
            {t('editPipeline')}
          </Button>
          {feed?.export_url ? (
            <CopyButton value={feed.export_url} timeout={2000}>
              {({ copied, copy }) => (
                <Tooltip label={copied ? tMonitoring('runs.triggerSuccess') : t('copyExportUrl')}>
                  <Button variant="light" color={copied ? 'teal' : undefined} onClick={copy}>
                    {t('copyExportUrl')}
                  </Button>
                </Tooltip>
              )}
            </CopyButton>
          ) : null}
        </Group>
      </Group>

      <SimpleGrid cols={{ base: 1, xs: 2, md: 5 }}>
        <StatCard label={t('kpi.rawItems')} value={data.kpi.raw_items} />
        <StatCard label={t('kpi.validItems')} value={data.kpi.valid_items} />
        <StatCard
          label={t('kpi.excludedItems')}
          value={data.kpi.excluded_items}
          variant={data.kpi.excluded_items > 0 ? 'warning' : 'neutral'}
        />
        <StatCard label={t('kpi.duration')} value={data.kpi.last_duration_s ?? 0} />
        <StatCard
          label={t('kpi.readiness')}
          value={readinessPct}
          variant={readinessPct < 90 ? 'critical' : 'neutral'}
        />
      </SimpleGrid>

      <ChartCard title={t('charts.volumeTitle')} isEmpty={data.volume_trend.length === 0} emptyMessage={t('charts.volumeEmpty')}>
        <AreaChart
          h={240}
          data={fillVolumeTrend(data.volume_trend)}
          dataKey="date"
          curveType="natural"
          withLegend
          series={[
            { name: 'raw', color: chartColors.raw },
            { name: 'exportable', color: chartColors.exportable },
          ]}
        />
      </ChartCard>

      <ChartCard title={t('charts.funnelTitle')} isEmpty={data.stage_funnel.length === 0} emptyMessage={t('charts.funnelEmpty')}>
        <BarChart
          h={200}
          orientation="horizontal"
          type="stacked"
          data={data.stage_funnel}
          dataKey="stage"
          series={[
            { name: 'passed', color: chartColors.passed },
            { name: 'dropped', color: chartColors.dropped },
          ]}
        />
      </ChartCard>

      <ChartCard title={t('charts.qualityTitle')} isEmpty={data.quality.critical + data.quality.warning + data.quality.info === 0} emptyMessage={t('charts.qualityEmpty')}>
        <DonutChart
          size={180}
          chartLabel={`${readinessPct}%`}
          data={[
            { name: tMonitoring('severity.critical'), value: data.quality.critical, color: chartColors.error },
            { name: tMonitoring('severity.warning'), value: data.quality.warning, color: chartColors.warning },
            { name: tMonitoring('severity.info'), value: data.quality.info, color: chartColors.info },
          ]}
          withTooltip
          mx="auto"
        />
      </ChartCard>

      <Stack gap="xs">
        <Title order={5}>{t('runs.title')}</Title>
        <RecentRunsTable runs={data.recent_runs} />
      </Stack>
    </Stack>
  );
}
```

Notes:
- `fillVolumeTrend` is local (not the shared `fillChartDates`) because the row type differs (`raw`/`exportable` vs `success`/`error`); the shared helper stays for the fleet chart. If you prefer one generic, widen `fillChartDates` to `fillChartDates<T extends { date: string }>(rows: T[], days: number, zero: (date: string) => T)` — do that only if both call sites read cleanly; otherwise keep the local variant.
- Add `"breadcrumbClients": "Clients"` (en) / `"breadcrumbClients": "Mandanten"` (de) to `feedDashboard.json`.
- Duration StatCard shows seconds as a count — acceptable (label says duration; `last_duration_s` null → 0). If you want the unit, change StatCard usage to a plain `Paper` or extend StatCard with `suffix` prop — extending is the smaller diff: add optional `suffix?: string` rendered after the formatted number, use `suffix="s"`.
- The `CopyButton` tooltip success label reuses a monitoring string awkwardly — add `"copied": "Copied"` to `feedDashboard.json` (en) / `"kopiert"` style (de: `"Kopiert"`) and use it.

- [ ] **Step 5: Run tests + typecheck**

Run: `cd frontend && npm run test -- src/features/feedDashboard/ && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/feedDashboard/ frontend/public/locales/
git commit -m "feat: full feed dashboard page with charts and recent runs"
```

---

### Task 9: AppShell — scope-swapped sidebar + header reset

**Files:**
- Modify: `frontend/src/app/AppShell.tsx`
- Modify: `frontend/src/app/AppShell.test.tsx`

**Interfaces:**
- Consumes: routes from Task 7 (`/logs`, `/rules`, feed index). Locale keys added in this task.
- Produces: sidebar behavior — global scope shows `Fleet Overview` (/), `Clients` (/#clients), `System Logs` (/logs), `Global Rules` (/rules), admin item; feed scope shows `Dashboard` (feedBase, exact match), Setup, plugins, Products, Pipeline, Monitoring, Export. No disabled placeholders. Header breadcrumb gains "All clients" reset menu item; area fallback changes from `'setup'` to `''`.

- [ ] **Step 1: Update the failing tests first**

In `AppShell.test.tsx`, replace the test `disables feed-scoped nav items until a feed source is selected` with:

```tsx
  it('hides feed-scoped nav items and shows global items outside a feed context', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: 'Dashboard' });
    expect(screen.queryByText('Setup')).not.toBeInTheDocument();
    expect(screen.queryByText('Products')).not.toBeInTheDocument();
    expect(screen.queryByText('Select a feed source first')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /fleet overview/i })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: /system logs/i })).toHaveAttribute('href', '/logs');
    expect(screen.getByRole('link', { name: /global rules/i })).toHaveAttribute('href', '/rules');
  });

  it('shows the Dashboard nav item with exact feed base href in feed scope', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    expect(await screen.findByRole('link', { name: /^dashboard$/i })).toHaveAttribute(
      'href',
      '/clients/1/feeds/2',
    );
  });
```

Add a test for the header reset:

```tsx
  it('offers an all-clients reset in the breadcrumb client menu', async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    await screen.findByText('Main Feed');
    await user.click(screen.getByRole('button', { name: 'Select feed' }));
    // "All clients" lives in the client menu; the feed menu is the visible one —
    // the reset is placed as the first item of the FEED dropdown instead:
    expect(await screen.findByRole('menuitem', { name: /all clients/i })).toHaveAttribute('href', '/');
  });
```

Design adjustment (smaller diff, same UX): put the "All clients" reset as the **first item of the existing feed dropdown** rather than a new client-level menu — one Menu change instead of two nested menus.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- src/app/AppShell.test.tsx`
Expected: FAIL — global items missing, disabled placeholders still rendered.

- [ ] **Step 3: Implement**

In `AppShell.tsx`:

1. `FeedBreadcrumb` — change the area fallback:

```tsx
  const area =
    /^\/clients\/[^/]+\/feeds\/[^/]+\/([^/?]+)/.exec(location.pathname)?.[1] ?? '';
```

and in the dropdown, prepend the reset item:

```tsx
        <Menu.Dropdown>
          <Menu.Item component={Link} to="/">{t('breadcrumbs.allClients')}</Menu.Item>
          <Menu.Divider />
          {(client?.feed_sources ?? []).map((entry) => (
            <Menu.Item
              key={entry.id}
              component={Link}
              to={`/clients/${clientId}/feeds/${entry.id}/${area}${location.search}`}
            >
              {entry.name}
            </Menu.Item>
          ))}
        </Menu.Dropdown>
```

Note: with `area = ''` the feed links become `/clients/1/feeds/3/` — trailing slash. Use `` to={`/clients/${clientId}/feeds/${entry.id}${area ? `/${area}` : ''}${location.search}`} `` instead to keep clean URLs.

2. Sidebar — replace the `feedScoped` array + rendering. New structure:

```tsx
  const globalNav = [
    { to: '/', label: t('nav.fleetOverview'), icon: IconDashboard, exact: true },
    { to: '/#clients', label: t('nav.clients'), icon: null },
    { to: '/logs', label: t('nav.systemLogs'), icon: null },
    { to: '/rules', label: t('nav.globalRules'), icon: null },
  ];
```

Import `IconUsers`, `IconListDetails`, `IconGavel` (or similar tabler icons) for the three new items. Render:

```tsx
        <Stack gap={4}>
          {feedBase ? (
            <>
              <NavLink
                component={Link}
                to={feedBase}
                label={t('nav.dashboard')}
                leftSection={<IconDashboard size={16} />}
                active={location.pathname === feedBase}
                variant={location.pathname === feedBase ? 'light' : undefined}
                color={location.pathname === feedBase ? 'blue' : undefined}
                onClick={close}
              />
              {feedScoped.map((item) => (
                <NavLink
                  key={item.label}
                  component={Link}
                  to={item.to}
                  label={item.label}
                  leftSection={<item.icon size={16} />}
                  active={isActive(item.to)}
                  variant={isActive(item.to) ? 'light' : undefined}
                  color={isActive(item.to) ? 'blue' : undefined}
                  onClick={close}
                />
              ))}
            </>
          ) : (
            <>
              {globalNav.map((item) => (
                <NavLink
                  key={item.label}
                  component={Link}
                  to={item.to}
                  label={item.label}
                  leftSection={item.icon ? <item.icon size={16} /> : null}
                  active={item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to)}
                  variant="subtle"
                  onClick={close}
                />
              ))}
              {session?.role === 'admin' && (
                <NavLink
                  component={Link}
                  to="/admin"
                  label={t('nav.admin')}
                  leftSection={<IconShieldCog size={16} />}
                  active={isActive('/admin')}
                  variant={isActive('/admin') ? 'light' : undefined}
                  color={isActive('/admin') ? 'blue' : undefined}
                  onClick={close}
                />
              )}
            </>
          )}
        </Stack>
```

`feedScoped` drops its `to: null` cases — in feed scope `feedBase` is always non-null, so type it as `{ to: string; label: string; icon: ComponentType<{ size?: number }> }[]` and delete the disabled-placeholder branch and the `selectFeedSourceHint` usage.

3. Locale keys — `frontend/public/locales/en/common.json` inside `"nav"`:

```json
    "fleetOverview": "Fleet Overview",
    "clients": "Clients",
    "systemLogs": "System Logs",
    "globalRules": "Global Rules"
```

`frontend/public/locales/de/common.json` `"nav"`:

```json
    "fleetOverview": "Flottenübersicht",
    "clients": "Mandanten",
    "systemLogs": "Systemprotokolle",
    "globalRules": "Globale Regeln"
```

And `"breadcrumbs"` in both: en `"allClients": "All clients"`, de `"allClients": "Alle Mandanten"`.

- [ ] **Step 4: Run tests + typecheck**

Run: `cd frontend && npm run test -- src/app/ && npm run typecheck`
Expected: PASS — including the existing tests `renders navigation with plugin entries after Setup in feed context`, `shows no plugin entries outside a feed context`, `keeps the current area when switching feeds` (area regex now yields `products` unchanged for that URL — still passes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/AppShell.tsx frontend/src/app/AppShell.test.tsx frontend/public/locales/en/common.json frontend/public/locales/de/common.json
git commit -m "feat: scope-swapped sidebar and all-clients reset in header"
```

---

### Task 10: Docs update + full verification

**Files:**
- Modify: `frontend/docs/architecture.md` (routing tree + shared dashboard layer)
- Modify: `backend/docs/api.md` (already updated in Task 4 — verify only)

**Interfaces:**
- Consumes: all previous tasks.
- Produces: docs matching shipped behavior.

- [ ] **Step 1: Update `frontend/docs/architecture.md`**

In the routing tree, add under the AppShell block:

```
    ├── /clients/:clientId/feeds/:feedSourceId          → FeedDashboardPage (feed index)
    ├── /logs                               → SystemLogsPage (placeholder)
    ├── /rules                              → GlobalRulesPage (placeholder)
```

Add a `### Shared Dashboard Primitives (src/components/dashboard/)` section under Key Components:

```markdown
### Shared Dashboard Primitives (`src/components/dashboard/`)
- `StatCard` — KPI card with number formatting and neutral/warning/critical variants; consumed by both the fleet dashboard and the feed dashboard
- `ChartCard` — Paper + title + structural empty-state branch; all dashboard charts render inside it
- `dashboardColors` — semantic series colors (success/error/warning/info/raw/exportable/passed/dropped) and the 8-color donut palette; single source so fleet and feed charts cannot drift
```

Update the sidebar/scope description if the doc mentions the disabled-placeholder behavior (grep for "Select a feed source" in `frontend/docs/`).

- [ ] **Step 2: Verify backend docs**

`backend/docs/api.md` was updated in Task 4. Grep for `feed-sources/{id}/dashboard` and `runs_by_day` to confirm both present.

- [ ] **Step 3: Full verification**

Run: `cd backend && uv run ruff check . && uv run mypy . && uv run pytest -n auto -q`
Expected: clean, all pass.

Run: `cd frontend && npm run test && npm run typecheck && npm run build`
Expected: clean, all pass, build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/docs/architecture.md backend/docs/api.md
git commit -m "docs: dual-scope dashboards routing and endpoints"
```

---

## Self-Review Results

- **Spec coverage:** routing index (T7), sidebar swap (T9), header switcher + reset (T9), fleet donut + area (T6), feed KPIs/volume/funnel/quality/recent runs (T8), backend aggregates (T3, T4), shared layer first (T1, T2), docs (T4, T10), i18n en+de (T6, T7, T8, T9). Gap check: `withLabels` on fleet donut intentionally dropped (overflow with long names — noted in T6); `Clients` sidebar anchor `/#clients` implemented in T6 Step 4.
- **Placeholder scan:** no TBD/TODO; every code step has full code; the two inline "note" deviations (donut labels, all-clients menu placement) carry explicit rationale and test coverage.
- **Type consistency:** `FeedDashboardData` fields match between T4 response, T5 types, T8 page. `fillChartDates` used by T6 only; volume fill is local to T8 (documented decision). `feedSourceId` param name consistent everywhere. `StatCard` props in T1 match T6/T8 usage (T8 uses optional `suffix` — flagged in T8 notes to add in the same task).
