# Create Genie Space

## Role

You are a senior Databricks Genie architect and semantic analytics engineer.

Create a production-quality **Databricks Genie Space / Genie Agent** for natural-language analytics over validated Metric Views.

The Genie configuration must be:

* grounded only in validated Metric Views and dimensions;
* aligned with the KPI specification;
* configured with high-quality business instructions;
* populated with representative sample questions;
* supplied with accurate example SQL;
* benchmarked with analytically meaningful questions;
* deployed through the official Databricks Genie management API;
* retrieved and validated after deployment.

The objective is NOT merely to create a Genie Space that exists.

The objective is to create a Genie Space that is:

```text
SEMANTICALLY GROUNDED
+
CONFIGURED
+
DEPLOYED
+
BENCHMARKED
+
VALIDATED
```

A title-only or minimally configured Genie Space is invalid.

---

# Core Principle

Genie must consume validated semantic assets.

The dependency chain is:

```text
KPI specification
        +
kpi_metric_mapping.yaml
        +
metric_view_design.yaml
        +
metric_view_validation.yaml
        ↓
Validated Genie semantic inventory
        ↓
Genie instruction design
        ↓
Sample questions
        ↓
Example question SQL
        ↓
Benchmark questions
        ↓
serialized_space
        ↓
Genie Create / Update API
        ↓
Get Genie Space
        ↓
Persisted configuration validation
        ↓
Benchmark validation
```

Do not skip stages.

---

# Critical Ownership Boundary

The Genie stage MUST NOT redefine metric semantics.

The Metric View layer owns:

* KPI formulas;
* aggregation semantics;
* fact grain;
* numerator/denominator logic;
* dimensional relationships;
* validated measures;
* validated dimensions.

The Genie layer owns:

* natural-language interpretation guidance;
* semantic descriptions;
* terminology and synonyms;
* question examples;
* SQL examples;
* benchmark questions;
* instructions for how users should query the validated semantic model.

If a required KPI, measure, dimension, or relationship is missing or invalid:

```text
DO NOT REPAIR IT INSIDE GENIE
```

Return the issue to the Metric View layer.

Do not compensate by querying raw tables or recreating KPI formulas inside Genie examples.

---

## State & Checkpoint Contract

This step uses **artifact-as-state** checkpointing (see `07_state_contract.md`).
The same rules apply in App mode and Genie Code — no backend infrastructure required.

**Before executing each phase**, check whether its output artifact already exists.
If it exists and is structurally valid → **skip** that phase and call `report_progress(status="completed")` immediately.
If it does not exist → execute the phase normally.

**Verification flow (run at the START of this step, after loading config):**

1. List the output folder.
2. Manage `run_context.yaml` per `07_state_contract.md` Section 8.
3. For each artifact below, apply ONE cheap check:
   - `genie_semantic_inventory.yaml` exists: skip build_inventory
   - Genie manifest (`*_genie_manifest.json`) exists with `space_id` field: skip create_genie_space
   - `genie_benchmark_validation.yaml` exists: skip validate_genie
4. Continue from the **first phase whose artifact is missing**.
5. Maintain `run_context.yaml` at each phase boundary (see contract).

**Rules:**

- Every `report_progress(status="completed")` marks a phase as done.
- **Never re-execute a phase whose output artifact already exists and is structurally valid.**
- For Genie spaces: if manifest contains a valid `space_id`, **UPDATE** the existing space rather than creating a new one.
- If `RESUME_CONTEXT` is provided (App mode), use it to accelerate. Otherwise, discover state from the output folder.

**Artifact-as-State mapping:**

| Phase | Artifact | Skip when |
|-------|----------|----------|
| load_config | Config + contracts loaded | Always re-read (stateless) |
| build_inventory | genie_semantic_inventory.yaml | file exists |
| create_genie_space | *_genie_manifest.json | file exists + contains space_id |
| validate_genie | genie_benchmark_validation.yaml | file exists |

---

# KPI-Driven Genie Design (Mandatory)

Genie Space configuration is ENTIRELY driven by two sources:

```text
Source 1: KPI Spec + metric_view_validation.yaml
  → defines WHICH KPIs are available (only IMPLEMENTED_AND_VALIDATED)
  → defines business descriptions and terminology
  → defines expected analytical questions
  → defines dimensional slicing requirements

Source 2: Metric View DESCRIBE output (Step 2)
  → defines ACTUAL column names for SQL
  → defines data types and value ranges
  → defines which columns are dimensions vs measures
  → defines actual categorical values for filter examples
```

The Genie configuration is the INTERSECTION of these two sources:

```text
KPI Spec says: "Users should be able to ask about denial rates by LOB"
DESCRIBE says: measure=denial_rate, dimension=line_of_business, values=['Commercial','Medicare','Medicaid']
→ Instruction: "denial_rate measures the percentage of denied claim lines. Can be grouped by line_of_business."
→ Sample question: "What is the denial rate for Commercial claims?"
→ Example SQL: SELECT MEASURE(denial_rate) FROM mv WHERE line_of_business = 'Commercial'
```

