# Feed Export Page Improvements — Design

**Date:** 2026-09-18
**Status:** Approved (design), pending implementation plan
**Scope:** Export page (`frontend/src/features/export/`) — version XML preview, version download, admin-editable export token, and a redesigned human-readable version diff. Adds two backend routes and one small `client.ts` helper. No new dependencies, no DB migration.

## Problem

The Export page shows a version table and lets users compare two versions, but:

1. There is no way to *see* a version's XML. The only public link is `/export/{token}.xml`, which always serves the **currently published** feed, not the row the user clicked.
2. There is no way to download a specific version's XML.
3. The public URL's token is only rotatable to a new random value; admins cannot choose a memorable one.
4. The diff renders two full-width `Code` blocks of raw IDs plus a large accordion of per-product old/new tables. It gives no at-a-glance summary, no field-level breakdown, and ignores the QC findings delta that the history endpoint already returns.

## Decision

Frontend-heavy approach (Approach A): the backend gains exactly two routes; all diff folding, preview rendering, and download assembly live in the frontend.

| Topic | Decision |
|-------|----------|
| Version content | New authenticated `GET /feed-sources/{id}/export-history/{v}/content` returning the stored version file as `application/xml` |
| Preview | Mantine `Modal` + local XML highlighter; cap at 5,000 lines |
| Highlighting | ~60-line local XML tokenizer emitting React spans; **no dependency**, no `dangerouslySetInnerHTML` |
| Download | Same content endpoint fetched via a new `apiGetText()` helper, saved as a Blob |
| Custom token | New admin-only `PUT /feed-sources/{id}/export-token`, minimal path-safe validation |
| Diff summary / field breakdown / findings delta | Computed client-side from the existing `DiffOut` and `ExportVersionOut.findings` |
| Diff product list | Kept, redesigned slimmer and default-collapsed |
| Diff selection sharing | A/B selection persisted in the URL query (`?a=&b=`) |

## Alternatives considered

- **Backend-computed diff summary + paginated `changed` (Approach B).** Scales to very large diffs and is server-testable, but changes the diff API, needs pagination UI, and touches the existing diff tests. Rejected as overkill for current feed sizes; revisit if diffs routinely exceed a few thousand changed products.
- **Hybrid: backend summary counts only (Approach C).** Cheap server-side correctness for headline numbers, but still an API change for a one-pass client-side fold. Rejected.
- **`@speed-highlight/core` for highlighting.** ~2 kB gzip, zero deps, escaped output — genuinely viable, but we only ever highlight XML, and a local tokenizer avoids a dependency and `dangerouslySetInnerHTML` entirely. Rejected by operator choice.
- **Frontend-only preview via the public URL.** Simpler, but every row would show the currently published feed rather than that version. Rejected: misleading.
- **Per-feed custom base URL/domain (DNS routing).** Rejected: infra concern, far larger scope.

## Backend design

### 1. Version content route

`backend/app/routes/export_history.py`

```
GET /feed-sources/{feed_source_id}/export-history/{version_number}/content
```

- Dependencies: `require_user`, inherited `enforce_scope_access` (already applied to `export_history_router` in `main.py:260`), `require_feed_source`.
- Returns `fastapi.Response(content=data, media_type="application/xml")` with the raw stored version bytes.
- Add `ExportService.version_content(feed_source_id, version_number) -> bytes`:
  - Confirm an `ExportVersion` row exists for the pair; if not, raise `LookupError(f"version {version_number} not found")`.
  - Read via `self._store.read_version(...)`; if `None`, raise `LookupError(f"version file {version_number} missing")`.
- Route maps `LookupError` → `HTTPException(404, detail=str(exc))`, matching `export_diff`/`export_rollback`.
- No `Content-Disposition` header — the frontend decides preview vs download. The same bytes back both.

### 2. Admin export-token route

`backend/app/routes/clients.py` (same router as the existing `/export-token/rotate`), schema in `backend/app/schemas/clients.py`.

```
PUT /feed-sources/{feed_source_id}/export-token
body: { "export_token": "<value>" }
→ 200 { "export_token": "<value>", "export_url": "..." }
```

