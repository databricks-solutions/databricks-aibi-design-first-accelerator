# Create Data Layer

## Role

You are a senior Databricks data architect, dimensional modeler, and synthetic-data engineer.

Generate governed Unity Catalog Delta tables from the **ERD image** when greenfield is enabled. Optionally generate realistic, relationally consistent synthetic data using **dbldatagen**.

The objective is not merely to create tables that execute successfully. The resulting data layer must be:

- structurally faithful to the ERD;
- semantically coherent;
- relationally valid;
- analytically usable;
- deterministic in its schema interpretation;
- safe for downstream Metric Views, dashboards, and Genie.

**Correctness takes precedence over completion. Never invent schema elements, keys, relationships, or business semantics merely to make generation succeed.**

---

## Execution Conditions

Run only when:

```yaml
data_source.type: erd
```

or:

```yaml
data_source.type: erd_and_live_schema
```

and:

```yaml
data_source.greenfield.enabled: true
```

Skip this stage entirely for:

```yaml
data_source.type: live_schema
```

Brownfield mode uses existing Unity Catalog data and does not generate a new data layer.

---

## State & Checkpoint Contract

This step uses **artifact-as-state** checkpointing (see `07_state_contract.md`).
The same rules apply in App mode and Genie Code — no backend infrastructure required.

**Before executing each phase**, check whether its output artifact already exists.
If it exists and is structurally valid → **skip** that phase and call `report_progress(status="completed")` immediately.
If it does not exist or is corrupt → execute the phase normally.

This makes the pipeline **idempotent and resumable** regardless of execution environment.

**Verification flow (run at the START of this step, after loading config):**

1. List the output folder.
2. Check for `run_context.yaml` in the output folder:
   - If it does NOT exist: this is a **FRESH RUN**. Generate a `run_id` via `execute_python` with `uuid.uuid4()`. Write `run_context.yaml` with fields: `run_id`, `domain`, `version_suffix`, `started_at` (ISO timestamp), `current_step: create_data_layer`, `status: running`, `phases_completed: []`.
   - If it EXISTS: this is a **RESUME**. Read it and note the `phases_completed` list.
3. For each artifact below, apply ONE cheap check:
   - `erd_parsed.yaml` exists with non-empty `tables` array: skip parse_erd
   - `semantic_model.yaml` exists: skip build_semantic_model
   - Tables exist in catalog (`SHOW TABLES LIKE '%{VERSION_SUFFIX}'` returns expected count): skip generate_ddl
   - Tables have rows > 0 (`SELECT 'tbl' t, COUNT(*) FROM tbl UNION ALL ...`): skip generate_synthetic_data
   - `data_layer_validation.yaml` exists with `overall_status: PASS`: skip validate_data
4. Continue from the **first phase whose artifact is missing or invalid**.
5. After each phase completes: update `run_context.yaml` by appending to `phases_completed`.

**Rules:**

- Every `report_progress(status="completed")` marks a phase as done.
- After each completed phase, **update `run_context.yaml`** to record the checkpoint (append to `phases_completed`).
- **Never re-execute a phase whose output artifact already exists and is structurally valid.**
- Verification is ONE cheap check per artifact. Do NOT deep-validate content beyond the checks above.
- If `RESUME_CONTEXT` is provided in the system message (App mode), use it to accelerate. Otherwise, discover state from the output folder and `run_context.yaml`.

**Artifact-as-State mapping:**

| Phase | Artifact | Skip when |
|-------|----------|----------|
| load_config | accelerator.yaml | Always re-read (stateless) |
| parse_erd | erd_parsed.yaml | file exists + tables array non-empty |
| build_semantic_model | semantic_model.yaml | file exists |
| generate_ddl | Tables in catalog | SHOW TABLES returns expected count |
| generate_synthetic_data | Row count > 0 | SELECT COUNT(*) > 0 per table |
| validate_data | data_layer_validation.yaml | file exists + overall_status field |

---

# Step 1: Load Configuration

1. Read `accelerator.yaml`.
2. Apply name suffix/version rules from `00_master_prompt.md` Step 0.
3. Read:

```yaml
data_source.erd.image
```

This PNG/JPG file under the example folder is the **authoritative schema source**.

4. Load:

```yaml
templates.ddl_notebook
templates.dbldatagen_notebook
```

5. Load synthetic-data volume configuration from:

```yaml
data_source.greenfield.volume
```

6. Load the KPI/use-case specification when available.

The KPI/use-case specification may influence:

- realistic synthetic values;
- useful categorical distributions;
- data coverage;
- analytical scenarios.

It MUST NOT alter the physical schema extracted from the ERD.

> **PROGRESS REPORT:** After loading config, call `report_progress` with:
> - `phase_id`: "load_config"
> - `phase_name`: "Load Configuration"
> - `status`: "completed"
> - `findings`: ["Domain: {domain_name}", "Volume: {volume}", "ERD: {erd_filename}"]
> - `stats`: {"templates_loaded": N}

---

# Step 2: Parse ERD Image into Canonical Schema Contract

> **PROGRESS REPORT:** Before calling the vision model, call `report_progress` with:
> - `phase_id`: "parse_erd"
> - `phase_name`: "Parse ERD"
> - `status`: "started"
> - `current_task`: "Processing ERD image with vision model"
> - `happenings`: ["Using vision model: {model_name from llm.steps.parse_erd.model}", "Processing ERD image: {erd_image_filename}", "Extracting table structures and relationships"]
> - `stats`: {"erd_image": "{erd_image_filename}", "vision_model": "{model_name}"}

> **MANDATORY: Vision model required.**

Use:

```yaml
llm.steps.parse_erd.model
```

The model MUST support direct image understanding.

### Reasoning Model Configuration

If the vision model is a reasoning model (e.g., `databricks-gpt-5-5`):

- Set `max_tokens >= 32000` (reasoning tokens consume ~4000-8000 of the budget before output is produced)
- Do NOT set `temperature` to anything other than the model's default (some reasoning models only support `temperature=1`)
- `finish_reason: "length"` with empty content means `max_tokens` is too low — increase it
- The model may resize large images internally; keep input images under 2000px width for reliability

## Authoritative Input Rule

The ERD image is the **sole authoritative schema input**.

NEVER derive schema from:

