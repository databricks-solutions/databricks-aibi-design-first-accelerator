# Create Genie Space

## Role

Create a Genie space for natural-language querying of metric views via a **configuration notebook** (the notebook is the deliverable).

> **CRITICAL:** Do NOT call the Genie API directly. Build the notebook from template, populate cells 2–7, copy cells 8–10 verbatim, then execute via notebook agent.

---

## Step 1: Load Inputs

1. Read `accelerator.yaml` (suffix resolution applied).
2. Metric views must exist.
3. Read template at `templates.genie_notebook` — 10 cells; placeholders in 2–7; infrastructure in 8–10.

---

## Step 2: Profile the Metric View

Same as dashboard step: dimensions, distinct values, measure ranges.

---

## Step 3: Delete Existing Genie Space

Search for space matching `assets.genie.space_name`. Delete if found (idempotent).

---

## Step 4: Create Configuration Notebook

Path: `{workspace.output_folder}/genie_space/{assets.genie.notebook_name}`

1. Delete existing notebook at path if present (Workspace API `delete` — not `dbutils.fs`).
2. Create notebook via **Workspace `import`** with `format: JUPYTER` or agent notebook tool; populate cells 1–7 from template:

| Cell | Replace |
|------|---------|
| 1 | `{{DOMAIN_NAME}}` → `domain.display_name` |
| 2 | `SPACE_TITLE` = `assets.genie.space_name`, `WAREHOUSE_ID`, `PARENT_PATH`, `SPACE_ID=""` |
| 3 | `GENERAL_INSTRUCTIONS` — full dimension/measure catalog, MEASURE() rules |
| 4 | `METRIC_VIEW_DESCRIPTIONS` — FQN → description dict |
| 5 | `SAMPLE_QUESTIONS` — 15–20 from KPI domains |
| 6 | `EXAMPLE_QUESTION_SQLS` — 15–20 tuples, MEASURE() syntax |
| 7 | `BENCHMARK_QUESTIONS` — 15–20 tuples, different phrasing |

3. Copy cells 8–10 **verbatim** from template.

---

## Step 5: Execute Notebook

1. `openAsset` on the notebook.
2. Run cells 8 → 9 → 10 via notebook agent.
3. Validate: ≥ `validation.min_benchmark_questions` benchmarks, instruction block > 500 chars.
4. Persist `SPACE_ID` in cell 2 for future updates.

---

## Rules

* `SPACE_TITLE` and notebook path must be snake_case from YAML.
* All SQL uses `MEASURE()` and `GROUP BY ALL`.
* On error: `❌ EXECUTION HALTED`.
