# State & Checkpoint Contract

## Purpose

This cross-cutting contract defines how pipeline state is persisted, recovered, and
resumed. It applies uniformly to ALL pipeline steps (01–05) and governs how `report_progress`
calls translate into durable checkpoints in Lakebase.

The system provides two guarantees:

1. **Durability** — Every `report_progress(status="completed")` is persisted to Lakebase
   within the same tool execution. If the browser refreshes, the process restarts, or the
   session switches from App to Genie Code, no completed work is lost.

2. **Resumability** — On restart, the pipeline reads the last durable checkpoint and
   provides `RESUME_CONTEXT` to the LLM, which verifies artifacts and skips completed phases.

---

## 1. Checkpoint Semantics

Every `report_progress` call with `status: "completed"` is a **DURABLE CHECKPOINT**.

The system persists to Lakebase:

```text
run_id, step_name, phase_id, phase_name, status, current_task,
progress_pct, stats (JSONB), happenings (JSONB), findings (JSONB),
started_at, completed_at
```

Once a phase is checkpointed as completed, it will NOT be re-executed on resume
unless the entire step is restarted from scratch.

### Checkpoint Granularity

```text
Step level:  step_started → step_completed   (coarse — 6 per run)
Phase level: report_progress completed       (fine — 4-6 per step, ~30 per run)
```

Phases are the **resume unit**. Steps are the **restart unit**.

---

## 2. Persistence Architecture

### Write Path (every event)

```text
LLM calls report_progress / tool
       │
       ▼
agent_event_bridge (pipeline.py)
       │ emits phase_update / tool_completed / tool_failed
       ▼
pipeline_routes.py event_callback
       │
       ├──► In-memory _runs dict       (fast path — serves status polling)
       │
       └──► StateStore.persist_*()     (durable path — Lakebase write-through)
            │
            ├── upsert_phase()         (phases table — rich fields)
            ├── append_tool_call()     (tool_calls table)
            └── update_run_status()    (runs table — progress_pct, current_step)
```

### Read Path (on refresh / recovery)

```text
Browser refreshes → GET /api/pipeline/run/<run_id>/status
       │
       ▼
┌─────────────────────────────────────────┐
│  run_id in _runs (in-memory)?           │
│       │                                 │
│  YES ──► Return from memory (fast)      │
│       │                                 │
│  NO  ──► Query Lakebase:                │
│           SELECT * FROM runs            │
│           + steps + phases + tool_calls  │
│           WHERE run_id = ?              │
│              │                           │
│         Found? ── YES ──► Hydrate _runs │
│              │             Return        │
│         NO ──► Return 404               │
└─────────────────────────────────────────┘
```

### Multi-Worker Safety

With `workers > 1`, Lakebase is the **sole source of truth**. In-memory `_runs` is
a per-worker cache that may be stale. The status endpoint ALWAYS falls back to
Lakebase when the in-memory cache misses.

### Lakebase Availability

```text
At pipeline start:
  Lakebase unavailable → ❌ EXECUTION HALTED (state persistence required)

Mid-run:
  Lakebase write fails → Retry with exponential backoff (3 attempts)
  3 consecutive failures → ❌ EXECUTION HALTED
```

---

## 3. Lakebase Schema

### Existing Tables (enhanced)

```sql
-- runs: add progress_pct, current_step, run_manifest
ALTER TABLE runs ADD COLUMN IF NOT EXISTS progress_pct INT DEFAULT 0;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS current_step TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS run_manifest JSONB;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- phases: add rich report_progress fields
ALTER TABLE phases ADD COLUMN IF NOT EXISTS phase_id TEXT;
ALTER TABLE phases ADD COLUMN IF NOT EXISTS current_task TEXT;
ALTER TABLE phases ADD COLUMN IF NOT EXISTS progress_pct INT DEFAULT 0;
ALTER TABLE phases ADD COLUMN IF NOT EXISTS stats JSONB;
ALTER TABLE phases ADD COLUMN IF NOT EXISTS happenings JSONB;
ALTER TABLE phases ADD COLUMN IF NOT EXISTS findings JSONB;
ALTER TABLE phases ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- steps: add duration_s
ALTER TABLE steps ADD COLUMN IF NOT EXISTS duration_s FLOAT;
ALTER TABLE steps ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
```

