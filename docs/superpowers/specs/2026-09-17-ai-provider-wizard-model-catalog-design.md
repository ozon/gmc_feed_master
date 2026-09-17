# GFM-12: AI Provider Wizard + Model Catalog — Design

Date: 2026-09-17
Status: Approved in brainstorming (operator)
Baseline: main at `1502e75`
Issue: GFM-12 — 3-step provider wizard for major providers, backed by a refreshable model catalog.
Builds on: `2026-09-11-ai-provider-abstraction-design.md` (Feature 1) and the Z1 roadmap (`2026-09-12-ai-restarbeiten-design.md`).

## Purpose

Creating an AI provider under Admin > AI Provider currently requires knowing `provider_type` (`litellm` vs. legacy `openai_compatible`), the LiteLLM model format (`vendor/model`), `base_url`, and advanced fields (`tier`, `max_concurrency`, `timeout_s`, prices). That distinction is internal (router mapping in `backend/app/ai/router.py::_litellm_model`) and not visible to the user.

GFM-12 replaces the raw form with a 3-step wizard (provider → API key → model) for major providers, with advanced options collapsed, driven by a model catalog that can be refreshed from an upstream source.

## Decisions (operator sign-off)

| # | Decision | Choice |
|---|---|---|
| 1 | Catalog source | Seed/read from the installed `litellm.model_cost` (offline, version-matched); scheduled refresh pulls the LiteLLM GitHub raw JSON over `httpx`; refresh failure keeps the last-good catalog |
| 2 | Key validation | No stateless test endpoint; test is deferred and runs on wizard Finish via the existing `POST /admin/ai/providers/{id}/test` |
| 3 | Finish behavior | Create provider → immediately auto-test → show ok/fail inline in the modal → close |
| 4 | Azure | Deferred to a follow-up cycle; no `api_version` column, no Azure preset this cycle |
| 5 | Recommended models | Static curated list per vendor, matched against the catalog at read time |
| 6 | Refresh schedule | Fixed daily system job + manual trigger; no configurable interval / settings field |
| 7 | Signal storage | Catalog rows hold models only; sync freshness/error in a one-row state table; `is_recommended` computed at read |
| 8 | Seed timing | Lazy seed-on-first-GET (bundled), not startup seeding |

Preset set: **OpenAI, Anthropic, Google Gemini, OpenRouter, Mistral, Groq**, plus **"OpenAI-kompatibel (custom)"** as the escape hatch for vLLM/Ollama/LM Studio.

## Backend

### `app/ai/presets.py`

```python
@dataclass(frozen=True)
class ProviderPreset:
    vendor_key: str            # "openai" | "anthropic" | "google" | "openrouter" | "mistral" | "groq" | "custom"
    label: str
    model_prefix: str          # LiteLLM vendor prefix ("gemini" for google, "openai" for custom)
    default_base_url: str      # "" when the LiteLLM default endpoint applies
    requires_base_url: bool    # True only for custom
    api_key_env_hint: str
    docs_url: str              # "create API key" docs page
    supports_catalog: bool     # False only for custom
```

`PROVIDER_PRESETS` exports the seven presets; `get_preset(vendor_key)` looks one up. `custom` is last (escape hatch).

`normalize_provider_input(model, provider_type) -> tuple[str, str]` — server-side write normalization: return `("litellm", model)` when the model already contains `/`; when `provider_type == "openai_compatible"` and the model has no prefix, return `("litellm", f"openai/{model}")`; otherwise `("litellm", model)`. After this, `provider_type` is only ever `litellm` at rest. Legacy read path is untouched.

### `app/ai/model_catalog.py`

- `LITELLM_CATALOG_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/litellm/model_prices_and_context_window.json"`.
- `SUPPORTED_VENDORS = {"openai": "openai", "anthropic": "anthropic", "gemini": "google", "openrouter": "openrouter", "mistral": "mistral", "groq": "groq"}` (LiteLLM `litellm_provider` → preset `vendor_key`).
- `parse_catalog(raw: dict) -> list[CatalogEntry]`:
  - keep entries whose `litellm_provider` is supported and whose `mode` is `None`, `"chat"` or `"completion"`; drop `deprecated`;
  - canonical `model_id` = key as-is when it contains `/`, else `f"{litellm_provider}/{key}"` (verified: `model_cost` keys are mostly bare, e.g. `gpt-4o`, while `mistral/mistral-large-latest` and `openrouter/anthropic/...` are already prefixed);
  - `vendor` = preset key from the map; `display_name` = trailing segment of `model_id`;
  - prices per Mtok = `input_cost_per_token × 1e6` / `output_cost_per_token × 1e6` (nullable);
  - `context_window` = `max_input_tokens` (fallback `max_tokens`), `max_output_tokens` = `max_output_tokens` (fallback `max_tokens`); both nullable;
  - `supports_vision` / `supports_function_calling` as booleans;
  - stored `mode` = `entry.get("mode") or "chat"` (a large share of entries omit `mode`; LiteLLM treats those as chat);
  - dedup by `model_id`.
