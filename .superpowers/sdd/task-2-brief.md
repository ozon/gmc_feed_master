### Task 2: Three-tier scope merge (pure function)

**Files:**
- Create: `backend/app/staging/config_resolver.py`
- Test: `backend/tests/test_config_merge.py`

**Interfaces:**
- Consumes: nothing yet (pure).
- Produces: `merge_scopes(global_payload: dict, client_payload: dict | None, feed_source_payload: dict | None) -> dict` implementing spec §5.3 (per key: dicts merge recursively, everything else replaces wholesale). Task 3 builds on it — do not rename.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_config_merge.py`:

```python
from app.staging.config_resolver import merge_scopes


class TestMergeScopes:
    def test_global_only(self):
        assert merge_scopes({"a": 1}, None, None) == {"a": 1}

    def test_client_overrides_global_per_key(self):
        assert merge_scopes({"a": 1, "b": 2}, {"b": 3}, None) == {"a": 1, "b": 3}

    def test_feed_source_wins(self):
        merged = merge_scopes({"a": 1, "b": 2, "c": 3}, {"c": 30}, {"a": 10})
        assert merged == {"a": 10, "b": 2, "c": 30}

    def test_non_dict_values_replace_wholesale(self):
        assert merge_scopes({"rules": [1, 2, 3]}, {"rules": [9]}, None) == {"rules": [9]}

    def test_dict_values_merge_recursively(self):
        merged = merge_scopes(
            {"limits": {"title": 150, "desc": 5000}},
            {"limits": {"title": 100}},
            None,
        )
        assert merged == {"limits": {"title": 100, "desc": 5000}}

    def test_missing_at_specific_scope_falls_through(self):
        assert merge_scopes({"a": 1}, {}, {"b": 2}) == {"a": 1, "b": 2}

    def test_type_flip_replaces(self):
        assert merge_scopes({"a": {"nested": 1}}, {"a": "flat"}, None) == {"a": "flat"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.staging.config_resolver'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/staging/config_resolver.py`:

```python
from __future__ import annotations

from typing import Any


def _merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_scopes(
    global_payload: dict[str, Any],
    client_payload: dict[str, Any] | None,
    feed_source_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = dict(global_payload)
    if client_payload is not None:
        resolved = _merge_dicts(resolved, client_payload)
    if feed_source_payload is not None:
        resolved = _merge_dicts(resolved, feed_source_payload)
    return resolved
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_merge.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/staging/config_resolver.py tests/test_config_merge.py
git commit -m "feat: three-tier scope merge per spec 5.3"
```

---

