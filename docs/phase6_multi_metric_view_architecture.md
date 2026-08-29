# Phase 6: Multi Metric View Architecture

## Problem Statement

The current framework creates a **single metric view** sourced from one fact table with no joins. This conservative approach prevents fanout risk but limits KPI coverage — in the Member Claims domain, 10 of 23 KPIs were skipped because they require:

1. **Different grain** — enrollment/member-month KPIs (M-1, M-2, M-3, MC-1, MC-2, W-1) need `fact_member_enrollment` as the source, not `fact_claim_detail`
2. **Fact-to-fact enrichment** — MC-3 (Utilization Rate) needs `fact_claim_detail` joined to `fact_claim_header` for header-level attributes
3. **Unsupported SQL semantics** — MC-4 (HAVING), W-2 (LAG) cannot be expressed as metric view measures regardless of source

## Design: Multi Metric View with Optional Intermediate Views

### Core Principle

The Metric View step should **analyze KPIs holistically** before creating any metric view, then determine:

1. How many metric views are needed (grouped by grain/source)
2. Whether any metric view requires an intermediate pre-joined view as its source
3. Which KPIs are genuinely unsupported (HAVING, LAG, window functions) and should be classified as NOT_IMPLEMENTED with documented reference SQL

### Decision Flow (LLM executes this during Metric View step)

```text
┌─────────────────────────────────────────────────────────┐
│  INPUT: Schema Profile + KPI Spec + Semantic Model       │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 1: Group KPIs by Required Source Grain             │
│                                                          │
│  For each KPI, determine:                                │
│    - Which fact table(s) are needed?                     │
│    - What grain does the KPI operate at?                 │
│    - Does it need columns from dimension tables?         │
│                                                          │
│  Output: KPI groups by source grain                      │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 2: Determine Metric View Count                     │
│                                                          │
│  Rule: One metric view per distinct source grain.        │
│                                                          │
│  Examples:                                               │
│    - Claim-line grain → metric_view_claims               │
│    - Member-month grain → metric_view_enrollment         │
│    - Enriched claim grain → metric_view_claims_enriched  │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 3: For Each Metric View — Determine Source         │
│                                                          │
│  Case A: Single fact table has all needed columns        │
│    → Source directly from fact table (no intermediate)   │
│    → Example: fact_member_enrollment has LOB, member_sk  │
│                                                          │
│  Case B: Fact table needs dimension attributes           │
│    → Source directly from fact table if dimensions are   │
│      denormalized in the fact (common in star schemas)   │
│    → If NOT denormalized: create intermediate view       │
│      that joins fact + dimension(s) at safe grain        │
│                                                          │
│  Case C: Two fact tables at different grains             │
│    → Create intermediate view joining them               │
│    → ONLY if join is N:1 (no fanout)                     │
│    → Example: fact_claim_detail JOIN fact_claim_header    │
│      ON claim_id (many lines per one header = N:1)       │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│  STEP 4: Classify Remaining KPIs                         │
│                                                          │
│  Any KPI requiring:                                      │
│    - HAVING clause (threshold-based filtering)           │
│    - Window functions (LAG, LEAD, rolling)               │
│    - Subqueries in measure definition                    │
│  → Classify as NOT_IMPLEMENTED                           │
│  → Document the reference SQL query in plan YAML         │
│  → Include in readme.md for manual implementation later  │
└───────────────────────────────────────────────────────────┘
```

---

## Architecture Patterns

### Pattern A: Direct Metric View (No Intermediate View)

Used when a single fact table contains all columns needed for the KPI group.

```text
fact_member_enrollment_v1 ──→ member_enrollment_metric_view_v1
                                 ├─ M-1: COUNT(DISTINCT member_sk) FILTER(...)
                                 ├─ M-2: COUNT(DISTINCT member_sk) by LOB
                                 ├─ M-3: COUNT(DISTINCT member_sk) by geography
                                 ├─ MC-1: SUM(paid) / NULLIF(member_months, 0)
                                 ├─ MC-2: claims_count * 1000 / member_months
                                 └─ W-1: Rolling 3-month PMPM
```