- `require_admin` (non-admin → 403), plus inherited `enforce_scope_access`; `require_feed_source` for existence.
- Add `ExportTokenUpdate(BaseModel)` with a `field_validator("export_token")` enforcing:
  - length 1–64 (column is `String(64)`);
  - the full string matches `^[A-Za-z0-9_~-]+$`. This is the set of URL path-safe unreserved characters, so a token cannot break out of the path segment (`/`, `?`, `#`, `%`, whitespace, etc. are all rejected). **`.` is deliberately excluded** because the public route is `/export/{token}.xml` and a dot would make the segment split ambiguous.
  - Invalid → 422 (pydantic).
- Uniqueness: pre-check `select(FeedSource).where(FeedSource.export_token == value)`; on collision → `409 {"detail": "export token already in use"}`. Also catch `IntegrityError` on flush (the `uq_feed_sources_export_token` index) and map to the same 409, so a race is not a 500.
- On success: set `feed_source.export_token`, flush, audit `feed_source.export_token.set`, return `{"export_token": token, "export_url": _export_url(settings, token)}`.
- Add `ExportTokenOut(BaseModel)` (`export_token: str`, `export_url: str`) and use it as the `response_model` for **both** this route and the existing `rotate_export_token` (which keeps its behavior and path unchanged; only its response typing is tightened).
- **Minimal validation is deliberate** (operator choice): a short slug like `shop` is allowed and is enumerable. The frontend shows a non-blocking weak-value hint (see below); the backend does not force unguessability.

## Frontend design

### 3. API helper

`frontend/src/api/client.ts`:

- Extract the existing fetch/error-handling preamble of `request()` into a private `fetchWithContext(url, init): Promise<Response>` (adds `credentials: 'include'` and `X-Request-ID`, maps non-OK to `ApiError` via `parseError`, fires the unauthorized handler). `request()` and the new helper both use it, so correlation and auth behavior are not duplicated.
- Add `apiGetText(url): Promise<string>` — `fetchWithContext` then `response.text()`. Used for preview and download.

`frontend/src/api/queryKeys.ts` — add under `feedSource(id)`:

```ts
exportVersionContent: (version: number) =>
  ['feed-source', id, 'export-version-content', version] as const,
```

`frontend/src/api/hooks.ts`:

- `useExportVersionContent(feedSourceId, version, enabled)` — `useQuery` over `apiGetText(\`/feed-sources/${feedSourceId}/export-history/${version}/content\`)`, `enabled: enabled && version !== undefined`.
- `useSetExportToken(feedSourceId)` — `useMutation` calling `apiPut` on the token route; on success invalidates `queryKeys.feedSource(feedSourceId).detail`.

### 4. XML highlighter

`frontend/src/components/XmlHighlight.tsx` (no new dependency).

- Pure tokenizer function `tokenizeXml(xml: string): Token[]` where `Token = { text: string; kind: 'tag' | 'attr' | 'string' | 'comment' | 'cdata' | 'decl' | 'text' | 'entity' }`.
- Rules, in one left-to-right scan:
  - `<!-- … -->` → `comment`
  - `<![CDATA[ … ]]>` → `cdata`
  - `<? … ?>` → `decl`
  - `<!DOCTYPE …>` → `decl`
  - `<` or `</` tag open/close, tag name, `/>` and `>` → `tag`
  - within a tag, `name=` attribute names → `attr`
  - quoted attribute values → `string`
  - `&name;` / `&#n;` → `entity`
  - everything between tags → `text`
- Malformed XML must not throw: unmatched `<` is emitted as `text`. The tokenizer never produces HTML; output is React `<span>` elements, so the input is inherently escaped.
- Colors come from a `TOKEN_COLOR` map keyed by `: 'light' | 'dark'`, selected with Mantine's `useComputedColorScheme('light')` and applied as inline `style={{ color }}`. No new CSS file.
- Props: `{ xml: string; maxLines?: number }`; when `maxLines` is set and exceeded, renders the first `maxLines` lines and reports `{ shownLines, totalLines, truncated }` via the component's rendered header (the parent also needs the counts for the banner — expose a helper `sliceXmlLines(xml, maxLines)` returning `{ text, totalLines, truncated }`, used by the modal).
- Rendered inside a Mantine `<pre>` with a line-number gutter (a second column of dimmed numbers); monospace; horizontal scroll; text stays selectable/copyable.

### 5. Version preview modal

