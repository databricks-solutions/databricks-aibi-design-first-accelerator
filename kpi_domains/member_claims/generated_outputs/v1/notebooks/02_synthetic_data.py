# Databricks notebook source
# DBTITLE 1,Synthetic Data — Member Claims
# Uses dbldatagen to generate realistic sample data for all requested tables.
# CRITICAL: All generated columns match the ERD column names and Spark-compatible data types.
# Target schema: aw_serverless_stable_catalog.aibi_member_claims

# COMMAND ----------

# DBTITLE 1,Install dependencies
%pip install dbldatagen --quiet
dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Setup and Type Helpers
import dbldatagen as dg
from pyspark.sql.types import *

spark.conf.set("spark.sql.ansi.enabled", "false")

_orig_withColumn = dg.DataGenerator.withColumn
def _safe_withColumn(self, colName, colType, *args, **kwargs):
    if colType == BooleanType() or colType is BooleanType:
        kwargs.pop("values", None)
        kwargs.pop("weights", None)
    if colType == TimestampType() or colType is TimestampType or str(colType).lower() in ("timestamp", "timestamp_ntz"):
        for key in ("begin", "end"):
            if key in kwargs and isinstance(kwargs[key], str) and len(kwargs[key]) == 10:
                kwargs[key] = f"{kwargs[key]} 00:00:00" if key == "begin" else f"{kwargs[key]} 23:59:59"
    return _orig_withColumn(self, colName, colType, *args, **kwargs)
dg.DataGenerator.withColumn = _safe_withColumn

schema_name = "aw_serverless_stable_catalog.aibi_member_claims"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")

member_sks = list(range(1, 501))
address_keys = list(range(1, 501))
provider_sks = list(range(1, 501))
claim_header_sks = list(range(1, 501))
claim_ids = [f"CLM-{i:07d}" for i in range(1, 501)]
detail_claim_ids = [f"CLM-{i:07d}" for i in range(1, 501) for j in range(1, 11)]
detail_line_nbrs = [str(j) for i in range(1, 501) for j in range(1, 11)]

source_system_values = ["FACETS", "QNXT", "EPIC", "EDI", "PORTAL"]
state_values = ["CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI"]
city_values = ["Los Angeles", "Houston", "New York", "Miami", "Chicago", "Philadelphia", "Columbus", "Atlanta", "Charlotte", "Detroit"]
county_values = ["Orange", "Harris", "Kings", "Dade", "Cook", "Franklin", "Fulton", "Wayne"]
first_name_values = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "William", "Elizabeth"]
middle_name_values = ["A", "B", "C", "D", "E", "F", "G", "H"]
last_name_values = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Wilson", "Anderson"]
full_name_values = ["James Smith", "Mary Johnson", "Robert Williams", "Patricia Brown", "John Jones", "Jennifer Garcia", "Michael Miller", "Linda Davis"]
provider_name_values = ["Northside Medical Group", "Valley Health Clinic", "Summit Family Practice", "Lakeside Hospital", "Metro Specialty Care", "Community Health Partners"]
lob_values = ["COMMERCIAL", "MEDICAID", "MEDICARE", "EXCHANGE", "TRICARE"]
claim_type_values = ["PROFESSIONAL", "INSTITUTIONAL", "PHARMACY", "DENTAL", "VISION"]
status_values = ["ACTIVE", "TERMINATED", "PENDING", "SUSPENDED"]
yn_values = ["Y", "N"]
sex_values = ["M", "F", "U"]
race_values = ["WHITE", "BLACK", "ASIAN", "NATIVE", "PACIFIC", "OTHER", "UNKNOWN"]
ethnicity_values = ["HISPANIC", "NON-HISPANIC", "UNKNOWN"]
marital_values = ["S", "M", "D", "W", "U"]
relationship_values = ["SELF", "SPOUSE", "CHILD", "DEPENDENT", "OTHER"]
id_type_values = ["MEMBER_ID", "SUBSCRIBER_ID", "MEDICAID_ID", "MEDICARE_ID", "EMPLOYEE_ID"]
benefit_values = ["MEDICAL", "SURGICAL", "EMERGENCY", "LAB", "RADIOLOGY", "PHARMACY", "BEHAVIORAL"]
place_values = ["11", "12", "21", "22", "23", "31", "32", "81"]
icd_method_values = ["ICD9", "ICD10"]
poa_values = ["Y", "N", "U", "W"]
source_name_values = ["Core Administration", "Clinical System", "Claims Gateway", "Member Portal", "Enrollment Hub"]

