# mypy Baseline

CI enforces the count via `backend/mypy-baseline.txt`; keep both in sync — each fix removes lines from both files in the same commit.

`uv run mypy .` is configured in `pyproject.toml` (`[tool.mypy]`, target
Python 3.10; `ignore_missing_imports` limited to the untyped third-party
libs `jsonschema`, `apscheduler`, `asyncpg`). The command reports the
known errors below — **42** as of 2026-09-08 (mypy 2.3.1) — and
exits non-zero until the baseline reaches zero. That is expected; do not
"fix" a red exit by loosening the config.

## Rules

- New code MUST NOT add errors outside this list. A change that adds a
  line is not done.
- Fixing an error removes its line from this file in the same commit.
- Do NOT add `# type: ignore` to silence a baseline error instead of
  removing its line.
- `annotation-unchecked` notes (dynamically-constructed plugin classes)
  are not errors and are not listed.

## Baseline (mypy output, `error:` lines only, sorted)

```text
app/config.py:45: error: Missing named argument "initial_password" for "Settings"  [call-arg]
app/config.py:45: error: Missing named argument "initial_username" for "Settings"  [call-arg]
app/config.py:45: error: Missing named argument "session_secret" for "Settings"  [call-arg]
app/ingest/fetch.py:28: error: Incompatible types in assignment (expression has type "AsyncClient | None", variable has type "AsyncClient")  [assignment]
app/ingest/xml_reader.py:58: error: Item "None" of "str | None" has no attribute "strip"  [union-attr]
app/pipeline/dry_run.py:94: error: Argument "previous_export_run" to "QcContext" has incompatible type "app.models.export.ExportRun | None"; expected "app.qc.engine.ExportRun | None"  [arg-type]
app/pipeline/runner.py:117: error: Incompatible types in assignment (expression has type "IngestionRun | None", variable has type "IngestionRun")  [assignment]
app/pipeline/runner.py:141: error: Incompatible types in assignment (expression has type "IngestionRun | None", variable has type "IngestionRun")  [assignment]
app/pipeline/scheduler.py:53: error: Argument 1 to "validate_cron" has incompatible type "str | None"; expected "str"  [arg-type]
app/pipeline/steps.py:292: error: Argument 1 to "PluginOutcome" has incompatible type "Any | None"; expected "str"  [arg-type]
app/pipeline/steps.py:370: error: Argument "image_probe" to "QcContext" has incompatible type "ImageProbe | None"; expected "ImageProbe"  [arg-type]
app/pipeline/steps.py:371: error: Argument "previous_export_run" to "QcContext" has incompatible type "app.models.export.ExportRun | None"; expected "app.qc.engine.ExportRun | None"  [arg-type]
app/pipeline/steps.py:381: error: Argument 4 to "run_engine" has incompatible type "list[object]"; expected "list[PerProductRule]"  [arg-type]
app/pipeline/steps.py:381: error: Argument 5 to "run_engine" has incompatible type "list[object]"; expected "list[CrossProductRule]"  [arg-type]
app/qc/engine.py:91: error: Incompatible types in assignment (expression has type "CrossProductRule", variable has type "PerProductRule")  [assignment]
app/qc/engine.py:93: error: Argument 1 to "check" of "PerProductRule" has incompatible type "list[dict[Any, Any]]"; expected "dict[Any, Any]"  [arg-type]
app/routes/dashboard.py:47: error: Need type annotation for "item_counts" (hint: "item_counts: dict[<type>, <type>] = ...")  [var-annotated]
app/routes/dashboard.py:48: error: Argument 1 to "dict" has incompatible type "Sequence[Row[tuple[int, int]]]"; expected "Iterable[tuple[Never, Never]]"  [arg-type]
app/routes/pipeline.py:120: error: Incompatible return value type (got "JSONResponse", expected "dict[Any, Any]")  [return-value]
app/routes/pipeline.py:191: error: Argument 1 to "where" of "Select" has incompatible type "bool | Any"; expected "ColumnElement[bool] | _HasClauseElement[bool] | SQLCoreOperations[bool] | Expressi...
app/routes/pipeline.py:191: error: Item "None" of "ModulePipeline | None" has no attribute "id"  [union-attr]
app/routes/pipeline.py:196: error: Item "None" of "ModulePipeline | None" has no attribute "definition"  [union-attr]
app/routes/pipeline.py:97: error: Incompatible return value type (got "JSONResponse", expected "dict[Any, Any]")  [return-value]
app/routes/plugins.py:117: error: Argument 1 to "dict" has incompatible type "Sequence[Row[tuple[int, int]]]"; expected "Iterable[tuple[Never, Never]]"  [arg-type]
app/routes/plugins.py:117: error: Need type annotation for "usage" (hint: "usage: dict[<type>, <type>] = ...")  [var-annotated]
app/routes/quality.py:58: error: "ExportRun" has no attribute "severity"  [attr-defined]
app/routes/quality.py:59: error: "ExportRun" has no attribute "code"  [attr-defined]
app/routes/quality.py:60: error: "ExportRun" has no attribute "field"  [attr-defined]
app/routes/quality.py:61: error: "ExportRun" has no attribute "message"  [attr-defined]
app/routes/quality.py:62: error: "ExportRun" has no attribute "product_id"  [attr-defined]
app/routes/quality.py:63: error: "ExportRun" has no attribute "details"  [attr-defined]
app/staging/persistence.py:124: error: Incompatible types in assignment (expression has type "Result[tuple[int, str]]", variable has type "list[StagingProduct]")  [assignment]
app/staging/persistence.py:128: error: "list[StagingProduct]" has no attribute "all"  [attr-defined]
registry/parser.py:294: error: Incompatible types in assignment (expression has type "list[Never]", variable has type "tuple[SubField, SubField]")  [assignment]
registry/parser.py:296: error: "tuple[SubField, SubField]" has no attribute "append"  [attr-defined]
tests/test_export_token_log_redaction.py:21: error: Invalid index type "int" for "Mapping[str, object]"; expected type "str"  [index]
tests/test_export_token_log_redaction.py:21: error: Value of type "tuple[object, ...] | Mapping[str, object] | None" is not indexable  [index]
tests/test_export_token_log_redaction.py:28: error: Invalid index type "int" for "Mapping[str, object]"; expected type "str"  [index]
tests/test_export_token_log_redaction.py:28: error: Value of type "tuple[object, ...] | Mapping[str, object] | None" is not indexable  [index]
tests/test_export_token_log_redaction.py:35: error: "None" object is not iterable  [misc]
tests/test_rules_conditions.py:9: error: Cannot find implementation or library stub for module named "plugin"  [import-not-found]
tests/test_rules_plugin.py:11: error: Cannot find implementation or library stub for module named "plugin"  [import-not-found]
```

