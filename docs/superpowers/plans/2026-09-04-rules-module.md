# Rules Module (Core Plugin `rules`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** First core pipeline module `rules` — row-based, drag-ordered transformation rules with a low-code IF/THEN editor, stored in `plugin_configs` JSONB via the plugin system.

**Architecture:** `plugins/core/rules/` package (manifest + Python engine + optional custom frontend component). Rules are an ordered JSON array in plugin config; the engine evaluates `when` (AST) and applies `then` actions per product at the plugin's pipeline position. UI renders via PluginPage custom-component wiring. No DB migrations.

**Tech Stack:** Python 3.10+ (stdlib only, no new deps), FastAPI plugin runtime, React 19 + Mantine 8 + dnd-kit, TanStack Query, i18next (en/de), vitest + pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-rules-module-design.md`

## Global Constraints

- Plugin id: `rules`; must match `^[a-z][a-z0-9_]*$` (manifest.py `_ID_RE`).
- Core plugins live in `plugins/core/<id>/` — `discover()` marks `core=True` → auto-enabled at registration (`backend/app/plugins/discovery.py:41,115`).
- `process(product, config, data, ctx)` must NOT mutate `ctx.original_product`; returns product dict (dict copy semantics per `example_upper`).
- No reserved routes: plugin router paths must not start with `/config` or `/data`.
- `validate_config({})` must NOT raise for contract test's config gate (`contract.py:92`) — engine-level strict validation happens on real configs.
- No new dependencies (backend `pyproject.toml`, frontend `package.json`).
- Field access: top-level keys of the current product dict only in MVP (dotted reads documented as follow-up).
- Backend commands run from `backend/`: `uv run pytest -n auto`, `uv run ruff check .`, `uv run mypy .`
- Frontend commands run from `frontend/`: `npm run test`, `npm run typecheck`, `npm run build`
- Locales: `en` and `de` JSON files in `frontend/public/locales/<lng>/rules.json` (NOTE: repo has en/de, not en/ru — `SUPPORTED_LANGUAGES = ['en', 'de']` in `frontend/src/i18n/index.ts:6`).
- Conventional Commits style messages (see `git log`): `feat:`, `fix:`, `test:`, `docs:`.
- All user-visible strings through i18n namespace `rules`.

---

### Task 1: Rules engine — condition evaluation

**Files:**
- Create: `plugins/core/rules/__init__.py` (empty)
- Create: `plugins/core/rules/plugin.py`
- Test: `backend/tests/test_rules_conditions.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces: `evaluate_condition(node: dict, product: dict) -> bool` in `plugins/core/rules/plugin.py` (used by Task 2's `RulesPlugin.process`); condition ops: `equals, contains, starts_with, ends_with, regex, exists, empty, gt, lt, gte, lte, between`; group ops `and`, `or`; `all` matches everything. `caseSensitive` defaults to `True` for text ops.

- [ ] **Step 1: Write failing tests for condition evaluation**

Create `backend/tests/test_rules_conditions.py`:

```python
"""Condition-AST evaluation tests for the rules core plugin."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/core/rules"))
from plugin import evaluate_condition  # noqa: E402


def test_all_matches_everything():
    assert evaluate_condition({"op": "all"}, {"id": "1"}) is True
    assert evaluate_condition({"op": "all"}, {}) is True


def test_equals_default_case_sensitive():
    node = {"op": "equals", "field": "title", "arg": "Hello"}
    assert evaluate_condition(node, {"title": "Hello"}) is True
    assert evaluate_condition(node, {"title": "hello"}) is False


def test_equals_case_insensitive():
    node = {"op": "equals", "field": "title", "arg": "hello", "caseSensitive": False}
    assert evaluate_condition(node, {"title": "HeLLo"}) is True


def test_contains():
    node = {"op": "contains", "field": "description", "arg": "<p>"}
    assert evaluate_condition(node, {"description": "a <p> b"}) is True
    assert evaluate_condition(node, {"description": "a b"}) is False


def test_contains_case_insensitive():
    node = {"op": "contains", "field": "title", "arg": "sale", "caseSensitive": False}
    assert evaluate_condition(node, {"title": "Big SALE today"}) is True


def test_starts_with_and_ends_with():
    assert evaluate_condition({"op": "starts_with", "field": "id", "arg": "SKU"}, {"id": "SKU-1"}) is True
    assert evaluate_condition({"op": "ends_with", "field": "id", "arg": "-1"}, {"id": "SKU-1"}) is True
    assert evaluate_condition({"op": "starts_with", "field": "id", "arg": "sku", "caseSensitive": False}, {"id": "SKU-1"}) is True


def test_regex_match():
    node = {"op": "regex", "field": "link", "arg": r"^https?://"}
    assert evaluate_condition(node, {"link": "https://x.y"}) is True
    assert evaluate_condition(node, {"link": "ftp://x.y"}) is False


def test_invalid_regex_raises_condition_error():
    from plugin import ConditionError

    with pytest.raises(ConditionError):
        evaluate_condition({"op": "regex", "field": "link", "arg": "("}, {"link": "x"})


def test_exists_and_empty():
    assert evaluate_condition({"op": "exists", "field": "title"}, {"title": "x"}) is True
    assert evaluate_condition({"op": "exists", "field": "title"}, {"title": None}) is False
    assert evaluate_condition({"op": "exists", "field": "title"}, {}) is False
    assert evaluate_condition({"op": "empty", "field": "title"}, {}) is True
    assert evaluate_condition({"op": "empty", "field": "title"}, {"title": ""}) is True
    assert evaluate_condition({"op": "empty", "field": "title"}, {"title": None}) is True
    assert evaluate_condition({"op": "empty", "field": "title"}, {"title": "x"}) is False


def test_numeric_comparisons():
    assert evaluate_condition({"op": "gt", "field": "price", "arg": 10}, {"price": 10.5}) is True
    assert evaluate_condition({"op": "gt", "field": "price", "arg": 10}, {"price": 10}) is False
    assert evaluate_condition({"op": "gte", "field": "price", "arg": 10}, {"price": 10}) is True
    assert evaluate_condition({"op": "lt", "field": "price", "arg": 10}, {"price": 9}) is True
    assert evaluate_condition({"op": "lte", "field": "price", "arg": 10}, {"price": 10}) is True
    assert evaluate_condition({"op": "between", "field": "price", "arg": 5, "arg2": 10}, {"price": 7}) is True
    assert evaluate_condition({"op": "between", "field": "price", "arg": 5, "arg2": 10}, {"price": 5}) is True
    assert evaluate_condition({"op": "between", "field": "price", "arg": 5, "arg2": 10}, {"price": 11}) is False


def test_numeric_on_non_numeric_value_is_false():
    assert evaluate_condition({"op": "gt", "field": "price", "arg": 10}, {"price": "cheap"}) is False
    assert evaluate_condition({"op": "between", "field": "price", "arg": 1, "arg2": 2}, {}) is False


def test_numeric_on_string_digits_coerces():
    assert evaluate_condition({"op": "gt", "field": "price", "arg": 10}, {"price": "15"}) is True


def test_and_or_groups():
    cond = {
        "op": "and",
        "children": [
            {"op": "equals", "field": "brand", "arg": "Acme"},
            {"op": "gt", "field": "price", "arg": 5},
        ],
    }
    assert evaluate_condition(cond, {"brand": "Acme", "price": 7}) is True
    assert evaluate_condition(cond, {"brand": "Acme", "price": 3}) is False
    either = {
        "op": "or",
        "children": [
            {"op": "equals", "field": "brand", "arg": "Acme"},
            {"op": "equals", "field": "brand", "arg": "Globex"},
        ],
    }
    assert evaluate_condition(either, {"brand": "Globex"}) is True
    assert evaluate_condition(either, {"brand": "Initech"}) is False


def test_text_ops_coerce_non_string_values():
    node = {"op": "contains", "field": "price", "arg": "9"}
    assert evaluate_condition(node, {"price": 19.99}) is True
    assert evaluate_condition(node, {"price": 20.0}) is False


def test_unknown_op_raises():
    from plugin import ConditionError

    with pytest.raises(ConditionError):
        evaluate_condition({"op": "nope", "field": "x"}, {"x": "1"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `uv run pytest tests/test_rules_conditions.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'plugin'` (file doesn't exist).

- [ ] **Step 3: Implement condition evaluation in plugin.py**

Create `plugins/core/rules/plugin.py`:

```python
"""Rules core plugin — row-based data transformation rules."""

from __future__ import annotations

import re
from typing import Any


class ConditionError(ValueError):
    """Invalid condition node (unknown op, bad regex, malformed args)."""


def _field_value(product: dict[str, Any], field: str) -> Any:
    return product.get(field)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _compile(arg: Any) -> re.Pattern[str]:
    try:
        return re.compile(str(arg))
    except re.error as exc:
        raise ConditionError(f"invalid regex {arg!r}: {exc}") from exc


def _compare_texts(actual: str, expected: str, case_sensitive: bool) -> tuple[str, str]:
    if case_sensitive:
        return actual, expected
    return actual.lower(), expected.lower()


def evaluate_condition(node: dict[str, Any], product: dict[str, Any]) -> bool:
    """Evaluate an IF-AST node against a product. Raises ConditionError on bad shape."""
    if not isinstance(node, dict):
        raise ConditionError("condition node must be an object")
    op = node.get("op")

    if op == "all":
        return True
    if op in ("and", "or"):
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise ConditionError(f"{op} requires a non-empty children list")
        results = (evaluate_condition(child, product) for child in children)
        return all(results) if op == "and" else any(results)

    if op is None:
        raise ConditionError("condition node is missing op")

    field = node.get("field")
    if not isinstance(field, str) or not field:
        raise ConditionError(f"condition op {op!r} requires a non-empty field")
    value = _field_value(product, field)

    if op == "exists":
        return value is not None
    if op == "empty":
        return value is None or (isinstance(value, str) and value == "")

    if op in ("equals", "contains", "starts_with", "ends_with"):
        arg = node.get("arg")
        if arg is None:
            raise ConditionError(f"condition op {op!r} requires arg")
        case_sensitive = node.get("caseSensitive", True)
        actual, expected = _compare_texts(_as_text(value), _as_text(arg), case_sensitive)
        if op == "equals":
            return actual == expected
        if op == "contains":
            return expected in actual
        if op == "starts_with":
            return actual.startswith(expected)
        return actual.endswith(expected)

    if op == "regex":
        arg = node.get("arg")
        if arg is None:
            raise ConditionError("condition op 'regex' requires arg")
        pattern = _compile(arg)
        return pattern.search(_as_text(value)) is not None

    if op in ("gt", "lt", "gte", "lte", "between"):
        number = _as_number(value)
        arg = _as_number(node.get("arg"))
        if number is None or arg is None:
            return False
        if op == "gt":
            return number > arg
        if op == "lt":
            return number < arg
        if op == "gte":
            return number >= arg
        if op == "lte":
            return number <= arg
        arg2 = _as_number(node.get("arg2"))
        if arg2 is None:
            raise ConditionError("condition op 'between' requires arg2")
        return arg <= number <= arg2

    raise ConditionError(f"unknown condition op {op!r}")
```

Create empty `plugins/core/rules/__init__.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rules_conditions.py -q`
Expected: PASS (all 15 tests).

- [ ] **Step 5: Lint and typecheck**

Run: `uv run ruff check ../plugins/core/rules/plugin.py` and `uv run mypy ../plugins/core/rules/plugin.py`
Note: if mypy's config excludes `../plugins`, verify inclusion; if excluded, run `npx tsc --noEmit`-equivalent check is N/A — instead ensure `mypy .` still passes from backend/ and skip external-path mypy. If mypy errors on path config, document and run `uv run mypy app` for regression instead.
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add ../plugins/core/rules/__init__.py ../plugins/core/rules/plugin.py tests/test_rules_conditions.py
git commit -m "feat(rules): condition-AST evaluation engine"
```

---

### Task 2: Rules engine — actions and RulesPlugin.process

**Files:**
- Modify: `plugins/core/rules/plugin.py` (append action code)
- Test: `backend/tests/test_rules_plugin.py`

**Interfaces:**
- Consumes: `evaluate_condition`, `ConditionError` from Task 1.
- Produces:
  - `apply_action(product: dict, action: dict) -> dict` (returns mutated copy-on-write product)
  - `class RulesPlugin` with `validate_config(config: dict) -> None` and `process(product: dict, config: dict, data: dict, ctx) -> dict | None`
  - Action ops: `set, replace, append, prepend, remove, clear`. `replace` uses `find` + `with`; a `find` value starting with `/` (e.g. `/<p>.*?</p>/`) is regex mode with `$1` capture groups.
  - Config shape: `{"rules": [{id, name, isMasterRule, isActive, when, then}]}`. `validate_config({})` must pass (empty config = no rules). Validation errors are `ValueError` subclasses.

- [ ] **Step 1: Write failing tests for actions + process + validate_config**

Create `backend/tests/test_rules_plugin.py`:

```python
"""RulesPlugin behaviour tests (actions, ordering, contract compliance)."""

import copy
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/core/rules"))
from plugin import RulesPlugin, apply_action, validate_config  # noqa: E402


def _ctx():
    class _Ctx:
        client_id = 0
        feed_source_id = 0
        run_id = 0
        logger = logging.getLogger("test")

    return _Ctx()


def test_set_action():
    assert apply_action({"condition": "old"}, {"op": "set", "field": "condition", "value": "new"})
    == {"condition": "new"}


def test_set_action_fix():
    result = apply_action({"condition": "old"}, {"op": "set", "field": "condition", "value": "new"})
    assert result == {"condition": "new"}


def test_replace_substring():
    result = apply_action(
        {"title": "Hello <b>World</b>"},
        {"op": "replace", "field": "title", "find": "<b>", "with": ""},
    )
    assert result == {"title": "Hello World"}


def test_replace_case_sensitive_flag():
    result = apply_action(
        {"title": "Big SALE"},
        {"op": "replace", "field": "title", "find": "sale", "with": "Deal", "caseSensitive": False},
    )
    assert result == {"title": "Big Deal"}


def test_replace_regex_with_capture_group():
    result = apply_action(
        {"title": "Item 123 - Blue"},
        {"op": "replace", "field": "title", "find": r"/Item (\d+)/", "with": "SKU-$1"},
    )
    assert result == {"title": "SKU-123 - Blue"}


def test_append_and_prepend_coerce():
    assert apply_action({"title": "A"}, {"op": "append", "field": "title", "value": 5})["title"] == "A5"
    assert apply_action({"title": "A"}, {"op": "prepend", "field": "title", "value": "x"})["title"] == "xA"


def test_remove_and_clear():
    assert apply_action({"a": 1, "b": 2}, {"op": "remove", "field": "a"}) == {"b": 2}
    assert apply_action({"a": "text"}, {"op": "clear", "field": "a"}) == {"a": ""}


def test_apply_action_returns_new_dict():
    original = {"title": "A"}
    result = apply_action(original, {"op": "set", "field": "title", "value": "B"})
    assert result is not original
    assert original["title"] == "A"


def test_unknown_action_op_raises():
    with pytest.raises(ValueError):
        apply_action({}, {"op": "explode", "field": "x"})


def test_process_applies_rules_in_order():
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": False, "isActive": True,
             "when": {"op": "all"},
             "then": [{"op": "set", "field": "title", "value": "mid"}]},
            {"id": "r2", "name": "n", "isMasterRule": False, "isActive": True,
             "when": {"op": "all"},
             "then": [{"op": "append", "field": "title", "value": "!"}]},
        ]
    }
    out = RulesPlugin().process({"title": "start"}, config, {}, _ctx())
    assert out == {"title": "mid!"}


def test_process_skips_inactive_rules():
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": False, "isActive": False,
             "when": {"op": "all"},
             "then": [{"op": "set", "field": "title", "value": "x"}]},
        ]
    }
    out = RulesPlugin().process({"title": "orig"}, config, {}, _ctx())
    assert out == {"title": "orig"}


def test_process_ignores_master_flag():
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": True, "isActive": True,
             "when": {"op": "all"},
             "then": [{"op": "set", "field": "title", "value": "master-was-here"}]},
        ]
    }
    out = RulesPlugin().process({"title": "orig"}, config, {}, _ctx())
    assert out == {"title": "master-was-here"}  # flag is UI-only; rule still runs


def test_process_respects_when_condition():
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": False, "isActive": True,
             "when": {"op": "equals", "field": "brand", "arg": "Acme"},
             "then": [{"op": "set", "field": "title", "value": "acme-item"}]},
        ]
    }
    out = RulesPlugin().process({"brand": "Acme", "title": "x"}, config, {}, _ctx())
    assert out["title"] == "acme-item"
    out = RulesPlugin().process({"brand": "Other", "title": "x"}, config, {}, _ctx())
    assert out["title"] == "x"


def test_process_empty_then_is_noop():
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": False, "isActive": True,
             "when": {"op": "all"}, "then": []},
        ]
    }
    out = RulesPlugin().process({"title": "x"}, config, {}, _ctx())
    assert out == {"title": "x"}


def test_process_does_not_mutate_original_product():
    class Ctx:
        client_id = feed_source_id = run_id = 0
        logger = logging.getLogger("test")

    product = {"title": "x"}
    Ctx.original_product = copy.deepcopy(product)
    config = {
        "rules": [
            {"id": "r1", "name": "n", "isMasterRule": False, "isActive": True,
             "when": {"op": "all"},
             "then": [{"op": "set", "field": "title", "value": "changed"}]},
        ]
    }
    RulesPlugin().process(product, config, {}, Ctx())
    assert Ctx.original_product == {"title": "x"}


def test_validate_config_accepts_empty():
    validate_config({})
    validate_config({"rules": []})


def test_validate_config_rejects_bad_shapes():
    with pytest.raises(ValueError):
        validate_config({"rules": "nope"})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"no_id": True}]})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"id": "r", "name": "n", "when": {"op": "all"}, "then": [
            {"op": "set", "field": "f"}  # missing value
        ]}]})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"id": "r", "name": "n", "when": {"op": "nope"}, "then": []}]})
    with pytest.raises(ValueError):
        validate_config({"rules": [{"id": "r", "name": "n", "when": {"op": "and", "children": []}, "then": []}]})


def test_validate_config_accepts_valid_document():
    validate_config({
        "rules": [{
            "id": "r1", "name": "ok", "isMasterRule": True, "isActive": True,
            "when": {"op": "and", "children": [{"op": "empty", "field": "title"}]},
            "then": [{"op": "set", "field": "title", "value": "x"}],
        }]
    })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_rules_plugin.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'apply_action'`.

- [ ] **Step 3: Implement actions, validate_config, RulesPlugin**

Append to `plugins/core/rules/plugin.py`:

```python
# ---------------------------------------------------------------------------
# THEN actions
# ---------------------------------------------------------------------------

_TEXT_FIND_OPS = {"replace"}


class ActionError(ValueError):
    """Invalid action node."""


def _regex_replace(text: str, find: str, with_value: str, case_sensitive: bool) -> str:
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(find[1:], flags)
    return pattern.sub(with_value.replace("\\", "\\\\"), text)
```

(Then the full implementation; see complete file content in Step 3 continued below.)

Complete appended block:

```python
class ActionError(ValueError):
    """Invalid action node."""


_ACTION_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "set": ("field", "value"),
    "replace": ("field", "find", "with"),
    "append": ("field", "value"),
    "prepend": ("field", "value"),
    "remove": ("field",),
    "clear": ("field",),
}


def _apply_replace(text: str, action: dict[str, Any]) -> str:
    find = str(action["find"])
    with_value = str(action["with"])
    case_sensitive = action.get("caseSensitive", True)
    if find.startswith("/"):
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            return re.sub(find[1:], with_value, text, flags=flags)
        except re.error as exc:
            raise ActionError(f"invalid regex find {find!r}: {exc}") from exc
    if case_sensitive:
        return text.replace(find, with_value)
    return re.sub(re.escape(find), with_value, text, flags=re.IGNORECASE)


def apply_action(product: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """Apply one THEN action; returns a NEW product dict (copy-on-write)."""
    if not isinstance(action, dict):
        raise ActionError("action node must be an object")
    op = action.get("op")
    if op not in _ACTION_REQUIRED_KEYS:
        raise ActionError(f"unknown action op {op!r}")
    field = action.get("field")
    if not isinstance(field, str) or not field:
        raise ActionError(f"action op {op!r} requires a non-empty field")

    next_product: dict[str, Any] = dict(product)

    if op == "set":
        next_product[field] = action.get("value")
    elif op in ("append", "prepend"):
        value = action.get("value")
        current = next_product.get(field)
        text = "" if current is None else str(current)
        addition = "" if value is None else str(value)
        next_product[field] = addition + text if op == "prepend" else text + addition
    elif op == "replace":
        current = next_product.get(field)
        text = "" if current is None else str(current)
        next_product[field] = _apply_replace(text, action)
    elif op == "remove":
        next_product.pop(field, None)
    elif op == "clear":
        next_product[field] = ""

    return next_product


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def _validate_condition(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        raise ValueError(f"{path}: condition must be an object")
    op = node.get("op")
    if op == "all":
        return
    if op in ("and", "or"):
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise ValueError(f"{path}: {op} requires a non-empty children list")
        for index, child in enumerate(children):
            _validate_condition(child, f"{path}.children[{index}]")
        return
    if op == "exists" or op == "empty":
        field = node.get("field")
        if not isinstance(field, str) or not field:
            raise ValueError(f"{path}: op {op!r} requires a non-empty field")
        return
    if op in ("equals", "contains", "starts_with", "ends_with", "regex"):
        if not isinstance(node.get("field"), str) or not node.get("field"):
            raise ValueError(f"{path}: op {op!r} requires a non-empty field")
        if node.get("arg") is None:
            raise ValueError(f"{path}: op {op!r} requires arg")
        if op == "regex":
            _compile(node["arg"])
        return
    if op in ("gt", "lt", "gte", "lte"):
        if not isinstance(node.get("field"), str) or not node.get("field"):
            raise ValueError(f"{path}: op {op!r} requires a non-empty field")
        if _as_number(node.get("arg")) is None:
            raise ValueError(f"{path}: op {op!r} requires a numeric arg")
        return
    if op == "between":
        if not isinstance(node.get("field"), str) or not node.get("field"):
            raise ValueError(f"{path}: op 'between' requires a non-empty field")
        if _as_number(node.get("arg")) is None or _as_number(node.get("arg2")) is None:
            raise ValueError(f"{path}: op 'between' requires numeric arg and arg2")
        return
    raise ValueError(f"{path}: unknown condition op {op!r}")


def validate_config(config: Any) -> None:
    """Strict validation of a rules config document."""
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    if not config:
        return  # empty config = no rules
    rules = config.get("rules")
    if rules is None:
        return
    if not isinstance(rules, list):
        raise ValueError("config.rules must be an array")
    for index, rule in enumerate(rules):
        path = f"rules[{index}]"
        if not isinstance(rule, dict):
            raise ValueError(f"{path}: rule must be an object")
        if not isinstance(rule.get("id"), str) or not rule.get("id"):
            raise ValueError(f"{path}: id must be a non-empty string")
        if not isinstance(rule.get("name"), str) or not rule.get("name"):
            raise ValueError(f"{path}: name must be a non-empty string")
        _validate_condition(rule.get("when"), f"{path}.when")
        then = rule.get("then")
        if not isinstance(then, list):
            raise ValueError(f"{path}.then must be an array")
        for action_index, action in enumerate(then):
            action_path = f"{path}.then[{action_index}]"
            op = action.get("op") if isinstance(action, dict) else None
            if op not in _ACTION_REQUIRED_KEYS:
                raise ValueError(f"{action_path}: unknown action op {op!r}")
            for key in _ACTION_REQUIRED_KEYS[op]:
                if key != "field" and action.get(key) is None:
                    raise ValueError(f"{action_path}: op {op!r} requires {key}")
            if not isinstance(action.get("field"), str) or not action.get("field"):
                raise ValueError(f"{action_path}: op {op!r} requires a non-empty field")


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class RulesPlugin:
    """Pipeline module executing ordered row-based rules."""

    def validate_config(self, config: dict[str, Any]) -> None:
        validate_config(config)

    def process(
        self,
        product: dict[str, Any],
        config: dict[str, Any],
        data: dict[str, Any],
        ctx: Any,
    ) -> dict[str, Any] | None:
        rules = config.get("rules", []) if isinstance(config, dict) else []
        current = product
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("isActive", True):
                continue
            if not evaluate_condition(rule.get("when", {"op": "all"}), current):
                continue
            for action in rule.get("then", []):
                current = apply_action(current, action)
        return current
```

**Important:** `apply_action` with `set` treats missing `value` as `None` at engine level (test uses `"value": None` semantics), but `validate_config` rejects it — engine is lenient (contract test runs with empty config), validator is strict (runs on save). `process` never mutates the incoming product because `apply_action` copies.

Also fix the intentional typo test in Step 1: delete `test_set_action` (it contains a deliberate syntax error); keep `test_set_action_fix`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rules_plugin.py tests/test_rules_conditions.py -q`
Expected: PASS (all).

- [ ] **Step 5: Lint and typecheck**

Run: `uv run ruff check ../plugins/core/rules/plugin.py tests/test_rules_plugin.py` and `uv run mypy .`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add ../plugins/core/rules/plugin.py tests/test_rules_plugin.py
git commit -m "feat(rules): actions, config validation, RulesPlugin.process"
```

---

### Task 3: Manifest and contract compliance

**Files:**
- Create: `plugins/core/rules/plugin.json`
- Test: `backend/tests/test_rules_contract.py`

**Interfaces:**
- Consumes: `RulesPlugin` from Task 2; `discover()` from `backend/app/plugins/discovery.py` (scans `plugins/core/<id>/` automatically — no registration code needed).
- Produces: plugin id `rules` registered at startup, auto-enabled (core=True). Manifest declares `config_schema`/`data_schema` (JSON Schema 2020-12), `config_scope`/`data_scope` `["global","client","feed_source"]`, `frontend: {menu_item, icon, component}`.

- [ ] **Step 1: Write failing contract test**

Create `backend/tests/test_rules_contract.py`:

```python
"""Contract + discovery tests for the rules core plugin."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/core/rules"))
from plugin import RulesPlugin  # noqa: E402

PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"


def _candidate():
    from app.plugins.contract import contract_violations
    from app.plugins.discovery import Candidate, collect_router, discover
    from app.plugins.manifest import parse_manifest

    candidates, _rejected = discover(PLUGINS_DIR)
    rules = [c for c in candidates if c.manifest.id == "rules"]
    assert rules, "rules plugin not discovered"
    return rules[0]


def test_rules_discovered_as_core():
    from app.plugins.discovery import discover

    candidates, rejected = discover(PLUGINS_DIR)
    rules = [c for c in candidates if c.manifest.id == "rules"]
    assert rules and rules[0].core is True
    assert all("rules" not in r for r in rejected)


def test_rules_manifest_fields():
    from app.plugins.discovery import discover

    candidates, _ = discover(PLUGINS_DIR)
    rules = next(c for c in candidates if c.manifest.id == "rules")
    assert rules.manifest.config_scope == ("global", "client", "feed_source")
    assert rules.manifest.data_scope == ("global", "client", "feed_source")
    frontend = rules.manifest.raw.get("frontend")
    assert frontend and frontend.get("menu_item")
    assert frontend.get("component") == "component.tsx"


def test_rules_passes_contract():
    from app.plugins.contract import contract_violations

    violations = contract_violations(_candidate())
    assert violations == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rules_contract.py -x -q`
Expected: FAIL — `rules plugin not discovered` (manifest missing; also `_check_process` gate: `validate_config({})` must not raise).

- [ ] **Step 3: Create manifest**

Create `plugins/core/rules/plugin.json`:

```json
{
  "id": "rules",
  "name": "Rules",
  "version": "1.0.0",
  "extension_point": "pipeline_module",
  "entry_point": "plugin:RulesPlugin",
  "config_scope": ["global", "client", "feed_source"],
  "data_scope": ["global", "client", "feed_source"],
  "config_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Rules",
    "properties": {
      "rules": {
        "type": "array",
        "title": "Rules",
        "items": {
          "type": "object",
          "properties": {
            "id": {"type": "string", "title": "ID"},
            "name": {"type": "string", "title": "Name"},
            "isMasterRule": {"type": "boolean", "title": "Master rule", "default": false},
            "isActive": {"type": "boolean", "title": "Active", "default": true},
            "when": {
              "type": "object",
              "title": "If",
              "properties": {
                "op": {"type": "string", "title": "Condition type", "enum": ["all", "and", "or", "equals", "contains", "starts_with", "ends_with", "regex", "exists", "empty", "gt", "lt", "gte", "lte", "between"]},
                "field": {"type": "string", "title": "Field"},
                "arg": {"title": "Value"},
                "arg2": {"type": "number", "title": "Max (between)"},
                "caseSensitive": {"type": "boolean", "title": "Case sensitive", "default": true},
                "children": {"type": "array", "title": "Conditions"}
              },
              "required": ["op"]
            },
            "then": {
              "type": "array",
              "title": "Then",
              "items": {
                "type": "object",
                "properties": {
                  "op": {"type": "string", "title": "Operation", "enum": ["set", "replace", "append", "prepend", "remove", "clear"]},
                  "field": {"type": "string", "title": "Field"},
                  "value": {"title": "Value"},
                  "find": {"type": "string", "title": "Find"},
                  "with": {"type": "string", "title": "Replace with"},
                  "caseSensitive": {"type": "boolean", "title": "Case sensitive", "default": true}
                },
                "required": ["op", "field"]
              }
            }
          },
          "required": ["id", "name", "when", "then"]
        }
      }
    }
  },
  "data_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Rules data"
  },
  "frontend": {
    "menu_item": "Rules",
    "icon": "list-check",
    "component": "component.tsx"
  }
}
```

Note: the contract test's `_check_validate_config` iterates required top-level properties (`rules`) — `config_schema` above declares no top-level `required`, so the check is skipped; `validate_config({})` not raising keeps `_check_process` enabled. Both behave correctly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rules_contract.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Run full backend suite for regressions**

Run: `uv run pytest -n auto -q`
Expected: PASS (uses TEST_DATABASE_URL; all prior tests green — plugin auto-registers as core).

- [ ] **Step 6: Lint and typecheck**

Run: `uv run ruff check .` and `uv run mypy .`
Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add ../plugins/core/rules/plugin.json tests/test_rules_contract.py
git commit -m "feat(rules): manifest and contract compliance"
```

---

### Task 4: Frontend — AST model and pure helpers (ast.ts)

**Files:**
- Create: `plugins/core/rules/frontend/ast.ts`
- Test: `frontend/src/features/rules/__tests__/ast.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces (imported by component.tsx and tests via relative path `../../../../plugins/core/rules/frontend/ast`):
  - `type ConditionOp = 'all' | 'and' | 'or' | 'equals' | 'contains' | 'starts_with' | 'ends_with' | 'regex' | 'exists' | 'empty' | 'gt' | 'lt' | 'gte' | 'lte' | 'between'`
  - `type ActionOp = 'set' | 'replace' | 'append' | 'prepend' | 'remove' | 'clear'`
  - `type RuleCondition = { op: ConditionOp; field?: string; arg?: string | number; arg2?: number; caseSensitive?: boolean; children?: RuleCondition[] }`
  - `type RuleAction = { op: ActionOp; field: string; value?: string; find?: string; with?: string; caseSensitive?: boolean }`
  - `type Rule = { id: string; name: string; isMasterRule: boolean; isActive: boolean; when: RuleCondition; then: RuleAction[] }`
  - `type RulesConfig = { rules: Rule[] }`
  - `newRule(name: string): Rule` — default `{when: {op:'all'}, then: []}`
  - `normalizeConfig(value: unknown): RulesConfig` — safe-shape any server JSON into RulesConfig (missing fields defaulted, unknown ops coerced to defaults, invalid entries dropped)
  - `rulesEqual(a: RulesConfig, b: RulesConfig): boolean` — deep structural equality for dirty-checks
  - `sortRulesPinned(rules: Rule[]): Rule[]` — stable partition masters-first (badge+pinning invariant)
  - `enforcePinning(rules: Rule[]): Rule[]` — after a reorder, re-partition so no non-master sits above a master, preserving relative order within each partition
  - `CONDITION_TEXT_OPS`, `CONDITION_NUMERIC_OPS` (const arrays) for UI grouping

- [ ] **Step 1: Write failing tests**

Create `frontend/src/features/rules/__tests__/ast.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import {
  enforcePinning,
  newRule,
  normalizeConfig,
  rulesEqual,
  sortRulesPinned,
  type Rule,
} from '../../../../plugins/core/rules/frontend/ast';

describe('newRule', () => {
  it('creates a rule with defaults', () => {
    expect(newRule('My rule')).toEqual({
      id: expect.any(String),
      name: 'My rule',
      isMasterRule: false,
      isActive: true,
      when: { op: 'all' },
      then: [],
    });
  });

  it('generates unique ids', () => {
    expect(newRule('a').id).not.toEqual(newRule('b').id);
  });
});

describe('normalizeConfig', () => {
  it('defaults empty values', () => {
    expect(normalizeConfig(undefined)).toEqual({ rules: [] });
    expect(normalizeConfig({})).toEqual({ rules: [] });
    expect(normalizeConfig({ rules: null })).toEqual({ rules: [] });
  });

  it('keeps valid rules and drops invalid entries', () => {
    const valid = {
      id: 'r1',
      name: 'ok',
      isMasterRule: true,
      isActive: false,
      when: { op: 'equals', field: 'title', arg: 'x' },
      then: [{ op: 'set', field: 'condition', value: 'new' }],
    };
    const out = normalizeConfig({ rules: [valid, { id: 'bad' }, 'junk'] });
    expect(out.rules).toHaveLength(1);
    expect(out.rules[0]).toEqual(valid);
  });

  it('coerces unknown op codes to safe defaults', () => {
    const out = normalizeConfig({
      rules: [{
        id: 'r1', name: 'n', when: { op: 'nope' }, then: [{ op: 'zap', field: 'f' }],
      }],
    });
    expect(out.rules[0].when.op).toBe('all');
    expect(out.rules[0].then).toEqual([]);
  });

  it('fills defaults for partial rules', () => {
    const out = normalizeConfig({ rules: [{ id: 'r1', name: 'n' }] });
    expect(out.rules[0].isMasterRule).toBe(false);
    expect(out.rules[0].isActive).toBe(true);
    expect(out.rules[0].when).toEqual({ op: 'all' });
    expect(out.rules[0].then).toEqual([]);
  });
});

describe('rulesEqual', () => {
  it('deep-compares config documents', () => {
    const a = normalizeConfig({ rules: [{ id: 'r1', name: 'n' }] });
    expect(rulesEqual(a, a)).toBe(true);
    const b = normalizeConfig({ rules: [{ id: 'r1', name: 'm' }] });
    expect(rulesEqual(a, b)).toBe(false);
  });
});

describe('pinning', () => {
  const master = (id: string): Rule => ({ ...newRule(id), id, isMasterRule: true });
  const normal = (id: string): Rule => ({ ...newRule(id), id });

  it('sortRulesPinned puts masters first preserving relative order', () => {
    const out = sortRulesPinned([normal('a'), master('m1'), normal('b'), master('m2')]);
    expect(out.map((r) => r.id)).toEqual(['m1', 'm2', 'a', 'b']);
  });

  it('enforcePinning repairs a broken order', () => {
    const broken = [normal('a'), master('m1'), normal('b')];
    const out = enforcePinning(broken);
    expect(out.map((r) => r.id)).toEqual(['m1', 'a', 'b']);
  });

  it('enforcePinning is idempotent', () => {
    const fixed = enforcePinning([master('m1'), normal('a'), master('m2'), normal('b')]);
    expect(enforcePinning(fixed)).toEqual(fixed);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm run test -- src/features/rules/__tests__/ast.test.ts`
Expected: FAIL — cannot resolve import.

- [ ] **Step 3: Implement ast.ts**

Create `plugins/core/rules/frontend/ast.ts`:

```typescript
export type ConditionOp =
  | 'all' | 'and' | 'or'
  | 'equals' | 'contains' | 'starts_with' | 'ends_with' | 'regex' | 'exists' | 'empty'
  | 'gt' | 'lt' | 'gte' | 'lte' | 'between';

export type ActionOp = 'set' | 'replace' | 'append' | 'prepend' | 'remove' | 'clear';

export type RuleCondition = {
  op: ConditionOp;
  field?: string;
  arg?: string | number;
  arg2?: number;
  caseSensitive?: boolean;
  children?: RuleCondition[];
};

export type RuleAction = {
  op: ActionOp;
  field: string;
  value?: string;
  find?: string;
  with?: string;
  caseSensitive?: boolean;
};

export type Rule = {
  id: string;
  name: string;
  isMasterRule: boolean;
  isActive: boolean;
  when: RuleCondition;
  then: RuleAction[];
};

export type RulesConfig = { rules: Rule[] };

export const CONDITION_TEXT_OPS = ['equals', 'contains', 'starts_with', 'ends_with', 'regex'] as const;
export const CONDITION_NUMERIC_OPS = ['gt', 'lt', 'gte', 'lte', 'between'] as const;

const CONDITION_OPS: ReadonlySet<string> = new Set([
  'all', 'and', 'or', 'exists', 'empty', ...CONDITION_TEXT_OPS, ...CONDITION_NUMERIC_OPS,
]);
const ACTION_OPS: ReadonlySet<string> = new Set(['set', 'replace', 'append', 'prepend', 'remove', 'clear']);

function newId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `r_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

export function newRule(name: string): Rule {
  return { id: newId(), name, isMasterRule: false, isActive: true, when: { op: 'all' }, then: [] };
}

function normalizeCondition(value: unknown): RuleCondition {
  if (typeof value !== 'object' || value === null) return { op: 'all' };
  const raw = value as Record<string, unknown>;
  const op = typeof raw.op === 'string' && CONDITION_OPS.has(raw.op) ? (raw.op as ConditionOp) : 'all';
  const cond: RuleCondition = { op };
  if (typeof raw.field === 'string') cond.field = raw.field;
  if (typeof raw.arg === 'string' || typeof raw.arg === 'number') cond.arg = raw.arg;
  if (typeof raw.arg2 === 'number') cond.arg2 = raw.arg2;
  if (typeof raw.caseSensitive === 'boolean') cond.caseSensitive = raw.caseSensitive;
  if (Array.isArray(raw.children)) cond.children = raw.children.map(normalizeCondition);
  return cond;
}

function normalizeAction(value: unknown): RuleAction | null {
  if (typeof value !== 'object' || value === null) return null;
  const raw = value as Record<string, unknown>;
  if (typeof raw.op !== 'string' || !ACTION_OPS.has(raw.op)) return null;
  if (typeof raw.field !== 'string' || !raw.field) return null;
  const action: RuleAction = { op: raw.op as ActionOp, field: raw.field };
  if (typeof raw.value === 'string') action.value = raw.value;
  if (typeof raw.find === 'string') action.find = raw.find;
  if (typeof raw.with === 'string') action.with = raw.with;
  if (typeof raw.caseSensitive === 'boolean') action.caseSensitive = raw.caseSensitive;
  return action;
}

export function normalizeConfig(value: unknown): RulesConfig {
  const rules: Rule[] = [];
  if (typeof value === 'object' && value !== null && Array.isArray((value as { rules?: unknown }).rules)) {
    for (const entry of (value as { rules: unknown[] }).rules) {
      if (typeof entry !== 'object' || entry === null) continue;
      const raw = entry as Record<string, unknown>;
      if (typeof raw.id !== 'string' || !raw.id) continue;
      if (typeof raw.name !== 'string' || !raw.name) continue;
      rules.push({
        id: raw.id,
        name: raw.name,
        isMasterRule: raw.isMasterRule === true,
        isActive: raw.isActive !== false,
        when: normalizeCondition(raw.when),
        then: Array.isArray(raw.then)
          ? raw.then.map(normalizeAction).filter((a): a is RuleAction => a !== null)
          : [],
      });
    }
  }
  return { rules };
}

export function rulesEqual(a: RulesConfig, b: RulesConfig): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function sortRulesPinned(rules: Rule[]): Rule[] {
  const masters = rules.filter((r) => r.isMasterRule);
  const others = rules.filter((r) => !r.isMasterRule);
  return [...masters, ...others];
}

export function enforcePinning(rules: Rule[]): Rule[] {
  return sortRulesPinned(rules);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- src/features/rules/__tests__/ast.test.ts`
Expected: PASS (all 10).

- [ ] **Step 5: Commit**

```bash
git add ../plugins/core/rules/frontend/ast.ts src/features/rules/__tests__/ast.test.ts
git commit -m "feat(rules): frontend AST model and pure helpers"
```

---

### Task 5: Frontend — RulesUI shell (list + editor wiring, no dnd yet)

**Files:**
- Create: `plugins/core/rules/frontend/component.tsx`
- Create: `plugins/core/rules/frontend/RuleList.tsx`
- Create: `plugins/core/rules/frontend/RuleEditor.tsx`
- Create: `frontend/public/locales/en/rules.json`
- Create: `frontend/public/locales/de/rules.json`
- Test: `frontend/src/features/rules/__tests__/RulesUI.test.tsx`

**Interfaces:**
- Consumes: `ast.ts` (Task 4), `usePluginConfig`/`useSavePluginConfig` (`frontend/src/api/hooks.ts:369-390`), `useFeedSourceFields` (`frontend/src/api/hooks.ts:106`), Mantine components, i18n.
- Produces: default-exported `RulesUI` component with props `{ pluginId: string; scope: PluginScope }` (matches PluginPage custom-component contract from `frontend/docs/plugin-uis.md`). Renders: left `RuleList` (create button, search toggle, select-all, rows with badge/kebab), right `RuleEditor` (name header, master badge, gear menu, IF block, THEN block, footer + Add).

NOTE for implementer: PluginPage (`frontend/src/features/plugin/PluginPage.tsx`) currently renders only `JsonSchemaForm` — it does NOT yet render custom components. Task 7 adds that wiring. For Task 5 the component is built standalone and unit-tested directly.

- [ ] **Step 1: Write failing component test**

Create `frontend/src/features/rules/__tests__/RulesUI.test.tsx`:

```tsx
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import RulesUI from '../../../../../plugins/core/rules/frontend/component';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeAll(async () => {
  await i18n.loadNamespaces(['rules', 'common']);
});

beforeEach(() => {
  vi.restoreAllMocks();
});

function withQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function renderUI() {
  stubFetch((url, init) => {
    if (url.startsWith('/plugins/rules/config')) {
      if (init?.method === 'PUT') return jsonResponse({ rules: [] });
      return jsonResponse({
        rules: [{
          id: 'r1', name: 'Remove HTML', isMasterRule: true, isActive: true,
          when: { op: 'all' },
          then: [{ op: 'set', field: 'condition', value: 'new' }],
        }],
      });
    }
    if (url.startsWith('/feed-sources/1/fields')) return jsonResponse({ fields: ['title', 'condition'] });
    return jsonResponse({});
  });
  return render(<RulesUI pluginId="rules" scope={{ feedSourceId: 1 }} />, {
    wrapper: withQueryClient(),
  });
}

describe('RulesUI', () => {
  it('loads rules from plugin config and renders the list', async () => {
    renderUI();
    expect(await screen.findByText('Remove HTML')).toBeInTheDocument();
    expect(screen.getByTestId('rules-list')).toBeInTheDocument();
  });

  it('shows master badge on master rules', async () => {
    renderUI();
    expect(await screen.findByText('Remove HTML')).toBeInTheDocument();
    expect(screen.getByTestId('master-badge-r1')).toBeInTheDocument();
  });

  it('selecting a row populates the editor', async () => {
    const user = userEvent.setup();
    renderUI();
    await user.click(await screen.findByText('Remove HTML'));
    expect(await screen.findByTestId('rule-editor')).toBeInTheDocument();
    expect(screen.getByTestId('rule-name-input')).toHaveValue('Remove HTML');
  });

  it('create rule button adds a new rule', async () => {
    const user = userEvent.setup();
    renderUI();
    await user.click(await screen.findByRole('button', { name: /create rule/i }));
    const editor = await screen.findByTestId('rule-editor');
    expect(editor).toBeInTheDocument();
    expect(screen.getByTestId('rule-name-input')).toHaveValue('');
  });

  it('editor renders THEN row with field and operation selects', async () => {
    const user = userEvent.setup();
    renderUI();
    await user.click(await screen.findByText('Remove HTML'));
    expect(await screen.findByTestId('then-row-0')).toBeInTheDocument();
    expect(screen.getByTestId('then-field-0')).toBeInTheDocument();
    expect(screen.getByTestId('then-op-0')).toBeInTheDocument();
    expect(screen.getByTestId('then-value-0')).toHaveValue('new');
  });

  it('add action appends a THEN row', async () => {
    const user = userEvent.setup();
    renderUI();
    await user.click(await screen.findByText('Remove HTML'));
    await user.click(await screen.findByTestId('then-add-0'));
    expect(await screen.findByTestId('then-row-1')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/features/rules/__tests__/RulesUI.test.tsx`
Expected: FAIL — cannot resolve component import.

- [ ] **Step 3: Create i18n files**

`frontend/public/locales/en/rules.json`:

```json
{
  "title": "Rules",
  "createRule": "Create rule",
  "search": "Search rules",
  "searchPlaceholder": "Search rules…",
  "select-all": "Select all rules",
  "list": {
    "empty": "No rules yet",
    "noResults": "No rules match your search",
    "master": "Master rule"
  },
  "editor": {
    "noSelection": "Select or create a rule",
    "name": "Rule name",
    "if": "If",
    "then": "Then",
    "conditionType": "Condition type",
    "all": "all products",
    "where": "where",
    "take": "take",
    "and": "and",
    "addSection": "Add section",
    "addField": "Field",
    "operation": "Operation"
  },
  "ops": {
    "all": "evaluates to all",
    "and": "all of",
    "or": "any of",
    "equals": "equals",
    "contains": "contains",
    "starts_with": "starts with",
    "ends_with": "ends with",
    "regex": "matches regex",
    "exists": "exists",
    "empty": "is empty",
    "gt": "greater than",
    "lt": "less than",
    "gte": "at least",
    "lte": "at most",
    "between": "between",
    "set": "set to value",
    "replace": "replace",
    "append": "append",
    "prepend": "prepend",
    "remove": "remove field",
    "clear": "clear field"
  },
  "fields": {
    "find": "Find",
    "with": "Replace with",
    "value": "Value",
    "caseSensitive": "Case sensitive",
    "min": "Min",
    "max": "Max"
  },
  "actions": {
    "edit": "Edit",
    "rename": "Rename",
    "duplicate": "Duplicate",
    "toggleActive": "Toggle active",
    "toggleMaster": "Toggle master rule",
    "delete": "Delete",
    "deleteRuleTitle": "Delete rule",
    "deleteRuleBody": "Delete {{name}}? This cannot be undone after saving.",
    "deleteSelectedTitle": "Delete selected rules",
    "deleteSelectedBody": "Delete {{count}} rule(s)? This cannot be undone after saving.",
    "activateSelected": "Activate selected",
    "deactivateSelected": "Deactivate selected"
  },
  "unsavedChanges": "You have unsaved changes. Leave anyway?",
  "saved": "Rules saved",
  "saveFailed": "Failed to save rules"
}
```

`frontend/public/locales/de/rules.json` (German translations, same keys):

```json
{
  "title": "Regeln",
  "createRule": "Regel erstellen",
  "search": "Regeln suchen",
  "searchPlaceholder": "Regeln suchen…",
  "select-all": "Alle Regeln auswählen",
  "list": {
    "empty": "Noch keine Regeln",
    "noResults": "Keine Regeln entsprechen der Suche",
    "master": "Master-Regel"
  },
  "editor": {
    "noSelection": "Regel auswählen oder erstellen",
    "name": "Regelname",
    "if": "Wenn",
    "then": "Dann",
    "conditionType": "Bedingungstyp",
    "all": "alle Produkte",
    "where": "wenn",
    "take": "übernehme",
    "and": "und",
    "addSection": "Abschnitt hinzufügen",
    "addField": "Feld",
    "operation": "Operation"
  },
  "ops": {
    "all": "gilt für alle",
    "and": "alle aus",
    "or": "eine aus",
    "equals": "ist gleich",
    "contains": "enthält",
    "starts_with": "beginnt mit",
    "ends_with": "endet mit",
    "regex": "entspricht Regex",
    "exists": "existiert",
    "empty": "ist leer",
    "gt": "größer als",
    "lt": "kleiner als",
    "gte": "mindestens",
    "lte": "höchstens",
    "between": "zwischen",
    "set": "auf Wert setzen",
    "replace": "ersetzen",
    "append": "anhängen",
    "prepend": "voranstellen",
    "remove": "Feld entfernen",
    "clear": "Feld leeren"
  },
  "fields": {
    "find": "Suchen",
    "with": "Ersetzen durch",
    "value": "Wert",
    "caseSensitive": "Groß-/Kleinschreibung beachten",
    "min": "Min",
    "max": "Max"
  },
  "actions": {
    "edit": "Bearbeiten",
    "rename": "Umbenennen",
    "duplicate": "Duplizieren",
    "toggleActive": "Aktiv umschalten",
    "toggleMaster": "Master-Regel umschalten",
    "delete": "Löschen",
    "deleteRuleTitle": "Regel löschen",
    "deleteRuleBody": "{{name}} löschen? Nach dem Speichern nicht rückgängig machbar.",
    "deleteSelectedTitle": "Ausgewählte Regeln löschen",
    "deleteSelectedBody": "{{count}} Regel(n) löschen? Nach dem Speichern nicht rückgängig machbar.",
    "activateSelected": "Auswahl aktivieren",
    "deactivateSelected": "Auswahl deaktivieren"
  },
  "unsavedChanges": "Ungespeicherte Änderungen. Trotzdem verlassen?",
  "saved": "Regeln gespeichert",
  "saveFailed": "Regeln speichern fehlgeschlagen"
}
```

Also register the namespace: in `frontend/src/i18n/index.ts` change `ns: ['common']` to `ns: ['common']` — no change needed (namespaces load on demand via `loadNamespaces`); but DO update `frontend/src/i18n/i18next.d.ts` if it enumerates namespaces — check and add `'rules'` to the Namespace list.

- [ ] **Step 4: Implement RuleList.tsx**

Create `plugins/core/rules/frontend/RuleList.tsx`:

```tsx
import { ActionIcon, Badge, Checkbox, Group, Menu, Paper, Stack, Text, TextInput, Tooltip, UnstyledButton } from '@mantine/core';
import { IconDotsVertical, IconGripVertical, IconPlus, IconSearch, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { Rule } from './ast';

export type RuleListProps = {
  rules: Rule[];
  selectedId: string | null;
  selectedIds: Set<string>;
  searchOpen: boolean;
  searchValue: string;
  onToggleSearch: () => void;
  onSearchChange: (value: string) => void;
  onSelect: (id: string) => void;
  onToggleSelected: (id: string, checked: boolean) => void;
  onToggleSelectAll: (checked: boolean) => void;
  onCreate: () => void;
  onEdit: (id: string) => void;
  onRename: (id: string) => void;
  onDuplicate: (id: string) => void;
  onToggleActive: (id: string) => void;
  onToggleMaster: (id: string) => void;
  onDelete: (id: string) => void;
  onBulkActivate: (active: boolean) => void;
  onBulkDelete: () => void;
};

export function RuleList(props: RuleListProps) {
  const { t } = useTranslation('rules');
  const {
    rules, selectedId, selectedIds, searchOpen, searchValue,
    onToggleSearch, onSearchChange, onSelect, onToggleSelected, onToggleSelectAll,
    onCreate, onRename, onDuplicate, onToggleActive, onToggleMaster, onDelete,
    onBulkActivate, onBulkDelete,
  } = props;

  const filtered = searchValue
    ? rules.filter((r) => r.name.toLowerCase().includes(searchValue.toLowerCase()))
    : rules;
  const allSelected = filtered.length > 0 && filtered.every((r) => selectedIds.has(r.id));

  return (
    <Stack gap="sm" data-testid="rules-list">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm" fw={500}>{t('title')}</Text>
        <Group gap={4} wrap="nowrap">
          {searchOpen ? (
            <TextInput
              size="xs"
              placeholder={t('searchPlaceholder')}
              value={searchValue}
              onChange={(e) => onSearchChange(e.currentTarget.value)}
              data-testid="rules-search"
              rightSection={
                <ActionIcon size="xs" variant="transparent" aria-label={t('search')} onClick={onToggleSearch}>
                  <IconX size={12} />
                </ActionIcon>
              }
            />
          ) : (
            <ActionIcon variant="default" size="sm" aria-label={t('search')} onClick={onToggleSearch}>
              <IconSearch size={14} />
            </ActionIcon>
          )}
          <ActionIcon variant="default" size="sm" aria-label={t('search')} onClick={onToggleSearch} style={{ display: 'none' }} />
          <IconPlusFallback onCreate={onCreate} label={t('createRule')} />
        </Group>
      </Group>
      <Group gap="xs" wrap="nowrap">
        <Checkbox
          aria-label={t('select-all')}
          checked={allSelected}
          indeterminate={selectedIds.size > 0 && !allSelected}
          onChange={(e) => onToggleSelectAll(e.currentTarget.checked)}
          data-testid="select-all"
        />
        {selectedIds.size > 0 ? (
          <Group gap={4}>
            <BulkButton onClick={() => onBulkActivate(true)}>{t('actions.activateSelected')}</BulkButton>
            <BulkButton onClick={() => onBulkActivate(false)}>{t('actions.deactivateSelected')}</BulkButton>
            <BulkButton onClick={onBulkDelete}>{t('actions.deleteSelectedTitle')}</BulkButton>
          </Group>
        ) : null}
      </Group>
      <Stack gap={6}>
        {filtered.length === 0 ? (
          <Text size="sm" c="dimmed" data-testid="rules-list-empty">
            {searchValue ? t('list.noResults') : t('list.empty')}
          </Text>
        ) : null}
        {filtered.map((rule) => (
          <RuleRow
            key={rule.id}
            rule={rule}
            selected={rule.id === selectedId}
            checked={selectedIds.has(rule.id)}
            onSelect={() => onSelect(rule.id)}
            onToggleChecked={(checked) => onToggleSelected(rule.id, checked)}
            onRename={() => onRename(rule.id)}
            onDuplicate={() => onDuplicate(rule.id)}
            onToggleActive={() => onToggleActive(rule.id)}
            onToggleMaster={() => onToggleMaster(rule.id)}
            onDelete={() => onDelete(rule.id)}
          />
        ))}
      </Stack>
    </Stack>
  );
}

function BulkButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <Paper
      component="button"
      type="button"
      onClick={onClick}
      px={6}
      py={2}
      withBorder
      style={{ fontSize: 'var(--mantine-font-size-xs)', cursor: 'pointer', background: 'transparent' }}
    >
      {children}
    </Paper>
  );
}

function IconPlusFallback({ onCreate, label }: { onCreate: () => void; label: string }) {
  return (
    <Paper
      component="button"
      type="button"
      onClick={onCreate}
      px={6}
      py={2}
      withBorder
      style={{ fontSize: 'var(--mantine-font-size-xs)', cursor: 'pointer', background: 'transparent' }}
    >
      {label}
    </Paper>
  );
}

function RuleRow({
  rule, selected, checked, onSelect, onToggleChecked,
  onRename, onDuplicate, onToggleActive, onToggleMaster, onDelete,
}: {
  rule: Rule;
  selected: boolean;
  checked: boolean;
  onSelect: () => void;
  onToggleChecked: (checked: boolean) => void;
  onRename: () => void;
  onDuplicate: () => void;
  onToggleActive: () => void;
  onToggleMaster: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation('rules');
  return (
    <Group
      wrap="nowrap"
      gap="xs"
      px="sm"
      py={6}
      component={UnstyledButton}
      onClick={onSelect}
      data-testid={`rule-row-${rule.id}`}
      style={{
        borderRadius: 'var(--mantine-radius-sm)',
        width: '100%',
        textAlign: 'left',
        background: selected ? 'var(--mantine-color-blue-light)' : undefined,
      }}
    >
      <IconGripVertical size={16} style={{ color: 'var(--mantine-color-dimmed-text)', flexShrink: 0 }} aria-hidden />
      <Checkbox
        aria-label={rule.name}
        checked={checked}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onToggleChecked(e.currentTarget.checked)}
        style={{ flexShrink: 0 }}
      />
      <Text size="sm" truncate style={{ flex: 1 }}>{rule.name}</Text>
      {!rule.isActive ? <Badge size="xs" variant="light" color="gray">{t('editor.inactive', 'inactive')}</Badge> : null}
      {rule.isMasterRule ? (
        <Badge size="xs" variant="filled" color="orange" data-testid={`master-badge-${rule.id}`}>
          {t('list.master')}
        </Badge>
      ) : null}
      <Menu shadow="md" width={180} withinPortal position="bottom-end" onClick={(e) => e.stopPropagation()}>
        <Menu.Target>
          <ActionIcon variant="subtle" aria-label={`${rule.name} menu`} onClick={(e) => e.stopPropagation()}>
            <IconDotsVertical size={14} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item onClick={onRename}>{t('actions.rename')}</Menu.Item>
          <Menu.Item onClick={onDuplicate}>{t('actions.duplicate')}</Menu.Item>
          <Menu.Item onClick={onToggleActive}>{t('actions.toggleActive')}</Menu.Item>
          <Menu.Item onClick={onToggleMaster}>{t('actions.toggleMaster')}</Menu.Item>
          <Menu.Item color="red" onClick={onDelete}>{t('actions.delete')}</Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
}
```

IMPORTANT: remove the stray hidden `ActionIcon` marked `style={{ display: 'none' }}` and the duplicate-aria-label line before committing — they were scaffolding; keep only the search toggle logic (if search open: show TextInput with X; else: show search icon button). Also remove the unused `Tooltip` import if ruff/ESLint flags it. `t('editor.inactive', 'inactive')` — add key `"inactive": "inactive"` / `"inaktiv"` under `editor` in both locale files.

- [ ] **Step 5: Implement RuleEditor.tsx**

Create `plugins/core/rules/frontend/RuleEditor.tsx`:

```tsx
import { ActionIcon, Badge, Group, Menu, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { IconCopy, IconSettings, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  CONDITION_NUMERIC_OPS, CONDITION_TEXT_OPS,
  type Rule, type RuleAction, type RuleCondition,
} from './ast';

const ALL_CONDITION_OPS = ['all', 'and', 'or', 'exists', 'empty', ...CONDITION_TEXT_OPS, ...CONDITION_NUMERIC_OPS] as const;
const ACTION_OPS = ['set', 'replace', 'append', 'prepend', 'remove', 'clear'] as const;

export type RuleEditorProps = {
  rule: Rule | null;
  fields: string[];
  onPatch: (patch: Partial<Rule>) => void;
  onPatchWhen: (when: RuleCondition) => void;
  onPatchThen: (then: RuleAction[]) => void;
  onToggleMaster: () => void;
  onToggleActive: () => void;
  onDelete: () => void;
  onRename: () => void;
};

function opOptions(t: (k: string) => string, ops: readonly string[]) {
  return ops.map((op) => ({ value: op, label: t(`ops.${op}`) }));
}

export function RuleEditor({
  rule, fields, onPatch, onPatchWhen, onPatchThen, onToggleMaster, onToggleActive, onDelete, onRename,
}: RuleEditorProps) {
  const { t } = useTranslation('rules');
  if (!rule) {
    return (
      <Stack data-testid="rule-editor" mih={200} justify="center" align="center">
        <Text c="dimmed">{t('editor.noSelection')}</Text>
      </Stack>
    );
  }

  const fieldData = fields.map((f) => ({ value: f, label: f }));
  const when = rule.when;

  return (
    <Stack gap="md" data-testid="rule-editor">
      <Group justify="space-between" wrap="nowrap">
        <Group gap="xs" wrap="nowrap">
          <TextInput
            aria-label={t('editor.name')}
            placeholder={t('editor.name')}
            value={rule.name}
            onChange={(e) => onPatch({ name: e.currentTarget.value })}
            data-testid="rule-name-input"
            style={{ flex: 1 }}
          />
          {rule.isMasterRule ? (
            <Badge variant="filled" color="orange">{t('list.master')}</Badge>
          ) : null}
        </Group>
        <Menu shadow="md" width={180}>
          <Menu.Target>
            <ActionIcon variant="default" aria-label="rule settings">
              <IconSettings size={14} />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={onRename}>{t('actions.rename')}</Menu.Item>
            <Menu.Item onClick={onToggleMaster}>{t('actions.toggleMaster')}</Menu.Item>
            <Menu.Item onClick={onToggleActive}>{t('actions.toggleActive')}</Menu.Item>
            <Menu.Item color="red" onClick={onDelete}>{t('actions.delete')}</Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>

      {/* IF block */}
      <Stack gap="xs">
        <Text size="sm" fw={500}>{t('editor.if')}</Text>
        <Group gap="xs" wrap="nowrap">
          <Select
            aria-label={t('editor.conditionType')}
            data={[
              { value: 'all', label: t('ops.all') },
              { value: 'where', label: t('editor.where') },
            ]}
            value={when.op === 'all' ? 'all' : 'where'}
            onChange={(v) => {
              if (v === 'all') onPatchWhen({ op: 'all' });
              else onPatchWhen({ op: 'equals', field: fields[0] ?? '', arg: '' });
            }}
            data-testid="condition-type"
            w={180}
          />
          {when.op !== 'all' ? (
            <ConditionNodeEditor
              node={when}
              fields={fieldData}
              onChange={onPatchWhen}
              t={t}
            />
          ) : null}
        </Group>
      </Stack>

      {/* THEN block */}
      <Stack gap="xs">
        <Text size="sm" fw={500}>{t('editor.then')}</Text>
        {rule.then.map((action, index) => (
          <Group key={index} gap="xs" wrap="nowrap" align="flex-start" data-testid={`then-row-${index}`}>
            <Text size="sm" c="dimmed">{t('editor.take')}</Text>
            <Select
              aria-label={t('editor.addField')}
              data={fieldData}
              value={action.field || null}
              onChange={(v) => {
                const next = [...rule.then];
                next[index] = { ...action, field: v ?? '' };
                onPatchThen(next);
              }}
              searchable
              data-testid={`then-field-${index}`}
              w={160}
            />
            <Text size="sm" c="dimmed">{t('editor.and')}</Text>
            <Select
              aria-label={t('editor.operation')}
              data={opOptions(t, ACTION_OPS)}
              value={action.op}
              onChange={(v) => {
                const next = [...rule.then];
                next[index] = { ...action, op: (v ?? 'set') as RuleAction['op'] };
                onPatchThen(next);
              }}
              data-testid={`then-op-${index}`}
              w={180}
            />
            {action.op === 'replace' ? (
              <>
                <TextInput
                  aria-label={t('fields.find')}
                  placeholder={t('fields.find')}
                  value={action.find ?? ''}
                  onChange={(e) => {
                    const next = [...rule.then];
                    next[index] = { ...action, find: e.currentTarget.value };
                    onPatchThen(next);
                  }}
                  data-testid={`then-find-${index}`}
                  w={120}
                />
                <TextInput
                  aria-label={t('fields.with')}
                  placeholder={t('fields.with')}
                  value={action.with ?? ''}
                  onChange={(e) => {
                    const next = [...rule.then];
                    next[index] = { ...action, with: e.currentTarget.value };
                    onPatchThen(next);
                  }}
                  data-testid={`then-with-${index}`}
                  w={120}
                />
                <Switch
                  aria-label={t('fields.caseSensitive')}
                  label={t('fields.caseSensitive')}
                  checked={action.caseSensitive !== false}
                  onChange={(e) => {
                    const next = [...rule.then];
                    next[index] = { ...action, caseSensitive: e.currentTarget.checked };
                    onPatchThen(next);
                  }}
                />
              </>
            ) : action.op === 'set' || action.op === 'append' || action.op === 'prepend' ? (
              <TextInput
                aria-label={t('fields.value')}
                placeholder={t('fields.value')}
                value={action.value ?? ''}
                onChange={(e) => {
                  const next = [...rule.then];
                  next[index] = { ...action, value: e.currentTarget.value };
                  onPatchThen(next);
                }}
                data-testid={`then-value-${index}`}
                w={160}
              />
            ) : null}
            <Group gap={2} wrap="nowrap">
              <ActionIcon
                variant="subtle" color="red" aria-label="delete action"
                onClick={() => onPatchThen(rule.then.filter((_, i) => i !== index))}
              >
                <IconTrash size={14} />
              </ActionIcon>
              <ActionIcon
                variant="subtle" aria-label="clone action"
                onClick={() => {
                  const next = [...rule.then];
                  next.splice(index + 1, 0, { ...action });
                  onPatchThen(next);
                }}
              >
                <IconCopy size={14} />
              </ActionIcon>
              <ActionIcon
                variant="subtle" aria-label="add action"
                onClick={() => {
                  const next = [...rule.then];
                  next.splice(index + 1, 0, { op: 'set', field: '', value: '' });
                  onPatchThen(next);
                }}
                data-testid={`then-add-${index}`}
              >
                + {/* replaced by IconPlus in final code */}
              </ActionIcon>
            </Group>
          </Group>
        ))}
      </Stack>
    </Stack>
  );
}
```

Implementer notes for RuleEditor:
1. Import `IconPlus` from `@tabler/icons-react` and use it instead of the literal `+` text in the add ActionIcon.
2. `ConditionNodeEditor` is an internal component you must write (recursive, ~80 lines): renders `[Field Select][Operator Select][Value Input]` for a leaf; for `and`/`or` renders children rows with per-row delete/clone/+ and an AND/OR combiner `Select` between rows; exposes `data-testid`-free simple structure (not covered by Task 5 tests; visual only).
3. Keep all aria-labels as written — the tests query by them.

- [ ] **Step 6: Implement component.tsx (RulesUI shell)**

Create `plugins/core/rules/frontend/component.tsx`:

```tsx
import { Button, Grid, Group, Stack, Text } from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useBlocker } from 'react-router';
import { useFeedSourceFields, usePluginConfig, useSavePluginConfig, type PluginScope } from '../../../../frontend/src/api/hooks';
import { notifyApiError, notifySuccess } from '../../../../frontend/src/app/notifications';
import { ApiError } from '../../../../frontend/src/api/client';
import { enforcePinning, newRule, normalizeConfig, rulesEqual, sortRulesPinned, type Rule, type RulesConfig } from './ast';
import { RuleList } from './RuleList';
import { RuleEditor } from './RuleEditor';

export type RulesUIProps = { pluginId: string; scope: PluginScope };

export default function RulesUI({ pluginId, scope }: RulesUIProps) {
  const { t } = useTranslation('rules');
  const { t: tCommon } = useTranslation('common');
  const config = usePluginConfig(pluginId, scope);
  const saveConfig = useSavePluginConfig(pluginId, scope);
  const fieldsQuery = useFeedSourceFields(String(scope.feedSourceId ?? ''));
  const fields = useMemo(() => fieldsQuery.data?.fields ?? [], [fieldsQuery.data]);

  const [rules, setRules] = useState<Rule[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchValue, setSearchValue] = useState('');
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (config.data && !hydrated) {
      setRules(normalizeConfig(config.data).rules);
      setHydrated(true);
    }
  }, [config.data, hydrated]);

  const serverRules = useMemo(
    () => (config.data ? sortRulesPinned(normalizeConfig(config.data).rules) : []),
    [config.data],
  );
  const localRules = useMemo(() => sortRulesPinned(rules), [rules]);
  const dirty = !rulesEqual({ rules: localRules }, { rules: serverRules });

  useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty) return false;
    if (currentLocation.pathname === nextLocation.pathname) return false;
    return !window.confirm(t('unsavedChanges'));
  });

  const selected = rules.find((r) => r.id === selectedId) ?? null;

  function patchRule(id: string, patch: Partial<Rule>) {
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }

  function createRule() {
    const rule = newRule('');
    setRules((prev) => [...prev, rule]);
    setSelectedId(rule.id);
  }

  async function onSave() {
    const payload: RulesConfig = { rules: localRules.map(({ id, name, isMasterRule, isActive, when, then }) => ({ id, name, isMasterRule, isActive, when, then })) };
    try {
      await saveConfig.mutateAsync(payload);
      notifySuccess(t('saved'));
      setHydrated(false);
    } catch (error) {
      notifyApiError(error, t('saveFailed'));
    }
  }

  function onReset() {
    setRules(normalizeConfig(config.data ?? {}).rules);
    setHydrated(true);
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text fw={500} size="lg">{t('title')}</Text>
        <Group>
          <Button variant="default" onClick={onReset} disabled={!dirty}>
            {tCommon('actions.cancel')}
          </Button>
          <Button onClick={() => void onSave()} loading={saveConfig.isPending} disabled={!dirty}>
            {tCommon('actions.save')}
          </Button>
        </Group>
      </Group>
      <Grid>
        <Grid.Col span={5}>
          <RuleList
            rules={localRules}
            selectedId={selectedId}
            selectedIds={selectedIds}
            searchOpen={searchOpen}
            searchValue={searchValue}
            onToggleSearch={() => { setSearchOpen((v) => !v); if (searchOpen) setSearchValue(''); }}
            onSearchChange={setSearchValue}
            onSelect={(id) => setSelectedId(id)}
            onToggleSelected={(id, checked) => setSelectedIds((prev) => {
              const next = new Set(prev);
              if (checked) next.add(id); else next.delete(id);
              return next;
            })}
            onToggleSelectAll={(checked) => setSelectedIds(checked ? new Set(localRules.map((r) => r.id)) : new Set())}
            onCreate={createRule}
            onEdit={(id) => setSelectedId(id)}
            onRename={(id) => setSelectedId(id)}
            onDuplicate={(id) => setRules((prev) => {
              const source = prev.find((r) => r.id === id);
              if (!source) return prev;
              const copy = { ...source, id: newRule('').id, name: `${source.name} (copy)` };
              return enforcePinning([...prev, copy]);
            })}
            onToggleActive={(id) => setRules((prev) => prev.map((r) => (r.id === id ? { ...r, isActive: !r.isActive } : r)))}
            onToggleMaster={(id) => setRules((prev) => enforcePinning(prev.map((r) => (r.id === id ? { ...r, isMasterRule: !r.isMasterRule } : r))))}
            onDelete={(id) => setRules((prev) => prev.filter((r) => r.id !== id))}
            onBulkActivate={(active) => setRules((prev) => prev.map((r) => (selectedIds.has(r.id) ? { ...r, isActive: active } : r)))}
            onBulkDelete={() => setRules((prev) => prev.filter((r) => !selectedIds.has(r.id)))}
          />
        </Grid.Col>
        <Grid.Col span={7}>
          <RuleEditor
            rule={selected}
            fields={fields}
            onPatch={(patch) => selected && patchRule(selected.id, patch)}
            onPatchWhen={(when) => selected && patchRule(selected.id, { when })}
            onPatchThen={(then) => selected && patchRule(selected.id, { then })}
            onToggleMaster={() => selected && setRules((prev) => enforcePinning(prev.map((r) => (r.id === selected.id ? { ...r, isMasterRule: !r.isMasterRule } : r))))}
            onToggleActive={() => selected && patchRule(selected.id, { isActive: !selected.isActive })}
            onDelete={() => selected && setRules((prev) => prev.filter((r) => r.id !== selected.id))}
            onRename={() => selected && setSelectedId(selected.id)}
          />
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
```

NOTE for implementer: `onDelete` (single and bulk) must call `modals.confirm` (from `@mantine/modals`) with `t('actions.deleteRuleTitle')`/`t('actions.deleteRuleBody', { name })` (or `deleteSelectedBody` with `{ count }`) before mutating. Check `frontend/package.json` for `@mantine/modals` availability; if absent, use `window.confirm` instead and note it in the commit message. Also: the deep import paths (`../../../../frontend/src/...`) are ugly but work for plugin-local components; keep them — the Vite alias `@/` does NOT exist in this repo (vite.config has no alias).

- [ ] **Step 7: Run tests to verify they pass**

Run: `npm run test -- src/features/rules/__tests__/RulesUI.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 8: Typecheck**

Run: `npm run typecheck`
Expected: no errors (ast.ts, component files, tests all compile).

- [ ] **Step 9: Commit**

```bash
git add ../plugins/core/rules/frontend/ public/locales/en/rules.json public/locales/de/rules.json src/features/rules/
git commit -m "feat(rules): RulesUI component — list, editor, i18n"
```

---

### Task 6: Frontend — drag-and-drop ordering with pinning

**Files:**
- Modify: `plugins/core/rules/frontend/component.tsx` (wrap list in DndContext)
- Modify: `plugins/core/rules/frontend/RuleList.tsx` (Sortable rows)
- Test: `frontend/src/features/rules/__tests__/dnd.test.tsx` (or extend RulesUI.test.tsx)

**Interfaces:**
- Consumes: dnd-kit core (`@dnd-kit/core`: `DndContext, useSensor, useSensors, PointerSensor, closestCenter`, `useSortable`, `SortableContext`, `verticalListSortingStrategy` — all already used in PipelinePage), `enforcePinning` from ast.ts.
- Produces: drag reorder of rules that respects master pinning (non-master cannot land above masters). Behavior contract: `arrayMove`-style reorder from index → index, then `enforcePinning`.

- [ ] **Step 1: Write failing dnd test**

Add to `frontend/src/features/rules/__tests__/dnd.test.tsx`:

```tsx
import { beforeAll, describe, expect, it } from 'vitest';
import { applyDragEnd } from '../dndUtils';

beforeAll(async () => {
  await i18n.loadNamespaces(['rules']);
});

import i18n from '../../../i18n';

describe('applyDragEnd (rules)', () => {
  const rules = [
    { id: 'm1', name: 'M1', isMasterRule: true, isActive: true, when: { op: 'all' as const }, then: [] },
    { id: 'a', name: 'A', isMasterRule: false, isActive: true, when: { op: 'all' as const }, then: [] },
    { id: 'b', name: 'B', isMasterRule: false, isActive: true, when: { op: 'all' as const }, then: [] },
  ];

  it('reorders within the same partition', () => {
    const out = applyDragEnd(rules, { active: 'b', over: 'a' });
    expect(out?.map((r) => r.id)).toEqual(['m1', 'b', 'a']);
  });

  it('blocks non-master from crossing above masters', () => {
    const out = applyDragEnd(rules, { active: 'a', over: 'm1' });
    expect(out?.map((r) => r.id)).toEqual(['m1', 'a', 'b']);
  });

  it('returns null when nothing changed', () => {
    expect(applyDragEnd(rules, { active: 'a', over: 'a' })).toBeNull();
  });

  it('returns null for unknown ids', () => {
    expect(applyDragEnd(rules, { active: 'zz', over: 'a' })).toBeNull();
  });
});
```

Where `frontend/src/features/rules/dndUtils.ts` is a thin wrapper: create it in this task with signature:

```typescript
import { enforcePinning, type Rule } from '../../../../plugins/core/rules/frontend/ast';

export function applyDragEnd(
  rules: Rule[],
  event: { active: { id: string | number }; over: { id: string | number } | null },
): Rule[] | null {
  const activeId = String(event.active.id);
  const overId = event.over ? String(event.over.id) : null;
  if (!overId || activeId === overId) return null;
  const fromIdx = rules.findIndex((r) => r.id === activeId);
  const toIdx = rules.findIndex((r) => r.id === overId);
  if (fromIdx < 0 || toIdx < 0) return null;
  const next = rules.slice();
  const [moved] = next.splice(fromIdx, 1);
  next.splice(toIdx, 0, moved);
  const pinned = enforcePinning(next);
  return pinned.some((r, i) => rules.some((_, j) => false)) || JSON.stringify(pinned) !== JSON.stringify(rules)
    ? pinned
    : pinned;
}
```

(The final `return` expression is deliberately written clearly in the real implementation: `return pinned;` — the long expression above is scaffolding noise; implement simply as: reorder, enforce pinning, return result even if equal to input only when a real move happened.)

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/features/rules/__tests__/dnd.test.tsx`
Expected: FAIL — `applyDragEnd` not found.

- [ ] **Step 3: Implement dndUtils.ts properly**

`frontend/src/features/rules/dndUtils.ts` (final form):

```typescript
import { enforcePinning, type Rule } from '../../../../plugins/core/rules/frontend/ast';

export function applyDragEnd(
  rules: Rule[],
  event: { active: { id: string | number }; over: { id: string | number } | null },
): Rule[] | null {
  const activeId = String(event.active.id);
  const overId = event.over ? String(event.over.id) : null;
  if (!overId || activeId === overId) return null;
  const fromIdx = rules.findIndex((r) => r.id === activeId);
  const toIdx = rules.findIndex((r) => r.id === overId);
  if (fromIdx < 0 || toIdx < 0) return null;
  const next = rules.slice();
  const [moved] = next.splice(fromIdx, 1);
  next.splice(toIdx, 0, moved);
  return enforcePinning(next);
}
```

- [ ] **Step 4: Wire DndContext in component.tsx, Sortable rows in RuleList.tsx**

`@dnd-kit/sortable` (10.0.0), `@dnd-kit/utilities` (3.2.2), and `@dnd-kit/core` (6.3.1) are all already installed — use the full SortableContext approach.

Modify `plugins/core/rules/frontend/component.tsx`:
- Import `{ DndContext, PointerSensor, closestCenter, useSensor, useSensors }` from `@dnd-kit/core` and `{ SortableContext, verticalListSortingStrategy }` from `@dnd-kit/sortable`.
- Sensors: `useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))` (same as PipelinePage).
- Wrap the `RuleList` Grid.Col content in `<DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>` + `<SortableContext items={localRules.map(r => r.id)} strategy={verticalListSortingStrategy}>`.
- `onDragEnd(event)`: `const next = applyDragEnd(rules, event); if (next) setRules(next);`

Modify `plugins/core/rules/frontend/RuleList.tsx`:
- Convert `RuleRow` to a sortable wrapper: each row gets `const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: rule.id })`; apply `style={{ transform: CSS.Transform.toString(transform), transition }}` and `ref={setNodeRef}`; attach `listeners` to the grip icon (`<IconGripVertical {...attributes} {...listeners} />`) so only the handle drags.
- Import `CSS` from `@dnd-kit/utilities`.

- [ ] **Step 5: Run all rules tests**

Run: `npm run test -- src/features/rules/`
Expected: PASS (ast, RulesUI, dnd).

- [ ] **Step 6: Typecheck + build**

Run: `npm run typecheck && npm run build`
Expected: both pass.

- [ ] **Step 7: Commit**

```bash
git add ../plugins/core/rules/frontend/component.tsx ../plugins/core/rules/frontend/RuleList.tsx src/features/rules/
git commit -m "feat(rules): drag-and-drop ordering with master pinning"
```

---

### Task 7: PluginPage custom-component wiring

**Files:**
- Modify: `frontend/src/features/plugin/PluginPage.tsx`
- Test: `frontend/src/features/plugin/PluginPage.test.tsx` (extend)

**Interfaces:**
- Consumes: `RulesUI` from Task 5 (default export), `PluginInfo.manifest.frontend.component` from `GET /plugins`.
- Produces: PluginPage renders a custom component when `manifest.frontend.component` is set, falling back to `JsonSchemaForm`. Resolution map: `component.tsx` (manifest value) → imported module. Component receives props `{ pluginId: string; scope: PluginScope }`.

- [ ] **Step 1: Write failing test**

Append to `frontend/src/features/plugin/PluginPage.test.tsx` (inside the existing describe; reuse existing `renderAt`, `jsonResponse`, `stubFetch`, `withQueryClient` helpers):

```tsx
  it('renders a custom component when manifest.frontend.component is set', async () => {
    const rulesPlugin = {
      ...plugin,
      id: 'rules',
      name: 'Rules',
      manifest: {
        ...plugin.manifest,
        frontend: { menu_item: 'Rules', icon: 'list-check', component: 'component.tsx' },
      },
    };
    stubFetch((url, init) => {
      if (url === '/plugins') return jsonResponse([rulesPlugin]);
      if (url.startsWith('/plugins/rules/config')) {
        if (init?.method === 'PUT') return jsonResponse({ rules: [] });
        return jsonResponse({ rules: [] });
      }
      return jsonResponse({});
    });
    renderAt('/plugins/rules');
    expect(await screen.findByTestId('rules-list')).toBeInTheDocument();
  });