- `load_bundled() -> list[CatalogEntry]` from `litellm.model_cost` (same value shape, no network).
- `ensure_seeded(session)` — no-op unless `ai_model_catalog` is empty; when empty, insert the bundled set and stamp sync state `source="bundled", last_success_at=now`. Called by the catalog GET handler before querying and by the refresh handler before attempting the fetch; never at startup (keeps test-app boot cheap).
- `refresh(session_factory, http_client, now) -> CatalogSyncState` — record `last_attempt_at`; fetch the URL (30 s timeout); `parse_catalog`; **guard**: fewer than 50 parsed entries ⇒ raise (format-change detection); parse fully before touching the DB, then delete-all + bulk insert + stamp `source="github", last_success_at=now, last_error=None` in one transaction. On any exception: log, store `last_error`, keep existing rows, return the state (fail-open, never raises to the caller).
- `get_entries(session, vendor, mode) -> list[CatalogEntry]` and `get_sync_state(session)` for the API layer.
- `RECOMMENDED_MODELS: dict[str, set[str]]` — static `vendor_key → {model_id}` map, e.g. `openai → {"openai/gpt-4o", "openai/gpt-4o-mini"}`, `anthropic → {"anthropic/claude-3-5-sonnet-20241022"}`, `google → {"gemini/gemini-1.5-pro"}`. `is_recommended` is computed as membership at read time.

### Data model (one Alembic revision)

`ai_model_catalog`

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| vendor | String(50) | preset `vendor_key` |
| model_id | String(255), unique | LiteLLM model string (`vendor/model`) |
| display_name | String(255) | |
| mode | String(20) | `chat` \| `completion` |
| context_window | Integer, nullable | |
| max_output_tokens | Integer, nullable | |
| input_price_per_mtok | Numeric(12,6), nullable | |
| output_price_per_mtok | Numeric(12,6), nullable | |
| supports_vision | Boolean, not null, default false | |
| supports_function_calling | Boolean, not null, default false | |

Index on `(vendor, mode)`.

`ai_model_catalog_sync` (singleton, `id = 1`)

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | always 1 |
| last_attempt_at | DateTime(tz), nullable | |
| last_success_at | DateTime(tz), nullable | badge: "aktualisiert vor X Tagen" |
| last_error | Text, nullable | badge warning on failed refresh |
| source | String(50), nullable | `bundled` \| `github` |

Dropped from the ticket's column list: per-row `last_synced_at`, per-row `source`, stored `is_recommended` — all derivable and otherwise able to drift.

### Routes (`backend/app/routes/ai_admin.py`)

- `GET /admin/ai/provider-presets` → `list[ProviderPresetOut]` (step 1 cards).
- `GET /admin/ai/model-catalog?vendor=&mode=chat` → `{entries: list[ModelCatalogEntryOut], sync: ModelCatalogSyncOut}`; each entry carries `is_recommended`; calls `ensure_seeded` first. `mode` defaults to `chat`.
- `POST /admin/ai/model-catalog/refresh` → runs `refresh` and returns the sync state.
- `create_provider` / `update_provider` run `normalize_provider_input` before persisting.
- No new `AiProviderCreate`/`Update` fields; `provider_type` stays in the input schema for back-compat but is always normalized to `litellm`.

Schemas added to `backend/app/schemas/ai_admin.py`: `ProviderPresetOut`, `ModelCatalogEntryOut`, `ModelCatalogSyncOut`.

### Router (`backend/app/ai/router.py`)

Unchanged. `_litellm_model` already returns any model containing `/` verbatim, so normalized new rows and legacy `openai_compatible` rows both work; `test_ai_router.py` stays green (`test_deployment_for_legacy_openai_compatible_row`, `test_deployment_does_not_double_prefix_already_prefixed_model`).

### Schedule (`backend/app/main.py`)

Register a fixed daily system job `system-ai-model-catalog-refresh` at `0 4 * * *` via the existing `scheduler_service.register_system_job(...)` pattern (peer to the AI purge job). The job calls `refresh` with the app's HTTP client. Manual trigger: the refresh endpoint above. No settings field, no `GlobalSetting` change.

## Frontend

### Wizard (`frontend/src/features/admin/ai/ProvidersPage.tsx`)

Keep the provider table; add a **Legacy** badge for rows with `provider_type === "openai_compatible"`. Replace `ProviderModal` with a Mantine `Stepper` wizard:

1. **Anbieter** — preset cards from `useProviderPresets()` (label, short description, "API-Key erstellen" docs link).
2. **API-Key** — password field (`api_key`). `base_url` shown and required only for `custom`.
3. **Modell** — searchable select from `useModelCatalog(vendor)`, sortable by price or context window, vision/function-calling badges, recommended entry preselected. For `custom`: a free-text `model` field, no catalog call.

Below the flow, a collapsed Mantine `Accordion` — **Erweiterte Optionen**: `tier` (default `bulk`), `max_concurrency`, `timeout_s`, `input_price_per_mtok`/`output_price_per_mtok` (prefilled from the selected catalog entry, overridable), `enabled`. The ticket's "must not be touched for the standard case" is satisfied: collapsed and prefilled.

