# AIBI Design-First Accelerator — Phase 2 Implementation Plan

**Requirements:** [FEIP_REQUIREMENTS_PHASE2.md](./FEIP_REQUIREMENTS_PHASE2.md)  
**Phase 1 Plan:** [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)  
**Reference App:** `/Workspace/Users/arun.wagle@databricks.com/Elevance/carelon-app/`

---

## 1. Architecture Overview

```
Flask App (UI) -> Python Orchestrator -> {
  Foundation Model API  (for reasoning/generation tasks),
  Statement Execution API  (for SQL execution),
  Workspace API  (for file/notebook CRUD),
  Lakeview Dashboard API  (for dashboard creation),
  Genie Spaces API  (for space creation)
}
```

The App replaces Genie Code's interactive agent loop with a **programmatic agent pattern**:
- Python reads the same `framework/prompts/*.md` as system prompts for the Foundation Model API
- LLM generates structured output (Pydantic-validated JSON/YAML)
- SDK executes the generated artifacts (SQL, notebooks, API calls)
- Self-correction loop feeds errors back to the LLM (up to 3 retries)

---

## 2. DAB Deployment (Everything via Bundle)

### 2.1 Updated Bundle Layout

```
aibi-design-first-accelerator/
|-- databricks.yml                     # Main bundle config (updated)
|-- resources/
|   |-- accelerator_app.app.yml        # Databricks App resource
|   |-- llm_serving.serving.yml        # Foundation Model serving endpoint (optional)
|   +-- accelerator_volume.volume.yml  # Output storage volume (optional)
|-- app/                               # App source code (deployed by DAB)
|   |-- app.yaml                       # App runtime config (command, env vars)
|   |-- app.py                         # Flask entry point
|   |-- gunicorn.conf.py               # Gunicorn production config
|   |-- requirements.txt               # Python dependencies
|   |-- config.py                      # Centralized env var config
|   |-- orchestrator/                  # Pipeline execution engine
|   |   |-- __init__.py
|   |   |-- pipeline.py                # Main pipeline runner
|   |   |-- config_loader.py           # Step 0: YAML parsing
|   |   |-- environment_setup.py       # Step 1: Clean start
|   |   |-- data_layer.py              # Step 2: ERD -> tables
|   |   |-- metric_views.py            # Step 3: KPI -> metric views
|   |   |-- dashboards.py             # Step 4: Lakeview dashboards
|   |   |-- genie_space.py             # Step 5: Genie space
|   |   +-- documentation.py           # Step 6: Run summary
|   |-- llm/
|   |   |-- __init__.py
|   |   |-- client.py                  # Foundation Model API wrapper
|   |   |-- prompts.py                 # System prompts (from framework/prompts/)
|   |   +-- schemas.py                 # Pydantic response models
|   |-- services/
|   |   |-- __init__.py
|   |   |-- workspace_io.py            # Workspace API helpers
|   |   |-- sql_client.py              # Statement Execution API
|   |   |-- lakeview_client.py         # Dashboard API helpers
|   |   +-- genie_client.py            # Genie Spaces API helpers
|   |-- routes/
|   |   |-- __init__.py
|   |   |-- pipeline_routes.py         # /pipeline/run, /pipeline/status
|   |   |-- config_routes.py           # /config/domains, /config/validate
|   |   +-- results_routes.py          # /results/history, /results/<run_id>
|   |-- templates/                     # Jinja2 HTML templates
|   |   |-- layout.html
|   |   |-- dashboard.html
|   |   |-- pipeline.html
|   |   +-- results.html
|   +-- static/
|       +-- css/style.css
|-- framework/                         # Shared prompts + templates (unchanged)
|-- examples/                          # Domain configs (unchanged)
+-- scripts/                           # Validation scripts (unchanged)
```

### 2.2 Updated `databricks.yml`