### Prohibited (No Making Things Up)

```text
✗ Inventing KPIs not in metric_view_validation.yaml
✗ Inventing dimensions not in DESCRIBE output
✗ Inventing filter values not discovered during profiling
✗ Using assumed column names (service_month, claim_month, etc.) without DESCRIBE verification
✗ Generating sample questions about measures/dimensions that don't exist
✗ Including example SQL that hasn't been validated on the warehouse
✗ Adding instructions about capabilities the metric view doesn't support
```

Every instruction, sample question, and example SQL must trace back to either the KPI spec or the DESCRIBE output. If it can't be traced, it must not be included.

---

# Step 1: Load Inputs

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "load_inputs"
> - `phase_name`: "Load Inputs"
> - `status`: "started"
> - `current_task`: "Loading configuration and semantic contracts"
> - `happenings`: ["Reading accelerator.yaml", "Loading metric view contracts", "Resolving Genie configuration"]

Read:

```text
accelerator.yaml
```

with version/suffix resolution applied.

Load the **Genie Space configuration contract** (`genie_space_configuration.md`):

1. **Check first:** If the system message already contains a section labeled
   `--- BEGIN inputs/genie_space_configuration.md ---` (injected as SUPPLEMENTARY REFERENCE),
   the file is already loaded — skip the read and proceed.
2. **Otherwise read it** from:
   ```text
   {deploy_root}/framework/inputs/genie_space_configuration.md
   ```

This file is mandatory.

It is the project-level contract for:

* Genie `serialized_space` construction;
* template structure;
* configuration fields;
* API helper usage;
* validation expectations;
* forbidden shortcuts.

Do not construct `serialized_space` from model memory.

### If `genie_space_configuration.md` is missing

If the file is neither in the system supplement NOR readable from the path above:

```text
❌ EXECUTION HALTED
Required configuration file not found: genie_space_configuration.md
Cannot construct serialized_space without project-level serialization contract.
```

Do not fall back to guessing the serialized_space format. This file defines the exact payload structure, API field names, and helper function contracts that vary between projects.

---

# Step 1.1: Load Semantic Contracts

Read when available:

```text
{workspace.output_folder}/schema_profile.yaml
{workspace.output_folder}/kpi_metric_mapping.yaml
{workspace.output_folder}/metric_view_design.yaml
{workspace.output_folder}/metric_view_validation.yaml
```

These artifacts are authoritative outputs from the Metric View stage.

Metric Views must already exist.

If required Metric Views are missing:

```text
RUN 02_create_metric_views.md
```

before continuing.

---

# Step 1.2: Determine Eligible Semantic Assets

Only consume Metric Views that were successfully created and validated.

For KPIs, only use:

```text
IMPLEMENTED_AND_VALIDATED
```

KPIs from:

```text
metric_view_validation.yaml
```

Do NOT include skipped or failed KPIs in:

* Genie instructions;
* sample questions;
* SQL examples;
* benchmarks.

Do NOT silently repair failed KPIs in Genie.

---

# Step 1.3: Resolve Runtime Configuration

Read:

```text
sql_warehouse_id
workspace.current_user.userName
workspace.host
```

from `databricks.yml` / resolved runtime configuration.

Resolve:

```text
SPACE_TITLE
SPACE_DESCRIPTION
WAREHOUSE_ID
PARENT_PATH
VERSION_SUFFIX
```

using accelerator naming rules.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "load_inputs"
> - `phase_name`: "Load Inputs"
> - `status`: "completed"
> - `findings`: ["{N} semantic assets eligible", "Runtime configuration resolved"]
> - `stats`: {"metric_views_loaded": N, "tables_eligible": M}

---

# Step 2: Profile Validated Metric Views

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "profile_metrics"
> - `phase_name`: "Profile Metrics"
> - `status`: "started"
> - `current_task`: "Building semantic inventory for Genie"
> - `happenings`: ["Querying metric view schemas", "Building Genie semantic inventory"]

## CRITICAL — Fast Path (saves 10+ tool calls)

When prior-step artifacts exist (`metric_view_design.yaml`, `metric_view_validation.yaml`, `schema_profile.yaml`):

1. These files ALREADY contain all measures, dimensions, types, and KPI mappings.
2. Run ONE combined SQL for row counts + sample categorical values:
   ```sql
   SELECT 'mv1' AS mv, COUNT(*) AS rows FROM catalog.schema.metric_view_1
   UNION ALL
   SELECT 'mv2', COUNT(*) FROM catalog.schema.metric_view_2
   ```
3. If any row count = 0, HALT (Zero-Data Guard).
4. Run ONE SQL per metric view for categorical profiling (batch dimensions):
   ```sql
   SELECT 'claim_type' AS dim, claim_type AS val FROM metric_view GROUP BY claim_type LIMIT 10
   UNION ALL
   SELECT 'line_status', line_status FROM metric_view GROUP BY line_status LIMIT 10
   UNION ALL ...
   ```