def target_table(table_name):
    return f"{schema_name}.{table_name}_v1"

def save_table(df, table_name):
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(target_table(table_name))
    print(f"Wrote {table_name}_v1")

def spark_type(dtype):
    if dtype == "bigint":
        return LongType()
    if dtype == "int":
        return IntegerType()
    if dtype == "string":
        return StringType()
    if dtype == "date":
        return DateType()
    if dtype == "timestamp":
        return TimestampType()
    if dtype == "boolean":
        return BooleanType()
    if dtype == "decimal":
        return DecimalType(18, 2)
    return StringType()

def values_for_string(name):
    n = name.lower()
    if "source_system_name" in n:
        return source_name_values
    if "source_system" in n or "orig_source" in n or "source_system_code" in n:
        return source_system_values
    if n.endswith("state") or n.endswith("_st") or "accident_st" in n:
        return state_values
    if "city" in n:
        return city_values
    if "county" in n:
        return county_values
    if "country" in n:
        return ["US"]
    if "first_name" in n:
        return first_name_values
    if "middle_name" in n:
        return middle_name_values
    if "last_name" in n:
        return last_name_values
    if "full_name" in n or "member_name" in n or "responsible_party_name" in n:
        return full_name_values
    if "provider_name" in n or "provider_group_name" in n or "fac_loc_name" in n:
        return provider_name_values
    if "line_of_business" in n or "lob" in n:
        return lob_values
    if "claim_type" in n:
        return claim_type_values
    if "status" in n:
        return status_values
    if "sex" in n:
        return sex_values
    if "race" in n:
        return race_values
    if "ethnicity" in n:
        return ethnicity_values
    if "marital" in n:
        return marital_values
    if "relationship" in n:
        return relationship_values
    if "id_type" in n:
        return id_type_values
    if "benefit" in n:
        return benefit_values
    if "place_of_service" in n:
        return place_values
    if "icd_method" in n or "diagnosis_method" in n:
        return icd_method_values
    if n.endswith("_poa"):
        return poa_values
    if "flag" in n or "indicator" in n or "ind" in n or "clean_claim" in n or "text_opt_in" in n or "secured" in n:
        return yn_values
    if "type_code" in n or "address_type" in n:
        return ["HOME", "MAILING", "SERVICE", "BILLING", "PRACTICE"]
    if "entity_type_key" in n:
        return ["MEMBER", "PROVIDER", "FACILITY"]
    if "level" in n:
        return ["IN", "OUT", "TIER1", "TIER2"]
    if "reason" in n:
        return ["COB", "DEDUCTIBLE", "COPAY", "EXCLUSION", "TIMELY", "AUTH"]
    if "code" in n or "modifier" in n or "drg" in n or "diagnosis" in n or "procedure" in n or "surgical" in n or "revenue" in n:
        return ["A001", "B203", "C349", "D456", "E789", "F012"]
    return None

