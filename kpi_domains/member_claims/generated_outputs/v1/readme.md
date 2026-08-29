# Member Claims Accelerator Run Summary

Generated: 2026-08-29T00:00:00Z  
Version: `_v1`  
Overall status: **PARTIAL_SUCCESS**

This document is a factual summary of the generated accelerator run for the Member Claims domain. It is derived from the run artifacts and deployment manifests in `/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v1`.

## 1. Solution Overview

This accelerator run created a semantic analytics solution for **Member Claims** using **ERD greenfield** mode. The solution includes:

- 8 generated Unity Catalog tables with synthetic data.
- 1 validated Metric View.
- 2 published AI/BI dashboards.
- 1 configured and validated Genie Space.
- 13 KPIs implemented and validated in the Metric View.
- 10 KPIs skipped with explicit terminal reasons in `metric_view_validation.yaml`.

Run metadata:

| Item | Value |
|---|---|
| Domain display name | Member Claims |
| Domain name | member_claims |
| Version suffix | `_v1` |
| Data-source mode | `erd` |
| Source catalog/schema | `aw_serverless_stable_catalog.aibi_member_claims` |
| Target catalog/schema | `aw_serverless_stable_catalog.aibi_member_claims` |
| Overall run status | PARTIAL_SUCCESS |
| LLM model | `databricks-gpt-5-5` |
| Vision model | `databricks-gpt-5-5` |
| Dashboard design model | `databricks-gpt-5-5` |
| Genie design model | `databricks-gpt-5-5` |
| SQL warehouse | `2d8e531640ffa469` |

The run is classified as **PARTIAL_SUCCESS** because data-layer, metric-view, dashboard, and Genie validations passed, while 10 KPIs were intentionally skipped by the Metric View validation layer due to unsafe grain, missing data, fact-to-fact fanout risk, or unsupported Metric View semantics.

## 2. Architecture / Asset Flow

Actual generated flow:

```text
ERD Image
      ↓
Parsed ERD and Semantic Model
      ↓
Generated Unity Catalog Tables with Synthetic Data
      ↓
Metric View at Claim-Line Grain
      ↓
Published AI/BI Dashboards
      ↓
Configured Genie Space
      ↓
Validation Artifacts and Run Documentation
```

The Metric View intentionally uses a single fact table source, `fact_claim_detail_v1`, with no joins. This design avoids fanout risk and limits implemented KPIs to claim-line-compatible measures.

## 3. Source Schema Summary

Source artifacts: `erd_parsed.yaml`, `semantic_model.yaml`.

Summary:

| Metric | Value |
|---|---:|
| Tables parsed | 8 |
| Relationships in semantic model | 6 |
| Generated table roles | DIMENSION, BRIDGE, SNAPSHOT, FACT |
| ERD mode | Greenfield from ERD image |
| Unresolved relationship items | 2 |

Table summary:

| Table | Role | Grain | Key relationships |
|---|---|---|---|
| `dim_member` | DIMENSION | One current or active member row per member surrogate key | Referenced by member identifier, member history, enrollment, and claim header paths |
| `dim_address` | DIMENSION | One address row for an entity, address type, and effective period | Referenced by provider address and claim header service-facility address paths |
| `dim_provider` | DIMENSION | One provider surrogate-key version or active provider row | `provider_address_sk` to `dim_address.address_key` |
| `dim_member_identifier` | BRIDGE | One identifier value and type for a member over an effective period | `member_sk` to `dim_member.member_sk` |
| `dim_member_history` | SNAPSHOT | One historical/effective-dated member attribute version per `mbr_history_sk` | `member_sk` to `dim_member.member_sk` |
| `fact_member_enrollment` | FACT | One member enrollment event or enrollment period record | `member_sk` to `dim_member.member_sk` |
| `fact_claim_header` | FACT | One claim header per claim surrogate key | `clm_member_sk` to `dim_member.member_sk`; `clm_service_facility_address_sk` to `dim_address.address_key` |
| `fact_claim_detail` | FACT | One claim service/detail line per claim id and line number | No joins included in final Metric View |

