# Create Dashboards

## CONTEXT ISOLATION — Read This First

Forget all execution details from prior steps (ERD parsing, synthetic data generation, metric view DDL). You do NOT need that context.

**Your ONLY inputs are:**

1. `{OUTPUT_FOLDER}/step_handoff.yaml` — contains pre-formatted values (paste verbatim):
   - `metric_view_fqns[].sql_fqn` — the EXACT backtick-quoted FQN for SQL (do NOT re-derive)
   - `dashboard_display_names[].display_name` — the EXACT name for API calls (do NOT reformat)
   - `warehouse_id`, `parent_path` — paste as-is

2. `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` — which KPIs are IMPLEMENTED

3. KPI specification Dashboard Mapping — which KPIs go on which page

**Rules:**
- Read `step_handoff.yaml` BEFORE any other action in this step
- Use `sql_fqn` value EXACTLY as written (it is already correctly backtick-quoted)
- Use `display_name` value EXACTLY as written (it is already snake_case validated)
- If these values look wrong, HALT — do NOT fix them locally

### Pipeline Halt Rules & Recovery

If `step_handoff.yaml` does NOT exist in `{OUTPUT_FOLDER}`:

1. Check if `run_context.yaml` exists in `{OUTPUT_FOLDER}`. If yes, reconstruct `step_handoff.yaml` from it:
   - Read `catalog`, `schema`, `version_suffix`, `assets.*` from `run_context.yaml`
   - Construct `sql_fqn` using: `` `{catalog}`.`{schema}`.`{metric_view_name}{version_suffix}` ``
   - Construct `dashboard_display_names` from `assets.dashboards[].name` + version suffix
   - Construct `genie_title` from `assets.genie.space_name` + version suffix
   - Populate `warehouse_id`, `parent_path`, `workspace_host`, `catalog`, `schema`
   - Write the reconstructed `step_handoff.yaml` to `{OUTPUT_FOLDER}`
   - Log: `"⚠️ RECOVERY: step_handoff.yaml was missing. Reconstructed from run_context.yaml."`
   - Proceed normally

2. If `run_context.yaml` also does NOT exist, reconstruct from `accelerator.yaml`:
   - Read `accelerator.yaml` from `{EXAMPLE_DIR}`
   - Determine version suffix from the output folder path (extract `vN` from path)
   - Apply the same construction logic as above
   - Write the reconstructed `step_handoff.yaml` to `{OUTPUT_FOLDER}`
   - Log: `"⚠️ RECOVERY: step_handoff.yaml was missing. Reconstructed from accelerator.yaml."`
   - Proceed normally

3. If NEITHER file can be found AND `accelerator.yaml` is unavailable:
   - HALT with: `"❌ EXECUTION HALTED: Cannot resolve asset names. Neither step_handoff.yaml, run_context.yaml, nor accelerator.yaml are accessible."`

---

## Role

You are a senior Databricks AI/BI dashboard architect and analytics visualization engineer.

Create production-quality **live Databricks AI/BI dashboards** using validated Metric Views and the KPI specification.

Dashboards MUST be created and managed through the **Databricks Lakeview REST API / Databricks SDK API client**.

The deliverable is a deployed and published workspace dashboard.

Do NOT treat dashboard JSON generation as the primary objective.

The objective is to produce dashboards that are:

- analytically correct;
- based only on validated metrics;
- aligned with the KPI specification;
- visually appropriate for each KPI;
- filter-compatible;
- backed by tested SQL;
- structurally valid according to the current Lakeview dashboard API contract;
- deployed successfully;
- validated after deployment.

---

## ENFORCEMENT HEADER

<!-- @enforcement
  pattern: lakeview_api_execution
  api_reference_required: lakeview_dashboard_api.md
  multi_dashboard_mandatory: true  # If assets.dashboards[] has N entries, create N dashboards
  filters_mandatory: true  # Every dashboard MUST have dimension filters
  gates:
    - id: api_contract_loaded
      after_step: 1
      check: "lakeview_dashboard_api.md content is in memory"
    - id: design_contract_exists
      after_step: 3
      check: "file_exists('{OUTPUT_FOLDER}/dashboards/dashboard_design.yaml')"
    - id: datasets_validated
      after_step: 4
      check: "file_exists('{OUTPUT_FOLDER}/dashboards/dashboard_dataset_validation.yaml')"
    - id: dashboards_created
      after_step: 5
      check: "manifest file(s) exist with dashboard_id for EACH entry in assets.dashboards[]"
    - id: dashboards_published
      after_step: 6
      check: "All manifests have published: true"
-->

---

## PROHIBITED ACTIONS (this entire step)

The following actions are STRICTLY FORBIDDEN:

1. **DO NOT create only 1 dashboard when `assets.dashboards[]` specifies multiple** — each entry MUST produce a separate deployed dashboard
2. **DO NOT create dashboards without filters** — every dashboard MUST include filter widgets for at least the primary dimensions (e.g., claim_type, line_of_business, service_month or equivalent)
3. **DO NOT create single-page dashboards when KPI spec Dashboard Mapping specifies multiple pages** — page count MUST match the mapping. A dashboard with 1 filter page + 1 canvas page is a SINGLE-PAGE dashboard (the filter page does not count). If the KPI spec maps N analytical pages, the dashboard MUST have N canvas pages + 1 filter page = N+1 total pages.
4. **DO NOT bypass `MEASURE()` syntax** — all validated KPI measures must use `MEASURE(measure_name)` from the Metric View
5. **DO NOT construct dashboard JSON from memory** — ALWAYS use `lakeview_dashboard_api.md` as the structural authority
6. **DO NOT skip dataset SQL validation** — every dataset query must execute successfully BEFORE building the dashboard JSON
7. **DO NOT jump directly to Lakeview API** without completing the design contract (`dashboard_design.yaml`)
8. **DO NOT silently implement skipped KPIs in dashboard SQL** — if a KPI was SKIPPED in metric view validation, it stays skipped
9. **DO NOT create empty/placeholder widgets** — every widget must have a valid dataset with real data
10. **DO NOT improvise or use custom logic** — this prompt defines the EXACT sequence. Do NOT substitute your own dashboard creation workflow, skip gates, or collapse multiple steps into a single API call. Every numbered step in this prompt exists because prior runs failed when it was skipped.
11. **DO NOT use `query` (string) in dataset objects** — MUST use `queryLines` (array of strings) per `lakeview_dashboard_api.md`. Using `query` causes silent rendering failures.
12. **DO NOT call `w.lakeview.create()` before Steps 1-11 are complete** — the design contract, dataset validation YAML, and preflight structural validation MUST all exist first. Jumping to API creation "because the dashboard seems simple" is the #1 cause of dashboard failures.
13. **DO NOT use `execute_python` for dashboard creation or publishing** — the subprocess has NO WorkspaceClient, NO Databricks SDK access, and NO API tokens. Use the `create_dashboard` and `publish_dashboard` tools instead. Any Python code using `w.lakeview.*`, `w.api_client.do(...)`, or `requests.post(...)` will FAIL.
14. **DO NOT use `multilineTextboxSpec` as a plain string for text widgets** — the Lakeview API rejects plain strings and returns `'failed to parse serialized dashboard'`. The field MUST be an object: `"multilineTextboxSpec": {"value": "<markdown>"}`. Also NEVER use `textboxSpec` or `textbox_spec` (wrong key names). The template's `build_text_widget()` handles this correctly; always use it.

### HARD STOP RULE: No Divergence from This Prompt

If the executing agent:
- Skips reading `lakeview_dashboard_api.md` and constructs JSON from model knowledge → **INVALID**
- Creates 1 dashboard when 2+ are configured → **INVALID**
- Creates 1 canvas page per dashboard when KPI spec maps multiple pages → **INVALID**
- Calls `w.lakeview.create()` without first writing `dashboard_design.yaml` → **INVALID**
- Uses `"query": "..."` instead of `"queryLines": ["..."]` in datasets → **INVALID**
- Omits filter widgets entirely → **INVALID**
- Skips dataset SQL execution validation → **INVALID**

Any of these invalidate the dashboard and require re-execution from Step 1 of this prompt.

### Multi-Dashboard Enforcement

If `assets.dashboards[]` in `accelerator.yaml` contains N entries, this step MUST produce:
- N separate dashboard_design sections
- N separate Lakeview API POST calls
- N separate manifest JSON files
- N published dashboards

Creating fewer than N dashboards is a pipeline failure, not a partial success.

### Multi-Page Enforcement

The KPI spec's **Dashboard Mapping** section defines pages for each dashboard. Each mapped page becomes a separate `PAGE_TYPE_CANVAS` page in the Lakeview dashboard. The number of canvas pages MUST equal the number of pages in the Dashboard Mapping.

**Common failure mode:** The agent collapses all KPIs onto a single canvas page "for simplicity" or "because there are only 6 widgets." This is PROHIBITED regardless of widget count. If the KPI spec maps 2 pages (e.g., "Executive Summary" + "Trend Analysis"), the dashboard MUST have 2 canvas pages.

**Counting rule:**
- `PAGE_TYPE_GLOBAL_FILTERS` pages do NOT count as analytical pages
- Only `PAGE_TYPE_CANVAS` pages count
- If KPI spec maps P pages → dashboard has P canvas pages + 1 filter page = P+1 total pages

**Validation (GATE 3.2):** After writing `dashboard_design.yaml`, count canvas pages per dashboard. If any dashboard has fewer canvas pages than its KPI spec mapping defines → **HALT. Do NOT proceed to dataset SQL.**

### Filter Enforcement

Every dashboard MUST include:
- At minimum 3 dimension filters (configurable by KPI spec)
- Date/time range filter if temporal dimensions exist
- Filters MUST be functional (bound to actual dataset columns)
- Dashboard without filters = pipeline failure

---

# Core Principle

Dashboard creation MUST follow this dependency chain:

```text
KPI specification
        +
metric_view_design.yaml
        +
metric_view_validation.yaml
        ↓
Validated KPI inventory
        ↓
Dashboard analytical design
        ↓
Dataset design
        ↓
SQL execution validation
        ↓
Widget design
        ↓
serialized_dashboard
        ↓
Lakeview API
        ↓
GET persisted dashboard
        ↓
Publish
        ↓
Post-deployment validation
```

Do not skip stages.

A dashboard API call succeeding does NOT prove that the dashboard is analytically or visually correct.

---

## MANDATORY: Use Deterministic Helpers

The `lakeview_dashboard_helpers.py.template` provides **programmatic builders** that guarantee structurally valid dashboard JSON. The LLM decides WHAT goes in (which KPIs, chart types, filters) but MUST use these builders to construct the JSON.

**Required workflow:**

