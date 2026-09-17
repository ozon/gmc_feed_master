# AI Action in the Rules Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `ai` action op to the Rules plugin that runs a template or an inline custom prompt against matching products, with preview, caching, and a budgeted async step.

**Architecture:** Two-phase. `PluginStep` (sync) records `op=ai` actions into `RunState.rule_ai_pending`; a new async `RuleAiStep` between `PluginStep` and `EnrichmentStep` drains them via `AiService`, writes results into the product, and persists to staging. Template mode uses the four structured AI tasks; custom mode uses a generic inline-only `rule_value` task.

**Tech Stack:** Python 3.10+ / FastAPI / SQLAlchemy 2.0 async / pytest; React 19 / TypeScript / Mantine / TanStack Query / vitest.

**Spec:** `docs/superpowers/specs/2026-09-17-ai-action-rules-plugin-design.md`

## Global Constraints

- Backend commands run from `backend/`; lint gate is hard: `uv run ruff check . ../plugins` and `uv run mypy .` must exit 0.
- No Alembic migration in this cycle: `uv run alembic check` must stay clean.
- Plugin code (`plugins/**`) must not import `app.*` at module import time; `app.*` imports are allowed only lazily inside `register_routes` (see `plugins/core/category/plugin.py:362`).
- Never mutate `ctx.original_product`; `op=ai` must leave the product unchanged in phase 1.
- Reserved plugin route prefixes `/config` and `/data` must not be used.
- All AI calls go through `AiService` so the litellm cache and usage log apply; no direct provider calls.
- `TEST_DATABASE_URL` must point at PostgreSQL; DB tests need the Docker Postgres container running.
- Frontend server state lives only in TanStack Query; no new npm dependencies.
- No code comments unless they explain a non-obvious constraint.

---

## File Structure

**Backend**
- Modify `plugins/core/rules/plugin.py` — `op=ai` types, validation, pending recording, routes.
- Modify `plugins/core/rules/plugin.json` — config schema `then` properties.
- Modify `backend/app/plugins/runtime.py` — `RunContext.run_state`.
- Modify `backend/app/pipeline/steps.py` — `RunState.rule_ai_pending`, `PluginStep` wiring, `RuleAiStep`, `default_steps`.
- Create `backend/app/pipeline/rule_ai.py` — `RuleAiOutcome`, `apply_rule_ai_actions`.
- Modify `backend/app/pipeline/dry_run.py` — insert `RuleAiStep`.
- Modify `backend/app/ai/schemas.py` — `RuleValueResult`.
- Modify `backend/app/ai/service.py` — `resolve_template_by_id`, `_resolve_template(template_id)`, `_execute_task`, `run_inline_task`.
- Create `backend/tests/test_rule_ai_step.py`, `backend/tests/test_rules_ai_routes.py`.
- Modify `backend/tests/test_rules_plugin.py`, `backend/tests/test_ai_service.py`.

**Frontend**
- Modify `plugins/core/rules/frontend/ast.ts`.
- Create `frontend/src/features/rules/hooks.ts`, `RuleAiActionEditor.tsx`, `AiPromptPreview.tsx`, `RuleAiBudget.tsx`.
- Modify `frontend/src/features/rules/RuleEditor.tsx`, `RulesUI.tsx`.
- Modify `frontend/public/locales/en/rules.json`, `frontend/public/locales/de/rules.json`.
- Modify `frontend/src/features/rules/__tests__/ast.test.ts`; create `__tests__/RuleAiActionEditor.test.tsx`, `__tests__/AiPromptPreview.test.tsx`.

**Docs**
- Modify `backend/docs/plugins.md`, `backend/docs/api.md`, `backend/docs/architecture.md`.
- Modify `frontend/docs/plugin-uis.md`, `docs/decisions.md`.
- Create `docs/decisions/0010-ai-action-rules-plugin.md`.

---

### Task 1: Phase 1 — record `op=ai` and extend the runtime channel

**Files:**
- Modify: `plugins/core/rules/plugin.py`
- Modify: `backend/app/plugins/runtime.py`
- Modify: `backend/app/pipeline/steps.py` (RunState + PluginStep RunContext sites)
- Test: `backend/tests/test_rules_plugin.py`

**Interfaces:**
- Consumes: existing `apply_action`, `validate_config`, `RulesPlugin.process`, `PluginStep.execute`.
- Produces: `STRUCTURED_AI_TASKS`, `GENERIC_AI_TASK = "rule_value"`, `_AI_OUTPUT_FIELDS`, `_pending_entry(product, action) -> dict`, `RunContext.run_state: Any`, `RunState.rule_ai_pending: list[dict[str, Any]]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_rules_plugin.py`:

```python
from types import SimpleNamespace


def _ai_state():
    return SimpleNamespace(rule_ai_pending=[])


def _ai_ctx(state):
    return SimpleNamespace(
        client_id=0, feed_source_id=0, run_id=0,
        logger=logging.getLogger("test"), run_state=state,
    )


def test_ai_action_records_pending_and_leaves_product():
    state = _ai_state()
    config = {"rules": [{
        "id": "r1", "name": "n", "isActive": True, "when": {"op": "all"},
        "then": [{
            "op": "ai", "promptSource": "custom", "taskType": "rule_value",
            "field": "title", "system": "sys", "user": "u {{title}}",
            "variables": ["title"],
        }],
    }]}
    out = RulesPlugin().process({"id": "p1", "title": "x"}, config, {}, _ai_ctx(state))
    assert out == {"id": "p1", "title": "x"}
    assert state.rule_ai_pending == [{
        "product_id": "p1", "field": "title", "taskType": "rule_value",
        "promptSource": "custom", "templateId": None, "system": "sys",
        "user": "u {{title}}", "variables": ["title"],
    }]


def test_ai_action_without_run_state_warns(caplog):
    config = {"rules": [{
        "id": "r1", "name": "n", "isActive": True, "when": {"op": "all"},
        "then": [{
            "op": "ai", "promptSource": "template",
            "taskType": "title_optimization", "templateId": 3,
        }],
    }]}
    with caplog.at_level(logging.WARNING, logger="plugin"):
        out = RulesPlugin().process({"id": "p1", "title": "x"}, config, {}, _ctx())
    assert out == {"id": "p1", "title": "x"}
    assert "no run_state" in caplog.text


def test_apply_action_ai_is_passthrough():
    product = {"title": "x"}
    assert apply_action(product, {"op": "ai", "field": "title"}) == product


def test_validate_ai_template_action_ok():
    validate_config({"rules": [{
        "id": "r", "name": "n", "when": {"op": "all"},
        "then": [{"op": "ai", "promptSource": "template",
                  "taskType": "title_optimization", "templateId": 5}],
    }]})


def test_validate_ai_custom_action_ok():
    validate_config({"rules": [{
        "id": "r", "name": "n", "when": {"op": "all"},
        "then": [{"op": "ai", "promptSource": "custom", "taskType": "rule_value",
                  "field": "title", "system": "Be helpful.", "user": "Rewrite {{title}}",
                  "variables": ["title"]}],
    }]})


@pytest.mark.parametrize("action", [
    {"op": "ai", "promptSource": "template", "taskType": "title_optimization"},
    {"op": "ai", "promptSource": "template", "taskType": "rule_value", "templateId": 1},
    {"op": "ai", "promptSource": "custom", "taskType": "title_optimization", "field": "t",
     "system": "s", "user": "u", "variables": ["t"]},
    {"op": "ai", "promptSource": "custom", "taskType": "rule_value",
     "system": "s", "user": "u {{t}}", "variables": ["t"]},
    {"op": "ai", "promptSource": "custom", "taskType": "rule_value", "field": "t",
     "system": "s", "user": "u {{missing}}", "variables": ["t"]},
])
def test_validate_ai_rejects_bad_actions(action):
    with pytest.raises(ValueError):
        validate_config({"rules": [{
            "id": "r", "name": "n", "when": {"op": "all"}, "then": [action],
        }]})


def test_validate_ai_rejects_action_after_ai_on_same_field():
    with pytest.raises(ValueError, match="preceding 'ai'"):
        validate_config({"rules": [{
            "id": "r", "name": "n", "when": {"op": "all"},
            "then": [
                {"op": "ai", "promptSource": "custom", "taskType": "rule_value",
                 "field": "title", "system": "s", "user": "u {{title}}",
                 "variables": ["title"]},
                {"op": "append", "field": "title", "value": "!"},
            ],
        }]})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rules_plugin.py -k "ai" -v`
Expected: FAIL — `ai` is an unknown action op.

- [ ] **Step 3: Implement the plugin changes**

In `plugins/core/rules/plugin.py`, add `import logging` next to `import re`, then after the imports:

```python
logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
_IDENT_RE = re.compile(r"[a-z_][a-z0-9_]*")

STRUCTURED_AI_TASKS: tuple[str, ...] = (
    "title_optimization",
    "description_optimization",
    "category_classification",
    "attribute_enrichment",
)
GENERIC_AI_TASK = "rule_value"

# Local mirror of app/pipeline/enrichment.py::TASK_FIELDS — plugins do not import
# app code. Locked by test_ai_output_fields_mirror_task_fields.
_AI_OUTPUT_FIELDS: dict[str, tuple[str, ...]] = {
    "title_optimization": ("title",),
    "description_optimization": ("description",),
    "category_classification": ("google_product_category",),
    "attribute_enrichment": (
        "color", "size", "material", "gtin", "gender", "age_group",
        "custom_label_0", "custom_label_1", "custom_label_2",
        "custom_label_3", "custom_label_4",
    ),
}
```

Add `"ai": ()` to `_ACTION_REQUIRED_KEYS`:

```python
_ACTION_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "set": ("field", "value"),
    "replace": ("field", "find", "with"),
    "append": ("field", "value"),
    "prepend": ("field", "value"),
    "remove": ("field",),
    "clear": ("field",),
    "ai": (),
}
```

In `apply_action`, immediately after the unknown-op check and before the `field` check, add:

```python
    if op == "ai":
        return dict(product)
```

Add the AI helpers just above `_validate_condition`:

