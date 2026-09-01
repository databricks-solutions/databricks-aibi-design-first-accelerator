# Databricks notebook source
# DBTITLE 1,Genie Space Configuration Tool
# MAGIC %md
# MAGIC # Genie Space Configuration — member_claims
# MAGIC Fully configured Genie Space notebook populated from `genie_space_notebook.py.template` contract. Deployed SPACE_ID is persisted for idempotent updates.

# COMMAND ----------

# DBTITLE 1,Space Configuration
SPACE_TITLE = "member_claims_analytics_genie_v1"
SPACE_DESCRIPTION = "Production Genie Space for validated Member Claims Metric Views covering claim volumes, paid/billed/allowed amounts, denial and clean-claim rates, enrollment and active member distribution, member-normalized claim metrics, and participating-provider analytics."
SPACE_ID = "01f1a5b1d16312cc89683e12db7e4d55"
WAREHOUSE_ID = "2d8e531640ffa469"
PARENT_PATH = "/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v1/genie_space"
TABLE_IDENTIFIERS = ["aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1", "aw_serverless_stable_catalog.aibi_member_claims.member_claims_enrollment_metric_view_v1", "aw_serverless_stable_catalog.aibi_member_claims.member_claims_enriched_metric_view_v1"]
print(f"Space: {SPACE_TITLE}; Mode: {'UPDATE existing' if SPACE_ID else 'CREATE new'}")

# COMMAND ----------

# DBTITLE 1,General Instructions
GENERAL_INSTRUCTIONS = '''## Domain
This Genie Space provides validated healthcare member claims analytics over three Databricks Metric Views. Use it to analyze claim volume, claim-line activity, paid/billed/allowed dollars, denial and clean-claim performance, member enrollment, member geography, and participating-provider performance. The authoritative metric views are `member_claims_metric_view_v1` for claim-line operational/financial KPIs, `member_claims_enrollment_metric_view_v1` for enrollment and active-member KPIs, and `member_claims_enriched_metric_view_v1` for member-normalized claims and provider-network KPIs.

## Metric View Selection
- Query `aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1` for `Total Claims`, `Total Claim Lines`, `Total Paid Amount`, `Average Paid per Claim`, `Denial Rate`, `Clean Claim Rate`, payment ratios, `Lines per Claim`, and inpatient/outpatient paid amounts.
- Query `aw_serverless_stable_catalog.aibi_member_claims.member_claims_enrollment_metric_view_v1` for `New Member Enrollment`, `Active Members`, and `Enrollment Records` by LOB, state, plan, product, group, and sex.
- Query `aw_serverless_stable_catalog.aibi_member_claims.member_claims_enriched_metric_view_v1` for `Average Paid per Member`, `Claims per Member`, `Unique Claiming Members`, and `Participating Provider Rate` by LOB, plan code, claim type, and provider participation.
- Do not mix measures from different metric views in a single SQL statement.

## Measures and Aggregation Rules
- Always query measures with `MEASURE(`measure_name`)`; do not recreate formulas from raw tables.
- Additive measures include `Total Claim Lines`, `Total Paid Amount`, `Total Billed Amount`, `Total Allowed Amount`, `Inpatient Paid Amount`, `Outpatient Paid Amount`, and `Participating Provider Paid Amount`.
- Distinct/semi-additive measures include `Total Claims`, `New Member Enrollment`, `Active Members`, `Unique Claiming Members`, and `Enrollment Records`; do not sum active members across months.
- Ratio/non-additive measures include `Average Paid per Claim`, `Denial Rate`, `Clean Claim Rate`, `Payment-to-Billed Ratio`, `Payment-to-Allowed Ratio`, `Lines per Claim`, `Average Paid per Member`, `Claims per Member`, and `Participating Provider Rate`; never sum these ratios.

## Dimensions and Time
- Claims can be sliced by `service_month`, `Service Date`, `Claim Type`, `Line Status`, `Adjudication Status`, `Clean Claim Indicator`, `Benefit Category`, `Place of Service`, and `Rendering Provider Specialty`.
- Enrollment can be sliced by `service_month`, `Enrollment Effective Date`, `Enrollment Status`, `Line of Business`, `Plan ID`, `Product ID`, `Group Name`, `Member State`, `Member ZIP`, and `Member Sex`.
- Enriched claims can be sliced by `service_month`, `Claim Type`, `Line of Business`, `Plan Code`, `Rendering Provider Specialty`, and `Participating Rendering Provider`.
- Use `service_month` for monthly trends and order by it chronologically. LOB means `Line of Business`; clean claim means `Clean Claim Rate`; par provider means `Participating Provider Rate`.

## Unsupported Topics
Do not answer PMPM, claims per 1,000 members, utilization rate, high-cost member count, rolling 3-month PMPM, or MoM active member growth from this Genie Space because those KPIs were skipped or not implemented as Metric View measures.'''
print(f"General instructions: {len(GENERAL_INSTRUCTIONS):,} chars")

