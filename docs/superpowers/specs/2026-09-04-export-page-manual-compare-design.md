# Design: Manual Version Comparison on Export Page

## Problem
The Export page automatically triggers a version diff comparison on page load by selecting the two most recent versions. This is unnecessary when the user just wants to view version history, and triggers an API call without user intent.

## Solution
Add a manual "Compare Versions" button that appears only after the user selects two versions via radio buttons.

## Changes

### ExportPage.tsx
1. Remove the `useEffect` that auto-selects versions on page load
2. Add `compared` state (`useState<boolean>(false)`)
3. Gate `useExportVersionDiff` with `compared` flag
4. Add "Compare Versions" button that:
   - Only renders when both `versionA` and `versionB` are defined
   - Sets `compared = true` on click
5. Reset `compared` to `false` when either version selection changes

### UX Flow
1. Page loads → version list shown, no diff fetched
2. User selects version A (radio)
3. User selects version B (radio)
4. "Compare Versions" button appears
5. User clicks button → diff is fetched and displayed
6. If user changes either version selection → diff clears, button reappears

## Files to Modify
- `frontend/src/features/export/ExportPage.tsx`