```python
def _ai_output_fields(action: dict[str, Any]) -> tuple[str, ...]:
    if action.get("promptSource") == "custom":
        field = action.get("field")
        return (field,) if isinstance(field, str) and field else ()
    return _AI_OUTPUT_FIELDS.get(str(action.get("taskType")), ())


def _validate_ai_action(action: dict[str, Any], path: str) -> None:
    source = action.get("promptSource")
    if source not in ("template", "custom"):
        raise ValueError(f"{path}: op 'ai' requires promptSource 'template' or 'custom'")
    if source == "template":
        if action.get("taskType") not in STRUCTURED_AI_TASKS:
            raise ValueError(
                f"{path}: op 'ai' template requires taskType in {STRUCTURED_AI_TASKS}"
            )
        template_id = action.get("templateId")
        if isinstance(template_id, bool) or not isinstance(template_id, int):
            raise ValueError(f"{path}: op 'ai' template requires an integer templateId")
        return
    if action.get("taskType") != GENERIC_AI_TASK:
        raise ValueError(
            f"{path}: op 'ai' custom requires taskType {GENERIC_AI_TASK!r}"
        )
    for key in ("system", "user"):
        if not isinstance(action.get(key), str) or not action.get(key):
            raise ValueError(f"{path}: op 'ai' custom requires a non-empty {key}")
    variables = action.get("variables")
    if (
        not isinstance(variables, list)
        or not variables
        or not all(isinstance(v, str) and v for v in variables)
    ):
        raise ValueError(f"{path}: op 'ai' custom requires a non-empty variables list")
    declared = set(variables)
    for name in variables:
        if _IDENT_RE.fullmatch(name) is None:
            raise ValueError(
                f"{path}: op 'ai' variable {name!r} must be a lowercase identifier"
            )
    used = _PLACEHOLDER_RE.findall(action["system"]) + _PLACEHOLDER_RE.findall(action["user"])
    for name in used:
        if name not in declared:
            raise ValueError(
                f"{path}: op 'ai' placeholder {{{{{name}}}}} is not declared in variables"
            )
    if not isinstance(action.get("field"), str) or not action.get("field"):
        raise ValueError(f"{path}: op 'ai' custom requires a non-empty field")


def _pending_entry(product: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_id": str(product.get("id", "")),
        "field": action.get("field") or "",
        "taskType": action.get("taskType"),
        "promptSource": action.get("promptSource"),
        "templateId": action.get("templateId"),
        "system": action.get("system"),
        "user": action.get("user"),
        "variables": list(action.get("variables") or []),
    }
```

In `validate_config`, replace the action loop body:

```python
        then = rule.get("then")
        if not isinstance(then, list):
            raise TypeError(f"{path}.then must be an array")
        ai_outputs: set[str] = set()
        for action_index, action in enumerate(then):
            action_path = f"{path}.then[{action_index}]"
            op = action.get("op") if isinstance(action, dict) else None
            if op == "ai":
                _validate_ai_action(action, action_path)
                ai_outputs.update(_ai_output_fields(action))
                continue
            if op not in _ACTION_REQUIRED_KEYS:
                raise ValueError(f"{action_path}: unknown action op {op!r}")
            for key in _ACTION_REQUIRED_KEYS[op]:
                if key != "field" and action.get(key) is None:
                    raise ValueError(f"{action_path}: op {op!r} requires {key}")
            if not isinstance(action.get("field"), str) or not action.get("field"):
                raise ValueError(f"{action_path}: op {op!r} requires a non-empty field")
            if action["field"] in ai_outputs:
                raise ValueError(
                    f"{action_path}: field {action['field']!r} is written by a "
                    f"preceding 'ai' action; an 'ai' action must be the last write "
                    f"to its field"
                )
            try:
                _parse_indexed(action["field"])
            except ValueError as exc:
                raise ValueError(f"{action_path}: {exc}") from exc
            if op == "replace" and action.get("find") == "":
                raise ValueError(f"{action_path}: op 'replace' requires a non-empty find")
```

Replace `RulesPlugin.process` with:

```python
    def process(
        self,
        product: dict[str, Any],
        config: dict[str, Any],
        data: dict[str, Any],
        ctx: Any,
    ) -> dict[str, Any] | None:
        rules = config.get("rules", []) if isinstance(config, dict) else []
        current = product
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("isActive", True):
                continue
            if not evaluate_condition(rule.get("when", {"op": "all"}), current):
                continue
            for action in rule.get("then", []):
                if isinstance(action, dict) and action.get("op") == "ai":
                    pending = getattr(getattr(ctx, "run_state", None), "rule_ai_pending", None)
                    if pending is None:
                        logger.warning(
                            "rules: ai action on product %s dropped (no run_state)",
                            product.get("id"),
                        )
                    else:
                        pending.append(_pending_entry(current, action))
                    continue
                current = apply_action(current, action)
        return current
```

- [ ] **Step 4: Extend the runtime + pipeline**

In `backend/app/plugins/runtime.py`, add the field to `RunContext`:

```python
    run_state: Any = None
```

In `backend/app/pipeline/steps.py`, add to `RunState`:

```python
    rule_ai_pending: list[dict[str, Any]] = field(default_factory=list)
```

In `PluginStep.execute`, add `run_state=ctx.run_state,` to both `RunContext(...)` constructions (the `prepare_run` one at ~line 221 and the per-product one at ~line 240).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rules_plugin.py -v`
Expected: PASS (old and new tests).

- [ ] **Step 6: Gate + commit**

```bash
uv run ruff check . ../plugins && uv run mypy .
git add plugins/core/rules/plugin.py backend/app/plugins/runtime.py backend/app/pipeline/steps.py backend/tests/test_rules_plugin.py
git commit -m "feat(rules): record ai rule actions in phase one"
```

---

### Task 2: AI service — pinned template, inline task, generic result model

**Files:**
- Modify: `backend/app/ai/schemas.py`
- Modify: `backend/app/ai/service.py`
- Test: `backend/tests/test_ai_service.py`

**Interfaces:**
- Consumes: `resolve_active_template`, `render_messages`, `NativeCache`, `TASK_SPECS`.
- Produces: `RuleValueResult(BaseModel)` with field `value: str`; `resolve_template_by_id(session_factory, template_id, client_id) -> ResolvedTemplate | None`; `AiService.run_task(..., template_id=None)`; `AiService.run_inline_task(system, user, variables, *, client_id=None, feed_source_id=None) -> AiResult`; `GENERIC_AI_TASK = "rule_value"` in `service.py`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_ai_service.py`:

```python
from app.ai.schemas import RuleValueResult


@pytest.mark.asyncio
async def test_run_task_passes_pinned_template_id(service, monkeypatch) -> None:
    resolve = AsyncMock(return_value=ai_service_module.ResolvedTemplate("sys", "user", "v1"))
    monkeypatch.setattr(service, "_resolve_template", resolve)
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(
        return_value=(_FakeModel(value="ok"), SimpleNamespace(usage=None, model="m"))
    )
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    await service.run_task("title_optimization", {"title": "t"}, template_id=7)
    resolve.assert_awaited_once_with("title_optimization", None, 7)


@pytest.mark.asyncio
async def test_run_inline_task_returns_value(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    instructor_client = MagicMock()
    instructor_client.create_with_completion = AsyncMock(
        return_value=(
            RuleValueResult(value="Blue"),
            SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2), model="m"
            ),
        )
    )
    monkeypatch.setattr(service, "_instructor", lambda: instructor_client)

    result = await service.run_inline_task("sys", "Title {{title}}", {"title": "Hat"})
    assert result.status == "ok"
    assert result.value.value == "Blue"
    assert result.prompt_tokens == 3


@pytest.mark.asyncio
async def test_run_inline_task_missing_variable_is_fallback(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=_provider_rows()))
    result = await service.run_inline_task("sys", "Title {{title}}", {})
    assert result.status == "fallback"
    assert result.error_code == "invalid_task"


@pytest.mark.asyncio
async def test_run_inline_task_no_provider_is_fallback(service, monkeypatch) -> None:
    monkeypatch.setattr(service, "_load_deployments", AsyncMock(return_value=[]))
    result = await service.run_inline_task("sys", "u", {})
    assert result.status == "fallback"
    assert result.error_code == "no_provider"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ai_service.py -k "inline or pinned" -v`
Expected: FAIL — `RuleValueResult` / `run_inline_task` do not exist; `run_task` has no `template_id`.

- [ ] **Step 3: Add the result model**

At the end of `backend/app/ai/schemas.py`, after `ImageQualityResult`, add:

```python
class RuleValueResult(BaseModel):
    value: str
```

Do **not** add it to `RESPONSE_MODELS`/`TASK_SPECS`: `rule_value` is inline-only and must have no DB template.

- [ ] **Step 4: Add pinned-template resolution**

In `backend/app/ai/service.py`, import the model:

```python
from .schemas import RuleValueResult
```

Add next to `resolve_active_template`:

```python
async def resolve_template_by_id(
    session_factory: Callable[[], AsyncSession],
    template_id: int,
    client_id: int | None,
) -> ResolvedTemplate | None:
    """Load one pinned template, scoped to global or the given client.

    Returns None (caller falls back to active/builtin) on any miss or DB error.
    """
    try:
        async with session_factory() as session:
            row = await session.get(PromptTemplate, template_id)
    except Exception:
        logger.exception("ai pinned template lookup failed; using active/builtin")
        return None
    if row is None or not row.is_active:
        return None
    if row.client_id is not None and row.client_id != client_id:
        return None
    return ResolvedTemplate(
        system=row.system_prompt,
        user=row.user_prompt,
        version=f"tmpl:{row.id}:v{row.version}",
    )
```

- [ ] **Step 5: Refactor `_resolve_template`, `run_task`; add `_execute_task` + `run_inline_task`**

Add the constant near `TIER_BULK`:

```python
GENERIC_AI_TASK = "rule_value"
```

Replace `_resolve_template` with:

```python
    async def _resolve_template(
        self, task_type: str, client_id: int | None, template_id: int | None = None
    ) -> ResolvedTemplate:
        if task_type not in TASK_SPECS:
            raise TaskSpecError(f"unknown task type {task_type!r}")
        if template_id is not None:
            pinned = await resolve_template_by_id(
                self._session_factory, template_id, client_id
            )
            if pinned is not None:
                return pinned
            logger.warning(
                "ai: pinned template %s unavailable; using active/builtin", template_id
            )
        resolved = await resolve_active_template(
            self._session_factory, task_type, client_id
        )
        if resolved is not None:
            return resolved
        spec = TASK_SPECS[task_type]
        return ResolvedTemplate(
            system=spec.system, user=spec.user, version=builtin_template_version(spec)
        )
```

Replace `run_task` and add `_execute_task` + `run_inline_task`:

```python
    async def run_task(
        self,
        task_type: str,
        variables: dict[str, Any],
        *,
        client_id: int | None = None,
        feed_source_id: int | None = None,
        template_id: int | None = None,
    ) -> AiResult:
        if task_type not in TASK_SPECS:
            await self._log_error(task_type, client_id, feed_source_id, "invalid_task")
            return AiResult(value=None, status="fallback", error_code="invalid_task",
                            prompt_tokens=0, completion_tokens=0)
        try:
            template = await self._resolve_template(task_type, client_id, template_id)
            messages = render_messages(template.system, template.user, variables)
        except TaskSpecError:
            logger.exception("ai task %s could not render; falling back", task_type)
            await self._log_error(task_type, client_id, feed_source_id, "invalid_task")
            return AiResult(value=None, status="fallback", error_code="invalid_task",
                            prompt_tokens=0, completion_tokens=0)
        return await self._execute_task(
            log_task_type=task_type,
            cache_task_type=task_type,
            response_model=TASK_SPECS[task_type].response_model,
            messages=messages,
            client_id=client_id,
            feed_source_id=feed_source_id,
        )

    async def run_inline_task(
        self,
        system: str,
        user: str,
        variables: dict[str, Any],
        *,
        client_id: int | None = None,
        feed_source_id: int | None = None,
    ) -> AiResult:
        try:
            messages = render_messages(system, user, variables)
        except TaskSpecError:
            logger.exception("ai inline task could not render; falling back")
            await self._log_error(GENERIC_AI_TASK, client_id, feed_source_id, "invalid_task")
            return AiResult(value=None, status="fallback", error_code="invalid_task",
                            prompt_tokens=0, completion_tokens=0)
        return await self._execute_task(
            log_task_type=GENERIC_AI_TASK,
            cache_task_type=GENERIC_AI_TASK,
            response_model=RuleValueResult,
            messages=messages,
            client_id=client_id,
            feed_source_id=feed_source_id,
        )

    async def _execute_task(
        self,
        *,
        log_task_type: str,
        cache_task_type: str,
        response_model: type[Any],
        messages: list[dict[str, str]],
        client_id: int | None,
        feed_source_id: int | None,
    ) -> AiResult:
        rows = await self._load_deployments()
        if not rows:
            await self._log_error(log_task_type, client_id, feed_source_id, "no_provider")
            return AiResult(value=None, status="fallback", error_code="no_provider",
                            prompt_tokens=0, completion_tokens=0)

        cfg = self._router_settings or await load_router_settings(self._session_factory)
        if self._router is None:
            try:
                self._ensure_built(rows, cfg)
            except Exception as exc:
                logger.warning("ai router build failed: %s", exc, exc_info=True)
                await self._log_error(log_task_type, client_id, feed_source_id, "provider_error")
                return AiResult(value=None, status="fallback", error_code="provider_error",
                                prompt_tokens=0, completion_tokens=0)
        await self._ensure_cache()

        cache_kwargs = self._cache.request_kwargs(cache_task_type)
        cache_request = {"model": TIER_BULK, "messages": messages, **cache_kwargs}

        cached = await self._cache.lookup(**cache_request)
        if cached is not None:
            try:
                value = response_model.model_validate(cached)
            except Exception:  # noqa: BLE001 — any invalid cached payload is a miss
                value = None
            if value is not None:
                await self._log_usage(UsageRecord(
                    client_id=client_id, feed_source_id=feed_source_id,
                    task_type=log_task_type, provider_config_id=None, model=TIER_BULK,
                    cache_hit=True, prompt_tokens=0, completion_tokens=0,
                    cost_usd=None, latency_ms=0, error_code=None,
                ))
                return AiResult(value=value, status="cache_hit", error_code=None,
                                prompt_tokens=0, completion_tokens=0)

        started = time.monotonic()
        try:
            value, completion = await self._instructor().create_with_completion(
                response_model=response_model,
                messages=messages,
                model=TIER_BULK,
                max_retries=cfg.instructor_max_retries,
            )
        except Exception as exc:
            logger.warning("ai task %s failed: %s", log_task_type, exc, exc_info=True)
            await self._log_error(log_task_type, client_id, feed_source_id, "provider_error")
            return AiResult(value=None, status="fallback", error_code="provider_error",
                            prompt_tokens=0, completion_tokens=0)

        latency_ms = int((time.monotonic() - started) * 1000)
        await self._cache.store(value.model_dump(), **cache_request)
        usage = getattr(completion, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        await self._log_usage(UsageRecord(
            client_id=client_id, feed_source_id=feed_source_id,
            task_type=log_task_type, provider_config_id=None, model=TIER_BULK,
            cache_hit=False, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens, cost_usd=None,
            latency_ms=latency_ms, error_code=None,
        ))
        return AiResult(value=value, status="ok", error_code=None,
                        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ai_service.py tests/test_ai_tasks.py tests/test_ai_cache.py -v`
Expected: PASS, including all pre-existing tests (the refactor preserves behavior).

- [ ] **Step 7: Gate + commit**

```bash
uv run ruff check . ../plugins && uv run mypy .
git add backend/app/ai/schemas.py backend/app/ai/service.py backend/tests/test_ai_service.py
git commit -m "feat(ai): pinned template + inline rule_value task"
```

---

### Task 3: Phase 2 — `RuleAiStep` engine and wiring

**Files:**
- Create: `backend/app/pipeline/rule_ai.py`
- Modify: `backend/app/pipeline/steps.py` (`RuleAiStep`, `default_steps`)
- Modify: `backend/app/pipeline/dry_run.py`
- Modify: `backend/docs/architecture.md`
- Test: `backend/tests/test_rule_ai_step.py`

**Interfaces:**
- Consumes: `RunState.rule_ai_pending`, `RunState.products`, `RunState.product_pks`, `AiService.run_task`, `AiService.run_inline_task`, `TASK_FIELDS`, `CANONICAL_VARIABLES`, `apply_plugin_outcomes`, `PluginOutcome`.
- Produces: `RuleAiOutcome(products, applied, failed, spent)`; `apply_rule_ai_actions(*, ai_service, products, pending, limit, budget, client_id, feed_source_id) -> tuple[dict[str, dict], RuleAiOutcome]`; `RuleAiStep(ai_service)` with `name == "rule_ai"`.

- [ ] **Step 1: Write the failing engine + step tests**

Create `backend/tests/test_rule_ai_step.py`:

```python
"""RuleAiStep: AI rule action engine, budget/limit, fallback isolation, persistence."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.schemas import EnrichedAttributes, OptimizedTitle, RuleValueResult
from app.ai.service import AiResult
from app.models.client import Client
from app.models.feed_source import FeedSource
from app.models.ingestion import IngestionRun
from app.models.staging import StagingProduct
from app.pipeline.rule_ai import apply_rule_ai_actions
from app.pipeline.steps import RuleAiStep, RunState, StepContext


def _result(value, status="ok"):
    return AiResult(value=value, status=status, error_code=None if status == "ok" else "x",
                    prompt_tokens=1, completion_tokens=1)


class FakeAi:
    def __init__(self, script):
        self._script = list(script)
        self.calls: list[dict] = []

    async def run_task(self, task_type, variables, *, client_id=None, feed_source_id=None,
                       template_id=None):
        self.calls.append({"task": task_type, "template_id": template_id, "vars": dict(variables)})
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def run_inline_task(self, system, user, variables, *, client_id=None,
                              feed_source_id=None):
        self.calls.append({"inline": system, "vars": dict(variables)})
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_TEMPLATE_ENTRY = {
    "product_id": "p1", "field": "", "taskType": "title_optimization",
    "promptSource": "template", "templateId": 5, "system": None, "user": None,
    "variables": [],
}
_CUSTOM_ENTRY = {
    "product_id": "p1", "field": "custom_label_0", "taskType": "rule_value",
    "promptSource": "custom", "templateId": None, "system": "sys",
    "user": "Brand {{title}}", "variables": ["title"],
}


def _products():
    return [{"id": "p1", "title": "Red Socks"}, {"id": "p2", "title": "Blue Hat"}]


@pytest.mark.asyncio
async def test_template_entry_maps_task_fields() -> None:
    ai = FakeAi([_result(OptimizedTitle(title="Red Wool Socks"))])
    changed, outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=[dict(_TEMPLATE_ENTRY)],
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert changed["p1"]["title"] == "Red Wool Socks"
    assert outcome == RuleAiOutcome(products=1, applied=1, failed=0, spent=1)
    assert ai.calls[0]["template_id"] == 5


@pytest.mark.asyncio
async def test_custom_entry_writes_target_field() -> None:
    ai = FakeAi([_result(RuleValueResult(value="Acme"))])
    changed, outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=[dict(_CUSTOM_ENTRY)],
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert changed["p1"]["custom_label_0"] == "Acme"
    assert ai.calls[0]["vars"] == {"title": "Red Socks"}
    assert outcome.spent == 1


@pytest.mark.asyncio
async def test_budget_stops_between_products() -> None:
    ai = FakeAi([_result(OptimizedTitle(title="A")), _result(OptimizedTitle(title="B"))])
    pending = [dict(_TEMPLATE_ENTRY), {**_TEMPLATE_ENTRY, "product_id": "p2"}]
    changed, outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=pending,
        limit=50, budget=1, client_id=1, feed_source_id=7,
    )
    assert set(changed) == {"p1"}
    assert outcome.spent == 1
    assert outcome.products == 1


@pytest.mark.asyncio
async def test_cache_hit_is_free() -> None:
    ai = FakeAi([_result(OptimizedTitle(title="A"), status="cache_hit")])
    changed, outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=[dict(_TEMPLATE_ENTRY)],
        limit=50, budget=1, client_id=1, feed_source_id=7,
    )
    assert outcome.spent == 0
    assert changed["p1"]["title"] == "A"


@pytest.mark.asyncio
async def test_failure_is_isolated() -> None:
    ai = FakeAi([RuntimeError("boom"), _result(OptimizedTitle(title="B"))])
    pending = [dict(_TEMPLATE_ENTRY), {**_TEMPLATE_ENTRY, "product_id": "p2"}]
    changed, outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=pending,
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert outcome.failed == 1
    assert changed["p2"]["title"] == "B"


@pytest.mark.asyncio
async def test_attribute_enrichment_merges_multiple_fields() -> None:
    ai = FakeAi([_result(EnrichedAttributes(color="Red", gender="unisex", size=None))])
    entry = {**_TEMPLATE_ENTRY, "taskType": "attribute_enrichment", "templateId": None}
    changed, _outcome = await apply_rule_ai_actions(
        ai_service=ai, products=_products(), pending=[entry],
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert changed["p1"]["color"] == "Red"
    assert changed["p1"]["gender"] == "unisex"
    assert "size" not in changed["p1"]


@pytest.mark.asyncio
async def test_no_service_is_empty() -> None:
    changed, outcome = await apply_rule_ai_actions(
        ai_service=None, products=_products(), pending=[dict(_CUSTOM_ENTRY)],
        limit=50, budget=50, client_id=1, feed_source_id=7,
    )
    assert changed == {}
    assert outcome == RuleAiOutcome(products=0, applied=0, failed=0, spent=0)


def test_ai_output_fields_mirror_task_fields() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/core/rules"))
    import plugin

    from app.pipeline.enrichment import TASK_FIELDS

    assert plugin._AI_OUTPUT_FIELDS == {k: tuple(v) for k, v in TASK_FIELDS.items()}


@pytest_asyncio.fixture
async def db(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        client = Client(name="c1")
        session.add(client)
        await session.flush()
        feed = FeedSource(client_id=client.id, name="f1", source_format="csv",
                          configuration={"ai_rules": {"enabled": True}})
        session.add(feed)
        await session.flush()
        run = IngestionRun(feed_source_id=feed.id, status="success",
                           started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()
        rows = []
        for pid in ("p1", "p2"):
            row = StagingProduct(
                feed_source_id=feed.id, ingestion_run_id=run.id, product_id=pid,
                content_hash="x", config_hash="x", status="active", excluded=False,
                raw_data={"id": pid, "title": pid}, processed_data={"id": pid, "title": pid},
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        ids = {"client_id": client.id, "feed_id": feed.id, "run_id": run.id,
               "pks": {r.product_id: r.id for r in rows}}
    yield factory, ids
    await engine.dispose()


def _ctx(factory, ids, *, dry_run=False):
    state = RunState(products=_products(), client_id=ids["client_id"],
                     product_pks=ids["pks"], rule_ai_pending=[dict(_TEMPLATE_ENTRY)])
    return StepContext(feed_source_id=ids["feed_id"], session_factory=factory,
                       logger=logging.getLogger("test"), run_state=state,
                       ingestion_run_id=ids["run_id"], dry_run=dry_run)


@pytest.mark.asyncio
async def test_step_persists_processed_data(db) -> None:
    factory, ids = db
    ai = FakeAi([_result(OptimizedTitle(title="New"))])
    ctx = _ctx(factory, ids)
    result = await RuleAiStep(ai).execute(ctx)
    assert result.statistics["ai_rules"]["applied"] == 1
    assert ctx.run_state.products[0]["title"] == "New"
    async with factory() as session:
        row = await session.get(StagingProduct, ids["pks"]["p1"])
        assert row.processed_data["title"] == "New"


@pytest.mark.asyncio
async def test_step_disabled_is_noop(db) -> None:
    factory, ids = db
    async with factory() as session, session.begin():
        feed = await session.get(FeedSource, ids["feed_id"])
        feed.configuration = {"ai_rules": {"enabled": False}}
    ai = FakeAi([_result(OptimizedTitle(title="New"))])
    ctx = _ctx(factory, ids)
    result = await RuleAiStep(ai).execute(ctx)
    assert result.statistics["ai_rules"]["enabled"] is False
    assert ctx.run_state.products[0]["title"] == "Red Socks"


@pytest.mark.asyncio
async def test_step_dry_run_does_not_persist(db) -> None:
    factory, ids = db
    ai = FakeAi([_result(OptimizedTitle(title="New"))])
    ctx = _ctx(factory, ids, dry_run=True)
    await RuleAiStep(ai).execute(ctx)
    assert ctx.run_state.products[0]["title"] == "New"
    async with factory() as session:
        row = await session.get(StagingProduct, ids["pks"]["p1"])
        assert row.processed_data["title"] == "p1"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rule_ai_step.py -v`
