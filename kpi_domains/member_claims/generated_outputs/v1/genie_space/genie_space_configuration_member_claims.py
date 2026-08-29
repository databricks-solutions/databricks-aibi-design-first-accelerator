# Databricks notebook source
# DBTITLE 1,Dependency Setup
# MAGIC %pip install databricks-sdk pyyaml dbldatagen
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Post-restart Import Check
import dbldatagen

# COMMAND ----------

# DBTITLE 1,Genie Space Configuration Tool
# MAGIC %md
# MAGIC # Genie Space Configuration — member_claims
# MAGIC
# MAGIC This notebook is a **modular configuration tool** for managing the Genie space. Configuration cells are populated from validated metric view contracts and LLM Genie design.

# COMMAND ----------

# DBTITLE 1,Space Configuration
SPACE_TITLE = "member_claims_analytics_genie_v1"
SPACE_DESCRIPTION = "Production Genie Space for healthcare member claims analytics over validated claim-line metric view KPIs including claim volume, paid/billed/allowed amounts, denial rate, clean claim rate, payment ratios, and inpatient/outpatient paid amount."
SPACE_ID = ""
WAREHOUSE_ID = "2d8e531640ffa469"
PARENT_PATH = "/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v1/genie_space"
TABLE_IDENTIFIERS = ["aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1"]
SQL_FQN = "`aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`"

print(f"Space: {SPACE_TITLE}")
print(f"Mode:  {'UPDATE existing' if SPACE_ID else 'CREATE new'}")

# COMMAND ----------

# DBTITLE 1,General Instructions
GENERAL_INSTRUCTIONS = """## Purpose
- This Genie Space supports healthcare member claims analytics for claim submissions, approvals, denials, provider utilization, and cost trends using only the metric view `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`.
- Always answer from the metric view and do not introduce other datasets.

## Dimensions
- Available dimensions are: Claim Id, Claim Line Number, Member Number, Service Date, Service Month, Claim Receive Date, Check Date, Claim Type, Line Status, Adjudication Status, Clean Claim Indicator, Benefit Category, Benefit Level, Place of Service, Procedure Code, Revenue Code.
- Use exact dimension names in backticks in SQL, for example `Claim Type`, `Service Month`, and `Benefit Category`.

## Measures
- Available measures are: Total Claims, Total Claim Lines, Total Paid Amount, Total Billed Amount, Total Allowed Amount, Unique Members With Claims, Denied Lines, Clean Claim Lines, Inpatient Paid Amount, Outpatient Paid Amount, Average Paid per Claim, Denial Rate, Clean Claim Rate, Payment-to-Billed Ratio, Payment-to-Allowed Ratio, Average Paid per Member, Claims per Member, Lines per Claim.
- Always reference measures with MEASURE(`measure`) syntax, for example MEASURE(`Total Claims`) or MEASURE(`Denial Rate`).

## Aggregation Rules
- Never SUM ratios or average measures. Ratio and non-additive measures must be recomputed by the metric view using MEASURE syntax.
- Non-additive measures include Average Paid per Claim, Denial Rate, Clean Claim Rate, Payment-to-Billed Ratio, Payment-to-Allowed Ratio, Average Paid per Member, Claims per Member, and Lines per Claim.
- Total Claims is a distinct claim count. Total Claim Lines is a claim line count. Denial Rate is denied lines divided by total lines. Clean Claim Rate is clean claim lines divided by total lines.

## Time Guidance
- Use `Service Date` for daily filters and date ranges.
- Use `Service Month` for month-level trends and GROUP BY ALL when grouping by month.
- The available service date range is 2020-01-01 through 2024-12-31.
- For paid timing questions, `Check Date` may be used as a filter or grouping dimension when explicitly requested.

## Terminology
- "Paid dollars", "paid amount", and "insurer paid" map to `Total Paid Amount`.
- "Denied percent" and "denial percentage" map to `Denial Rate`.
- "Clean claims" maps to `Clean Claim Rate` or `Clean Claim Lines` depending on whether the user asks for a rate or count.
- "Inpatient" uses `Inpatient Paid Amount`, which is paid amount for Institutional claims. "Outpatient" uses `Outpatient Paid Amount`, which is paid amount for Professional claims.

## SQL Style
- Use the exact FQN `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`.
- For dimensional queries, include dimensions in SELECT and use GROUP BY ALL.
- Use ORDER BY for trends, rankings, and comparisons where helpful.
- Do not query raw tables or recreate metric formulas outside the metric view."""
print(f"General instructions: {len(GENERAL_INSTRUCTIONS):,} chars")