Unresolved or excluded ERD elements documented in artifacts:

| Item | Impact |
|---|---|
| `dim_address` relationship annotation was uncertain and polymorphic in the ERD | Not used as a broad polymorphic join path in analytics design |
| `fact_claim_detail` to `fact_claim_header` had low-confidence relationship evidence | Excluded from Metric View to avoid fact-to-fact fanout and unsafe joins |

No live-schema drift section is applicable because this run used `data_source.type: erd`.

## 4. Data Layer

Greenfield data generation ran and passed validation.

Source artifact: `data_layer_validation.yaml`.

| Check | Result |
|---|---|
| Overall data-layer status | PASS |
| Expected tables | 8 |
| Created tables | 8 |
| Schema reconciliation | PASS |
| Primary-key validation | PASS, 8 tested, 0 duplicate failures |
| Foreign-key validation | PASS, 6 tested, 0 orphan failures |
| Join/cardinality stability | PASS, 6 tested, 0 fanout failures |
| Semantic constraints | PASS, 3 tested |
| Domain values | PASS, 43 columns checked |
| Generic fallback columns | None |

Generated Unity Catalog tables and row counts:

| Table | Rows |
|---|---:|
| `dim_member_v1` | 500 |
| `dim_address_v1` | 300 |
| `dim_provider_v1` | 300 |
| `dim_member_identifier_v1` | 800 |
| `dim_member_history_v1` | 800 |
| `fact_member_enrollment_v1` | 1,200 |
| `fact_claim_header_v1` | 2,000 |
| `fact_claim_detail_v1` | 5,000 |

Synthetic data status: generated and validated. The validation confirms referential and semantic checks; it does not make a claim that the synthetic data reflects real production distributions.

## 5. Metric Views

Source artifacts: `metric_view_design.yaml`, `member_claims_metric_view_v1.yaml`, `metric_view_validation.yaml`.

| Metric View | FQN | Source table | Source grain | Measures | Dimensions | Status |
|---|---|---|---|---:|---:|---|
| `member_claims_metric_view_v1` | `` `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` `` | `aw_serverless_stable_catalog.aibi_member_claims.fact_claim_detail_v1` | One claim service/detail line per claim id and line number | 18 | 16 | PASS |

Validated measures:

- `Total Claims`
- `Total Claim Lines`
- `Total Paid Amount`
- `Total Billed Amount`
- `Total Allowed Amount`
- `Unique Members With Claims`
- `Denied Lines`
- `Clean Claim Lines`
- `Inpatient Paid Amount`
- `Outpatient Paid Amount`
- `Average Paid per Claim`
- `Denial Rate`
- `Clean Claim Rate`
- `Payment-to-Billed Ratio`
- `Payment-to-Allowed Ratio`
- `Average Paid per Member`
- `Claims per Member`
- `Lines per Claim`

Major dimensions include `Service Date`, `Service Month`, `Claim Type`, `Line Status`, `Adjudication Status`, `Clean Claim Indicator`, `Benefit Category`, `Benefit Level`, `Place of Service`, `Procedure Code`, and `Revenue Code`.

The Metric View contains no joins. The validation artifact records `join_validation.status: PASS` because no join fanout is possible in the single-source design.

## 6. KPI Catalog

Authoritative source for final KPI status: `metric_view_validation.yaml`. KPIs are documented as implemented only when status is `IMPLEMENTED_AND_VALIDATED`.

