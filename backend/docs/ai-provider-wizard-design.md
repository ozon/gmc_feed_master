# AI Provider Configuration 2.0 — Design Doc

Tracking ticket: itsaplan **GFM-12** — "AI Provider Configuration 2.0: Preset-Wizard + Model-Katalog"

## Problem

Today, adding an AI provider under Admin > AI Provider requires the operator to
know `provider_type` (`litellm` vs. legacy `openai_compatible`), the LiteLLM
`vendor/model` naming scheme, and to manually fill `base_url` plus several
advanced fields. See `backend/docs/data-model.md` and
`frontend/src/features/admin/ai/ProvidersPage.tsx`.

## Goal

`Anbieter auswaehlen -> API-Key hinterlegen -> Modell auswaehlen`, with a
collapsed "Erweiterte Optionen" section for `tier`, `max_concurrency`,
`timeout_s`, and pricing overrides. Backed by a model catalog that is kept
current via a scheduled refresh from an external source.

## New building blocks introduced on this branch

| File | Purpose |
|---|---|
| `backend/app/ai/presets.py` | Static `PROVIDER_PRESETS` list (OpenAI, Anthropic, Gemini, Azure OpenAI, Mistral, Groq, custom OpenAI-compatible). |
| `backend/app/ai/model_catalog.py` | Fetches `model_prices_and_context_window.json` from the LiteLLM repo, normalizes to `vendor/model` rows, upserts into `ai_model_catalog`, fail-open on refresh errors. |
| `backend/app/models/ai_model_catalog.py` | ORM model for the new table. |
| `backend/app/schemas/model_catalog.py` | Pydantic response schemas for the new endpoints. |
| `backend/app/db/migrations/versions/a1b2c3d4e5f6_add_ai_model_catalog.py` | Alembic migration for `ai_model_catalog` (down_revision placeholder — see file header). |
| `frontend/src/features/admin/ai/ProviderWizard.tsx` | Standalone 3-step Mantine `Stepper` wizard component (preset -> key -> model), with a collapsed advanced-options `Accordion`. |
| `frontend/src/api/modelCatalog.ts` | React Query hooks for `GET /admin/ai/model-catalog` and preset listing. |

## Still to be wired (follow-up PRs / commits on this branch)

This branch adds new, additive modules only. It does **not** yet modify:

1. `backend/app/schemas/ai_admin.py` — extend `AiProviderCreate`/`AiProviderOut`
   with optional `azure_deployment_name` / `azure_api_version`, and normalize
   `provider_type="openai_compatible"` to `litellm` + `openai/<model>` on write
   (keep `openai_compatible` readable for existing rows only).
2. `backend/app/routes/ai_admin.py` — add:
   - `GET /admin/ai/providers/presets` (serializes `PROVIDER_PRESETS`)
   - `GET /admin/ai/model-catalog?vendor=&mode=`
   - `POST /admin/ai/model-catalog/refresh`
   - `GET /admin/ai/model-catalog/status`
3. `frontend/src/features/admin/ai/ProvidersPage.tsx` — replace the existing
   type/model text fields with `<ProviderWizard />` for the create flow; keep
   the table + edit modal, add a "Legacy" badge for `provider_type ===
   "openai_compatible"` rows.
4. Scheduled job registration for `refresh_model_catalog` (reuse the pattern
   in `backend/app/ai/purge.py`).
5. Alembic `down_revision` must be set to the actual current head before
   merging (see migration file header) — this could not be resolved from the
   GitHub API alone.

## Acceptance criteria (from GFM-12)

- [ ] Model catalog refresh works both manually and on schedule; a failed
      refresh never breaks existing functionality.
- [ ] OpenAI / Anthropic / Gemini / Azure OpenAI providers configurable in 3
      clicks without knowing `provider_type` or the LiteLLM model format.
- [ ] Advanced options collapsed by default.
- [ ] Custom OpenAI-compatible endpoints (vLLM/Ollama/LM Studio) still
      supported via the "custom" preset.
- [ ] Existing provider rows keep working unmodified (`test_ai_router.py`
      stays green).
- [ ] `api_key` remains write-only/redacted.
