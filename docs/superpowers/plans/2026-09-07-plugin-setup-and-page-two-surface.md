# Plugin Setup + Plugin Page (Two-Surface Model) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split each plugin into a **Plugin Page** (dashboard/tool, reachable from the feed navigation) and a **Setup** surface (Pipeline Editor config panel), per the two-surface model: Labelizer page = Bulk IDs only, Labelizer Setup = slot-rules editor; Rules/Filter keep their tool pages and get a hint + link in the panel instead of a raw form.

**Architecture:** `CustomLabelsUI` gains an optional `onlyTab` prop and drops its dead-end read-only hint. Two thin wrappers (`LabelizerPage` ids-only, `LabelizerSetup` rules-only) plus a new static `CONFIG_COMPONENTS` registry (same convention as `CUSTOM_COMPONENTS`, ADR-0002) drive the split. `PluginConfigPanel` picks the surface: CONFIG registry → embed; page-registry only → hint + "Open plugin page" link; neither → RJSF instance settings. `AppShell` renders plugin entries after Setup. Pure frontend — no manifest, backend, or DB changes.

**Tech Stack:** React 19, TypeScript, Mantine 9.5, TanStack Query, i18next, vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-09-07-plugin-setup-and-page-two-surface-design.md`

## Global Constraints

- All UI text via i18next — every new key in BOTH `frontend/public/locales/en/` and `de/`; remove keys whose UI is gone; en/de key sets must stay identical.
- No plugin manifests, backend routes, or DB changes. Plugin component files under `plugins/*/frontend/` stay pure re-export stubs (rules-cycle convention).
- `PluginErrorBoundary`, tier switcher, read-only alert, key-remount semantics in the panel are reused unchanged.
- Commands from `frontend/`: `npm run test -- <file>`, `npm run typecheck`. Known ProductsPage parallel-load flake is pre-existing (solo-green); re-run a file solo before concluding failure.
- RTL `rerender` REMOUNTS in this repo — fresh `render` per scenario.
- Commits follow `feat(frontend): ...` / `docs(frontend): ...` style; docs ship in the same commit as the behavior they describe (or in this cycle's docs task).
- Do not touch files outside each task's list without disclosing it.

---

### Task 1: `CustomLabelsUI` `onlyTab` prop + read-only hint removal

**Files:**
- Modify: `frontend/src/features/customLabels/CustomLabelsUI.tsx`
- Modify: `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx`
- Modify: `frontend/public/locales/en/customLabels.json`, `frontend/public/locales/de/customLabels.json`

**Interfaces:**
- Produces: `CustomLabelsUI` props become `{ pluginId: string; scope: PluginScope; onlyTab?: 'ids' | 'rules' }`. When `onlyTab` is set the component renders that tab's content WITHOUT the `Tabs`/`Tabs.List` wrapper (content shown directly); unset renders both tabs exactly as today. Tasks 2-3 rely on this prop.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx` (the helper `renderUI(scope, route?, handler?)` at ~line 65 renders `<CustomLabelsUI pluginId scope>` — extend it to accept an optional fourth arg `onlyTab` passed through; keep existing three-arg calls working). Add these tests near the tab-behavior tests:

```tsx
it('onlyTab="ids" renders the bulk grid without any rules tab or rules UI', async () => {
  renderUI({ feedSourceId: 1 }, '/clients/1/feeds/1/plugins/custom_labels', undefined, 'ids');
  expect(await screen.findByTestId('slot-grid')).toBeInTheDocument();
  expect(screen.queryByRole('tab', { name: /slot rules/i })).not.toBeInTheDocument();
  expect(screen.queryByRole('tab', { name: /bulk ids/i })).not.toBeInTheDocument();
  expect(screen.queryByTestId('rules-readonly-hint')).not.toBeInTheDocument();
});

it('onlyTab="rules" renders the rules list without the bulk grid', async () => {
  renderUI({ clientId: 1 }, '/clients/1/plugins/custom_labels', undefined, 'rules');
  expect(await screen.findByTestId(/sortable-rule-row|rule-row/)).toBeInTheDocument();
  expect(screen.queryByTestId('slot-grid')).not.toBeInTheDocument();
  expect(screen.queryByRole('tab', { name: /slot rules/i })).not.toBeInTheDocument();
});
```

Adjust the second test's `findByTestId` to the actual rule-row testid used elsewhere in this file (grep `SortableRuleRow` usage in `frontend/src/features/customLabels/SortableRuleRow.tsx` for its `data-testid` and reuse an existing test's query pattern).

- [ ] **Step 2: Run to verify RED**

Run: `npm run test -- CustomLabelsUI` (from `frontend/`)
Expected: the 2 new tests FAIL (component ignores `onlyTab`); all existing tests PASS.

- [ ] **Step 3: Implement `onlyTab`**

In `frontend/src/features/customLabels/CustomLabelsUI.tsx`:

1. Change the signature (line ~64) to accept the prop:

```tsx
export function CustomLabelsUI({
  pluginId, scope, onlyTab,
}: { pluginId: string; scope: PluginScope; onlyTab?: 'ids' | 'rules' }) {
```

2. Extract the two tab-panel contents into locals declared just before `return` (do NOT change the content JSX itself — move it verbatim, keeping all existing lines/handlers; the ids content is currently `Tabs.Panel value="ids"` inner block at lines ~295-351, the rules content is `Tabs.Panel value="rules"` inner block at lines ~355-520):

```tsx
  const idsPanel = (
    <Stack gap="sm">
      {/* …verbatim content of the ids Tabs.Panel (save/cancel buttons, slot-grid,
          emptySlots group)… */}
    </Stack>
  );
  const rulesPanel = (
    <Stack gap="sm">
      {/* …verbatim content of the rules Tabs.Panel (minus the rules-readonly-hint
          block — see Step 4)… */}
    </Stack>
  );