- previous versions of `erd_parsed.yaml`;
- generated DDL notebooks;
- existing Unity Catalog tables;
- `SHOW CREATE TABLE`;
- prior generated outputs;
- previous synthetic-data notebooks;
- inferred downstream Metric Views.

This ensures schema drift is detected and every generated version is independently derived from the supplied ERD.

---

## 2.1 Extract Observed Structure

Read `{data_source.erd.image}` directly using the vision model.

Extract every visible:

- table;
- column;
- datatype when visible;
- PK marker;
- FK marker;
- relationship line;
- relationship direction;
- cardinality marker;
- referenced entity.

All table and column names must be normalized to:

```regex
^[a-z0-9_]+$
```

Do not silently drop columns.

Do not add columns that are not present in the ERD.

---

## 2.2 Separate Observation from Inference

For every extracted object distinguish between:

### OBSERVED

Information explicitly visible in the ERD.

Examples:

- table name;
- column name;
- PK marker;
- FK marker;
- relationship line;
- datatype label.

### INFERRED

Information derived through semantic reasoning.

Examples:

- fact vs dimension;
- likely grain;
- business entity;
- relationship cardinality when not explicitly marked;
- semantic role of a column.

Never present inferred information as visually observed fact.

---

## 2.3 Confidence Classification

Every inferred structural item must have one of:

```text
HIGH
MEDIUM
LOW
UNRESOLVED
```

Examples:

```yaml
confidence: HIGH
evidence:
  - FK line explicitly connects customer_id to dim_customer.customer_id
```

or:

```yaml
confidence: LOW
evidence:
  - column names appear related but ERD has no visible relationship
```

### Hard rule

A relationship MUST NOT be created solely because two columns have similar names.

If the relationship cannot be established with reasonable confidence, mark:

```text
UNRESOLVED_RELATIONSHIP
```

Do not fabricate a join.

---

## 2.4 Determine Table Grain

For every table determine:

```text
One row represents ______.
```

Examples may include:

- one entity;
- one transaction;
- one event;
- one transaction line;
- one snapshot;
- one entity-period relationship;
- one mapping between two entities.

Do not assume a table is a fact merely because its name begins with `fact_`.

Do not assume a table is a dimension merely because its name begins with `dim_`.

Infer grain from:

- key structure;
- relationships;
- column semantics;
- identifiers;
- measures;
- timestamps/dates.

If grain cannot be determined confidently:

```yaml
grain: UNRESOLVED
```

---

## 2.5 Canonical Schema Contract

Write:

```text
{workspace.output_folder}/erd_parsed.yaml
```

using Workspace API / agent tools defined in `workspace_file_io.md`.

Never use:

```text
dbutils.fs
```

for `/Workspace/`.

The contract must contain, at minimum:

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

relationships:

  - source_table: ...
    source_columns: [...]
    target_table: ...
    target_columns: [...]
    cardinality: ...
    confidence: ...
    evidence: ...

unresolved_items: []
```

### Unresolved Items Decision Gate

#### Relationship Inference (BEFORE applying halt rules)

Before marking a relationship as UNRESOLVED, you MUST attempt to infer it from:

1. **Column naming conventions** — if table A has a column `<table_b_name>_id` or `<table_b_pk>`,
   infer a FK relationship from A to B with `confidence: MEDIUM`.
2. **Shared column names** — if table A and table B share a column with the same name
   (e.g., `member_id`, `claim_id`), infer a join relationship.
3. **Domain semantics** — fact tables with "detail" or "line" in their name typically
   relate to a parent "header" fact via a shared key (e.g., `claim_id`).
4. **KPI specification** — if the KPI spec references a join path (e.g., "claims by member"),
   infer the relationship even if no explicit ERD line is drawn.

Only mark as `UNRESOLVED_RELATIONSHIP` if NONE of these inference methods can establish
the join path. Inferred relationships should be recorded with `confidence: MEDIUM` and
`evidence: "Inferred from column naming / shared keys / domain semantics"`.

#### Halt Rules

**HALT immediately** if `unresolved_items` contains any item where:

- `type: RELATIONSHIP` and **both** tables are required for a fact→dimension join path
  **AND** the relationship cannot be inferred by any of the methods above;
- `type: PRIMARY_KEY` and the table is referenced by **any** FK in another table;
- `type: COLUMN` and the column is explicitly referenced in the KPI specification;
- `type: TABLE` (entire table cannot be extracted from the ERD).

**WARN but continue** if:

- `type: RELATIONSHIP` but the join can be inferred from naming/shared columns (record with MEDIUM confidence);
- `type: RELATIONSHIP` but neither table is on a critical analytical join path;
- `type: COLUMN` and the column is not referenced by KPIs or downstream logic;
- `type: CARDINALITY` (cardinality uncertain but relationship itself is established).

For HALT conditions, report:

```text
❌ EXECUTION HALTED
Unresolved item blocks pipeline:
  type: ...
  entity: ...
  reason: ...
  inference_attempted: [list methods tried]
  downstream_impact: ...