```python
# 1. Discover actual metric view columns (SINGLE SOURCE OF TRUTH)
columns = describe_metric_view(metric_view_fqn)
validate_column_refs(columns, [list of columns you'll use], "dataset_name")

# 2. Build datasets WITH validation (SQL must execute before assembly)
ds = build_validated_dataset("ds_name", sql, "Display Name")

# 3. Build filters page using shared dataset (deterministic structure)
filters_page = build_filters_page(dataset_name, filter_dimensions)

# 4. Build canvas widgets using builder functions
widget = build_counter(name, dataset_name, field_name, display, title, agg)
widget = build_bar_chart(name, dataset_name, x_field, y_field, y_display, title)
widget = build_line_chart(name, dataset_name, x_field, y_field, y_display, title)

# 5. Deploy (idempotent — updates existing if same name)
result = deploy_dashboard(display_name, warehouse_id, parent_path, datasets, pages, filter_dims)

# 6. Validate post-deploy
validate_dashboard_post_deploy(result["dashboard_id"])
```

**DO NOT:**
- Hand-write serialized_dashboard JSON from memory
- Use `"query"` (string) instead of `"queryLines"` (array)
- Create filter widgets without `queryName` in encodings
- Use `spec.version: 1` for filters (MUST be 2)
- Reference columns not returned by `describe_metric_view()`

---

# Critical Ownership Boundary

The Dashboard stage MUST NOT redefine metric semantics.

The Metric View stage owns:

- KPI definition;
- measure formula;
- numerator/denominator logic;
- aggregation semantics;
- fact grain;
- dimensional relationships;
- Metric View source selection.

The Dashboard stage owns:

- KPI presentation;
- dataset queries;
- visualization selection;
- filters;
- page composition;
- layout;
- interaction;
- deployment.

If a metric appears incorrect, missing, or unsupported:

```text
DO NOT REIMPLEMENT THE KPI IN DASHBOARD SQL
```

Return the issue to the Metric View contract.

Do not bypass `MEASURE()` with raw-table calculations merely to make a visualization work.

---

## State & Checkpoint Contract

This step uses **artifact-as-state** checkpointing (see `07_state_contract.md`).
The same rules apply in App mode and Genie Code — no backend infrastructure required.

**Before executing each phase**, check whether its output artifact already exists.
If it exists and is structurally valid → **skip** that phase and call `report_progress(status="completed")` immediately.
If it does not exist → execute the phase normally.

**Verification flow (run at the START of this step, after loading config):**

1. List the output folder.
2. Manage `run_context.yaml` per `07_state_contract.md` Section 8.
3. For each artifact below, apply ONE cheap check:
   - `dashboard_design.yaml` exists → skip design_dashboard
   - `dashboard_dataset_validation.yaml` exists → skip validate_datasets
   - Dashboard manifest (`*_dashboard_manifest.json`) exists with `dashboard_id` field → skip create_dashboard
   - Manifest has `published: true` → skip publish_dashboard
   - `dashboard_validation.yaml` exists → skip validate_dashboard
3. Continue from the **first phase whose artifact is missing**.

**Rules:**

- Every `report_progress(status="completed")` marks a phase as done.
- **Never re-execute a phase whose output artifact already exists and is structurally valid.**
- For dashboards: if manifest contains a valid `dashboard_id`, **UPDATE** the existing dashboard rather than creating a new one.
- If `RESUME_CONTEXT` is provided (App mode), use it to accelerate. Otherwise, discover state from the output folder.

**Artifact-as-State mapping:**

| Phase | Artifact | Skip when |
|-------|----------|----------|
| load_config | Config + contracts loaded | Always re-read (stateless) |
| design_dashboard | dashboard_design.yaml | file exists |
| validate_datasets | dashboard_dataset_validation.yaml | file exists |
| create_dashboard | *_dashboard_manifest.json | file exists + contains dashboard_id |
| publish_dashboard | manifest.published = true | manifest field check |
| validate_dashboard | dashboard_validation.yaml | file exists |

---

# Step 1: Load Configuration and Contracts

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "load_config"
> - `phase_name`: "Load Configuration"
> - `status`: "started"
> - `current_task`: "Loading configuration and metric contracts"
> - `happenings`: ["Reading accelerator.yaml", "Loading metric view contracts", "Resolving dashboard assets"]

Read:

```text
accelerator.yaml
```

and apply name suffix resolution from Step 0 of `00_master_prompt.md`.

Load the **Lakeview API contract** (`lakeview_dashboard_api.md`):

1. **Check first:** If the system message already contains a section labeled
   `--- BEGIN inputs/lakeview_dashboard_api.md ---` (injected as SUPPLEMENTARY REFERENCE),
   the file is already loaded — skip the read and proceed.
2. **Otherwise read it** from:
   ```text
   {deploy_root}/framework/inputs/lakeview_dashboard_api.md
   ```

This file is **MANDATORY**.

### HARD GATE: lakeview_dashboard_api.md Must Be Loaded

If `lakeview_dashboard_api.md` is neither in the system supplement NOR readable from the path above:

```text
❌ EXECUTION HALTED
Cannot proceed with dashboard creation without the Lakeview API contract reference.
Do NOT guess JSON structure from model knowledge.
```

This gate exists because the Lakeview serialized_dashboard format has non-obvious structural requirements (e.g., widget nesting under a `widget` key, page types, filter page separation) that CANNOT be reliably inferred from general knowledge. Every prior attempt to skip this file resulted in:

- `child node [widget] not found` errors
- Silent widget rendering failures
- Missing filters
- Incorrect disaggregated settings

The file is the project-level authoritative contract for:

- `serialized_dashboard` structure;
- page structure;
- widget structure;
- visualization specifications;
- supported `spec.version` values;
- encoding structures;
- field naming;
- dataset representation;
- filter representation;
- layout representation;
- API helper usage.

---

# Serialization Authority Rule

Do NOT construct Lakeview dashboard JSON from:

- model memory;
- prior generated dashboards;
- examples from unrelated projects;
- assumptions about widget JSON;
- hardcoded knowledge embedded in this prompt.

Always construct serialized-dashboard objects according to:

```text
lakeview_dashboard_api.md
```

and the project's dashboard helper library/template.

If the project contract conflicts with an API error returned by the current Databricks workspace:

1. capture the API error;
2. classify it;
3. verify the current API contract;
4. update the serialization logic intentionally.

Do not randomly modify JSON fields until the API accepts the request.

### HARD GATE: No Dashboard Construction Without Design Contract

The following sequence is MANDATORY and non-negotiable:

```text
1. Load lakeview_dashboard_api.md            (JSON structure authority — check supplement first, then read from {deploy_root}/framework/inputs/)
2. Read accelerator.yaml assets.dashboards[] (how many dashboards, what names)
3. Read kpi_spec Dashboard Mapping           (which KPIs go on which dashboard/page)
4. Create dashboard_design.yaml              (full design contract with pages, widgets, filters)
5. Create + validate datasets SQL            (dashboard_dataset_validation.yaml)
6. ONLY THEN construct serialized_dashboard JSON
7. ONLY THEN call the Lakeview API
```

Skipping steps 1-5 and jumping directly to step 6 or 7 is PROHIBITED regardless of time pressure, context constraints, or perceived simplicity of the dashboard.

If `assets.dashboards[]` defines N dashboards, then N dashboards MUST be created (not 1). Each may have multiple pages as specified by the KPI spec's Dashboard Mapping.

---

# Step 1.1: Load Metric Contracts

Read when available:

```text
{OUTPUT_FOLDER}/metric_views/schema_profile.yaml
{OUTPUT_FOLDER}/metric_views/kpi_metric_mapping.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml
```

These are authoritative outputs from the Metric View stage.

Metric Views MUST already exist.

If required Metric Views do not exist:

```text
RUN 02_create_metric_views.md
```

before continuing.

---

# Step 1.2: Determine Eligible KPIs

Read the KPI specification and Dashboard Mapping.

For every KPI referenced by Dashboard Mapping, check:

```text
metric_view_validation.yaml
```

Only KPIs with:

```text
IMPLEMENTED_AND_VALIDATED
```

may be visualized as authoritative dashboard KPIs.

KPIs with statuses such as:

```text
SKIPPED_MISSING_DATA
SKIPPED_UNRESOLVED_RELATIONSHIP
SKIPPED_UNSAFE_GRAIN
SKIPPED_UNSUPPORTED_SEMANTICS
SKIPPED_UNSUPPORTED_METRIC_VIEW_FEATURE
```

must NOT be silently recreated in dashboard SQL.

Record them as:

```text
DASHBOARD_KPI_SKIPPED
```

with their existing Metric View reason.

---

# Step 1.3: Resolve Dashboard Assets

For each entry in:

```text
assets.dashboards[]
```

resolve:

```text
dashboard_id
configured_name
VERSION_SUFFIX
resolved_display_name
dashboard_mapping
target_pages
target_kpis
```

Apply the naming convention defined by the accelerator.

The resolved API `display_name` MUST follow the configured versioning/name rules.

Do not independently create another display naming convention.

---

# Step 1.4: Load Runtime Configuration

From `databricks.yml` / resolved accelerator configuration, obtain:

```text
sql_warehouse_id
workspace.current_user.userName
workspace.host
```

Use:

```text
sql_warehouse_id
```

for all dataset query execution and dashboard warehouse configuration.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "load_config"
> - `phase_name`: "Load Configuration"
> - `status`: "completed"
> - `findings`: ["{N} KPIs eligible for dashboard", "Dashboard target resolved"]
> - `stats`: {"kpis_eligible": N, "metric_views_loaded": M}

---

# Step 2: Profile Validated Metric Views

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "profile_metrics"
> - `phase_name`: "Profile Metrics"
> - `status`: "started"
> - `current_task`: "Profiling metric view fields for dashboard design"
> - `happenings`: ["Querying metric view schemas", "Building field inventory", "Resolving column types"]

## CRITICAL — Fast Path (saves 10+ tool calls)

When prior-step artifacts exist (`metric_view_design.yaml`, `metric_view_validation.yaml`, `schema_profile.yaml`):

1. These files ALREADY contain ALL measures, dimensions, types, and KPI mappings.
2. Do NOT call DESCRIBE TABLE EXTENDED on each metric view.
3. Run ONE combined SQL for row counts + date ranges:
   ```sql
   SELECT 'mv1' AS mv, COUNT(*) AS rows, MIN(service_date) AS min_dt, MAX(service_date) AS max_dt
   FROM catalog.schema.metric_view_1
   UNION ALL
   SELECT 'mv2', COUNT(*), MIN(service_date), MAX(service_date)
   FROM catalog.schema.metric_view_2
   ```
4. If needed, ONE SQL for categorical value discovery (batch all dimensions):
   ```sql
   SELECT 'claim_type' dim, claim_type val, COUNT(*) n FROM mv GROUP BY claim_type
   UNION ALL SELECT 'line_status', line_status, COUNT(*) FROM mv GROUP BY line_status
   ```
5. Build the field inventory directly from contract files.
6. Call `report_progress(profile_metrics, completed)` immediately.