### New Table: tool_calls

```sql
CREATE TABLE IF NOT EXISTS tool_calls (
    id           BIGSERIAL PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES runs(run_id),
    step_name    TEXT NOT NULL,
    tool_name    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',
    args_summary TEXT,
    error        TEXT,
    duration_ms  INT,
    started_at   TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_run_step
    ON tool_calls(run_id, step_name, started_at DESC);
```

### TTL Cleanup

Tool calls and events older than 30 days are eligible for cleanup:

```sql
DELETE FROM tool_calls WHERE started_at < NOW() - INTERVAL '30 days';
DELETE FROM events WHERE created_at < NOW() - INTERVAL '30 days';
```

This can be run as a scheduled job or triggered from the Admin page.

---

## 4. Resume Contract (LLM Behavior)

When a run resumes after interruption (refresh, crash, rerun), the system
provides `RESUME_CONTEXT` in the agent's system message.

### What the LLM receives:

```text
RESUME_CONTEXT:
  run_id: <uuid>
  last_completed_step: create_metric_views
  last_completed_phase: validate_metric_views
  current_step: create_dashboards (restarting from beginning of step)
  artifacts_written:
    - erd_parsed.yaml
    - semantic_model.yaml
    - data_layer_validation.yaml
    - schema_profile.yaml
    - metric_view_design.yaml
    - metric_view_validation.yaml
  prior_findings:
    - "8 tables created"
    - "3 metric views validated PASS"
```

### What the LLM MUST do:

1. **VERIFY** prior artifacts exist (ONE `read_workspace_file` per artifact, or
   ONE batched SQL to check tables exist)
2. If artifact exists and is valid → **SKIP** that phase, call `report_progress`
   with `status: "completed"` immediately (replay the checkpoint)
3. If artifact is MISSING or CORRUPT → re-execute that phase from scratch
4. **NEVER** re-execute a phase whose output artifact already exists and
   is structurally valid

### What the LLM MUST NOT do:

- Re-parse the ERD if `erd_parsed.yaml` exists with correct table count
- Re-generate DDL if tables already exist in catalog with correct columns
- Re-generate synthetic data if tables have rows > 0
- Re-create metric views if they already exist in catalog
- Re-create dashboards if manifest shows a valid `dashboard_id`
- Re-create Genie space if manifest shows a valid `space_id`

---

## 5. Artifact-as-State

Each phase produces a durable artifact. The artifact IS the state:

| Phase | Artifact | Verification |
|-------|----------|-------------|
| parse_erd | erd_parsed.yaml | file exists + tables array non-empty |
| build_semantic_model | semantic_model.yaml | file exists |
| generate_ddl | Tables in catalog | `SHOW TABLES LIKE '%_vN'` returns expected count |
| generate_synthetic_data | Row count > 0 | `SELECT COUNT(*) > 0` for each table |
| validate_data | data_layer_validation.yaml | file exists |
| profile_schema | schema_profile.yaml | file exists |
| map_kpis | kpi_metric_mapping.yaml | file exists |
| design_metric_views | metric_view_design.yaml | file exists |
| generate_metric_views | Metric views in catalog | `SHOW VIEWS` returns expected names |
| validate_metric_views | metric_view_validation.yaml | file exists |
| design_dashboard | dashboard_design.yaml | file exists |
| create_dashboard | *_manifest.json | file exists + contains dashboard_id |
| create_genie_space | *_manifest.json | file exists + contains space_id |
| generate_documentation | readme.md | file exists |

---

## 6. Idempotency Rules

### CREATE IF NOT EXISTS semantics:

- **Tables**: `CREATE TABLE IF NOT EXISTS` (DDL is already idempotent)
- **Metric Views**: `CREATE OR REPLACE` (always safe to re-apply)
- **Dashboards**: Check manifest for `dashboard_id` → update existing if found
- **Genie Spaces**: Check manifest for `space_id` → update existing if found
- **Files**: Always overwrite (`write_workspace_file` is idempotent)

### Row data:

- If table exists with rows > 0 → do NOT regenerate synthetic data
- If table exists with rows = 0 → regenerate