```

Also update the module-level `plugin` fixture import if needed — reuse the existing one.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/features/plugin/PluginPage.test.tsx`
Expected: FAIL — PluginPage renders JsonSchemaForm (no `rules-list` testid in DOM).

- [ ] **Step 3: Implement custom-component branch**

Modify `frontend/src/features/plugin/PluginPage.tsx`:

```tsx
import RulesUI from '../../../../plugins/core/rules/frontend/component';
```

Replace the schema/form render block with:

```tsx
  const customComponent = plugin.manifest?.frontend?.component;
  const CustomComponent = customComponent === 'component.tsx' ? RulesUI : null;

  return (
    <Stack gap="md">
      <Title order={3}>{plugin.name}</Title>
      {config.isPending ? (
        <LoadingState />
      ) : config.isError ? (
        <ErrorState onRetry={() => void config.refetch()} />
      ) : CustomComponent ? (
        <CustomComponent pluginId={plugin.id} scope={scope} />
      ) : (
        <JsonSchemaForm
          schema={schema}
          value={formValue}
          onChange={(next) => setFormValue((next ?? {}) as Record<string, unknown>)}
          errors={saveConfig.error instanceof ApiError ? mapFieldErrors(saveConfig.error.errors) : {}}
        />
      )}
      <Group justify="flex-end">
        <Button onClick={() => void onSubmit(formValue)} loading={saveConfig.isPending}>
          {t('save')}
        </Button>
      </Group>
    </Stack>
  );
```

