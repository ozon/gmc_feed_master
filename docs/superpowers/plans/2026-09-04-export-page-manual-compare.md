# Manual Version Comparison on Export Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace automatic version diff comparison with a manual "Compare Versions" button on the Export page.

**Architecture:** Add a `compared` state flag that gates the diff query. Remove the auto-select `useEffect`. Add a button that triggers the comparison when both versions are selected.

**Tech Stack:** React 19, Mantine UI, TanStack Query, TypeScript

## Global Constraints
- React 19 + TypeScript
- Mantine UI components
- TanStack Query for server state
- i18next for translations

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `frontend/src/features/export/ExportPage.tsx` | Modify | Remove auto-select, add compare button, gate diff query |

---

### Task 1: Add Manual Compare Button to ExportPage

**Files:**
- Modify: `frontend/src/features/export/ExportPage.tsx`

**Interfaces:**
- Consumes: `useExportVersionDiff(id, versionA, versionB)` from existing hooks
- Produces: Same component with updated behavior

- [ ] **Step 1: Update imports**

Add `Button` to Mantine imports and `IconGitCompare` to tabler icons:

```tsx
import { Button, Stack, Title } from '@mantine/core';
import { IconGitCompare } from '@tabler/icons-react';
```

- [ ] **Step 2: Remove auto-select useEffect**

Delete lines 32-39 (the `useEffect` that auto-selects versions).

- [ ] **Step 3: Add compared state and reset logic**

After the `versionB` state declaration, add:

```tsx
const [compared, setCompared] = useState(false);
```

Add a new `useEffect` to reset `compared` when version selections change:

```tsx
useEffect(() => {
  setCompared(false);
}, [versionA, versionB]);
```

- [ ] **Step 4: Gate the diff query**

Change the diff hook call to only fetch when `compared` is true:

```tsx
const diff = useExportVersionDiff(id, compared ? versionA : undefined, compared ? versionB : undefined);
```

- [ ] **Step 5: Add the Compare button**

After the `ExportVersionList` component and before `ExportVersionDiff`, add:

```tsx
{versionA !== undefined && versionB !== undefined && !compared && (
  <Button
    leftSection={<IconGitCompare size={16} />}
    onClick={() => setCompared(true)}
    data-testid="compare-versions-button"
  >
    {t('compareVersions')}
  </Button>
)}
```

- [ ] **Step 6: Run typecheck**

Run: `npm run typecheck`
Expected: PASS

- [ ] **Step 7: Run tests**

Run: `npm run test`
Expected: PASS (existing tests should still pass)

- [ ] **Step 8: Update i18n translation key**

Check `frontend/public/locales/en/export.json` for `compareVersions` key. If missing, add:

```json
"compareVersions": "Compare Versions"
```

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/export/ExportPage.tsx frontend/public/locales/en/export.json
git commit -m "feat(export): add manual compare button instead of auto-compare"
```