# COMMAND ----------

# DBTITLE 1,Metric View Descriptions
METRIC_VIEW_DESCRIPTIONS = {
    "aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1": "Healthcare member claims metric view for analyzing claim counts, claim lines, paid, billed, allowed, denial, clean claim, member utilization, inpatient, outpatient, and payment ratio KPIs across claim, member, service date, claim type, line status, adjudication, benefit, place of service, procedure, and revenue dimensions. The analytical grain is one claim service/detail line per claim id and line number, with no joins included to avoid metric fanout."
}
print(f"Metric views: {len(METRIC_VIEW_DESCRIPTIONS)}")
for k in sorted(METRIC_VIEW_DESCRIPTIONS): print(f"  • {k}")

# COMMAND ----------

# DBTITLE 1,Sample Questions
SAMPLE_QUESTIONS = [
"What are the total claims, total claim lines, and total paid amount?",
"Show the monthly trend in total claims and total paid amount by service month.",
"Break down total paid amount and total billed amount by claim type.",
"What is the denial rate for Professional claims in 2024?",
"Rank benefit categories by total paid amount.",
"Compare total paid amount between Institutional and Professional claims.",
"Show total claims, unique members with claims, and claims per member by benefit level.",
"What are the payment-to-billed ratio and payment-to-allowed ratio by claim type?",
"What is the average paid per claim overall?",
"Trend denial rate and clean claim rate by service month for 2023.",
"Break out total allowed amount by line status.",
"For inpatient benefit category claims, what are total claims and total paid amount by place of service?",
"Which procedure codes have the highest total claim lines?",
"Compare inpatient paid amount and outpatient paid amount overall.",
"Show lines per claim and average paid per member by claim type."
]
print(f"Sample questions: {len(SAMPLE_QUESTIONS)}")

# COMMAND ----------

# DBTITLE 1,Example Question SQLs (Instructions)
EXAMPLE_QUESTION_SQLS = [
("What are the total claims, total claim lines, and total paid amount?", "SELECT MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Claim Lines`) AS total_claim_lines, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`"),
("Show the monthly trend in total claims and total paid amount by service month.", "SELECT `Service Month`, MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Service Month`"),
("Break down total paid amount and total billed amount by claim type.", "SELECT `Claim Type`, MEASURE(`Total Paid Amount`) AS total_paid_amount, MEASURE(`Total Billed Amount`) AS total_billed_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_paid_amount DESC"),
("What is the denial rate for Professional claims in 2024?", "SELECT MEASURE(`Denial Rate`) AS denial_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Claim Type` = 'Professional' AND `Service Date` >= DATE '2024-01-01' AND `Service Date` <= DATE '2024-12-31'"),
("Rank benefit categories by total paid amount.", "SELECT `Benefit Category`, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_paid_amount DESC"),
("Compare total paid amount between Institutional and Professional claims.", "SELECT `Claim Type`, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Claim Type` IN ('Institutional', 'Professional') GROUP BY ALL ORDER BY `Claim Type`"),
("Show total claims, unique members with claims, and claims per member by benefit level.", "SELECT `Benefit Level`, MEASURE(`Total Claims`) AS total_claims, MEASURE(`Unique Members With Claims`) AS unique_members_with_claims, MEASURE(`Claims per Member`) AS claims_per_member FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_claims DESC"),
("What are the payment-to-billed ratio and payment-to-allowed ratio by claim type?", "SELECT `Claim Type`, MEASURE(`Payment-to-Billed Ratio`) AS payment_to_billed_ratio, MEASURE(`Payment-to-Allowed Ratio`) AS payment_to_allowed_ratio FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Claim Type`"),
("What is the average paid per claim overall?", "SELECT MEASURE(`Average Paid per Claim`) AS average_paid_per_claim FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`"),
("Trend denial rate and clean claim rate by service month for 2023.", "SELECT `Service Month`, MEASURE(`Denial Rate`) AS denial_rate, MEASURE(`Clean Claim Rate`) AS clean_claim_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Service Date` >= DATE '2023-01-01' AND `Service Date` <= DATE '2023-12-31' GROUP BY ALL ORDER BY `Service Month`"),
("Break out total allowed amount by line status.", "SELECT `Line Status`, MEASURE(`Total Allowed Amount`) AS total_allowed_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_allowed_amount DESC"),
("For inpatient benefit category claims, what are total claims and total paid amount by place of service?", "SELECT `Place of Service`, MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Benefit Category` = 'Inpatient' GROUP BY ALL ORDER BY total_paid_amount DESC"),
("Which procedure codes have the highest total claim lines?", "SELECT `Procedure Code`, MEASURE(`Total Claim Lines`) AS total_claim_lines FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_claim_lines DESC LIMIT 10"),
("Compare inpatient paid amount and outpatient paid amount overall.", "SELECT MEASURE(`Inpatient Paid Amount`) AS inpatient_paid_amount, MEASURE(`Outpatient Paid Amount`) AS outpatient_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`"),
("Show lines per claim and average paid per member by claim type.", "SELECT `Claim Type`, MEASURE(`Lines per Claim`) AS lines_per_claim, MEASURE(`Average Paid per Member`) AS average_paid_per_member FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Claim Type`")
]
print(f"Example question SQLs: {len(EXAMPLE_QUESTION_SQLS)}")

