# Phase 3: Durable State & Real-Time Streaming Architecture

## Status: DRAFT — Pending Review

---

## 1. Problem Statement

The current architecture has three durability and performance issues:

| Issue | Impact |
| --- | --- |
| In-memory `_runs` dict is lost on app restart/redeploy | Orphaned runs show as "failed" with no detail; UI loses all progress |
| Delta tables for state (pipeline_runs, pipeline_run_steps, pipeline_run_phases) have high write latency | Each phase transition = 1 SQL statement via Statement API (~200-500ms); 15 phases × 2 transitions = 30+ round-trips per run |
| UI polls `/status/<run_id>` every 2 seconds | Expensive compute (SQL warehouse hit per poll if in-memory miss); not scalable for concurrent users |

## 2. Target Architecture

```
                         DATABRICKS APP
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│                     Pipeline execution                       │
│                            │                                 │
│                            │ _emit()                         │
│                            ▼                                 │
│                 ┌────────────────────┐                       │
│                 │ Pipeline callback  │                       │
│                 └─────────┬──────────┘                       │
│                           │                                  │
│                    ┌──────┴────────┐                         │
│                    │               │                         │
│                    ▼               ▼                         │
│               Lakebase       queue.Queue                     │
│             durable state     transient event                │
│                    │               │                         │
│                    │               ▼                         │
│                    │          SSE endpoint                   │
│                    │               │                         │
└────────────────────┼───────────────┼─────────────────────────┘
                     │               │
                     │               │ push
                     │               ▼
                     │            Browser
                     │
                     │ read only:
                     │
                     ├── initial page load
                     ├── page refresh
                     ├── SSE reconnect
                     └── version gap
```

### Core Principles

1. **Lakebase is the single source of truth** — all run/step/phase state lives in Postgres, not in app memory or Delta tables
2. **SSE is fire-and-forget** — the in-memory queue only buffers events for connected browsers; no durability requirement
3. **No polling** — the UI never polls on a timer; it uses SSE for live updates and Lakebase reads only on specific triggers
4. **Crash-safe** — if the app restarts mid-run, state is fully recoverable from Lakebase; the pipeline resumes from the last persisted phase

---

## 3. Lakebase Schema Design

### 3.1 Database & Connection

- **Project:** `aibi-studio` (created via Lakebase API)
- **Branch:** `main`
- **Database:** `pipeline_state`
- **Connection:** App connects via the Lakebase Data API (HTTP) or native Postgres driver using SP OAuth token

### 3.2 Tables