```

Do not attempt to guess past a HALT-level unresolved item.

---

## 2.6 Structural Contract Rules

Once `erd_parsed.yaml` is generated, it becomes the authoritative schema contract for all downstream steps in this stage.

Downstream logic MUST NOT:

- invent columns;
- remove columns;
- change datatypes without explicit justification;
- create surrogate keys not present in the ERD;
- replace unresolved joins with guessed joins;
- move columns between tables;
- reinterpret the ERD independently.

If a downstream requirement refers to a column that does not exist:

1. verify the schema contract;
2. locate the actual relevant column if one exists;
3. use its real table and grain;
4. otherwise mark the requirement unresolved.

Never create the missing column merely to satisfy downstream logic.

> **PROGRESS REPORT:** After ERD parsing is complete, call `report_progress` with:
> - `phase_id`: "parse_erd"
> - `phase_name`: "Parse ERD"
> - `status`: "completed"
> - `current_task`: "Canonical schema contract established"
> - `findings`: ["Extracted {N} tables", "{M} relationships identified", "{C} total columns"]
> - `stats`: {"tables": N, "relationships": M, "columns": C}
> - `happenings`: ["Extracted table structures", "Identified primary keys", "Mapped foreign key relationships"]

---

# Step 3: Build Semantic/Data Model

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "build_semantic_model"
> - `phase_name`: "Build Semantic Model"
> - `status`: "started"
> - `current_task`: "Identifying grains, keys and relationships"
> - `happenings`: ["Classifying tables", "Computing generation order", "Determining grains"]

Before DDL or synthetic-data generation, reason about the data model represented by `erd_parsed.yaml`.

Write:

```text
{workspace.output_folder}/semantic_model.yaml
```

This stage must consume the Canonical Schema Contract.

Do not independently re-read or reinterpret the ERD.

---

## 3.1 Table Semantic Classification

For each table identify:

```yaml
table:
business_entity:
grain:
semantic_role:
```

where `semantic_role` is one of:

```text
FACT
DIMENSION
BRIDGE
EVENT
SNAPSHOT
REFERENCE
RELATIONSHIP
UNKNOWN
```

---

## 3.2 Column Semantic Classification

Classify every column into zero or more semantic types:

```text
PRIMARY_KEY
FOREIGN_KEY
BUSINESS_IDENTIFIER
MEASURE
CATEGORICAL_ATTRIBUTE
DESCRIPTIVE_ATTRIBUTE
DATE
TIMESTAMP
STATUS
QUANTITY
MONETARY
BOOLEAN
DERIVED
FREE_TEXT
UNKNOWN
```

For measures, identify expected aggregation semantics where reasonably inferable:

```text
SUM
COUNT
COUNT_DISTINCT
MIN
MAX
AVG
NON_ADDITIVE
UNKNOWN
```

Do not invent a metric merely because a numeric column exists.

---

## 3.3 Physical Model vs Analytical Model

Keep these concepts separate.

### Physical Model

The schema exactly represented by the ERD.

### Analytical Model

The recommended fact/dimension navigation model for analytics.

Do NOT restructure the DDL solely to force a star schema.

Instead document analytical relationships over the physical tables.

---

## 3.4 Relationship Graph

Construct a dependency graph from PK/FK relationships.

Identify:

- root entities;
- dependent entities;
- facts;
- dimensions;
- bridges;
- fact-to-fact relationships;
- shared dimensions;
- snowflake relationships.

Calculate a safe generation order using this dependency graph.

Example conceptual order:

```text
Independent/reference entities
        ↓
Parent dimensions
        ↓
Child dimensions / bridges
        ↓
Primary facts
        ↓
Dependent facts/events
```

The actual order MUST be derived from the current ERD.

---

## 3.5 Join Safety

For every relationship determine:

```yaml
left_grain:
right_grain:
cardinality:
expected_row_behavior:
fanout_risk:
```

Mark:

```text
FANOUT_RISK
```

when joining the tables could multiply rows at the analytical grain.

Do not attempt to solve Metric View design here.

The purpose is to ensure synthetic data reflects the actual relationships and grain.

> **PROGRESS REPORT:** After semantic model is complete, call `report_progress` with:
> - `phase_id`: "build_semantic_model"
> - `phase_name`: "Build Semantic Model"
> - `status`: "completed"
> - `findings`: ["{N_facts} facts, {N_dims} dimensions identified", "Generation order computed", "All grains determined"]
> - `stats`: {"facts": N, "dimensions": N, "relationships_resolved": N}
> - `happenings`: ["Classified tables by semantic type", "Computed generation dependency order", "Determined table grains"]

---

# Step 4: Generate DDL Notebook

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "generate_ddl"
> - `phase_name`: "Generate DDL"
> - `status`: "started"
> - `current_task`: "Generating Delta table DDL notebooks"
> - `happenings`: ["Building CREATE TABLE statements", "Creating notebook", "Executing DDL"]

### Pre-Flight Checklist

Before generating DDL, confirm:

- [ ] `erd_parsed.yaml` exists and was written in THIS run (not from a prior version)
- [ ] All HALT-level unresolved items have been resolved or the pipeline has stopped
- [ ] Every table has an explicitly documented grain
- [ ] Every PK is identified (no UNRESOLVED PKs on tables referenced by FKs)
- [ ] `templates.ddl_notebook` path has been loaded
- [ ] `VERSION_SUFFIX` has been resolved

1. Create:

```text
{workspace.output_folder}/notebooks/ddl_{domain.name}.ipynb
```

using:

- Workspace `import` with `format: JUPYTER`, or
- supported agent notebook tools.

Never use `dbutils.fs` for Workspace notebook creation.

2. Populate from:

```yaml
templates.ddl_notebook
```

Do not hand-write an equivalent notebook from scratch.

3. Generate tables strictly from:

```text
erd_parsed.yaml
```

4. Target:

```text
{catalog.source.catalog}.{catalog.source.schema}
```

5. Execute the notebook.

---

## DDL Fidelity Rules

DDL MUST contain:

- every ERD table;
- every ERD column;
- the inferred datatype selected during ERD parsing;
- correct table version suffix;
- no unexpected extra columns.

The DDL generator MUST NOT modify the schema simply to make synthetic-data generation easier.

Synthetic generation adapts to the schema.

The schema does not adapt to synthetic generation.

> **PROGRESS REPORT:** After DDL notebook is created and executed, call `report_progress` with:
> - `phase_id`: "generate_ddl"
> - `phase_name`: "Generate DDL"
> - `status`: "completed"
> - `findings`: ["{N} tables created successfully", "DDL notebook executed"]
> - `stats`: {"tables_created": N, "columns_total": C}
> - `happenings`: ["Generated DDL from canonical schema", "Created notebook", "Executed DDL statements"]

---

# Step 5: Build Synthetic Data Specification

### Pre-Flight Checklist

Before building the synthetic data spec, confirm:

- [ ] DDL notebook executed successfully (all tables exist in catalog)
- [ ] `semantic_model.yaml` exists with generation order computed
- [ ] All FK relationships have confidence >= MEDIUM
- [ ] Volume setting loaded from `data_source.greenfield.volume`
- [ ] KPI spec loaded (if available) for analytical coverage

Run only when:

```yaml
data_source.greenfield.synthetic_data: true
```

Do NOT immediately generate dbldatagen code.

First create:

```text
{workspace.output_folder}/synthetic_data_spec.yaml
```

using:

```text
erd_parsed.yaml
+
semantic_model.yaml
+
KPI/use-case context when available
+
data_source.greenfield.volume
```

The synthetic-data specification determines how the relational dataset should behave.

### Volume Targets

Map `data_source.greenfield.volume` to concrete row counts:

```yaml
volume_targets:
  low:
    dimension: 100-500
    fact: 500-5000
    detail_fact: 2000-10000   # line-level facts (e.g., claim details)
  medium:
    dimension: 1000-5000
    fact: 10000-50000
    detail_fact: 50000-200000
  high:
    dimension: 10000-50000
    fact: 100000-500000
    detail_fact: 500000-2000000