**When to use:**
- The fact table already contains the dimension attributes needed (LOB, geography, dates)
- OR the KPIs only need columns from the source fact (no dimension lookups)

**When to use for enrollment specifically:**
- `fact_member_enrollment` typically has `member_sk`, `enrollment_lob`, `enrollment_effective_date`, `enrollment_term_date`
- `dim_member` has geography (state, zip) — if these are needed, check if they're denormalized in enrollment
- If geography is NOT in enrollment → need Pattern B

---

### Pattern B: Intermediate View + Metric View

Used when the metric view needs columns from multiple tables that aren't co-located.

```text
fact_claim_detail_v1 ─────┐
                          ├─ claim_detail_enriched_v1 ──→ claims_enriched_metric_view_v1
fact_claim_header_v1 ─────┘       (intermediate view)        ├─ MC-3: Utilization Rate
                                                             ├─ Facility-type breakdowns
                                                             └─ Admission-type analysis
```

**Intermediate view rules:**
1. Join MUST be N:1 from the grain table to the lookup table (no fanout)
2. Validate with: `SELECT COUNT(*) FROM detail d JOIN header h ON ... ` = same as `SELECT COUNT(*) FROM detail`
3. Name convention: `{grain_table}_enriched_v{N}`
4. Created as a regular SQL VIEW (not a table) — no data duplication
5. The metric view sources from this view

**Join safety validation (MANDATORY before creating intermediate view):**
```sql
-- Verify no fanout: row count must be identical
SELECT 
  (SELECT COUNT(*) FROM fact_claim_detail_v1) AS detail_rows,
  (SELECT COUNT(*) FROM fact_claim_detail_v1 d 
   JOIN fact_claim_header_v1 h ON d.clm_dtl_claim_id = h.clm_claim_id) AS joined_rows
-- detail_rows MUST equal joined_rows
```

---

### Pattern C: Not Implemented — Documentation Only

Used for KPIs that cannot be expressed as metric view measures.

```text
KPIs like MC-4 (High-Cost Member Count), W-2 (MoM Growth)
  → NOT implemented in any metric view or dashboard
  → Documented in metric_view_plan.yaml with full SQL query
  → Documented in final readme.md as NOT_IMPLEMENTED
  → SQL provided for manual implementation if needed later
```

**Criteria for NOT_IMPLEMENTED classification:**
- Requires `HAVING` clause (e.g., members with total > threshold)
- Requires window functions (`LAG`, `LEAD`, `ROW_NUMBER`)
- Requires subqueries in the measure definition
- Requires conditional aggregation that metric view syntax cannot express

**MANDATORY: Document the SQL query even though it's not implemented.**

The Metric View step must still produce a reference SQL query for these KPIs so they can be manually implemented later. The query is:
1. Written and validated (executed against the warehouse to confirm it returns correct results)
2. Stored in `metric_view_plan.yaml` under the `not_implemented` section
3. Documented in the final `readme.md` with the full SQL and reason for non-implementation

These KPIs are **not included in dashboards or Genie spaces** — they are documentation-only artifacts for future manual work.

---

## Impact on Pipeline Steps

### Step 2: Create Metric Views (Updated Flow)

```text
1. Load schema profile + KPI spec + semantic model
2. ── NEW ── Analyze KPI grouping:
   a. Group KPIs by required source grain
   b. Determine number of metric views needed
   c. For each group, decide: direct source vs intermediate view
   d. Classify unsupported KPIs as NOT_IMPLEMENTED (with reference SQL)
   e. Write `metric_view_plan.yaml` (new artifact)
3. For each planned intermediate view:
   a. Design the JOIN SQL
   b. Validate join safety (no fanout)
   c. CREATE VIEW in Unity Catalog
4. For each planned metric view:
   a. Design measures and dimensions
   b. CREATE METRIC VIEW sourced from fact/intermediate view
   c. Validate each KPI (baseline reconciliation)
5. Write updated validation YAML with all groups
```

### New Artifact: `metric_view_plan.yaml`