```sql
-- Runs: one row per pipeline execution
CREATE TABLE runs (
    run_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain         TEXT NOT NULL,
    run_mode       TEXT NOT NULL DEFAULT 'versioned',  -- 'versioned' | 'clean'
    version        INT,
    version_suffix TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',    -- pending | running | completed | failed | cancelled
    total_steps    INT NOT NULL DEFAULT 6,
    steps_completed INT NOT NULL DEFAULT 0,
    current_step   TEXT,
    progress_pct   INT NOT NULL DEFAULT 0,
    error          TEXT,
    error_detail   TEXT,
    config_json    JSONB,         -- full config snapshot for rerun
    started_at     TIMESTAMPTZ DEFAULT now(),
    completed_at   TIMESTAMPTZ,
    duration_s     FLOAT,
    event_seq      BIGINT NOT NULL DEFAULT 0,  -- monotonic event counter (for gap detection)
    created_at     TIMESTAMPTZ DEFAULT now(),
    updated_at     TIMESTAMPTZ DEFAULT now()
);

-- Steps: one row per step per run
CREATE TABLE steps (
    run_id         UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    step_name      TEXT NOT NULL,
    step_index     INT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    started_at     TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ,
    duration_s     FLOAT,
    error          TEXT,
    error_detail   TEXT,
    suggestion     TEXT,
    artifacts      JSONB DEFAULT '[]'::jsonb,
    retry_count    INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ DEFAULT now(),
    updated_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (run_id, step_name)
);

-- Phases: one row per phase per step per run
CREATE TABLE phases (
    run_id         UUID NOT NULL,
    step_name      TEXT NOT NULL,
    phase_name     TEXT NOT NULL,
    phase_index    INT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    started_at     TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ,
    duration_ms    BIGINT,
    error          TEXT,
    error_detail   TEXT,
    artifacts      JSONB DEFAULT '[]'::jsonb,
    retry_count    INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ DEFAULT now(),
    updated_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (run_id, step_name, phase_name),
    FOREIGN KEY (run_id, step_name) REFERENCES steps(run_id, step_name) ON DELETE CASCADE
);

-- Event log: append-only log for SSE replay on reconnect
CREATE TABLE events (
    event_id       BIGSERIAL PRIMARY KEY,
    run_id         UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    event_type     TEXT NOT NULL,        -- step_started, phase_completed, log, etc.
    event_data     JSONB NOT NULL,
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- Index for fast event replay
CREATE INDEX idx_events_run_seq ON events(run_id, event_id);

-- Index for active runs lookup
CREATE INDEX idx_runs_status ON runs(status) WHERE status IN ('running', 'pending');

-- Step logs: per-step log accumulator
CREATE TABLE step_logs (
    run_id         UUID NOT NULL,
    step_name      TEXT NOT NULL,
    log_text       TEXT NOT NULL DEFAULT '',
    updated_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (run_id, step_name),
    FOREIGN KEY (run_id, step_name) REFERENCES steps(run_id, step_name) ON DELETE CASCADE
);
```

### 3.3 Why Lakebase Over Delta Tables

| Dimension | Delta (current) | Lakebase (proposed) |
| --- | --- | --- |
| Write latency | 200-500ms per statement via Statement API | 1-5ms per INSERT/UPDATE via Postgres wire protocol |
| Concurrency | Single writer (Statement API serializes) | Full MVCC, multiple concurrent writers |
| Read latency | 500ms-2s (warehouse spin-up, query planning) | 1-10ms (connection pooled) |
| Schema enforcement | Loose (string columns for everything) | Strict (UUID, TIMESTAMPTZ, JSONB, FK constraints) |
| Crash recovery | Manual orphan detection on startup | Transactions — incomplete writes are rolled back |
| Operational cost | Warehouse DBUs for every read/write | Included in Lakebase (scales to zero) |

---

## 4. State Management Layer

### 4.1 `StateStore` — Replaces `RunStore`

```python
class StateStore:
    """Durable state backed by Lakebase Postgres.
    
    Replaces: RunStore (Delta), _runs dict (in-memory), step_data dict.
    Connection: Lakebase Data API or psycopg with SP OAuth.
    """
    
    def create_run(self, run_id, domain, ...) -> None
    def update_run(self, run_id, **fields) -> None
    def get_run(self, run_id) -> dict           # Full run + steps + phases
    
    def upsert_step(self, run_id, step_name, **fields) -> None
    def upsert_phase(self, run_id, step_name, phase_name, **fields) -> None
    
    def append_event(self, run_id, event_type, event_data) -> int  # Returns event_id
    def get_events_since(self, run_id, after_event_id) -> list     # For SSE replay
    
    def append_log(self, run_id, step_name, line: str) -> None
    def get_step_log(self, run_id, step_name) -> str
    
    def get_active_runs(self) -> list        # For crash recovery
    def get_resume_point(self, run_id) -> dict  # First non-completed phase
```

### 4.2 Write Path (Pipeline Callback)

```python
def event_callback(event):
    # 1. Write durable state to Lakebase (1-5ms)
    if event.event_type == "step_started":
        state_store.upsert_step(run_id, step, status='running')
        state_store.update_run(run_id, current_step=step, status='running')
    elif event.event_type == "phase_completed":
        state_store.upsert_phase(run_id, step, phase, status='completed', duration_ms=...)
    # ... etc
    
    # 2. Append to event log (for SSE replay)
    event_id = state_store.append_event(run_id, event.event_type, event.data)
    
    # 3. Push to transient SSE queue (fire-and-forget, in-memory)
    q = _event_queues.get(run_id)
    if q:
        q.put({**event.data, 'type': event.event_type, 'event_id': event_id})
```

