# Frontend Lint and Format with Oxc — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt `oxlint` + `oxfmt` (+ `oxlint-tsgolint` for type-aware linting) as the frontend's lint/format toolchain, gated in CI, without changing TypeScript 7.0.2.

**Architecture:** Rust-native Oxc tools parse TS/TSX themselves, so no `typescript-eslint`/TS-compiler-API dependency exists. `frontend/.oxlintrc.json` enables the broad `correctness`/`suspicious`/`perf` categories plus React, React-hooks, TypeScript, import, jsx-a11y, and vitest rules; `options.typeAware` delegates `typescript/*` type-aware rules to `oxlint-tsgolint` (which requires TS ≥ 7.0 — satisfied). `frontend/.oxfmtrc.json` configures `oxfmt`. One isolated commit reformats `src/`.

**Tech Stack:** `oxlint`, `oxfmt`, `oxlint-tsgolint` (exact-pinned), Node ≥ 22, TypeScript 7.0.2, Vite 8 / rolldown (unchanged).

## Global Constraints

- TypeScript stays **7.0.2**. No downgrade, no side-by-side copy, no `typescript-eslint`.
- Exact version pins only, **no `^` ranges** in `frontend/package.json` (repo convention).
- Formatting scope is `frontend/src` **only** — no configs, JSON, or Markdown.
- Errors stay **zero**; warnings pinned to a **measured** baseline (`maxWarnings`) that must never grow.
- The one-time reformat is **semantics-preserving**; the test pass count must be identical before and after.
- Docs (`frontend/AGENTS.md`, `docs/decisions.md`, `TODO.md`) update in the same commit as the behavior they describe.
- No dependency other than the three Oxc packages. All commands run from `frontend/` unless stated.

## File Structure

- `frontend/package.json` — add three exact devDependencies; add `lint`, `lint:fix`, `format`, `format:check` scripts.
- `frontend/.oxlintrc.json` — new; linter config, categories, plugins, rules, `maxWarnings`.
- `frontend/.oxfmtrc.json` — new; formatter config.
- `.git-blame-ignore-revs` — new at repo root; holds the reformat commit SHA.
- `.github/workflows/ci.yml` — frontend job gains a lint+format-check step.
- `frontend/AGENTS.md`, `docs/decisions.md`, `TODO.md`, `docs/superpowers/plans/2026-09-08-review-remediation.md` — docs/tracker updates.

---

### Task 1: Add Oxc dependencies, configs, and scripts

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/.oxlintrc.json`
- Create: `frontend/.oxfmtrc.json`

**Interfaces:**
- Produces: `npm run lint` (`oxlint --type-aware src`), `npm run lint:fix` (`oxlint --fix src`), `npm run format` (`oxfmt --write src`), `npm run format:check` (`oxfmt --check src`). Tasks 2–5 consume these.

- [ ] **Step 1: Empirically validate rule/plugin identifiers before writing the config**

`oxlint@1.83.0`'s `--rules` listing prints nothing, so read the real namespaces from a probe. From `/tmp/opencode`:

```bash
mkdir -p /tmp/opencode/oxlint-probe && cd /tmp/opencode/oxlint-probe
cat > probe.tsx <<'EOF'
import { useEffect, useState } from 'react';

export const notAComponent = 42;

