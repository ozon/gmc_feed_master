# Frontend Lint and Format with Oxc — Design

**Date:** 2026-09-18
**Status:** Approved (design), pending implementation plan
**Scope:** Frontend `oxlint` linter + `oxfmt` formatter + `oxlint-tsgolint` type-aware linting; config files, npm scripts, CI gate, and a one-time `src/` reformat. Supersedes TODO 9A.14 / review-remediation plan Task 14 (eslint + typescript-eslint).

## Problem

The frontend has **no lint or format tooling**: `frontend/package.json` has no lint script, and there is no eslint/prettier/`.editorconfig`. The hook-order bug class that review-remediation Task 4 fixed by hand is not statically enforced.

TODO 9A.14 (Task 14: adopt `eslint` + `typescript-eslint` + `eslint-plugin-react-hooks` + `eslint-plugin-react-refresh`) is blocked by an ecosystem conflict: `typescript-eslint@8.x` hard-fails at import on the repo's `typescript 7.0.2` pin, because the TS 7 native package ships no JS AST API (`require('typescript')` exports only `version`/`versionMajorMinor`). No released `typescript-eslint` supports TS ≥7 (upstream `typescript-eslint/typescript-eslint#10940`), and plain ESLint cannot parse TS syntax, so partial adoption is impossible.

The operator has chosen to **keep TypeScript 7.0.2**. That pin is scaffold-era (`92205a3`, 2026-08-24), not an ADR decision, but it is now binding.

## Decision

Adopt the Oxc toolchain:

| Topic | Decision |
|-------|----------|
| Linter | `oxlint` (Rust-native; needs no TS compiler API, so it is TS7-proof) |
| Formatter | `oxfmt` (Rust-native, Prettier-compatible; beta — pinned exact) |
| Type-aware linting | `oxlint-tsgolint` behind `oxlint --type-aware`; **requires TypeScript 7.0+**, which the repo already has |
| TypeScript | Stays at `7.0.2` — no downgrade, no side-by-side copy |
| Config files | `frontend/.oxlintrc.json` (jsonc) + `frontend/.oxfmtrc.json` |
| Enforcement | Errors zero; warnings pinned to a captured baseline via `maxWarnings`; both linted and format-checked in CI |
| Formatting scope | `frontend/src` only (not configs, JSON, or Markdown) |
| Formatting rollout | One isolated formatting-only commit + `.git-blame-ignore-revs` entry |
| ESLint | Never adopted; `eslint-plugin-react-hooks`/`react-refresh` replaced by oxlint's native rules |

Rationale: Oxc's parsers are self-contained, so the TS 7 blocker disappears entirely; oxlint natively ports `react-hooks/rules-of-hooks`, `react-hooks/exhaustive-deps`, and `react/only-export-components` (the `eslint-plugin-react-refresh` rule); and `oxlint-tsgolint` builds TS programs with `typescript-go` and implements 59 of 61 `typescript-eslint` type-aware rules — recovering most of what Task 14 originally wanted, on top of TS 7 rather than instead of it. It is also the same toolchain family as the repo's existing Vite 8 / rolldown stack.

## Alternatives considered