### 4.3 Read Path (UI)

| Trigger | Action | Source |
| --- | --- | --- |
| Initial page load | `GET /api/pipeline/state/{run_id}` | Lakebase (single query joins runs+steps+phases) |
| SSE connected | Events stream in real-time | In-memory queue |
| SSE reconnects (browser tab returns) | `GET /api/pipeline/events/{run_id}?after={last_event_id}` | Lakebase events table (replay missed events) |
| Page refresh | Same as initial page load | Lakebase |

**No 2-second polling.** The UI maintains its state purely from:
1. The initial Lakebase read (full snapshot)
2. SSE events (incremental updates)
3. Gap-fill on reconnect (missed events from Lakebase)

---

## 5. SSE Event Protocol

### 5.1 Event Envelope

Each SSE event includes an `event_id` (monotonically increasing per run) for gap detection:

```json
{"event_id": 47, "type": "phase_completed", "step": "create_data_layer", "phase": "generate_ddl", "duration_ms": 12345}
```

### 5.2 Gap Detection (Client-Side)

```javascript
let lastEventId = 0;

evtSource.onmessage = function(event) {
    const data = JSON.parse(event.data);
    
    // Gap detected — missed events (e.g., tab was backgrounded)
    if (data.event_id > lastEventId + 1) {
        fetchMissedEvents(lastEventId);  // GET /api/pipeline/events/{runId}?after={lastEventId}
    }
    
    lastEventId = data.event_id;
    handleEvent(data);
};
```

### 5.3 SSE Reconnect

When `EventSource` reconnects after a disconnect:
1. Browser fires `onopen`
2. Client sends `GET /api/pipeline/events/{runId}?after={lastEventId}` to get missed events
3. Apply missed events in order, then resume streaming

---

## 6. Crash Recovery

### 6.1 App Restart During Active Run

**Current behavior:** `recover_orphaned_runs()` marks stuck runs as "failed" — destructive.

**New behavior:**

```python
def on_startup():
    active_runs = state_store.get_active_runs()  # status IN ('running', 'pending')
    for run in active_runs:
        resume_point = state_store.get_resume_point(run['run_id'])
        if resume_point:
            # Auto-resume from last completed phase
            _resume_pipeline(run['run_id'], resume_point)
        else:
            # All phases complete but run not finalized — just mark complete
            state_store.update_run(run['run_id'], status='completed')
```

Because Lakebase persists every phase completion, the exact point of failure is known. The pipeline can resume from the last durable checkpoint without re-running completed work.

### 6.2 Pipeline Execution Guarantees

| Scenario | Behavior |
| --- | --- |
| App crashes during phase execution | Phase stays `running` in Lakebase; on restart, detected and re-executed |
| App crashes between phases | Previous phase is `completed`; next phase is `pending`; resume from next |
| App crashes during Lakebase write | Postgres transaction not committed; phase state unchanged; safe to retry |
| SSE queue lost on crash | No data loss — events are in Lakebase; clients reconnect and replay |

---

## 7. API Changes

### 7.1 New Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/pipeline/state/{run_id}` | Full run snapshot (runs + steps + phases) from Lakebase |
| GET | `/api/pipeline/events/{run_id}?after={event_id}` | Event replay for gap-fill |
| GET | `/api/pipeline/logs/{run_id}/{step_name}` | Step logs from Lakebase (already exists, now backed by Postgres) |

### 7.2 Deprecated Endpoints

| Method | Path | Replacement |
| --- | --- | --- |
| GET | `/api/pipeline/status/{run_id}` | `/api/pipeline/state/{run_id}` (Lakebase-backed, no in-memory) |
| GET | `/api/pipeline/runs/{run_id}` | `/api/pipeline/state/{run_id}` (same endpoint for live + historical) |