5. Write `genie_semantic_inventory.yaml` directly from contract files + profiling.
6. Call `report_progress(profile_metrics, completed)` immediately.

**DO NOT** call DESCRIBE TABLE on each metric view individually when `metric_view_design.yaml` already provides the full column inventory.

## Full Profiling (fallback only — when contracts are missing)

Profile every Metric View intended for the Genie Space.

Use:

```sql
DESCRIBE TABLE EXTENDED <metric_view_fqn>
```

and representative queries.

Build an inventory of:

* validated measures;
* validated dimensions;
* time dimensions;
* categorical values;
* units/formats;
* supported groupings;
* common terminology;
* KPI mappings.

Do NOT infer new measure definitions from profiling.

Metric semantics come from the Metric View contracts.

### Zero-Data Guard

For every Metric View intended for the Genie Space, execute:

```sql
SELECT COUNT(*) FROM <metric_view_fqn>
```

If result = 0:

```text
❌ EXECUTION HALTED
Metric View contains no data: {metric_view_fqn}
Genie example SQL and benchmarks will produce empty results.
Return to data layer / metric view validation.
```

Do not proceed to build instructions, examples, or benchmarks against an empty Metric View.

---

# Step 2.1: Build Genie Semantic Inventory

Create:

```text
{workspace.output_folder}/genie_space/genie_semantic_inventory.yaml
```

containing:

```yaml
metric_views:

  - fqn:
    description:

    measures:
      - name:
        description:
        datatype:
        aggregation_semantics:
        kpis_supported:
        synonyms: []

    dimensions:
      - name:
        description:
        datatype:
        sample_values:
        synonyms: []

validated_kpis:

  - name:
    definition:
    metric_view:
    measure:
    dimensions:
    time_dimension:

unsupported_kpis: []
```

This artifact becomes the source of truth for Genie configuration generation.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "profile_metrics"
> - `phase_name`: "Profile Metrics"
> - `status`: "completed"
> - `findings`: ["{N} measures inventoried", "{D} dimensions cataloged"]
> - `stats`: {"measures": N, "dimensions": D}

---

# Step 3: Design Genie Instructions

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "design_instructions"
> - `phase_name`: "Design Instructions"
> - `status`: "started"
> - `current_task`: "Building Genie instructions, samples, and descriptions"
> - `happenings`: ["Writing system instructions", "Generating sample questions", "Creating metric descriptions"]

Generate `GENERAL_INSTRUCTIONS` from:

```text
genie_semantic_inventory.yaml
+
KPI specification
+
metric_view_design.yaml
```

Do not use generic boilerplate unrelated to the current domain.

Instructions should help Genie understand:

* the analytical domain;
* authoritative Metric Views;
* measure meanings;
* dimensional meanings;
* business terminology;
* common synonyms;
* time interpretation;
* metric-selection rules;
* ambiguity resolution;
* expected use of `MEASURE()`.

### Critical: Instructions String Format

The Genie Space API `text_instructions[].content[]` field truncates at newline characters (`\n`). Instructions MUST be a single continuous string with NO newline characters.

Use spaces and sentence structure for readability instead of line breaks:

```text
✓ "You are an analytics assistant. MEASURES: total_paid (sum of paid amounts), ... DIMENSIONS: service_date (DATE), ..."
✗ "You are an analytics assistant.\nMEASURES:\n- total_paid\n- ..."  ← TRUNCATED after first line
```

If instructions are < 500 chars after deployment, the content was likely truncated by newlines.

---

# Step 3.1: Instruction Requirements

Instructions must clearly state:

1. Which Metric Views are authoritative.

2. Which measures are available.

3. What each measure means.

4. Which dimensions can be used for:

   * filtering;
   * grouping;
   * slicing.

5. How time questions should map to available date/time dimensions.

6. How ambiguous business terms should be interpreted when supported by the KPI specification.

7. That validated measures must be queried using Metric View semantics.

8. That raw source-table reconstruction of validated KPIs is prohibited.

---

# Do Not Over-Instruct

Do not create instructions that:

* restate every SQL query;
* encode hundreds of brittle column-specific rules;
* invent business rules not present in the KPI/semantic contracts;
* tell Genie to guess missing relationships;
* duplicate Metric View formulas.

The Metric View remains the semantic computation layer.

Genie instructions should guide interpretation, not recreate the semantic model.

---

# Step 4: Create Metric View Descriptions

Generate:

```text
METRIC_VIEW_DESCRIPTIONS
```

for every attached Metric View.

Descriptions should explain:

```text
business purpose
primary analytical grain
major measure families
major dimensions
typical questions answered
```

Do not simply repeat the FQN or table name.

Example conceptual format:

```python
{
    "catalog.schema.metric_view": (
        "Provides validated analytical measures for ... "
        "at the ... grain, with dimensions for ..."
    )
}
```

Keys must be deterministic and sorted where required by the template.

---

# Step 5: Generate Sample Questions

Generate representative natural-language questions based only on:

```text
IMPLEMENTED_AND_VALIDATED KPIs
+
validated dimensions
+
validated measures
```

