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

## ENFORCEMENT HEADER

<!-- @enforcement
  pattern: notebook_execution_for_genie
  template_required: genie_notebook (templates.genie_notebook from accelerator.yaml, if configured)
  api_method: Genie Management API (POST /api/2.0/genie/spaces)
  gates:
    - id: semantic_inventory_built
      after_step: 2
      check: "Internal inventory of validated measures/dimensions exists"
    - id: instructions_designed
      after_step: 3
      check: "Genie instructions text is >= 200 characters with MEASURE() guidance"
    - id: sample_questions_ready
      after_step: 4
      check: "Sample questions count >= validation.min_benchmark_questions from config"
    - id: example_sql_validated
      after_step: 5
      check: "All example SQL queries execute without error"
    - id: genie_space_created
      after_step: 6
      check: "GET /api/2.0/genie/spaces/{id} returns valid response"
    - id: benchmark_passed
      after_step: 7
      check: "Benchmark results show >= 80% query success rate"
-->

---

## PROHIBITED ACTIONS (this entire step)

The following actions are STRICTLY FORBIDDEN:

1. **DO NOT create a blank or title-only Genie Space** — the space MUST have instructions, sample questions, AND example SQL
2. **DO NOT bypass the notebook template** — if `templates.genie_notebook` is configured, use it (read template, populate, execute)
3. **DO NOT hardcode domain-specific instructions** in the template — instructions are generated from the validated KPI/metric inventory
4. **DO NOT skip benchmark validation** — sample questions must be tested against the Genie space to verify it answers correctly
5. **DO NOT create sample questions that cannot be answered** by the metric view — every sample question must map to available measures/dimensions
6. **DO NOT use raw SQL in example queries** when `MEASURE()` syntax should be used — Genie must learn the metric view query pattern
7. **DO NOT skip the instruction quality check** — instructions must explicitly mention: measure names, dimension names, MEASURE() syntax rules, ratio non-additivity warnings
8. **DO NOT create fewer sample questions than `validation.min_benchmark_questions`** from accelerator.yaml
9. **DO NOT use `createAsset(assetType="genie")` as the deployment mechanism** — this creates a blank title-only space. Genie Spaces MUST be created via the official Genie Management API (`POST /api/2.0/genie/spaces`) with a complete `serialized_space` payload.
10. **DO NOT improvise or use custom logic** — this prompt defines the EXACT sequence. Do NOT substitute your own Genie Space creation workflow, skip gates, or collapse multiple steps into a single API call. Every numbered step exists because prior runs failed when it was skipped.
11. **DO NOT call the Genie Create/Update API before Steps 1-10 are complete** — the semantic inventory, instructions, sample questions, example SQL (validated), and benchmarks MUST all be designed and tested before constructing `serialized_space`. Jumping to API creation "because the space seems simple" produces blank or misconfigured spaces.
12. **DO NOT construct `serialized_space` from model memory** — ALWAYS read `genie_space_configuration.md` first and follow its exact payload structure. The JSON schema has non-obvious requirements (newline truncation, column_configs sorting, UUID format) that CANNOT be reliably inferred.
13. **DO NOT skip reading `genie_space_configuration.md`** — if this file is neither in the system supplement NOR readable from `{deploy_root}/framework/inputs/`, HALT immediately. Do NOT guess the payload format.
14. **DO NOT submit `serialized_space` with unsorted ID arrays** — ALL arrays containing `id` fields (`example_question_sqls`, `sample_questions`, `benchmarks.questions`, `text_instructions`) MUST be sorted by `id` ascending. The API rejects with `must be sorted by id` otherwise. Always call `sorted(items, key=lambda x: x['id'])` before serializing.
15. **DO NOT rely on `GET /api/2.0/genie/spaces/{id}` for content validation** — the GET response does NOT return `serialized_space` content. Validation must be based on successful POST acceptance (API returns 400 with specific error if payload is structurally invalid).
16. **DO NOT use assumed or semantic column names in example SQL** — ALWAYS use EXACT column names from `DESCRIBE TABLE` / `genie_semantic_inventory.yaml`. Common failures: `service_month` (doesn't exist — use `DATE_TRUNC('MONTH', service_date)`), `claim_month`, `member_name`. If a column is not in the inventory, it MUST NOT appear in any SQL.
17. **DO NOT skip `validate_genie_config()` before deployment** — the Genie notebook template includes a validation cell that executes ALL example SQL queries before calling the Genie API. This is the determinism gate — it catches SQL with wrong column names before they become broken Genie examples. If validation fails, FIX the SQL, do not proceed.

### HARD STOP RULE: No Divergence from This Prompt

If the executing agent:
- Uses `createAsset(assetType="genie")` instead of the Genie Management API → **INVALID**
- Skips reading `genie_space_configuration.md` and constructs payload from memory → **INVALID**
- Calls `POST /api/2.0/genie/spaces` without a complete `serialized_space` → **INVALID**
- Omits instructions, sample questions, or example SQL from the payload → **INVALID**
- Includes example SQL that was NOT executed and validated first → **INVALID**
- Skips the template-based notebook and writes one from scratch → **INVALID**
- Creates 0 benchmark questions → **INVALID**

Any of these invalidate the Genie Space and require re-execution from Step 1 of this prompt.

### Minimum Configuration Requirements

A valid Genie Space MUST contain ALL of:
- Title (versioned per accelerator naming)
- Description (domain-specific, mentioning key metrics)
- Table identifiers (metric view FQN)
- Warehouse ID
- Instructions (>= 500 chars with MEASURE() guidance, aggregation warnings, dimension list)
- Sample/curated questions (>= 15 covering at least 5 distinct analytical patterns)
- Example SQL (>= 10 validated queries using MEASURE() syntax)
- Benchmark questions (>= 15 using different phrasing than samples)

Creating a space without ANY of these is a pipeline failure.

### Instruction Richness Requirements (Expanded)

Instructions MUST contain ALL of the following content sections (not just length):

1. **Domain introduction**: 1-2 sentences explaining what data this Genie Space provides
2. **Measure catalog**: List EVERY validated measure with a brief business meaning
3. **Dimension catalog**: List EVERY validated dimension with typical use (filter, group, slice)
4. **MEASURE() syntax rule**: Explicit statement that all measures must be queried via `MEASURE(\`measure_name\`)`
5. **Aggregation warnings**: Which measures are ratios (non-additive) and must NOT be summed
6. **Time interpretation**: Which column represents time, what format, how to do monthly aggregation
7. **Terminology**: Common business terms and their mapping to measure/dimension names

An instruction string that is 500 chars but only says "This is a claims analytics space with some metrics" → **INVALID** (fails content richness check even if length passes).

### Sample Question Diversity Gate

Sample questions MUST cover at least 5 of these 8 analytical patterns:

| Pattern | Example | Measures Involved |
|---------|---------|------------------|
| HEADLINE | "What is total paid amount?" | Single measure, no dimensions |
| TIME_TREND | "How has denial rate changed over time?" | Measure + temporal dimension |
| DIMENSION_BREAKDOWN | "Show paid amount by claim type" | Measure + categorical dimension |
| FILTERED | "What is clean claim rate for Institutional?" | Measure + WHERE filter |
| RANKING | "Which benefit category has the highest paid?" | Measure + ORDER BY + LIMIT |
| COMPARISON | "Compare denial rate across claim types" | Measure + multiple dimension values |
| MULTI_MEASURE | "Show paid and allowed amounts by status" | Multiple measures + dimension |
| RATIO | "What percentage of claims are denied?" | Ratio/rate measure |

If fewer than 5 patterns are represented → **FAIL** (regenerate with explicit pattern targeting).

Duplicate paraphrases (same pattern + same measure + same dimension) count as ONE question regardless of phrasing.

### Validated Learnings (from production runs)

These are confirmed errors encountered and resolved during actual Genie Space creation. Treat them as mandatory guardrails.

**1. All ID-containing arrays MUST be sorted by `id` (ascending)**

The Genie API rejects payloads where any array containing `id` fields is unsorted:

```text
Error: "Invalid export proto: instructions.example_question_sqls must be sorted by id"
```

This applies to ALL of:
- `config.sample_questions`
- `instructions.text_instructions`
- `instructions.example_question_sqls`
- `benchmarks.questions`

Fix: Always sort after generating UUIDs:
```python
items = sorted(items, key=lambda x: x["id"])
```

**2. GET /genie/spaces/{id}?include_serialized_space=true DOES return content**

Pass `?include_serialized_space=true` query param to get the full configuration back. Two quirks in the read-back:

- `data_sources.metric_views` is RENAMED to `data_sources.tables` in the response
- `text_instructions[].content` is stored as a multi-line array (one item per line), not a single string. Join all items to get the full text: `''.join(ti['content'])`

Validation should check both key names:
```python
mvs = ss.get("data_sources", {}).get("metric_views", []) or \
      ss.get("data_sources", {}).get("tables", [])
```

**3. `column_configs` must be sorted alphabetically by `column_name`**

The API rejects with `InvalidParameterValue` if `column_configs[]` entries within a table are not alphabetically sorted.

```python
column_configs = sorted(column_configs, key=lambda x: x["column_name"])
```

**4. UUIDs MUST be 32-char lowercase hex WITHOUT hyphens**

The API rejects standard UUIDs with hyphens (`a1b2c3d4-e5f6-7890-...`). Use `uuid.uuid4().hex` (32 hex chars):

```text
Error: "Invalid id for sample_question.id: 'a1b2c3d4-e5f6-...'. Expected lowercase 32-hex UUID without hyphens"
```

Fix: Use `uuid.uuid4().hex` instead of `str(uuid.uuid4())`:
```python
item_id = uuid.uuid4().hex  # "a1b2c3d4e5f6789012345678abcdef01"
```

**5. `version` field MUST be 2 in `serialized_space`**

The API rejects version 0 or 1:

```text
Error: "Invalid export proto: ExportConverter supports versions 1 and 2, but got 0"
```

Fix: Always include `"version": 2` at the top level of `serialized_space`.

**6. ALL text fields (`question`, `sql`, `content`) MUST be arrays, not strings**

The API rejects plain strings for these fields:

```text
Error: "Expected an array for question but found 'What is the total paid amount?'"
Error: "Expected an array for sql but found 'SELECT SUM(paid_amount)...'"
Error: "Expected an array for content but found '## Domain\nThis Genie Space...'"
```

Fix: Wrap ALL text values in arrays:
```python
# WRONG:
{"question": "What is total paid?", "sql": "SELECT ..."}

# CORRECT:
{"question": ["What is total paid?"], "sql": ["SELECT ..."]}
{"content": ["Full instructions text here"]}
```

**7. Use SDK `w.api_client.do()` — NEVER raw `requests` with extracted tokens**

Extracting API tokens via `dbutils.notebook.entry_point.getDbutils()...apiToken()` and using `requests.post()` is:
- A credential exfiltration risk (triggers safety guardrails in Genie Code)
- Fragile (token rotation, format changes)
- Unnecessary (SDK handles auth automatically)

Fix: Use `WorkspaceClient().api_client.do(method, path, body=...)` for all API calls.

**8. `table_identifiers` goes in the CREATE body, NOT inside `serialized_space`**

Putting `table_identifiers` inside `serialized_space.config` causes:
```text
Error: "Unknown field 'table_identifiers'"
```

The correct structure:
```python
# table_identifiers is a TOP-LEVEL field in the POST body:
body = {
    "title": ...,
    "warehouse_id": ...,
    "table_identifiers": ["catalog.schema.metric_view"],  # HERE
    "serialized_space": json.dumps({...}),  # NOT inside here
}
```

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
| llm_design | llm_genie_design.yaml | file exists + instructions >= 500 chars + questions >= 15 |
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
✗ Using shortened/semantic column names from memory instead of exact DDL names
```

Every instruction, sample question, and example SQL must trace back to either the KPI spec or the DESCRIBE output. If it can't be traced, it must not be included.

### Column Name Source of Truth (DETERMINISM RULE)

**Column names used anywhere in the Genie configuration (instructions, SQL, questions) MUST come from ONE of these verified sources:**

| Source | What it provides |
|--------|------------------|
| `DESCRIBE TABLE {metric_view_fqn}` | Exact measure and dimension column names |
| `genie_semantic_inventory.yaml` | Same columns with business descriptions |
| `metric_view_design.yaml` | Column definitions from design phase |

**NEVER** derive column names from:
- The KPI spec text (it uses business language, not DDL names)
- Memory of similar healthcare schemas
- Assumed abbreviation patterns
- Prior examples in this prompt (they are illustrative patterns, NOT actual names)

**Required sequence for every SQL you write:**
```text
1. Look up exact column name in genie_semantic_inventory.yaml
2. Use that exact name in the SQL
3. validate_genie_config() will execute it to confirm correctness
```

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

## API Authentication Pattern (MANDATORY)

All API calls to Databricks endpoints MUST use the authenticated SDK client:

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config

# Standard calls (Genie CRUD, SQL execution)
w = WorkspaceClient()
result = w.api_client.do("POST", "/api/2.0/genie/spaces", body={...})

# LLM calls (need longer timeout)
w_llm = WorkspaceClient(config=Config(http_timeout_seconds=600))
result = w_llm.api_client.do("POST", "/serving-endpoints/{model}/invocations", body={...})
```

**NEVER** use:
- `requests.post()` with extracted tokens
- `requests.get()` with manual Authorization headers
- `urllib` or `httpx` for API calls
- Token extraction from `dbutils.notebook.entry_point`

The SDK handles authentication automatically. Raw HTTP calls are forbidden.

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

# Step 2.2: LLM-Assisted Genie Design (MANDATORY)

Before manually writing instructions, sample questions, and example SQL, call a **reasoning model** to propose production-quality Genie configuration. This ensures:
- Domain-specific instructions (not generic boilerplate)
- Analytically diverse sample questions (not paraphrases)
- Proper MEASURE() syntax in all examples
- Aggregation semantics warnings for non-additive measures
- Natural business terminology appropriate to the domain

## Why This Step Exists

The executing agent may generate minimal instructions ("This Genie Space has metrics") and repetitive sample questions ("What is total paid? / Show total paid / How much paid?"). A reasoning model produces domain-aware, analytically rich configuration that covers multiple question patterns per KPI.

## Context Assembly (BEFORE the LLM call)

Gather all of these inputs and include them in the prompt:

| Input | Source | What It Provides |
|-------|--------|------------------|
| KPI specification | `{EXAMPLE_DIR}/inputs/kpi_spec.md` | Business definitions, analytical intent, terminology |
| Metric View YAML | `SHOW CREATE TABLE {metric_view_fqn}` | Exact measure names, expressions, dimension names, MEASURE() syntax |
| Metric View validation | `metric_view_validation.yaml` | Which KPIs are IMPLEMENTED vs SKIPPED |
| Semantic inventory | `genie_semantic_inventory.yaml` | Profiled values, synonyms, data types |
| Categorical samples | From Step 2 profiling | Actual dimension values for grounded examples |

**The metric view definition is critical** — without it, the LLM may propose questions about measures that don't exist or generate SQL that misuses MEASURE() syntax.

## LLM Call Pattern

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config

w_llm = WorkspaceClient(config=Config(http_timeout_seconds=600))

# CRITICAL: Include the FULL metric view definition in context
genie_design_prompt = f"""
You are a senior Databricks Genie Space architect.

Given the following validated semantic model, design a complete Genie Space configuration.

## Metric View Definition (COMPLETE — this is the ACTUAL view Genie will query)
```sql
{metric_view_ddl}
```

## Metric View Validation Results
KPIs implemented and validated: {implemented_kpis}
KPIs skipped (DO NOT reference these): {skipped_kpis}

## KPI Specification (business context)
{kpi_spec_content}

## Semantic Inventory
{semantic_inventory_yaml}

## Data Profile
- Row count: {row_count}
- Date range: {min_date} to {max_date}
- Categorical samples:
{categorical_samples}

## Design Requirements

### 1. General Instructions (markdown-formatted for readability)
Write comprehensive Genie instructions using markdown structure (## headers, - bullets, blank lines between sections). The instructions should:
- Introduce the analytical domain (what this data represents)
- List ALL available measures with their business meaning and aggregation semantics
- List ALL available dimensions with their purpose and sample values
- Explain MEASURE() syntax rules (MUST use MEASURE(`measure_name`) for all measures)
- Warn about non-additive measures (ratios like Denial Rate cannot be summed — they must use AVG or be reconstructed from components)
- Provide time interpretation guidance (which temporal column to use, date format)
- Define common business terminology and synonyms
- Minimum 500 characters, target 800-1500 characters
- FORMAT: Use markdown structure — ## headers to separate sections, - bullet points for lists, blank lines between sections

### 2. Sample Questions (15-20, analytically diverse)
Generate questions covering these DISTINCT analytical patterns:
- HEADLINE: "What is the total X?" (one per primary measure)
- TIME_TREND: "How has X changed over time?" / "Monthly trend for X"
- DIMENSION_BREAKDOWN: "Show X by Y" (different dimension each time)
- FILTERED: "What is X for [specific value]?" (use actual categorical values)
- RANKING: "Which [dimension] has the highest/lowest X?"
- COMPARISON: "Compare X across [dimension values]"
- MULTI_MEASURE: "Show both X and Y by Z"
- RATIO: "What is the denial rate for [segment]?"

Each question must:
- Reference ONLY measures/dimensions in the metric view
- Use actual categorical values from the data profile
- Be phrased as a business user would ask (NOT SQL syntax)
- Test a DIFFERENT analytical pattern than other questions

### 3. Example SQL (15-20 validated queries using MEASURE() syntax)
For each sample question, provide the correct SQL. Rules:
- ALWAYS use MEASURE(`measure_name`) — never raw SUM/COUNT
- Use backtick-quoted dimension names if they contain spaces
- Use GROUP BY ALL for dimensional queries
- Use actual filter values from the data profile
- ORDER BY for trends and rankings

### 4. Benchmark Questions (15-20, generalization test)
Different wording than sample questions but testing the same semantic patterns.
Genie should be able to answer these WITHOUT memorizing sample phrasing.

## Output Format
Return ONLY a YAML structure (no markdown fencing) with this format:

genie_design:
  instructions: "<markdown-formatted string with ## headers and - bullets, 500-1500 chars>"
  metric_view_description: "<2-3 sentence description of what this metric view provides>"
  sample_questions:
    - question: "<natural language question>"
      pattern: HEADLINE | TIME_TREND | DIMENSION_BREAKDOWN | FILTERED | RANKING | COMPARISON | MULTI_MEASURE | RATIO
      measures_tested: [<measure names>]
      dimensions_tested: [<dimension names>]
  example_sqls:
    - question: "<the question this SQL answers>"
      sql: "<valid SQL using MEASURE() syntax>"
  benchmark_questions:
    - question: "<differently worded question>"
      expected_measures: [<measures Genie should select>]
      expected_dimensions: [<dimensions Genie should use>]
"""

response = w_llm.api_client.do(
    "POST",
    f"/serving-endpoints/{design_model}/invocations",
    body={
        "messages": [
            {"role": "system", "content": "You are a Genie Space design architect. Output valid YAML only. No markdown fencing. No explanatory text."},
            {"role": "user", "content": genie_design_prompt},
        ],
        "max_tokens": 16000,
        "temperature": 1,
    }
)
genie_design_yaml = response["choices"][0]["message"]["content"]
```

## Model Selection

Use the model configured in `accelerator.yaml` under `llm.steps.genie_design.model`.
Fallback: use the same reasoning model as the dashboard design step (e.g., `databricks-gpt-5-5`).

## Validation of LLM Output

After receiving the model's proposed design, validate:

1. **Instructions length**: >= 500 characters (reject thin instructions)
2. **Instructions format**: Uses markdown structure (## headers, - bullets) for readability
3. **Instructions content**: Must mention MEASURE() syntax, list measures, list dimensions
4. **Sample question count**: >= 15 questions
5. **Sample question diversity**: At least 5 of 8 pattern types represented (HEADLINE, TIME_TREND, DIMENSION_BREAKDOWN, FILTERED, RANKING, COMPARISON, MULTI_MEASURE, RATIO)
6. **Measure coverage**: Every IMPLEMENTED KPI referenced in at least 2 different questions
7. **Dimension coverage**: Every dimension used in at least 1 question
8. **Example SQL validity**: Every SQL uses MEASURE() syntax (not raw SUM/COUNT)
9. **Example SQL measure names**: All referenced measures exist in the metric view
10. **No SKIPPED KPIs**: Questions/examples do NOT reference skipped KPIs
11. **Grounded filter values**: Any WHERE clause filter values match actual profiled values
12. **Benchmark distinctness**: Benchmark questions use different phrasing than sample questions

If validation fails:
- Fix obvious issues (replace non-existent measure names with correct ones)
- Re-prompt the model with specific corrections
- Do NOT accept thin/generic instructions

## Output

Save the validated design to:

```text
{workspace.output_folder}/genie_space/llm_genie_design.yaml
```

This becomes the AUTHORITATIVE input for Steps 3-8. Instructions, sample questions, and example SQL must faithfully implement the LLM-proposed design — do not thin them out or replace with generic content.

## Skip Condition

If `{workspace.output_folder}/genie_space/llm_genie_design.yaml` already exists and contains valid instructions (>= 500 chars), sample questions (>= 15), and example SQL (>= 15) → skip the LLM call and use the existing file.

---

# Step 3: Design Genie Instructions

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "design_instructions"
> - `phase_name`: "Design Instructions"
> - `status`: "started"
> - `current_task`: "Building Genie instructions, samples, and descriptions"
> - `happenings`: ["Writing system instructions", "Generating sample questions", "Creating metric descriptions"]

## GATE 2.2: LLM Design Validation

Before proceeding to Step 3, verify the LLM design artifact:

```python
# Pseudocode — execute this validation
assert len(llm_design['instructions']) >= 500, "Instructions too short"
assert 'MEASURE' in llm_design['instructions'], "Instructions don't mention MEASURE() syntax"
assert '##' in llm_design['instructions'], "Instructions should use markdown headers for structure"
assert len(llm_design['sample_questions']) >= 15, "Too few sample questions"
patterns = set(q['pattern'] for q in llm_design['sample_questions'])
assert len(patterns) >= 5, f"Only {len(patterns)} patterns covered (need 5+)"
assert len(llm_design['example_sqls']) >= 10, "Too few example SQL queries"
for sql in llm_design['example_sqls']:
    assert 'MEASURE' in sql['sql'].upper(), f"SQL missing MEASURE(): {sql['sql'][:50]}"
assert len(llm_design['benchmark_questions']) >= 15, "Too few benchmarks"
```

If ANY assertion fails:
```text
❌ GATE 2.2 FAILED: LLM design does not meet quality requirements
Failing check: <which assertion>
Action: Re-prompt the model with specific correction guidance
```

Do NOT proceed to Step 3 until GATE 2.2 passes.

---

Use the LLM design from Step 2.2 as the AUTHORITATIVE source for instructions, questions, and SQL. Do not discard or thin out the LLM-proposed content.

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

The Genie Space API `text_instructions[].content[]` field supports **markdown formatting**. Use markdown structure for readability:

```text
✓ Use ## headers to separate sections (Domain, Measures, Dimensions, Rules)
✓ Use - bullet points to list measures and dimensions
✓ Use blank lines between sections
✓ Use `backticks` for measure/dimension names
```

Example structure:

```markdown
## Domain
This Genie Space provides healthcare claims analytics...

## Measures (use MEASURE(`name`) syntax)
- `Total Paid Amount` — sum of insurer-paid dollars
- `Denial Rate` — percentage of denied lines (non-additive, use AVG)

## Dimensions
- `Claim Type`: Professional, Institutional, Pharmacy, Dental, Vision

## Query Rules
- Always use MEASURE(`measure_name`) — never raw SUM() or COUNT()
```

This renders properly in the Genie admin UI with clear visual structure.

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

### Determinism Gate: `validate_genie_config()` (MANDATORY)

The Genie notebook template (`genie_space_notebook.py.template`) includes a **validation cell** that runs BEFORE the Create/Update API call. This cell:

1. Verifies all `TABLE_IDENTIFIERS` are accessible
2. **Executes every example SQL query** with `LIMIT 1` to confirm it runs without error
3. Checks sample question count and instruction length
4. **RAISES AssertionError** if any SQL fails (preventing deployment of broken examples)

This is the programmatic enforcement of column name correctness:

```text
LLM writes SQL with wrong column name (e.g., "service_month")
  → validate_genie_config() executes it
  → Spark raises UNRESOLVED_COLUMN
  → AssertionError with "Example SQL #3 failed: ..."
  → Notebook halts BEFORE API call
  → LLM fixes the SQL using correct column from DESCRIBE
```

**Prompt + Validation = Deterministic:**
- The prompt instructs the LLM to use correct names (~98% success)
- The validation catches the remaining ~2% before deployment
- Result: Every deployed Genie space has working example SQL, guaranteed

The LLM MUST:
1. Get actual column names from `DESCRIBE TABLE` / inventory FIRST
2. Use those exact names in all example SQL
3. Let the validation cell confirm correctness before proceeding

---

# Step 6.2: SQL Validation (BATCH — saves 15+ tool calls)

**CRITICAL EFFICIENCY RULE:** Do NOT validate example SQL queries one-by-one. Batch validate using this safe pattern:

```sql
-- Wrap each query as an existence check (always returns 1 column — compatible for UNION ALL)
SELECT 'q1' AS qid, CASE WHEN cnt > 0 THEN 'PASS' ELSE 'EMPTY' END AS status FROM (SELECT COUNT(*) AS cnt FROM (SELECT MEASURE(total_paid) AS total_paid FROM metric_view))
UNION ALL
SELECT 'q2', CASE WHEN cnt > 0 THEN 'PASS' ELSE 'EMPTY' END FROM (SELECT COUNT(*) AS cnt FROM (SELECT claim_type, MEASURE(total_paid) AS total_paid FROM metric_view GROUP BY ALL))
UNION ALL
SELECT 'q3', CASE WHEN cnt > 0 THEN 'PASS' ELSE 'EMPTY' END FROM (SELECT COUNT(*) AS cnt FROM (SELECT service_month, MEASURE(claim_count) FROM metric_view GROUP BY ALL))
```

**Why this pattern works:** Every SELECT in the UNION ALL returns exactly 2 columns (`qid STRING, status STRING`) regardless of how many columns the inner query produces. This avoids UNION column-count mismatch errors.

**DO NOT use `SELECT *, ...` in UNION ALL batches** — different queries have different column counts and will cause PARSE_SYNTAX_ERROR.

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
| `text_instructions[].content[]` | Supports markdown formatting (## headers, - bullets, newlines, `backticks`) | Use markdown structure for readability |
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

---

# Output Contract

At the END of this step, the following artifacts MUST exist:

| Artifact | Location | Validation Check |
|----------|----------|-----------------|
| LLM Genie Design | `{OUTPUT_FOLDER}/genie_space/llm_genie_design.yaml` | Instructions >= 500 chars, >= 15 questions, >= 10 SQL |
| Semantic Inventory | `{OUTPUT_FOLDER}/genie_space/genie_semantic_inventory.yaml` | All validated measures + dimensions cataloged |
| Genie Space (live) | Databricks workspace | GET /api/2.0/genie/spaces/{id} returns valid response |
| genie_space_manifest.json | `{OUTPUT_FOLDER}/genie_space/` | Contains `space_id`, `title`, `configured: true` |
| genie_space_configuration notebook | `{OUTPUT_FOLDER}/notebooks/` | File exists (if template-based pattern used) |
| sample_queries_{domain}.sql | `{OUTPUT_FOLDER}/genie_space/` | Contains >= 15 queries |
| benchmark_results.yaml | `{OUTPUT_FOLDER}/genie_space/` | Contains test results with success rate >= 80% |
| run_context.yaml | `{OUTPUT_FOLDER}/` | `phases_completed` includes genie phases |

### Minimum Quality Gates

- Instructions length >= 500 characters AND passes content richness check (see Instruction Richness Requirements)
- Instructions use markdown formatting (## headers, - bullets) for structure and readability
- Sample questions >= 15 covering at least 5 distinct analytical patterns
- Example SQL >= 10 validated queries ALL using MEASURE() syntax
- All example SQL queries execute without error on the SQL warehouse
- Benchmark questions >= 15 using different phrasing than sample questions
- Benchmark success rate >= 80%
- Every IMPLEMENTED KPI referenced in at least 2 questions
- Every dimension used in at least 1 question

If ANY artifact is missing or quality gate fails, the step has NOT completed successfully.
