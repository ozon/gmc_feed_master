# Pipeline Editor as Plugin Config Hub — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Pipeline Editor the single hub for plugin configuration — embedded rich plugin UIs with an in-place tier switcher (Feed/Client/Global), a labeled Instance Settings section, an actionable read-only alert, and a sidebar without the "Plugins" section.

**Architecture:** `PluginConfigPanel` (right pane of `PipelinePage`) gains a tier switcher that re-renders the plugin's registered custom UI (`CUSTOM_COMPONENTS`) with a different `PluginScope`. Tier options and editability are derived from the manifest scopes. Scoped-config saves stay inside the embedded components (unchanged); instance settings keep saving with pipeline Save. Pure frontend — no backend, API, manifest, or DB changes.

**Tech Stack:** React 19, TypeScript, Mantine 7 (`SegmentedControl`, `Alert`, `Divider`), TanStack Query, i18next, vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-07-pipeline-editor-config-hub-design.md`

## Global Constraints

- All UI text via i18next — add every new key to BOTH `frontend/public/locales/en/` and `frontend/public/locales/de/` files.
- Server state only in TanStack Query (ADR 0001) — no new stores; embedded components already comply.
- Plugin components (`CustomLabelsUI`, `RulesUI`, `FilterUI`) are NOT modified.
- Plugin manifests, backend routes, and DB schema are NOT modified.
- Run frontend commands from `frontend/`: `npm run test` (vitest), `npm run typecheck` (tsc -b).
- Commit messages follow repo style: `feat(frontend): ...`, `test(frontend): ...`, `docs(frontend): ...` (see `git log --oneline -5`).
- Never commit `.env` files or secrets.
- Docs must be updated in the same commit as behavior changes (repo AGENTS.md rule).

---

### Task 1: `PluginErrorBoundary` component

A crashing plugin UI must not take down the page it is embedded in (ADR 0004). `frontend/docs/plugin-uis.md` documents this boundary as a planned follow-up — this task creates it and wires it into `PluginPage`; Task 3 uses it in the pipeline panel.

**Files:**
- Create: `frontend/src/features/plugin/PluginErrorBoundary.tsx`
- Create: `frontend/src/features/plugin/PluginErrorBoundary.test.tsx`
- Modify: `frontend/src/features/plugin/PluginPage.tsx:90-92` (wrap custom component)
- Modify: `frontend/public/locales/en/plugins.json`, `frontend/public/locales/de/plugins.json` (add `errorBoundary` keys)

**Interfaces:**
- Produces: `PluginErrorBoundary` — class component, props `{ pluginName: string; children: ReactNode }`, renders children or a fallback Alert (testid `plugin-error-boundary`) with a retry button (testid `plugin-error-retry`). Consumed unchanged by Task 3.

- [ ] **Step 1: Add the i18n keys**

In `frontend/public/locales/en/plugins.json` add (keep existing keys, add `errorBoundary` object):

```json
{
  "section": "Plugins",
  "empty": "No plugins available.",
  "notFound": "Plugin not found.",
  "noSchema": "This plugin has no configuration schema.",
  "configSaved": "Configuration saved.",
  "saveFailed": "Could not save plugin configuration.",
  "saveFailedWithErrors": "Could not save: {{count}} validation error(s).",
  "save": "Save",
  "errorBoundary": {
    "title": "This plugin's interface crashed",
    "retry": "Try again"
  }
}
```

In `frontend/public/locales/de/plugins.json` add the same structure with German values:

```json
{
  "errorBoundary": {
    "title": "Die Oberfläche dieses Plugins ist abgestürzt",
    "retry": "Erneut versuchen"
  }
}
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/features/plugin/PluginErrorBoundary.test.tsx`:

```tsx
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { PluginErrorBoundary } from './PluginErrorBoundary';

beforeAll(async () => {
  await i18n.loadNamespaces(['plugins']);
});

function Boom(): never {
  throw new Error('boom');
}