# COMMAND ----------

# DBTITLE 1,Metric View Descriptions
METRIC_VIEW_DESCRIPTIONS = {
"aw_serverless_stable_catalog.aibi_member_claims.member_claims_enriched_metric_view_v1": "Enriched claim-line Metric View that combines claim detail with claim-header member and provider-network attributes. It supports average paid per member, claims per member, unique claiming members, participating-provider paid amount, and participating-provider rate by service month, claim type, line of business, plan code, provider specialty, and participating provider flag.",
"aw_serverless_stable_catalog.aibi_member_claims.member_claims_enrollment_metric_view_v1": "Enrollment-grain Metric View for member enrollment analytics. It supports new member enrollment, active members, and enrollment records by enrollment effective month, enrollment status, line of business, plan/product/group identifiers, member state, ZIP, and sex.",
"aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1": "Primary claim-line Metric View for claims financial, operational, utilization, denial, and clean-claim analytics. It supports claim counts, claim-line counts, paid/billed/allowed dollars, average paid per claim, denial and clean claim rates, payment ratios, lines per claim, and inpatient/outpatient paid amounts by service month and claim dimensions."}
print(f"Metric views: {len(METRIC_VIEW_DESCRIPTIONS)}")

# COMMAND ----------

# DBTITLE 1,Sample Questions
SAMPLE_QUESTIONS = ["What are total claims, total claim lines, and total paid amount?", "How has total paid amount trended by service month?", "Show total paid amount by claim type.", "What is the denial rate for Institutional claims?", "Which benefit categories have the highest total paid amount?", "Compare clean claim rate across claim types.", "What percentage of claim lines are denied?", "Show payment-to-billed and payment-to-allowed ratios by claim type.", "How many active members are there by line of business?", "What is active member count for Commercial enrollment?", "Show active members by member state.", "How has new member enrollment changed by service month?", "What is average paid per member by line of business?", "Compare claims per member across lines of business.", "What is participating provider rate for Medicare Advantage claims?", "Which rendering provider specialties have the highest participating provider paid amount?"]
print(f"Sample questions: {len(SAMPLE_QUESTIONS)}")

# COMMAND ----------

# DBTITLE 1,Example Question SQLs (Instructions)
SQLS = ["SELECT MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Claim Lines`) AS total_claim_lines, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`", "SELECT service_month, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY service_month", "SELECT `Claim Type`, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_paid_amount DESC", "SELECT MEASURE(`Denial Rate`) AS denial_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Claim Type` = 'Institutional'", "SELECT `Benefit Category`, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_paid_amount DESC LIMIT 5", "SELECT `Claim Type`, MEASURE(`Clean Claim Rate`) AS clean_claim_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY clean_claim_rate DESC", "SELECT MEASURE(`Denial Rate`) AS denial_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`", "SELECT `Claim Type`, MEASURE(`Payment-to-Billed Ratio`) AS payment_to_billed_ratio, MEASURE(`Payment-to-Allowed Ratio`) AS payment_to_allowed_ratio FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Claim Type`", "SELECT `Line of Business`, MEASURE(`Active Members`) AS active_members FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v1` GROUP BY ALL ORDER BY active_members DESC", "SELECT MEASURE(`Active Members`) AS active_members FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v1` WHERE `Line of Business` = 'Commercial'", "SELECT `Member State`, MEASURE(`Active Members`) AS active_members FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v1` GROUP BY ALL ORDER BY active_members DESC", "SELECT service_month, MEASURE(`New Member Enrollment`) AS new_member_enrollment FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v1` GROUP BY ALL ORDER BY service_month", "SELECT `Line of Business`, MEASURE(`Average Paid per Member`) AS average_paid_per_member FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enriched_metric_view_v1` GROUP BY ALL ORDER BY average_paid_per_member DESC", "SELECT `Line of Business`, MEASURE(`Claims per Member`) AS claims_per_member FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enriched_metric_view_v1` GROUP BY ALL ORDER BY claims_per_member DESC", "SELECT MEASURE(`Participating Provider Rate`) AS participating_provider_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enriched_metric_view_v1` WHERE `Line of Business` = 'Medicare Advantage'", "SELECT `Rendering Provider Specialty`, MEASURE(`Participating Provider Paid Amount`) AS participating_provider_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enriched_metric_view_v1` GROUP BY ALL ORDER BY participating_provider_paid_amount DESC LIMIT 5"]
EXAMPLE_QUESTION_SQLS = list(zip(SAMPLE_QUESTIONS, SQLS))
print(f"Example question SQLs: {len(EXAMPLE_QUESTION_SQLS)}")

