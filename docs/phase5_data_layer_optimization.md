# Phase 5: Data Layer Performance Optimization

## Objective

Reduce Data Layer step execution from ~20 minutes to ~5 minutes while maintaining:
- **Purely agentic architecture** — LLM-driven, no custom Python execution layer
- **Environment parity** — Same prompts work in both App mode and Genie Code
- **Prompt-driven execution** — All optimization is achieved through smarter prompt design

---

## Problem Analysis

### Current Data Layer Breakdown (~20 min, 42 iterations)

| Phase | LLM Iterations | Wall Time | Root Cause |
|-------|---------------|-----------|------------|
| Parse ERD (vision model) | 3-5 | ~2.5 min | Vision model inference + LLM reading result |
| Semantic Model | 5-8 | ~3 min | LLM reasoning about relationships iteratively |
| Generate DDL (per-table) | 8-12 | ~5 min | LLM writes SQL one table at a time, executes each |
| Generate Synthetic Data (dbldatagen) | 10-15 | ~7 min | LLM generates Python per-table, multiple notebooks |
| Validate | 5-8 | ~2.5 min | Individual SELECT COUNT(*) per table |

### Why It's Slow

1. **42 LLM round-trips** × 15-25s each (inference + tool execution + response parse) = ~14 min pure latency
2. **Context grows** with each iteration → later iterations are 2-3× slower
3. **SQL runs sequentially** even though tables are independent
4. **Per-table iteration** pattern instead of batch-all-at-once
5. **Multiple notebook create+execute cycles** instead of one comprehensive notebook

---

## Solution: Multi-Statement SQL + Single-Notebook Pattern

### Key Insight

The optimization is purely **prompt-level** — instruct the LLM to:
1. Batch ALL DDL into one multi-statement SQL call (instead of per-table)
2. Generate ONE comprehensive dbldatagen notebook (instead of per-table notebooks)
3. Use a single UNION ALL validation query (instead of per-table counts)

### Multi-Statement SQL Support

Databricks SQL warehouses support multi-statement execution:
- Multiple statements separated by semicolons in a single API call
- Sequential execution within the same session
- Transactional support available: https://docs.databricks.com/aws/en/transactions/transaction-modes

---

## Target: Optimized Data Layer Flow (~5 min, 10-13 iterations)

```
Iteration  Tool Call                                     Time      Phase
─────────────────────────────────────────────────────────────────────────
1          read_file(accelerator.yaml)                   ~3s       Input
2          call_vision_model(erd.png)                    ~45s      Parse ERD
3          read_file(kpi_spec.md)                        ~3s       Input
4          write_file(erd_parsed.yaml)                   ~3s       Artifact
5          write_file(semantic_model.yaml)               ~3s       Artifact
6          report_progress(parse_erd, completed)         ~1s       Checkpoint

           [LLM inference: generate ALL DDL              ~45-60s   (single reasoning pass)
            using erd_parsed + semantic_model]

7          execute_sql(ALL DDL — multi-statement)        ~30-45s   DDL
8          report_progress(create_tables, completed)     ~1s       Checkpoint

           [LLM inference: generate complete             ~45-60s   (single reasoning pass)
            dbldatagen notebook for ALL tables]

9          create_notebook(synthetic_data_all_tables)    ~5s       Data Gen
10         execute_notebook(synthetic_data_all_tables)   ~60-90s   Data Gen (Spark)
11         report_progress(generate_data, completed)     ~1s       Checkpoint
12         execute_sql(VALIDATION — single UNION ALL)    ~5s       Validate
13         write_file(data_layer_validation.yaml)        ~3s       Artifact
14         report_step_complete                          ~1s       Done
─────────────────────────────────────────────────────────────────────────
TOTAL: ~13 iterations                                   ~4.5-5.5 min
```

---

## Detailed Design: Prompt Changes

### 1. DDL Phase — Multi-Statement Batch

**Current prompt pattern (causes 12+ iterations):**
```
For each table in the parsed ERD:
  1. Generate CREATE TABLE DDL
  2. Execute it via execute_sql
  3. Verify it exists
  4. Move to next table
```

