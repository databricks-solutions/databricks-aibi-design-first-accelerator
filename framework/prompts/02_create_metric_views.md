# Create Metric Views

## CONTEXT ISOLATION — Read This First

Forget all execution details from the Data Layer step (ERD parsing, synthetic data generation, DDL execution). You do NOT need that context.

**Your ONLY inputs are:**

1. `{OUTPUT_FOLDER}/step_handoff.yaml` — contains pre-formatted values (paste verbatim):
   - `metric_view_fqns[].name` — the resolved metric view name
   - `metric_view_fqns[].sql_fqn` — the EXACT backtick-quoted FQN (do NOT re-derive)
   - `catalog`, `schema` — for table references

2. `{OUTPUT_FOLDER}/erd_parsed.yaml` — table schemas (columns, types, PKs)

3. `{OUTPUT_FOLDER}/semantic_model.yaml` — relationships and grain

4. KPI specification — business definitions and formulas

**Rules:**
- Read `step_handoff.yaml` BEFORE any other action in this step
- Use `sql_fqn` for the metric view name in CREATE statements
- Use `catalog` and `schema` for source table references
- If these values look wrong, HALT — do NOT fix them locally

### Pipeline Halt Rules & Recovery

If `step_handoff.yaml` does NOT exist in `{OUTPUT_FOLDER}`:

1. Check if `run_context.yaml` exists in `{OUTPUT_FOLDER}`. If yes, reconstruct `step_handoff.yaml` from it:
   - Read `catalog`, `schema`, `version_suffix`, `assets.*` from `run_context.yaml`
   - Construct `sql_fqn` using: `` `{catalog}`.`{schema}`.`{metric_view_name}{version_suffix}` ``
   - Construct `dashboard_display_names` from `assets.dashboards[].name` + version suffix
   - Construct `genie_title` from `assets.genie.space_name` + version suffix
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
   - HALT with: `"❌ EXECUTION HALTED: Cannot resolve metric view FQNs. Neither step_handoff.yaml, run_context.yaml, nor accelerator.yaml are accessible."`

This recovery clause ensures that a missing handoff file (which should have been written in Step 0.7) does not permanently block the pipeline when all required information is available from other authoritative sources.

---

## Role

You are a senior analytics engineer and Databricks Unity Catalog Metric View architect.

Map KPIs to physical sources, design grain-safe Metric Views, create them using supported YAML syntax, and validate every implemented KPI.

The resulting Metric Views must be: semantically correct, grain-aware, resistant to measure fanout, faithful to the KPI spec, based only on confirmed physical columns, and safe for dashboards/SQL/Genie.

**Correct metric semantics take precedence over implementing every KPI. A KPI with insufficient source data MUST be skipped rather than implemented with guessed columns or unsafe joins.**

---

## ENFORCEMENT HEADER

<!-- @enforcement
  pattern: sql_statement_execution
  execution_context: sql_warehouse (Statement Execution API)
  inline_spark_sql_forbidden: true
  gates:
    - id: schema_profiled
      after_step: 2
      check: "file_exists('{OUTPUT_FOLDER}/metric_views/schema_profile.yaml')"
    - id: kpi_mapped
      after_step: 4
      check: "file_exists('{OUTPUT_FOLDER}/metric_views/kpi_metric_mapping.yaml')"
    - id: design_validated
      after_step: 6
      check: "file_exists('{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml')"
    - id: metric_view_created
      after_step: 8
      check: "SHOW VIEWS IN {catalog}.{schema} LIKE '%{VERSION_SUFFIX}' returns >= 1"
    - id: validation_passed
      after_step: 10
      check: "file_exists('{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml')"
-->

---

## PROHIBITED ACTIONS

