# Databricks notebook source
# DBTITLE 1,Validate Deployed Genie Space
import json
from databricks.sdk import WorkspaceClient

SPACE_ID = "01f1a5b1d16312cc89683e12db7e4d55"
EXPECTED_TITLE = "member_claims_analytics_genie_v1"
EXPECTED_WAREHOUSE_ID = "2d8e531640ffa469"
EXPECTED_TABLES = [
    "aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1",
    "aw_serverless_stable_catalog.aibi_member_claims.member_claims_enrollment_metric_view_v1",
    "aw_serverless_stable_catalog.aibi_member_claims.member_claims_enriched_metric_view_v1",
]

w = WorkspaceClient()
data = w.api_client.do("GET", f"/api/2.0/genie/spaces/{SPACE_ID}", query={"include_serialized_space":"true"})
ss_raw = data.get("serialized_space") or "{}"
ss = json.loads(ss_raw)

sqs = ss.get("config", {}).get("sample_questions", [])
mvs = ss.get("data_sources", {}).get("metric_views", []) or ss.get("data_sources", {}).get("tables", [])
tis = ss.get("instructions", {}).get("text_instructions", [])
eqs = ss.get("instructions", {}).get("example_question_sqls", [])
bms = ss.get("benchmarks", {}).get("questions", [])
instr_total = sum(len(''.join(t.get('content', []))) for t in tis)
actual_tables = sorted([mv.get("identifier") for mv in mvs])

issues = []
if data.get("space_id") != SPACE_ID: issues.append("space_id mismatch")
if data.get("title") != EXPECTED_TITLE: issues.append(f"title mismatch: {data.get('title')}")
if len(sqs) < 15: issues.append(f"sample questions too few: {len(sqs)}")
if len(eqs) < 10: issues.append(f"example SQL too few: {len(eqs)}")
if len(bms) < 15: issues.append(f"benchmarks too few: {len(bms)}")
if instr_total < 500: issues.append(f"instructions too short: {instr_total}")
if len(mvs) < 3: issues.append(f"metric views too few: {len(mvs)}")
for t in EXPECTED_TABLES:
    if t not in actual_tables:
        issues.append(f"missing table: {t}")

result = {
    "space_id": SPACE_ID,
    "title": data.get("title"),
    "warehouse_id": data.get("warehouse_id"),
    "metric_view_count": len(mvs),
    "actual_tables": actual_tables,
    "sample_question_count": len(sqs),
    "example_sql_count": len(eqs),
    "benchmark_count": len(bms),
    "instruction_chars": instr_total,
    "status": "PASS" if not issues else "FAIL",
    "issues": issues,
}
print(json.dumps(result, indent=2))
assert not issues, "; ".join(issues)
dbutils.notebook.exit(json.dumps(result))