- **Biome** (single lint+format tool; `useHookAtTopLevel`, `useExhaustiveDependencies`, `useComponentExportOnlyModules`, Biotype). Viable and more mature as a formatter, but the operator chose Oxc for closer ESLint rule parity and the `typescript-go` type-aware path.
- **Downgrade TypeScript to 6.0.3** so the original `typescript-eslint` plan runs. Rejected: operator wants TS 7 kept.
- **Wait for `typescript-eslint` TS7 support** (#10940). Rejected: indefinite; the operator wants a gate now.
- **Side-by-side TS 6 (for ESLint) + TS 7 (for `tsc`)**. Rejected: npm has no clean way to point `typescript-eslint`'s `typescript` peer at a second copy; fragile for no benefit over Oxc.

## Configuration

### Dependencies

Add to `frontend/devDependencies`, pinned to exact versions (repo convention — no `^` ranges): `oxlint`, `oxfmt`, `oxlint-tsgolint`. These are the only three top-level pins: `oxlint-tsgolint`'s `@oxlint-tsgolint/<platform>` binaries are transitive `optionalDependencies`, and `typescript-go` is embedded in those binaries (it is not a separate package to pin). Versions current at design time were `oxlint@1.83.0`, `oxfmt@0.68.0`, `oxlint-tsgolint@7.0.2002`; the implementing task pins whatever is current then and records the exact three versions in `docs/decisions.md`.

### `frontend/.oxlintrc.json`

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
    "typescript/no-unused-vars": "warn",
    "eslint/no-unused-vars": "off",
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

Notes (identifiers verified empirically against `oxlint@1.83.0`, see "Rule-name drift" in Risks):
- Setting `plugins` **replaces** oxlint's default plugin set (`unicorn`, `oxc`, `typescript` are on by default; `react` is off), so the array lists every plugin wanted. `react-hooks` is a rule **namespace**, not a plugin identifier — the `react-hooks/*` rules ship with the `react` plugin (there is no `react-hooks` plugin).
- `react/react-in-jsx-scope` is turned off because the app uses React 19's automatic JSX runtime (`"jsx": "react-jsx"`), where the rule is a false positive. `react/hooks` and `react/exhaustive-effect-dependencies` are turned off because they duplicate `react-hooks/rules-of-hooks` and `react-hooks/exhaustive-deps` (the canonical, ESLint-named rules we gate on).
- `"style": "off"` because the formatter owns style; `correctness`/`suspicious`/`perf` are the "broad rules" the operator asked for.
- `maxWarnings` starts at `0` and is overwritten with the captured baseline in the lint-baseline task (see Enforcement). Until then `npm run lint` fails if any warnings exist — that is expected, not a regression.
- `typeCheck` is intentionally **not** enabled: `tsc -b` remains the typecheck gate (`npm run typecheck`), so oxlint stays fast and single-purpose.

### `frontend/.oxfmtrc.json`

```json
{
  "$schema": "./node_modules/oxfmt/configuration_schema.json",
  "printWidth": 100,
  "singleQuote": true
}
```

All other oxfmt defaults already match the codebase: `semi: true`, `trailingComma: "all"`, `tabWidth: 2`, `insertFinalNewline: true`. `printWidth: 100` is oxfmt's default and matches the existing line length; `singleQuote: true` matches the existing code style (oxfmt defaults to double quotes). Import sorting (`sortImports`) stays disabled to avoid churn.

### npm scripts (`frontend/package.json`)

```json
"lint": "oxlint --type-aware src",
"lint:fix": "oxlint --fix src",
"format": "oxfmt --write src",
"format:check": "oxfmt --check src"
```

Type-aware linting is on `lint` (the CI/local gate) but not on `lint:fix` (faster autofix path). `format` and `format:check` are scoped to `src`.

### CI (`.github/workflows/ci.yml`, frontend job)

The frontend job adds one step after install, before the existing test/typecheck/build step:

```yaml
      - name: Lint and format check
        working-directory: frontend
        run: npm run lint && npm run format:check
```

`oxlint` exits non-zero on errors and on warnings over `maxWarnings`; `oxfmt --check` exits non-zero on any unformatted file.

## Enforcement and baseline policy

- **Errors stay zero.** Every rule left at `error` must have zero findings; findings are fixed, not suppressed, unless a specific, commented `oxlint-disable-next-line` with a reason is warranted.
- **Warnings are pinned.** After the first full `npm run lint`, the reported warning count becomes `options.maxWarnings`. Warnings must never grow; a later change that adds one fails CI until it is fixed or the baseline is deliberately lowered (which requires a `docs/decisions.md` note).
- **Disable directives must be justified.** `oxlint --report-unused-disable-directives` is used during the baseline pass to catch stale suppressions.
- The baseline count, exact tool versions, and the beta caveat for `oxfmt` are recorded in `docs/decisions.md`.

## Rollout (task outline; the implementation plan expands this)

1. **Deps, configs, scripts** — add the three pinned devDependencies, `frontend/.oxlintrc.json`, `frontend/.oxfmtrc.json`, and the four npm scripts. No source changes. `npm run lint` will likely fail at this point (any warning over the placeholder `maxWarnings: 0`, plus unfixed errors); that is expected and is resolved in step 3, not by forcing every warning out here.
2. **One-time format commit** — `npm run format` over `src`, committed alone; add a `.git-blame-ignore-revs` entry naming that commit's SHA (the file does not exist today — create it). No logic changes.
3. **Lint baseline** — run `npm run lint`, fix `error` findings, capture the warning count, set `maxWarnings`, remove stale disable directives. Commit findings fixes separately from the baseline number where practical.
4. **CI gate** — add the lint+format step to the frontend job.
5. **Docs and tracker** — update `frontend/AGENTS.md` (HOW commands + lint/format conventions), `docs/decisions.md` (tooling decision, versions, warning baseline, oxfmt-beta note), close TODO 9A.14, and mark review-remediation plan Task 14 as superseded by this design. Add the `TODO.md` cycle-log entry.

## Verification

- After step 2 (reformat): record the current `npm run test` pass count **before** formatting, then assert the identical count after. Do not hardcode a figure — the reformat is semantics-preserving, so any change in count (up or down) is a formatter bug to investigate, not to accept. `npm run typecheck` and `npm run build` must likewise be green before and after.
- `npm run lint` exits 0 (zero errors, warnings ≤ baseline); `npm run format:check` exits 0.
- `oxlint` reports at least one `react-hooks/rules-of-hooks` diagnostic when a deliberate temporary conditional-hook is introduced, and `react/only-export-components` fires on a mixed component/non-component module — proving the gate actually covers the Task-4 class (smoke check, then reverted).
- CI frontend job is green on the branch.

## Risks and non-goals

- **`oxfmt` is beta (0.54.x).** Mitigated by exact pinning, `--check` in CI, and documenting the beta status; upgrades are deliberate, reviewed commits, not automatic.
- **One large formatting diff.** Mitigated by an isolated commit and `.git-blame-ignore-revs` (GitHub and `git blame --ignore-revs-file` then skip it).
- **Type-aware lint cost.** `tsgolint` builds TS programs and can use significant memory on large trees; it runs only in `lint`, not `lint:fix`. The tsconfigs have no `baseUrl`/`paths`, so no TS7-incompatible legacy options exist.
- **Rule-name drift.** Oxc iterates quickly. The identifiers in this spec were verified empirically against `oxlint@1.83.0` (its `--rules` listing prints nothing in that version, so a small probe file with a conditional hook and a mixed component/non-component export was linted to read the real namespaces). Re-validate the same way after any oxlint bump rather than trusting this document.
- **Non-goals:** replacing `tsc -b` (kept as the typecheck gate), `--type-check`, formatting anything outside `src` (configs/JSON/Markdown), editor/LSP setup, JS plugins (alpha), and changing TypeScript's version.

## References

- TODO `9A.14`; `docs/superpowers/plans/2026-09-08-review-remediation.md` Task 14.
- `docs/decisions.md` — "eslint adoption" entry (2026-09-09) and the TS 7 / rolldown notes.
- Oxlint: configuration, type-aware linting, rules reference (`oxc.rs/docs/guide/usage/linter/...`); Oxfmt: configuration and CLI (`oxc.rs/docs/guide/usage/formatter/...`).
- `frontend/package.json`, `frontend/tsconfig.app.json`, `frontend/tsconfig.node.json`, `.github/workflows/ci.yml`.
