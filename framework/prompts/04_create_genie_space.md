# Create Genie Space

<!-- Enforcement: template-first only. Agents must not use createAsset or empty API calls. See genie_space_configuration.md. -->

## Role

Create a Genie space for natural-language querying of metric views via a **configuration notebook** (the notebook + fully configured space are the deliverables).

> **CRITICAL:** Do **not** create a blank Genie space (`createAsset`, UI shortcut, or bare `POST /api/2.0/genie/spaces` without `serialized_space`). Build the notebook from **`templates.genie_notebook`**, populate cells 2–7, copy cells 8–10 **verbatim**, execute cells 8 → 9 → 10, and pass validation.

**Deliverable = configured Genie space via template notebook.** A blank space with title only is **incomplete** — same as a dashboard with datasets but no widgets.

---

## Step 1: Load Inputs

1. Read `accelerator.yaml` (suffix resolution applied).
2. Read **`{EXAMPLE_DIR}/{paths.framework_root}/inputs/genie_space_configuration.md`** — mandatory; forbidden shortcuts and validation gates.
3. Metric views must exist — run `02_create_metric_views.md` first if not.
4. Read template at `{EXAMPLE_DIR}/{templates.genie_notebook}` — 10 cells; placeholders in 2–7; infrastructure in 8–10.
5. From `databricks.yml`: `sql_warehouse_id`, `workspace.current_user.userName` (for `PARENT_PATH` and `WAREHOUSE_ID` in cell 2).

---

## Step 2: Profile the Metric View

Same as dashboard step: dimensions, distinct values, measure ranges. Use profiling to populate `GENERAL_INSTRUCTIONS`, sample questions, and SQL examples.

---

## Step 3: Delete Existing Genie Space

Search for space matching `assets.genie.space_name`. Delete if found (idempotent) — including any blank space from a prior failed run.

---

## Step 4: Create Configuration Notebook

Path: `{workspace.output_folder}/genie_space/{assets.genie.notebook_name}`

1. Delete existing notebook at path if present (Workspace API `delete` — not `dbutils.fs`).
2. Create notebook via **Workspace `import`** with `format: JUPYTER` or agent notebook tool.
3. Populate cells 1–7 from template — **remove every `<<< REPLACE >>>` placeholder**:

| Cell | Replace |
|------|---------|
| 1 | `{{DOMAIN_NAME}}` → `domain.display_name` |
| 2 | `SPACE_TITLE` = `assets.genie.space_name`, `SPACE_DESCRIPTION`, `WAREHOUSE_ID`, `PARENT_PATH=/Users/{userName}`, `SPACE_ID=""` |
| 3 | `GENERAL_INSTRUCTIONS` — full dimension/measure catalog, MEASURE() rules (> 500 chars) |
| 4 | `METRIC_VIEW_DESCRIPTIONS` — FQN → description dict (sorted keys) |
| 5 | `SAMPLE_QUESTIONS` — 15–20 from KPI domains |
| 6 | `EXAMPLE_QUESTION_SQLS` — 15–20 tuples, MEASURE() syntax, cover every dimension and measure |
| 7 | `BENCHMARK_QUESTIONS` — 15–20 tuples, different phrasing from cell 6 |

4. Copy cells 8–10 **verbatim** from template — must include `build_serialized_space()`, create/update API calls, and validation cell.

**Never** hand-write Genie API payloads or omit cells 8–10.

---

## Step 5: Execute Notebook

1. `openAsset` on the configuration notebook.
2. Run **Cell 8** (helpers) → **Cell 9** (create/update) → **Cell 10** (validate) via notebook agent.
3. Cell 9 must print `✅ SUCCESS` with a `space_id`.
4. Cell 10 must print the validation report. **Halt with `❌ EXECUTION HALTED`** if any check fails:

| Check | Minimum |
|-------|---------|
| Benchmark questions | ≥ `validation.min_benchmark_questions` |
| Sample questions | ≥ 15 |
| Example question SQLs | ≥ 15 |
| Text instructions | > 500 characters |
| Metric views in space | ≥ 1 (all metric views from this run) |

5. Persist returned `SPACE_ID` in cell 2 for future updates.

Do **not** proceed to Step 06 if benchmarks or instructions are missing.

---

## Step 6: Validate (definition of done)

1. Configuration notebook exists at the path above with no placeholder text in cells 2–7.
2. Genie space exists with full `serialized_space` (not title-only).
3. Open the space in AI/BI Genie UI — suggested questions appear; metric views are attached.
4. Write manifest to `{workspace.output_folder}/genie_space/{space_name}_manifest.json` (space_id, title, benchmark_count, notebook_path) via Workspace API / agent tools.

---

## Forbidden

* ❌ `createAsset` or UI "Create Genie Space" without running the configuration notebook
* ❌ `POST /api/2.0/genie/spaces` without `serialized_space` from `build_serialized_space()`
* ❌ Skipping cells 8–10 or executing only cell 9 without helpers
* ❌ Notebook with `<<< REPLACE >>>` text remaining in cells 2–7
* ❌ Marking step complete when Cell 10 shows 0 benchmarks or empty instructions

---

## Rules

* `SPACE_TITLE` and notebook path must be snake_case from YAML.
* All SQL uses `MEASURE()` and `GROUP BY ALL`.
* Genie API calls happen **only** inside the template notebook cells 9–10 — not via ad-hoc agent REST calls.
* On error: `❌ EXECUTION HALTED` with API body or validation counts.
