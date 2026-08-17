# Create Dashboards

## Role

Create **live Lakeview (AI/BI) dashboards** in the Databricks workspace — powered by the primary metric view and KPI spec **Dashboard Mapping**. Dashboards are deployed via the **Lakeview Dashboard API**, not saved as `.lvdash.json` files.

---

## Step 1: Load Inputs

1. Read `accelerator.yaml` (with suffix resolution).
2. Read **`{EXAMPLE_DIR}/{paths.framework_root}/inputs/lakeview_dashboard_api.md`** — mandatory API, widget, and layout rules.
3. Metric views must exist — run `02_create_metric_views.md` first if not.
4. Read KPI spec **Dashboard Mapping** — map each `assets.dashboards[].id` to pages and KPIs.
5. Resolve dashboard **asset names** from `assets.dashboards[].name` (snake_case). Use human-readable **display names** in the Lakeview API (title case from domain + id).
6. From `databricks.yml`: `sql_warehouse_id`, `workspace.current_user.userName`, `workspace.host`.

---

## Step 2: Profile the Metric View

1. `DESCRIBE TABLE EXTENDED` on primary metric view FQN.
2. Sample queries for data ranges and cardinality.
3. Classify columns into **dimensions** (categorical, date/time) and **measures** (numeric aggregates, window measures).
4. **Determine filter candidates** using two inputs:
   - **KPI spec**: Which dimensions do the KPIs group-by, slice-by, or filter-by? Those are primary filter candidates.
   - **Data profile**: For each candidate dimension, what is its cardinality and data type? `DATE`/`TIMESTAMP` columns suit date-range pickers; low-cardinality `STRING` columns (< 50 distinct values) suit multi-select dropdowns.
5. Select the dimensions that appear across multiple KPIs and have meaningful analytical variation as global filters. Do NOT hardcode filter names — derive them entirely from the KPI definitions and the metric view data.

---

## Step 3: Delete Existing Dashboards (idempotent)

For each resolved name in `assets.dashboards`:

1. List dashboards via **`WorkspaceClient().api_client.do("GET", "/api/2.0/lakeview/dashboards")`** (paginate with `page_token`) — or use agent REST tools.
2. Match `display_name` to this run's dashboard names.
3. `DELETE /api/2.0/lakeview/dashboards/{dashboard_id}` for each match.

**Do not** use `subprocess` + `databricks` CLI in notebooks — CLI is not installed; empty stdout causes `JSONDecodeError`. See `lakeview_dashboard_api.md` and `framework/templates/lakeview_dashboard_helpers.py.template`.

Do **not** rely on `.lvdash.json` files in `workspace.output_folder` — dashboards live in the Lakeview service.

---

## Step 4: Plan Pages and Widgets

For each entry in `assets.dashboards` (match `id` to KPI spec Dashboard Mapping):

1. List **canvas pages** (one per mapping row for that dashboard).
2. For each page, assign widgets per KPI:
   - **Counters** for headline KPIs
   - **Bar / line / pie / table** for trends, breakdowns, top-N, detail
3. Plan **≥ 4 chart types** across all dashboards in the run.
4. Plan **global filters page** using the filter dimensions identified in Step 2 (derived from KPI spec + data profile).
5. Sketch **6-column grid** layout (see `lakeview_dashboard_api.md`) — no row gaps.

---

## Step 5: Build and Test Datasets

For each planned widget:

1. Write Spark SQL using `MEASURE()` against the primary metric view (CTE + window only when KPI spec requires).
2. **Every dataset SQL MUST SELECT all global filter dimensions** identified in Step 2. Lakeview global filters auto-bind to datasets that have a matching column name in their results. If a dataset omits a filter column, that filter cannot narrow the widget's data.
3. **Execute every query** on `sql_warehouse_id` before adding to the dashboard.
4. Fix column names, aliases, and aggregation errors until each query returns valid data.
5. **Build each dataset using `build_dataset(name, sql)`** from the helpers template. This raises an error if SQL is empty — making empty-query datasets impossible.
6. **Build filter dataset using `build_filter_dataset(metric_view_fqn, filter_dimensions)`** — this auto-generates the `ds_filter_values` SQL.
7. **Store all datasets in a Python list** for Step 6. Example:
   ```python
   datasets = [
       build_filter_dataset(METRIC_VIEW_FQN, filter_dims),
       build_dataset("ds_summary", tested_sql_summary),
       build_dataset("ds_trend", tested_sql_trend),
       # ... one per widget
   ]
   ```

