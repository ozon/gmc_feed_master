# AI Action in the Rules Plugin — Design

Date: 2026-09-17
Status: Approved in brainstorming (operator)
Baseline: main at `b105f6d`
Builds on: `2026-09-16-litellm-instructor-ai-core-design.md` (AiService, cache, usage),
`2026-09-11-prompt-template-library-design.md` (PromptTemplate + preview),
`2026-09-09-category-plugin-design.md` (plugin `register_routes` pattern).

## Purpose

The Rules plugin can set/replace/append/prepend/remove/clear a field, but has no way to
produce a value with AI. This cycle adds a seventh action op, `ai`, whose value comes from
a prompt run against a product. The prompt is either a **template** from the prompt library
or an **inline custom prompt**, and both modes can be **previewed** (rendered messages, no AI
call) against a sample product.

## Decisions (operator sign-off)

| # | Decision | Choice |
|---|---|---|
| 1 | Runtime model | **Two-phase, budgeted.** Phase 1 (`PluginStep`, sync) records pending AI actions; phase 2 (new async `RuleAiStep`) executes them and writes results into the product |
| 2 | Task types | **Both, one per source**: template mode runs one of the four structured tasks (`TASK_FIELDS` output); custom mode runs the generic inline-only `rule_value` (free text → chosen field). Mixing (structured + custom, generic + template) is rejected |
| 3 | Application | New dedicated step after `PluginStep`, before `EnrichmentStep`; writes directly into the target field and persists to staging, independent of `ai_enrichment.enabled` |
| 4 | Caching | All calls go through `AiService`, so the litellm cache (namespace + model + rendered messages) applies to template and custom prompts alike |
| 5 | Custom prompt storage | **Inline in the rule config** (JSONB), not as a `PromptTemplate` row; no admin rights needed |
| 6 | Budget/limit config | `feed_source.configuration.ai_rules = {enabled, limit, budget}`, written via the existing `PUT /feed-sources/{id}` |
| 7 | Preview | For **both** template and custom modes: render messages + validation warnings against a staging sample, no AI call |
| 8 | DB schema | No migration: rule config and budget live in existing JSONB columns; new state is in-memory |
| 9 | Same-rule ordering | An `ai` action must be the last action targeting its output field(s) in a rule; `validate_config` rejects a following action on an overlapping field (deferred execution cannot honor `ai → append`) |
| 10 | Precedence vs enrichment | `RuleAiStep` runs after `PluginStep`, so rule AI output overrides feed values and pinned enrichment values for the same field. `EnrichmentStep` only stores suggestions and never mutates a product, so it cannot overwrite a rule result in the same run |
| 11 | Budget counting | `limit` = max distinct products touched; `budget` = max actual AI calls (`status == "ok"`). Budget exhaustion may leave one product partially applied (see §6) |
| 12 | Pinned template | `templateId` is honored (the rule pins that exact template), not "latest"; a missing/inactive template falls back to the task's active template, then builtin, with a warning |

## Architecture

```
StagingStep → PluginStep            → RuleAiStep        → EnrichmentStep → QC → Export
              (sync, per product)     (async, budgeted)
              applies set/replace/…   drains run_state.rule_ai_pending
              and RECORDS op=ai   ──▶ calls AiService.run_task / run_inline_task
              into run_state.rule_ai_pending
                                      writes result field,
                                      persists via apply_plugin_outcomes
```

Phase 1 evaluates `when` exactly once, in the real `then` sequence, and records the action.
Phase 2 does not re-evaluate conditions; it consumes the recorded list. Product identity is
by `product["id"]`.

## Backend

### 1. Rule AST (`plugins/core/rules/frontend/ast.ts`, `plugin.json`)

`ActionOp` gains `'ai'`. `RuleAction` gains optional AI fields:

```ts
export type ActionOp = 'set' | 'replace' | 'append' | 'prepend' | 'remove' | 'clear' | 'ai';

export type RuleAction = {
  op: ActionOp;
  field: string;
  value?: string; find?: string; with?: string; caseSensitive?: boolean;
  // op === 'ai' only:
  taskType?: string;                 // template: STRUCTURED_AI_TASKS; custom: 'rule_value'
  promptSource?: 'template' | 'custom';
  templateId?: number;               // promptSource === 'template'
  system?: string;                   // promptSource === 'custom'
  user?: string;                     // promptSource === 'custom'
  variables?: string[];              // promptSource === 'custom', declared
};
```

`normalizeAction` preserves these fields with the same type guards as the existing ones.
`plugin.json` `config_schema.then.items.properties` gains `op` enum value `ai` plus the new
properties; `required` stays `["op", "field"]` with op-specific checks in `validate_config`.

### 2. Phase 1 — recording (`plugins/core/rules/plugin.py`, `app/pipeline/steps.py`)

- `RunState` gains `rule_ai_pending: list[dict[str, Any]] = field(default_factory=list)`.
- `RunContext` (`app/plugins/runtime.py`) gains `run_state: Any = None`.
- `PluginStep.execute` passes `run_state=ctx.run_state` into both `RunContext(...)` sites
  (prepare_run and per-product process).
- `RulesPlugin.process` intercepts `op == 'ai'` before `apply_action`:

  ```python
  if isinstance(action, dict) and action.get("op") == "ai":
      pending = getattr(getattr(ctx, "run_state", None), "rule_ai_pending", None)
      if pending is not None:
          pending.append(_pending_entry(current, action, ctx))
      continue
  current = apply_action(current, action)
  ```

  `_pending_entry` captures `product_id`, `field`, `taskType`, `promptSource`, `templateId`,
  `system`, `user`, `variables`. A missing `run_state` is treated as a wiring bug, not a silent
  no-op: `plugin.py` gains `logging` + a module `logger` and emits
  `logger.warning("rules: ai action on product %s dropped (no run_state)", pid)` before skipping.
- `apply_action` treats `'ai'` as a **passthrough** (`return dict(product)`) and
  `_ACTION_REQUIRED_KEYS["ai"] = ("field",)` so direct callers and existing tests do not break.

### 3. Config validation (`validate_config`)

New constants and branch:

- `STRUCTURED_AI_TASKS = ("title_optimization", "description_optimization", "category_classification", "attribute_enrichment")`;
  `GENERIC_AI_TASK = "rule_value"`.
- For `op == 'ai'`:
  - `promptSource` must be `template` or `custom`;
  - `template` requires `taskType in STRUCTURED_AI_TASKS` and an int `templateId`; `field` is
    optional (structured output fields come from `TASK_FIELDS`);
  - `custom` requires `taskType == "rule_value"`, non-empty `system` and `user` strings, a
    non-empty `variables` list of lowercase identifiers (`PLACEHOLDER_RE`), and a non-empty
    `field` (the write target);
  - custom prompts are validated with `validate_template(variables, system, user, variables)`
    (the declared set doubles as canonical, so any product field the author declares is
    allowed);
  - **ordering**: an `ai` action must be the last action in the rule targeting its output
    field(s) — for `template` the mapped `TASK_FIELDS` fields, for `custom` the `field`.
    `validate_config` rejects any following action in the same rule whose `field` overlaps that
    set (deferred execution makes `ai → append` on the same field meaningless).

### 4. Generic result model (`app/ai/schemas.py`)

```python
class RuleValueResult(BaseModel):
    value: str
```

`rule_value` is **inline-only**: it is intentionally absent from `TASK_SPECS` and
`CANONICAL_VARIABLES`, so no `PromptTemplate` row can exist for it. `run_inline_task` uses
`RuleValueResult` directly; template mode never uses `rule_value`.

### 5. `AiService.run_inline_task` (`app/ai/service.py`)

Mirror of `run_task` for an inline prompt pair:

```python
async def run_inline_task(
    self, system: str, user: str, variables: dict[str, Any], *,
    client_id: int | None = None, feed_source_id: int | None = None,
) -> AiResult
```