| KPI | Metric View | Measure | Status | Notes |
|---|---|---|---|---|
| C-1 Total Claims | `member_claims_metric_view_v1` | `Total Claims` | IMPLEMENTED_AND_VALIDATED | Baseline matched Metric View result |
| C-2 Total Claim Lines | `member_claims_metric_view_v1` | `Total Claim Lines` | IMPLEMENTED_AND_VALIDATED | Baseline matched Metric View result |
| C-3 Total Paid Amount | `member_claims_metric_view_v1` | `Total Paid Amount` | IMPLEMENTED_AND_VALIDATED | Baseline matched Metric View result |
| C-4 Average Paid per Claim | `member_claims_metric_view_v1` | `Average Paid per Claim` | IMPLEMENTED_AND_VALIDATED | Ratio matched direct baseline |
| ADD-1 Denial Rate | `member_claims_metric_view_v1` | `Denial Rate` | IMPLEMENTED_AND_VALIDATED | Ratio matched direct baseline |
| ADD-2 Clean Claim Rate | `member_claims_metric_view_v1` | `Clean Claim Rate` | IMPLEMENTED_AND_VALIDATED | Ratio matched direct baseline |
| ADD-3 Payment-to-Billed Ratio | `member_claims_metric_view_v1` | `Payment-to-Billed Ratio` | IMPLEMENTED_AND_VALIDATED | Ratio matched direct baseline |
| ADD-4 Payment-to-Allowed Ratio | `member_claims_metric_view_v1` | `Payment-to-Allowed Ratio` | IMPLEMENTED_AND_VALIDATED | Ratio matched direct baseline |
| ADD-5 Average Paid per Member | `member_claims_metric_view_v1` | `Average Paid per Member` | IMPLEMENTED_AND_VALIDATED | Ratio matched direct baseline |
| ADD-6 Claims per Member | `member_claims_metric_view_v1` | `Claims per Member` | IMPLEMENTED_AND_VALIDATED | Ratio matched direct baseline |
| ADD-7 Lines per Claim | `member_claims_metric_view_v1` | `Lines per Claim` | IMPLEMENTED_AND_VALIDATED | Ratio matched direct baseline |
| ADD-8 Inpatient Paid Amount | `member_claims_metric_view_v1` | `Inpatient Paid Amount` | IMPLEMENTED_AND_VALIDATED | Filtered additive measure matched baseline |
| ADD-9 Outpatient Paid Amount | `member_claims_metric_view_v1` | `Outpatient Paid Amount` | IMPLEMENTED_AND_VALIDATED | Filtered additive measure matched baseline |
| M-1 New Member Enrollment | Not implemented | Not applicable | SKIPPED_UNSAFE_GRAIN | Requires member effective-dated/enrollment metric view rather than claim-line grain |
| M-2 Members by Line of Business | Not implemented | Not applicable | SKIPPED_UNSAFE_GRAIN | Requires active member snapshot grain |
| M-3 Members by Geography | Not implemented | Not applicable | SKIPPED_UNSAFE_GRAIN | Requires active member snapshot/geography grain |
| MC-1 PMPM | Not implemented | Not applicable | SKIPPED_UNSAFE_GRAIN | Requires member-month exposure denominator from enrollment fact |
| MC-2 Claims per 1,000 Members | Not implemented | Not applicable | SKIPPED_UNSAFE_GRAIN | Requires member-month denominator from enrollment fact |
| MC-3 Utilization Rate | Not implemented | Not applicable | SKIPPED_FACT_TO_FACT_FANOUT_RISK | Requires unsafe claims/enrollment fact-to-fact combination |
| MC-4 High-Cost Member Count | Not implemented | Not applicable | SKIPPED_UNSUPPORTED_METRIC_VIEW_FEATURE | Requires aggregate member spend threshold before distinct-member count |
| W-1 Rolling 3-Month PMPM | Not implemented | Not applicable | SKIPPED_UNSAFE_GRAIN | Depends on unavailable safe PMPM denominator |
| W-2 MoM Active Member Growth | Not implemented | Not applicable | SKIPPED_UNSUPPORTED_METRIC_VIEW_FEATURE | Requires member snapshot calendar and LAG/offset semantics |
| ADD-10 Participating Provider Rate | Not implemented | Not applicable | SKIPPED_MISSING_DATA | Participating-provider flag absent at claim-detail grain and header join is unsafe |

