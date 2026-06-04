# AIBI Design-First Accelerator — Master Prompt

<!-- Template-first: steps with templates.* in accelerator.yaml must use populated templates + validation, not UI shortcuts (e.g. createAsset for Genie). -->

You are a Databricks Platform Engineer. Execute the pipeline below in sequence for the domain defined in `accelerator.yaml`.

Run this prompt from an **example folder** (e.g. `examples/<domain>/`) that contains `accelerator.yaml` and `inputs/`.

---

## Step 0: Load Configuration

**Path rule:** Let `EXAMPLE_DIR` = the workspace directory that contains this run’s `accelerator.yaml` (e.g. `.../examples/member_claims`). Every `paths.*` value in `accelerator.yaml` is relative to `EXAMPLE_DIR` — **not** relative to where `00_master_prompt.md` lives.

1. Read `accelerator.yaml` from `EXAMPLE_DIR`. Extract domain, catalog, data source, assets, pipeline, validation, and **`paths`**.
2. Read Databricks config from **`{EXAMPLE_DIR}/{paths.databricks_yml}`** (default `../../databricks.yml` → bundle-root `databricks.yml`).  
   - Confirm file exists; if missing, halt with: expected `{deploy_root}/databricks.yml` where `deploy_root` = normalize(`EXAMPLE_DIR` + `paths.bundle_root`).  
   - From `variables.*.default` and `targets.<target>.workspace` (deploy target, typically `dev`), resolve:
   - `deploy_root` — normalize(`EXAMPLE_DIR` + `paths.bundle_root`) (must match `variables.deploy_root` after substituting `${workspace.current_user.userName}`)
   - `workspace.current_user.userName` — from active session when resolving deploy_root
   - `sql_warehouse_id` — use for **all** SQL execution in this run
   - `example_domain` — must equal `domain.name` in `accelerator.yaml`; if not, halt with a clear error
   - `workspace.host` — from `targets.<target>.workspace.host` (informational for API context)
3. **Resolve output folder** (absolute workspace path used in all later steps as `workspace.output_folder`):
   - Base: `{deploy_root}/examples/{domain.name}/{workspace.output_subpath}` (default subpath: `output`)
   - If `workspace.short_name` is set (non-null, non-empty): use `{deploy_root}/examples/{domain.name}/{output_subpath}_{short_name}` instead
4. **Name suffix resolution** — apply to every asset name in `assets`:
   - If `workspace.short_name` is **null or empty**: use names as written in YAML.
   - If `workspace.short_name` is set (e.g. `jane_doe`): append `_{short_name}` to each asset name **unless** it already ends with that suffix.
   - After resolution, validate every asset name matches `^[a-z0-9_]+$`. Reject spaces, hyphens, uppercase, or Title Case.
5. Read **KPI spec** (`inputs.kpi_spec`) and **best practices** (`inputs.best_practices`). Internalize all KPI definitions, formulas, aggregation rules, and dashboard mapping.
6. Read **`{EXAMPLE_DIR}/{paths.framework_root}/inputs/workspace_file_io.md`** — mandatory for all `/Workspace/` reads, writes, and deletes (**never `dbutils.fs`** on workspace paths; use Workspace API or agent tools — works on serverless and classic).
7. If `data_source.type` is `live_schema` or `erd_and_live_schema`, read **`{EXAMPLE_DIR}/{paths.framework_root}/inputs/live_schema_discovery.md`** — resolves `live_schemas[]`, single `live_schema`, or `catalog.source`.
8. If `data_source.erd.image` is set, note its path for Step 2 (data layer) and metric view join design.
9. Load step prompts from **`{EXAMPLE_DIR}/{paths.framework_prompts}/`** (default `../../framework/prompts/`).
10. `EXAMPLE_DIR` on workspace after DAB deploy: `{deploy_root}/examples/{domain.name}`. Input paths in `accelerator.yaml` are relative to `EXAMPLE_DIR`.

**Template-first policy:** When `accelerator.yaml` defines a `templates.*` path for a step, the deliverable is a **populated artifact from that template** (notebook or YAML header), executed and validated — not a hand-built shortcut or empty UI asset. Steps with templates: DDL/dbldatagen (01), metric view YAML header (02), Genie notebook (04). Do not use `createAsset` or equivalent one-click creation when a template workflow exists.

---

## Step 1: Environment Setup

If `pipeline.clean_start` is `true`:

1. Delete `workspace.output_folder` recursively using **Workspace API** or agent workspace tools (see `workspace_file_io.md`). **Do not use `dbutils.fs.rm` or other `dbutils.fs` calls on `/Workspace/` paths.**
2. `DROP SCHEMA IF EXISTS {catalog.target.catalog}.{catalog.target.schema} CASCADE` (ignore errors) — **target semantic schema only**.
3. Recreate `workspace.output_folder` using **Workspace API `mkdirs`** (or agent tools) — not `dbutils.fs.mkdirs`.

**Brownfield:** Never `DROP` or truncate source data in `live_schemas`, `live_schema`, or `catalog.source`. For production `live_schema` runs, prefer `pipeline.clean_start: false`.

---

## Step 2: Create Data Layer (conditional)

If `pipeline.steps.create_data_layer` is `auto` and `data_source.type` is `erd` or `erd_and_live_schema` and `data_source.greenfield.enabled` is `true`:

Execute `01_create_data_layer.md`.

Otherwise log `ℹ️ Skipping data layer (live_schema or greenfield disabled)` and proceed.

---

## Step 3: Create Metric Views

If `pipeline.steps.create_metric_views` is `true`:

Execute `02_create_metric_views.md`.

---

## Step 4: Create Dashboards

If `pipeline.steps.create_dashboards` is `true`:

Execute `03_create_dashboards.md` (live Lakeview dashboards via API — not `.lvdash.json` exports).

---

## Step 5: Create Genie Space

If `pipeline.steps.create_genie_space` is `true`:

Execute `04_create_genie_space.md`.

**Acceptance (required before Step 6):** Configuration notebook exists; cells 8–10 executed; Cell 10 validation report shows ≥ `validation.min_benchmark_questions` benchmarks, ≥ 15 sample questions, ≥ 15 example SQLs, and general instructions > 500 chars. A blank Genie space (title only, no `serialized_space` content) is **incomplete** — halt with `❌ EXECUTION HALTED`.

---

## Step 6: Generate Documentation

If `pipeline.steps.generate_documentation` is `true`:

Execute `05_generate_documentation.md`.

---

## Step 7: Secured Dashboards (optional)

If `pipeline.steps.create_secured_dashboards` is `true`:

Execute `06_create_secured_dashboards.md`.

---

## Error Handling

* **Fail fast**: Any SQL, API, or file operation failure stops execution immediately.
* **Report**: `❌ EXECUTION HALTED` — Step, error, context, suggested fix.
* **No silent failures**: Never catch and ignore errors (except DROP IF EXISTS / delete non-existent folder).
* **Workspace files**: Follow `workspace_file_io.md` — Workspace API / SDK / agent tools only for `/Workspace/` paths; **never `dbutils.fs`** (serverless-safe).
* **Sequential**: Complete each step fully before moving to the next.
* **Template-first**: Use `templates.*` from `accelerator.yaml` for notebooks and Genie configuration — never substitute UI shortcuts (`createAsset`, blank space creation) or empty API calls when a template exists.
* **No hardcoding**: Catalogs, schemas, and asset names from `accelerator.yaml`; host, deploy_root, warehouse from `{EXAMPLE_DIR}/{paths.databricks_yml}`; resolve paths from `EXAMPLE_DIR`, not from the prompt file path.
