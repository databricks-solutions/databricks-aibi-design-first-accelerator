# Databricks notebook source
# DBTITLE 1,Genie Space Configuration Tool
# MAGIC %md
# MAGIC # Genie Space Configuration — member_claims
# MAGIC
# MAGIC This notebook is a modular configuration tool for managing the Genie space. Edit the configuration cells below, then run the execution cells to create or update the space.

# COMMAND ----------

# DBTITLE 1,Space Configuration
SPACE_TITLE = "member_claims_analytics_genie_v2"
SPACE_DESCRIPTION = "Production Genie space for Member Claims analytics over validated Metric Views covering claims, paid amounts, denial and clean-claim rates, provider participation, enrollment, line of business, and geography."
SPACE_ID = "01f19fe2918e1238a890e4796a9a722e"
WAREHOUSE_ID = "2d8e531640ffa469"
PARENT_PATH = "/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v2/genie_space"
TABLE_IDENTIFIERS = ["aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2", "aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2"]
print(f"Space: {SPACE_TITLE}")
print(f"Mode:  {'UPDATE existing' if SPACE_ID else 'CREATE new'}")

# COMMAND ----------

# DBTITLE 1,General Instructions
GENERAL_INSTRUCTIONS = """You are the Member Claims analytics assistant. Use only these authoritative Databricks Metric Views: aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 for claim-line measures and aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 for enrollment/member measures. Always query validated measures with MEASURE(measure_name); do not reconstruct KPI formulas from raw source tables and do not join raw tables. Claims measures available in member_claims_metric_view_v2 include total_claims for distinct claims, total_claim_lines for service/detail lines, total_paid_amount for summed paid dollars, average_paid_per_claim for paid divided by distinct claims, total_billed_amount, total_allowed_amount, denied_lines, denial_rate, clean_lines, clean_claim_rate, payment_to_billed_ratio, payment_to_allowed_ratio, unique_members for distinct claiming members, average_paid_per_member, claims_per_member, lines_per_claim, inpatient_paid_amount, outpatient_paid_amount, par_paid_amount, and participating_provider_rate. Enrollment measures available in member_enrollment_metric_view_v2 include new_member_enrollment, active_enrolled_members, and enrollment_records. Use member_claims_metric_view_v2 dimensions service_date and service_month for claim time questions, claim_type for categories such as INSTITUTIONAL, PROFESSIONAL, DENTAL, VISION, and PHARMACY, line_of_business for COMMERCIAL, MEDICARE, TRICARE, MEDICAID, and EXCHANGE, adjudication_status or line_status for APPROVED, DENIED, IN_REVIEW, and PENDING, clean_claim_indicator for Y or N, participating_provider_indicator for PAR or NON_PAR, plus benefit_category, benefit_level, place_of_service, procedure_code, rendering_provider_specialty, header_claim_type, and plan_code when requested. Use member_enrollment_metric_view_v2 dimensions enrollment_effective_date and enrollment_month for enrollment time questions, enrollment_line_of_business for LOB, enrollment_status for ACTIVE, TERMINATED, or PENDING, enrollment_plan_id, enrollment_group_name, member_state, member_zip_code, member_sex, and member_line_of_business. Interpret LOB as line of business. Interpret paid, cost, spend, and claims cost as total_paid_amount unless the user asks for average paid or paid ratio. Interpret denied percentage as denial_rate and clean percentage as clean_claim_rate. Interpret participating provider or PAR questions as participating_provider_rate or par_paid_amount depending on whether the user asks for a rate or dollars. For ratios such as denial_rate, clean_claim_rate, payment_to_billed_ratio, payment_to_allowed_ratio, average_paid_per_claim, average_paid_per_member, claims_per_member, lines_per_claim, and participating_provider_rate, never sum the ratio; use MEASURE() and group by dimensions so Metric View semantics recompute correctly. For monthly claim trends use service_month; for monthly enrollment trends use enrollment_month. For filtering examples use only discovered values: claim_type INSTITUTIONAL, PROFESSIONAL, DENTAL, VISION, PHARMACY; line of business COMMERCIAL, MEDICARE, TRICARE, MEDICAID, EXCHANGE; statuses APPROVED, DENIED, IN_REVIEW, PENDING; enrollment statuses ACTIVE, TERMINATED, PENDING; member states include NY, WA, IL, PA, CA, OH, FL, NC, GA, TX. Unsupported KPIs are PMPM, Claims per 1,000 Members, Utilization Rate, High-Cost Member Count, Rolling 3-Month PMPM, and MoM Active Member Growth because validated metric views do not contain member-month exposure, safe cross-fact ratios, required member spend preaggregation, or monthly active snapshot/window semantics; if asked, explain that the KPI is not currently supported rather than inventing SQL. Use GROUP BY ALL for grouped Metric View queries and order or limit only when analytically useful."""
print(f"General instructions: {len(GENERAL_INSTRUCTIONS):,} chars")