KPI totals:

| Metric | Count |
|---|---:|
| Total KPIs and additional measures tracked in validation | 23 |
| Implemented and validated | 13 |
| Skipped | 10 |

## 7. Dashboards

Authoritative sources: dashboard manifests and dashboard validation artifacts.

Workspace host from `databricks.yml`: `https://fevm-aw-serverless-stable.cloud.databricks.com`.

| Dashboard | ID | Pages | Canvas pages | Widgets including filters | Published | Validation |
|---|---|---:|---:|---:|---|---|
| `member_claims_kpis_dashboard_v1` | `01f1a352b74f161b8007a612db04e89b` | 4 | 3 | 21 | true | PASS |
| `member_claims_utilization_dashboard_v1` | `01f1a352cb9e1ec181db6bd7d2817d50` | 4 | 3 | 21 | true | PASS |

Deployed dashboard links:

- `member_claims_kpis_dashboard_v1`: https://fevm-aw-serverless-stable.cloud.databricks.com/dashboardsv3/01f1a352b74f161b8007a612db04e89b/published
- `member_claims_utilization_dashboard_v1`: https://fevm-aw-serverless-stable.cloud.databricks.com/dashboardsv3/01f1a352cb9e1ec181db6bd7d2817d50/published

Dashboard details:

| Dashboard | Source Metric Views | Page structure | Widget type summary | Filter dimensions | Viz diversity | Design source |
|---|---|---|---|---|---:|---|
| `member_claims_kpis_dashboard_v1` | `` `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` `` | Filters; Financial Overview; Claims Analysis; Member Demographics | 6 counters, 7 bar charts, 3 line charts, 5 filters | Service Date, Claim Type, Line Status, Benefit Category, Clean Claim Indicator | 3 | LLM-assisted, `llm_dashboard_design.yaml` |
| `member_claims_utilization_dashboard_v1` | `` `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` `` | Filters; Utilization Patterns; Provider Insights; Operational Metrics | 7 counters, 7 bar charts, 2 line charts, 5 filters | Service Date, Claim Type, Line Status, Benefit Category, Place of Service | 3 | LLM-assisted, `llm_dashboard_design.yaml` |

Dataset validation:

| Dataset | Dashboard | SQL status | Rows | Measures | Dimensions | Semantic status |
|---|---|---|---:|---:|---:|---|
| `ds_kpis_shared` | `member_claims_kpis_dashboard_v1` | PASS | 5,000 | 18 | 10 | PASS |
| `ds_util_shared` | `member_claims_utilization_dashboard_v1` | PASS | 5,000 | 18 | 10 | PASS |

Dashboard validation confirms both dashboards were created and published, with page, dataset, widget, and filter checks passing. The representative filter impact test passed for `claim_type = Institutional`, changing total paid amount from `12,497,500.0000` to `5,016,880.0000` and total claims from `5,000` to `2,003`.

## 8. Genie Space / Genie Agent

Authoritative sources: `genie_semantic_inventory.yaml`, `llm_genie_design.yaml`, `member_claims_analytics_genie_v1_manifest.json`, `member_claims_analytics_genie_v1_validation.yaml`, `genie_benchmark_validation.yaml`.

| Item | Value |
|---|---|
| Title | `member_claims_analytics_genie_v1` |
| Space ID | `01f1a356f08c12b0a314cc0077f7048b` |
| Warehouse ID | `2d8e531640ffa469` |
| Attached Metric View | `aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1` |
| Configured | true |
| Validated | true |
| Configuration notebook path | `/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v1/genie_space/genie_space_configuration_member_claims` |
| Validation notebook path | `/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v1/genie_space/validate_genie_space_member_claims` |
| Genie link | https://fevm-aw-serverless-stable.cloud.databricks.com/genie/rooms/01f1a356f08c12b0a314cc0077f7048b |