```yaml
metric_view_plan:
  total_kpis: 23
  implementable_in_metric_views: 21
  not_implemented: 2

  metric_views:
    - name: member_claims_metric_view_v1
      source: fact_claim_detail_v1
      intermediate_view: null
      grain: "one claim service/detail line per claim id and line number"
      kpis: [C-1, C-2, C-3, C-4, ADD-1, ADD-2, ADD-3, ADD-4, ADD-5, ADD-6, ADD-7, ADD-8, ADD-9]

    - name: member_enrollment_metric_view_v1
      source: fact_member_enrollment_v1
      intermediate_view: null
      grain: "one enrollment record per member per coverage period"
      kpis: [M-1, M-2, M-3, MC-1, MC-2, W-1]

    - name: claims_enriched_metric_view_v1
      source: claim_detail_enriched_v1
      intermediate_view:
        name: claim_detail_enriched_v1
        join_sql: |
          SELECT d.*, h.clm_admission_type, h.clm_facility_type
          FROM fact_claim_detail_v1 d
          JOIN fact_claim_header_v1 h ON d.clm_dtl_claim_id = h.clm_claim_id
        join_type: "N:1 (detail to header)"
        fanout_validated: true
      grain: "one claim line enriched with header attributes"
      kpis: [MC-3, ADD-10]

  not_implemented:
    - kpi: MC-4
      name: "High-Cost Member Count"
      reason: "Requires HAVING clause (threshold-based member filtering)"
      status: NOT_IMPLEMENTED
      documentation_only: true
      sql: |
        SELECT
          DATE_TRUNC('MONTH', e.enrollment_effective_date) AS service_month,
          COUNT(DISTINCT e.member_sk) AS high_cost_member_count
        FROM {catalog}.{schema}.fact_member_enrollment_v1 e
        JOIN (
          SELECT clm_dtl_member_nbr_sk, SUM(clm_dtl_paid_amt) AS total_paid
          FROM {catalog}.{schema}.fact_claim_detail_v1
          GROUP BY clm_dtl_member_nbr_sk
          HAVING SUM(clm_dtl_paid_amt) > 50000
        ) hc ON e.member_sk = hc.clm_dtl_member_nbr_sk
        GROUP BY DATE_TRUNC('MONTH', e.enrollment_effective_date)
      validated: true
      validation_row_count: 12
      manual_implementation_notes: |
        To implement: Add as a named SQL dataset in the dashboard.
        Cannot be a metric view measure due to HAVING clause.

    - kpi: W-2
      name: "MoM Active Member Growth"
      reason: "Requires LAG window function (month-over-month comparison)"
      status: NOT_IMPLEMENTED
      documentation_only: true
      sql: |
        WITH monthly_members AS (
          SELECT
            DATE_TRUNC('MONTH', enrollment_effective_date) AS enrollment_month,
            COUNT(DISTINCT member_sk) AS active_members
          FROM {catalog}.{schema}.fact_member_enrollment_v1
          GROUP BY DATE_TRUNC('MONTH', enrollment_effective_date)
        )
        SELECT
          enrollment_month,
          active_members,
          LAG(active_members) OVER (ORDER BY enrollment_month) AS prev_month_members,
          ROUND(
            (active_members - LAG(active_members) OVER (ORDER BY enrollment_month))
            / NULLIF(LAG(active_members) OVER (ORDER BY enrollment_month), 0) * 100,
            2
          ) AS mom_growth_pct
        FROM monthly_members
        ORDER BY enrollment_month
      validated: true
      validation_row_count: 24
      manual_implementation_notes: |
        To implement: Add as a named SQL dataset in the dashboard.
        Cannot be a metric view measure due to LAG window function.
```

### Impact on Step 3: Create Dashboards

- Dashboard datasets can reference ANY of the created metric views using `MEASURE()` syntax
- `NOT_IMPLEMENTED` KPIs are **excluded from dashboards** entirely
- Filter dimensions shared across metric views should use consistent naming

### Impact on Step 4: Create Genie Space

- Genie space tables list includes ALL metric views (not just primary)
- Sample questions span all metric view domains
- Instructions document which metric view to query for which KPI category
- `NOT_IMPLEMENTED` KPIs are **excluded from Genie space** sample questions and instructions

### Impact on Step 6: Generate Documentation (readme.md)