Same collaborators, fallback semantics, usage logging, and cache path as `run_task`
(`NativeCache.request_kwargs("rule_value")` + `render_messages` + `model_validate(RuleValueResult)`),
so repeated identical inputs are cache hits.

`run_task` gains an optional `template_id: int | None = None`. When set, `_resolve_template`
loads that exact row instead of the active one, after checking it belongs to the feed source's
client or global scope (`PromptTemplate.client_id in (None, client_id)`). A missing or inactive
pinned row falls back to the active template, then the builtin, with a warning. The cache is
unaffected (rendered messages key the entry).

### 6. Phase 2 — `RuleAiStep` (`app/pipeline/steps.py`, `app/pipeline/rule_ai.py`)

New module `app/pipeline/rule_ai.py` holds the engine; `RuleAiStep` is thin, mirroring
`EnrichmentStep` / `enrichment.py`.

- Config: `(feed_source.configuration or {}).get("ai_rules")`; skip when missing, `enabled` is
  falsy, `self._ai_service is None`, or `run_state.rule_ai_pending` is empty.
- `limit` = max distinct products touched (default 50); `budget` = max actual AI calls
  (default 50). Products are processed in order and, within a product, their pending entries in
  order. `spent` counts only `status == "ok"`; cache hits are free and do not consume budget.
  When `budget` is reached mid-product, that product's remaining entries and all later products
  are skipped — a product can be partially applied, which is accepted because each entry writes
  an independent field. `applied`/`spent` in the statistics make the partial state observable.