Genie quality and validation metrics:

| Metric | Value |
|---|---:|
| Instruction character count | 2,991 |
| Instruction format | Markdown with section headers |
| Instruction section count | 6 |
| Sample questions | 15 |
| Analytical patterns covered | 8 of 8 |
| Example SQL count | 15 |
| Example SQL validation | 15 passed / 15 executed |
| Benchmark count | 15 |
| Benchmark pass rate | 100% |
| Semantic coverage | 18 measures, 16 dimensions, 13 implemented KPIs |

Representative sample questions from the generated inventory:

- What are the total claims, total claim lines, and total paid amount?
- Show the monthly trend in total claims and total paid amount by service month.
- Break down total paid amount and total billed amount by claim type.
- What is the denial rate for Professional claims in 2024?
- Rank benefit categories by total paid amount.

The Genie configuration was designed with the configured LLM reasoning model and validated from persisted Genie configuration plus benchmark SQL ground truth against the validated Metric View.

## 9. LLM-Assisted Design Summary

LLM design artifacts exist for dashboards and Genie.

### Dashboard Design

| Item | Value |
|---|---|
| Design artifact | `dashboards/llm_dashboard_design.yaml` |
| Model | `databricks-gpt-5-5` |
| Dashboards designed | 2 |
| Canvas pages per dashboard | 3 |
| Total pages per dashboard | 4 including global filter page |
| Widget density | 16 canvas widgets per dashboard plus 5 filters |
| Visualization diversity | 3 distinct visualization types per dashboard: counter, bar, line |
| Gate 3.1 multi-page enforcement | PASS |

Key design decisions reflected in artifacts:

- The KPI Overview dashboard separates financial overview, claims analysis, and member-demographic mapped content.
- The Utilization dashboard separates utilization patterns, provider-adjacent insights, and operational metrics.
- Skipped Metric View KPIs were not rendered as validated dashboard KPIs.

### Genie Space Design

| Item | Value |
|---|---|
| Design artifact | `genie_space/llm_genie_design.yaml` |
| Model | `databricks-gpt-5-5` |
| Instructions | 2,991 characters in validated persisted configuration |
| Format | Markdown with `##` section headers |
| Sections | Purpose, Dimensions, Measures, Aggregation Rules, Time Guidance, SQL Style |
| Question pattern coverage | 8 of 8: HEADLINE, TIME_TREND, DIMENSION_BREAKDOWN, FILTERED, RANKING, COMPARISON, MULTI_MEASURE, RATIO |
| Example SQL validation | 15 passed / 15 total |
| Benchmark questions | 15 |
| Benchmark answer format | SQL ground truth executed against the validated Metric View |

## 10. Validation Summary

| Layer | Validation | Result | Artifact |
|---|---|---|---|
| Data Layer | Schema reconciliation | PASS | `data_layer_validation.yaml` |
| Data Layer | PK/FK integrity | PASS | `data_layer_validation.yaml` |
| Data Layer | Join/cardinality stability | PASS | `data_layer_validation.yaml` |
| Data Layer | Semantic constraints and domain values | PASS | `data_layer_validation.yaml` |
| Metric Layer | Metric View structural validation | PASS | `metric_views/metric_view_validation.yaml` |
| Metric Layer | KPI baseline reconciliation | PASS | `metric_views/metric_view_validation.yaml` |
| Metric Layer | Join fanout checks | PASS | `metric_views/metric_view_validation.yaml` |
| Dashboards | Dataset SQL | PASS | `dashboards/dashboard_dataset_validation.yaml` |
| Dashboards | Page/widget/filter validation | PASS | `dashboards/dashboard_validation.yaml` |
| Dashboards | Publication state | PASS | Dashboard manifests, `published: true` |
| Genie | Persisted configuration | PASS | `genie_space/member_claims_analytics_genie_v1_validation.yaml` |
| Genie | Example SQL execution | PASS | `genie_space/member_claims_analytics_genie_v1_validation.yaml` |
| Genie | Benchmarks | PASS | `genie_space/genie_benchmark_validation.yaml` |