- The final readme MUST include a **"Not Implemented KPIs"** section
- For each NOT_IMPLEMENTED KPI, document:
  - KPI ID and name
  - Reason it cannot be expressed as a metric view measure
  - Full reference SQL query (copy from `metric_view_plan.yaml`)
  - Manual implementation notes (where to add it if needed later)
- This provides a clear handoff for anyone who wants to implement these manually

**Example readme section:**

```markdown
## Not Implemented KPIs

The following KPIs could not be implemented as metric view measures due to SQL
semantics that Databricks Metric Views do not support. The validated SQL queries
are provided below for manual implementation if needed.

### MC-4: High-Cost Member Count

**Reason:** Requires HAVING clause (threshold-based member filtering)

**Status:** NOT_IMPLEMENTED — documentation only

```sql
SELECT
  DATE_TRUNC('MONTH', e.enrollment_effective_date) AS service_month,
  COUNT(DISTINCT e.member_sk) AS high_cost_member_count
FROM catalog.schema.fact_member_enrollment_v1 e
JOIN (
  SELECT clm_dtl_member_nbr_sk, SUM(clm_dtl_paid_amt) AS total_paid
  FROM catalog.schema.fact_claim_detail_v1
  GROUP BY clm_dtl_member_nbr_sk
  HAVING SUM(clm_dtl_paid_amt) > 50000
) hc ON e.member_sk = hc.clm_dtl_member_nbr_sk
GROUP BY DATE_TRUNC('MONTH', e.enrollment_effective_date)
```

**To implement manually:** Add as a named SQL dataset in a Lakeview dashboard
or as a standalone SQL query.
```

---

## Naming Conventions

| Asset | Pattern | Example |
|-------|---------|--------|
| Primary metric view | `{domain}_metric_view_v{N}` | `member_claims_metric_view_v1` |
| Secondary metric view | `{domain}_{grain_hint}_metric_view_v{N}` | `member_claims_enrollment_metric_view_v1` |
| Intermediate view | `{source_table}_enriched_v{N}` | `claim_detail_enriched_v1` |
| Plan artifact | `metric_view_plan.yaml` | — |

---

## Validation Updates

### `metric_view_validation.yaml` Changes

The validation file should now contain sections for each metric view:

```yaml
status: PASS
metric_views:
  - name: member_claims_metric_view_v1
    source: fact_claim_detail_v1
    validation_status: PASS
    kpi_count: 13
  - name: member_enrollment_metric_view_v1
    source: fact_member_enrollment_v1
    validation_status: PASS
    kpi_count: 6
  - name: claims_enriched_metric_view_v1
    source: claim_detail_enriched_v1
    validation_status: PASS
    kpi_count: 2

intermediate_views:
  - name: claim_detail_enriched_v1
    fanout_check: PASS
    source_rows: 5000
    joined_rows: 5000

kpis:
  - {kpi: C-1, metric_view: member_claims_metric_view_v1, status: IMPLEMENTED_AND_VALIDATED}
  ...
  - {kpi: M-1, metric_view: member_enrollment_metric_view_v1, status: IMPLEMENTED_AND_VALIDATED}
  ...
  - {kpi: MC-3, metric_view: claims_enriched_metric_view_v1, status: IMPLEMENTED_AND_VALIDATED}
  - kpi: MC-4
    metric_view: null
    status: NOT_IMPLEMENTED
    reason: "Requires HAVING clause (threshold-based member filtering)"
    sql_ref: "See metric_view_plan.yaml → not_implemented[0].sql"
    documentation_only: true
  - kpi: W-2
    metric_view: null
    status: NOT_IMPLEMENTED
    reason: "Requires LAG window function (month-over-month comparison)"
    sql_ref: "See metric_view_plan.yaml → not_implemented[1].sql"
    documentation_only: true
```

---

## Guard Rails

1. **Max metric views per domain**: 4 (prevents over-fragmentation)
2. **Intermediate view fanout validation is MANDATORY** — never create an intermediate view without proving row count is preserved
3. **Each metric view must have ≥ 2 KPIs** — don't create a metric view for a single KPI (use dashboard SQL instead)
4. **Prefer direct source over intermediate view** — only create intermediate views when columns are genuinely missing from the grain table
5. **NOT_IMPLEMENTED classification requires explicit reason + reference SQL** — the LLM must document why metric view syntax is insufficient and provide a validated query for manual implementation