describe('PluginErrorBoundary', () => {
  it('renders children when nothing throws', () => {
    render(
      <PluginErrorBoundary pluginName="Upper">
        <div data-testid="healthy-child" />
      </PluginErrorBoundary>,
    );
    expect(screen.getByTestId('healthy-child')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-error-boundary')).not.toBeInTheDocument();
  });

  it('shows the fallback with the plugin name and error message when the child throws', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <PluginErrorBoundary pluginName="Upper">
        <Boom />
      </PluginErrorBoundary>,
    );
    expect(screen.getByTestId('plugin-error-boundary')).toBeInTheDocument();
    expect(screen.getByText('Upper')).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
    spy.mockRestore();
  });

  it('retry button clears the error and re-renders children', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const user = userEvent.setup();
    let shouldThrow = true;
    function MaybeBoom() {
      if (shouldThrow) throw new Error('boom');
      return <div data-testid="healthy-child" />;
    }
    render(
      <PluginErrorBoundary pluginName="Upper">
        <MaybeBoom />
      </PluginErrorBoundary>,
    );
    shouldThrow = false;
    await user.click(screen.getByTestId('plugin-error-retry'));
    expect(screen.getByTestId('healthy-child')).toBeInTheDocument();
    spy.mockRestore();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `npm run test -- PluginErrorBoundary` (from `frontend/`)
Expected: FAIL — cannot resolve `./PluginErrorBoundary`.

- [ ] **Step 4: Implement the component**

Create `frontend/src/features/plugin/PluginErrorBoundary.tsx`:

```tsx
import { Component, type ReactNode } from 'react';
import { Alert, Button, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

function PluginErrorFallback({
  pluginName,
  message,
  onRetry,
}: {
  pluginName: string;
  message?: string;
  onRetry: () => void;
}) {
  const { t } = useTranslation('plugins');
  return (
    <Alert color="red" title={t('errorBoundary.title')} data-testid="plugin-error-boundary">
      <Stack gap="xs" mt={4}>
        <Text size="sm" fw={600}>{pluginName}</Text>
        {message ? <Text size="sm" c="dimmed">{message}</Text> : null}
        <div>
          <Button size="xs" variant="light" onClick={onRetry} data-testid="plugin-error-retry">
            {t('errorBoundary.retry')}
          </Button>
        </div>
      </Stack>
    </Alert>
  );
}

type Props = { pluginName: string; children: ReactNode };
type State = { error: Error | null };

export class PluginErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    const { error } = this.state;
    if (error !== null) {
      return (
        <PluginErrorFallback
          pluginName={this.props.pluginName}
          message={error.message}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npm run test -- PluginErrorBoundary`
Expected: PASS (3 tests).

- [ ] **Step 6: Wrap the custom component in `PluginPage`**

In `frontend/src/features/plugin/PluginPage.tsx`, add the import next to the existing `CUSTOM_COMPONENTS` import:

```tsx
import { PluginErrorBoundary } from './PluginErrorBoundary';
```

Replace lines 90-92:

```tsx
      ) : CustomComponent ? (
        <CustomComponent pluginId={plugin.id} scope={scope} />
      ) : (
```

with:

```tsx
      ) : CustomComponent ? (
        <PluginErrorBoundary pluginName={plugin.name}>
          <CustomComponent pluginId={plugin.id} scope={scope} />
        </PluginErrorBoundary>
      ) : (
```

- [ ] **Step 7: Run the full plugin-page test suite**

Run: `npm run test -- PluginPage` (from `frontend/`)
Expected: PASS — the boundary is transparent when components render fine.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/plugin/PluginErrorBoundary.tsx \
  frontend/src/features/plugin/PluginErrorBoundary.test.tsx \
  frontend/src/features/plugin/PluginPage.tsx \
  frontend/public/locales/en/plugins.json frontend/public/locales/de/plugins.json
git commit -m "feat(frontend): PluginErrorBoundary isolates crashing plugin UIs (ADR 0004)"
```

---

### Task 2: Tier helpers (`tierUtils.ts`)

Pure functions that derive the tier switcher options and the `PluginScope` per tier from the plugin manifest. The local `manifestScopes` in `AppShell.tsx:49` moves here so both files share one implementation (AppShell's copy is deleted with its Plugins section in Task 4).

**Files:**
- Create: `frontend/src/features/pipeline/tierUtils.ts`
- Create: `frontend/src/features/pipeline/tierUtils.test.ts`
- Modify: `frontend/src/app/AppShell.tsx:42-57` (delete local `manifestScopes`, import from tierUtils)

**Interfaces:**
- Consumes: `PluginInfo` from `frontend/src/api/types` (`manifest: { frontend?: PluginManifestFrontend; [key: string]: unknown } | null`), `PluginScope = { clientId?: number; feedSourceId?: number }` from `frontend/src/api/hooks`.
- Produces (used by Task 3):
  - `type ConfigTier = 'feed_source' | 'client' | 'global'`
  - `manifestScopes(manifest: PluginInfo['manifest'], key: 'config_scope' | 'data_scope'): string[]`
  - `tierOptions(manifest, available: { hasFeedSource: boolean; hasClient: boolean }): ConfigTier[]` — most-specific first: `['feed_source', 'client', 'global']` filtered by declared scopes ∩ availability.
  - `scopeForTier(tier: ConfigTier, route: { clientId?: string | number; feedSourceId?: string | number }): PluginScope`
  - `configEditableAtFeed(manifest): boolean` — `'feed_source' ∈ config_scope`.
  - `highestEditableConfigTier(manifest): 'client' | 'global' | null` — `'client'` if client ∈ config_scope, else `'global'` if global ∈ config_scope, else `null`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/pipeline/tierUtils.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { PluginInfo } from '../../api/types';
import {
  configEditableAtFeed,
  highestEditableConfigTier,
  scopeForTier,
  tierOptions,
} from './tierUtils';

const labelizer: PluginInfo['manifest'] = {
  config_scope: ['global', 'client'],
  data_scope: ['client', 'feed_source'],
};

const rules: PluginInfo['manifest'] = {
  config_scope: ['global', 'client', 'feed_source'],
  data_scope: ['global', 'client', 'feed_source'],
};

describe('tierOptions', () => {
  it('derives most-specific-first tiers from manifest scopes and route availability', () => {
    expect(tierOptions(labelizer, { hasFeedSource: true, hasClient: true }))
      .toEqual(['feed_source', 'client', 'global']);
  });

  it('omits feed_source when no feed source is in context', () => {
    expect(tierOptions(labelizer, { hasFeedSource: false, hasClient: true }))
      .toEqual(['client', 'global']);
  });

  it('accepts a string scope value', () => {
    expect(tierOptions({ data_scope: 'client' }, { hasFeedSource: true, hasClient: true }))
      .toEqual(['client']);
  });
});

describe('scopeForTier', () => {
  it('maps tiers to PluginScope using route ids', () => {
    const route = { clientId: '3', feedSourceId: '9' };
    expect(scopeForTier('feed_source', route)).toEqual({ feedSourceId: 9 });
    expect(scopeForTier('client', route)).toEqual({ clientId: 3 });
    expect(scopeForTier('global', route)).toEqual({});
  });
});

describe('config editability', () => {
  it('labelizer config is not editable at feed tier; client is the highest editable tier', () => {
    expect(configEditableAtFeed(labelizer)).toBe(false);
    expect(highestEditableConfigTier(labelizer)).toBe('client');
  });

  it('rules config is editable at feed tier', () => {
    expect(configEditableAtFeed(rules)).toBe(true);
    expect(highestEditableConfigTier(rules)).toBe('client');
  });

  it('falls back to global when client is not in config_scope', () => {
    expect(highestEditableConfigTier({ config_scope: ['global'] })).toBe('global');
    expect(highestEditableConfigTier(null)).toBe(null);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- tierUtils` (from `frontend/`)
Expected: FAIL — cannot resolve `./tierUtils`.

- [ ] **Step 3: Implement the helpers**

Create `frontend/src/features/pipeline/tierUtils.ts`:

```ts
import type { PluginInfo } from '../../api/types';
import type { PluginScope } from '../../api/hooks';

export type ConfigTier = 'feed_source' | 'client' | 'global';

export function manifestScopes(
  manifest: PluginInfo['manifest'],
  key: 'config_scope' | 'data_scope',
): string[] {
  const value = manifest?.[key];
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string');
  return [];
}

export function tierOptions(
  manifest: PluginInfo['manifest'],
  available: { hasFeedSource: boolean; hasClient: boolean },
): ConfigTier[] {
  const scopes = new Set([
    ...manifestScopes(manifest, 'config_scope'),
    ...manifestScopes(manifest, 'data_scope'),
  ]);
  const tiers: ConfigTier[] = [];
  if (available.hasFeedSource && scopes.has('feed_source')) tiers.push('feed_source');
  if (available.hasClient && scopes.has('client')) tiers.push('client');
  if (scopes.has('global')) tiers.push('global');
  return tiers;
}

export function scopeForTier(
  tier: ConfigTier,
  route: { clientId?: string | number; feedSourceId?: string | number },
): PluginScope {
  if (tier === 'feed_source') return { feedSourceId: Number(route.feedSourceId) };
  if (tier === 'client') return { clientId: Number(route.clientId) };
  return {};
}

export function configEditableAtFeed(manifest: PluginInfo['manifest']): boolean {
  return manifestScopes(manifest, 'config_scope').includes('feed_source');
}

export function highestEditableConfigTier(
  manifest: PluginInfo['manifest'],
): 'client' | 'global' | null {
  const scopes = manifestScopes(manifest, 'config_scope');
  if (scopes.includes('client')) return 'client';
  if (scopes.includes('global')) return 'global';
  return null;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm run test -- tierUtils`
Expected: PASS (7 tests).

- [ ] **Step 5: Point `AppShell` at the shared helper**

In `frontend/src/app/AppShell.tsx`, delete the local `manifestScopes` function (lines 49-57) and add the import:

```tsx
import { manifestScopes } from '../features/pipeline/tierUtils';
```

(`isClientScoped`/`isFeedScoped` at lines 59-71 keep working unchanged; they are deleted in Task 4.)

- [ ] **Step 6: Run the AppShell tests**

Run: `npm run test -- AppShell` (from `frontend/`)
Expected: PASS — behavior unchanged.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/pipeline/tierUtils.ts frontend/src/features/pipeline/tierUtils.test.ts \
  frontend/src/app/AppShell.tsx
git commit -m "feat(frontend): tier helpers deriving PluginScope and switcher options from manifest scopes"
```

---

### Task 3: `PluginConfigPanel` config hub (tier switcher + embedded plugin UI)

The panel gains: a tier switcher (default Feed), a "Plugin configuration" section embedding the plugin's custom component inside `PluginErrorBoundary`, an actionable read-only alert, and a labeled "Instance settings" section (the existing RJSF form, unchanged behavior).

**Files:**
- Modify: `frontend/src/features/pipeline/PluginConfigPanel.tsx` (full rewrite of the component body, props extended)
- Modify: `frontend/src/features/pipeline/PluginConfigPanel.test.tsx` (extend)
- Modify: `frontend/src/features/pipeline/PipelinePage.tsx:42-43` (pass route ids)
- Modify: `frontend/src/features/pipeline/PipelinePage.test.tsx` (one new test)
- Modify: `frontend/public/locales/en/pipeline.json`, `frontend/public/locales/de/pipeline.json` (new keys)

**Interfaces:**
- Consumes: `PluginErrorBoundary` (Task 1), `CUSTOM_COMPONENTS` from `frontend/src/features/plugin/customComponents.ts` (type `Record<string, ComponentType<{ pluginId: string; scope: PluginScope }>>`), tier helpers (Task 2), existing `LocalInstance` from `./dndUtils`, `JsonSchemaForm` from `../../components/JsonSchemaForm`.
- Produces: `PluginConfigPanel` props become:

```ts
type Props = {
  instance: LocalInstance | null;
  plugin: PluginInfo | undefined;
  clientId?: string;
  feedSourceId?: string;
  onChange: (next: Record<string, unknown>) => void;
  onRemove: () => void;
};
```

`PipelinePage` passes `clientId`/`feedSourceId` from its `useParams()` (Task 3, Step 8).

- [ ] **Step 1: Add the i18n keys**

In `frontend/public/locales/en/pipeline.json`, add after `"configNoSchema"` (keep all existing keys):

```json
  "configPluginSection": "Plugin configuration",
  "configInstanceSection": "Instance settings",
  "configReadOnlyBody": "This plugin's configuration is managed at {{tier}} level.",
  "configSwitchTier": "Switch to {{tier}} tier"
```

In `frontend/public/locales/de/pipeline.json`, add the matching keys:

```json
  "configPluginSection": "Plugin-Konfiguration",
  "configInstanceSection": "Instanz-Einstellungen",
  "configReadOnlyBody": "Die Konfiguration dieses Plugins wird auf {{tier}}-Ebene verwaltet.",
  "configSwitchTier": "Zur {{tier}}-Ebene wechseln"
```

(Read the de file first and mirror the key order of the en file.)

- [ ] **Step 2: Write the failing tests**

In `frontend/src/features/pipeline/PluginConfigPanel.test.tsx`:

Add these imports at the top (after the existing ones) and mock the registry so the tests do not pull in the real heavy plugin UIs (async factory + dynamic import because `vi.mock` factories cannot reference outer-scope imports):

```tsx
import { afterEach, beforeEach } from 'vitest';
import { ProbeComponent, resetProbe, setCrashOnRender } from '../../test/probeComponent';

vi.mock('../plugin/customComponents', async () => {
  const { ProbeComponent: Probe } = await import('../../test/probeComponent');
  return { CUSTOM_COMPONENTS: { probe: Probe } };
});
```

Create `frontend/src/test/probeComponent.tsx` (a tiny recorder component matching `CustomComponentProps`; `crashOnRender` lets tests exercise the error boundary):

```tsx
import type { PluginScope } from '../api/hooks';

export const probeScopes: Array<{ pluginId: string; scope: PluginScope }> = [];
export let crashOnRender = false;

export function setCrashOnRender(value: boolean) {
  crashOnRender = value;
}

export function resetProbe() {
  probeScopes.length = 0;
  crashOnRender = false;
}

export function ProbeComponent({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  if (crashOnRender) throw new Error('boom');
  probeScopes.push({ pluginId, scope });
  return (
    <div
      data-testid="probe-component"
      data-plugin-id={pluginId}
      data-scope={JSON.stringify(scope)}
    />
  );
}
```

Add fixtures and tests inside the existing `describe('PluginConfigPanel', ...)` (the existing 4 tests with the `upper` plugin stay valid and unchanged — `upper` has no `frontend.component`):

```tsx
const labelizerInstance: LocalInstance = {
  id: 2, position: 0, plugin_id: 'probe', name: 'Probe',
  configuration: {}, enabled: true, clientId: 'probe-0',
};
const labelizerPlugin: PluginInfo = {
  id: 'probe', name: 'Probe', version: '1.0.0', enabled: true,
  manifest: {
    extension_point: 'pipeline_module',
    frontend: { component: 'component.tsx' },
    config_scope: ['global', 'client'],
    data_scope: ['client', 'feed_source'],
  },
  used_by_feed_sources: 0,
};
const feedEditablePlugin: PluginInfo = {
  ...labelizerPlugin,
  manifest: {
    ...labelizerPlugin.manifest,
    config_scope: ['global', 'client', 'feed_source'],
  },
};

beforeEach(() => resetProbe());

it('renders the plugin-config section with a tier switcher defaulting to Feed scope', () => {
  render(
    <PluginConfigPanel
      instance={labelizerInstance} plugin={labelizerPlugin}
      clientId="3" feedSourceId="9"
      onChange={vi.fn()} onRemove={vi.fn()}
    />,
  );
  const probe = screen.getByTestId('probe-component');
  expect(probe).toHaveAttribute('data-plugin-id', 'probe');
  expect(probe).toHaveAttribute('data-scope', JSON.stringify({ feedSourceId: 9 }));
});

it('switching the tier re-renders the embedded component with the new scope', async () => {
  const user = userEvent.setup();
  render(
    <PluginConfigPanel
      instance={labelizerInstance} plugin={labelizerPlugin}
      clientId="3" feedSourceId="9"
      onChange={vi.fn()} onRemove={vi.fn()}
    />,
  );
  await user.click(screen.getByRole('radio', { name: /client/i }));
  const probe = screen.getByTestId('probe-component');
  expect(probe).toHaveAttribute('data-scope', JSON.stringify({ clientId: 3 }));
});

it('shows an actionable read-only alert at Feed tier and switches to Client', async () => {
  const user = userEvent.setup();
  render(
    <PluginConfigPanel
      instance={labelizerInstance} plugin={labelizerPlugin}
      clientId="3" feedSourceId="9"
      onChange={vi.fn()} onRemove={vi.fn()}
    />,
  );
  const alert = screen.getByTestId('config-readonly-alert');
  expect(alert).toHaveTextContent(/managed at Client level/i);
  await user.click(screen.getByRole('button', { name: /switch to client tier/i }));
  expect(screen.getByTestId('probe-component'))
    .toHaveAttribute('data-scope', JSON.stringify({ clientId: 3 }));
});

it('shows no read-only alert for a plugin editable at feed tier', () => {
  render(
    <PluginConfigPanel
      instance={labelizerInstance} plugin={feedEditablePlugin}
      clientId="3" feedSourceId="9"
      onChange={vi.fn()} onRemove={vi.fn()}
    />,
  );
  expect(screen.queryByTestId('config-readonly-alert')).not.toBeInTheDocument();
});

it('shows no plugin-config section or switcher when the plugin has no custom component', () => {
  render(<PluginConfigPanel instance={instance} plugin={plugin} onChange={vi.fn()} onRemove={vi.fn()} />);
  expect(screen.queryByTestId('config-tier-switcher')).not.toBeInTheDocument();
  expect(screen.queryByTestId('probe-component')).not.toBeInTheDocument();
});

it('isolates a crashing embedded component; instance settings survive', () => {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
  setCrashOnRender(true);
  render(
    <PluginConfigPanel
      instance={labelizerInstance} plugin={labelizerPlugin}
      clientId="3" feedSourceId="9"
      onChange={vi.fn()} onRemove={vi.fn()}
    />,
  );
  expect(screen.getByTestId('plugin-error-boundary')).toBeInTheDocument();
  expect(screen.getByText(/no configuration options/i)).toBeInTheDocument();
  spy.mockRestore();
});

afterEach(() => {
  vi.restoreAllMocks();
});
```

(`beforeEach(() => resetProbe())` above resets the recorder and crash flag between tests; `labelizerInstance`'s manifest declares no `config_schema`, so the instance-settings section shows the "no configuration options" text in the crash test.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npm run test -- PluginConfigPanel` (from `frontend/`)
Expected: FAIL — new tests fail (`config-tier-switcher`, `probe-component`, `config-readonly-alert` missing); the original 4 tests still PASS.

- [ ] **Step 4: Implement the panel**

Replace the full contents of `frontend/src/features/pipeline/PluginConfigPanel.tsx` with:

```tsx
import { useEffect, useState } from 'react';
import {
  Alert, Badge, Button, Divider, Group, SegmentedControl, Stack, Text, Title,
} from '@mantine/core';
import { IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { JsonSchemaForm, type JsonSchema } from '../../components/JsonSchemaForm';
import type { PluginInfo } from '../../api/types';
import { CUSTOM_COMPONENTS } from '../plugin/customComponents';
import { PluginErrorBoundary } from '../plugin/PluginErrorBoundary';
import {
  configEditableAtFeed, highestEditableConfigTier, scopeForTier, tierOptions,
  type ConfigTier,
} from './tierUtils';
import type { LocalInstance } from './dndUtils';

type Props = {
  instance: LocalInstance | null;
  plugin: PluginInfo | undefined;
  clientId?: string;
  feedSourceId?: string;
  onChange: (next: Record<string, unknown>) => void;
  onRemove: () => void;
};

export function PluginConfigPanel({
  instance, plugin, clientId, feedSourceId, onChange, onRemove,
}: Props) {
  const { t } = useTranslation('pipeline');
  const { t: tCommon } = useTranslation('common');
  const [draft, setDraft] = useState<Record<string, unknown>>(instance?.configuration ?? {});
  const [selectedTier, setSelectedTier] = useState<ConfigTier>('feed_source');

  useEffect(() => {
    setDraft(instance?.configuration ?? {});
  }, [instance?.configuration]);

  // Reset the tier when switching instances — each plugin starts at Feed scope.
  useEffect(() => {
    setSelectedTier('feed_source');
  }, [instance?.clientId]);

  if (!instance) {
    return (
      <Text c="dimmed" data-testid="config-panel" ta="center" py="xl">
        {t('configSelectPlugin')}
      </Text>
    );
  }

  const schema = (plugin?.manifest?.config_schema as JsonSchema | undefined) ?? null;
  const CustomComponent = plugin?.manifest?.frontend?.component
    ? CUSTOM_COMPONENTS[plugin.id] ?? null
    : null;
  const declaredTiers = CustomComponent && plugin
    ? tierOptions(plugin.manifest, {
        hasFeedSource: Boolean(feedSourceId),
        hasClient: Boolean(clientId),
      })
    : [];
  const tiers: ConfigTier[] = declaredTiers.length > 0 ? declaredTiers : ['global'];
  const tier = tiers.includes(selectedTier) ? selectedTier : tiers[0];
  const readOnlyTarget = CustomComponent && plugin && tier === 'feed_source'
    && !configEditableAtFeed(plugin.manifest)
    ? highestEditableConfigTier(plugin.manifest)
    : null;

  return (
    <Stack gap="md" data-testid="config-panel">
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={4}>{instance.name}</Title>
          {plugin ? <Badge size="sm" variant="light">v{plugin.version}</Badge> : null}
        </Group>
        <Button
          variant="light"
          color="red"
          leftSection={<IconTrash size={14} />}
          onClick={onRemove}
        >
          {t('configRemove')}
        </Button>
      </Group>
      {!instance.enabled ? (
        <Alert color="yellow">{t('configDisabledInfo')}</Alert>
      ) : null}
      {CustomComponent && plugin ? (
        <>
          <Group justify="space-between" wrap="nowrap">
            <Title order={5}>{t('configPluginSection')}</Title>
            <SegmentedControl
              size="xs"
              data={tiers.map((value) => ({ value, label: tCommon(`scope.${value}`) }))}
              value={tier}
              onChange={(value) => setSelectedTier(value as ConfigTier)}
              data-testid="config-tier-switcher"
            />
          </Group>
          {readOnlyTarget !== null ? (
            <Alert color="blue" data-testid="config-readonly-alert">
              <Group justify="space-between" wrap="nowrap">
                <Text size="sm">
                  {t('configReadOnlyBody', { tier: tCommon(`scope.${readOnlyTarget}`) })}
                </Text>
                <Button
                  size="xs"
                  variant="light"
                  onClick={() => setSelectedTier(readOnlyTarget)}
                >
                  {t('configSwitchTier', { tier: tCommon(`scope.${readOnlyTarget}`) })}
                </Button>
              </Group>
            </Alert>
          ) : null}
          <PluginErrorBoundary pluginName={plugin.name}>
            <CustomComponent
              key={`${instance.plugin_id}-${tier}`}
              pluginId={instance.plugin_id}
              scope={scopeForTier(tier, { clientId, feedSourceId })}
            />
          </PluginErrorBoundary>
          <Divider />
        </>
      ) : null}
      <Title order={5}>{t('configInstanceSection')}</Title>
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
    </Stack>
  );
}
```

- [ ] **Step 5: Run the panel tests to verify they pass**

Run: `npm run test -- PluginConfigPanel` (from `frontend/`)
Expected: PASS — all old and new tests.

- [ ] **Step 6: Pass route ids from `PipelinePage`**

In `frontend/src/features/pipeline/PipelinePage.tsx`, change line 42:

```tsx
  const { feedSourceId } = useParams();
```

to:

```tsx
  const { clientId, feedSourceId } = useParams();
```

and in the `<PluginConfigPanel ...>` JSX (around line 159), add the two props right after `instance={selected}`:

```tsx
          <PluginConfigPanel
            key={selected?.clientId ?? 'none'}
            instance={selected}
            clientId={clientId}
            feedSourceId={feedSourceId}
            plugin={plugins?.find((p) => p.id === selected?.plugin_id)}
```

(keep the remaining props `onChange`/`onRemove` exactly as they are).

- [ ] **Step 7: Add one `PipelinePage` pass-through test**

In `frontend/src/features/pipeline/PipelinePage.test.tsx`, add this mock after the imports (before the fixtures) — note the relative path to the registry, which lives in `frontend/src/features/plugin/`:

```tsx
vi.mock('../plugin/customComponents', () => ({
  CUSTOM_COMPONENTS: {
    probe: ({ scope }: { pluginId: string; scope: unknown }) => (
      <div data-testid="probe-component" data-scope={JSON.stringify(scope)} />
    ),
  },
}));
```

Add this test inside `describe('PipelinePage', ...)`:

```tsx
  it('embeds a custom-component plugin at feed scope with route ids', async () => {
    stubFetch((url) => {
      if (url === '/plugins') {
        return jsonResponse([
          {
            ...plugin,
            id: 'probe',
            name: 'Probe',
            manifest: {
              extension_point: 'pipeline_module',
              frontend: { component: 'component.tsx' },
              config_scope: ['global', 'client'],
              data_scope: ['client', 'feed_source'],
            },
          },
        ]);
      }
      if (url === '/feed-sources/1/pipeline') {
        return jsonResponse({
          instances: [
            { id: 21, position: 0, plugin_id: 'probe', name: 'Probe',
              configuration: {}, enabled: true },
          ],
        });
      }
      return jsonResponse({});
    });
    renderAt();
    const probe = await screen.findByTestId('probe-component');
    expect(probe).toHaveAttribute('data-scope', JSON.stringify({ feedSourceId: 1 }));
  });
```

- [ ] **Step 8: Run the pipeline suite and typecheck**

Run: `npm run test -- PipelinePage` then `npm run typecheck` (from `frontend/`)
Expected: PASS / no type errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/pipeline/PluginConfigPanel.tsx \
  frontend/src/features/pipeline/PluginConfigPanel.test.tsx \
  frontend/src/features/pipeline/PipelinePage.tsx \
  frontend/src/features/pipeline/PipelinePage.test.tsx \
  frontend/src/test/probeComponent.tsx \
  frontend/public/locales/en/pipeline.json frontend/public/locales/de/pipeline.json
git commit -m "feat(frontend): pipeline editor config hub - tier switcher and embedded plugin UIs"
```

---

### Task 4: Remove the "Plugins" sidebar section

Plugin configuration now lives in the Pipeline Editor; the per-plugin nav links (which landed users on read-only pages for `custom_labels`) go away. Routes stay as deep links.

**Files:**
- Modify: `frontend/src/app/AppShell.tsx`
- Modify: `frontend/src/app/AppShell.test.tsx`
- Modify: `frontend/public/locales/en/common.json`, `frontend/public/locales/de/common.json` (drop unused `nav.plugins`)

**Interfaces:**
- Consumes: nothing new; deletes the `pluginItems` block, `pluginIcon`/`PLUGIN_ICONS`, `isClientScoped`/`isFeedScoped`, and the `manifestScopes` import added in Task 2, plus now-unused imports (`useMemo`, `usePlugins`, `IconPuzzle`, `PluginInfo`, `useTranslation` stays).
- Produces: sidebar with exactly Dashboard + the 5 feed-scoped items.

- [ ] **Step 1: Update the failing test first**

In `frontend/src/app/AppShell.test.tsx`:

1. Rename the first test and drop plugin assertions:

```tsx
  it('renders the fixed navigation without a plugins section', async () => {
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.getByText('Setup')).toBeInTheDocument();
    expect(screen.getByText('Products')).toBeInTheDocument();
    expect(screen.getByText('Pipeline Editor')).toBeInTheDocument();
    expect(screen.getByText('Monitoring')).toBeInTheDocument();
    expect(screen.getByText('Export')).toBeInTheDocument();
    expect(screen.queryByText('Plugins')).not.toBeInTheDocument();
    expect(screen.queryByText('Example Upper')).not.toBeInTheDocument();
    expect(screen.queryByText('Global Tool')).not.toBeInTheDocument();
  });
```

2. Delete these tests entirely (they assert plugin links that no longer exist):
   - `links a global-scoped plugin to the global plugin route`
   - `links a client-scoped plugin to the client route while on a client page`
   - `hides a client-scoped plugin from the nav when no client is selected`
   - `treats a plugin with client data_scope as client-scoped`
   - `defaults a manifest without scope fields to the global route on a client page`
   - `links a feed-scoped plugin to the feed route while inside a feed context`
   - `hides a feed-scoped plugin from the nav outside a feed context`
   - `hides a feed-scoped plugin from the nav on the dashboard`

3. The `plugins` fixture array and the `/plugins` handler line can stay (other tests use the same fetch stub; harmless).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm run test -- AppShell` (from `frontend/`)
Expected: FAIL — "Plugins"/"Example Upper" still rendered.

- [ ] **Step 3: Remove the section from `AppShell.tsx`**

In `frontend/src/app/AppShell.tsx`:

1. Delete the `PLUGIN_ICONS` const and `pluginIcon` function (lines 42-47).
2. Delete `isClientScoped` and `isFeedScoped` (lines 59-71).
3. Delete the `manifestScopes` import added in Task 2 (`import { manifestScopes } from '../features/pipeline/tierUtils';`).
4. In the `AppShell` component (line ~239): delete `const { data: plugins } = usePlugins();` and the `pluginItems` `useMemo` (lines ~249-255).
5. Delete the whole `pluginItems.length > 0 ? (...) : null` JSX block (lines ~320-354).
6. Remove now-unused imports: `useMemo` from 'react'; `IconPuzzle` from '@tabler/icons-react'; `usePlugins` from `'../api/hooks'` (keep the other hooks in that import); `import type { PluginInfo } from '../api/types';` (only if no other usage remains in the file — check with a search before removing).
7. In `frontend/public/locales/en/common.json` and `de/common.json`: remove the `"plugins": "Plugins"` line from the `nav` object.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm run test -- AppShell` (from `frontend/`)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/AppShell.tsx frontend/src/app/AppShell.test.tsx \
  frontend/public/locales/en/common.json frontend/public/locales/de/common.json
git commit -m "feat(frontend): remove plugins sidebar section - pipeline editor is the config hub"
```

---

### Task 5: ADR-0006, docs updates, full verification

Repo rule: behavior/doc changes ship in the same commit. Navigation, embedding, and the now-existing `PluginErrorBoundary` must be reflected in the frontend docs.

**Files:**
- Create: `docs/decisions/0006-pipeline-editor-config-hub.md`
- Modify: `frontend/docs/architecture.md` (navigation section)
- Modify: `frontend/docs/plugin-uis.md` (error-boundary follow-up note + pipeline embedding)
- Modify: `docs/superpowers/specs/2026-09-07-pipeline-editor-config-hub-design.md` — no change needed (spec matches).

**Interfaces:** none (documentation only).

- [ ] **Step 1: Write ADR-0006**

Create `docs/decisions/0006-pipeline-editor-config-hub.md` (same format as `docs/decisions/0005-labelizer-scope-merge-and-value-pinning.md`):

```markdown
# ADR-0006: Pipeline Editor as Plugin Config Hub

## Status
Accepted

## Context
Plugin configuration lived on two surfaces: per-instance settings in the
Pipeline Editor (RJSF form over `instance.configuration`) and the rich scoped
UIs (Rules, Filter, Labelizer) on dedicated plugin pages with the three-tier
scope merge. The sidebar linked each plugin by its most specific manifest
scope, which for `custom_labels` (config_scope `["global", "client"]`) landed
users on a feed-tier page whose Slot Rules tab is read-only — a dead end that
sent them elsewhere to manage rules.

## Decision
1. The Pipeline Editor is the single hub for configuring a feed's plugins.
   `PluginConfigPanel` embeds the plugin's registered custom component
   (`CUSTOM_COMPONENTS`) inside a tier switcher (Feed / Client / Global,
   derived from manifest scopes, default Feed) and re-renders it with the
   selected `PluginScope`. Tier semantics stay exactly as designed (ADR 0005):
   Labelizer slot rules remain editable only at Global/Client tier; at Feed
   tier an actionable alert switches to the highest editable tier instead of
   the old dead-end hint.
2. Instance settings remain a separate, labeled section (RJSF over
   `instance.configuration`, saved with pipeline Save). Scoped config saves
   via `/plugins/{id}/config` stay independent transactions.
3. The sidebar "Plugins" section is removed; plugin routes remain as deep
   links (ScopeContextBar tier hrefs, bookmarks).
4. Embedded plugin UIs are wrapped in `PluginErrorBoundary` (ADR 0004
   follow-up now implemented), also used by `PluginPage`.

## Consequences
- Plugin components (`CustomLabelsUI`, `RulesUI`, `FilterUI`), manifests,
  backend routes, and DB schema are unchanged.
- Global-tier config is now reachable from any feed's Pipeline Editor via the
  switcher (previously only via the global plugin route, which still exists).
- The sidebar shows Dashboard + feed items only.
```

- [ ] **Step 2: Update `frontend/docs/architecture.md`**

Read the file, locate the section describing navigation/sidebar (search for `AppShell` or `nav`). Replace the sentences describing plugin menu items in the sidebar with:

```markdown
The sidebar shows Dashboard plus the feed-scoped areas (Setup, Products,
Pipeline, Monitoring, Export). Plugin configuration is reached through the
Pipeline Editor: `PluginConfigPanel` embeds the plugin's custom UI with a
tier switcher (Feed / Client / Global, derived from manifest scopes). Plugin
routes (`/plugins/:id`, `/clients/:c/plugins/:id`,
`/clients/:c/feeds/:f/plugins/:id`) remain as deep links.
```

- [ ] **Step 3: Update `frontend/docs/plugin-uis.md`**

Read the file. In the section around line 128-137 that says "Planned follow-up — `PluginErrorBoundary` does not exist yet", replace that block with the actual state:

```markdown
Error isolation via `PluginErrorBoundary` (`src/features/plugin/PluginErrorBoundary.tsx`):
custom plugin components are wrapped with it in both `PluginPage` and the
Pipeline Editor's `PluginConfigPanel`, so a crashing plugin UI shows a retry
fallback instead of taking the page down (ADR 0004).
```

Also add a short subsection after the discovery/rendering description:

```markdown
### Pipeline Editor embedding

`PluginConfigPanel` (Pipeline Editor) renders a registered custom component
inside a tier switcher (Feed / Client / Global) driven by the manifest's
`config_scope`/`data_scope` ∩ route context. Switching tiers re-renders the
component with the matching `PluginScope`; the component itself is
unchanged. When the manifest's `config_scope` excludes `feed_source`
(e.g. `custom_labels`), the panel shows an actionable alert that switches to
the highest editable tier.
```

- [ ] **Step 4: Full verification**

Run from `frontend/`:

```bash
npm run test
npm run typecheck
```

Expected: all tests PASS, no type errors. If any test outside the touched files references the removed sidebar plugins section (e.g. router or i18n tests), fix that test in this task and mention it in the commit message.

- [ ] **Step 5: Commit**

```bash
git add docs/decisions/0006-pipeline-editor-config-hub.md \
  frontend/docs/architecture.md frontend/docs/plugin-uis.md
git commit -m "docs(frontend): ADR-0006 pipeline editor config hub; nav and plugin-UI docs"
```

---

## Self-Review (completed)

- **Spec coverage:** tier switcher + embedded UI + labeled sections (Task 3), read-only actionable alert (Task 3), sidebar removal + routes kept (Task 4), error boundary (Tasks 1+3, also fixes the ADR-0004 follow-up), i18n en/de (Tasks 1/3/4), docs + ADR (Task 5). PipelinePage pass-through of route ids (Task 3 Step 6-7).
- **Type consistency:** `ConfigTier`, `scopeForTier`, `tierOptions`, `highestEditableConfigTier`, `configEditableAtFeed` names match between Task 2 (definition) and Task 3 (usage). `PluginErrorBoundary` props match Task 1 → Task 3. Panel `Props` in Task 3 matches the `PipelinePage` JSX edit.
- **No placeholders:** every code step contains complete code; the two flagged "implementer notes" in Task 3 Step 2 offer a concrete preferred alternative (crash-flag probe), not a TBD.
