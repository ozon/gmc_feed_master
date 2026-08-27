# M8 XML Writer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the no-op `ExportStep` with a registry-driven GMC XML writer: versioned (deduped by file_hash), atomically published, fetchable via a per-feed-source token URL, with field-based diff and append-only rollback.

**Architecture:** Layered `app/export/` package — pure `renderer` (canonical products → RSS/g: XML bytes), filesystem `store` (atomic temp+`os.replace` writes, version/published layout), DB `service` (version allocation under `SELECT ... FOR UPDATE`, dedupe by SHA-256 `file_hash`, ExportRun wiring, retention prune, rollback, diff). `ExportStep` is a thin caller; history/diff/rollback/public-fetch routes reuse the same service. Design doc: `docs/superpowers/specs/2026-08-27-m8-xml-writer-design.md`.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2 async (asyncpg), Alembic, pytest/pytest-asyncio against real PostgreSQL (pytest-postgresql). No new dependencies — stdlib only (`xml.sax.saxutils`, `hashlib`, `secrets`, `io`).

## Global Constraints

- Atomic publish only: temp file in the same directory + `os.replace()` (spec §2). Never write the published file in place.
- Removed/excluded products are omitted from the XML (snapshot semantics, spec §2/§4). Export-bound set = staging `status='active'` AND `excluded=false`, value = `processed_data` falling back to `raw_data` — the exact same set QC evaluates.
- QC never blocks the export (spec §7). The writer runs whenever QC finishes.
- Dedupe (owner decision 2026-08-27): a run whose rendered bytes have the same SHA-256 `file_hash` as the latest `ExportVersion` creates NO version row/file and skips the retention prune; its ExportRun finalizes `completed` pointing at the existing latest version; if the published file is missing on disk it is restored. Rollback is exempt and always creates a version.
- Rollback is append-only: new version (`source='rollback'`, `source_version_id` set) + new ExportRun (`status='rollback'`, finding counts 0, `ingestion_run_id=NULL`) (spec §2/§8).
- Retention: newest `feed_sources.history_retention_count` versions kept (default 30); older rows AND files pruned; applies to rollback versions too.
- Public endpoint `GET /export/{token}.xml` is unauthenticated, no Basic Auth; token rotation invalidates the old URL immediately (spec §2/§8). The token must never appear in this app's own log output.
- Pass-through fidelity: nested structures no plugin touches (`shipping`/`tax`) reach the XML unchanged (spec §5.5).
- Element order, repetition, and the `g:` namespace are registry-driven (spec §5.6). Unknown keys (incl. `_category_provenance`) and `export_status=non_exportable` attributes are never emitted. Empty elements are stripped from repeated fields before export (spec §5.7).
- Backend commands run from `backend/` with `uv run ...`. Async tests are marked `@pytest.mark.asyncio` (`asyncio_mode` is not auto). PostgreSQL-backed tests use the `isolated_database_url` fixture from `tests/conftest.py` (requires `TEST_DATABASE_URL` and the Compose PostgreSQL running).
- TDD: write the failing test → run it red → minimal implementation → green → commit per task. No code comments unless a non-obvious decision needs one.
- Plugin contract suite (`tests/test_plugin_contract.py`) must stay green; this milestone touches no plugin host code.

## File map

| File | Responsibility |
|---|---|
| `backend/app/config.py` | add `export_dir`, `public_base_url` settings |
| `backend/alembic/versions/20260828_0001_m8_export_versioning.py` | feed_type, export_token (+backfill, unique), history_retention_count; export_versions product_count/source/source_version_id; export_runs.export_version_id FK → SET NULL |
| `backend/app/models/feed_source.py` | new columns on the model |
| `backend/app/models/export.py` | new columns on ExportVersion |
| `backend/app/export/__init__.py` | package exports |
| `backend/app/export/renderer.py` | `ChannelMetadata`, `render_feed` |
| `backend/app/export/store.py` | `ExportFileStore` (paths, atomic writes, read, delete) |
| `backend/app/export/service.py` | `generate_export_token`, `channel_metadata_for`, `ExportOutcome`, `ExportService` |
| `backend/app/staging/persistence.py` | add `load_export_bound` shared helper |
| `backend/app/qc/persistence.py` | ExportRun status `pending_export` |
| `backend/app/pipeline/steps.py` | real `ExportStep`; `QualityCheckStep` uses shared helper; `default_steps` gains `export_dir`/`public_base_url` |
| `backend/app/main.py` | pass settings into `default_steps`; include new routers |
| `backend/app/schemas/clients.py` | FeedSourceOut gains feed_type/history_retention_count/export_url; FeedSourceUpdate gains history_retention_count |
| `backend/app/schemas/export.py` | ExportVersionOut, diff response models |
| `backend/app/routes/clients.py` | token generation on create, rotation endpoint, export_url in responses, file cleanup on delete |
| `backend/app/routes/export_public.py` | `GET /export/{token}.xml` |
| `backend/app/routes/export_history.py` | history list, diff, rollback |
| `backend/app/routes/__init__.py` | export new routers |
| `.gitignore` | ignore `exports/` |
| `backend/tests/test_export_renderer.py` … `test_m8_acceptance.py` | new test modules per task |

---

### Task 1: Settings, migration, models

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/alembic/versions/20260828_0001_m8_export_versioning.py`
- Modify: `backend/app/models/feed_source.py`
- Modify: `backend/app/models/export.py`
- Modify: `.gitignore`
- Test: `backend/tests/test_m8_migration.py`, `backend/tests/test_models.py`

**Interfaces:**
- Consumes: existing migration chain (head `20260827_0002`), `Base` from `app.db.base`
- Produces: `Settings.export_dir: str`, `Settings.public_base_url: str`; columns `feed_sources.feed_type`, `feed_sources.export_token`, `feed_sources.history_retention_count`, `export_versions.product_count`, `export_versions.source`, `export_versions.source_version_id`

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/test_m8_migration.py`:

```python
import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


async def _columns(url, table):
    engine = create_async_engine(url, pool_size=2, max_overflow=0)

    def _run(connection):
        inspector = inspect(connection)
        return {c["name"] for c in inspector.get_columns(table)}

    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_run)
    finally:
        await engine.dispose()


async def test_upgrade_adds_m8_columns(isolated_database_url):
    feed_cols = await _columns(isolated_database_url, "feed_sources")
    assert "feed_type" in feed_cols
    assert "export_token" in feed_cols
    assert "history_retention_count" in feed_cols

    version_cols = await _columns(isolated_database_url, "export_versions")
    assert "product_count" in version_cols
    assert "source" in version_cols
    assert "source_version_id" in version_cols


async def test_export_token_backfilled_unique(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)

    def _run(connection):
        inspector = inspect(connection)
        indexes = inspector.get_indexes("feed_sources")
        return indexes

    try:
        async with engine.connect() as connection:
            indexes = await connection.run_sync(_run)
    finally:
        await engine.dispose()

    assert any(
        idx["unique"] and idx["column_names"] == ["export_token"] for idx in indexes
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_m8_migration.py -v` (from `backend/`)
Expected: FAIL — `test_upgrade_adds_m8_columns` assertion error (`feed_type` missing; the template DB is built by alembic, so the new columns do not exist yet).

- [ ] **Step 3: Write the migration**

Create `backend/alembic/versions/20260828_0001_m8_export_versioning.py`:

```python
"""M8 XML writer: export tokens, retention, version bookkeeping

Revision ID: 20260828_0001
Revises: 20260827_0002
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '20260828_0001'
down_revision: Union[str, Sequence[str], None] = '20260827_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('feed_sources', sa.Column('feed_type', sa.String(20), nullable=False, server_default='primary'))
    op.add_column('feed_sources', sa.Column('export_token', sa.String(64), nullable=True))
    op.add_column('feed_sources', sa.Column('history_retention_count', sa.Integer(), nullable=False, server_default='30'))
    op.execute(
        "UPDATE feed_sources SET export_token = "
        "md5(random()::text || clock_timestamp()::text) || md5(random()::text) "
        "WHERE export_token IS NULL"
    )
    op.alter_column('feed_sources', 'export_token', nullable=False)
    op.create_index('uq_feed_sources_export_token', 'feed_sources', ['export_token'], unique=True)

    op.add_column('export_versions', sa.Column('product_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('export_versions', sa.Column('source', sa.String(20), nullable=False, server_default='run'))
    op.add_column('export_versions', sa.Column('source_version_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_export_versions_source_version_id', 'export_versions', 'export_versions',
        ['source_version_id'], ['id'], ondelete='SET NULL',
    )

    op.drop_constraint('fk_export_runs_export_version_id', 'export_runs', type_='foreignkey')
    op.create_foreign_key(
        'fk_export_runs_export_version_id', 'export_runs', 'export_versions',
        ['export_version_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_export_runs_export_version_id', 'export_runs', type_='foreignkey')
    op.create_foreign_key(
        'fk_export_runs_export_version_id', 'export_runs', 'export_versions',
        ['export_version_id'], ['id'], ondelete='RESTRICT',
    )

    op.drop_constraint('fk_export_versions_source_version_id', 'export_versions', type_='foreignkey')
    op.drop_column('export_versions', 'source_version_id')
    op.drop_column('export_versions', 'source')
    op.drop_column('export_versions', 'product_count')

    op.drop_index('uq_feed_sources_export_token', table_name='feed_sources')
    op.drop_column('feed_sources', 'history_retention_count')
    op.drop_column('feed_sources', 'export_token')
    op.drop_column('feed_sources', 'feed_type')
```

Note: the existing FK constraint is named `fk_export_runs_export_version_id` (created by the M1 baseline migration); it is dropped and recreated with `ondelete='SET NULL'` so retention pruning can delete old versions while ExportRun rows survive with a NULLed reference.

- [ ] **Step 4: Update the models**

In `backend/app/models/feed_source.py`, add after the `currency` column:

```python
    feed_type: Mapped[str] = mapped_column(String(20), nullable=False, default="primary", server_default="primary")
    export_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    history_retention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
```

In `backend/app/models/export.py`, replace the `ExportVersion` class body after `version_number`/`file_hash` with:

```python
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    product_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="run", server_default="run")
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("export_versions.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

and change `ExportRun.export_version_id` to:

```python
    export_version_id: Mapped[int | None] = mapped_column(ForeignKey("export_versions.id", ondelete="SET NULL"))
```

- [ ] **Step 5: Add settings and gitignore entry**

In `backend/app/config.py` add to `Settings`:

```python
    export_dir: str = str(Path(__file__).resolve().parents[2] / "exports")
    public_base_url: str = "http://localhost:8000"
```

Append to `.gitignore` (repo root):

```
# Exported feed files
exports/
```

- [ ] **Step 6: Add model metadata tests**

Append to `backend/tests/test_models.py`:

```python
def test_m8_feed_source_columns():
    feed = Base.metadata.tables["feed_sources"]
    assert {"feed_type", "export_token", "history_retention_count"} <= set(feed.c.keys())
    assert any(
        {c.name for c in constraint.columns} == {"export_token"}
        for constraint in feed.constraints
        if isinstance(constraint, UniqueConstraint)
    )