## Notes on clusters

- **`app/routes/quality.py:58-63` (6)** — mypy joins `row` (a
  `QualityFinding`) with the earlier `result`/`export_run` binding
  (`ExportRun`) because `result` is reused across two queries. Inference
  artifact, not a runtime bug. Renaming the second `result` (e.g.
  `findings_result`) resolves all six at once.
- **`app/pipeline/steps.py`, `runner.py`, `dry_run.py`, `qc/engine.py`
  (10)** — `| None` arguments/assignments where the runtime guarantees
  presence; fix by narrowing (assert/local var) or widening signatures.
- **`app/routes/pipeline.py:97/120`, `plugins.py:117`, `dashboard.py:47-48`
  (7)** — `JSONResponse` returns on typed `dict` routes; missing dict
  annotations for `dict(Sequence[Row[...]])` conversions.
- **`app/staging/persistence.py:124-128` (2)** — SQLAlchemy `Result` vs
  `list[StagingProduct]` variable reuse; introduce a typed local.
- **`app/config.py:45` (3)** — `Settings()` constructed with env-provided
  kwargs mypy cannot see; needs an explicit constructor call signature.
- **`registry/parser.py:294-296` (2)** — `tuple[SubField, SubField]`
  variable later reassigned to a list.
- **`app/ingest/fetch.py:28`, `xml_reader.py:58`, `pipeline/scheduler.py:53`
  (3)** — single-site `| None` narrowing.
- **`tests/` (7)** — `record.args` indexing (`tuple | Mapping | None`)
  in the token-redaction test; `import plugin` in the two rules-plugin
  tests resolves at runtime via sys.path manipulation (register under
  `[[tool.mypy.overrides]]` or import via the plugin loader).

## Follow-up

Fix entries by cluster; each fix removes its lines here. When the file
reaches zero, flip `backend/AGENTS.md` to treat `uv run mypy .` as a
hard gate (exit-0 required), like ruff's clean run today.