def add_synthetic_column(gen, name, dtype, nullable=True, values=None, random_values=True, minValue=None, maxValue=None, step=None):
    col_type = spark_type(dtype)
    kwargs = {}
    if values is not None:
        kwargs["values"] = values
        kwargs["random"] = random_values
    elif dtype == "bigint":
        kwargs["minValue"] = 1 if minValue is None else minValue
        kwargs["maxValue"] = 100000 if maxValue is None else maxValue
        if step is not None:
            kwargs["step"] = step
        else:
            kwargs["random"] = True
    elif dtype == "int":
        kwargs["minValue"] = 1 if minValue is None else minValue
        kwargs["maxValue"] = 10000 if maxValue is None else maxValue
        if step is not None:
            kwargs["step"] = step
        else:
            kwargs["random"] = True
    elif dtype == "decimal":
        kwargs["minValue"] = 0 if minValue is None else minValue
        kwargs["maxValue"] = 5000 if maxValue is None else maxValue
        kwargs["random"] = True
    elif dtype == "date":
        if "dob" in name.lower():
            kwargs["begin"] = "1940-01-01"
            kwargs["end"] = "2005-12-31"
        else:
            kwargs["begin"] = "2020-01-01"
            kwargs["end"] = "2024-12-31"
        kwargs["interval"] = "1 day"
        kwargs["random"] = True
    elif dtype == "timestamp":
        kwargs["begin"] = "2020-01-01 00:00:00"
        kwargs["end"] = "2024-12-31 23:59:59"
        kwargs["interval"] = "1 day"
        kwargs["random"] = True
    elif dtype == "boolean":
        kwargs["random"] = True
    elif dtype == "string":
        string_values = values_for_string(name)
        if string_values is not None:
            kwargs["values"] = string_values
            kwargs["random"] = True
        elif "zip" in name.lower():
            kwargs["template"] = r"\d\d\d\d\d"
            kwargs["random"] = True
        elif "phone" in name.lower() or "mobile" in name.lower() or "work_nbr" in name.lower():
            kwargs["template"] = r"\d\d\d-\d\d\d-\d\d\d\d"
            kwargs["random"] = True
        elif "email" in name.lower():
            kwargs["template"] = r"\w\w\w\w\w@example.com"
            kwargs["random"] = True
        elif "npi" in name.lower():
            kwargs["template"] = r"\d\d\d\d\d\d\d\d\d\d"
            kwargs["random"] = True
        elif "tax" in name.lower() or "ssn" in name.lower():
            kwargs["template"] = r"\d\d\d-\d\d-\d\d\d\d"
            kwargs["random"] = True
        elif "street_address_1" in name.lower():
            kwargs["values"] = ["100 Main St", "250 Oak Ave", "75 Pine Rd", "430 Cedar Blvd", "980 Maple Dr"]
            kwargs["random"] = True
        elif "street_address_2" in name.lower():
            kwargs["values"] = ["Apt 1", "Suite 200", "Unit B", "Floor 3", "Building C"]
            kwargs["random"] = True
        else:
            kwargs["template"] = r"\w\w\w-\d\d\d\d"
            kwargs["random"] = True
    if nullable:
        kwargs["percentNulls"] = 0.08
    return gen.withColumn(name, col_type, **kwargs)

def add_columns(gen, cols):
    for c in cols:
        gen = add_synthetic_column(gen, c[0], c[1])
    return gen

# COMMAND ----------

# DBTITLE 1,dim_member
dim_member_gen = dg.DataGenerator(spark, rows=500)
dim_member_gen = add_synthetic_column(dim_member_gen, "member_sk", "bigint", nullable=False, minValue=1, maxValue=500, step=1)
dim_member_cols = [("mbr_source_member_id", "string"), ("mbr_member_id", "int"), ("mbr_deers_beneficiary_id", "string"), ("mbr_deers_family_id", "string"), ("mbr_sponsor_ssn", "string"), ("mbr_current_pcp_eff_date", "date"), ("mbr_current_pcp_nbr", "string"), ("mbr_dob", "date"), ("mbr_race", "string"), ("mbr_sex", "string"), ("mbr_ethnicity", "string"), ("mbr_first_name", "string"), ("mbr_middle_name", "string"), ("mbr_last_name", "string"), ("mbr_full_name", "string"), ("mbr_marital_status", "string"), ("mbr_deceased_date", "date"), ("mbr_email", "string"), ("mbr_phone_nbr", "string"), ("mbr_mobile_nbr", "string"), ("mbr_work_nbr", "string"), ("mbr_sub_group_cd", "string"), ("mbr_idcard_issue_date", "date"), ("mbr_line_of_business", "string"), ("mbr_text_opt_in", "string"), ("mbr_current_riders", "string"), ("mbr_authorized_rep", "string"), ("mbr_alt_sub_nbr", "string"), ("mbr_relationship_type", "string"), ("mbr_salary_tier", "string"), ("mbr_pcp_auto_assigned", "string"), ("mbr_secured_flag", "string"), ("mbr_pharmacy_discount_flag", "string"), ("mbr_employee_id", "string"), ("mbr_line_of_business_name", "string"), ("mbr_responsible_party_id", "string"), ("mbr_responsible_party_name", "string"), ("mbr_deceased_flag", "string"), ("mbr_pcp_lock_in_indicator", "string"), ("mbr_alt_person_nbr", "string"), ("mbr_state", "string"), ("mbr_zip_code", "string"), ("mbr_pcp_lock_in_type", "string"), ("mbr_provider_group_name", "string"), ("mbr_name_suffix", "string"), ("mbr_sub_flag", "int"), ("mbr_sub_ssn", "string"), ("mbr_extract_date", "date"), ("mbr_medicaid_case_nbr", "string"), ("mbr_relationship_ind", "string"), ("source_system_code", "string"), ("source_system_name", "string"), ("record_hash", "string"), ("created_at", "timestamp"), ("updated_at", "timestamp"), ("is_active", "boolean"), ("end_date", "timestamp")]
dim_member_gen = add_columns(dim_member_gen, dim_member_cols)
df_dim_member = dim_member_gen.build()
save_table(df_dim_member, "dim_member")