```

3. Replace the `<Tabs>` block (lines ~288-522) with:

```tsx
      {onlyTab === 'ids' ? (
        idsPanel
      ) : onlyTab === 'rules' ? (
        rulesPanel
      ) : (
        <Tabs defaultValue={initialTab} keepMounted={false}>
          <Tabs.List>
            <Tabs.Tab value="ids" disabled={idsUnavailable}>{t('tabs.bulkIds')}</Tabs.Tab>
            <Tabs.Tab value="rules">{t('tabs.slotRules')}</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="ids" pt="sm">{idsPanel}</Tabs.Panel>
          <Tabs.Panel value="rules" pt="sm">{rulesPanel}</Tabs.Panel>
        </Tabs>
      )}
```

Note: `initialTab` (line ~241) stays as-is — it is only used by the Tabs path; the ids panel already handles `idsUnavailable` internally.

- [ ] **Step 4: Remove the dead-end read-only hint**

The rules panel's `rulesReadOnly` hint block (lines ~356-368, `data-testid="rules-readonly-hint"` with the `manageAtClient` Anchor) is deleted entirely: under the two-surface model the rules tab never renders on the Plugin Page (Task 2 makes the page ids-only) and the Pipeline panel provides its own actionable alert. Read-only-ness is still conveyed by the disabled inputs and hidden save/add controls.

- [ ] **Step 5: Update the affected tests**

In `CustomLabelsUI.test.tsx`:
- DELETE `it('at feed tier the read-only hint links to the client-level page', ...)` (~line 392) and `it('feed page shows the short read-only hint with the client-level link', ...)` (~line 695).
- In `it('at feed-source tier the slot-rules tab is read-only ...')` (~line 310): remove the `rules-readonly-hint` assertion (~line 331); keep every other read-only assertion (disabled inputs, absent save/add).
- `it('no override action on the feed page (config read-only there)')` (~line 728) and `it('tier badges navigate ...')` (~line 740) should still pass unchanged — verify, don't rewrite.
- Run the file; fix ONLY failures caused by the hint removal or the Tabs refactor (e.g. a test that clicked the rules tab now needs the tab click to still work — it does, the unset path keeps Tabs).

- [ ] **Step 6: Locale cleanup**

In `frontend/public/locales/en/customLabels.json` and `de/customLabels.json`: remove `rulesReadOnly` and `manageAtClient` keys (first verify with `rg "rulesReadOnly|manageAtClient" frontend/src` that no other usage remains). Keep every other key.

- [ ] **Step 7: Run gates**

Run: `npm run test -- CustomLabelsUI` then `npm run typecheck` (from `frontend/`)
Expected: all PASS (58+ tests minus 2 deleted, plus 2 new).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/customLabels/CustomLabelsUI.tsx \
  frontend/src/features/customLabels/__tests__/CustomLabelsUI.test.tsx \
  frontend/public/locales/en/customLabels.json frontend/public/locales/de/customLabels.json
git commit -m "feat(frontend): labelizer onlyTab prop splits config and data surfaces; drop dead-end hint"
```

