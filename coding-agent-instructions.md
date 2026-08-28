# Coding Agent Instructions — GMC Feed Engine (Greenfield Setup)

> These instructions govern how you (the coding agent) set up and build this project.
> They are process rules, not a spec. The product specification lives in `gmc-feed-engine-spec.md`.

## 1. Source documents & read order

1. `gmc-feed-engine-spec.md` — the binding product specification. Read it fully before writing any code.
2. `gmc_def.md` — the GMC attribute reference. Required to populate the Attribute Registry (spec §5.6).
3. This file — process rules.

If documents contradict each other, the spec wins over this file; flag the contradiction to the human instead of resolving it silently.

## 2. Authority model — what is fixed, what is yours

- **Binding (do not reopen):** everything in spec §2 (architecture decisions), the plugin contract in §5, the delta mechanics in §4, the QC rule set in §7, the API shape in §8. These were decided with the human and are not subject to re-brainstorming.
- **Yours to derive:** the concrete DB schema from the conceptual data model (§4), internal module structure, naming, library versions (pinned, see §4 of this document), test granularity beyond the contract suite.
- **Spec is silent / ambiguous:** propose a decision in writing and wait for human approval. Never guess on behavior that is observable from outside (API responses, XML output, UI flows). Record every approved implementation-level decision in `docs/decisions.md` (date, topic, decision, rationale) — do not edit the spec file yourself.

## 3. Workflow (superpowers)

This project is built with the superpowers skill workflow. Apply it **per milestone** (see §6):

1. **Brainstorm** (`/superpowers:brainstorm`) — scoped to the current milestone only. The spec is the pre-approved product design: brainstorming refines *how* to implement the milestone, never *whether* the spec is right. If you catch yourself questioning a binding decision, write it into `docs/decisions.md` as an open question for the human and continue with the spec as written.
2. **Design doc** — produce it per milestone; it must cite the spec sections it implements (e.g. "implements §5.3 scope resolution"). Human approval required before planning.
3. **Plan** (`/superpowers:write-plan`) — bite-sized tasks with exact file paths and verification steps.
4. **Execute** (`/superpowers:execute-plan`) — TDD is mandatory (RED-GREEN-REFACTOR). The plugin contract test suite (spec §5.10) must pass after every milestone that touches the plugin host or any plugin.
5. **Review** — code review between tasks as the workflow prescribes; critical issues block progress.

Work in isolated branches/worktrees per milestone; keep `main` green.

## 4. Library documentation (context7)

Your training-data knowledge of library APIs is outdated by definition. Rules:

- Before writing code against any third-party library, fetch its current, version-specific documentation via context7 (add `use context7` to your own lookup prompts / use the queryDocs tool).
- Pin every dependency to an exact version on first use and record it (lockfile + a line in `docs/decisions.md`).
- Libraries you will need docs for (non-exhaustive): FastAPI, APScheduler, SQLAlchemy/alembic (or chosen ORM), pydantic, React 19, Vite, Mantine v9.5.2, TanStack Query / Table / Form, dnd-kit.
- If context7 and your memory disagree, context7 wins. If context7 has no entry for a library, say so and ask before improvising.

## 5. Target project layout (greenfield)

```
/
├── backend/            # FastAPI app (API, readers, staging, plugin host, QC, XML writer)
├── frontend/           # React 19 + TypeScript (Vite), Mantine v9.5.2
├── plugins/
│   └── core/           # labelizer, rules, category, filter — same format as any plugin (spec §5.1)
├── tests/              # incl. the plugin contract test suite (spec §5.10)
├── docs/
│   └── decisions.md    # implementation-level decision log (see §2)
├── docker-compose.yml  # PostgreSQL container (only containerized component, spec §2)
└── gmc-feed-engine-spec.md
```

Backend and frontend run natively on the host; only PostgreSQL runs in Docker.

## 6. Milestones & build order

Sequence is deliberate — each milestone is verifiable on its own and unblocks the next. Do not reorder without human approval.

| # | Milestone | Spec sections | Done when |
|---|---|---|---|
| M0 | Repo, tooling, CI, Docker Postgres, FastAPI skeleton, Vite/React skeleton, session login | §2, §8 | Login/logout works; CI runs backend + frontend tests |
| M1 | DB schema, core entities, Attribute Registry loader | §4, §5.6 | Registry loads from `gmc_def.md`; migrations run clean |
| M2 | Input readers + canonical product model + flat-notation parsing | §5.5, §5.8 | All four formats parse into the canonical model; malformed rows logged & skipped |
| M3 | Field mapping (auto + manual) | §6 | Auto mapper suggests from registry; manual edits persist per feed source |
| M4 | Staging + delta mechanics | §4 | `content_hash`/`config_hash` behave exactly as specified, incl. reactivation & purge |
| M5 | Plugin host: discovery, manifest validation, scope merge, runtime contract, contract test suite | §5.1–5.4, 5.10 | A dummy third-party plugin passes the contract suite without any core change |
| M6 | Four core plugins, rudimentary scope | §5.9 | Each passes the contract suite; MVP-scope limits respected |
| M7 | Quality Check engine (registry-driven) | §7 | All rule categories fire; image-size escalation uses injectable clock; ExportRun carries counts |
| M8 | XML writer, versioning, atomic publish, export endpoint | §2, §8 | Google-fetchable URL; rollback append-only; diff endpoint field-based |
| M9 | Scheduling & run orchestration | §2 | APScheduler (UTC), per-feed-source lock, manual `POST /run` |
| M10 | Frontend areas | §9 | All ten areas usable; plugin menu items render dynamically |

## 7. Non-negotiables (will be verified)

- No core code changes to add a plugin — ever (spec §5). If you feel the need, the contract has a gap: report it, don't patch around it.
- The reserved sub-paths `config` and `data` under `/plugins/{id}/…` stay reserved (spec §5.4/§8).
- Pass-through fidelity for untouched nested structures (`shipping`/`tax`) is a hard requirement (spec §5.5).
- Removed products are omitted from XML — no tombstones, no `expiration_date` tricks (spec §2/§4; the 30-day GMC expiry is accepted).
- QC never blocks an export; it runs sequentially before the writer (spec §7).
- Atomic publish only: temp file + `os.replace()` (spec §2).
- No Basic Auth on the export endpoint; token rotation invalidates immediately (spec §8).
- No mapping templates; mappings live per feed source (spec §6).
- Client state in the frontend: React built-ins only — do not add a store library (spec §2).

## 8. Definition of done (MVP)

- All milestones M0–M10 complete with their "done when" criteria met.
- Contract test suite green against all four core plugins.
- A full pipeline run on a real wide-format TSV produces a GMC-compliant XML, versioned and fetchable via the token URL.
- `docs/decisions.md` contains every implementation-level decision you made along the way.