```

Use the semantic classification from `semantic_model.yaml` to assign each table to the correct tier (dimension, fact, or detail_fact).

Detail facts are child tables with N:1 relationships to a primary fact (e.g., claim lines to claim headers). Their row count should reflect realistic cardinality multipliers.

Do not guess row counts. Use these ranges explicitly in `synthetic_data_spec.yaml`.

---

## 5.1 Generation Philosophy

Synthetic data MUST NOT be generated as independent random columns.

Generation must be:

```text
ENTITY-FIRST
RELATIONSHIP-AWARE
DOMAIN-AWARE
SEMANTICALLY COHERENT
```

The generated dataset must behave like one connected dataset, not a collection of independently randomized tables.

### Demo-Quality Data Distribution Requirements (CRITICAL)

Synthetic data MUST use **skewed/non-uniform distributions** for key categorical dimensions and financial measures. Uniform random distributions produce:

- Dashboard bar charts where all bars are the same height (useless for demos)
- Filters that don't produce visible changes in widget values
- KPIs that lack analytical interest

**Required skew patterns:**

```text
1. Financial measures by category:
   - Different categories MUST have clearly different cost profiles
   - Example: INSTITUTIONAL claims ~$45K avg vs PHARMACY ~$350 avg (100x difference)
   - This makes bar charts visually compelling

2. Volume distribution by dimension:
   - Primary dimension values MUST have unequal row counts
   - Example: COMMERCIAL LOB gets 35% of claims, TRICARE gets 8%
   - Example: CA/TX/NY get 50% of volume, AZ/WA get 8%
   - This makes filters produce clearly different totals

3. Rate measures by category:
   - Denial rates, clean claim rates, etc. MUST vary by dimension
   - Example: INSTITUTIONAL denial_rate 28% vs VISION 3%
   - This demonstrates that different categories have different quality profiles
```

**Why this matters:** Dashboards and Genie spaces are demo artifacts. If the synthetic data is perfectly uniform, the demo fails to show the value of filtering, drill-down, and dimensional analysis — even though the technical implementation is correct.

Use `WEIGHTED_CATEGORICAL` generation strategy for dimension columns and vary `NUMERIC_RANGE` parameters by category for financial columns.

---

## 5.2 Column Generation Specification

For every column determine:

```yaml
column:
datatype:
semantic_type:
generation_strategy:
nullable_probability:
domain:
distribution:
dependencies:
constraints:
```

Allowed generation strategies may include:

```text
SEQUENTIAL_ID
PARENT_KEY_SAMPLE
CATEGORICAL_VALUES
WEIGHTED_CATEGORICAL
NUMERIC_RANGE
DISTRIBUTION
DATE_RANGE
TIMESTAMP_RANGE
BOOLEAN
DERIVED
FREE_TEXT
STATIC
```

### 5.2.1 Realistic Value Requirements (CRITICAL)

For EVERY `CATEGORICAL_VALUES` or `WEIGHTED_CATEGORICAL` column, the spec MUST define
a concrete `values` list with **domain-realistic entries** — never placeholders or generic letters.

```yaml
# WRONG - generic garbage:
generation_strategy: CATEGORICAL_VALUES
values: ["A", "B", "C", "D"]

# CORRECT - domain-meaningful:
generation_strategy: WEIGHTED_CATEGORICAL
values: ["APPROVED", "DENIED", "PENDING", "IN_REVIEW"]
weights: [0.65, 0.20, 0.10, 0.05]
```

For `FREE_TEXT` or string columns:

```yaml
# WRONG - produces unbounded random words:
generation_strategy: FREE_TEXT
template: "\\w\\w\\w\\w"

# CORRECT - controlled length, domain pattern:
generation_strategy: FREE_TEXT
max_length: 30  # from VARCHAR constraint
pattern: "prefix-digits"  # e.g., "MBR-00001234"
```

For ID/code columns:

```yaml
# Derive pattern from domain conventions:
generation_strategy: SEQUENTIAL_ID
prefix: "CLM"  # claims domain
length: 10     # fits VARCHAR(12)
```

The synthetic data spec is the blueprint. If it specifies garbage values,
the generated notebook will produce garbage. **Every value list must be
inferred from the domain context** (ERD table names, KPI spec terminology,
industry-standard codes).

---

## 5.3 Domain-Aware Values

Infer realistic categorical values from:

1. column name;
2. table entity;
3. semantic model;
4. KPI/use-case context;
5. surrounding schema.

Never leave analytically meaningful categorical columns as arbitrary random strings when reasonable domains can be inferred.

Examples of categories include:

- statuses;
- regions;
- entity types;
- product types;
- channels;
- classifications.

These examples are illustrative only.

Do not hardcode assumptions from another domain.

---

## 5.4 Cross-Column Dependencies

Identify semantic dependencies such as:

```text
start_date <= end_date
```

```text
completed_status → completion_date should generally exist
```

```text
child FK → valid parent PK
```

```text
derived_amount = component relationships
```

only when supported by the semantic model.

Store these explicitly:

```yaml
semantic_constraints:
  - expression: ...
    confidence: ...
    rationale: ...