---

## 7. Progress Reporting as State Machine

Each phase follows this state machine:

```text
  ┌─────────┐    report_progress     ┌─────────┐
  │ PENDING │ ──── started ────────► │ RUNNING │
  └─────────┘                        └────┬────┘
                                          │
                              report_progress completed
                                          │
                                          ▼
                                     ┌──────────┐
                                     │COMPLETED │ ← durable checkpoint
                                     └──────────┘

  On failure: report_progress status="failed"
  On resume: system provides RESUME_CONTEXT, agent verifies + replays
```

### report_progress Field Mapping to Lakebase

| report_progress field | Lakebase column | Table |
|---|---|---|
| phase_id | phases.phase_id | phases |
| phase_name | phases.phase_name | phases |
| status | phases.status | phases |
| current_task | phases.current_task | phases |
| progress_pct | phases.progress_pct | phases |
| stats | phases.stats (JSONB) | phases |
| happenings | phases.happenings (JSONB) | phases |
| findings | phases.findings (JSONB) | phases |

---

## 8. Genie Code Compatibility

The artifact-as-state contract works **identically** in App mode and Genie Code.
The difference is only WHERE state is persisted:

| Concern | App Mode | Genie Code |
|---------|----------|------------|
| run_id generation | `pipeline_routes.py` generates UUID | LLM generates UUID via `execute_python(uuid4())` |
| State storage | Lakebase (phases table) + workspace files | Workspace files ONLY (`run_context.yaml` + artifacts) |
| Resume trigger | `RESUME_CONTEXT` injected in system message | LLM reads `run_context.yaml` from output folder |
| Progress reporting | `report_progress` → event_callback → Lakebase | `report_progress` → rendered inline (no persistence) |
| Phase verification | Same artifact checks (SHOW TABLES, file exists) | Same artifact checks (SHOW TABLES, file exists) |

**In Genie Code, there is no Lakebase, no HTTP endpoints, no background threads.**
Everything is prompt-driven. The LLM IS the runtime.

### run_context.yaml — The Genie Code State File

At the start of each run, the LLM writes a `run_context.yaml` file in the output folder.
This file IS the run's identity and progress tracker:

```yaml
# Written by the LLM at the start of a new run
# Updated at each phase boundary (report_progress completed)
run_id: "550e8400-e29b-41d4-a716-446655440000"
domain: member_claims
version: 2                    # from version_registry.yaml resolution
version_suffix: "_v2"         # derived: "_v{version}"
created_by: genie_code        # app | genie_code
started_at: "2024-01-15T10:00:00Z"
current_step: create_data_layer
status: running               # running | completed | failed
phases_completed:
  - step: create_data_layer
    phase: parse_erd
    completed_at: "2024-01-15T10:02:30Z"
  - step: create_data_layer
    phase: build_semantic_model
    completed_at: "2024-01-15T10:05:12Z"
  - step: create_data_layer
    phase: generate_ddl
    completed_at: "2024-01-15T10:08:45Z"
findings:
  - "8 tables created from ERD"
  - "All FK relationships validated"
```

### Genie Code Execution Flow

```text
1. User pastes step prompt (e.g., 01_create_data_layer.md)
2. LLM reads accelerator.yaml → resolves output base path
3. LLM reads version_registry.yaml from domain root:
   a. If no registry or no genie_code entry with status=running:
      - FRESH RUN: compute NEXT_VERSION = max(all versions) + 1
      - Create output folder v{N}, generate run_id, initialize run_context.yaml
      - Register new entry in version_registry.yaml (created_by: genie_code)
   b. If genie_code entry with status=running exists:
      - RESUME: use that version number
      - Navigate to its output folder, read run_context.yaml
4. Verify artifacts (one cheap check per phase)
5. Skip verified phases, execute from first gap
6. After each phase: update run_context.yaml
7. After all phases: update run_context.yaml status=completed,
   update version_registry.yaml status=completed
```

### Genie Code Resume Flow (Same-Environment Only)

