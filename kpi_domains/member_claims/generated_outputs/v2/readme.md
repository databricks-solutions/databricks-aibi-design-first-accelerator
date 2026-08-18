# member_claims — Pipeline Run Summary

**Generated:** 2026-08-18T22:00:43.193163  
**Domain:** member_claims  
**Description:** Healthcare member claims analytics covering claim submissions, approvals, denials, provider utilization, and cost trends. Enables KPI tracking for claims processing efficiency, member out-of-pocket spend, provider network utilization, and denial root-cause analysis.  
**Data Source:** erd  

---

## Configuration

| Setting | Value |
|---------|-------|
| Deploy Root | `/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator` |
| Source Schema | `aw_serverless_stable_catalog.aibi_member_claims` |
| Target Schema | `aw_serverless_stable_catalog.aibi_member_claims` |
| Clean Start | False |

---

## Generated Assets

### Metric Views
- **Validation:** PASSED

### Genie Space
- **Content file:** `/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v2/manifests/genie_content.yaml`

### Notebooks
- `01_ddl_create_tables`
- `02_synthetic_data`
- `genie_space_configuration_member_claims_v2`

---

## Validation

| Check | Status |
|-------|--------|
| Metric view queryable | PASS |
| Genie space configured | PASS |
