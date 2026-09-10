# mypy Baseline

CI enforces the count via `backend/mypy-baseline.txt`; keep both in sync — each fix removes lines from both files in the same commit.

`uv run mypy .` is configured in `pyproject.toml` (`[tool.mypy]`, target
Python 3.10; `ignore_missing_imports` limited to the untyped third-party
libs `jsonschema`, `apscheduler`, `asyncpg`). The command reports the
known errors below — **10** as of 2026-09-10 (mypy 2.3.1) — and
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
tests/test_export_token_log_redaction.py:21: error: Invalid index type "int" for "Mapping[str, object]"; expected type "str"  [index]
tests/test_export_token_log_redaction.py:21: error: Value of type "tuple[object, ...] | Mapping[str, object] | None" is not indexable  [index]
tests/test_export_token_log_redaction.py:28: error: Invalid index type "int" for "Mapping[str, object]"; expected type "str"  [index]
tests/test_export_token_log_redaction.py:28: error: Value of type "tuple[object, ...] | Mapping[str, object] | None" is not indexable  [index]
tests/test_export_token_log_redaction.py:35: error: "None" object is not iterable  [misc]
tests/test_rules_conditions.py:9: error: Cannot find implementation or library stub for module named "plugin"  [import-not-found]
tests/test_rules_plugin.py:11: error: Cannot find implementation or library stub for module named "plugin"  [import-not-found]
```

## Notes on clusters

- **`app/config.py:45` (3)** — `Settings()` constructed with env-provided
  kwargs mypy cannot see; needs an explicit constructor call signature.
  Exception: `alembic/env.py` carries one narrowly-scoped
  `# type: ignore[call-arg]` on the same false-positive class (new code,
  2026-09-08) — the no-ignore rule above targets *baseline* lines; removing
  the env.py directive belongs to this cluster's constructor-signature fix.
- **`tests/` (7)** — `record.args` indexing (`tuple | Mapping | None`)
  in the token-redaction test; `import plugin` in the two rules-plugin
  tests resolves at runtime via sys.path manipulation (register under
  `[[tool.mypy.overrides]]` or import via the plugin loader).

## Follow-up

Fix entries by cluster; each fix removes its lines here. When the file
reaches zero, flip `backend/AGENTS.md` to treat `uv run mypy .` as a
hard gate (exit-0 required), like ruff's clean run today.
