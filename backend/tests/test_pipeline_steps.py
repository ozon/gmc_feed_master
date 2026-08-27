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
