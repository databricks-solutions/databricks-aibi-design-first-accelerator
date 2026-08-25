# Create Dashboards

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

Read:

```text
{EXAMPLE_DIR}/{paths.framework_root}/inputs/lakeview_dashboard_api.md
```

This file is **MANDATORY**.

### HARD GATE: lakeview_dashboard_api.md Must Be Loaded

If `lakeview_dashboard_api.md` cannot be read or does not exist:

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
1. Read lakeview_dashboard_api.md            (JSON structure authority)
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
{workspace.output_folder}/schema_profile.yaml
{workspace.output_folder}/kpi_metric_mapping.yaml
{workspace.output_folder}/metric_view_design.yaml
{workspace.output_folder}/metric_view_validation.yaml
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

# Step 2.2: Dataset SQL Column Resolution Rules (CRITICAL)

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

---

# Step 3.1: Dashboard Mapping Is Authoritative (KPI-Driven Design)

Dashboard creation is ENTIRELY driven by two sources:

```text
Source 1: KPI Spec (Dashboard Mapping section)
  → defines WHICH dashboards exist
  → defines WHICH pages each dashboard has
  → defines WHICH KPIs appear on each page
  → defines visualization types and layout intent

Source 2: Metric View DESCRIBE output (Step 2 above)
  → defines ACTUAL column names available for SQL
  → defines data types (date, string, decimal, etc.)
  → defines which columns are dimensions vs measures
```

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

# Step 3.2: Page Design

Each page should have a clear analytical purpose.

Examples of page purposes include:

```text
Executive Summary
Trend Analysis
Segment Performance
Operational Breakdown
Detailed Analysis
```

These are examples only.

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

## Visualization Diversity

Aim for useful visualization diversity across dashboards.

If the KPI set naturally supports multiple visual forms, prefer at least several meaningful visualization types.

However:

```text
ANALYTICAL APPROPRIATENESS
>
CHART TYPE COUNT
```

Do not select an inappropriate chart merely to satisfy a chart-count target.

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

Use the project's supported:

```python
build_dataset(...)
```

or equivalent helper.

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

# Step 8.1: Filter Dataset

If the current project serialization contract requires a dedicated filter-values dataset, create it using the configured helper such as:

```python
build_filter_dataset(...)
```

and validate its SQL.

Do not assume a dedicated filter dataset is required unless specified by:

```text
lakeview_dashboard_api.md
```

The project serialization contract is authoritative.

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

**3. SDK deployment method:** On serverless compute, use the Databricks SDK:

```text
from databricks.sdk.service.dashboards import Dashboard
w.lakeview.create(dashboard=Dashboard(
    display_name=...,
    warehouse_id=...,
    serialized_dashboard=json.dumps(spec)
))
```

Do NOT use `requests.post()` with `w.config.token` (returns None on serverless). Do NOT pass keyword arguments directly to `w.lakeview.create()` — it takes a single `dashboard=Dashboard(...)` parameter.

**4. Publish after create:** Always call `w.lakeview.publish(dashboard_id=..., warehouse_id=..., embed_credentials=True)` after successful creation.

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