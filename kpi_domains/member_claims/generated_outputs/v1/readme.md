# Member Claims Accelerator Run Summary

Generated: 2026-09-01T00:00:00Z  
Version: _v1  
Overall run status: PARTIAL_SUCCESS

This README is a factual run summary derived from generated artifacts in `/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v1` and deployment manifests. Validation artifacts are treated as authoritative for success claims; deployment manifests are authoritative for deployed asset IDs and publication state.

## 1. Solution Overview

This accelerator run created a semantic analytics solution for **Member Claims** using the configured `erd` data-source mode. The solution contains:

- 8 Unity Catalog tables created and validated for the generated data layer.
- 3 Databricks Metric Views validated successfully.
- 17 KPIs confirmed by Metric View validation as implemented and validated.
- 2 KPIs documented as `NOT_IMPLEMENTED` with validated reference SQL.
- 4 KPIs skipped due to missing data or unsafe grain.
- 2 AI/BI dashboards created, published, and validated.
- 1 Genie Space configured and validated.

The run is classified as `PARTIAL_SUCCESS` because mandatory data, metric, dashboard, and Genie validations passed, but optional KPI coverage is incomplete: 2 KPIs were not implemented as Metric View measures and 4 KPIs were skipped.

Configuration metadata used for this run:

| Item | Value |
|---|---|
| Domain display name | Member Claims |
| Domain name | member_claims |
| Version suffix | _v1 |
| Data-source mode | erd |
| Source catalog/schema | aw_serverless_stable_catalog.aibi_member_claims |
| Target catalog/schema | aw_serverless_stable_catalog.aibi_member_claims |
| SQL warehouse | 2d8e531640ffa469 |
| Default LLM model | Configured in accelerator.yaml |
| Vision model | Configured in accelerator.yaml |
| Dashboard design model | Configured in accelerator.yaml for dashboard design step |
| Genie design model | Configured in accelerator.yaml for Genie design step |

## 2. Architecture / Asset Flow

The generated asset flow for this run is:

```text
ERD input
      ↓
Parsed semantic schema artifacts
      ↓
Unity Catalog generated tables
      ↓
Metric Views
      ↓
AI/BI Dashboards
      ↓
Genie Space
      ↓
Validation artifacts and run documentation
```

This was a greenfield ERD-driven run. The generated tables feed Metric Views. Published dashboards and the Genie Space consume validated Metric Views rather than raw tables.

## 3. Source Schema Summary

Authoritative artifacts used: `erd_parsed.yaml`, `semantic_model.yaml`, and `schema_profile.yaml`.

The ERD-derived semantic model generated 8 tables. The data-layer validation artifact confirmed that 8 expected tables were created and no missing or unexpected tables were reported.

| Table | Role | Grain | Key relationships |
|---|---|---|---|
| dim_member_v1 | Dimension | Current member profile | Referenced by enrollment and claims through member surrogate keys |
| dim_address_v1 | Dimension | Address record | Used for address/location attributes in the member claims model |
| dim_member_identifier_v1 | Dimension / member identifier | Member identifier record | Related to member records |
| dim_member_history_v1 | History / SCD-like member table | Member historical version | Related to member profile history |
| fact_member_enrollment_v1 | Fact | Member enrollment span or event | Joins to dim_member_v1 by member_sk |
| dim_provider_v1 | Dimension | Provider record | Referenced by provider-related claim attributes |
| fact_claim_header_v1 | Fact | Claim header | Parent claim record for claim detail lines |
| fact_claim_detail_v1 | Fact | Claim service/detail line | Joins to fact_claim_header_v1 by claim ID |

ERD-vs-live drift was not applicable as a separate brownfield drift analysis because this run used ERD-driven generation. No unresolved ERD elements were surfaced in the documentation authority artifacts used for this summary.

## 4. Data Layer

Authoritative artifact used: `data_layer_validation.yaml`.

The greenfield data layer ran and passed validation.

| Check | Result | Evidence |
|---|---|---|
| Expected tables | 8 | `data_layer_validation.yaml` reported `tables_expected: 8` |
| Created tables | 8 | `data_layer_validation.yaml` reported `tables_created: 8` |
| Missing tables | PASS | `missing: []` |
| Unexpected tables | PASS | `unexpected: []` |
| Column validation | PASS | 434 columns validated |
| Primary-key validation | PASS | 8 primary keys tested with no failures reported |
| Overall data-layer status | PASS | `overall_status: PASS` |