# COMMAND ----------

# DBTITLE 1,Metric View Descriptions
METRIC_VIEW_DESCRIPTIONS = {
    "aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2": "Validated claim-line analytical Metric View at one claim service/detail line grain. It supports claim counts, service line counts, paid/billed/allowed dollars, denial and clean claim rates, payment ratios, claiming member ratios, inpatient and outpatient paid amounts, and participating provider analysis by service date/month, claim type, LOB, statuses, place of service, procedure, and provider participation dimensions.",
    "aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2": "Validated enrollment analytical Metric View at one member enrollment coverage/event record grain. It supports new member enrollment, active enrolled members, and enrollment record counts by enrollment effective date/month, enrollment status, enrollment line of business, plan, group, member state, member ZIP, member sex, and member LOB."
}
print(f"Metric views: {len(METRIC_VIEW_DESCRIPTIONS)}")

# COMMAND ----------

# DBTITLE 1,Sample Questions
SAMPLE_QUESTIONS = ["What is the total paid amount across all claims?", "How many distinct claims are there by claim type?", "Which lines of business have the highest denial rate?", "Show the monthly trend in total paid amount by service month.", "What are total paid amount and average paid per claim for INSTITUTIONAL claims?", "How does participating provider rate compare between PAR and NON_PAR providers?", "What is the clean claim rate for MEDICARE claims?", "Compare payment-to-billed and payment-to-allowed ratios by claim type.", "Which places of service have the most claim lines?", "What are average paid per member and claims per member by line of business?", "Which claim types have the highest lines per claim?", "Compare inpatient paid amount and outpatient paid amount.", "How many new members enrolled?", "How many active enrolled members are there by enrollment line of business?", "Which member states have the most active enrolled members?", "Show monthly new member enrollment by enrollment month.", "How many active enrolled members are there by member sex for ACTIVE enrollments?", "For COMMERCIAL enrollment, how many active enrolled members and enrollment records are there?"]
print(f"Sample questions: {len(SAMPLE_QUESTIONS)}")

# COMMAND ----------