---

### Task 2: `LabelizerPage` / `LabelizerSetup` wrappers + `CONFIG_COMPONENTS` registry

**Files:**
- Create: `frontend/src/features/customLabels/LabelizerPage.tsx`
- Create: `frontend/src/features/customLabels/LabelizerSetup.tsx`
- Create: `frontend/src/features/plugin/configComponents.ts`
- Modify: `frontend/src/features/plugin/customComponents.ts` (swap custom_labels entry)
- Test: `frontend/src/features/plugin/configComponents.test.tsx` (new)

**Interfaces:**
- Consumes: `CustomLabelsUI` with `onlyTab` (Task 1).
- Produces (used by Task 3 and the PluginPage path):
  - `LabelizerPage` — default export + named, props `{ pluginId: string; scope: PluginScope }`, renders `CustomLabelsUI` with `onlyTab="ids"`.
  - `LabelizerSetup` — same signature, renders `CustomLabelsUI` with `onlyTab="rules"`.
  - `CONFIG_COMPONENTS: Record<string, ComponentType<{ pluginId: string; scope: PluginScope }>>` in `frontend/src/features/plugin/configComponents.ts`, initially `{ custom_labels: LabelizerSetup }`.
  - `CUSTOM_COMPONENTS.custom_labels` now maps to `LabelizerPage`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/plugin/configComponents.test.tsx`:

```tsx
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { stubFetch } from '../../test/fetch';
import { CONFIG_COMPONENTS } from './configComponents';
import { CUSTOM_COMPONENTS } from './customComponents';

beforeAll(async () => {
  await i18n.loadNamespaces(['common', 'customLabels', 'plugins']);
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  stubFetch((url) => jsonResponse({}));
});

describe('plugin surface registries', () => {
  it('maps custom_labels page to the ids-only surface and setup to the rules-only surface', async () => {
    expect(CONFIG_COMPONENTS.custom_labels).toBeDefined();
    expect(CUSTOM_COMPONENTS.custom_labels).toBeDefined();
    expect(CONFIG_COMPONENTS.custom_labels).not.toBe(CUSTOM_COMPONENTS.custom_labels);
  });

  it('LabelizerPage renders the bulk grid without rules UI', async () => {
    const Page = CUSTOM_COMPONENTS.custom_labels;
    render(<Page pluginId="custom_labels" scope={{ feedSourceId: 1 }} />);
    expect(await screen.findByTestId('slot-grid')).toBeInTheDocument();
    expect(screen.queryByTestId('rules-readonly-hint')).not.toBeInTheDocument();
  });

  it('LabelizerSetup renders rules UI without the bulk grid', async () => {
    const Setup = CONFIG_COMPONENTS.custom_labels;
    render(<Setup pluginId="custom_labels" scope={{ clientId: 1 }} />);
    // rules list renders; no slot grid, no tabs
    expect(screen.queryByTestId('slot-grid')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /slot rules/i })).not.toBeInTheDocument();
  });
});
```

Import `beforeEach` from vitest at the top. (The LabelizerSetup rules-list presence assertion: reuse the rule-row query pattern chosen in Task 1.)

- [ ] **Step 2: Run to verify RED**

Run: `npm run test -- configComponents` (from `frontend/`)
Expected: FAIL — `./configComponents` unresolvable.

- [ ] **Step 3: Implement**

Create `frontend/src/features/customLabels/LabelizerPage.tsx`:

```tsx
import CustomLabelsUI from './CustomLabelsUI';
import type { PluginScope } from '../../api/hooks';

