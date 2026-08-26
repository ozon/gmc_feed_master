### Task 1: Canonical hashing module

**Files:**
- Create: `backend/app/staging/__init__.py`
- Create: `backend/app/staging/hashing.py`
- Test: `backend/tests/test_staging_hashing.py`

**Interfaces:**
- Consumes: stdlib only.
- Produces: `strip_derived(value: Any) -> Any`, `canonical_json(value: Any) -> str`, `content_hash(value: dict[str, Any]) -> str` (SHA-256 hexdigest). All later tasks import from `app.staging.hashing`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_staging_hashing.py`:

```python
from app.staging.hashing import canonical_json, content_hash, strip_derived


class TestStripDerived:
    def test_removes_top_level_underscore_keys(self):
        assert strip_derived({"id": "1", "_prov": "x"}) == {"id": "1"}

    def test_removes_nested_and_inside_lists(self):
        value = {
            "shipping": [{"country": "US", "_i": "x"}, {"country": "DE"}],
            "meta": {"keep": 1, "_drop": 2},
        }
        assert strip_derived(value) == {
            "shipping": [{"country": "US"}, {"country": "DE"}],
            "meta": {"keep": 1},
        }

    def test_leaves_scalars_untouched(self):
        assert strip_derived("x") == "x"
        assert strip_derived(42) == 42
        assert strip_derived(None) is None


class TestCanonicalJson:
    def test_key_order_independent(self):
        assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})

    def test_nested_keys_sorted(self):
        assert canonical_json({"o": {"y": 1, "x": 2}}) == canonical_json({"o": {"x": 2, "y": 1}})

    def test_unicode_preserved_and_compact(self):
        assert canonical_json({"t": "schön"}) == '{"t":"schön"}'


class TestContentHash:
    def test_is_sha256_hexdigest(self):
        digest = content_hash({"id": "1"})
        assert len(digest) == 64
        int(digest, 16)

    def test_sidecars_do_not_change_hash(self):
        plain = {"id": "1", "title": "Shirt"}
        decorated = {**plain, "_category_provenance": "auto"}
        assert content_hash(plain) == content_hash(decorated)

    def test_content_change_changes_hash(self):
        assert content_hash({"title": "a"}) != content_hash({"title": "b"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_staging_hashing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.staging'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/staging/__init__.py` (empty file, package marker only).

Create `backend/app/staging/hashing.py`:

```python
from __future__ import annotations

import hashlib
import json
from typing import Any


def strip_derived(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_derived(item)
            for key, item in value.items()
            if not (isinstance(key, str) and key.startswith("_"))
        }
    if isinstance(value, list):
        return [strip_derived(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        strip_derived(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def content_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_staging_hashing.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add app/staging tests/test_staging_hashing.py
git commit -m "feat: canonical product hashing with derived-key stripping"
```

---