**New prompt pattern (1 iteration):**
```markdown
## DDL Execution Rules

Generate ALL CREATE TABLE statements as a SINGLE multi-statement SQL block.
Execute them in ONE execute_sql call with semicolons separating statements.

Ordering within the block:
1. CREATE SCHEMA IF NOT EXISTS (first)
2. Dimension tables (no FK dependencies on other new tables)
3. Fact tables (may reference dimension PKs — but CREATE TABLE doesn't enforce FKs in Delta)

Example pattern:
```sql
CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`;

CREATE TABLE IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`.dim_members (
  member_id STRING NOT NULL,
  first_name STRING,
  last_name STRING,
  date_of_birth DATE,
  gender STRING,
  plan_type STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`.dim_providers (
  provider_id STRING NOT NULL,
  provider_name STRING,
  specialty STRING,
  facility_id STRING
) USING DELTA;

-- ... ALL remaining tables in one block
```

**DO NOT:**
- Execute tables one at a time
- Verify each table after creation (validate all at end)
- Loop through tables individually
- Create a notebook for DDL (use execute_sql directly)

**DO:**
- Generate ALL DDL in one reasoning pass
- Execute ALL DDL in ONE multi-statement execute_sql call
- Include all column definitions, data types, and constraints
```

### 2. Synthetic Data Phase — Single Comprehensive dbldatagen Notebook

**Current prompt pattern (causes 10-15+ iterations):**
```
For each table:
  1. Generate dbldatagen Python code for this table
  2. Create notebook (or append to notebook)
  3. Execute notebook
  4. Verify data exists
```

**New prompt pattern (2 iterations: create + execute):**
```markdown
## Synthetic Data Generation Rules

Generate ONE Python notebook that uses `dbldatagen` to populate ALL tables.
The notebook handles table ordering internally (dimensions first, then facts).

Notebook structure:
```python
# Cmd 1: Setup
import dbldatagen as dg
from pyspark.sql.types import *

catalog = "{CATALOG}"
schema = "{SCHEMA}"

# Cmd 2: Dimension tables (independent — generate first)
dim_members_spec = (
    dg.DataGenerator(spark, name="dim_members", rows=500, seedMethod="hash_fieldname")
    .withColumn("member_id", StringType(), format="MEM-%06d", uniqueValues=500)
    .withColumn("first_name", StringType(), values=["James","Mary","John","Patricia",...], random=True)
    .withColumn("last_name", StringType(), values=["Smith","Johnson","Williams",...], random=True)
    .withColumn("date_of_birth", DateType(), begin="1940-01-01", end="2005-12-31", random=True)
    .withColumn("gender", StringType(), values=["M","F","O"], weights=[48,48,4], random=True)
    .withColumn("plan_type", StringType(), values=["HMO","PPO","EPO","POS"], random=True)
)
dim_members_spec.build().write.mode("overwrite").saveAsTable(f"{catalog}.{schema}.dim_members")
print("✓ dim_members: 500 rows")

dim_providers_spec = (
    dg.DataGenerator(spark, name="dim_providers", rows=200, seedMethod="hash_fieldname")
    # ... all columns
)
dim_providers_spec.build().write.mode("overwrite").saveAsTable(f"{catalog}.{schema}.dim_providers")
print("✓ dim_providers: 200 rows")

# ... all other dimension tables

# Cmd 3: Fact tables (reference dimension values for FK integrity)
member_ids = [row.member_id for row in spark.table(f"{catalog}.{schema}.dim_members").select("member_id").collect()]
provider_ids = [row.provider_id for row in spark.table(f"{catalog}.{schema}.dim_providers").select("provider_id").collect()]

fact_claims_spec = (
    dg.DataGenerator(spark, name="fact_claims", rows=5000, seedMethod="hash_fieldname")
    .withColumn("claim_id", StringType(), format="CLM-%09d", uniqueValues=5000)
    .withColumn("member_id", StringType(), values=member_ids, random=True)
    .withColumn("provider_id", StringType(), values=provider_ids, random=True)
    .withColumn("claim_date", DateType(), begin="2022-01-01", end="2024-12-31", random=True)
    .withColumn("claim_amount", DecimalType(10,2), minValue=50.0, maxValue=50000.0, random=True)
    # ... all columns with realistic distributions
)
fact_claims_spec.build().write.mode("overwrite").saveAsTable(f"{catalog}.{schema}.fact_claims")
print("✓ fact_claims: 5000 rows")

# Cmd 4: Summary
print("\n=== ALL TABLES GENERATED ===")
```

**Key principles for the notebook:**
- ONE notebook, ALL tables
- Dimensions generated FIRST (so facts can reference their actual values)
- Use `.collect()` on dimension PKs to feed into fact table FK columns
- Use `seedMethod="hash_fieldname"` for reproducibility
- Use realistic distributions (weights, ranges, value lists)
- Print progress after each table for visibility
- Mode "overwrite" for idempotency

**DO NOT:**
- Create separate notebooks per table
- Execute notebook multiple times
- Generate data using SQL INSERT statements
- Generate data without proper FK referential integrity
```

### 3. Validation Phase — Single UNION ALL Query

**Current prompt pattern (causes 5-8 iterations):**
```
For each table:
  1. SELECT COUNT(*) FROM table
  2. Parse result
  3. Record in validation
```

**New prompt pattern (1 iteration):**
```markdown
## Validation Rules

Validate ALL tables in ONE execute_sql call using a UNION ALL pattern:

```sql
SELECT 'dim_members' as table_name, COUNT(*) as row_count FROM `{CATALOG}`.`{SCHEMA}`.dim_members
UNION ALL
SELECT 'dim_providers', COUNT(*) FROM `{CATALOG}`.`{SCHEMA}`.dim_providers
UNION ALL
SELECT 'dim_facilities', COUNT(*) FROM `{CATALOG}`.`{SCHEMA}`.dim_facilities
UNION ALL
SELECT 'fact_claims', COUNT(*) FROM `{CATALOG}`.`{SCHEMA}`.fact_claims
-- ... ALL tables
```

A table passes validation if row_count > 0.
Write results to `data_layer_validation.yaml`.

**DO NOT:**
- Query tables individually
- Run DESCRIBE TABLE on each table
- Do column-level validation (that's for brownfield/migration scenarios only)
```

---

## Tool Layer Changes Required

### 1. `execute_sql` Timeout for Multi-Statement

Multi-statement DDL + data gen can take 30-90s. The current `execute_and_wait` has `timeout_s=120.0` which should be sufficient, but:

**Change in `tool_executor.py`:**
```python
def _handle_execute_sql(self, args: dict) -> str:
    statement = args["statement"]
    # Use longer timeout for multi-statement SQL (contains semicolons)
    timeout = 300.0 if ';' in statement else 120.0
    try:
        result = self._sql.execute_and_wait(statement, timeout_s=timeout)
    except Exception as e:
        return f"SQL ERROR: {str(e)}"
    # ... rest unchanged
```

### 2. No Other Tool Changes Needed

- `create_notebook` — already supports full content
- `execute_notebook` — already supports long-running notebooks
- `write_file` — unchanged
- `call_vision_model` — unchanged

---

## Genie Code Compatibility

The same prompt works identically in Genie Code:

| Concern | App Mode | Genie Code |
|---------|----------|------------|
| Multi-statement SQL | execute_sql tool (sql_client.py) | Genie Code's built-in SQL execution |
| dbldatagen notebook | create_notebook + execute_notebook tools | Genie Code creates + runs notebook |
| Vision model | call_vision_model tool | Genie Code's built-in vision |
| Validation | execute_sql tool | Genie Code's SQL execution |
| Iterations | ~13 | ~13 (same prompt, same flow) |
| Time | ~5 min | ~5-7 min (slightly slower LLM inference) |

**No divergence** — the optimization is purely in how the prompt instructs the LLM to batch work, not in any app-layer Python execution.

---

## Comparison: Before vs After

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| LLM iterations | 42 | 13 | 3.2× fewer |
| execute_sql calls | 12-15 | 2 | 7× fewer |
| Notebooks created | 2-3 | 1 | 2-3× fewer |
| Notebook executions | 2-3 | 1 | 2-3× fewer |
| Validation queries | 5-8 | 1 | 5-8× fewer |
| Total wall time | ~20 min | ~5 min | 4× faster |
| Context window growth | 50K+ tokens | ~15K tokens | 3× smaller |

---

## Implementation Plan

### Step 1: Prompt Rewrite (`01_create_data_layer.md`)
- Restructure phase instructions to use batch patterns
- Add explicit "multi-statement DDL" rules
- Add "single notebook for all tables" rules for dbldatagen
- Add "UNION ALL validation" pattern
- Remove per-table iteration patterns

### Step 2: Tool Timeout Adjustment (`tool_executor.py`)
- Detect multi-statement SQL (contains semicolons)
- Use 300s timeout for multi-statement batches
- Return aggregate result summary

### Step 3: Test Run
- Run data layer with new prompt on member_claims domain
- Verify multi-statement DDL executes correctly
- Verify single dbldatagen notebook creates all tables with FK integrity
- Verify UNION ALL validation catches missing tables
- Measure iteration count and wall time

### Step 4: Apply Same Pattern to Other Steps
- **Metric Views**: Batch all CREATE VIEW statements into one multi-statement call
- **Dashboards**: Generate complete dashboard spec in one pass, single create_dashboard call
- **Genie Space**: Single create_genie_space call (already one call)
- **Documentation**: Single write_file for each doc (already efficient)

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Multi-statement SQL fails mid-batch | Critical tool halt triggers immediately; LLM reports failure |
| LLM output token limit hit (DDL too large) | 16384 token limit should cover ~15 tables; increase if needed |
| dbldatagen notebook too large for one cell | Split into multiple cells (one per table group) within same notebook |
| FK integrity in synthetic data | Prompt instructs: generate dimensions first, collect PKs, feed to facts |
| Vision model output quality | Unchanged — same single call, same quality |
| Genie Code multi-statement support | Databricks SQL natively supports it; Genie Code uses same warehouse |

---

## Success Criteria

- [ ] Data Layer completes in ≤ 6 minutes (end-to-end)
- [ ] LLM iterations ≤ 15
- [ ] All tables created with correct schema
- [ ] Synthetic data has FK referential integrity
- [ ] Validation passes (all tables have rows > 0)
- [ ] Same prompt works in Genie Code without modification
- [ ] No custom Python execution at app layer (purely agentic)

---

## Bug Fixes Applied (Prerequisite for Phase 5)

### Fix 1: `lakeview_dashboard_api.md` Path Error

**Problem**: Prompt line 165 in `03_create_dashboards.md` used `{EXAMPLE_DIR}/{paths.framework_root}/inputs/lakeview_dashboard_api.md` which concatenated a relative domain path with an absolute framework path, producing an invalid path.

**Fix**: Changed to environment-aware loading:
- In App mode: the file is injected as SUPPLEMENTARY REFERENCE (system message) — LLM checks for it first
- In Genie Code: LLM reads from `{deploy_root}/framework/inputs/lakeview_dashboard_api.md` (correct absolute path)
- Same fix applied to `04_create_genie_space.md` for `genie_space_configuration.md`

### Fix 2: SQL Syntax Errors (UNION ALL generation)

**Problem**: LLM generates complex UNION ALL queries with many columns and occasionally produces syntax errors (trailing commas, truncated column names, mismatched column counts). Self-corrects on retry but wastes time.

**Fix**: Added SQL Quality Rules to both `00_master_prompt.md` and `03_create_dashboards.md`:
- Column count alignment check before UNION ALL
- No trailing commas rule
- Complete identifiers rule (never truncate)
- Explicit alias rule for all computed columns
- Mental verification rule for >30 line SQL

---

## Future Optimizations (Phase 5b)

Once the batch pattern is proven for Data Layer:

1. **Metric Views**: Multi-statement CREATE VIEW (all views in one call)
2. **Dashboards**: Template-driven spec generation (fewer LLM reasoning iterations)
3. **Cross-step**: Cache `erd_parsed.yaml` and `semantic_model.yaml` across runs (skip vision on re-run)
4. **LLM model routing**: Use faster model for mechanical tasks (DDL generation) if available
5. **Token budget**: Monitor output token usage; switch to `max_tokens=32768` if DDL is truncated
