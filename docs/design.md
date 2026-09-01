# Design Guide

Single reference for configuration, deploy, validation, and framework assets. **Getting started:** [README.md](../README.md).

---

## Overview

The accelerator is a **design-first Genie pipeline**: KPI spec + data model (ERD or live UC schemas) + best practices → Unity Catalog tables (optional), **Metric Views**, **Lakeview dashboards**, and a **Genie space** with one `MEASURE()` source of truth.

| Layer | Greenfield | Brownfield |
|-------|------------|------------|
| Inputs | KPI spec, ERD image, best practices | KPI spec, `live_schema(s)`, best practices |
| Step 01 | ERD → DDL + synthetic data | Skipped |
| Step 02+ | Metric views → dashboards → Genie | Same |

**Config split:**

| Setting | File |
|---------|------|
| Workspace host, deploy root, SQL warehouse, `example_domain` | [`databricks.yml`](../databricks.yml) |
| Domain, catalogs, `data_source`, assets, pipeline, inputs | [`examples/<domain>/accelerator.yaml`](../examples/member_claims/accelerator.yaml) |
| Resolved `workspace.output_folder` | Computed in Genie Step 0 from both files |

Validate before deploy:

```bash
python3 scripts/validate_dab_config.py examples/<domain>
```

Machine-readable schema: [`framework/schema/accelerator.schema.yaml`](../framework/schema/accelerator.schema.yaml).

---

## Configuration

### EXAMPLE_DIR

Genie must know **which example** to run when multiple exist under `examples/`.

**`EXAMPLE_DIR`** = workspace folder containing that example’s `accelerator.yaml` (e.g. `.../examples/member_claims`). All `paths.*` in `accelerator.yaml` are relative to **EXAMPLE_DIR**, not the master prompt location.

| Examples on workspace | Kickoff |
|----------------------|---------|
| One (default) | Master prompt path only is often enough |
| Multiple | Include `EXAMPLE_DIR .../examples/<domain>` or `for domain <domain>` |

Formula after DAB deploy: `{deploy_root}/examples/{domain.name}`.

### paths (bundle layout)

Relative to **EXAMPLE_DIR** (`examples/<domain>/`):

```yaml
paths:
  bundle_root: ../..
  databricks_yml: ../../databricks.yml
  framework_root: ../../framework
  framework_prompts: ../../framework/prompts
  master_prompt: ../../framework/prompts/00_master_prompt.md
```

| Key | Resolves to (on workspace) |
|-----|------------------------------|
| `paths.databricks_yml` | `{deploy_root}/databricks.yml` |
| `paths.framework_prompts` | `{deploy_root}/framework/prompts/` |

### workspace

```yaml
workspace:
  short_name: null
  output_subpath: output
```

Output folder: `{deploy_root}/examples/{domain.name}/{output_subpath}` (or `{output_subpath}_{short_name}` when `short_name` is set).

When `workspace.short_name` is set (e.g. `jane_doe`), append `_{short_name}` to each asset name under `assets`.

### data_source.type

| Value | Step 01 (data layer) | Step 02 (discovery) |
|-------|----------------------|---------------------|
| `erd` | Parse ERD image → DDL + optional dbldatagen | Profile `catalog.source` |
| `live_schema` | **Skipped** — no synthetic data | Profile `live_schemas[]` or `live_schema` or `catalog.source` |
| `erd_and_live_schema` | Greenfield when `greenfield.enabled: true` | Profile live + compare to ERD |

### Data source modes

| Mode | `data_source.type` | Key settings | Step 01 |
|------|-------------------|--------------|---------|
| **Greenfield** | `erd` | `erd.image`, `greenfield.enabled: true`, `greenfield.synthetic_data: true`, `greenfield.volume` | ERD → DDL + synthetic |
| **Brownfield** | `live_schema` | `live_schema` or `live_schemas[]`, `greenfield.enabled: false`, `clean_start: false` recommended | Skipped |
| **Brownfield (multi-schema)** | `live_schema` | `live_schemas[]` with `{catalog, schema, tables?, label?}` | Skipped |
| **Hybrid** | `erd_and_live_schema` | ERD + live pointers; `greenfield.enabled` controls synthetic | Optional |

**POC → production:** `type: erd` → `live_schema`; `greenfield` → `false`; add `live_schemas[]`; `pipeline.clean_start: false`; update KPI spec for real columns.