Target:

```text
15–20 sample questions
```

when enough semantic coverage exists.

Do not artificially generate 15 low-quality duplicates solely to satisfy count requirements.

If fewer meaningful combinations exist, report the limitation and follow the configured minimum validation policy.

---

# Step 5.1: Sample Question Coverage

Questions should collectively cover:

* headline measures;
* time trends;
* dimension breakdowns;
* filtered analysis;
* rankings / Top-N where appropriate;
* comparisons;
* ratios where validated;
* multiple measures where analytically meaningful.

Avoid superficial paraphrase duplication.

Bad:

```text
What is total revenue?
Show total revenue.
Tell me total revenue.
How much total revenue?
```

These count as essentially one semantic pattern.

Prefer diversity of analytical intent.

### Question Quality Criteria

Every sample question must be:

1. **Answerable** — resolvable to one SQL query against the validated Metric View.
2. **Specific** — specifies a concrete analytical intent (not "tell me about claims").
3. **Grounded** — references only measures/dimensions in `genie_semantic_inventory.yaml`.
4. **Distinct** — tests a different analytical pattern than other questions in the set.
5. **Natural** — phrased as a business user would ask (not SQL syntax disguised as English).

Bad:

```text
"Show me the MEASURE(total_paid) grouped by claim_type"  ← SQL disguised as English
"Tell me about the data"  ← not specific
"What is the YTD revenue adjusted for inflation?"  ← not answerable (no inflation measure)
```

Good:

```text
"What is the average paid amount per claim this year?"
"Which states have the highest denial rate?"
"How has PMPM trended over the last 12 months?"
```

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "design_instructions"
> - `phase_name`: "Design Instructions"
> - `status`: "completed"
> - `findings`: ["Instructions generated", "{N} sample questions created", "Metric descriptions written"]
> - `stats`: {"sample_questions": N, "metric_descriptions": M}

---

# Step 6: Generate Example Question SQL

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "generate_sql"
> - `phase_name`: "Generate SQL & Benchmarks"
> - `status`: "started"
> - `current_task`: "Generating example SQL and benchmark questions"
> - `happenings`: ["Writing example SQL queries", "Validating SQL execution", "Generating benchmark ground truth"]

Generate:

```text
EXAMPLE_QUESTION_SQLS
```

using validated Metric Views only.

Target:

```text
15–20 examples
```

where meaningful.

Every SQL example MUST execute successfully before inclusion.

---

# Step 6.1: SQL Rules

Use:

```sql
MEASURE(...)
```

for Metric View measures.

Use the Metric View's validated dimensions.

Do NOT:

* query raw source tables to recreate KPIs;
* invent columns;
* invent joins;
* bypass Metric View calculations;
* use measures that failed validation.

Use:

```sql
GROUP BY ALL
```

where appropriate and required by project conventions.

### Reference SQL Patterns for Example Questions

**CRITICAL: Column names below are PATTERNS ONLY. Replace with actual measure/dimension names from DESCRIBE output (Step 2) and `genie_semantic_inventory.yaml`. Never assume a column exists — verify against the profiled inventory.**

```sql
-- Headline KPI ("What is total paid amount?")
SELECT MEASURE(total_paid) AS total_paid
FROM catalog.schema.metric_view

-- Time trend ("Show monthly paid trend")
-- NOTE: Use actual temporal dimension from DESCRIBE (e.g., service_date)
-- If monthly aggregation needed, use DATE_TRUNC:
SELECT DATE_TRUNC('MONTH', service_date) AS service_month, MEASURE(total_paid) AS total_paid
FROM catalog.schema.metric_view
GROUP BY ALL
ORDER BY service_month

-- Dimension breakdown ("Total paid by claim type")
SELECT claim_type, MEASURE(total_paid) AS total_paid
FROM catalog.schema.metric_view
GROUP BY ALL

-- Filtered ("Total paid for Medicare members")
-- NOTE: Use actual dimension values from profiling (Step 2)
SELECT MEASURE(total_paid) AS total_paid
FROM catalog.schema.metric_view
WHERE line_of_business = 'MEDICARE'

-- Top-N ("Top 5 states by claims count")
SELECT member_state, MEASURE(total_claims) AS total_claims
FROM catalog.schema.metric_view
GROUP BY ALL
ORDER BY total_claims DESC
LIMIT 5

-- Multi-measure ("Show paid and denied amounts by LOB")
SELECT line_of_business,
       MEASURE(total_paid) AS total_paid,
       MEASURE(denial_rate) AS denial_rate
FROM catalog.schema.metric_view
GROUP BY ALL
```

### Column Name Resolution (MANDATORY)

Do NOT copy these patterns verbatim. Every example SQL must use:

1. **Actual measure names** from `genie_semantic_inventory.yaml` (sourced from DESCRIBE)
2. **Actual dimension names** from `genie_semantic_inventory.yaml` (sourced from DESCRIBE)
3. **Actual filter values** from metric view profiling (Step 2)

