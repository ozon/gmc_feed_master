from sqlalchemy import JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base
import app.models  # noqa: F401


def test_m1_table_set_is_complete():
    assert set(Base.metadata.tables) == {
        "users", "sessions", "clients", "feed_sources", "plugins",
        "plugin_configs", "plugin_data", "module_pipelines",
        "module_instances", "ingestion_runs", "staging_products",
        "staging_history", "quality_findings", "export_runs",
        "export_versions",
    }


def test_session_stores_hash_and_revocation_generation():
    columns = Base.metadata.tables["sessions"].c
    assert {"token_hash", "user_id", "absolute_expires_at", "revocation_generation"} <= set(columns.keys())
    assert Base.metadata.tables["sessions"].indexes


def test_required_foreign_keys_and_uniqueness():
    feed = Base.metadata.tables["feed_sources"]
    assert {"clients.id"} == {str(f.column) for f in feed.c.client_id.foreign_keys}
    instances = Base.metadata.tables["module_instances"]
    assert {"module_pipelines.id", "plugins.id"} == {
        str(f.column) for c in (instances.c.pipeline_id, instances.c.plugin_id)
        for f in c.foreign_keys
    }
    assert any({"feed_source_id", "product_id"} == {c.name for c in constraint.columns}
               for constraint in Base.metadata.tables["staging_products"].constraints
               if isinstance(constraint, UniqueConstraint))
    assert any({"feed_source_id", "version_number"} == {c.name for c in constraint.columns}
               for constraint in Base.metadata.tables["export_versions"].constraints
               if isinstance(constraint, UniqueConstraint))


def test_conceptual_json_columns_use_postgresql_jsonb():
    json_columns = [
        Base.metadata.tables["clients"].c.settings,
        Base.metadata.tables["plugin_configs"].c.config,
        Base.metadata.tables["plugin_data"].c.data,
        Base.metadata.tables["module_pipelines"].c.definition,
        Base.metadata.tables["staging_products"].c.raw_data,
        Base.metadata.tables["quality_findings"].c.details,
        Base.metadata.tables["export_runs"].c.options,
    ]
    assert all(isinstance(column.type, (JSONB, JSON)) for column in json_columns)