export function LabelizerPage({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  return <CustomLabelsUI pluginId={pluginId} scope={scope} onlyTab="ids" />;
}

export default LabelizerPage;
```

Create `frontend/src/features/customLabels/LabelizerSetup.tsx`:

```tsx
import CustomLabelsUI from './CustomLabelsUI';
import type { PluginScope } from '../../api/hooks';

export function LabelizerSetup({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  return <CustomLabelsUI pluginId={pluginId} scope={scope} onlyTab="rules" />;
}

export default LabelizerSetup;
```

Create `frontend/src/features/plugin/configComponents.ts`:

```tsx
import type { ComponentType } from 'react';
import type { PluginScope } from '../../api/hooks';
import { LabelizerSetup } from '../customLabels/LabelizerSetup';

export type ConfigComponentProps = { pluginId: string; scope: PluginScope };

// Plugin id -> Pipeline Editor Setup surface. Extend as plugins split their
// page and config UIs (ADR-0007 two-surface model).
export const CONFIG_COMPONENTS: Record<string, ComponentType<ConfigComponentProps>> = {
  custom_labels: LabelizerSetup,
};
```

In `frontend/src/features/plugin/customComponents.ts`, replace the custom_labels import and entry:

```tsx
import { LabelizerPage } from '../../../../frontend/src/features/customLabels/LabelizerPage';
```

(Use the existing file's actual import style — it currently imports from `'../../../../plugins/core/custom_labels/frontend/component'`; the new import from the features dir is `'../customLabels/LabelizerPage'` since both files live under `src/features/plugin/` and `src/features/customLabels/`.) Change the map entry to `custom_labels: LabelizerPage`. Keep `rules` and `filter` entries untouched. Leave the plugin stub `plugins/core/custom_labels/frontend/component.tsx` as the pure re-export (component-level tests import through it).

- [ ] **Step 4: Run to verify GREEN**

Run: `npm run test -- configComponents` then `npm run test -- PluginPage` then `npm run typecheck` (from `frontend/`)
Expected: new tests PASS; PluginPage tests unaffected (rules/filter entries unchanged; if a PluginPage test asserts the custom_labels page shows the rules tab — none is expected — update it to the ids-only expectation).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/customLabels/LabelizerPage.tsx \
  frontend/src/features/customLabels/LabelizerSetup.tsx \
  frontend/src/features/plugin/configComponents.ts frontend/src/features/plugin/configComponents.test.tsx \
  frontend/src/features/plugin/customComponents.ts
git commit -m "feat(frontend): labelizer page/setup wrappers and CONFIG_COMPONENTS registry (ADR-0007)"
```

---

### Task 3: Panel surface selection (Setup embed / plugin-page link / RJSF)

**Files:**
- Modify: `frontend/src/features/pipeline/PluginConfigPanel.tsx`
- Modify: `frontend/src/features/pipeline/PluginConfigPanel.test.tsx`
- Modify: `frontend/src/features/pipeline/PipelinePage.test.tsx` (one test changes meaning)
- Modify: `frontend/public/locales/en/pipeline.json`, `frontend/public/locales/de/pipeline.json`

**Interfaces:**
- Consumes: `CONFIG_COMPONENTS` (Task 2), `CUSTOM_COMPONENTS`, `PluginErrorBoundary`, tierUtils helpers, panel props `{ instance, plugin, clientId, feedSourceId, onChange, onRemove }` (unchanged).
- Produces: panel surface order — (1) `CONFIG_COMPONENTS[plugin.id]` → Setup embed with tier switcher + read-only alert + instance settings (current shipped layout, component swapped); (2) else `CUSTOM_COMPONENTS[plugin.id]` (i.e. manifest declares `frontend.component`) → hint + "Open plugin page" link, NO instance settings; (3) else → RJSF instance settings only.

- [ ] **Step 1: Add the i18n keys**

`frontend/public/locales/en/pipeline.json` (append, keeping existing keys):

```json
  "configOnPluginPage": "This plugin is configured on its plugin page.",
  "configOpenPluginPage": "Open plugin page"
```

`frontend/public/locales/de/pipeline.json`:

```json
  "configOnPluginPage": "Dieses Plugin wird auf seiner Plugin-Seite konfiguriert.",
  "configOpenPluginPage": "Plugin-Seite öffnen"
```

- [ ] **Step 2: Update the panel tests (RED)**

In `frontend/src/features/pipeline/PluginConfigPanel.test.tsx`: the existing registry mock covers `../plugin/customComponents`. Add a mock for the new registry right below it (probe id `probe` stays in CUSTOM_COMPONENTS; a NEW id `setup` lives in CONFIG_COMPONENTS):

```tsx
vi.mock('../plugin/configComponents', async () => {
  const { ProbeComponent: Probe } = await import('../../test/probeComponent');
  return { CONFIG_COMPONENTS: { setup: Probe } };
});
```

Add fixtures:

```tsx
const setupInstance: LocalInstance = {
  id: 3, position: 0, plugin_id: 'setup', name: 'Setup Probe',
  configuration: {}, enabled: true, clientId: 'setup-0',
};
const setupPlugin: PluginInfo = {
  id: 'setup', name: 'Setup Probe', version: '1.0.0', enabled: true,
  manifest: {
    extension_point: 'pipeline_module',
    frontend: { component: 'component.tsx' },
    config_scope: ['global', 'client'],
    data_scope: ['client', 'feed_source'],
  },
  used_by_feed_sources: 0,
};
```

Re-point the existing embed tests: the tier-switcher / readonly-alert / crash tests currently use `labelizerInstance` + `labelizerPlugin` (id `probe`, CUSTOM-only) — under the new selection order those now produce the hint + link, NOT the embed. Change them to use `setupInstance` + `setupPlugin` (assert the same things: default feed scope `{"feedSourceId":9}`, tier switch to `{"clientId":3}`, readonly alert + switch action, crash isolation). Then add the new-surface tests:

```tsx
it('CUSTOM-only plugin shows the plugin-page hint and link, no instance form', () => {
  render(
    <PluginConfigPanel
      instance={labelizerInstance} plugin={labelizerPlugin}
      clientId="3" feedSourceId="9"
      onChange={vi.fn()} onRemove={vi.fn()}
    />,
  );
  expect(screen.getByText(/configured on its plugin page/i)).toBeInTheDocument();
  const link = screen.getByRole('link', { name: /open plugin page/i });
  expect(link).toHaveAttribute('href', '/clients/3/feeds/9/plugins/probe');
  expect(screen.queryByTestId('config-tier-switcher')).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/suffix/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/instance settings/i)).not.toBeInTheDocument();
});

it('schema-only plugin still renders the instance settings form', () => {
  render(<PluginConfigPanel instance={instance} plugin={plugin} onChange={vi.fn()} onRemove={vi.fn()} />);
  expect(screen.getByLabelText(/suffix/i)).toBeInTheDocument();
  expect(screen.queryByText(/configured on its plugin page/i)).not.toBeInTheDocument();
});
```

(The `labelizerPlugin` fixture declares no `config_schema`, which is what makes the first test's form-absence assertion clean.)

- [ ] **Step 3: Run to verify RED**

Run: `npm run test -- PluginConfigPanel` (from `frontend/`)
Expected: the re-pointed + new tests FAIL (selection order not implemented).

- [ ] **Step 4: Implement the selection**

In `frontend/src/features/pipeline/PluginConfigPanel.tsx`:

1. Import the registry: `import { CONFIG_COMPONENTS } from '../plugin/configComponents';` and add `Anchor` to the Mantine import; add `import { Link } from 'react-router';`.
2. Replace the component lookup (currently `const CustomComponent = ...CUSTOM_COMPONENTS[plugin.id]...`) with:

```tsx
  const SetupComponent = plugin
    ? CONFIG_COMPONENTS[plugin.id] ?? null
    : null;
  const PageComponent = plugin?.manifest?.frontend?.component
    ? CUSTOM_COMPONENTS[plugin.id] ?? null
    : null;
```

3. All existing embed JSX (tier switcher, readonly alert, `PluginErrorBoundary`) switches from `CustomComponent`/`CustomComponent && plugin` to `SetupComponent`/`SetupComponent && plugin` — identical structure.
4. Add the PageComponent branch between the Setup block and the Instance settings title. The full render tail becomes:

```tsx
      {SetupComponent && plugin ? (
        <>
          {/* …existing switcher + alert + boundary embed… */}
          <Divider />
        </>
      ) : null}
      {PageComponent && plugin ? (
        <Group justify="space-between" wrap="nowrap" data-testid="config-plugin-page-hint">
          <Text size="sm" c="dimmed">{t('configOnPluginPage')}</Text>
          {clientId && feedSourceId ? (
            <Anchor
              component={Link}
              to={`/clients/${clientId}/feeds/${feedSourceId}/plugins/${plugin.id}`}
              underline="never"
            >
              <Button size="xs" variant="light">{t('configOpenPluginPage')}</Button>
            </Anchor>
          ) : null}
        </Group>
      ) : null}
      {!PageComponent ? (
        <>
          <Title order={5">{t('configInstanceSection')}</Title>
          {schema ? (
            <JsonSchemaForm
              schema={schema}
              value={draft}
              onChange={(next) => {
                const merged = (next ?? {}) as Record<string, unknown>;
                setDraft(merged);
                onChange(merged);
              }}
            />
          ) : (
            <Text c="dimmed" size="sm">{t('configNoSchema')}</Text>
          )}
        </>
      ) : null}
```

(Keep the existing `configNoSchema`/instance-settings code paths byte-equivalent where not structurally moved; the `readOnlyTarget`/`tiers` computations keep using `SetupComponent` and the manifest.)

- [ ] **Step 5: Update the PipelinePage pass-through test**

In `frontend/src/features/pipeline/PipelinePage.test.tsx`, the shipped test `embeds a custom-component plugin at feed scope with route ids` renders a `probe` plugin that is CUSTOM-only — under the new order it now shows the hint + link, not an embed. Rewrite it:

```tsx
  it('CUSTOM-only plugin in the panel links to its feed-tier plugin page', async () => {
    // …same stubFetch body as today (probe plugin + feed-sources/1 pipeline doc)…
    renderAt();
    const link = await screen.findByRole('link', { name: /open plugin page/i });
    expect(link).toHaveAttribute('href', '/clients/1/feeds/1/plugins/probe');
  });
```

(The `vi.mock('../plugin/customComponents')` at the top of the file stays; do not mock configComponents here — the real registry has no `probe` entry, which is exactly what this test asserts.)

- [ ] **Step 6: Run gates**

Run: `npm run test -- PluginConfigPanel` then `npm run test -- PipelinePage` then `npm run typecheck` (from `frontend/`)
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/pipeline/PluginConfigPanel.tsx \
  frontend/src/features/pipeline/PluginConfigPanel.test.tsx \
  frontend/src/features/pipeline/PipelinePage.test.tsx \
  frontend/public/locales/en/pipeline.json frontend/public/locales/de/pipeline.json
git commit -m "feat(frontend): panel picks setup embed, plugin-page link, or instance form per registry"
```

---

### Task 4: Sidebar plugin entries after Setup

**Files:**
- Modify: `frontend/src/app/AppShell.tsx`
- Modify: `frontend/src/app/AppShell.test.tsx`

**Interfaces:**
- Consumes: `usePlugins` hook, `PluginInfo`, `getPluginIcon` from `frontend/src/components/PluginIconMap.ts`, `pluginNames.*` i18n (common ns).
- Produces: nav order Dashboard → Setup → plugin entries → Products → Pipeline → Monitoring → Export. Entries render ONLY in feed context (`feedBase` set) and ONLY for enabled plugins with `manifest.frontend.component`; href `${feedBase}/plugins/${plugin.id}`.

- [ ] **Step 1: Update the AppShell tests first (RED)**

In `frontend/src/app/AppShell.test.tsx`: the `plugins` fixture array currently has `manifest.frontend` with only `menu_item`/`icon`. Give the entries that should be visible a `component: 'component.tsx'` (e.g. `example_upper`, `feed_rules`) and leave others without (e.g. `global_tool`, `client_widget`, `data_scoped_widget` — rename `feed_rules`'s manifest if needed so exactly two fixtures have `component`). Replace the first test:

```tsx
  it('renders navigation with plugin entries after Setup in feed context', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Products' })).toBeInTheDocument();
    const labels = screen.getAllByRole('link').map((a) => a.textContent ?? '');
    const setupIdx = labels.findIndex((l) => l === 'Setup');
    const pluginIdx = labels.findIndex((l) => l.includes('Example Upper'));
    const productsIdx = labels.findIndex((l) => l === 'Products');
    expect(setupIdx).toBeGreaterThan(-1);
    expect(pluginIdx).toBeGreaterThan(setupIdx);
    expect(productsIdx).toBeGreaterThan(pluginIdx);
    expect(screen.getByRole('link', { name: /example upper/i }))
      .toHaveAttribute('href', '/clients/1/feeds/2/plugins/example_upper');
  });

  it('shows no plugin entries outside a feed context', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: 'Dashboard' });
    expect(screen.queryByText('Example Upper')).not.toBeInTheDocument();
    expect(screen.queryByText('Feed Rules')).not.toBeInTheDocument();
  });

  it('lists only custom-UI plugins in the nav', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    expect(await screen.findByRole('link', { name: /example upper/i })).toBeInTheDocument();
    expect(screen.queryByText('Global Tool')).not.toBeInTheDocument();
    expect(screen.queryByText('Client Widget')).not.toBeInTheDocument();
  });
