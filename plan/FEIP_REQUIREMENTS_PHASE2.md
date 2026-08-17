# AIBI Design-First Accelerator — Phase 2 Requirements

**Implementation:** [IMPLEMENTATION_PLAN_PHASE2.md](./IMPLEMENTATION_PLAN_PHASE2.md)  
**Parent:** [FEIP_REQUIREMENTS.md](./FEIP_REQUIREMENTS.md)  
**Repo:** `aibi-design-first-accelerator/`

---

## 1. Problem Statement

The current accelerator requires users to manually paste a master prompt into Genie Code chat and monitor an interactive multi-turn agent session. This limits adoption to technical users comfortable with agentic AI chat, makes runs non-repeatable (LLM non-determinism across sessions), and provides no UI for configuration, progress tracking, or run history.

---

## 2. Goal

Deliver a **Databricks App** that provides a self-service UI for executing the accelerator pipeline, while preserving the existing Genie Code mode for users who prefer it.

**Both execution modes must coexist as first-class paths:**

| Mode | Trigger | Target User |
|------|---------|-------------|
| **Genie Code** (existing) | Paste master prompt in chat | Developers, SAs comfortable with agent chat |
| **App UI** (new) | Click "Run Pipeline" in browser | Broader audience, demos, repeatable runs |

**Both modes share the same:**
- `accelerator.yaml` configuration
- `framework/` prompts, templates, and inputs
- `examples/<domain>/` structure
- Output folder layout and naming conventions
- Validation criteria

---

## 3. Functional Requirements

### FR-1: Pipeline Execution via UI

The App must execute the same pipeline steps (0–6) as the Genie Code master prompt:

| Step | Capability | Output |
|------|-----------|--------|
| 0 | Load and validate `accelerator.yaml` configuration | Resolved config |
| 1 | Environment setup (clean start) | Clean target schema + output folder |
| 2 | Create data layer (greenfield: ERD image parsing, DDL, synthetic data) | UC tables in source schema |
| 3 | Create metric views (KPI spec + schema profiling -> YAML) | Metric views in target schema |
| 4 | Create dashboards (Lakeview API) | Live AI/BI dashboards |
| 5 | Create Genie space (template notebook + API) | Configured Genie space |
| 6 | Generate documentation | Run summary README |

### FR-2: LLM-Powered Reasoning

Steps 2–6 require LLM reasoning (not purely deterministic). The App must:
- Call a Foundation Model serving endpoint for vision (ERD parsing), code generation, YAML design, content generation
- Support structured output (JSON schema) for type-safe LLM responses
- Implement self-correction: feed errors back to the LLM (up to 3 retries per step)
- Use the same prompt logic encoded in `framework/prompts/*.md`

### FR-3: Configuration Management

The App must:
- List available example domains from the workspace
- Display and validate `accelerator.yaml` before execution
- Support both greenfield (`erd`) and brownfield (`live_schema`) modes
- Allow selection of data source type, target catalog/schema, and pipeline steps

### FR-4: Real-Time Progress

During pipeline execution, the App must:
- Show which step is currently executing
- Stream logs and LLM reasoning in real time
- Display step completion status (pending / running / completed / failed)
- Report errors immediately with context and suggested fixes (fail-fast)

### FR-5: Run History and Results

The App must:
- Track past pipeline runs with timestamps, domain, and status
- Provide links to all generated assets (dashboards, Genie space, notebooks, metric views)
- Display validation results (KPI coverage, benchmark question counts)

### FR-7: Run Mode — Clean & Replace vs Create New Version

The App must present two run modes before pipeline execution:

| Mode | Behavior |
|------|----------|
| **Clean & Replace** | Drop existing target schema CASCADE, delete output folder, delete dashboard/Genie by name, then recreate. This is `clean_start: true` (existing behavior). |
| **Create New Version** | Discover the latest version suffix (`_v1`, `_v2`, ...) across target schema, output folder, dashboard, and Genie space. Increment to `_vN+1` and create all assets with the new suffix. Previous versions remain untouched. |

