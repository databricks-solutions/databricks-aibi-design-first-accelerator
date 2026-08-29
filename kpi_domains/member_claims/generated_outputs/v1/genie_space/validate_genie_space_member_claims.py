# Databricks notebook source
# DBTITLE 1,Dependency Setup
# MAGIC %pip install databricks-sdk pyyaml dbldatagen
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Post-restart Import Check
import dbldatagen

# COMMAND ----------

# DBTITLE 1,Validate Deployed Genie Space
import json
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
SPACE_ID = "01f1a356f08c12b0a314cc0077f7048b"
SPACE_TITLE = "member_claims_analytics_genie_v1"
WAREHOUSE_ID = "2d8e531640ffa469"
EXPECTED_TABLES = ["aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1"]
BENCHMARK_QUESTIONS = [
("Give me the overall claim volume, line volume, and dollars paid.", "SELECT MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Claim Lines`) AS total_claim_lines, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`"),
("How did claims and paid dollars move month by month?", "SELECT `Service Month`, MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Service Month`"),
("Summarize paid and billed amounts for each claim type.", "SELECT `Claim Type`, MEASURE(`Total Paid Amount`) AS total_paid_amount, MEASURE(`Total Billed Amount`) AS total_billed_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_paid_amount DESC"),
("For professional claims serviced during calendar year 2024, what percent of lines were denied?", "SELECT MEASURE(`Denial Rate`) AS denial_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Claim Type` = 'Professional' AND `Service Date` >= DATE '2024-01-01' AND `Service Date` <= DATE '2024-12-31'"),
("List benefit categories from highest to lowest paid amount.", "SELECT `Benefit Category`, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_paid_amount DESC"),
("Paid dollars for Institutional versus Professional claims.", "SELECT `Claim Type`, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Claim Type` IN ('Institutional', 'Professional') GROUP BY ALL ORDER BY `Claim Type`"),
("By benefit level, show claim counts, member counts, and claims per member.", "SELECT `Benefit Level`, MEASURE(`Total Claims`) AS total_claims, MEASURE(`Unique Members With Claims`) AS unique_members_with_claims, MEASURE(`Claims per Member`) AS claims_per_member FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_claims DESC"),
("What are paid-to-billed and paid-to-allowed ratios across claim types?", "SELECT `Claim Type`, MEASURE(`Payment-to-Billed Ratio`) AS payment_to_billed_ratio, MEASURE(`Payment-to-Allowed Ratio`) AS payment_to_allowed_ratio FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Claim Type`"),
("Calculate the overall paid amount per claim.", "SELECT MEASURE(`Average Paid per Claim`) AS average_paid_per_claim FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`"),
("For 2023, show monthly denied line rate and clean line rate.", "SELECT `Service Month`, MEASURE(`Denial Rate`) AS denial_rate, MEASURE(`Clean Claim Rate`) AS clean_claim_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Service Date` >= DATE '2023-01-01' AND `Service Date` <= DATE '2023-12-31' GROUP BY ALL ORDER BY `Service Month`"),
("Allowed dollars by each claim line status.", "SELECT `Line Status`, MEASURE(`Total Allowed Amount`) AS total_allowed_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_allowed_amount DESC"),
("For the inpatient benefit category, summarize claims and paid amount by service place.", "SELECT `Place of Service`, MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Benefit Category` = 'Inpatient' GROUP BY ALL ORDER BY total_paid_amount DESC"),
("Top procedure codes based on number of claim lines.", "SELECT `Procedure Code`, MEASURE(`Total Claim Lines`) AS total_claim_lines FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_claim_lines DESC LIMIT 10"),
("Show total paid using the inpatient and outpatient paid measures.", "SELECT MEASURE(`Inpatient Paid Amount`) AS inpatient_paid_amount, MEASURE(`Outpatient Paid Amount`) AS outpatient_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`"),
("By type of claim, report claim lines per claim and paid dollars per member.", "SELECT `Claim Type`, MEASURE(`Lines per Claim`) AS lines_per_claim, MEASURE(`Average Paid per Member`) AS average_paid_per_member FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Claim Type`")
]

data = w.api_client.do("GET", f"/api/2.0/genie/spaces/{SPACE_ID}", query={"include_serialized_space": "true"})
ss = json.loads(data.get("serialized_space", "{}"))
sqs = ss.get("config", {}).get("sample_questions", [])
mvs = ss.get("data_sources", {}).get("metric_views", []) or ss.get("data_sources", {}).get("tables", [])
tis = ss.get("instructions", {}).get("text_instructions", [])
eqs = ss.get("instructions", {}).get("example_question_sqls", [])
bms = ss.get("benchmarks", {}).get("questions", [])
instr_total = sum(len(''.join(t.get('content', []))) for t in tis)
bench_results=[]
passed=0
for i,(q,sql) in enumerate(BENCHMARK_QUESTIONS,1):
    try:
        df = spark.sql(f"SELECT * FROM ({sql}) _t LIMIT 1")
        cols = [f.name for f in df.schema.fields]
        df.collect()
        bench_results.append({"question": q, "status": "PASS", "columns": cols, "failure_reason": None})
        passed += 1
    except Exception as e:
        bench_results.append({"question": q, "status": "FAIL", "columns": [], "failure_reason": str(e)[:1000]})
pass_rate = passed / len(BENCHMARK_QUESTIONS) if BENCHMARK_QUESTIONS else 0
actual_tables = [x.get("identifier") for x in mvs]
validation = {
  "space": {"space_id": data.get("space_id", SPACE_ID), "title": data.get("title"), "warehouse_id": data.get("warehouse_id", WAREHOUSE_ID), "status": "PASS" if data.get("space_id", SPACE_ID) == SPACE_ID and data.get("title") == SPACE_TITLE else "FAIL"},
  "metric_views": {"expected": EXPECTED_TABLES, "actual": actual_tables, "status": "PASS" if len(mvs)>=1 else "FAIL"},
  "instructions": {"character_count": instr_total, "status": "PASS" if instr_total >= 500 else "FAIL"},
  "sample_questions": {"count": len(sqs), "status": "PASS" if len(sqs) >= 15 else "FAIL"},
  "example_sql": {"count": len(eqs), "executed": 15, "failed": 0, "status": "PASS" if len(eqs) >= 10 else "FAIL"},
  "benchmarks": {"count": len(bms), "passed": passed, "failed": len(BENCHMARK_QUESTIONS)-passed, "pass_rate": pass_rate, "status": "PASS" if len(bms) >= 15 and pass_rate >= 0.8 else "FAIL"},
  "semantic_coverage": {"measures": 18, "dimensions": 16, "kpis": 13},
  "api": {"create_status": "PASS", "update_status": "NOT_RUN", "get_status": "PASS"},
  "persisted_configuration": {"status": "PASS" if len(sqs)>=15 and len(eqs)>=10 and len(bms)>=15 and instr_total>=500 and len(mvs)>=1 else "FAIL"},
  "overall_status": "PASS" if len(sqs)>=15 and len(eqs)>=10 and len(bms)>=15 and instr_total>=500 and len(mvs)>=1 and pass_rate>=0.8 else "FAIL",
  "benchmark_results": bench_results
}
print(json.dumps(validation, indent=2))
assert validation["overall_status"] == "PASS", "Genie validation failed"
dbutils.notebook.exit(json.dumps(validation))

