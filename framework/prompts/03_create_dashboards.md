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
3. Classify dimensions and measures (including window measures).
4. Pick filter dimensions (date, LOB, one high-value slice) — max ~8 values for chart color/grouping.

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
4. Plan **global filters page**: date range, primary slice dimension, one additional dimension from profiling.
5. Sketch **6-column grid** layout (see `lakeview_dashboard_api.md`) — no row gaps.

---

## Step 5: Build and Test Datasets

For each planned widget:

1. Write Spark SQL using `MEASURE()` against the primary metric view (CTE + window only when KPI spec requires).
2. **Execute every query** on `sql_warehouse_id` before adding to the dashboard.
3. Fix column names, aliases, and aggregation errors until each query returns valid data.
4. Record dataset id → SQL mapping for the serialized dashboard.

**Never** proceed to widget creation with untested SQL.

---

## Step 6: Create Dashboards via Lakeview API

For each entry in `assets.dashboards`:

1. Build `serialized_dashboard` object with **all three** top-level keys:
   - `datasets` — tested SQL per dataset
   - `pages` — **must include** `PAGE_TYPE_GLOBAL_FILTERS` + `PAGE_TYPE_CANVAS` pages with **layout** widgets (not empty)
   - `uiSettings` — consistent theme
2. Follow widget specs in `lakeview_dashboard_api.md`:
   - Matching `fieldName` / query `name`
   - Correct `spec.version` per widget type
   - Filters use valid `filter-*` widget types
3. `POST /api/2.0/lakeview/dashboards` with:
   - `display_name`, `warehouse_id`, `parent_path: /Users/{userName}`
   - `serialized_dashboard` as **JSON string**
4. Capture `dashboard_id` from response.
5. `POST /api/2.0/lakeview/dashboards/{dashboard_id}/published`
6. Open the dashboard in AI/BI and confirm **widgets render with data** — not datasets-only drafts.

If widgets fail validation, **PATCH** the dashboard with a corrected `serialized_dashboard` and re-publish. Do not halt after creating datasets without visuals.

---

## Step 7: Global Filters

Each dashboard:

1. Global filters page with minimum 3 filters (date range, primary slice, one additional).
2. Every canvas-page dataset must include filter columns so global filters apply.
3. Verify filter–dataset compatibility — never bind to a missing column.

---

## Step 8: Validate

1. No Unknown Column or Invalid widget definition errors.
2. Every KPI from Dashboard Mapping appears on the correct page.
3. At least 4 chart types across all dashboards.
4. Global filters narrow widget data correctly.
5. Write manifest per dashboard to `{workspace.output_folder}/dashboards/{name}_manifest.json` (dashboard_id, display_name, pages, widget_count, published status) via Workspace API / agent tools (`workspace_file_io.md`).

---

## Rules

* **Deliverable = live workspace dashboard**, not a `.lvdash.json` file.
* **`serialized_dashboard` must include pages with layout widgets** — datasets alone is incomplete.
* Asset names snake_case from YAML only; API `display_name` may be human-readable.
* Bar charts: omit `color` unless grouping by dimension.
* All SQL on `sql_warehouse_id` from `databricks.yml`.
* All Lakeview API calls via **SDK or REST** — never `subprocess` + Databricks CLI in notebooks.
* On error: `❌ EXECUTION HALTED` with API body, SQL, or widget name.
