# Tooling, Testing, CI & DX Review — 2026-09-17

Scope: `.github/`, `Makefile`, `docker-compose.yml`, `Caddyfile*`, `ruff.toml`, `backend/pyproject.toml`, `backend/alembic.ini`, `backend/scripts/`, `frontend/package.json`, `frontend/vite.config.ts`, `.env.example`, `README.md`, AGENTS.md files, and root-level instruction docs. Read-only; no code modified.

## Status update — 2026-09-19

Remediated on branch `feat/quality-contract-gaps`. Verified: ruff exit-0 (`extend-select` B/C4/SIM/I/E711/E712), `mypy .` and `mypy --explicit-package-bases ../plugins` clean, full backend suite 1440 passed at 85.81% coverage (floor 85), runtime `pip-audit` clean (2 ignored), `npm audit` clean.

| # | Status | Note |
|---|--------|------|
| T1 | Fixed | `/chat` was already proxied in `Caddyfile`, `Caddyfile.dev`, and `vite.config.ts`; this cycle added it to the `README.md:64` prefix list, the one remaining drift. |
| T2 | Fixed | `.github/dependabot.yml` (uv/npm/github-actions) + runtime `pip-audit` (pinned 2.10.1, `--no-dev`) + `npm audit --audit-level=high` CI steps. The runtime audit found 33 CVEs in `pillow 10.4.0`; bumped to `pillow==12.3.0`. `diskcache` `PYSEC-2026-2447` has no fix → documented `--ignore-vuln`. |
| T3 | Resolved (superseded) | The Oxc cycle (2026-09-18) shipped `oxlint`/`oxfmt` + a CI lint/format step; ESLint was never adopted (TS 7 blocker). |
| T4 | Fixed | `ruff.toml` gains `[lint] extend-select = ["B","C4","SIM","I","E711","E712"]` (not the report's literal `select`: Ruff 0.16's defaults are narrower, so `select` additionally pulled in 10 unrelated `E402`/`E702` test findings). 18 findings fixed. |
| T5 | Partially fixed | `plugins/` is now typechecked via a separate `mypy --explicit-package-bases` invocation; its 1 finding fixed. `strict` deferred — 3274 errors / 172 files, recorded in `docs/decisions.md`. |
| T6 | Fixed | `pytest-cov==7.1.0`; `[tool.coverage]` source `app/`, `fail_under = 85`; CI runs `pytest --cov=app`. The AGENTS reportlog claim is reconciled to local triage. |
| T7 | Fixed | Superseded by the production-container-deployment cycle (`docker-compose.prod.yml`, `docs/prod_deployment.md`). |
| T8 | Open | Stale root instruction docs (`coding-agent-instructions.md`, `i18n-agent-instructions.md`, `m10-frontend-instructions.md`) still present. |
| T9 | Open | `examples/feed.xml` duplicate still present. |
| T10 | Open | `.env.example` still ships sync `postgresql://`. |
| T11 | Open | CI still `on: push` + `pull_request` with no branch filter and sets both `DATABASE_URL`/`TEST_DATABASE_URL`. |
| T12 | Partially fixed | `pillow` is now exact-pinned; `mypy`/`uvicorn` ranges remain (cosmetic, `uv sync --locked`). |

Top 5 priority actions: #1 (T1), #3 (T2), #4 (T4 + T5-plugins), and the coverage half of #5 (T6) are done; the runbook half of #5 landed with T7. #2 was already in place (T3).

## Overall assessment

This is a well-run repo in most respects: a single CI workflow covers an above-average gate set (registry artifact check, `alembic upgrade` + `alembic check` drift gate, hard exit-0 ruff/mypy, full backend suite against real Postgres, frontend typecheck+test+build), the test infrastructure is genuinely strong (template-database cloning per xdist worker, `TestClock`, 1079 tests, contract tests with negative cases), and repo hygiene is good (clean `git status`, comprehensive `.gitignore`, `uv lock --check` passes, `npm audit` clean). The three real weaknesses: the API proxy prefix list is hand-duplicated across four files and has already drifted (`/chat` is broken in dev and prod), the frontend has zero lint and the backend's documented ruff rule set is not actually enabled in config, and there is no security/dependency scanning or coverage measurement anywhere. Deployment is a manual host-process story with a single-worker constraint and no runbook outside a buried design doc.

## Findings

### High

**[T1] `/chat` is not proxied anywhere — user-facing feature broken in dev and prod** — `Caddyfile:11-37`, `Caddyfile.dev:3-31`, `frontend/vite.config.ts:48-85`. *(Controller-verified.)*
Backend `POST /chat` exists (`backend/app/routes/chat.py:38`) and the frontend calls it same-origin (`frontend/src/api/hooks.ts:931`), but the prefix list in both Caddyfiles and the Vite dev proxy omits `/chat` — in dev Vite returns 404 HTML, in prod Caddy falls through to the static `index.html` handler. The same list is duplicated a fourth time in `README.md:64`; all four drifted together when the chat feature landed (grep confirms `/chat` absent from all four).
*Recommendation:* add `/chat` to all three configs + README. Longer term, mount API routes under one `/api` prefix or generate the proxy list from a single source.

**[T2] No security or dependency scanning in CI** — `.github/workflows/ci.yml`.
No `dependabot.yml`, no `pip-audit`/`npm audit`/CodeQL step (verified: `.github/` contains only `workflows/ci.yml`). The backend pins `litellm==1.101.0` — a large transitive surface with a CVE history — and nothing would flag a vulnerable pin.
*Recommendation:* add dependabot (pip, npm, github-actions) plus a `pip-audit`/`npm audit` CI step.

