# Lakeview Dashboard API — Agent Reference

Use this for **Step 03 (Create Dashboards)**. Deliverables are **live AI/BI dashboards in the workspace**, not `.lvdash.json` files on disk.

---

## Mandatory workflow

```
1. Profile metric view (DESCRIBE + sample queries)
2. Write dataset SQL for every widget (MEASURE() against metric view)
3. TEST every dataset SQL on sql_warehouse_id — fix failures before building widgets
4. Build serialized_dashboard JSON with datasets AND pages/layout/widgets (never datasets-only)
5. POST /api/2.0/lakeview/dashboards → capture dashboard_id
6. POST .../published → publish draft
7. Verify widgets render (no "Invalid widget definition", no "Unknown Column")
8. Write manifest JSON to workspace.output_folder/dashboards/ (IDs + URLs only)
```

**Root cause of empty dashboards:** `serialized_dashboard` contained `datasets` but no `pages` with `layout` widgets. Every dashboard MUST include at least one `PAGE_TYPE_GLOBAL_FILTERS` page and one or more `PAGE_TYPE_CANVAS` pages with positioned widgets.

---

## Do not use (common failure)

| Approach | Why it fails |
|----------|----------------|
| `subprocess.run(["databricks", "api", ...])` in a notebook | **Databricks CLI is not installed** in notebook/serverless runtimes → empty stdout → `JSONDecodeError` |
| `databricks api get ...` shell from `%sh` | Same — CLI unavailable; auth not configured in compute |

Use **Genie agent REST tools**, **`WorkspaceClient().api_client.do(...)`**, or **`requests` + notebook token** (see below).

---

## API calls

Read `warehouse_id` and workspace user from `databricks.yml` (`variables.sql_warehouse_id`, `workspace.current_user.userName`).

**Parent path** for new dashboards:

`/Users/{workspace.current_user.userName}`

### Python in notebooks (preferred for generated cells)

Use the SDK — preinstalled on Databricks runtimes. Reference template: `framework/templates/lakeview_dashboard_helpers.py.template`.

```python
from databricks.sdk import WorkspaceClient
import json

w = WorkspaceClient()

def lakeview_get(path, query=None):
    return w.api_client.do("GET", path, query=query or {})

def list_all_dashboards():
    dashboards, page_token = [], None
    while True:
        q = {"page_size": 100}
        if page_token:
            q["page_token"] = page_token
        data = lakeview_get("/api/2.0/lakeview/dashboards", q)
        dashboards.extend(data.get("dashboards", []))
        page_token = data.get("next_page_token")
        if not page_token:
            break
    return dashboards

def delete_dashboard(dashboard_id):
    w.api_client.do("DELETE", f"/api/2.0/lakeview/dashboards/{dashboard_id}")

# Match by display_name (case-insensitive substring)
needles = {"member claims kpis", "member claims utilization"}
for d in list_all_dashboards():
    name = (d.get("display_name") or "").lower()
    if any(n in name for n in needles):
        delete_dashboard(d["dashboard_id"])
        print(f"DELETED {d['display_name']}")
```

**Create / publish:**

```python
body = {
    "display_name": "Member Claims KPIs Dashboard",
    "warehouse_id": "<sql_warehouse_id>",
    "parent_path": "/Users/<user>",
    "serialized_dashboard": json.dumps({"datasets": [...], "pages": [...], "uiSettings": {...}}),
}
created = w.api_client.do("POST", "/api/2.0/lakeview/dashboards", body=body)
dashboard_id = created["dashboard_id"]
w.api_client.do("POST", f"/api/2.0/lakeview/dashboards/{dashboard_id}/published")
```

### Alternative: requests + notebook token

If SDK is unavailable, mirror `genie_space_notebook.py.template`:

```python
import requests

def get_workspace_url():
    return spark.conf.get("spark.databricks.workspaceUrl")

def get_api_headers():
    token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

host = f"https://{get_workspace_url()}"
resp = requests.get(f"{host}/api/2.0/lakeview/dashboards", headers=get_api_headers(), params={"page_size": 100})
resp.raise_for_status()
data = resp.json()
```

Always call `resp.raise_for_status()` and check `resp.text` before `json.loads` — never parse empty stdout.

### CLI (local machine / Genie with shell + auth only)

Use only when running **outside** Databricks notebooks (e.g. your laptop after `databricks auth login`):

```bash
databricks api get /api/2.0/lakeview/dashboards
databricks api post /api/2.0/lakeview/dashboards --json '{ ... }'
databricks api post /api/2.0/lakeview/dashboards/{dashboard_id}/published
```

---

## serialized_dashboard structure