Major generated row-count evidence visible in generated artifacts:

| Table or asset | Row count evidence | Source artifact |
|---|---:|---|
| dim_member | 500 | `synthetic_data_spec.yaml` |
| dim_address | 300 | `synthetic_data_spec.yaml` |
| dim_member_identifier | 800 | `synthetic_data_spec.yaml` |
| dim_member_history | 900 | `synthetic_data_spec.yaml` |
| fact_member_enrollment | 1200 configured synthetic rows | `synthetic_data_spec.yaml` |
| member_claims_metric_view_v1 source | 900 rows | `genie_semantic_inventory.yaml` |
| member_claims_enrollment_metric_view_v1 source | 800 rows | `genie_semantic_inventory.yaml` |
| member_claims_enriched_metric_view_v1 source | 900 rows | `genie_semantic_inventory.yaml` |
| fact_claim_detail_enriched_v1 intermediate view | 900 source rows and 900 joined rows | `metric_view_plan.yaml` |

No data-layer validation failure was documented in the loaded validation artifact.

## 5. Metric Views

Authoritative artifacts used: `metric_view_plan.yaml`, `metric_view_design.yaml`, generated Metric View YAML files, `metric_view_validation.yaml`, and `genie_semantic_inventory.yaml`.

Metric View validation status: `PASS`.

| Metric View | FQN | Source | Source grain | Validated measures | Major dimensions | Status |
|---|---|---|---|---|---|---|
| member_claims_metric_view_v1 | `aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1` | fact_claim_detail_v1 | Claim service/detail line | Total Claims; Total Claim Lines; Total Paid Amount; Average Paid per Claim; Denial Rate; Clean Claim Rate; Payment-to-Billed Ratio; Payment-to-Allowed Ratio; Lines per Claim; Inpatient Paid Amount; Outpatient Paid Amount | Service Date; service_month; Claim Type; Line Status; Adjudication Status; Clean Claim Indicator; Benefit Category; Place of Service; Rendering Provider Specialty | PASS |
| member_claims_enrollment_metric_view_v1 | `aw_serverless_stable_catalog.aibi_member_claims.member_claims_enrollment_metric_view_v1` | fact_member_enrollment_v1 | Member enrollment span or event | New Member Enrollment; Active Members; Enrollment Records | Enrollment Effective Date; service_month; Enrollment Status; Line of Business; Plan ID; Product ID; Group Name; Member State; Member ZIP; Member Sex | PASS |
| member_claims_enriched_metric_view_v1 | `aw_serverless_stable_catalog.aibi_member_claims.member_claims_enriched_metric_view_v1` | fact_claim_detail_enriched_v1 | Claim detail line enriched with claim-header attributes | Total Paid Amount; Unique Claiming Members; Average Paid per Member; Total Claims; Claims per Member; Participating Provider Paid Amount; Participating Provider Rate | Service Date; service_month; Claim Type; Line of Business; Plan Code; Rendering Provider Specialty; Participating Rendering Provider | PASS |

Multiple Metric Views were created because the KPIs require different safe grains: claim-line financial and denial metrics use claim detail grain, enrollment/member metrics use enrollment grain, and member-normalized or participating-provider metrics use an enriched claim-line grain.

Intermediate materialized support view:

| Intermediate View | Source Tables | Join Type | Fanout Check |
|---|---|---|---|
| fact_claim_detail_enriched_v1 | fact_claim_detail_v1 and fact_claim_header_v1 | N:1 from claim detail to claim header on claim ID | Passed; 900 source rows and 900 joined rows |

## 6. KPI Catalog

Authoritative artifacts used: `kpi_metric_mapping.yaml`, `metric_view_plan.yaml`, and `metric_view_validation.yaml`.

Only KPIs listed as validated in `metric_view_validation.yaml` are marked `IMPLEMENTED_AND_VALIDATED`.

