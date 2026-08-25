import dataclasses
import logging

import pytest

from app.pipeline import (
    DEFAULT_STEPS,
    ExportStep,
    IngestStep,
    PipelineStep,
    PluginStep,
    QualityCheckStep,
    RunState,
    StepContext,
    StepResult,
)


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
@pytest.mark.parametrize(
    "step_cls", [IngestStep, PluginStep, QualityCheckStep, ExportStep]
)
async def test_no_op_steps_contract(step_cls, ctx):
    step = step_cls()
    assert isinstance(step.name, str) and step.name
    result = await step.execute(ctx)
    assert result == StepResult(processed_count=0, failed_count=0)


def test_step_names_are_distinct():
    steps = [IngestStep(), PluginStep(), QualityCheckStep(), ExportStep()]
    names = [step.name for step in steps]
    assert len(set(names)) == 4


def test_default_steps_order():
    assert [type(step) for step in DEFAULT_STEPS] == [
        IngestStep,
        PluginStep,
        QualityCheckStep,
        ExportStep,
    ]
    assert [step.name for step in DEFAULT_STEPS] == [
        "ingest",
        "run_plugins",
        "quality_check",
        "export",
    ]


def test_steps_satisfy_protocol():
    for step in DEFAULT_STEPS:
        assert isinstance(step, PipelineStep)


def test_run_state_has_empty_products():
    ctx = StepContext(
        feed_source_id=1,
        session_factory=lambda: None,
        logger=logging.getLogger("test"),
        run_state=RunState(),
    )
    assert ctx.run_state.products == []
