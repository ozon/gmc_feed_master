# Z1: AI-Restarbeiten Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the deferred AI-integration gaps: usage time filters, malformed-brace warnings, non-canonical declared variables as errors, activation deadlock → 409, content-hashed builtin template version.

**Architecture:** Four small backend changes in the AI module (templates/service/routes) plus two frontend touches (UsagePage, TemplateEditor). No schema changes, no new endpoints.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic; React 19 + Mantine + TanStack Query.

**Spec:** `docs/superpowers/specs/2026-09-12-ai-restarbeiten-design.md`

## Global Constraints

- Backend gates (from `backend/`): `uv run ruff check .` (count must stay ≤ `ruff-baseline.txt`, zero new), `uv run mypy .` (exit-0), `uv run pytest` (needs `TEST_DATABASE_URL`; activate env with `set -a; source ../.env; set +a`).
- Frontend gates (from `frontend/`): `npm run typecheck`, `npx vitest run`, `npm run build`.
- i18n parity: every new key in `public/locales/en/*.json` AND `de/*.json`.
- Logger calls use lazy `%s` interpolation, never f-strings.
- Docs updated in the same commit as the behavior change.
- Commit style: conventional commits (`feat:`, `test:`, `docs:`).

---

### Task 1: validate_template — malformed-brace warning + non-canonical declared error

**Files:**
- Modify: `backend/app/ai/templates.py`
- Test: `backend/tests/test_ai_templates.py`

**Interfaces:**
- Produces: `malformed_placeholders(text: str) -> list[str]` (module-level); `validate_template` gains one error class and one warning class.

- [x] **Step 1: Write failing tests** — append to `backend/tests/test_ai_templates.py`:

```python
def test_malformed_brace_warns():
    result = validate_template(["title"], "Say {{title}} and {{Title}}", "", ["title"])
    assert result.errors == []
    assert any("{{Title}}" in w for w in result.warnings)


def test_valid_braces_do_not_warn():
    result = validate_template(["title"], "Say {{ title }}", "", ["title"])
    assert result.warnings == []


def test_empty_braces_warn():
    result = validate_template(["title"], "Say {{}}", "", ["title"])
    assert any("{{}}" in w for w in result.warnings)


def test_declared_non_canonical_is_error():
    result = validate_template(["title"], "{{title}}", "", ["title", "bogus"])
    assert "declared variable 'bogus' is not a canonical variable of this task type" in result.errors
    assert result.warnings == []


def test_declared_unused_canonical_still_warns():
    result = validate_template(["title", "brand"], "{{title}}", "", ["title", "brand"])
    assert result.errors == []
    assert "declared variable 'brand' is not used in the template" in result.warnings
```

- [x] **Step 2: Run** `uv run pytest tests/test_ai_templates.py -k "malformed or declared" -v` — expect the new tests FAIL (no malformed warning; bogus only warns today).

- [x] **Step 3: Implement** in `backend/app/ai/templates.py`:

Add after `PLACEHOLDER_RE`:

```python
MALFORMED_BRACE_RE = re.compile(r"\{\{[^{}]*\}\}")


def malformed_placeholders(text: str) -> list[str]:
    """Brace pairs that look like placeholders but fail the identifier grammar."""
    seen: set[str] = set()
    out: list[str] = []
    for candidate in MALFORMED_BRACE_RE.findall(text):
        if candidate in seen:
            continue
        seen.add(candidate)
        if PLACEHOLDER_RE.fullmatch(candidate) is None:
            out.append(candidate)
    return out
```

In `validate_template`, replace the declared-unused loop:

```python
    for name in sorted(declared - used):
        if name in canonical:
            warnings.append("declared variable %r is not used in the template" % name)  # noqa: UP031
        else:
            errors.append(
                "declared variable %r is not a canonical variable of this task type" % name  # noqa: UP031
            )
```

And append before `return`:

```python
    for candidate in malformed_placeholders(system_prompt) + malformed_placeholders(user_prompt):
        warnings.append(
            "malformed placeholder %s — variables must be lowercase identifiers" % candidate  # noqa: UP031
        )
```