Implementation notes:
1. The direct static import of the core plugin component is the MVP wiring (docs call for build-time discovery generating `pluginComponents.ts`; that full generator is out of scope for this plan — documented in Task 8 as follow-up). Guard with a comment referencing ADR 0002.
2. The Save button at PluginPage level must be hidden when a custom component is rendered (RulesUI has its own Save): wrap the `<Group justify="flex-end">` in `{!CustomComponent && (...)}`.
3. Keep `JsonSchemaForm` fallback path exactly as-is otherwise.
4. Wrap the custom component render in the repo's error-isolation pattern if `PluginErrorBoundary` exists in `frontend/src/components/` — search for it; if absent, plain render (ADR 0004 compliance noted as follow-up in Task 8).

- [ ] **Step 4: Run tests**

Run: `npm run test -- src/features/plugin/PluginPage.test.tsx`
Expected: PASS (all, including new custom-component test).

- [ ] **Step 5: Typecheck + full frontend suite**

Run: `npm run typecheck && npm run test`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/features/plugin/PluginPage.tsx src/features/plugin/PluginPage.test.tsx
git commit -m "feat(plugin-page): render custom plugin components (rules first)"
```

---

### Task 8: Documentation updates + final verification

**Files:**
- Modify: `backend/docs/plugins.md` (core-plugin table row + MVP scope)
- Modify: `frontend/docs/plugin-uis.md` (first-party reference component + wiring note)
- Modify: `AGENTS.md` (only if commands change — they don't; skip if unchanged)

**Interfaces:**
- Consumes: everything above.
- Produces: docs matching reality, same commit.

- [ ] **Step 1: Update backend/docs/plugins.md**

In the "Core Plugins (MVP Rudimentary)" table, replace the Rules row:

```markdown
| Rules | `rules` | `config: [global, client, feed_source]`, `data: [global, client, feed_source]` | Ordered rule list (IF/THEN AST): text/numeric/regex conditions; set/replace/append/prepend/remove/clear actions; master flag = UI pinning; `plugins/core/rules/` |
```

Add after the table a short subsection:

```markdown
### Rules Plugin (`plugins/core/rules/`)