### 7.3 Retained Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/pipeline/stream/{run_id}` | SSE — unchanged; queue still in-memory |
| POST | `/api/pipeline/run` | Unchanged |
| POST | `/api/pipeline/rerun/{run_id}` | Now reads resume point from Lakebase |
| POST | `/api/pipeline/cancel/{run_id}` | Unchanged |

---

## 8. Migration Path

### 8.1 Phase 3a: Lakebase Provisioning (Setup Job + Admin UI Trigger)

Lakebase is **not a DABs-supported resource** — it cannot be declared in `databricks.yml`.
Instead, provisioning is automated via a **setup job task** (notebook using `w.postgres.*` SDK),
triggered from the **Admin UI** as a menu action.

#### Why a Setup Job?

| Approach | Verdict |
| --- | --- |
| DABs resource | Not supported — no `resources.lakebase` block exists |
| Direct API call from app | App SP may lack permissions; no compute for SDK calls |
| App `on_startup()` auto-create | Slow first boot; unclear failure UX |
| **Setup job task + Admin UI trigger** | Runs on proper compute, has admin credentials, fits existing pattern (`setup_app_permissions`), triggered on demand |

#### Architecture

```
┌────────────────────────────┐     ┌───────────────────────────────┐
│     Admin UI               │     │     Databricks Jobs          │
│                            │     │                               │
│  Settings > Setup          │     │  aibi-studio-setup           │
│  ─────────────────────  │     │                               │
│                            │     │  Tasks:                       │
│  [Run Setup]  ───────────┼─────►  1. grant_workspace_access   │
│                            │     │  2. grant_uc_access           │
│  Status:                   │     │  3. setup_metadata_tables    │
│  ● Lakebase: Connected     │     │  4. setup_lakebase    ◀─ NEW  │
│  ● UC Perms: Granted      │     │                               │
│  ● Metadata: Ready        │     └───────────────────────────────┘
│                            │
└────────────────────────────┘
```

#### Job Definition (added to `resources/aibi.job.yml`)

Consolidate all setup into a single job with dependent tasks:

```yaml
resources:
  jobs:
    setup_app_infrastructure:
      name: "aibi-studio-setup"
      description: "One-time workspace setup: permissions, metadata, and Lakebase provisioning."
      tags:
        project: aibi-studio
        purpose: infrastructure-setup

      parameters:
        - name: app_name
          default: ${var.app_name}
        - name: project_folder
          default: ${var.deploy_root}
        - name: app_sp_id
          default: ${var.app_sp_application_id}
        - name: catalog_name
          default: ${var.catalog_name}
        - name: metadata_schema
          default: ${var.metadata_schema}
        - name: lakebase_project_id
          default: "aibi-studio"

      tasks:
        # Existing tasks (parallel)
        - task_key: grant_workspace_folder_access
          notebook_task:
            notebook_path: "../notebooks/setup_permissions.py"
            base_parameters:
              app_name: "{{job.parameters.app_name}}"
              project_folder: "{{job.parameters.project_folder}}"

        - task_key: grant_uc_catalog_access
          notebook_task:
            notebook_path: "../notebooks/setup_uc_permissions.py"
            base_parameters:
              sp_id: "{{job.parameters.app_sp_id}}"
              catalog_name: "{{job.parameters.catalog_name}}"
              metadata_schema: "{{job.parameters.metadata_schema}}"

        - task_key: setup_metadata_tables
          notebook_task:
            notebook_path: "../notebooks/setup_metadata_tables.sql"
            base_parameters:
              catalog: "{{job.parameters.catalog_name}}"
              schema: "{{job.parameters.metadata_schema}}"

        # NEW: Lakebase provisioning (depends on UC perms for SP role grant)
        - task_key: setup_lakebase
          depends_on:
            - task_key: grant_uc_catalog_access
          notebook_task:
            notebook_path: "../notebooks/setup_lakebase.py"
            base_parameters:
              project_id: "{{job.parameters.lakebase_project_id}}"
              app_sp_id: "{{job.parameters.app_sp_id}}"
              catalog_name: "{{job.parameters.catalog_name}}"
              metadata_schema: "{{job.parameters.metadata_schema}}"

      queue:
        enabled: true
```