## 11. Known Limitations

Known limitations are sourced from validation artifacts.

| Limitation | Layer | Impact | Reason |
|---|---|---|---|
| M-1 New Member Enrollment | Metric View | KPI not available | Requires member effective-dated/enrollment metric view rather than claim-line grain |
| M-2 Members by Line of Business | Metric View | KPI not available | Requires active member snapshot grain |
| M-3 Members by Geography | Metric View | KPI not available | Requires active member snapshot/geography grain |
| MC-1 PMPM | Metric View | KPI not available | Requires member-month exposure denominator from enrollment fact |
| MC-2 Claims per 1,000 Members | Metric View | KPI not available | Requires member-month denominator from enrollment fact |
| MC-3 Utilization Rate | Metric View | KPI not available | Requires unsafe claims/enrollment fact-to-fact combination |
| MC-4 High-Cost Member Count | Metric View | KPI not available | Requires aggregate member spend threshold before distinct-member count |
| W-1 Rolling 3-Month PMPM | Metric View | KPI not available | Depends on unavailable safe PMPM denominator |
| W-2 MoM Active Member Growth | Metric View | KPI not available | Requires member snapshot calendar and LAG/offset semantics |
| ADD-10 Participating Provider Rate | Metric View | KPI not available | Participating-provider flag absent at claim-detail grain and header join is unsafe |
| `fact_claim_detail` to `fact_claim_header` join excluded | Semantic/Metric layer | Header-level provider fields are not available in the Metric View | Relationship confidence was low and fact-to-fact join was considered unsafe |
| `dim_address` polymorphic relationship | Semantic layer | Generic entity-address analytics are not exposed through the Metric View | ERD annotation was uncertain and polymorphic |

No generic fallback columns were reported in `data_layer_validation.yaml`.

## 12. Usage

### Query Metric Views

Use the validated Metric View with Metric View measure syntax.

```sql
SELECT
  `Claim Type`,
  MEASURE(`Total Claims`) AS total_claims,
  MEASURE(`Total Paid Amount`) AS total_paid_amount,
  MEASURE(`Denial Rate`) AS denial_rate
FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`
GROUP BY ALL
ORDER BY total_paid_amount DESC;
```

A time-trend query using validated dimensions and measures:

```sql
SELECT
  `Service Month`,
  MEASURE(`Total Claims`) AS total_claims,
  MEASURE(`Total Paid Amount`) AS total_paid_amount
FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`
GROUP BY ALL
ORDER BY `Service Month`;
```

### Dashboards

Open these published dashboards:

- `member_claims_kpis_dashboard_v1` for financial overview, claims analysis, and member-claim segmentation.
- `member_claims_utilization_dashboard_v1` for utilization patterns, provider-adjacent service/procedure analysis, and operational metrics.

Dashboard IDs and links are listed in Section 7.

### Genie

Open Genie Space `member_claims_analytics_genie_v1` using the link in Section 8. Ask questions grounded in the configured semantic model and the validated Metric View. Representative supported questions include:

- What are the total claims, total claim lines, and total paid amount?
- Show the monthly trend in total claims and total paid amount by service month.
- What are the payment-to-billed ratio and payment-to-allowed ratio by claim type?
- Which procedure codes have the highest total claim lines?

Do not ask Genie to answer skipped KPIs such as PMPM, active member growth, or participating provider rate unless additional semantic assets are added.

## 13. Troubleshooting

This section is included because overall run status is PARTIAL_SUCCESS.