```

Remove the old `renders the fixed navigation without a plugins section` test (its assertions are superseded). Keep the other existing tests (breadcrumb, logout, disabled-items) — they don't assert plugin entries.

- [ ] **Step 2: Run to verify RED**

Run: `npm run test -- AppShell` (from `frontend/`)
Expected: new tests FAIL (no plugin entries).

- [ ] **Step 3: Implement**

In `frontend/src/app/AppShell.tsx`:

1. Re-add imports: `usePlugins` in the `'../api/hooks'` import list; `import { getPluginIcon } from '../components/PluginIconMap';`; `useMemo` from 'react'.
2. In `AppShell()`, after `feedBase`:

```tsx
  const { data: plugins } = usePlugins();

  const pluginNavItems = useMemo(
    () =>
      (Array.isArray(plugins) ? plugins : [])
        .filter((p) => p.enabled && p.manifest?.frontend?.component)
        .map((p) => ({
          to: feedBase ? `${feedBase}/plugins/${p.id}` : null,
          label: t(`pluginNames.${p.id}`, { defaultValue: p.name }),
          icon: getPluginIcon(p.manifest?.frontend?.icon),
        })),
    [plugins, feedBase, t],
  );
```

3. Restructure `feedScoped` so plugin entries sit after Setup. Change the array to:

```tsx
  const feedScoped: Array<{ to: string | null; label: string; icon: { size?: number } & ComponentType }> = [
    { to: feedBase ? `${feedBase}/setup` : null, label: t('nav.setup'), icon: IconSettings },
    ...(feedBase ? pluginNavItems : []),
    { to: feedBase ? `${feedBase}/products` : null, label: t('nav.products'), icon: IconBox },
    { to: feedBase ? `${feedBase}/pipeline` : null, label: t('nav.pipeline'), icon: IconGitBranch },
    { to: feedBase ? `${feedBase}/monitoring` : null, label: t('nav.monitoring'), icon: IconActivity },
    { to: feedBase ? `${feedBase}/export` : null, label: t('nav.export'), icon: IconFileExport },
  ];