| KPI | Metric View | Measure | Status | Notes |
|---|---|---|---|---|
| C-1 Total Claims | member_claims_metric_view_v1 | Total Claims | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| C-2 Total Claim Lines | member_claims_metric_view_v1 | Total Claim Lines | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| C-3 Total Paid Amount | member_claims_metric_view_v1 | Total Paid Amount | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| C-4 Average Paid per Claim | member_claims_metric_view_v1 | Average Paid per Claim | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| M-1 New Member Enrollment | member_claims_enrollment_metric_view_v1 | New Member Enrollment | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| M-2 Members by Line of Business | member_claims_enrollment_metric_view_v1 | Active Members | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| M-3 Members by Geography | member_claims_enrollment_metric_view_v1 | Active Members | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| D-1 Denial Rate | member_claims_metric_view_v1 | Denial Rate | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| D-2 Clean Claim Rate | member_claims_metric_view_v1 | Clean Claim Rate | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| D-3 Payment-to-Billed Ratio | member_claims_metric_view_v1 | Payment-to-Billed Ratio | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| D-4 Payment-to-Allowed Ratio | member_claims_metric_view_v1 | Payment-to-Allowed Ratio | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| D-5 Average Paid per Member | member_claims_enriched_metric_view_v1 | Average Paid per Member | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| D-6 Claims per Member | member_claims_enriched_metric_view_v1 | Claims per Member | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| D-7 Lines per Claim | member_claims_metric_view_v1 | Lines per Claim | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| D-8 Inpatient Paid Amount | member_claims_metric_view_v1 | Inpatient Paid Amount | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| D-9 Outpatient Paid Amount | member_claims_metric_view_v1 | Outpatient Paid Amount | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| D-10 Participating Provider Rate | member_claims_enriched_metric_view_v1 | Participating Provider Rate | IMPLEMENTED_AND_VALIDATED | Validated by Metric View validation |
| MC-4 High-Cost Member Count | None | None | NOT_IMPLEMENTED | Requires member-level pre-aggregation and HAVING threshold before distinct counting |
| W-2 MoM Active Member Growth | None | None | NOT_IMPLEMENTED | Requires LAG over monthly active-member aggregate |
| MC-1 PMPM | None | None | SKIPPED_MISSING_DATA | No member-month exposure table or month-expanded enrollment denominator exists |
| MC-2 Claims per 1000 Members | None | None | SKIPPED_MISSING_DATA | No member-month exposure table exists; denominator cannot be safely derived from event/span rows |
| MC-3 Utilization Rate | None | None | SKIPPED_UNSAFE_GRAIN | Requires combining claims and enrollment facts at conformed member/month grain |
| W-1 Rolling 3-Month PMPM | None | None | SKIPPED_MISSING_DATA | Depends on unsupported PMPM member-month denominator |

The itemized KPI evidence contains 17 implemented KPIs plus 6 non-implemented or skipped KPIs. `metric_view_plan.yaml` also contains a header field `total_kpis: 19`; this README uses the itemized KPI statuses from validation and plan details as the factual authority for per-KPI documentation.

## 6.1 Not Implemented KPIs

The following KPIs could not be implemented as Metric View measures due to SQL semantics that Databricks Metric Views do not support for these definitions. The validated SQL queries from `metric_view_plan.yaml` are provided below for manual implementation if needed. These KPIs are not included in dashboards or Genie.

### MC-4: High-Cost Member Count

**Reason:** Requires member-level pre-aggregation and HAVING threshold before distinct counting; not safe as a single metric-view measure over line grain.

**Status:** NOT_IMPLEMENTED — documentation only

```sql
SELECT COUNT(*) AS high_cost_member_count
FROM (
  SELECT h.clm_member_sk, SUM(d.clm_dtl_paid_amt) AS member_paid
  FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`fact_claim_detail_v1` d
  JOIN `aw_serverless_stable_catalog`.`aibi_member_claims`.`fact_claim_header_v1` h
    ON d.clm_dtl_claim_id = h.clm_claim_id
  GROUP BY h.clm_member_sk
  HAVING SUM(d.clm_dtl_paid_amt) > 10000
) x
```

**To implement manually:** Add as a named SQL dataset in the dashboard. Cannot be a Metric View measure because it requires aggregate-threshold filtering using HAVING.

### W-2: MoM Active Member Growth

**Reason:** Requires LAG over monthly active-member aggregate; offset window semantics are better implemented as dashboard SQL/reference SQL for this source.

**Status:** NOT_IMPLEMENTED — documentation only

```sql
WITH monthly AS (
  SELECT DATE_TRUNC('month', mbr_enr_effective_date) AS service_month, COUNT(DISTINCT member_sk) AS active_members
  FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`fact_member_enrollment_v1`
  GROUP BY DATE_TRUNC('month', mbr_enr_effective_date)
)
SELECT service_month, active_members,
       (active_members - LAG(active_members) OVER (ORDER BY service_month)) / NULLIF(LAG(active_members) OVER (ORDER BY service_month), 0) AS mom_active_member_growth
FROM monthly
```