## Full Profiling (fallback only — when contracts are missing)

For every Metric View required by Dashboard Mapping:

```sql
DESCRIBE TABLE EXTENDED <metric_view_fqn>
```

Profile enough data to understand:

- dimensions;
- measures;
- dates/timestamps;
- valid categorical values;
- cardinality;
- data ranges;
- null behavior;
- available periods.

Do NOT derive measure formulas from this profiling.

Metric definitions already come from the validated Metric View contract.

### Zero-Data Guard

If profiling reveals that a required Metric View returns zero rows for any basic query:

```sql
SELECT COUNT(*) FROM metric_view_fqn
```

Result = 0 → **HALT**.

```text
❌ EXECUTION HALTED
Metric View contains no data: {metric_view_fqn}
Dashboard widgets will render as empty.
Return to data layer / metric view validation.
```

Do not proceed to build widgets against an empty Metric View. This catches data layer failures before they propagate to confusing empty dashboards.

---

# Step 2.1: Build Dashboard Field Inventory

Create an internal inventory:

```yaml
metric_view:
  fqn:

measures:
  - name:
    validated_kpis:
    datatype:
    format:

dimensions:
  - name:
    datatype:
    approximate_cardinality:
    null_rate:
    used_by_kpis:
    filter_candidate:

temporal_dimensions:
  - name:
    datatype:
    min:
    max:
    used_by_kpis:
```

Use this inventory for visualization and filter selection.

---

# Step 2.2: LLM-Assisted Dashboard Design (MANDATORY)

Before writing the design contract, call a **reasoning model** (e.g., `databricks-gpt-5-5`) to propose a rich multi-page dashboard layout. This leverages the model's understanding of dashboard UX, analytical storytelling, and domain-specific visualization best practices.

## Why This Step Exists

The agent executing this pipeline may default to the simplest possible layout (one page, one counter per KPI). A reasoning model call produces domain-aware, analytically rich designs that:
- Adapt to the specific KPI domain (healthcare vs. finance vs. retail)
- Propose appropriate page structures based on KPI analytical categories
- Select visualization types matched to each KPI's data shape
- Identify optimal filter dimensions and scope
- Balance widget density across pages

## Context Assembly (BEFORE the LLM call)

Gather all of these inputs and include them in the prompt:

| Input | Source | What It Provides |
|-------|--------|------------------|
| KPI specification | `{EXAMPLE_DIR}/inputs/kpi_spec.md` | Business definitions, KPI categories, Dashboard Mapping |
| Metric View YAML | The CREATE VIEW DDL or reconstructed YAML | Exact measure names, expressions (SUM/COUNT/ratio), dimension names |
| Metric View validation | `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` | Which KPIs are IMPLEMENTED vs SKIPPED |
| Field inventory | Step 2.1 output | Data types, cardinalities, date ranges |
| Dashboard names | `accelerator.yaml` `assets.dashboards[]` | How many dashboards, their configured names |
| Categorical samples | Profiling query from Step 2 | Actual dimension values (for the model to understand the domain) |

**The metric view definition is critical** — without it, the LLM may propose widgets using measures that don't exist or misunderstand aggregation semantics (e.g., proposing SUM on a ratio measure).

To get the metric view YAML content, use:
```sql
SHOW CREATE TABLE {catalog}.{schema}.{metric_view_name}
```
or reconstruct from the metric view creation DDL stored during Step 3 (create metric views).

## LLM Call Pattern

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config

w_llm = WorkspaceClient(config=Config(http_timeout_seconds=600))

# Assemble context for the model
# CRITICAL: Include BOTH the KPI spec AND the metric view definition.
# The LLM needs to know:
#   - What KPIs exist and their business meaning (from KPI spec)
#   - What measures/dimensions are ACTUALLY available (from metric view)
#   - How measures are computed (SUM, COUNT, ratio formulas)
#   - What aggregation semantics apply (additive vs ratio vs distinct)
#   - What the source grain is (claim line, enrollment, etc.)

design_prompt = f"""
You are a senior Databricks AI/BI dashboard architect.

Given the following inputs, design a rich multi-page dashboard layout.

## KPI Specification
{kpi_spec_content}

## Metric View Definition
Metric View FQN: {metric_view_fqn}
Source Table: {source_table}
Source Grain: {source_grain}

### Measures (available via MEASURE() syntax)
{metric_view_measures_yaml}

### Dimensions (available for GROUP BY and filtering)
{metric_view_dimensions_yaml}

### Metric View YAML (complete definition)
{metric_view_yaml_content}

## Metric View Validation Results
KPIs implemented and validated: {implemented_kpis}
KPIs skipped (DO NOT include these): {skipped_kpis}

## Data Profile
- Row count: {row_count}
- Date range: {min_date} to {max_date}
- Categorical value samples:
{categorical_samples}

## Dashboard Assets Configured
{dashboard_names_and_purposes}

## Aggregation Semantics Reference
- Additive measures (Total Paid, Total Claims, Line Count): Use SUM() — safe to aggregate across all dimensions
- Ratio measures (Denial Rate, Clean Claim Rate, Payment-to-Billed): Use AVG() for widget aggregation or reconstruct from components (SUM(numerator)/SUM(denominator))
- Count distinct measures: Use SUM() when pre-computed in dataset SQL via COUNT(DISTINCT ...)

## Requirements
1. Each dashboard MUST have multiple canvas pages (minimum 2-3 per dashboard)
2. Each primary KPI should appear in AT LEAST 2 different visualization contexts across pages
   (e.g., Total Paid as counter on Summary page AND as line chart on Trends page AND as bar chart on Segments page)
3. Pages must have clear analytical purposes:
   - Executive Summary: headline counters + 1-2 contextual charts
   - Trend Analysis: line charts showing KPIs over time (monthly/quarterly)
   - Segment Breakdown: bar/pie charts showing KPIs by each dimension
   - Quality/Performance: rate and ratio KPIs with comparisons
   - Detail View: tables with multi-dimensional breakdowns
4. Include 4-8 widgets per page for a rich analytical experience
5. Use at least 3 different visualization types per dashboard (counter, line, bar, pie, table)
6. Identify which dimensions make the best global filters (high analytical value, moderate cardinality)
7. For each widget, specify: title, KPI/measure, visualization type, dimensions used, aggregation
8. Consider which measures are additive (safe to SUM) vs ratios (need AVG or component reconstruction)
9. Only use measures and dimensions that actually exist in the metric view definition above

## Output Format
Return a YAML structure with this exact format:

dashboards:
  - name: <dashboard_display_name>
    purpose: <one-line analytical purpose>
    pages:
      - page_name: <name>
        purpose: <analytical intent of this page>
        widgets:
          - title: <widget title>
            kpi: <KPI name from spec>
            measure: <exact metric view measure name>
            viz_type: counter | line | bar | pie | table
            dimensions: [<exact dimension names from metric view>]
            aggregation: SUM | AVG | component_ratio
            rationale: <why this viz type for this KPI on this page>
        ...
    filters:
      - dimension: <exact dimension name from metric view>
        filter_type: multi-select | date-range-picker | single-select
        scope: global | page-specific
        rationale: <why this filter is valuable for analysis>
"""

response = w_llm.api_client.do(
    "POST",
    f"/serving-endpoints/{design_model}/invocations",
    body={
        "messages": [
            {"role": "system", "content": "You are a dashboard design architect. Output valid YAML only."},
            {"role": "user", "content": design_prompt},
        ],
        "max_tokens": 16000,
        "temperature": 1,
    }
)
dashboard_design_yaml = response["choices"][0]["message"]["content"]
```

## Model Selection

Use the model configured in `accelerator.yaml` under `llm.steps.dashboard_design.model`.
Fallback: use the same reasoning model as the ERD parse step (e.g., `databricks-gpt-5-5`).

## Validation of LLM Output

After receiving the model's proposed design, validate:

1. **Page count**: Each dashboard has ≥ 2 canvas pages (reject single-page designs)
2. **Widget density**: Each page has 4-8 widgets (flag sparse or overloaded pages)
3. **Viz diversity**: At least 3 different viz types per dashboard
4. **KPI coverage**: Every IMPLEMENTED_AND_VALIDATED KPI appears in at least 1 widget
5. **Multi-variation**: Primary KPIs appear in ≥ 2 different viz contexts
6. **Measure validity**: Every `measure` field in the LLM output matches an EXACT measure name from the metric view YAML (e.g., "Total Paid Amount" not "total_paid")
7. **Dimension validity**: Every `dimensions[]` entry matches an EXACT dimension name from the metric view YAML
8. **Aggregation correctness**: Ratio/rate measures use `AVG` or `component_ratio`, NOT `SUM` (SUM of a ratio is mathematically wrong)
9. **Filter relevance**: Proposed filters reference actual metric view dimensions with moderate cardinality
10. **No SKIPPED KPIs**: Widgets do NOT reference KPIs that were SKIPPED in metric view validation

If validation fails on any point, either:
- Fix obvious issues (e.g., replace a non-existent column with the correct one from the metric view)
- Re-prompt the model with specific corrections (include the error and the correct metric view field list)
- Do NOT silently accept a single-page design
- Do NOT invent measures/dimensions not in the metric view

## Output

Save the validated design to:

```text
{workspace.output_folder}/dashboards/llm_dashboard_design.yaml
```

This becomes the AUTHORITATIVE input for Step 3 (`dashboard_design.yaml`). The design contract in Step 3 must faithfully implement the LLM-proposed structure — do not collapse pages or remove widgets.

## Skip Condition

If `{workspace.output_folder}/dashboards/llm_dashboard_design.yaml` already exists and contains valid multi-page designs for all configured dashboards → skip the LLM call and use the existing file.

---

# Step 2.3: Dataset SQL Column Resolution Rules (CRITICAL)

This section prevents the most common dashboard rendering failure: `UNRESOLVED_COLUMN` errors caused by referencing columns that do not exist in the metric view.

### Rule 1: Only Use Actual Metric View Columns

Dataset SQL MUST reference only columns that appear in the DESCRIBE output (Step 2 above).

Do NOT assume derived or transformed column names exist. Common violations:

```text
✗ service_month     (does not exist — the dimension is service_date)
✗ claim_month       (does not exist — the dimension is admit_date)
✗ member_name       (does not exist — might be mbr_full_name)
✗ provider_state    (does not exist — might be member_state)
```

If a monthly/quarterly aggregation is needed, use the date expression in the SQL:

```sql
-- CORRECT: derive from actual dimension
SELECT DATE_TRUNC('MONTH', service_date) AS service_month, ...
FROM metric_view
GROUP BY DATE_TRUNC('MONTH', service_date), ...