- [x] **Step 4: Run** `uv run pytest tests/test_ai_templates.py -v` — ALL pass (existing tests too; if an existing test asserted non-canonical-declared as warning, update it to the new error expectation).

- [x] **Step 5: Commit** `git add backend/app/ai/templates.py backend/tests/test_ai_templates.py && git commit -m "feat: malformed-brace warning and non-canonical declared variables as errors"`

---

### Task 2: Activation deadlock → 409

**Files:**
- Modify: `backend/app/routes/ai_admin.py` (create_prompt_template + activate_prompt_template)
- Test: `backend/tests/test_ai_admin_conflicts.py` (new)

**Interfaces:**
- Produces: `_is_deadlock(exc: OperationalError) -> bool` in `ai_admin.py`.

- [x] **Step 1: Write failing tests** — create `backend/tests/test_ai_admin_conflicts.py`:

```python
from sqlalchemy.exc import OperationalError

from app.routes.ai_admin import _is_deadlock


def test_is_deadlock_detects_asyncpg_message():
    exc = OperationalError("stmt", {}, Exception("deadlock detected"))
    assert _is_deadlock(exc) is True


def test_is_deadlock_ignores_other_operational_errors():
    exc = OperationalError("stmt", {}, Exception("connection refused"))
    assert _is_deadlock(exc) is False
```

- [x] **Step 2: Run** `uv run pytest tests/test_ai_admin_conflicts.py -v` — FAIL (import error: `_is_deadlock` missing).

- [x] **Step 3: Implement** in `backend/app/routes/ai_admin.py`:

Change import: `from sqlalchemy.exc import IntegrityError, OperationalError`.

Add helper near `_require_db`:

```python
def _is_deadlock(exc: OperationalError) -> bool:
    return "deadlock" in str(getattr(exc, "orig", exc)).lower()
```

In `create_prompt_template`, extend the except clause:

```python
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="concurrent template modification; retry"
        ) from exc
    except OperationalError as exc:
        if not _is_deadlock(exc):
            raise
        raise HTTPException(
            status_code=409, detail="concurrent template modification; retry"
        ) from exc
```

In `activate_prompt_template`, same pattern with detail `"concurrent activation; retry"`.

- [x] **Step 4: Run** `uv run pytest tests/test_ai_admin_conflicts.py tests/test_ai_admin_api.py -v` — pass.

- [x] **Step 5: Commit** `git add backend/app/routes/ai_admin.py backend/tests/test_ai_admin_conflicts.py && git commit -m "feat: map activation deadlock to 409"`

---

### Task 3: Builtin template version becomes content-hashed

**Files:**
- Modify: `backend/app/ai/service.py`
- Test: `backend/tests/test_ai_service.py`

**Interfaces:**
- Produces: `builtin_template_version(spec: TaskSpec) -> str` (module-level in service.py); format `"builtin:<12 hex>"`.

- [x] **Step 1: Write failing test** — append to `backend/tests/test_ai_service.py`:

```python
from app.ai.service import builtin_template_version
from app.ai.tasks import TASK_SPECS, TaskSpec


def test_builtin_version_is_content_hashed():
    spec = TASK_SPECS["title_optimization"]
    v1 = builtin_template_version(spec)
    assert v1.startswith("builtin:")
    changed = TaskSpec(system=spec.system + "x", user=spec.user, validate=spec.validate)
    assert builtin_template_version(changed) != v1
    assert builtin_template_version(spec) == v1
```

- [x] **Step 2: Run** `uv run pytest tests/test_ai_service.py -k builtin_version -v` — FAIL (import error).

- [x] **Step 3: Implement** in `backend/app/ai/service.py`:

Add `import hashlib` at the top. Extend the tasks import: `from .tasks import TASK_SPECS, TaskSpec, input_hash, validate_task`.

Add after `TEMPLATE_VERSION_BUILTIN = "builtin"`:

```python
def builtin_template_version(spec: TaskSpec) -> str:
    """Content-hash the builtin prompts so any code change auto-invalidates cache rows."""
    digest = hashlib.sha256(
        (spec.system + "\x00" + spec.user).encode("utf-8")
    ).hexdigest()[:12]
    return f"{TEMPLATE_VERSION_BUILTIN}:{digest}"
```

In `_resolve_template`, change the fallback:

```python
        return ResolvedTemplate(
            system=spec.system, user=spec.user, version=builtin_template_version(spec)
        )
```

- [x] **Step 4: Run** `uv run pytest tests/test_ai_service.py tests/test_ai_cache_usage.py -v` — if any existing test asserts the literal version `"builtin"`, update it to the new `builtin:<hash>` shape (grep: `rg '"builtin"' tests/`).

- [x] **Step 5: Commit** `git add backend/app/ai/service.py backend/tests/test_ai_service.py && git commit -m "feat: content-hashed builtin template version (cache auto-invalidation)"`

---

### Task 4: UsagePage time-range filters

**Files:**
- Modify: `frontend/src/features/admin/ai/UsagePage.tsx`
- Create: `frontend/src/features/admin/ai/usageDates.ts`
- Test: `frontend/src/features/admin/ai/UsagePage.test.tsx` (new), `frontend/src/features/admin/ai/usageDates.test.ts` (new)
- i18n: `frontend/public/locales/en/admin.json`, `de/admin.json`

**Interfaces:**
- Produces: `usageDateParams(from: Date | null, to: Date | null) -> { from?: string; to?: string }` — `from` = picked date 00:00 ISO, `to` = picked date 23:59:59 ISO.

- [x] **Step 1: Write failing tests**:

`usageDates.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { usageDateParams } from './usageDates';

describe('usageDateParams', () => {
  it('builds from at midnight and to at end of day', () => {
    const from = new Date(2026, 8, 1);   // Sep 1 2026, local
    const to = new Date(2026, 8, 12);
    const params = usageDateParams(from, to);
    expect(params.from).toBe(new Date(2026, 8, 1).toISOString());
    expect(params.to).toBe(new Date(2026, 8, 12, 23, 59, 59).toISOString());
  });
  it('omits unset dates', () => {
    expect(usageDateParams(null, null)).toEqual({});
  });
});
```

`UsagePage.test.tsx` (follow the stub-fetch pattern from `src/test/fetch.ts` and QueryClient wrapper from existing admin tests):

```tsx
import { render, screen } from '../../test-utils/render'; // use the project's render helper (see src/test/)
// assert: two DateInputs with labels exist, the group-by Select exists
```

Write the render assertions concretely: after rendering `<UsagePage />` with stubbed `GET /admin/ai/usage`, `screen.getByLabelText(/from/i)` and `screen.getByLabelText(/to/i)` exist.

- [x] **Step 2: Run** `npx vitest run src/features/admin/ai` — FAIL (files missing).

- [x] **Step 3: Implement** `usageDates.ts`:

```ts
export function usageDateParams(from: Date | null, to: Date | null): { from?: string; to?: string } {
  return {
    from: from ? new Date(from.getFullYear(), from.getMonth(), from.getDate()).toISOString() : undefined,
    to: to ? new Date(to.getFullYear(), to.getMonth(), to.getDate(), 23, 59, 59).toISOString() : undefined,
  };
}
```

In `UsagePage.tsx`: import `DateInput` from `@mantine/dates` and `usageDateParams`; add state `const [fromDate, setFromDate] = useState<Date | null>(null); const [toDate, setToDate] = useState<Date | null>(null);`; pass both into `useAiUsage({ group_by: groupBy, ...usageDateParams(fromDate, toDate) })`; render two `DateInput`s (labels `t('ai.usage.from')` / `t('ai.usage.to')`, `clearable`, `value/onChange`) next to the group-by Select inside a `Group`.

Add i18n keys to `en/admin.json` under `ai.usage`: `"from": "From"`, `"to": "To"`; German: `"from": "Von"`, `"to": "Bis"`.

