### Task 3: Cap test-engine pools

**Files:**
- Modify: all 21 test files under `backend/tests/` containing `create_async_engine(` (57 call sites; authoritative list via `grep -rln create_async_engine backend/tests`)

**Interfaces:**
- Consumes: nothing new.
- Produces: every test engine created with `pool_size=2, max_overflow=0` (spec-owner decision).

- [ ] **Step 1: Mechanical sweep**

Every `create_async_engine(<url-expr>)` call in `backend/tests/**` becomes `create_async_engine(<url-expr>, pool_size=2, max_overflow=0)`. Multi-line calls get the kwargs appended to the argument list. Do NOT touch `backend/app/` production engine creation (`app/db/engine.py` or equivalent) — this cap applies to tests only.

After the sweep, verify completeness:

```bash
grep -rn "create_async_engine(" backend/tests | grep -v "pool_size=2" || echo CLEAN
```
Expected: `CLEAN`.

- [ ] **Step 2: Full suite, serial**

```bash
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres uv run pytest -q -n0 2>&1 | tail -1
```
Expected: 366 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests
git commit -m "perf: cap test-engine pools (pool_size=2, max_overflow=0)"
```

---