# COMMAND ----------

# DBTITLE 1,dim_address
dim_address_gen = dg.DataGenerator(spark, rows=500)
dim_address_gen = add_synthetic_column(dim_address_gen, "address_key", "bigint", nullable=False, minValue=1, maxValue=500, step=1)
dim_address_gen = add_synthetic_column(dim_address_gen, "entity_type_key", "string")
dim_address_gen = add_synthetic_column(dim_address_gen, "entity_dimension_key", "bigint", nullable=False, values=member_sks, random_values=True)
dim_address_cols = [("address_type_code", "string"), ("street_address_1", "string"), ("street_address_2", "string"), ("city", "string"), ("state", "string"), ("zip_code", "string"), ("country_code", "string"), ("county", "string"), ("is_active", "boolean"), ("valid_from_date", "timestamp"), ("valid_to_date", "timestamp"), ("source_system_code", "string"), ("source_system_name", "string"), ("record_hash", "string"), ("created_at", "timestamp"), ("updated_at", "timestamp")]
dim_address_gen = add_columns(dim_address_gen, dim_address_cols)
df_dim_address = dim_address_gen.build()
save_table(df_dim_address, "dim_address")

# COMMAND ----------

# DBTITLE 1,dim_provider
dim_provider_gen = dg.DataGenerator(spark, rows=500)
dim_provider_gen = add_synthetic_column(dim_provider_gen, "provider_sk", "bigint", nullable=False, minValue=1, maxValue=500, step=1)
dim_provider_gen = add_synthetic_column(dim_provider_gen, "assigned_provider_sk", "bigint", minValue=1, maxValue=500)
dim_provider_gen = add_synthetic_column(dim_provider_gen, "source_provider_id", "string")
dim_provider_gen = add_synthetic_column(dim_provider_gen, "provider_npi", "string")
dim_provider_gen = add_synthetic_column(dim_provider_gen, "provider_tax_id", "string")
dim_provider_gen = add_synthetic_column(dim_provider_gen, "provider_name", "string")
dim_provider_gen = add_synthetic_column(dim_provider_gen, "provider_address_sk", "bigint", nullable=False, values=address_keys, random_values=True)
dim_provider_cols = [("pcp_flag", "boolean"), ("affiliation_id", "string"), ("valid_from_date", "timestamp"), ("valid_to_date", "timestamp"), ("is_active", "boolean"), ("source_system", "string"), ("created_at", "timestamp"), ("updated_at", "timestamp"), ("last_update_dt", "timestamp"), ("record_hash", "string")]
dim_provider_gen = add_columns(dim_provider_gen, dim_provider_cols)
df_dim_provider = dim_provider_gen.build()
save_table(df_dim_provider, "dim_provider")

# COMMAND ----------