- [x] **Step 4: Run** `npx vitest run src/features/admin/ai && npm run typecheck` — pass.

- [x] **Step 5: Commit** `git add frontend/src/features/admin/ai frontend/public/locales && git commit -m "feat: usage page time-range filters"`

---

### Task 5: TemplateEditor malformed-brace mirror

**Files:**
- Modify: `frontend/src/features/admin/promptLibrary/TemplateEditor.tsx`
- Test: `frontend/src/features/admin/promptLibrary/PromptLibraryPage.test.tsx`
- i18n: `en/admin.json`, `de/admin.json`

**Interfaces:**
- Consumes: `PLACEHOLDER_RE` from `./HighlightedTextarea` (global regex — do NOT use `.test()` on it; use a local anchored regex).

- [x] **Step 1: Write failing test** — append to the `TemplateEditor` describe in `PromptLibraryPage.test.tsx`:

```tsx
it('shows a malformed-brace warning for {{Title}}', async () => {
  // render TemplateEditor (existing helper pattern in this file), type "Check {{Title}}"
  // into the user prompt textarea, then:
  expect(screen.getByTestId('malformed-brace-{{Title}}')).toBeInTheDocument();
});
```

(Use the same render + `userEvent` plumbing the existing editor tests in this file already use; type into the user-prompt textarea which is the second `HighlightedTextarea`.)

- [x] **Step 2: Run** `npx vitest run src/features/admin/promptLibrary` — FAIL.

- [x] **Step 3: Implement** in `TemplateEditor.tsx`:

```tsx
const ANCHORED_PLACEHOLDER = /\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}/; // non-global: safe .test()
const MALFORMED_RE = /\{\{[^{}]*\}\}/g;

function malformedBraces(text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(MALFORMED_RE)) {
    if (!ANCHORED_PLACEHOLDER.test(m[0])) out.push(m[0]);
  }
  return [...new Set(out)];
}
```

In the component: `const malformed = [...new Set([...malformedBraces(system), ...malformedBraces(user)])];` and render after the `unusedDeclared` block:

```tsx
{malformed.map((b) => (
  <Text key={b} c="orange" size="sm" data-testid={`malformed-brace-${b}`}>
    {t('promptLibrary.editor.malformedBrace', { brace: b })}
  </Text>
))}
```

i18n en: `"malformedBrace": "Malformed placeholder {{brace}} — variables must be lowercase identifiers"`; de: `"malformedBrace": "Ungültiger Platzhalter {{brace}} — Variablen müssen Kleinbuchstaben-Bezeichner sein"`.

- [x] **Step 4: Run** `npx vitest run src/features/admin/promptLibrary && npm run typecheck` — pass (all existing tests too).

- [x] **Step 5: Commit** `git add frontend/src/features/admin/promptLibrary frontend/public/locales && git commit -m "feat: live malformed-brace warning in template editor"`

---

### Task 6: Docs + full gates

**Files:**
- Modify: `backend/docs/api.md` (activate/create 409 wording mentions deadlock; `from`/`to` documented on usage — verify wording exists, extend if missing)
- Modify: `backend/docs/data-model.md` (builtin template_version is content-hashed)
- Modify: `docs/decisions.md` (Z1 entry: non-canonical → error is a deliberate breaking change; content-hash chosen over delete-on-activate)

- [x] **Step 1: Update the three docs** — append a dated Z1 entry to decisions.md (Topic/Decision/Rationale format used in that file).

- [x] **Step 2: Run all gates**:

```bash
# backend/
set -a; source ../.env; set +a
uv run ruff check . && uv run mypy . && uv run pytest
# frontend/
npm run typecheck && npx vitest run && npm run build
```

Expected: ruff ≤ baseline with zero new, mypy exit-0, pytest 0 failed, vitest all pass, build clean.

- [x] **Step 3: Commit** `git add -A && git commit -m "docs: z1 ai restarbeiten cycle notes"`
