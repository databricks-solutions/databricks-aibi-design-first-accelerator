# Live schema discovery (brownfield)

Use when `data_source.type` is `live_schema` or `erd_and_live_schema`. Step 01 (DDL/synthetic) is skipped for pure `live_schema`; metric views join across **one or many** Unity Catalog locations.

---

## Resolve source locations

Build an ordered list of `{catalog, schema, tables?}` from `accelerator.yaml`:

1. If **`data_source.live_schemas`** is a non-empty array → use each entry (supports multiple catalogs/schemas).
2. Else if **`data_source.live_schema.catalog`** and **`data_source.live_schema.schema`** are set → use that single entry (legacy).
3. Else → use **`catalog.source`** (`catalog` + `schema`).

Optional **`tables`** on any entry limits profiling to named tables; omit to profile all tables in that schema.

Example (data spread across two schemas):

```yaml
data_source:
  type: live_schema
  live_schemas:
    - catalog: prod_clinical
      schema: claims_core
      label: claims
    - catalog: prod_reference
      schema: member_master
      label: members
  greenfield:
    enabled: false
    synthetic_data: false
```

---

## Profiling workflow

For **each** resolved location:

1. `SHOW TABLES IN {catalog}.{schema}` (respect `tables` filter if set).
2. For each table: `DESCRIBE TABLE EXTENDED`, row count, sample 5 rows.
3. Record FQN: `{catalog}.{schema}.{table}`.
4. Classify: fact, dimension, SCD2/history, bridge, reference.
5. Infer PK/FK candidates from column names and sample joins.

Then **across all locations**:

1. Build a **unified join map** (which facts join to which dimensions, including cross-catalog joins).
2. Map KPI spec entities → physical FQNs.
3. Flag missing tables/columns — KPIs depending on them are skipped with reason.
4. Write `{workspace.output_folder}/schema_profile.yaml` summarizing locations, tables, roles, and join map.

---

## Metric view design

- Use **fully qualified** table names in metric view YAML when sources span catalogs/schemas.
- Prefer joins on confirmed keys from profiling; document assumed keys in `schema_profile.yaml`.
- Do **not** create or drop source schemas/tables in brownfield mode.
- Target semantic objects still land in `{catalog.target.catalog}.{catalog.target.schema}`.

---

## Greenfield + live (`erd_and_live_schema`)

When `greenfield.enabled: true`:

1. Run Step 01 (ERD → DDL + optional synthetic) into `catalog.source` as today.
2. Also profile all `live_schemas` / `live_schema` locations.
3. Compare ERD-parsed entities to live profiling; log drift (missing/extra columns, type mismatches).
4. Prefer **live** tables for metric views when both exist and live has data; otherwise use greenfield tables.

---

## Safety (brownfield)

- **Never** `DROP` or truncate source catalogs/schemas listed in `live_schemas` / `live_schema` / `catalog.source`.
- Set `pipeline.clean_start: false` for production brownfield runs (only drops `catalog.target` + output folder when true).
