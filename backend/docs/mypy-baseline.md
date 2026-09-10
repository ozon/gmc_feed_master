# mypy Baseline

CI enforces the count via `backend/mypy-baseline.txt`; keep both in sync — each fix removes lines from both files in the same commit.

`uv run mypy .` is configured in `pyproject.toml` (`[tool.mypy]`, target
Python 3.10; `ignore_missing_imports` limited to the untyped third-party
libs `jsonschema`, `apscheduler`, `asyncpg`). The command reports the
known errors below — **0** as of 2026-09-10 (mypy 2.3.1) — and
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
```

## Notes on clusters


## Follow-up

Fix entries by cluster; each fix removes its lines here. When the file
reaches zero, flip `backend/AGENTS.md` to treat `uv run mypy .` as a
hard gate (exit-0 required), like ruff's clean run today.