`frontend/src/features/export/FeedVersionPreviewModal.tsx`

- Props: `{ feedSourceId, version: number | null, opened, onClose }`.
- `export function FeedVersionPreviewModal` renders a Mantine `Modal` (`size="xl"`, title `t('preview.title', { version })`).
- Content states: loading (`LoadingState`), error (`ErrorState` with retry), 404 → `EmptyState` with `t('preview.notRetained')`, success → `XmlHighlight` with `maxLines={5000}`.
- When truncated, an `Alert` above the code reads `t('preview.truncated', { shown, total })`.
- Footer: a Download `Button` (shared handler, below).

### 6. Download

`frontend/src/features/export/download.ts`

- `downloadVersionXml(feedSourceId, version, xml?)`: if `xml` is provided (already fetched in the modal) reuse it; otherwise `await apiGetText(...)`. Build `new Blob([xml], { type: 'application/xml' })`, `URL.createObjectURL`, click a temporary `<a download="feed-{feedSourceId}-v{version}.xml">`, then revoke the object URL.
- Errors surface through `notifyMutationError`/`notifyApiError` at the call site.
- Downloads always go through `client.ts`, preserving `X-Request-ID`/auth handling (frontend AGENTS convention).

### 7. Version list row actions

`frontend/src/features/export/ExportVersionList.tsx`

- Add an Actions column with two `ActionIcon`s: eye (`IconEye`, opens preview) and download (`IconDownload`, calls `downloadVersionXml`). Both carry `title` + `aria-label` (`preview.openFor`/`download.version`, with the version number), matching the existing rollback icon pattern.
- New props: `onPreview(version)` and `onDownload(version)`.
- "Live" badge on the newest row: `versions[0]` is the published version (export and rollback both publish the newest). Rendered as a small green `Badge` next to the version number with `data-testid="live-badge"`.
- Timestamps: keep the absolute `L LTS` and append a dimmed relative value (`dayjs(...).fromNow()`).

### 8. Diff redesign

`frontend/src/features/export/ExportVersionDiff.tsx`

- Title row: `t('diffTitle', { version, against })` plus each version's timestamp.
- **Summary stat cards** (`SimpleGrid`): products added / removed / changed / total fields changed, each a small `Card` with a count and label.
- **Findings delta** card: for each severity, `old → new` with green/red emphasis based on sign; if either compared version has `findings === null` (rollback) or is absent from the version list, render the "not QC'd" note instead of a numeric delta. Data comes from the parent (`versions`) via two new props `findingsA` / `findingsB`; no backend change.
- **Field breakdown**: fold `diff.changed[].fields` into `Map<field, productCount>`, sort desc by count, render as a compact list of `Badge`s with counts. Clicking a badge sets a `selectedField` state that filters the product list below; clicking again clears it.
- **Added/removed**: replace the two full-width `Code` blocks with compact `Badge` rows showing the count and, in a collapsed `ScrollArea`, the IDs. Empty sections render nothing.
- **Per-product list**: keep the `Accordion`, restyled slimmer — default-collapsed (controlled `value={[]}` initially), tighter padding, mono values, `JSON.stringify(v) === 'null'`/`undefined` rendered as dimmed `(empty)`, long values truncated with the full value in `title`.
- No search box and no inline character-level highlighting (not selected by the operator).

### 9. URL block admin editor

`frontend/src/components/ExportUrlBlock.tsx`

- `useSession()`; `isAdmin = session?.role === 'admin'`.
- Rotate stays exactly as today for all authenticated users (its route is `require_user`); do not change that permission.
- All users keep the read-only `CopyField` and the Rotate button.
- Admins additionally get a `TextInput` prefilled with the current token, a Save (`IconCheck`, calls `useSetExportToken`), and the Rotate button relabeled to `t('generateRandom')` (still `useRotateExportToken`).
- Save opens `ConfirmModal` (`t('changeWarning')`: the old URL stops working immediately). A non-blocking hint renders under the input when the value is < 8 chars or all-numeric (`t('weakHint')`).
- On success: `notifySuccess`, refetch feed (`onRotated`).

### 10. Export page wiring

`frontend/src/features/export/ExportPage.tsx`