Expected: FAIL — `app.pipeline.rule_ai` and `RuleAiStep` do not exist.

- [ ] **Step 3: Implement the engine**

Create `backend/app/pipeline/rule_ai.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..ai.tasks import CANONICAL_VARIABLES
from .enrichment import TASK_FIELDS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuleAiOutcome:
    products: int
    applied: int
    failed: int
    spent: int


async def _run_entry(
    ai_service: Any,
    entry: dict[str, Any],
    product: dict[str, Any],
    client_id: int | None,
    feed_source_id: int | None,
) -> tuple[dict[str, Any], str]:
    if entry.get("promptSource") == "template":
        task_type = str(entry.get("taskType"))
        variables = {
            name: product.get(name) for name in CANONICAL_VARIABLES.get(task_type, [])
        }
        result = await ai_service.run_task(
            task_type, variables, client_id=client_id,
            feed_source_id=feed_source_id, template_id=entry.get("templateId"),
        )
    else:
        variables = {
            name: product.get(name) for name in (entry.get("variables") or [])
        }
        result = await ai_service.run_inline_task(
            entry.get("system") or "", entry.get("user") or "", variables,
            client_id=client_id, feed_source_id=feed_source_id,
        )
    if result.value is None:
        return {}, result.status
    if entry.get("promptSource") == "template":
        task_type = str(entry.get("taskType"))
        dumped = result.value.model_dump() if hasattr(result.value, "model_dump") else {}
        updates = {
            field: str(dumped[field])
            for field in TASK_FIELDS.get(task_type, ())
            if dumped.get(field) not in (None, "")
        }
        return updates, result.status
    value = getattr(result.value, "value", None)
    field = entry.get("field")
    if value in (None, "") or not field:
        return {}, result.status
    return {str(field): str(value)}, result.status


async def apply_rule_ai_actions(
    *,
    ai_service: Any,
    products: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    limit: int,
    budget: int,
    client_id: int | None,
    feed_source_id: int | None,
) -> tuple[dict[str, dict[str, Any]], RuleAiOutcome]:
    if ai_service is None:
        return {}, RuleAiOutcome(products=0, applied=0, failed=0, spent=0)

    by_id = {str(p.get("id", "")): p for p in products if p.get("id") is not None}
    order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in pending:
        pid = entry.get("product_id")
        if not isinstance(pid, str) or pid not in by_id:
            continue
        if pid not in grouped:
            order.append(pid)
            grouped[pid] = []
        grouped[pid].append(entry)

    changed: dict[str, dict[str, Any]] = {}
    touched = applied = failed = spent = 0
    for pid in order:
        if touched >= limit or spent >= budget:
            break
        current = by_id[pid]
        product_changed = False
        for entry in grouped[pid]:
            if spent >= budget:
                break
            try:
                updates, status = await _run_entry(
                    ai_service, entry, current, client_id, feed_source_id
                )
            except Exception:
                logger.warning("rule_ai: entry failed for product %s", pid, exc_info=True)
                failed += 1
                continue
            if status == "fallback":
                failed += 1
                continue
            if status == "ok":
                spent += 1
            if updates:
                current = {**current, **updates}
                product_changed = True
                applied += 1
        touched += 1
        if product_changed:
            changed[pid] = current
    return changed, RuleAiOutcome(
        products=touched, applied=applied, failed=failed, spent=spent
    )
```

- [ ] **Step 4: Add `RuleAiStep` and wire the pipeline**

In `backend/app/pipeline/steps.py`, add after `EnrichmentStep`:

```python
class RuleAiStep:
    name = "rule_ai"

    def __init__(self, ai_service: Any = None) -> None:
        self._ai_service = ai_service

    async def execute(self, ctx: StepContext) -> StepResult:
        from .rule_ai import apply_rule_ai_actions

        async with ctx.session_factory() as session, session.begin():
            feed_source = await session.get(FeedSource, ctx.feed_source_id)
        if feed_source is None:
            raise LookupError(f"feed source {ctx.feed_source_id} not found")

        cfg = (feed_source.configuration or {}).get("ai_rules") or {}
        pending = ctx.run_state.rule_ai_pending
        if not cfg.get("enabled") or self._ai_service is None:
            return StepResult(statistics={"ai_rules": {
                "enabled": False, "products": 0, "applied": 0, "failed": 0, "spent": 0,
            }})
        if not pending:
            return StepResult(statistics={"ai_rules": {
                "enabled": True, "products": 0, "applied": 0, "failed": 0, "spent": 0,
            }})

        limit = max(1, int(cfg.get("limit", 50)))
        budget = max(1, int(cfg.get("budget", 50)))
        changed, outcome = await apply_rule_ai_actions(
            ai_service=self._ai_service,
            products=ctx.run_state.products,
            pending=pending,
            limit=limit,
            budget=budget,
            client_id=ctx.run_state.client_id,
            feed_source_id=ctx.feed_source_id,
        )
        if changed:
            ctx.run_state.products = [
                changed.get(str(p.get("id", "")), p) for p in ctx.run_state.products
            ]
        if changed and not ctx.dry_run:
            from ..staging.persistence import PluginOutcome, apply_plugin_outcomes

            outcomes = [
                PluginOutcome(pid, ctx.run_state.product_pks[pid], "processed", prod)
                for pid, prod in changed.items()
                if pid in ctx.run_state.product_pks
            ]
            if outcomes:
                await apply_plugin_outcomes(
                    ctx.session_factory, ctx.feed_source_id,
                    ctx.ingestion_run_id, outcomes,
                )
        return StepResult(
            processed_count=outcome.applied,
            failed_count=outcome.failed,
            statistics={"ai_rules": {
                "enabled": True,
                "products": outcome.products,
                "applied": outcome.applied,
                "failed": outcome.failed,
                "spent": outcome.spent,
            }},
        )
```

In `default_steps`, insert after `PluginStep(plugin_registry),`:

```python
        RuleAiStep(ai_service),
```

In `backend/app/pipeline/dry_run.py`, import `RuleAiStep` and call it between `PluginStep` and the `processed = list(run_state.products)` capture:

```python
    await RuleAiStep(ai_service).execute(ctx)
    processed = list(run_state.products)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rule_ai_step.py tests/test_pipeline_steps.py tests/test_enrichment_step.py -v`
Expected: PASS.

- [ ] **Step 6: Update architecture docs + gate + commit**

In `backend/docs/architecture.md`, add `RuleAiStep` between `PluginStep` and `EnrichmentStep` in the stage list: "drains `op=ai` rule actions through `AiService` (budgeted, cached), writes target fields, persists to staging."

```bash
uv run ruff check . ../plugins && uv run mypy . && uv run alembic check
git add backend/app/pipeline/rule_ai.py backend/app/pipeline/steps.py backend/app/pipeline/dry_run.py backend/tests/test_rule_ai_step.py backend/docs/architecture.md
git commit -m "feat(pipeline): rule_ai step executes ai rule actions"
```

---

### Task 4: Rules plugin routes — template list + render-only preview

**Files:**
- Modify: `plugins/core/rules/plugin.py` (`RulesPlugin.register_routes`)
- Modify: `backend/docs/api.md`, `backend/docs/plugins.md`
- Test: `backend/tests/test_rules_ai_routes.py`

**Interfaces:**
- Consumes: `ensure_feed_source_access`, `get_current_user`, `get_db_session`, `PromptTemplate`, `FeedSource`, `StagingProduct`, `CANONICAL_VARIABLES`, `render_messages`, `validate_template`, `parse_placeholders`, `GENERIC_AI_TASK`.
- Produces: `GET /plugins/rules/ai/templates`, `POST /plugins/rules/ai/preview`.

- [ ] **Step 1: Write the failing route tests**

Create `backend/tests/test_rules_ai_routes.py`:

```python
"""Rules plugin AI routes: template listing and render-only preview."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.models import Client, FeedSource, IngestionRun
from app.models.ai import PromptTemplate
from app.models.plugin import Plugin as PluginRow
from app.models.staging import StagingProduct
from app.persistence.users import seed_initial_user

pytestmark = pytest.mark.asyncio

_spec = importlib.util.spec_from_file_location(
    "rules_plugin_ai", Path(__file__).resolve().parents[2] / "plugins/core/rules/plugin.py"
)
assert _spec is not None and _spec.loader is not None
_rules_module = importlib.util.module_from_spec(_spec)
sys.modules["rules_plugin_ai"] = _rules_module
_spec.loader.exec_module(_rules_module)
RulesPlugin = _rules_module.RulesPlugin


@pytest_asyncio.fixture
async def app_factory(isolated_database_url):
    engine = create_async_engine(isolated_database_url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed_initial_user(session, "operator", "pw")
    manifest = json.loads(
        (Path(__file__).resolve().parents[2] / "plugins/core/rules/plugin.json").read_text()
    )
    async with factory() as session, session.begin():
        session.add(PluginRow(name="rules", version="1.0.0", manifest=manifest))
    settings = Settings(_env_file=None, session_secret="test-secret",
                        initial_username="operator", initial_password="pw",
                        database_url=isolated_database_url)
    app = create_app(settings=settings, db_session_factory=factory)
    router = APIRouter()
    RulesPlugin().register_routes(router)
    app.include_router(router, prefix="/plugins/rules")
    yield app, factory
    await engine.dispose()


async def _login(app_factory):
    app, _factory = app_factory
    client = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
    resp = await client.post("/auth/login", json={"username": "operator", "password": "pw"})
    assert resp.status_code == 200
    return client


async def _feed(factory, client):
    created = (await client.post("/clients", json={"name": "Acme"})).json()
    feed = (await client.post(f"/clients/{created['id']}/feed-sources",
                              json={"name": "DE", "source_format": "wide_tsv"})).json()
    async with factory() as session, session.begin():
        run = IngestionRun(feed_source_id=feed["id"], status="success",
                           started_at=datetime.now(timezone.utc))
        session.add(run)
        await session.flush()
        session.add(StagingProduct(
            feed_source_id=feed["id"], ingestion_run_id=run.id, product_id="p1",
            content_hash="x", config_hash="x", status="active", excluded=False,
            raw_data={"id": "p1", "title": "Red Socks"},
        ))
        session.add(PromptTemplate(
            task_type="title_optimization", client_id=None, version=1, name="T1",
            system_prompt="sys", user_prompt="Rewrite {{title}}",
            variables=["title"], is_active=True,
        ))
    return feed


async def test_templates_lists_global(app_factory):
    client = await _login(app_factory)
    feed = await _feed(app_factory[1], client)
    resp = await client.get(
        f"/plugins/rules/ai/templates?feed_source_id={feed['id']}"
        "&task_type=title_optimization"
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["name"] for i in items] == ["T1"]


async def test_templates_rejects_unknown_task_type(app_factory):
    client = await _login(app_factory)
    feed = await _feed(app_factory[1], client)
    resp = await client.get(
        f"/plugins/rules/ai/templates?feed_source_id={feed['id']}&task_type=nope"
    )
    assert resp.status_code == 422


async def test_preview_renders_template_without_ai_call(app_factory):
    client = await _login(app_factory)
    feed = await _feed(app_factory[1], client)
    resp = await client.post("/plugins/rules/ai/preview", json={
        "feed_source_id": feed["id"], "taskType": "title_optimization", "templateId": 1,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "Red Socks" in body["messages"][1]["content"]
    assert body["errors"] == []


async def test_preview_missing_feed_source_is_distinct_404(app_factory):
    client = await _login(app_factory)
    resp = await client.post("/plugins/rules/ai/preview", json={
        "feed_source_id": 999, "taskType": "rule_value", "system": "s", "user": "u",
        "variables": [],
    })
    assert resp.status_code == 404
    assert resp.json()["detail"] == "feed source not found"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rules_ai_routes.py -v`
Expected: FAIL — routes are not registered (404). Note: `/plugins/rules/ai/preview` with feed 999 returns 404 before auth failures because the plugin has no routes yet; confirm the failure is "no route".

- [ ] **Step 3: Implement `register_routes`**

Append the method to `RulesPlugin` in `plugins/core/rules/plugin.py`:

```python
    def register_routes(self, router: Any) -> None:
        from fastapi import Depends, HTTPException, Query
        from pydantic import BaseModel
        from sqlalchemy import or_, select

        from app.access import CurrentUser, ensure_feed_source_access, get_current_user
        from app.ai.tasks import CANONICAL_VARIABLES
        from app.ai.templates import parse_placeholders, render_messages, validate_template
        from app.db.engine import get_db_session
        from app.models.ai import PromptTemplate
        from app.models.feed_source import FeedSource
        from app.models.staging import StagingProduct

        class PreviewRequest(BaseModel):
            feed_source_id: int
            taskType: str
            templateId: int | None = None
            system: str | None = None
            user: str | None = None
            variables: list[str] | None = None
            product_id: str | None = None

        async def ai_templates(
            feed_source_id: int = Query(...),
            task_type: str = Query(...),
            user: CurrentUser = Depends(get_current_user),
            db_session: Any = Depends(get_db_session),
        ) -> dict[str, Any]:
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            await ensure_feed_source_access(db_session, user, feed_source_id)
            if task_type not in CANONICAL_VARIABLES:
                raise HTTPException(status_code=422, detail=f"unknown task type {task_type!r}")
            async with db_session.begin():
                feed = await db_session.get(FeedSource, feed_source_id)
                if feed is None:
                    raise HTTPException(status_code=404, detail="feed source not found")
                statement = select(PromptTemplate).where(
                    PromptTemplate.task_type == task_type
                )
                if feed.client_id is not None:
                    statement = statement.where(or_(
                        PromptTemplate.client_id.is_(None),
                        PromptTemplate.client_id == feed.client_id,
                    ))
                else:
                    statement = statement.where(PromptTemplate.client_id.is_(None))
                statement = statement.order_by(PromptTemplate.version.desc())
                rows = (await db_session.execute(statement)).scalars().all()
            return {"items": [
                {"id": r.id, "name": r.name, "task_type": r.task_type,
                 "client_id": r.client_id, "version": r.version, "is_active": r.is_active}
                for r in rows
            ]}

        async def ai_preview(
            payload: PreviewRequest,
            user: CurrentUser = Depends(get_current_user),
            db_session: Any = Depends(get_db_session),
        ) -> dict[str, Any]:
            if db_session is None:
                raise HTTPException(status_code=503, detail="database unavailable")
            await ensure_feed_source_access(db_session, user, payload.feed_source_id)
            has_draft = (
                payload.system is not None
                or payload.user is not None
                or payload.variables is not None
            )
            if payload.templateId is not None and has_draft:
                raise HTTPException(
                    status_code=422, detail="provide either templateId or an inline draft"
                )
            if payload.templateId is None and not (
                payload.system is not None and payload.user is not None
            ):
                raise HTTPException(
                    status_code=422, detail="inline draft requires system and user"
                )
            async with db_session.begin():
                feed = await db_session.get(FeedSource, payload.feed_source_id)
                if feed is None:
                    raise HTTPException(status_code=404, detail="feed source not found")
                if payload.templateId is not None:
                    if payload.taskType not in CANONICAL_VARIABLES:
                        raise HTTPException(
                            status_code=422,
                            detail=f"unknown task type {payload.taskType!r}",
                        )
                    row = await db_session.get(PromptTemplate, payload.templateId)
                    if row is None or row.task_type != payload.taskType:
                        raise HTTPException(status_code=422, detail="template not usable")
                    if row.client_id is not None and row.client_id != feed.client_id:
                        raise HTTPException(status_code=422, detail="template not usable")
                    system = row.system_prompt
                    user_prompt = row.user_prompt
                    declared = list(row.variables)
                    canonical = list(CANONICAL_VARIABLES[payload.taskType])
                else:
                    if payload.taskType != GENERIC_AI_TASK:
                        raise HTTPException(
                            status_code=422,
                            detail="inline draft requires taskType 'rule_value'",
                        )
                    system = payload.system or ""
                    user_prompt = payload.user or ""
                    declared = list(payload.variables or [])
                    canonical = list(declared)
                statement = select(StagingProduct).where(
                    StagingProduct.feed_source_id == payload.feed_source_id,
                    StagingProduct.status == "active",
                    StagingProduct.excluded.is_(False),
                )
                if payload.product_id is not None:
                    statement = statement.where(
                        StagingProduct.product_id == payload.product_id
                    )
                statement = statement.order_by(StagingProduct.id).limit(1)
                staged = (await db_session.execute(statement)).scalar_one_or_none()
                if staged is None:
                    raise HTTPException(status_code=404, detail="no sample product found")
                product = staged.raw_data or {}

            validation = validate_template(canonical, system, user_prompt, declared)
            if validation.errors:
                raise HTTPException(status_code=422, detail={
                    "errors": validation.errors, "warnings": validation.warnings,
                })
            values = {name: product.get(name) for name in canonical}
            warnings = list(validation.warnings)
            for name in canonical:
                if values[name] is None:
                    warnings.append(
                        f"variable {name!r} is missing in the sample product; rendered empty"
                    )
            messages = render_messages(system, user_prompt, values, lenient=True)
            used = sorted(parse_placeholders(system) | parse_placeholders(user_prompt))
            return {"messages": messages, "used_variables": used,
                    "warnings": warnings, "errors": []}

        router.get("/ai/templates", response_model=None)(ai_templates)
        router.post("/ai/preview", response_model=None)(ai_preview)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rules_ai_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Update docs + gate + commit**

Add both routes to `backend/docs/api.md` (params, XOR rule, distinct 404 details, render-only) and document `RunContext.run_state` + `op=ai` in `backend/docs/plugins.md`.

```bash
uv run ruff check . ../plugins && uv run mypy .
git add plugins/core/rules/plugin.py backend/tests/test_rules_ai_routes.py backend/docs/api.md backend/docs/plugins.md
git commit -m "feat(rules): ai template list and preview routes"
```

---

### Task 5: Config schema + contract coverage

**Files:**
- Modify: `plugins/core/rules/plugin.json`
- Test: `backend/tests/test_rules_contract.py`, `backend/tests/test_plugin_contract.py`

**Interfaces:**
- Consumes: `validate_config`.
- Produces: manifest schema accepting the `op=ai` properties.

- [ ] **Step 1: Extend the manifest schema**

In `plugins/core/rules/plugin.json`, change `then.items.properties` to:

```json
"properties": {
  "op": {"type": "string", "title": "Operation", "enum": ["set", "replace", "append", "prepend", "remove", "clear", "ai"]},
  "field": {"type": "string", "title": "Field"},
  "value": {"title": "Value"},
  "find": {"type": "string", "title": "Find"},
  "with": {"type": "string", "title": "Replace with"},
  "caseSensitive": {"type": "boolean", "title": "Case sensitive", "default": true},
  "promptSource": {"type": "string", "title": "Prompt source", "enum": ["template", "custom"]},
  "taskType": {"type": "string", "title": "AI task"},
  "templateId": {"type": "integer", "title": "Template"},
  "system": {"type": "string", "title": "System prompt"},
  "user": {"type": "string", "title": "User prompt"},
  "variables": {"type": "array", "title": "Variables", "items": {"type": "string"}}
}
```

- [ ] **Step 2: Run the contract tests**

Run: `uv run pytest tests/test_rules_contract.py tests/test_plugin_contract.py -v`
Expected: PASS. If a schema-driven sample config check fails, add an `op=ai` action to the fixture the test uses and re-run.

- [ ] **Step 3: Commit**

```bash
uv run ruff check . ../plugins && uv run mypy .
git add plugins/core/rules/plugin.json
git commit -m "feat(rules): declare ai action in the config schema"
```

---

### Task 6: Frontend AST types

**Files:**
- Modify: `plugins/core/rules/frontend/ast.ts`
- Test: `frontend/src/features/rules/__tests__/ast.test.ts`

**Interfaces:**
- Produces: `ActionOp` includes `'ai'`; `RuleAction` optional `promptSource`, `taskType`, `templateId`, `system`, `user`, `variables`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/features/rules/__tests__/ast.test.ts`:

```typescript
import { normalizeAction } from '../../../../../plugins/core/rules/frontend/ast';

describe('normalizeAction ai', () => {
  it('keeps ai template fields and allows a missing field', () => {
    const action = normalizeAction({
      op: 'ai', promptSource: 'template', taskType: 'title_optimization', templateId: 5,
    });
    expect(action).toEqual({
      op: 'ai', promptSource: 'template', taskType: 'title_optimization', templateId: 5,
      field: '',
    });
  });

  it('keeps ai custom fields', () => {
    const action = normalizeAction({
      op: 'ai', promptSource: 'custom', taskType: 'rule_value', field: 'title',
      system: 's', user: 'u {{title}}', variables: ['title'],
    });
    expect(action).toEqual({
      op: 'ai', promptSource: 'custom', taskType: 'rule_value', field: 'title',
      system: 's', user: 'u {{title}}', variables: ['title'],
    });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- ast.test.ts`
Expected: FAIL — `normalizeAction` rejects `op: 'ai'` / drops `field: ''`.

- [ ] **Step 3: Implement the AST changes**

In `plugins/core/rules/frontend/ast.ts`:

```typescript
export type ActionOp = 'set' | 'replace' | 'append' | 'prepend' | 'remove' | 'clear' | 'ai';

export type RuleAction = {
  op: ActionOp;
  field: string;
  value?: string;
  find?: string;
  with?: string;
  caseSensitive?: boolean;
  promptSource?: 'template' | 'custom';
  taskType?: string;
  templateId?: number;
  system?: string;
  user?: string;
  variables?: string[];
};
```

Update the op set:

```typescript
const ACTION_OPS: ReadonlySet<string> = new Set([
  'set', 'replace', 'append', 'prepend', 'remove', 'clear', 'ai',
]);
```

Replace `normalizeAction` with:

```typescript
function normalizeAction(value: unknown): RuleAction | null {
  if (typeof value !== 'object' || value === null) return null;
  const raw = value as Record<string, unknown>;
  if (typeof raw.op !== 'string' || !ACTION_OPS.has(raw.op)) return null;
  const op = raw.op as ActionOp;
  const isAi = op === 'ai';
  if (!isAi && (typeof raw.field !== 'string' || !raw.field)) return null;
  const action: RuleAction = {
    op,
    field: typeof raw.field === 'string' ? raw.field : '',
  };
  if (typeof raw.value === 'string') action.value = raw.value;
  if (typeof raw.find === 'string') action.find = raw.find;
  if (typeof raw.with === 'string') action.with = raw.with;
  if (typeof raw.caseSensitive === 'boolean') action.caseSensitive = raw.caseSensitive;
  if (isAi) {
    if (raw.promptSource === 'template' || raw.promptSource === 'custom') {
      action.promptSource = raw.promptSource;
    }
    if (typeof raw.taskType === 'string') action.taskType = raw.taskType;
    if (typeof raw.templateId === 'number') action.templateId = raw.templateId;
    if (typeof raw.system === 'string') action.system = raw.system;
    if (typeof raw.user === 'string') action.user = raw.user;
    if (Array.isArray(raw.variables)) {
      action.variables = raw.variables.filter((v): v is string => typeof v === 'string');
    }
  }
  return action;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm run test -- ast.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/core/rules/frontend/ast.ts frontend/src/features/rules/__tests__/ast.test.ts
git commit -m "feat(rules-ui): ai action types"
```

---

### Task 7: Frontend hooks — templates, preview, ai_rules config

**Files:**
- Create: `frontend/src/features/rules/hooks.ts`
- Modify (only if missing `configuration`): `frontend/src/api/types.ts`

**Interfaces:**
- Consumes: `apiGet`, `apiPost`, `apiPut`, `useQuery`, `useMutation`, `useFeedSource`, `queryKeys`.
- Produces: `RuleAiTemplate`, `RuleAiPreviewResult`, `RuleAiPreviewRequest`, `AiRulesConfig`, `useRuleAiTemplates`, `useRuleAiPreview`, `useSaveAiRules`.

- [ ] **Step 1: Create the hooks**

Create `frontend/src/features/rules/hooks.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, apiPut } from '../../api/client';
import { queryKeys } from '../../api/queryKeys';
import { useFeedSource } from '../../api/hooks';
import type { FeedSourceRow } from '../../api/types';

export type RuleAiTemplate = {
  id: number;
  name: string;
  task_type: string;
  client_id: number | null;
  version: number;
  is_active: boolean;
};

export type RuleAiPreviewResult = {
  messages: { role: string; content: string }[];
  used_variables: string[];
  warnings: string[];
  errors: string[];
};

export type RuleAiPreviewRequest = {
  feed_source_id: number;
  taskType: string;
  templateId?: number;
  system?: string;
  user?: string;
  variables?: string[];
  product_id?: string;
};

export type AiRulesConfig = { enabled: boolean; limit: number; budget: number };

export function useRuleAiTemplates(
  feedSourceId: number | undefined,
  taskType: string | undefined,
) {
  return useQuery({
    queryKey: ['rules', 'ai-templates', feedSourceId ?? 0, taskType ?? ''],
    enabled: Boolean(feedSourceId) && Boolean(taskType) && taskType !== 'rule_value',
    queryFn: () =>
      apiGet<{ items: RuleAiTemplate[] }>(
        `/plugins/rules/ai/templates?feed_source_id=${feedSourceId}` +
          `&task_type=${encodeURIComponent(taskType ?? '')}`,
      ),
  });
}

export function useRuleAiPreview() {
  return useMutation({
    mutationFn: (payload: RuleAiPreviewRequest) =>
      apiPost<RuleAiPreviewResult>('/plugins/rules/ai/preview', payload),
  });
}

export function useSaveAiRules(feedSourceId: number | undefined) {
  const queryClient = useQueryClient();
  const feed = useFeedSource(feedSourceId);
  return useMutation({
    mutationFn: (aiRules: AiRulesConfig) =>
      apiPut<FeedSourceRow>(`/feed-sources/${feedSourceId}`, {
        configuration: {
          ...((feed.data?.configuration ?? {}) as Record<string, unknown>),
          ai_rules: aiRules,
        },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedSource(feedSourceId ?? 0).detail,
      });
    },
  });
}
```

If `FeedSourceRow` does not expose `configuration`, add `configuration: Record<string, unknown>;` to it in `frontend/src/api/types.ts` (it mirrors the backend `FeedSourceOut`, which already includes it).

- [ ] **Step 2: Typecheck**

Run: `npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/rules/hooks.ts frontend/src/api/types.ts
git commit -m "feat(rules-ui): ai template, preview and budget hooks"
```

---

### Task 8: Frontend — AI action editor + i18n

**Files:**
- Create: `frontend/src/features/rules/RuleAiActionEditor.tsx`
- Modify: `frontend/src/features/rules/RuleEditor.tsx`
- Modify: `frontend/public/locales/en/rules.json`, `frontend/public/locales/de/rules.json`
- Test: `frontend/src/features/rules/__tests__/RuleAiActionEditor.test.tsx`

