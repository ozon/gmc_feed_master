# M10-b Frontend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the M10 frontend foundation — pinned dependencies, i18n, Mantine theme, router + auth guard, AppShell with dynamic plugin nav, query keys, notifications, and shared components (incl. JsonSchemaForm) — so M10-c/d can implement the feature areas on top.

**Architecture:** Client-side SPA in `frontend/` (React 19 + Vite 8 + TypeScript 7). Mantine v9 provides the component library and AppShell layout; TanStack Query owns all server state (central query-key factory, no server state copied into client state); React Router v7 (data router) provides routing with a `RequireSession` guard; react-i18next provides lazy HTTP-loaded namespaces with typed keys. The existing `src/api.ts` fetch client is extended into `src/api/client.ts` with centralized 401 handling.

**Tech Stack:** React 19.2.7, Vite 8.2.2, TypeScript 7.0.2, vitest 4.1.11, @mantine/{core,hooks,notifications,dates}@9.5.2, @tabler/icons-react, @tanstack/react-query, react-router@7, i18next + react-i18next + i18next-browser-languagedetector + i18next-http-backend, dayjs.

**Working tree:** All work happens in the isolated worktree created by the executing skill (branch `m10-b-frontend`, base = current `main`). All frontend commands run from `<worktree>/frontend`.

## Global Constraints

These bind every task (from `docs/superpowers/specs/2026-08-28-m10-frontend-design.md` §2, `m10-frontend-instructions.md`, `i18n-agent-instructions.md`):

- Mantine pinned exactly to `9.5.2` for `@mantine/core`, `@mantine/hooks`, `@mantine/notifications`, `@mantine/dates`. Docs reference: `https://mantine.dev/llms.txt` (fetch the per-component page before writing against an unfamiliar component).
- Mantine default theme with `primaryColor: 'blue'` (recorded in `docs/decisions.md`). Dark/light toggle persisted via Mantine color-scheme storage. Text wordmark placeholder logo (no brand assets).
- React Router v7 (`react-router@7`, data router `createBrowserRouter`). Selected client/feed context comes from URL params only — no duplicated context store.
- i18n per `i18n-agent-instructions.md` exactly: `fallbackLng: 'en'`, allowlist `['en','de']`, detector order querystring → localStorage → navigator, cache in localStorage, `common` preloaded, all other namespaces lazy via `i18next-http-backend` from `public/locales/<lng>/<ns>.json`, typed keys via declaration merging from `en` resources. **Never statically import locale JSON into application code** (type-generation imports in `.d.ts` are the only exception). No hardcoded user-facing strings — everything through `t()`/`Trans`.
- Notifications via `@mantine/notifications`: provider mounted once at root, position top-right, `limit: 5`, errors sticky/longer autoClose, all text via `t()` (`notifications` namespace).
- Polling (fixed): while any run of the current feed source is `running` → `refetchInterval: 5000` on runs/findings/dashboard summary; idle dashboard summary → `30000`; `refetchIntervalInBackground: false` everywhere.
- Server state is never copied into client state; every mutation invalidates affected query keys via the central factory.
- No comments in code (repo convention). TypeScript strict; no `any` casts around translation calls.
- Frontend gate (must pass at end of each task and matches CI): `npm test -- --run && npm run typecheck && npm run build` from `frontend/`.
- Tests: vitest + Testing Library, jsdom, `fetch` stubbed with `vi.fn()` (existing pattern — no new mocking library). Mantine components require `MantineProvider` in the tree; use the shared custom render from Task 1.

---

## File Structure

New/modified files and their single responsibility:

```
frontend/
├── postcss.config.cjs                 # Mantine PostCSS preset + breakpoint vars
├── vite.config.ts                     # MODIFY: extend dev proxy to all API prefixes (Task 9)
├── package.json                       # MODIFY: pinned deps (Task 1)
├── public/locales/{en,de}/*.json      # 11 namespaces each (Task 2)
└── src/
    ├── main.tsx                       # MODIFY: import i18n first, render <App/>
    ├── App.tsx                        # MODIFY: provider composition root
    ├── app/
    │   ├── theme.ts                   # createTheme({ primaryColor: 'blue' })
    │   ├── router.tsx                 # route tree + RequireSession + AppRouter
    │   └── AppShell.tsx               # Mantine AppShell layout (header/navbar/breadcrumb)
    ├── i18n/
    │   ├── index.ts                   # single i18next init module
    │   ├── i18next.d.ts               # typed keys from en resources
    │   ├── LocaleProvider.tsx         # dayjs.locale + document.lang + DatesProvider
    │   └── LanguageSwitcher.tsx       # header language control
    ├── api/
    │   ├── client.ts                  # typed fetch client + centralized 401 (replaces ../api.ts)
    │   ├── queryClient.ts             # QueryClient instance
    │   ├── queryKeys.ts               # central query-key factory
    │   └── hooks.ts                   # foundation query/mutation hooks
    ├── components/
    │   ├── StateViews.tsx             # LoadingState / EmptyState / ErrorState
    │   ├── ConfirmModal.tsx           # irreversible-action confirm modal
    │   ├── CopyField.tsx              # read-only value + copy button
    │   └── JsonSchemaForm.tsx         # Mantine-themed JSON Schema renderer
    ├── features/
    │   ├── auth/LoginPage.tsx         # minimal Mantine login (guard target)
    │   └── placeholders.tsx           # placeholder pages for M10-c/d areas
    └── test/
        ├── setup.ts                   # MODIFY: Mantine jsdom mocks + default locale fetch + i18n init (Task 2)
        ├── fetch.ts                   # locale-aware fetch stub helpers (Task 2)
        └── render.tsx                 # custom render with MantineProvider env="test"
```

The existing `src/api.ts` and `src/App.css` are removed; `src/App.test.tsx` is replaced by task-specific tests.

---

### Task 1: Pinned dependencies + Mantine foundation (theme, providers, PostCSS, test setup)

**Files:**
- Modify: `frontend/package.json` (deps)
- Create: `frontend/postcss.config.cjs`
- Create: `frontend/src/app/theme.ts`
- Modify: `frontend/src/test/setup.ts`
- Create: `frontend/src/test/render.tsx`
- Modify: `frontend/src/main.tsx`, `frontend/src/App.tsx`
- Remove: `frontend/src/App.css`
- Test: `frontend/src/app/theme.test.tsx`

**Interfaces:**
- Consumes: nothing (foundation).
- Produces: `theme` (MantineThemeOverride) used by App and test render; `render(ui)` test helper used by every later test; `App` provider root that later tasks extend.

- [ ] **Step 1: Install pinned dependencies**

Run from `frontend/`:

```bash
npm install --save-exact \
  @mantine/core@9.5.2 @mantine/hooks@9.5.2 @mantine/notifications@9.5.2 @mantine/dates@9.5.2 \
  @tabler/icons-react@^3.0.0 \
  @tanstack/react-query@^5.0.0 @tanstack/react-table@^9.0.0 @tanstack/react-form@^1.0.0 \
  @dnd-kit/core@^6.0.0 @dnd-kit/sortable@^10.0.0 \
  react-router@7.18.2 \
  i18next@^26.0.0 react-i18next@^17.0.0 i18next-browser-languagedetector@^8.0.0 i18next-http-backend@^4.0.0 \
  dayjs@^1.11.0
npm install --save-exact --save-dev postcss@^8.5.0 postcss-preset-mantine@^1.18.0 postcss-simple-vars@^7.0.0
```

All packages from design §2.1 are installed now (pins are recorded in Task 9) even though `@tanstack/react-table`, `@tanstack/react-form`, and `@dnd-kit/*` are first used by M10-c/d. Record the exact resolved versions (`npm ls --depth=0`) in your report — Task 9 writes them into `docs/decisions.md`.

- [ ] **Step 2: Create `postcss.config.cjs`**

```js
module.exports = {
  plugins: {
    'postcss-preset-mantine': {},
    'postcss-simple-vars': {
      variables: {
        'mantine-breakpoint-xs': '36em',
        'mantine-breakpoint-sm': '48em',
        'mantine-breakpoint-md': '62em',
        'mantine-breakpoint-lg': '75em',
        'mantine-breakpoint-xl': '88em',
      },
    },
  },
};
```

- [ ] **Step 3: Create `src/app/theme.ts`**

```ts
import { createTheme } from '@mantine/core';

export const theme = createTheme({
  primaryColor: 'blue',
});
```

- [ ] **Step 4: Update `src/test/setup.ts` with Mantine jsdom mocks**

Replace the file contents with:

```ts
import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

const { getComputedStyle } = window;
window.getComputedStyle = (elt) => getComputedStyle(elt);
window.HTMLElement.prototype.scrollIntoView = () => {};

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

if (!document.fonts) {
  Object.defineProperty(document, 'fonts', {
    writable: true,
    value: { addEventListener: vi.fn(), removeEventListener: vi.fn() },
  });
}

class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

window.ResizeObserver = ResizeObserver;
```

- [ ] **Step 5: Create `src/test/render.tsx` (custom render)**

```tsx
import { render as testingLibraryRender } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import type { ReactNode } from 'react';
import { theme } from '../app/theme';

export function render(ui: ReactNode) {
  return testingLibraryRender(<>{ui}</>, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <MantineProvider theme={theme} env="test">
        {children}
      </MantineProvider>
    ),
  });
}
```

- [ ] **Step 6: Write the failing test `src/app/theme.test.tsx`**

```tsx
import { describe, expect, it } from 'vitest';
import { theme } from './theme';
import { render } from '../test/render';
import { Button } from '@mantine/core';
import { screen } from '@testing-library/react';

describe('theme', () => {
  it('uses blue as the primary color', () => {
    expect(theme.primaryColor).toBe('blue');
  });

  it('renders Mantine children inside the provider', () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Run test to verify it fails**

Run: `npx vitest run src/app/theme.test.tsx`
Expected: FAIL — cannot resolve `@mantine/core` (if deps not yet installed) or `./theme` missing.

- [ ] **Step 8: Rewire `src/main.tsx` and `src/App.tsx` as the provider root**

`src/main.tsx`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`src/App.tsx` (foundation composition root; later tasks wrap `AppRouter` inside it):

```tsx
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';