`serialized_dashboard` is a **stringified** JSON object passed to create/patch:

```json
{
  "datasets": [ ... ],
  "pages": [ ... ],
  "uiSettings": { "theme": { "widgetHeaderAlignment": "ALIGNMENT_UNSPECIFIED" }, "applyModeEnabled": false }
}
```

### Datasets

- One dataset per logical query (not one mega-dataset with multiple statements).
- **Exactly one SQL statement** per dataset — no `;`-separated queries.
- Fully qualified metric view: `{catalog.target.catalog}.{catalog.target.schema}.{primary_metric_view_name}`.
- Prefer `MEASURE()` in SELECT; use CTE + window functions only when KPI spec requires it.
- `queryLines` elements concatenate **with no separator** — end each line with a space or use a single-line query.

**NOTE:** Column names in examples are illustrative. Always use actual dimension names from `DESCRIBE <metric_view>`. If the metric view has `service_date` (not `service_month`), use DATE_TRUNC:

```json
{
  "name": "a1b2c3d4",
  "displayName": "Monthly Cost Trend",
  "queryLines": [
    "SELECT DATE_TRUNC('MONTH', service_date) AS service_month, MEASURE(total_paid) AS total_paid FROM catalog.schema.metric_view GROUP BY DATE_TRUNC('MONTH', service_date) "
  ]
}
```

### Pages (required)

Every dashboard needs:

1. **Global filters page** — `"pageType": "PAGE_TYPE_GLOBAL_FILTERS"` with filter widgets derived from KPI dimensions and data profile (see Step 2 of `03_create_dashboards.md`).
2. **Canvas pages** — one per KPI spec Dashboard Mapping page, `"pageType": "PAGE_TYPE_CANVAS"`.

```json
{
  "name": "filters_page",
  "displayName": "Filters",
  "pageType": "PAGE_TYPE_GLOBAL_FILTERS",
  "layout": [ /* filter widgets */ ]
},
{
  "name": "financial_overview",
  "displayName": "Financial Overview",
  "pageType": "PAGE_TYPE_CANVAS",
  "layout": [ /* counters, charts, tables */ ]
}
```

### Layout (6-column grid)

Each row must sum to **width = 6**. No gaps.

| Widget | width | height |
|--------|-------|--------|
| Title text | 6 | 1 |
| Counter/KPI | 2 | 3–4 |
| Bar/line/pie | 3 | 5–6 |
| Full-width chart/table | 6 | 5–8 |

**Text widgets:** use separate widgets for title and subtitle; `multilineTextboxSpec` only — **no `spec` block**.

---

## Widget rules (common failures)

| Rule | Detail |
|------|--------|
| Field name match | `query.fields[].name` must **exactly** equal `spec.encodings.*.fieldName` (e.g. both `"sum(total_paid)"`) |
| Counter version | `spec.version: 2`, `widgetType: "counter"` |
| Chart version | bar/line/pie/area/scatter: `spec.version: 3` |
| Table version | `spec.version: 2` |
| Filter types | `filter-multi-select`, `filter-single-select`, `filter-date-range-picker` — never `widgetType: "filter"` |
| Filter version | `spec.version: 2` for ALL filter types (NOT 1 — version 1 causes broken binding) |
| Filter encodings | `encodings.fields[]` MUST include `queryName` referencing `queries[].name` (e.g., `"queryName": "main_query"`) |
| Filter queries | `disaggregated: true`, simple field expression — **no** `associative_filter_predicate_group` |
| **Canvas widget `disaggregated`** | **MUST be `false`** with SUM/AVG expressions — see Critical Filter Binding Rule below |
| Bar color | Omit `color` encoding unless grouping by a dimension |
| Query name | Always `"main_query"` on chart/table widgets |
| Widget `name` | alphanumeric, hyphens, underscores only |

### Counter example

```json
{
  "widget": {
    "name": "kpi-total-paid",
    "queries": [{
      "name": "main_query",
      "query": {
        "datasetName": "ds_summary",
        "fields": [{"name": "sum(total_paid)", "expression": "SUM(`total_paid`)"}],
        "disaggregated": false
      }
    }],
    "spec": {
      "version": 2,
      "widgetType": "counter",
      "encodings": {
        "value": {"fieldName": "sum(total_paid)", "displayName": "Total Paid"}
      },
      "frame": {"showTitle": true, "title": "Total Paid"}
    }
  },
  "position": {"x": 0, "y": 2, "width": 2, "height": 3}
}
```

### Bar chart example

