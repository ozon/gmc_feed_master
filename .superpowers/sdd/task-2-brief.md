### Task 2: Manifest parsing + validation

**Files:**
- Create: `backend/app/plugins/__init__.py`
- Create: `backend/app/plugins/manifest.py`
- Test: `backend/tests/test_plugins_manifest.py`

**Interfaces:**
- Produces:

```python
_ID_RE: re.Pattern                      # ^[a-z][a-z0-9_]*$
_ALLOWED_SCOPES: frozenset[str]         # {"global","client","feed_source"}
class ManifestError(Exception): ...     # .reason: str
@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    extension_point: str
    config_schema: dict[str, Any]
    data_schema: dict[str, Any]
    config_scope: tuple[str, ...]
    data_scope: tuple[str, ...]
    raw: dict[str, Any]                 # original manifest document
def parse_manifest(data: Any) -> PluginManifest   # raises ManifestError
```

Tasks 3+ consume exactly these names.

Validation rules (each violation → `ManifestError` with a specific reason string):
- document must be a JSON object
- required keys present: `id, name, version, extension_point, config_schema, data_schema`
- `id` matches `_ID_RE`; `name`/`version` non-empty strings
- `extension_point == "pipeline_module"` (anything else rejected for MVP)
- `config_schema`/`data_schema` are dicts AND valid against the JSON-Schema 2020-12 meta-schema (`jsonschema.Draft202012Validator.check_schema`, catching `jsonschema.SchemaError`)
- `config_scope`/`data_scope`: missing → defaults `(global,)`; a bare string → 1-tuple; a list/tuple → every element in `_ALLOWED_SCOPES`, at least one element

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_plugins_manifest.py` covering, at minimum: valid minimal manifest round-trips (defaults applied); each failure reason above (missing keys, bad id `"Bad-Id"`, wrong extension point `"quality_rule"`, non-dict schema, schema invalid against meta-schema (`{"type": "nope"}`), undeclared scope value, empty scope list, string→tuple normalization); `raw` preserves the input document.

- [ ] **Step 2: RED** — `cd backend && uv run pytest tests/test_plugins_manifest.py -q` fails on import.

- [ ] **Step 3: Implement** `backend/app/plugins/manifest.py` exactly per the interface above (empty `__init__.py` package marker alongside).

- [ ] **Step 4: GREEN** — same command passes.

- [ ] **Step 5: Commit** — `feat: plugin manifest parsing and validation`

---