import { Center, MantineProvider, Text } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { theme } from './app/theme';

export default function App() {
  return (
    <MantineProvider theme={theme}>
      <Notifications position="top-right" limit={5} />
      <Center h="100vh">
        <Text>GMC Feed Master</Text>
      </Center>
    </MantineProvider>
  );
}
```

Delete `src/App.css` and remove its import. Delete `src/App.test.tsx` (it tests the removed demo app; later tasks add real tests).

- [ ] **Step 9: Run test to verify it passes**

Run: `npx vitest run src/app/theme.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 10: Run the full gate**

Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: all green. (If `src/api.ts` is now unused, leave it until Task 3 replaces it.)

- [ ] **Step 11: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/postcss.config.cjs \
  frontend/src/app/theme.ts frontend/src/app/theme.test.tsx frontend/src/test/setup.ts \
  frontend/src/test/render.tsx frontend/src/main.tsx frontend/src/App.tsx
git rm frontend/src/App.css frontend/src/App.test.tsx
git commit -m "feat(m10-b): pin frontend deps and add Mantine theme/provider foundation"
```

---

### Task 2: i18n foundation (init, typed keys, locale files, LocaleProvider, LanguageSwitcher)

**Files:**
- Create: `frontend/src/i18n/index.ts`, `frontend/src/i18n/i18next.d.ts`, `frontend/src/i18n/LocaleProvider.tsx`, `frontend/src/i18n/LanguageSwitcher.tsx`
- Create: `frontend/public/locales/en/*.json` and `frontend/public/locales/de/*.json` (11 namespaces each)
- Create: `frontend/src/test/fetch.ts`
- Modify: `frontend/src/main.tsx` (import i18n first), `frontend/src/App.tsx` (LocaleProvider + Suspense), `frontend/src/test/setup.ts` (default locale fetch + await i18n init)
- Test: `frontend/src/i18n/i18n.test.tsx`

**Interfaces:**
- Consumes: `theme`/`render` from Task 1.
- Produces: `i18n` default export (initialized instance); `LocaleProvider` wrapping the app; `LanguageSwitcher` used by AppShell (Task 7); typed `t()` for all later components.

- [ ] **Step 1: Create the 11 namespace files for `en` and `de`**

Create `frontend/public/locales/en/common.json`:

```json
{
  "appName": "GMC Feed Master",
  "nav": {
    "dashboard": "Dashboard",
    "setup": "Setup",
    "products": "Products",
    "pipeline": "Pipeline Editor",
    "monitoring": "Monitoring",
    "export": "Export",
    "plugins": "Plugins"
  },
  "actions": {
    "confirm": "Confirm",
    "cancel": "Cancel",
    "save": "Save",
    "close": "Close",
    "retry": "Retry",
    "copy": "Copy",
    "copied": "Copied",
    "add": "Add",
    "remove": "Remove",
    "logout": "Log out",
    "changePassword": "Change password"
  },
  "state": {
    "loading": "Loading…",
    "empty": "Nothing here yet.",
    "error": "Something went wrong."
  },
  "language": {
    "label": "Language",
    "en": "English",
    "de": "German"
  },
  "colorScheme": {
    "toLight": "Switch to light mode",
    "toDark": "Switch to dark mode"
  },
  "breadcrumbs": {
    "selectClient": "Select client",
    "selectFeed": "Select feed"
  }
}
```

Create `frontend/public/locales/en/auth.json`:

```json
{
  "login": {
    "title": "Sign in",
    "subtitle": "Use your operator account to continue.",
    "username": "Username",
    "password": "Password",
    "submit": "Sign in",
    "submitting": "Signing in…",
    "error": "Unable to sign in. Check your credentials and try again."
  },
  "passwordChange": {
    "title": "Change password",
    "current": "Current password",
    "next": "New password",
    "confirm": "Confirm new password",
    "submit": "Change password",
    "success": "Password changed. Sign in with your new password.",
    "mismatch": "New passwords do not match.",
    "error": "Unable to change password."
  }
}
```

Create `frontend/public/locales/en/notifications.json`:

```json
{
  "runFinished": "Run finished",
  "runFailed": "Run failed",
  "mutationSuccess": "Saved",
  "mutationError": "Request failed",
  "validationError": "Please fix the highlighted fields."
}
```

Create `frontend/public/locales/en/plugins.json`:

```json
{
  "section": "Plugins",
  "empty": "No plugins available."
}
```

Create the remaining seven `en` namespaces as minimal stubs that M10-c/d will expand — `dashboard.json`, `setup.json`, `mapping.json`, `products.json`, `pipeline.json`, `monitoring.json`, `export.json` — each containing:

```json
{
  "title": "<Area>"
}
```

with `<Area>` = `Dashboard`, `Setup`, `Mapping`, `Products`, `Pipeline Editor`, `Monitoring`, `Export` respectively.

Create the `de` mirrors. `de/common.json`:

```json
{
  "appName": "GMC Feed Master",
  "nav": {
    "dashboard": "Übersicht",
    "setup": "Einrichtung",
    "products": "Produkte",
    "pipeline": "Pipeline-Editor",
    "monitoring": "Überwachung",
    "export": "Export",
    "plugins": "Plugins"
  },
  "actions": {
    "confirm": "Bestätigen",
    "cancel": "Abbrechen",
    "save": "Speichern",
    "close": "Schließen",
    "retry": "Erneut versuchen",
    "copy": "Kopieren",
    "copied": "Kopiert",
    "add": "Hinzufügen",
    "remove": "Entfernen",
    "logout": "Abmelden",
    "changePassword": "Passwort ändern"
  },
  "state": {
    "loading": "Wird geladen…",
    "empty": "Noch nichts vorhanden.",
    "error": "Etwas ist schiefgelaufen."
  },
  "language": {
    "label": "Sprache",
    "en": "Englisch",
    "de": "Deutsch"
  },
  "colorScheme": {
    "toLight": "Zum hellen Modus wechseln",
    "toDark": "Zum dunklen Modus wechseln"
  },
  "breadcrumbs": {
    "selectClient": "Mandant auswählen",
    "selectFeed": "Feed auswählen"
  }
}
```

`de/auth.json`:

```json
{
  "login": {
    "title": "Anmelden",
    "subtitle": "Verwenden Sie Ihr Operator-Konto, um fortzufahren.",
    "username": "Benutzername",
    "password": "Passwort",
    "submit": "Anmelden",
    "submitting": "Anmeldung läuft…",
    "error": "Anmeldung nicht möglich. Prüfen Sie Ihre Zugangsdaten."
  },
  "passwordChange": {
    "title": "Passwort ändern",
    "current": "Aktuelles Passwort",
    "next": "Neues Passwort",
    "confirm": "Neues Passwort bestätigen",
    "submit": "Passwort ändern",
    "success": "Passwort geändert. Melden Sie sich mit dem neuen Passwort an.",
    "mismatch": "Die neuen Passwörter stimmen nicht überein.",
    "error": "Passwort konnte nicht geändert werden."
  }
}
```

`de/notifications.json`:

```json
{
  "runFinished": "Lauf abgeschlossen",
  "runFailed": "Lauf fehlgeschlagen",
  "mutationSuccess": "Gespeichert",
  "mutationError": "Anfrage fehlgeschlagen",
  "validationError": "Bitte korrigieren Sie die markierten Felder."
}
```

`de/plugins.json`:

```json
{
  "section": "Plugins",
  "empty": "Keine Plugins verfügbar."
}
```

And the seven `de` stubs with `"title"`: `Übersicht`, `Einrichtung`, `Mapping`, `Produkte`, `Pipeline-Editor`, `Überwachung`, `Export`.

- [ ] **Step 2: Create `src/i18n/index.ts` (single init module)**

The backend uses a custom `request` function built on global `fetch` (documented `i18next-http-backend` option). This gives one code path in the browser and in tests, where `fetch` is stubbed — jsdom provides `XMLHttpRequest`, which the backend's default transport would otherwise prefer and which cannot be stubbed with `vi.stubGlobal('fetch', ...)`. The callback contract is `callback(err, { status, data })` with `data` as the response text. `initPromise` is exported so the test setup can await startup before any test runs.

```ts
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import HttpBackend, { type HttpBackendOptions } from 'i18next-http-backend';

export const SUPPORTED_LANGUAGES = ['en', 'de'] as const;

export const initPromise = i18n
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init<HttpBackendOptions>({
    fallbackLng: 'en',
    supportedLngs: [...SUPPORTED_LANGUAGES],
    ns: ['common'],
    defaultNS: 'common',
    preload: ['common'],
    backend: {
      loadPath: '/locales/{{lng}}/{{ns}}.json',
      request: (_options, url, _payload, callback) => {
        void fetch(url)
          .then(async (response) => {
            if (!response.ok) {
              callback(new Error(`Failed to load ${url}: ${response.status}`), null);
              return;
            }
            callback(null, { status: response.status, data: await response.text() });
          })
          .catch((error: unknown) => {
            callback(error instanceof Error ? error : new Error(String(error)), null);
          });
      },
    },
    detection: {
      order: ['querystring', 'localStorage', 'navigator'],
      caches: ['localStorage'],
    },
    interpolation: {
      escapeValue: false,
    },
  });

export default i18n;
```

If the installed `i18next-http-backend` types do not export `HttpBackendOptions` or reject the `request` signature, adapt the typing (e.g. type the options parameter of `request` as the backend's options type via `Parameters<...>` or a minimal structural type) — do not drop the custom `request` function itself.

- [ ] **Step 3: Create `src/i18n/i18next.d.ts` (typed keys from en resources)**

```ts
import 'i18next';
import type auth from '../../public/locales/en/auth.json';
import type common from '../../public/locales/en/common.json';
import type dashboard from '../../public/locales/en/dashboard.json';
import type exportNs from '../../public/locales/en/export.json';
import type mapping from '../../public/locales/en/mapping.json';
import type monitoring from '../../public/locales/en/monitoring.json';
import type pipeline from '../../public/locales/en/pipeline.json';
import type plugins from '../../public/locales/en/plugins.json';
import type products from '../../public/locales/en/products.json';
import type setup from '../../public/locales/en/setup.json';
import type notifications from '../../public/locales/en/notifications.json';

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'common';
    resources: {
      auth: typeof auth;
      common: typeof common;
      dashboard: typeof dashboard;
      export: typeof exportNs;
      mapping: typeof mapping;
      monitoring: typeof monitoring;
      notifications: typeof notifications;
      pipeline: typeof pipeline;
      plugins: typeof plugins;
      products: typeof products;
      setup: typeof setup;
    };
  }
}
```

- [ ] **Step 4: Create `src/i18n/LocaleProvider.tsx`**

```tsx
import { useEffect, useMemo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { DatesProvider } from '@mantine/dates';
import dayjs from 'dayjs';
import 'dayjs/locale/de';

export function LocaleProvider({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation();
  const language = i18n.language;

  useEffect(() => {
    dayjs.locale(language);
    document.documentElement.lang = language;
  }, [language]);

  const settings = useMemo(
    () => ({ locale: language, firstDayOfWeek: language === 'de' ? 1 : 0 }),
    [language],
  );

  return <DatesProvider settings={settings}>{children}</DatesProvider>;
}
```

- [ ] **Step 5: Create `src/i18n/LanguageSwitcher.tsx`**

```tsx
import { Select } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { SUPPORTED_LANGUAGES } from './index';

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();

  return (
    <Select
      size="xs"
      w={110}
      aria-label={t('language.label')}
      data={SUPPORTED_LANGUAGES.map((lng) => ({ value: lng, label: t(`language.${lng}`) }))}
      value={i18n.language}
      onChange={(value) => {
        if (value) void i18n.changeLanguage(value);
      }}
      allowDeselect={false}
    />
  );
}
```

- [ ] **Step 6: Wire i18n into `src/main.tsx`, `src/App.tsx`, and the test harness**

`src/main.tsx` — i18n import must be first (per `i18n-agent-instructions.md` §Initialization: imported exactly once, at the top of the application entry file):

```tsx
import './i18n';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`src/App.tsx` — add `LocaleProvider` and a `Suspense` boundary with a Mantine `Loader`:

```tsx
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';

import { Suspense } from 'react';
import { Center, Loader, MantineProvider, Text } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { theme } from './app/theme';
import { LocaleProvider } from './i18n/LocaleProvider';

export default function App() {
  return (
    <MantineProvider theme={theme}>
      <Notifications position="top-right" limit={5} />
      <LocaleProvider>
        <Suspense
          fallback={
            <Center h="100vh">
              <Loader />
            </Center>
          }
        >
          <Center h="100vh">
            <Text>GMC Feed Master</Text>
          </Center>
        </Suspense>
      </LocaleProvider>
    </MantineProvider>
  );
}
```

Test harness — create `src/test/fetch.ts`. `localeResponse` serves `public/locales/<lng>/<ns>.json` from disk for any `/locales/...` URL; `stubFetch` installs a `fetch` mock that always serves locales first and delegates everything else to the test's handler (so component tests that render `App` can still lazy-load namespaces while mocking API URLs):

```ts
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { vi } from 'vitest';

const localesDir = resolve(dirname(fileURLToPath(import.meta.url)), '../../public/locales');

export function localeResponse(url: string): Response | undefined {
  const match = url.match(/^\/locales\/([^/]+)\/([^/]+)\.json$/);
  if (!match) return undefined;
  const file = resolve(localesDir, match[1], `${match[2]}.json`);
  if (!existsSync(file)) return undefined;
  return new Response(readFileSync(file, 'utf8'), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

export function stubFetch(handler: (url: string) => Response | Promise<Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const locale = localeResponse(url);
    if (locale) return locale;
    return handler(url);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
```

Modify `src/test/setup.ts` — keep the Mantine jsdom mocks from Task 1 and append: (1) a default global `fetch` that serves locale files and throws on anything else (so the module-level i18n preload can resolve before any test), and (2) a `beforeAll` that dynamically imports the i18n module *after* the stub is installed (static imports would be hoisted above the stub) and awaits `initPromise` so `common` is loaded before the first render of every test file:

```ts
import { beforeAll } from 'vitest';
import { localeResponse } from './fetch';

vi.stubGlobal(
  'fetch',
  vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const locale = localeResponse(url);
    if (locale) return locale;
    throw new Error(`Unexpected fetch in test: ${url}`);
  }),
);

beforeAll(async () => {
  const { initPromise } = await import('../i18n');
  await initPromise;
});
```

- [ ] **Step 7: Write the failing test `src/i18n/i18n.test.tsx`**

```tsx
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from './index';
import { render } from '../test/render';
import { LanguageSwitcher } from './LanguageSwitcher';
import { LocaleProvider } from './LocaleProvider';
import { useTranslation } from 'react-i18next';

function Probe() {
  const { t } = useTranslation();
  return <span>{t('nav.dashboard')}</span>;
}

describe('i18n', () => {
  it('configures en fallback and the en/de allowlist', () => {
    expect(i18n.options.fallbackLng).toContain('en');
    expect(i18n.options.supportedLngs).toEqual(expect.arrayContaining(['en', 'de']));
  });

  it('translates from the common namespace', async () => {
    await i18n.changeLanguage('en');
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    expect(await screen.findByText('Dashboard')).toBeInTheDocument();
  });

  it('switches language without reload, updates html lang, and translates', async () => {
    const user = userEvent.setup();
    render(
      <LocaleProvider>
        <LanguageSwitcher />
        <Probe />
      </LocaleProvider>,
    );

    const switcher = await screen.findByRole('textbox', { name: 'Language' });
    await user.click(switcher);
    const german = await screen.findByRole('option', { name: 'Deutsch' });
    await user.click(german);

    expect(await screen.findByText('Übersicht')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('de');

    await i18n.changeLanguage('en');
  });
});
```

- [ ] **Step 8: Run test to verify it fails**

Run: `npx vitest run src/i18n/i18n.test.tsx`
Expected: FAIL — `./index` / locale files missing.

- [ ] **Step 9: Run test to verify it passes**

Run: `npx vitest run src/i18n/i18n.test.tsx`
Expected: PASS (3 tests). The harness from Step 6 already serves `/locales/...` from disk via the stubbed `fetch`, and the custom backend `request` function routes through it — no per-test stubbing should be needed here. If a load still fails, debug the stub/request wiring; do not switch to static locale imports.

- [ ] **Step 10: Run the full gate**

Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: all green. Confirm the production build emits the locale JSON as separate assets under `dist/locales/` and does not inline them into JS.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/i18n frontend/src/main.tsx frontend/src/App.tsx frontend/public/locales \
  frontend/src/test/fetch.ts frontend/src/test/setup.ts
git commit -m "feat(m10-b): add i18n foundation with lazy namespaces and typed keys"
```

---

### Task 3: Shared state components (StateViews, ConfirmModal, CopyField)

**Files:**
- Create: `frontend/src/components/StateViews.tsx`, `frontend/src/components/ConfirmModal.tsx`, `frontend/src/components/CopyField.tsx`
- Test: `frontend/src/components/StateViews.test.tsx`, `frontend/src/components/ConfirmModal.test.tsx`, `frontend/src/components/CopyField.test.tsx`

**Interfaces:**
- Consumes: `render` (Task 1), i18n `common` namespace (Task 2).
- Produces: `LoadingState`, `EmptyState`, `ErrorState` (used by RequireSession, AppShell, all areas); `ConfirmModal` (used by M10-c/d irreversible actions); `CopyField` (used by Export URL block).

- [ ] **Step 1: Create `src/components/StateViews.tsx`**

```tsx
import { Button, Center, Loader, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export function LoadingState() {
  const { t } = useTranslation();
  return (
    <Center py="xl">
      <Loader aria-label={t('state.loading')} />
    </Center>
  );
}

export function EmptyState({ message }: { message?: string }) {
  const { t } = useTranslation();
  return (
    <Center py="xl">
      <Text c="dimmed">{message ?? t('state.empty')}</Text>
    </Center>
  );
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <Center py="xl">
      <Stack align="center" gap="sm">
        <Text c="red" role="alert">
          {message ?? t('state.error')}
        </Text>
        {onRetry ? (
          <Button variant="light" onClick={onRetry}>
            {t('actions.retry')}
          </Button>
        ) : null}
      </Stack>
    </Center>
  );
}
```

- [ ] **Step 2: Create `src/components/ConfirmModal.tsx`**

```tsx
import { Button, Group, Modal, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export type ConfirmModalProps = {
  opened: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onClose: () => void;
};

export function ConfirmModal({
  opened,
  title,
  message,
  confirmLabel,
  danger = false,
  loading = false,
  onConfirm,
  onClose,
}: ConfirmModalProps) {
  const { t } = useTranslation();
  return (
    <Modal opened={opened} onClose={onClose} title={title} centered>
      <Text>{message}</Text>
      <Group mt="lg" justify="flex-end">
        <Button variant="default" onClick={onClose} disabled={loading}>
          {t('actions.cancel')}
        </Button>
        <Button color={danger ? 'red' : undefined} loading={loading} onClick={onConfirm}>
          {confirmLabel ?? t('actions.confirm')}
        </Button>
      </Group>
    </Modal>
  );
}
```

- [ ] **Step 3: Create `src/components/CopyField.tsx`**

```tsx
import { ActionIcon, CopyButton, Group, TextInput, Tooltip } from '@mantine/core';
import { IconCheck, IconCopy } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

export function CopyField({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  return (
    <Group gap="xs" wrap="nowrap">
      <TextInput readOnly value={value} label={label} style={{ flex: 1 }} />
      <CopyButton value={value}>
        {({ copied, copy }) => (
          <Tooltip label={copied ? t('actions.copied') : t('actions.copy')}>
            <ActionIcon
              variant="default"
              onClick={copy}
              aria-label={copied ? t('actions.copied') : t('actions.copy')}
              color={copied ? 'teal' : undefined}
            >
              {copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
            </ActionIcon>
          </Tooltip>
        )}
      </CopyButton>
    </Group>
  );
}
```

- [ ] **Step 4: Write the failing tests**

`src/components/StateViews.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { EmptyState, ErrorState, LoadingState } from './StateViews';

describe('StateViews', () => {
  it('renders a labelled loader', () => {
    render(<LoadingState />);
    expect(screen.getByRole('progressbar', { name: 'Loading…' })).toBeInTheDocument();
  });

  it('renders the default empty message', () => {
    render(<EmptyState />);
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument();
  });

  it('renders an error with a retry callback', async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorState onRetry={onRetry} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong.');
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
```

`src/components/ConfirmModal.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { ConfirmModal } from './ConfirmModal';

describe('ConfirmModal', () => {
  it('confirms and cancels', async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmModal
        opened
        title="Delete client"
        message="This cannot be undone."
        danger
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

`src/components/CopyField.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { CopyField } from './CopyField';

describe('CopyField', () => {
  it('copies the value to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const user = userEvent.setup();
    render(<CopyField label="Export URL" value="http://localhost/export/abc.xml" />);

    expect(screen.getByDisplayValue('http://localhost/export/abc.xml')).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Copy' }));
    expect(writeText).toHaveBeenCalledWith('http://localhost/export/abc.xml');
  });
});
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `npx vitest run src/components`
Expected: FAIL — components missing.

- [ ] **Step 6: Run tests to verify they pass**

Run: `npx vitest run src/components`
Expected: PASS (5 tests).

- [ ] **Step 7: Run the full gate**

Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components
git commit -m "feat(m10-b): add shared StateViews, ConfirmModal, and CopyField components"
```

---

### Task 4: API client + query keys + foundation hooks + QueryClient

**Files:**
- Create: `frontend/src/api/client.ts`, `frontend/src/api/queryClient.ts`, `frontend/src/api/queryKeys.ts`, `frontend/src/api/hooks.ts`
- Remove: `frontend/src/api.ts`
- Test: `frontend/src/api/client.test.ts`, `frontend/src/api/queryKeys.test.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: `apiGet/apiPost/apiPut/apiDelete`, `ApiError`, `setUnauthorizedHandler`, auth functions (`login`, `getCurrentUser`, `logout`, `changePassword`); `queryClient`; `queryKeys`; hooks `useSession`, `useDashboardSummary`, `usePlugins`, `useLogout`, `useChangePassword` used by RequireSession, AppShell, and M10-c/d areas.

- [ ] **Step 1: Create `src/api/client.ts`**

```ts
export type User = { username: string };

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | undefined;

  constructor(status: number, detail?: string) {
    super(detail ?? `Request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler;
}

async function parseError(response: Response): Promise<ApiError> {
  let detail: string | undefined;
  try {
    const body = (await response.json()) as { detail?: string };
    detail = body.detail;
  } catch {
    detail = undefined;
  }
  return new ApiError(response.status, detail);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, credentials: 'include' });
  if (!response.ok) {
    const authExempt =
      url.startsWith('/auth/login') || url.startsWith('/auth/password');
    if (response.status === 401 && unauthorizedHandler && !authExempt) {
      unauthorizedHandler();
    }
    throw await parseError(response);
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type');
  if (contentType && !contentType.includes('application/json')) return undefined as T;
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

export function apiGet<T>(url: string): Promise<T> {
  return request<T>(url);
}

export function apiPost<T>(url: string, body?: unknown): Promise<T> {
  return request<T>(url, jsonInit('POST', body));
}

export function apiPut<T>(url: string, body?: unknown): Promise<T> {
  return request<T>(url, jsonInit('PUT', body));
}

export function apiDelete<T>(url: string): Promise<T> {
  return request<T>(url, { method: 'DELETE' });
}

export function login(username: string, password: string): Promise<User> {
  return apiPost<User>('/auth/login', { username, password });
}

export function getCurrentUser(): Promise<User> {
  return apiGet<User>('/auth/me');
}

export function logout(): Promise<{ status: string }> {
  return apiPost<{ status: string }>('/auth/logout');
}

export function changePassword(currentPassword: string, newPassword: string): Promise<{ status: string }> {
  return apiPost<{ status: string }>('/auth/password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
}
```

- [ ] **Step 2: Create `src/api/queryClient.ts`**

```ts
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchIntervalInBackground: false,
    },
  },
});
```

- [ ] **Step 3: Create `src/api/queryKeys.ts`**

```ts
export const queryKeys = {
  session: ['session'] as const,
  dashboardSummary: ['dashboard', 'summary'] as const,
  clients: ['clients'] as const,
  plugins: ['plugins'] as const,
  feedSource: (id: number | string) => ({
    detail: ['feed-source', id] as const,
    products: (params: unknown) => ['feed-source', id, 'products', params] as const,
    pipeline: ['feed-source', id, 'pipeline'] as const,
    runs: ['feed-source', id, 'runs'] as const,
    findings: ['feed-source', id, 'findings'] as const,
    exportHistory: ['feed-source', id, 'export-history'] as const,
    fieldMapping: ['feed-source', id, 'field-mapping'] as const,
  }),
};
```

- [ ] **Step 4: Create `src/api/hooks.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, changePassword, getCurrentUser, logout } from './client';
import { queryKeys } from './queryKeys';

export type FeedSourceSummary = {
  id: number;
  client_id: number;
  name: string;
  source_format: string;
  item_count: number;
  last_export_at: string | null;
  last_export_status: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
};

export type ClientSummary = {
  id: number;
  name: string;
  status: string;
  feed_sources: FeedSourceSummary[];
};

export type DashboardSummary = {
  counts: {
    clients: number;
    feed_sources: number;
    active_products: number;
    failed_last_exports: number;
  };
  clients: ClientSummary[];
};

export type PluginManifestFrontend = {
  menu_item?: string;
  icon?: string;
  component?: string;
};

export type PluginInfo = {
  id: string;
  name: string;
  version: string;
  enabled: boolean;
  manifest: { frontend?: PluginManifestFrontend; [key: string]: unknown } | null;
  used_by_feed_sources: number;
};

export function useSession() {
  return useQuery({
    queryKey: queryKeys.session,
    queryFn: getCurrentUser,
    retry: false,
    staleTime: Infinity,
  });
}

export function useDashboardSummary() {
  return useQuery({
    queryKey: queryKeys.dashboardSummary,
    queryFn: () => apiGet<DashboardSummary>('/dashboard/summary'),
    refetchInterval: (query) => {
      const data = query.state.data as DashboardSummary | undefined;
      const anyRunning = data?.clients.some((client) =>
        client.feed_sources.some((feed) => feed.last_run_status === 'running'),
      );
      return anyRunning ? 5000 : 30000;
    },
  });
}

export function usePlugins() {
  return useQuery({
    queryKey: queryKeys.plugins,
    queryFn: () => apiGet<PluginInfo[]>('/plugins'),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSuccess: () => {
      void queryClient.resetQueries({ queryKey: queryKeys.session });
    },
  });
}

export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ currentPassword, newPassword }: { currentPassword: string; newPassword: string }) =>
      changePassword(currentPassword, newPassword),
    onSuccess: () => {
      void queryClient.resetQueries({ queryKey: queryKeys.session });
    },
  });
}
```

- [ ] **Step 5: Write the failing tests**

`src/api/client.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  apiGet,
  changePassword,
  getCurrentUser,
  login,
  setUnauthorizedHandler,
} from './client';

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  setUnauthorizedHandler(null);
});

describe('api client', () => {
  it('sends credentials and parses JSON', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ username: 'operator' }));
    await expect(getCurrentUser()).resolves.toEqual({ username: 'operator' });
    expect(fetchMock).toHaveBeenCalledWith(
      '/auth/me',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('throws ApiError with the backend detail', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid credentials' }, 401));
    const error = await login('a', 'b').catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(401);
    expect(error.detail).toBe('Invalid credentials');
  });

  it('invokes the unauthorized handler on non-login 401', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Not authenticated' }, 401));
    await apiGet('/dashboard/summary').catch(() => undefined);
    expect(handler).toHaveBeenCalledTimes(1);
  });
  it('does not invoke the handler for a failed login', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid credentials' }, 401));
    await login('a', 'b').catch(() => undefined);
    expect(handler).not.toHaveBeenCalled();
  });

  it('does not invoke the handler for a failed password change', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid credentials' }, 401));
    await changePassword('wrong', 'new').catch(() => undefined);
    expect(handler).not.toHaveBeenCalled();
  });
});
```

`src/api/queryKeys.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { queryKeys } from './queryKeys';

describe('queryKeys', () => {
  it('builds stable top-level keys', () => {
    expect(queryKeys.session).toEqual(['session']);
    expect(queryKeys.dashboardSummary).toEqual(['dashboard', 'summary']);
    expect(queryKeys.plugins).toEqual(['plugins']);
  });

  it('nests feed-source keys by id and area', () => {
    expect(queryKeys.feedSource(7).pipeline).toEqual(['feed-source', 7, 'pipeline']);
    expect(queryKeys.feedSource(7).products({ page: 1 })).toEqual([
      'feed-source',
      7,
      'products',
      { page: 1 },
    ]);
  });
});
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `npx vitest run src/api`
Expected: FAIL — modules missing.

- [ ] **Step 7: Delete `src/api.ts` and run tests to verify they pass**

Remove `frontend/src/api.ts` (its functions now live in `src/api/client.ts`).
Run: `npx vitest run src/api`
Expected: PASS (7 tests).

- [ ] **Step 8: Run the full gate**

Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api
git rm frontend/src/api.ts
git commit -m "feat(m10-b): add typed API client, query-key factory, and foundation hooks"
```

---

### Task 5: Notification helpers + run-transition notifier

**Files:**
- Create: `frontend/src/app/notifications.ts`
- Test: `frontend/src/app/notifications.test.tsx`

**Interfaces:**
- Consumes: i18n `notifications` namespace (Task 2), `@mantine/notifications` (Task 1).
- Produces: `notifySuccess`, `notifyError`, `notifyMutationError`, `withLoadingNotification`, `useRunTransitionNotifier` used by M10-c/d mutations and polling views.

- [ ] **Step 1: Create `src/app/notifications.ts`**

```ts
import { notifications } from '@mantine/notifications';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../api/client';

export function notifySuccess(message: string) {
  notifications.show({ color: 'teal', message, autoClose: 4000 });
}

export function notifyError(message: string) {
  notifications.show({ color: 'red', message, autoClose: false });
}

export function notifyMutationError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.detail) {
    notifyError(error.detail);
    return;
  }
  notifyError(fallback);
}

export function withLoadingNotification<T>(
  id: string,
  loadingMessage: string,
  action: () => Promise<T>,
  successMessage: string,
  failureMessage: string,
): Promise<T> {
  notifications.show({ id, loading: true, message: loadingMessage, autoClose: false });
  return action()
    .then((result) => {
      notifications.update({ id, color: 'teal', message: successMessage, loading: false, autoClose: 4000 });
      return result;
    })
    .catch((error) => {
      notifications.update({ id, color: 'red', message: failureMessage, loading: false, autoClose: false });
      throw error;
    });
}

export type RunStatusView = { id: number; status: string };

export function useRunTransitionNotifier(runs: RunStatusView[] | undefined) {
  const { t } = useTranslation('notifications');
  const seen = useRef<Map<number, string>>(new Map());

  useEffect(() => {
    if (!runs) return;
    for (const run of runs) {
      const previous = seen.current.get(run.id);
      if (previous === 'running' && run.status === 'success') {
        notifySuccess(t('runFinished'));
      } else if (previous === 'running' && run.status === 'error') {
        notifyError(t('runFailed'));
      }
      seen.current.set(run.id, run.status);
    }
  }, [runs, t]);
}
```

- [ ] **Step 2: Write the failing test `src/app/notifications.test.tsx`**

```tsx
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../test/render';
import { Notifications } from '@mantine/notifications';
import { notifyError, notifyMutationError, notifySuccess } from './notifications';
import { ApiError } from '../api/client';

describe('notification helpers', () => {
  it('shows success and error notifications', async () => {
    render(<Notifications />);
    notifySuccess('Saved');
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    notifyError('Request failed');
    expect(await screen.findByText('Request failed')).toBeInTheDocument();
  });

  it('prefers the ApiError detail for mutation errors', async () => {
    render(<Notifications />);
    notifyMutationError(new ApiError(422, 'name already exists'), 'Request failed');
    expect(await screen.findByText('name already exists')).toBeInTheDocument();
  });

  it('falls back when the error has no detail', async () => {
    render(<Notifications />);
    notifyMutationError(new Error('boom'), 'Request failed');
    expect(await screen.findByText('Request failed')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npx vitest run src/app/notifications.test.tsx`
Expected: FAIL — `./notifications` missing.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/app/notifications.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full gate**

Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/notifications.ts frontend/src/app/notifications.test.tsx
git commit -m "feat(m10-b): add notification helpers and run-transition notifier"
```

---

### Task 6: Router + RequireSession guard + minimal login + placeholder pages

**Files:**
- Create: `frontend/src/app/router.tsx`, `frontend/src/features/auth/LoginPage.tsx`, `frontend/src/features/placeholders.tsx`
- Modify: `frontend/src/App.tsx` (render `AppRouter` inside providers)
- Test: `frontend/src/app/router.test.tsx`

**Interfaces:**
- Consumes: `useSession`, `login`, `setUnauthorizedHandler` (Task 4); `LoadingState` (Task 3); i18n `auth` namespace (Task 2).
- Produces: `AppRouter` rendered by `App`; the full route tree; `RequireSession` guard. M10-c/d replace the placeholder page components only — route paths are final.

Note: the design sequences the full Login area in M10-c (§4.1), but §2.3 (this milestone) requires the guard to restore the originally requested route *after successful login*, which needs a working login target. This task therefore ports the existing minimal login to Mantine; M10-c polishes it.

- [ ] **Step 1: Create `src/features/placeholders.tsx`**

```tsx
import { Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';

function Placeholder({ ns }: { ns: 'dashboard' | 'setup' | 'products' | 'pipeline' | 'monitoring' | 'export' }) {
  const { t } = useTranslation(ns);
  return <Title order={2}>{t('title')}</Title>;
}

export function DashboardPlaceholder() {
  return <Placeholder ns="dashboard" />;
}

export function SetupPlaceholder() {
  return <Placeholder ns="setup" />;
}

export function ProductsPlaceholder() {
  return <Placeholder ns="products" />;
}

export function PipelinePlaceholder() {
  return <Placeholder ns="pipeline" />;
}

export function MonitoringPlaceholder() {
  return <Placeholder ns="monitoring" />;
}

export function ExportPlaceholder() {
  return <Placeholder ns="export" />;
}

export function PluginPlaceholder() {
  return <Title order={2}>Plugin</Title>;
}
```

- [ ] **Step 2: Create `src/features/auth/LoginPage.tsx`**

```tsx
import { useState, type FormEvent } from 'react';
import { Button, Center, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router';
import { login } from '../../api/client';
import { queryClient } from '../../api/queryClient';
import { queryKeys } from '../../api/queryKeys';

export function LoginPage() {
  const { t } = useTranslation('auth');
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login(username, password);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session });
      const from = (location.state as { from?: string } | null)?.from ?? '/';
      navigate(from, { replace: true });
    } catch {
      setError(t('login.error'));
    } finally {
      setPending(false);
    }
  }

  return (
    <Center h="100vh">
      <Paper withBorder p="xl" radius="md" w={360}>
        <Stack component="form" onSubmit={submit} gap="md">
          <div>
            <Title order={3}>{t('login.title')}</Title>
            <Text c="dimmed" size="sm">
              {t('login.subtitle')}
            </Text>
          </div>
          {error ? (
            <Text c="red" size="sm" role="alert">
              {error}
            </Text>
          ) : null}
          <TextInput
            label={t('login.username')}
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            autoComplete="username"
            required
          />
          <PasswordInput
            label={t('login.password')}
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            autoComplete="current-password"
            required
          />
          <Button type="submit" loading={pending}>
            {pending ? t('login.submitting') : t('login.submit')}
          </Button>
        </Stack>
      </Paper>
    </Center>
  );
}
```

- [ ] **Step 3: Create `src/app/router.tsx`**

The router is created per `AppRouter` mount (lazy ref), not at module scope: a module-level `createBrowserRouter` would keep its location state across test cases in one file, and each test needs a router initialized from the current `window.location`. The 401 handler is registered in an effect bound to the mounted router.

```tsx
import { useEffect, useRef } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import {
  createBrowserRouter,
  Navigate,
  Outlet,
  RouterProvider,
  useLocation,
} from 'react-router';
import { setUnauthorizedHandler } from '../api/client';
import { queryClient } from '../api/queryClient';
import { useSession } from '../api/hooks';
import { LoadingState } from '../components/StateViews';
import { LoginPage } from '../features/auth/LoginPage';
import {
  DashboardPlaceholder,
  ExportPlaceholder,
  MonitoringPlaceholder,
  PipelinePlaceholder,
  PluginPlaceholder,
  ProductsPlaceholder,
  SetupPlaceholder,
} from '../features/placeholders';
import { AppShell } from './AppShell';

export function RequireSession() {
  const location = useLocation();
  const { status } = useSession();

  if (status === 'pending') return <LoadingState />;
  if (status === 'error') {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }
  return <Outlet />;
}

const routes = [
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireSession />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <DashboardPlaceholder /> },
          { path: 'clients/:clientId/feeds/:feedSourceId/setup', element: <SetupPlaceholder /> },
          { path: 'clients/:clientId/feeds/:feedSourceId/products', element: <ProductsPlaceholder /> },
          { path: 'clients/:clientId/feeds/:feedSourceId/pipeline', element: <PipelinePlaceholder /> },
          { path: 'clients/:clientId/feeds/:feedSourceId/monitoring', element: <MonitoringPlaceholder /> },
          { path: 'clients/:clientId/feeds/:feedSourceId/export', element: <ExportPlaceholder /> },
          { path: 'clients/:clientId/plugins/:pluginId', element: <PluginPlaceholder /> },
          { path: 'plugins/:pluginId', element: <PluginPlaceholder /> },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
];

export function AppRouter() {
  const routerRef = useRef<ReturnType<typeof createBrowserRouter> | null>(null);
  if (routerRef.current === null) {
    routerRef.current = createBrowserRouter(routes);
  }
  const router = routerRef.current;

  useEffect(() => {
    setUnauthorizedHandler(() => {
      const current = router.state.location;
      if (current.pathname !== '/login') {
        void router.navigate('/login', {
          state: { from: current.pathname + current.search },
        });
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [router]);

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
```

This task also creates a minimal `src/app/AppShell.tsx` so the router compiles; Task 7 replaces its body:

```tsx
import { Outlet } from 'react-router';

export function AppShell() {
  return <Outlet />;
}
```

- [ ] **Step 4: Update `src/App.tsx` to render `AppRouter`**

```tsx
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';

import { Suspense } from 'react';
import { Center, Loader, MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { theme } from './app/theme';
import { AppRouter } from './app/router';
import { LocaleProvider } from './i18n/LocaleProvider';

export default function App() {
  return (
    <MantineProvider theme={theme}>
      <Notifications position="top-right" limit={5} />
      <LocaleProvider>
        <Suspense
          fallback={
            <Center h="100vh">
              <Loader />
            </Center>
          }
        >
          <AppRouter />
        </Suspense>
      </LocaleProvider>
    </MantineProvider>
  );
}
```

- [ ] **Step 5: Write the failing test `src/app/router.test.tsx`**

Uses `stubFetch` from Task 2 so `/locales/...` namespace loads are served from disk while API URLs are handled per test:

```tsx
import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { stubFetch } from '../test/fetch';
import App from '../App';
import { queryClient } from '../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const emptySummary = {
  counts: { clients: 0, feed_sources: 0, active_products: 0, failed_last_exports: 0 },
  clients: [],
};

beforeEach(() => {
  queryClient.clear();
  window.history.replaceState({}, '', '/');
});

describe('auth route guard', () => {
  it('redirects unauthenticated users from a protected route to /login', async () => {
    stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ detail: 'Not authenticated' }, 401);
      return jsonResponse({});
    });

    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('renders the dashboard for an authenticated user', async () => {
    stubFetch((url) => {
      if (url === '/auth/me') return jsonResponse({ username: 'operator' });
      if (url === '/dashboard/summary') return jsonResponse(emptySummary);
      if (url === '/plugins') return jsonResponse([]);
      return jsonResponse({});
    });

    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
  });

  it('restores the originally requested route after login', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    let authenticated = false;
    stubFetch((url) => {
      if (url === '/auth/me') {
        return authenticated
          ? jsonResponse({ username: 'operator' })
          : jsonResponse({ detail: 'Not authenticated' }, 401);
      }
      if (url === '/auth/login') {
        authenticated = true;
        return jsonResponse({ username: 'operator' });
      }
      if (url === '/dashboard/summary') return jsonResponse(emptySummary);
      if (url === '/plugins') return jsonResponse([]);
      return jsonResponse({});
    });

    const user = userEvent.setup();
    render(<App />);

    await screen.findByRole('heading', { name: 'Sign in' });
    await user.type(screen.getByLabelText('Username'), 'operator');
    await user.type(screen.getByLabelText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(window.location.pathname).toBe('/clients/1/feeds/2/products');
    });
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `npx vitest run src/app/router.test.tsx`
Expected: FAIL — router/login modules missing.

- [ ] **Step 7: Run test to verify it passes**

Run: `npx vitest run src/app/router.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 8: Run the full gate**

Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/app frontend/src/features frontend/src/App.tsx
git commit -m "feat(m10-b): add router with session guard, minimal login, and placeholder routes"
```

---

### Task 7: AppShell (header, breadcrumb, navbar, user menu, dynamic plugin nav)

**Files:**
- Modify/replace: `frontend/src/app/AppShell.tsx`
- Modify: `frontend/src/api/client.ts` (401-exempt `/auth/password`), `frontend/src/api/client.test.ts` (+1 test), `frontend/src/api/hooks.ts` (`useChangePassword` resets session query)
- Test: `frontend/src/app/AppShell.test.tsx`

**Interfaces:**
- Consumes: `useSession`, `useDashboardSummary`, `usePlugins`, `useLogout`, `useChangePassword` (Task 4); `LanguageSwitcher` (Task 2); notification helpers (Task 5); i18n `common`/`auth` namespaces.
- Produces: the authenticated layout wrapping all area routes (already referenced by the router from Task 6).

Note (Task 4 review follow-up, applied here because Task 4 is already committed): `POST /auth/password` returns 401 on a wrong current password while the session is still valid, and on success the backend revokes the session. Therefore: (1) the centralized 401 handler must also skip `/auth/password`; (2) `useChangePassword` must reset the session query on success so the guard re-checks `/auth/me` and redirects to login. Apply exactly:

`src/api/client.ts` — in `request`, replace the login-only exemption with:

```ts
    const authExempt =
      url.startsWith('/auth/login') || url.startsWith('/auth/password');
    if (response.status === 401 && unauthorizedHandler && !authExempt) {
      unauthorizedHandler();
    }
```

`src/api/client.test.ts` — add `changePassword` to the import list from `'./client'` and append this test:

```ts
  it('does not invoke the handler for a failed password change', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid credentials' }, 401));
    await changePassword('wrong', 'new').catch(() => undefined);
    expect(handler).not.toHaveBeenCalled();
  });
```

`src/api/hooks.ts` — `useChangePassword` resets the session on success (the backend revokes the session on password change, and the guard must re-check `/auth/me`):

```ts
export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ currentPassword, newPassword }: { currentPassword: string; newPassword: string }) =>
      changePassword(currentPassword, newPassword),
    onSuccess: () => {
      void queryClient.resetQueries({ queryKey: queryKeys.session });
    },
  });
}
```

- [ ] **Step 1: Replace `src/app/AppShell.tsx` with the full shell**

```tsx
import { useMemo, useState, type FormEvent } from 'react';
import {
  ActionIcon,
  AppShell as MantineAppShell,
  Burger,
  Button,
  Group,
  Menu,
  Modal,
  NavLink,
  PasswordInput,
  Stack,
  Text,
  Title,
  UnstyledButton,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  IconActivity,
  IconBox,
  IconChevronDown,
  IconDashboard,
  IconFileExport,
  IconGitBranch,
  IconLogout,
  IconMoon,
  IconPuzzle,
  IconSettings,
  IconSun,
  type Icon,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { Link, Outlet, useNavigate, useParams } from 'react-router';
import { useChangePassword, useDashboardSummary, useLogout, usePlugins, useSession } from '../api/hooks';
import { LanguageSwitcher } from '../i18n/LanguageSwitcher';
import { notifyError, notifyMutationError, notifySuccess } from './notifications';

const PLUGIN_ICONS: Record<string, Icon> = {};

function pluginIcon(name: string | undefined) {
  if (name && name in PLUGIN_ICONS) return PLUGIN_ICONS[name];
  return IconPuzzle;
}

function ColorSchemeToggle() {
  const { t } = useTranslation();
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme('light');
  return (
    <ActionIcon
      variant="default"
      aria-label={computed === 'dark' ? t('colorScheme.toLight') : t('colorScheme.toDark')}
      onClick={() => setColorScheme(computed === 'dark' ? 'light' : 'dark')}
    >
      {computed === 'dark' ? <IconSun size={16} /> : <IconMoon size={16} />}
    </ActionIcon>
  );
}

function ChangePasswordModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const { t } = useTranslation('auth');
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [mismatch, setMismatch] = useState(false);
  const mutation = useChangePassword();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (next !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    mutation.mutate(
      { currentPassword: current, newPassword: next },
      {
        onSuccess: () => {
          notifySuccess(t('passwordChange.success'));
          onClose();
        },
        onError: (error) => notifyMutationError(error, t('passwordChange.error')),
      },
    );
  }

  return (
    <Modal opened={opened} onClose={onClose} title={t('passwordChange.title')} centered>
      <Stack component="form" onSubmit={submit} gap="md">
        <PasswordInput
          label={t('passwordChange.current')}
          value={current}
          onChange={(event) => setCurrent(event.currentTarget.value)}
          autoComplete="current-password"
          required
        />
        <PasswordInput
          label={t('passwordChange.next')}
          value={next}
          onChange={(event) => setNext(event.currentTarget.value)}
          autoComplete="new-password"
          required
        />
        <PasswordInput
          label={t('passwordChange.confirm')}
          value={confirm}
          onChange={(event) => setConfirm(event.currentTarget.value)}
          error={mismatch ? t('passwordChange.mismatch') : undefined}
          autoComplete="new-password"
          required
        />
        <Button type="submit" loading={mutation.isPending}>
          {t('passwordChange.submit')}
        </Button>
      </Stack>
    </Modal>
  );
}

function UserMenu() {
  const { t } = useTranslation();
  const { data: user } = useSession();
  const logoutMutation = useLogout();
  const navigate = useNavigate();
  const [passwordOpened, { open: openPassword, close: closePassword }] = useDisclosure(false);

  return (
    <>
      <Menu shadow="md" width={200} position="bottom-end">
        <Menu.Target>
          <UnstyledButton aria-label={user?.username ?? 'user'}>
            <Group gap={4}>
              <Text size="sm">{user?.username}</Text>
              <IconChevronDown size={14} />
            </Group>
          </UnstyledButton>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item leftSection={<IconSettings size={14} />} onClick={openPassword}>
            {t('actions.changePassword')}
          </Menu.Item>
          <Menu.Item
            leftSection={<IconLogout size={14} />}
            onClick={() =>
              logoutMutation.mutate(undefined, { onSuccess: () => navigate('/login') })
            }
          >
            {t('actions.logout')}
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
      <ChangePasswordModal opened={passwordOpened} onClose={closePassword} />
    </>
  );
}

function FeedBreadcrumb() {
  const { t } = useTranslation();
  const { clientId, feedSourceId } = useParams();
  const { data: summary } = useDashboardSummary();

  const client = summary?.clients.find((entry) => String(entry.id) === clientId);
  const feed = client?.feed_sources.find((entry) => String(entry.id) === feedSourceId);

  if (!clientId) return null;

  return (
    <Group gap={4}>
      <Text size="sm" c="dimmed">
        {client?.name ?? t('breadcrumbs.selectClient')}
      </Text>
      <Text size="sm" c="dimmed">
        ›
      </Text>
      <Menu shadow="md" width={220} position="bottom-start">
        <Menu.Target>
          <UnstyledButton aria-label={t('breadcrumbs.selectFeed')}>
            <Group gap={4}>
              <Text size="sm">{feed?.name ?? t('breadcrumbs.selectFeed')}</Text>
              <IconChevronDown size={14} />
            </Group>
          </UnstyledButton>
        </Menu.Target>
        <Menu.Dropdown>
          {(client?.feed_sources ?? []).map((entry) => (
            <Menu.Item
              key={entry.id}
              component={Link}
              to={`/clients/${clientId}/feeds/${entry.id}/setup`}
            >
              {entry.name}
            </Menu.Item>
          ))}
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
}

export function AppShell() {
  const { t } = useTranslation();
  const [opened, { toggle }] = useDisclosure();
  const { clientId, feedSourceId } = useParams();
  const { data: plugins } = usePlugins();

  const feedBase = clientId && feedSourceId ? `/clients/${clientId}/feeds/${feedSourceId}` : null;

  const pluginItems = useMemo(
    () =>
      (plugins ?? []).filter(
        (plugin) => plugin.enabled && plugin.manifest?.frontend?.menu_item,
      ),
    [plugins],
  );

  const feedScoped = [
    { to: feedBase ? `${feedBase}/setup` : null, label: t('nav.setup'), icon: IconSettings },
    { to: feedBase ? `${feedBase}/products` : null, label: t('nav.products'), icon: IconBox },
    { to: feedBase ? `${feedBase}/pipeline` : null, label: t('nav.pipeline'), icon: IconGitBranch },
    { to: feedBase ? `${feedBase}/monitoring` : null, label: t('nav.monitoring'), icon: IconActivity },
    { to: feedBase ? `${feedBase}/export` : null, label: t('nav.export'), icon: IconFileExport },
  ];

  return (
    <MantineAppShell
      padding="md"
      header={{ height: 60 }}
      navbar={{ width: 260, breakpoint: 'sm', collapsed: { mobile: !opened } }}
    >
      <MantineAppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="md" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Title order={4}>{t('appName')}</Title>
            <FeedBreadcrumb />
          </Group>
          <Group gap="sm" wrap="nowrap">
            <LanguageSwitcher />
            <ColorSchemeToggle />
            <UserMenu />
          </Group>
        </Group>
      </MantineAppShell.Header>

      <MantineAppShell.Navbar p="md">
        <Stack gap={4}>
          <NavLink
            component={Link}
            to="/"
            label={t('nav.dashboard')}
            leftSection={<IconDashboard size={16} />}
          />
          {feedScoped.map((item) =>
            item.to ? (
              <NavLink
                key={item.label}
                component={Link}
                to={item.to}
                label={item.label}
                leftSection={<item.icon size={16} />}
              />
            ) : (
              <NavLink
                key={item.label}
                label={item.label}
                leftSection={<item.icon size={16} />}
                disabled
              />
            ),
          )}
          {pluginItems.length > 0 ? (
            <>
              <Text size="xs" c="dimmed" tt="uppercase" mt="md">
                {t('nav.plugins')}
              </Text>
              {pluginItems.map((plugin) => {
                const PluginIcon = pluginIcon(plugin.manifest?.frontend?.icon);
                const scope = plugin.manifest?.frontend;
                const to = clientId
                  ? `/clients/${clientId}/plugins/${plugin.id}`
                  : `/plugins/${plugin.id}`;
                return (
                  <NavLink
                    key={plugin.id}
                    component={Link}
                    to={to}
                    label={scope?.menu_item ?? plugin.name}
                    leftSection={<PluginIcon size={16} />}
                  />
                );
              })}
            </>
          ) : null}
        </Stack>
      </MantineAppShell.Navbar>

      <MantineAppShell.Main>
        <Outlet />
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
```

- [ ] **Step 2: Write the failing test `src/app/AppShell.test.tsx`**

Uses `stubFetch` (locales served from disk, API URLs per handler). The logout test flips `/auth/me` to 401 after `/auth/logout` so the `resetQueries` refetch in `useLogout` drives the guard redirect realistically:

```tsx
import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { stubFetch } from '../test/fetch';
import App from '../App';
import { queryClient } from '../api/queryClient';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const summary = {
  counts: { clients: 1, feed_sources: 1, active_products: 5, failed_last_exports: 0 },
  clients: [
    {
      id: 1,
      name: 'Acme',
      status: 'active',
      feed_sources: [
        {
          id: 2,
          client_id: 1,
          name: 'Main Feed',
          source_format: 'xml',
          item_count: 5,
          last_export_at: null,
          last_export_status: null,
          last_run_at: null,
          last_run_status: null,
        },
      ],
    },
  ],
};

const plugins = [
  {
    id: 'example_upper',
    name: 'Example Upper',
    version: '1.0.0',
    enabled: true,
    manifest: { frontend: { menu_item: 'Example Upper', icon: 'letter-e' } },
    used_by_feed_sources: 0,
  },
  {
    id: 'disabled_plugin',
    name: 'Disabled',
    version: '1.0.0',
    enabled: false,
    manifest: { frontend: { menu_item: 'Hidden' } },
    used_by_feed_sources: 0,
  },
];

function authenticatedHandler(url: string) {
  if (url === '/auth/me') return jsonResponse({ username: 'operator' });
  if (url === '/dashboard/summary') return jsonResponse(summary);
  if (url === '/plugins') return jsonResponse(plugins);
  return jsonResponse({});
}

beforeEach(() => {
  queryClient.clear();
  window.history.replaceState({}, '', '/');
  stubFetch(authenticatedHandler);
});

describe('AppShell', () => {
  it('renders the fixed navigation and only enabled plugin menu items', async () => {
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.getByText('Setup')).toBeInTheDocument();
    expect(screen.getByText('Products')).toBeInTheDocument();
    expect(screen.getByText('Pipeline Editor')).toBeInTheDocument();
    expect(screen.getByText('Monitoring')).toBeInTheDocument();
    expect(screen.getByText('Export')).toBeInTheDocument();
    expect(await screen.findByText('Example Upper')).toBeInTheDocument();
    expect(screen.queryByText('Hidden')).not.toBeInTheDocument();
  });

  it('disables feed-scoped nav items until a feed source is selected', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: 'Dashboard' });
    expect(screen.getByText('Setup').closest('a,button')).toBeDisabled();
  });

  it('shows the client and feed breadcrumb on a feed route', async () => {
    window.history.replaceState({}, '', '/clients/1/feeds/2/products');
    render(<App />);
    expect(await screen.findByText('Acme')).toBeInTheDocument();
    expect(await screen.findByText('Main Feed')).toBeInTheDocument();
  });

  it('logs out and returns to the login page', async () => {
    let loggedIn = true;
    stubFetch((url) => {
      if (url === '/auth/me') {
        return loggedIn
          ? jsonResponse({ username: 'operator' })
          : jsonResponse({ detail: 'Not authenticated' }, 401);
      }
      if (url === '/auth/logout') {
        loggedIn = false;
        return jsonResponse({ status: 'ok' });
      }
      if (url === '/dashboard/summary') return jsonResponse(summary);
      if (url === '/plugins') return jsonResponse(plugins);
      return jsonResponse({});
    });
    const user = userEvent.setup();
    render(<App />);

    await screen.findByRole('heading', { name: 'Dashboard' });
    await user.click(screen.getByRole('button', { name: 'operator' }));
    await user.click(await screen.findByText('Log out'));

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npx vitest run src/app/AppShell.test.tsx`
Expected: FAIL — the Task 6 stub AppShell renders no nav.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/app/AppShell.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full gate**

Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/AppShell.tsx frontend/src/app/AppShell.test.tsx \
  frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/api/hooks.ts
git commit -m "feat(m10-b): add AppShell with header, breadcrumb, user menu, and dynamic plugin nav"
```

---

### Task 8: JsonSchemaForm (schema-rendered form)

**Files:**
- Create: `frontend/src/components/JsonSchemaForm.tsx`
- Test: `frontend/src/components/JsonSchemaForm.test.tsx`

**Interfaces:**
- Consumes: `render` (Task 1), i18n `common` namespace (Task 2).
- Produces: `JsonSchemaForm` — Mantine-themed renderer over a JSON Schema, used by M10-d plugin auto-UI and Pipeline Editor instance config. Supports `string`→TextInput, `number`/`integer`→NumberInput, `boolean`→Switch, `enum`→Select, `object`→nested Stack, `array`→add/remove list.

- [ ] **Step 1: Create `src/components/JsonSchemaForm.tsx`**

```tsx
import {
  ActionIcon,
  Button,
  Group,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

export type JsonSchema = {
  type?: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array';
  title?: string;
  description?: string;
  enum?: string[];
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
  required?: string[];
};

export type JsonSchemaFormProps = {
  schema: JsonSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  errors?: Record<string, string>;
  path?: string;
};

function joinPath(path: string | undefined, key: string): string {
  return path ? `${path}.${key}` : key;
}

export function JsonSchemaForm({ schema, value, onChange, errors = {}, path }: JsonSchemaFormProps) {
  const { t } = useTranslation();
  const error = path ? errors[path] : undefined;
  const label = schema.title ?? path?.split('.').pop();

  if (schema.type === 'object') {
    const record = (value ?? {}) as Record<string, unknown>;
    return (
      <Stack gap="sm">
        {Object.entries(schema.properties ?? {}).map(([key, propertySchema]) => (
          <JsonSchemaForm
            key={key}
            schema={propertySchema}
            value={record[key]}
            onChange={(next) => onChange({ ...record, [key]: next })}
            errors={errors}
            path={joinPath(path, key)}
          />
        ))}
      </Stack>
    );
  }

  if (schema.type === 'array') {
    const items = Array.isArray(value) ? value : [];
    return (
      <Stack gap="xs">
        {label ? <Text size="sm">{label}</Text> : null}
        {items.map((item, index) => (
          <Group key={index} gap="xs" wrap="nowrap" align="flex-start">
            <div style={{ flex: 1 }}>
              <JsonSchemaForm
                schema={schema.items ?? {}}
                value={item}
                onChange={(next) =>
                  onChange(items.map((existing, i) => (i === index ? next : existing)))
                }
                errors={errors}
                path={joinPath(path, String(index))}
              />
            </div>
            <ActionIcon
              variant="subtle"
              color="red"
              aria-label={t('actions.remove')}
              onClick={() => onChange(items.filter((_, i) => i !== index))}
            >
              <IconTrash size={16} />
            </ActionIcon>
          </Group>
        ))}
        <Button
          variant="light"
          size="xs"
          leftSection={<IconPlus size={14} />}
          onClick={() => onChange([...items, undefined])}
        >
          {t('actions.add')}
        </Button>
      </Stack>
    );
  }

  if (schema.enum) {
    return (
      <Select
        label={label}
        description={schema.description}
        data={schema.enum}
        value={(value as string | undefined) ?? null}
        onChange={(next) => onChange(next)}
        error={error}
      />
    );
  }

  switch (schema.type) {
    case 'number':
    case 'integer':
      return (
        <NumberInput
          label={label}
          description={schema.description}
          value={typeof value === 'number' ? value : ''}
          onChange={(next) => onChange(next === '' ? undefined : Number(next))}
          error={error}
        />
      );
    case 'boolean':
      return (
        <Switch
          label={label}
          description={schema.description}
          checked={value === true}
          onChange={(event) => onChange(event.currentTarget.checked)}
          error={error}
        />
      );
    default:
      return (
        <TextInput
          label={label}
          description={schema.description}
          value={(value as string | undefined) ?? ''}
          onChange={(event) => onChange(event.currentTarget.value)}
          error={error}
        />
      );
  }
}
```

- [ ] **Step 2: Write the failing test `src/components/JsonSchemaForm.test.tsx`**

```tsx
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../test/render';
import { JsonSchemaForm, type JsonSchema } from './JsonSchemaForm';

const schema: JsonSchema = {
  type: 'object',
  properties: {
    suffix: { type: 'string', title: 'Suffix' },
    retries: { type: 'integer', title: 'Retries' },
    enabled: { type: 'boolean', title: 'Enabled' },
    mode: { type: 'string', title: 'Mode', enum: ['strict', 'lenient'] },
    tags: { type: 'array', title: 'Tags', items: { type: 'string' } },
  },
};

describe('JsonSchemaForm', () => {
  it('renders one control per schema type', () => {
    render(
      <JsonSchemaForm schema={schema} value={{}} onChange={() => undefined} />,
    );
    expect(screen.getByLabelText('Suffix')).toBeInTheDocument();
    expect(screen.getByLabelText('Retries')).toBeInTheDocument();
    expect(screen.getByLabelText('Enabled')).toBeInTheDocument();
    expect(screen.getByLabelText('Mode')).toBeInTheDocument();
    expect(screen.getByText('Tags')).toBeInTheDocument();
  });

  it('emits changed values through onChange', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<JsonSchemaForm schema={schema} value={{}} onChange={onChange} />);

    await user.type(screen.getByLabelText('Suffix'), '_UP');
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ suffix: '_UP' }));
  });

  it('adds and removes array items', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <JsonSchemaForm schema={schema} value={{ tags: ['a'] }} onChange={onChange} />,
    );

    expect(screen.getByDisplayValue('a')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ tags: ['a', undefined] }));

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ tags: [] }));
  });

  it('shows per-field validation errors by path', () => {
    render(
      <JsonSchemaForm
        schema={schema}
        value={{}}
        onChange={() => undefined}
        errors={{ suffix: 'required' }}
      />,
    );
    expect(screen.getByLabelText('Suffix')).toHaveAttribute('aria-invalid', 'true');
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npx vitest run src/components/JsonSchemaForm.test.tsx`
Expected: FAIL — component missing.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/JsonSchemaForm.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full gate**

Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/JsonSchemaForm.tsx frontend/src/components/JsonSchemaForm.test.tsx
git commit -m "feat(m10-b): add JsonSchemaForm schema-rendered form component"
```

---

### Task 9: Vite dev proxy extension + decisions + final gate

**Files:**
- Modify: `frontend/vite.config.ts`
- Modify: `docs/decisions.md`
- Test: none new (gate only)

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: a working dev proxy for all API prefixes and the recorded M10-b decisions; green final gate.

- [ ] **Step 1: Extend the dev proxy in `vite.config.ts`**

In the existing `server.proxy` object, keep `/auth` and `/health` and add the remaining API prefixes, each with the same shape:

```ts
      proxy: {
        '/auth': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/health': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/clients': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/feed-sources': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/dashboard': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/plugins': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/registry': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/export': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
```

- [ ] **Step 2: Record decisions in `docs/decisions.md`**

Append under a new `## 2026-08-28` heading if not present (M10-a already added one — extend it), using the existing `### Title` + `**Topic/Decision/Rationale**` bullet format:

1. `### M10 frontend primary color` — Topic: M10 theme. Decision: Mantine default theme with `primaryColor: 'blue'`; dark/light toggle persisted via Mantine color-scheme storage; text wordmark placeholder logo. Rationale: m10-frontend-instructions §4 requires one recorded primary-color choice; design §2.6.
2. `### M10-b frontend dependency pins` — Topic: frontend foundation dependencies. Decision: pinned exactly (list each package@version resolved in Task 1, one line each: `@mantine/core@9.5.2`, `@mantine/hooks@9.5.2`, `@mantine/notifications@9.5.2`, `@mantine/dates@9.5.2`, `@tabler/icons-react@<resolved>`, `@tanstack/react-query@<resolved>`, `@tanstack/react-table@<resolved>`, `@tanstack/react-form@<resolved>`, `@dnd-kit/core@<resolved>`, `@dnd-kit/sortable@<resolved>`, `react-router@7.18.2`, `i18next@<resolved>`, `react-i18next@<resolved>`, `i18next-browser-languagedetector@<resolved>`, `i18next-http-backend@<resolved>`, `dayjs@<resolved>`, plus dev `postcss@<resolved>`, `postcss-preset-mantine@<resolved>`, `postcss-simple-vars@<resolved>`). Rationale: design §2.1 pins Mantine at 9.5.2 and requires every new pin recorded; versions resolved against current docs 2026-08-28.
3. `### React Router v7 for M10 routing` — Topic: routing library major version. Decision: use `react-router@7.18.2` (data router, `createBrowserRouter`) rather than the newer v8 line. Rationale: design §2.3 specifies React Router v7; keeps the milestone on the reviewed spec.

- [ ] **Step 3: Run the full gate**

Run: `npm test -- --run && npm run typecheck && npm run build`
Expected: all green. Report exact test count.

- [ ] **Step 4: Verify the production build serves lazy locales**

Run: `ls dist/locales/en dist/locales/de`
Expected: 11 JSON files per language copied as static assets (not bundled into JS).

- [ ] **Step 5: Commit**

```bash
git add frontend/vite.config.ts docs/decisions.md
git commit -m "chore(m10-b): extend dev proxy to all API prefixes and record M10-b decisions"
```

---

## Self-Review Notes

- **Spec coverage (design §2):** §2.1 deps/pins → Task 1 + Task 9 decisions; §2.2 source layout → File Structure (all tasks); §2.3 routing + RequireSession guard + redirect-to-origin → Task 6; §2.4 AppShell (wordmark, breadcrumb Client>Feed, language switcher, dark/light, user menu w/ password change + logout, navbar with disabled feed-scoped items + dynamic plugin section) → Task 7; §2.5 query keys + polling + notifications → Tasks 4, 5; §2.6 theme + i18n → Tasks 1, 2. Shared components incl. JsonSchemaForm → Tasks 3, 8. Vite proxy extension → Task 9.
- **DoD minimum tests (design §5) covered in M10-b:** auth route guards (Task 6), schema-form rendering (Task 8), notification on mutation failure (Task 5). Column-config persistence, diff-view rendering, and pipeline dirty tracking belong to M10-c/d areas and are out of scope here.
- **Deviations to flag for review:** (1) minimal Mantine login is built in M10-b although §6 lists Login under M10-c — required so the §2.3 guard can restore the original route after a real login; M10-c polishes it. (2) `ExportUrlBlock` (design §2.2) is deferred to M10-d Export area since it needs export-token endpoints not consumed by the foundation.
- **Review-driven amendment (Task 4 review, Important):** the centralized 401 handler also exempts `/auth/password` (backend returns 401 on wrong current password with a still-valid session), and `useChangePassword` resets the session query on success (backend revokes the session). The deltas are folded into Task 7 (applied after Task 4's already-committed state) with one new client test; final-state code in Task 4 reflects them.
- **Review-driven note (Task 4, Minor):** old `src/api.ts#recordInteraction` (idle keepalive button) is intentionally not carried over; nothing in M10-b/c/d references it. Backend sessions hard-expire `session_idle_minutes` after login (all routes renew_idle=False) — flagged to M10-c/d planning.
- **Test-harness note:** i18n loads namespaces through a custom backend `request` function using global `fetch`; `src/test/setup.ts` installs a default locale-serving `fetch` stub and awaits `initPromise` before all tests, and `src/test/fetch.ts#stubFetch` layers locale serving under per-test API mocks. This keeps `i18n-agent-instructions.md`'s "no static locale imports" rule intact in tests.
- **Type consistency:** `JsonSchema`/`JsonSchemaFormProps` (Task 8), `DashboardSummary`/`PluginInfo` (Task 4), `queryKeys` (Task 4) are the single definitions referenced by later tasks and by M10-c/d.