```yaml
bundle:
  name: aibi_design_first_accelerator

include:
  - resources/*.yml

variables:
  bundle_name_path:
    description: Folder name under /Workspace/Users/<current_user>/ for this bundle.
    default: "aibi-design-first-accelerator"
  deploy_root:
    description: Bundle sync root.
    default: /Workspace/Users/${workspace.current_user.userName}/${var.bundle_name_path}
  sql_warehouse_id:
    description: SQL warehouse for all SQL execution.
    default: "2d8e531640ffa469"
  example_domain:
    description: Active example module.
    default: member_claims
  llm_endpoint_name:
    description: Foundation Model serving endpoint name for LLM calls.
    default: "databricks-gpt-5-5"
  vision_endpoint_name:
    description: Vision-capable model endpoint for ERD parsing.
    default: "databricks-gpt-5-5"

sync:
  paths:
    - databricks.yml
    - resources
    - framework
    - app
    - examples/member_claims
  exclude:
    - "**/.DS_Store"
    - "**/__pycache__/**"
    - "**/.venv/**"

targets:
  dev:
    default: true
    mode: development
    workspace:
      host: https://fevm-aw-serverless-stable.cloud.databricks.com
      root_path: ${var.deploy_root}
    variables:
      example_domain: member_claims

  staging:
    mode: production
    workspace:
      host: https://fevm-aw-serverless-stable.cloud.databricks.com
      root_path: ${var.deploy_root}

  prod:
    mode: production
    workspace:
      host: https://your-workspace.cloud.databricks.com/
      root_path: ${var.deploy_root}
    variables:
      llm_endpoint_name: "databricks-gpt-5-5"
```

### 2.3 App Resource (`resources/accelerator_app.app.yml`)

```yaml
resources:
  apps:
    accelerator_app:
      name: dbx-aibi-semantic-studio-${workspace.current_user.domain_friendly_name}
      description: "AI/BI Studio - Design-First Semantic Layer, Metric Views, Dashboards & Genie"
      source_code_path: ../app

      user_api_scopes:
        - "files"
        - "sql"

      permissions:
        - level: CAN_USE
          group_name: users
```

### 2.4 Model Serving Resource (`resources/llm_serving.serving.yml`)

For most workspaces, pre-provisioned Foundation Model endpoints (`databricks-gpt-5-5`, etc.) are already available. The DAB variable `llm_endpoint_name` points to whichever endpoint the user configures. A custom endpoint is only needed if the workspace requires a dedicated one.

### 2.5 App Runtime Configuration (`app/app.yaml`)

```yaml
command:
  - gunicorn
  - app:app
  - --config
  - gunicorn.conf.py
  - -w
  - '2'
  - --timeout
  - '600'
  - --max-requests
  - '500'
  - --max-requests-jitter
  - '50'
env:
  - name: 'FLASK_ENV'
    value: 'production'
  - name: 'DEPLOY_ROOT'
    value: '/Workspace/Users/${DATABRICKS_APP_CREATOR}/aibi-design-first-accelerator'
  - name: 'SQL_WAREHOUSE_ID'
    value: '2d8e531640ffa469'
  - name: 'LLM_ENDPOINT_NAME'
    value: 'databricks-gpt-5-5'
  - name: 'VISION_ENDPOINT_NAME'
    value: 'databricks-gpt-5-5'
  - name: 'LLM_TEMPERATURE'
    value: '0.1'
  - name: 'LLM_MAX_RETRIES'
    value: '3'
  - name: 'DEFAULT_EXAMPLE_DOMAIN'
    value: 'member_claims'
  - name: 'SECRET_KEY'
    valueFrom: 'secret/aibi-accelerator/flask-secret-key'
```

---

## 3. Step-by-Step Execution Approach

Each pipeline step decomposes into: **Context** (deterministic) -> **Reason** (LLM) -> **Execute** (SDK).

### Step 0: Load Configuration

| Phase | LLM? | Action |
|-------|------|--------|
| Parse YAML | No | Read `accelerator.yaml`, resolve paths, apply suffix rules |
| Validate | No | Check schema against `accelerator.schema.yaml` |
| Resolve endpoints | No | Read `databricks.yml` for warehouse_id, deploy_root |

### Step 1: Environment Setup

| Phase | LLM? | Action |
|-------|------|--------|
| Clean output folder | No | Workspace API: recursive delete + mkdirs |
| Reset target schema | No | SQL: CREATE SCHEMA IF NOT EXISTS |

### Step 2: Create Data Layer (Greenfield)

| Phase | LLM? | Action |
|-------|------|--------|
| A: Parse ERD image | YES (vision) | Send image to vision endpoint, get structured table/column/FK output |
| B: Generate DDL notebook | YES (code gen) | Template + parsed ERD -> DDL SQL cells |
| C: Generate synthetic data | YES (code gen) | Template + ERD + volume config -> dbldatagen notebook |
| D: Execute notebooks | No | Workspace import + Jobs API runs/submit |
| E: Validate | No | SQL: SHOW TABLES, row counts, FK join checks |

### Step 3: Create Metric Views

| Phase | LLM? | Action |
|-------|------|--------|
| A: Profile schema | No | SQL: DESCRIBE TABLE EXTENDED, sample rows, row counts |
| B: Design YAML | YES | KPI spec + best practices + schema profile -> metric view YAML |
| C: Execute CREATE VIEW | No | Statement Execution API |
| D: Retry on error | YES | Feed SQL error back to LLM for self-correction (up to 3x) |
| E: Save artifact | No | Write YAML to output folder |

