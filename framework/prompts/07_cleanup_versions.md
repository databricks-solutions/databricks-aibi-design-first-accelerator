# Cleanup Versions

## Role

You are a Databricks workspace and catalog administrator performing targeted cleanup of versioned accelerator assets.

Remove ALL artifacts associated with a specific version (or range of versions) across ALL asset types: Unity Catalog tables, metric views, Lakeview dashboards, Genie spaces, and workspace files.

---

## ENFORCEMENT HEADER

<!-- @enforcement
  pattern: targeted_deletion
  confirmation_required: true  # MUST confirm with user before any deletion
  scope: version-specific only (NEVER delete unversioned or other-version assets)
  gates:
    - id: version_resolved
      check: "Target version(s) identified and confirmed by user"
    - id: asset_inventory_complete
      check: "All assets for target version listed and presented to user"
    - id: user_confirmed
      check: "User explicitly confirmed deletion (not inferred)"
    - id: cleanup_verified
      check: "Post-cleanup validation confirms assets removed"
-->

---

## PROHIBITED ACTIONS (this entire step)

1. **DO NOT delete assets without explicit user confirmation** — present the inventory first, wait for approval
2. **DO NOT delete assets from a version other than the confirmed target** — version mismatch is a pipeline failure
3. **DO NOT delete assets that are currently running** (status=running in version_registry.yaml)
4. **DO NOT delete the version_registry.yaml file itself** — only remove the entry for the target version
5. **DO NOT use broad wildcard deletes** — each asset must be individually targeted by its versioned name
6. **DO NOT skip any asset type** — tables, views, dashboards, Genie spaces, AND workspace files must ALL be cleaned
7. **DO NOT delete catalog or schema** — only delete versioned objects WITHIN them
8. **DO NOT proceed if any deletion fails** — halt and report the failure for user decision

---

# Step 1: Load Configuration

1. Read `accelerator.yaml`.
2. Resolve catalog/schema from `catalog.source` and `catalog.target`.
3. Read `version_registry.yaml` from the domain root.
4. Identify available versions and their statuses.

---

# Step 2: Determine Target Version(s)

The user MUST specify which version(s) to clean up. Accepted inputs:

```text
"clean up v1"               → single version
"clean up v1 and v2"        → multiple specific versions
"clean up all except v3"    → retain only specified version
"clean up all"              → remove ALL versions (requires double confirmation)
```

**GATE 2.1**: Confirm target version(s) with user before proceeding.

If the target version has `status: running` in version_registry.yaml:

```text
⚠️ WARNING: Version {N} has status=running. This may be an in-progress run.
Are you sure you want to delete it? (yes/no)
```

---

# Step 3: Build Asset Inventory

For the target version(s), discover ALL associated assets:

### 3.1 Unity Catalog Tables

```sql
SHOW TABLES IN {catalog}.{schema} LIKE '%_v{N}'
```

Expected pattern: `dim_member_v1`, `fact_claim_header_v1`, etc.

### 3.2 Unity Catalog Metric Views

```sql
SHOW VIEWS IN {catalog}.{schema} LIKE '%_v{N}'
```

Expected pattern: `member_claims_metric_view_v1`

### 3.3 Lakeview Dashboards

Read the dashboard manifest(s) from:

```text
{OUTPUT_FOLDER}/v{N}/dashboards/*_dashboard_manifest.json
```

Each manifest contains a `dashboard_id` field. Verify the dashboard still exists:

```text
GET /api/2.0/lakeview/dashboards/{dashboard_id}
```

If no manifest exists, search by name pattern using the Lakeview API:

```text
GET /api/2.0/lakeview/dashboards?page_size=100
```

Filter results where `display_name` contains the version suffix (e.g., `_v1`).

Expected pattern: `member_claims_kpis_dashboard_v1`, `member_claims_utilization_dashboard_v1`

### 3.4 Genie Spaces

Read the Genie manifest from:

```text
{OUTPUT_FOLDER}/v{N}/genie_space/genie_space_manifest.json
```

Each manifest contains a `space_id` field. Verify the space still exists:

```text
GET /api/2.0/genie/spaces/{space_id}
```

If no manifest exists, search by name using the Genie API:

```text
GET /api/2.0/genie/spaces
```

Filter results where `title` contains the version suffix.

Expected pattern: `member_claims_analytics_genie_v1`

### 3.5 Workspace Files

The output folder for version N:

```text
{EXAMPLE_DIR}/generated_outputs/v{N}/
```