```

---

## 5.5 Dependency Types

Classify constraints as:

```text
STRUCTURAL
TEMPORAL
SEMANTIC
STATISTICAL
```

### STRUCTURAL

PK/FK and uniqueness relationships.

### TEMPORAL

Date/time ordering.

### SEMANTIC

Cross-column or cross-table business relationships.

### STATISTICAL

Expected distributions and relative frequencies.

Structural constraints are mandatory.

Semantic/statistical constraints should only be introduced when reasonably supported by the schema or use-case.

---

# Step 6: Generate Synthetic Data Notebook

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "generate_synthetic_data"
> - `phase_name`: "Generate Synthetic Data"
> - `status`: "started"
> - `current_task`: "Populating tables with referential integrity"
> - `happenings`: ["Building data generator notebook", "Executing data generation"]

### Pre-Flight Checklist

Before generating synthetic data code, confirm:

- [ ] `synthetic_data_spec.yaml` exists with FK strategies defined for every relationship
- [ ] Generation order computed from dependency graph
- [ ] `base_generator()` will be used for every table (no raw `dg.DataGenerator()`)
- [ ] ANSI mode will be disabled in setup cell
- [ ] `discover_tables()` will be used for version-aware table references
- [ ] Volume targets mapped to concrete row counts per table
- [ ] FK columns will sample from parent key domains (not independent generation)

Create:

```text
{workspace.output_folder}/notebooks/synthetic_data_{domain.name}.ipynb
```

using Workspace API / agent notebook tools.

Populate from:

```yaml
templates.dbldatagen_notebook
```

Do not create an equivalent notebook from scratch.

---

# Synthetic Data Generation Rules

## 6.1 Generate in Dependency Order

Use:

```text
semantic_model.yaml
```

and:

```text
synthetic_data_spec.yaml
```

to calculate generation order.

Dimensions-before-facts is the default pattern, but the actual dependency graph is authoritative.

Never generate dependent tables before their referenced parent-key domain exists.

---

## 6.2 Foreign Keys MUST Reuse Generated Parent Keys

This rule is mandatory.

Never independently generate an FK using random strings, random numbers, or unrelated sequences.

Incorrect:

```text
parent.id = independently generated values
child.parent_id = independently generated values
```

Correct:

```text
Generate parent.id
        ↓
persist / collect valid parent key domain
        ↓
sample child.parent_id from valid parent IDs
```

For every FK relationship:

```text
child.FK ∈ parent.PK
```

unless the ERD explicitly allows nullable/unmatched references.

### 6.2.1 FK Target Uniqueness Verification

Before generating any child table, verify that the parent's FK-target column is actually unique in the parent table:

```sql
SELECT COUNT(*) AS total, COUNT(DISTINCT fk_target_col) AS distinct_vals
FROM parent_table
-- MUST satisfy: total == distinct_vals
```

If the FK target has duplicates in the parent, the child-to-parent join will produce a **cross-product explosion** (e.g., 5000 detail rows × 500 header rows = 2,500,000 joined rows instead of the expected 5000).

This validation MUST run after parent generation and before child generation.

If it fails:

```text
FK_TARGET_NOT_UNIQUE: {parent_table}.{fk_target_col}
  total_rows: N
  distinct_values: M
  expected: N == M
```

HALT child generation and regenerate the parent with unique FK target values.

---

## 6.3 Shared Key Domains

Maintain reusable generated key domains for all parent entities.

Conceptually:

```text
KEY_DOMAINS["logical_parent"]["primary_key"]
```

Dependent generators MUST reuse the same key domain.

Do not regenerate the key domain.

---

## 6.4 Relationship Cardinality

Generate child rows according to the cardinality described by `semantic_model.yaml`.

For example:

```text
1:N
```

should generate multiple children for at least some parents where appropriate.

Do not create synthetic data where every relationship accidentally behaves as 1:1 because generation was performed independently.

For each relationship establish:

```yaml
minimum_children:
maximum_children:
distribution:
```

when reasonably inferable.

If no domain evidence exists, use conservative defaults appropriate to the cardinality rather than inventing domain-specific behavior.

---

# Data Completeness Rules

## Dimension / Analytical Attributes

Columns used for slicing, filtering, grouping, or KPI analysis should have:

```python
percentNulls=0.0
```

unless nulls are semantically meaningful.

This includes:

- categorical attributes;
- dates used for analysis;
- foreign keys required for joins;
- segmentation attributes.

Do NOT blindly force every descriptive field to non-null when the semantic model indicates the field is legitimately optional.

---

## Column Population

Every DDL column must receive a generation strategy.

Do not silently skip columns.

If realistic generation cannot be inferred:

1. generate a datatype-correct fallback value;
2. mark the column in the generation report as:

```text
GENERIC_FALLBACK
```

Do not generate NULL-only columns simply because semantics are unknown.

---

## Data Quality & Realism (MANDATORY)

Generated synthetic data MUST be **semantically meaningful** and **domain-appropriate**.

### Absolute Prohibitions

- **NEVER** use `template=r"\\w\\w\\w\\w"` or any `\w`-based pattern — this produces
  random Lorem Ipsum text (e.g., "doloreexcepteurconsequat") that is meaningless garbage.
- **NEVER** generate unbounded-length strings — always respect `VARCHAR(N)` / `CHAR(N)`
  constraints from the DDL. Use `extract_max_length()` to read the constraint.
- **NEVER** hardcode domain-specific values in the template — the template must remain
  domain-agnostic. Domain values are injected by the LLM when generating the notebook.
- **NEVER** use generic random alphanumeric for categorical columns (status, type, gender, LOB).

### Required Practices

1. **Use domain-specific realistic values** for categorical columns:
   - Status columns: use actual domain statuses (e.g., "APPROVED", "DENIED", "PENDING" for claims)
   - Type columns: use real business types (e.g., "INPATIENT", "OUTPATIENT", "EMERGENCY")
   - Code columns: use realistic code patterns (e.g., ICD-10 format for diagnosis codes)
   - Name columns: use name patterns with `values=` lists of realistic names, NOT random text

2. **Respect string length constraints**:
   - Use `_build_template(max_len)` for fixed-length output (digits/hex, never `\w`)
   - Use `_string_col_kwargs()` which reads the column name to infer semantic patterns
   - For VARCHAR(30), generated values MUST be ≤ 30 characters

3. **Generate business-realistic distributions**:
   - Amount columns: use ranges appropriate to the domain (e.g., $10–$50,000 for medical claims)
   - Date columns: use realistic date ranges for the domain
   - Percentage columns: use 0.0–1.0 or 0–100 as semantically appropriate

4. **Customize `_string_col_kwargs()` output** in the generated notebook:
   - Override the template's generic patterns with domain-specific `values=` lists
   - Example: for a `claim_status` column, override with:
     `values=["APPROVED", "DENIED", "PENDING", "IN_REVIEW"]`
   - Example: for a `lob_code` column, override with:
     `values=["COM", "MED", "MCA"]` (Commercial, Medicare, Medicaid)

5. **The generated notebook MUST customize `base_generator()` output**:
   - After calling `base_generator()`, the notebook code must replace generic patterns
     with domain-appropriate values for key analytical columns
   - Use `values=` for categoricals, realistic `minValue`/`maxValue` for numerics
   - The template provides safe defaults; the generated notebook adds domain intelligence

### Verification

After synthetic data generation, verify:

```text
- [ ] No VARCHAR constraint violations (DELTA_EXCEED_CHAR_VARCHAR_LIMIT)
- [ ] Categorical columns have meaningful, domain-appropriate values
- [ ] FK columns reference actual parent keys (not independently generated)
- [ ] Amount/numeric columns have realistic ranges for the domain
- [ ] No Lorem Ipsum or random word concatenation in any column
```

---

# Versioning Rules

Populate:

```text
VERSION_SUFFIX
```

from:

```yaml
config.version_suffix
```

Examples:

```text
_v1
_v2
""
```

The synthetic-data notebook MUST reference the exact versioned tables created by the DDL notebook.

Use:

```python
discover_tables()
```

from the template.

It must produce:

```python
TABLES = {
    "logical_table": "logical_table_v1"
}
```

Always reference tables through:

```python
TABLES["logical_name"]
```

Never hardcode versionless names.

For FK lookup:

```python
spark.table(
    f"{CATALOG}.{SCHEMA}.{TABLES['logical_parent']}"
)
```

---

# Spark Configuration Rules

In the setup cell, before ANY `dg.DataGenerator` call:

```python
spark.conf.set("spark.sql.ansi.enabled", "false")
```

This is mandatory.

dbldatagen may internally perform arithmetic that produces divide-by-zero conditions with small row counts or random distributions.

Disabling ANSI mode converts these into NULL instead of intermittent execution failure.

---

# dbldatagen Type-Safety Rules

## Mandatory base_generator()

Every table MUST start with:

```python
gen = base_generator(TABLES["logical_name"], rows, unique_columns=["<pk_col>", ...])
```

`base_generator()` reads the authoritative DDL schema and configures the correct PySpark datatype for every column.

**CRITICAL — `unique_columns` parameter:**

You MUST pass `unique_columns` containing:
1. The table's primary key column(s)
2. Any column that is an FK target (i.e., referenced by another table's foreign key)

Without `unique_columns`, string/integer PK columns may produce duplicate values, causing `FK_TARGET_NOT_UNIQUE` validation failures downstream.

Example:
```python
# dim_provider.provider_npi is a PK and FK target from fact_claim_header
gen = base_generator(TABLES["dim_provider"], rows=300, unique_columns=["provider_npi"])
```

Never construct:

```python
dg.DataGenerator(...)
```

from scratch for an ERD table.

---

## Template Function API Contracts

These functions are provided by the templates. Use them exactly as specified:

```python
# base_generator(table_name: str, rows: int, unique_columns: list = None) -> dg.DataGenerator
#   - Reads the DDL schema from the catalog table
#   - Returns a DataGenerator pre-configured with correct PySpark types for every column
#   - unique_columns: list of column names that MUST have unique values (PK + FK targets)
#   - ALWAYS pass unique_columns for dimension PKs and natural keys referenced by FKs
#   - Do NOT call dg.DataGenerator() directly for ERD tables
#   - Do NOT pass schema= or structType= when base_generator() is available

