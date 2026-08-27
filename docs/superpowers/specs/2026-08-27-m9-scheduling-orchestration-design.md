# M9 Design: Scheduling & Run Orchestration (Hardening + Verification)

**Date:** 2026-08-27
**Implements:** spec §2 (Scheduling, Run concurrency), §8 (manual trigger and
run-history endpoints, already present — verified, not re-built).

Most of M9's "done when" criteria (APScheduler in-process UTC scheduling,
per-feed-source lock, manual `POST /run`) were delivered ahead of time by the
internal M2 milestone (scheduler/runner skeleton). This milestone closes the
remaining spec-conformance gaps and proves the behavior with tests. No new API
surface, no schema changes, no new dependencies (APScheduler stays pinned at
3.11.3).

Owner-approved decisions from brainstorming (2026-08-27):

1. Scope is hardening + verification only; no new scheduling API endpoints.
2. Overlap semantics are uniform: every overlap (scheduled or manual) is
   handled by the `LockRegistry`, producing a `skipped` run row and the
   spec-mandated log message.
3. Crash-orphaned runs (`running`/`pending` at startup) are reconciled to
   `error` with an explanatory message. Spec is silent; owner approved.

## 1. Current state (verified 2026-08-27)

Already in place and unchanged unless noted:

- `SchedulerService` (`app/pipeline/scheduler.py`): `AsyncIOScheduler(timezone="UTC")`,
  cron validated by constructing a real `CronTrigger` at write time,
  `misfire_grace_time=None` (no catch-up after downtime, spec §2),
  register/unregister/reschedule on feed-source CRUD, `register_all` at
  startup, system purge job (`system-staging-purge`, `0 3 * * *`).
- `PipelineRunner` (`app/pipeline/runner.py`): per-feed-source `LockRegistry`;
  an overlapping `execute()` finalizes a `skipped` `IngestionRun` row.
- `POST /feed-sources/{id}/run` (`app/routes/clients.py`): 202 + `run_id`,
  pre-created `pending` row, `asyncio.create_task` dispatch (M2 decision).
- `GET /feed-sources/{id}/ingestion-runs`: paginated history incl. errors.

Gaps closed by this milestone:

| # | Gap | Spec basis |
|---|---|---|
| G1 | Scheduled overlaps are swallowed by APScheduler's default `max_instances=1`: no run row, generic APScheduler log — asymmetric with the manual path | §2 "overlapping run is skipped and logged" |
| G2 | The spec-mandated log message "previous run still active" is not emitted anywhere | §2 |
| G3 | Crash-orphaned `running`/`pending` run rows stay non-terminal forever | silent; owner-approved |
| G4 | Manual-trigger background task has no strong reference (GC hazard) | hardening |
| G5 | Scheduler lifespan wiring (start, purge job, `register_all`) has no direct test | verification |
| G6 | No acceptance proof that the scheduled entry point drives the full pipeline (ingest → plugins → QC → export) | verification |

## 2. Uniform overlap semantics (G1, G2)

### 2.1 Scheduled overlaps reach the runner

`SchedulerService.register` adds feed-source jobs with `max_instances=2`
(verified against installed APScheduler 3.11.3 source: default is 1; on
`MaxInstancesReachedError` the scheduler skips submission and logs a generic
warning). With 2, a tick that fires while the previous run is still executing
is dispatched into `PipelineRunner.execute`, where the `LockRegistry` treats
it exactly like a manual overlap: the existing locked branch finalizes a new
`IngestionRun` row with `status="skipped"` (`run_id=None` path of `_finish`).

Rationale for 2 and not more: the skip path performs one small DB write and
returns in milliseconds, so at most one long-running instance plus one
briefly-skipping instance coexist. A third concurrent tick being dropped by
APScheduler would require two skips to overlap each other — a theoretical
extreme accepted without extra configuration.

System jobs (`register_system_job`) keep APScheduler defaults; only
feed-source jobs change.

### 2.2 Spec-mandated log and skip reason (G2)

The locked branch of `PipelineRunner.execute` logs at WARNING:

```
previous run still active: skipping run for feed source <id>
```

and the skipped run row carries `statistics={"reason": "previous run still
active"}` (JSONB column, no schema change) so the M10 ingestion-status area
can display why a run was skipped. `error_message` stays NULL — a skip is
not an error.

### 2.3 Note on check-then-acquire