```text
1. User re-opens same step prompt (same or new conversation)
2. LLM reads version_registry.yaml:
   - Finds entry with created_by=genie_code AND status=running → RESUME
   - Uses that version number to locate the output folder
3. LLM reads run_context.yaml from that folder:
   - Gets run_id (for traceability)
   - Gets phases_completed list
   - Gets current_step (where it was when interrupted)
4. LLM verifies artifacts (one cheap check per phase)
5. Skip verified phases, resume from first missing artifact
6. Update run_context.yaml as each phase completes
```

**Important:** If an App-created version is `running` in the registry, Genie Code
does NOT resume it. It creates a new version instead. The App's partial work stays
untouched for the App to resume later.

### Genie Code Multi-Step Continuation

When the user moves to the next step (e.g., from 01 to 02), the LLM:

1. Reads `version_registry.yaml` → finds its own running version
2. Navigates to that version's output folder
3. Reads the EXISTING `run_context.yaml` (carries the same run_id forward)
4. Appends new phases to `phases_completed` as step 02 executes
5. Updates `current_step` to the new step name

This gives a continuous run_id across all steps in a single "run," even across
multiple Genie Code conversations.

### What report_progress Does in Genie Code

In App mode, `report_progress` is intercepted by the event_callback and persisted to Lakebase.
In Genie Code, `report_progress` has no backend listener — but the LLM still calls it because:

1. It serves as a **self-structuring checkpoint** (forces the LLM to think in phases)
2. The prompt contract says to call it (consistent behavior across environments)
3. The LLM updates `run_context.yaml` immediately after each completed phase

The `run_context.yaml` update IS the durable checkpoint in Genie Code.

### Genie Code State Recovery (User Asks "What's my run status?")

```text
User: "What's the status of my member_claims pipeline?"

LLM:
1. Read run_context.yaml from the output folder
2. Report: run_id, status, phases_completed, current_step
3. If status=running but no conversation is active → it was interrupted
4. Offer: "Would you like to resume from phase X?"
```

### Version Registry Integration

The `version_registry.yaml` (in the domain root, NOT inside a version folder) coordinates
version numbering across App and Genie Code. See `00_master_prompt.md` Step 0.3 for the
full schema and resolution algorithm.