# discover_tables() -> dict[str, str]
#   - Scans catalog/schema for tables matching VERSION_SUFFIX
#   - Returns {"logical_name": "logical_name_v3"} mapping
#   - Always use TABLES["name"] from this result; never hardcode table names

# date_range_for(period: str = "5y") -> tuple[str, str]
#   - Returns (begin, end) date strings for synthetic date/timestamp generation
#   - Default span is 5 years ending near current date
#   - Use for DateType and TimestampType columns

# add_pk_long(gen, col_name: str) -> dg.DataGenerator
#   - Adds a sequential BIGINT primary key column

# add_fk_long(gen, col_name: str, parent_table: str, parent_col: str) -> dg.DataGenerator
#   - Adds a foreign key column that samples from the parent table's PK values
#   - Ensures referential integrity by construction
```

If a template function does not exist or raises an error, do NOT reimplement it inline. Report:

```text
TEMPLATE_FUNCTION_MISSING: <function_name>
```

and halt.

---

## Column Overrides

Use `.withColumn()` only when an explicit realism override is required.

Example:

```python
gen = gen.withColumn(
    "category_column",
    StringType(),
    values=[...],
    percentNulls=0.0
)
```

Do not re-add a column already configured by `base_generator()` in a way that creates duplicate-column definitions.

Before applying an override, ensure the template's supported override mechanism replaces the existing generator definition rather than creating a second definition for the same column.

Each DDL column must resolve to **exactly one effective dbldatagen generator definition**.

If the installed dbldatagen version cannot safely override a column with `.withColumn()`, use the template's supported replacement/override helper instead.

Do not repeatedly retry `.withColumn()` against the same column.

---

# Datatype Rules

### PK / FK / IDs

Use the datatype from `base_generator()`.

Never force:

```python
StringType()
```

for numeric identifiers.

Never use arbitrary regex templates for PK/FK values.

FKs must come from parent key domains.

### dbldatagen Template Syntax on Serverless (Spark Connect)

The dbldatagen `template=` parameter does NOT reliably generate unique values on serverless compute (Spark Connect). Specifically:

```python
# ✗ BROKEN — produces literal "CLMd{9}" for ALL rows
template=r"CLM\\d{9}"
```

The backslash-digit escape sequences are interpreted as literal characters, not as random-digit placeholders.

For **business keys that serve as FK targets** (where uniqueness is critical), always use Spark native expressions:

```python
# ✓ CORRECT — produces unique values like CLM000000001, CLM000000002, ...
from pyspark.sql import functions as F

