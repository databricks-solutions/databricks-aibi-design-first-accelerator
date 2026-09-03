# Create Metric Views

> **Guardrails:** Before executing this step, read and internalize:
> 1. `framework/prompts/guardrails/00_global_rules.md` (ALWAYS — every step)
> 2. `framework/prompts/guardrails/02_metric_view_guardrails.md` (THIS step's gates, rules, and anti-patterns)
>
> These guardrail files are BINDING. Violations are pipeline failures.

## CONTEXT ISOLATION — Read This First

Forget all execution details from the Data Layer step (ERD parsing, synthetic data generation, DDL execution). You do NOT need that context.

**Your ONLY inputs are:**

1. `{OUTPUT_FOLDER}/step_handoff.yaml` — contains:
   - `metric_view_fqns[]` — pre-resolved FQN(s) when `strategy: explicit`; empty or absent when `strategy: auto`
   - `metric_view_strategy` — `auto` or `explicit` (from run_context)
   - `metric_view_naming_prefix` — base prefix for auto-generated names (e.g., `member_claims`)
   - `catalog`, `schema`, `version_suffix` — for table references and dynamic FQN generation
   - `assets.metric_views` — base config from accelerator.yaml (may be auto strategy or explicit list)

2. `{OUTPUT_FOLDER}/erd_parsed.yaml` — table schemas (columns, types, PKs)

3. `{OUTPUT_FOLDER}/semantic_model.yaml` — relationships and grain

4. KPI specification — business definitions and formulas

**Rules:**
- Read `step_handoff.yaml` BEFORE any other action in this step
- Use `catalog` and `schema` for source table references
- The PRIMARY metric view FQN from `step_handoff.yaml` is used as-is for the main/primary metric view
- **ADDITIONAL metric views** are DYNAMICALLY CREATED during Step 4.5 planning when KPI grain analysis determines multiple source grains exist. See **Dynamic Metric View FQN Generation** below.
- After planning, UPDATE `step_handoff.yaml` to include ALL metric view FQNs (primary + dynamic) so downstream steps (dashboards, Genie) can discover them
- If catalog/schema values look wrong, HALT — do NOT fix them locally

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

## Dynamic Metric View FQN Generation

The `step_handoff.yaml` provides the **primary** metric view FQN. When KPI grain analysis (Step 4.5) determines that multiple source grains exist (e.g., claim-line grain AND enrollment grain), the LLM MUST dynamically generate additional metric view FQNs — do NOT skip KPIs simply because only one FQN was provided.

### Naming Convention

Derive additional metric view names from the primary name using the pattern:

```text
{base_name}_{grain_qualifier}{version_suffix}
```

Where:
- `base_name` = the primary metric view name WITHOUT the version suffix (e.g., `member_claims_metric_view`)
- `grain_qualifier` = a short, descriptive grain label (e.g., `enrollment`, `enriched`)
- `version_suffix` = from `step_handoff.yaml` (e.g., `_v1`)

**Examples (given primary = `member_claims_metric_view_v1`):**

| Grain | Derived Name | Source |
|-------|-------------|--------|
| Claim detail line (primary) | `member_claims_metric_view_v1` | `fact_claim_detail_v1` |
| Member enrollment | `member_claims_enrollment_metric_view_v1` | `fact_member_enrollment_v1` |
| Enriched claim (detail+header) | `member_claims_enriched_metric_view_v1` | intermediate materialized view |

### FQN Construction

For each dynamically derived name, construct the SQL FQN:

```text
sql_fqn: `{catalog}`.`{schema}`.`{derived_name}`
```

Use `catalog` and `schema` from `step_handoff.yaml`.

### Mandatory: Update `step_handoff.yaml` After Planning

After Step 4.5 completes, **APPEND** all dynamically derived metric view FQNs to `step_handoff.yaml` under `metric_view_fqns[]`. This is CRITICAL — downstream steps (dashboards, Genie) read `step_handoff.yaml` to discover ALL metric views.

```yaml
# Updated step_handoff.yaml after planning:
metric_view_fqns:
  - name: member_claims_metric_view_v1
    sql_fqn: "`catalog`.`schema`.`member_claims_metric_view_v1`"
    primary: true
  - name: member_claims_enrollment_metric_view_v1
    sql_fqn: "`catalog`.`schema`.`member_claims_enrollment_metric_view_v1`"
    primary: false
    grain: enrollment
    source: fact_member_enrollment_v1
```

### When NOT to Create Additional Metric Views

- All KPIs can be served by a single source grain → 1 metric view is correct
- A secondary grain has zero implementable KPIs → do not create a metric view for that grain
- A secondary grain has one or more implementable KPIs → create the metric view if the KPI is valid, sourced from a distinct fact grain, and may be consumed by dashboards or Genie. Do NOT drop a secondary grain solely because it has only 1 implementable KPI.
- The required join for an intermediate view fails the fanout safety test → do NOT create the intermediate view or the metric view that depends on it

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

0. **DO NOT classify enrollment/secondary-grain KPIs as NOT_IMPLEMENTED without creating their metric view** — if `fact_member_enrollment` (or any secondary fact table) has >= 2 KPIs with status READY, you MUST plan a secondary metric view in Step 4.5. Jumping straight to NOT_IMPLEMENTED because "it requires a different grain" is the #1 cause of metric view count divergence between runs. The correct flow is: mark READY in Step 4 → group by grain in Step 4.5 → create secondary MV → only mark NOT_IMPLEMENTED for HAVING/LAG/window KPIs.
1. **DO NOT execute Metric View DDL via `spark.sql()`** — `WITH METRICS LANGUAGE YAML` is ONLY supported via SQL Warehouse (Statement Execution API). Spark Connect raises `UNSUPPORTED_CLAUSE_FOR_OPERATION`.
2. **DO NOT invent columns** — every expr must reference confirmed physical columns.
3. **DO NOT blindly guess join keys** from column-name similarity alone — use ONLY relationships declared in `semantic_model.yaml` (both ERD-declared and inferred). Relationship discovery happens upstream in the data layer (Step 3.4). Step 2.5 here only verifies those relationships via data probes. If a relationship is missing from `semantic_model.yaml`, do NOT infer it here — mark the KPI as SKIPPED_UNRESOLVED_RELATIONSHIP.
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
18. **DO NOT use simple strings for `format`** — `format: "#,##0"` or `format: "$#,##0.00"` causes `METRIC_VIEW_INVALID_VIEW_DEFINITION: Failed to parse YAML: Could not resolve subtype of [simple`. The `format` property MUST be a structured YAML object with a `type` discriminator. See Validated Learning #8 for correct syntax.
19. **DO NOT use `format: {type: date}` or `format: {type: date_time}` without their MANDATORY sub-properties** — causes `METRIC_VIEW_INVALID_VIEW_DEFINITION: Missing required creator property 'date_format'`. When `type: date`, you MUST include `date_format`. When `type: date_time`, you MUST include both `date_format` and `time_format`. **Safest approach: OMIT `format` entirely on date/timestamp dimensions** — the dashboard will auto-format dates correctly without it. Only add `format` to date dimensions if the user specifically requests a custom date display format.

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

Uses **artifact-as-state** checkpointing (see `06_state_contract.md`). Before each phase, check if output exists → skip if valid.

| Phase | Artifact | Skip When |
|-------|----------|-----------|
| profile_schema | schema_profile.yaml | file exists |
| map_kpis | kpi_metric_mapping.yaml | file exists |
| plan_metric_views | metric_view_plan.yaml | file exists |
| design_metric_views | metric_view_design.yaml | file exists |
| create_intermediate_views | Intermediate views in catalog | SHOW VIEWS returns expected names |
| generate_metric_views | Metric views in catalog | SHOW VIEWS returns expected names |
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

# Step 2.5: Relationship Verification

## Purpose

Verify that the relationships declared in `semantic_model.yaml` (both ERD-declared and inferred from data layer Step 3.4) are safe for metric view joins. This step does **NOT** discover new relationships — relationship inference was done upstream in the data layer (Step 3.4 of `01_create_data_layer.md`). This step only validates what is already in the semantic model against actual data.

## When to Execute

- ALWAYS execute this step — it confirms join safety with actual data probes before designing metric views

## Verification Protocol

For every relationship in `semantic_model.yaml` (both `confidence: erd_declared` and `confidence: inferred`), run a cardinality probe. This step does NOT discover new relationships — it only verifies what the data layer already inferred.

### Cardinality Probe (run for each relationship)

```sql
SELECT
  '{child_table}.{child_col} -> {parent_table}.{parent_col}' AS relationship,
  COUNT(DISTINCT c.{child_col}) AS child_distinct,
  COUNT(DISTINCT p.{parent_col}) AS parent_distinct,
  (SELECT COUNT(*) FROM {catalog}.{schema}.{child_table}) AS child_rows,
  (SELECT COUNT(*) FROM {catalog}.{schema}.{child_table} c2
   JOIN {catalog}.{schema}.{parent_table} p2 ON c2.{child_col} = p2.{parent_col}) AS joined_rows,
  CASE
    WHEN (SELECT COUNT(*) FROM {catalog}.{schema}.{child_table}) =
         (SELECT COUNT(*) FROM {catalog}.{schema}.{child_table} c2
          JOIN {catalog}.{schema}.{parent_table} p2 ON c2.{child_col} = p2.{parent_col})
    THEN 'N:1_SAFE'
    ELSE 'FANOUT_OR_ORPHAN'
  END AS join_safety
FROM {catalog}.{schema}.{child_table} c
JOIN {catalog}.{schema}.{parent_table} p ON c.{child_col} = p.{parent_col}
```

### Classification

| Validation Result | Action |
|------------------|--------|
| `N:1_SAFE` + child_distinct > 1 + joined_rows = child_rows | PASS — relationship is safe for metric view joins |
| `N:1_SAFE` but child_distinct = 1 | WARN — FK diversity failure (all rows share one value), usable but dashboards will show single-value dimensions |
| `FANOUT_OR_ORPHAN` + joined_rows > child_rows | REJECT — M:N relationship (unsafe for metric views). Exclude from metric view joins. |
| `FANOUT_OR_ORPHAN` + joined_rows < child_rows | PASS with LEFT JOIN — orphan rows exist but join is still N:1 safe. Document data quality gap. |
| `joined_rows = 0` (zero matches) | FAIL — indicates a data generation gap (FK values not linked). Log and exclude from metric view joins for this run. |

**Note on zero-match results:** If `joined_rows = 0` for an inferred relationship on greenfield/synthetic data, this means the data layer's FK_REPLACEMENTS did not include this relationship. The relationship itself is likely valid (it was inferred from schema patterns in Step 3.4). Log: `"⚠️ DATA GAP: {relationship} has 0 matching rows. Re-run data layer to fix."` Do NOT use this relationship for metric view joins in this run — the data is not linkable.

### Output

Write verification results to `schema_profile.yaml` under `relationship_verification:`:

```yaml
relationship_verification:
  - relationship: fact_claim_detail.clm_dtl_claim_nbr -> fact_claim_header.clm_hdr_claim_nbr
    source: inferred  # or erd_declared
    child_rows: 10001
    joined_rows: 10001
    child_distinct: 1000
    join_safety: N:1_SAFE
    status: PASS
```

Only relationships with status PASS are available for metric view join decisions in Steps 4.5 and 5.

**GATE 2.5**: Relationship verification completed for all `semantic_model.yaml` relationships. At minimum, document `relationship_verification: []`.

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

**IMPORTANT: Do NOT mark a KPI as UNSUPPORTED solely because it requires a different grain than the primary metric view.** If the KPI's physical columns exist in a table (e.g., enrollment KPIs in `fact_member_enrollment`), mark it as `READY` with its `required_grain`. Step 4.5 will group READY KPIs by grain and dynamically create additional metric views as needed. Only mark UNSUPPORTED when the physical columns genuinely do not exist or the KPI business definition cannot be mapped to any available source.

### Column Name Authority: Physical Schema vs Spec Names

**The `physical_column` field in `kpi_metric_mapping.yaml` MUST use the exact column name from the ACTUAL physical table, not from the KPI spec text or `semantic_model.yaml` business names.**

Observed failure mode: The agent writes `physical_column: member_sk` because the spec says "member surrogate key", but the actual column in `fact_member_enrollment` is `member_sk` (correct) while in `dim_address` the actual column is `address_key` not `addr_key` (the ERD-parsed name). The ERD image column names are authoritative and already in `erd_parsed.yaml`. For greenfield data, `erd_parsed.yaml` column names MUST match because the data layer created tables from the same spec. For brownfield data, always validate with `DESCRIBE TABLE`.

**Rule:** When building `kpi_metric_mapping.yaml`, cross-reference each `physical_column` against `erd_parsed.yaml` (greenfield) or `DESCRIBE TABLE` output (brownfield). If the column name doesn't exist in the actual table schema, the mapping is WRONG and will cause downstream failures in metric view DDL, dashboard datasets, and Genie example SQL.

The metric view DDL step (Step 5+) may alias these physical names to cleaner dimension names (e.g., `clm_dtl_claim_type AS claim_type`). Those aliases become the authoritative column names for dashboards and Genie. Dashboard SQL MUST use the metric view's aliased names, NOT the source table's physical names.

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

### GATE 4.2: KPI Enumeration Completeness (MANDATORY)

After writing `kpi_metric_mapping.yaml`, verify that EVERY KPI from the KPI specification is present in the mapping — not just the ones that map to the primary fact table. Count the KPIs in the spec and count the entries in your mapping file.

```text
IF count(kpi_mapping_entries) < count(kpi_spec_entries):
  → HALT: "KPI enumeration incomplete: spec has {N} KPIs but mapping has {M}.
           Missing KPIs must be added with status READY (if columns exist in any
           fact table) or UNSUPPORTED (if genuinely unmappable)."
```

**Common violation (detected in prior runs):** The agent only maps KPIs whose columns exist in the PRIMARY fact table, silently dropping KPIs that belong to other fact tables (e.g., enrollment KPIs from `fact_member_enrollment`). This is WRONG — Step 4.5 needs the complete list to perform grain analysis.

### GATE 4.3: No Premature NOT_IMPLEMENTED Classification (MANDATORY)

Scan `kpi_metric_mapping.yaml` for any KPI marked `NOT_IMPLEMENTED` or `UNSUPPORTED` whose reason mentions "cross-grain", "different grain", "enrollment", or "different fact table".

```text
IF any KPI is NOT_IMPLEMENTED with a grain-based reason:
  → HALT: "Premature NOT_IMPLEMENTED: KPI {id} was classified as NOT_IMPLEMENTED
           because it requires a different grain. This decision belongs to Step 4.5
           (Multi-Metric View Planning), NOT Step 4. Reclassify as READY with the
           correct source_table and required_grain. Step 4.5 will determine whether
           a secondary metric view is feasible."
```

The ONLY valid reasons for NOT_IMPLEMENTED at Step 4 are:
- KPI requires HAVING clause (threshold-based filtering)
- KPI requires window functions (LAG, LEAD, rolling aggregation)
- KPI requires subqueries in the measure definition
- Physical columns genuinely do not exist in ANY table

"Requires a different fact table" is NOT a valid reason — it means a second metric view is needed, which is Step 4.5's job.

---

# Step 4.5: Multi-Metric View Planning

## Purpose

Before designing or creating any metric view, analyze ALL KPIs holistically to determine:

1. How many metric views are needed (grouped by source grain)
2. Whether any metric view requires an intermediate pre-joined materialized view as its source
3. Which KPIs are genuinely unsupported (HAVING, LAG, window functions) and should be classified as `NOT_IMPLEMENTED` with documented reference SQL

This planning step produces `metric_view_plan.yaml` — the authoritative plan consumed by all downstream phases.

## Decision Flow

Execute the following decision logic using `kpi_metric_mapping.yaml`, `schema_profile.yaml`, and the KPI specification:

```text
┌─────────────────────────────────────────────────────────┐
│  STEP A: Group KPIs by Required Source Grain             │
│                                                          │
│  For each KPI with status READY, determine:              │
│    - Which fact table(s) are needed?                     │
│    - What grain does the KPI operate at?                 │
│    - Does it need columns from multiple tables?          │
│                                                          │
│  Output: KPI groups by source grain                      │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│  STEP B: Determine Metric View Count                     │
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
│  STEP C: For Each Metric View — Determine Source         │
│                                                          │
│  Case A: Single fact table has all needed columns        │
│    → Source directly from fact table (no intermediate)   │
│                                                          │
│  Case B: Fact table needs dimension attributes           │
│    → If denormalized in fact: source directly            │
│    → If NOT denormalized: create intermediate view       │
│      that joins fact + dimension(s) at safe grain        │
│                                                          │
│  Case C: Two fact tables at different grains             │
│    → Create intermediate materialized view               │
│    → ONLY if join is N:1 (no fanout)                     │
│    → Example: fact_claim_detail JOIN fact_claim_header    │
│      ON claim_id (many lines per one header = N:1)       │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│  STEP D: Classify NOT_IMPLEMENTED KPIs                   │
│                                                          │
│  Any KPI requiring:                                      │
│    - HAVING clause (threshold-based filtering)           │
│    - Window functions (LAG, LEAD, rolling)               │
│    - Subqueries in measure definition                    │
│  → Classify as NOT_IMPLEMENTED                           │
│  → Write and validate reference SQL query                │
│  → Document in metric_view_plan.yaml                     │
│  → Exclude from dashboards and Genie spaces              │
└───────────────────────────────────────────────────────────┘
                            ▼
┌───────────────────────────────────────────────────────────┐
│  STEP E: Derive FQNs for All Metric Views                 │
│                                                          │
│  When strategy = auto (from step_handoff.yaml):           │
│    - ALL FQNs are derived dynamically from naming_prefix  │
│    - PRIMARY group: {prefix}_metric_view{version_suffix}  │
│    - SECONDARY groups: {prefix}_{grain}_metric_view{vs}   │
│      (e.g., member_claims_enrollment_metric_view_v3)      │
│                                                          │
│  When strategy = explicit:                                │
│    - PRIMARY group: use FQN from step_handoff.yaml        │
│    - ADDITIONAL groups: derive FQN dynamically            │
│      per the naming convention above                      │
│                                                          │
│  After FQN derivation (both modes):                       │
│    1. Include ALL metric views in metric_view_plan.yaml   │
│    2. Write/extend step_handoff.yaml metric_view_fqns[]   │
│       with ALL entries so downstream steps can discover   │
│       all metric views                                    │
│                                                          │
│  IMPORTANT: Do NOT skip KPIs because only one FQN was    │
│  provided or no FQNs were pre-resolved. If a grain group  │
│  has >= 2 implementable KPIs, derive an FQN and create    │
│  that metric view.                                        │
└───────────────────────────────────────────────────────────┘
```

## Architecture Patterns

### Pattern A: Direct Metric View (No Intermediate View)

Used when a single fact table contains all columns needed for the KPI group.

```text
fact_table ──→ metric_view
                ├─ KPI-1: measure expression
                ├─ KPI-2: measure expression
                └─ KPI-N: measure expression
```

**When to use:**
- The fact table already contains the dimension attributes needed
- OR the KPIs only need columns from the source fact (no dimension lookups)

### Pattern B: Intermediate Materialized View + Metric View

Used when the metric view needs columns from multiple tables that aren't co-located.

```text
fact_table_a ─────┐
                   ├─ intermediate_enriched_view ──→ metric_view
fact_table_b ─────┘       (materialized view)          ├─ KPI-X: measure
                                                        └─ KPI-Y: measure
```

**Intermediate view rules:**
1. Join MUST be N:1 from the grain table to the lookup table (no fanout)
2. Validate with: `SELECT COUNT(*) FROM detail d JOIN header h ON ...` = same as `SELECT COUNT(*) FROM detail`
3. Name convention: `{grain_table}_enriched_{version_suffix}`
4. Created as a **MATERIALIZED VIEW** (precomputed, no runtime join cost)
5. The metric view sources from this materialized view

**Join safety validation (MANDATORY before creating intermediate view):**

```sql
-- Verify no fanout: row count must be identical
SELECT
  (SELECT COUNT(*) FROM {catalog}.{schema}.{detail_table}) AS detail_rows,
  (SELECT COUNT(*) FROM {catalog}.{schema}.{detail_table} d
   JOIN {catalog}.{schema}.{header_table} h ON d.{fk_col} = h.{pk_col}) AS joined_rows
-- detail_rows MUST equal joined_rows
```

### Pattern C: Not Implemented — Documentation Only

Used for KPIs that cannot be expressed as metric view measures.

**Criteria for NOT_IMPLEMENTED classification:**
- Requires `HAVING` clause (e.g., members with total > threshold)
- Requires window functions (`LAG`, `LEAD`, `ROW_NUMBER`)
- Requires subqueries in the measure definition
- Requires conditional aggregation that metric view syntax cannot express

**MANDATORY: Write, validate, and document the reference SQL query.**

For each NOT_IMPLEMENTED KPI:
1. Write the reference SQL query that correctly computes the KPI
2. Execute the query against the warehouse to confirm it returns correct results
3. Store the validated SQL in `metric_view_plan.yaml` under `not_implemented`
4. These KPIs are **not included in dashboards or Genie spaces** — they are documentation-only artifacts

### GATE 4.5: Multi-Grain Analysis Verification (MANDATORY)

After writing `metric_view_plan.yaml`, verify the grain analysis was complete:

```text
1. List ALL fact tables from erd_parsed.yaml / schema_profile.yaml
2. For each fact table, check: does kpi_metric_mapping.yaml have >= 1 READY KPI
   sourced from this table?
3. For each fact table with >= 2 READY KPIs at a DISTINCT grain from the primary:
   → metric_view_plan.yaml MUST contain a metric view entry for that grain
   → If it does NOT, HALT: "Grain group missed: {fact_table} has {N} READY KPIs
     at {grain} but no metric view was planned for it."
```

**Common violation (detected in prior runs):** The agent plans only the primary metric view (from the largest fact table) and classifies all KPIs from other fact tables as NOT_IMPLEMENTED without creating secondary metric views. Another observed failure mode is planning the secondary metric view and then silently dropping it during creation because it contains only 1 KPI. Both behaviors are WRONG. The correct behavior is:
- `fact_claim_detail` → primary claims metric view (claim-line grain)
- `fact_member_enrollment` → secondary enrollment metric view (enrollment grain), even if it currently carries only `M-2`
- Only KPIs requiring HAVING/LAG/window are genuinely NOT_IMPLEMENTED

**Self-check before proceeding:**
```text
Fact tables in schema:       {list all fact tables}
Fact tables with metric views: {list fact tables that source a planned metric view}
Fact tables WITHOUT metric views: {list any fact tables with >= 2 READY KPIs but no MV}

IF Fact tables WITHOUT metric views is non-empty:
  → Go back to STEP B and create the missing metric view(s)
```

### GATE 5.7: Planned-vs-Created Metric View Parity (MANDATORY)

Before marking the metric-view stage complete, compare:
- `metric_view_plan.yaml` → `metric_views[]`
- `metric_view_validation.yaml` → `metric_views[]`
- `step_handoff.yaml` → `metric_view_fqns[]`

```text
IF count(planned_metric_views) != count(validated_metric_views):
  → FAIL the stage. Do NOT downgrade the missing metric view's KPI(s) to NOT_IMPLEMENTED.
  → Diagnose why the planned metric view was not created, fix the creation step, and rerun validation.

IF count(validated_metric_views) != count(step_handoff.metric_view_fqns):
  → FAIL the stage. Downstream stages must receive the full metric view set.
```

A run is NOT allowed to end Step 5 with:
- plan says 2 metric views
- validation says 1 metric view
- downstream dashboards/Genie proceed anyway

That exact mismatch caused fresh-run divergence and must now be treated as a hard failure.

## Guard Rails

1. **Max metric views per domain**: 4 (prevents over-fragmentation)
2. **Intermediate view fanout validation is MANDATORY** — never create an intermediate view without proving row count is preserved
3. **Each metric view must have ≥ 2 KPIs** — don't create a metric view for a single KPI (document the SQL as NOT_IMPLEMENTED instead)
4. **Prefer direct source over intermediate view** — only create intermediate views when columns are genuinely missing from the grain table
5. **NOT_IMPLEMENTED classification requires explicit reason + validated reference SQL** — the LLM must document why metric view syntax is insufficient and provide a query that runs successfully
6. **Common time dimension** — all metric views must expose a common time dimension name (e.g., `service_month`) so a single date filter works across dashboard pages

## Output: `metric_view_plan.yaml`

Write `{workspace.output_folder}/metric_views/metric_view_plan.yaml`:

```yaml
metric_view_plan:
  total_kpis: <N>
  implementable_in_metric_views: <N>
  not_implemented: <N>

  metric_views:
    - name: <metric_view_name_with_version>
      sql_fqn: "`catalog`.`schema`.`<metric_view_name_with_version>`"  # from step_handoff (primary)
      source: <source_table_or_intermediate_view>
      primary: true
      intermediate_view: null  # or object (see below)
      grain: "<one-row-represents description>"
      kpis: [<KPI-ID-1>, <KPI-ID-2>, ...]

    - name: <secondary_metric_view_name>  # dynamically derived name
      sql_fqn: "`catalog`.`schema`.`<secondary_metric_view_name>`"  # dynamically generated FQN
      source: <fact_table>
      primary: false
      intermediate_view: null
      grain: "<one-row-represents description>"
      kpis: [<KPI-ID-A>, <KPI-ID-B>, ...]

    - name: <enriched_metric_view_name>  # dynamically derived name
      sql_fqn: "`catalog`.`schema`.`<enriched_metric_view_name>`"  # dynamically generated FQN
      source: <intermediate_view_name>
      primary: false
      intermediate_view:
        name: <intermediate_view_name>
        join_sql: |
          SELECT d.*, h.<col1>, h.<col2>
          FROM {catalog}.{schema}.<detail_table> d
          JOIN {catalog}.{schema}.<header_table> h ON d.<fk> = h.<pk>
        join_type: "N:1 (<detail> to <header>)"
        fanout_validated: true
      grain: "<one-row-represents description>"
      kpis: [<KPI-ID-X>, <KPI-ID-Y>, ...]

  not_implemented:
    - kpi: <KPI-ID>
      name: "<KPI Name>"
      reason: "<Why metric view syntax is insufficient>"
      status: NOT_IMPLEMENTED
      documentation_only: true
      sql: |
        <Full validated SQL query>
      validated: true
      validation_row_count: <N>
      manual_implementation_notes: |
        To implement: Add as a named SQL dataset in the dashboard.
        Cannot be a metric view measure due to <reason>.
```

**GATE 4.5**: metric_view_plan.yaml exists with ≥ 1 metric view (each with `sql_fqn`), all NOT_IMPLEMENTED KPIs have validated SQL, and `step_handoff.yaml` has been extended with all dynamically derived metric_view_fqns entries. HALT if missing.

---

# Step 5: Source Selection & Join Safety

## Source Selection Rules

**This step now executes per metric view as defined in `metric_view_plan.yaml`.**

For each metric view in the plan, validate the source selection:
1. Contains or safely supports the measures assigned to this metric view
2. Represents the grain documented in the plan
3. Supports safe navigation to dimensions
4. If an intermediate view is planned: validate the join safety (Step 5.1 below)
5. Minimizes fanout

The metric_view_plan.yaml (from Step 4.5) is authoritative for which KPIs go to which metric view. Do NOT re-derive groupings here.

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

Write `{workspace.output_folder}/metric_views/metric_view_design.yaml`.

**This file now contains an array of metric view designs** — one per entry in `metric_view_plan.yaml`.

```yaml
metric_view_designs:
  - metric_view:
      name: <metric_view_name>
      source_table: <source_table_or_intermediate_view>
      source_grain: <grain description>
    measures: [...]
    dimensions: [...]
    joins: [...]
    kpis_supported: []
    kpis_skipped: []
    data_quality_blockers: []

  - metric_view:
      name: <secondary_metric_view_name>
      source_table: <source_table>
      source_grain: <grain description>
    measures: [...]
    dimensions: [...]
    joins: [...]
    kpis_supported: []
    kpis_skipped: []
    data_quality_blockers: []

not_implemented_kpis:
  - kpi: <KPI-ID>
    name: <KPI Name>
    reason: <reason>
    reference_sql: <validated SQL from metric_view_plan.yaml>

intermediate_views:
  - name: <view_name>
    source_tables: [<table1>, <table2>]
    join_type: "N:1"
    fanout_check: PASS
    source_rows: <N>
    joined_rows: <N>
```

**Rules for multi-view design:**
- Each metric view in the plan gets its own design entry
- All metric views MUST share a common time dimension name (e.g., `service_month`) for cross-view dashboard filtering
- Intermediate views are documented with their fanout validation results
- NOT_IMPLEMENTED KPIs are documented with the validated reference SQL from the plan

**GATE 6.1**: metric_view_design.yaml exists with all joins validated and all planned metric views represented. HALT if missing.

---

# Step 7: KPI Coverage Gate

Before YAML generation, produce a planning table:

| KPI | Source | Grain | Measure | Join Safety | Status |
|-----|--------|-------|---------|-------------|--------|

Only `READY` KPIs proceed. Every non-READY KPI needs a precise reason.

---

# Step 7.5: Create Intermediate Views

If `metric_view_plan.yaml` specifies any metric views with a non-null `intermediate_view`, create them **before** generating metric view YAML.

### For each intermediate view in the plan:

1. **Validate join safety (MANDATORY):**

```sql
SELECT
  (SELECT COUNT(*) FROM {catalog}.{schema}.{detail_table}) AS detail_rows,
  (SELECT COUNT(*) FROM {catalog}.{schema}.{detail_table} d
   JOIN {catalog}.{schema}.{header_table} h ON d.{fk_col} = h.{pk_col}) AS joined_rows
```

If `detail_rows != joined_rows` → **HALT** — do NOT create the intermediate view. Reclassify affected KPIs as `SKIPPED_FACT_TO_FACT_FANOUT_RISK`.

2. **Create the materialized view** using the DDL pattern:

```text
DDL Pattern: CREATE MATERIALIZED VIEW {catalog}.{schema}.{intermediate_view_name} AS
  SELECT d.*, h.{col1}, h.{col2}, ...
  FROM {catalog}.{schema}.{detail_table} d
  JOIN {catalog}.{schema}.{header_table} h ON d.{fk_col} = h.{pk_col}
```

If the view already exists, drop and recreate it. **Execute via Statement Execution API** (same pattern as metric view DDL). Do NOT use `spark.sql()`.

3. **Verify the materialized view exists:**

```sql
SHOW VIEWS IN {catalog}.{schema} LIKE '{intermediate_view_name}'
```

**GATE 7.5**: All planned intermediate views exist in catalog. HALT if any are missing.

---

# Step 8: Generate Metric View YAML

**This step now iterates over ALL metric views in `metric_view_plan.yaml`.**

For each metric view in `metric_view_designs[]` from the design contract:

### Pre-Flight (per metric view)

- [ ] metric_view_design.yaml exists with this metric view's entry
- [ ] All joins validated (no unresolved JOIN_FANOUT_FAILURE)
- [ ] All READY KPIs assigned to this metric view have confirmed measure columns
- [ ] Metric View FQN resolved: primary from `step_handoff.yaml`, additional from `metric_view_plan.yaml` (dynamically derived in Step 4.5)
- [ ] If sourced from an intermediate view: that view exists in catalog

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
  - name: Claim Count
    expr: COUNT(*)
    comment: "..."
    format:
      type: number
      decimal_places:
        type: exact
        places: 0
  - name: Total Paid Amount
    expr: SUM(paid_amount)
    comment: "..."
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
  - name: Denial Rate
    expr: SUM(denied) / NULLIF(COUNT(*), 0)
    comment: "..."
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 2
$$
```

**CRITICAL: `format` must be a structured object.** Never use simple strings like `format: "#,##0"`. Valid `format.type` values: `number`, `currency`, `percentage`, `date`, `date_time`, `byte`. **For date/timestamp dimensions: OMIT `format` entirely** (safest) or include ALL mandatory sub-properties (`date_format` for `date`, both `date_format` + `time_format` for `date_time`). See Prohibited Action #19 and Validated Learning #8.

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

**CRITICAL SQL SYNTAX RULE**: In Databricks SQL, `LIMIT` binds to the entire
statement, NOT to individual sub-queries. Placing `LIMIT` inside a `UNION ALL`
sub-query is a **PARSE_SYNTAX_ERROR**. Either:
- Run each metric view's structural check as a **separate** `execute_sql` call, OR
- Wrap each sub-query in parentheses: `(SELECT ... LIMIT 1) UNION ALL (SELECT ... LIMIT 1)`

Prefer separate calls — they are easier to diagnose on failure.

```sql
-- BATCH 1: Structural (all measures/dimensions exist)
-- Run ONE query per metric view — do NOT combine with UNION ALL + LIMIT
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
  - name: <metric_view_name>
    source: <source_table_or_intermediate_view>
    source_grain: <grain description>
    validation_status: PASS | FAIL
    kpi_count: <N>
  - name: <secondary_metric_view_name>
    source: <source_table>
    validation_status: PASS | FAIL
    kpi_count: <N>

intermediate_views:
  - name: <intermediate_view_name>
    fanout_check: PASS | FAIL
    source_rows: <N>
    joined_rows: <N>

kpis:
  - kpi: <KPI-ID>
    metric_view: <metric_view_name>  # which metric view implements this KPI
    status: IMPLEMENTED_AND_VALIDATED | SKIPPED_* | NOT_IMPLEMENTED
    baseline_result: <value>
    metric_view_result: <value>
    difference: <value>
    validation_status: PASS | FAIL
  - kpi: <KPI-ID>
    metric_view: null  # NOT_IMPLEMENTED KPIs have no metric view
    status: NOT_IMPLEMENTED
    reason: "<reason>"
    sql_ref: "See metric_view_plan.yaml"
    documentation_only: true

join_validation: [...]
measure_stability: [...]
skipped_kpis: [...]
```

### KPI Terminal States

```text
IMPLEMENTED_AND_VALIDATED
NOT_IMPLEMENTED
SKIPPED_MISSING_DATA
SKIPPED_UNRESOLVED_RELATIONSHIP
SKIPPED_UNSAFE_GRAIN
SKIPPED_UNSUPPORTED_SEMANTICS
SKIPPED_UNSUPPORTED_METRIC_VIEW_FEATURE
SKIPPED_FACT_TO_FACT_FANOUT_RISK
```

**NOT_IMPLEMENTED vs SKIPPED distinction:**
- `NOT_IMPLEMENTED`: KPI is well-defined and the SQL is known, but metric view syntax cannot express it (HAVING, LAG, window). Reference SQL is provided in `metric_view_plan.yaml`.
- `SKIPPED_*`: KPI cannot be implemented due to data quality, missing relationships, or unsafe grain. No reference SQL is provided.

**GATE 10.1**: metric_view_validation.yaml exists. HALT if missing.

---

# Step 11: Generate Sample Queries

Only for KPIs with `IMPLEMENTED_AND_VALIDATED` status.

Write `{workspace.output_folder}/genie_space/{assets.sample_queries_file}`.

Generate 10–12 representative `MEASURE()` queries **spanning ALL metric views**. Queries should cover: overall measures, dimension grouping, filtering, time trends, multiple measures, ratios, window measures.

Each query must reference the correct metric view FQN for the KPIs it uses. Do NOT mix measures from different metric views in a single query — `MEASURE()` operates on one metric view at a time.

**Exclude NOT_IMPLEMENTED KPIs** — these have no metric view and cannot be queried with `MEASURE()`.

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

**8. `format` MUST be a structured object — NEVER a simple string**

Using `format: "#,##0"` or `format: "$#,##0.00"` causes `METRIC_VIEW_INVALID_VIEW_DEFINITION: Failed to parse YAML: Could not resolve subtype of [simple`. The YAML parser uses polymorphic deserialization on `format` and requires a `type` discriminator.

```yaml
# WRONG — causes parse failure:
  - name: Total Paid Amount
    expr: SUM(paid_amt)
    format: "$#,##0.00"           # ← simple string = CRASH

# WRONG — causes parse failure:
  - name: Denial Rate
    expr: SUM(denied) / NULLIF(COUNT(*), 0)
    format: "0.00%"               # ← simple string = CRASH

# CORRECT — structured object:
  - name: Total Paid Amount
    expr: SUM(paid_amt)
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2

# CORRECT — percentage:
  - name: Denial Rate
    expr: SUM(denied) / NULLIF(COUNT(*), 0)
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 2

# CORRECT — integer count:
  - name: Total Claims
    expr: COUNT(DISTINCT claim_id)
    format:
      type: number
      decimal_places:
        type: exact
        places: 0

# CORRECT — decimal ratio:
  - name: Lines per Claim
    expr: COUNT(*) / NULLIF(COUNT(DISTINCT claim_id), 0)
    format:
      type: number
      decimal_places:
        type: exact
        places: 2
```

# CORRECT — date dimension (ALL sub-properties are MANDATORY):
  - name: Service Date
    expr: service_date
    format:
      type: date
      date_format: year_month_day    # REQUIRED: locale_short_month | locale_long_month | year_month_day | locale_number_month | year_week

# CORRECT — date_time dimension (BOTH sub-properties are MANDATORY):
  - name: Created At
    expr: created_timestamp
    format:
      type: date_time
      date_format: locale_short_month  # REQUIRED
      time_format: locale_hour_minute  # REQUIRED: no_time | locale_hour_minute | locale_hour_minute_second

# WRONG — missing date_format causes CRASH:
  - name: Service Date
    expr: service_date
    format:
      type: date                       # ← Missing date_format = METRIC_VIEW_INVALID_VIEW_DEFINITION

# SAFEST for date/timestamp dimensions — just OMIT format entirely:
  - name: Service Date
    expr: service_date
    comment: "Date of service"         # No format block — dashboard auto-formats dates correctly
```

Valid `format.type` values: `number` | `currency` | `percentage` | `date` | `date_time` | `byte`. Omit `format` entirely if no specific formatting is needed. **For date/timestamp dimensions, omitting `format` is strongly recommended** — dashboards auto-detect and format date columns correctly.

---

# Output Contract

| Artifact | Location | Validation |
|----------|----------|-----------|
| schema_profile.yaml | `{OUTPUT_FOLDER}/metric_views/` | Tables + relationships documented |
| kpi_metric_mapping.yaml | `{OUTPUT_FOLDER}/metric_views/` | Every KPI mapped or skipped |
| metric_view_plan.yaml | `{OUTPUT_FOLDER}/metric_views/` | ≥ 1 metric view planned, NOT_IMPLEMENTED KPIs have validated SQL |
| metric_view_design.yaml | `{OUTPUT_FOLDER}/metric_views/` | All metric views designed, all joins validated safe |
| {name}.yaml | `{OUTPUT_FOLDER}/metric_views/` | Raw YAML saved (one per metric view) |
| metric_view_validation.yaml | `{OUTPUT_FOLDER}/metric_views/` | `status: PASS`, all metric views validated |
| sample_queries file | `{OUTPUT_FOLDER}/genie_space/` | 10-12 MEASURE() queries spanning all metric views |

---

# Progress Reporting Reference

| Phase | phase_id | Key Stats |
|-------|----------|-----------|
| Load Inputs | `load_inputs` | kpis_defined, source_tables |
| Profile Schema | `profile_schema` | tables_profiled, columns_total, relationships |
| Map KPIs | `map_kpis` | kpis_mapped, kpis_skipped, measures_classified |
| Plan Metric Views | `plan_metric_views` | metric_views_planned, intermediate_views_needed, kpis_not_implemented |
| Design Metric Views | `design_metric_views` | metric_views_designed, join_paths_validated |
| Create Intermediate Views | `create_intermediate_views` | intermediate_views_created, fanout_checks_passed |
| Generate Metric Views | `generate_metric_views` | metric_views_created, measures_total, dimensions_total |
| Validate | `validate_metric_views` | validations_run, passed, failed |

Call `report_progress` with `status: "started"` before, `status: "completed"` after each phase.