# DBTITLE 1,Example Question SQLs (Instructions)
EXAMPLE_QUESTION_SQLS = [
("What is the total paid amount across all claims?", "SELECT MEASURE(total_paid_amount) AS total_paid_amount FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2"),
("How many distinct claims are there by claim type?", "SELECT claim_type, MEASURE(total_claims) AS total_claims FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY total_claims DESC"),
("Which lines of business have the highest denial rate?", "SELECT line_of_business, MEASURE(denial_rate) AS denial_rate FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY denial_rate DESC"),
("Show the monthly trend in total paid amount by service month.", "SELECT service_month, MEASURE(total_paid_amount) AS total_paid_amount FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY service_month"),
("What are total paid amount and average paid per claim for INSTITUTIONAL claims?", "SELECT MEASURE(total_paid_amount) AS total_paid_amount, MEASURE(average_paid_per_claim) AS average_paid_per_claim FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 WHERE claim_type = 'INSTITUTIONAL'"),
("How does participating provider rate compare between PAR and NON_PAR providers?", "SELECT participating_provider_indicator, MEASURE(participating_provider_rate) AS participating_provider_rate, MEASURE(total_paid_amount) AS total_paid_amount FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY participating_provider_indicator"),
("What is the clean claim rate for MEDICARE claims?", "SELECT MEASURE(clean_claim_rate) AS clean_claim_rate FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 WHERE line_of_business = 'MEDICARE'"),
("Compare payment-to-billed and payment-to-allowed ratios by claim type.", "SELECT claim_type, MEASURE(payment_to_billed_ratio) AS payment_to_billed_ratio, MEASURE(payment_to_allowed_ratio) AS payment_to_allowed_ratio FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY claim_type"),
("Which places of service have the most claim lines?", "SELECT place_of_service, MEASURE(total_claim_lines) AS total_claim_lines FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY total_claim_lines DESC LIMIT 5"),
("What are average paid per member and claims per member by line of business?", "SELECT line_of_business, MEASURE(average_paid_per_member) AS average_paid_per_member, MEASURE(claims_per_member) AS claims_per_member FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY line_of_business"),
("Which claim types have the highest lines per claim?", "SELECT claim_type, MEASURE(lines_per_claim) AS lines_per_claim FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY lines_per_claim DESC"),
("Compare inpatient paid amount and outpatient paid amount.", "SELECT MEASURE(inpatient_paid_amount) AS inpatient_paid_amount, MEASURE(outpatient_paid_amount) AS outpatient_paid_amount FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2"),
("How many new members enrolled?", "SELECT MEASURE(new_member_enrollment) AS new_member_enrollment FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2"),
("How many active enrolled members are there by enrollment line of business?", "SELECT enrollment_line_of_business, MEASURE(active_enrolled_members) AS active_enrolled_members FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 GROUP BY ALL ORDER BY active_enrolled_members DESC"),
("Which member states have the most active enrolled members?", "SELECT member_state, MEASURE(active_enrolled_members) AS active_enrolled_members FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 GROUP BY ALL ORDER BY active_enrolled_members DESC LIMIT 5"),
("Show monthly new member enrollment by enrollment month.", "SELECT enrollment_month, MEASURE(new_member_enrollment) AS new_member_enrollment FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 GROUP BY ALL ORDER BY enrollment_month"),
("How many active enrolled members are there by member sex for ACTIVE enrollments?", "SELECT member_sex, MEASURE(active_enrolled_members) AS active_enrolled_members FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 WHERE enrollment_status = 'ACTIVE' GROUP BY ALL ORDER BY member_sex"),
("For COMMERCIAL enrollment, how many active enrolled members and enrollment records are there?", "SELECT MEASURE(active_enrolled_members) AS active_enrolled_members, MEASURE(enrollment_records) AS enrollment_records FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 WHERE enrollment_line_of_business = 'COMMERCIAL'")]
print(f"Example question SQLs: {len(EXAMPLE_QUESTION_SQLS)}")

# COMMAND ----------