#### Setup Notebook (`notebooks/setup_lakebase.py`)

```python
# Databricks notebook: setup_lakebase
# Creates a small Lakebase instance for pipeline durable state.
# Idempotent — safe to run multiple times.

dbutils.widgets.text("project_id", "aibi-studio")
dbutils.widgets.text("app_sp_id", "")
dbutils.widgets.text("catalog_name", "")
dbutils.widgets.text("metadata_schema", "")

project_id = dbutils.widgets.get("project_id")
app_sp_id = dbutils.widgets.get("app_sp_id")
catalog_name = dbutils.widgets.get("catalog_name")
metadata_schema = dbutils.widgets.get("metadata_schema")

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.postgres import (
    Project, ProjectSpec, Role, RoleRoleSpec, RoleIdentityType,
)

w = WorkspaceClient()
branch_id = "production"  # Auto-created with project
db_name = "pipeline_state"

# ── Step 1: Create project (idempotent) ──────────────────────────
try:
    project = w.postgres.get_project(name=f"projects/{project_id}")
    print(f"✓ Project '{project_id}' already exists")
except Exception:
    print(f"Creating Lakebase project '{project_id}'...")
    op = w.postgres.create_project(
        project=Project(spec=ProjectSpec(
            display_name="AI/BI Studio State Store",
            pg_version=17,
        )),
        project_id=project_id,
    )
    project = op.wait()
    print(f"✓ Project created: {project.name}")

# ── Step 2: Get endpoint host ────────────────────────────────────
endpoints = list(w.postgres.list_endpoints(
    parent=f"projects/{project_id}/branches/{branch_id}"
))
endpoint_host = endpoints[0].status.hosts.host
print(f"✓ Endpoint host: {endpoint_host}")

# ── Step 3: Create database (idempotent) ─────────────────────────
try:
    w.postgres.get_database(
        name=f"projects/{project_id}/branches/{branch_id}/databases/{db_name}"
    )
    print(f"✓ Database '{db_name}' already exists")
except Exception:
    from databricks.sdk.service.postgres import Database, DatabaseSpec
    w.postgres.create_database(
        parent=f"projects/{project_id}/branches/{branch_id}",
        database=Database(spec=DatabaseSpec()),
        database_id=db_name,
    ).wait()
    print(f"✓ Database '{db_name}' created")

# ── Step 4: Create schema tables via Data API ────────────────────
# (Uses w.postgres SDK or psycopg connection to run DDL)
print("Creating schema tables...")
# DDL statements from Section 3.2 of design doc
# CREATE TABLE IF NOT EXISTS runs (...)
# CREATE TABLE IF NOT EXISTS steps (...)
# CREATE TABLE IF NOT EXISTS phases (...)
# CREATE TABLE IF NOT EXISTS events (...)
# CREATE TABLE IF NOT EXISTS step_logs (...)
print("✓ Schema tables created")

# ── Step 5: Grant App SP role ────────────────────────────────────
if app_sp_id:
    role_id = f"app-sp-{app_sp_id[:8]}"
    try:
        w.postgres.get_role(
            name=f"projects/{project_id}/branches/{branch_id}/roles/{role_id}"
        )
        print(f"✓ SP role '{role_id}' already exists")
    except Exception:
        w.postgres.create_role(
            parent=f"projects/{project_id}/branches/{branch_id}",
            role=Role(spec=RoleRoleSpec(
                postgres_role=app_sp_id,
                identity_type=RoleIdentityType.SERVICE_PRINCIPAL,
            )),
            role_id=role_id,
        ).wait()
        print(f"✓ SP role created: {role_id}")

# ── Step 6: Persist config to metadata schema ────────────────────
# Store connection details in Delta so the app can discover them at startup
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {catalog_name}.{metadata_schema}.lakebase_config (
        config_key STRING NOT NULL,
        config_value STRING NOT NULL,
        updated_at TIMESTAMP DEFAULT current_timestamp()
    ) USING DELTA
""")

configs = {
    "project_id": project_id,
    "branch_id": branch_id,
    "endpoint_host": endpoint_host,
    "database": db_name,
    "status": "ready",
}
for k, v in configs.items():
    spark.sql(f"""
        MERGE INTO {catalog_name}.{metadata_schema}.lakebase_config t
        USING (SELECT '{k}' AS config_key, '{v}' AS config_value) s
        ON t.config_key = s.config_key
        WHEN MATCHED THEN UPDATE SET config_value = s.config_value, updated_at = current_timestamp()
        WHEN NOT MATCHED THEN INSERT (config_key, config_value) VALUES (s.config_key, s.config_value)
    """)

print(f"\n─── Lakebase provisioning complete ───")
print(f"Project:  {project_id}")
print(f"Branch:   {branch_id}")
print(f"Endpoint: {endpoint_host}")
print(f"Database: {db_name}")

# Output for downstream tasks / Admin UI
dbutils.notebook.exit({
    "status": "ready",
    "project_id": project_id,
    "endpoint_host": endpoint_host,
    "database": db_name,
})
```