# DBTITLE 1,dim_member_identifier
dim_member_identifier_gen = dg.DataGenerator(spark, rows=500)
dim_member_identifier_gen = add_synthetic_column(dim_member_identifier_gen, "mbr_identifier_sk", "bigint", nullable=False, minValue=1, maxValue=500, step=1)
dim_member_identifier_gen = add_synthetic_column(dim_member_identifier_gen, "member_sk", "bigint", nullable=False, values=member_sks, random_values=True)
dim_member_identifier_cols = [("id_type", "string"), ("id_value", "string"), ("source_system_code", "string"), ("source_system_name", "string"), ("valid_to_date", "timestamp"), ("valid_from_date", "timestamp"), ("is_active", "boolean"), ("created_at", "timestamp"), ("updated_at", "timestamp"), ("record_hash", "string")]
dim_member_identifier_gen = add_columns(dim_member_identifier_gen, dim_member_identifier_cols)
df_dim_member_identifier = dim_member_identifier_gen.build()
save_table(df_dim_member_identifier, "dim_member_identifier")

# COMMAND ----------

# DBTITLE 1,dim_member_history
dim_member_history_gen = dg.DataGenerator(spark, rows=500)
dim_member_history_gen = add_synthetic_column(dim_member_history_gen, "mbr_history_sk", "bigint", nullable=False, minValue=1, maxValue=500, step=1)
dim_member_history_gen = add_synthetic_column(dim_member_history_gen, "member_sk", "bigint", nullable=False, values=member_sks, random_values=True)
dim_member_history_cols = [("mbr_source_member_id", "string"), ("mbr_member_id", "int"), ("mbr_deers_beneficiary_id", "string"), ("mbr_deers_family_id", "string"), ("mbr_sponsor_ssn", "string"), ("mbr_current_pcp_eff_date", "date"), ("mbr_current_pcp_nbr", "string"), ("mbr_dob", "date"), ("mbr_race", "string"), ("mbr_sex", "string"), ("mbr_ethnicity", "string"), ("mbr_first_name", "string"), ("mbr_middle_name", "string"), ("mbr_last_name", "string"), ("mbr_full_name", "string"), ("mbr_marital_status", "string"), ("mbr_deceased_date", "date"), ("mbr_email", "string"), ("mbr_phone_nbr", "string"), ("mbr_mobile_nbr", "string"), ("mbr_work_nbr", "string"), ("mbr_sub_group_cd", "string"), ("mbr_idcard_issue_date", "date"), ("mbr_line_of_business", "string"), ("mbr_text_opt_in", "string"), ("mbr_current_riders", "string"), ("mbr_authorized_rep", "string"), ("mbr_alt_sub_nbr", "string"), ("mbr_relationship_type", "string"), ("mbr_salary_tier", "string"), ("mbr_pcp_auto_assigned", "string"), ("mbr_secured_flag", "string"), ("mbr_pharmacy_discount_flag", "string"), ("mbr_employee_id", "string"), ("mbr_line_of_business_name", "string"), ("mbr_responsible_party_id", "string"), ("mbr_responsible_party_name", "string"), ("mbr_deceased_flag", "string"), ("mbr_pcp_lock_in_indicator", "string"), ("mbr_alt_person_nbr", "string"), ("mbr_state", "string"), ("mbr_zip_code", "string"), ("mbr_pcp_lock_in_type", "string"), ("mbr_provider_group_name", "string"), ("mbr_name_suffix", "string"), ("mbr_sub_flag", "int"), ("mbr_sub_ssn", "string"), ("mbr_extract_date", "date"), ("mbr_medicaid_case_nbr", "string"), ("mbr_relationship_ind", "string"), ("source_system_code", "string"), ("source_system_name", "string"), ("record_hash", "string"), ("created_at", "timestamp"), ("updated_at", "timestamp"), ("is_active", "boolean"), ("valid_to_date", "timestamp"), ("valid_from_date", "timestamp")]
dim_member_history_gen = add_columns(dim_member_history_gen, dim_member_history_cols)
df_dim_member_history = dim_member_history_gen.build()
save_table(df_dim_member_history, "dim_member_history")