Versioning rules:
- **Target schema:** `catalog.schema_v1`, `catalog.schema_v2`, ...
- **Output folder:** `examples/<domain>/output_v1/`, `output_v2/`, ...
- **Dashboard name:** `<name>_v1`, `<name>_v2`, ...
- **Genie space title:** `<title>_v1`, `<title>_v2`, ...
- **Metric views:** Created inside the versioned target schema (no extra suffix on view names)
- **Source tables (greenfield):** Shared across versions (never versioned — data layer is reused)
- Version discovery scans the workspace and UC catalog to find the highest existing `_vN`
- First versioned run creates `_v1`; subsequent runs increment
- Users can override the version number manually (optional text input)

### FR-6: Authentication and Authorization

The App must:
- Authenticate users via Databricks platform identity (no login form)
- Execute workspace operations using the user's identity (on-behalf-of)
- Access SQL warehouse and Foundation Model endpoints via the app's service principal
- Grant `CAN_USE` to all workspace users by default

---

## 4. Non-Functional Requirements

### NFR-1: Deployment via DAB

All infrastructure must be deployed via a single Declarative Automation Bundle:
- Databricks App resource
- Foundation Model serving endpoint (or reference to pre-provisioned endpoint)
- Volumes (if needed for output persistence)
- Permissions

A single `databricks bundle deploy -t <target>` must provision everything.

### NFR-2: Performance

- Full pipeline execution (greenfield, member_claims domain) must complete in under 10 minutes
- Individual LLM calls must timeout after 120 seconds with retry
- UI must remain responsive during pipeline execution (async/background execution)

### NFR-3: Reliability

- Self-correction: on LLM output validation failure, retry with error context (up to 3 attempts)
- Fail-fast: any unrecoverable error halts the pipeline immediately with diagnostic context
- Idempotent: re-running the pipeline with `clean_start: true` produces the same result

### NFR-4: Compatibility

- App execution must not interfere with Genie Code mode (both can run independently)
- Output artifacts must be identical regardless of which mode produced them
- Existing `accelerator.yaml` schema must not change (no breaking changes for Genie Code users)

### NFR-5: Configurability

- LLM endpoint name must be configurable per target (dev vs prod)
- Vision endpoint must be configurable (different workspaces may have different models)
- SQL warehouse ID configurable via DAB variables
- Temperature and retry count configurable via environment variables

---

## 5. Constraints

### C-1: Technology Constraints

- App framework: Flask + gunicorn (proven pattern from carelon-app reference)
- LLM access: Databricks Foundation Model API serving endpoints only (no external API keys)
- Deployment: Declarative Automation Bundle (DAB) exclusively
- Auth: Databricks Apps platform identity (X-Forwarded-* headers, no custom login)
- SQL execution: Statement Execution API via configured SQL warehouse

### C-2: Shared Assets (No Breaking Changes)

- `framework/prompts/*.md` must remain readable by both Genie Code and the App
- `accelerator.yaml` schema must not change
- `databricks.yml` changes must be additive (existing sync paths and targets preserved)
- Output folder structure (`examples/<domain>/output/`) must be identical

### C-3: Workspace Assumptions

- Unity Catalog enabled
- AI/BI (Lakeview) and Genie enabled
- Foundation Model endpoints available (pay-per-token or provisioned)
- SQL warehouse (Pro or Serverless) available
- Databricks CLI v0.239+ (Apps support in DAB)

---