#### Admin UI Integration

The Admin UI triggers the setup job via the Jobs API:

```python
# App route: POST /api/admin/run-setup
@admin_bp.route('/run-setup', methods=['POST'])
def run_setup():
    """Trigger the setup job and return run_id for polling."""
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    
    # Find the setup job by name
    jobs = w.jobs.list(name="aibi-studio-setup")
    job = next(iter(jobs), None)
    if not job:
        return jsonify({'error': 'Setup job not found. Run: databricks bundle deploy'}), 404
    
    # Trigger job run
    run = w.jobs.run_now(job_id=job.job_id)
    
    return jsonify({
        'status': 'triggered',
        'run_id': run.run_id,
        'job_id': job.job_id,
    })
```

```python
# App route: GET /api/admin/setup-status
@admin_bp.route('/setup-status')
def setup_status():
    """Check infrastructure status from metadata table."""
    # Read lakebase_config from Delta
    # Read metadata tables existence
    # Return combined status for Admin UI cards
    return jsonify({
        'lakebase': {'status': 'ready', 'endpoint': '...'},
        'metadata': {'status': 'ready'},
        'permissions': {'status': 'ready'},
    })
```

#### Admin UI Mockup

```
┌────────────────────────────────────────────────────────────┐
│  ☰  AI/BI Studio            Admin > Infrastructure      │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  One-time workspace setup. Run after first deploy.         │
│                                                            │
│  [Run Full Setup]    [Run Individual ▼]                    │
│                                                            │
│  ┌────────────────────────────────────────────────────────┐
│  │  Component             Status           Action          │
│  ├────────────────────────────────────────────────────────┤
│  │  Workspace Perms       ● Ready           [Re-run]       │
│  │  UC Catalog Access     ● Ready           [Re-run]       │
│  │  Metadata Tables       ● Ready           [Re-run]       │
│  │  Lakebase State Store  ○ Not provisioned [Provision]    │
│  └────────────────────────────────────────────────────────┘
│                                                            │
│  Last run: 2025-01-15 10:30 UTC — 3/4 tasks succeeded     │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

#### Config Persistence (Lakebase connection details)

Stored in the **metadata schema** (Delta) so the app discovers them at startup:

```sql
CREATE TABLE IF NOT EXISTS aibi_studio_metadata.lakebase_config (
    config_key STRING NOT NULL,
    config_value STRING NOT NULL,
    updated_at TIMESTAMP DEFAULT current_timestamp()
) USING DELTA;
```

The app reads this table once on startup to get `endpoint_host`, `project_id`, `branch_id`, `database`.
If the table is empty or missing, the app operates in **degraded mode** (in-memory state only, with a banner: "Lakebase not provisioned — run Setup from Admin panel").

#### `databricks.yml` Variable Addition

```yaml
variables:
  lakebase_project_id:
    description: Lakebase project ID for pipeline state store.
    default: "aibi-studio"