Common violations that WILL cause SQL failures:

```text
✗ service_month     → does not exist; use DATE_TRUNC('MONTH', service_date) if MV has service_date
✗ claim_month       → does not exist; check DESCRIBE for actual temporal dimensions
✗ member_name       → may not exist; check DESCRIBE for actual column names
✗ 'MEDICARE'        → may not be a valid value; profile actual categorical values first
```

If a SQL pattern references a column that does not appear in `genie_semantic_inventory.yaml`, it is INVALID and must not be included.

---

# Step 6.2: SQL Validation (BATCH — saves 15+ tool calls)

**CRITICAL EFFICIENCY RULE:** Do NOT validate example SQL queries one-by-one. Batch them:

```sql
-- Validate all example SQLs in 2-3 batches
SELECT 'q1' AS qid, * FROM (SELECT MEASURE(total_paid) AS total_paid FROM metric_view) LIMIT 2
UNION ALL
SELECT 'q2', * FROM (SELECT claim_type, MEASURE(total_paid) AS total_paid FROM metric_view GROUP BY ALL) LIMIT 2
UNION ALL
... (group queries with compatible column shapes)
```

For queries with incompatible output shapes, group into 2-3 separate batch calls.

This reduces 15-20 individual `execute_sql` calls to 2-3 batched validations.

Use:

```text
sql_warehouse_id
```

Validate:

```text
SQL executes (no UNRESOLVED_COLUMN errors)
required measure exists
required dimensions exist
result is non-empty where data exists
result shape matches question
```

Failed SQL examples must be corrected or removed.

Never include untested example SQL.

---

# Step 7: Generate Benchmark Questions

Generate:

```text
BENCHMARK_QUESTIONS
```

using different wording and analytical formulations from the example questions.

Benchmarks should test whether Genie can generalize rather than memorize sample phrasing.

Target:

```text
15–20 benchmarks
```

subject to:

```text
validation.min_benchmark_questions
```

---

# Benchmark Design Principles

Benchmarks should include a mix of:

```text
DIRECT KPI
DIMENSION BREAKDOWN
TEMPORAL
FILTERED
COMPARISON
RANKING
MULTI-MEASURE
AMBIGUITY / SYNONYM
```

where supported.

Avoid benchmarks that depend on:

* unavailable measures;
* unsupported dimensions;
* raw-table semantics;
* business rules absent from the semantic model.

---

# Step 8: Benchmark Ground Truth

Where the template/configuration supports expected SQL or expected analytical output, derive benchmark ground truth from the validated Metric Views.

Do not use LLM-generated expected values without executing the authoritative query.

Conceptually:

```text
BENCHMARK QUESTION
        ↓
authoritative Metric View SQL
        ↓
expected semantics/result
```

Store benchmark ground truth in the format required by:

```text
genie_space_configuration.md
```

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "generate_sql"
> - `phase_name`: "Generate SQL & Benchmarks"
> - `status`: "completed"
> - `findings`: ["{N} example queries validated", "{B} benchmark questions generated"]
> - `stats`: {"example_queries": N, "benchmarks": B, "sql_validations_passed": V}

---

# Step 9: Create Configuration Notebook

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "create_genie_space"
> - `phase_name`: "Create Genie Space"
> - `status`: "started"
> - `current_task`: "Creating Genie space via API"
> - `happenings`: ["Building configuration notebook", "Constructing space payload", "Calling Genie API"]

Create:

```text
{workspace.output_folder}/genie_space/{assets.genie.notebook_name}
```

using:

* Workspace `import` with `format: JUPYTER`; or
* approved notebook agent tools.

Never use `dbutils.fs` for `/Workspace/`.

Delete/replace an existing notebook at the exact versioned path only when required by the accelerator's idempotency rules.

---

# Step 9.1: Template-First Notebook Construction

Read:

```text
{EXAMPLE_DIR}/{templates.genie_notebook}
```

The configured template is mandatory.

Populate configured cells from the template.

Do NOT create an equivalent notebook from scratch.

---

# Step 9.2: Replace Configurable Cells

Populate cells 1–7 according to the template contract.

Typical responsibilities:

| Cell | Responsibility              |
| ---- | --------------------------- |
| 1    | Domain/context metadata     |
| 2    | Space runtime configuration |
| 3    | General instructions        |
| 4    | Metric View descriptions    |
| 5    | Sample questions            |
| 6    | Example question SQL        |
| 7    | Benchmarks                  |

Remove all:

```text
<<< REPLACE >>>
```

placeholders.

No configuration cell may retain unresolved placeholder text.

---

# Step 9.3: Infrastructure Cells

Copy infrastructure/helper cells from the configured template exactly where required.

Do not hand-write equivalent API payload logic when the template already provides validated helper functions.

However, the final API operation MUST conform to the official Databricks Genie management API contract.

---

# Step 10: Build serialized_space

Construct:

```text
serialized_space
```

using the builder/helper defined in:

```text
genie_space_configuration.md
```

and the configured template.

### Authoritative Schema Reference

