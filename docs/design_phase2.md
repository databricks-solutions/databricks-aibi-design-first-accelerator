# Phase 2 Design — AI/BI Studio (Databricks App)

**App Name:** `dbx-aibi-semantic-studio`  
**Header:** AI/BI Studio  
**Subtitle:** Design-First Semantic Layer, Metric Views, Dashboards & Genie

---

## 1. Architecture

### Layer Responsibilities

| Layer | Location | Responsibility |
|-------|----------|----------------|
| **Routes** | `app/routes/` | HTTP endpoints, request validation, response formatting |
| **Orchestrator** | `app/orchestrator/` | Pipeline step sequencing, progress tracking, error handling |
| **Services** | `app/services/` | Databricks API wrappers (stateless, reusable, testable) |
| **LLM** | `app/llm/` | Foundation Model API client, prompts, structured output schemas |
| **Models** | `app/models/` | Pydantic data models shared across layers |

### Design Principles

- Services are stateless — no request context, no session; accept explicit params
- Orchestrator owns state — tracks pipeline progress, manages step sequencing
- Routes are thin — validate input, call orchestrator, format output
- LLM is isolated — all model interaction in `app/llm/`; swappable endpoints

---

## 2. Services Layer (`app/services/`)

Each service wraps a single Databricks API surface. All methods are synchronous, return typed results, and raise `ServiceError` on failure.

### 2.1 WorkspaceService (`workspace_io.py`)

| Method | Description | API |
|--------|-------------|-----|
| `read_file(path) -> str` | Read workspace file content | `GET /api/2.0/workspace/export` |
| `write_file(path, content, overwrite)` | Write/create workspace file | `POST /api/2.0/workspace/import` |
| `mkdirs(path)` | Create directory recursively | `POST /api/2.0/workspace/mkdirs` |
| `delete(path, recursive)` | Delete file or folder | `POST /api/2.0/workspace/delete` |
| `list_dir(path) -> list[FileInfo]` | List directory contents | `GET /api/2.0/workspace/list` |
| `file_exists(path) -> bool` | Check if path exists | `GET /api/2.0/workspace/get-status` |
| `import_notebook(path, content, format)` | Import notebook | `POST /api/2.0/workspace/import` |

### 2.2 SQLService (`sql_client.py`)

| Method | Description |
|--------|-------------|
| `execute(sql, warehouse_id) -> StatementResult` | Execute SQL statement |
| `execute_and_wait(sql, warehouse_id, timeout_s) -> DataFrame` | Execute and poll for results |
| `get_table_schema(fqn) -> list[Column]` | DESCRIBE TABLE EXTENDED |
| `table_exists(fqn) -> bool` | Check table/view existence |
| `get_row_count(fqn) -> int` | SELECT COUNT(*) |
| `sample_rows(fqn, n) -> list[dict]` | SELECT * LIMIT n |

### 2.3 LakeviewService (`lakeview_client.py`)

| Method | Description |
|--------|-------------|
| `create_dashboard(display_name, warehouse_id, serialized_dashboard, parent_path) -> Dashboard` | Create dashboard |
| `publish_dashboard(dashboard_id)` | Publish draft to live |
| `list_dashboards(page_size) -> list[Dashboard]` | List all dashboards (paginated) |
| `find_by_name(display_name) -> Dashboard or None` | Search by display_name |
| `delete_dashboard(dashboard_id)` | Delete dashboard |
| `delete_by_name(display_name)` | Find and delete by name (idempotent) |

### 2.4 GenieService (`genie_client.py`)

| Method | Description |
|--------|-------------|
| `list_spaces() -> list[GenieSpace]` | List all Genie spaces |
| `find_by_title(title) -> GenieSpace or None` | Search by title |
| `delete_space(space_id)` | Delete Genie space |
| `delete_by_title(title)` | Find and delete by title (idempotent) |

### 2.5 JobsService (`jobs_client.py`)

| Method | Description |
|--------|-------------|
| `run_notebook(path, warehouse_id) -> RunResult` | Submit one-time notebook run |
| `wait_for_run(run_id, timeout_s) -> RunResult` | Poll until completion |
| `run_and_wait(path, warehouse_id, timeout_s) -> RunResult` | Submit + poll |

---

## 3. LLM Layer (`app/llm/`)

### 3.1 LLMClient (`client.py`)

| Method | Description |
|--------|-------------|
| `chat(messages, response_format, max_tokens) -> str` | Text generation |
| `chat_with_vision(messages, image_bytes) -> str` | Vision model call |
| `chat_structured(messages, schema) -> BaseModel` | Parse into Pydantic model |