```

Type the array pragmatically: `ComponentType` from 'react' (add `type ComponentType` to the react import) and let the tabler icons / `getPluginIcon` results both satisfy `{ size?: number }`-shaped components — if the strictest workable type is `ComponentType<{ size?: number }>`, use that on the array type and drop the ad-hoc shape.

- [ ] **Step 4: Run gates**

Run: `npm run test -- AppShell` then `npm run test -- router` then `npm run typecheck` (from `frontend/`)
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/AppShell.tsx frontend/src/app/AppShell.test.tsx
git commit -m "feat(frontend): plugin entries in feed nav between Setup and Products"
```

---

### Task 5: ADR-0007, docs, full verification

**Files:**
- Create: `docs/decisions/0007-plugin-setup-and-page-two-surface.md`
- Modify: `docs/decisions/0006-pipeline-editor-config-hub.md` (Status note)
- Modify: `docs/decisions/0005-labelizer-scope-merge-and-value-pinning.md` (Consequences note)
- Modify: `frontend/docs/architecture.md`, `frontend/docs/plugin-uis.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Write ADR-0007** (format matches ADR-0005/0006):

```markdown
# ADR-0007: Plugin Setup + Plugin Page Two-Surface Model

## Status
Accepted (supersedes the sidebar-removal consequence of ADR-0006; 0006's
panel-hub, tier-switcher, and error-boundary decisions stand)