**[T3] No ESLint config exists at all** — `frontend/` (duplicate of `F5`).
No `eslint.config.*`/`.eslintrc*`, no eslint in devDependencies, no `lint` script (verified by glob and `package.json`). React-hooks rules are entirely unenforced across component code; CI's frontend job is test+typecheck+build only.
*Recommendation:* add typescript-eslint + react-hooks, an `npm run lint` script, and a CI step.

### Medium

**[T4] Documented ruff rule set is not enabled; only ruff defaults run** — `ruff.toml:1-14`.
`backend/AGENTS.md` claims B006/B008, C4, SIM113, and I are "enforced via Ruff", but the config has no `[lint] select` — and `extend-immutable-calls` (a B008-only setting) is configured yet inert. Verified: `ruff check --select B,C4,SIM,I` finds **15 latent violations** (B905×6, B904×3, SIM×3, C4×2, B007×1).
*Recommendation:* add `select = ["E4","E7","E9","F","B","C4","SIM","I"]` and fix the 15.

**[T5] mypy is non-strict and `plugins/` is completely excluded** — `backend/pyproject.toml:38-52`, `.github/workflows/ci.yml:44`.
No `strict = true` / `disallow_untyped_defs`; CI runs `mypy .` from `backend/` only. `uv run mypy ../plugins` fails on module resolution, so all plugin code — the piece with a runtime contract — is untypechecked.
*Recommendation:* enable strict mode and add plugins to the mypy path (`--explicit-package-bases` or namespace config).

**[T6] Zero coverage tooling; documented CI gate does not match actual CI** — `backend/pyproject.toml:22-32`, `ci.yml:46-48`.
No pytest-cov dependency, no `--cov`, no vitest coverage, no thresholds — 1079 tests with no visibility into uncovered critical paths (delta hashing, run locks, atomic export). `backend/AGENTS.md` documents a jq-based `--report-log` failure gate "enforced in CI", but `ci.yml:48` runs plain `uv run pytest -q`.
*Recommendation:* add pytest-cov with a reported (then gated) floor; reconcile the doc.

**[T7] No production compose; deployment is undocumented manual host processes** — `docker-compose.yml:1-29`.
Compose has only postgres+redis; production = hand-run `uvicorn --workers 1` + Caddy on the host, migrations applied manually. The sole deploy reference is `docs/superpowers/specs/2026-08-31-caddy-production-deployment-design.md` (predates `/chat`, hence `T1`). The single-worker constraint also means every deploy restart wipes all sessions.
*Recommendation:* write a deploy runbook (migrate → build → caddy reload, session-restart caveat) or add a prod compose profile.

**[T8] Four tracked instruction docs compete with AGENTS.md** — root.
`coding-agent-instructions.md` (greenfield setup, untouched since 2026-08-28), `i18n-agent-instructions.md` (one-off task), and `m10-frontend-instructions.md` (milestone-final) all predate the canonical AGENTS.md and describe earlier project states; plus `TODO.md` (581 lines) and `AGENT_MSG_BOARD.md`. Multiple authority sources are how the `T4`/`T6` doc drift happened. Move the three stale docs under `docs/superpowers/` as historical archive.

### Low

- **[T9] `examples/feed.xml` is a byte-identical duplicate** of `backend/tests/fixtures/feeds/example_feed.xml` (same md5, 568KB tracked twice). Delete the `examples/` copy or replace with a pointer.
- **[T10] `DATABASE_URL` dialect inconsistency** — `.env.example:11` ships sync `postgresql://` while every documented command passes `postgresql+asyncpg://`. The app normalizes both (`app/config.py:28-39`) so it works, but new contributors hit avoidable confusion. Pick one form with a comment that both are accepted.
- **[T11] Duplicate CI runs and a deliberate warning in every log** — `ci.yml:3-6,14-15`. `on: push` + `on: pull_request` without branch filters double-runs PR branches; CI also sets both `DATABASE_URL` and `TEST_DATABASE_URL`, which `conftest.py:28-36` warns about by design. Add `push: branches: [main]` and drop `DATABASE_URL` from the backend job env.
- **[T12] Inconsistent pinning policy** — `backend/pyproject.toml:26`. Nearly everything is exact-pinned (good) but `mypy>=2.3.1`, `uvicorn[standard]>=0.30,<1`, `pillow>=10.4,<11` are ranges; `uv sync --locked` mitigates, so cosmetic. Frontend deps are clean (`npm audit` 0 vulnerabilities; recharts is both direct and a `@mantine/charts` peer — expected; dnd-kit/dayjs/i18next all verified in use).

## Clean areas

- **Test infrastructure** — conftest template-DB cloning, `TestClock`, per-test isolation, contract tests with targeted negative cases (`backend/tests/test_plugin_contract.py`).
- **Migration drift gating** — `alembic check` in CI (better than most repos).
- **Registry artifact freshness check** in CI.
- **`.gitignore` coverage and working-tree cleanliness**, Makefile ergonomics, and README accuracy for everything except the proxy list.

## Top 5 priority actions

1. Add `/chat` to `Caddyfile`, `Caddyfile.dev`, `vite.config.ts`, and `README.md:64` — user-facing feature currently broken in every documented runtime path.
2. Add ESLint (typescript-eslint + react-hooks) to the frontend with a CI step — the only completely missing gate.
3. Add dependabot + pip-audit/npm audit to CI — litellm's CVE history makes this the biggest silent risk.
4. Enable the ruff rules the docs already claim (B, C4, SIM, I — 15 latent fixes) and turn on mypy strict incl. `plugins/`.
5. Add pytest-cov/vitest coverage reporting with a floor, and write the deploy runbook (migrate → build → caddy reload, session-restart caveat).
