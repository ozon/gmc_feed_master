# Caddy Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone Caddyfile for production reverse-proxying and update .env.example with public_base_url guidance.

**Architecture:** Single Caddyfile at project root handles TLS, API routing to backend, and static file serving for the React SPA. Environment variables (`DOMAIN`, `BACKEND_URL`) make it portable. No changes to existing dev tooling.

**Tech Stack:** Caddy (web server), Caddyfile syntax

## Global Constraints

- Dev workflow unchanged: `make dev` continues to work as-is
- `docker-compose.yml`, `vite.config.ts`, `Makefile` — no modifications
- API routes must match Vite proxy config in `frontend/vite.config.ts:44-76`

---

### Task 1: Create Caddyfile

**Files:**
- Create: `Caddyfile`

**Interfaces:**
- Consumes: `DOMAIN` env var (default: `localhost`), `BACKEND_URL` env var (default: `http://127.0.0.1:8000`)
- Produces: Caddy configuration for production reverse proxy

- [ ] **Step 1: Write the Caddyfile**

```caddyfile
{$DOMAIN:localhost} {
	handle /auth/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
	handle /health {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
	handle /clients/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
	handle /feed-sources/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
	handle /dashboard/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
	handle /plugins/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
	handle /registry/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}
	handle /export/* {
		reverse_proxy {$BACKEND_URL:http://127.0.0.1:8000}
	}

	handle {
		root * /path/to/frontend/dist
		try_files {path} /index.html
		file_server
	}
}
```

- [ ] **Step 2: Validate Caddyfile syntax**

Run: `caddy validate --config Caddyfile --adapter caddyfile`
Expected: `Valid configuration`

- [ ] **Step 3: Commit**

```bash
git add Caddyfile
git commit -m "ops: add Caddyfile for production reverse proxy"
```

---

### Task 2: Update .env.example

**Files:**
- Modify: `.env.example`

**Interfaces:**
- Consumes: Existing .env.example content
- Produces: Updated .env.example with PUBLIC_BASE_URL guidance

- [ ] **Step 1: Add PUBLIC_BASE_URL to .env.example**

Append to `.env.example`:

```bash
# Production: set to your public URL (https://gmc.example.com)
# PUBLIC_BASE_URL=https://gmc.example.com
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "ops: add PUBLIC_BASE_URL guidance to .env.example"
```

---

### Task 3: Update Makefile (optional)

**Files:**
- Modify: `Makefile`

**Interfaces:**
- Consumes: Existing Makefile content
- Produces: New `make prod` target

- [ ] **Step 1: Add prod target to Makefile**

Add after the `dev-stop` target (around line 139):

```makefile
.PHONY: prod
prod: ## Start Caddy production server (requires DOMAIN and BACKEND_URL env vars)
	caddy run --config Caddyfile --adapter caddyfile
```

- [ ] **Step 2: Commit**

```bash
git add Makefile
git commit -m "ops: add make prod target for Caddy"
```

---

## Summary

| Task | Files | Description |
|------|-------|-------------|
| 1 | `Caddyfile` | Standalone Caddyfile with env var support |
| 2 | `.env.example` | Add PUBLIC_BASE_URL documentation |
| 3 | `Makefile` | Add `make prod` convenience target |

Total: 3 tasks, 3 files modified/created. Estimated time: 10 minutes.