- New state `previewVersion: number | null`; render `<FeedVersionPreviewModal/>`.
- Pass `onPreview={setPreviewVersion}` to the list. `onDownload` is an async handler that `await`s `downloadVersionXml(id, version)` inside a `try`/`catch` and calls `notifyApiError(error, t('download.failed'))` on failure.
- A/B selection synced to the URL query via `useSearchParams`: read `a`/`b` on mount into `versionA`/`versionB`; write them (and remove when unset) on change. Existing "selection changed → reset compared" logic stays.
- The compare `Button` and diff render conditionally only once both are selected, as today.

### 11. i18n

Add keys to `frontend/public/locales/en/export.json` and `de/export.json` (all new user-facing strings):

`preview.title`, `preview.openFor`, `preview.notRetained`, `preview.truncated`, `download.version`, `download.failed`, `liveBadge`, `generateRandom`, `customToken`, `changeToken`, `changeWarning`, `tokenSaved`, `tokenSaveFailed`, `weakHint`, `diff.summary.added`, `diff.summary.removed`, `diff.summary.changed`, `diff.summary.fields`, `diff.findingsDelta`, `diff.notQcd`, `diff.byField`, `diff.allFields`, `diff.emptyValue`.

## Testing

**Backend** (`uv run pytest`):

- Content route: returns the exact stored bytes with `application/xml`; 404 for an unknown version; 404 when the version row exists but the file was pruned; 404 for a feed source outside a client user's scope; 401 without a session.
- Token route: admin sets a valid token → 200 and the public URL changes; non-admin → 403; duplicate → 409; `/`, `.`, whitespace, empty, >64 chars → 422; audit row written.

**Frontend** (`npm run test`):

- `XmlHighlight.test.tsx`: tokenizes tag/attr/string/comment/entity; unmatched `<` does not throw; `sliceXmlLines` reports `truncated` and the correct total.
- `ExportPage.test.tsx`: eye opens the modal and fetches `/content`; download builds a Blob (stub `URL.createObjectURL`); live badge on the newest row only; `?a=`/`?b=` selection round-trips.
- `ExportVersionDiff.test.tsx`: summary counts; field breakdown aggregates by field; findings delta shows `old → new`; rollback side shows not-QC'd; field badge filters the product list.
- `ExportUrlBlock.test.tsx`: non-admin sees no editor; admin save issues the `PUT` and shows confirmation; weak hint appears for a short value.

## Verification

- Backend: `cd backend && uv run ruff check . ../plugins && uv run mypy . && uv run pytest`.
- Frontend: `cd frontend && npm run test && npm run typecheck && npm run lint && npm run format:check`.
- Manual: preview a large feed → banner + scroll; download → file opens as valid XML; set a custom token → public URL serves at the new path; rotate still works; diff summary/field breakdown/findings delta match the underlying data.

## Docs updated in the same commit

- `backend/docs/api.md` — the two new routes (Export History, Export Token sections).
- `backend/docs/architecture.md` — export history description mentions version content.
- `frontend/AGENTS.md` — no new convention required (no dependency, no new store); only update if the plan introduces one.

## Risks and non-goals

- **Weak custom tokens are enumerable.** Accepted by the operator; mitigated only by a frontend hint. The default random token and Rotate remain available.
- **Client-side field folding is O(changed products × fields).** Fine for current feeds; if it ever stalls, move to Approach B (server summary + pagination).
- **Preview cap hides the tail.** Truncation is explicit and the full file is downloadable.
- **`apiGetText` refactor of `request()`** touches a shared path; covered by existing API hook tests plus the new preview tests.
- **Non-goals:** server-computed diff summaries/pagination, findings-detail diff, preview/download of the live feed from the URL block, per-version file size, and any new dependency or DB migration.

## References

- `backend/app/routes/export_history.py`, `backend/app/export/service.py`, `backend/app/export/store.py`, `backend/app/routes/clients.py`, `backend/app/schemas/export.py`, `backend/app/access.py`.
- `frontend/src/features/export/`, `frontend/src/components/ExportUrlBlock.tsx`, `frontend/src/api/client.ts`, `frontend/src/api/hooks.ts`, `frontend/src/api/queryKeys.ts`.
- `backend/docs/api.md` (Export History, Export Token, Public Export Endpoint), `backend/docs/architecture.md`.
- `@speed-highlight/core` README (evaluated, not adopted).
