# Generate Documentation

## Role

Produce a run summary in the output folder after all pipeline steps complete.

---

## Step 1: Load Configuration

Read `accelerator.yaml` (resolved asset names).

---

## Step 2: Write readme.md

Create `{workspace.output_folder}/readme.md` via Workspace API / agent tools (`workspace_file_io.md`) containing:

1. Domain name and `data_source.type`
2. Schema discovery summary — `erd_parsed.yaml` (greenfield) and/or `schema_profile.yaml` (brownfield / multi-schema)
3. Assets created:
   - Metric views (FQN list)
   - Dashboards (display names, dashboard IDs, AI/BI links from manifest files)
   - Genie space ID and notebook path
   - Sample queries file
4. KPI catalog status (implemented vs skipped with reasons)
5. Usage: how to query with `MEASURE()`, open dashboards, use Genie
6. Config reference: pointer to `accelerator.yaml` keys used

---

## Rules

* Factual summary only — no placeholder text.
* On error: `❌ EXECUTION HALTED`.
