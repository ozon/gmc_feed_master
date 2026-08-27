## Code analysis tools

- CodeGraph and ast-grep are configured as MCP servers. The
  `codegraph-ast-grep` skill is installed and drives the workflow.
- Semantic questions (structure, symbols, callers, impact) -> CodeGraph.
  Structural patterns and rewrites -> ast-grep. Never use grep for
  syntax-aware questions.
- For exploration, impact analysis, or refactoring tasks, load the
  codegraph-ast-grep skill first.
- The CodeGraph index lives in `.codegraph/` (listed in .gitignore).

## Testing

- Tests run with pytest against real PostgreSQL via pytest-postgresql:
  the schema is loaded once per session as a template database and
  cloned per test. Do not replace this with mocks.
- Full suite -> `pytest -n auto` (xdist, one worker per core).
  Single test -> `pytest tests/test_x.py::test_name -v`.
  Rerun failures -> `pytest --lf`. Find slow tests ->
  `pytest --durations=20`.
- Each xdist worker gets its own database. Never hardcode database
  names in tests or fixtures.
- Every test runs in a transaction that is rolled back afterwards.
  Use `flush()` instead of `commit()` in fixtures. Migrations run
  via `alembic upgrade head`.
- Never run `DROP DATABASE` outside the pytest test databases.
  Never touch the production database.
  
## Conventions

- Use absolute paths when invoking ast-grep.
- Keep searches bounded to relevant paths, languages, and globs.
- Treat generated code, vendor trees, and ignored files as explicit
  scope decisions; ask before scanning them.## Conventions

- Use absolute paths when invoking ast-grep.
- Keep searches bounded to relevant paths, languages, and globs.
- Treat generated code, vendor trees, and ignored files as explicit
  scope decisions; ask before scanning them.