# DBTITLE 1,Benchmark Questions
BENCHMARK_QUESTIONS = [
("How much paid spend is represented in the validated claims view?", "SELECT MEASURE(total_paid_amount) AS total_paid_amount FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2"),
("Rank claim categories by distinct claim volume.", "SELECT claim_type, MEASURE(total_claims) AS total_claims FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY total_claims DESC"),
("By LOB, where is the denied-line percentage highest?", "SELECT line_of_business, MEASURE(denial_rate) AS denial_rate FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY denial_rate DESC"),
("Trend paid dollars over claim service months.", "SELECT service_month, MEASURE(total_paid_amount) AS total_paid_amount FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY service_month"),
("For institutional claims, return paid dollars and paid per claim.", "SELECT MEASURE(total_paid_amount) AS total_paid_amount, MEASURE(average_paid_per_claim) AS average_paid_per_claim FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 WHERE claim_type = 'INSTITUTIONAL'"),
("Show paid dollars and PAR rate by provider participation flag.", "SELECT participating_provider_indicator, MEASURE(participating_provider_rate) AS participating_provider_rate, MEASURE(total_paid_amount) AS total_paid_amount FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY participating_provider_indicator"),
("What percent of Medicare claim lines are clean claims?", "SELECT MEASURE(clean_claim_rate) AS clean_claim_rate FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 WHERE line_of_business = 'MEDICARE'"),
("Return paid-to-billed and paid-to-allowed percentages for each claim type.", "SELECT claim_type, MEASURE(payment_to_billed_ratio) AS payment_to_billed_ratio, MEASURE(payment_to_allowed_ratio) AS payment_to_allowed_ratio FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY claim_type"),
("List top service place codes by service line count.", "SELECT place_of_service, MEASURE(total_claim_lines) AS total_claim_lines FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY total_claim_lines DESC LIMIT 5"),
("Compare paid per claiming member and claims per claiming member by LOB.", "SELECT line_of_business, MEASURE(average_paid_per_member) AS average_paid_per_member, MEASURE(claims_per_member) AS claims_per_member FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY line_of_business"),
("For each claim type, calculate service lines per distinct claim.", "SELECT claim_type, MEASURE(lines_per_claim) AS lines_per_claim FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2 GROUP BY ALL ORDER BY lines_per_claim DESC"),
("Return inpatient paid versus outpatient paid from the claims metric view.", "SELECT MEASURE(inpatient_paid_amount) AS inpatient_paid_amount, MEASURE(outpatient_paid_amount) AS outpatient_paid_amount FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2"),
("What is the validated count of newly enrolled members?", "SELECT MEASURE(new_member_enrollment) AS new_member_enrollment FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2"),
("Break out active enrolled membership by enrollment LOB.", "SELECT enrollment_line_of_business, MEASURE(active_enrolled_members) AS active_enrolled_members FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 GROUP BY ALL ORDER BY active_enrolled_members DESC"),
("Which states have the largest active enrolled populations?", "SELECT member_state, MEASURE(active_enrolled_members) AS active_enrolled_members FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 GROUP BY ALL ORDER BY active_enrolled_members DESC LIMIT 5"),
("Show the effective-month trend for new member enrollment.", "SELECT enrollment_month, MEASURE(new_member_enrollment) AS new_member_enrollment FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 GROUP BY ALL ORDER BY enrollment_month"),
("For active enrollment records, break active members down by sex.", "SELECT member_sex, MEASURE(active_enrolled_members) AS active_enrolled_members FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 WHERE enrollment_status = 'ACTIVE' GROUP BY ALL ORDER BY member_sex"),
("Within Commercial enrollment, return active members and total enrollment event rows.", "SELECT MEASURE(active_enrolled_members) AS active_enrolled_members, MEASURE(enrollment_records) AS enrollment_records FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2 WHERE enrollment_line_of_business = 'COMMERCIAL'")]
print(f"Benchmark questions: {len(BENCHMARK_QUESTIONS)}")

# COMMAND ----------

# DBTITLE 1,Helper Functions
import json, uuid, requests
COLUMN_CONFIGS = {"aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2": sorted([{"column_name": c} for c in ["adjudication_status","average_paid_per_claim","average_paid_per_member","benefit_category","benefit_level","claim_type","claims_per_member","clean_claim_indicator","clean_claim_rate","clean_lines","denial_rate","denied_lines","header_claim_type","inpatient_paid_amount","line_of_business","line_status","lines_per_claim","outpatient_paid_amount","par_paid_amount","participating_provider_indicator","participating_provider_rate","payment_to_allowed_ratio","payment_to_billed_ratio","place_of_service","plan_code","procedure_code","rendering_provider_specialty","service_date","service_month","total_allowed_amount","total_billed_amount","total_claim_lines","total_claims","total_paid_amount","unique_members"]], key=lambda x: x['column_name']), "aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2": sorted([{"column_name": c} for c in ["active_enrolled_members","enrollment_effective_date","enrollment_group_name","enrollment_line_of_business","enrollment_month","enrollment_plan_id","enrollment_records","enrollment_status","member_line_of_business","member_sex","member_state","member_zip_code","new_member_enrollment"]], key=lambda x: x['column_name'])}
def get_workspace_url(): return spark.conf.get("spark.databricks.workspaceUrl")
def get_api_headers():
    token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get(); return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