The `serialized_space` JSON schema is defined in the official Databricks documentation:

```text
https://docs.databricks.com/aws/en/genie-agents/conversation-api#understanding-the-serialized_space-field
```

Consult this reference for:

* the complete field structure (version, config, data_sources, instructions, benchmarks);
* required vs optional fields;
* correct nesting and array formats;
* field semantics and behavior.

Do NOT construct the payload from LLM memory or prior examples alone. Always validate against the current docs schema.

### Required Sections

The serialization must include all required configuration, including the appropriate combination of:

```text
version (currently 2)
config.sample_questions
data_sources.tables (metric views are listed here)
instructions.text_instructions
instructions.example_question_sqls
benchmarks.questions
```

as defined by the current project contract and the docs schema.

### Critical API Behaviors (Learned from Deployment)

| Field | Behavior | Fix |
|-------|----------|-----|
| `data_sources` | Key is `tables` (NOT `metric_views`) — metric views are listed under `tables[]` | Always use `data_sources.tables[]` |
| `text_instructions[].content[]` | API truncates at newline characters (`\n`) — only the first line is persisted | Instructions MUST be a single continuous string with no `\n` |
| `column_configs[]` | Must be sorted alphabetically by `column_name` or API rejects with InvalidParameterValue | Sort before submission |
| All IDs | Must be 32-character lowercase hex UUIDs | Use `uuid.uuid4().hex` |
| All text fields | Wrapped in arrays `["text"]` | Never use bare strings |

Do not infer serialized-space JSON structure from memory.

---

# Step 10.1: Preflight Validation

Before invoking the Create or Update API validate:

```text
serialized_space exists
serialized_space is non-empty
Metric View references exist
instructions are populated
sample questions meet configured minimum
example SQL meets configured minimum
benchmarks meet configured minimum
all example SQL was executed successfully
no template placeholders remain
WAREHOUSE_ID is populated
SPACE_TITLE is populated
```

If preflight fails:

```text
GENIE_SERIALIZATION_VALIDATION_FAILURE
```

Do NOT call the API.

---

# Step 11: Resolve Existing Genie Space

Use the official Genie management APIs or approved SDK/API client to determine whether the resolved space already exists.

Do not use UI shortcuts.

Do not use `createAsset`.

Do not issue a blank/bare Create Space call.

Use version-aware identity rules from the accelerator.

### Matching Strategy

To determine if the resolved Genie Space already exists:

1. Check if a previous manifest exists at `{workspace.output_folder}/genie_space/{space_name}_manifest.json` — if so, extract `space_id` and GET it.
2. If no manifest, list existing Genie Spaces and match by `title` (case-insensitive exact match against the resolved `SPACE_TITLE` with VERSION_SUFFIX).
3. If a match is found: use UPDATE flow.
4. If no match: use CREATE flow.

Do not match by partial title or substring. The full versioned title is the identity key.

---

# Idempotency Strategy

Preferred:

```text
existing matching space
        ↓
GET existing space
        ↓
UPDATE with full serialized_space
```

when updating the same resolved asset.

For a new versioned name:

```text
CREATE new space
```

Do not delete older versions unless explicitly required.

Do not delete an existing configured Genie Space merely to achieve idempotency when Update can safely replace its configuration.

---

# Step 12: Create Genie Space Through Official API

For a new space use the official Databricks Genie Create Space API.

Conceptually:

```text
POST /api/2.0/genie/spaces
```

using the request contract defined by the current Databricks API.

The creation request MUST include a complete:

```text
serialized_space
```

payload.

A Create call without full configuration is prohibited.

Databricks' Create Genie Space API is the deployment authority.

Do not use UI creation or generic workspace-asset creation as a substitute.

---

# Step 12.1: Create Response Validation

Capture:

```text
space_id
title
warehouse_id
API status
```

and any other returned identity/version information.

Creation is successful only when a valid:

```text
space_id
```

is returned.

---

# Step 13: Update Existing Genie Space

When the resolved Genie Space already exists and should be updated, use the official Genie Update Space API with the full intended configuration.

Treat `serialized_space` update semantics according to the API contract.

Do not assume patch/merge behavior when the API defines full replacement semantics.

Retrieve the existing configuration first when necessary.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "create_genie_space"
> - `phase_name`: "Create Genie Space"
> - `status`: "completed"
> - `findings`: ["Genie space created successfully", "Space ID: {space_id}"]
> - `stats`: {"tables_registered": N, "instructions_set": 1}

---

# Step 14: GET Persisted Genie Space

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_genie"
> - `phase_name`: "Validate Genie Space"
> - `status`: "started"
> - `current_task`: "Validating configuration and running benchmarks"
> - `happenings`: ["Checking persisted configuration", "Running benchmark questions", "Validating semantic coverage"]

Immediately after Create or Update, call the official Get Genie Space API.

Retrieve the persisted:

```text
serialized_space
```

and metadata.

The persisted configuration is authoritative after deployment.

Do not assume the request payload was stored exactly as intended.

---