`execute` checks `is_locked()` and then `await lock.acquire()`. There is no
await point between the check and an uncontended acquire on a single-threaded
event loop, so two overlapping invocations cannot both pass the check; the
second always observes the lock held. No change needed; recorded here so the
reasoning is not re-derived later.

## 3. Startup reconciliation of crash-orphaned runs (G3)

New module `app/pipeline/reconcile.py`:

```python
async def reconcile_interrupted_runs(session_factory, clock) -> int
```

- One statement at startup, inside the lifespan, **before** `register_all`:
  `UPDATE ingestion_runs SET status='error',
   error_message='interrupted by restart', completed_at=<clock now>
   WHERE status IN ('running','pending')`.
- Returns the affected count; lifespan logs INFO
  `startup reconciliation: marked %s orphaned runs as interrupted`.
- `error` is the existing terminal status for failed runs — no new status
  value, no migration. `error_stack_trace` stays NULL; `error_message`
  distinguishes interrupted runs from genuine pipeline failures.
- Takes the injectable app clock (pattern established by the M7 QC engine),
  unit-testable without the lifespan.
- Rationale for ordering: cosmetic (locks are fresh at startup either way),
  but history is honest before the first new tick fires.

## 4. Manual-trigger task references (G4)

`trigger_run` keeps `asyncio.create_task` (M2 decision stands) but the task
gets a strong reference: a `set[asyncio.Task]` created on `app.state`
(`background_tasks`), `discard`-ing via the task's done callback. No
observable behavior change; protects against CPython garbage-collecting an
unreferenced task mid-run. Recorded in `docs/decisions.md` as an amendment
to the M2 manual-trigger decision.

## 5. Testing (G5, G6)

Real PostgreSQL per AGENTS.md (pytest-postgresql template cloning; no mocks).

| Area | Approach |
|---|---|
| Overlap semantics | Hold a feed source's lock, invoke the scheduled job's coroutine exactly as APScheduler would (`runner.execute(feed_source_id)`, no pre-created run): assert `skipped` row, `statistics.reason`, and `caplog` contains "previous run still active". Same assertions for the manual-overlap path. |
| Registration correctness | `register` produces job id `feed-source-{id}`, UTC cron trigger, `max_instances=2`; assert `next_run_time` for a known cron against a frozen clock. |
| Cron-fire verification | Seam-level: the scheduler's job callable **is** `runner.execute`; tests invoke it the way the scheduler does. No real-timer wait test — cron is minute-granular, a live wait is slow and flaky. Rationale recorded in `decisions.md`. |
| Lifespan wiring | Existing `app.router.lifespan_context(app)` pattern (used by M6 acceptance and plugin-startup tests): scheduler started, purge job present under `system-staging-purge`, `register_all` registers seeded feed sources, orphaned runs reconciled, clean shutdown. |
| Scheduled-path end-to-end | One acceptance test drives the full pipeline (ingest → plugins → QC → export) via the scheduled entry point (`run_id=None`), complementing existing manual-trigger acceptance coverage. |
| Reconcile unit tests | Seeded `running`/`pending`/terminal rows → only non-terminal rows flipped to `error` with the message and `completed_at` set; count returned. |

**Acceptance gate:** `backend/scripts/verify_m9_gate.py` following the
M6/M8 gate-script pattern — full suite serial (`-n0`) + parallel, compileall,
`git diff --check`.

## 6. Out of scope

- New API endpoints (next-run-time, pause/resume) — owner declined; spec §8
  lists neither.
- Schema changes / migrations — none needed.
- Frontend cron presets and free-text cron — M10 (spec §9.3).
- Core plugins — deferred by owner (2026-08-27); the scheduled-path
  end-to-end test runs with whatever plugins are discovered.
- Plugin contract suite changes — M9 touches neither plugin host nor
  plugins; the full suite (which includes the contract tests) runs in the
  gate regardless.

## 7. Decision records

`docs/decisions.md` entries to add during implementation:

1. Uniform overlap semantics via `max_instances=2` + LockRegistry, with the
   APScheduler 3.11.3 source verification noted.
2. Startup reconciliation of crash-orphaned runs (owner-approved; spec
   silent).
3. Amendment to the M2 manual-trigger decision: strong task references.
4. Seam-level cron-fire verification rationale (no real-timer test).

## 8. Dependencies

None added. APScheduler remains pinned at `3.11.3`; behavior claims verified
against the installed 3.11.3 source (`schedulers/base.py`: default
`max_instances=1`, `MaxInstancesReachedError` skip path).