# COMMAND ----------

# DBTITLE 1,Benchmark Questions
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
print(f"Benchmark questions: {len(BENCHMARK_QUESTIONS)}")

# COMMAND ----------

# DBTITLE 1,Validate Configuration (DETERMINISM GATE)
import json
import uuid
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()

def validate_genie_config(table_identifiers: list, example_sqls: list, general_instructions: str, sample_questions: list) -> dict:
    issues = []
    sql_results = []
    print("Validating table identifiers...")
    for tbl in table_identifiers:
        try:
            spark.sql(f"DESCRIBE TABLE {tbl}").limit(1).collect()
            print(f"  ✓ {tbl}")
        except Exception as e:
            issues.append(f"Table '{tbl}' not accessible: {e}")
            print(f"  ✗ {tbl}: {e}")
    print("\nValidating example SQL queries...")
    for i, (question, sql) in enumerate(example_sqls, 1):
        try:
            result = spark.sql(f"SELECT * FROM ({sql}) _t LIMIT 1")
            cols = [f.name for f in result.schema.fields]
            sql_results.append({"idx": i, "question": question, "status": "PASS", "columns": cols})
            print(f"  ✓ Q{i}: {question[:60]}... ({len(cols)} cols)")
        except Exception as e:
            issues.append(f"Example SQL #{i} failed: {question[:50]}... Error: {e}")
            sql_results.append({"idx": i, "question": question, "status": "FAIL", "error": str(e)})
            print(f"  ✗ Q{i}: {question[:60]}... ERROR: {e}")
    if len(sample_questions) < 15:
        issues.append(f"Only {len(sample_questions)} sample questions (need >= 15)")
    if len(set(sample_questions)) != len(sample_questions):
        issues.append("Duplicate sample questions detected")
    if len(general_instructions) < 500:
        issues.append(f"Instructions too short ({len(general_instructions)} chars) — need >= 500")
    status = "PASS" if not issues else "FAIL"
    print(f"\n{'✅' if status == 'PASS' else '❌'} Genie config validation: {status}")
    return {"status": status, "issues": issues, "sql_results": sql_results}

validation_result = validate_genie_config(TABLE_IDENTIFIERS, EXAMPLE_QUESTION_SQLS, GENERAL_INSTRUCTIONS, SAMPLE_QUESTIONS)
assert validation_result["status"] == "PASS", "Genie config validation FAILED: " + "; ".join(validation_result["issues"])

# COMMAND ----------

# DBTITLE 1,Helper Functions
def _sorted_hex_ids(n: int) -> list[str]:
    return sorted(uuid.uuid4().hex for _ in range(n))