## Context
After the config-hub cycle (ADR-0006) removed per-plugin sidebar entries,
operator feedback clarified that each plugin has TWO user-facing surfaces:
a Setup surface (Pipeline Editor config panel) and a working Plugin Page that
must stay reachable in the feed navigation — e.g. the Labelizer page shows
the slot dashboard (bulk IDs) while slot rules are configured in Pipeline
Editor → Labelizer Setup; Rules has no special setup and "does its job" on
its plugin page.

## Decision
1. Per-plugin split via the frontend static registry `CONFIG_COMPONENTS`
   (`src/features/plugin/configComponents.ts`, ADR-0002 convention; no
   manifest or backend changes):
   - plugin in `CONFIG_COMPONENTS` → the Pipeline panel embeds its Setup
     component with the Feed/Client/Global tier switcher and the actionable
     read-only alert (ADR-0006 machinery), plus Instance settings;
   - plugin only in `CUSTOM_COMPONENTS` (manifest `frontend.component`) →
     panel shows a hint + "Open plugin page" link to the feed-tier plugin
     page; no raw JSON-schema instance form;
   - neither → generic RJSF instance settings.
2. `custom_labels` splits via `CustomLabelsUI`'s additive `onlyTab` prop:
   `LabelizerPage` (ids-only) on the plugin page; `LabelizerSetup`
   (rules-only) in the panel. The feed-tier rules read-only hint is removed
   — the panel's alert is the actionable path.