-- INCORRECT: assume service_month exists
SELECT service_month, ...
FROM metric_view
GROUP BY service_month, ...
```

### Rule 2: Filter Widgets Must Share Dataset with Canvas Widgets (CRITICAL)

Global filter widgets MUST reference the **SAME dataset** as the canvas widgets they filter. Do NOT create a separate `ds_filter_values` dataset for filters.

**Root cause of non-functional filters:** When filter widgets reference a different dataset than canvas widgets, Lakeview API-created dashboards do NOT auto-bind across datasets. Filters will appear to work (dropdowns populate, pills show selected values) but canvas widget values will NOT change.

```text
✗ BROKEN: Filters reference separate dataset (binding never established)
  Filter widget:  datasetName = "ds_filter_values"
  Counter widget: datasetName = "ds_kpi_headline"
  → Selecting a filter value does NOT change counter values

✓ CORRECT: Filters and canvas widgets share the same dataset
  Filter widget:  datasetName = "ds_kpi_headline"
  Counter widget: datasetName = "ds_kpi_headline"
  → Selecting a filter value narrows shared rows → counter re-aggregates
```

**Implementation pattern:**

1. Create ONE dataset per canvas page that includes BOTH filter dimensions and measures:
   ```sql
   SELECT service_date, line_of_business, claim_type, member_state,
          MEASURE(total_paid) AS total_paid, MEASURE(total_claims) AS total_claims
   FROM metric_view
   GROUP BY service_date, line_of_business, claim_type, member_state
   ```

2. Filter widgets on PAGE_TYPE_GLOBAL_FILTERS reference this same dataset with `disaggregated: true`
3. Counter/chart widgets on PAGE_TYPE_CANVAS reference this same dataset with `disaggregated: false` + SUM/AVG

The filter dimension column names MUST match actual metric view dimension names (from DESCRIBE).

Example: if the metric view has `service_date` (not `service_month`):

```text
✓ Filter on: service_date (date-range-picker)
  → Canvas datasets include: service_date in SELECT + GROUP BY
  → Filter binds correctly

✗ Filter on: service_month (derived alias)
  → Canvas datasets have: service_date (not matching)
  → Filter DOES NOT bind