```json
{
  "widget": {
    "name": "cost-by-lob",
    "queries": [{
      "name": "main_query",
      "query": {
        "datasetName": "ds_lob",
        "fields": [
          {"name": "line_of_business", "expression": "`line_of_business`"},
          {"name": "sum(total_paid)", "expression": "SUM(`total_paid`)"}
        ],
        "disaggregated": false
      }
    }],
    "spec": {
      "version": 3,
      "widgetType": "bar",
      "encodings": {
        "x": {"fieldName": "line_of_business", "scale": {"type": "categorical"}, "displayName": "LOB"},
        "y": {"fieldName": "sum(total_paid)", "scale": {"type": "quantitative"}, "displayName": "Total Paid"}
      },
      "frame": {"showTitle": true, "title": "Cost by Line of Business"}
    }
  },
  "position": {"x": 0, "y": 6, "width": 3, "height": 5}
}
```

### Filter widget examples (CRITICAL)

Filter widgets are special — they live on the `PAGE_TYPE_GLOBAL_FILTERS` page and **auto-bind** to canvas-page datasets that have a matching column name. For filters to work:

1. **A dedicated filter dataset must exist with actual SQL** — e.g. `ds_filter_values` that SELECTs DISTINCT filter dimensions from the metric view.
2. **Every canvas-page dataset must also SELECT the filter columns** in its SQL query. Filters cannot narrow widgets whose datasets don't include the filter column.
3. **The dataset `query` field must be NON-EMPTY** — a dataset with `"query": ""` will cause "Filter has no fields or parameters selected".

#### Shared Dataset Pattern (REQUIRED for filters to work):

**CRITICAL: Filter widgets and canvas widgets MUST reference the SAME dataset.** Do NOT create a separate `ds_filter_values` dataset for filters. When filters reference a different dataset than canvas widgets, Lakeview does NOT auto-bind across datasets via the API — filters will appear to work (values populate, pills show) but canvas widget values will NOT change.

**Correct pattern:** One dataset per canvas page that includes BOTH filter dimensions and measures:

```json
{
  "name": "ds_kpi_headline",
  "displayName": "Headline KPIs",
  "queryLines": [
    "SELECT service_date, line_of_business, claim_type, member_state, MEASURE(total_paid) AS total_paid, MEASURE(total_claims) AS total_claims, MEASURE(denial_rate) AS denial_rate FROM catalog.schema.metric_view GROUP BY service_date, line_of_business, claim_type, member_state"
  ]
}
```

Then BOTH filter widgets AND counter/chart widgets reference this same `ds_kpi_headline`:
- Filter widget: `datasetName: "ds_kpi_headline"`, `disaggregated: true`
- Counter widget: `datasetName: "ds_kpi_headline"`, `disaggregated: false`, `SUM(\`total_paid\`)`

This way, when the filter selects a value, it narrows the shared dataset rows, and the counter re-aggregates only the remaining rows.

**CRITICAL:** Filter dimensions MUST use actual metric view dimension names (from DESCRIBE). Do NOT use derived aliases like `service_month` unless the metric view actually has that column. Use DATE_TRUNC only in canvas datasets where monthly aggregation is needed — not in the filter fields.

#### Multi-select filter widget:

```json
{
  "widget": {
    "name": "filter-line-of-business",
    "queries": [{
      "name": "main_query",
      "query": {
        "datasetName": "ds_filter_values",
        "fields": [{"name": "line_of_business", "expression": "`line_of_business`"}],
        "disaggregated": true
      }
    }],
    "spec": {
      "version": 2,
      "widgetType": "filter-multi-select",
      "encodings": {
        "fields": [{
          "fieldName": "line_of_business",
          "displayName": "Line of Business",
          "queryName": "main_query"
        }]
      },
      "frame": {"showTitle": true, "title": "Line of Business"}
    }
  },
  "position": {"x": 0, "y": 0, "width": 2, "height": 2}
}
```

#### Date range filter widget:

**NOTE:** Use the actual temporal dimension name from DESCRIBE (e.g., `service_date`, not a derived alias like `service_month`).

```json
{
  "widget": {
    "name": "filter-service-date",
    "queries": [{
      "name": "main_query",
      "query": {
        "datasetName": "ds_filter_values",
        "fields": [{"name": "service_date", "expression": "`service_date`"}],
        "disaggregated": true
      }
    }],
    "spec": {
      "version": 2,
      "widgetType": "filter-date-range-picker",
      "encodings": {
        "fields": [{
          "fieldName": "service_date",
          "displayName": "Service Date",
          "queryName": "main_query"
        }]
      },
      "frame": {"showTitle": true, "title": "Service Date"}
    }
  },
  "position": {"x": 2, "y": 0, "width": 2, "height": 2}
}
```