**Config:** `LLM_ENDPOINT_NAME`, `VISION_ENDPOINT_NAME`, `LLM_TEMPERATURE`, `LLM_MAX_RETRIES`

### 3.2 Schemas (`schemas.py`)

| Schema | Step | Key Fields |
|--------|------|------------|
| `ParsedERD` | 2 | tables, relationships |
| `NotebookCells` | 2 | cells (language, source, title) |
| `MetricViewYAML` | 3 | yaml_content (validated string) |
| `DashboardSpec` | 4 | pages, datasets |
| `GenieContent` | 5 | instructions, questions, sqls |
| `RunSummary` | 6 | title, assets, validation |

### 3.3 Prompts (`prompts.py`)

| Function | Source Prompt | Purpose |
|----------|--------------|---------|
| `erd_parser_prompt()` | `01_create_data_layer.md` | Parse ERD image |
| `ddl_generator_prompt()` | `01_create_data_layer.md` | Generate DDL |
| `metric_view_prompt()` | `02_create_metric_views.md` | Design YAML |
| `dashboard_prompt()` | `03_create_dashboards.md` | Plan layout |
| `genie_content_prompt()` | `04_create_genie_space.md` | Generate content |
| `documentation_prompt()` | `05_generate_documentation.md` | Run summary |

---

## 4. Orchestrator (`app/orchestrator/`)

### 4.1 PipelineRunner (`pipeline.py`)

| Method | Description |
|--------|-------------|
| `run(config, progress_callback) -> PipelineResult` | Execute all enabled steps |
| `run_step(step_name, config) -> StepResult` | Execute single step |
| `cancel()` | Request cancellation |

### 4.2 Step Modules

| Module | Class | Pipeline Step |
|--------|-------|---------------|
| `config_loader.py` | `ConfigLoader` | Step 0: Load + validate config |
| `environment_setup.py` | `EnvironmentSetup` | Step 1: Clean start |
| `data_layer.py` | `DataLayerCreator` | Step 2: ERD -> tables |
| `metric_views.py` | `MetricViewCreator` | Step 3: KPI -> views |
| `dashboards.py` | `DashboardCreator` | Step 4: Lakeview dashboards |
| `genie_space.py` | `GenieSpaceCreator` | Step 5: Genie space |
| `documentation.py` | `DocumentationGenerator` | Step 6: Run summary |

---

## 5. Routes (`app/routes/`)

### 5.1 Pipeline API (`pipeline_routes.py`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/pipeline/run` | Start pipeline (async) |
| GET | `/api/pipeline/status/<run_id>` | Get status + logs |
| POST | `/api/pipeline/cancel/<run_id>` | Cancel pipeline |
| GET | `/api/pipeline/stream/<run_id>` | SSE event stream |

### 5.2 Config API (`config_routes.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config/domains` | List domains |
| GET | `/api/config/domain/<name>` | Get domain config |
| POST | `/api/config/validate` | Validate before run |

### 5.3 Results API (`results_routes.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/results/history` | Past runs |
| GET | `/api/results/<run_id>` | Run details |
| GET | `/api/results/<run_id>/assets` | Generated asset links |

### 5.4 Auth (`auth_routes.py`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/login` | Auto-login from platform headers |
| GET | `/logout` | Clear session |
| GET | `/api/auth/user` | Current user info |

---

## 6. Configuration (`app/config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DEPLOY_ROOT` | (required) | Bundle workspace root |
| `SQL_WAREHOUSE_ID` | (required) | SQL warehouse |
| `LLM_ENDPOINT_NAME` | `databricks-gpt-5-5` | Primary LLM endpoint |
| `VISION_ENDPOINT_NAME` | `databricks-gpt-5-5` | Vision model |
| `LLM_TEMPERATURE` | `0.1` | Generation temperature |
| `LLM_MAX_RETRIES` | `3` | Max retries |
| `DEFAULT_EXAMPLE_DOMAIN` | `member_claims` | Default domain |

---

## 7. Authentication

Platform-based identity (no login form):

| Header | Description |
|--------|-------------|
| `X-Forwarded-Email` | User email from IdP |
| `X-Forwarded-Preferred-Username` | Username |
| `X-Forwarded-Access-Token` | OAuth token for API calls |

---

## 8. Error Handling

### Error Hierarchy

- `AppError` (base)
  - `ConfigError` — Invalid configuration
  - `ServiceError` — Databricks API failure
    - `SQLError`, `WorkspaceError`, `LakeviewError`
  - `LLMError` — Foundation Model failure
    - `LLMTimeoutError`, `LLMValidationError`
  - `PipelineError` — Pipeline execution failure
    - `StepError` — Individual step failure