| Setting | Greenfield | Brownfield |
|---------|------------|------------|
| `data_source.erd.image` | Required | Not used |
| `data_source.live_schema` / `live_schemas[]` | Optional | Required (or `catalog.source` fallback) |
| `catalog.source` | Synthetic table target | Fallback discovery location |
| `catalog.target` | Metric view schema | Metric view schema |
| `pipeline.clean_start` | `true` OK for POC | `false` recommended |

#### Greenfield (`type: erd`)

```yaml
data_source:
  type: erd
  erd:
    image: inputs/erd.png
  greenfield:
    enabled: true
    synthetic_data: true
    volume:
      members: 20000
      claim_headers: 100000
```

Genie writes `{output_folder}/erd_parsed.yaml`, then DDL + synthetic notebooks into `catalog.source`.

#### Brownfield (`type: live_schema`)

No ERD required. Synthetic generation is **not** run.

Single schema:

```yaml
data_source:
  type: live_schema
  live_schema:
    catalog: prod_analytics
    schema: claims_gold
    # tables: [fact_claims, dim_member]   # optional allow-list
  greenfield:
    enabled: false
    synthetic_data: false

pipeline:
  clean_start: false
```

Multiple catalogs/schemas:

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

Resolution order: `live_schemas[]` → `live_schema` → `catalog.source`. See [`live_schema_discovery.md`](../framework/inputs/live_schema_discovery.md). Output: `{output_folder}/schema_profile.yaml`.

#### Hybrid (`type: erd_and_live_schema`)

Use when validating a design against production or bootstrapping synthetic data alongside live tables. Set `greenfield.enabled` to control Step 01.

### clean_start

| | `clean_start: true` | `clean_start: false` |
|--|---------------------|----------------------|
| `output/` folder | Deleted and recreated | Kept |
| `catalog.target` (semantic) | `DROP SCHEMA ... CASCADE` | Kept; views replaced via `CREATE OR REPLACE` |
| `catalog.source` / live schemas | **Never dropped** by Step 1 | Same |
| Dashboards (Step 03) | Deleted by name, recreated | Same |

Brownfield: never drop or truncate source data; prefer `clean_start: false`.

### assets

All asset names under `assets` must match `^[a-z0-9_]+$` (snake_case). See [`accelerator.schema.yaml`](../framework/schema/accelerator.schema.yaml) for structure.

---

## Deploy

### Prerequisites

