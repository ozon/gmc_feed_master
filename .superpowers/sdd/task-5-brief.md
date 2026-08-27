### Task 5: Migration + runtime contract execution

**Files:**
- Create: `backend/alembic/versions/20260827_0001_m6_plugin_host.py`
- Modify: `backend/app/models/staging.py` (two columns)
- Create: `backend/app/plugins/runtime.py`
- Modify: `backend/app/pipeline/steps.py` (`RunState`, `StagingStep`, `PluginStep`, `default_steps`)
- Modify: `backend/app/staging/persistence.py` (`apply_plugin_outcomes`)
- Modify: `backend/app/main.py` (the deferred `default_steps` call-site change)
- Test: `backend/tests/test_m6_migration.py`, `backend/tests/test_plugin_step.py`

**Interfaces:**
- Consumes: M5's `apply_staging_delta(...) -> dict[str, int]` (pk_map), `resolve_config_bundle`.
- Produces:

```python
# runtime.py
@dataclass(frozen=True)
class RunContext:
    client_id: int
    feed_source_id: int
    run_id: int
    logger: logging.Logger
    original_product: dict[str, Any]

# persistence.py
@dataclass(frozen=True)
class PluginOutcome:
    product_id: str
    pk: int
    status: str                    # "processed" | "dropped"
    final_product: dict[str, Any] | None

async def apply_plugin_outcomes(
    session_factory, feed_source_id: int, ingestion_run_id: int,
    outcomes: Sequence[PluginOutcome], *, chunk_size: int = 1000,
) -> None
```

Migration revision `20260827_0001` (down_revision `20260826_0001`):

```python
def upgrade() -> None:
    op.add_column('staging_products', sa.Column('processed_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('staging_products', sa.Column('excluded', sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade() -> None:
    op.drop_column('staging_products', 'excluded')
    op.drop_column('staging_products', 'processed_data')
```

Model additions on `StagingProduct` (after `raw_data`):

```python
    processed_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
```
(import `false` from sqlalchemy alongside existing imports; extend the sqlalchemy import list.)

RunState gains three fields (after `source_fields`):

```python
    client_id: int | None = None
    config_bundle: dict[str, Any] = field(default_factory=dict)
    product_pks: dict[str, int] = field(default_factory=dict)
```

`StagingStep.execute` additions (after resolving `bundle`, before classify):

```python
        ctx.run_state.client_id = feed_source.client_id
        ctx.run_state.config_bundle = bundle
```

and capture the pk map: `pk_map = await apply_staging_delta(...)` followed by `ctx.run_state.product_pks = pk_map`.

`apply_plugin_outcomes` writes, chunked like its sibling (single transaction per chunk):
- `status == "processed"` → UPDATE by pk: `processed_data = final_product`, `excluded = False`, `ingestion_run_id`, `last_seen_at = now`
- `status == "dropped"` → UPDATE by pk: `processed_data = NULL`, `excluded = True`, `ingestion_run_id`
(`now = datetime.now(timezone.utc)` once per call.)

New `PluginStep` (replaces the `_NoOpStep` subclass entirely; constructor takes the shared registry dict):

```python
class PluginStep:
    name = "run_plugins"

    def __init__(self, registry: dict[str, Any] | None = None) -> None:
        self._registry = registry if registry is not None else {}

    async def execute(self, ctx: StepContext) -> StepResult:
        from copy import deepcopy

        bundle = ctx.run_state.config_bundle or {"instances": []}
        pks = ctx.run_state.product_pks
        survivors: list[dict[str, Any]] = []
        outcomes: list[PluginOutcome] = []
        processed = dropped = errored = 0

        for product in ctx.run_state.products:
            pid = product.get("id")
            current = product
            drop = error = False
            for instance in bundle.get("instances", []):
                plugin_obj = self._registry.get(instance["plugin"])
                if plugin_obj is None:
                    continue
                rctx = RunContext(
                    client_id=ctx.run_state.client_id or 0,
                    feed_source_id=ctx.feed_source_id,
                    run_id=ctx.ingestion_run_id,
                    logger=ctx.logger,
                    original_product=deepcopy(product),
                )
                try:
                    result = plugin_obj.process(
                        current,
                        instance["resolved_config"],
                        instance["resolved_data"],
                        rctx,
                    )
                except Exception as exc:
                    ctx.logger.warning(
                        "plugin %s errored on product %s: %s",
                        instance["plugin"], pid, exc,
                    )
                    errored += 1
                    error = True
                    break
                if result is None:
                    drop = True
                    break
                current = result
            if error:
                continue
            pk = pks.get(pid) if isinstance(pid, str) else None
            if drop:
                dropped += 1
                if pk is not None:
                    outcomes.append(PluginOutcome(pid, pk, "dropped", None))
                continue
            processed += 1
            survivors.append(current)
            if pk is not None:
                outcomes.append(PluginOutcome(str(pid), pk, "processed", current))

        await apply_plugin_outcomes(
            ctx.session_factory,
            ctx.feed_source_id,
            ctx.ingestion_run_id,
            outcomes,
        )
        ctx.run_state.products = survivors
        return StepResult(
            processed_count=len(survivors),
            failed_count=errored,
            statistics={
                "plugins": {
                    "processed": processed,
                    "dropped": dropped,
                    "errored": errored,
                }
            },
        )
```

`default_steps` gains an optional third parameter and passes it through:

```python
def default_steps(
    fetcher: HttpFetcher,
    registry: RegistryDocument,
    plugin_registry: dict[str, Any] | None = None,
) -> tuple[PipelineStep, ...]:
    return (
        IngestStep(fetcher, registry),
        MappingStep(registry),
        StagingStep(),
        PluginStep(plugin_registry),
        QualityCheckStep(),
        ExportStep(),
    )
```

Apply the deferred main.py change (pass `app.state.plugin_registry`).

Semantics locked by the design (assert these in tests):
- Survivor of all instances → `processed_data` = final dict, `excluded = False`.
- Any None → chain aborts for that product, `processed_data = NULL`, `excluded = True` (reversible next passing run).
- Exception → chain aborts, NO staging write for that product, counted errored.
- `original_product` equals a deep copy of the product as it entered THIS step, even after earlier instances mutate `current` (test mutates in first instance, asserts `rctx.original_product` unchanged in second).
- Missing registry entry → instance skipped silently for that product (host has no registered plugin; logged skip acceptable).
- Products whose id lacks a staged pk still flow through but get no outcome write.

Testing:
- Migration test mirrors `test_m5_migration.py` (columns present head, absent at `20260826_0001`).
- Unit `test_plugin_step.py`: fake session-free? No — outcomes need DB; use the isolated-database pattern from `test_staging_step.py` (seed client/feed source/run, stage via `StagingStep` first, then run `PluginStep` with fake plugin objects). Cover: transform+persist, drop+persist-clear, exception leaves row untouched + failed_count, multi-instance ordering, original_product immutability, statistics shape, registry-miss skip.
- Full suite serial `-n0`: 366 passed + new tests (M5 acceptance asserts `captured == []` semantics stay intact because registry defaults empty → PluginStep is pass-through when nothing registered; verify `test_m3/m4/m5_acceptance` remain green).

Commits: `feat: processed-output store migration` (migration+models+its test), then `feat: PluginStep executes registered pipeline plugins` (runtime+persistence+wiring+tests).

---