### API Error Response

```json
{
  "error": {
    "type": "StepError",
    "step": "create_metric_views",
    "message": "Column not found",
    "suggestion": "Check column names; retry will attempt correction"
  }
}
```

---

## 9. Real-Time Progress (SSE)

Events streamed via `GET /api/pipeline/stream/<run_id>`:

| Event | Data |
|-------|------|
| `step_started` | `{step, index, total}` |
| `step_completed` | `{step, duration_s, artifacts}` |
| `step_failed` | `{step, error, suggestion}` |
| `log` | `{level, message, timestamp}` |
| `pipeline_completed` | `{run_id, duration_s, assets}` |

---

## 10. Versioning (`app/orchestrator/version_resolver.py`)

### 10.1 Run Modes

The UI presents two run modes before pipeline execution:

| Mode | `run_mode` value | Behavior |
|------|-----------------|----------|
| Clean & Replace | `clean` | `clean_start=true`, no suffix. Drops target schema CASCADE, deletes output folder, replaces dashboard/Genie by name. |
| Create New Version | `versioned` | Discovers latest `_vN`, creates all assets with `_v(N+1)`. Previous versions untouched. |

### 10.2 API Change

**POST `/api/pipeline/run`** request body gains `run_mode`:

```json
{
  "domain": "member_claims",
  "steps": ["environment_setup", "create_metric_views", ...],
  "run_mode": "versioned",
  "version_override": null
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `run_mode` | `"clean" \| "versioned"` | `"clean"` | Controls asset lifecycle |
| `version_override` | `int \| null` | `null` | Force a specific version number (optional) |

### 10.3 VersionResolver

```python
class VersionResolver:
    """Discovers existing versions and computes the next suffix."""

    def __init__(self, workspace_service, sql_service):
        ...

    def resolve(self, config: AcceleratorConfig, override: int | None = None) -> VersionInfo:
        """Scan workspace + UC to find highest existing version.

        Returns:
            VersionInfo(version=N, suffix="_vN", is_new=True)
        """

    def _scan_output_folders(self, base_path: str) -> list[int]:
        """Find output_v1/, output_v2/, ... folders."""

    def _scan_schemas(self, catalog: str, base_schema: str) -> list[int]:
        """Find schema_v1, schema_v2, ... in catalog via SHOW SCHEMAS."""

    def _scan_dashboards(self, base_name: str) -> list[int]:
        """Find <name>_v1, <name>_v2, ... dashboards."""
```

### 10.4 Per-Asset Versioning

| Asset | Clean Mode | Versioned Mode |
|-------|-----------|----------------|
| Target schema | `catalog.schema` (dropped + recreated) | `catalog.schema_v1` (new schema created) |
| Output folder | `examples/<domain>/output/` (wiped) | `examples/<domain>/output_v1/` (new folder) |
| Dashboard | `<name>` (replaced) | `<name>_v1` (new dashboard) |
| Genie space | `<title>` (replaced) | `<title>_v1` (new space) |
| Source tables | `catalog.source_schema` (IF NOT EXISTS) | `catalog.source_schema` (shared, never versioned) |
| Metric views | In target schema (OR REPLACE) | In versioned target schema (new views) |

### 10.5 Version Threading Through Config

`AcceleratorConfig` gains:

```python
@dataclass
class AcceleratorConfig:
    ...
    run_mode: str = "clean"          # "clean" or "versioned"
    version: int | None = None       # None for clean, N for versioned
    version_suffix: str = ""         # "" for clean, "_v1" for versioned
```

Orchestrator steps read `config.version_suffix` to append to asset names:
- `environment_setup.py`: Uses `output_folder + version_suffix`, creates versioned schema
- `metric_views.py`: Creates views in `catalog.target{version_suffix}`
- `dashboards.py`: Dashboard name becomes `{base_name}{version_suffix}`
- `genie_space.py`: Space title becomes `{base_title}{version_suffix}`

### 10.6 UI Wireframe

```
┌──────────────────────────────────────────────────┐
│  Run Mode                                        │
│  (●) Clean & Replace                              │
│      Removes existing assets and recreates fresh  │
│  ( ) Create New Version                           │
│      Keeps existing, creates _v2 (next: _v3)      │
│      [ ] Override version: [___]                   │
└──────────────────────────────────────────────────┘
```

When "Create New Version" is selected, the UI shows the detected next version
number (e.g., "Next version: v3") based on the VersionResolver scan.
