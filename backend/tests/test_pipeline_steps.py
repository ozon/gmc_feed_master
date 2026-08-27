import dataclasses
import logging

import pytest

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


def _steps():
    return default_steps(StubFetcher(), RegistryDocument(attributes={}))


@pytest.fixture
def ctx():
    return StepContext(
        feed_source_id=1,
        session_factory=lambda: None,
        logger=logging.getLogger("test"),
        run_state=RunState(),
    )


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


@pytest.mark.asyncio
async def test_no_op_steps_contract(ctx):
    step = ExportStep()
    assert isinstance(step.name, str) and step.name
    result = await step.execute(ctx)
    assert result == StepResult(processed_count=0, failed_count=0)


def test_step_names_are_distinct():
    steps = _steps()
    names = [step.name for step in steps]
    assert len(set(names)) == 6


def test_default_steps_order():
    steps = _steps()
    assert [type(step) for step in steps] == [
        IngestStep,
        MappingStep,
        StagingStep,
        PluginStep,
        QualityCheckStep,
        ExportStep,
    ]
    assert [step.name for step in steps] == [
        "ingest",
        "mapping",
        "staging",
        "run_plugins",
        "quality_check",
        "export",
    ]


def test_steps_satisfy_protocol():
    for step in _steps():
        assert isinstance(step, PipelineStep)


def test_run_state_has_empty_products():
    ctx = StepContext(
        feed_source_id=1,
        session_factory=lambda: None,
        logger=logging.getLogger("test"),
        run_state=RunState(),
    )
    assert ctx.run_state.products == []
