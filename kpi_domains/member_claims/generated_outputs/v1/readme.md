# Member Claims Analytics — Accelerator Run Documentation

## 1. Solution Overview

This accelerator run created a semantic analytics solution for **Member Claims** using ERD-based greenfield data generation. The solution includes 2 Metric Views, 2 AI/BI Dashboards, and 1 Genie Space.

| Property | Value |
| --- | --- |
| Domain | member_claims (Member Claims) |
| Version | _v1 |
| Data Source | ERD (greenfield, synthetic data) |
| Source Catalog | aw_serverless_stable_catalog |
| Source Schema | aibi_member_claims |
| Overall Status | **PARTIAL_SUCCESS** |
| Generated | 2026-09-03T14:03:51Z |
| LLM Model | databricks-gpt-5-5 |
| Vision Model | databricks-gpt-5-5 |

PARTIAL_SUCCESS because 9 of 16 KPIs are implemented; 6 NOT_IMPLEMENTED (cross-grain, HAVING, window/LAG requirements) and 1 SKIPPED (missing SCD2 data).

---

## 2. Architecture / Asset Flow

```text
ERD Image (inputs/erd.png)
       ↓
8 Unity Catalog Tables (synthetic data, 15,550 rows)
       ↓
2 Metric Views (claim-line grain + enrollment grain)
       ↓
2 AI/BI Dashboards (KPIs Overview + Utilization & Provider)
       ↓
1 Genie Space (member_claims_analytics_genie_v1)
```

---

## 3. Source Schema Summary

8 tables parsed from ERD with 9 relationships (7 ERD-declared, 2 inferred).

| Table | Role | Grain | Key Relationships |
| --- | --- | --- | --- |
| dim_member | Dimension | member_sk | → fact_claim_header, dim_member_identifier, dim_member_history, fact_member_enrollment, fact_claim_detail |
| dim_address | Dimension | address_key | → dim_provider, fact_claim_header |
| dim_provider | Dimension | provider_key | ← dim_address |
| dim_member_identifier | Dimension | member_sk + id_type | ← dim_member |
| dim_member_history | Dimension (SCD2) | member_sk + effective_date | ← dim_member |
| fact_claim_header | Fact | clm_claim_id | ← dim_member, dim_address; → fact_claim_detail |
| fact_claim_detail | Fact | clm_dtl_claim_id + clm_dtl_line_nbr | ← fact_claim_header, dim_member |
| fact_member_enrollment | Fact | member_sk + enrollment_date | ← dim_member |

---

## 4. Data Layer

| Table | Role | Rows | Status |
| --- | --- | --- | --- |

Data generated using `dbldatagen` with domain-specific categorical values. Overall validation: **PASS**.

---

## 5. Metric Views

| Metric View | Source | Source Grain | Measures | Dimensions | Status |
| --- | --- | --- | --- | --- | --- |
| member_claims_metric_view_v1 | fact_claim_detail_v1 | claim_line | total_claims, total_claim_lines, total_paid_amount, avg_paid_per_claim, total_billed_amount, total_allowed_amount, denied_lines, denial_rate, clean_claim_lines, clean_claim_rate, payment_to_billed_ratio, total_deductible, total_copay, total_coinsurance, unique_members, avg_paid_per_member, lines_per_claim | service_date, claim_type, line_status, clean_claim_indicator, adjudication_status, procedure_code, rendering_provider_type, fee_schedule_code | PASS |
| member_claims_enrollment_metric_view_v1 | fact_member_enrollment_v1 | enrollment | active_members, total_enrollments | enrollment_effective_date, enrollment_status, insured_code, group_code | PASS |

Two metric views were created because the domain has incompatible fact grains: claim-line grain (from fact_claim_detail) and enrollment grain (from fact_member_enrollment). These cannot be combined in a single metric view without cross-grain joins.

---

## 6. KPI Catalog

