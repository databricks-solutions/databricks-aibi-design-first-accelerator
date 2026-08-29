# Create Data Layer

## Role

You are a senior Databricks data architect, dimensional modeler, and synthetic-data engineer.

Generate governed Unity Catalog Delta tables from the **ERD image** when greenfield is enabled. Generate realistic, relationally consistent synthetic data using **dbldatagen** with domain-specific values.

The resulting data layer must be: structurally faithful to the ERD, semantically coherent, relationally valid, analytically usable, deterministic in schema interpretation, and safe for downstream Metric Views, dashboards, and Genie.

**Correctness takes precedence over completion. Never invent schema elements, keys, relationships, or business semantics merely to make generation succeed.**

---

## ENFORCEMENT HEADER

<!-- @enforcement
  pattern: notebook_execution
  templates_required:
    - ddl_notebook (templates.ddl_notebook from accelerator.yaml)
    - dbldatagen_notebook (templates.dbldatagen_notebook from accelerator.yaml)
  inline_code_forbidden: true
  ddl_pattern: CREATE TABLE IF NOT EXISTS (NEVER CREATE OR REPLACE TABLE)
  gates:
    - id: erd_parsed_exists
      after_step: 2
      check: "file_exists('{OUTPUT_FOLDER}/erd_parsed.yaml') AND contains 'tables:' array"
    - id: semantic_model_exists
      after_step: 3
      check: "file_exists('{OUTPUT_FOLDER}/semantic_model.yaml')"
    - id: ddl_notebook_executed
      after_step: 4
      check: "SHOW TABLES IN {catalog}.{schema} LIKE '%{VERSION_SUFFIX}' returns >= 1 row"
    - id: synthetic_spec_domain_check
      after_step: 5
      check: "Every CATEGORICAL/WEIGHTED_CATEGORICAL column has concrete domain values (no val_N, no single-char placeholders)"
    - id: synthetic_data_populated
      after_step: 6
      check: "SELECT COUNT(*) > 0 FROM each table"
    - id: validation_passed
      after_step: 7
      check: "file_exists('{OUTPUT_FOLDER}/data_layer_validation.yaml') AND overall_status = PASS"
-->

---

## PROHIBITED ACTIONS (this entire step)

The following actions are STRICTLY FORBIDDEN. Violating any is a pipeline failure:

1. **DO NOT execute DDL or synthetic data code directly in chat** — ALL code goes into notebooks and executes as notebooks.
2. **DO NOT use `CREATE OR REPLACE TABLE`** — triggers safety guardrail. Use `CREATE TABLE IF NOT EXISTS`.
3. **DO NOT generate notebooks from scratch** when templates exist — read template, populate placeholders, write.
4. **DO NOT skip notebook execution** by running inline code "because it's faster".
5. **DO NOT proceed past a GATE** without verifying the condition.
6. **DO NOT use `dbutils.fs`** for `/Workspace/` paths.
7. **DO NOT use `.mode("overwrite").saveAsTable()`** — use `.mode("append")` (tables created empty by DDL).
8. **DO NOT use Statement Execution API** for DDL/data gen — only for Metric View creation.
9. **DO NOT reimplement template functions** — `generate_table()`, `enforce_varchar_limits()`, `verify_before_write()`, etc. are tested and bug-free. HALT on errors, never rewrite.
10. **DO NOT skip FK replacement after `build()`** — generates identical placeholder values for ALL rows. Replace EVERY FK in EVERY child table with sampled parent keys. This is the #1 synthetic data bug.
11. **DO NOT leave business keys with 1 distinct value** — parent business keys referenced by child FKs MUST have diverse values post-build(). Without this, ALL downstream joins break.
12. **DO NOT generate categorical columns with generic values** — NEVER produce `val_1`, `val_2`, `A`, `B`, `C`, or random strings for status/type/code/category columns. Every categorical MUST have domain-meaningful values (see §5.3).
13. **DO NOT mark validation PASS if ANY FK has COUNT(DISTINCT) = 1** — indicates FK replacement was not applied.
14. **DO NOT generate line-number columns as strings** — `*_line_nbr`, `*_seq` columns MUST be sequential integers.
15. **DO NOT treat notebook execution success as data validation success** — always run Step 7.
16. **DO NOT extract auth tokens and use `requests.post()` for API calls** — triggers safety guardrail (credential exfiltration risk). Always use `w.api_client.do(method, path, body=...)` which handles auth internally.
17. **DO NOT use the default SDK timeout for vision/reasoning model calls** — the default 5-minute timeout causes `TimeoutError`. Create a dedicated client: `WorkspaceClient(config=Config(http_timeout_seconds=600))`.
18. **DO NOT use semantic/shortened column names in DOMAIN_COLS or FK_REPLACEMENTS** — ALWAYS use EXACT column names from `DESCRIBE TABLE` (e.g., `"clm_dtl_claim_type"` NOT `"claim_type"`). Wrong names are silently ignored → garbage data. Call `validate_domain_cols()` to catch mismatches.
19. **DO NOT skip `validate_domain_cols()` before `generate_table()`** — this is the determinism gate. Without it, column name mismatches produce garbage data non-deterministically across runs.
20. **DO NOT write unquoted numeric values for STRING/VARCHAR columns in `synthetic_data_spec.yaml`** — YAML parses `99213` as integer, creating mixed-type lists. The LLM HAS the DDL types from ERD; use them: ALL values for VARCHAR/STRING columns MUST be quoted strings (`"99213"` not `99213`). See §5.4 GATE 5.2.
21. **DO NOT write date-only strings for TIMESTAMP columns** — `"2020-01-01"` causes ValueError in dbldatagen. Always use full datetime: `"2020-01-01 00:00:00"`. The LLM KNOWS the column is TIMESTAMP from ERD; use that information.

### Environment-Specific Rules

| Rule | Genie Code | Databricks App |
|------|-----------|----------------|
| DML (DELETE/TRUNCATE/UPDATE) | BLOCKED — ensure correctness BEFORE write | ALLOWED — use TRUNCATE + re-append to fix |
| Recovery from bad data | Report as `DATA_QUALITY_WARNING`, proceed | TRUNCATE and regenerate |
| Safety guardrail trigger | HALT immediately, report block | N/A (no guardrails) |
| `.mode("overwrite")` | BLOCKED | ALSO PROHIBITED (template uses append) |

### HARD STOP RULE

If the agent encounters a safety guardrail, tool limitation, or API timeout: STOP immediately, report the exact error, DO NOT attempt alternatives. The prescribed approach IS the approach.

---

## Execution Conditions

Run only when `data_source.type` is `erd` or `erd_and_live_schema` AND `data_source.greenfield.enabled: true`.

Skip entirely for `data_source.type: live_schema` (brownfield uses existing data).

---

## State & Checkpoint Contract

Uses **artifact-as-state** checkpointing (see `07_state_contract.md`). Before each phase, check if output artifact exists. If valid → skip. If missing/corrupt → execute.

| Phase | Artifact | Skip When |
|-------|----------|-----------|
| load_config | accelerator.yaml | Always re-read (stateless) |
| parse_erd | erd_parsed.yaml | file exists + tables array non-empty, OR image hash matches prior version (cache hit) |
| build_semantic_model | semantic_model.yaml | file exists |
| generate_ddl | Tables in catalog | SHOW TABLES returns expected count |
| generate_synthetic_data | Row count > 0 | SELECT COUNT(*) > 0 per table |
| validate_data | data_layer_validation.yaml | file exists + overall_status field |