def _sorted_hex_ids(n: int) -> list[str]: return sorted(uuid.uuid4().hex for _ in range(n))
def build_serialized_space(general_instructions, metric_view_descriptions, sample_questions, example_question_sqls, benchmark_questions):
    assert general_instructions and "\n" not in general_instructions and len(general_instructions) > 500
    sq_ids, eq_ids, bm_ids = _sorted_hex_ids(len(sample_questions)), _sorted_hex_ids(len(example_question_sqls)), _sorted_hex_ids(len(benchmark_questions)); ti_id = uuid.uuid4().hex
    payload = {"version": 2, "config": {"sample_questions": [{"id": sq_ids[i], "question": [q]} for i, q in enumerate(sample_questions)]}, "data_sources": {"tables": [{"identifier": k, "description": [v], "column_configs": COLUMN_CONFIGS.get(k, [])} for k, v in sorted(metric_view_descriptions.items())]}, "instructions": {"text_instructions": [{"id": ti_id, "content": [general_instructions]}], "example_question_sqls": [{"id": eq_ids[i], "question": [q], "sql": [sql]} for i, (q, sql) in enumerate(example_question_sqls)]}, "benchmarks": {"questions": [{"id": bm_ids[i], "question": [q], "answer": [{"format": "SQL", "content": [sql]}]} for i, (q, sql) in enumerate(benchmark_questions)]}}
    return json.dumps(payload)
print("✅ Helper functions loaded: get_workspace_url, get_api_headers, build_serialized_space")

# COMMAND ----------

# DBTITLE 1,Create or Update Space
serialised = build_serialized_space(GENERAL_INSTRUCTIONS, METRIC_VIEW_DESCRIPTIONS, SAMPLE_QUESTIONS, EXAMPLE_QUESTION_SQLS, BENCHMARK_QUESTIONS)
ws_url, headers = get_workspace_url(), get_api_headers()
resp = requests.patch(f"https://{ws_url}/api/2.0/genie/spaces/{SPACE_ID}", headers=headers, json={"title": SPACE_TITLE, "description": SPACE_DESCRIPTION, "warehouse_id": WAREHOUSE_ID, "serialized_space": serialised}) if SPACE_ID else requests.post(f"https://{ws_url}/api/2.0/genie/spaces", headers=headers, json={"title": SPACE_TITLE, "description": SPACE_DESCRIPTION, "warehouse_id": WAREHOUSE_ID, "parent_path": PARENT_PATH, "table_identifiers": TABLE_IDENTIFIERS, "serialized_space": serialised})
if resp.status_code == 200:
    result = resp.json(); SPACE_ID = result.get("space_id", SPACE_ID); print("✅ SUCCESS"); print(f"Space ID: {SPACE_ID}")
else:
    err = resp.json() if resp.headers.get('content-type','').startswith('application/json') else {}; raise RuntimeError(f"Genie Space API failed ({resp.status_code}): {err.get('error_code','UNKNOWN')} - {err.get('message', resp.text[:300])}")

# COMMAND ----------

# DBTITLE 1,Validate Space
ws_url, headers = get_workspace_url(), get_api_headers(); resp = requests.get(f"https://{ws_url}/api/2.0/genie/spaces/{SPACE_ID}?include_serialized_space=true", headers=headers)
if resp.status_code != 200: raise RuntimeError(f"Failed to read space: {resp.status_code} {resp.text[:300]}")
data = resp.json(); ss = json.loads(data["serialized_space"]); sqs = ss.get("config", {}).get("sample_questions", []); tables = ss.get("data_sources", {}).get("tables", []); tis = ss.get("instructions", {}).get("text_instructions", []); eqs = ss.get("instructions", {}).get("example_question_sqls", []); bms = ss.get("benchmarks", {}).get("questions", [])
print("=" * 60); print("GENIE SPACE VALIDATION REPORT"); print("=" * 60); print(f"Title: {data.get('title')}"); print(f"Space ID: {data.get('space_id', SPACE_ID)}"); print(f"Warehouse: {data.get('warehouse_id', 'N/A')}"); print(f"Metric Views/Tables: {len(tables)}"); print(f"Sample Questions: {len(sqs)}"); print(f"Example SQLs: {len(eqs)}"); print(f"Benchmark Questions: {len(bms)}"); print(f"Text Instructions: {len(tis)} block(s), {sum(len(t['content'][0]) for t in tis)} chars")
assert len(tables) >= 1 and len(sqs) >= 15 and len(eqs) >= 15 and len(bms) >= 15 and sum(len(t['content'][0]) for t in tis) > 500
print("✅ Validation complete")
dbutils.notebook.exit(json.dumps({"space_id": SPACE_ID, "title": data.get("title"), "sample_questions": len(sqs), "example_sqls": len(eqs), "benchmarks": len(bms), "tables": len(tables)}))