Config document: `{"rules": [{id, name, isMasterRule, isActive, when, then}]}`.
- `when`: condition AST — `all` | `and`/`or` groups | leaf ops
  (`equals, contains, starts_with, ends_with, regex, exists, empty, gt, lt, gte, lte, between`);
  `caseSensitive` defaults `true`.
- `then`: ordered actions (`set, replace, append, prepend, remove, clear`);
  `replace` supports regex mode when `find` starts with `/` (capture groups via `$1`).
- `isMasterRule` is UI-only (badge + list pinning); engine order = array order.
- `isActive: false` skips the rule at run time.
- `validate_config` strictly validates the document on save; `process` evaluates
  conditions against the current product state (post-previous-plugins) and applies
  actions in order; never mutates `ctx.original_product`.
```

- [ ] **Step 2: Update frontend/docs/plugin-uis.md**

In "Custom Plugin Components", replace the example with the real first-party reference:

```markdown
### First-Party Reference: Rules (`plugins/core/rules/frontend/component.tsx`)

The Rules module is the first core plugin with a custom UI. MVP wiring:
`PluginPage` statically imports the component and renders it when
`manifest.frontend.component === 'component.tsx'`, passing
`{ pluginId, scope }`. The RulesUI owns its own save state (dirty check +
`useBlocker`) — PluginPage hides its generic Save button for custom components.