export function Card({ flag }: { flag: boolean }) {
  const [n] = useState(0);
  if (flag) {
    useEffect(() => {
      console.log(n);
    }, []);
  }
  return <div>{n}</div>;
}
EOF
npx --yes oxlint@latest --react-plugin -D rules-of-hooks -W only-export-components probe.tsx
```

Expected: it reports `react-hooks(rules-of-hooks)` (error), `react-hooks(exhaustive-deps)` (warning), and `react(only-export-components)` (warning). This confirms `react-hooks/*` is a rule namespace carried by the `react` plugin (there is no `react-hooks` plugin). If any namespace differs, use the names actually printed in the config below and note the correction in `docs/decisions.md` (Task 5).

- [ ] **Step 2: Install the three devDependencies pinned exact**

```bash
cd /home/ozon/gmc_feed_master/frontend
npm install -D --save-exact oxlint oxfmt oxlint-tsgolint
npm ls oxlint oxfmt oxlint-tsgolint
```

Expected: three new exact entries in `devDependencies`, no `^`. Confirm `oxlint-tsgolint`'s only extra entries are its transitive `@oxlint-tsgolint/<platform>` optional dependencies — do **not** add a separate `typescript-go` pin. If no `src`-wide run has happened yet, `npm run lint` will not exist until Step 4.

- [ ] **Step 3: Create the two config files**

`frontend/.oxlintrc.json` (identifiers verified in Step 1):

```jsonc
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "options": {
    "typeAware": true,
    "maxWarnings": 0
  },
  "categories": {
    "correctness": "error",
    "suspicious": "warn",
    "perf": "warn",
    "style": "off"
  },
  "plugins": ["unicorn", "oxc", "typescript", "react", "import", "jsx-a11y", "vitest"],
  "rules": {
    "react/react-in-jsx-scope": "off",
    "react/hooks": "off",
    "react/exhaustive-effect-dependencies": "off",
    "react/only-export-components": ["warn", { "allowConstantExport": true }],
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn",
    "eslint/no-unused-vars": "warn",
    "typescript/no-floating-promises": "error",
    "typescript/no-misused-promises": "error",
    "typescript/no-unsafe-assignment": "warn",
    "typescript/no-unsafe-member-access": "warn",
    "typescript/no-unsafe-argument": "warn",
    "typescript/no-unsafe-call": "warn",
    "typescript/no-unsafe-return": "warn"
  },
  "ignorePatterns": ["dist", "coverage"]
}
```

`react/react-in-jsx-scope` is off (React 19 automatic JSX runtime); `react/hooks` and `react/exhaustive-effect-dependencies` are off (they duplicate the canonical `react-hooks/*` rules). `maxWarnings` stays `0` for now; Task 3 overwrites it with the measured count.

`frontend/.oxfmtrc.json`:

```json
{
  "$schema": "./node_modules/oxfmt/configuration_schema.json",
  "printWidth": 100,
  "singleQuote": true
}
```

- [ ] **Step 4: Add the four npm scripts**

In `frontend/package.json` `scripts`, alongside the existing `dev`/`build`/`typecheck`/`test`:

```json
    "lint": "oxlint --type-aware src",
    "lint:fix": "oxlint --fix src",
    "format": "oxfmt --write src",
    "format:check": "oxfmt --check src"
```

- [ ] **Step 5: Verify the configs load and the commands run**

```bash
cd /home/ozon/gmc_feed_master/frontend
npx oxlint --print-config src 2>&1 | head -5
npm run format:check 2>&1 | tail -5
npm run lint 2>&1 | tail -20
```

Expected: `--print-config` shows the resolved config (JSON); `format:check` reports files needing formatting and exits non-zero; `npm run lint` reports findings and exits non-zero. **Both non-zero exits are expected here** — no source has been fixed or formatted yet. Do not "fix" the lint run by force this task.

- [ ] **Step 6: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add frontend/package.json frontend/package-lock.json frontend/.oxlintrc.json frontend/.oxfmtrc.json
git commit -m "build(frontend): add oxlint + oxfmt toolchain and configs"
```

---

### Task 2: One-time `src/` reformat (isolated commit)

**Files:**
- Modify: `frontend/src/**` (formatting only)
- Create: `.git-blame-ignore-revs`

**Interfaces:**
- Consumes: `npm run format` from Task 1.
- Produces: a formatted `src/` tree and a `.git-blame-ignore-revs` file holding the reformat commit SHA.

- [ ] **Step 1: Capture the pre-format test count**

```bash
cd /home/ozon/gmc_feed_master/frontend
npm test -- --run 2>&1 | tail -5
```

Record the pass count and test-file count from the summary line (e.g. `Tests  N passed (N)`). This is the reference value; do not assume a fixed number.

- [ ] **Step 2: Format `src/`**

```bash
cd /home/ozon/gmc_feed_master/frontend
npm run format 2>&1 | tail -10
npm run format:check 2>&1 | tail -5
```

Expected: `format` writes files; `format:check` now passes (exit 0).

- [ ] **Step 3: Sanity-check the diff is formatting-only**

```bash
cd /home/ozon/gmc_feed_master
git diff --stat
git diff -- 'frontend/src/**/*.ts' 'frontend/src/**/*.tsx' | grep -E '^\+' | grep -vE '^\+\+\+' | grep -vE '^\+[[:space:]]*$' | head -30
```

Expected: only files under `frontend/src` changed; no config, JSON, or Markdown. Spot-check the added lines for whitespace/quote/line-break changes, not logic.

- [ ] **Step 4: Verify tests, typecheck, and build are unchanged**

```bash
cd /home/ozon/gmc_feed_master/frontend
npm test -- --run 2>&1 | tail -5
npm run typecheck 2>&1 | tail -3
npm run build 2>&1 | tail -3
```

Expected: the pass count and file count exactly match Step 1; typecheck and build exit 0. Any difference is a formatter bug — revert the formatting for the offending file (`git checkout -- <file>`) and record it, do not accept the change.

- [ ] **Step 5: Commit the reformat alone**

```bash
cd /home/ozon/gmc_feed_master
git add -A frontend/src
git commit -m "chore(frontend): apply oxfmt formatting to src"
git rev-parse HEAD
```

Record the printed SHA as `<FORMAT_SHA>` for Step 6.

- [ ] **Step 6: Create `.git-blame-ignore-revs`**

The file does not currently exist, so create it:

```bash
cd /home/ozon/gmc_feed_master
printf '# oxfmt reformat of frontend/src\n<FORMAT_SHA>\n' > .git-blame-ignore-revs
git add .git-blame-ignore-revs
git commit -m "chore: ignore oxfmt reformat commit in git blame"
git log --oneline -2
```

Expected: two commits — the reformat, then the blame-ignore. Replace `<FORMAT_SHA>` with the real 40-char SHA from Step 5 (no angle brackets).

---

### Task 3: Lint baseline — fix errors, pin warnings

**Files:**
- Modify: `frontend/src/**` (only where an `error` rule fires)
- Modify: `frontend/.oxlintrc.json` (`maxWarnings` value only)

**Interfaces:**
- Consumes: `npm run lint` from Task 1.
- Produces: a lint run with zero errors and a pinned warning baseline.

- [ ] **Step 1: Capture the raw findings**

```bash
cd /home/ozon/gmc_feed_master/frontend
npm run lint 2>&1 | tee /tmp/opencode/oxlint-baseline.txt | tail -40
grep -cE '^.*error ' /tmp/opencode/oxlint-baseline.txt || true
tail -3 /tmp/opencode/oxlint-baseline.txt
```

Expected: the famous summary line reports `X errors, Y warnings`. Record `X` and `Y`.

- [ ] **Step 2: Fix every `error` finding**

Work the errors from the captured file. Apply the rule, not a blanket suppression:

```bash
cd /home/ozon/gmc_feed_master/frontend
grep -E 'error ' /tmp/opencode/oxlint-baseline.txt | head -40
npx oxlint --fix src            # auto-fixable errors only
npm run lint 2>&1 | tail -3     # re-check; repeat until the summary says 0 errors
```

Fixes are real code changes (e.g. move a conditional hook to the top level, add a missing dependency, add an `await`/`void` for `no-floating-promises`, tighten an `any`). If a rule is genuinely wrong for a specific line, use a narrow `// oxlint-disable-next-line <rule> -- <reason>` and nothing broader. Do not disable an `error` rule globally.

- [ ] **Step 3: Confirm zero errors and no stale suppressions**

```bash
cd /home/ozon/gmc_feed_master/frontend
npm run lint 2>&1 | tail -3
npx oxlint --type-aware --report-unused-disable-directives src 2>&1 | grep -i 'unused.*disable' || echo "no unused disable directives"
```

Expected: `0 errors`; the second command prints "no unused disable directives" (fix any it reports).

- [ ] **Step 4: Pin the measured warning baseline**

Re-run and read the exact warning count `W`:

```bash
cd /home/ozon/gmc_feed_master/frontend
npm run lint 2>&1 | tail -3
```

Edit `frontend/.oxlintrc.json` `options.maxWarnings` from `0` to `W` (the integer from the summary line). Then:

```bash
npm run lint; echo "exit=$?"
```

Expected: exit 0 (warnings `W` are within the baseline). If `W` is `0`, leave `maxWarnings` at `0`.

- [ ] **Step 5: Prove the gate catches the Task-4 hook-order class**

```bash
cd /home/ozon/gmc_feed_master/frontend
cp src/main.tsx /tmp/opencode/main.tsx.bak
printf 'export function Bad({ flag }: { flag: boolean }) {\n  if (flag) { React.useEffect(() => {}, []); }\n  return null;\n}\n' > src/__oxlint_probe.tsx
npm run lint 2>&1 | grep 'rules-of-hooks' ; echo "exit=$?"
rm src/__oxlint_probe.tsx
npm run lint 2>&1 | tail -1
```

Expected: the probe produces a `react-hooks(rules-of-hooks)` error and non-zero exit; after removing the probe, lint exits 0. (If `React` is not imported, import it in the probe or use a direct `useEffect` import.)

- [ ] **Step 6: Commit**

```bash
cd /home/ozon/gmc_feed_master
git add -A frontend/src frontend/.oxlintrc.json
git commit -m "fix(frontend): resolve oxlint errors and pin warning baseline"
```

---

### Task 4: CI gate

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `npm run lint`, `npm run format:check` from Task 1.
- Produces: a CI step that fails on lint errors, exceeded warning baseline, or unformatted files.

- [ ] **Step 1: Add the step to the frontend job**

In `.github/workflows/ci.yml`, in the `frontend:` job, insert immediately after the "Install frontend dependencies" step and before "Run frontend tests, typecheck, and build":

```yaml
      - name: Lint and format check
        working-directory: frontend
        run: npm run lint && npm run format:check
```

- [ ] **Step 2: Verify the workflow file parses**

```bash
cd /home/ozon/gmc_feed_master
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"
grep -n -A3 "Lint and format check" .github/workflows/ci.yml
```

Expected: `yaml ok` and the step visible in the frontend job.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(frontend): lint and format-check gate"
```

---

### Task 5: Docs, tracker, and cycle close-out

**Files:**
- Modify: `frontend/AGENTS.md`
- Modify: `docs/decisions.md`
- Modify: `TODO.md`
- Modify: `docs/superpowers/plans/2026-09-08-review-remediation.md`
- Modify: `.superpowers/sdd/progress.md` (gitignored ledger)

**Interfaces:**
- Consumes: exact versions from Task 1, the warning baseline `W` from Task 3, the reformat SHA from Task 2.
- Produces: closed TODO 9A.14; recorded tooling decision.

- [ ] **Step 1: Update `frontend/AGENTS.md`**

Add to the HOW command block, after `npm run typecheck`:

```bash
npm run lint             # oxlint (type-aware); errors fail, warnings capped
npm run format:check     # oxfmt check; npm run format to write
```

Add one convention bullet under "Key conventions": formatting is owned by `oxfmt` (`frontend/src` only) and lint by `oxlint`; do not add ESLint or Prettier; use a narrow `// oxlint-disable-next-line <rule> -- <reason>` only when a rule is genuinely wrong for a line; new warnings are not allowed (baseline is pinned in `.oxlintrc.json`).

- [ ] **Step 2: Record the decision in `docs/decisions.md`**

Append a dated entry (following the file's existing Topic / Decision / Rationale style) titled for the Oxc toolchain adoption, stating: `oxlint` + `oxfmt` + `oxlint-tsgolint` adopted with the exact three versions installed in Task 1; TypeScript stays 7.0.2 (the design's reason: Oxc parsers need no TS compiler API, and `tsgolint` requires TS ≥ 7.0); warning baseline is `W` (measured, must never grow); `oxfmt` is beta and pinned exact with `--check` in CI, so upgrades are deliberate; the prior "eslint adoption" entry is superseded.

- [ ] **Step 3: Close TODO 9A.14 and log the cycle**

In `TODO.md`, change `### 9A.14 [ ]` to `### 9A.14 [x]` and append a `**Done (2026-09-18):**` note: superseded by the Oxc toolchain — `typescript-eslint` remains incompatible with TS 7 (`#10940`), but `oxlint` + `tsgolint` deliver the same rule classes (React hooks, react-refresh, unused vars, type-aware TS rules) without it; design/spec link. Since Section 11 is otherwise closed, the Open items section then holds only 8.1, 8.2, and 9.4. Add a cycle-log entry at the top of `## Cycle log`.

- [ ] **Step 4: Mark review-remediation Task 14 superseded**

In `docs/superpowers/plans/2026-09-08-review-remediation.md`, append to the Task 14 STATUS blockquote (do not rewrite the existing text): a line stating it is **superseded** by `docs/superpowers/specs/2026-09-18-frontend-oxc-lint-format-design.md`, and why (Oxc/tsgolint satisfies the requirement under the TS 7 pin).

- [ ] **Step 5: Append the SDD ledger note**

Append to `.superpowers/sdd/progress.md`: the cycle summary — tasks executed, exact versions, warning baseline, reformat SHA, and final gate results.

- [ ] **Step 6: Run the full frontend gate and commit**

```bash
cd /home/ozon/gmc_feed_master/frontend
npm run lint && npm run format:check && npm test -- --run && npm run typecheck && npm run build 2>&1 | tail -5
cd /home/ozon/gmc_feed_master
git add frontend/AGENTS.md docs/decisions.md TODO.md docs/superpowers/plans/2026-09-08-review-remediation.md
git commit -m "docs: record Oxc lint/format adoption and close TODO 9A.14"
```

Expected: all five commands exit 0; commit succeeds.

---

## Final Verification

```bash
cd /home/ozon/gmc_feed_master/frontend
npm run lint; echo "lint=$?"
npm run format:check; echo "format=$?"
npm test -- --run 2>&1 | tail -4
npm run typecheck && npm run build; echo "build=$?"
cd /home/ozon/gmc_feed_master
grep -n 'oxlint\|oxfmt' frontend/package.json
cat .git-blame-ignore-revs
git log --oneline -8
```

Expected: `lint=0`, `format=0`, the test count equals the Task 2 Step 1 reference, `build=0`, the three Oxc devDependencies are present and exact-pinned, `.git-blame-ignore-revs` holds the reformat SHA, and the commit sequence matches Tasks 1–5.

## Self-Review Notes

- **Spec coverage:** deps/config/scripts → Task 1; isolated reformat + blame-ignore → Task 2; baseline policy → Task 3; CI gate → Task 4; docs/tracker (incl. spec's step 5) → Task 5. Spec's type-aware, `style: off`, `printWidth`/`singleQuote`, and verification smoke check are all represented.
- **Reviewer clarifications:** (1) identifier validation is Task 1 Step 1, before the config is committed; (2) `maxWarnings` sequencing is explicit (placeholder `0` in Task 1, measured `W` in Task 3 Step 4); (3) dependency footprint confirmed three top-level pins, tsgolint binaries transitive; (4) test count is captured/compared, never hardcoded; (5) `.git-blame-ignore-revs` is confirmed absent and created.
- **Measured-not-guessed values:** exact versions (`W`, the reformat SHA) are runtime-measured by the task that needs them, with the exact command to produce them — not placeholders.