**Key principle: Resume ONLY within the same environment.**
- App resumes App's incomplete runs. Genie Code resumes Genie Code's incomplete runs.
- Cross-environment always creates a NEW version (never resumes the other's partial work).
- A partial version from the other environment is NOT inconsistent — it's just incomplete,
  and can be resumed by its original environment later or cleaned up.

Key interaction with `run_context.yaml`:

```text
version_registry.yaml        run_context.yaml
(domain root)                (inside OUTPUT_FOLDER/vN/)
┌───────────────────────┐  ┌───────────────────────┐
│ Which version to use?     │  │ Where inside that version   │
│ Resume MY v2 or create v3?│  │ to resume from?             │
│                           │  │                             │
│ Answers: version number,  │  │ Answers: run_id, current    │
│ who created, status       │  │ step, phases_completed      │
└───────────────────────┘  └───────────────────────┘
```

The resolution order on any run start:
1. Read `version_registry.yaml` → determine version number:
   - If MY incomplete version exists (same `created_by`) → resume it
   - Otherwise → create next version (max + 1)
2. Navigate to `OUTPUT_FOLDER/v{N}/`
3. Read `run_context.yaml` → determine phase-level resume point
4. Verify artifacts → skip completed phases

---

## 9. Frontend State Persistence

The browser persists `run_id` across refresh:

```javascript
// On pipeline start:
history.replaceState(null, '', `?run_id=${runId}`);
localStorage.setItem('last_run_id', runId);

// On page load:
const params = new URLSearchParams(window.location.search);
const savedRunId = params.get('run_id') || localStorage.getItem('last_run_id');
if (savedRunId) { currentRunId = savedRunId; startPolling(); }
```

On refresh, the poll hits the status endpoint → backend checks in-memory first,
then falls back to Lakebase → returns full state → UI hydrates normally.

---

## 10. Implementation Checklist

### Backend (pipeline_routes.py + state_store.py)

- [ ] Enhance `phases` table DDL (add phase_id, current_task, progress_pct, stats, happenings, findings)
- [ ] Create `tool_calls` table DDL
- [ ] StateStore: `persist_phase_update(run_id, step, phase_data)` — called on every phase_update event
- [ ] StateStore: `persist_tool_call(run_id, step, tool_data)` — called on tool_started/completed/failed
- [ ] StateStore: `load_run_full(run_id)` — returns runs + steps + phases + tool_calls (for recovery)
- [ ] Status endpoint: fallback to `load_run_full()` when `_runs[run_id]` is missing
- [ ] Wire event_callback: after in-memory update, call `state_store.persist_*()` (non-blocking)
- [ ] Pipeline start: block if `health_check()` fails

### Frontend (pipeline_monitor.html)

- [ ] Store `run_id` in URL query param on pipeline start
- [ ] On page load: read `run_id` from URL → start polling immediately
- [ ] On poll response: hydrate STEPS, substeps, activities from server state

### Setup (setup_lakebase.py)

- [ ] Add ALTER TABLE statements for enhanced columns
- [ ] Add CREATE TABLE for tool_calls
- [ ] Add index on tool_calls(run_id, step_name, started_at DESC)

### Prompts (cross-cutting)

- [ ] Reference this contract from 00_master_prompt.md system message injection
- [ ] agent_loop.py: inject RESUME_CONTEXT when resume_from is provided

---

## 11. Critical Tool Failure Contract

Certain tool failures leave the system in an **inconsistent state** that downstream
phases cannot recover from. When these fail, you MUST halt immediately — do NOT
adapt, skip, or retry with alternative approaches.

### Critical Tools (single failure = HALT)

| Tool | Why Critical | Exception |
|------|-------------|----------|
| `execute_sql` | DDL/DML creates schemas, tables, views | SELECT/SHOW/DESCRIBE are non-critical (read-only) |
| `execute_python` | Generates YAML artifacts and configs needed downstream | — |
| `execute_notebook` | ETL/data generation notebooks produce required data | — |
| `create_notebook` | Can't create = can't execute = missing output | — |
| `write_file` | Produces artifacts that later phases depend on | — |
| `create_dashboard` | Step's primary deliverable | — |
| `create_genie_space` | Step's primary deliverable | — |

### Critical Error Patterns (any tool = HALT)

- `PermissionDenied` or `PERMISSION_DENIED`
- `RESOURCE_EXHAUSTED` or `QUOTA_EXCEEDED`
- `INTERNAL_ERROR` (server-side failure)

### On Critical Failure

1. **DO NOT** call the next phase's tools
2. **DO NOT** attempt alternative approaches to work around the failure
3. **DO** call `report_progress(status="failed", ...)` with the error details
4. **DO** call `report_step_complete(status="failed", summary="Critical failure in {tool}: {error}")` 
5. **DO** update `run_context.yaml` with `status: failed` and the error

This rule applies **identically in App mode and Genie Code**. In App mode,
the agent loop enforces it programmatically. In Genie Code, the LLM must
self-enforce by following this contract.

### Non-Critical Failures (adapt allowed)

- `read_file` returning "file not found" (legitimate check-before-create)
- `execute_sql` with SELECT/SHOW/DESCRIBE (informational queries)
- `report_progress` itself failing (cosmetic, not state-critical)
- `describe_table` failing (table may not exist yet)

For non-critical failures: retry once, then adapt or skip.

---

## 12. Non-Negotiable Rules

1. **`report_progress(status="completed")` is durable.** The system guarantees persistence.
2. **Never re-execute a phase whose artifact exists and is valid.**
3. **Verify before skipping.** Always confirm the artifact exists (one cheap check).
4. **Lakebase is the source of truth.** In-memory state is a cache.
5. **Block on Lakebase unavailability at start.** Mid-run: retry 3x then halt.
6. **Same behavior in App and Genie Code.** State is environment-agnostic.
7. **Tool calls are persisted for debuggability.** All calls, not just failures.
8. **TTL cleanup at 30 days.** Tool calls and events are transient diagnostic data.
9. **Steps restart from the beginning.** Phases within a completed step are never partially replayed.
10. **run_id survives browser refresh.** URL query param is the primary mechanism.
11. **Critical tool failures halt immediately.** See Section 11 above.