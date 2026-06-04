# Create Metric Views

<!-- Generic for all domains: profile → schema_profile.yaml → lint YAML → CREATE. See metric_view_yaml.md. -->

## Role

Discover the source schema(s), then design and create Metric Views implementing every KPI in the KPI spec, following best practices and the platform YAML contract.

---

## Step 1: Load Inputs

1. Read `accelerator.yaml`. Apply name suffix resolution (Step 0 of master prompt).
2. Read **best practices** (design principles) and **KPI spec** (business logic) from `inputs`.
3. Read **`{EXAMPLE_DIR}/{paths.framework_root}/inputs/metric_view_yaml.md`** — mandatory platform syntax, forbidden patterns, and pre-CREATE lint rules.
4. If `data_source.type` is `live_schema` or `erd_and_live_schema`, read **`{EXAMPLE_DIR}/{paths.framework_root}/inputs/live_schema_discovery.md`**.
5. Primary metric view FQN: `{catalog.target.catalog}.{catalog.target.schema}.{assets.metric_views[primary].name}`.

---

## Step 2: Discover and Profile Source Schema(s)

### Resolve locations (all modes)

Follow **`live_schema_discovery.md`** (or `catalog.source` for greenfield `erd`) to build the list of `{catalog, schema, tables?}`.

**For every table** that will be `source` or appear in `joins`:

1. `DESCRIBE TABLE {fqn}` — record **exact** column names (never guess from ERD/KPI spec alone).
2. Row count + sample rows where useful for FK inference.

### Mode-specific notes

| `data_source.type` | Profiling |
|--------------------|-----------|
| `live_schema` | All resolved live locations; cross-catalog join map |
| `erd` | Tables in `catalog.source` after Step 01; ERD/`erd_parsed.yaml` for join design, **DESCRIBE for column names** |
| `erd_and_live_schema` | Greenfield + live; prefer live when populated; log drift |

### Write `schema_profile.yaml`

Path: `{workspace.output_folder}/schema_profile.yaml`

Include: `locations`, `tables` (fqn, role, columns from DESCRIBE), `joins` (name, source, `'on'` expression with verified columns). See shape in **`metric_view_yaml.md`**.

Map KPI spec entities → physical FQNs. Flag gaps — dependent KPIs are skipped with reason.

---

## Step 3: Design and Lint YAML (before CREATE)

1. `CREATE SCHEMA IF NOT EXISTS {catalog.target.catalog}.{catalog.target.schema}`.
2. Draft YAML (`version: 1.1`): `source`, `joins`, `dimensions`, `measures` from KPI spec + **`schema_profile.yaml`** join map.
3. **Lint against `metric_view_yaml.md`** — halt and fix before CREATE:

| Check | Rule |
|-------|------|
| Joins | Only `name`, `source`, `'on'` or `using` — **no `type:` / join keywords** |
| Formats | `format.type` ∈ {`byte`, `currency`, `date`, `date_time`, `number`, `percentage`} — map KPI Format column per `metric_view_yaml.md` |
| Columns | Every `{alias}.{col}` exists in DESCRIBE / `schema_profile.yaml` |
| Aliases | Use `joins[].name`, not physical table name when they differ |
| `'on'` | Quote as `'on':` |

4. Save draft to `{workspace.output_folder}/metric_views/{name}.yaml` via Workspace API / agent tools (`workspace_file_io.md`).
5. `CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML AS $$ ... $$`.
6. On `METRIC_VIEW_INVALID_VIEW_DEFINITION` or `UNRESOLVED_COLUMN`: fix YAML using error + DESCRIBE, update saved draft, retry up to 3 times.

---

## Step 4: Validate

* `SELECT MEASURE(<measure>) ... GROUP BY ALL` for each KPI measure (or documented skip).
* Ratios in expected ranges (e.g. 0–1 for rates where applicable).
* Window measures show multi-period trends when defined.
* Multi-schema: cross-catalog joins return rows.

---

## Step 5: Sample Queries

Create `{workspace.output_folder}/genie_space/{assets.sample_queries_file}` with 10–12 `MEASURE()` queries (Workspace API / agent tools).

---

## Forbidden

* ❌ `type: LEFT` / `type: INNER` on join entries
* ❌ `format.type: percent` or other values outside the allowed enum
* ❌ Column references not confirmed by DESCRIBE
* ❌ CREATE before saving draft YAML and passing lint checks in `metric_view_yaml.md`

---

## Rules

* Names from `accelerator.yaml`; columns from DESCRIBE / `schema_profile.yaml` only.
* Brownfield: **never** drop or mutate source schemas in `live_schemas` / `live_schema` / `catalog.source`.
* FQNs in YAML when sources span multiple catalogs/schemas.
* Workspace file writes: `workspace_file_io.md` (not `dbutils.fs`).
* Every KPI implemented or explicitly skipped.
* On error: `❌ EXECUTION HALTED`.