**To implement manually:** Add as a named SQL dataset in the dashboard. Cannot be a basic Metric View measure because it needs LAG/offset calculation over month aggregates.

## 7. Dashboards

Authoritative artifacts used: dashboard manifests and validation files under `dashboards/`, plus `dashboard_validation.yaml`, `dashboard_dataset_validation.yaml`, `dashboard_design.yaml`, and `llm_dashboard_design.yaml`.

Dashboard validation status: `PASS`.

| Dashboard | ID | Pages | Widgets | Filters | Published | Validation |
|---|---|---:|---:|---:|---|---|
| member_claims_kpis_dashboard_v1 | 01f1a5afd415119fbcfb53807202eed2 | 4 total, including 3 canvas pages | 22 | 7 | true | PASS |
| member_claims_utilization_dashboard_v1 | 01f1a5afeb821a4c9c96c68ed7d307bf | 4 total, including 3 canvas pages | 22 | 7 | true | PASS |

Dashboard details:

| Dashboard | Source Metric Views | Page structure | Dataset validation | Design source |
|---|---|---|---|---|
| member_claims_kpis_dashboard_v1 | member_claims_metric_view_v1 and related validated Metric Views listed in manifest | 1 filter page plus 3 canvas pages; design artifact includes a Financial Overview page | Datasets validated | LLM-assisted design artifact present |
| member_claims_utilization_dashboard_v1 | member_claims_metric_view_v1 and related validated Metric Views listed in manifest | 1 filter page plus 3 canvas pages | Datasets validated | LLM-assisted design artifact present |

The consolidated dashboard validation artifact reported:

- Dashboards created: 2
- Dashboards published: 2
- Configured dashboards: 2
- Total datasets: 6
- Total pages: 8
- Total canvas pages: 6
- Total widgets including filters and titles: 44
- Total filters: 14
- Rendered validated KPIs: 15
- KPI coverage status: PASS

No absolute workspace host was documented in the deployment manifests loaded for this summary, so this README does not construct full clickable URLs. Use the dashboard IDs above with the Databricks workspace dashboard route `/dashboardsv3/{dashboard_id}/published`.

## 8. Genie Space / Genie Agent

Authoritative artifacts used: `genie_semantic_inventory.yaml`, `llm_genie_design.yaml`, `member_claims_analytics_genie_v1_manifest.json`, `member_claims_analytics_genie_v1_validation.yaml`, `genie_benchmark_validation.yaml`, `benchmark_results.yaml`, and `sample_queries_member_claims.sql`.

Genie was enabled, created, configured, and validated.

| Item | Value |
|---|---|
| Title | member_claims_analytics_genie_v1 |
| Space ID | 01f1a5b1d16312cc89683e12db7e4d55 |
| Warehouse ID | 2d8e531640ffa469 |
| Attached Metric Views | member_claims_metric_view_v1; member_claims_enrollment_metric_view_v1; member_claims_enriched_metric_view_v1 |
| Configuration notebook | `/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v1/genie_space/genie_space_configuration_member_claims` |
| Instruction character count | 3352 |
| Instruction format | Markdown with section headers |
| Sample questions | 16 |
| Example SQL statements | 16 |
| Example SQL validation | 16 executed, 0 failed |
| Benchmark count | 16 |
| Benchmark pass rate | 1.0 |
| Benchmark status | PASS |
| Overall Genie validation | PASS |

The Genie design explicitly excludes unsupported PMPM, claims-per-1000, utilization-rate, high-cost-member-count, rolling-PMPM, and MoM-growth topics because those KPIs were skipped or not implemented as Metric View measures.

## 9. LLM-Assisted Design Summary

LLM-assisted design artifacts exist for both dashboards and Genie.

### Dashboard Design

Source artifact: `dashboards/llm_dashboard_design.yaml`.

- Dashboards designed: 2
- Dashboard layout quality target: multi-page dashboards with at least 2 canvas pages each
- Actual generated dashboard structure: each dashboard has 4 total pages and 3 canvas pages
- Visualization and widget scale: 44 total dashboard elements across both dashboards, including filters and titles
- Design outcome: generated dashboards were created, published, and validated

### Genie Space Design

Source artifact: `genie_space/llm_genie_design.yaml`.