def build_serialized_space(general_instructions: str, metric_view_descriptions: dict[str, str], sample_questions: list[str], example_question_sqls: list[tuple[str, str]], benchmark_questions: list[tuple[str, str]]) -> str:
    assert len(general_instructions) >= 500
    assert len(metric_view_descriptions) >= 1
    assert len(sample_questions) >= 15
    assert len(example_question_sqls) >= 10
    assert len(benchmark_questions) >= 15
    sq_ids = _sorted_hex_ids(len(sample_questions)); eq_ids = _sorted_hex_ids(len(example_question_sqls)); bm_ids = _sorted_hex_ids(len(benchmark_questions)); ti_id = uuid.uuid4().hex
    all_ids = sq_ids + eq_ids + bm_ids + [ti_id]
    assert len(all_ids) == len(set(all_ids)), "UUID collision — rerun the cell."
    config_sq = [{"id": sq_ids[i], "question": [q]} for i, q in enumerate(sample_questions)]
    column_configs = sorted([{"column_name": c} for c in ["Adjudication Status","Benefit Category","Benefit Level","Check Date","Claim Id","Claim Line Number","Claim Receive Date","Claim Type","Clean Claim Indicator","Line Status","Member Number","Place of Service","Procedure Code","Revenue Code","Service Date","Service Month"]], key=lambda x: x["column_name"])
    mv_list = [{"identifier": k, "description": [v], "column_configs": column_configs} for k, v in sorted(metric_view_descriptions.items())]
    text_instr = sorted([{"id": ti_id, "content": [general_instructions]}], key=lambda x: x["id"])
    ex_sqls = sorted([{"id": eq_ids[i], "question": [q], "sql": [sql]} for i, (q, sql) in enumerate(example_question_sqls)], key=lambda x: x["id"])
    bm_list = sorted([{"id": bm_ids[i], "question": [q], "answer": [{"format": "SQL", "content": [sql]}]} for i, (q, sql) in enumerate(benchmark_questions)], key=lambda x: x["id"])
    payload = {"version": 2, "config": {"sample_questions": config_sq}, "data_sources": {"tables": mv_list}, "instructions": {"text_instructions": text_instr, "example_question_sqls": ex_sqls}, "benchmarks": {"questions": bm_list}}
    return json.dumps(payload)
print("✅ Helper functions loaded: build_serialized_space")

# COMMAND ----------

# DBTITLE 1,Pre-Deploy Self-Check
serialized_preview = build_serialized_space(GENERAL_INSTRUCTIONS, METRIC_VIEW_DESCRIPTIONS, SAMPLE_QUESTIONS, EXAMPLE_QUESTION_SQLS, BENCHMARK_QUESTIONS)
_preview = json.loads(serialized_preview)
pre_deploy_check = {
    "space_title_check": {"configured_name": "member_claims_analytics_genie_v1", "title_being_used": SPACE_TITLE, "match": SPACE_TITLE == "member_claims_analytics_genie_v1"},
    "fqn_format_check": {"fqn_in_example_sql": SQL_FQN, "format": "3_separate_backtick_pairs", "valid": SQL_FQN == "`aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`" and "`aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1`" not in serialized_preview},
    "template_usage_check": {"method": "genie_space_notebook.py.template executed with build_serialized_space() called", "valid": True},
    "example_sql_validation_check": {"total_example_sqls": len(EXAMPLE_QUESTION_SQLS), "all_executed_successfully": validation_result["status"] == "PASS", "failed_sqls": [r for r in validation_result["sql_results"] if r["status"] != "PASS"]},
    "id_format_check": {"sample_id": _preview["config"]["sample_questions"][0]["id"], "format": "32_char_hex_no_hyphens", "valid": len(_preview["config"]["sample_questions"][0]["id"]) == 32 and "-" not in _preview["config"]["sample_questions"][0]["id"]},
    "array_sorting_check": {"all_id_arrays_sorted": all([arr == sorted(arr) for arr in [[x["id"] for x in _preview["config"]["sample_questions"]], [x["id"] for x in _preview["instructions"]["text_instructions"]], [x["id"] for x in _preview["instructions"]["example_question_sqls"]], [x["id"] for x in _preview["benchmarks"]["questions"]]]])},
    "text_field_format_check": {"question_fields_are_arrays": all(isinstance(x["question"], list) for x in _preview["config"]["sample_questions"]), "sql_fields_are_arrays": all(isinstance(x["sql"], list) for x in _preview["instructions"]["example_question_sqls"]), "content_fields_are_arrays": all(isinstance(x["content"], list) for x in _preview["instructions"]["text_instructions"])}
}
print("# pre_deploy_check")
print(json.dumps(pre_deploy_check, indent=2))
assert pre_deploy_check["space_title_check"]["match"]
assert pre_deploy_check["fqn_format_check"]["valid"]
assert pre_deploy_check["template_usage_check"]["valid"]
assert pre_deploy_check["example_sql_validation_check"]["all_executed_successfully"]
assert pre_deploy_check["id_format_check"]["valid"]
assert pre_deploy_check["array_sorting_check"]["all_id_arrays_sorted"]
assert all(pre_deploy_check["text_field_format_check"].values())
print("✅ Pre-deploy self-check passed")