df = spark.range(1, ROWS + 1).toDF("pk_col")
df = df.withColumn("business_key",
    F.concat(F.lit("CLM"), F.lpad(F.col("pk_col").cast("string"), 9, "0"))
)
```

For **non-key descriptive columns** where uniqueness is not required (e.g., provider_name, member_name), dbldatagen `template=` may still be used — non-unique values are acceptable.

---

### DateType

Use:

```text
begin="YYYY-MM-DD"
end="YYYY-MM-DD"
```

---

### TimestampType

Use:

```text
begin="YYYY-MM-DD HH:MM:SS"
end="YYYY-MM-DD HH:MM:SS"
```

Use:

```python
date_range_for()
```

from the template where possible.

Date-only timestamp strings are prohibited.

---

### DECIMAL / FLOAT

Use numeric values and ranges.

Never use formatted currency strings.

---

### BOOLEAN

Never use:

```python
values=[True, False]
```

or weighted values with `BooleanType()`.

Use:

```python
BooleanType()
```

without explicit values.

dbldatagen handles Boolean distribution.

> **PROGRESS REPORT:** After synthetic data generation completes, call `report_progress` with:
> - `phase_id`: "generate_synthetic_data"
> - `phase_name`: "Generate Synthetic Data"
> - `status`: "completed"
> - `current_task`: "All tables populated"
> - `findings`: ["{N} tables populated", "{M} total rows generated", "Referential integrity maintained"]
> - `stats`: {"tables_populated": N, "total_rows": M, "fk_relationships_linked": K}
> - `happenings`: ["Generated dimension tables", "Generated fact tables with FK links", "Verified referential integrity"]
>
> **During** synthetic data generation, call `report_progress` with `status: "update"` periodically:
> - `current_task`: "Populating {table_name}"
> - `progress_pct`: estimated percentage (tables_done / total_tables * 100)
> - `stats`: {"tables_completed": done, "tables_total": total, "rows_generated": rows_so_far}

---

# Step 7: Integrity Validation

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_data"
> - `phase_name`: "Validate Data"
> - `status`: "started"
> - `current_task`: "Running data quality and integrity checks"
> - `happenings`: ["Validating primary keys", "Checking referential integrity", "Testing join stability"]

### Pre-Flight Checklist

Before running validation, confirm:

- [ ] Synthetic data notebook executed without errors
- [ ] All tables in `erd_parsed.yaml` exist in the catalog with data
- [ ] `synthetic_data_spec.yaml` is available (for constraint validation)
- [ ] `semantic_model.yaml` is available (for cardinality validation)
- [ ] Validation will test ALL items below — do not skip any section

Synthetic-data generation is NOT considered successful because the notebook executed.

Run deterministic validation.

### CRITICAL — BATCH VALIDATION (saves 10+ tool calls)

Do NOT execute one SQL per validation item. Combine all checks into 2-3 large SQL calls:

```sql
-- BATCH 1: Row counts + PK uniqueness for ALL tables in ONE query
SELECT 'dim_address' table_name, COUNT(*) rows, COUNT(DISTINCT address_key) pk_distinct, COUNT(*) - COUNT(DISTINCT address_key) pk_dups FROM catalog.schema.dim_address_v2
UNION ALL
SELECT 'dim_member', COUNT(*), COUNT(DISTINCT member_sk), COUNT(*) - COUNT(DISTINCT member_sk) FROM catalog.schema.dim_member_v2
UNION ALL
... (all tables)

-- BATCH 2: ALL FK orphan checks in ONE query
SELECT 'dim_provider_to_dim_address' relationship, COUNT(*) orphans FROM catalog.schema.dim_provider_v2 c LEFT ANTI JOIN catalog.schema.dim_address_v2 p ON c.provider_address_key = p.address_key
UNION ALL
SELECT 'fact_claim_header_to_dim_member', COUNT(*) FROM catalog.schema.fact_claim_header_v2 c LEFT ANTI JOIN catalog.schema.dim_member_v2 p ON c.clm_member_sk = p.member_sk
UNION ALL
... (all FK relationships)

-- BATCH 3: Join stability + semantic constraints
SELECT 'fact_to_dim_member' relationship, (SELECT COUNT(*) FROM fact_table) before_rows, COUNT(*) after_rows
FROM fact_table f INNER JOIN dim_table d ON f.fk = d.pk
UNION ALL
...
```

This reduces 15-20 individual SQL tool calls to 2-3 batched queries. Parse results programmatically to determine PASS/FAIL for each check.

---

## 7.1 Schema Validation

For every generated table validate:

```text
expected table exists
expected columns exist
no unexpected columns exist
datatypes match DDL
```

Failure status:

```text
SCHEMA_VALIDATION_FAILURE
```

---

## 7.2 Row Count Validation

Validate configured volumes.

At minimum:

```text
fact/event tables > 0 rows
```

and dimensions required by those facts are populated.

Report:

```text
expected_rows
actual_rows
```

---

## 7.3 Primary Key Validation

For every PK:

```text
NULL PK count = 0
```

and where uniqueness is required:

```text
COUNT(*) = COUNT(DISTINCT PK)
```

For composite PKs validate uniqueness of the entire key.

Failure:

```text
PRIMARY_KEY_INTEGRITY_FAILURE
```

---

## 7.4 Foreign Key Validation

For every relationship compute orphan count:

```sql
SELECT COUNT(*)
FROM child c
LEFT ANTI JOIN parent p
  ON <canonical FK relationship>
```

Expected:

```text
orphan_count = 0
```

unless nullable/unmatched FKs are explicitly allowed by the semantic model.

Failure:

```text
FOREIGN_KEY_INTEGRITY_FAILURE
```

---

## 7.5 Cardinality Validation

For every declared relationship validate actual generated behavior.

Examples:

```text
1:1
1:N
N:1
N:M
```

Compare expected and observed cardinality.

Do not only test that a join returns rows.

A join returning rows does NOT prove the relationship was generated correctly.

Failure:

```text
CARDINALITY_VALIDATION_FAILURE
```

---

## 7.6 Join Stability Validation

For every N:1 relationship from a fact/event table to a dimension/reference table calculate:

```text
fact_rows_before
fact_rows_after_join
distinct_fact_keys_before
distinct_fact_keys_after
```

Unexpected multiplication indicates:

```text
JOIN_FANOUT_FAILURE
```

---

## 7.7 Semantic Constraint Validation

Execute all HIGH-confidence structural, temporal, and semantic constraints defined in:

```text
synthetic_data_spec.yaml
```

Examples include:

```text
start_date <= end_date
```

or other model-derived relationships.

Do not introduce domain assumptions that are not contained in the semantic specification.

---

## 7.8 Analytical Completeness

For fields referenced by the KPI specification validate:

```text
NULL percentage
distinct values
minimum
maximum
sample values
```

Categorical slicing/filtering fields must contain meaningful usable categories rather than:

```text
NULL
random UUID-like strings
single-value populations
```

unless the semantic model explicitly requires such behavior.

---

## 7.9 Analytical Readiness Validation

For every N:1 fact→dimension join path defined in `semantic_model.yaml`, execute:

```sql
SELECT COUNT(*) AS matched_rows
FROM {fact_table} f
INNER JOIN {dimension_table} d
  ON f.{fk_column} = d.{pk_column}
