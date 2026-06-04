# Workspace file I/O (all environments)

Use this for **every** read/write/delete under `/Workspace/...` (including `workspace.output_folder`, `EXAMPLE_DIR`, and bundle paths).

## Do not use

| Approach | Why |
|----------|-----|
| `dbutils.fs.cp`, `put`, `rm`, `mkdirs`, `ls` on `/Workspace/...` | **Fails on serverless** and is not the workspace-files model |
| Local filesystem assumptions | Genie runs against remote workspace |
| `file:/` or `dbfs:/` for accelerator deliverables | Outputs belong under `/Workspace/Users/...` from config |

`dbutils.fs` is only for DBFS/volumes paths (e.g. `dbfs:/FileStore/...`) — **not** for DAB-synced repo paths or `workspace.output_folder`.

---

## Required approach (pick one, in order)

### 1. Genie Code native workspace tools (preferred)

If the agent has **workspace file / notebook / import** tools, use them for:

- Read: `accelerator.yaml`, `databricks.yml`, `inputs/*`, ERD image, templates
- Write: `erd_parsed.yaml`, `.yaml`, `.sql`, `.md`, `.ipynb`, dashboard `*_manifest.json` under `workspace.output_folder`
- Delete: recursive delete of `workspace.output_folder` on `clean_start`

No notebook code required for file staging.

### 2. Databricks Workspace API (REST)

Host from `databricks.yml` → `targets.<target>.workspace.host`. Auth: same token/session as the agent (PAT or OAuth).

| Operation | API |
|-----------|-----|
| Create directory | `POST /api/2.0/workspace/mkdirs` — `{"path": "/Workspace/Users/.../output/metric_views"}` |
| Write text file | `POST /api/2.0/workspace/import` — `path`, `content` (base64), `format`: `AUTO` or `RAW` |
| Write notebook | `POST /api/2.0/workspace/import` — `format`: `JUPYTER`, content = base64 notebook JSON |
| Read file | `GET /api/2.0/workspace/export` — `path`, `format`: `AUTO` |
| Delete tree | `POST /api/2.0/workspace/delete` — `path`, `recursive`: true |

Paths must start with `/Workspace/` (or `/Users/` on some APIs — prefer full `/Workspace/Users/...` as in `deploy_root`).

### 3. Databricks SDK (`databricks-sdk`)

Use when generating reusable Python (e.g. a one-off setup cell). Default auth (`WorkspaceClient()` picks up notebook/job identity or env).

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ImportFormat

w = WorkspaceClient()

def workspace_mkdirs(path: str) -> None:
    parent = path.rstrip("/").rsplit("/", 1)[0]
    if parent:
        w.workspace.mkdirs(parent)

def workspace_write_text(path: str, text: str, overwrite: bool = True) -> None:
    workspace_mkdirs(path)
    w.workspace.upload(
        path,
        text.encode("utf-8"),
        format=ImportFormat.AUTO,
        overwrite=overwrite,
    )

def workspace_delete_recursive(path: str) -> None:
    try:
        w.workspace.delete(path, recursive=True)
    except Exception:
        pass  # idempotent clean_start
```

For `.ipynb` under `workspace.output_folder/notebooks/`, use `ImportFormat.JUPYTER` with notebook JSON bytes.

---

## Path conventions (this accelerator)

| Purpose | Path |
|---------|------|
| Bundle root | `deploy_root` from Step 0 (e.g. `/Workspace/Users/<user>/aibi-design-first-accelerator`) |
| Example inputs | `{deploy_root}/examples/<domain>/` = `EXAMPLE_DIR` |
| Generated assets | `workspace.output_folder` (under `EXAMPLE_DIR`, default `.../output`) |

Resolve paths from `accelerator.yaml` `paths.*` relative to **EXAMPLE_DIR** only.

---

## Operations by pipeline step

| Step | File ops | Method |
|------|----------|--------|
| clean_start | Delete `workspace.output_folder` | Workspace API `delete` recursive — **not** `dbutils.fs.rm` |
| 01 data layer | Write `erd_parsed.yaml` (columns+types), notebooks | `synthetic_data_sizing.md` + `synthetic_data_generation.md` |
| 01 execute DDL | Run notebook | Jobs/run or notebook execution API — notebook already at workspace path |
| 02 metric views | Write `schema_profile.yaml`, draft `.yaml`, CREATE view | Workspace `import`; lint per `metric_view_yaml.md` |
| 03 dashboards | Create/publish via Lakeview API; write `*_manifest.json` only | REST `POST /api/2.0/lakeview/dashboards` |
| 04 Genie | Create config `.ipynb`; execute cells 8–10; write manifest | Workspace `import` format `JUPYTER`; see `genie_space_configuration.md` |
| 05 docs | Write `readme.md` | Workspace `import` |

---

## SQL vs workspace files

- **Unity Catalog / SQL warehouse**: use `sql_warehouse_id` from `databricks.yml` — SQL statements, `CREATE TABLE`, metric views, etc.
- **Workspace files**: Workspace API / SDK / agent tools only — never `dbutils.fs` for `/Workspace/`.

---

## Fail-fast

If a file operation fails, report the **API used**, **full workspace path**, and **error body**. Do not retry with `dbutils.fs` on `/Workspace/`.