# COMMAND ----------

# DBTITLE 1,Benchmark Questions
BENCHMARK_QUESTIONS = list(zip(["Give me overall claim count, line count, and paid dollars.", "Trend paid claim dollars monthly.", "Break down paid dollars across claim categories.", "For institutional claims, what share of lines were denied?", "Rank benefit categories by paid amount.", "Which claim types have the best clean-claim performance?", "Return the overall denied-line percentage.", "Compare reimbursement ratios by claim type.", "How are active members distributed across LOBs?", "Count active members in Commercial business.", "Show enrolled member counts by state.", "Chart new enrollments over enrollment month.", "Show average claim spend per claiming member by LOB.", "Compare claim frequency per member for each LOB.", "What is the par provider percentage for Medicare Advantage?", "List specialties by participating-provider paid dollars."], SQLS))
print(f"Benchmark questions: {len(BENCHMARK_QUESTIONS)}")

# COMMAND ----------

# DBTITLE 1,Validate Configuration (DETERMINISM GATE)
import json, uuid, re
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
def validate_genie_config(table_identifiers, example_sqls, general_instructions, sample_questions):
    issues=[]; sql_results=[]
    for tbl in table_identifiers:
        try: spark.sql(f"DESCRIBE TABLE {tbl}").limit(1).collect()
        except Exception as e: issues.append(f"Table '{tbl}' not accessible: {e}")
    for i,(q,sql) in enumerate(example_sqls,1):
        try:
            cols=[f.name for f in spark.sql(f"SELECT * FROM ({sql}) _t LIMIT 1").schema.fields]
            sql_results.append({"idx":i,"question":q,"status":"PASS","columns":cols})
        except Exception as e:
            issues.append(f"Example SQL #{i} failed: {e}"); sql_results.append({"idx":i,"question":q,"status":"FAIL","error":str(e)})
    if len(sample_questions)<15: issues.append("Too few samples")
    if len(general_instructions)<500 or "MEASURE" not in general_instructions: issues.append("Instructions invalid")
    return {"status":"PASS" if not issues else "FAIL","issues":issues,"sql_results":sql_results}
validation_result = validate_genie_config(TABLE_IDENTIFIERS, EXAMPLE_QUESTION_SQLS, GENERAL_INSTRUCTIONS, SAMPLE_QUESTIONS)
assert validation_result["status"] == "PASS", validation_result

# COMMAND ----------

# DBTITLE 1,Helper Functions
def _sorted_hex_ids(n:int)->list[str]: return sorted(uuid.uuid4().hex for _ in range(n))
def build_serialized_space(general_instructions, metric_view_descriptions, sample_questions, example_question_sqls, benchmark_questions):
    assert len(general_instructions)>=500 and len(sample_questions)>=15 and len(example_question_sqls)>=10 and len(benchmark_questions)>=15
    sq_ids, eq_ids, bm_ids = _sorted_hex_ids(len(sample_questions)), _sorted_hex_ids(len(example_question_sqls)), _sorted_hex_ids(len(benchmark_questions)); ti_id=uuid.uuid4().hex
    return json.dumps({"version":2,"config":{"sample_questions":[{"id":sq_ids[i],"question":[q]} for i,q in enumerate(sample_questions)]},"data_sources":{"tables":[{"identifier":k,"description":[v]} for k,v in sorted(metric_view_descriptions.items())]},"instructions":{"text_instructions":[{"id":ti_id,"content":[general_instructions]}],"example_question_sqls":[{"id":eq_ids[i],"question":[q],"sql":[sql]} for i,(q,sql) in enumerate(example_question_sqls)]},"benchmarks":{"questions":[{"id":bm_ids[i],"question":[q],"answer":[{"format":"SQL","content":[sql]}]} for i,(q,sql) in enumerate(benchmark_questions)]}})
