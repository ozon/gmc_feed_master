# i18n Implementation Instructions (react-i18next)

## Context

- Project stack: React 19, Mantine, TypeScript, bundled with Vite as a client-side SPA.
- Goal: Add full internationalization (i18n) support using **react-i18next**. The initial languages are English (`en`, fallback) and German (`de`). The architecture must allow adding more locales later without refactoring.
- These instructions describe WHAT to build and WHY. Do not hardcode anything locale-specific beyond the supported-language list.

## Required dependencies

- `i18next` — core i18n framework
- `react-i18next` — React bindings (`useTranslation`, `Trans`, `initReactI18next`)
- `i18next-browser-languagedetector` — automatic language detection and persistence
- `i18next-http-backend` — runtime (lazy) loading of translation files over HTTP

Day.js is already present via `@mantine/dates`; do not add a second date library.

## Initialization requirements

1. Create a single dedicated i18n initialization module and import it exactly once, at the top of the application entry file, before any component renders.
2. Configure i18next with the following behavior:
   - `fallbackLng` set to `en`.
   - An explicit allowlist of supported languages (`en`, `de`) so detection cannot resolve to unsupported locales.
   - Language detection via `i18next-browser-languagedetector`: check (in order) query string, then `localStorage`, then browser navigator settings; cache the resolved language in `localStorage`.
   - React integration via `initReactI18next` with interpolation escaping disabled (React already escapes output).
   - Suspense mode enabled (the default) so components wait for their namespaces.
3. Wrap the application root (or the lazily translated parts of the route tree) in a React `Suspense` boundary that renders a Mantine `Loader`/`Center` fallback while namespaces load.

## Namespaces and lazy loading (critical)

Translations MUST be split into namespaces and loaded on demand, not bundled into JavaScript.

1. Organize translation files as static JSON assets served from the public directory, using the layout `public/locales/<language>/<namespace>.json` (for example `public/locales/de/common.json`).
2. Define one namespace per domain or feature area. Start with at least: `common` (shared UI labels, navigation, actions) plus one namespace per major feature/route (e.g. `auth`, `dashboard`, `settings`).
3. Configure `i18next-http-backend` with a load path pattern matching the folder layout above, so each namespace JSON is fetched over HTTP only when a component first declares it.
4. Set `common` as the default namespace. Every other namespace must be declared explicitly by the component that needs it, via the namespace argument of `useTranslation` (a component may declare several namespaces).
5. Only the `common` namespace is loaded eagerly at startup (via `ns` preload). Feature namespaces must load lazily when their components mount — never import translation JSON files statically into the bundle.
6. Keep each namespace file small and cohesive; when a namespace grows beyond one feature, split it rather than letting it become a catch-all.
7. Verify in the browser network tab that navigating to a feature triggers exactly the requests for that feature's namespace files, and nothing more.

## Mantine integration

1. Create a small effect (at app shell level) that runs whenever the active i18next language changes and performs all of the following:
   - Calls `dayjs.locale(...)` with the active language, after statically importing the required dayjs locale modules (`dayjs/locale/de`, etc.) once.
   - Passes the active language to the Mantine `DatesProvider` `settings.locale` prop, with `firstDayOfWeek: 1` (Monday) for German and locale-appropriate values otherwise.
   - Sets `document.documentElement.lang` to the active language (important for accessibility and SEO).
2. Any user-facing Mantine component text (placeholders, labels, pagination text, notifications) must come from `t(...)` calls, never from string literals in JSX.
3. Provide a language switcher in the app header or settings area using a Mantine `SegmentedControl` or `Select`, wired to `i18n.changeLanguage(...)`.

## Type safety

1. Enable TypeScript strict typing for translation keys: augment the i18next type declarations (declaration merging in a dedicated `i18next.d.ts`) based on the English (`en`) resources so that `t()` keys and namespace names are compile-time checked and autocompleted.
2. Adding a key to the `en` files must be the single source of truth; other locales follow the same key structure.

## Message format rules (best practices)

1. Keys are semantic, lowercase, dot-separated identifiers scoped to their namespace (e.g. `dashboard.title`, `auth.login.button`) — never use raw English sentences as keys.
2. Translate whole sentences, never sentence fragments. Never concatenate translated strings to build sentences; word order differs across languages.
3. Use interpolation for all dynamic values (`{name}`, `{count}`) instead of string concatenation or template literals around translations.
4. Use i18next plural forms via the `count` option (suffix convention `_one` / `_other` for German and English). Never implement manual singular/plural branching.
5. Use the `Trans` component for strings that contain markup (bold text, links); keep element tags inside translations generic and indexed.
6. For numbers, currencies, percentages, and dates outside Mantine components, use the native `Intl` APIs (`Intl.NumberFormat`, `Intl.DateTimeFormat`) parameterized with the active i18next language — do not hardcode locale strings and do not format such values by hand.

## Constraints — do NOT

- Do not hardcode any user-facing string in components; everything visible goes through `t()` or `Trans`.
- Do not statically import locale JSON into application code (this defeats lazy loading), except for TypeScript type generation of the `en` resources if needed.
- Do not construct translation keys dynamically from runtime data (breaks type checking and extraction); if unavoidable, keep a fixed whitelist of keys.
- Do not lazy-load the `common` namespace behind a route; it must be available before first paint.
- Do not add ICU MessageFormat plugins for this iteration; stick to the built-in i18next format.
- Do not implement RTL support, server-side rendering concerns, or a translation-management-platform integration — out of scope.

## Procedure: adding a new language later

The implementation must make this a four-step change: (1) create `public/locales/<lng>/` with all namespace files, (2) add the language to the supported-languages allowlist, (3) add the matching dayjs locale import if `@mantine/dates` is used in that language, (4) add an entry to the language switcher. No other code changes should be necessary.

## Acceptance criteria

- Switching the language updates all UI text, the Mantine `DatesProvider` locale, and the `<html lang>` attribute immediately, without a page reload.
- The selected language persists across reloads via `localStorage`; on first visit the browser language is used if supported, otherwise English.
- Network requests show namespace JSON files loading on demand per feature; the production bundle contains no translation JSON.
- Missing keys fall back to English and are logged in development mode only.
- TypeScript compilation passes with fully typed `t()` usage; no `any` casts around translation calls.
- Production build succeeds and works with lazy-loaded namespaces (verify the built app, not only dev mode).