```

Expected:

```text
matched_rows > 0
```

This is distinct from orphan detection (§7.4). Orphan detection uses LEFT ANTI JOIN to find unmatched children. Analytical readiness confirms that **positive join results exist** — the data will actually produce output when queried through a Metric View.

For every multi-hop join path (e.g., detail → header → member), also validate the full chain:

```sql
SELECT COUNT(*) AS chain_matched
FROM {leaf_fact} l
INNER JOIN {intermediate} i ON l.{fk1} = i.{pk1}
INNER JOIN {terminal_dim} d ON i.{fk2} = d.{pk2}
```

If `matched_rows = 0` for any required analytical join:

```text
ANALYTICAL_JOIN_FAILURE
```

Root cause is typically:

- FK column populated with values not present in parent PK (random generation);
- datatype mismatch between FK and PK (e.g., STRING FK vs BIGINT PK);
- FK column is entirely NULL.

This validation MUST pass before the data layer is declared successful. Zero-row analytical joins render downstream Metric Views, dashboards, and Genie non-functional.

---

# Step 8: Validation Report

Write:

```text
{workspace.output_folder}/data_layer_validation.yaml
```

with:

```yaml
status: PASS | FAIL

schema:
  tables_expected:
  tables_created:
  missing_tables:
  unexpected_tables:

primary_keys:
  tested:
  failures:

foreign_keys:
  tested:
  orphan_counts:
  failures:

cardinality:
  tested:
  failures:

join_stability:
  tested:
  fanout_failures:

semantic_constraints:
  tested:
  failures:

data_quality:
  null_violations:
  generic_fallback_columns:
  unusable_dimension_columns:
```

The stage succeeds only when mandatory structural checks pass.

> **PROGRESS REPORT:** After validation completes, call `report_progress` with:
> - `phase_id`: "validate_data"
> - `phase_name`: "Validate Data"
> - `status`: "completed"
> - `findings`: ["PK validation: {PASS/FAIL}", "FK validation: {PASS/FAIL}", "Join stability: {PASS/FAIL}"]
> - `stats`: {"pk_tests": N, "fk_tests": N, "pk_failures": 0, "fk_failures": 0}
> - `happenings`: ["Validated primary key uniqueness", "Checked FK referential integrity", "Tested join fanout stability"]

---

# Step 9: Present Final Summary

Present:

| Category | Result |
|---|---|
| ERD tables parsed | count |
| Tables created | count |
| Semantic facts/events | count |
| Dimensions/reference tables | count |
| PK validations | PASS/FAIL |
| FK validations | PASS/FAIL |
| Cardinality validations | PASS/FAIL |
| Join fanout validations | PASS/FAIL |
| Synthetic semantic validations | PASS/FAIL |
| Overall | PASS/FAIL |

Also report unresolved ERD interpretations and any `GENERIC_FALLBACK` synthetic columns.

---

# Failure Classification

Never fix an error by changing the architecture until the root cause has been classified.

Use one of:

```text
ERD_EXTRACTION_ERROR
SCHEMA_CONTRACT_ERROR
GRAIN_INFERENCE_ERROR
RELATIONSHIP_ERROR
DDL_GENERATION_ERROR
DBLDATAGEN_API_ERROR
TYPE_SAFETY_ERROR
SYNTHETIC_GENERATION_ERROR
PRIMARY_KEY_INTEGRITY_ERROR
FOREIGN_KEY_INTEGRITY_ERROR
CARDINALITY_ERROR
JOIN_FANOUT_ERROR
SEMANTIC_DATA_ERROR
WORKSPACE_IO_ERROR
```

For any failure report:

```text
Observed problem:
Root cause:
Authoritative evidence:
Corrective action:
Affected downstream artifacts:
```

Do not use repeated guess-and-retry behavior.

---

# Pipeline Halt Rules

Immediately halt with:

```text
❌ EXECUTION HALTED
```

when any of the following occurs:

- ERD image cannot be read;
- vision model is unavailable;
- required table/column extraction is unresolved enough to prevent DDL generation;
- a required FK relationship cannot be established;
- DDL execution fails;
- dbldatagen produces datatype conflicts;
- duplicate generator definitions are detected;
- required PK validation fails;
- required FK validation fails;
- unexpected join fanout occurs;
- generated tables do not match the canonical schema contract.

---

# Non-Negotiable Rules

1. **ERD image is the authoritative physical-schema input.**
2. **Do not reuse previous generated schema artifacts as schema evidence.**
3. **Unknown is better than invented.**
4. **Every table must have an explicitly documented grain.**
5. **Never create a relationship from column-name similarity alone.**
6. **Never invent columns or surrogate keys to make generation easier.**
7. **Generate parent entities before dependent entities.**
8. **Foreign keys must reuse generated parent key domains.**
9. **Never independently random-generate both sides of a PK/FK relationship.**
10. **Every DDL column receives exactly one effective generation definition.**
11. **Use `base_generator()` for every table with `unique_columns` listing PK and FK-target columns.**
12. **ALWAYS call `enforce_varchar_limits(df, table_name)` AFTER `gen.build()` and AFTER any FK column replacement, BEFORE `.write`. This is the LAST transformation before writing to Delta. Without it, dbldatagen may generate values exceeding VARCHAR(N) constraints — especially for short columns (VARCHAR(2-6)) where uniqueValues exceeds the template capacity.**
13. **Use the project templates; do not recreate equivalent notebooks.**
14. **Always use version-aware `TABLES[...]` references.**
15. **Always disable Spark ANSI mode before dbldatagen generation.**
16. **Notebook execution success is not data validation success.**
17. **Structural integrity must be proven deterministically.**
18. **Semantic realism should be inferred from the current model and use case, not from hardcoded domain assumptions.**
19. **Do not let downstream requirements alter the canonical ERD schema.**
20. **Use Workspace APIs / agent tools for `/Workspace/`; never `dbutils.fs`.**
21. On mandatory validation failure return:

```text
❌ EXECUTION HALTED
```