| KPI | Metric View | Status | Notes |
| --- | --- | --- | --- |
| C-1 | member_claims_metric_view_v1 | IMPLEMENTED_AND_VALIDATED |  |
| C-2 | member_claims_metric_view_v1 | IMPLEMENTED_AND_VALIDATED |  |
| C-3 | member_claims_metric_view_v1 | IMPLEMENTED_AND_VALIDATED |  |
| C-4 | member_claims_metric_view_v1 | IMPLEMENTED_AND_VALIDATED |  |
| denial_rate | member_claims_metric_view_v1 | IMPLEMENTED_AND_VALIDATED |  |
| clean_claim_rate | member_claims_metric_view_v1 | IMPLEMENTED_AND_VALIDATED |  |
| payment_to_billed | member_claims_metric_view_v1 | IMPLEMENTED_AND_VALIDATED |  |
| M-2 | member_claims_enrollment_metric_view_v1 | IMPLEMENTED_AND_VALIDATED |  |
| M-3 | member_claims_enrollment_metric_view_v1 | IMPLEMENTED_AND_VALIDATED |  |
| MC-1 | — | NOT_IMPLEMENTED | Cross-grain PMPM requires claims+enrollment join |
| MC-2 | — | NOT_IMPLEMENTED | Cross-grain computation |
| MC-3 | — | NOT_IMPLEMENTED | Cross-grain computation |
| MC-4 | — | NOT_IMPLEMENTED | HAVING clause required |
| M-1 | — | SKIPPED_MISSING_DATA | SCD2 history linkage unavailable |
| W-1 | — | NOT_IMPLEMENTED | Window on ratio |
| W-2 | — | NOT_IMPLEMENTED | LAG() required |


**Summary:** 9 implemented, 6 not implemented, 1 skipped.

---

## 6.1 Not Implemented KPIs

The following KPIs could not be implemented as metric view measures due to SQL semantics that Databricks Metric Views do not support. The validated SQL queries are provided below for manual implementation if needed.

### MC-1: 

**Reason:** Cross-grain PMPM

**Status:** NOT_IMPLEMENTED — documentation only

```sql
SELECT SUM(clm_dtl_paid_amt) / NULLIF(COUNT(DISTINCT CONCAT(member_sk, '-', DATE_TRUNC('month', enrl_start_date))), 0) FROM aw_serverless_stable_catalog.aibi_member_claims.fact_claim_detail_v1
```

**To implement manually:** Execute as a named SQL dataset in a dashboard or Databricks SQL query.

### MC-4: 

**Reason:** HAVING clause needed

**Status:** NOT_IMPLEMENTED — documentation only

```sql
-- Reference SQL not available
```

**To implement manually:** Execute as a named SQL dataset in a dashboard or Databricks SQL query.

### W-1: 

**Reason:** Window measure on ratio

**Status:** NOT_IMPLEMENTED — documentation only

```sql
-- Reference SQL not available
```

**To implement manually:** Execute as a named SQL dataset in a dashboard or Databricks SQL query.

### W-2: 

**Reason:** LAG() required

**Status:** NOT_IMPLEMENTED — documentation only

```sql
-- Reference SQL not available
```

**To implement manually:** Execute as a named SQL dataset in a dashboard or Databricks SQL query.

### MC-2: 

**Reason:** Cross-grain computation

**Status:** NOT_IMPLEMENTED — documentation only

```sql
-- Reference SQL not available
```

**To implement manually:** Execute as a named SQL dataset in a dashboard or Databricks SQL query.

### MC-3: 

**Reason:** Cross-grain computation

**Status:** NOT_IMPLEMENTED — documentation only

```sql
-- Reference SQL not available
```

**To implement manually:** Execute as a named SQL dataset in a dashboard or Databricks SQL query.



---

## 7. Dashboards

| Dashboard | ID | Pages | Canvas Widgets | Filters | Published | Validation |
| --- | --- | --- | --- | --- | --- | --- |
| member_claims_kpis_dashboard_v1 | 01f1a79e16b71fe5a03c998672132df7 | 4 (1 filter + 3 canvas) | 22 | 4 | Yes | PASS (api_readback) |
| member_claims_utilization_dashboard_v1 | 01f1a79e3f0c1403ae74c90063fb984d | 4 (1 filter + 3 canvas) | 19 | 3 | Yes | PASS (api_readback) |

### KPIs Dashboard Pages
* **Claims Overview** — KPI counters (total claims, claim lines, paid amount, avg paid, unique members, lines/claim) + paid amount trend line
* **Financial Analysis** — Paid/billed by claim type, deductible/copay/coinsurance counters, cost by provider
* **Quality & Denial Analysis** — Denial rate, clean claim rate, payment-to-billed ratio + trend charts

### Utilization Dashboard Pages
* **Utilization Patterns** — Claims volume counters + breakdown by type + volume trend
* **Provider Analysis** — Cost and volume by provider type, avg paid metrics
* **Enrollment & Population** — Active members, enrollment by insurance code and group

### Deployed Asset Links