def test_m8_export_version_columns():
    versions = Base.metadata.tables["export_versions"]
    assert {"product_count", "source", "source_version_id"} <= set(versions.c.keys())
    runs = Base.metadata.tables["export_runs"]
    fk = next(iter(runs.c.export_version_id.foreign_keys))
    assert str(fk.column) == "export_versions.id"
    assert fk.ondelete == "SET NULL"
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_m8_migration.py tests/test_models.py tests/test_migrations.py -v`
Expected: all PASS (migration applied to the template DB; metadata assertions green).

- [ ] **Step 8: Commit**

```bash
git add backend/alembic/versions/20260828_0001_m8_export_versioning.py backend/app/config.py backend/app/models/feed_source.py backend/app/models/export.py backend/tests/test_m8_migration.py backend/tests/test_models.py .gitignore
git commit -m "feat(schema): M8 export tokens, retention count, version bookkeeping"
```

---

### Task 2: XML renderer

**Files:**
- Create: `backend/app/export/__init__.py`
- Create: `backend/app/export/renderer.py`
- Test: `backend/tests/test_export_renderer.py`

**Interfaces:**
- Consumes: `registry.model.RegistryDocument`, `RegistryAttribute`, `AttributeKind`, `ExportStatus`
- Produces: `ChannelMetadata(title: str, link: str, description: str)` (frozen dataclass) and `render_feed(products: Sequence[dict[str, Any]], registry: RegistryDocument, channel: ChannelMetadata) -> bytes`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_export_renderer.py`:

```python
from app.export.renderer import ChannelMetadata, render_feed
from registry.loader import load_registry
from registry.model import (
    AttributeKind,
    ExportStatus,
    FeedDomain,
    RegistryAttribute,
    RegistryDocument,
    RequirementStatus,
    SubField,
)

CHANNEL = ChannelMetadata(title="Feed", link="https://shop.example", description="Desc")


def _attr(name, kind, fields=(), export_status=ExportStatus.EXPORTABLE):
    return RegistryAttribute(
        name=name,
        kind=kind,
        type="string",
        required=RequirementStatus.OPTIONAL,
        domain=FeedDomain.PRIMARY,
        export_status=export_status,
        fields=tuple(fields),
    )


def _sub(name):
    return SubField(name=name, type="string", required=RequirementStatus.OPTIONAL)


def _doc(*attrs):
    return RegistryDocument(attributes={a.name: a for a in attrs})


def test_scalar_rendering_and_escaping():
    registry = _doc(_attr("id", AttributeKind.SCALAR), _attr("title", AttributeKind.SCALAR))
    xml = render_feed([{"id": "1", "title": "A & B <c>"}], registry, CHANNEL)
    text = xml.decode("utf-8")
    assert "<g:id>1</g:id>" in text
    assert "<g:title>A &amp; B &lt;c&gt;</g:title>" in text


def test_rss_envelope_and_channel_metadata():
    registry = _doc(_attr("id", AttributeKind.SCALAR))
    xml = render_feed([{"id": "1"}], registry, ChannelMetadata(title="T & Co", link="https://x", description="D")).decode("utf-8")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<rss version="2.0" xmlns:g="http://base.google.com/schemas/1.0">' in xml
    assert "<title>T &amp; Co</title>" in xml
    assert "<link>https://x</link>" in xml
    assert "<description>D</description>" in xml
    assert xml.rstrip().endswith("</rss>")


def test_repeated_scalar_strips_empty_elements():
    registry = _doc(_attr("id", AttributeKind.SCALAR), _attr("additional_image_link", AttributeKind.REPEATED_SCALAR))
    product = {"id": "1", "additional_image_link": ["a", "", None, "b"]}
    text = render_feed([product], registry, CHANNEL).decode("utf-8")
    assert text.count("<g:additional_image_link>") == 2
    assert "<g:additional_image_link>a</g:additional_image_link>" in text
    assert "<g:additional_image_link>b</g:additional_image_link>" in text


def test_structured_rendering_follows_registry_subfield_order():
    registry = _doc(
        _attr("id", AttributeKind.SCALAR),
        _attr("installment", AttributeKind.STRUCTURED, fields=(_sub("months"), _sub("amount"))),
    )
    product = {"id": "1", "installment": {"amount": "49.99 EUR", "months": "12"}}
    text = render_feed([product], registry, CHANNEL).decode("utf-8")
    assert "<g:installment><g:months>12</g:months><g:amount>49.99 EUR</g:amount></g:installment>" in text


def test_repeated_structured_pass_through_fidelity():
    registry = _doc(
        _attr("id", AttributeKind.SCALAR),
        _attr("shipping", AttributeKind.REPEATED_STRUCTURED, fields=(_sub("country"), _sub("price"))),
    )
    shipping = [{"country": "US", "price": "6.49 USD"}, {"country": "UK", "price": "5.99 GBP"}]
    text = render_feed([{"id": "1", "shipping": shipping}], registry, CHANNEL).decode("utf-8")
    assert text.count("<g:shipping>") == 2
    assert "<g:shipping><g:country>US</g:country><g:price>6.49 USD</g:price></g:shipping>" in text
    assert "<g:shipping><g:country>UK</g:country><g:price>5.99 GBP</g:price></g:shipping>" in text


def test_element_order_follows_registry_not_product():
    registry = _doc(
        _attr("id", AttributeKind.SCALAR),
        _attr("title", AttributeKind.SCALAR),
        _attr("price", AttributeKind.SCALAR),
    )
    text = render_feed([{"price": "1 USD", "id": "1", "title": "T"}], registry, CHANNEL).decode("utf-8")
    assert text.index("<g:id>") < text.index("<g:title>") < text.index("<g:price>")


def test_unknown_and_non_exportable_attributes_are_skipped():
    registry = _doc(
        _attr("id", AttributeKind.SCALAR),
        _attr("secret", AttributeKind.SCALAR, export_status=ExportStatus.NON_EXPORTABLE),
    )
    product = {"id": "1", "secret": "x", "_category_provenance": "auto"}
    text = render_feed([product], registry, CHANNEL).decode("utf-8")
    assert "secret" not in text
    assert "_category_provenance" not in text


def test_empty_values_skipped_entirely():
    registry = _doc(
        _attr("id", AttributeKind.SCALAR),
        _attr("title", AttributeKind.SCALAR),
        _attr("additional_image_link", AttributeKind.REPEATED_SCALAR),
        _attr("installment", AttributeKind.STRUCTURED, fields=(_sub("months"),)),
    )
    product = {"id": "1", "title": "", "additional_image_link": [], "installment": {}}
    text = render_feed([product], registry, CHANNEL).decode("utf-8")
    assert "<g:title>" not in text
    assert "<g:additional_image_link>" not in text
    assert "<g:installment>" not in text


def test_items_sorted_by_id():
    registry = _doc(_attr("id", AttributeKind.SCALAR))
    text = render_feed([{"id": "b"}, {"id": "a"}], registry, CHANNEL).decode("utf-8")
    assert text.index("<g:id>a</g:id>") < text.index("<g:id>b</g:id>")


def test_render_is_deterministic():
    registry = load_registry()
    product = {
        "id": "1",
        "title": "Shirt",
        "shipping": [{"country": "US", "price": "6.49 USD"}],
    }
    assert render_feed([product], registry, CHANNEL) == render_feed([product], registry, CHANNEL)


def test_empty_product_list_yields_valid_channel():
    registry = _doc(_attr("id", AttributeKind.SCALAR))
    text = render_feed([], registry, CHANNEL).decode("utf-8")
    assert "<item>" not in text
    assert "<channel>" in text and "</channel>" in text


def test_full_registry_round_trip_through_parse_xml():
    from app.ingest.xml_reader import parse_xml

    registry = load_registry()
    product = {
        "id": "SKU-1",
        "title": "Red Shirt",
        "additional_image_link": ["http://a/1.jpg", "http://a/2.jpg"],
        "installment": {"months": "12", "amount": "49.99 EUR"},
        "shipping": [{"country": "US", "price": "6.49 USD"}, {"country": "UK", "price": "5.99 GBP"}],
    }
    data = render_feed([product], registry, CHANNEL)
    report = parse_xml(data, registry)
    assert report.row_errors == []
    assert report.products == [product]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_export_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.export'`.

- [ ] **Step 3: Implement the renderer**

Create `backend/app/export/__init__.py`:

```python
from .renderer import ChannelMetadata, render_feed

__all__ = ["ChannelMetadata", "render_feed"]
```

Create `backend/app/export/renderer.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

from registry.model import AttributeKind, ExportStatus, RegistryAttribute, RegistryDocument


@dataclass(frozen=True)
class ChannelMetadata:
    title: str
    link: str
    description: str


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _scalar_element(name: str, value: Any) -> str:
    return f"<g:{name}>{escape(str(value))}</g:{name}>"


def _structured_body(attribute: RegistryAttribute, value: dict[str, Any]) -> str:
    parts: list[str] = []
    for sub_field in attribute.fields:
        sub_value = value.get(sub_field.name)
        if _is_empty(sub_value):
            continue
        parts.append(_scalar_element(sub_field.name, sub_value))
    return "".join(parts)


def _render_attribute(attribute: RegistryAttribute, value: Any) -> str:
    name = attribute.name
    if attribute.kind is AttributeKind.SCALAR:
        return _scalar_element(name, value) + "\n"
    if attribute.kind is AttributeKind.REPEATED_SCALAR:
        items = [item for item in value if not _is_empty(item)]
        return "".join(_scalar_element(name, item) + "\n" for item in items)
    if attribute.kind is AttributeKind.STRUCTURED:
        body = _structured_body(attribute, value)
        if not body:
            return ""
        return f"<g:{name}>{body}</g:{name}>\n"
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict) or _is_empty(item):
            continue
        body = _structured_body(attribute, item)
        if body:
            parts.append(f"<g:{name}>{body}</g:{name}>\n")
    return "".join(parts)


def render_feed(
    products: Sequence[dict[str, Any]],
    registry: RegistryDocument,
    channel: ChannelMetadata,
) -> bytes:
    chunks: list[str] = []
    chunks.append('<?xml version="1.0" encoding="UTF-8"?>\n')
    chunks.append('<rss version="2.0" xmlns:g="http://base.google.com/schemas/1.0">\n')
    chunks.append("<channel>\n")
    chunks.append(f"<title>{escape(channel.title)}</title>\n")
    chunks.append(f"<link>{escape(channel.link)}</link>\n")
    chunks.append(f"<description>{escape(channel.description)}</description>\n")
    for product in sorted(products, key=lambda p: str(p.get("id", ""))):
        chunks.append("<item>\n")
        for attribute in registry.attributes.values():
            if attribute.export_status is not ExportStatus.EXPORTABLE:
                continue
            value = product.get(attribute.name)
            if _is_empty(value):
                continue
            chunks.append(_render_attribute(attribute, value))
        chunks.append("</item>\n")
    chunks.append("</channel>\n")
    chunks.append("</rss>\n")
    return "".join(chunks).encode("utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_export_renderer.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/export/__init__.py backend/app/export/renderer.py backend/tests/test_export_renderer.py
git commit -m "feat(export): registry-driven GMC XML renderer"
```