Contains: notebooks, metric_views, dashboards, genie_space directories, YAML artifacts, validation files.

### 3.6 Lakebase Run Records

The app stores pipeline run state in Lakebase Postgres. Each version entry in `version_registry.yaml` has a `run_id` field.

Collect all `run_id` values from target versions:

```yaml
# From version_registry.yaml:
- version: 4
  run_id: e80caf35-6188-418c-b7a2-df243fab8729  # ← this needs cleanup
```

These Lakebase records cause stale "Resume vN" buttons in the UI if not cleaned.

**Important**: Even if the version_registry.yaml is reset, the Lakebase run table retains the record. The app's `checkResumableRun()` checks BOTH sources. After cleanup, either:
- Deploy the updated app (which checks registry FIRST and won't show resume for missing versions)
- Or mark the Lakebase run records as failed/deleted

---

# Step 4: Present Inventory and Confirm

Present the COMPLETE inventory to the user in a clear table:

```text
Version v{N} — Assets to be deleted:

UNITY CATALOG TABLES ({count}):
  - {catalog}.{schema}.dim_member_v{N}
  - {catalog}.{schema}.fact_claim_header_v{N}
  - ...

METRIC VIEWS ({count}):
  - {catalog}.{schema}.member_claims_metric_view_v{N}

LAKEVIEW DASHBOARDS ({count}):
  - member_claims_kpis_dashboard_v{N} (id: {dashboard_id})
  - member_claims_utilization_dashboard_v{N} (id: {dashboard_id})

GENIE SPACES ({count}):
  - member_claims_analytics_genie_v{N} (id: {space_id})

WORKSPACE FILES:
  - {OUTPUT_FOLDER}/v{N}/ (entire directory)

VERSION REGISTRY:
  - Entry for version {N} will be removed from version_registry.yaml

TOTAL: {total_count} assets

⚠️ This action is IRREVERSIBLE. Type 'confirm' to proceed.
```

**GATE 4.1**: User must explicitly confirm. Do NOT infer confirmation from prior messages.

---

# Step 5: Execute Cleanup

Execute deletions in this MANDATORY order (dependencies first, then dependents):

### 5.1 Delete Genie Spaces

For each Genie space:

```text
DELETE /api/2.0/genie/spaces/{space_id}
```

Verify deletion:

```text
GET /api/2.0/genie/spaces/{space_id}
Expected: 404 Not Found
```

### 5.2 Delete Lakeview Dashboards

For each dashboard:

First trash (soft delete):

```text
DELETE /api/2.0/lakeview/dashboards/{dashboard_id}
```

Verify deletion:

```text
GET /api/2.0/lakeview/dashboards/{dashboard_id}
Expected: 404 Not Found or lifecycle_state = TRASHED
```

### 5.3 Delete Metric Views

For each metric view:

```sql
DROP VIEW IF EXISTS {catalog}.{schema}.{metric_view_name}_v{N}
```

### 5.4 Delete Unity Catalog Tables

For each table, in REVERSE dependency order (facts before dimensions to avoid FK constraint issues):

```sql
DROP TABLE IF EXISTS {catalog}.{schema}.{table_name}_v{N}
```

Order: fact tables first, then bridge tables, then dimension tables.

### 5.5 Delete Workspace Files

Remove the entire version output folder:

```text
DELETE {OUTPUT_FOLDER}/v{N}/ (recursive)
```

Use Workspace API:
```python
w.workspace.delete(path, recursive=True)
```

### 5.6 Clean Lakebase Run Store

The app persists pipeline runs in a Lakebase Postgres database. Stale run records cause the UI to show "Resume vN" even after other assets are cleaned.

For each run_id associated with the target version (found in version_registry.yaml before cleanup):

1. Mark the run as failed in Lakebase:

```python
# Via the app's run_store API (if app is running):
POST /api/pipeline/cancel/{run_id}
```

Or directly in Lakebase SQL:

```sql
UPDATE runs SET status = 'failed', error = 'Cleaned up by version cleanup'
WHERE run_id = '{run_id}';
```

2. Optionally delete the run record entirely:

```sql
DELETE FROM run_steps WHERE run_id = '{run_id}';
DELETE FROM run_tool_calls WHERE run_id = '{run_id}';
DELETE FROM runs WHERE run_id = '{run_id}';
```

**Note**: If the app is running, the zombie detection code will automatically mark orphaned `running` records as `failed` on the next `/api/pipeline/runs` poll. However, if the app was RESTARTED after cleanup, the in-memory `_runs` dict is empty and zombie detection handles it.

**If app is NOT deployed with latest code**: The old code does NOT have zombie detection on the domains page `checkResumableRun()`. In this case, you MUST either:
- Deploy the app first (which has the updated `/api/pipeline/version-status` endpoint that checks `version_registry.yaml`), OR
- Manually mark the Lakebase run as failed/cancelled before the user sees the stale resume button.

### 5.7 Update Version Registry

Remove the entry for version N from `version_registry.yaml`.

Read the file, remove the target version entry, write back.

For "clean all":

```yaml
domain: {domain_name}
versions: []
```

This ensures the next pipeline run starts fresh at v1.

---

# Step 6: Post-Cleanup Validation

**GATE 6.1**: Verify all assets are removed:

```sql
-- Tables should be gone
SHOW TABLES IN {catalog}.{schema} LIKE '%_v{N}'
-- Expected: empty result

-- Views should be gone
SHOW VIEWS IN {catalog}.{schema} LIKE '%_v{N}'
-- Expected: empty result
```

Verify dashboards deleted:
```text
GET /api/2.0/lakeview/dashboards/{dashboard_id}
Expected: 404 for each
```

Verify Genie spaces deleted:
```text
GET /api/2.0/genie/spaces/{space_id}
Expected: 404 for each
```

Verify workspace folder deleted:
```text
Attempt to list {OUTPUT_FOLDER}/v{N}/
Expected: Not Found
```

Verify version registry consistency:
```text
Read version_registry.yaml
Expected: No entry with version={N} exists
For "clean all": versions list is empty
```

---

# Step 7: Report Summary

Present final cleanup report:

```text
✓ Cleanup Complete — Version v{N}

| Asset Type | Count | Status |
|-----------|-------|--------|
| Tables | {N} | ✓ Deleted |
| Metric Views | {N} | ✓ Deleted |
| Dashboards | {N} | ✓ Deleted |
| Genie Spaces | {N} | ✓ Deleted |
| Workspace Files | {N} dirs | ✓ Deleted |
| Registry Entry | 1 | ✓ Removed |

Remaining versions: v{X}, v{Y}, ...
```

---

# Error Handling

### Partial Failure

If any deletion fails mid-execution:

1. HALT immediately
2. Report which assets were successfully deleted
3. Report which asset failed and the error
4. Present options to user:
   - Retry the failed deletion
   - Skip the failed asset and continue
   - Abort (leave remaining assets intact)

### Asset Not Found

If an asset from the inventory no longer exists (404 on GET):

```text
SKIP — asset already deleted or does not exist
```

This is NOT an error. Continue with remaining assets.

### Permission Denied

If deletion returns 403:

```text
⚠️ Permission denied: Cannot delete {asset_type} '{name}'
Required permission: {required_permission}
```

HALT and report. Do not silently skip.

---

# Non-Negotiable Rules

1. **ALWAYS confirm with user before any deletion** — never auto-delete
2. **ALWAYS present complete inventory first** — no blind deletion
3. **ALWAYS delete in dependency order** — Genie → Dashboards → Views → Tables → Files
4. **ALWAYS verify after deletion** — confirm assets are actually gone
5. **ALWAYS update version_registry.yaml** — keep it consistent with reality. Without this, the next pipeline run resumes a ghost version (see master prompt Step 0.3 output-folder existence check). For "clean all": ensure `versions: []` so next run starts at v1
6. **NEVER delete assets from non-target versions** — version isolation is mandatory
7. **NEVER delete the schema or catalog** — only delete versioned objects within them
8. **NEVER skip dashboard or Genie space deletion** — these are first-class versioned assets
9. **NEVER assume an asset is deleted without verification** — check with GET/SHOW after delete
10. **NEVER proceed after a permission error** — halt and report

---

# Output Contract

At the END of this step:

| Artifact | Location | Validation Check |
|----------|----------|-----------------|
| No tables with target suffix | `{catalog}.{schema}` | SHOW TABLES LIKE '%_v{N}' returns empty |
| No views with target suffix | `{catalog}.{schema}` | SHOW VIEWS LIKE '%_v{N}' returns empty |
| No dashboards with target names | Workspace | GET /api returns 404 for each dashboard_id |
| No Genie spaces with target names | Workspace | GET /api returns 404 for each space_id |
| No output folder for target version | Workspace | Folder does not exist |
| No stale Lakebase run records | Lakebase Postgres | Run status != 'running' for target run_ids |
| version_registry.yaml updated | Domain root | No entry for target version |