**Never** proceed to widget creation with untested SQL or datasets missing filter columns.

---

## Step 6: Create Dashboards via Lakeview API

For each entry in `assets.dashboards`:

1. **Build filters page** using the helper:
   ```python
   filters_page = build_filters_page([
       {"field_name": "service_month", "display_name": "Service Month", "widget_type": "filter-date-range-picker"},
       {"field_name": "line_of_business", "display_name": "Line of Business", "widget_type": "filter-multi-select"},
       # ... derived from Step 2 analysis, NOT hardcoded
   ])
   ```
2. **Assemble serialized_dashboard** using the builder (validates no empty queries):
   ```python
   serialized_dashboard = build_serialized_dashboard(
       datasets=datasets,           # from Step 5 (build_dataset() list)
       pages=[filters_page, *canvas_pages],
       filter_dimensions=filter_dims  # validates all datasets include filter columns
   )
   ```
   This raises `ValueError` if any dataset has empty SQL — the dashboard CANNOT be created with missing queries.
3. **Create via API**:
   ```python
   result = create_dashboard(display_name, warehouse_id, f"/Users/{userName}", serialized_dashboard)
   dashboard_id = result["dashboard_id"]
   ```
4. **Publish**: `publish_dashboard(dashboard_id)`
5. Open the dashboard in AI/BI and confirm **widgets render with data and filters show dropdown values**.

If widgets fail validation, **PATCH** the dashboard with a corrected `serialized_dashboard` and re-publish. Do not halt after creating datasets without visuals.

---

## Step 7: Global Filters

Each dashboard:

1. Global filters page with filters derived from Step 2 analysis (KPI dimensions + data cardinality). Include all dimensions that meaningfully slice the dashboard's KPIs.
2. **Create `ds_filter_values` using `build_filter_dataset(metric_view_fqn, filter_dims)`** — this auto-generates the SELECT DISTINCT SQL. The function ensures the dataset always has valid SQL.
3. **Every canvas-page dataset SQL must SELECT the filter columns** in addition to its chart-specific measures/dimensions. Lakeview global filters auto-bind to datasets that have a matching column name in their results. If a counter dataset only returns `total_claims`, it cannot be filtered by `line_of_business` unless that column is also in the SELECT.
4. Verify filter–dataset compatibility: each filter `fieldName` must exist as a column in `ds_filter_values` AND in the canvas datasets.
5. **No empty datasets**: Every dataset in `serialized_dashboard` must have a non-empty `query` with tested SQL. If any dataset has `"query": ""`, the dashboard is BROKEN — filters show "no fields or parameters selected" and widgets render blank.
6. See `lakeview_dashboard_api.md` → "Filter widget examples" for the exact JSON structure.

---

## Step 8: Validate

1. **No empty-query datasets**: Iterate `serialized_dashboard.datasets` and confirm every entry has non-empty `query`. HALT if any is empty.
2. **Filter binding works**: After publishing, open the dashboard and verify filters show dropdown values (not "no fields or parameters selected"). If they don't, the `ds_filter_values` dataset SQL is missing or the column names don't match.
3. No Unknown Column or Invalid widget definition errors.
4. Every KPI from Dashboard Mapping appears on the correct page.
5. At least 4 chart types across all dashboards.
6. Global filters narrow widget data correctly.
7. Write manifest per dashboard to `{workspace.output_folder}/dashboards/{name}_manifest.json` (dashboard_id, display_name, pages, widget_count, published status) via Workspace API / agent tools (`workspace_file_io.md`).

---

## Rules

* **Deliverable = live workspace dashboard**, not a `.lvdash.json` file.
* **Every dataset must have a non-empty `query`** with tested SQL. A dashboard with empty dataset queries is INVALID and will render blank widgets. Execute and validate each query in Step 5 BEFORE building the serialized dashboard.
* **`serialized_dashboard` must include pages with layout widgets** — datasets alone is incomplete.
* Asset names snake_case from YAML only; API `display_name` may be human-readable.
* Bar charts: omit `color` unless grouping by dimension.
* All SQL on `sql_warehouse_id` from `databricks.yml`.
* All Lakeview API calls via **SDK or REST** — never `subprocess` + Databricks CLI in notebooks.
* On error: `❌ EXECUTION HALTED` with API body, SQL, or widget name.