3. Sidebar (feed context): Dashboard → Setup → plugin entries (enabled
   plugins with `frontend.component`) → Products → Pipeline → Monitoring →
   Export. Plugin routes remain the same URLs.

## Consequences
- The Labelizer Plugin Page is data-only at every tier; rule editing happens
  in the Pipeline Editor at the tier chosen by the switcher (client/global).
- `rules`/`filter` instance-level RJSF forms are no longer rendered in the
  panel (their `instance.configuration` remains whatever it was; both
  plugins operate through scoped PluginConfig, not instance configuration).
- ADR-0005's merge/value-pinning semantics are unchanged; only the surface
  exposing them moved.
```

- [ ] **Step 2: Amend ADR-0006 and ADR-0005**

In `docs/decisions/0006-pipeline-editor-config-hub.md`, change `## Status` to:

```markdown
## Status
Accepted; navigation consequence superseded by ADR-0007 (plugin entries
returned to the sidebar between Setup and Products)
```

In `docs/decisions/0005-labelizer-scope-merge-and-value-pinning.md`, append to `## Consequences`:

```markdown
- Since ADR-0007 the Labelizer Plugin Page is data-only (bulk IDs); slot
  rules are edited in Pipeline Editor → Labelizer Setup at the tier chosen
  by the panel's switcher.
```

- [ ] **Step 3: Update frontend docs**

`frontend/docs/architecture.md` — in the navigation section, replace the "no Plugins section" wording with the new order (Dashboard → Setup → plugin entries → Products → Pipeline → Monitoring → Export; entries only in feed context, custom-UI plugins only) and describe the two surfaces (Plugin Page = dashboard/tool; Pipeline panel Setup via `CONFIG_COMPONENTS`).

`frontend/docs/plugin-uis.md` — update the Pipeline Editor embedding section: describe the three-way selection order (setup embed / plugin-page link / instance form), the `onlyTab` split for custom_labels, and that the Labelizer page is ids-only. Remove any claim that the page hosts the slot-rules editor.

- [ ] **Step 4: Full verification**

Run from `frontend/`:

```bash
npm run test
npm run typecheck
```

Expected: all PASS. Known ProductsPage parallel-load flake may fail 1 test — re-run `npm run test -- ProductsPage` solo to confirm pre-existing. Fix any OTHER failure in this task and disclose it.

- [ ] **Step 5: Commit**

```bash
git add docs/decisions/0007-plugin-setup-and-page-two-surface.md \
  docs/decisions/0006-pipeline-editor-config-hub.md \
  docs/decisions/0005-labelizer-scope-merge-and-value-pinning.md \
  frontend/docs/architecture.md frontend/docs/plugin-uis.md
git commit -m "docs: ADR-0007 two-surface plugin model; nav and plugin-UI docs"
```

---

## Self-Review (completed)

- **Spec coverage:** per-plugin split via CONFIG_COMPONENTS (Tasks 2-3), Labelizer page ids-only + rules tab removal (Task 1-2), hint removal (Task 1), nav entries after Setup with custom-UI filter (Task 4), Rules/Filter hint+link with no raw form (Task 3), ADR-0007 + ADR amendments + docs (Task 5).
- **Type consistency:** `onlyTab` (Task 1) matches wrapper usage (Task 2); `CONFIG_COMPONENTS`/`ConfigComponentProps` (Task 2) match panel import (Task 3); plugin nav item shape (Task 4) matches the `feedScoped` render map.
- **No placeholders:** code blocks are complete except two verbatim JSX moves in Task 1 Step 3 and one in Task 3 Step 4, each given as exact line ranges of content to move unchanged — moves, not unspecified work.