# Step 14.1: Persisted Configuration Validation

Compare:

```text
INTENDED CONFIGURATION
vs
PERSISTED GENIE CONFIGURATION
```

Validate at minimum:

```text
space ID
title
warehouse
attached Metric Views
instructions
sample questions
example SQL
benchmark inventory
```

Do not require byte-for-byte JSON equality if the service normalizes serialization.

Validate semantically important structure.

Failure:

```text
PERSISTED_GENIE_CONFIGURATION_MISMATCH
```

---

# Step 15: Configuration Quality Validation

Validate:

```text
Metric Views attached >= 1
all Metric Views expected for this space are attached
instructions length >= configured minimum
sample questions >= configured minimum
example SQL examples >= configured minimum
benchmark questions >= validation.min_benchmark_questions
```

Do not hardcode `500`, `15`, or `20` where accelerator configuration already provides the minimum.

Use configured minimums when present.

Fallback defaults may be used only if the project contract explicitly defines them.

---

# Step 16: Semantic Coverage Validation

Validate that the Genie configuration covers the available semantic model.

Report coverage for:

```text
validated measures
validated dimensions
validated KPI families
temporal dimensions
major synonyms
```

Do not require every measure/dimension to appear in an example if doing so creates meaningless examples.

However, all major user-facing semantic concepts must be represented in:

```text
instructions
descriptions
examples
or benchmarks
```

---

# Step 17: Benchmark Validation

Run or evaluate benchmarks using the project's supported validation mechanism.

For every benchmark capture:

```yaml
question:
expected_semantics:
actual_result:
status:
failure_reason:
```

Where API/conversation execution is available, test Genie itself rather than only validating benchmark count.

Benchmark presence alone is NOT sufficient.

### Pass Rate Threshold

Benchmark validation status:

```text
pass_rate >= 80%  → PASS
pass_rate >= 60%  → WARN (proceed but document gaps)
pass_rate < 60%   → FAIL (trigger Step 18 correction cycle)
```

Override these thresholds when `accelerator.yaml` provides explicit `validation.benchmark_pass_rate` configuration.

A FAIL status triggers the iterative correction in Step 18 (max 3 cycles). If 3 correction cycles cannot achieve >= 60%, HALT.

---

# Step 17.1: Benchmark Failure Classification

Classify benchmark failures as:

```text
QUESTION_INTERPRETATION_ERROR
METRIC_SELECTION_ERROR
DIMENSION_SELECTION_ERROR
FILTER_ERROR
TIME_INTERPRETATION_ERROR
SQL_GENERATION_ERROR
UNSUPPORTED_QUESTION
AMBIGUOUS_QUESTION
```

Do not immediately alter Metric View definitions because Genie answered one benchmark incorrectly.

First identify whether the problem belongs to:

```text
Genie instructions
example SQL
synonyms
question ambiguity
or upstream metric semantics
```

---

# Step 18: Iterative Genie Quality Correction

If benchmarks fail:

1. identify the failure pattern;
2. determine the correct ownership layer;
3. correct only the responsible configuration;
4. rebuild `serialized_space`;
5. update through the official Genie Update Space API;
6. GET the persisted configuration again;
7. rerun affected benchmarks.

Do NOT use blind retries.

Do NOT add arbitrary instructions after every failure.

Changes must address an identified failure pattern.

---

# Step 19: Persist SPACE_ID

After successful Create/Update and validation:

persist the returned:

```text
SPACE_ID
```

in the configuration notebook's runtime/configuration cell when the template requires it.

This supports deterministic future updates.

---

# Step 20: Notebook Validation

The notebook deliverable must:

```text
exist at configured path
use the configured template
contain no unresolved placeholders
contain the deployed SPACE_ID
contain the final instructions
contain sample questions
contain tested example SQL
contain benchmarks
contain deployment/validation helpers
```

The notebook is an auditable configuration artifact.

The live Genie Space remains the deployed runtime asset.

---

# Step 21: Genie Validation Artifact

Write:

```text
{workspace.output_folder}/genie_space/{space_name}_validation.yaml
```

containing:

```yaml
space:
  space_id:
  title:
  warehouse_id:
  status:

metric_views:
  expected:
  actual:
  status:

instructions:
  character_count:
  status:

sample_questions:
  count:
  status:

example_sql:
  count:
  executed:
  failed:
  status:

benchmarks:
  count:
  passed:
  failed:
  pass_rate:
  status:

semantic_coverage:
  measures:
  dimensions:
  kpis:

api:
  create_status:
  update_status:
  get_status:

persisted_configuration:
  status:

overall_status:
  PASS | FAIL
```

---

# Step 22: Manifest

Write:

```text
{workspace.output_folder}/genie_space/{space_name}_manifest.json
```

containing:

```json
{
  "space_id": "...",
  "title": "...",
  "warehouse_id": "...",
  "metric_views": [],
  "sample_question_count": 0,
  "example_sql_count": 0,
  "benchmark_count": 0,
  "notebook_path": "...",
  "validated": true
}
```

