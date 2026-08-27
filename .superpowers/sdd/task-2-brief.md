### Task 2: Pin Pillow Dependency

**Goal:** Add Pillow as an exact-pinned dependency.

**Files:**
- Modify: `backend/pyproject.toml`

#### Steps

- [ ] **Step 1: Add Pillow to pyproject.toml**

```toml
# backend/pyproject.toml — dependencies section
dependencies = [
    "alembic>=1.13,<2",
    "fastapi>=0.111,<1",
    "httpx>=0.27,<1",
    "itsdangerous>=2.2,<3",
    "passlib[bcrypt]>=1.7,<2",
    "pillow>=10.4,<11",
    "pydantic>=2.7,<3",
    "pyjwt>=2.8,<3",
    "sqlalchemy[asyncio]>=2.0,<3",
    "uvicorn[standard]>=0.30,<1",
]
```

- [ ] **Step 2: Lock the dependency**

Run: `cd backend && uv lock`
Expected: Pillow added to uv.lock

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "deps: pin Pillow for image dimension parsing"
```

---