- [Databricks CLI](https://docs.databricks.com/en/dev-tools/cli/install.html) v0.218+
- `databricks auth login --host <your-host>`

### Commands

```bash
cd databricks-aibi-design-first-accelerator
python3 scripts/validate_dab_config.py examples/<domain>
databricks bundle validate -t dev
databricks bundle deploy -t dev
```

Files sync to: `/Workspace/Users/<you>/aibi-design-first-accelerator/`

### Workspace layout after deploy

```
{deploy_root}/
├── databricks.yml
├── framework/
└── examples/<domain>/
    ├── accelerator.yaml
    ├── inputs/
    └── output/          # Genie runtime (not in git)
```

### Add another example module

1. Copy `examples/member_claims/` → `examples/<new_domain>/`.
2. Edit `accelerator.yaml` (`domain.name` = folder name).
3. Update [`databricks.yml`](../databricks.yml): `variables.example_domain` and `sync.paths`.
4. `python3 scripts/validate_dab_config.py examples/<new_domain>`
5. `databricks bundle deploy -t dev`

### Run Genie

Paste into **Databricks Genie** (replace `<you>`):

```
Execute the master prompt at /Workspace/Users/<you>/aibi-design-first-accelerator/framework/prompts/00_master_prompt.md with EXAMPLE_DIR /Workspace/Users/<you>/aibi-design-first-accelerator/examples/member_claims — run end to end.
```

---

## Validation

### Definition of done

- [ ] `accelerator.yaml` validates against [`accelerator.schema.yaml`](../framework/schema/accelerator.schema.yaml)
- [ ] `python3 scripts/validate_dab_config.py examples/<domain>` passes
- [ ] All asset names match `^[a-z0-9_]+$`
- [ ] KPI spec: every KPI implemented or skipped with documented reason
- [ ] Metric view(s) queryable with `MEASURE()`
- [ ] Dashboards published in AI/BI with widgets rendering (not datasets-only)
- [ ] Genie space: configuration notebook executed; Cell 10 shows ≥ `validation.min_benchmark_questions` benchmarks, ≥ 15 sample questions, ≥ 15 example SQLs, instructions > 500 chars (not a blank `createAsset` space)
- [ ] `readme.md` in output folder lists all assets

### KPI checks

| Type | Check |
|------|-------|
| Additive | SUM aggregates return expected magnitude |
| Ratio | Values in 0–1 (or documented scale) |
| Semi-additive | Not summed across time in dashboards |
| Window | Multi-period trends present |

### Per data source mode

| type | Validate |
|------|----------|
| `erd` | Tables exist in source schema after Step 01 |
| `live_schema` | Profiling finds expected fact/dim tables; `schema_profile.yaml` documents all `live_schemas[]` |
| `erd_and_live_schema` | ERD entities map to live tables; drift logged in `schema_profile.yaml` |

### Reference run

Use [`examples/member_claims/`](../examples/member_claims/) for end-to-end validation. No pre-built `output/` in git.

---

## Framework reference

Runtime assets Genie loads from the deployed bundle. Paths below are under `{deploy_root}/framework/`.

### Framework inputs

| File | Purpose |
|------|---------|
| [`inputs/best_practices.md`](../framework/inputs/best_practices.md) | Metric view design rules, aggregation pitfalls |
| [`inputs/kpi_spec.template.md`](../framework/inputs/kpi_spec.template.md) | Template for domain `inputs/kpi_spec.md` |
| [`inputs/live_schema_discovery.md`](../framework/inputs/live_schema_discovery.md) | Brownfield profiling, multi-schema joins |
| [`inputs/lakeview_dashboard_api.md`](../framework/inputs/lakeview_dashboard_api.md) | Live dashboard API, widgets, SDK (not CLI in notebooks) |
| [`inputs/genie_space_configuration.md`](../framework/inputs/genie_space_configuration.md) | Genie space template workflow; no blank `createAsset` shortcuts |
| [`inputs/workspace_file_io.md`](../framework/inputs/workspace_file_io.md) | Workspace file I/O; never `dbutils.fs` on `/Workspace/` |

### Genie pipeline prompts

Orchestrated by [`prompts/00_master_prompt.md`](../framework/prompts/00_master_prompt.md).

| Step | Prompt | Output |
|------|--------|--------|
| 0 | [`00_master_prompt.md`](../framework/prompts/00_master_prompt.md) | Full pipeline |
| 1 | [`01_create_data_layer.md`](../framework/prompts/01_create_data_layer.md) | Greenfield DDL + synthetic (`erd` only) |
| 2 | [`02_create_metric_views.md`](../framework/prompts/02_create_metric_views.md) | Metric view YAML + UC views |
| 3 | [`03_create_dashboards.md`](../framework/prompts/03_create_dashboards.md) | Live Lakeview dashboards + manifests |
| 4 | [`04_create_genie_space.md`](../framework/prompts/04_create_genie_space.md) | Genie config notebook + fully configured space |
| 5 | [`05_generate_documentation.md`](../framework/prompts/05_generate_documentation.md) | Run summary in `output/readme.md` |

### Templates

| Template | Purpose |
|----------|---------|
| [`ddl_notebook.py.template`](../framework/templates/ddl_notebook.py.template) | Greenfield table DDL |
| [`dbldatagen_notebook.py.template`](../framework/templates/dbldatagen_notebook.py.template) | Synthetic data |
| [`genie_space_notebook.py.template`](../framework/templates/genie_space_notebook.py.template) | Genie space configuration |
| [`lakeview_dashboard_helpers.py.template`](../framework/templates/lakeview_dashboard_helpers.py.template) | Lakeview API helpers |
| [`metric_view_yaml.header.yaml`](../framework/templates/metric_view_yaml.header.yaml) | Metric view YAML header |

### Example modules

| Example | Mode | Contents |
|---------|------|----------|
| [`examples/member_claims/`](../examples/member_claims/) | Greenfield (`type: erd`) | `accelerator.yaml`, `inputs/kpi_spec.md`, `inputs/erd.png`; commented brownfield block in YAML |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Refresh token is invalid` | `databricks auth login --host <your-host>` |
| `databricks.yml` not found | Set **EXAMPLE_DIR** to `examples/<domain>/` |
| `dbutils.fs` on serverless | Use Workspace API — [`workspace_file_io.md`](../framework/inputs/workspace_file_io.md) |
| Empty dashboard widgets | Follow [`lakeview_dashboard_api.md`](../framework/inputs/lakeview_dashboard_api.md); use SDK not CLI |
| Blank Genie space (no benchmarks/instructions) | Follow [`genie_space_configuration.md`](../framework/inputs/genie_space_configuration.md); run template notebook cells 8–10 |
| Host mismatch | `targets.dev.workspace.host` must match CLI profile |
