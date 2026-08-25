# Step: Cleanup Versions

> **Purpose:** Reclaim resources by removing artifacts (tables, output folders, dashboards,
> Genie spaces) created by one or more pipeline versions.
> Works identically from App mode and Genie Code.

---

## Inputs

| Variable | Source | Description |
|----------|--------|-------------|
| `{CATALOG}` | accelerator.yaml | Target catalog |
| `{SCHEMA}` | accelerator.yaml | Base schema (e.g. `aibi_member_claims`) |
| `{EXAMPLE_DIR}` | accelerator.yaml | Domain root path |
| `{OUTPUT_FOLDER}` | accelerator.yaml | Base output path |
| `{deploy_root}` | config | Workspace root |
| `VERSIONS_TO_CLEAN` | User input | Comma-separated list: `"3"` or `"1,2,3"` or `"all"` |

---

## Phase 1: Resolve Versions to Clean

> **PROGRESS:** `report_progress(resolve_versions, started)`

1. Read `{EXAMPLE_DIR}/version_registry.yaml`
2. If `VERSIONS_TO_CLEAN` == `"all"`: target all versions in the registry
3. Otherwise: parse comma-separated list into target version numbers
4. For each target version, collect:
   - Version number
   - Suffix (`_v{N}`)
   - Status from registry
   - Output folder path (`{EXAMPLE_DIR}/output/v{N}/`)

> `report_progress(resolve_versions, completed, findings=["Targeting N versions for cleanup"])`

---

## Phase 2: Remove Versioned Tables

> **PROGRESS:** `report_progress(remove_tables, started)`

For each version suffix `_v{N}` in the target list:

1. Discover all tables and views in the schema:
   ```sql
   SHOW TABLES IN `{CATALOG}`.`{SCHEMA}`
   ```

2. Filter to tables/views whose names end with the version suffix `_v{N}`

3. Generate a single multi-statement SQL with IF EXISTS guards for each object

4. Execute in ONE `execute_sql` call (multi-statement with semicolons)

**IMPORTANT:** Only remove version-suffixed objects. Never remove the schema itself.

> `report_progress(remove_tables, completed, stats={tables_removed: N})`

---

## Phase 3: Remove Output Folders

> **PROGRESS:** `report_progress(remove_output, started)`

For each version `v{N}` in the target list:

1. Remove the output folder: `{EXAMPLE_DIR}/output/v{N}/`
   Use `cleanup_path` tool to recursively remove.

2. Also check for legacy pattern: `{EXAMPLE_DIR}/generated_outputs/v{N}/`

> `report_progress(remove_output, completed, findings=["Removed N output folders"])`

---

## Phase 4: Remove Dashboards (if applicable)

> **PROGRESS:** `report_progress(remove_dashboards, started)`

For each version suffix `_v{N}`:
1. List dashboards and find any with `_v{N}` suffix
2. Remove matched dashboards via API if tool available
3. If no tool available, log finding for manual action

> `report_progress(remove_dashboards, completed)`

---

## Phase 5: Remove Genie Spaces (if applicable)

> **PROGRESS:** `report_progress(remove_genie_spaces, started)`

For each version suffix `_v{N}`:
1. List Genie spaces and find any with `_v{N}` suffix
2. Remove matched spaces via API if tool available
3. If no tool available, log finding for manual action

> `report_progress(remove_genie_spaces, completed)`

---

## Phase 6: Update Version Registry

> **PROGRESS:** `report_progress(update_registry, started)`

1. Read `{EXAMPLE_DIR}/version_registry.yaml`
2. If removing ALL versions: reset the registry to empty versions list
3. If removing specific versions: remove those entries from `versions` list
4. Write updated registry

> `report_progress(update_registry, completed)`

---

## Phase 7: Report Completion

Call `report_step_complete` with:
- `status`: "success"
- `summary`: "Cleaned N versions: removed M tables, P output folders, Q dashboards/spaces"

---

## Constraints

1. **Only version-suffixed objects** - never the schema itself
2. **Never touch versions NOT in the target list**
3. **Multi-statement SQL** for efficiency
4. **Idempotent** - IF EXISTS guards, non-existent paths should not error
5. **Works from Genie Code** - all operations use standard tools
6. **Report progress** for each phase so the UI shows status

---

## Error Handling

- SQL failures: non-critical (objects may already be gone)
- Folder removal failures: log and continue (folder may not exist)
- Missing version_registry.yaml: skip Phase 6
- Only critical failure: inability to connect to SQL warehouse