```

---

#### Remaining Phase 3a tasks (after provisioning job is deployed):
4. Implement `StateStore` class with Data API connection
5. Wire `StateStore` into pipeline callback (dual-write mode)

### 8.2 Phase 3b: Dual-Write
1. Pipeline callback writes to BOTH Lakebase and Delta (backward compat)
2. `/status` endpoint reads from Lakebase (primary), falls back to Delta
3. Validate correctness: compare Lakebase vs Delta state after runs

### 8.3 Phase 3c: Cut Over
1. Remove Delta writes from pipeline callback
2. Remove `_runs` in-memory dict (Lakebase is source of truth)
3. Remove 2s polling from UI (SSE + initial load only)
4. Remove `RunStore` class; `StateStore` is the only persistence layer
5. Drop Delta metadata tables (`pipeline_runs`, `pipeline_run_steps`, `pipeline_run_phases`)

### 8.4 Phase 3d: Event Replay
1. Add `events` table and `append_event()` calls
2. Implement `/api/pipeline/events/{run_id}?after={event_id}` endpoint
3. Update UI with gap detection + replay logic
4. Remove `EventSource` error/reconnect polling fallback

---

## 9. Performance Comparison

| Operation | Current (Delta + polling) | Proposed (Lakebase + SSE) |
| --- | --- | --- |
| Phase transition write | ~300ms (Statement API) | ~3ms (Postgres INSERT) |
| UI status read (polling) | ~800ms every 2s = 400ms avg latency | 0ms (SSE push, <50ms propagation) |
| Full run state load (page refresh) | ~1.5s (3 Delta queries) | ~10ms (1 Postgres query with JOINs) |
| Crash recovery | Manual orphan scan, data loss | Automatic resume from last checkpoint |
| Per-run overhead | 30+ SQL statements to warehouse | 30+ Postgres writes (~90ms total) |

---

## 10. Open Questions

1. **Lakebase connection method:** Data API (HTTP, simpler) vs native Postgres driver (psycopg, faster)? 
   - Data API: No driver dependency, works with SP token, ~10ms per call
   - psycopg: 1-3ms per call, needs connection pool, OAuth token refresh
   - **Recommendation:** Start with Data API (simpler); switch to psycopg if latency matters

2. **Event retention:** How long to keep the `events` table? 
   - Option A: TTL — delete events older than 7 days (cron job)
   - Option B: Partition by run_id, cascade delete when run is cleaned up
   - **Recommendation:** Option B (cascade delete)

3. **Delta tables fate:** Keep as read-only analytics layer (sync from Lakebase) or drop entirely?
   - If kept: Lakebase → Delta sync via scheduled job (for BI/reporting)
   - If dropped: All queries go to Lakebase
   - **Recommendation:** Drop for operational state; keep `pipeline_step_phases_config` in Delta (it's static config, not operational)

4. **Multi-user concurrency:** Multiple users running pipelines simultaneously?
   - Lakebase handles this natively (MVCC)
   - Each run has its own SSE queue — no cross-run interference
   - The UI already scopes everything by `run_id`

5. **Lakebase scale-to-zero:** If the Lakebase endpoint is cold, first connection adds ~2-3s. Acceptable?
   - Mitigation: Keep-alive ping from app (every 5 min)
   - Or: accept cold start on first request after idle

---

## 11. What Stays the Same

- Pipeline execution logic (`pipeline.py`, step orchestrators)
- LLM client and prompts
- Template population and notebook execution
- Version resolver
- UI layout and components (only the data-fetching layer changes)
- SSE streaming mechanism (queue.Queue → EventSource)
- `pipeline_step_phases_config` table (static config, stays in Delta/UC)

---

## 12. Dependencies

- Lakebase Postgres Autoscaling (GA)
- App SP must have access to the Lakebase project
- `databricks-sdk` >= 0.118.0 (for `w.postgres.*` APIs)
- No additional Python packages needed if using Data API; `psycopg[binary]` if native driver