### Step 4: Create Dashboards

| Phase | LLM? | Action |
|-------|------|--------|
| A: Profile metric view | No | SQL: DESCRIBE + sample queries for data ranges |
| B: Plan layout | YES | KPI dashboard mapping + MV profile -> Lakeview JSON spec |
| C: Delete existing | No | Lakeview API: list by name, remove matches (idempotent) |
| D: Create + publish | No | Lakeview API: create with serialized_dashboard, then publish |
| E: Save manifest | No | Write dashboard_id + URL to output folder |

### Step 5: Create Genie Space

| Phase | LLM? | Action |
|-------|------|--------|
| A: Generate content | YES | MV profile + KPI spec -> instructions, questions, SQL examples |
| B: Populate template | No | Fill template placeholders with LLM-generated content |
| C: Create + execute notebook | No | Workspace import + Jobs API execution |
| D: Validate | No | Check benchmarks >=15, instructions >500 chars |

### Step 6: Generate Documentation

| Phase | LLM? | Action |
|-------|------|--------|
| A: Collect outputs | No | Read all manifests, YAML files, validation results |
| B: Generate README | YES | Summarize run into structured documentation |
| C: Write to output | No | Write readme.md to output folder |

---

## 4. LLM Integration

### 4.1 Client (`app/llm/client.py`)

- Uses `WorkspaceClient().serving_endpoints.query()` for all LLM calls
- Supports structured output via `response_format: json_schema` with Pydantic schemas
- Low temperature (0.1) for deterministic generation
- Retry with exponential backoff on rate limits
- Vision support: base64-encoded images in message content array
- Endpoint name configured via env var (switchable per target)

### 4.2 System Prompts (`app/llm/prompts.py`)

Each `framework/prompts/NN_*.md` is split into:

| Component | Used As |
|-----------|---------|
| Role section | `system` message |
| Step instructions | `user` message context |
| Validation criteria | Post-processing assertion |
| Error handling rules | Retry logic |

### 4.3 Structured Output Schemas (`app/llm/schemas.py`)

| Schema | Used In | Key Fields |
|--------|---------|------------|
| `ParsedERD` | Step 2A | tables (name, type, columns, PK, FKs), relationships |
| `NotebookCells` | Step 2B/2C | ordered list of cells (language, source, title) |
| `MetricViewYAML` | Step 3B | version, source, joins, dimensions, measures |
| `LakeviewDashboardSpec` | Step 4B | pages (widgets with type, SQL, position, encodings) |
| `GenieSpaceContent` | Step 5A | instructions, descriptions, questions, SQL examples |

### 4.4 Model Selection

| Task | Endpoint |
|------|----------|
| ERD image parsing | `VISION_ENDPOINT_NAME` (vision-capable) |
| Code generation (DDL, dbldatagen) | `LLM_ENDPOINT_NAME` |
| Metric view YAML | `LLM_ENDPOINT_NAME` |
| Dashboard JSON | `LLM_ENDPOINT_NAME` |
| Content generation | `LLM_ENDPOINT_NAME` |

---

## 5. App Implementation

### 5.1 Flask App (`app/app.py`)

Pattern: Flask application factory (same as carelon-app)
- Blueprint-based route registration
- Databricks platform auth via `X-Forwarded-*` headers (no login form)
- Session management for user context
- Background thread execution for pipeline runs

### 5.2 Routes

| Blueprint | Routes | Description |
|-----------|--------|-------------|
| `pipeline_bp` | `POST /pipeline/run` | Start pipeline execution (async) |
| | `GET /pipeline/status/<run_id>` | Poll execution status + logs |
| | `POST /pipeline/cancel/<run_id>` | Cancel running pipeline |
| `config_bp` | `GET /config/domains` | List available example domains |
| | `GET /config/domain/<name>` | Get accelerator.yaml for domain |
| | `POST /config/validate` | Validate config before run |
| `results_bp` | `GET /results/history` | List past runs with status |
| | `GET /results/<run_id>` | Get run details + asset links |
| `auth_bp` | `GET /login` | Auto-login from platform headers |

### 5.3 UI Pages

| Page | Features |
|------|----------|
| **Dashboard** | Domain selector, quick-run button, recent runs |
| **Pipeline** | Step progress bars, real-time logs (SSE), LLM reasoning display |
| **Results** | Asset links (dashboards, Genie space), validation report |
| **Config Editor** | YAML editor for accelerator.yaml, mode selector |

