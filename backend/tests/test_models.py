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


def test_review_contract_fields_and_foreign_key_indexes():
    tables = Base.metadata.tables
    assert {"field_mapping"} <= set(tables["feed_sources"].c.keys())
    assert {"feed_source_id"} <= set(tables["module_pipelines"].c.keys())
    assert {"position"} <= set(tables["module_instances"].c.keys())
    assert {"content_hash", "config_hash", "status", "last_seen_at"} <= set(tables["staging_products"].c.keys())
    assert {"error_message", "error_stack_trace", "processed_count", "failed_count"} <= set(tables["ingestion_runs"].c.keys())
    assert {"ingestion_run_id"} <= set(tables["quality_findings"].c.keys())
    assert {"product_count", "info_finding_count", "warning_finding_count", "error_finding_count", "export_version_id"} <= set(tables["export_runs"].c.keys())
    assert "manifest" in tables["plugins"].c
    for table in (tables["feed_sources"], tables["module_pipelines"], tables["ingestion_runs"], tables["staging_products"], tables["quality_findings"], tables["export_runs"]):
        assert table.indexes


def test_plugin_scope_and_owner_references_are_represented():
    for name in ("plugin_configs", "plugin_data"):
        table = Base.metadata.tables[name]
        assert {"scope", "client_id", "feed_source_id"} <= set(table.c.keys())
        assert {str(f.column) for f in table.c.client_id.foreign_keys} == {"clients.id"}
        assert {str(f.column) for f in table.c.feed_source_id.foreign_keys} == {"feed_sources.id"}


def test_conceptual_json_columns_use_postgresql_jsonb():
    json_columns = [
        Base.metadata.tables["clients"].c.settings,
        Base.metadata.tables["plugin_configs"].c.config,
        Base.metadata.tables["plugin_data"].c.data,
        Base.metadata.tables["module_pipelines"].c.definition,
        Base.metadata.tables["staging_products"].c.raw_data,
        Base.metadata.tables["quality_findings"].c.details,
        Base.metadata.tables["export_runs"].c.options,
        Base.metadata.tables["feed_sources"].c.field_mapping,
        Base.metadata.tables["plugins"].c.manifest,
    ]
    assert all(isinstance(column.type, (JSONB, JSON)) for column in json_columns)