# COMMAND ----------

# DBTITLE 1,fact_claim_header
fact_claim_header_gen = dg.DataGenerator(spark, rows=500)
fact_claim_header_gen = add_synthetic_column(fact_claim_header_gen, "clm_header_sk", "bigint", nullable=False, minValue=1, maxValue=500, step=1)
fact_claim_header_gen = add_synthetic_column(fact_claim_header_gen, "clm_id", "int", minValue=100000, maxValue=999999)
fact_claim_header_gen = add_synthetic_column(fact_claim_header_gen, "clm_claim_id", "string", nullable=False, values=claim_ids, random_values=False)
fact_claim_header_cols_pre = [("clm_original_source_claim_id", "string"), ("clm_original_batch_nbr", "string"), ("clm_patient_control_nbr", "string"), ("clm_document_adj_control_nbr", "string"), ("clm_claim_type", "string"), ("clm_bill_type", "string"), ("clm_authorization_nbr", "string"), ("clm_ext_authorization_nbr", "string"), ("clm_admit_date", "date"), ("clm_claim_thru_date", "date"), ("clm_discharge_date", "date"), ("clm_admission_hour", "int"), ("clm_discharge_hour", "int"), ("clm_admission_type", "string"), ("clm_admission_source", "string"), ("clm_member_nbr", "string"), ("clm_member_name", "string")]
fact_claim_header_gen = add_columns(fact_claim_header_gen, fact_claim_header_cols_pre)
fact_claim_header_gen = add_synthetic_column(fact_claim_header_gen, "clm_member_sk", "bigint", nullable=False, values=member_sks, random_values=True)
fact_claim_header_cols_mid = [("clm_member_group_nbr", "string"), ("clm_member_subgroup_nbr", "string"), ("clm_plan_code", "string"), ("clm_line_of_business", "string"), ("clm_birth_weight", "decimal"), ("clm_covered_days", "int"), ("clm_accident_st", "string"), ("clm_attending_physician", "string"), ("clm_attending_physician_spec", "string"), ("clm_operating_provider_name", "string"), ("clm_operating_provider_npi", "string"), ("clm_submitting_provider", "string"), ("clm_submitting_provider_spec", "string"), ("clm_submitting_provider_type", "string"), ("clm_billing_provider", "string"), ("clm_referring_provider", "string"), ("clm_referring_provider_spec", "string"), ("clm_referring_provider_type", "string"), ("clm_is_par_submitting_provider", "string"), ("clm_is_par_referring_provider", "boolean"), ("clm_is_par_rendering_provider", "boolean"), ("clm_assigned_pcp", "string"), ("clm_assigned_provider_site", "string"), ("clm_insurance_id", "string"), ("clm_member_contract_id", "string"), ("clm_pcp_visit_flag", "int"), ("clm_pcp_in_type", "string"), ("clm_pcp_wthld_pct", "decimal"), ("clm_service_fac_npi", "string"), ("clm_service_fac_loc_name", "string")]
fact_claim_header_gen = add_columns(fact_claim_header_gen, fact_claim_header_cols_mid)
fact_claim_header_gen = add_synthetic_column(fact_claim_header_gen, "clm_service_facility_address_sk", "bigint", nullable=False, values=address_keys, random_values=True)
fact_claim_header_cols_diag_pre = [("clm_providers_account_no", "string"), ("clm_onset_of_illness_date", "string"), ("clm_admitting_diagnosis_code", "string"), ("clm_admitting_diagnosis_method", "string")]
fact_claim_header_gen = add_columns(fact_claim_header_gen, fact_claim_header_cols_diag_pre)
for i in range(1, 26):
    fact_claim_header_gen = add_synthetic_column(fact_claim_header_gen, f"clm_diagnosis_{i}", "string")
    fact_claim_header_gen = add_synthetic_column(fact_claim_header_gen, f"clm_diagnosis_{i}_icd_method", "string")
for i in range(1, 26):
    fact_claim_header_gen = add_synthetic_column(fact_claim_header_gen, f"clm_diagnosis_{i}_poa", "string")