Full build-time discovery (Vite scan of `plugins/*/frontend/` generating
`pluginComponents.ts`) is the follow-up per ADR 0002; third-party plugins
currently use schema-rendered forms until that generator lands.
```

- [ ] **Step 3: Run full verification suites**

Backend (from `backend/`): `uv run pytest -n auto -q && uv run ruff check . && uv run mypy .`
Frontend (from `frontend/`): `npm run typecheck && npm run test && npm run build`
Expected: everything green.

- [ ] **Step 4: Commit docs**

```bash
git add ../backend/docs/plugins.md ../frontend/docs/plugin-uis.md
git commit -m "docs: rules core plugin — config shape, UI wiring, follow-ups"
```

---

## Self-Review Notes (for executing agents)

- Task 2 Step 1 contains a deliberate broken test (`test_set_action`) — implementer must DELETE it and keep `test_set_action_fix` (instruction repeated in Task 2 Step 3).
- Task 5 Step 4 contains scaffolding artifacts to remove (hidden ActionIcon, duplicate aria-label) — instructions inline.
- Task 6 Step 1/3: use the FINAL simple `applyDragEnd` implementation (Step 3), not the Step 1 sketch.
- Task 7: follow implementation notes 1–4 exactly (hide generic Save, keep fallback intact).
- All commits from repo root or respective subdirs as written; never commit `.env`, secrets, or `__pycache__`.
