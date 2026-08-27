### Task 6: Plugin API endpoints

**Files:**
- Create: `backend/app/routes/plugins.py`
- Create: `backend/app/schemas/plugins.py`
- Modify: `backend/app/routes/__init__.py` (export `plugins_router`), `backend/app/main.py` (`include_router(plugins_router)` + import)
- Test: `backend/tests/test_plugins_api.py`

**Interfaces:**
- Consumes: models `Plugin`, `PluginConfig`, `PluginData`, `Client`, `FeedSource`; `require_user`; `get_db_session`; `jsonschema`.
- Produces: `plugins_router` with:

| Route | Semantics |
|---|---|
| `GET /plugins` | ALL rows → `[{"id": <name column>, "name": manifest["name"], "version", "enabled", "manifest"}]` |
| `PUT /plugins/{plugin_id}/enabled` | Body `{"enabled": bool}`; 404 unknown; persists |
| `GET /plugins/{plugin_id}/config` | Query `client_id: int | None`, `feed_source_id: int | None`; returns stored flat payload for that scope or `{}` |
| `PUT /plugins/{plugin_id}/config` | Full replace after validation; 200 → `{"status": "ok"}` |
| `GET/PUT /plugins/{plugin_id}/data` | Same against `data_schema` |

Shared resolution helper (in the router module):

```python
async def _resolve_target(
    plugin_id: str,
    client_id: int | None,
    feed_source_id: int | None,
    db_session: AsyncSession,
    scope_kind: str,                     # "config_scope" | "data_scope"
) -> tuple[Plugin, str, int | None, int | None]:
```

Validation order (each its own status code):
1. `_require_db` → 503 when no session (existing pattern).
2. Plugin row by `name == plugin_id` → 404.
3. Both scope params present → 422 `{"errors": ["pass at most one of client_id, feed_source_id"]}` (JSONResponse, matching §8's error shape).
4. Requested scope must be in the manifest's declared `config_scope`/`data_scope` respectively → else 422 `{"errors": ["scope not declared for this plugin"]}`. Global (no params) is always allowed.
5. Ownership existence: `client_id` → `session.get(Client, ...)` else 404; same for feed source.

Storage convention (realizes M5's flat one-payload-per-scope decision on the keyed tables): host reads/writes exactly one row per (plugin, scope-owner) using `key = "default"`. GET: fetch row(s) for that owner, return first payload or `{}`. PUT: delete existing rows for that (plugin_id, scope, owner) then insert one with the validated payload — inside one transaction.

Payload validation: `jsonschema.validate(payload, schema)` catches `jsonschema.ValidationError` and `jsonschema.SchemaError` → 422 `{"errors": [<message>]}`.

Schemas file:

```python
class EnabledPut(BaseModel):
    enabled: bool
```

Auth: every route takes `_user: str = Depends(require_user)` and `db_session: AsyncSession | None = Depends(get_db_session)`.

**Tests** (mirror `test_field_mapping_api.py` patterns: engine from `isolated_database_url`, `create_app(settings=..., session_store=InMemorySessionStore..., db_session_factory=factory)`, login via `/auth/login`): list-all incl. disabled; toggle round-trip + 404; config PUT/GET per scope incl. global default `{}`; undeclared-scope 422; both-scopes 422; unknown client/feed-source 404; schema-violation PUT → 422 with `errors` key; data endpoints mirror one happy path + violation.

TDD; commit `feat: plugin management API endpoints`.

---