**Interfaces:**
- Consumes: `useRuleAiTemplates`, `AiPromptPreview` (Task 9 — for this task render a simple inline `<Modal>`; Task 9 swaps it out), `FieldSelect`, `GroupedFieldOptions`, `RuleAction`.
- Produces: `RuleAiActionEditor({ action, fieldOptions, feedSourceId, onChange })`; `RuleEditor` gains prop `feedSourceId?: number`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/rules/__tests__/RuleAiActionEditor.test.tsx`:

```typescript
import { beforeAll, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { RuleAiActionEditor } from '../RuleAiActionEditor';
import type { RuleAction } from '../../../../../plugins/core/rules/frontend/ast';

beforeAll(async () => {
  await i18n.loadNamespaces(['rules', 'common']);
});

const options = [{ group: 'Field', items: [{ value: 'title', label: 'title' }] }];

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

it('lists templates in template mode', async () => {
  stubFetch((url) => {
    if (url.startsWith('/plugins/rules/ai/templates')) {
      return jsonResponse({ items: [
        { id: 5, name: 'T1', task_type: 'title_optimization', client_id: null, version: 1, is_active: true },
      ] });
    }
    return jsonResponse({});
  });
  const action: RuleAction = {
    op: 'ai', field: '', promptSource: 'template',
    taskType: 'title_optimization', templateId: 5,
  };
  render(
    <RuleAiActionEditor action={action} fieldOptions={options} feedSourceId={1} onChange={vi.fn()} />,
  );
  expect(await screen.findByText('T1')).toBeInTheDocument();
});

it('switching to custom emits a rule_value action', async () => {
  const user = userEvent.setup();
  stubFetch(() => jsonResponse({}));
  const onChange = vi.fn();
  const action: RuleAction = {
    op: 'ai', field: 'title', promptSource: 'template',
    taskType: 'title_optimization', templateId: 5,
  };
  render(
    <RuleAiActionEditor action={action} fieldOptions={options} feedSourceId={1} onChange={onChange} />,
  );
  await user.click(screen.getByTestId('ai-source'));
  await user.click(await screen.findByText('Custom'));
  const next = onChange.mock.calls.at(-1)?.[0] as RuleAction;
  expect(next.taskType).toBe('rule_value');
  expect(next.templateId).toBeUndefined();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- RuleAiActionEditor.test.tsx`
Expected: FAIL — component does not exist.

- [ ] **Step 3: Add i18n keys**

In `frontend/public/locales/en/rules.json`, add `"ai": "set with AI"` to the `ops` block, and add a top-level `ai` block:

```json
"ai": {
  "source": "Prompt source",
  "template": "Template",
  "custom": "Custom",
  "task": "AI task",
  "templatePick": "Prompt template",
  "outputFields": "Writes: {{fields}}",
  "targetField": "Target field",
  "system": "System prompt",
  "user": "User prompt",
  "variables": "Variables",
  "preview": "Preview",
  "previewTitle": "Prompt preview",
  "tasks": {
    "title_optimization": "Optimize title",
    "description_optimization": "Optimize description",
    "category_classification": "Classify category",
    "attribute_enrichment": "Extract attributes",
    "rule_value": "Free text"
  },
  "budget": {
    "title": "AI rules",
    "enabled": "Enable AI rule actions",
    "limit": "Max products per run",
    "budget": "Max AI calls per run",
    "saved": "AI rules settings saved",
    "saveFailed": "Failed to save AI rules settings"
  }
}
```

Mirror the block in `frontend/public/locales/de/rules.json` with German copy (`"ai": "mit KI setzen"`, `"source": "Prompt-Quelle"`, `"template": "Vorlage"`, `"custom": "Eigene"`, `"task": "KI-Aufgabe"`, `"templatePick": "Prompt-Vorlage"`, `"outputFields": "Schreibt: {{fields}}"`, `"targetField": "Zielfeld"`, `"system": "System-Prompt"`, `"user": "User-Prompt"`, `"variables": "Variablen"`, `"preview": "Vorschau"`, `"previewTitle": "Prompt-Vorschau"`, budget keys analogous).

- [ ] **Step 4: Implement the editor**

Create `frontend/src/features/rules/RuleAiActionEditor.tsx`:

```tsx
import { Button, Group, Modal, MultiSelect, Select, Stack, Text, Textarea } from '@mantine/core';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FieldSelect } from '../../components/FieldSelect';
import type { GroupedFieldOptions } from '../../api/fieldOptions';
import type { RuleAction } from '../../../../plugins/core/rules/frontend/ast';
import { useRuleAiPreview, useRuleAiTemplates } from './hooks';

const STRUCTURED_TASKS = [
  'title_optimization',
  'description_optimization',
  'category_classification',
  'attribute_enrichment',
] as const;

const OUTPUT_FIELDS: Record<string, string[]> = {
  title_optimization: ['title'],
  description_optimization: ['description'],
  category_classification: ['google_product_category'],
  attribute_enrichment: [
    'color', 'size', 'material', 'gtin', 'gender', 'age_group',
    'custom_label_0', 'custom_label_1', 'custom_label_2', 'custom_label_3', 'custom_label_4',
  ],
};

export type RuleAiActionEditorProps = {
  action: RuleAction;
  fieldOptions: GroupedFieldOptions;
  feedSourceId?: number;
  onChange: (next: RuleAction) => void;
};

export function RuleAiActionEditor({
  action, fieldOptions, feedSourceId, onChange,
}: RuleAiActionEditorProps) {
  const { t } = useTranslation('rules');
  const source = action.promptSource ?? 'template';
  const [previewOpen, setPreviewOpen] = useState(false);

  const templates = useRuleAiTemplates(
    feedSourceId,
    source === 'template' ? action.taskType : undefined,
  );
  const preview = useRuleAiPreview();

  const knownFields = useMemo(
    () => fieldOptions.flatMap((group) => group.items.map((item) => item.value)),
    [fieldOptions],
  );
  const templateOptions = useMemo(
    () => (templates.data?.items ?? []).map((item) => ({ value: String(item.id), label: item.name })),
    [templates.data],
  );

  function switchSource(next: 'template' | 'custom') {
    if (next === 'custom') {
      onChange({
        op: 'ai', promptSource: 'custom', taskType: 'rule_value',
        field: action.field || '', system: '', user: '', variables: [],
      });
    } else {
      onChange({
        op: 'ai', promptSource: 'template',
        taskType: STRUCTURED_TASKS[0], field: action.field || '',
      });
    }
  }

  function previewPayload() {
    if (source === 'custom') {
      return {
        feed_source_id: feedSourceId ?? 0, taskType: 'rule_value',
        system: action.system ?? '', user: action.user ?? '',
        variables: action.variables ?? [],
      };
    }
    return {
      feed_source_id: feedSourceId ?? 0, taskType: action.taskType ?? '',
      templateId: action.templateId,
    };
  }

  function runPreview() {
    if (!feedSourceId) return;
    preview.mutate(previewPayload(), { onSuccess: () => setPreviewOpen(true) });
  }

  return (
    <Stack gap="xs" data-testid="ai-action-editor">
      <Group gap="xs" align="flex-end" wrap="wrap">
        <Select
          aria-label={t('ai.source')}
          data={[
            { value: 'template', label: t('ai.template') },
            { value: 'custom', label: t('ai.custom') },
          ]}
          value={source}
          onChange={(v) => switchSource(v === 'custom' ? 'custom' : 'template')}
          data-testid="ai-source"
          w={140}
        />
        {source === 'template' ? (
          <>
            <Select
              aria-label={t('ai.task')}
              data={STRUCTURED_TASKS.map((task) => ({ value: task, label: t(`ai.tasks.${task}`) }))}
              value={action.taskType ?? STRUCTURED_TASKS[0]}
              onChange={(v) => onChange({
                ...action, taskType: v ?? STRUCTURED_TASKS[0], templateId: undefined,
              })}
              w={200}
            />
            <Select
              aria-label={t('ai.templatePick')}
              data={templateOptions}
              value={action.templateId === undefined ? null : String(action.templateId)}
              onChange={(v) => onChange({
                ...action, templateId: v === null ? undefined : Number(v),
              })}
              w={200}
            />
          </>
        ) : (
          <FieldSelect
            aria-label={t('ai.targetField')}
            value={action.field}
            onChange={(v) => onChange({ ...action, field: v })}
            options={fieldOptions}
            w={200}
          />
        )}
        <Button variant="light" size="xs" onClick={runPreview} loading={preview.isPending}>
          {t('ai.preview')}
        </Button>
      </Group>

      {source === 'template' ? (
        <Text size="xs" c="dimmed">
          {t('ai.outputFields', {
            fields: (OUTPUT_FIELDS[action.taskType ?? ''] ?? []).join(', '),
          })}
        </Text>
      ) : (
        <Stack gap="xs">
          <Textarea
            aria-label={t('ai.system')}
            placeholder={t('ai.system')}
            value={action.system ?? ''}
            onChange={(e) => onChange({ ...action, system: e.currentTarget.value })}
            minRows={2}
          />
          <Textarea
            aria-label={t('ai.user')}
            placeholder={t('ai.user')}
            value={action.user ?? ''}
            onChange={(e) => onChange({ ...action, user: e.currentTarget.value })}
            minRows={3}
          />
          <MultiSelect
            aria-label={t('ai.variables')}
            data={knownFields}
            value={action.variables ?? []}
            onChange={(values) => onChange({ ...action, variables: values })}
            searchable
          />
        </Stack>
      )}

      <Modal
        opened={previewOpen}
        onClose={() => setPreviewOpen(false)}
        title={t('ai.previewTitle')}
        size="lg"
      >
        <Stack gap="xs" data-testid="ai-preview">
          {(preview.data?.messages ?? []).map((message, index) => (
            <Text key={index} size="xs" style={{ whiteSpace: 'pre-wrap' }}>
              <strong>{message.role}</strong>: {message.content}
            </Text>
          ))}
          {(preview.data?.warnings ?? []).map((warning, index) => (
            <Text key={`w-${index}`} size="xs" c="orange">{warning}</Text>
          ))}
          {preview.isError ? <Text size="xs" c="red">{String(preview.error)}</Text> : null}
        </Stack>
      </Modal>
    </Stack>
  );
}
```

- [ ] **Step 5: Wire into `RuleEditor`**

In `frontend/src/features/rules/RuleEditor.tsx`:

- Add `import { RuleAiActionEditor } from './RuleAiActionEditor';`
- Add `'ops.ai'` to `OP_KEYS` and `'ai'` to the `ACTION_OPS` array.
- Add `feedSourceId?: number;` to `RuleEditorProps` and destructure it.
- In the `then.map`, insert the AI branch before the existing `action.op === 'replace'` branch:

```tsx
            {action.op === 'ai' ? (
              <RuleAiActionEditor
                action={action}
                fieldOptions={fieldOptions}
                feedSourceId={feedSourceId}
                onChange={(next) => {
                  const nextThen = [...rule.then];
                  nextThen[index] = next;
                  onPatchThen(nextThen);
                }}
              />
            ) : action.op === 'replace' ? (
```

- [ ] **Step 6: Run the test + typecheck**

Run: `npm run test -- RuleAiActionEditor.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/rules/RuleAiActionEditor.tsx frontend/src/features/rules/RuleEditor.tsx frontend/public/locales/en/rules.json frontend/public/locales/de/rules.json frontend/src/features/rules/__tests__/RuleAiActionEditor.test.tsx
git commit -m "feat(rules-ui): ai action editor with custom prompt"
```

---

### Task 9: Frontend — extract preview modal + tests

**Files:**
- Create: `frontend/src/features/rules/AiPromptPreview.tsx`
- Modify: `frontend/src/features/rules/RuleAiActionEditor.tsx` (use the extracted modal)
- Test: `frontend/src/features/rules/__tests__/AiPromptPreview.test.tsx`

**Interfaces:**
- Consumes: `useRuleAiPreview`, `RuleAiPreviewRequest`.
- Produces: `AiPromptPreview({ opened, onClose, payload })`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/rules/__tests__/AiPromptPreview.test.tsx`:

```typescript
import { beforeAll, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { AiPromptPreview } from '../AiPromptPreview';

beforeAll(async () => {
  await i18n.loadNamespaces(['rules', 'common']);
});

it('renders messages and warnings', async () => {
  stubFetch(() =>
    new Response(JSON.stringify({
      messages: [
        { role: 'system', content: 'sys' },
        { role: 'user', content: 'Hello Red Socks' },
      ],
      used_variables: ['title'],
      warnings: ["variable 'color' is missing in the sample product; rendered empty"],
      errors: [],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
  );
  render(
    <AiPromptPreview
      opened
      onClose={() => {}}
      payload={{ feed_source_id: 1, taskType: 'rule_value', system: 's', user: 'u', variables: [] }}
    />,
  );
  expect(await screen.findByText(/Hello Red Socks/)).toBeInTheDocument();
  expect(await screen.findByText(/color/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- AiPromptPreview.test.tsx`
Expected: FAIL — component does not exist.

- [ ] **Step 3: Implement the modal**

Create `frontend/src/features/rules/AiPromptPreview.tsx`:

```tsx
import { Alert, Modal, Stack, Text } from '@mantine/core';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useRuleAiPreview, type RuleAiPreviewRequest } from './hooks';

export type AiPromptPreviewProps = {
  opened: boolean;
  onClose: () => void;
  payload: RuleAiPreviewRequest;
};

export function AiPromptPreview({ opened, onClose, payload }: AiPromptPreviewProps) {
  const { t } = useTranslation('rules');
  const preview = useRuleAiPreview();
  const { mutate } = preview;

  useEffect(() => {
    if (opened) mutate(payload);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  return (
    <Modal opened={opened} onClose={onClose} title={t('ai.previewTitle')} size="lg">
      <Stack gap="xs" data-testid="ai-preview">
        {(preview.data?.messages ?? []).map((message, index) => (
          <Text key={index} size="xs" style={{ whiteSpace: 'pre-wrap' }}>
            <strong>{message.role}</strong>: {message.content}
          </Text>
        ))}
        {(preview.data?.warnings ?? []).map((warning, index) => (
          <Alert key={`w-${index}`} color="orange" py={4}>{warning}</Alert>
        ))}
        {preview.isError ? <Alert color="red">{String(preview.error)}</Alert> : null}
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 4: Use it from the editor**

In `RuleAiActionEditor.tsx`, remove the inline `<Modal>...</Modal>` block and the `Modal` import, import `AiPromptPreview`, and render at the end:

```tsx
      <AiPromptPreview
        opened={previewOpen}
        onClose={() => setPreviewOpen(false)}
        payload={previewPayload()}
      />
```

Keep the existing `runPreview()` for the button state; the modal fires the request when it opens, so `runPreview` may simply call `setPreviewOpen(true)`:

```tsx
  function runPreview() {
    if (!feedSourceId) return;
    setPreviewOpen(true);
  }
```

- [ ] **Step 5: Run the tests + typecheck**

Run: `npm run test -- AiPromptPreview.test.tsx RuleAiActionEditor.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/rules/AiPromptPreview.tsx frontend/src/features/rules/RuleAiActionEditor.tsx frontend/src/features/rules/__tests__/AiPromptPreview.test.tsx
git commit -m "feat(rules-ui): render-only prompt preview modal"
```

---

### Task 10: Frontend — budget section + RulesUI wiring

**Files:**
- Create: `frontend/src/features/rules/RuleAiBudget.tsx`
- Modify: `frontend/src/features/rules/RulesUI.tsx`
- Test: `frontend/src/features/rules/__tests__/RulesUI.test.tsx`

**Interfaces:**
- Consumes: `useFeedSource`, `useSaveAiRules`, `AiRulesConfig`.
- Produces: `RuleAiBudget({ feedSourceId })`; `RulesUI` passes `feedSourceId` to `RuleEditor` and renders `RuleAiBudget`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/features/rules/__tests__/RulesUI.test.tsx`:

```typescript
it('renders the AI rules budget section', async () => {
  renderUI();
  expect(await screen.findByText('AI rules')).toBeInTheDocument();
});
```

Extend the `stubFetch` handler in `renderUI` so `/feed-sources/1` returns a configuration:

```typescript
    if (url.startsWith('/feed-sources/1')) {
      return jsonResponse({ id: 1, configuration: { ai_rules: { enabled: true, limit: 50, budget: 50 } } });
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- RulesUI.test.tsx`
Expected: FAIL — "AI rules" is not rendered.

- [ ] **Step 3: Implement the budget component**

Create `frontend/src/features/rules/RuleAiBudget.tsx`:

```tsx
import { Group, NumberInput, Stack, Switch, Text } from '@mantine/core';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { notifyApiError, notifySuccess } from '../../app/notifications';
import { useFeedSource } from '../../api/hooks';
import { useSaveAiRules, type AiRulesConfig } from './hooks';

const DEFAULTS: AiRulesConfig = { enabled: false, limit: 50, budget: 50 };

export function RuleAiBudget({ feedSourceId }: { feedSourceId?: number }) {
  const { t } = useTranslation('rules');
  const feed = useFeedSource(feedSourceId);
  const save = useSaveAiRules(feedSourceId);
  const [value, setValue] = useState<AiRulesConfig>(DEFAULTS);

  useEffect(() => {
    const stored = (feed.data?.configuration as Record<string, unknown> | undefined)?.ai_rules;
    if (stored && typeof stored === 'object') {
      setValue({ ...DEFAULTS, ...(stored as Partial<AiRulesConfig>) });
    }
  }, [feed.data]);

  function commit(next: AiRulesConfig) {
    setValue(next);
    if (!feedSourceId) return;
    save.mutate(next, {
      onSuccess: () => notifySuccess(t('ai.budget.saved')),
      onError: (error) => notifyApiError(error, t('ai.budget.saveFailed')),
    });
  }

  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>{t('ai.budget.title')}</Text>
      <Group gap="md">
        <Switch
          aria-label={t('ai.budget.enabled')}
          label={t('ai.budget.enabled')}
          checked={value.enabled}
          onChange={(e) => commit({ ...value, enabled: e.currentTarget.checked })}
        />
        <NumberInput
          aria-label={t('ai.budget.limit')}
          value={value.limit}
          min={1}
          onChange={(v) => setValue({ ...value, limit: typeof v === 'number' ? v : 1 })}
          onBlur={() => commit(value)}
          w={140}
          label={t('ai.budget.limit')}
        />
        <NumberInput
          aria-label={t('ai.budget.budget')}
          value={value.budget}
          min={1}
          onChange={(v) => setValue({ ...value, budget: typeof v === 'number' ? v : 1 })}
          onBlur={() => commit(value)}
          w={140}
          label={t('ai.budget.budget')}
        />
      </Group>
    </Stack>
  );
}
```

- [ ] **Step 4: Wire into `RulesUI`**

In `frontend/src/features/rules/RulesUI.tsx`:

- Add `import { RuleAiBudget } from './RuleAiBudget';`
- Compute `const feedSourceId = scope.feedSourceId;` (the component already has `scope`).
- Render `<RuleAiBudget feedSourceId={feedSourceId} />` inside the header `<Stack>` above the `<Grid>` (after the save/cancel `Group`).
- Pass `feedSourceId={feedSourceId}` to `<RuleEditor ... />`.

Note: `RulesUI` currently reads `scope.feedSourceId`? It calls `useRegistryAttributes(scope.feedSourceId)`; derive `feedSourceId` from `scope` and pass it down.

- [ ] **Step 5: Run the tests + typecheck + build**

Run: `npm run test -- RulesUI.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/rules/RuleAiBudget.tsx frontend/src/features/rules/RulesUI.tsx frontend/src/features/rules/__tests__/RulesUI.test.tsx
git commit -m "feat(rules-ui): ai rules budget section"
```

---

### Task 11: Documentation — ADR, decisions log, plugin UI docs

**Files:**
- Create: `docs/decisions/0010-ai-action-rules-plugin.md`
- Modify: `docs/decisions.md`
- Modify: `frontend/docs/plugin-uis.md`

- [ ] **Step 1: Write the ADR**

Create `docs/decisions/0010-ai-action-rules-plugin.md`:

```markdown
# 0010: AI action in the rules plugin

## Status
Accepted (2026-09-17)

## Context
Rules need AI-produced values, but `RulesPlugin.process` runs synchronously and purely
inside `PluginStep` while AI calls are asynchronous, budgeted, and cached. Prompt templates
are admin-managed and scoped by `task_type` + `client_id`.

## Decision
Two-phase execution. Phase 1 records `op=ai` actions in `RunState.rule_ai_pending`; phase 2
(`RuleAiStep`, between `PluginStep` and `EnrichmentStep`) drains them through `AiService`,
writes the target fields, and persists to staging via `apply_plugin_outcomes`.

- Template mode pins a template id (`run_task(template_id=...)`), falling back to the active
  template then the builtin.
- Custom mode is sent through a new inline-only `rule_value` task; the prompt is stored inline
  in the rule JSONB, so no admin rights are needed.
- Budget/limit live in `feed_source.configuration.ai_rules`; cache hits do not consume budget.
- An `ai` action must be the last action targeting its output field(s); `validate_config`
  rejects a following same-field action.
- `RuleAiStep` runs after `PluginStep`, so its output overrides feed and pinned-enrichment
  values for the same field.

## Consequences
No DB migration. Preview is render-only (no AI call). Custom variables are validated in the
frontend and surfaced by preview, because `validate_config` is scope-agnostic and global
rules have no feed source.
```

- [ ] **Step 2: Append the dated decision-log entry**

In `docs/decisions.md`, append an entry following the existing Topic / Decision / Rationale format:
Topic "AI action in the rules plugin"; Decision = two-phase execution + pinned/inline prompts
+ budget + render-only preview; Rationale = preserves the synchronous pipeline contract while
reusing the AI cache/usage/fallback machinery.

- [ ] **Step 3: Document the preview surface**

In `frontend/docs/plugin-uis.md`, add a short subsection describing the Rules plugin's
`op=ai` editor: source toggle (template/custom), template select, custom system/user/variables,
target field for the generic task, and the render-only preview modal backed by
`POST /plugins/rules/ai/preview`.

- [ ] **Step 4: Commit**

```bash
git add docs/decisions/0010-ai-action-rules-plugin.md docs/decisions.md frontend/docs/plugin-uis.md
git commit -m "docs: ai rule action ADR and preview surface"
```

---

### Task 12: Full verification

- [ ] **Step 1: Backend gates (from `backend/`)**

```bash
uv run ruff check . ../plugins
uv run mypy .
uv run alembic check
uv run pytest --report-log=.report.jsonl
```

Expected: all exit 0; no failing `TestReport` entries in `.report.jsonl`.

- [ ] **Step 2: Frontend gates (from `frontend/`)**

```bash
npm run test
npm run typecheck
npm run build
```

Expected: PASS.

- [ ] **Step 3: Contract test**

```bash
cd backend && uv run pytest tests/test_plugin_contract.py tests/test_rules_contract.py -v
```

Expected: PASS.

- [ ] **Step 4: Manual smoke (dev server)**

Start Postgres + backend + frontend, open a feed source's Rules page, add an `ai` action,
switch between Template and Custom, click Preview in both modes, save, and confirm
`feed_source.configuration.ai_rules` persists.

---

## Self-Review (spec coverage)

- Decisions #1/#3 (two-phase, dedicated step): Task 3.
- Decision #2 (both task types, one per source): Tasks 1, 2, 3, 8.
- Decision #4 (caching): Task 2 (`_execute_task` cache path), Task 3 (cache hit free).
- Decision #5 (inline custom prompt): Tasks 1, 6, 8.
- Decision #6 (`ai_rules` config): Tasks 3, 7, 10.
- Decision #7 (preview both modes): Tasks 4, 8, 9.
- Decision #8 (no migration): no schema task; Task 3 step 6 runs `alembic check`.
- Decision #9 (same-field ordering): Task 1.
- Decision #10 (precedence vs enrichment): Task 3 (order) + docs Task 11.
- Decision #11 (budget counting): Task 3 engine.
- Decision #12 (pinned template): Task 2.
- Minor review notes (distinct 404s, unknown-field warnings, typo): Tasks 4, 8.
- Docs: Tasks 3, 4, 11.