for i in range(1, 7):
    fact_claim_header_gen = add_synthetic_column(fact_claim_header_gen, f"clm_surgical_{i}", "string")
    fact_claim_header_gen = add_synthetic_column(fact_claim_header_gen, f"clm_surgical_icd_method_{i}", "string")
fact_claim_header_cols_tail = [("clm_drg_code", "string"), ("clm_service_type_code", "string"), ("clm_cob_type", "string"), ("clm_claim_timely_filing", "string"), ("clm_accept_assignment_indicator", "string"), ("clm_add_date", "date"), ("clm_add_user", "string"), ("clm_update_date", "date"), ("clm_update_user", "string"), ("clm_extract_date", "timestamp"), ("clm_last_updated_date", "date"), ("clm_original_insert_date", "date"), ("clm_user_id", "string"), ("clm_orig_source", "string"), ("is_active", "boolean"), ("end_date", "timestamp"), ("record_hash", "string"), ("last_updated_date", "date"), ("created_at", "timestamp"), ("updated_at", "timestamp"), ("source_system_code", "string"), ("source_system_name", "string")]
fact_claim_header_gen = add_columns(fact_claim_header_gen, fact_claim_header_cols_tail)
df_fact_claim_header = fact_claim_header_gen.build()
save_table(df_fact_claim_header, "fact_claim_header")

# COMMAND ----------

# DBTITLE 1,fact_claim_detail
fact_claim_detail_gen = dg.DataGenerator(spark, rows=5000)
fact_claim_detail_gen = add_synthetic_column(fact_claim_detail_gen, "clm_dtl_claim_id", "string", nullable=False, values=detail_claim_ids, random_values=False)
fact_claim_detail_gen = add_synthetic_column(fact_claim_detail_gen, "clm_dtl_line_nbr", "string", nullable=False, values=detail_line_nbrs, random_values=False)
fact_claim_detail_cols = [("clm_dtl_original_source_claim_id", "string"), ("clm_dtl_source_system", "string"), ("clm_dtl_member_nbr_sk", "string"), ("clmdetail_admit_dt", "timestamp"), ("clm_dtl_specific_dos_date", "date"), ("clm_dtl_specific_dos_thru_date", "date"), ("clm_dtl_apl_posting_date", "date"), ("clm_dtl_claim_receive_date", "timestamp"), ("clm_dtl_check_date", "timestamp"), ("clm_dtl_last_update_date", "timestamp"), ("clm_dtl_benefit_category", "string"), ("clm_dtl_benefit_level", "string"), ("clm_dtl_claim_type", "string"), ("clm_dtl_allowed_amt", "decimal"), ("clm_dtl_billed_amt", "decimal"), ("clm_dtl_deduct_amt", "decimal"), ("clm_dtl_net_amt", "decimal"), ("clm_dtl_paid_amt", "decimal"), ("clm_dtl_actual_paid_amt", "decimal"), ("clm_dtl_not_covered_amt", "decimal"), ("clm_dtl_co_insurance_amt", "decimal"), ("clm_dtl_other_adjustments_amt", "decimal"), ("clm_dtl_cob_savings", "decimal"), ("clm_dtl_oic_paid_amt", "decimal"), ("clm_dtl_oic_allowed_amt", "decimal"), ("clm_dtl_interest_amt", "decimal"), ("clm_dtl_prompt_pay_discount_amt", "decimal"), ("clm_dtl_interest_discount_amt", "decimal"), ("clm_dtl_interest_discount_flag", "string"), ("clm_dtl_copay_amt", "decimal"), ("clm_dtl_copay_reason", "string"), ("clm_dtl_st_cd", "string"), ("clm_dtl_reason_code_sk", "string"), ("clm_dtl_line_status", "string"), ("clm_dtl_clean_claim_ind", "string"), ("clm_dtl_place_of_service", "string"), ("clm_dtl_fee_schedule_code", "string"), ("clm_dtl_authorization_nbr", "string"), ("clm_dtl_check_nbr", "string"), ("clm_dtl_check_added_line_flag", "string"), ("clm_dtl_check_message", "string"), ("clm_dtl_submitting_provider", "string"), ("clm_dtl_rendering_provider", "string"), ("clm_dtl_rendering_provider_type", "string"), ("clm_dtl_rendering_provider_spec", "string"), ("clm_dtl_participating_provider", "string"), ("clm_dtl_adjudication_status", "string"), ("clm_dtl_procedure_code", "string"), ("clm_dtl_procedure_modifier", "string"), ("clm_dtl_modifier_2", "string"), ("clm_dtl_modifier_3", "string"), ("clm_dtl_modifier_4", "string"), ("clm_dtl_procedure_adj", "string"), ("clm_dtl_procedure_qty", "decimal"), ("clm_dtl_revenue_code", "string"), ("clm_dtl_diagnosis_ind_1", "string"), ("clm_dtl_diagnosis_ind_2", "string"), ("clm_dtl_diagnosis_ind_3", "string"), ("clm_dtl_diagnosis_ind_4", "string"), ("clm_dtl_paid_days", "decimal"), ("clm_dtl_anesthesia_time_units", "decimal"), ("clm_dtl_cob_rule", "string"), ("clm_dtl_wrap_network", "string"), ("clm_dtl_returned_ntwrk_repric", "string"), ("clm_dtl_user_id", "string"), ("clm_dtl_extract_date", "timestamp"), ("is_active", "boolean"), ("updated_at", "timestamp"), ("created_at", "timestamp")]
fact_claim_detail_gen = add_columns(fact_claim_detail_gen, fact_claim_detail_cols)
df_fact_claim_detail = fact_claim_detail_gen.build()
save_table(df_fact_claim_detail, "fact_claim_detail")