```

### Rule 3: Widget `disaggregated` Mode and Aggregation Semantics (CRITICAL)

Canvas widgets MUST use `disaggregated: false` + explicit aggregation. Filter widgets MUST use `disaggregated: true`.

```text
✗ BROKEN: disaggregated=true on counters → shows single row value (e.g. "1" instead of "500")
✓ CORRECT: disaggregated=false on counters → SUM/AVG aggregates all filtered rows into total
```

| Widget type | disaggregated | Field expression | Behavior |
|-------------|---------------|------------------|---------|
| Filter | `true` | `` `column` `` | Shows distinct values for user selection |
| Counter (additive) | `false` | `SUM(\`total_paid\`)` | Sums all filtered rows into total |
| Counter (rate) | `false` | `AVG(\`denial_rate\`)` | Averages rate across filtered rows |
| Bar/Line (y-axis) | `false` | `SUM(\`total_paid\`)` | Aggregates by x-axis grouping |
| Bar/Line (x-axis) | `false` | `` `line_of_business` `` | Dimension for grouping |

When a counter widget's dataset includes filter dimensions (for cross-filter binding), the dataset returns multiple rows. The counter's field expression aggregates them.

For **additive measures** (totals, counts, sums):

```text
Widget expression: SUM(`total_paid`)     → correct (additive)
Widget expression: SUM(`total_claims`)   → correct (additive)
```

For **ratio/rate measures** (percentages, averages, rates):

```text
Widget expression: SUM(`denial_rate`)    → WRONG (cannot sum ratios)
Widget expression: AVG(`denial_rate`)    → acceptable for filtered aggregation
```

For ratio measures, use one of:

1. **AVG of pre-computed rate** (simplest, works with filters):
   ```text
   expression: "AVG(`denial_rate`)"
   ```

2. **Reconstruct from components** (most accurate):
   ```text
   expression: "SUM(`denied_lines`) / SUM(`total_claim_lines`)"
   ```

3. **Dedicated pre-aggregated dataset** (no filter-dim GROUP BY):
   ```sql
   SELECT MEASURE(denial_rate) AS denial_rate FROM metric_view
   ```
   (This dataset won't respond to filters — acceptable for headline KPIs)

### Rule 3b: SQL Generation Quality (Prevents Syntax Errors on First Execution)

When generating dataset SQL — especially UNION ALL queries:

1. **Column count alignment**: Every SELECT in a UNION ALL MUST have the exact same number of columns. Count them before writing UNION.
2. **No trailing commas**: Never leave a comma before FROM, UNION, or a closing parenthesis.
3. **Complete column names**: Never truncate or abbreviate column identifiers. Use the full column name as it appears in the metric view schema.
4. **One dataset per execute_sql**: Execute each dataset SQL individually for validation. Do NOT combine multiple unrelated datasets into one multi-statement call.
5. **Alias all computed columns**: Every expression (`SUM(...)`, `CASE WHEN...`, literals) must have an explicit `AS alias`.

If a generated SQL exceeds ~30 lines, mentally verify the structure before calling `execute_sql`:
- Count the columns in the first SELECT
- Confirm every subsequent SELECT in the UNION has the same count
- Confirm no dangling commas

### Rule 4: Mandatory Dataset SQL Validation

Before constructing `serialized_dashboard` JSON, EVERY dataset's SQL must be executed on the SQL warehouse and confirmed to return rows without error.

This is NOT optional. It is a mandatory gate (Step 7 of this prompt).

The validation query:

```sql
SELECT * FROM (<dataset_sql>) LIMIT 5
```

must succeed for every dataset. If ANY dataset fails:

```text
❌ DATASET_SQL_VALIDATION_FAILURE
Dataset: <name>
Error: <sql_error_message>
```

Do NOT construct dashboard JSON until all datasets pass.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "profile_metrics"
> - `phase_name`: "Profile Metrics"
> - `status`: "completed"
> - `findings`: ["{N} measures available", "{D} dimensions available", "Field inventory complete"]
> - `stats`: {"measures": N, "dimensions": D, "datasets_planned": K}

---

# Step 3: Build Dashboard Design Contract

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "design_dashboard"
> - `phase_name`: "Design Dashboard"
> - `status`: "started"
> - `current_task`: "Designing pages, visualizations, and filters"
> - `happenings`: ["Mapping KPIs to visualizations", "Selecting chart types", "Designing filter controls"]

Before writing dataset SQL or constructing JSON, create:

```text
{workspace.output_folder}/dashboards/dashboard_design.yaml
```

using Workspace API / agent tools.

Never use `dbutils.fs` for `/Workspace/`.

For every dashboard define:

```yaml
dashboard:
  id:
  display_name:
  metric_views: []

pages:
  - id:
    title:
    purpose:
    page_type:

    filters: []

    widgets:
      - id:
        title:
        kpi:
        measure:
        dimensions:
        visualization:
        rationale:
        dataset:
        position:
        size:
```

This design contract MUST be completed before serialized-dashboard construction.

### GATE 3.1: Page Count Validation (MANDATORY)

After writing `dashboard_design.yaml`, verify page counts match the KPI spec Dashboard Mapping:

```text
For each dashboard:
  expected_canvas_pages = count of pages defined in KPI spec Dashboard Mapping for this dashboard
  actual_canvas_pages   = count of PAGE_TYPE_CANVAS entries in dashboard_design.yaml

  IF actual_canvas_pages < expected_canvas_pages:
    → HALT: "Page count mismatch: expected {expected} canvas pages, got {actual}"
    → DO NOT proceed to dataset SQL or API creation
    → Redesign the dashboard_design.yaml to include all mapped pages
```

A dashboard with only 1 canvas page when the KPI spec defines 2+ pages is a **design contract violation**, not a simplification.

---

# Step 3.1: Dashboard Mapping Is Authoritative (KPI-Driven Design)

Dashboard creation is ENTIRELY driven by two sources:

```text
Source 1: KPI Spec (Dashboard Mapping section)
  → defines WHICH dashboards exist
  → defines WHICH pages each dashboard has
  → defines WHICH KPIs appear on each page
  → defines visualization types and layout intent
  → defines the ANALYTICAL DEPTH expected (summary vs detail vs trends)

Source 2: Metric View DESCRIBE output (Step 2 above)
  → defines ACTUAL column names available for SQL
  → defines data types (date, string, decimal, etc.)
  → defines which columns are dimensions vs measures
  → defines which dimensions support different analytical views
```

**Deriving page richness from KPI spec:**

The KPI spec doesn't just list metrics — it defines analytical categories (e.g., Enrollment KPIs, Claims KPIs, Cost KPIs, Quality KPIs, Window/Trend KPIs). Each category typically maps to at least one page, and each page should present its KPIs in the visualization style most appropriate to that category:

```text
KPI Categories → Page Mapping:
  Headline/Summary KPIs     → Executive Summary page (counters + 1-2 charts)
  Time-series/Window KPIs   → Trend Analysis page (line charts, period-over-period)
  Segment/Category KPIs     → Segment Breakdown page (bar charts, stacked bars)
  Rate/Ratio KPIs           → Quality/Performance page (gauges, bar comparisons)
  Multi-dimensional KPIs    → Detail/Drill-down page (tables, heatmaps)
```

When the KPI spec has 10+ KPIs spanning multiple analytical categories, a SINGLE canvas page is almost certainly insufficient. The design contract MUST map KPIs to pages based on their analytical category, NOT cram everything into one page.

The dashboard design is the INTERSECTION of these two sources:

```text
KPI Spec says: "Show Total Paid by Line of Business on Claims Analysis page"
DESCRIBE says: dimensions are [line_of_business, service_date, ...], measures are [total_paid, ...]
→ Dataset SQL: SELECT line_of_business, MEASURE(total_paid) AS total_paid FROM mv GROUP BY line_of_business
→ Widget: bar chart, x=line_of_business, y=sum(total_paid)
```

### What the KPI Spec determines:

```text
dashboard names and count (from accelerator.yaml assets.dashboards[])
page names and purpose
KPI-to-page assignment
visualization type per KPI
filter dimensions (from KPI required dimensions)
```

### What DESCRIBE determines:

```text
exact column names for SQL
date/temporal dimension names for DATE_TRUNC
categorical dimension names for GROUP BY
measure names for MEASURE()
```

### Prohibited:

```text
✗ Inventing dashboards not in accelerator.yaml
✗ Inventing pages not in KPI Spec Dashboard Mapping
✗ Adding KPIs not in the spec
✗ Moving KPIs to different dashboards/pages
✗ Guessing column names without DESCRIBE verification
✗ Using derived aliases (service_month) as if they were actual columns
```

Minor layout changes within a mapped page are allowed.

Semantic mapping changes are not.

---

# Step 3.2: Page Design — Rich Multi-Page KPI Visualization

Each page should have a clear analytical purpose AND present KPIs in a visualization style appropriate to that page's intent.

**CORE PRINCIPLE: KPIs should be shown in MULTIPLE variations across pages.**

A single KPI (e.g., "Total Paid Amount") is not fully represented by a single counter widget. A rich dashboard shows the same KPI from different analytical angles:

```text
Page 1 (Executive Summary): Counter showing headline total
Page 2 (Trend Analysis):    Line chart showing the same KPI over time
Page 3 (Segment Breakdown): Bar chart showing the same KPI by category
Page 4 (Detail):             Table showing the same KPI with multiple dimensions
```

This multi-variation approach is MANDATORY, not optional. The KPI spec defines WHAT to measure; the Dashboard Mapping defines WHERE to show it; the page purpose defines HOW to visualize it.

### Minimum Page Types (derive from KPI spec Dashboard Mapping)

| Page Purpose | Widget Types | KPI Presentation |
|---|---|---|
| Executive Summary | Counters, sparklines | Headline values, period comparison |
| Trend Analysis | Line charts, area charts | KPIs over time (monthly, quarterly) |
| Segment Performance | Bar charts, stacked bars | KPIs by dimension (type, status, geography) |
| Composition | Pie/donut charts | Part-to-whole distributions |
| Detailed Analysis | Tables, heatmaps | Multi-dimensional KPI breakdowns |

### Widget Density Guidelines

Each canvas page should have **4-8 widgets** for a rich analytical experience:
- Executive Summary: 4-6 counters + 1-2 charts for at-a-glance context
- Trend pages: 2-4 line/area charts showing different KPIs or the same KPI with different groupings
- Segment pages: 3-5 bar/pie charts showing KPIs sliced by different dimensions
- Detail pages: 1-2 tables + 1-2 supporting charts

**A page with only 1-2 widgets is too sparse.** Combine related visualizations to tell a coherent analytical story.

### Anti-patterns (PROHIBITED)

```text
✗ Single canvas page with all KPIs as counters only — no trend or segment analysis
✗ One counter per KPI and nothing else — produces a "wall of numbers" with no insight
✗ Putting ALL chart types on one page — splits analytical stories
✗ Skipping trend analysis when temporal data exists — wastes the time dimension
✗ Showing only top-level totals without dimensional breakdowns — hides patterns
```

Derive actual pages from Dashboard Mapping.

Avoid pages that are merely arbitrary collections of charts.

Widgets on the same page should answer related analytical questions.

---

# Step 4: Visualization Selection

Visualization choice MUST follow the analytical question and data shape.

Do not choose chart types merely to satisfy visual variety.

---

## Counter

Prefer counters for:

- headline KPIs;
- single-value measures;
- executive summary values.

Avoid counters for metrics where context/trend is essential.

---

## Line Chart

Prefer line charts for:

```text
measure over ordered time
```

provided sufficient periods exist.

Do not use a line chart merely because a date column exists.

---

## Bar Chart

Prefer bar charts for:

- category comparisons;
- rankings;
- top-N analysis;
- discrete dimension comparisons.

Horizontal bar charts are generally preferable when category labels are long.

---

## Pie / Donut

Use only when:

- representing part-to-whole composition;
- category count is small;
- categories are mutually understandable;
- percentages/composition are analytically meaningful.

Do NOT use pie charts solely to create chart-type diversity.

If cardinality is too high, use a bar chart.

---

## Table

Prefer tables when:

- precise values matter;
- multiple measures must be compared;
- detail inspection is required;
- categorical cardinality is too high for an effective chart.

---

## Visualization Diversity & Multi-Variation KPI Display

Aim for useful visualization diversity across dashboards.

If the KPI set naturally supports multiple visual forms, prefer at least several meaningful visualization types.

**Minimum visualization type diversity per dashboard:**

```text
Every dashboard with 2+ pages MUST include AT LEAST 3 of these 5 visualization types:
  1. Counter (headline values)
  2. Line chart (temporal trends)
  3. Bar chart (categorical comparisons)
  4. Pie/Donut (composition/distribution)
  5. Table (detailed multi-measure view)
```

**KPI Multi-Variation Rule:**

For every primary KPI (defined in KPI spec as a headline metric), show it in AT LEAST 2 different visualization contexts across the dashboard pages:

```text
Example: "Total Paid Amount" appears as:
  - Counter on Executive Summary page (headline value)
  - Line chart on Trends page (monthly trend)
  - Bar chart on Segments page (by claim type)

Example: "Denial Rate" appears as:
  - Counter on Summary page (headline percentage)
  - Line chart on Trends page (monthly trend)
  - Bar chart on Segments page (by claim type or provider)
```

This ensures stakeholders can analyze each KPI from multiple analytical perspectives without needing to write their own queries.

However:

```text
ANALYTICAL APPROPRIATENESS
>
CHART TYPE COUNT
```

Do not select an inappropriate chart merely to satisfy a chart-count target. But DO show each major KPI in multiple meaningful contexts — this is analytical richness, not artificial variety.

---

# Step 5: Determine Global Filters

Determine filters using BOTH:

```text
KPI specification
+
Metric View data profile
```

Do NOT hardcode domain-specific filter fields.

---

# Step 5.1: Filter Candidate Selection

A dimension is a strong global-filter candidate when:

1. it is used to slice/filter multiple KPIs;
2. it exists in the validated Metric View;
3. it has meaningful analytical variation;
4. its cardinality supports an appropriate control;
5. it can be made available to the required dashboard datasets.

Prefer dimensions that affect multiple widgets.

Avoid adding filters that apply to only one obscure visualization unless Dashboard Mapping specifically requires them.

---

# Step 5.2: Filter Type Selection

Determine filter widget type from:

```text
datatype
+
cardinality
+
business usage
```

Examples:

```text
DATE / TIMESTAMP → date-oriented control
low-cardinality categorical → multi-select/list control
numeric range → range control when supported
```

Use only filter widget types supported by:

```text
lakeview_dashboard_api.md
```

Do not invent unsupported filter types.

---

# Step 5.3: Filter Scope

Determine whether a filter should be:

```text
GLOBAL
PAGE_LEVEL
WIDGET_LEVEL
```

based on KPI Mapping and analytical intent.

**Current Lakeview API constraint:** The Lakeview API supports global filters via a `PAGE_TYPE_GLOBAL_FILTERS` page. Page-level and widget-level filters are not first-class API concepts. To scope filter impact, control which datasets expose the filter column — a filter only affects widgets whose dataset includes the matching column name.

Do not make every filter global by default.

Global filters should represent broadly applicable analytical dimensions.

To limit filter scope to specific widgets:

1. add the filter dimension column to the datasets of widgets that SHOULD respond;
2. omit it from datasets of widgets that should NOT respond.

This is the supported mechanism for filter scoping in the current API.

---

# Step 6: Dataset Design

Every widget MUST map to an explicit dataset.

For each widget create a dataset design record:

```yaml
dataset:
  name:
  widget:
  metric_view:
  measures:
  dimensions:
  filters:
  order_by:
  limit:
  expected_shape:
```

Do not construct serialized-dashboard datasets before this design exists.

---

# Step 6.1: Metric View Queries Only

Where the KPI is implemented through a Metric View, use:

```sql
MEASURE(...)
```

against the validated Metric View.

Do not recalculate the KPI against raw source tables.

Do not reproduce complex KPI formulas in dashboard SQL.

The dashboard query should primarily perform:

```text
measure selection
dimension grouping
filter exposure
sorting
top-N
time presentation
```

not semantic-model repair.

---

# Step 6.2: Global Filter Compatibility

For every global filter determine which datasets it is intended to affect.

Each applicable dataset MUST expose the filter field using the exact compatible field name required by the dashboard filter contract.

Do not blindly add every global filter column to every dataset if doing so changes the dataset's analytical grain or makes the query semantically invalid.

Instead:

1. identify the intended filter scope;
2. ensure compatible datasets expose the field;
3. ensure the resulting grouping/query remains analytically correct.

If adding a filter dimension would change a counter from:

```text
one-row result
```

to:

```text
multiple rows
```

do not simply add it to the SELECT.

Design the dataset/filter binding according to the supported Lakeview filtering contract.

Analytical correctness takes precedence over simplistic column exposure.

---

# Important Grain Rule

Never modify dataset grain merely to satisfy filter binding.

Example anti-pattern:

```sql
SELECT
    region,
    MEASURE(total_revenue)
FROM metric_view
GROUP BY region
```

for a headline counter intended to show one total value, solely because `region` is a global filter.

If the dashboard/filter API supports binding filters to source fields without changing result grain, use the supported mechanism defined in:

```text
lakeview_dashboard_api.md
```

If not, redesign the dataset/filter scope intentionally.

Do not break widget semantics.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "design_dashboard"
> - `phase_name`: "Design Dashboard"
> - `status`: "completed"
> - `findings`: ["{P} pages designed", "{W} widgets planned", "{F} filters configured"]
> - `stats`: {"pages": P, "widgets": W, "filters": F}

---

# Step 7: Build Dataset SQL

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "build_datasets"
> - `phase_name`: "Build Datasets"
> - `status`: "started"
> - `current_task`: "Building and validating dataset SQL queries"
> - `happenings`: ["Writing dataset SQL", "Executing validation queries", "Checking column resolution"]

For each planned widget:

1. generate SQL against the validated Metric View;
2. use `MEASURE()` for validated measures;
3. include required grouping dimensions;
4. include only supported filters;
5. apply ordering/Top-N where required;
6. use CTE/window logic only when the KPI/dashboard design requires it.

Each dataset SQL must have an expected result shape.

Expected shapes and SQL patterns:

```text
COUNTER → exactly one analytical row
TREND → one row per time grain
BAR → one row per category
TABLE → one row per requested dimensional combination
```

Reference MEASURE() query patterns:

**CRITICAL: Column names below are EXAMPLES ONLY. Replace with actual dimension names discovered from DESCRIBE in Step 2. Never assume a column name exists — verify against your Step 2.1 field inventory.**

```sql
-- COUNTER (one-row summary, no GROUP BY needed for overall totals)
SELECT MEASURE(total_paid) AS total_paid,
       MEASURE(total_claims) AS total_claims
FROM catalog.schema.metric_view

-- TREND (time series — use DATE_TRUNC on actual temporal dimension)
-- NOTE: Use the ACTUAL dimension name from DESCRIBE (e.g., service_date, NOT service_month)
SELECT DATE_TRUNC('MONTH', service_date) AS service_month,
       MEASURE(total_paid) AS total_paid
FROM catalog.schema.metric_view
GROUP BY DATE_TRUNC('MONTH', service_date)
ORDER BY service_month

-- BAR (category comparison — use actual dimension name from DESCRIBE)
SELECT claim_type,
       MEASURE(total_paid) AS total_paid
FROM catalog.schema.metric_view
GROUP BY claim_type

-- FILTER VALUES (dedicated filter dataset — use ACTUAL dimension names only)
SELECT DISTINCT service_date, claim_type, line_of_business
FROM catalog.schema.metric_view
```

### Filter-Compatible Canvas Datasets

Every canvas-page dataset MUST also include the global filter dimension columns (so filters can bind), as defined in `lakeview_dashboard_api.md`.

The filter column names in canvas datasets MUST exactly match the filter column names in the filter dataset. Both must use actual metric view dimension names.

```sql
-- CORRECT: filter on actual dimension (service_date), trend uses DATE_TRUNC alias
SELECT DATE_TRUNC('MONTH', service_date) AS service_month,
       service_date,           -- for filter binding
       line_of_business,       -- for filter binding
       claim_type,             -- for filter binding
       MEASURE(total_paid) AS total_paid
FROM catalog.schema.metric_view
GROUP BY DATE_TRUNC('MONTH', service_date), service_date, line_of_business, claim_type
ORDER BY service_month

-- INCORRECT: filter on derived alias that doesn't match canvas datasets
SELECT service_month,        -- DOES NOT EXIST as a metric view dimension
       MEASURE(total_paid) AS total_paid
FROM catalog.schema.metric_view
GROUP BY service_month       -- WILL FAIL: UNRESOLVED_COLUMN
```

### Counter Datasets with Filter Binding

For counters that should respond to global filters, include filter dims in the dataset:

```sql
-- Additive measures — widget uses SUM(`total_paid`) to collapse rows
SELECT service_date, line_of_business, claim_type,
       MEASURE(total_paid) AS total_paid,
       MEASURE(total_claims) AS total_claims
FROM catalog.schema.metric_view
GROUP BY service_date, line_of_business, claim_type

-- Ratio measures — widget must reconstruct from components, NOT sum the ratio
SELECT service_date, line_of_business, claim_type,
       MEASURE(denied_lines) AS denied_lines,
       MEASURE(total_claim_lines) AS total_claim_lines
FROM catalog.schema.metric_view
GROUP BY service_date, line_of_business, claim_type
-- Widget expression: "SUM(`denied_lines`) / SUM(`total_claim_lines`)"
-- NOT: "SUM(`denial_rate`)"  ← WRONG (cannot sum ratios)
```

---

# Step 7.1: Execute Every Dataset Query (BATCH VALIDATION)

Before adding any dataset to a dashboard, ALL datasets must be validated.

**CRITICAL EFFICIENCY RULE:** Do NOT validate datasets one-by-one (this wastes 10-20 tool calls). Instead, batch-validate in 2-3 SQL calls:

```sql
-- Batch 1: datasets with similar column shapes
SELECT 'ds_headline' AS _ds, * FROM (
  SELECT MEASURE(total_paid) AS total_paid, MEASURE(total_claims) AS total_claims
  FROM metric_view
) LIMIT 3
UNION ALL
SELECT 'ds_headline_rates' AS _ds, * FROM (
  SELECT MEASURE(denial_rate) AS denial_rate, MEASURE(clean_claim_rate) AS clean_claim_rate
  FROM metric_view
) LIMIT 3

-- Batch 2: datasets with dimension GROUP BY
SELECT 'ds_by_type' AS _ds, claim_type, MEASURE(total_paid) AS total_paid
FROM metric_view GROUP BY claim_type LIMIT 5
```

For datasets with incompatible column shapes (different column counts), group into 2-3 separate batches. This reduces 15+ tool calls to 2-3.

Use:

```text
sql_warehouse_id
```

Validate:

```text
query executes successfully
result is non-empty when source data exists
expected columns exist
expected aliases exist
result shape matches widget expectation
measure values are non-null where expected
dimension values are usable
row count is reasonable
```

A successful SQL statement that returns the wrong shape is a failure.

---

# Step 7.2: Dataset Validation Contract

Write:

```text
{workspace.output_folder}/dashboards/dashboard_dataset_validation.yaml
```

containing:

```yaml
datasets:

  - name:
    dashboard:
    page:
    widget:

    sql_status:
      PASS | FAIL

    metric_view:

    expected_shape:
    actual_rows:
    actual_columns:

    measures:
    dimensions:
    filters:

    semantic_status:
      PASS | FAIL

    failure_reason:
```

Only datasets with:

```text
sql_status: PASS
semantic_status: PASS
```

may be included in `serialized_dashboard`.

---

# Step 8: Build Dataset Objects

Use project helpers defined by:

```text
lakeview_dashboard_api.md
```

and:

```text
framework/templates/lakeview_dashboard_helpers.py.template
```

where configured.

Use the project's supported helpers:

```python
# Dataset
build_dataset(name, sql, display_name)

# Widget builders (canvas pages)
build_text_widget(name, markdown, position)        # uses multilineTextboxSpec (NOT textboxSpec)
build_counter(name, dataset_name, field_name, display_name, title, agg, position)
build_bar_chart(name, dataset_name, x_field, y_field, y_display, title, agg, position)
build_line_chart(name, dataset_name, x_field, y_field, y_display, title, agg, position)

# Filter widgets (MUST use same dataset_name as canvas widgets)
build_filter_widget(name, dataset_name, field_name, display_name, widget_type, position)

# Page builders
build_filters_page(dataset_name, filter_dimensions)  # PAGE_TYPE_GLOBAL_FILTERS
build_canvas_page(name, display_name, layout)        # PAGE_TYPE_CANVAS

# Assembly + validation
build_serialized_dashboard(datasets, pages, filter_dimensions)

# End-to-end
deploy_dashboard(display_name, warehouse_id, parent_path, datasets, pages, filter_dimensions)
```

### CRITICAL: Shared Dataset Pattern

`build_filter_widget` takes `dataset_name` as its SECOND argument. This MUST be the same
dataset name used by canvas widgets on the page. Do NOT create a separate `ds_filter_values` dataset.

### CRITICAL: Text Widget Format

`build_text_widget` uses `multilineTextboxSpec` (NOT `textboxSpec` or `spec`).
Using `textboxSpec` or adding a `spec` block causes: `missing spec, textbox_spec, multilineTextboxSpec`.

Every dashboard dataset MUST have a non-empty tested query.

Dataset format MUST follow `lakeview_dashboard_api.md` exactly:

```json
{
  "name": "ds_example",
  "displayName": "Example Dataset",
  "queryLines": ["SELECT ... FROM ..."]
}
```

Required properties:

- `name`: short identifier (referenced by widgets)
- `displayName`: human label
- `queryLines`: array of strings (NOT a `query` string field)

Prohibited:

```json
{"query": ""}
{"query": "SELECT ..."}
```

Using `query` (string) instead of `queryLines` (array) causes silent rendering failures. An empty-query dataset is a pipeline error.

---

# Step 8.1: Filter Dataset (DEPRECATED — Use Shared Dataset Pattern)

Do NOT create a separate `ds_filter_values` dataset. The `build_filter_dataset()` function is DEPRECATED.

Instead, include filter dimension columns in each canvas-page dataset and have filter widgets reference that same dataset. This is the ONLY pattern that enables cross-filtering in API-created dashboards.

The shared dataset pattern is:
1. ONE dataset per canvas page includes BOTH filter dimensions AND measures in GROUP BY
2. Filter widgets reference this dataset with `disaggregated: true`
3. Canvas widgets reference this dataset with `disaggregated: false` + SUM/AVG

See `lakeview_dashboard_api.md` § "Shared Dataset Pattern (REQUIRED for filters to work)" for details.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "build_datasets"
> - `phase_name`: "Build Datasets"
> - `status`: "completed"
> - `findings`: ["{N} datasets validated", "All queries execute successfully"]
> - `stats`: {"datasets_built": N, "queries_validated": N}

---

# Step 9: Construct Widgets

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "create_dashboard"
> - `phase_name`: "Create Dashboard"
> - `status`: "started"
> - `current_task`: "Constructing widgets and creating via Lakeview API"
> - `happenings`: ["Building widget specifications", "Constructing layout", "Calling Lakeview API"]

Only after dataset validation passes may widgets be generated.

For every widget validate:

```text
dataset exists
field names exist in dataset
encoding field names exactly match dataset field names
visualization type matches expected data shape
title matches KPI meaning
```

Widget JSON MUST follow:

```text
lakeview_dashboard_api.md
```

exactly.

### Critical Field Name Convention

The `query.fields[].name` MUST exactly match `spec.encodings.*.fieldName`.

For aggregated measures, the field name includes the aggregation function:

```json
"fields": [{"name": "sum(total_paid)", "expression": "SUM(`total_paid`)"}]
```

And the encoding references the same string:

```json
"encodings": {"y": {"fieldName": "sum(total_paid)", "displayName": "Total Paid"}}
```

For dimension fields, the field name matches the column:

```json
"fields": [{"name": "claim_type", "expression": "`claim_type`"}]
```

Mismatch between `fields[].name` and `encodings.*.fieldName` produces:

```text
"Visualization has no fields selected"
```

This is the single most common widget rendering failure.

---

# Widget Specification Rule

Do NOT hardcode widget:

```text
spec.version
encodings
field structures
queryName behavior
```

from model memory.

Use the exact current definitions contained in:

```text
lakeview_dashboard_api.md
```

If that file defines different structures for:

```text
counter
bar
line
pie
table
filter
```

follow them exactly.

---

# Step 10: Layout Design

Build canvas layouts according to the grid/layout contract in:

```text
lakeview_dashboard_api.md
```

Design rules:

- avoid overlapping widgets;
- avoid unintended gaps;
- align related widgets;
- use consistent sizing;
- make headline KPIs visually prominent;
- give detailed charts sufficient space;
- keep analytical flow readable from top to bottom.

Do not optimize for maximum widget density.

Prefer clarity.

---

# Step 10.1: Page Validation

Before API creation validate every page:

```text
page has valid page type
page has widgets
all widget positions are valid
no overlapping layout coordinates
all referenced datasets exist
all widget field references resolve
```

---

# Step 11: Build serialized_dashboard

Construct the dashboard only through the project builder defined by:

```text
lakeview_dashboard_api.md
```

For example, when supported:

```python
serialized_dashboard = build_serialized_dashboard(
    datasets=datasets,
    pages=pages,
    filter_dimensions=filter_dims
)
```

The exact signature must come from the current project helper.

Do not guess helper arguments.

---

# Step 11.1: Preflight Structural Validation

Before calling the Lakeview API validate:

```text
serialized_dashboard is non-empty
datasets exist
every dataset has tested non-empty SQL
pages exist
every page contains valid widgets
every widget references an existing dataset
every encoding field resolves
filter references resolve
layout is complete
```

If any preflight check fails:

```text
DASHBOARD_SERIALIZATION_VALIDATION_FAILURE
```

Do NOT call the Create Dashboard API.

---

# Step 12: Idempotency

For every resolved dashboard display name:

list existing dashboards using the supported Lakeview API.

Handle pagination completely.

Match dashboards according to the accelerator's resolved identity rules.

Do NOT use:

```text
subprocess
databricks CLI
```

inside notebooks.

Use:

```text
Databricks SDK
WorkspaceClient API client
or supported REST agent tools
```

---

# Idempotency Strategy

Use the strategy configured by the accelerator.

Preferred behavior:

```text
existing matching dashboard
        ↓
update existing draft when supported/configured
```

rather than deleting a dashboard unnecessarily.

If the project's versioning strategy intentionally creates immutable versioned dashboard names, creation of the new version is acceptable.

If the configured strategy requires replacement:

```text
delete existing matching version
        ↓
create replacement
```

Do not delete unrelated dashboard versions.

---

# Step 13: Create Dashboard Through Lakeview API

### Pre-Flight Checklist

Before calling the Lakeview Create/Update API, confirm ALL of:

- [ ] `dashboard_design.yaml` exists (Step 3 complete)
- [ ] `dashboard_dataset_validation.yaml` shows ALL datasets as `sql_status: PASS` + `semantic_status: PASS`
- [ ] `serialized_dashboard` contains `datasets` AND `pages` (never datasets-only)
- [ ] Every page has `pageType` set (`PAGE_TYPE_GLOBAL_FILTERS` or `PAGE_TYPE_CANVAS`)
- [ ] Every widget references an existing dataset by `datasetName`
- [ ] Every widget `query.fields[].name` exactly matches `spec.encodings.*.fieldName`
- [ ] Counter widgets use `spec.version: 2`
- [ ] Chart widgets (bar/line/pie) use `spec.version: 3`
- [ ] Filter widgets use `spec.version: 2` with `queryName` in `encodings.fields[]`
- [ ] Canvas widget queries have `disaggregated: false`; filter queries have `disaggregated: true`
- [ ] `display_name` uses snake_case versioned format from accelerator.yaml
- [ ] `warehouse_id` is set

If any item fails, return to the relevant design/build step. Do NOT call the API with known defects.

### Critical Lakeview JSON Structure Rules

These rules reflect the actual Lakeview API contract as validated in production. Violations produce `child node [widget] not found` or silent rendering failures.

**1. Layout item nesting:** Each layout item wraps the widget under a `widget` key, with `position` as a sibling:

```text
pages[].layout[] = {
  "widget": { "name": ..., "queries": [...], "spec": {...} },
  "position": { "x": 0, "y": 0, "width": 2, "height": 2 }
}
```

INCORRECT (causes `child node [widget] not found`):

```text
pages[].layout[] = {
  "name": ..., "queries": [...], "spec": {...}, "position": {...}
}
```

**2. Page types:** The `serialized_dashboard` must include a `PAGE_TYPE_GLOBAL_FILTERS` page for filters, and `PAGE_TYPE_CANVAS` pages for widgets. Filter pages are separate from canvas pages.

**3. Deployment method — use the `create_dashboard` tool (MANDATORY):**

```text
Tool: create_dashboard
Args:
  display_name: "<configured_name_from_accelerator.yaml>"
  serialized_dashboard: "<JSON string of the full serialized dashboard spec>"
  warehouse_id: "<warehouse_id>"
```

Returns: `SUCCESS: Dashboard ID: <id>`

**CRITICAL:** Do NOT use `execute_python` with SDK calls (`w.lakeview.create(...)`, `w.api_client.do(...)`) — the subprocess has NO WorkspaceClient and NO access to Databricks APIs.
Do NOT use `requests.post()` with tokens.
The `create_dashboard` tool handles authentication, parent_path resolution, and error handling internally.

**4. Publish after create — use the `publish_dashboard` tool (MANDATORY):**

```text
Tool: publish_dashboard
Args:
  dashboard_id: "<id returned from create_dashboard>"
  warehouse_id: "<warehouse_id>"
```

Always call `publish_dashboard` immediately after successful `create_dashboard`.

**5. Multiple dashboards:** When `accelerator.yaml` defines `assets.dashboards[]` as an array with multiple entries, create ALL configured dashboards — not just one. Each may have multiple pages.

Use the official Lakeview Dashboard API.

The API call MUST use the exact Create Dashboard request contract defined by the current Databricks API and the project's helper implementation.

Conceptually:

```text
POST
/api/2.0/lakeview/dashboards
```

using the required fields such as the resolved dashboard metadata and serialized definition according to the current API contract.

Do not construct undocumented top-level request properties.

Do not use Workspace file import as a substitute for the Lakeview Create Dashboard API unless the accelerator explicitly configures import/export deployment.

---

# Step 13.1: Capture Create Response

Capture:

```text
dashboard_id
display_name
etag when available
path when available
API status
```

Do not assume creation succeeded solely because no exception was thrown.

Validate the response contains the required dashboard identity.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "create_dashboard"
> - `phase_name`: "Create Dashboard"
> - `status`: "completed"
> - `findings`: ["Dashboard created via Lakeview API", "Draft published"]
> - `stats`: {"widgets_created": W, "pages_created": P}

---

# Step 14: Retrieve Persisted Draft

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_publish"
> - `phase_name`: "Validate & Publish"
> - `status`: "started"
> - `current_task`: "Validating dashboard and running post-publish checks"
> - `happenings`: ["Structural diff check", "Filter validation", "KPI coverage validation"]

Immediately after create/update, retrieve the dashboard through the Lakeview Get Dashboard API.

Compare the persisted representation with the intended dashboard design.

Validate at minimum:

```text
dashboard exists
display_name matches
warehouse configuration matches
serialized dashboard exists
expected pages exist
expected datasets exist
expected widgets exist
```

This step is mandatory.

The API-persisted dashboard is authoritative after creation.

---

# Step 14.1: Structural Diff

Compare:

```text
INTENDED DASHBOARD
vs
PERSISTED DASHBOARD
```

Check:

```text
dataset count
page count
widget count
filter count
dataset names
page names
widget identities
```

Do not require byte-for-byte serialized JSON equality because the service may normalize representation.

Validate semantically relevant structure.

---

# Step 15: Publish

Only publish after persisted-draft validation passes.

Use the supported Lakeview Publish Dashboard API/helper.

Capture publication response.

If publishing fails:

```text
DASHBOARD_PUBLISH_ERROR
```

Do not report the dashboard as complete.

---

# Step 16: Post-Publish Validation

Validate the published dashboard.

Where API capabilities allow, verify:

```text
published state
dashboard identity
warehouse
page/widget inventory
```

Also execute representative underlying dataset queries to ensure data remains available.

---

# Step 16.1: Filter Validation

For every filter validate:

```text
filter field exists
filter dataset/source exists where required
compatible target datasets exist
field names match exactly
filter has usable values
```

For categorical filters:

```text
distinct usable values > 0
```

when source data exists.

For temporal filters:

```text
valid min/max range
```

when source data exists.

---

# Step 16.2: Filter Impact Validation

Do not validate filters only structurally.

For representative filters, test that applying a valid dimension value changes or appropriately constrains the underlying KPI dataset.

Conceptually:

```text
UNFILTERED KPI
vs
FILTERED KPI
```

The filtered result should be analytically consistent with the filter.

This test must use the same validated Metric View.

---

# Step 17: KPI Coverage Validation

For every KPI from Dashboard Mapping report one of:

```text
RENDERED_AND_VALIDATED
SKIPPED_NOT_VALIDATED_IN_METRIC_LAYER
SKIPPED_MISSING_DATA
SKIPPED_UNSUPPORTED_VISUALIZATION
DASHBOARD_GENERATION_FAILURE
```

Every validated KPI assigned to the dashboard must either be rendered successfully or have an explicit dashboard-stage failure reason.

---

# Step 18: Visualization Validation

For every widget validate:

```text
KPI maps to correct measure
dimensions match Dashboard Mapping
chart type is appropriate
dataset shape matches visualization
field references resolve
data exists when expected
title accurately describes content
```

Do NOT consider a widget valid simply because its JSON is accepted by the API.

---

# Step 19: Dashboard Validation Artifact

Write:

```text
{workspace.output_folder}/dashboards/{name}_validation.yaml
```

using Workspace API / agent tools.

Include:

```yaml
dashboard:
  dashboard_id:
  display_name:
  status:
  published:

source_metric_views: []

pages:
  expected:
  actual:
  status:

datasets:
  expected:
  actual:
  empty_queries:
  failed_queries:
  status:

widgets:
  expected:
  actual:
  invalid_widgets:
  status:

filters:
  expected:
  actual:
  binding_failures:
  impact_tests:
  status:

kpis:
  - name:
    metric_validation_status:
    dashboard_status:
    widget:
    page:

api:
  create_status:
  get_status:
  publish_status:

overall_status:
  PASS | FAIL
```

---

# Step 20: Dashboard Manifest

Write:

```text
{workspace.output_folder}/dashboards/{name}_manifest.json
```

containing:

```json
{
  "dashboard_id": "...",
  "display_name": "...",
  "metric_views": [],
  "pages": [],
  "dataset_count": 0,
  "widget_count": 0,
  "filter_count": 0,
  "published": true
}
```

The manifest is metadata only.

The actual deliverable remains the live Lakeview dashboard.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_publish"
> - `phase_name`: "Validate & Publish"
> - `status`: "completed"
> - `findings`: ["Dashboard published", "All validations passed", "KPI coverage: {N}/{T}"]
> - `stats`: {"validations_passed": N, "kpi_coverage_pct": P}

---

# Step 21: Final Summary

For each dashboard present:

| Check | Result |
|---|---|
| Validated KPIs mapped | PASS/FAIL |
| Dataset SQL | PASS/FAIL |
| Widget definitions | PASS/FAIL |
| Page/layout validation | PASS/FAIL |
| Create API | PASS/FAIL |
| Persisted draft GET | PASS/FAIL |
| Publish API | PASS/FAIL |
| Filters | PASS/FAIL |
| KPI coverage | PASS/FAIL |
| Overall | PASS/FAIL |

Include the deployed dashboard ID.

---

# Error Classification

Use one of:

```text
DASHBOARD_INPUT_ERROR
METRIC_VIEW_NOT_VALIDATED
KPI_MAPPING_ERROR
DASHBOARD_DESIGN_ERROR
DATASET_SQL_ERROR
DATASET_SHAPE_ERROR
FILTER_DESIGN_ERROR
FILTER_BINDING_ERROR
FILTER_IMPACT_ERROR
WIDGET_SPEC_ERROR
WIDGET_FIELD_ERROR
LAYOUT_ERROR
DASHBOARD_SERIALIZATION_ERROR
DASHBOARD_API_CREATE_ERROR
DASHBOARD_API_UPDATE_ERROR
DASHBOARD_API_GET_ERROR
DASHBOARD_API_DELETE_ERROR
DASHBOARD_PUBLISH_ERROR
PERSISTED_DASHBOARD_MISMATCH
WORKSPACE_IO_ERROR
```

For every error provide:

```text
Observed problem:
Root cause:
Authoritative evidence:
Dashboard:
Page:
Widget:
Dataset:
Affected KPI(s):
Corrective action:
Affected downstream artifacts:
```

---

# Retry Policy

Blind retries are prohibited.

Do NOT:

```text
create
fail
change random JSON
retry
change widget version
retry
change encodings
retry
```

When an error occurs:

1. capture the complete API response or SQL error;
2. classify the failure;
3. identify the responsible contract;
4. make one targeted correction;
5. rerun the relevant preflight validation;
6. retry only after the root cause is understood.

Maximum API creation/update attempts:

```text
3
```

Each retry must have a documented cause and correction.

---

# Pipeline Halt Rules

Return:

```text
❌ EXECUTION HALTED
```

when any mandatory dashboard cannot be reliably deployed.

Halt conditions include:

- required Metric View does not exist;
- required KPI is marked validated but its Metric View measure cannot be queried;
- dataset SQL fails after diagnosed corrections;
- dataset result shape is incompatible with the intended widget;
- serialized dashboard fails preflight validation;
- required widget references nonexistent fields;
- Lakeview API rejects the dashboard after diagnosed corrections;
- persisted dashboard differs materially from intended design;
- dashboard cannot be published;
- mandatory filters cannot be bound correctly.

A failure isolated to an optional KPI/widget does not necessarily halt unrelated dashboards.

Document and continue when safe.

---

# Non-Negotiable Rules

1. **Dashboard logic consumes validated Metric Views; it does not redefine metrics.**
2. **Only `IMPLEMENTED_AND_VALIDATED` KPIs are authoritative dashboard KPIs.**
3. **Never repair Metric View modeling problems inside dashboard SQL.**
4. **Use `MEASURE()` for validated Metric View measures.**
5. **Dashboard Mapping controls KPI-to-dashboard/page assignment.**
6. **Visualization type must follow analytical intent and result shape.**
7. **Do not use pie charts merely for visual diversity.**
8. **Do not hardcode domain-specific filters.**
9. **Do not change dataset grain merely to expose a global filter column.**
10. **Every widget dataset must be executed and validated before dashboard creation.**
11. **Every dataset must contain non-empty SQL.**
12. **Dataset execution success alone does not prove correct dataset shape.**
13. **Every widget field reference must exactly resolve to its dataset.**
14. **`lakeview_dashboard_api.md` is authoritative for serialized-dashboard structure.**
15. **Do not hardcode widget serialization details in this orchestration prompt.**
16. **Use the official Lakeview API / SDK API client for live dashboard deployment.**
17. **Do not use Databricks CLI via subprocess in notebooks.**
18. **Do not use `.lvdash.json` workspace files as the deployed dashboard deliverable.**
19. **Retrieve the persisted dashboard after creation/update and validate it.**
20. **Publish only after persisted-draft validation passes.**
21. **API success does not prove analytical dashboard correctness.**
22. **Validate filter binding and representative filter impact.**
23. **Never use blind API retries.**
24. **Workspace artifact writes use `workspace_file_io.md`, never `dbutils.fs`.**
25. On unrecoverable mandatory failure:

```text
❌ EXECUTION HALTED
```

---

# Output Contract

At the END of this step, the following artifacts MUST exist for EACH dashboard in `assets.dashboards[]`:

| Artifact | Location | Validation Check |
|----------|----------|-----------------|
| dashboard_design.yaml | `{OUTPUT_FOLDER}/dashboards/` | Contains pages[], widgets[], filters[] for EACH dashboard |
| dashboard_dataset_validation.yaml | `{OUTPUT_FOLDER}/dashboards/` | All dataset queries executed successfully |
| {name}_dashboard_manifest.json | `{OUTPUT_FOLDER}/dashboards/` | Contains `dashboard_id`, `published: true` |
| Live dashboard in workspace | Databricks workspace | GET /api/2.0/lakeview/dashboards/{id} returns valid response |
| Published dashboard | Databricks workspace | Dashboard is accessible via published URL |

### Per-Dashboard Requirements

Each manifest MUST confirm:
- `pages_count` matches KPI spec Dashboard Mapping
- `widgets_count` > 0 per page
- `filters_count` >= 3 (dimension filters)
- `datasets_validated: true`
- `published: true`

If ANY artifact is missing or any dashboard is not published, the step has NOT completed successfully.

---

# Validated Learnings (from production runs)

**1. `multilineTextboxSpec` NOT `textboxSpec` for text/title widgets**

Using `textboxSpec` (or adding a `spec` block to text widgets) causes:
`validation failed: missing spec, textbox_spec, multilineTextboxSpec, or imageSpec`.

Text widgets MUST use only:
```json
{"widget": {"name": "title-1", "multilineTextboxSpec": "## Page Title"}, "position": {...}}
```
No `spec`, no `queries`, no `textboxSpec` — just `name` + `multilineTextboxSpec`.

**2. `uiSettings` format must include `theme` and `applyModeEnabled`**

Using `{"themeColors": {}}` causes `failed to parse serialized dashboard`.

Correct format:
```json
"uiSettings": {"theme": {"widgetHeaderAlignment": "ALIGNMENT_UNSPECIFIED"}, "applyModeEnabled": false}
```

**3. Separate filter datasets break cross-filtering**

Creating a dedicated `ds_filter_values` dataset for filters causes filters to populate but NOT bind to canvas widgets. The API does not auto-bind across datasets.

Fix: Filter widgets and canvas widgets MUST reference the SAME `datasetName`.

**4. `publish_dashboard` requires `warehouse_id` + `embed_credentials`**

Calling publish without a body (or with empty body) may succeed but the published dashboard won't render. Always pass:
```json
{"warehouse_id": "<id>", "embed_credentials": true}
```

**5. Counter widgets for rates/ratios MUST use AVG, not SUM**

When a shared dataset includes filter dimensions (multiple rows), counters aggregate with SUM/AVG.
- Additive measures (total_paid, total_claims): use `SUM`
- Rate measures (denial_rate, clean_claim_rate): use `AVG` (summing ratios is mathematically wrong)

**6. Widget `name` must be alphanumeric/hyphens/underscores only**

Spaces, special characters, or dots in widget names cause silent failures.

**7. `queryLines` concatenation uses NO separator**

Array elements join with no space between them. Either use a single-element array (one long SQL string) or end each element with a space character.

---

# MANDATORY PRE-DEPLOY SELF-CHECK (read LAST before any API call)

## Why This Section Exists

In prior runs, the executing agent read all prior sections, understood the intent, then shortcut the process by hand-constructing API payloads. This resulted in:
- Incorrect display names (human-friendly instead of configured snake_case)
- Broken FQN quoting (entire 3-part name in one backtick pair → rendering failure)
- Skipped template usage (hand-rolled JSON instead of `deploy_dashboard()`)

This section exists at the END of the prompt to leverage recency bias. These checks are NON-NEGOTIABLE.

## Pre-Deploy Check Artifact (GATE)

**Before ANY call to `POST /api/2.0/lakeview/dashboards`**, the agent MUST produce and print the following self-check. If ANY check shows `FAIL`, the agent MUST NOT proceed.

```yaml
# pre_deploy_check (print to stdout before API call)
dashboard_name_check:
  configured_name: "{exact value from assets.dashboards[].name + VERSION_SUFFIX}"
  name_being_used: "{exact value being passed as display_name}"
  match: true/false  # MUST be true

fqn_format_check:
  fqn_in_dataset_sql: "{exact FQN string as it appears in queryLines}"
  format: "3_separate_backtick_pairs"  # MUST be this value
  # CORRECT: `catalog`.`schema`.`table`
  # WRONG:  `catalog.schema.table`
  valid: true/false  # MUST be true

template_usage_check:
  helper_function_used: "{function name from lakeview_dashboard_helpers.py.template}"
  # Expected: deploy_dashboard() or build_validated_dataset()
  # FAIL if: "none" or "hand-constructed JSON"
  valid: true/false

dataset_sql_execution_check:
  all_datasets_executed: true/false  # MUST be true
  failed_datasets: []  # MUST be empty
```

**Rules:**
- If `dashboard_name_check.match` is `false` → **HALT. Fix the name.**
- If `fqn_format_check.valid` is `false` → **HALT. Fix the quoting.**
- If `template_usage_check.valid` is `false` → **HALT. Use the template.**
- If `dataset_sql_execution_check.all_datasets_executed` is `false` → **HALT. Execute SQL first.**

Producing this check takes 10 seconds. Skipping it and deploying a broken dashboard wastes 10+ minutes of debugging.

---

# CORRECT vs WRONG Examples (Critical Reference)

These examples show the EXACT correct patterns and the EXACT errors from prior failed runs.

## Display Name

```python
# ✅ CORRECT — uses configured name from accelerator.yaml
"display_name": "member_claims_kpis_dashboard_v3"

# ❌ WRONG — agent invented a human-friendly name
"display_name": "Member Claims KPIs v3"
"display_name": "Member Claims KPIs Dashboard v3"
"display_name": "KPIs Dashboard"
```

The display_name MUST be the exact string from `assets.dashboards[].name` + `VERSION_SUFFIX`. No spaces, no title case, no reformatting.

## Metric View FQN in SQL

```sql
-- ✅ CORRECT — each segment separately backtick-quoted
SELECT MEASURE(`Total Paid Amount`)
FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v3`
GROUP BY ALL

-- ❌ WRONG — entire 3-part name in one backtick pair (causes rendering failure)
SELECT MEASURE(`Total Paid Amount`)
FROM `aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v3`
GROUP BY ALL
```

The FQN MUST use 3 separate backtick pairs: `` `catalog`.`schema`.`table` ``. Never `` `catalog.schema.table` ``.

## Tool Usage (MANDATORY)

```text
# ✅ CORRECT — use the create_dashboard tool
Tool: create_dashboard
Args:
  display_name: "<configured_name_from_accelerator.yaml>"
  serialized_dashboard: "<json.dumps(full_spec)>"
  warehouse_id: "<warehouse_id>"

# ❌ WRONG — execute_python with SDK calls (subprocess has no WorkspaceClient)
execute_python with code: w.lakeview.create(...)
execute_python with code: w.api_client.do("POST", ...)
execute_python with code: requests.post(...)
```

## Publish Call (MANDATORY)

```text
# ✅ CORRECT — use the publish_dashboard tool
Tool: publish_dashboard
Args:
  dashboard_id: "<id from create_dashboard response>"
  warehouse_id: "<warehouse_id>"

# ❌ WRONG — execute_python with SDK publish calls
execute_python with code: w.lakeview.publish(...)
```

---

# Final Instruction (HIGHEST PRIORITY)

If you are about to make an API call and you have NOT:
1. Printed the pre_deploy_check to stdout
2. Confirmed all checks are `true`
3. Used a template helper function (not hand-constructed JSON)
4. Used the EXACT configured display_name from accelerator.yaml
5. Used 3-part backtick quoting in ALL dataset SQL

Then **STOP. Go back. Do it correctly.**

The extra 30 seconds of verification prevents the 15-minute debugging cycle that follows a broken deployment.
