# mypy Baseline (historical)

> **Closed 2026-09-10:** the baseline reached 0 and the CI gate was flipped to hard exit-0 (`uv run mypy .`). `mypy-baseline.txt` is deleted. This doc remains as the historical record of the 42-error baseline and its clusters.

`uv run mypy .` is configured in `pyproject.toml` (`[tool.mypy]`, target
Python 3.10; `plugins = ["pydantic.mypy"]`; `ignore_missing_imports`
limited to `jsonschema`, `apscheduler`, `asyncpg`, and the `plugin`
module for the core rules tests). CI enforces a hard exit-0 gate.

## Cluster history (2026-09-10, branch `mypy-baseline-cleanup`)

- **C1 — renames/locals (10):** quality.py `result` rename, persistence.py
  `rows` renamed, parser.py tuple→list variable rename.
- **C2 — None-narrowing (13):** runner.py `existing` local, steps.py
  pid guard + rule list annotations, qc/engine.py ExportRun Protocol
  deleted (ORM model imported) + cross-rule loop rename +
  `QcContext.image_probe` widened to `ImageProbe | None` with None guard
  in ImageRequirements rule, scheduler.py cron guard, fetch.py annotated
  client local, xml_reader.py cached text.
- **C3 — route annotations (9):** pipeline.py `dict | JSONResponse` return
  + pipeline None guard, plugins.py/dashboard.py dict comprehensions.
- **C4 — pydantic.mypy (3):** `plugins = ["pydantic.mypy"]` enabled;
  `alembic/env.py` type-ignore removed.
- **C5 — tests (7):** `isinstance(record.args, tuple)` narrowing in
  redaction tests; `[[tool.mypy.overrides]]` for `plugin` module in core
  rules tests.
