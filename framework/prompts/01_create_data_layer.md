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

### Data completeness rules for synthetic data (MANDATORY)

* **Dimension columns must have ZERO nulls.** For every dimension table column that will be used for slicing, filtering, or grouping in KPIs (from the KPI spec), set `percentNulls=0.0` in `withColumn()`. This includes: date columns, categorical dimensions (state, sex, age band, line of business, etc.), and FK columns.
* **Generate realistic categorical values** for ALL string dimension columns. Use representative `values=[...]` lists (e.g., US state codes, M/F, age bands) — never leave them as random strings or NULL.
* **Every column in the DDL should be populated** — do not skip columns. A dimension table with NULLs in key fields makes dashboards show `null` bars/slices and renders filters useless.

### Versioning rules for synthetic data (MANDATORY)

* **Populate `VERSION_SUFFIX`** from `config.version_suffix` (e.g. `_v1`, `_v2`, or `""` for unversioned). The DDL notebook creates tables like `dim_address_v1` — the synthetic data notebook MUST reference the same versioned names.
* **Use `discover_tables()`** at the top of the notebook (from template). It returns `TABLES = {"dim_address": "dim_address_v1", ...}` — a mapping from logical name to actual versioned table name. This handles multiple versions coexisting in one schema.
* **Always reference tables via `TABLES["logical_name"]`**, never hardcode unversioned table names. Example: `table_name = TABLES["dim_address"]` resolves to `"dim_address_v1"`.
* **FK lookups**: Use `spark.table(f"{CATALOG}.{SCHEMA}.{TABLES['dim_table']}")` to collect FK values from the versioned table.

### Type-safety rules for synthetic data (MANDATORY)

* **ALWAYS use `base_generator(table_name, rows)` as the starting point for EVERY table.** This function reads the DDL schema and pre-configures ALL columns with the correct PySpark types automatically. It makes CAST_INVALID_INPUT errors impossible.
* **Pattern**: `gen = base_generator(TABLES["logical"], rows)` then override specific columns for realism: `gen = gen.withColumn("col", StringType(), values=[...], percentNulls=0.0)`. The base types are already correct — only override for realistic categorical values.
* **NEVER construct a `dg.DataGenerator()` from scratch.** Always start with `base_generator()` which reads the actual DDL types and ensures BIGINT columns get `LongType()`, timestamps get correct format, etc.
* **NEVER use `StringType()` with `template=r"..."` for PK/FK/ID columns** — `base_generator()` handles these as `LongType()` automatically.
* **Date columns** (`DateType`): Use `begin="YYYY-MM-DD", end="YYYY-MM-DD"` format.
* **Timestamp columns** (`TimestampType`): Use `begin="YYYY-MM-DD HH:MM:SS", end="YYYY-MM-DD HH:MM:SS"` format. Using date-only strings (`"2024-12-31"`) for timestamp columns causes `ValueError: time data does not match format`. Use the `date_range_for()` helper from the template to auto-format.
* **DECIMAL/FLOAT columns**: Use numeric ranges — never formatted currency strings.
* **Violation = pipeline halt**: A type mismatch causes `CAST_INVALID_INPUT` and halts the pipeline.

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