- For each pending entry, in order:
  - `template`: `ai_service.run_task(taskType, variables, template_id=templateId, client_id=…,
    feed_source_id=…)`, `variables` from `CANONICAL_VARIABLES[taskType]`; result fields mapped
    via `TASK_FIELDS` (`title`→`title`, `description`→`description`,
    `category_classification`→`google_product_category`, `attribute_enrichment`→ its mapped
    fields).
  - `custom` / `rule_value`: `ai_service.run_inline_task(system, user, variables, …)`;
    result string written to `field`.
  - For both modes the variable values are read from the current product (template:
    `CANONICAL_VARIABLES[taskType]`; custom: the entry's declared `variables`); no step between
    `PluginStep` and `RuleAiStep` mutates product fields, so phase-2 values match phase 1.
  - `fallback` or exception → `failed += 1`, product unchanged, loop continues.
- Precedence: `RuleAiStep` runs after `PluginStep`, so its output overwrites feed values and
  pinned enrichment values for the same field. `EnrichmentStep` (after) only stores suggestions
  and never mutates `run_state.products` (`steps.py:341-359`), so it cannot overwrite a rule
  result in the same run.
- Writes into `run_state.products` by matching `product_id`, then persists changed products
  with `apply_plugin_outcomes(session_factory, feed_source_id, ingestion_run_id,
  [PluginOutcome(pid, pk, "processed", final), …])` (same call PluginStep uses), because
  `QualityCheckStep` and `ExportStep` read from staging (`load_export_bound`,
  `staging/persistence.py:195`), not `run_state`.
- `dry_run`: run AI and write in-memory for the sample, skip `apply_plugin_outcomes`.
- `StepResult.statistics = {"ai_rules": {enabled, products, applied, failed, spent}}`.

### 7. Pipeline wiring

- `default_steps` (`steps.py:537`): insert `RuleAiStep(ai_service)` between `PluginStep` and
  `EnrichmentStep`.
- `run_dry_run` (`app/pipeline/dry_run.py:72`): insert `RuleAiStep(ai_service)` after
  `PluginStep(plugin_registry).execute(ctx)`.

### 8. Plugin routes (`plugins/core/rules/plugin.py::register_routes`)

Mounted at `/plugins/rules`, following the category-plugin pattern (`get_current_user`,
`ensure_feed_source_access`, `get_db_session`, `request.app.state.ai_service`). Reserved
prefixes are only `/config` and `/data`, so these paths are allowed.

- `GET /plugins/rules/ai/templates?feed_source_id=&task_type=`
  - 404 if the feed source is missing; `ensure_feed_source_access`.
  - Returns `{items: [{id, name, task_type, client_id, version, is_active}]}` for the feed
    source's client scope **plus** global (`client_id IS NULL`), newest version first.
  - Returns `{items: []}` for `rule_value`.
- `POST /plugins/rules/ai/preview`
  - Body: `{feed_source_id, taskType, templateId? | (system, user, variables?), product_id?}`;
    `templateId` XOR the inline draft (422 otherwise), same rule as `ai_admin.preview`.
  - Sample product: `product_id` on the feed source, else the first active staging product
    (`staging/persistence` query pattern). 404 `detail` distinguishes `"feed source not found"`
    from `"no sample product found"` so the frontend renders different messages.
  - Renders with `render_messages(system, user, values, lenient=True)`, validates with
    `validate_template`; returns `{messages, used_variables, warnings, errors}` — the same
    shape as `PromptPreviewResult` (`frontend/src/api/types.ts:447`). `warnings` additionally
    list declared variables absent from the sample product (unknown/typo fields). No AI call,
    no usage row.

## Frontend

### 1. `plugins/core/rules/frontend/ast.ts`
Update `ActionOp`, `RuleAction`, `normalizeAction`, and `ACTION_OPS` as above.

### 2. `RuleEditor.tsx`
Add `'ai'` to `ACTION_OPS`/`OP_KEYS` and render a new `RuleAiActionEditor` branch when
`action.op === 'ai'` (alongside the replace/set/append/… branches).

`frontend/src/features/rules/RuleAiActionEditor.tsx` (new):
- `Select` prompt source: Template | Custom (switching clears the other mode's fields).
- Template mode: `Select` task type (the four structured tasks, label explains output) plus a
  `Select` fed by `useRuleAiTemplates(feedSourceId, taskType)`; an informational label shows
  the mapped output field(s).
- Custom mode: `taskType` is fixed to `rule_value`; system + user `Textarea`s and a variables
  editor whose chips come from `useRegistryAttributes` (the same source as `FieldSelect`), with
  inline warnings for unknown or unused variables. This is the primary guard against typos,
  because server-side `validate_config` is scope-agnostic (global/client rules have no feed
  source and thus no field registry); see §8 for the preview-time unknown-field warning. A
  `FieldSelect` picks the write target (`field`).
- `Preview` button opens `AiPromptPreview`.

### 3. Preview (`frontend/src/features/rules/AiPromptPreview.tsx`, new)
Modal that sends the current payload (template id **or** inline draft) to
`POST /plugins/rules/ai/preview` and shows the rendered `system`/`user` messages plus
`warnings`/`errors`. Mirrors `features/admin/promptLibrary/PreviewPanel.tsx` but scoped to a
feed source and non-admin; a local component avoids importing admin-only code.

### 4. Hooks (`frontend/src/features/rules/hooks.ts`, new)
- `useRuleAiTemplates(feedSourceId, taskType)` — `GET /plugins/rules/ai/templates`.
- `useRuleAiPreview()` — mutation to `POST /plugins/rules/ai/preview`.
- `useFeedSourceConfiguration(feedSourceId)` / `useSaveAiRules(feedSourceId)` — read the feed
  source and `PUT /feed-sources/{id}` with `configuration.ai_rules` merged (preserving other
  configuration keys).

### 5. Budget UI
A compact `ai_rules` section in the Rules page header: `Switch` enabled + `NumberInput`s
`limit`/`budget`, writing `feed_source.configuration.ai_rules` via `useSaveAiRules`.

### 6. i18n
Extend `rules` namespace (`frontend/src/i18n/.../rules.json`) with the new op label, source
labels, task labels, field labels, and preview strings.

## Error handling & caching

- Phase 1 never fails a run: an invalid `ai` action is rejected by `validate_config` at
  save time; at runtime a malformed pending entry is skipped and logged.
- Phase 2 never aborts the pipeline: per-entry exceptions and AI `fallback` increment `failed`
  and leave the product unchanged (same contract as `generate_suggestions`).
- Missing/`None` variable values render empty with a warning (existing lenient behavior).
- Caching: every call routes through `AiService` (`NativeCache`, namespace/model/rendered
  messages). Identical product input → cache hit → deterministic output, so repeated runs are
  stable and do not re-bill. Cache hits do not consume budget.
- Budget exhaustion stops processing further pending entries for the run; remaining products
  keep their pre-AI values.

## Testing

Backend (`uv run pytest`):
- Rules plugin: `op=ai` records a pending entry and leaves the product unchanged; a missing
  `run_state` emits a warning (caplog) and no-ops; `validate_config` accepts valid
  template/custom actions and rejects unknown `taskType`, missing `templateId`, missing
  `system`/`user`, generic actions without `field`, and a later action targeting the same field
  as a preceding `ai` action.
- `RuleAiStep`: writes structured fields via `TASK_FIELDS`; writes generic `field`; respects
  `limit` (distinct products) and `budget` (ok calls); counts cache hits without spending;
  budget exhaustion mid-product leaves the first field applied and the rest untouched;
  `fallback` leaves the product intact and counts `failed`; persists via
  `apply_plugin_outcomes` (staging row updated); overrides a pinned enrichment value for the
  same field.
- `run_inline_task`: renders and validates like `run_task`, hits the cache on repeat.
- `run_task(template_id=…)`: uses the pinned template, rejects a template scoped to another
  client, and falls back with a warning when the pinned row is missing/inactive.
- Routes: templates scoped to client+global and access-checked; preview XOR validation,
  distinct 404 details for missing feed source vs. missing sample, unknown-field warnings, and
  no AI call.
- Pipeline: `default_steps` order; a re-run with identical input produces the same export
  (cache-backed stability) and one `ai_rules` statistics block.
- Contract test (`tests/test_plugin_contract.py`) covers the extended config schema.
- `uv run alembic check` stays clean (no model change).

Frontend (`npm run test`, `npm run typecheck`):
- `ast.test.ts`: `normalizeAction` round-trips `ai` fields; rejects unknown op.
- `RuleAiActionEditor`: source/task switches, template select, custom draft, registry-backed
  variable chips with an unknown-variable warning, field select for `rule_value`; preview button
  payload (template vs inline).
- `AiPromptPreview`: renders messages/warnings from a mocked response, including the
  unknown/typo variable warning and the distinct not-found messages.
- `RulesUI`: save payload includes the `ai` action with all fields.

## Documentation

- `backend/docs/plugins.md` — new `RunContext.run_state`, `op=ai`, rules routes.
- `backend/docs/api.md` — two new routes + preview request/response.
- `backend/docs/architecture.md` — insert `RuleAiStep` in the stage list.
- `docs/decisions.md` — dated entry (two-phase AI action, cache/budget, inline custom prompts).
- `frontend/docs/plugin-uis.md` — preview surface for the rules AI action.
- New ADR `docs/decisions/0010-ai-action-rules-plugin.md` (two-phase AI execution + inline prompts).

## Out of scope / deliberate simplifications

- No per-action limit/budget; one feed-source-level `ai_rules` block.
- `rule_value` is inline-only; no DB templates for free-form prompts.
- No save-time server validation of custom `variables` against the field registry: the plugin
  `validate_config` contract is scope-agnostic and global/client-scoped rules have no feed
  source, so this is enforced in the frontend editor and surfaced by the preview instead.
- No new DB columns/migration.
- No AI call in preview (render-only, matching the admin preview).
- Re-running phase 2 on the same input relies on the cache for stability; output is not part
  of `content_hash` (consistent with existing plugin behavior, `config_hash` carries config).
