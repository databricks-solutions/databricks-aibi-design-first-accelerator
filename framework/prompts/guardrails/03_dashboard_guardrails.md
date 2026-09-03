# Dashboard Guardrails — Step 4 (Create Dashboards)

> **Also read:** `guardrails/00_global_rules.md` (always applies)

---

## Enforcement Architecture

Dashboard deployment uses the **template notebook pattern** (`dashboard_notebook.py.template`).
The LLM's job is to produce `dashboard_design.yaml` (a structured spec). The template notebook
compiles the spec into deployed dashboards with all guardrails in the code path.

**The template enforces these rules automatically:**
- Always uses `build_filter_widget()` → queryName always present
- Always runs DESCRIBE before building datasets → column names always correct
- Always uses `build_bar_chart()`, `build_counter()`, etc. → no hand-rolled builders
- Always calls `deploy_dashboard()` → pre-deploy gates + API readback

---

## Gates

### GATE 3.1: Page Count Validation (MANDATORY)
After writing `dashboard_design.yaml`, count canvas pages per dashboard. If any dashboard has fewer canvas pages than its KPI spec mapping defines → HALT.

### GATE 3.2: Design Contract Validation
`dashboard_design.yaml` must be written and validated BEFORE any dashboard construction. No dashboard JSON may be built without this contract.

### HARD GATE: lakeview_dashboard_api.md Must Be Loaded
The agent must read the Lakeview API reference before building dashboards. This is non-negotiable.

### HARD GATE: No Dashboard Construction Without Design Contract
If `dashboard_design.yaml` does not exist → HALT. Do NOT construct dashboards from memory.

### GATE 19.1: Ground-Truth Validation Required
After all dashboards deployed, `ground_truth_validation.yaml` must be written via cross-validation sweep.

---

## Dashboard Design Spec Schema

The LLM produces `dashboard_design.yaml` with this structure:

```yaml
dashboards:
  - name: my_dashboard_v1
    metric_view: catalog.schema.my_metric_view_v1     # single MV
    # OR for multi-MV dashboards:
    metric_views:                                       # list of MVs
      - catalog.schema.claims_mv_v1
      - catalog.schema.enrollment_mv_v1
    pages:
      - title: Overview
        widgets:
          - type: counter          # counter, bar, line, or text
            measure: total_claims  # column name from DESCRIBE output
            title: Total Claims
            display_name: Claims   # optional: counter label
            agg: SUM               # optional: SUM (default) or AVG
          - type: bar
            measure: total_paid_amount
            dimension: claim_type  # x-axis for bar/line charts
            title: Paid Amount by Type
          - type: line
            measure: total_paid_amount
            dimension: service_date
            title: Paid Amount Trend
          - type: text
            content: "## Section Header"
    filter_dimensions:
      - claim_type               # simple string → auto-detects widget type
      - field_name: service_date # OR dict with explicit config
        display_name: Service Date
        widget_type: filter-date-range-picker
```

---

## Prohibited Actions

1. DO NOT use `execute_python` for dashboard creation or publishing — the subprocess has NO WorkspaceClient
2. DO NOT bypass the dashboard_design.yaml contract — build from spec, not from memory
3. DO NOT create dashboards with 0 filter pages
4. DO NOT create dashboards with 0 canvas widgets
5. DO NOT publish dashboards without API readback validation
6. DO NOT write manifests without `validation_source: api_readback`
7. DO NOT skip DESCRIBE on the metric view before building datasets
8. DO NOT use column names from spec text or agent memory — only from DESCRIBE
9. DO NOT mix filter and canvas widgets on the same page
10. DO NOT use `spec.version: 1` for filter widgets (must be 2)
11. DO NOT omit `queryName` from filter widget `encodings.fields[]`
12. DO NOT use a separate filter dataset — filters MUST share the same dataset as canvas widgets
13. DO NOT fall back to `execute_python` when SQL fails — fix the SQL
14. DO NOT skip the pre-deploy gate checks
15. DO NOT hand-write filter widget JSON inline — ALWAYS use `build_filter_widget()` from helpers
16. DO NOT define your own widget builder functions (e.g., `def bar(...)`, `def counter(...)`)
17. DO NOT skip DESCRIBE on the metric view before building datasets

---

## Anti-Patterns

### AP-DB-1: Missing queryName in Filter Widgets
**Pattern:** Filter shows "no fields or parameters selected" in Lakeview UI.
**Root cause:** Hand-written filter JSON omits `queryName: "main_query"` from `encodings.fields[]`.
**Fix:** Template `build_filter_widget()` always includes `queryName`. NEVER hand-write filter JSON.

**Working (correct):**
```json
"encodings": {"fields": [{"fieldName": "claim_type", "displayName": "Claim Type", "queryName": "main_query"}]}
```

**Broken (incorrect):**
```json
"encodings": {"fields": [{"fieldName": "claim_type", "displayName": "Claim Type"}]}
```

### AP-DB-2: bar() TypeError from Hand-Rolled Builders
**Pattern:** `TypeError: bar() missing 1 required positional argument: 'p'`
**Root cause:** Agent defined `def bar(n, d, x, y, t):` (5 params) then called with 6 params.
**Fix:** ALWAYS import `build_bar_chart` from template. NEVER define custom builder functions.

### AP-DB-3: Column Name Mismatch in Dataset SQL
**Pattern:** Dashboard dataset SQL references `clm_dtl_claim_type` but metric view alias is `claim_type`.
**Root cause:** Agent used source table column names instead of metric view aliases.
**Fix:** DESCRIBE the metric view (not source table). Template Cell 3 does this automatically.

### AP-DB-4: f-string Backslash SyntaxError
**Pattern:** `SyntaxError: f-string expression part cannot include a backslash` in gate_checks.py
**Root cause:** `f"{'\u2500' * 40}"` — backslash inside f-string `{}` on Python <3.12.
**Fix:** Extract to variable: `sep = '\u2500' * 40; f"{sep}"`. Already fixed in gate_checks.py.

### AP-DB-5: Agent Bypasses Template Helpers
**Pattern:** Agent builds entire dashboard JSON inline via `execute_python` instead of importing the template.
**Root cause:** Prompt told agent to use helpers but didn't show HOW to import them in subprocess context.
**Fix:** `dashboard_notebook.py.template` imports are in Cell 2 (VERBATIM). Agent copies template, not builds from scratch.

---

## Hard Stop Rules

Any of these invalidate the dashboard and require re-execution:

- Hand-writes filter widget JSON without using `build_filter_widget()`
- Builds dataset SQL without first running `DESCRIBE TABLE {metric_view_fqn}`
- Defines its own `bar()`, `counter()`, `line()` builder functions
- Reports `published: true` without API readback
- Creates a dashboard with 0 filter pages
- Creates a dashboard with canvas pages missing widgets