---

### Task 3: File store (atomic publish, version files)

**Files:**
- Create: `backend/app/export/store.py`
- Modify: `backend/app/export/__init__.py`
- Test: `backend/tests/test_export_store.py`

**Interfaces:**
- Consumes: nothing beyond stdlib
- Produces: `ExportFileStore(root)` with `published_path(feed_source_id) -> Path`, `version_path(feed_source_id, version_number) -> Path`, `write_version(feed_source_id, version_number, data) -> Path`, `publish(feed_source_id, data) -> Path`, `published_exists(feed_source_id) -> bool`, `read_version(feed_source_id, version_number) -> bytes | None`, `delete_version_file(feed_source_id, version_number) -> None`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_export_store.py`:

```python
from app.export.store import ExportFileStore


def test_write_version_creates_file_at_expected_path(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    path = store.write_version(7, 3, b"<xml/>")
    assert path == tmp_path / "exports" / "versions" / "7" / "3.xml"
    assert path.read_bytes() == b"<xml/>"


def test_publish_creates_file_at_expected_path(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    path = store.publish(7, b"<xml/>")
    assert path == tmp_path / "exports" / "published" / "7.xml"
    assert path.read_bytes() == b"<xml/>"


def test_writes_leave_no_temp_files(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    store.write_version(1, 1, b"a")
    store.publish(1, b"b")
    leftovers = [p.name for p in tmp_path.rglob("*") if p.is_file() and ".tmp" in p.name]
    assert leftovers == []


def test_publish_replaces_existing_atomically(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    store.publish(1, b"old")
    store.publish(1, b"new")
    assert store.published_path(1).read_bytes() == b"new"


def test_published_exists(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    assert store.published_exists(1) is False
    store.publish(1, b"x")
    assert store.published_exists(1) is True


def test_read_version_returns_bytes_or_none(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    assert store.read_version(1, 1) is None
    store.write_version(1, 1, b"data")
    assert store.read_version(1, 1) == b"data"


def test_delete_version_file_is_idempotent(tmp_path):
    store = ExportFileStore(tmp_path / "exports")
    store.delete_version_file(1, 1)
    store.write_version(1, 1, b"data")
    store.delete_version_file(1, 1)
    assert store.read_version(1, 1) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_export_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'ExportFileStore'`.

- [ ] **Step 3: Implement the store**

Create `backend/app/export/store.py`:

```python
from __future__ import annotations

import os
from pathlib import Path


def _atomic_write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


class ExportFileStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def published_path(self, feed_source_id: int) -> Path:
        return self._root / "published" / f"{feed_source_id}.xml"

    def version_path(self, feed_source_id: int, version_number: int) -> Path:
        return self._root / "versions" / str(feed_source_id) / f"{version_number}.xml"

    def write_version(self, feed_source_id: int, version_number: int, data: bytes) -> Path:
        return _atomic_write(self.version_path(feed_source_id, version_number), data)

    def publish(self, feed_source_id: int, data: bytes) -> Path:
        return _atomic_write(self.published_path(feed_source_id), data)

    def published_exists(self, feed_source_id: int) -> bool:
        return self.published_path(feed_source_id).is_file()

    def read_version(self, feed_source_id: int, version_number: int) -> bytes | None:
        path = self.version_path(feed_source_id, version_number)
        if not path.is_file():
            return None
        return path.read_bytes()

    def delete_version_file(self, feed_source_id: int, version_number: int) -> None:
        self.version_path(feed_source_id, version_number).unlink(missing_ok=True)
```

Update `backend/app/export/__init__.py`:

```python
from .renderer import ChannelMetadata, render_feed
from .store import ExportFileStore

__all__ = ["ChannelMetadata", "ExportFileStore", "render_feed"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_export_store.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/export/store.py backend/app/export/__init__.py backend/tests/test_export_store.py
git commit -m "feat(export): atomic file store for published and version XML"
```

---

### Task 4: Shared export-bound query + QC status `pending_export`

**Files:**
- Modify: `backend/app/staging/persistence.py`
- Modify: `backend/app/pipeline/steps.py` (QualityCheckStep only)
- Modify: `backend/app/qc/persistence.py`
- Modify: `backend/tests/test_m7_acceptance.py`
- Test: `backend/tests/test_export_bound.py`

**Interfaces:**
- Consumes: `StagingProduct` model, `session_factory` pattern used by existing staging functions
- Produces: `load_export_bound(session_factory, feed_source_id) -> list[tuple[str, dict[str, Any]]]` — `(product_id, product)` pairs ordered by `product_id`, product = `processed_data` if not None else `raw_data`; QC-written ExportRun rows now carry `status="pending_export"`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_export_bound.py`:

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Client, FeedSource, IngestionRun
from app.models.staging import StagingProduct
from app.staging.persistence import load_export_bound

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(session_factory):
    async with session_factory() as session:
        async with session.begin():
            client = Client(name="C")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="F",
                source_format="tsv",
                export_token="tok-bound-test",
            )
            session.add(feed_source)
            await session.flush()
            run = IngestionRun(feed_source_id=feed_source.id, status="completed")
            session.add(run)
            await session.flush()

            def row(product_id, status, raw, processed=None, excluded=False):
                return StagingProduct(
                    feed_source_id=feed_source.id,
                    ingestion_run_id=run.id,
                    product_id=product_id,
                    content_hash="c" + product_id,
                    config_hash="g" + product_id,
                    status=status,
                    raw_data=raw,
                    processed_data=processed,
                    excluded=excluded,
                )

            session.add(row("b", "active", {"id": "b", "title": "raw-b"}, {"id": "b", "title": "proc-b"}))
            session.add(row("a", "active", {"id": "a", "title": "raw-a"}, None))
            session.add(row("x", "active", {"id": "x"}, {"id": "x"}, excluded=True))
            session.add(row("r", "removed", {"id": "r"}, None))
            return feed_source.id


async def test_load_export_bound_filters_and_falls_back(session_factory):
    feed_source_id = await _seed(session_factory)
    bound = await load_export_bound(session_factory, feed_source_id)
    assert [(pid, product["title"] if "title" in product else None) for pid, product in bound] == [
        ("a", "raw-a"),
        ("b", "proc-b"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_export_bound.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_export_bound'`.

- [ ] **Step 3: Implement the helper**

Append to `backend/app/staging/persistence.py`:

```python
async def load_export_bound(
    session_factory: Callable[[], AsyncSession], feed_source_id: int
) -> list[tuple[str, dict[str, Any]]]:
    async with session_factory() as session:
        result = await session.execute(
            select(StagingProduct)
            .where(
                StagingProduct.feed_source_id == feed_source_id,
                StagingProduct.status == "active",
                StagingProduct.excluded == False,  # noqa: E712
            )
            .order_by(StagingProduct.product_id)
        )
        rows = list(result.scalars().all())
    return [
        (
            row.product_id,
            row.processed_data if row.processed_data is not None else row.raw_data,
        )
        for row in rows
    ]
```

Ensure `select` and `StagingProduct` are imported at the top of `staging/persistence.py` (it already imports the model for its existing functions — add `select` from `sqlalchemy` if missing).

- [ ] **Step 4: Point QualityCheckStep at the helper**

In `backend/app/pipeline/steps.py`, replace the inline staging query block inside `QualityCheckStep.execute` (the `async with ctx.session_factory() as session:` block that selects `StagingProduct` rows and the following `products`/`product_ids` loop) with:

```python
        from ..staging.persistence import load_export_bound

        bound = await load_export_bound(ctx.session_factory, ctx.feed_source_id)
        product_ids = [product_id for product_id, _ in bound]
        products = [product for _, product in bound]
```

- [ ] **Step 5: Switch QC's ExportRun status to pending_export**

In `backend/app/qc/persistence.py`, change the `ExportRun(...)` construction:

```python
            session.add(ExportRun(
                feed_source_id=feed_source_id,
                ingestion_run_id=ingestion_run_id,
                status="pending_export",
                product_count=product_count,
                critical_finding_count=counts["critical"],
                warning_finding_count=counts["warning"],
                info_finding_count=counts["info"],
                export_version_id=None,
            ))
```

In `backend/tests/test_m7_acceptance.py`, update the assertion (around line 214):

```python
        assert export_runs[0].status == "pending_export"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_export_bound.py tests/test_m7_acceptance.py tests/test_staging_step.py tests/test_pipeline_steps.py -v`
Expected: all PASS (QC behavior unchanged apart from the status string).

- [ ] **Step 7: Commit**

```bash
git add backend/app/staging/persistence.py backend/app/pipeline/steps.py backend/app/qc/persistence.py backend/tests/test_export_bound.py backend/tests/test_m7_acceptance.py
git commit -m "feat(export): shared export-bound query; QC marks runs pending_export"
```

---

### Task 5: ExportService — export_for_run with dedupe

**Files:**
- Create: `backend/app/export/service.py`
- Modify: `backend/app/export/__init__.py`
- Test: `backend/tests/test_export_service.py`

**Interfaces:**
- Consumes: `ExportFileStore`, `render_feed`, `ChannelMetadata`, models `FeedSource`/`Client`/`ExportRun`/`ExportVersion`, `Clock`
- Produces:
  - `generate_export_token() -> str` (43-char `secrets.token_urlsafe(32)`)
  - `channel_metadata_for(feed_source, client_name: str, public_base_url: str) -> ChannelMetadata` — configuration keys `channel_title`/`channel_link`/`channel_description`, fallbacks: name / public_base_url / client_name
  - `ExportOutcome(version_number: int, product_count: int, deduplicated: bool)` frozen dataclass
  - `ExportService(session_factory, store, clock, public_base_url)` with `async export_for_run(feed_source_id, ingestion_run_id, products, registry) -> ExportOutcome`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_export_service.py`:

```python
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clock import TestClock
from app.export.renderer import ChannelMetadata
from app.export.service import ExportOutcome, ExportService, channel_metadata_for, generate_export_token
from app.export.store import ExportFileStore
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from registry.loader import load_registry

pytestmark = pytest.mark.asyncio

REGISTRY = load_registry()
PRODUCTS = [
    {"id": "SKU-1", "title": "Red Shirt", "price": "10 USD"},
    {"id": "SKU-2", "title": "Blue Hat", "price": "5 USD"},
]


@pytest_asyncio.fixture
async def env(isolated_database_url, tmp_path):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = ExportFileStore(tmp_path / "exports")
    clock = TestClock(datetime(2026, 8, 27, tzinfo=timezone.utc))
    service = ExportService(factory, store, clock, "http://test.public")

    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id,
                name="Main",
                source_format="tsv",
                export_token="tok-service-test",
                history_retention_count=2,
            )
            session.add(feed_source)
            await session.flush()
            feed_source_id = feed_source.id

    yield {"factory": factory, "store": store, "clock": clock, "service": service, "feed_source_id": feed_source_id}
    await engine.dispose()


async def _start_run(env):
    factory = env["factory"]
    async with factory() as session:
        async with session.begin():
            ingestion_run = IngestionRun(feed_source_id=env["feed_source_id"], status="running")
            session.add(ingestion_run)
            await session.flush()
            session.add(ExportRun(
                feed_source_id=env["feed_source_id"],
                ingestion_run_id=ingestion_run.id,
                status="pending_export",
                product_count=len(PRODUCTS),
            ))
            return ingestion_run.id


async def _versions(factory, feed_source_id):
    async with factory() as session:
        result = await session.execute(
            select(ExportVersion)
            .where(ExportVersion.feed_source_id == feed_source_id)
            .order_by(ExportVersion.version_number)
        )
        return list(result.scalars().all())


async def _export_runs(factory, feed_source_id):
    async with factory() as session:
        result = await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source_id)
        )
        return list(result.scalars().all())


def test_generate_export_token_shape():
    tokens = {generate_export_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(token) == 43 for token in tokens)


def test_channel_metadata_for_uses_config_then_fallbacks():
    class FS:
        name = "Feed name"
        configuration = {}

    meta = channel_metadata_for(FS(), "Client name", "http://base")
    assert meta == ChannelMetadata(title="Feed name", link="http://base", description="Client name")

    FS.configuration = {
        "channel_title": "T", "channel_link": "http://l", "channel_description": "D",
    }
    meta = channel_metadata_for(FS(), "Client name", "http://base")
    assert meta == ChannelMetadata(title="T", link="http://l", description="D")


async def test_first_export_creates_version_publishes_and_wires_run(env):
    run_id = await _start_run(env)
    outcome = await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)

    assert outcome == ExportOutcome(version_number=1, product_count=2, deduplicated=False)
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert [v.version_number for v in versions] == [1]
    assert versions[0].source == "run"
    assert versions[0].product_count == 2
    assert len(versions[0].file_hash) == 64
    assert env["store"].published_exists(env["feed_source_id"])
    assert env["store"].read_version(env["feed_source_id"], 1) == env["store"].published_path(env["feed_source_id"]).read_bytes()

    runs = await _export_runs(env["factory"], env["feed_source_id"])
    assert runs[0].status == "completed"
    assert runs[0].export_version_id == versions[0].id
    assert runs[0].completed_at == datetime(2026, 8, 27, tzinfo=timezone.utc)


async def test_unchanged_second_export_is_deduplicated(env):
    run_id = await _start_run(env)
    await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)

    run_id_2 = await _start_run(env)
    outcome = await env["service"].export_for_run(env["feed_source_id"], run_id_2, PRODUCTS, REGISTRY)

    assert outcome.deduplicated is True
    assert outcome.version_number == 1
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert len(versions) == 1
    runs = await _export_runs(env["factory"], env["feed_source_id"])
    second = next(r for r in runs if r.ingestion_run_id == run_id_2)
    assert second.status == "completed"
    assert second.export_version_id == versions[0].id


async def test_changed_content_creates_new_version(env):
    run_id = await _start_run(env)
    await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)

    run_id_2 = await _start_run(env)
    changed = [dict(PRODUCTS[0], title="Green Scarf"), PRODUCTS[1]]
    outcome = await env["service"].export_for_run(env["feed_source_id"], run_id_2, changed, REGISTRY)

    assert outcome == ExportOutcome(version_number=2, product_count=2, deduplicated=False)
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert [v.version_number for v in versions] == [1, 2]
    assert versions[0].file_hash != versions[1].file_hash


async def test_dedupe_restores_missing_published_file(env):
    run_id = await _start_run(env)
    await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)
    env["store"].published_path(env["feed_source_id"]).unlink()

    run_id_2 = await _start_run(env)
    outcome = await env["service"].export_for_run(env["feed_source_id"], run_id_2, PRODUCTS, REGISTRY)

    assert outcome.deduplicated is True
    assert env["store"].published_exists(env["feed_source_id"])
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert len(versions) == 1


async def test_retention_prunes_oldest_versions_and_files(env):
    titles = ["t1", "t2", "t3"]
    for index, title in enumerate(titles):
        run_id = await _start_run(env)
        products = [dict(PRODUCTS[0], title=title), PRODUCTS[1]]
        await env["service"].export_for_run(env["feed_source_id"], run_id, products, REGISTRY)

    versions = await _versions(env["factory"], env["feed_source_id"])
    assert [v.version_number for v in versions] == [2, 3]
    assert env["store"].read_version(env["feed_source_id"], 1) is None
    assert env["store"].read_version(env["feed_source_id"], 2) is not None


async def test_publish_failure_marks_run_failed_and_keeps_version(env, monkeypatch):
    run_id = await _start_run(env)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(env["store"], "publish", boom)
    with pytest.raises(OSError):
        await env["service"].export_for_run(env["feed_source_id"], run_id, PRODUCTS, REGISTRY)

    runs = await _export_runs(env["factory"], env["feed_source_id"])
    assert runs[0].status == "failed"
    versions = await _versions(env["factory"], env["feed_source_id"])
    assert [v.version_number for v in versions] == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_export_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'ExportService'` (and `channel_metadata_for`).

- [ ] **Step 3: Implement the service**

Create `backend/app/export/service.py`:

```python
from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from registry.model import RegistryDocument

from ..clock import Clock
from ..models.client import Client
from ..models.export import ExportRun, ExportVersion
from ..models.feed_source import FeedSource
from .renderer import ChannelMetadata, render_feed
from .store import ExportFileStore

logger = logging.getLogger(__name__)


def generate_export_token() -> str:
    return secrets.token_urlsafe(32)


def channel_metadata_for(
    feed_source: FeedSource, client_name: str, public_base_url: str
) -> ChannelMetadata:
    configuration = feed_source.configuration or {}
    return ChannelMetadata(
        title=configuration.get("channel_title") or feed_source.name,
        link=configuration.get("channel_link") or public_base_url,
        description=configuration.get("channel_description") or client_name,
    )


@dataclass(frozen=True)
class ExportOutcome:
    version_number: int
    product_count: int
    deduplicated: bool


class ExportService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        store: ExportFileStore,
        clock: Clock,
        public_base_url: str,
    ) -> None:
        self._session_factory = session_factory
        self._store = store
        self._clock = clock
        self._public_base_url = public_base_url

    async def export_for_run(
        self,
        feed_source_id: int,
        ingestion_run_id: int,
        products: Sequence[dict[str, Any]],
        registry: RegistryDocument,
    ) -> ExportOutcome:
        async with self._session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, feed_source_id)
                if feed_source is None:
                    raise LookupError(f"feed source {feed_source_id} not found")
                client = await session.get(Client, feed_source.client_id)
                client_name = client.name if client is not None else ""
                retention = feed_source.history_retention_count

        channel = channel_metadata_for(feed_source, client_name, self._public_base_url)
        data = render_feed(products, registry, channel)
        file_hash = hashlib.sha256(data).hexdigest()

        deduplicated = False
        version_number: int | None = None

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    locked = (
                        await session.execute(
                            select(FeedSource)
                            .where(FeedSource.id == feed_source_id)
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    if locked is None:
                        raise LookupError(f"feed source {feed_source_id} not found")

                    latest = (
                        await session.execute(
                            select(ExportVersion)
                            .where(ExportVersion.feed_source_id == feed_source_id)
                            .order_by(ExportVersion.version_number.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    run = (
                        await session.execute(
                            select(ExportRun).where(
                                ExportRun.feed_source_id == feed_source_id,
                                ExportRun.ingestion_run_id == ingestion_run_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if run is None:
                        raise LookupError(
                            f"export run for ingestion run {ingestion_run_id} not found"
                        )

                    if latest is not None and latest.file_hash == file_hash:
                        deduplicated = True
                        version_number = latest.version_number
                        run.export_version_id = latest.id
                    else:
                        version_number = (latest.version_number + 1) if latest is not None else 1
                        self._store.write_version(feed_source_id, version_number, data)
                        new_version = ExportVersion(
                            feed_source_id=feed_source_id,
                            export_run_id=run.id,
                            version_number=version_number,
                            file_hash=file_hash,
                            product_count=len(products),
                            source="run",
                        )
                        session.add(new_version)
                        await session.flush()
                        run.export_version_id = new_version.id
                    run.status = "completed"
                    run.completed_at = self._clock.now()
        except Exception:
            if not deduplicated and version_number is not None:
                self._store.delete_version_file(feed_source_id, version_number)
            await self._mark_run_failed(feed_source_id, ingestion_run_id)
            raise

        try:
            if not (deduplicated and self._store.published_exists(feed_source_id)):
                self._store.publish(feed_source_id, data)
        except Exception:
            await self._mark_run_failed(feed_source_id, ingestion_run_id)
            raise

        if not deduplicated:
            await self._prune_retention(feed_source_id, retention)

        return ExportOutcome(
            version_number=version_number,
            product_count=len(products),
            deduplicated=deduplicated,
        )

    async def list_versions(self, feed_source_id: int) -> list[ExportVersion]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ExportVersion)
                .where(ExportVersion.feed_source_id == feed_source_id)
                .order_by(ExportVersion.version_number.desc())
            )
            return list(result.scalars().all())

    async def _mark_run_failed(self, feed_source_id: int, ingestion_run_id: int) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    run = (
                        await session.execute(
                            select(ExportRun).where(
                                ExportRun.feed_source_id == feed_source_id,
                                ExportRun.ingestion_run_id == ingestion_run_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if run is not None:
                        run.status = "failed"
                        run.completed_at = self._clock.now()
        except Exception:
            logger.exception(
                "failed to mark export run failed for feed source %s", feed_source_id
            )

    async def _prune_retention(self, feed_source_id: int, retention: int) -> None:
        numbers: list[int] = []
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    stale = (
                        await session.execute(
                            select(ExportVersion)
                            .where(ExportVersion.feed_source_id == feed_source_id)
                            .order_by(ExportVersion.version_number.desc())
                            .offset(max(retention, 1))
                        )
                    ).scalars().all()
                    numbers = [row.version_number for row in stale]
                    for row in stale:
                        await session.delete(row)
            for number in numbers:
                self._store.delete_version_file(feed_source_id, number)
        except Exception:
            logger.exception(
                "retention prune failed for feed source %s", feed_source_id
            )
```

Update `backend/app/export/__init__.py`:

```python
from .renderer import ChannelMetadata, render_feed
from .service import ExportOutcome, ExportService, channel_metadata_for, generate_export_token
from .store import ExportFileStore

__all__ = [
    "ChannelMetadata",
    "ExportFileStore",
    "ExportOutcome",
    "ExportService",
    "channel_metadata_for",
    "generate_export_token",
    "render_feed",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_export_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/export/service.py backend/app/export/__init__.py backend/tests/test_export_service.py
git commit -m "feat(export): export service with file_hash dedupe and retention"
```

---

### Task 6: ExportStep, default_steps wiring, existing-test updates

**Files:**
- Modify: `backend/app/pipeline/steps.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_pipeline_steps.py`
- Modify: `backend/tests/test_pipeline_runner.py`
- Modify: `backend/tests/test_m2_acceptance.py`, `test_m3_acceptance.py`, `test_m4_acceptance.py`, `test_m5_acceptance.py`, `test_m6_acceptance.py`, `test_runs_api.py`
- Modify: row-cleanup fixtures in `test_clients_api.py`, `test_field_mapping_api.py`, `test_plugins_api.py`, `test_quality_api.py`, `test_registry_api.py`, `test_m7_acceptance.py`

**Interfaces:**
- Consumes: `ExportService`, `ExportFileStore`, `load_export_bound`
- Produces: `ExportStep(registry, store, clock, public_base_url)` with `name = "export"`; `default_steps(fetcher, registry, plugin_registry=None, clock=None, image_probe=None, export_dir=None, public_base_url=None)` — `export_dir`/`public_base_url` default to the `Settings` defaults when None

- [ ] **Step 1: Replace ExportStep and default_steps**

In `backend/app/pipeline/steps.py`, replace the `ExportStep(_NoOpStep)` class with:

```python
class ExportStep:
    name = "export"

    def __init__(
        self,
        registry: RegistryDocument,
        store: ExportFileStore,
        clock: Clock,
        public_base_url: str,
    ) -> None:
        self._registry = registry
        self._store = store
        self._clock = clock
        self._public_base_url = public_base_url

    async def execute(self, ctx: StepContext) -> StepResult:
        from ..export.service import ExportService
        from ..staging.persistence import load_export_bound

        bound = await load_export_bound(ctx.session_factory, ctx.feed_source_id)
        products = [product for _, product in bound]
        service = ExportService(
            ctx.session_factory, self._store, self._clock, self._public_base_url
        )
        outcome = await service.export_for_run(
            ctx.feed_source_id, ctx.ingestion_run_id, products, self._registry
        )
        return StepResult(
            statistics={
                "export": {
                    "products": outcome.product_count,
                    "version": outcome.version_number,
                    "deduplicated": outcome.deduplicated,
                }
            }
        )
```

Add the import `from ..export.store import ExportFileStore` at the top of `steps.py` (next to the other app imports). Keep `processed_count=0` (the StepResult default) so IngestionRun totals keep their existing semantics.

Replace `default_steps` with:

```python
def default_steps(
    fetcher: HttpFetcher,
    registry: RegistryDocument,
    plugin_registry: dict[str, Any] | None = None,
    clock: Clock | None = None,
    image_probe: ImageProbe | None = None,
    export_dir: Path | str | None = None,
    public_base_url: str | None = None,
) -> tuple[PipelineStep, ...]:
    if clock is None:
        clock = SystemClock()
    store = ExportFileStore(
        Path(export_dir) if export_dir is not None else Path("exports")
    )
    base_url = public_base_url if public_base_url is not None else "http://localhost:8000"
    return (
        IngestStep(fetcher, registry),
        MappingStep(registry),
        StagingStep(),
        PluginStep(plugin_registry),
        QualityCheckStep(registry, clock, image_probe),
        ExportStep(registry, store, clock, base_url),
    )
```

Add `from pathlib import Path` to the imports of `steps.py`. Delete the `_NoOpStep` class — after this change nothing references it.

- [ ] **Step 2: Wire settings through create_app**

In `backend/app/main.py`, update the `default_steps(...)` call inside `create_app`:

```python
        steps = default_steps(
            fetcher if fetcher is not None else HttpFetcher(),
            load_registry(),
            app.state.plugin_registry,
            clock=app.state.clock,
            image_probe=image_probe,
            export_dir=settings.export_dir if settings is not None else None,
            public_base_url=settings.public_base_url if settings is not None else None,
        )
```

- [ ] **Step 3: Update test_pipeline_steps.py**

The no-op contract test no longer applies. In `backend/tests/test_pipeline_steps.py`:

- Change the `_steps()` fixture to accept `tmp_path` and pass it through:

```python
@pytest.fixture
def _steps(tmp_path):
    return default_steps(StubFetcher(), RegistryDocument(attributes={}), export_dir=tmp_path / "exports")
```

(adjust the existing fixture's body only — keep its name and usages)

- Replace `test_no_op_steps_contract` with:

```python
def test_export_step_is_wired():
    steps = default_steps(StubFetcher(), RegistryDocument(attributes={}), export_dir="unused")
    step = steps[-1]
    assert isinstance(step, ExportStep)
    assert step.name == "export"
```

- [ ] **Step 4: Update direct default_steps call sites**

Apply the same mechanical change — add `export_dir=<tmp dir>` and, where the enclosing function lacks it, add the `tmp_path` fixture parameter:

- `backend/tests/test_pipeline_runner.py` — `test_success_path_with_default_steps(session_factory, feed_source_id)` → add `tmp_path` parameter; `default_steps(StubFetcher(), RegistryDocument(attributes={}), export_dir=tmp_path / "exports")`.
- `backend/tests/test_m3_acceptance.py` — both `steps = [*default_steps(fetcher, load_registry()), capture]` lines → `steps = [*default_steps(fetcher, load_registry(), export_dir=tmp_path / "exports"), capture]`; add `tmp_path` to those test functions' signatures.
- `backend/tests/test_m4_acceptance.py` — same change at its `default_steps` call site.
- `backend/tests/test_m6_acceptance.py` — all four `default_steps(fetcher, registry, plugin_registry)` calls → `default_steps(fetcher, registry, plugin_registry, export_dir=tmp_path / "exports")`; add `tmp_path` to the enclosing test functions.

- [ ] **Step 5: Update create_app-based Settings fixtures**

In each of `backend/tests/test_m2_acceptance.py`, `test_m5_acceptance.py`, `test_runs_api.py`, the `app_factory` fixture constructs `Settings(_env_file=None, ...)`. Add the `tmp_path` fixture parameter to `app_factory` and add to the `Settings(...)` call:

```python
        export_dir=str(tmp_path / "exports"),
```

(`test_scheduler_startup.py` and `test_m7_acceptance.py` never trigger a pipeline run that reaches export file writes through `create_app`; leave their Settings unchanged.)

- [ ] **Step 6: Add ExportVersion to row-cleanup deletes**

Every fixture/test that executes `delete(ExportRun)` must first execute `delete(ExportVersion)` (versions reference runs via RESTRICT; runs reference versions via SET NULL after the M8 migration). Files: `test_clients_api.py`, `test_field_mapping_api.py`, `test_m2_acceptance.py` (fixture AND the in-test cleanup block near line 133), `test_m4_acceptance.py`, `test_m5_acceptance.py`, `test_m6_acceptance.py`, `test_m7_acceptance.py`, `test_plugins_api.py`, `test_quality_api.py`, `test_registry_api.py`, `test_runs_api.py`.

In each, insert immediately before the `delete(ExportRun)` line:

```python
            await session.execute(delete(ExportVersion))
```

and add `ExportVersion` to the `from app.models import ...` import (or `from app.models.export import ExportVersion` where imports are module-specific).

- [ ] **Step 7: Run the affected suites**

Run: `uv run pytest tests/test_pipeline_steps.py tests/test_pipeline_runner.py tests/test_m2_acceptance.py tests/test_m3_acceptance.py tests/test_m4_acceptance.py tests/test_m5_acceptance.py tests/test_m6_acceptance.py tests/test_runs_api.py tests/test_m7_acceptance.py -v`
Expected: all PASS. If an assertion on run statistics fails because the new `export` key appears, extend the assertion to include it (statistics dicts gained `"export": {"products": ..., "version": ..., "deduplicated": ...}`).

- [ ] **Step 8: Commit**

```bash
git add backend/app/pipeline/steps.py backend/app/main.py backend/tests/
git commit -m "feat(pipeline): real ExportStep wired into default_steps and app"
```

---

### Task 7: Export token, public endpoint, rotation, delete cleanup

**Files:**
- Modify: `backend/app/schemas/clients.py`
- Modify: `backend/app/routes/clients.py`
- Create: `backend/app/routes/export_public.py`
- Modify: `backend/app/routes/__init__.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_export_public.py`

**Interfaces:**
- Consumes: `generate_export_token`, `ExportFileStore`, `Settings.export_dir`/`public_base_url`
- Produces: `GET /export/{token}.xml` (unauthenticated, `application/xml`, 404 otherwise); `POST /feed-sources/{id}/export-token/rotate` → `{"export_token", "export_url"}`; `FeedSourceOut` gains `feed_type`, `history_retention_count`, `export_url`; feed source create generates the token; feed source delete removes export files

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_export_public.py`:

```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.export.store import ExportFileStore
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
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
        export_dir=str(tmp_path / "exports"),
        public_base_url="http://test.public",
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory, settings
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _create_feed_source(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={"name": "Main", "source_format": "tsv"},
    )
    assert resp.status_code == 201
    return client, resp.json()


async def test_create_feed_source_generates_token_and_export_url(app_factory):
    _, payload = await _create_feed_source(app_factory)
    assert payload["feed_type"] == "primary"
    assert payload["history_retention_count"] == 30
    assert payload["export_url"].startswith("http://test.public/export/")
    assert payload["export_url"].endswith(".xml")

    _, factory, _ = app_factory
    async with factory() as session:
        row = (await session.execute(select(FeedSource))).scalar_one()
        assert row.feed_type == "primary"
        assert row.export_token
        assert payload["export_url"] == f"http://test.public/export/{row.export_token}.xml"


async def test_public_endpoint_404_for_unknown_token_and_before_export(app_factory):
    client, payload = await _create_feed_source(app_factory)
    token = payload["export_url"].rsplit("/", 1)[1].removesuffix(".xml")

    resp = await client.get("/export/does-not-exist.xml")
    assert resp.status_code == 404

    resp = await client.get(f"/export/{token}.xml")
    assert resp.status_code == 404


async def test_public_endpoint_serves_published_file_without_auth(app_factory):
    app, factory, settings = app_factory
    client, payload = await _create_feed_source(app_factory)
    token = payload["export_url"].rsplit("/", 1)[1].removesuffix(".xml")

    async with factory() as session:
        feed_source_id = (await session.execute(select(FeedSource))).scalar_one().id

    store = ExportFileStore(settings.export_dir)
    store.publish(feed_source_id, b"<rss>published</rss>")

    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await anonymous.get(f"/export/{token}.xml")
    assert resp.status_code == 200
    assert resp.content == b"<rss>published</rss>"
    assert resp.headers["content-type"].startswith("application/xml")


async def test_rotate_token_invalidates_old_url_immediately(app_factory):
    app, factory, settings = app_factory
    client, payload = await _create_feed_source(app_factory)
    old_url = payload["export_url"]
    old_token = old_url.rsplit("/", 1)[1].removesuffix(".xml")
    feed_source_id = payload["id"]

    ExportFileStore(settings.export_dir).publish(feed_source_id, b"<rss/>")

    resp = await client.post(f"/feed-sources/{feed_source_id}/export-token/rotate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["export_url"] != old_url
    assert body["export_token"] != old_token

    assert (await client.get(f"/export/{old_token}.xml")).status_code == 404
    resp = await client.get(f"/export/{body['export_token']}.xml")
    assert resp.status_code == 200


async def test_delete_feed_source_removes_export_files(app_factory):
    client, payload = await _create_feed_source(app_factory)
    _, _, settings = app_factory
    feed_source_id = payload["id"]
    store = ExportFileStore(settings.export_dir)
    store.publish(feed_source_id, b"<rss/>")
    store.write_version(feed_source_id, 1, b"<rss/>")

    resp = await client.delete(f"/feed-sources/{feed_source_id}")
    assert resp.status_code == 204
    assert not store.published_exists(feed_source_id)
    assert store.read_version(feed_source_id, 1) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_export_public.py -v`
Expected: FAIL — `feed_type`/`export_url` missing from the create response (422 response-validation or KeyError) and `/export/...` route 404s for the wrong reason.

- [ ] **Step 3: Update schemas**

In `backend/app/schemas/clients.py`:

- `FeedSourceOut` — add fields:

```python
    feed_type: str
    history_retention_count: int
    export_url: str = ""
```

- `FeedSourceUpdate` — add:

```python
    history_retention_count: int | None = Field(default=None, ge=1)
```

- [ ] **Step 4: Update the clients routes**

In `backend/app/routes/clients.py`:

- Imports: add `from pathlib import Path`, `from fastapi.responses import Response`, `from ..config import Settings, get_settings`, `from ..export.service import generate_export_token`, `from ..export.store import ExportFileStore`.

- Add helpers after `_locks`:

```python
def _export_url(settings: Settings, token: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/export/{token}.xml"


def _feed_source_out(feed_source: FeedSource, settings: Settings) -> dict:
    data = FeedSourceOut.model_validate(feed_source).model_dump()
    data["export_url"] = _export_url(settings, feed_source.export_token)
    return data
```

- `create_feed_source`: add `settings: Settings = Depends(get_settings)` parameter; construct with a token:

```python
    feed_source = FeedSource(
        client_id=client_id, export_token=generate_export_token(), **payload.model_dump()
    )
```

and return `_feed_source_out(feed_source, settings)`.

- `list_feed_sources`: add the `settings` parameter; return `[_feed_source_out(fs, settings) for fs in result.scalars()]`.

- `update_feed_source`: add the `settings` parameter; return `_feed_source_out(feed_source, settings)`.

- `delete_feed_source`: after the successful `session.begin()` block and scheduler/lock cleanup, add best-effort file cleanup:

```python
    settings = _resolve_settings(request)
    store = ExportFileStore(settings.export_dir)
    store.published_path(feed_source_id).unlink(missing_ok=True)
    versions_dir = Path(settings.export_dir) / "versions" / str(feed_source_id)
    if versions_dir.is_dir():
        import shutil

        shutil.rmtree(versions_dir, ignore_errors=True)
```

with the small helper (settings may live on `app.state` when injected; add it next to `_require_db`):

```python
def _resolve_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        settings = get_settings()
    return settings
```

- Add the rotation endpoint:

```python
@router.post("/feed-sources/{feed_source_id}/export-token/rotate")
async def rotate_export_token(
    feed_source_id: int,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
) -> dict[str, str]:
    session = _require_db(db_session)
    async with session.begin():
        feed_source = await session.get(FeedSource, feed_source_id)
        if feed_source is None:
            raise HTTPException(status_code=404, detail="feed source not found")
        feed_source.export_token = generate_export_token()
        await session.flush()
        token = feed_source.export_token
    settings = _resolve_settings(request)
    return {"export_token": token, "export_url": _export_url(settings, token)}
```

- [ ] **Step 5: Create the public endpoint**

Create `backend/app/routes/export_public.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db.engine import get_db_session
from ..models.feed_source import FeedSource

router = APIRouter()


@router.get("/export/{token}.xml")
async def public_export(
    token: str,
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    result = await db_session.execute(
        select(FeedSource).where(FeedSource.export_token == token)
    )
    feed_source = result.scalar_one_or_none()
    if feed_source is None:
        raise HTTPException(status_code=404, detail="not found")
    path = Path(settings.export_dir) / "published" / f"{feed_source.id}.xml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="application/xml")
```

No `require_user` dependency, and no logging of the token anywhere in this module.

- [ ] **Step 6: Register the router**

In `backend/app/routes/__init__.py` add:

```python
from .export_public import router as export_public_router
```

and include it in `__all__`. In `backend/app/main.py` add `export_public_router` to the routes import and `app.include_router(export_public_router)` next to the other routers.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_export_public.py tests/test_clients_api.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/clients.py backend/app/routes/clients.py backend/app/routes/export_public.py backend/app/routes/__init__.py backend/app/main.py backend/tests/test_export_public.py
git commit -m "feat(api): export token, public fetch endpoint, rotation, delete cleanup"
```

---

### Task 8: Export history list + field-based diff

**Files:**
- Create: `backend/app/schemas/export.py`
- Create: `backend/app/routes/export_history.py`
- Modify: `backend/app/export/service.py` (add `diff`)
- Modify: `backend/app/routes/__init__.py`, `backend/app/main.py`
- Test: `backend/tests/test_export_history_api.py`

**Interfaces:**
- Consumes: `ExportService.list_versions`, `parse_xml` from `app.ingest.xml_reader`, `load_registry`
- Produces: `ExportService.diff(feed_source_id, version_number, against: int | None, registry) -> dict` raising `LookupError` for unknown versions/files and when no preceding version exists; `GET /feed-sources/{id}/export-history` → `list[ExportVersionOut]`; `GET /feed-sources/{id}/export-history/{v}/diff?against={v2}` → `DiffOut`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_export_history_api.py`:

```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.export.service import ExportService
from app.export.store import ExportFileStore
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from app.clock import TestClock
from datetime import datetime, timezone
from registry.loader import load_registry

pytestmark = pytest.mark.asyncio

REGISTRY = load_registry()


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
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
        export_dir=str(tmp_path / "exports"),
        public_base_url="http://test.public",
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory, settings
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _seed_versions(app_factory, product_sets):
    """Run export_for_run once per product set; returns feed_source_id."""
    _, factory, settings = app_factory
    clock = TestClock(datetime(2026, 8, 27, tzinfo=timezone.utc))
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id, name="Main", source_format="tsv",
                export_token="tok-history-test",
            )
            session.add(feed_source)
            await session.flush()
            feed_source_id = feed_source.id

    service = ExportService(factory, ExportFileStore(settings.export_dir), clock, "http://test.public")
    for products in product_sets:
        async with factory() as session:
            async with session.begin():
                run = IngestionRun(feed_source_id=feed_source_id, status="completed")
                session.add(run)
                await session.flush()
                session.add(ExportRun(
                    feed_source_id=feed_source_id, ingestion_run_id=run.id,
                    status="pending_export", product_count=len(products),
                ))
                run_id = run.id
        await service.export_for_run(feed_source_id, run_id, products, REGISTRY)
    return feed_source_id


BASE = [{"id": "A", "title": "Shirt", "price": "10 USD"}]
CHANGED = [{"id": "A", "title": "Shirt v2", "price": "9 USD"}, {"id": "B", "title": "Hat", "price": "5 USD"}]


async def test_history_lists_versions_descending(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history")
    assert resp.status_code == 200
    body = resp.json()
    assert [v["version_number"] for v in body] == [2, 1]
    assert body[0]["source"] == "run"
    assert body[0]["product_count"] == 2
    assert len(body[0]["file_hash"]) == 64
    assert body[0]["source_version_id"] is None


async def test_history_requires_auth_and_known_feed_source(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    app, _, _ = app_factory
    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anonymous.get(f"/feed-sources/{feed_source_id}/export-history")).status_code == 401

    client = await logged_in_client(app_factory)
    assert (await client.get("/feed-sources/999999/export-history")).status_code == 404


async def test_diff_reports_added_removed_and_changed_fields(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history/2/diff?against=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 2
    assert body["against"] == 1
    assert body["added"] == ["B"]
    assert body["removed"] == []
    changed = {entry["product_id"]: entry["fields"] for entry in body["changed"]}
    assert set(changed) == {"A"}
    fields = {f["field"]: (f["old"], f["new"]) for f in changed["A"]}
    assert fields["title"] == ("Shirt", "Shirt v2")
    assert fields["price"] == ("10 USD", "9 USD")


async def test_diff_defaults_to_preceding_version(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)

    resp = await client.get(f"/feed-sources/{feed_source_id}/export-history/2/diff")
    assert resp.status_code == 200
    assert resp.json()["against"] == 1


async def test_diff_404_cases(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    client = await logged_in_client(app_factory)

    assert (await client.get(f"/feed-sources/{feed_source_id}/export-history/9/diff")).status_code == 404
    assert (await client.get(f"/feed-sources/{feed_source_id}/export-history/1/diff")).status_code == 404
    assert (await client.get(f"/feed-sources/{feed_source_id}/export-history/1/diff?against=9")).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_export_history_api.py -v`
Expected: FAIL — 404/405 (routes missing).

- [ ] **Step 3: Implement service.diff**

Append to `ExportService` in `backend/app/export/service.py`:

```python
    async def diff(
        self,
        feed_source_id: int,
        version_number: int,
        against: int | None,
        registry: RegistryDocument,
    ) -> dict[str, Any]:
        async with self._session_factory() as session:
            version = (
                await session.execute(
                    select(ExportVersion).where(
                        ExportVersion.feed_source_id == feed_source_id,
                        ExportVersion.version_number == version_number,
                    )
                )
            ).scalar_one_or_none()
            if version is None:
                raise LookupError(f"version {version_number} not found")
            if against is None:
                against = (
                    await session.execute(
                        select(ExportVersion.version_number)
                        .where(
                            ExportVersion.feed_source_id == feed_source_id,
                            ExportVersion.version_number < version_number,
                        )
                        .order_by(ExportVersion.version_number.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if against is None:
                    raise LookupError(f"no preceding version for {version_number}")
            against_version = (
                await session.execute(
                    select(ExportVersion).where(
                        ExportVersion.feed_source_id == feed_source_id,
                        ExportVersion.version_number == against,
                    )
                )
            ).scalar_one_or_none()
            if against_version is None:
                raise LookupError(f"version {against} not found")

        new_products = self._load_version_products(feed_source_id, version_number, registry)
        old_products = self._load_version_products(feed_source_id, against, registry)
        return _field_diff(old_products, new_products, version_number, against)

    def _load_version_products(
        self, feed_source_id: int, version_number: int, registry: RegistryDocument
    ) -> dict[str, dict[str, Any]]:
        data = self._store.read_version(feed_source_id, version_number)
        if data is None:
            raise LookupError(f"version file {version_number} missing")
        report = parse_xml(data, registry)
        return {
            str(product["id"]): product
            for product in report.products
            if product.get("id")
        }
```

Add at module level in `service.py`:

```python
def _field_diff(
    old: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
    version_number: int,
    against: int,
) -> dict[str, Any]:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed: list[dict[str, Any]] = []
    for product_id in sorted(set(old) & set(new)):
        fields = []
        for key in sorted(set(old[product_id]) | set(new[product_id])):
            old_value = old[product_id].get(key)
            new_value = new[product_id].get(key)
            if old_value != new_value:
                fields.append({"field": key, "old": old_value, "new": new_value})
        if fields:
            changed.append({"product_id": product_id, "fields": fields})
    return {
        "version": version_number,
        "against": against,
        "added": added,
        "removed": removed,
        "changed": changed,
    }
```

and add the import `from ..ingest.xml_reader import parse_xml` at the top of `service.py`.

- [ ] **Step 4: Create schemas and routes**

Create `backend/app/schemas/export.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ExportVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_number: int
    product_count: int
    file_hash: str
    source: str
    source_version_id: int | None
    created_at: datetime


class DiffFieldOut(BaseModel):
    field: str
    old: Any = None
    new: Any = None


class DiffProductOut(BaseModel):
    product_id: str
    fields: list[DiffFieldOut]


class DiffOut(BaseModel):
    version: int
    against: int
    added: list[str]
    removed: list[str]
    changed: list[DiffProductOut]
```

Create `backend/app/routes/export_history.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from registry.loader import load_registry

from ..auth import require_user
from ..config import Settings, get_settings
from ..db.engine import get_db_session
from ..export.service import ExportService
from ..export.store import ExportFileStore
from ..models.feed_source import FeedSource
from ..schemas.export import DiffOut, ExportVersionOut

router = APIRouter()


def _require_db(db_session: AsyncSession | None) -> AsyncSession:
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_session


def _service(request: Request, settings: Settings) -> ExportService:
    return ExportService(
        request.app.state.db_session_factory,
        ExportFileStore(Path(settings.export_dir)),
        request.app.state.clock,
        settings.public_base_url,
    )


async def _require_feed_source(session: AsyncSession, feed_source_id: int) -> None:
    if await session.get(FeedSource, feed_source_id) is None:
        raise HTTPException(status_code=404, detail="feed source not found")


@router.get(
    "/feed-sources/{feed_source_id}/export-history",
    response_model=list[ExportVersionOut],
)
async def export_history(
    feed_source_id: int,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> list:
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
    return await _service(request, settings).list_versions(feed_source_id)


@router.get(
    "/feed-sources/{feed_source_id}/export-history/{version_number}/diff",
    response_model=DiffOut,
)
async def export_diff(
    feed_source_id: int,
    version_number: int,
    request: Request,
    against: int | None = None,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
    try:
        return await _service(request, settings).diff(
            feed_source_id, version_number, against, load_registry()
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

- [ ] **Step 5: Register the router**

In `backend/app/routes/__init__.py` add `from .export_history import router as export_history_router` and include in `__all__`. In `backend/app/main.py` import and `app.include_router(export_history_router)`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_export_history_api.py tests/test_export_service.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/export/service.py backend/app/schemas/export.py backend/app/routes/export_history.py backend/app/routes/__init__.py backend/app/main.py backend/tests/test_export_history_api.py
git commit -m "feat(api): export history list and field-based diff"
```

---

### Task 9: Rollback (append-only)

**Files:**
- Modify: `backend/app/export/service.py`
- Modify: `backend/app/routes/export_history.py`
- Test: `backend/tests/test_export_rollback_api.py`

**Interfaces:**
- Consumes: everything from Tasks 5/8
- Produces: `ExportService.rollback(feed_source_id, version_number, registry) -> ExportVersion` raising `LookupError` for unknown feed source/version/missing file; `POST /feed-sources/{id}/export-history/{v}/rollback` → `ExportVersionOut` (201)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_export_rollback_api.py`:

```python
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clock import TestClock
from app.config import Settings
from app.export.service import ExportService
from app.export.store import ExportFileStore
from app.ingest.xml_reader import parse_xml
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from registry.loader import load_registry

pytestmark = pytest.mark.asyncio

REGISTRY = load_registry()


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
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
        export_dir=str(tmp_path / "exports"),
        public_base_url="http://test.public",
    )
    app = create_app(settings=settings, db_session_factory=factory)
    yield app, factory, settings
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _seed_versions(app_factory, product_sets):
    """Run export_for_run once per product set; returns feed_source_id."""
    _, factory, settings = app_factory
    clock = TestClock(datetime(2026, 8, 27, tzinfo=timezone.utc))
    async with factory() as session:
        async with session.begin():
            client = Client(name="Acme")
            session.add(client)
            await session.flush()
            feed_source = FeedSource(
                client_id=client.id, name="Main", source_format="tsv",
                export_token="tok-rollback-test",
            )
            session.add(feed_source)
            await session.flush()
            feed_source_id = feed_source.id

    service = ExportService(factory, ExportFileStore(settings.export_dir), clock, "http://test.public")
    for products in product_sets:
        async with factory() as session:
            async with session.begin():
                run = IngestionRun(feed_source_id=feed_source_id, status="completed")
                session.add(run)
                await session.flush()
                session.add(ExportRun(
                    feed_source_id=feed_source_id, ingestion_run_id=run.id,
                    status="pending_export", product_count=len(products),
                ))
                run_id = run.id
        await service.export_for_run(feed_source_id, run_id, products, REGISTRY)
    return feed_source_id


BASE = [{"id": "A", "title": "Shirt", "price": "10 USD"}]
CHANGED = [{"id": "A", "title": "Shirt v2", "price": "9 USD"}]


async def test_rollback_creates_new_version_and_republishes_old_content(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    client = await logged_in_client(app_factory)

    resp = await client.post(f"/feed-sources/{feed_source_id}/export-history/1/rollback")
    assert resp.status_code == 201
    body = resp.json()
    assert body["version_number"] == 3
    assert body["source"] == "rollback"
    assert body["source_version_id"] is not None

    _, factory, settings = app_factory
    async with factory() as session:
        versions = list((await session.execute(
            select(ExportVersion).where(ExportVersion.feed_source_id == feed_source_id)
            .order_by(ExportVersion.version_number)
        )).scalars().all())
        runs = list((await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source_id)
            .order_by(ExportRun.id)
        )).scalars().all())

    assert [v.version_number for v in versions] == [1, 2, 3]
    assert versions[2].source_version_id == versions[0].id
    assert versions[2].file_hash == versions[0].file_hash

    rollback_run = runs[-1]
    assert rollback_run.status == "rollback"
    assert rollback_run.ingestion_run_id is None
    assert rollback_run.product_count == 1
    assert rollback_run.critical_finding_count == 0
    assert rollback_run.warning_finding_count == 0
    assert rollback_run.info_finding_count == 0
    assert rollback_run.id == versions[2].export_run_id

    published = ExportFileStore(settings.export_dir).published_path(feed_source_id).read_bytes()
    report = parse_xml(published, REGISTRY)
    assert report.products == [BASE[0]]


async def test_rollback_after_deduplicated_run_still_creates_version(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, BASE])
    client = await logged_in_client(app_factory)

    resp = await client.post(f"/feed-sources/{feed_source_id}/export-history/1/rollback")
    assert resp.status_code == 201
    assert resp.json()["version_number"] == 2
    assert resp.json()["source"] == "rollback"


async def test_rollback_404_for_unknown_version_or_feed_source(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE])
    client = await logged_in_client(app_factory)
    assert (await client.post(f"/feed-sources/{feed_source_id}/export-history/9/rollback")).status_code == 404
    assert (await client.post("/feed-sources/999999/export-history/1/rollback")).status_code == 404


async def test_rollback_respects_retention(app_factory):
    feed_source_id = await _seed_versions(app_factory, [BASE, CHANGED])
    _, factory, settings = app_factory
    async with factory() as session:
        async with session.begin():
            fs = await session.get(FeedSource, feed_source_id)
            fs.history_retention_count = 2

    client = await logged_in_client(app_factory)
    resp = await client.post(f"/feed-sources/{feed_source_id}/export-history/1/rollback")
    assert resp.status_code == 201

    async with factory() as session:
        versions = list((await session.execute(
            select(ExportVersion).where(ExportVersion.feed_source_id == feed_source_id)
            .order_by(ExportVersion.version_number)
        )).scalars().all())
    assert [v.version_number for v in versions] == [2, 3]
    store = ExportFileStore(settings.export_dir)
    assert store.read_version(feed_source_id, 1) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_export_rollback_api.py -v`
Expected: FAIL — 405/404 (rollback route missing).

- [ ] **Step 3: Implement service.rollback**

Append to `ExportService` in `backend/app/export/service.py`:

```python
    async def rollback(
        self, feed_source_id: int, version_number: int, registry: RegistryDocument
    ) -> ExportVersion:
        async with self._session_factory() as session:
            async with session.begin():
                feed_source = await session.get(FeedSource, feed_source_id)
                if feed_source is None:
                    raise LookupError(f"feed source {feed_source_id} not found")
                client = await session.get(Client, feed_source.client_id)
                client_name = client.name if client is not None else ""
                source_version = (
                    await session.execute(
                        select(ExportVersion).where(
                            ExportVersion.feed_source_id == feed_source_id,
                            ExportVersion.version_number == version_number,
                        )
                    )
                ).scalar_one_or_none()
        if source_version is None:
            raise LookupError(f"version {version_number} not found")
        data = self._store.read_version(feed_source_id, version_number)
        if data is None:
            raise LookupError(f"version file {version_number} missing")

        report = parse_xml(data, registry)
        products = list(report.products)
        channel = channel_metadata_for(feed_source, client_name, self._public_base_url)
        rendered = render_feed(products, registry, channel)
        file_hash = hashlib.sha256(rendered).hexdigest()

        new_number: int | None = None
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    locked = (
                        await session.execute(
                            select(FeedSource)
                            .where(FeedSource.id == feed_source_id)
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    if locked is None:
                        raise LookupError(f"feed source {feed_source_id} not found")
                    retention = locked.history_retention_count
                    latest = (
                        await session.execute(
                            select(ExportVersion)
                            .where(ExportVersion.feed_source_id == feed_source_id)
                            .order_by(ExportVersion.version_number.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    new_number = (latest.version_number + 1) if latest is not None else 1
                    self._store.write_version(feed_source_id, new_number, rendered)
                    run = ExportRun(
                        feed_source_id=feed_source_id,
                        ingestion_run_id=None,
                        status="rollback",
                        product_count=len(products),
                    )
                    session.add(run)
                    await session.flush()
                    version = ExportVersion(
                        feed_source_id=feed_source_id,
                        export_run_id=run.id,
                        version_number=new_number,
                        file_hash=file_hash,
                        product_count=len(products),
                        source="rollback",
                        source_version_id=source_version.id,
                    )
                    session.add(version)
                    await session.flush()
        except Exception:
            if new_number is not None:
                self._store.delete_version_file(feed_source_id, new_number)
            raise

        self._store.publish(feed_source_id, rendered)
        await self._prune_retention(feed_source_id, retention)
        return version
```

- [ ] **Step 4: Add the rollback endpoint**

Append to `backend/app/routes/export_history.py`:

```python
@router.post(
    "/feed-sources/{feed_source_id}/export-history/{version_number}/rollback",
    response_model=ExportVersionOut,
    status_code=201,
)
async def export_rollback(
    feed_source_id: int,
    version_number: int,
    request: Request,
    _user: str = Depends(require_user),
    db_session: AsyncSession | None = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    session = _require_db(db_session)
    async with session.begin():
        await _require_feed_source(session, feed_source_id)
    try:
        return await _service(request, settings).rollback(
            feed_source_id, version_number, load_registry()
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_export_rollback_api.py tests/test_export_history_api.py tests/test_export_service.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/export/service.py backend/app/routes/export_history.py backend/tests/test_export_rollback_api.py
git commit -m "feat(api): append-only export rollback with republish"
```

---

### Task 10: M8 acceptance gate + meta gate

**Files:**
- Create: `backend/tests/test_m8_acceptance.py`

**Interfaces:**
- Consumes: the full pipeline (`create_app` + `POST /feed-sources/{id}/run`), public export endpoint, history/diff/rollback endpoints
- Produces: the milestone's "done when" evidence

- [ ] **Step 1: Write the acceptance test**

Create `backend/tests/test_m8_acceptance.py`:

```python
import asyncio
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.ingest.xml_reader import parse_xml
from app.main import create_app
from app.models import Client, ExportRun, ExportVersion, FeedSource, IngestionRun
from app.models.session import Session
from app.models.user import User
from app.persistence.users import seed_initial_user
from registry.loader import load_registry

pytestmark = pytest.mark.asyncio

REGISTRY = load_registry()

WIDE_TSV = (
    "id\ttitle\tdescription\tlink\timage_link\tavailability\tprice\tcondition\tbrand\tgtin\tshipping(country:price)\tshipping(country:price)\n"
    "SKU-1\tRed Shirt\tA red shirt\thttp://shop.example/1\thttp://shop.example/1.jpg\tin_stock\t10.00 USD\tnew\tAcme\t0012345678905\tUS:6.49 USD\tUK:5.99 GBP\n"
    "SKU-2\tBlue Hat\tA blue hat\thttp://shop.example/2\thttp://shop.example/2.jpg\tin_stock\t5.00 USD\tnew\tAcme\t0012345678912\tUS:6.49 USD\n"
).encode("utf-8")

WIDE_TSV_CHANGED = WIDE_TSV.replace(b"10.00 USD\t", b"9.00 USD\t", 1)


class StubFetcher:
    def __init__(self, data: bytes):
        self.data = data

    async def fetch(self, url, basic_auth=None):
        return self.data


@pytest_asyncio.fixture
async def app_factory(isolated_database_url, tmp_path):
    url = isolated_database_url
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(ExportVersion))
            await session.execute(delete(ExportRun))
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
        export_dir=str(tmp_path / "exports"),
        public_base_url="http://test.public",
    )
    fetcher = StubFetcher(WIDE_TSV)
    app = create_app(settings=settings, db_session_factory=factory, fetcher=fetcher)
    yield app, factory, settings, fetcher
    await engine.dispose()


async def logged_in_client(app_factory):
    app, _, _, _ = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _create_feed_source(app_factory):
    client = await logged_in_client(app_factory)
    resp = await client.post("/clients", json={"name": "Acme"})
    assert resp.status_code == 201
    client_id = resp.json()["id"]
    resp = await client.post(
        f"/clients/{client_id}/feed-sources",
        json={"name": "Main", "source_format": "wide_tsv", "currency": "USD"},
    )
    assert resp.status_code == 201
    return client, resp.json()


async def _trigger_run(app_factory, feed_source_id):
    app, factory, _, _ = app_factory
    client = await logged_in_client(app_factory)
    resp = await client.post(f"/feed-sources/{feed_source_id}/run")
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    run = None
    for _ in range(200):
        async with factory() as session:
            run = await session.get(IngestionRun, run_id)
            if run is not None and run.status in ("success", "error"):
                break
        await asyncio.sleep(0.05)
    assert run is not None and run.status == "success", (
        f"run ended in {(run.status if run else 'unknown')}: "
        f"{getattr(run, 'error_message', None)}"
    )
    return run


def _token_of(feed_source_payload):
    return feed_source_payload["export_url"].rsplit("/", 1)[1].removesuffix(".xml")


async def test_full_pipeline_publishes_gmc_xml_at_token_url(app_factory):
    app, factory, _, _ = app_factory
    client, feed_source = await _create_feed_source(app_factory)
    await _trigger_run(app_factory, feed_source["id"])

    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await anonymous.get(f"/export/{_token_of(feed_source)}.xml")
    assert resp.status_code == 200
    body = resp.content
    assert body.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert b'<rss version="2.0" xmlns:g="http://base.google.com/schemas/1.0">' in body
    assert b"<g:id>SKU-1</g:id>" in body

    report = parse_xml(body, REGISTRY)
    assert len(report.products) == 2
    sku1 = next(p for p in report.products if p["id"] == "SKU-1")
    assert sku1["shipping"] == [
        {"country": "US", "price": "6.49 USD"},
        {"country": "UK", "price": "5.99 GBP"},
    ]

    async with factory() as session:
        versions = list((await session.execute(
            select(ExportVersion).where(ExportVersion.feed_source_id == feed_source["id"])
        )).scalars().all())
        runs = list((await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source["id"])
        )).scalars().all())
    assert len(versions) == 1
    assert versions[0].source == "run"
    assert versions[0].product_count == 2
    assert len(runs) == 1
    assert runs[0].status == "completed"
    assert runs[0].export_version_id == versions[0].id


async def test_second_unchanged_run_is_deduplicated(app_factory):
    _, factory, _, _ = app_factory
    _, feed_source = await _create_feed_source(app_factory)
    await _trigger_run(app_factory, feed_source["id"])
    second = await _trigger_run(app_factory, feed_source["id"])

    assert second.statistics["export"]["deduplicated"] is True
    assert second.statistics["export"]["version"] == 1
    async with factory() as session:
        versions = list((await session.execute(
            select(ExportVersion).where(ExportVersion.feed_source_id == feed_source["id"])
        )).scalars().all())
        runs = list((await session.execute(
            select(ExportRun).where(ExportRun.feed_source_id == feed_source["id"])
            .order_by(ExportRun.id)
        )).scalars().all())
    assert len(versions) == 1
    assert len(runs) == 2
    assert runs[1].status == "completed"
    assert runs[1].export_version_id == versions[0].id


async def test_changed_run_creates_version_and_diff_shows_field_change(app_factory):
    app, factory, _, fetcher = app_factory
    client, feed_source = await _create_feed_source(app_factory)
    await _trigger_run(app_factory, feed_source["id"])

    fetcher.data = WIDE_TSV_CHANGED
    await _trigger_run(app_factory, feed_source["id"])

    async with factory() as session:
        versions = list((await session.execute(
            select(ExportVersion).where(ExportVersion.feed_source_id == feed_source["id"])
            .order_by(ExportVersion.version_number)
        )).scalars().all())
    assert [v.version_number for v in versions] == [1, 2]

    resp = await client.get(f"/feed-sources/{feed_source['id']}/export-history/2/diff")
    assert resp.status_code == 200
    body = resp.json()
    changed = {entry["product_id"]: entry["fields"] for entry in body["changed"]}
    fields = {f["field"]: (f["old"], f["new"]) for f in changed["SKU-1"]}
    assert fields["price"] == ("10.00 USD", "9.00 USD")


async def test_rollback_republishes_old_version(app_factory):
    app, factory, _, fetcher = app_factory
    client, feed_source = await _create_feed_source(app_factory)
    await _trigger_run(app_factory, feed_source["id"])
    fetcher.data = WIDE_TSV_CHANGED
    await _trigger_run(app_factory, feed_source["id"])

    resp = await client.post(f"/feed-sources/{feed_source['id']}/export-history/1/rollback")
    assert resp.status_code == 201
    body = resp.json()
    assert body["version_number"] == 3
    assert body["source"] == "rollback"

    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await anonymous.get(f"/export/{_token_of(feed_source)}.xml")
    assert resp.status_code == 200
    report = parse_xml(resp.content, REGISTRY)
    sku1 = next(p for p in report.products if p["id"] == "SKU-1")
    assert sku1["price"] == "10.00 USD"


async def test_rotated_token_invalidates_old_url(app_factory):
    app, _, _, _ = app_factory
    client, feed_source = await _create_feed_source(app_factory)
    await _trigger_run(app_factory, feed_source["id"])
    old_token = _token_of(feed_source)

    resp = await client.post(f"/feed-sources/{feed_source['id']}/export-token/rotate")
    assert resp.status_code == 200
    new_token = resp.json()["export_token"]
    assert new_token != old_token

    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    assert (await anonymous.get(f"/export/{old_token}.xml")).status_code == 404
    assert (await anonymous.get(f"/export/{new_token}.xml")).status_code == 200
```

Note: `create_app(..., fetcher=fetcher)` injects the stub fetcher into `default_steps` (existing M3 pattern); the same `StubFetcher` instance is mutated between runs via `fetcher.data = ...`.

- [ ] **Step 2: Run the acceptance test**

Run: `uv run pytest tests/test_m8_acceptance.py -v`
Expected: all PASS.

- [ ] **Step 3: Run the full backend suite (serial + parallel)**

Run: `uv run pytest -n0 -q` then `uv run pytest -n auto -q` (from `backend/`)
Expected: all tests PASS in both modes. Fix any cross-test interference (e.g. a fixture still missing the `ExportVersion` delete) before continuing.

- [ ] **Step 4: Run the plugin contract suite explicitly**

Run: `uv run pytest tests/test_plugin_contract.py -v`
Expected: PASS (no plugin host changes this milestone).

- [ ] **Step 5: Meta gate**

Run: `uv run python -m compileall -q app tests` and `git diff --check`
Expected: no output, no whitespace errors.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_m8_acceptance.py
git commit -m "test: M8 acceptance gate"
```

- [ ] **Step 7: Record the milestone completion in docs/decisions.md**

Append under the existing `## 2026-08-27` heading:

```markdown
### M8 final verification

- **Topic:** Milestone 8 (XML writer, versioning, atomic publish, export
  endpoint) completion
- **Date:** 2026-08-27
- **Decision:** Recorded as complete. Full pipeline run on a wide-format
  TSV produces GMC-compliant RSS/g: XML, atomically published and
  fetchable via the per-feed-source token URL; versions are deduplicated
  by file_hash; field-based diff and append-only rollback work; token
  rotation invalidates immediately. QC-written ExportRun rows finalize
  via the writer (`pending_export` → `completed`/`failed`). `feed_type`
  column added (default `primary`). Full backend suite green serial and
  parallel; contract suite untouched.
- **Deviations from plan:** none material. (Record any here during
  execution.)
```

Commit: `git add docs/decisions.md && git commit -m "docs: M8 final verification"`.