1. **DO NOT execute Metric View DDL via `spark.sql()`** — `WITH METRICS LANGUAGE YAML` is ONLY supported via SQL Warehouse (Statement Execution API). Spark Connect raises `UNSUPPORTED_CLAUSE_FOR_OPERATION`.
2. **DO NOT invent columns** — every expr must reference confirmed physical columns.
3. **DO NOT guess join keys** from column-name similarity — use semantic_model.yaml relationships.
4. **DO NOT implement KPIs marked UNSAFE or AMBIGUOUS** — skip with documented reason.
5. **DO NOT use blind retry** — max 3 attempts, each with documented root cause and fix.
6. **DO NOT skip validation** — compilation success does NOT prove correctness.
7. **DO NOT use `description`** — use `comment` (description is NOT a valid YAML property).
8. **DO NOT use chained joins** — each `on` clause may ONLY reference `source.<col>` or `<this_join>.<col>`.
9. **DO NOT fall back to `spark.sql()`** if Statement Execution API times out — HALT and report.
10. **DO NOT use `CREATE OR REPLACE METRIC VIEW`** — "METRIC VIEW" is NOT a SQL object type. Correct: `CREATE OR REPLACE VIEW <name> WITH METRICS LANGUAGE YAML AS $$ ... $$`.
11. **DO NOT trust `data_layer_validation.yaml` alone** — ALWAYS run Join Key Diversity Pre-Check before designing joins.
12. **DO NOT include a join whose stability test fails** — if SUM before join ≠ SUM after join, the join produces fanout.
13. **DO NOT use `version: 1`** — MUST be `version: 1.1`.
14. **DO NOT use `type:` on columns** — causes `Unrecognized field` error.
15. **DO NOT use `agg:` on measures** — aggregation goes directly in `expr`.
16. **DO NOT use `wait_timeout` outside 5s–50s** — use `"50s"` as standard maximum.
17. **DO NOT use unquoted multi-word names in `MEASURE()`** — causes `PARSE_SYNTAX_ERROR`. Always use backticks: `` MEASURE(`Total Paid Amount`) ``.

---

## Databricks Metric View Reference

**Official documentation:** https://docs.databricks.com/aws/en/uc-semantics/metric-views/yaml-reference

The LLM MUST consult the official Databricks documentation for the current YAML specification. Do NOT rely on hardcoded templates for version numbers or syntax. The documentation is authoritative for:
- Supported YAML version
- Valid field/measure/join properties
- Expression syntax rules
- Filter and window support