Use Workspace API / agent tools.

Never use `dbutils.fs` for `/Workspace/`.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_genie"
> - `phase_name`: "Validate Genie Space"
> - `status`: "completed"
> - `findings`: ["Configuration validated", "Benchmark accuracy: {pct}%", "Semantic coverage: {cov}%"]
> - `stats`: {"benchmarks_passed": P, "benchmarks_total": T, "coverage_pct": C}

---

# Step 23: Final Status

Report:

| Check                           | Result    |
| ------------------------------- | --------- |
| Validated Metric Views attached | PASS/FAIL |
| Instructions populated          | PASS/FAIL |
| Sample question quality         | PASS/FAIL |
| Example SQL execution           | PASS/FAIL |
| Benchmarks configured           | PASS/FAIL |
| Create/Update API               | PASS/FAIL |
| Persisted configuration GET     | PASS/FAIL |
| Benchmark execution             | PASS/FAIL |
| Overall                         | PASS/FAIL |

Include:

```text
space_id
```

for the deployed Genie Space.

---

# Forbidden

❌ `createAsset` for Genie Space creation

❌ UI "Create Genie Space" shortcuts as the deployment mechanism

❌ bare:

```text
POST /api/2.0/genie/spaces
```

without a complete `serialized_space`

❌ hand-written serialized-space payloads that bypass the project builder

❌ querying raw source tables to recreate Metric View KPIs

❌ using skipped/unvalidated KPIs in sample questions

❌ including untested SQL examples

❌ notebook containing unresolved placeholders

❌ declaring success based only on a returned `space_id`

❌ declaring quality success based only on benchmark count

❌ blind retries with arbitrary instruction changes

---

# Error Classification

Use one of:

```text
GENIE_INPUT_ERROR
METRIC_VIEW_NOT_VALIDATED
GENIE_SEMANTIC_INVENTORY_ERROR
GENIE_INSTRUCTION_ERROR
SAMPLE_QUESTION_ERROR
EXAMPLE_SQL_ERROR
BENCHMARK_DESIGN_ERROR
BENCHMARK_EXECUTION_ERROR
GENIE_SERIALIZATION_ERROR
GENIE_API_CREATE_ERROR
GENIE_API_UPDATE_ERROR
GENIE_API_GET_ERROR
PERSISTED_GENIE_CONFIGURATION_MISMATCH
WORKSPACE_IO_ERROR
```

For every error report:

```text
Observed problem:
Root cause:
Authoritative evidence:
Affected KPI(s):
Affected Metric View(s):
Corrective action:
Affected downstream artifacts:
```

---

# Retry Policy

Blind retry behavior is prohibited.

Do NOT:

```text
create
fail
change random serialized_space
retry
add arbitrary instruction
retry
```

Instead:

1. capture the complete API / SQL / benchmark failure;
2. classify it;
3. identify the responsible contract;
4. make a targeted correction;
5. rerun preflight validation;
6. call Update or Create again only after the correction is understood.

Maximum deployment attempts:

```text
3
```

Each attempt must have a documented cause and correction.

---

# Pipeline Halt Rules

Return:

```text
❌ EXECUTION HALTED
```

when a mandatory Genie Space cannot be reliably configured.

Halt conditions include:

* required Metric Views do not exist;
* required Metric Views are not validated;
* `serialized_space` cannot be constructed;
* no Metric View can be attached;
* example SQL consistently fails;
* required benchmark minimum cannot be met;
* Genie Create/Update API continues to fail after diagnosed corrections;
* persisted configuration does not contain required semantic assets;
* mandatory benchmark quality threshold fails after targeted corrections.

---

# Non-Negotiable Rules

1. **Genie consumes validated Metric Views; it does not redefine metrics.**
2. **Only `IMPLEMENTED_AND_VALIDATED` KPIs may drive Genie examples and benchmarks.**
3. **Do not repair Metric View issues in Genie SQL or instructions.**
4. **Use `MEASURE()` for validated Metric View measures.**
5. **Example SQL must execute successfully before inclusion.**
6. **Benchmark questions must test generalization, not just paraphrase samples.**
7. **Instructions should guide interpretation, not duplicate Metric View formulas.**
8. **Do not invent joins or source-table relationships inside Genie.**
9. **Use the configured Genie template and serialization builder.**
10. **Do not build `serialized_space` from model memory.**
11. **Use the official Databricks Genie Create Space API for new spaces.**
12. **Use the official Update Space API for existing spaces where appropriate.**
13. **Use Get Genie Space after Create/Update and validate persisted configuration.**
14. **A returned `space_id` does not prove correct configuration.**
15. **Benchmark count does not prove Genie quality.**
16. **Do not use `createAsset` as a Genie deployment mechanism.**
17. **Do not create title-only or blank spaces.**
18. **Do not use ad-hoc API calls that bypass the validated serialization contract.**
19. **Workspace file writes use `workspace_file_io.md`, never `dbutils.fs`.**
20. On unrecoverable mandatory failure:

```text
❌ EXECUTION HALTED
```
