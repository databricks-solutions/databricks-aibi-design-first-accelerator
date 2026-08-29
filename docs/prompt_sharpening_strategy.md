# Prompt Sharpening Strategy — Genie Code Compliance

## Problem Statement

When executing the accelerator pipeline in Genie Code, the agent:

1. **Ignores notebook execution patterns** — runs inline PySpark/SQL instead of creating notebooks from templates and executing via Jobs API
2. **Gets blocked by safety guardrails** — `CREATE OR REPLACE TABLE` triggers Genie Code's destructive-action interception, requiring manual approval
3. **Takes shortcuts on multi-asset stages** — creates 1 dashboard (no filters/pages) instead of following the full dashboard prompt spec
4. **Summarizes long prompts** — context window pressure causes the agent to skim 1000+ line prompts rather than executing each instruction

---

## Root Causes

| Cause | Effect |
|-------|--------|
| Prompts are narrative (explain "why" alongside "what") | Agent treats explanations as optional, skips to what seems essential |
| Steps are compound (parse + classify + write + validate in one section) | Agent merges or shortcuts multi-part instructions |
| No mandatory checkpoints between sub-steps | Agent can skip ahead without proving prior step completed |
| Templates are described but not enforced with exact cell content | Agent generates "equivalent" code instead of populating template |
| `CREATE OR REPLACE TABLE` in DDL | Triggers Genie Code safety block |

---

## Sharpening Principles

### 1. Atomic Imperative Steps

Every instruction the agent must execute is ONE numbered step with ONE verb:

```
BAD:  "Parse the ERD image, classify tables, and write erd_parsed.yaml"
GOOD: "2.1 — Call vision model on {erd_image_path}. Store response in variable `erd_response`."
      "2.2 — Extract table list from erd_response. Validate count >= 1."
      "2.3 — Write erd_parsed.yaml to {OUTPUT_FOLDER} using workspace_write_text()."
```

### 2. Mandatory Checkpoints (GATE pattern)

After each phase, require an explicit verification before proceeding:

```
GATE 2.3: Verify erd_parsed.yaml exists.
  CHECK: workspace_read("{OUTPUT_FOLDER}/erd_parsed.yaml") returns content with `tables:` key.
  IF FAIL: HALT with "ERD parsing did not produce valid output."
  IF PASS: Proceed to Step 3.
```

### 3. Template-First Execution (No Inline Shortcuts)

When a template exists, the agent MUST:

```
1. READ the template file
2. POPULATE template placeholders with resolved values
3. WRITE the populated notebook to {OUTPUT_FOLDER}/notebooks/
4. EXECUTE the notebook (via Jobs API or notebook execution)
5. VERIFY execution succeeded (check output/status)
```

The agent MUST NOT:
- Run equivalent code inline in chat
- Skip the notebook and execute DDL/DML directly
- Generate a "simpler version" of the template
- Say "I'll do this more efficiently by..."

### 4. Non-Destructive DDL Only

All DDL in the accelerator MUST use:

```sql
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.{table}{suffix} (
  ...
) USING DELTA;
```

NEVER use:
- `CREATE OR REPLACE TABLE` (triggers safety block)
- `DROP TABLE` on source data
- `TRUNCATE` on existing tables

For re-runs with `clean_start=true`, use targeted cleanup:
```sql
DROP TABLE IF EXISTS {catalog}.{schema}.{table}{suffix};
CREATE TABLE IF NOT EXISTS ...;
```

This pattern is idempotent AND doesn't trigger Genie Code's destructive-action guard on fresh runs.

### 5. Explicit Tool Selection (No Ambiguity)

Each step must state exactly WHICH tool to use:

```
BAD:  "Write the file to the output folder"
GOOD: "Write using: workspace_write_text(path='{OUTPUT_FOLDER}/erd_parsed.yaml', content=yaml_content)"
```

For notebooks:
```
BAD:  "Execute the DDL"
GOOD: "Execute notebook at '{OUTPUT_FOLDER}/notebooks/ddl_{domain}.ipynb' using Jobs API run-now"
```

