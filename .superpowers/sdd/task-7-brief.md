### Task 7: Contract checker + dummy fixture

**Files:**
- Create: `backend/app/plugins/contract.py`
- Create: `backend/tests/fixtures/example_plugin/plugin.json`
- Create: `backend/tests/fixtures/example_plugin/plugin.py`
- Create: `backend/tests/test_plugin_contract.py`

**Interfaces:**
- Consumes: `Candidate`, `discover`, `jsonschema`.
- Produces: `def contract_violations(candidate: Candidate) -> list[str]` — pure function returning human-readable violations (empty list = pass).

Checks implemented:
1. Meta-schema validity of `manifest.config_schema`/`data_schema` (`Draft202012Validator.check_schema`).
2. `process()` honors dict|None: call with `product={"id": "contract-check"}, config={}, data={}, ctx=None-tolerant` — build a real minimal `RunContext(client_id=0, feed_source_id=0, run_id=0, logger=logging.getLogger("contract"), original_product={...copy})`; any exception that is NOT a deliberate schema rejection counts as a violation unless it's raised for missing required config (plugins may require config to operate — treat `Exception` mentioning required keys as acceptable? NO: deterministic rule — if `validate_config({})` raises, skip the process-call checks 2–4 with reason "" (they are config-gated); otherwise they must pass).
3. `original_product` unmutated: deep-compare before/after the `process()` call.
4. `validate_config()` rejects missing required properties: for each name in `config_schema.get("required", [])`, assert `validate_config(payload_without_that_name)` raises.
5. Reserved sub-paths: inspect candidate router (via `collect_router`) — any path `/config…` or `/data…` is a violation.

Fixture `plugin.json`:

```json
{
  "id": "example_upper",
  "name": "Example Upper",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "entry_point": "example:UpperPlugin",
  "config_scope": ["global", "client"],
  "data_scope": [],
  "config_schema": {
    "type": "object",
    "properties": {"suffix": {"type": "string"}},
    "required": ["suffix"]
  },
  "data_schema": {"type": "object"}
}
```

Note `"data_scope": []` exercises the empty-declaration edge (all data access then 422s). Fixture `plugin.py`:

```python
class UpperPlugin:
    def validate_config(self, config):
        if not isinstance(config, dict) or "suffix" not in config:
            raise ValueError("suffix is required")

    def process(self, product, config, data, ctx):
        title = product.get("title")
        if product.get("id") == "drop-me":
            return None
        if isinstance(title, str):
            product["title"] = title.upper()
        product["title_suffix"] = config["suffix"]
        return product
```

Test wrapper `test_plugin_contract.py`: discover over `tests/fixtures` (a directory containing only `example_plugin` at top level — copy the fixture dir into `tmp_path` first so `discover()` sees exactly one candidate), assert `contract_violations(candidate) == []`; plus negative tests: mutate a copy of the fixture manifest to break each check (bad meta-schema, process returning `"str"`, mutating original_product, non-raising validate_config despite required, reserved-route contribution) and assert exactly one targeted violation.

TDD; commit `feat: plugin contract checker and example fixture`.

---