# COMMAND ----------

# DBTITLE 1,fact_member_enrollment
fact_member_enrollment_gen = dg.DataGenerator(spark, rows=5000)
fact_member_enrollment_gen = add_synthetic_column(fact_member_enrollment_gen, "src_member_business_id", "int", nullable=False, minValue=1, maxValue=5000, step=1)
fact_member_enrollment_cols_pre = [("source_system", "string"), ("mbr_enr_source_member_id", "string"), ("mbr_enr_insured_id", "string"), ("mbr_enr_contract_id", "string"), ("mbr_enr_insured_code", "string"), ("mbr_enr_insured_add_date", "timestamp"), ("mbr_enr_insured_event_date", "timestamp"), ("mbr_enr_insured_event_id", "string"), ("mbr_enr_insured_event_code", "string"), ("mbr_enr_status", "string"), ("mbr_enr_insured_event_add_date", "timestamp"), ("mbr_enr_plan_id", "string"), ("mbr_enr_line_of_business", "string"), ("mbr_enr_line_of_business_id", "string"), ("mbr_enr_group_name", "string"), ("mbr_enr_subgroup_name", "string"), ("mbr_enr_effective_date", "date"), ("mbr_enr_termination_date", "date"), ("mbr_enr_termination_event_date", "date"), ("mbr_enr_termination_reason", "string"), ("mbr_enr_product_id", "string"), ("mbr_enr_group_ck", "string"), ("mbr_enr_group_code", "string"), ("mbr_enr_subgroup_ck", "string"), ("mbr_enr_subgroup_code", "string"), ("is_active", "boolean"), ("id_value", "string"), ("id_type", "string")]
fact_member_enrollment_gen = add_columns(fact_member_enrollment_gen, fact_member_enrollment_cols_pre)
fact_member_enrollment_gen = add_synthetic_column(fact_member_enrollment_gen, "member_sk", "bigint", nullable=False, values=member_sks, random_values=True)
fact_member_enrollment_cols_tail = [("enrollment_sk", "string"), ("payload_hash", "string")]
fact_member_enrollment_gen = add_columns(fact_member_enrollment_gen, fact_member_enrollment_cols_tail)
df_fact_member_enrollment = fact_member_enrollment_gen.build()
save_table(df_fact_member_enrollment, "fact_member_enrollment")

# COMMAND ----------

# DBTITLE 1,Completion
print("Synthetic data generation complete")