- Instruction quality: 3352 characters
- Instruction format: Markdown with domain, Metric View selection, measure rules, dimensions/time, and unsupported-topic sections
- Question pattern coverage: sample questions cover MULTI_MEASURE, TIME_TREND, DIMENSION_BREAKDOWN, FILTERED, RANKING, COMPARISON, and RATIO patterns
- Example SQL validation: 16 passed out of 16 executed
- Benchmark questions: 16
- Benchmark answer format: SQL-backed Metric View answers using validated `MEASURE()` expressions
- Benchmark pass rate: 1.0

## 10. Validation Summary

| Layer | Validation | Result | Artifact |
|---|---|---|---|
| Data Layer | Schema/table creation | PASS | data_layer_validation.yaml |
| Data Layer | Primary-key validation | PASS | data_layer_validation.yaml |
| Metric Layer | Metric View validation | PASS | metric_views/metric_view_validation.yaml |
| Metric Layer | Intermediate view fanout | PASS | metric_views/metric_view_plan.yaml |
| Dashboards | Dataset SQL | PASS | dashboards/dashboard_dataset_validation.yaml |
| Dashboards | Dashboard creation/publication | PASS | dashboards/dashboard_validation.yaml and dashboard manifests |
| Dashboards | KPI coverage for rendered dashboard KPIs | PASS | dashboards/dashboard_validation.yaml |
| Genie | Space configuration | PASS | genie_space/member_claims_analytics_genie_v1_validation.yaml |
| Genie | Example SQL | PASS | genie_space/member_claims_analytics_genie_v1_validation.yaml |
| Genie | Benchmarks | PASS | genie_space/genie_benchmark_validation.yaml and benchmark_results.yaml |

## 11. Known Limitations

| Limitation | Layer | Impact | Reason |
|---|---|---|---|
| MC-4 High-Cost Member Count | Metric View | KPI not available as a Metric View, dashboard metric, or Genie metric | Requires member-level pre-aggregation and HAVING threshold before distinct counting |
| W-2 MoM Active Member Growth | Metric View | KPI not available as a Metric View, dashboard metric, or Genie metric | Requires LAG over monthly active-member aggregate |
| MC-1 PMPM | Metric View | KPI skipped | No member-month exposure table or month-expanded enrollment denominator exists |
| MC-2 Claims per 1000 Members | Metric View | KPI skipped | No member-month exposure table exists; denominator cannot be safely derived from event/span rows |
| MC-3 Utilization Rate | Metric View | KPI skipped | Requires combining claims and enrollment facts at conformed member/month grain |
| W-1 Rolling 3-Month PMPM | Metric View | KPI skipped | Depends on unsupported PMPM member-month denominator |
| KPI-count header mismatch | Documentation / metric planning artifact | Consumers should rely on itemized KPI statuses rather than the plan header count | `metric_view_plan.yaml` header reports `total_kpis: 19`, while itemized validation and plan entries document 17 implemented and 6 non-implemented or skipped KPIs |

## 12. Usage

### Query Metric Views

Use Metric Views directly with validated measure names. Example using generated names from this run:

```sql
SELECT
  `Claim Type`,
  MEASURE(`Total Paid Amount`) AS total_paid_amount
FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`
GROUP BY ALL
ORDER BY total_paid_amount DESC;
```

Enrollment example:

```sql
SELECT
  `Line of Business`,
  MEASURE(`Active Members`) AS active_members
FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v1`
GROUP BY ALL
ORDER BY active_members DESC;
```

Enriched claims example:

```sql
SELECT
  `Line of Business`,
  MEASURE(`Participating Provider Rate`) AS participating_provider_rate
FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enriched_metric_view_v1`
GROUP BY ALL
ORDER BY participating_provider_rate DESC;
```

### Dashboards

Open these published AI/BI dashboards in the Databricks workspace:

- `member_claims_kpis_dashboard_v1`, dashboard ID `01f1a5afd415119fbcfb53807202eed2`
- `member_claims_utilization_dashboard_v1`, dashboard ID `01f1a5afeb821a4c9c96c68ed7d307bf`

The KPI dashboard is intended for executive KPI monitoring across financial, claims-quality, and member-demographic views. The utilization dashboard is intended for claims utilization and operational analysis. Publication status is confirmed by dashboard validation and manifest artifacts.

### Genie

Open Genie Space `member_claims_analytics_genie_v1`, space ID `01f1a5b1d16312cc89683e12db7e4d55`, and ask questions over the configured semantic model. Representative validated sample questions include:

- What are total claims, total claim lines, and total paid amount?
- How has total paid amount trended by service month?
- Show total paid amount by claim type.
- How many active members are there by line of business?
- What is average paid per member by line of business?
- What is participating provider rate for Medicare Advantage claims?

Do not use this Genie Space for PMPM, claims per 1000 members, utilization rate, high-cost member count, rolling 3-month PMPM, or MoM active member growth; those KPIs are explicitly unsupported or not implemented in this run.

## 13. Troubleshooting

This section is included because the overall run status is `PARTIAL_SUCCESS` due to KPI coverage gaps.

| Layer | Symptom | Root Cause | Resolution | Artifact |
|---|---|---|---|---|
| Metric Views | PMPM, claims per 1000 members, utilization rate, or rolling PMPM are unavailable | Missing member-month exposure denominator or unsafe conformed member/month grain | Add or generate a member-month exposure table and design conformed member/month aggregates before implementing these KPIs | metric_views/metric_view_plan.yaml and metric_views/metric_view_validation.yaml |
| Metric Views | High-cost member count is unavailable as a Metric View measure | Requires aggregate threshold filtering over member-level paid totals | Use the reference SQL in this README or add a materialized member-cost aggregate | metric_views/metric_view_plan.yaml |
| Metric Views | MoM active member growth is unavailable as a Metric View measure | Requires window LAG over monthly active-member aggregate | Use the reference SQL in this README as a dashboard dataset or create a monthly aggregate table | metric_views/metric_view_plan.yaml |
| Dashboards / Genie | Unsupported KPI questions are not answered by generated assets | Dashboards and Genie intentionally exclude unsupported KPIs | Implement the skipped/not-implemented KPIs manually before adding them to dashboards or Genie | dashboards/dashboard_validation.yaml and genie_space/member_claims_analytics_genie_v1_validation.yaml |

## 14. Generated Artifacts

Schema and data layer:

- erd_parsed.yaml
- semantic_model.yaml
- synthetic_data_spec.yaml
- data_layer_validation.yaml
- step_handoff.yaml

Metric layer:

- metric_views/schema_profile.yaml
- metric_views/kpi_metric_mapping.yaml
- metric_views/metric_view_plan.yaml
- metric_views/metric_view_design.yaml
- metric_views/member_claims_metric_view_v1.yaml
- metric_views/member_claims_enrollment_metric_view_v1.yaml
- metric_views/member_claims_enriched_metric_view_v1.yaml
- metric_views/metric_view_validation.yaml

Dashboards:

- dashboards/llm_dashboard_design.yaml
- dashboards/dashboard_design.yaml
- dashboards/dashboard_dataset_validation.yaml
- dashboards/dashboard_validation.yaml
- dashboards/member_claims_kpis_dashboard_v1_dashboard_manifest.json
- dashboards/member_claims_utilization_dashboard_v1_dashboard_manifest.json
- dashboards/member_claims_kpis_dashboard_v1_validation.yaml
- dashboards/member_claims_utilization_dashboard_v1_validation.yaml

Genie:

- genie_space/genie_semantic_inventory.yaml
- genie_space/llm_genie_design.yaml
- genie_space/member_claims_analytics_genie_v1_manifest.json
- genie_space/member_claims_analytics_genie_v1_validation.yaml
- genie_space/genie_benchmark_validation.yaml
- genie_space/benchmark_results.yaml
- genie_space/sample_queries_member_claims.sql
- genie_space/genie_space_configuration_member_claims

Run checkpoints:

- run_manifest.json
- run_context.yaml
- readme.md

## 15. Configuration Reference

Primary configuration values used by this documentation step:

| Configuration key | Value |
|---|---|
| domain.name | member_claims |
| domain.display_name | Member Claims |
| data_source.type | erd |
| catalog.source | aw_serverless_stable_catalog.aibi_member_claims |
| catalog.target | aw_serverless_stable_catalog.aibi_member_claims |
| assets.metric_views | Enabled and generated |
| assets.dashboards | Enabled; 2 dashboards generated and published |
| assets.genie | Enabled; 1 Genie Space generated and validated |
| config.version_suffix | _v1 |
| workspace.output_folder | `/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v1` |

See `accelerator.yaml` for the full source configuration. This README intentionally summarizes only the configuration values needed to understand and consume the generated solution.