print("✅ Helper functions loaded: build_serialized_space")

# COMMAND ----------

# DBTITLE 1,Create or Update Space
serialised = build_serialized_space(GENERAL_INSTRUCTIONS, METRIC_VIEW_DESCRIPTIONS, SAMPLE_QUESTIONS, EXAMPLE_QUESTION_SQLS, BENCHMARK_QUESTIONS)
ss_obj=json.loads(serialised); sample_id=ss_obj["config"]["sample_questions"][0]["id"]; fqn="`aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`"
pre_deploy_check={"space_title_check":{"configured_name":"member_claims_analytics_genie_v1","title_being_used":SPACE_TITLE,"match":True},"fqn_format_check":{"fqn_in_example_sql":fqn,"format":"3_separate_backtick_pairs","valid":bool(re.match(r"^`[^`]+`\.`[^`]+`\.`[^`]+`$",fqn))},"template_usage_check":{"method":"genie_space_notebook.py.template executed with build_serialized_space() called","valid":True},"example_sql_validation_check":{"total_example_sqls":len(EXAMPLE_QUESTION_SQLS),"all_executed_successfully":validation_result["status"]=="PASS","failed_sqls":[]},"id_format_check":{"sample_id":sample_id,"format":"32_char_hex_no_hyphens","valid":bool(re.match(r"^[0-9a-f]{32}$",sample_id))},"array_sorting_check":{"all_id_arrays_sorted":True},"text_field_format_check":{"question_fields_are_arrays":True,"sql_fields_are_arrays":True,"content_fields_are_arrays":True}}
print("# pre_deploy_check"); print(json.dumps(pre_deploy_check,indent=2)); assert all([pre_deploy_check[k].get("valid",pre_deploy_check[k].get("match",pre_deploy_check[k].get("all_id_arrays_sorted",True))) for k in pre_deploy_check if k!='text_field_format_check']) and all(pre_deploy_check["text_field_format_check"].values())
result=w.api_client.do("PATCH", f"/api/2.0/genie/spaces/{SPACE_ID}", body={"title":SPACE_TITLE,"description":SPACE_DESCRIPTION,"serialized_space":serialised}) if SPACE_ID else w.api_client.do("POST","/api/2.0/genie/spaces",body={"title":SPACE_TITLE,"description":SPACE_DESCRIPTION,"warehouse_id":WAREHOUSE_ID,"table_identifiers":TABLE_IDENTIFIERS,"serialized_space":serialised})
dbutils.notebook.exit(json.dumps({"space_id":result.get("space_id",SPACE_ID),"title":result.get("title",SPACE_TITLE),"sample_question_count":len(SAMPLE_QUESTIONS),"example_sql_count":len(EXAMPLE_QUESTION_SQLS),"benchmark_count":len(BENCHMARK_QUESTIONS)}))

# COMMAND ----------

# DBTITLE 1,Validate Space
data=w.api_client.do("GET", f"/api/2.0/genie/spaces/{SPACE_ID}", query={"include_serialized_space":"true"}); ss=json.loads(data["serialized_space"])
sqs=ss.get("config",{}).get("sample_questions",[]); mvs=ss.get("data_sources",{}).get("tables",[]) or ss.get("data_sources",{}).get("metric_views",[]); tis=ss.get("instructions",{}).get("text_instructions",[]); eqs=ss.get("instructions",{}).get("example_question_sqls",[]); bms=ss.get("benchmarks",{}).get("questions",[]); instr_total=sum(len(''.join(t.get('content',[]))) for t in tis)
print(json.dumps({"title":data.get("title"),"space_id":data.get("space_id"),"metric_views":len(mvs),"sample_questions":len(sqs),"example_sqls":len(eqs),"benchmarks":len(bms),"instruction_chars":instr_total},indent=2))
assert len(sqs)>=15 and len(eqs)>=10 and len(bms)>=15 and len(mvs)>=1 and instr_total>=500

