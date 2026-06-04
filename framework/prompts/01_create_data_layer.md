# Create Data Layer

## Role

Generate governed Unity Catalog Delta tables from the **ERD image** when greenfield is enabled. Optional synthetic data via dbldatagen.

**Runs only when** `data_source.type` is `erd` or `erd_and_live_schema` **and** `data_source.greenfield.enabled` is `true`. Skipped entirely for `live_schema` (brownfield — existing UC data only).

---

## Step 1: Load Configuration

1. Read `accelerator.yaml`. Apply name suffix rules from `00_master_prompt.md` Step 0.
2. Read **`data_source.erd.image`** (required for `type: erd`) — PNG/JPG under the example folder. **This is the only ERD input.**
3. Load templates: `templates.ddl_notebook`, `templates.dbldatagen_notebook`.
4. Synthetic row counts from `data_source.greenfield.volume` in `accelerator.yaml`.

---

## Step 2: Parse ERD Image

1. Open and read `{data_source.erd.image}`.
2. Extract and document:
   - Every **table** (fact vs dimension), **snake_case** table names
   - **Primary keys** and **foreign keys** (star/snowflake joins)
   - **Column names** and inferred data types
   - Cardinality (fact → dimensions)
3. Write parsed structure to `{workspace.output_folder}/erd_parsed.yaml` using **Workspace API / agent tools** (see `workspace_file_io.md` — not `dbutils.fs`).
4. Present a summary table before generating DDL.

---

## Step 3: Generate DDL Notebook

1. Create `{workspace.output_folder}/notebooks/ddl_{domain.name}.ipynb` via **Workspace `import`** (`format: JUPYTER`) or agent notebook tool — not `dbutils.fs`.
2. **Populate from `templates.ddl_notebook`** using parsed ERD — do not hand-write an equivalent notebook from scratch.
3. Target: `{catalog.source.catalog}.{catalog.source.schema}`.
4. Execute the notebook.

---

## Step 4: Generate Synthetic Data (optional)

If `data_source.greenfield.synthetic_data` is `true`:

1. Create `{workspace.output_folder}/notebooks/synthetic_data_{domain.name}.ipynb` via Workspace API / agent tools (same as DDL notebook).
2. **Populate from `templates.dbldatagen_notebook`** — do not hand-write from scratch.
3. Use **dbldatagen** — dimensions before facts; respect FKs from parsed ERD.
4. Map `data_source.greenfield.volume` keys to tables (e.g. `members` → `dim_member`, `claim_headers` → `fact_claim_header`); infer defaults for other dimensions from ERD.
5. Execute the notebook.

---

## Step 5: Validate

1. `SHOW TABLES IN {catalog.source.catalog}.{catalog.source.schema}` — all ERD tables exist.
2. Row counts > 0 for fact tables.
3. Spot-check FK joins.

---

## Rules

* All names **snake_case** (`^[a-z0-9_]+$`).
* **ERD image is the only schema input** — do not require a repo-local `erd.yaml`.
* **Workspace paths**: `workspace_file_io.md` — never `dbutils.fs` on `/Workspace/`.
* On error: `❌ EXECUTION HALTED`.