* KPIs Dashboard: https://fevm-aw-serverless-stable.cloud.databricks.com/dashboardsv3/01f1a79e16b71fe5a03c998672132df7/published
* Utilization Dashboard: https://fevm-aw-serverless-stable.cloud.databricks.com/dashboardsv3/01f1a79e3f0c1403ae74c90063fb984d/published

---

## 8. Genie Space

| Property | Value |
| --- | --- |
| Title | member_claims_analytics_genie_v1 |
| Space ID | 01f1a79eebc217808072e6a6880c79cf |
| Warehouse ID | 2d8e531640ffa469 |
| Metric Views | 2 (claims + enrollment) |
| Instructions | 2,386 chars (markdown with ## headers) |
| Sample Questions | 18 (covering 7+ analytical patterns) |
| Example SQL | 18/18 validated |
| Benchmarks | 16 (different phrasing from examples) |
| Status | CREATED_AND_CONFIGURED |

Genie Space link: https://fevm-aw-serverless-stable.cloud.databricks.com/genie/rooms/01f1a79eebc217808072e6a6880c79cf

---

## 10. Validation Summary

| Layer | Validation | Result |
| --- | --- | --- |
| Data Layer | Schema integrity | PASS |
| Data Layer | Synthetic data generation | PASS |
| Metric Views | KPI implementation (9/16) | PARTIAL |
| Metric Views | MEASURE() validation | PASS |
| Dashboards | Dataset SQL execution | PASS |
| Dashboards | Filter binding (queryName) | PASS |
| Dashboards | API readback | PASS |
| Genie | Example SQL (18/18) | PASS |
| Genie | API acceptance | PASS |

---

## 11. Known Limitations

| Limitation | Layer | Impact | Reason |
| --- | --- | --- | --- |
| MC-1 (PMPM) | Metric View | KPI not available in dashboards/Genie | Cross-grain: requires claims + enrollment join |
| MC-2 (Claims per 1K Members) | Metric View | KPI not available | Cross-grain computation |
| MC-3 (Utilization Rate) | Metric View | KPI not available | Cross-grain computation |
| MC-4 (High-Cost Member Count) | Metric View | KPI not available | HAVING clause required |
| W-1 (Rolling 3-Month PMPM) | Metric View | KPI not available | Window measure on ratio |
| W-2 (MoM Active Member Growth) | Metric View | KPI not available | LAG() required |
| M-1 (New Member Enrollment) | Metric View | KPI not available | SCD2 history linkage unavailable in synthetic data |
| Synthetic data | Data Layer | Data is illustrative only | Generated via dbldatagen; not real production data |

---

## 12. Usage

### Query Metric Views

```sql
-- Claims: Total paid by claim type
SELECT claim_type, MEASURE(total_paid_amount)
FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`
GROUP BY ALL;

-- Enrollment: Active members by insurance code
SELECT insured_code, MEASURE(active_members)
FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v1`
GROUP BY ALL;
```

### Dashboards

Open either dashboard from the links in Section 7. The KPIs Dashboard covers financial and quality metrics; the Utilization Dashboard covers volume, provider analysis, and enrollment population.

### Genie Space

Open the Genie Space at the link in Section 8. Ask natural-language questions such as:
* "What is the total paid amount across all claims?"
* "Show denial rate by claim type"
* "How many active enrolled members do we have?"

---

## 14. Generated Artifacts

**Schema**
* erd_parsed.yaml
* semantic_model.yaml
* synthetic_data_spec.yaml

**Data Layer**
* data_layer_validation.yaml

**Metrics**
* schema_profile.yaml
* kpi_metric_mapping.yaml
* metric_view_plan.yaml
* metric_view_validation.yaml

**Dashboards**
* dashboard_design.yaml
* dashboard_dataset_validation.yaml
* kpis_dashboard_manifest.json
* utilization_dashboard_manifest.json

**Genie**
* genie_manifest.json
* sample_queries_member_claims_v1.sql

**Run**
* run_context.yaml
* step_handoff.yaml
* run_manifest.json
* readme.md

---

## 15. Configuration Reference

| Key | Value |
| --- | --- |
| domain.name | member_claims |
| data_source.type | erd |
| greenfield.enabled | true |
| catalog | aw_serverless_stable_catalog |
| schema | aibi_member_claims |
| metric_view_strategy | auto |
| naming_prefix | member_claims |
| llm.default_model | databricks-gpt-5-5 |
| version_suffix | _v1 |

Full configuration: `accelerator.yaml`
