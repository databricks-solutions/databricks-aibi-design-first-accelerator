# Create Metric Views

## Role

Discover the source schema(s), then design and create Metric Views implementing every KPI in the KPI spec, following best practices.

---

## Step 1: Load Inputs

1. Read `accelerator.yaml`. Apply name suffix resolution (Step 0 of master prompt).
2. Read **best practices** and **KPI spec** from `inputs`.
3. If `data_source.type` is `live_schema` or `erd_and_live_schema`, read **`{EXAMPLE_DIR}/{paths.framework_root}/inputs/live_schema_discovery.md`** — mandatory for resolving and profiling source locations.
4. Primary metric view FQN: `{catalog.target.catalog}.{catalog.target.schema}.{assets.metric_views[primary].name}`.

---

## Step 2: Discover and Profile Source Schema(s)

### Resolve locations (all modes)

Follow **`live_schema_discovery.md`** to build the list of `{catalog, schema, tables?}`:

| Priority | Source |
|----------|--------|
| 1 | `data_source.live_schemas[]` (multi catalog/schema) |
| 2 | `data_source.live_schema` (single catalog/schema) |
| 3 | `catalog.source` (default) |

**If `data_source.type` is `live_schema` or `erd_and_live_schema`:**

1. Profile **every** resolved location (not just the first).
2. For each table: `DESCRIBE TABLE EXTENDED`, row count, sample 5 rows.
3. Classify as fact, dimension, SCD2/history, bridge, or reference.
4. Build a **cross-location join map** using fully qualified names (`catalog.schema.table`).
5. Write `{workspace.output_folder}/schema_profile.yaml` (locations, tables, roles, joins, gaps).

**If `data_source.type` is `erd` (after greenfield load):**

1. Re-read `data_source.erd.image` or `{workspace.output_folder}/erd_parsed.yaml` for join design.
2. Profile tables in `catalog.source`; map entities to physical tables.
3. Map KPI spec entities to discovered tables. Flag missing entities — corresponding KPIs will be skipped.

**If `data_source.type` is `erd_and_live_schema`:**

1. Profile greenfield tables in `catalog.source` (if Step 01 ran).
2. Also profile all live locations per `live_schema_discovery.md`.
3. Compare ERD vs live; log drift in `schema_profile.yaml`.
4. Prefer live tables for metric views when populated; fall back to greenfield otherwise.

---

## Step 3: Create Metric Views

1. `CREATE SCHEMA IF NOT EXISTS {catalog.target.catalog}.{catalog.target.schema}`.
2. Design YAML (`version: 1.1`): source, joins (FQNs when multi-schema), dimensions, measures from KPI spec.
3. `CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML AS $$ ... $$`.
4. Save YAML to `{workspace.output_folder}/metric_views/{name}.yaml` via Workspace API / agent tools (`workspace_file_io.md`).
5. Retry up to 3 times on failure after validating column names.

---

## Step 4: Validate

* Each KPI returns non-null results where data exists.
* Ratios in expected ranges (e.g. 0–1 for rates).
* Window measures show multi-period trends.
* Document skipped KPIs with reasons.
* For multi-schema: confirm cross-catalog joins return rows.

---

## Step 5: Sample Queries

Create `{workspace.output_folder}/genie_space/{assets.sample_queries_file}` with 10–12 `MEASURE()` queries (Workspace API / agent tools).

---

## Rules

* Names from YAML only; columns confirmed via DESCRIBE.
* Brownfield: **never** drop or mutate source schemas in `live_schemas` / `live_schema` / `catalog.source`.
* Use FQNs in metric view YAML when sources span multiple catalogs/schemas.
* Workspace file writes: `workspace_file_io.md` (not `dbutils.fs`).
* Every KPI implemented or explicitly skipped.
* On error: `❌ EXECUTION HALTED`.
