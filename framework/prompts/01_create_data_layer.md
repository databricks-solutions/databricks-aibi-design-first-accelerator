# Create Data Layer

<!-- Synthetic row counts: ERD → erd_parsed.yaml via synthetic_data_sizing.md — not per-table keys in accelerator.yaml. -->

## Role

Generate governed Unity Catalog Delta tables from the **ERD image** when greenfield is enabled. Optional synthetic data via dbldatagen.

**Runs only when** `data_source.type` is `erd` or `erd_and_live_schema` **and** `data_source.greenfield.enabled` is `true`. Skipped entirely for `live_schema` (brownfield — existing UC data only).

---

## Step 1: Load Configuration

1. Read `accelerator.yaml`. Apply name suffix rules from `00_master_prompt.md` Step 0.
2. Read **`data_source.erd.image`** (required for `type: erd`) — PNG/JPG under the example folder. **This is the only schema input.**
3. Load templates: `templates.ddl_notebook`, `templates.dbldatagen_notebook`.
4. If `data_source.greenfield.synthetic_data` is `true`, read **`{EXAMPLE_DIR}/{paths.framework_root}/inputs/synthetic_data_sizing.md`** — mandatory sizing rules.
5. Optional scale: `data_source.greenfield.volume.scale` (`demo` \| `standard` \| `large`, default `standard`) and optional `volume.overrides` — see `synthetic_data_sizing.md`. **Do not** require per-table volume keys in `accelerator.yaml`.

---

## Step 2: Parse ERD Image and Size Synthetic Data

1. Open and read `{data_source.erd.image}`.
2. Extract and document:
   - Every **table** (fact vs dimension vs bridge vs reference vs scd2), **snake_case** table names
   - **Primary keys** and **foreign keys** (star/snowflake joins)
   - **Column names** and inferred data types
   - Cardinality (fact → dimensions)
3. For each table, assign **`role`** and **`synthetic_rows`** using **`synthetic_data_sizing.md`** + `volume.scale` + any `volume.overrides`.
4. Write full structure to `{workspace.output_folder}/erd_parsed.yaml` (include `volume_scale`, `tables` with `synthetic_rows`, joins/FKs) via **Workspace API / agent tools** (see `workspace_file_io.md` — not `dbutils.fs`).
5. Present a summary table (table, role, synthetic_rows) before generating DDL.

---

## Step 3: Generate DDL Notebook

1. Create `{workspace.output_folder}/notebooks/ddl_{domain.name}.ipynb` via **Workspace `import`** (`format: JUPYTER`) or agent notebook tool — not `dbutils.fs`.
2. **Populate from `templates.ddl_notebook`** using `erd_parsed.yaml` — do not hand-write an equivalent notebook from scratch.
3. Target: `{catalog.source.catalog}.{catalog.source.schema}`.
4. Execute the notebook.

---

## Step 4: Generate Synthetic Data (optional)

If `data_source.greenfield.synthetic_data` is `true`:

1. Confirm every ERD table has `synthetic_rows` in `erd_parsed.yaml` — halt if missing.
2. Create `{workspace.output_folder}/notebooks/synthetic_data_{domain.name}.ipynb` via Workspace API / agent tools.
3. **Populate from `templates.dbldatagen_notebook`** — read row counts from **`erd_parsed.yaml`**, not from `accelerator.yaml`.
4. Use **dbldatagen** — generation order: reference → dimension → bridge → scd2 → fact; respect FKs from `erd_parsed.yaml`.
5. Execute the notebook.

---

## Step 5: Validate

1. `SHOW TABLES IN {catalog.source.catalog}.{catalog.source.schema}` — all ERD tables exist.
2. Row counts > 0 for fact tables when `synthetic_data` is true.
3. Spot-check FK joins.

---

## Forbidden

* ❌ Per-entity volume keys in `accelerator.yaml` (e.g. `members: 20000`) — table list is ERD-driven
* ❌ dbldatagen row counts hardcoded without `erd_parsed.yaml`
* ❌ Skipping `synthetic_rows` assignment before synthetic notebook generation

---

## Rules

* All names **snake_case** (`^[a-z0-9_]+$`).
* **ERD image is the only schema input** — do not require a repo-local `erd.yaml` in git.
* **Workspace paths**: `workspace_file_io.md` — never `dbutils.fs` on `/Workspace/`.
* On error: `❌ EXECUTION HALTED`.