### 5.4 Authentication

Same pattern as carelon-app:
- Platform authenticates users before requests reach the app
- Identity from `X-Forwarded-Email` / `X-Forwarded-Preferred-Username`
- User's OAuth token from `X-Forwarded-Access-Token` for downstream API calls
- `user_api_scopes: ["files", "sql"]` enables on-behalf-of workspace + SQL access
- App service principal handles Workspace API, Lakeview API, Genie API calls

---

## 6. Dependencies (`app/requirements.txt`)

```
flask>=3.0.0
gunicorn>=21.2.0
databricks-sdk>=0.72.0
pyyaml>=6.0
pydantic>=2.0.0
requests>=2.31.0
python-dotenv>=1.0.0
werkzeug>=3.0.0
jinja2>=3.1.0
```

---

## 7. Deployment Workflow

### 7.1 First-Time Setup

Prerequisites:
- Databricks CLI v0.239+ installed and authenticated
- SQL warehouse created (ID in `sql_warehouse_id` variable)
- Foundation Model endpoints accessible (pay-per-token)
- Secret scope `aibi-accelerator` with key `flask-secret-key`

Deploy:
1. `databricks bundle validate --strict -t dev`
2. `databricks bundle deploy -t dev`
3. `databricks bundle run accelerator_app -t dev`

### 7.2 Iterative Development

After code changes in `app/`:
1. `databricks bundle deploy -t dev` (app auto-redeploys)
2. If needed, restart the app: `dbx-aibi-semantic-studio-<your-domain-friendly-name>`

### 7.3 Production

1. `databricks bundle deploy -t prod`
2. Override app name in prod target for stable URL (no user suffix)

---

## 8. Implementation Phases

### Phase 2a: DAB + App Scaffold (Week 1)
- [ ] Update `databricks.yml` — add `include: resources/*.yml`, sync `app/`
- [ ] Create `resources/accelerator_app.app.yml`
- [ ] Create `app/app.yaml`, `app/app.py`, `app/config.py`, `app/gunicorn.conf.py`
- [ ] Create `app/requirements.txt`
- [ ] Validate + deploy: confirm app starts and serves dashboard page

### Phase 2b: Core Orchestrator (Week 2)
- [ ] `app/orchestrator/config_loader.py` — parse YAML, resolve paths, validate
- [ ] `app/llm/client.py` — Foundation Model API wrapper with structured output
- [ ] `app/llm/schemas.py` — Pydantic models for all step outputs
- [ ] `app/services/workspace_io.py` — Workspace API read/write/mkdirs
- [ ] `app/services/sql_client.py` — Statement Execution API wrapper
- [ ] `app/orchestrator/pipeline.py` — step runner with progress + error handling
- [ ] `app/orchestrator/environment_setup.py` — clean start (Step 1)

### Phase 2c: Metric Views + Data Layer (Week 3)
- [ ] `app/orchestrator/metric_views.py` — schema profiling + LLM YAML generation
- [ ] `app/orchestrator/data_layer.py` — ERD vision parsing + notebook generation
- [ ] `app/llm/prompts.py` — system prompts derived from framework/prompts/
- [ ] Retry/self-correction loops
- [ ] End-to-end test: config -> metric view created in UC

### Phase 2d: Dashboards + Genie Space (Week 4)
- [ ] `app/services/lakeview_client.py` — Dashboard API helpers
- [ ] `app/services/genie_client.py` — Genie Spaces API helpers
- [ ] `app/orchestrator/dashboards.py` — layout planning + Lakeview creation
- [ ] `app/orchestrator/genie_space.py` — template population + space creation
- [ ] `app/orchestrator/documentation.py` — run summary generation
- [ ] End-to-end test: full pipeline run via API

### Phase 2e: UI + Polish (Week 5)
- [ ] HTML templates: dashboard, pipeline progress, results, config editor
- [ ] Server-Sent Events (SSE) for real-time progress
- [ ] Run history storage
- [ ] Error display and diagnostic UI
- [ ] Production deploy test (`-t prod`)
- [ ] Update main README with App usage instructions

---

## 9. Open Questions

1. **Vision model** — Is `databricks-gpt-5-5` available on target workspaces?
2. **Notebook execution** — Jobs API `runs/submit` vs Statement Execution API for SQL-only steps?
3. **Structured output** — Which endpoints support `response_format: json_schema`?
4. **Concurrency** — Can Steps 4 and 5 run in parallel after Step 3?
5. **Run history** — Workspace file vs Delta table?
6. **User scopes** — Does `["files", "sql"]` cover Lakeview/Genie API calls?
