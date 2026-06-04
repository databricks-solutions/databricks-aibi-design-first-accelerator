# Create Data Layer

<!-- Synthetic: erd_parsed.yaml + synthetic_data_sizing.md + synthetic_data_generation.md -->

## Role

Generate governed Unity Catalog Delta tables from the **ERD image** when greenfield is enabled. Optional synthetic data via dbldatagen.

**Runs only when** `data_source.type` is `erd` or `erd_and_live_schema` **and** `data_source.greenfield.enabled` is `true`. Skipped entirely for `live_schema` (brownfield — existing UC data only).

---

## Step 1: Load Configuration

1. Read `accelerator.yaml`. Apply name suffix rules from `00_master_prompt.md` Step 0.
2. Read **`data_source.erd.image`** (required for `type: erd`) — PNG/JPG under the example folder. **This is the only schema input.**
3. Load templates: `templates.ddl_notebook`, `templates.dbldatagen_notebook`.
4. If `data_source.greenfield.synthetic_data` is `true`, read **both**:
   - **`{EXAMPLE_DIR}/{paths.framework_root}/inputs/synthetic_data_sizing.md`** — row counts and generation order
   - **`{EXAMPLE_DIR}/{paths.framework_root}/inputs/synthetic_data_generation.md`** — dbldatagen columns, FKs, DATE/TIMESTAMP formats (mandatory)
5. Optional scale: `data_source.greenfield.volume.scale` (`demo` \| `standard` \| `large`, default `standard`) and optional `volume.overrides`.

---

## Step 2: Parse ERD Image and Size Synthetic Data

1. Open and read `{data_source.erd.image}`.
2. Extract for **every table**:
   - **role** (fact, dimension, bridge, reference, scd2)
   - **columns**: name, Spark SQL **type** (`DATE`, `TIMESTAMP`, `BIGINT`, `STRING`, …), PK/FK flags
   - **primary_key**, **foreign_keys** (column → `parent_table.parent_column`)
   - Cardinality (fact → dimensions)
3. Assign **`synthetic_rows`** per table using **`synthetic_data_sizing.md`** + `volume.scale` + `volume.overrides`.
4. Write **`{workspace.output_folder}/erd_parsed.yaml`** including `volume_scale`, `tables` (columns + types + FKs + `synthetic_rows`), joins — see shapes in `synthetic_data_sizing.md` and `synthetic_data_generation.md`.
5. Present summary (table, role, column count, synthetic_rows) before DDL.

---

## Step 3: Generate DDL Notebook

1. Create `{workspace.output_folder}/notebooks/ddl_{domain.name}.ipynb` via Workspace `import` or agent notebook tool.
2. **Populate from `templates.ddl_notebook`** using `erd_parsed.yaml`.
3. Target: `{catalog.source.catalog}.{catalog.source.schema}`.
4. Execute the notebook.
5. **`DESCRIBE TABLE`** each created table — confirm columns/types match `erd_parsed.yaml`. Update `erd_parsed.yaml` if DDL drifted.

---

## Step 4: Generate Synthetic Data (optional)

If `data_source.greenfield.synthetic_data` is `true`:

1. Confirm `erd_parsed.yaml` has **full column lists with types** and `synthetic_rows` for every table.
2. Create `{workspace.output_folder}/notebooks/synthetic_data_{domain.name}.ipynb`.
3. **Populate from `templates.dbldatagen_notebook`** following **`synthetic_data_generation.md`**:
   - One table (or parent-child group) per cell where practical
   - **Every DDL column** in generator; FK columns defined **before** FK wiring
   - **DATE** → `format="%Y-%m-%d"`; **TIMESTAMP** → `format="%Y-%m-%d %H:%M:%S"`
   - Order: reference → dimension → bridge → scd2 → fact
   - Keep `built[table_name] = df` for parent FK lookups
4. Run **pre-flight checklist** in `synthetic_data_generation.md` before first `build()`.
5. Execute the notebook. **Halt on first DataGenError** — fix column/FK/date format, re-run from failed table.

---

## Step 5: Validate

1. `SHOW TABLES IN {catalog.source.catalog}.{catalog.source.schema}` — all ERD tables exist.
2. Row counts > 0 for fact tables when `synthetic_data` is true.
3. Spot-check FK joins and DATE columns (`SELECT MIN/MAX(date_col) ...`).

---

## Forbidden

* ❌ Per-entity volume keys in `accelerator.yaml`
* ❌ dbldatagen specs that omit columns present in DDL
* ❌ FK references before column defined on child generator
* ❌ `%Y-%m-%d %H:%M:%S` format on **DATE** columns or date-only literals
* ❌ Proceeding to Step 02 if synthetic generation failed or fact tables are empty

---

## Rules

* All names **snake_case** (`^[a-z0-9_]+$`).
* **ERD image is the only schema input** in git.
* **Workspace paths**: `workspace_file_io.md` — never `dbutils.fs` on `/Workspace/`.
* On error: `❌ EXECUTION HALTED`.
