# Metric View Guardrails — Step 3 (Create Metric Views)

> **Also read:** `guardrails/00_global_rules.md` (always applies)

---

## Gates

### GATE 2.1: Schema Profile Exists
`schema_profile.yaml` must exist. HALT if missing.

### GATE 2.5: Relationship Verification
Relationship verification completed for all `semantic_model.yaml` relationships.

### GATE 4.1: KPI Metric Mapping Exists
`kpi_metric_mapping.yaml` must exist. HALT if missing.

### GATE 4.2: KPI Enumeration Completeness (MANDATORY)
Count mapping entries vs spec entries. If `len(kpi_metric_mapping) < len(kpi_spec)`, some KPIs were dropped without reason. HALT and re-enumerate.

### GATE 4.3: No Premature NOT_IMPLEMENTED Classification (MANDATORY)
At Step 4 (metric view planning), the ONLY valid reasons for NOT_IMPLEMENTED are:
- HAVING clause required (metric views cannot express HAVING)
- Window functions (LAG, LEAD, ROW_NUMBER) required
- Cross-grain joins required (two fact tables with incompatible grains)

**INVALID reasons at Step 4:**
- "Only 1 KPI for this grain" — a single KPI justifies a metric view if it's from a distinct fact table
- "Enrollment grain — single KPI insufficient for MV" — this was the v4/v5 root cause

### GATE 4.5: Multi-Grain Analysis Verification (MANDATORY)
List all fact tables. Verify each fact table with READY KPIs has a planned metric view. If `count(fact_tables_with_ready_kpis) > count(planned_metric_views)`, a grain was dropped. HALT and re-plan.

### GATE 5.7: Planned-vs-Created Metric View Parity (MANDATORY)
```
count(metric_view_plan) == count(metric_view_validation) == count(step_handoff.metric_view_fqns)
```
Hard FAIL if not equal. This catches the v4/v5 bug where plan said 2 MVs but only 1 was created.

### GATE 6.1: Metric View Design Exists
`metric_view_design.yaml` must exist with all joins validated. HALT if missing.

### GATE 7.5: Intermediate Views Exist
All planned intermediate views must exist in catalog. HALT if any are missing.

### GATE 8.1: Metric View Exists in Catalog
`SHOW VIEWS` must include the created metric view. HALT if missing.

### GATE 8.2: Metric View Queryable
`SELECT MEASURE(first_measure) FROM mv LIMIT 1` must succeed.

### GATE 10.1: Validation Artifact Exists
`metric_view_validation.yaml` must exist. HALT if missing.

---

## Prohibited Actions

0. DO NOT classify enrollment/secondary-grain KPIs as NOT_IMPLEMENTED without creating their metric view
1. DO NOT skip schema profiling
2. DO NOT skip relationship verification
3. DO NOT skip KPI enumeration completeness check (GATE 4.2)
4. DO NOT use raw SUM/COUNT/AVG instead of MEASURE() syntax
5. DO NOT create metric views with columns not in the source table
6. DO NOT modify source table data or schema
7. DO NOT skip validation of metric view queryability
8. DO NOT create metric views in a different schema than configured
9. DO NOT skip the multi-grain analysis (GATE 4.5)
10. DO NOT skip the planned-vs-created parity check (GATE 5.7)
11. DO NOT drop a secondary grain because it has "fewer than 2 KPIs"
12. DO NOT use source table column names in metric view DDL without verifying they match
13. DO NOT assume column names from spec text — use DESCRIBE TABLE
14. DO NOT create a metric view without validating its SQL against the source tables
15. DO NOT skip writing `step_handoff.yaml` with all metric_view_fqns
16. DO NOT reuse metric view names from prior versions without version suffix
17. DO NOT skip the KPI-to-metric-view mapping validation
18. DO NOT create metric views for KPIs that require HAVING/window functions
19. DO NOT skip intermediate view creation when metric views require joins
20. DO NOT proceed to dashboards without GATE 10.1 passing

---

## Anti-Patterns

### AP-MV-1: Single Metric View When 2 Grains Exist
**Pattern:** Plan says 2 metric views (claims + enrollment), validation shows 1. Enrollment MV was dropped because "only 1 KPI".
**Root cause:** Threshold of "fewer than 2 KPIs" in `02_create_metric_views.md` allowed dropping secondary grain.
**Fix:** Changed threshold from 2 to 1. GATE 5.7 now enforces plan-vs-created parity.

### AP-MV-2: Column Name Mismatch
**Pattern:** Metric view aliases differ from source table columns (e.g., `clm_dtl_claim_type` → `claim_type`). Dashboard SQL uses source names → fails.
**Fix:** Column Name Authority rule (G-3). Always DESCRIBE the metric view, not the source table.

### AP-MV-3: Premature NOT_IMPLEMENTED
**Pattern:** Agent classifies KPI as NOT_IMPLEMENTED at planning stage because it thinks "only 1 KPI per grain is insufficient." The KPI was actually implementable.
**Fix:** GATE 4.3 restricts NOT_IMPLEMENTED reasons to HAVING/window/cross-grain only.