### 6. No Narrative — Only Imperatives and Gates

Remove from prompts:
- Background explanations ("The reason we do this is...")
- Optional context ("This ensures that...")
- Soft language ("You may want to...", "Consider...")
- Repeated rules (state once at top, reference by ID)

Keep:
- Numbered imperative steps
- GATE checks
- Error handling ("IF fails → do X")
- Exact values/templates

---

## Specific Fixes by Stage

### 01_create_data_layer.md

| Current | Sharpened |
|---------|-----------|
| "Generate DDL from erd_parsed.yaml" | "4.1 READ template: `{templates.ddl_notebook}`. 4.2 For EACH table in erd_parsed.yaml, generate a `CREATE TABLE IF NOT EXISTS` cell. 4.3 WRITE notebook to `{OUTPUT_FOLDER}/notebooks/ddl_{domain}.ipynb`. 4.4 EXECUTE notebook via Jobs API." |
| "Generate synthetic data using dbldatagen" | "5.1 READ template: `{templates.dbldatagen_notebook}`. 5.2 POPULATE placeholders: CATALOG, SCHEMA, VERSION_SUFFIX. 5.3 For EACH table, generate a cell using `base_generator()` from template. 5.4 WRITE notebook. 5.5 EXECUTE notebook via Jobs API." |
| `CREATE OR REPLACE TABLE` anywhere | `CREATE TABLE IF NOT EXISTS` everywhere. For `clean_start`: `DROP TABLE IF EXISTS` + `CREATE TABLE IF NOT EXISTS` |

### 03_create_dashboards.md

| Current | Sharpened |
|---------|-----------|
| "Create dashboards from KPI spec" | "For EACH entry in `assets.dashboards[]`: 4.1 Read dashboard mapping from KPI spec. 4.2 For each page, generate dataset SQL. 4.3 EXECUTE each dataset SQL to validate. 4.4 Build Lakeview JSON with exact widget structure per template. 4.5 POST to `/api/2.0/lakeview/dashboards`. 4.6 POST publish. 4.7 Write manifest." |
| Dashboard without filters | "MANDATORY: Every dashboard MUST include filter widgets for: claim_type, line_of_business, service_month. Reference exact Lakeview filter JSON structure." |
| Single page | "MANDATORY: Dashboard pages MUST match KPI spec Dashboard Mapping section exactly. `member_claims_kpis_dashboard` = 3 pages (Financial Overview, Claims Analysis, Member Demographics)." |

### 04_create_genie_space.md

| Current | Sharpened |
|---------|-----------|
| "Create Genie space" | "4.1 READ template: `{templates.genie_notebook}`. 4.2 POPULATE with: metric view name, instructions, sample questions, example SQL. 4.3 WRITE notebook. 4.4 EXECUTE notebook (cells that call Genie API). 4.5 VERIFY space created via GET /api/2.0/genie/spaces/{id}." |
| Unclear serialized_space format | "Provide EXACT JSON structure for serialized_space field in the prompt with documented fields." |

---

## Enforcement Mechanisms

### 1. Step Prompt Header Block

Every step prompt should start with a machine-parseable enforcement block:

```markdown
<!-- @enforcement
  pattern: notebook_execution
  templates_required:
    - ddl_notebook
    - dbldatagen_notebook
  inline_code_forbidden: true
  gates:
    - id: erd_parsed_exists
      check: "file_exists('{OUTPUT_FOLDER}/erd_parsed.yaml')"
    - id: tables_created
      check: "SHOW TABLES IN {catalog}.{schema} LIKE '%{VERSION_SUFFIX}' returns >= 1"
    - id: data_populated
      check: "SELECT COUNT(*) > 0 from each table"
-->
```

### 2. Anti-Shortcut Declarations

Explicit "DO NOT" blocks at the start of each execution section:

```markdown
## PROHIBITED ACTIONS (this step)

Do NOT:
- Execute DDL/DML directly in chat (use notebook)
- Generate code inline instead of populating template
- Skip notebook execution "because the tables already exist"
- Create a single dashboard when config specifies multiple
- Omit filters from dashboards
- Create a blank/title-only Genie space
```

### 3. Output Contract Tables

At the END of each step, declare exactly what must exist:

```markdown
## Output Contract

| Artifact | Location | Validation |
|----------|----------|------------|
| erd_parsed.yaml | {OUTPUT_FOLDER}/ | `tables:` array with >= 1 entry |
| ddl notebook | {OUTPUT_FOLDER}/notebooks/ddl_{domain}.ipynb | File exists, executed successfully |
| dbldatagen notebook | {OUTPUT_FOLDER}/notebooks/dbldatagen_{domain}.ipynb | File exists, executed successfully |
| data_layer_validation.yaml | {OUTPUT_FOLDER}/ | `overall_status: PASS` |
```

---

## Implementation Priority

1. **Fix DDL pattern** (immediate — unblocks fresh runs without safety interrupts)
2. **Add anti-shortcut blocks** to 01, 03, 04 (prevents the most common agent bypass)
3. **Break into atomic steps** with GATE checks (ensures completeness)
4. **Add exact JSON/YAML templates** for dashboard and Genie payloads (prevents minimal implementations)
5. **Add output contract tables** (gives clear "done" criteria per stage)

---

## Testing Approach

After sharpening, validate by running the master prompt in Genie Code and checking:

- [ ] No safety blocks encountered (all DDL is `CREATE TABLE IF NOT EXISTS`)
- [ ] DDL notebook created at expected path and executed via Jobs API
- [ ] dbldatagen notebook created at expected path and executed via Jobs API
- [ ] Metric view created with all KPIs from spec
- [ ] Dashboard(s) match `assets.dashboards[]` count with filters and pages per KPI spec
- [ ] Genie space created with sample questions >= `validation.min_benchmark_questions`
- [ ] All artifacts written to `OUTPUT_FOLDER` matching output contract

---

## Implementation Status (Completed)

All prompts have been sharpened with the following additions:

| Prompt | Enforcement Header | Prohibited Actions | GATE Checks | Output Contract |
|--------|-------------------|-------------------|-------------|-----------------|
| `00_master_prompt.md` | ✓ Global rules | ✓ Anti-shortcut | — (orchestrator) | — (orchestrator) |
| `01_create_data_layer.md` | ✓ notebook_execution | ✓ 8 rules | ✓ GATE 4.1, 6.1 | ✓ 7 artifacts |
| `02_create_metric_views.md` | ✓ sql_warehouse | ✓ 9 rules | ✓ GATE 12.1, 12.2 | ✓ 7 artifacts |
| `03_create_dashboards.md` | ✓ lakeview_api | ✓ 9 rules + multi-dashboard + filter enforcement | ✓ 5 gates | ✓ per-dashboard reqs |
| `04_create_genie_space.md` | ✓ notebook_template | ✓ 8 rules + min config reqs | ✓ 7 gates | ✓ quality gates |
| `05_generate_documentation.md` | — | ✓ 5 rules | — | ✓ 3 artifacts |

### Key Fixes Applied

1. **DDL Safety**: `01_create_data_layer.md` now has MANDATORY `CREATE TABLE IF NOT EXISTS` pattern with explicit prohibition of `CREATE OR REPLACE TABLE`
2. **Notebook Enforcement**: `01_create_data_layer.md` has atomic sub-steps (6.0.1-6.0.6) enforcing template-based notebook creation and execution
3. **Multi-Dashboard**: `03_create_dashboards.md` explicitly requires N dashboards when config specifies N, and mandates filters on every dashboard
4. **Anti-Shortcut**: `00_master_prompt.md` now has a global anti-shortcut section that applies to ALL sub-prompts
5. **Output Contracts**: Every step prompt now has an explicit artifact checklist that defines "done"