| Layer | Symptom | Root Cause | Resolution | Artifact |
|---|---|---|---|---|
| Metric Views | PMPM, member snapshot, high-cost member, active member growth, and participating provider KPIs are unavailable | Metric View validation skipped these KPIs for unsafe grain, missing data, fact-to-fact fanout risk, or unsupported Metric View semantics | Add separate safe-grain Metric Views for member snapshot/enrollment exposure, or add validated pre-aggregations for high-cost member logic | `metric_views/metric_view_validation.yaml` |
| Dashboards | Dashboard pages do not show skipped KPI widgets | Dashboard validation excludes KPIs not implemented and validated in the Metric Layer | Extend Metric Layer first, then regenerate dashboard designs | `dashboards/dashboard_validation.yaml` |
| Genie | Genie should not answer unsupported PMPM/member-growth/provider-rate questions from the current semantic model | Genie is configured only with the validated claim-line Metric View | Add and validate the missing semantic assets before expanding Genie instructions or sample questions | `genie_space/member_claims_analytics_genie_v1_validation.yaml` |

## 14. Generated Artifacts

Important files that exist for this run:

Schema and data layer:

- `erd_parsed.yaml`
- `semantic_model.yaml`
- `synthetic_data_spec.yaml`
- `data_layer_validation.yaml`

Metric layer:

- `metric_views/schema_profile.yaml`
- `metric_views/kpi_metric_mapping.yaml`
- `metric_views/metric_view_design.yaml`
- `metric_views/member_claims_metric_view_v1.yaml`
- `metric_views/metric_view_validation.yaml`

Dashboards:

- `dashboards/llm_dashboard_design.yaml`
- `dashboards/dashboard_design.yaml`
- `dashboards/dashboard_dataset_validation.yaml`
- `dashboards/pre_deploy_check.yaml`
- `dashboards/member_claims_kpis_dashboard_v1_manifest.json`
- `dashboards/member_claims_utilization_dashboard_v1_manifest.json`
- `dashboards/member_claims_kpis_dashboard_v1_validation.yaml`
- `dashboards/member_claims_utilization_dashboard_v1_validation.yaml`
- `dashboards/dashboard_validation.yaml`

Genie:

- `genie_space/genie_semantic_inventory.yaml`
- `genie_space/llm_genie_design.yaml`
- `genie_space/member_claims_analytics_genie_v1_manifest.json`
- `genie_space/member_claims_analytics_genie_v1_validation.yaml`
- `genie_space/benchmark_results.yaml`
- `genie_space/genie_benchmark_validation.yaml`
- `genie_space/sample_queries_member_claims.sql`

Run state and handoff:

- `step_handoff.yaml`
- `run_context.yaml`
- `run_manifest.json`
- `readme.md`

## 15. Configuration Reference

Primary configuration used by this run:

| Key | Value |
|---|---|
| `domain.name` | `member_claims` |
| `domain.display_name` | `Member Claims` |
| `data_source.type` | `erd` |
| `data_source.greenfield.enabled` | `true` |
| `data_source.greenfield.synthetic_data` | `true` |
| `catalog.source.catalog` | `aw_serverless_stable_catalog` |
| `catalog.source.schema` | `aibi_member_claims` |
| `catalog.target.catalog` | `aw_serverless_stable_catalog` |
| `catalog.target.schema` | `aibi_member_claims` |
| `assets.metric_views` | `member_claims_metric_view` |
| `assets.dashboards` | `member_claims_kpis_dashboard`, `member_claims_utilization_dashboard` |
| `assets.genie.space_name` | `member_claims_analytics_genie` |
| `assets.sample_queries_file` | `sample_queries_member_claims.sql` |
| `config.version_suffix` | `_v1` |
| `pipeline.create_data_layer.enabled` | `true` |
| `pipeline.create_metric_views.enabled` | `true` |
| `pipeline.create_dashboards.enabled` | `true` |
| `pipeline.create_genie_space.enabled` | `true` |

See `accelerator.yaml` for the complete configuration.