`name` is auto-suggested as `"{preset label} {model display name}"`, editable. **Finish** = create (`provider_type` never sent explicitly by the wizard; the server normalizes anyway), then call `useTestAiProvider` on the new id and show ok/fail inline before closing.

Catalog status line above the table / in step 3: last success timestamp + Refresh button; `sync.last_error` renders as a warning badge ("Katalog Refresh fehlgeschlagen"). Rendering is plain timestamps formatted client-side (`react-i18next` relative or the existing date helper).

Editing a legacy or existing row opens the wizard with a best-effort preset mapping: `provider_type === "openai_compatible"` → `custom`; otherwise infer from the model prefix (`anthropic/`→anthropic, `gemini/`→google, `openrouter/`→openrouter, `mistral/`→mistral, `groq/`→groq, else openai). `api_key` stays empty and is only sent when the admin types a new value, preserving the write-only behavior.

### API surface client (`frontend/src/api/`)

- `types.ts`: `ProviderPreset`, `ModelCatalogEntry`, `ModelCatalogSync`, and a small preset classification helper.
- `hooks.ts`: `useProviderPresets`, `useModelCatalog(vendor, mode?)`, `useRefreshModelCatalog` (invalidates the catalog query on success).
- i18n keys under the `admin` namespace, en + de.

## Error handling

| Failure | Behavior |
|---|---|
| Catalog refresh network/format failure | Job/endpoint logs, records `last_error`, keeps existing rows, returns 200 with the failed sync state |
| Catalog never synced and bundled load fails | Empty catalog; `custom` preset still usable; wizard surfaces the sync error |
| Catalog GET with empty table | Lazy bundled seed runs first, so the combobox is usable offline |
| Provider create with legacy `openai_compatible` payload | Server normalizes to `litellm` + `openai/<model>`; no 422 |
| Auto-test after create fails | Provider stays created; inline error shown; user can retry from the table |

## Testing

Backend (`backend/tests/`):
- `test_ai_model_catalog.py` — parse canonicalizes bare and prefixed keys, filters `mode`/vendor/deprecated, converts per-token → per-Mtok; `refresh` success upserts and stamps `source="github"`; refresh failure (mock transport error / malformed payload) keeps rows and records `last_error`; format guard rejects `<50` entries; `ensure_seeded` only inserts when empty; recommended membership computed at read.
- `test_ai_admin_api.py` — presets endpoint shape; catalog GET (seeded, vendor/mode filter, recommended flag, sync payload); refresh POST; provider create normalizes `openai_compatible` → `litellm`/`openai/<model>`.
- `test_ai_router.py` — unchanged, must stay green.
- `uv run alembic check` — no pending model drift.

Frontend (`frontend/src/features/admin/ai/*.test.tsx`):
- Wizard renders 3 steps; preset cards select and advance; recommended model preselected; advanced accordion collapsed by default and prices stay prefilled/overridable; `custom` requires `base_url` and shows a free-text model field; Finish flow calls create then test; legacy row opens the wizard on `custom` with fields prefilled; catalog error badge renders.

## Docs (same commit)

- `backend/docs/data-model.md` — two new tables; provider `provider_type` normalized to `litellm` on write; `openai_compatible` marked read-only legacy.
- `backend/docs/api.md` — 3 new endpoints; provider create/update normalization.
- `backend/docs/architecture.md` — model-catalog module + scheduled refresh, catalog never blocks provider use.
- `docs/decisions.md` — dated entry: bundled-seed + GitHub refresh w/ fail-open, Azure deferred, lazy seed-on-GET, static recommended list, fixed daily cron, `is_recommended` computed at read.
- `frontend/docs/architecture.md` — wizard + catalog hooks.

## Acceptance criteria mapping

- Manual + automatic refresh, fail-open → `refresh` is fail-open by construction; fixed daily system job + `POST .../refresh`; tests pin the failure path.
- 3-click provider for OpenAI/Anthropic/Google/OpenRouter/Mistral/Groq without knowing `provider_type` or the LiteLLM format → presets endpoint + wizard steps 1–3; server-side normalization removes the format requirement.
- Advanced options collapsed by default → `Accordion` closed; prefilled from the selected catalog entry.
- Custom preset covers self-hosted (vLLM/Ollama/LM Studio) → `custom` = free model + required `base_url`, no catalog.
- Existing configs keep working → router unchanged; `test_ai_router.py` regression suite green.
- `api_key` stays write-only → unchanged create/update contract; wizard sends it only when typed.

## Out of scope

- Azure OpenAI preset and `api_version` plumbing (deferred per decision 4).
- Configurable refresh interval / settings UI (fixed daily cron this cycle).
- Per-request stateless provider test endpoint (Finish uses the existing id-based test).
- Catalog-driven model recommendations via heuristics; provider logos; per-task provider overrides.
- Encryption of `api_key` at rest (separate, explicitly-scoped task per backend AGENTS.md).
