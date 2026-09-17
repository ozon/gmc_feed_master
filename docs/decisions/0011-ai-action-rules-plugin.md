# 0011: AI action in the rules plugin

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