**Key rules for filter binding (common failures):**
- **`spec.version` must be `2`** for all filter widget types (NOT 1 — version 1 causes "no fields or parameters selected")
- **`encodings.fields[]` must include `queryName`** — this references the `queries[].name` value (e.g., `"main_query"`). Without it, the filter cannot resolve its field.
- **Datasets must use `queryLines` (array)** not `query` (string), and must include `displayName`
- `queries[].query.datasetName` must reference a dataset with **non-empty SQL**
- `queries[].query.disaggregated` must be `true` for filters
- `encodings.fields[].fieldName` must match the column name in the dataset SQL results
- The same column name must appear in canvas-page datasets for cross-filtering to work
- If a filter shows "no fields or parameters selected": check `spec.version` is 2, check `queryName` is present, check dataset has SQL

### Critical Filter Binding Rule (Correct Widget Aggregation Pattern)

**Canvas-page widgets (counters, charts, tables) MUST use `disaggregated: false` with explicit aggregation expressions (`SUM`/`AVG`).**

The filter mechanism works as follows:
1. Dataset SQL uses `MEASURE()` against the metric view, grouped by filter dimensions
2. The dataset returns multiple rows (one per dimension combination)
3. When a filter is applied, Lakeview narrows the rows client-side to matching values
4. The widget re-aggregates (`SUM`/`AVG`) the remaining rows → values change

**Additive measures** (total_paid, total_claims, total_claim_lines, distinct_members): use `SUM`
**Rate/ratio measures** (denial_rate, clean_claim_rate, par_provider_rate, avg_paid_per_line): use `AVG`

```text
✓ CORRECT — counter for additive measure:
  "disaggregated": false
  "fields": [{"name": "sum(total_paid)", "expression": "SUM(`total_paid`)"}]

✓ CORRECT — counter for rate measure:
  "disaggregated": false
  "fields": [{"name": "avg(denial_rate)", "expression": "AVG(`denial_rate`)"}]

✓ CORRECT — bar chart:
  "disaggregated": false
  "fields": [
    {"name": "line_of_business", "expression": "`line_of_business`"},
    {"name": "sum(total_paid)", "expression": "SUM(`total_paid`)"}
  ]

✗ BROKEN — disaggregated: true on counters shows individual row values (e.g. "1" instead of "500"):
  "disaggregated": true
  "fields": [{"name": "total_claims", "expression": "`total_claims`"}]
```

**Rule:** Always use `disaggregated: false` + SUM/AVG for canvas widgets. Use `disaggregated: true` ONLY for filter widgets.

| Widget type | disaggregated | Field expression | Why |
|-------------|---------------|------------------|-----|
| Filter | `true` | `` `column` `` | Shows distinct values for selection |
| Counter (additive) | `false` | `SUM(\`col\`)` | Aggregates all filtered rows into total |
| Counter (rate) | `false` | `AVG(\`col\`)` | Averages rate across filtered rows |
| Bar/Line chart | `false` | x=`` `dim` ``, y=`SUM(\`col\`)` | Groups by x, aggregates y across filtered rows |

---

## Visualization mix

Across all dashboards for the domain, use **at least 4 chart types** (counter, bar, line, pie, table, etc.). Map KPI spec **Dashboard Mapping** to pages and widget types — every listed KPI must appear on the correct page.

---

## Output manifest (optional traceability)

After create + publish, write `{workspace.output_folder}/dashboards/{name}_manifest.json`:

```json
{
  "name": "member_claims_kpis_dashboard",
  "display_name": "Member Claims KPIs Dashboard",
  "dashboard_id": "...",
  "warehouse_id": "...",
  "parent_path": "/Users/...",
  "pages": ["Filters", "Financial Overview", "..."],
  "widget_count": 12,
  "published": true
}
```

Do **not** treat `.lvdash.json` export as the deliverable.

---

## Validation checklist

Before marking Step 03 complete:

- [ ] **Every dataset has non-empty `query` SQL** — no dataset may have `"query": ""`. Execute each query on the warehouse first.
- [ ] **Filter dataset (`ds_filter_values`) has SQL** that SELECTs all filter dimension columns from the metric view
- [ ] **Every canvas-page dataset includes filter columns** in its SQL SELECT so global filters can bind
- [ ] `pages` array is non-empty with filters + canvas pages
- [ ] Every KPI from Dashboard Mapping has at least one widget
- [ ] Dashboard opens in AI/BI with rendered visuals (not empty canvas)
- [ ] Global filters show values (not "no fields or parameters selected")
- [ ] No Unknown Column / Invalid widget definition errors

On failure: halt with `❌ EXECUTION HALTED`, API response body, and failing SQL or widget name.