---

## Migration Path

This is a non-breaking change:
- Existing single-metric-view runs continue to work (they produce 1 metric view)
- The new planning step (`metric_view_plan.yaml`) is additive
- Intermediate views are regular SQL VIEWs — no performance cost if unused
- The `step_handoff.yaml` will carry an array of metric view FQNs instead of a single value

---

## Design Decisions (Resolved)

| # | Question | Decision | Rationale |
|---|----------|----------|----------|
| 1 | Should all metric views share the same time-dimension column name? | **Yes** | Enables cross-metric-view filtering in dashboards. All metric views must expose a common time dimension (e.g., `service_month`) so a single date filter widget works across all dashboard pages regardless of which metric view sources the data. |
| 2 | Should Genie space receive ALL metric views? | **Yes — ALL** | Both dashboards and Genie spaces are developed for ALL implemented KPIs. The Genie space receives every metric view in its table list, with instructions explaining which metric view to query for each KPI category. |
| 3 | Should intermediate views be VIEWs or MATERIALIZED VIEWs? | **MATERIALIZED VIEW** (precomputed) | Intermediate views serve as stable, precomputed sources for metric views. Using materialized views avoids runtime join cost and ensures consistent performance for dashboard queries. |
| 4 | How should documentation report multi-view vs single-view? | **Abstracted — no distinction to user** | The system reports a unified KPI status regardless of how many metric views were created. The readme shows: what's implemented, what's not, reasons, and reference SQL for NOT_IMPLEMENTED KPIs. Internal architecture (number of metric views, intermediate views) is an implementation detail, not a user-facing concern. |

---

## LLM Agent-Driven Execution

### Core Design Principle: Prompt-Driven, Not Code-Driven

The entire multi-metric-view architecture is **executed by the LLM agent through prompts** — there is no hardcoded logic for determining metric view count, grouping KPIs, or deciding on intermediate views. The LLM makes all architectural decisions at runtime based on:

1. The schema profile (what tables/columns exist)
2. The KPI spec (what business logic is required)
3. The semantic model (what joins are safe)
4. The metric view constraints (what SQL is expressible)

### What the Prompt Must Instruct

The Metric View prompt (`02_create_metric_views.md`) drives the LLM to:

```text
1. ANALYZE: Read schema + KPI spec + semantic model holistically
2. PLAN: Produce metric_view_plan.yaml BEFORE creating anything
   - Group KPIs by grain
   - Decide metric view count (1, 2, 3... up to max 4)
   - Decide intermediate views needed (with join safety proof)
   - Classify NOT_IMPLEMENTED KPIs with reference SQL
3. BUILD: Execute the plan sequentially
   - Create intermediate materialized views (if any)
   - Create metric views
   - Validate each KPI
4. DOCUMENT: Write validation artifacts for downstream steps
```

### What Is NOT Hardcoded

- Number of metric views (LLM decides based on KPI analysis)
- Which KPIs go in which metric view (LLM decides based on grain)
- Whether intermediate views are needed (LLM decides based on schema)
- Which KPIs are NOT_IMPLEMENTED (LLM decides based on SQL constraints)

### What IS Fixed (Guard Rails in Prompt)

- Max 4 metric views per domain
- Each metric view must have ≥ 2 KPIs
- Fanout validation is mandatory for intermediate views
- NOT_IMPLEMENTED KPIs must have validated reference SQL
- Common time dimension name across all metric views
- All metric views go to both dashboards and Genie spaces

### Downstream Steps Consume the Plan

| Step | What it reads | What it does |
|------|--------------|-------------|
| Dashboard (Step 3) | `metric_view_plan.yaml` → all metric view FQNs | Creates datasets using `MEASURE()` from ALL metric views |
| Genie Space (Step 4) | `metric_view_plan.yaml` → all metric view FQNs | Adds ALL metric views to Genie table list + instructions |
| Documentation (Step 6) | `metric_view_plan.yaml` → full plan including NOT_IMPLEMENTED | Reports unified KPI coverage status with reference SQL |