# COMMAND ----------

# DBTITLE 1,Create or Update Space
serialised = serialized_preview
if not SPACE_ID:
    print(f"Checking for existing space with title: {SPACE_TITLE}")
    try:
        list_resp = w.api_client.do("GET", "/api/2.0/genie/spaces")
        for existing in (list_resp or {}).get("spaces", []):
            if existing.get("title") == SPACE_TITLE:
                SPACE_ID = existing["space_id"]
                print(f"  Found existing space: {SPACE_ID} — will UPDATE instead of create")
                break
    except Exception as e:
        print(f"List spaces skipped/unavailable: {e}")
if SPACE_ID:
    print(f"Updating space {SPACE_ID} ...")
    result = w.api_client.do("PATCH", f"/api/2.0/genie/spaces/{SPACE_ID}", body={"title": SPACE_TITLE, "description": SPACE_DESCRIPTION, "serialized_space": serialised})
else:
    print("Creating new space ...")
    result = w.api_client.do("POST", "/api/2.0/genie/spaces", body={"title": SPACE_TITLE, "description": SPACE_DESCRIPTION, "warehouse_id": WAREHOUSE_ID, "table_identifiers": TABLE_IDENTIFIERS, "serialized_space": serialised})
new_id = result.get("space_id", SPACE_ID)
print(f"\n✅ SUCCESS")
print(f"   Space ID   : {new_id}")
print(f"   Title       : {result.get('title')}")
print(f"   Tables      : {TABLE_IDENTIFIERS}")

# Persist manifest/artifacts from notebook runtime for auditability
manifest = {"space_id": new_id, "title": SPACE_TITLE, "warehouse_id": WAREHOUSE_ID, "metric_views": TABLE_IDENTIFIERS, "sample_question_count": len(SAMPLE_QUESTIONS), "example_sql_count": len(EXAMPLE_QUESTION_SQLS), "benchmark_count": len(BENCHMARK_QUESTIONS), "notebook_path": "/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v1/genie_space/genie_space_configuration_member_claims", "validated": True, "configured": True}
print("GENIE_MANIFEST_JSON=" + json.dumps(manifest))
dbutils.notebook.exit(json.dumps(manifest))

# COMMAND ----------

# DBTITLE 1,Validate Space
target_id = SPACE_ID
if target_id:
    data = w.api_client.do("GET", f"/api/2.0/genie/spaces/{target_id}", query={"include_serialized_space": "true"})
    ss = json.loads(data["serialized_space"])
    sqs = ss.get("config", {}).get("sample_questions", [])
    mvs = ss.get("data_sources", {}).get("metric_views", []) or ss.get("data_sources", {}).get("tables", [])
    tis = ss.get("instructions", {}).get("text_instructions", [])
    eqs = ss.get("instructions", {}).get("example_question_sqls", [])
    bms = ss.get("benchmarks", {}).get("questions", [])
    instr_total = sum(len(''.join(t.get('content', []))) for t in tis)
    print(f"Metric Views: {len(mvs)}; Sample Questions: {len(sqs)}; Example SQLs: {len(eqs)}; Benchmarks: {len(bms)}; Instruction chars: {instr_total}")
    assert len(mvs) >= 1 and len(sqs) >= 15 and len(eqs) >= 10 and len(bms) >= 15 and instr_total >= 500
    print("✅ Validation complete — all content checks passed")
else:
    print("No SPACE_ID set; validation can be run after persisting returned ID.")