This prompt documents only the **validated learnings** (things the docs don't tell you) and **execution patterns** specific to this accelerator.

---

## Core Principle

For every KPI, establish this chain before generating YAML:

```text
KPI → Business definition → Required grain → Measure column(s) → Physical source table →
Source grain → Required dimensions → Validated join paths → Aggregation semantics →
Validation query → Metric View implementation
```

No YAML may be generated until this chain is established.

---

## State & Checkpoint Contract

Uses **artifact-as-state** checkpointing (see `07_state_contract.md`). Before each phase, check if output exists → skip if valid.

| Phase | Artifact | Skip When |
|-------|----------|-----------|
| profile_schema | schema_profile.yaml | file exists |
| map_kpis | kpi_metric_mapping.yaml | file exists |
| design_metric_views | metric_view_design.yaml | file exists |
| generate_metric_views | Views in catalog | SHOW VIEWS returns expected names |
| validate_metric_views | metric_view_validation.yaml | file exists + status field |

---

# Step 1: Load Inputs

1. Read `accelerator.yaml`, apply name/version rules from `00_master_prompt.md`
2. Read KPI specification (authoritative for business intent, NOT for physical columns)
3. Read `erd_parsed.yaml` + `semantic_model.yaml` (when available)
4. Read `data_layer_validation.yaml` — HALT if `join_stability` or `foreign_keys` failed
5. Resolve Metric View FQN: `{catalog.target}.{schema}.{metric_view_name}`

### Input Authority

| Input | Authoritative For |
|-------|------------------|
| Physical schema (DESCRIBE TABLE / erd_parsed.yaml) | Columns, types, existence |
| semantic_model.yaml | Relationships, grains, classifications |
| KPI specification | Business intent, numerator/denominator, dimensions |

---

# Step 2: Resolve and Profile Source Schema

## Greenfield Fast Path (MANDATORY when applicable)

When `data_source.type = erd` AND `erd_parsed.yaml` + `semantic_model.yaml` + `data_layer_validation.yaml (PASS)` all exist:

1. Read contracts directly (DO NOT run DESCRIBE TABLE individually)
2. Run ONE SQL for table existence + row counts
3. Run ONE SQL for **Join Key Diversity Pre-Check** (see below)
4. Write `schema_profile.yaml` from contracts
5. Skip section 2.2 entirely

**NEVER loop through tables calling DESCRIBE TABLE when contracts are available.**

### MANDATORY: Join Key Diversity Pre-Check

Even with Greenfield Fast Path, verify ALL proposed join columns have diverse values:

```sql
SELECT '{table}.{col}' AS join_col, COUNT(DISTINCT {col}) AS distinct_vals, COUNT(*) AS total_rows
FROM {catalog}.{schema}.{table}
UNION ALL ...
```

**HALT if ANY join column has `distinct_vals = 1`** — this means FK/business-key diversity bug. Do NOT include the join; mark affected KPIs as SKIPPED.

## Data Source Mode Resolution

| Mode | Source |
|------|--------|
| `erd` | erd_parsed.yaml + semantic_model.yaml + catalog.source tables |
| `live_schema` | Discovered live schemas + KPI spec (follow live_schema_discovery.md) |
| `erd_and_live_schema` | Both; prefer live when populated AND semantically appropriate |

## Schema Profile Output

Write `{workspace.output_folder}/metric_views/schema_profile.yaml`:

```yaml
tables:
  - fqn:
    semantic_role:
    grain:
    row_count:
    keys:
    dimensions:
    measures:
    temporal_columns:
relationships: [...]
schema_drift: []
unresolved_relationships: []
```

**GATE 2.1**: schema_profile.yaml exists. HALT if missing.

---

# Step 3: Table Classification

Classify each table: FACT | DIMENSION | EVENT | SNAPSHOT | BRIDGE | REFERENCE | SCD2 | UNKNOWN.

For every table: "One row represents ______."

**Greenfield shortcut:** If `semantic_model.yaml` already classifies tables, copy directly.

---

# Step 4: Build KPI Semantic Mapping

Write `{workspace.output_folder}/metric_views/kpi_metric_mapping.yaml`:

```yaml
- kpi_id:
  kpi_name:
  business_definition:
  status: READY | UNSUPPORTED | AMBIGUOUS | UNSAFE
  required_grain:
  measure_components:
    - physical_table:
      physical_column:
      aggregation: SUM | COUNT | COUNT_DISTINCT | AVG | MIN | MAX
  dimensions: [...]
  time_dimension:
  aggregation_semantics: ADDITIVE | SEMI_ADDITIVE | NON_ADDITIVE | RATIO | DISTINCT_COUNT | WINDOW
  validation_strategy:
  gaps: []
```

### Measure Classification Rules

| Type | Rule |
|------|------|
| ADDITIVE | SUM/COUNT across all dimensions safely |
| SEMI_ADDITIVE | Unsafe to SUM across time (balances/snapshots) |
| RATIO | Use `SUM(numerator) / NULLIF(SUM(denominator), 0)` — NEVER `AVG(row_ratio)` |
| DISTINCT_COUNT | Use authoritative business key — never substitute `COUNT(*)` |
| WINDOW | Only when KPI spec requires period-over-period / running total |
| DERIVED | References other measures via `MEASURE(name)` composition |

**GATE 4.1**: kpi_metric_mapping.yaml exists. HALT if missing.

---

# Step 5: Source Selection & Join Safety

## Source Selection Rules

Choose source by **measure grain** (not by table name or size):
1. Contains or safely supports primary measures
2. Represents lowest analytical grain needed
3. Supports safe navigation to dimensions
4. Avoids fact-to-fact joins
5. Minimizes fanout

If one view can't safely represent all KPIs → CREATE MULTIPLE METRIC VIEWS.

## Join Validation (for every proposed join)

Document and verify:

```text
LEFT/RIGHT table, grain, key → Expected vs Observed cardinality → Rows before/after → SAFE/UNSAFE
```

**Rules:**
- Dimension joins must preserve source fact grain (N:1 = no row increase)
- Column-name similarity alone is INSUFFICIENT — use semantic_model.yaml
- Fact-to-fact joins = HIGH_RISK — establish grain compatibility before attempting
- Join chains NOT supported — every `on` clause references ONLY `source.` or `<this_join>.`
- SCD2 dimensions require temporal join conditions; if not representable → skip

**Measure Stability Test (MANDATORY for every join):**
```sql
-- Pre-join:
SELECT SUM(measure_col) FROM source_table
-- Post-join:
SELECT SUM(s.measure_col) FROM source_table s JOIN dim d ON s.fk = d.pk
-- MUST be equal. If not: JOIN_FANOUT_FAILURE — remove the join.
```

---

# Step 6: Build Metric View Design Contract

Write `{workspace.output_folder}/metric_views/metric_view_design.yaml`:

```yaml
metric_view:
  name:
  source_table:
  source_grain:
measures: [...]
dimensions: [...]
joins: [...]
kpis_supported: []
kpis_skipped: []
data_quality_blockers: []
```

**GATE 6.1**: metric_view_design.yaml exists with all joins validated. HALT if missing.

---

# Step 7: KPI Coverage Gate

Before YAML generation, produce a planning table:

| KPI | Source | Grain | Measure | Join Safety | Status |
|-----|--------|-------|---------|-------------|--------|

Only `READY` KPIs proceed. Every non-READY KPI needs a precise reason.

---

# Step 8: Generate Metric View YAML

### Pre-Flight

- [ ] metric_view_design.yaml exists
- [ ] All joins validated (no unresolved JOIN_FANOUT_FAILURE)
- [ ] All READY KPIs have confirmed measure columns
- [ ] Metric View FQN resolved

### DDL Syntax (ONLY correct form)

```sql
CREATE OR REPLACE VIEW {catalog}.{schema}.{view_name} WITH METRICS LANGUAGE YAML AS
$$
version: 1.1
comment: "..."
source: catalog.schema.table

fields:
  - name: Dimension Name
    expr: column_name
    comment: "..."

measures:
  - name: Measure Name
    expr: SUM(column_name)
    comment: "..."
$$
```

### Key Syntax Rules

- **Allowed field/dimension properties:** `name`, `expr`, `comment`, `display_name`, `format`, `synonyms`, `window`
- **Allowed measure properties:** `name`, `expr`, `comment`, `display_name`, `format`, `synonyms`, `window`
- **Allowed join properties:** `name`, `source`, `on`, `rely`
- `joins[].on`: SQL expression string (`source.col = join_name.col`) — NOT an object
- `'on'` key MUST be quoted in YAML (reserved word)
- `rely: {at_most_one_match: true}` for N:1 joins
- When NO joins: bare column names in expr. When joins exist: MUST prefix with `source.` or `<join_name>.`
- `MEASURE()` is for QUERYING metric views, NOT for creating them. Creation uses SQL agg in `expr`.

### Execution Pattern

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

w = WorkspaceClient()
response = w.statement_execution.execute_statement(
    warehouse_id="{sql_warehouse_id}",
    statement=ddl_statement,
    wait_timeout="50s"
)

if response.status.state == StatementState.SUCCEEDED:
    print("✓ Metric view created")
elif response.status.state == StatementState.FAILED:
    print(f"✗ Failed: {response.status.error.message}")
    # HALT — do NOT retry with spark.sql()
```

### Timeout Rules

- Use `"50s"` as default (valid range: 5s–50s)
- If timeout: poll with `w.statement_execution.get_statement(statement_id)` — NEVER re-execute
- If failed: HALT, fix YAML syntax, retry (max 3 attempts with documented root cause)

### No Chained Joins

```yaml
# INVALID (causes UNRESOLVED_COLUMN):
joins:
  - name: header
    source: catalog.schema.header
    'on': source.claim_id = header.claim_id
  - name: member
    source: catalog.schema.member
    'on': header.member_sk = member.member_sk   # ← ILLEGAL: references header

# VALID workarounds:
# 1. Direct FK in source → join dimension directly to source
# 2. Separate metric view sourced from the intermediate table
# 3. Skip dimension if FK only exists on intermediate
```

**GATE 8.1**: Metric view exists in catalog (`SHOW VIEWS`). HALT if missing.
**GATE 8.2**: Basic `SELECT MEASURE(first_measure) FROM mv LIMIT 1` succeeds.

---

# Step 9: Validate Metric Views

### BATCH VALIDATION (combine into 3-4 SQL calls)

```sql
-- BATCH 1: Structural (all measures/dimensions exist)
SELECT MEASURE(measure_1), MEASURE(measure_2), ... FROM metric_view LIMIT 1

-- BATCH 2: Baseline reconciliation (direct SQL vs MEASURE)
SELECT 'baseline_total_paid' check, SUM(col) val FROM source_table
UNION ALL
SELECT 'mv_total_paid', (SELECT MEASURE(total_paid) FROM metric_view)
UNION ALL ...

-- BATCH 3: Measure stability (pre-join vs post-join)
SELECT 'pre_join' check, SUM(col) FROM source
UNION ALL
SELECT 'post_join', SUM(s.col) FROM source s JOIN dim d ON s.fk = d.pk
UNION ALL ...

-- BATCH 4: Dimension slices
SELECT dim_col, MEASURE(total_paid) FROM metric_view GROUP BY dim_col LIMIT 10
```

### Validation Matrix

| Check | Expected | Fail Code |
|-------|----------|-----------|
| Structural: all measures/dimensions resolve | Query succeeds | `METRIC_VIEW_SYNTAX_ERROR` |
| Baseline reconciliation: direct SQL = MEASURE() | Values match (tolerance 0 for integers) | `METRIC_RECONCILIATION_ERROR` |
| Measure stability: SUM before join = after join | Equal | `MEASURE_FANOUT_FAILURE` |
| Dimension slice: grouped totals match baseline | Match | `DIMENSION_SLICE_ERROR` |
| Ratio: numerator + denominator independently validated | Match baseline | `RATIO_DEFINITION_ERROR` |
| Distinct count: matches direct COUNT(DISTINCT) | Equal | `DISTINCT_COUNT_ERROR` |
| Temporal: multiple periods produce expected results | Non-zero per period | `TEMPORAL_VALIDATION_ERROR` |

---

# Step 10: Write Validation Report

Write `{workspace.output_folder}/metric_views/metric_view_validation.yaml`:

```yaml
status: PASS | FAIL
metric_views:
  - name:
    source:
    source_grain:
kpis:
  - kpi:
    status: IMPLEMENTED_AND_VALIDATED | SKIPPED_*
    baseline_result:
    metric_view_result:
    difference:
    validation_status:
join_validation: [...]
measure_stability: [...]
skipped_kpis: [...]
```

### KPI Terminal States

```text
IMPLEMENTED_AND_VALIDATED
SKIPPED_MISSING_DATA
SKIPPED_UNRESOLVED_RELATIONSHIP
SKIPPED_UNSAFE_GRAIN
SKIPPED_UNSUPPORTED_SEMANTICS
SKIPPED_UNSUPPORTED_METRIC_VIEW_FEATURE
SKIPPED_FACT_TO_FACT_FANOUT_RISK
```

**GATE 10.1**: metric_view_validation.yaml exists. HALT if missing.

---

# Step 11: Generate Sample Queries

Only for KPIs with `IMPLEMENTED_AND_VALIDATED` status.

Write `{workspace.output_folder}/genie_space/{assets.sample_queries_file}`.

Generate 10–12 representative `MEASURE()` queries covering: overall measures, dimension grouping, filtering, time trends, multiple measures, ratios, window measures.

---

# Error Classification

| Code | Meaning |
|------|---------|
| `SCHEMA_DISCOVERY_ERROR` | Cannot resolve source tables |
| `SCHEMA_DRIFT` | Physical schema disagrees with contracts |
| `GRAIN_INFERENCE_ERROR` | Cannot determine source grain |
| `KPI_MAPPING_ERROR` | KPI cannot map to physical columns |
| `RELATIONSHIP_MAPPING_ERROR` | Join key not confirmed |
| `JOIN_FANOUT_ERROR` | Join multiplies rows |
| `FACT_TO_FACT_FANOUT_RISK` | Unsafe fact-to-fact join |
| `SCD_JOIN_UNSAFE` | Temporal dimension cannot be safely joined |
| `METRIC_VIEW_SYNTAX_ERROR` | YAML compilation failure |
| `METRIC_RECONCILIATION_ERROR` | Baseline ≠ MEASURE() result |
| `UNSUPPORTED_METRIC_VIEW_FEATURE` | Required feature not available |

---

# Pipeline Halt Rules

HALT with `❌ EXECUTION HALTED` when: no viable source for primary KPIs, primary grain unestablishable, required measure column missing, mandatory join produces fanout, YAML invalid after 3 root-cause-based retries.

A failure affecting only individual KPIs does NOT halt the entire stage — skip those KPIs with explicit classification.

---

# Validated Learnings (from production runs)

**1. `version` MUST be `1.1` (NOT integer `1`)**

Bare integer causes `Invalid YAML version: 1`. Omitting causes `Invalid YAML version: null`. Always use `version: 1.1`.

**2. `type` is NOT a valid column property**

Only: `name`, `expr`, `comment`, `display_name`, `format`, `synonyms`, `window`. Using `type: date` causes `Unrecognized field "type"`.

**3. `agg` is NOT a valid measure property**

Measures use full SQL in `expr`. No separate aggregation field. `agg: sum` causes `Unrecognized field "agg"`.

**4. Derived measures use `MEASURE()` composition**

```yaml
- name: avg_paid_per_claim
  expr: MEASURE(`total_paid`) / NULLIF(MEASURE(`total_claims`), 0)
```

No `agg: derived` property exists.

**5. `MEASURE()` references MUST use backtick quoting for multi-word names**

Without backticks, `MEASURE(Total Paid Amount)` causes `PARSE_SYNTAX_ERROR: Syntax error at or near 'Paid'`. The parser interprets spaces as expression boundaries.

```yaml
# WRONG — causes PARSE_SYNTAX_ERROR:
  expr: MEASURE(Total Paid Amount) / NULLIF(MEASURE(Total Claims), 0)

# CORRECT — backtick-quoted:
  expr: MEASURE(`Total Paid Amount`) / NULLIF(MEASURE(`Total Claims`), 0)
```

Rule: ALWAYS backtick-quote measure names inside `MEASURE()` — even single-word names are safe to quote.

**6. `wait_timeout` bounds: 5s–50s only**

Values outside (e.g., `"60s"`) cause `INVALID_PARAMETER_VALUE`. Use `"50s"` as standard.

**6. Single-source preferred for greenfield synthetic data**

Avoids fact-to-fact fanout from synthetic FK distributions. Add joins only after stability test passes.

**7. Column prefix rules depend on joins**

No joins → bare column names. With joins → MUST prefix `source.` or `<join_name>.` on ALL references.

---

# Output Contract

| Artifact | Location | Validation |
|----------|----------|-----------|
| schema_profile.yaml | `{OUTPUT_FOLDER}/metric_views/` | Tables + relationships documented |
| kpi_metric_mapping.yaml | `{OUTPUT_FOLDER}/metric_views/` | Every KPI mapped or skipped |
| metric_view_design.yaml | `{OUTPUT_FOLDER}/metric_views/` | All joins validated safe |
| {name}.yaml | `{OUTPUT_FOLDER}/metric_views/` | Raw YAML saved |
| metric_view_validation.yaml | `{OUTPUT_FOLDER}/metric_views/` | `status: PASS` |
| sample_queries file | `{OUTPUT_FOLDER}/genie_space/` | 10-12 MEASURE() queries |

---

# Progress Reporting Reference

| Phase | phase_id | Key Stats |
|-------|----------|-----------|
| Load Inputs | `load_inputs` | kpis_defined, source_tables |
| Profile Schema | `profile_schema` | tables_profiled, columns_total, relationships |
| Map KPIs | `map_kpis` | kpis_mapped, kpis_skipped, measures_classified |
| Design Metric Views | `design_metric_views` | metric_views_designed, join_paths_validated |
| Generate Metric Views | `generate_metric_views` | metric_views_created, measures_total, dimensions_total |
| Validate | `validate_metric_views` | validations_run, passed, failed |

Call `report_progress` with `status: "started"` before, `status: "completed"` after each phase.