**Rules:** Never re-execute a phase whose artifact exists and is valid. After each completed phase, update `run_context.yaml` by appending to `phases_completed`.

---

# Step 1: Load Configuration

1. Read `accelerator.yaml`
2. Apply name suffix/version rules from `00_master_prompt.md` Step 0
3. Read `data_source.erd.image` (the PNG/JPG — authoritative schema source)
4. Load `templates.ddl_notebook` and `templates.dbldatagen_notebook`
5. Load `data_source.greenfield.volume` for row count targets
6. Load KPI/use-case specification (influences realistic values and coverage, NEVER alters schema)

---

# Step 2: Parse ERD Image into Canonical Schema Contract

> **MANDATORY: Vision model required.** Use `llm.steps.parse_erd.model`.
> For reasoning models (e.g., `databricks-gpt-5-5`): set `max_tokens >= 32000`.

### Vision Model Call Pattern (MANDATORY)

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config

# Standard client for normal SDK calls
w = WorkspaceClient()

# Long-timeout client for vision/reasoning model calls (REQUIRED)
# Default SDK timeout = 5 min → TimeoutError on reasoning models.
w_llm = WorkspaceClient(config=Config(http_timeout_seconds=600))

# Call the serving endpoint via SDK (NEVER via raw requests + extracted token):
response = w_llm.api_client.do(
    "POST",
    "/serving-endpoints/<model-name>/invocations",
    body={
        "messages": [
            {"role": "system", "content": "..."},
            {"role": "user", "content": [
                {"type": "text", "text": "..."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ]},
        ],
        "max_tokens": 32000,
        "temperature": 1,
    }
)
content = response["choices"][0]["message"]["content"]
```

**Rules:**
- ALWAYS use `w_llm.api_client.do()` (SDK handles auth via runtime token)
- NEVER use `requests.post()` with manually extracted tokens (blocked by safety guardrail)
- Use the MAXIMUM resolution supported by the model (do NOT downscale). Convert to JPEG quality 90 for payload efficiency, but preserve full pixel dimensions. For `databricks-gpt-5-5` the API accepts images up to 20MB base64-encoded — send at original resolution to ensure small-font annotations (e.g., DECIMAL(28,2)) are fully legible. Only resize if the base64 payload exceeds 20MB.
- Reasoning models consume tokens for "thinking" — `max_tokens=32000` ensures enough budget

### ERD Image Cache (skip vision call when image unchanged)

The vision model call is expensive (3-7 minutes, ~20K tokens for reasoning models). Since the ERD image is an **input** (not a generated artifact), its parsed output can be cached across versions when the image has not changed.

This works identically in **Genie Code** and **Databricks App** mode — both use the Databricks SDK (`WorkspaceClient`) for all file operations.

**Cache algorithm (pseudocode):**

```text
1. Read ERD image bytes via SDK workspace export
   erd_hash = hashlib.sha256(erd_bytes).hexdigest()

2. List prior version folders under {OUTPUT_BASE}/ (newest first):
   For each v{N} where N < CURRENT_VERSION:
     - Try loading {OUTPUT_BASE}/v{N}/erd_parsed.yaml via SDK workspace export
     - Parse YAML content and read "_erd_image_hash" field
     - If _erd_image_hash == erd_hash AND tables array is non-empty:
       → CACHE HIT: use this parsed content for the current version
       → Log "✓ ERD cache HIT (vN) — skipping vision model call"
       → Break
     - If file missing, corrupt YAML, or hash mismatch: continue to next

3. If no cache hit:
   → CACHE MISS: call vision model (full parse)
   → Inject "_erd_image_hash: {erd_hash}" as a top-level field in the output

4. Save erd_parsed.yaml to CURRENT version's OUTPUT_FOLDER via SDK workspace import
   (always — even on cache hit, so the current version is self-contained)
```

**Environment compatibility:**

Both environments use `WorkspaceClient()` with their respective authentication (runtime token for Genie Code, service principal token for App). The SDK methods used are:
- `workspace.export()` to read files (ERD image and prior YAML)
- `workspace.list()` to enumerate version folders
- `workspace.import_()` to save the YAML to the current version folder
- `hashlib.sha256()` for hash computation (stdlib, no dependencies)

No environment-specific branching is needed. The algorithm is identical in both modes.

**Rules:**
- The `_erd_image_hash` field is metadata only — downstream stages MUST ignore it
- This is the ONLY permitted exception to version isolation: reusing a prior version's `erd_parsed.yaml` when the source image is byte-identical
- If the image changed even 1 byte → full vision model re-parse (no partial reuse)
- Always save to the CURRENT version's output folder regardless of cache hit
- On cache hit: still validate the YAML parses correctly (tables array non-empty)
- Works identically in Genie Code and Databricks App — both use the same SDK calls

## Authoritative Input Rule

The ERD image is the **sole authoritative schema input**. NEVER derive schema from previous outputs, existing tables, or DDL notebooks.

## 2.1 Extract Observed Structure

Read `{data_source.erd.image}` with vision model. Extract every visible table, column, datatype, PK/FK marker, relationship line, direction, and cardinality. Normalize all names to `^[a-z0-9_]+$`.

### Data Type Completeness (CRITICAL — DETERMINISM RULE)

**The vision model MUST return COMPLETE data type definitions including precision, scale, and length.** Truncated types (e.g., `decimal(28` instead of `decimal(28,2)`) produce invalid DDL that fails at table creation.

**The LLM system prompt for ERD parsing MUST include this instruction:**

```text
For EVERY column, return the COMPLETE data type exactly as shown in the ERD image:
- decimal/numeric types: MUST include both precision AND scale in parentheses — e.g., decimal(28,2), NOT decimal(28
- varchar/char types: MUST include the length — e.g., varchar(100), NOT varchar
- If precision/scale/length is partially visible or cut off, infer the most likely complete value from context
- NEVER return an unclosed parenthesis in a data type
- NEVER truncate a data type definition mid-specification
```

**Common vision model truncation errors (GATE 2.1b will catch these):**

| Truncated (WRONG) | Complete (CORRECT) |
|-------------------|--------------------|
| `decimal(28` | `decimal(28,2)` |
| `decimal(18` | `decimal(18,4)` |
| `varchar(` | `varchar(100)` |
| `numeric(10` | `numeric(10,0)` |
| `char(` | `char(1)` |

### GATE 2.1b: Data Type Validation (MANDATORY post-parse)

After the vision model returns the parsed ERD, load and run the validation utility from `{deploy_root}/framework/templates/erd_validation_utils.py`.

**Load the utility:**
```python
import importlib.util
spec = importlib.util.spec_from_file_location(
    "erd_validation_utils",
    f"{deploy_root}/framework/templates/erd_validation_utils.py"
)
erd_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(erd_utils)
```

**Run the combined validation pipeline:**
```python
# parsed_tables = the tables list from vision model YAML output
tables, report = erd_utils.validate_erd_output(parsed_tables)
assert report['status'] == 'PASS', f"ERD validation failed: {report['errors']}"
# Now safe to write erd_parsed.yaml
```

This runs on EVERY column's datatype BEFORE writing `erd_parsed.yaml`:

```python
import re

def validate_and_fix_datatypes(tables: list) -> tuple[list, list]:
    """Validate all column datatypes for completeness.
    Fixes common truncation errors. Returns (fixed_tables, fixes_applied).
    
    This is the DETERMINISTIC GATE that prevents incomplete types from
    reaching DDL generation. The vision model may truncate; this function
    guarantees completeness.
    """
    fixes = []
    
    for table in tables:
        for col in table.get('observed', {}).get('columns', []):
            dtype = col.get('datatype', '').strip()
            
            # Check 1: Unclosed parenthesis
            if '(' in dtype and ')' not in dtype:
                # Fix: close the parenthesis with reasonable defaults
                if dtype.lower().startswith('decimal') or dtype.lower().startswith('numeric'):
                    # decimal(28 → decimal(28,2) [financial default]
                    match = re.match(r'(decimal|numeric)\((\d+)', dtype, re.IGNORECASE)
                    if match:
                        precision = int(match.group(2))
                        scale = 2 if precision > 10 else 0  # financial columns get scale=2
                        fixed = f"{match.group(1)}({precision},{scale})"
                        fixes.append(f"{table['name']}.{col['name']}: '{dtype}' → '{fixed}'")
                        col['datatype'] = fixed
                elif dtype.lower().startswith('varchar') or dtype.lower().startswith('char'):
                    match = re.match(r'(var)?char\((\d*)', dtype, re.IGNORECASE)
                    if match:
                        length = match.group(2) or '255'
                        prefix = match.group(0).split('(')[0]
                        fixed = f"{prefix}({length})"
                        fixes.append(f"{table['name']}.{col['name']}: '{dtype}' → '{fixed}'")
                        col['datatype'] = fixed
                else:
                    # Generic: just close it
                    fixed = dtype + ')'
                    fixes.append(f"{table['name']}.{col['name']}: '{dtype}' → '{fixed}'")
                    col['datatype'] = fixed
            
            # Check 2: decimal with precision but no scale
            decimal_no_scale = re.match(r'(decimal|numeric)\((\d+)\)$', dtype, re.IGNORECASE)
            if decimal_no_scale:
                precision = int(decimal_no_scale.group(2))
                if precision > 4:  # likely financial, needs scale
                    fixed = f"{decimal_no_scale.group(1)}({precision},2)"
                    fixes.append(f"{table['name']}.{col['name']}: '{dtype}' → '{fixed}' (added scale)")
                    col['datatype'] = fixed
            
            # Check 3: Empty datatype
            if not dtype:
                col['datatype'] = 'string'  # safe default
                fixes.append(f"{table['name']}.{col['name']}: empty → 'string'")
    
    if fixes:
        print(f"⚠️  Data type validation: {len(fixes)} fix(es) applied:")
        for f in fixes:
            print(f"    {f}")
    else:
        print("✓ Data type validation: all types complete")
    
    return tables, fixes
```

**This function MUST be called after vision model parsing and BEFORE writing `erd_parsed.yaml`.** It converts a non-deterministic LLM output (sometimes truncated) into a deterministic, complete schema.

**Can there be zero synthetic errors?** With this validation gate:
- **Data type errors: eliminated** — truncated types are auto-fixed before DDL
- **Column name errors: eliminated** — `validate_domain_cols()` catches mismatches (Step 6)
- **FK errors: eliminated** — `validate_fk_replacements()` catches mismatches (Step 6)
- **Value errors: eliminated** — `verify_before_write()` catches generic values (Step 6)

The combination of prompt instructions + programmatic validation makes zero-error synthetic data achievable.

## 2.2 Observation vs Inference

- **OBSERVED**: explicitly visible in ERD (table/column names, PK/FK markers, relationship lines)
- **INFERRED**: derived through reasoning (fact vs dimension, grain, cardinality when unmarked)

Never present inferred as observed.

## 2.3 Confidence Classification

Every inferred item: `HIGH | MEDIUM | LOW | UNRESOLVED`

A relationship MUST NOT be created solely from column-name similarity.

## 2.4 Determine Table Grain

For every table: "One row represents ______." Infer from key structure, relationships, column semantics. If uncertain: `grain: UNRESOLVED`.

## 2.5 Canonical Schema Contract

Write `{workspace.output_folder}/erd_parsed.yaml`:

```yaml
tables:
  - name: table_name
    observed:
      columns:
        - name: column_name
          datatype: string
          nullable: unknown
          key_marker: PK | FK | NONE | UNKNOWN
    inferred:
      semantic_role: FACT | DIMENSION | BRIDGE | EVENT | SNAPSHOT | REFERENCE | UNKNOWN
      business_entity: description
      grain: one row represents ...
      primary_key:
        columns: [...]
        confidence: HIGH | MEDIUM | LOW | UNRESOLVED
      foreign_keys:
        - columns: [...]
          references_table: ...
          references_columns: [...]
          cardinality: 1:1 | 1:N | N:1 | N:M | UNKNOWN
          confidence: ...
          evidence: ...
relationships: [...]
unresolved_items: []
```

### Unresolved Items Decision Gate

Before marking UNRESOLVED, attempt inference from: (1) column naming conventions, (2) shared column names, (3) domain semantics (detail/line → header pattern), (4) KPI spec join paths. Only mark UNRESOLVED if ALL methods fail.

**HALT** if unresolved item blocks a required fact→dimension join, a PK referenced by an FK, or a KPI-referenced column. **WARN** otherwise.

## 2.6 Structural Contract Rules

Once written, `erd_parsed.yaml` is authoritative. Downstream MUST NOT invent/remove columns, change datatypes, create surrogate keys, or reinterpret the ERD.

**GATE 2.1**: `erd_parsed.yaml` exists with non-empty `tables:` array. HALT if missing.

---

# Step 3: Build Semantic/Data Model

Write `{workspace.output_folder}/semantic_model.yaml` consuming the Canonical Schema Contract.

## 3.1 Table Classification

For each table: `semantic_role` (FACT | DIMENSION | BRIDGE | EVENT | SNAPSHOT | REFERENCE), `business_entity`, `grain`.

## 3.2 Column Classification

Classify every column: PRIMARY_KEY, FOREIGN_KEY, BUSINESS_IDENTIFIER, MEASURE, CATEGORICAL_ATTRIBUTE, DESCRIPTIVE_ATTRIBUTE, DATE, TIMESTAMP, STATUS, QUANTITY, MONETARY, BOOLEAN, DERIVED, FREE_TEXT, UNKNOWN.

For measures, identify aggregation: SUM, COUNT, COUNT_DISTINCT, MIN, MAX, AVG, NON_ADDITIVE, UNKNOWN.

## 3.3 Relationship Graph & Generation Order

Construct dependency graph from PK/FK. Compute generation order (dimensions before facts). For every relationship determine join safety:

```yaml
left_grain:
right_grain:
cardinality:
fanout_risk:
```

Mark `FANOUT_RISK` when joining could multiply rows.

**GATE 3.1**: `semantic_model.yaml` exists with `generation_order`. HALT if missing.

---

# Step 4: Generate DDL Notebook

### Pre-Flight

- [ ] `erd_parsed.yaml` exists (this run)
- [ ] All HALT-level items resolved
- [ ] Every table has documented grain
- [ ] Every PK identified
- [ ] `templates.ddl_notebook` loaded

### Process

1. Create `{workspace.output_folder}/notebooks/ddl_{domain.name}.ipynb`
2. Populate from `templates.ddl_notebook`
3. Generate tables from `erd_parsed.yaml` targeting `{catalog.source.catalog}.{catalog.source.schema}`
4. Execute the notebook

### DDL Pattern (MANDATORY)

```sql
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.{table_name}{version_suffix} (
  column_definitions...
) USING DELTA
COMMENT '{table description}';
```

The DDL MUST NOT modify schema to make synthetic-data generation easier. The schema does not adapt to generation.

**GATE 4.1**: `SHOW TABLES IN {catalog}.{schema} LIKE '%{VERSION_SUFFIX}'` returns expected count. HALT if fewer.

### GATE 4.2: Schema Reconciliation (MANDATORY after DDL execution)

After GATE 4.1 passes, verify that each table's **actual schema** matches the **ERD-parsed schema**. This prevents a critical failure mode where `CREATE TABLE IF NOT EXISTS` is a no-op on tables that already exist with a different schema (from a prior interrupted run with a different ERD parse).

**Algorithm:**

```text
For each table in erd_parsed.yaml:
  1. Run DESCRIBE TABLE {catalog}.{schema}.{table_name}{version_suffix}
  2. Extract actual column names (excluding partition info/metadata rows)
  3. Extract expected column names from erd_parsed.yaml
  4. Compare: actual_cols vs expected_cols

  If MISMATCH (missing or extra columns):
    a. Check if table is EMPTY: SELECT COUNT(*) FROM table
    b. If EMPTY (count = 0):
       → DROP TABLE {catalog}.{schema}.{table_name}{version_suffix}
       → Re-run the CREATE TABLE statement for this table
       → Log: "⚠️ SCHEMA RECONCILIATION: {table} had stale schema from prior run. Dropped and recreated."
    c. If NOT EMPTY (count > 0):
       → HALT with:
         "❌ SCHEMA MISMATCH: {table} has {actual_count} columns but ERD specifies {expected_count}.
          Table contains data ({row_count} rows) — cannot safely DROP.
          Manual cleanup required: DROP TABLE {catalog}.{schema}.{table_name}{version_suffix}
          Then re-run the pipeline."

  If MATCH: continue
```

**Why this is safe:**
- Version-scoped tables (suffixed with `_v{N}`) are OWNED by this pipeline run
- Empty tables have no data to lose — they were just created by this or a prior DDL step
- Non-empty tables require manual confirmation (they may have synthetic data from a prior successful run that should not be silently destroyed)

**Why this is necessary:**
- `CREATE TABLE IF NOT EXISTS` does NOT alter existing table schemas
- The ERD vision model is non-deterministic — it may parse different column counts on different runs
- Without this gate, the synthetic data step (Step 5/6) builds specs from `erd_parsed.yaml` that reference columns that don't exist in the actual table, causing `validate_domain_cols()` to raise `AssertionError`

---

# Step 5: Build Synthetic Data Specification

Run only when `data_source.greenfield.synthetic_data: true`.

Create `{workspace.output_folder}/synthetic_data_spec.yaml` from: `erd_parsed.yaml` + `semantic_model.yaml` + KPI context + volume config.

### Column Authority Rule (CRITICAL)

The **actual table schema** (from `DESCRIBE TABLE`) is the authoritative source for which columns exist. The `erd_parsed.yaml` provides semantic context (datatypes, roles, relationships) but MUST NOT be used as the sole column list.

**Before building the synthetic data spec, for EACH table:**

```text
1. Run: DESCRIBE TABLE {catalog}.{schema}.{table_name}{version_suffix}
2. Use the returned column list as the DEFINITIVE set of columns to generate
3. Cross-reference with erd_parsed.yaml for semantic context (types, roles, FK relationships)
4. If a column exists in erd_parsed.yaml but NOT in the actual table → SKIP it (do not include in spec)
5. If a column exists in the actual table but NOT in erd_parsed.yaml → include it with type-based defaults
```

This rule prevents `validate_domain_cols()` failures caused by ERD-vs-table schema drift (which occurs when `CREATE TABLE IF NOT EXISTS` encounters a pre-existing table from a prior run).

## 5.1 Generation Philosophy

Synthetic data MUST be: **ENTITY-FIRST, RELATIONSHIP-AWARE, DOMAIN-AWARE, SEMANTICALLY COHERENT.** Not independent random columns.

### Demo-Quality Distribution Requirements (CRITICAL)

Uniform distributions produce useless dashboards (all bars same height, filters don't change values).

**Required skew patterns:**

1. **Financial measures by category** — different categories MUST have clearly different cost profiles (e.g., 100x difference between high-cost and low-cost categories)
2. **Volume by dimension** — primary values MUST have unequal row counts (e.g., top 3 get 50%, bottom 2 get 8%)
3. **Rate measures by category** — denial rates, approval rates, etc. MUST vary by dimension

Use `WEIGHTED_CATEGORICAL` for dimension columns. Vary `NUMERIC_RANGE` by category for financial columns.

## 5.2 Column Generation Specification

For every column:

```yaml
column:
datatype:
semantic_type:
generation_strategy:  # SEQUENTIAL_ID | PARENT_KEY_SAMPLE | CATEGORICAL_VALUES | WEIGHTED_CATEGORICAL | NUMERIC_RANGE | DISTRIBUTION | DATE_RANGE | TIMESTAMP_RANGE | BOOLEAN | DERIVED | FREE_TEXT | STATIC
nullable_probability:
domain:
distribution:
dependencies:
constraints:
```

## 5.3 Domain-Aware Value Generation (MANDATORY — CRITICAL)

This is the **#1 quality gate** for synthetic data. Generic values (`val_1`, `val_2`, `A`, `B`, `C`) render all downstream artifacts useless — dashboards show meaningless labels, Genie cannot answer questions about categories, filters have no semantic meaning.

### Domain Value Inference Protocol (MANDATORY for every categorical column)

For EVERY column classified as CATEGORICAL_ATTRIBUTE, STATUS, or having strategy CATEGORICAL_VALUES / WEIGHTED_CATEGORICAL, the LLM MUST execute this inference chain:

```text
Step 1: Parse column name → identify semantic concept
        (e.g., "claim_type" → type of insurance claim)

Step 2: Identify parent entity from table name
        (e.g., table "fact_claim_detail" → medical/insurance claims domain)

Step 3: Cross-reference with KPI spec terminology
        (e.g., KPI mentions "Institutional vs Professional" → use those exact terms)

Step 4: Generate 3-10 domain-realistic values using industry knowledge
        (e.g., ["Institutional", "Professional", "Pharmacy", "Dental", "Vision"])

Step 5: Assign weights reflecting real-world distribution skew
        (e.g., [0.30, 0.35, 0.15, 0.12, 0.08])
```

### Value Inference Patterns (by column name pattern)

| Column Name Contains | Semantic Concept | Example Values |
|---------------------|-----------------|----------------|
| `status`, `_sts` | Workflow state | Domain-specific states (Approved/Denied/Pending, Active/Inactive, Open/Closed) |
| `type`, `_typ` | Entity classification | Domain entity types (Institutional/Professional, Checking/Savings, Inbound/Outbound) |
| `category`, `_cat` | Grouping/segment | Business-meaningful segments |
| `code` (short VARCHAR) | Industry standard code | Format-correct codes (ICD-10, CPT, SIC, ZIP patterns) |
| `place`, `location`, `site` | Physical/logical location | Domain-appropriate location types |
| `flag`, `_ind` | Binary indicator | Y/N or domain-specific binary (Clean/Not Clean) |
| `region`, `state`, `country` | Geography | Real geography codes/names |
| `channel`, `source` | Origin/method | Business channels (Web/Phone/In-Person, Direct/Broker) |
| `priority`, `severity`, `level` | Ordinal ranking | Domain-appropriate levels (Critical/High/Medium/Low) |
| `gender`, `sex` | Demographics | M/F/U or Male/Female/Unknown |
| `plan`, `product`, `lob` | Business product | Actual product/plan types from the domain |

### PROHIBITED Value Patterns (GATE 5.1 will reject these)

```yaml
# ALL of these are FORBIDDEN in synthetic_data_spec.yaml:
values: ["val_1", "val_2", "val_3"]          # Generic numbered placeholders
values: ["A", "B", "C", "D"]                  # Single-character placeholders
values: ["type1", "type2", "type3"]           # Generic typed placeholders
values: ["cat_1", "cat_2", "cat_3"]           # Generic prefixed placeholders
values: ["status_a", "status_b"]              # Generic status placeholders
template: "\w\w\w\w"                       # Random Lorem Ipsum text
```

```yaml
# CORRECT — domain-meaningful values:
values: ["APPROVED", "DENIED", "PENDING", "IN_REVIEW"]
values: ["Institutional", "Professional", "Pharmacy", "Dental", "Vision"]
values: ["11", "21", "22", "23", "31", "32", "41"]  # CMS Place of Service codes
values: ["COMMERCIAL", "MEDICARE", "MEDICAID", "TRICARE"]
```

### GATE 5.1: Domain Value Validation

After writing `synthetic_data_spec.yaml`, scan ALL columns with strategy `CATEGORICAL_VALUES` or `WEIGHTED_CATEGORICAL`. The spec FAILS if ANY column has:
- Values matching pattern `val_\d+`, `[A-Z]` single chars, `type\d+`, `cat_\d+`, `status_[a-z]`
- Fewer than 3 values for a column with cardinality > 2
- Values that are clearly not domain-relevant (column is `claim_type` but values are `["foo", "bar", "baz"]`)

If GATE 5.1 fails: regenerate the spec for failing columns using the Domain Value Inference Protocol above. Do NOT proceed to Step 6 with generic values.

## 5.4 YAML Type Safety (DETERMINISM RULE — CRITICAL)

**Root Cause:** YAML auto-parses unquoted numeric-looking values as integers. A procedure code `99213` written without quotes becomes `int(99213)` in Python, while `D0120` stays `str("D0120")`. When both appear in the same domain values list for a VARCHAR column, you get a mixed-type list that causes `NumberFormatException` at Spark write time.

**The LLM generating `synthetic_data_spec.yaml` already HAS the column types from `erd_parsed.yaml`.** It MUST use them to ensure proper YAML output:

### Rule: Match YAML Value Format to Column DDL Type

| Column DDL Type | YAML Value Format | Example |
|----------------|------------------|--------|
| VARCHAR(N), STRING, CHAR(N) | ALL values MUST be quoted strings | `values: ["99213", "D0120", "99396"]` |
| TIMESTAMP, TIMESTAMP_NTZ | Full datetime with time component | `begin: "2020-01-01 00:00:00"` |
| DATE | Date-only string (YYYY-MM-DD) | `begin: "2020-01-01"` |
| BIGINT, INT, INTEGER | Unquoted integers | `values: [1, 2, 3]` |
| DOUBLE, FLOAT, DECIMAL | Unquoted decimals | `values: [10.5, 20.3]` |
| BOOLEAN | Unquoted booleans | `values: [true, false]` |

### PROHIBITED (causes mixed-type lists):

```yaml
# WRONG — procedure codes without quotes (YAML parses 99213 as int):
values: [99213, D0120, 99396, J0585]

# WRONG — timestamps as date-only (causes ValueError in dbldatagen):
begin: 2020-01-01
end: 2024-12-31
```

### CORRECT:

```yaml
# CORRECT — ALL values quoted for VARCHAR column:
values: ["99213", "D0120", "99396", "J0585"]

# CORRECT — full datetime for TIMESTAMP column:
begin: "2020-01-01 00:00:00"
end: "2024-12-31 23:59:59"
```

### GATE 5.2: YAML Type Safety Validation (MANDATORY before writing spec)

After constructing the spec dict and BEFORE serializing to YAML, apply `coerce_spec_values_for_yaml(spec_tables, erd_tables)`. This function:

1. Builds a type lookup from ERD parse output (`{table: {col: ddl_type}}`)
2. For each column with domain values:
   - String columns (`char`, `string` in DDL type) → `str(v)` for ALL values
   - Timestamp columns → append ` 00:00:00` to any date-only value (10-char YYYY-MM-DD)
   - Integer columns → `int(v)` for all values
   - Float/decimal columns → `float(v)` for all values
3. Returns the coerced spec (safe for YAML serialization)

**Implementation pattern (in synthetic data spec generation cell):**

```python
# After LLM generates spec_tables, BEFORE yaml.dump:
for table in spec_tables:
    tname = table['name']
    col_types = type_map.get(tname, {})  # from erd_parsed.yaml
    for col in table.get('columns', []):
        cname = col.get('column', '')
        ddl_type = col_types.get(cname, '').lower()
        values = col.get('domain', {}).get('values', [])
        if not values:
            continue
        if any(t in ddl_type for t in ('char', 'string')):
            col['domain']['values'] = [str(v) for v in values]
        elif 'timestamp' in ddl_type:
            col['domain']['values'] = [
                f"{str(v)} 00:00:00" if len(str(v)) == 10 else str(v)
                for v in values
            ]
```

This ensures the YAML file contains correctly-typed values from the moment it is written. The runtime coercion in `generate_table()` is a SAFETY NET only — it should never need to fire if this gate runs.

## 5.5 Cross-Column Dependencies

Identify and store semantic constraints:

```yaml
semantic_constraints:
  - expression: "start_date <= end_date"
    type: TEMPORAL
    confidence: HIGH
  - expression: "child.FK IN parent.PK"
    type: STRUCTURAL
    confidence: HIGH
```

Types: STRUCTURAL (PK/FK, uniqueness), TEMPORAL (date ordering), SEMANTIC (cross-column business rules), STATISTICAL (distributions).

## 5.5 Volume Targets

Map `data_source.greenfield.volume` to row counts:

```yaml
volume_targets:
  low:    { dimension: 100-500, fact: 500-5000, detail_fact: 2000-10000 }
  medium: { dimension: 1000-5000, fact: 10000-50000, detail_fact: 50000-200000 }
  high:   { dimension: 10000-50000, fact: 100000-500000, detail_fact: 500000-2000000 }
```

---

# Step 6: Generate Synthetic Data Notebook

### Pre-Flight

- [ ] `synthetic_data_spec.yaml` exists with FK strategies for every relationship
- [ ] GATE 5.1 passed (domain values validated)
- [ ] Generation order computed from dependency graph
- [ ] `generate_table()` will be used for every table (domain-first pattern)
- [ ] ANSI mode will be disabled in setup cell
- [ ] `discover_tables()` will be used for version-aware references
- [ ] FK columns will sample from parent key domains

### Process

1. Create `{workspace.output_folder}/notebooks/synthetic_data_{domain.name}.ipynb`
2. Populate from `templates.dbldatagen_notebook`
3. For EACH table (dependency order), add generation cell using `generate_table()` with `DOMAIN_COLS` dict
4. Execute the notebook
5. Verify execution completed without errors

### Notebook Execution

| Environment | Method |
|------------|--------|
| Genie Code | `openAsset` + `continueMessage` (preferred) OR SDK `w.jobs.submit()` OR `executeCode` (last resort, only after notebook artifact saved) |
| Databricks App | SDK `w.jobs.submit()` with `NotebookTask` |

### MANDATORY Write Pattern

```python
df.write.format("delta").mode("append").saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")
```

NEVER `.mode("overwrite")`. Tables are empty from DDL; append = initial load.

### MANDATORY Python 3.11 Compatibility

Serverless compute runs Python 3.11 which PROHIBITS backslashes inside f-string `{}` expressions:

```python
# ILLEGAL — causes SyntaxError:
f"{'\n'.join(items)}"        # backslash in f-string expression
f"{val.replace('\n', '')}"   # backslash in f-string expression

# LEGAL — use a variable instead:
nl = '\n'
f"{nl.join(items)}"
# Or assign first:
joined = '\n'.join(items)
f"{joined}"
```

This applies to ALL generated notebook code. Violation = `SyntaxError` at runtime.

---

## 6.1 Foreign Key Replacement (MANDATORY for every child table)

`generate_table()` handles FK replacement automatically via the `fk_replacements` parameter.
It samples actual parent keys and distributes them uniformly across child rows.

### Usage:

```python
FK_REPLACEMENTS = {
    "clm_member_sk": (TABLES["dim_member"], "member_sk"),
    "clm_provider_sk": (TABLES["dim_provider"], "provider_sk"),
}

df = generate_table(table_name, rows=5000,
    domain_cols=DOMAIN_COLS, pk_cols=["claim_id"],
    fk_replacements=FK_REPLACEMENTS)
```

`generate_table()` will:
1. Build the DataGenerator with domain values + type-appropriate random data
2. After `build()`: sample parent PKs and replace FK columns
3. After `build()`: ensure PK columns have unique sequential values

### Manual FK Pattern (if NOT using `generate_table()`):

```python
from pyspark.sql import functions as F
from pyspark.sql.window import Window

w = Window.orderBy(F.monotonically_increasing_id())
df = df.withColumn("_row_num", F.row_number().over(w))

parent_pks = [row[0] for row in
    spark.table(f"{CATALOG}.{SCHEMA}.{TABLES['parent_logical']}").select("pk_col").distinct().collect()]

df = df.drop("fk_col").withColumn("fk_col",
    F.element_at(
        F.array([F.lit(v) for v in parent_pks]),
        (F.col("_row_num") % len(parent_pks) + 1).cast("int")
    ))
df = df.drop("_row_num")
```

### Line Number / Sequence Columns

Columns named `*_line_nbr`, `*_seq` → sequential integers, NOT strings:

```python
df = df.drop("line_nbr_col").withColumn("line_nbr_col",
    (F.row_number().over(Window.orderBy(F.monotonically_increasing_id())) % max_lines + 1).cast("int"))
```

## 6.2 Domain Value Specification (MANDATORY — Domain-First Pattern)

The LLM defines ALL categorical/analytical columns upfront in a `DOMAIN_COLS` dict.
`generate_table()` handles everything in one pass — no separate "override" step needed.

### CRITICAL: Column Name Source (DETERMINISM RULE)

**Column names in `DOMAIN_COLS` and `FK_REPLACEMENTS` MUST come from `DESCRIBE TABLE` output — NEVER from memory, semantic inference, or the KPI spec.**

The LLM MUST follow this exact sequence for every table:

```text
1. Run: DESCRIBE TABLE `{catalog}`.`{schema}`.`{table_name}` → get exact column names
2. Identify which columns are categorical (from semantic_model.yaml classification)
3. Use the EXACT column name from DESCRIBE (e.g., "clm_dtl_claim_type", NOT "claim_type")
4. Call validate_domain_cols() to catch any remaining mismatches
```

**Why this matters:** If the DOMAIN_COLS key is `"claim_type"` but the actual column is `"clm_dtl_claim_type"`, the domain values are silently skipped and the column gets random garbage. The `validate_domain_cols()` function catches this, but the LLM should get it right in the first place.

### Correct Pattern (MANDATORY):

```python
table_name = TABLES["fact_claim_detail"]

# Step 1: Get ACTUAL column names from DDL (source of truth)
col_types = get_table_col_types(table_name)
print(f"Columns in {table_name}: {list(col_types.keys())}")

# Step 2: Define DOMAIN_COLS using EXACT column names from Step 1
# (NOT semantic names like "claim_type" — use the actual "clm_dtl_claim_type")
DOMAIN_COLS = {
    "clm_dtl_claim_type": (["Institutional", "Professional", "Pharmacy", "Dental", "Vision"],
                            [0.30, 0.35, 0.15, 0.12, 0.08]),
    "clm_dtl_line_status": (["Paid", "Denied", "Pending", "Adjusted"],
                             [0.65, 0.20, 0.10, 0.05]),
    "clm_dtl_place_of_service": (["Office", "Inpatient", "Outpatient", "Emergency", "Lab"],
                                  [0.35, 0.15, 0.25, 0.10, 0.15]),
}

# Step 3: Validate (catches any remaining mismatches — RAISES on failure)
DOMAIN_COLS = validate_domain_cols(table_name, DOMAIN_COLS)

# Step 4: Define FK replacements using EXACT column names
FK_REPLACEMENTS = {
    "clm_dtl_member_sk": (TABLES["dim_member"], "member_sk"),
    "clm_dtl_provider_sk": (TABLES["dim_provider"], "provider_sk"),
}
FK_REPLACEMENTS = validate_fk_replacements(table_name, FK_REPLACEMENTS)

# Step 5: Generate + validate + write
df = generate_table(table_name, rows=5000,
    domain_cols=DOMAIN_COLS, pk_cols=["clm_dtl_claim_id"],
    fk_replacements=FK_REPLACEMENTS)
df = enforce_varchar_limits(df, table_name)
verify_before_write(df, table_name,
    pk_cols=["clm_dtl_claim_id"],
    fk_cols=list(FK_REPLACEMENTS.keys()),
    categorical_cols=list(DOMAIN_COLS.keys()))
df.write.format("delta").mode("append").saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")
```

### PROHIBITED Column Name Patterns:

```python
# ❌ WRONG — semantic/shortened names (will be silently ignored):
DOMAIN_COLS = {
    "claim_type": ...,       # Actual column is "clm_dtl_claim_type"
    "line_status": ...,      # Actual column is "clm_dtl_line_status"
    "member_sk": ...,        # Actual column is "clm_dtl_member_sk"
}

# ✓ CORRECT — exact names from DESCRIBE TABLE:
DOMAIN_COLS = {
    "clm_dtl_claim_type": ...,
    "clm_dtl_line_status": ...,
}
```

**Every column in `synthetic_data_spec.yaml` with `CATEGORICAL_VALUES` or `WEIGHTED_CATEGORICAL` strategy MUST appear in the `DOMAIN_COLS` dict, using the EXACT column name from `DESCRIBE TABLE`.**

## 6.3 Spark Configuration

In setup cell, BEFORE any `dg.DataGenerator` call:

```python
spark.conf.set("spark.sql.ansi.enabled", "false")
```

## 6.4 Template Functions (DO NOT REIMPLEMENT)

| Function | Purpose |
|----------|---------|
| `discover_tables()` | Finds versioned tables, returns `{logical: versioned}` mapping |
| `get_table_col_types(table_name)` | Reads DDL column types from catalog (preserves VARCHAR(N)) — **USE THIS to get exact column names before building DOMAIN_COLS** |
| `validate_domain_cols(table_name, domain_cols)` | **DETERMINISM GATE**: Asserts all DOMAIN_COLS keys exist in table schema. RAISES with available column list if any don't match. Auto-corrects case. Returns corrected dict. **MUST be called before `generate_table()`** |
| `validate_fk_replacements(table_name, fk_replacements)` | Same as above for FK columns. Returns corrected dict |
| `generate_table(table, rows, domain_cols, pk_cols, fk_replacements, date_range)` | One-pass generation: domain cols → values, bulk cols → type loop, FK replacement + PK uniqueness |
| `spark_type_for(type_str)` | Maps DDL type string to PySpark type |
| `enforce_varchar_limits(df, table)` | Truncates overlong values — call LAST before write |
| `verify_before_write(df, table, pk_cols, fk_cols, categorical_cols)` | Pre-write gate: PK unique, FK diverse, no generic values |
| `extract_max_length(type_str)` | Returns max length for VARCHAR/CHAR (0 for plain string) |

### Mandatory Call Order (per table):

```text
1. get_table_col_types(table_name)     → discover exact column names
2. validate_domain_cols(table, DOMAIN_COLS)  → assert all keys match (RAISES on mismatch)
3. validate_fk_replacements(table, FK_REPLACEMENTS) → assert FK keys match
4. generate_table(...)                  → build data
5. enforce_varchar_limits(df, table)    → truncate
6. verify_before_write(...)             → final quality gate
7. df.write...                          → persist
```

Skipping steps 1-3 produces non-deterministic output (garbage data on some runs).

**GATE 6.1**: ALL tables have rows > 0. HALT with `SYNTHETIC_GENERATION_ERROR` if any table empty.

---

# Step 7: Integrity Validation

Synthetic-data generation is NOT successful because the notebook executed. Run deterministic validation.

### BATCH VALIDATION (combine into 2-3 SQL calls)

```sql
-- IMPORTANT: Databricks SQL Compatibility Notes:
-- • Do NOT use INFORMATION_SCHEMA.TABLES.table_rows (column does not exist in Databricks)
-- • Do NOT use INFORMATION_SCHEMA.TABLES.data_length or avg_row_length
-- • Use SELECT COUNT(*) FROM <table> for row counts
-- • Use DESCRIBE DETAIL <table> for file-level metadata (numFiles, sizeInBytes)
--
-- BATCH 1: Row counts + PK uniqueness for ALL tables
SELECT '{table_a}' t, COUNT(*) rows, COUNT(DISTINCT {pk}) pk_distinct,
       COUNT(*) - COUNT(DISTINCT {pk}) pk_dups
FROM {catalog}.{schema}.{table_a}
UNION ALL ...

-- BATCH 2: FK orphans + FK diversity
SELECT '{child}.{fk}' col, 'orphan_count' chk, COUNT(*) val
FROM {child} c LEFT ANTI JOIN {parent} p ON c.{fk} = p.{pk}
UNION ALL
SELECT '{child}.{fk}', 'distinct_vals', COUNT(DISTINCT {fk}) FROM {child}
UNION ALL ...

-- BATCH 3: Join stability (N:1 must NOT multiply rows)
SELECT '{join_name}' j,
  (SELECT COUNT(*) FROM {child}) before_rows,
  (SELECT COUNT(*) FROM {child} f JOIN {parent} d ON f.{fk} = d.{pk}) after_rows
UNION ALL ...
```

### Validation Matrix

| Check | Expected | Fail Code |
|-------|----------|-----------|
| 7.1 Schema: all tables exist, correct columns/types | Match DDL | `SCHEMA_VALIDATION_FAILURE` |
| 7.2 Row counts > 0 for all tables | rows > 0 | `EMPTY_TABLE_FAILURE` |
| 7.3 PK uniqueness (composite: CONCAT all key cols) | COUNT = COUNT(DISTINCT) | `PRIMARY_KEY_INTEGRITY_FAILURE` |
| 7.4 FK orphan count | 0 (unless nullable FK allowed) | `FOREIGN_KEY_INTEGRITY_FAILURE` |
| 7.5 FK diversity | COUNT(DISTINCT fk) > 1 | `FK_DIVERSITY_FAILURE` |
| 7.6 Business key diversity in parents | distinct_vals ≈ total_rows | `BUSINESS_KEY_DIVERSITY_FAILURE` |
| 7.7 Join cardinality (N:1 joins) | after_rows <= before_rows | `JOIN_CARDINALITY_FAILURE` |
| 7.8 Semantic constraints (dates, derivations) | Per spec | `SEMANTIC_DATA_ERROR` |
| 7.9 Analytical completeness | No NULL-only, no single-value categoricals | `ANALYTICAL_COMPLETENESS_FAILURE` |
| 7.10 Domain value check | No `val_\d+` in categorical columns | `DOMAIN_VALUE_FAILURE` |

**CRITICAL**: Do NOT mark `overall_status: PASS` if ANY join produces fanout or ANY FK has diversity = 1. These block ALL downstream stages.

---

# Step 8: Validation Report

Write `{workspace.output_folder}/data_layer_validation.yaml`:

```yaml
overall_status: PASS | FAIL
schema: { tables_expected: N, tables_created: N, missing: [], unexpected: [] }
primary_keys: { tested: N, failures: [] }
foreign_keys: { tested: N, orphan_counts: {}, diversity: {}, failures: [] }
join_stability: { tested: N, fanout_failures: [] }
semantic_constraints: { tested: N, failures: [] }
domain_values: { columns_checked: N, generic_value_failures: [] }
data_quality: { null_violations: [], generic_fallback_columns: [] }
```

**GATE 7.1**: `data_layer_validation.yaml` exists with `overall_status: PASS`. HALT if FAIL.

---

# Step 9: Final Summary

| Category | Result |
|----------|--------|
| ERD tables parsed | count |
| Tables created | count |
| Facts/Events | count |
| Dimensions/Reference | count |
| PK validations | PASS/FAIL |
| FK validations | PASS/FAIL |
| FK diversity | PASS/FAIL |
| Domain values | PASS/FAIL |
| Join stability | PASS/FAIL |
| Overall | PASS/FAIL |

---

# Versioning Rules

Use `VERSION_SUFFIX` from `config.version_suffix`. Reference tables via `discover_tables()` → `TABLES["logical_name"]`. Never hardcode versionless names.

---

# Datatype Rules

| Type | Rule |
|------|------|
| PK/FK/IDs | Use datatype from `get_table_col_types()`. Never force StringType for numeric IDs. |
| DateType | `begin="YYYY-MM-DD"`, `end="YYYY-MM-DD"` |
| TimestampType | `begin="YYYY-MM-DD HH:MM:SS"` (date-only PROHIBITED). Pass `date_range` tuple to `generate_table()`. |
| DECIMAL/FLOAT | Numeric values and ranges. Never formatted currency strings. |
| BOOLEAN | Use `BooleanType()` without explicit `values=[True,False]`. |

### dbldatagen Template Syntax on Serverless (Spark Connect)

`template=` does NOT reliably generate unique values on serverless. Backslash-digit escapes are literal.

For **business keys / FK targets** (uniqueness required): use `F.row_number()` over a Window:

```python
w = Window.orderBy(F.monotonically_increasing_id())  # ordering seed only
df = df.withColumn("_row_num", F.row_number().over(w))
df = df.drop("business_key").withColumn("business_key",
    F.concat(F.lit("PREFIX-"), F.lpad(F.col("_row_num").cast("string"), 7, "0")))
df = df.drop("_row_num")
```

For **non-key descriptive columns**: `template=` acceptable (non-unique values OK).

**Rule: Use `monotonically_increasing_id()` ONLY as a Window ordering seed. NEVER in expressions requiring sequential/uniform values.**

---

# Pre-Write Verification (MANDATORY before every `.write`)

```python
# PK unique:
assert df.select("pk_col").distinct().count() == df.count(), "PK not unique!"
# Business key unique (if FK target):
assert df.select("business_key").distinct().count() == df.count(), "Business key not unique!"
# FK replaced:
assert df.select("fk_col").distinct().count() > 1, "FK replacement not applied!"
```

If verification fails: fix DataFrame in memory, re-verify, THEN write. Never write first and fix later.

---

# Failure Classification

| Code | Meaning |
|------|---------|
| `ERD_EXTRACTION_ERROR` | Vision model failed to parse ERD |
| `SCHEMA_CONTRACT_ERROR` | Contract violation in downstream step |
| `GRAIN_INFERENCE_ERROR` | Cannot determine table grain |
| `RELATIONSHIP_ERROR` | Cannot establish required relationship |
| `DDL_GENERATION_ERROR` | DDL notebook execution failed |
| `DBLDATAGEN_API_ERROR` | dbldatagen API misuse |
| `TYPE_SAFETY_ERROR` | Datatype mismatch |
| `SYNTHETIC_GENERATION_ERROR` | Data generation notebook failed |
| `DOMAIN_VALUE_FAILURE` | Generic/placeholder values in categorical columns |
| `PRIMARY_KEY_INTEGRITY_ERROR` | PK not unique |
| `FOREIGN_KEY_INTEGRITY_ERROR` | FK orphans exist |
| `FK_DIVERSITY_FAILURE` | FK column has only 1 distinct value |
| `JOIN_FANOUT_ERROR` | N:1 join produces row multiplication |
| `WORKSPACE_IO_ERROR` | File write/read failure |

For any failure: report Observed problem, Root cause, Evidence, Corrective action, Affected downstream.

---

# Pipeline Halt Rules

HALT with `❌ EXECUTION HALTED` when: ERD unreadable, vision model unavailable, required FK unresolvable, DDL execution fails, dbldatagen type conflicts, PK/FK validation fails, join fanout occurs, domain values are generic/placeholder.

---

# Non-Negotiable Rules

1. ERD image is authoritative schema input.
2. Never reuse previous generated artifacts as schema evidence.
3. Unknown is better than invented.
4. Every table has explicitly documented grain.
5. Never create relationships from column-name similarity alone.
6. Never invent columns/keys to make generation easier.
7. Generate parents before dependents.
8. Foreign keys MUST reuse parent key domains.
9. Never independently random-generate both sides of PK/FK.
10. Every DDL column gets exactly one effective generation definition.
11. Use `generate_table()` with `domain_cols` + `pk_cols` + `fk_replacements` for every table.
12. Call `enforce_varchar_limits()` LAST, after FK replacement, before write.
13. Use project templates; do not recreate notebooks.
14. Use version-aware `TABLES[...]` references.
15. Disable Spark ANSI mode before dbldatagen.
16. Notebook execution ≠ data validation.
17. Structural integrity must be proven deterministically.
18. Semantic realism inferred from model/use-case, not hardcoded domain assumptions.
19. Schema does not adapt to generation; generation adapts to schema.
20. Every categorical column MUST have domain-meaningful values — NEVER generic placeholders.

---

# Output Contract

| Artifact | Location | Validation |
|----------|----------|-----------|
| erd_parsed.yaml | `{OUTPUT_FOLDER}/` | `tables:` array matches ERD count |
| semantic_model.yaml | `{OUTPUT_FOLDER}/` | Contains `generation_order:` |
| synthetic_data_spec.yaml | `{OUTPUT_FOLDER}/` | Entry for every table, GATE 5.1 passed |
| DDL notebook | `{OUTPUT_FOLDER}/notebooks/ddl_{domain}.ipynb` | All tables in catalog |
| Synthetic data notebook | `{OUTPUT_FOLDER}/notebooks/synthetic_data_{domain}.ipynb` | Executed, all tables populated |
| data_layer_validation.yaml | `{OUTPUT_FOLDER}/` | `overall_status: PASS` |

---

# Validated Learnings (from production runs)

These are confirmed failures from actual runs. Treat as mandatory guardrails.

**1. `monotonically_increasing_id()` is NOT sequential on serverless**

On 200-partition serverless, 3000 rows produce ~195 distinct values with modulo. ALWAYS use `F.row_number().over(Window.orderBy(F.monotonically_increasing_id()))` for sequential/uniform distribution.

**2. Large `F.array([F.lit(v) for v in list])` fails with EXECUTION_ERROR**

When parent PK lists exceed ~500 values, the literal array expression overflows. Use broadcast join pattern instead:

```python
parent_df = spark.table(parent).select("pk_col").distinct()
df = df.join(parent_df.withColumn("_rn", F.row_number().over(w)), ...)
```

**3. `DecimalType(p,s)` bounds generators**

`DecimalType(5,2)` max is 999.99. Bound `minValue`/`maxValue` accordingly or generation overflows.

**4. Generic `val_xx` values are the #1 data quality failure**

Prior runs produced `val_1`...`val_5` for ALL categorical columns because the LLM skipped domain inference. GATE 5.1 now catches this BEFORE data generation executes. The fix is the Domain Value Inference Protocol in §5.3.

**5. dbldatagen `template=r"PREFIX\\d{N}"` is literal on Spark Connect**

Backslash-digit sequences don't generate random digits on serverless. Use native Spark expressions for all PK/FK generation.

---

# Progress Reporting Reference

| Phase | phase_id | Key Stats |
|-------|----------|-----------|
| Load Config | `load_config` | templates_loaded |
| Parse ERD | `parse_erd` | tables, relationships, columns |
| Semantic Model | `build_semantic_model` | facts, dimensions, relationships_resolved |
| Generate DDL | `generate_ddl` | tables_created, columns_total |
| Synthetic Data | `generate_synthetic_data` | tables_populated, total_rows, fk_linked |
| Validate | `validate_data` | pk_tests, fk_tests, pk_failures, fk_failures |

Call `report_progress` with `status: "started"` before each phase, `status: "completed"` after, and `status: "update"` with `progress_pct` during long phases.