## 6. Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Full pipeline completes via App UI | `member_claims` greenfield: UC tables + metric views + dashboards + Genie space created |
| AC-2 | Output matches Genie Code mode | Same assets generated, same validation checks pass (KPI coverage, benchmark counts) |
| AC-3 | Single-command deploy | `databricks bundle deploy -t dev` provisions app + all resources without manual steps |
| AC-4 | No manual infrastructure setup | All endpoints, volumes, and permissions declared in DAB or documented as prerequisites |
| AC-5 | Sub-10-minute execution | Full greenfield pipeline completes in under 10 minutes via App |
| AC-6 | Both modes coexist | Running the App does not prevent Genie Code execution (and vice versa) |
| AC-7 | Real-time feedback | User sees step progress and can identify which step failed (within 5 seconds of failure) |
| AC-8 | Self-correction works | At least one retry scenario (e.g., invalid column in metric view YAML) resolves automatically |
| AC-9 | Brownfield mode supported | App successfully runs with `data_source.type: live_schema` (no ERD parsing, profiles existing tables) |
| AC-10 | Versioned run creates new assets | "Create New Version" produces `_v2` suffix when `_v1` exists; previous assets are unchanged |
| AC-11 | Clean run removes previous assets | "Clean & Replace" drops target schema CASCADE and deletes output folder before recreating |

---

## 7. User Stories

### US-1: SA runs full pipeline from UI
**As a** Solution Architect  
**I want to** select a domain and click "Run Pipeline"  
**So that** all assets (tables, metric views, dashboards, Genie space) are generated without using Genie Code chat

### US-2: User monitors pipeline progress
**As a** user running the pipeline  
**I want to** see real-time progress (which step is running, logs, errors)  
**So that** I can identify issues immediately without waiting for the full run to complete

### US-3: User views generated assets
**As a** user who completed a pipeline run  
**I want to** see links to all generated dashboards, Genie space, and metric views  
**So that** I can navigate directly to the outputs

### US-4: User configures before running
**As a** user  
**I want to** review and validate the `accelerator.yaml` configuration before execution  
**So that** I can catch config errors before wasting pipeline time

### US-5: Team deploys to new workspace
**As a** platform team  
**I want to** deploy the entire accelerator (app + framework + examples) with one command  
**So that** new workspaces are ready without manual setup

### US-6: User switches between modes
**As a** developer  
**I want to** run the pipeline via Genie Code OR the App UI on the same configuration  
**So that** I can choose the mode that fits my workflow without reconfiguring

### US-7: User creates versioned runs
**As a** Solution Architect iterating on metric views  
**I want to** keep previous versions of dashboards, metric views, and Genie spaces intact while creating a new version  
**So that** I can compare outputs across iterations and roll back if needed

### US-8: User cleans up and restarts
**As a** user who wants a fresh start  
**I want to** choose "Clean & Replace" to wipe all existing assets before regenerating  
**So that** I don't accumulate stale artifacts from previous runs

---

## 8. Open Questions

1. **Vision model availability** — Is `databricks-gpt-5-5` (vision) available on all target workspaces? What is the fallback?
2. **Notebook execution from App** — Should DDL/synthetic notebooks use Jobs API `runs/submit` or execute SQL directly via Statement Execution API?
3. **Structured output** — Which Foundation Model endpoints support `response_format: json_schema`? Fallback strategy for endpoints that don't?
4. **Run history persistence** — Workspace file (`runs.json`) vs Delta table for tracking past pipeline runs?
5. **Secret scope** — What secrets are required beyond the Flask secret key?
6. **User API scopes** — Does `["files", "sql"]` cover all operations, or does the app SP need to handle Lakeview/Genie API calls?

---

## 9. References

- **Implementation:** [IMPLEMENTATION_PLAN_PHASE2.md](./IMPLEMENTATION_PLAN_PHASE2.md)
- **Phase 1 Requirements:** [FEIP_REQUIREMENTS.md](./FEIP_REQUIREMENTS.md)
- **Phase 1 Implementation:** [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)
- **Design Guide:** [docs/design.md](../docs/design.md)
- **Reference App:** `/Workspace/Users/arun.wagle@databricks.com/Elevance/carelon-app/`

---

*End of requirements. Implementation details live in [IMPLEMENTATION_PLAN_PHASE2.md](./IMPLEMENTATION_PLAN_PHASE2.md).*
