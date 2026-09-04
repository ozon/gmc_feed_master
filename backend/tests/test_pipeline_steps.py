import dataclasses
import logging

import pytest

from app.config import DEFAULT_EXPORT_DIR
from app.pipeline import (
    ExportStep,
    IngestStep,
    MappingStep,
    PipelineStep,
    PluginStep,
    QualityCheckStep,
    RunState,
    StagingStep,
    StepContext,
    StepResult,
    default_steps,
)
from registry.model import RegistryDocument


class StubFetcher:
    async def fetch(self, url, basic_auth=None, _client=None):
        return b""


@pytest.fixture
def _steps(tmp_path):
    return default_steps(StubFetcher(), RegistryDocument(attributes={}), export_dir=tmp_path / "exports")


def test_step_context_and_result_are_frozen():
    assert dataclasses.is_dataclass(StepContext)
    assert dataclasses.is_dataclass(StepResult)
    ctx = StepContext(feed_source_id=1, session_factory=lambda: None, logger=logging.getLogger("test"), run_state=RunState())
    result = StepResult()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.feed_source_id = 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.processed_count = 1


def test_step_result_defaults():
    result = StepResult()
    assert result.processed_count == 0
    assert result.failed_count == 0
    assert result.statistics == {}


def test_export_step_is_wired():
    steps = default_steps(StubFetcher(), RegistryDocument(attributes={}), export_dir="unused")
    step = steps[-1]
    assert isinstance(step, ExportStep)
    assert step.name == "export"


def test_default_steps_export_dir_fallback_matches_settings_default():
    steps = default_steps(StubFetcher(), RegistryDocument(attributes={}))
    step = steps[-1]
    assert isinstance(step, ExportStep)
    root = step._store._root
    assert root == DEFAULT_EXPORT_DIR
    assert root.is_absolute()
    assert root.name == "exports"


def test_step_names_are_distinct(_steps):
    names = [step.name for step in _steps]
    assert len(set(names)) == 6


def test_default_steps_order(_steps):
    assert [type(step) for step in _steps] == [
        IngestStep,
        MappingStep,
        StagingStep,
        PluginStep,
        QualityCheckStep,
        ExportStep,
    ]
    assert [step.name for step in _steps] == [
        "ingest",
        "mapping",
        "staging",
        "run_plugins",
        "quality_check",
        "export",
    ]


def test_steps_satisfy_protocol(_steps):
    for step in _steps:
        assert isinstance(step, PipelineStep)


def test_run_state_has_empty_products():
    ctx = StepContext(
        feed_source_id=1,
        session_factory=lambda: None,
        logger=logging.getLogger("test"),
        run_state=RunState(),
    )
    assert ctx.run_state.products == []


class _StatefulPlugin:
    def validate_config(self, config):
        pass

    def prepare_run(self, config, data, ctx):
        return {"suffix": str((config or {}).get("suffix", ""))}

    def process(self, product, config, data, ctx, state=None):
        out = dict(product)
        out["title"] = str(product.get("title", "")) + state["suffix"]
        return out


class _LegacyPlugin:
    def validate_config(self, config):
        pass

    def process(self, product, config, data, ctx):
        return dict(product)


@pytest.mark.asyncio
async def test_plugin_step_calls_prepare_run_once_and_passes_state(monkeypatch):
    async def _noop_outcomes(*args, **kwargs):
        return None

    monkeypatch.setattr("app.pipeline.steps.apply_plugin_outcomes", _noop_outcomes)

    step = PluginStep({"stateful": _StatefulPlugin(), "legacy": _LegacyPlugin()})
    run_state = RunState(
        products=[{"id": "p1", "title": "T"}],
        config_bundle={"instances": [
            {"plugin": "legacy", "resolved_config": {}, "resolved_data": {}},
            {"plugin": "stateful", "resolved_config": {"suffix": "-X"}, "resolved_data": {}},
        ]},
        product_pks={},
    )
    ctx = StepContext(
        feed_source_id=1,
        session_factory=None,
        logger=logging.getLogger("test"),
        run_state=run_state,
    )

    result = await step.execute(ctx)

    assert result.processed_count == 1
    assert run_state.products[0]["title"] == "T-X"


@pytest.mark.asyncio
async def test_plugin_step_legacy_plugins_called_without_state(monkeypatch):
    async def _noop_outcomes(*args, **kwargs):
        return None

    monkeypatch.setattr("app.pipeline.steps.apply_plugin_outcomes", _noop_outcomes)

    seen_kwargs: dict[str, object] = {}

    class _Recorder:
        def validate_config(self, config):
            pass

        def process(self, product, config, data, ctx):
            seen_kwargs["keys"] = list(locals().keys())
            return dict(product)

    step = PluginStep({"rec": _Recorder()})
    run_state = RunState(
        products=[{"id": "p1"}],
        config_bundle={"instances": [{"plugin": "rec", "resolved_config": {}, "resolved_data": {}}]},
        product_pks={},
    )
    ctx = StepContext(
        feed_source_id=1,
        session_factory=None,
        logger=logging.getLogger("test"),
        run_state=run_state,
    )

    result = await step.execute(ctx)

    assert result.processed_count == 1
    assert "state" not in seen_kwargs["keys"]
