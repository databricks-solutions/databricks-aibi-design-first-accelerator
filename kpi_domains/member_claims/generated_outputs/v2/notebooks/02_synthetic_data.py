# Databricks notebook source
# DBTITLE 1,Synthetic Data — Member Claims
# Uses dbldatagen to generate realistic sample data for all requested tables.
# CRITICAL: All generated columns match the ERD column names and data types.

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

member_keys = list(range(1, 501))
address_keys = list(range(1, 501))
claim_header_keys = list(range(1, 501))
claim_ids = [f"CLM-{i:07d}" for i in range(1, 501)]
detail_claim_ids = [claim_ids[i // 10] for i in range(5000)]
detail_line_numbers = [str((i % 10) + 1) for i in range(5000)]
enrollment_ids = [f"ENR-{i:07d}" for i in range(1, 5001)]

source_codes = ["FACETS", "QNXT", "EPIC", "EDI", "CRM"]
lob_values = ["COMMERCIAL", "MEDICARE", "MEDICAID", "EXCHANGE", "TRICARE"]
state_values = ["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI", "AZ", "WA"]
yn_values = ["Y", "N"]
sex_values = ["F", "M", "U"]
race_values = ["WHITE", "BLACK", "ASIAN", "NATIVE", "PACIFIC", "OTHER", "UNKNOWN"]
ethnicity_values = ["HISPANIC", "NON-HISPANIC", "UNKNOWN"]
name_values = ["Alex Morgan", "Jordan Smith", "Taylor Johnson", "Casey Brown", "Riley Davis", "Avery Miller", "Morgan Wilson", "Jamie Moore"]
first_names = ["Alex", "Jordan", "Taylor", "Casey", "Riley", "Avery", "Morgan", "Jamie", "Cameron", "Quinn"]
last_names = ["Smith", "Johnson", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Thomas"]
city_values = ["Los Angeles", "Houston", "Miami", "New York", "Philadelphia", "Chicago", "Columbus", "Atlanta", "Charlotte", "Phoenix", "Seattle"]
provider_names = ["Northside Medical Group", "Valley Primary Care", "Metro Health Clinic", "Evergreen Family Practice", "Summit Specialty Center", "Lakeside Hospital", "Cedar Surgical Associates", "Community Wellness Partners"]
claim_types = ["PROFESSIONAL", "INSTITUTIONAL", "DENTAL", "VISION", "PHARMACY"]
plan_values = ["HMO", "PPO", "EPO", "POS", "HDHP"]
status_values = ["ACTIVE", "TERMINATED", "PENDING", "SUSPENDED"]
benefit_values = ["MEDICAL", "SURGICAL", "EMERGENCY", "PREVENTIVE", "PHARMACY", "BEHAVIORAL"]
pos_values = ["11", "21", "22", "23", "24", "31", "32", "81"]
proc_values = ["99213", "99214", "93000", "80053", "36415", "71046", "97110", "A0428"]
diag_values = ["I10", "E119", "J45909", "M545", "R079", "Z0000", "N390", "F419", "K219", "G4733"]
modifier_values = ["25", "59", "GP", "RT", "LT", "TC", "QW", "NU"]
poa_values = ["Y", "N", "U", "W"]
id_types = ["MEMBER_ID", "INSURED_ID", "SSN", "ALT_ID", "MEDICAID_ID"]

def add_pk_long(gen, name, rows):
    return gen.withColumn(name, LongType(), minValue=1, maxValue=rows, step=1, random=False)

def add_pk_string_values(gen, name, values):
    return gen.withColumn(name, StringType(), values=values, random=False)

def add_fk_long(gen, name, base_col, values, nulls=0.02):
    return gen.withColumn(name, LongType(), baseColumn=base_col, values=values, percentNulls=nulls)

def add_string(gen, name, nulls=0.08, values=None, template=None):
    if values is not None:
        return gen.withColumn(name, StringType(), values=values, percentNulls=nulls)
    if template is not None:
        return gen.withColumn(name, StringType(), template=template, percentNulls=nulls)
    return gen.withColumn(name, StringType(), template=r"\w\w\w-\d\d\d\d", percentNulls=nulls)

def add_int(gen, name, minv=1, maxv=999999, nulls=0.08):
    return gen.withColumn(name, IntegerType(), minValue=minv, maxValue=maxv, random=True, percentNulls=nulls)

def add_bool(gen, name, nulls=0.05):
    return gen.withColumn(name, BooleanType(), percentNulls=nulls)

def add_date(gen, name, nulls=0.08):
    return gen.withColumn(name, DateType(), begin="2020-01-01", end="2024-12-31", interval="1 day", random=True, percentNulls=nulls)

def add_old_date(gen, name, nulls=0.08):
    return gen.withColumn(name, DateType(), begin="1940-01-01", end="2010-12-31", interval="1 day", random=True, percentNulls=nulls)

def add_ts(gen, name, nulls=0.08):
    return gen.withColumn(name, TimestampType(), begin="2020-01-01 00:00:00", end="2024-12-31 23:59:59", interval="1 day", random=True, percentNulls=nulls)

def add_decimal(gen, name, precision, scale, minv=0, maxv=10000, nulls=0.08):
    return gen.withColumn(name, DecimalType(precision, scale), minValue=minv, maxValue=maxv, random=True, percentNulls=nulls)

def add_member_profile_columns(gen):
    gen = add_string(gen, "mbr_source_member_id", values=[f"MBR-{i:07d}" for i in range(1, 501)])
    gen = add_int(gen, "mbr_member_id", 100000, 999999)
    gen = add_string(gen, "mbr_deers_beneficiary_id")
    gen = add_string(gen, "mbr_deers_family_id")
    gen = add_string(gen, "mbr_sponsor_ssn", template=r"\d\d\d-\d\d-\d\d\d\d")
    gen = add_date(gen, "mbr_current_pcp_eff_date")
    gen = add_string(gen, "mbr_current_pcp_nbr")
    gen = add_old_date(gen, "mbr_dob")
    gen = add_string(gen, "mbr_race", values=race_values)
    gen = add_string(gen, "mbr_sex", values=sex_values)
    gen = add_string(gen, "mbr_ethnicity", values=ethnicity_values)
    gen = add_string(gen, "mbr_first_name", values=first_names)
    gen = add_string(gen, "mbr_middle_name", values=first_names, nulls=0.35)
    gen = add_string(gen, "mbr_last_name", values=last_names)
    gen = add_string(gen, "mbr_full_name", values=name_values)
    gen = add_string(gen, "mbr_marital_status", values=["SINGLE", "MARRIED", "DIVORCED", "WIDOWED", "UNKNOWN"])
    gen = add_date(gen, "mbr_deceased_date", nulls=0.92)
    gen = add_string(gen, "mbr_email", template=r"\w\w\w\w\w@example.com")
    gen = add_string(gen, "mbr_phone_nbr", template=r"\d\d\d-\d\d\d-\d\d\d\d")
    gen = add_string(gen, "mbr_mobile_nbr", template=r"\d\d\d-\d\d\d-\d\d\d\d")
    gen = add_string(gen, "mbr_work_nbr", template=r"\d\d\d-\d\d\d-\d\d\d\d", nulls=0.25)
    gen = add_string(gen, "mbr_sub_group_cd")
    gen = add_date(gen, "mbr_idcard_issue_date")
    gen = add_string(gen, "mbr_line_of_business", values=lob_values)
    gen = add_string(gen, "mbr_text_opt_in", values=yn_values)
    gen = add_string(gen, "mbr_current_riders", values=["NONE", "DENTAL", "VISION", "RX", "DENTAL_VISION"])
    gen = add_string(gen, "mbr_authorized_rep", values=name_values, nulls=0.45)
    gen = add_string(gen, "mbr_alt_sub_nbr")
    gen = add_string(gen, "mbr_relationship_type", values=["SELF", "SPOUSE", "CHILD", "DEPENDENT", "OTHER"])
    gen = add_string(gen, "mbr_salary_tier", values=["A", "B", "C", "D", "UNKNOWN"])
    gen = add_string(gen, "mbr_pcp_auto_assigned", values=yn_values)
    gen = add_string(gen, "mbr_secured_flag", values=yn_values)
    gen = add_string(gen, "mbr_pharmacy_discount_flag", values=yn_values)
    gen = add_string(gen, "mbr_employee_id")
    gen = add_string(gen, "mbr_line_of_business_name", values=lob_values)
    gen = add_string(gen, "mbr_responsible_party_id")
    gen = add_string(gen, "mbr_responsible_party_name", values=name_values)
    gen = add_string(gen, "mbr_deceased_flag", values=yn_values)
    gen = add_string(gen, "mbr_pcp_lock_in_indicator", values=yn_values)
    gen = add_string(gen, "mbr_alt_person_nbr")
    gen = add_string(gen, "mbr_state", values=state_values)
    gen = add_string(gen, "mbr_zip_code", template=r"\d\d\d\d\d")
    gen = add_string(gen, "mbr_pcp_lock_in_type", values=["NONE", "SOFT", "HARD", "TEMPORARY"])
    gen = add_string(gen, "mbr_provider_group_name", values=provider_names)
    gen = add_string(gen, "mbr_name_suffix", values=["JR", "SR", "II", "III", "IV"], nulls=0.75)
    gen = add_int(gen, "mbr_sub_flag", 0, 1)
    gen = add_string(gen, "mbr_sub_ssn", template=r"\d\d\d-\d\d-\d\d\d\d")
    gen = add_date(gen, "mbr_extract_date")
    gen = add_string(gen, "mbr_medicaid_case_nbr")
    gen = add_string(gen, "mbr_relationship_ind", values=["S", "P", "C", "D", "O"])
    gen = add_string(gen, "source_system_code", values=source_codes)
    gen = add_string(gen, "source_system_name", values=source_codes)
    gen = add_string(gen, "record_hash")
    gen = add_ts(gen, "created_at")
    gen = add_ts(gen, "updated_at")
    gen = add_bool(gen, "is_active")
    return gen

print("Setup complete")

# COMMAND ----------

# DBTITLE 1,dim_member_v2
gen = dg.DataGenerator(spark, rows=500, partitions=4)
gen = add_pk_long(gen, "member_sk", 500)
gen = add_member_profile_columns(gen)
gen = add_ts(gen, "end_date", nulls=0.70)
df = gen.build()
df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{schema_name}.dim_member_v2")
print("Wrote dim_member_v2")

# COMMAND ----------

# DBTITLE 1,dim_address_v2
gen = dg.DataGenerator(spark, rows=500, partitions=4)
gen = add_pk_long(gen, "address_key", 500)
gen = add_string(gen, "entity_type_key", values=["MEMBER", "PROVIDER", "FACILITY"])
gen = add_fk_long(gen, "entity_dimension_key", "address_key", member_keys, nulls=0.05)
gen = add_string(gen, "address_type_code", values=["HOME", "MAILING", "BILLING", "SERVICE", "OFFICE"])
gen = add_string(gen, "street_address_1", template=r"\d\d\d Main St")
gen = add_string(gen, "street_address_2", template=r"Suite \d\d\d", nulls=0.60)
gen = add_string(gen, "city", values=city_values)
gen = add_string(gen, "state", values=state_values)
gen = add_string(gen, "zip_code", template=r"\d\d\d\d\d")
gen = add_string(gen, "country_code", values=["US"])
gen = add_string(gen, "county", values=["Orange", "Harris", "Miami-Dade", "Kings", "Cook", "Maricopa", "Franklin", "Fulton"])
gen = add_bool(gen, "is_active")
gen = add_ts(gen, "valid_from_date")
gen = add_ts(gen, "valid_to_date", nulls=0.50)
gen = add_string(gen, "source_system_code", values=source_codes)
gen = add_string(gen, "source_system_name", values=source_codes)
gen = add_string(gen, "record_hash")
gen = add_ts(gen, "created_at")
gen = add_ts(gen, "updated_at")
df = gen.build()
df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{schema_name}.dim_address_v2")
print("Wrote dim_address_v2")

# COMMAND ----------

# DBTITLE 1,dim_provider_v2
gen = dg.DataGenerator(spark, rows=500, partitions=4)
gen = add_pk_long(gen, "provider_sk", 500)
gen = add_fk_long(gen, "assigned_provider_sk", "provider_sk", list(range(1, 501)), nulls=0.20)
gen = add_string(gen, "source_provider_id")
gen = add_string(gen, "provider_npi", template=r"\d\d\d\d\d\d\d\d\d\d")
gen = add_string(gen, "provider_tax_id", template=r"\d\d-\d\d\d\d\d\d\d")
gen = add_string(gen, "provider_name", values=provider_names)
gen = add_fk_long(gen, "provider_address_sk", "provider_sk", address_keys, nulls=0.05)
gen = add_bool(gen, "pcp_flag")
gen = add_string(gen, "affiliation_id")
gen = add_ts(gen, "valid_from_date")
gen = add_ts(gen, "valid_to_date", nulls=0.50)
gen = add_bool(gen, "is_active")
gen = add_string(gen, "source_system", values=source_codes)
gen = add_ts(gen, "created_at")
gen = add_ts(gen, "updated_at")
gen = add_ts(gen, "last_update_dt")
gen = add_string(gen, "record_hash")
df = gen.build()
df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{schema_name}.dim_provider_v2")
print("Wrote dim_provider_v2")

# COMMAND ----------

# DBTITLE 1,dim_member_identifier_v2
gen = dg.DataGenerator(spark, rows=500, partitions=4)
gen = add_pk_long(gen, "mbr_identifier_sk", 500)
gen = add_fk_long(gen, "member_sk", "mbr_identifier_sk", member_keys, nulls=0.02)
gen = add_string(gen, "id_type", values=id_types)
gen = add_string(gen, "id_value")
gen = add_string(gen, "source_system_code", values=source_codes)
gen = add_string(gen, "source_system_name", values=source_codes)
gen = add_ts(gen, "valid_to_date", nulls=0.50)
gen = add_ts(gen, "valid_from_date")
gen = add_bool(gen, "is_active")
gen = add_ts(gen, "created_at")
gen = add_ts(gen, "updated_at")
gen = add_string(gen, "record_hash")
df = gen.build()
df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{schema_name}.dim_member_identifier_v2")
print("Wrote dim_member_identifier_v2")

# COMMAND ----------

# DBTITLE 1,dim_member_history_v2
gen = dg.DataGenerator(spark, rows=500, partitions=4)
gen = add_pk_long(gen, "mbr_history_sk", 500)
gen = add_fk_long(gen, "member_sk", "mbr_history_sk", member_keys, nulls=0.02)
gen = add_member_profile_columns(gen)
gen = add_ts(gen, "valid_to_date", nulls=0.35)
gen = add_ts(gen, "valid_from_date")
df = gen.build()
df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{schema_name}.dim_member_history_v2")
print("Wrote dim_member_history_v2")

# COMMAND ----------

# DBTITLE 1,fact_claim_header_v2
gen = dg.DataGenerator(spark, rows=500, partitions=4)
gen = add_pk_long(gen, "clm_header_sk", 500)
gen = add_int(gen, "clm_id", 100000, 999999)
gen = add_pk_string_values(gen, "clm_claim_id", claim_ids)
for c in ["clm_original_source_claim_id", "clm_original_batch_nbr", "clm_patient_control_nbr", "clm_document_adj_control_nbr"]:
    gen = add_string(gen, c)
gen = add_string(gen, "clm_claim_type", values=claim_types)
gen = add_string(gen, "clm_bill_type", values=["111", "131", "137", "851", "831"])
gen = add_string(gen, "clm_authorization_nbr")
gen = add_string(gen, "clm_ext_authorization_nbr")
for c in ["clm_admit_date", "clm_claim_thru_date", "clm_discharge_date"]:
    gen = add_date(gen, c)
gen = add_int(gen, "clm_admission_hour", 0, 23)
gen = add_int(gen, "clm_discharge_hour", 0, 23)
gen = add_string(gen, "clm_admission_type", values=["ELECTIVE", "EMERGENCY", "URGENT", "NEWBORN", "TRAUMA"])
gen = add_string(gen, "clm_admission_source", values=["PHYSICIAN", "CLINIC", "TRANSFER", "ER", "COURT"])
gen = add_string(gen, "clm_member_nbr")
gen = add_string(gen, "clm_member_name", values=name_values)
gen = add_fk_long(gen, "clm_member_sk", "clm_header_sk", member_keys, nulls=0.02)
gen = add_string(gen, "clm_member_group_nbr")
gen = add_string(gen, "clm_member_subgroup_nbr")
gen = add_string(gen, "clm_plan_code", values=plan_values)
gen = add_string(gen, "clm_line_of_business", values=lob_values)
gen = add_decimal(gen, "clm_birth_weight", 9, 2, 500, 6000, 0.70)
gen = add_int(gen, "clm_covered_days", 0, 45)
gen = add_string(gen, "clm_accident_st", values=state_values, nulls=0.75)
for c in ["clm_attending_physician", "clm_attending_physician_spec", "clm_operating_provider_name", "clm_operating_provider_npi", "clm_submitting_provider", "clm_submitting_provider_spec", "clm_submitting_provider_type", "clm_billing_provider", "clm_referring_provider", "clm_referring_provider_spec", "clm_referring_provider_type"]:
    gen = add_string(gen, c)
gen = add_string(gen, "clm_is_par_submitting_provider", values=yn_values)
gen = add_bool(gen, "clm_is_par_referring_provider")
gen = add_bool(gen, "clm_is_par_rendering_provider")
for c in ["clm_assigned_pcp", "clm_assigned_provider_site", "clm_insurance_id", "clm_member_contract_id"]:
    gen = add_string(gen, c)
gen = add_int(gen, "clm_pcp_visit_flag", 0, 1)
gen = add_string(gen, "clm_pcp_in_type", values=["IN_NETWORK", "OUT_NETWORK", "UNKNOWN"])
gen = add_decimal(gen, "clm_pcp_wthld_pct", 9, 4, 0, 100, 0.30)
gen = add_string(gen, "clm_service_fac_npi", template=r"\d\d\d\d\d\d\d\d\d\d")
gen = add_string(gen, "clm_service_fac_loc_name", values=provider_names)
gen = add_fk_long(gen, "clm_service_facility_address_sk", "clm_header_sk", address_keys, nulls=0.05)
for c in ["clm_providers_account_no", "clm_onset_of_illness_date", "clm_admitting_diagnosis_code", "clm_admitting_diagnosis_method"]:
    gen = add_string(gen, c)
for i in range(1, 26):
    gen = add_string(gen, f"clm_diagnosis_{i}", values=diag_values)
    gen = add_string(gen, f"clm_diagnosis_{i}_icd_method", values=["ICD9", "ICD10"])
for i in range(1, 26):
    gen = add_string(gen, f"clm_diagnosis_{i}_poa", values=poa_values)
for i in range(1, 7):
    gen = add_string(gen, f"clm_surgical_{i}", values=["0FT44ZZ", "0DTJ4ZZ", "021009W", "5A1221Z", "30233N1"])
    gen = add_string(gen, f"clm_surgical_icd_method_{i}", values=["ICD9", "ICD10"])
for c in ["clm_drg_code", "clm_service_type_code", "clm_cob_type", "clm_claim_timely_filing", "clm_accept_assignment_indicator"]:
    gen = add_string(gen, c)
gen = add_date(gen, "clm_add_date")
gen = add_string(gen, "clm_add_user")
gen = add_date(gen, "clm_update_date")
gen = add_string(gen, "clm_update_user")
gen = add_ts(gen, "clm_extract_date")
gen = add_date(gen, "clm_last_updated_date")
gen = add_date(gen, "clm_original_insert_date")
gen = add_string(gen, "clm_user_id")
gen = add_string(gen, "clm_orig_source", values=source_codes)
gen = add_bool(gen, "is_active")
gen = add_ts(gen, "end_date", nulls=0.70)
gen = add_string(gen, "record_hash")
gen = add_date(gen, "last_updated_date")
gen = add_ts(gen, "created_at")
gen = add_ts(gen, "updated_at")
gen = add_string(gen, "source_system_code", values=source_codes)
gen = add_string(gen, "source_system_name", values=source_codes)
df = gen.build()
df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{schema_name}.fact_claim_header_v2")
print("Wrote fact_claim_header_v2")

# COMMAND ----------

# DBTITLE 1,fact_claim_detail_v2
gen = dg.DataGenerator(spark, rows=5000, partitions=8)
gen = add_pk_string_values(gen, "clm_dtl_claim_id", detail_claim_ids)
gen = add_pk_string_values(gen, "clm_dtl_line_nbr", detail_line_numbers)
for c in ["clm_dtl_original_source_claim_id", "clm_dtl_source_system", "clm_dtl_member_nbr_sk"]:
    gen = add_string(gen, c)
gen = add_ts(gen, "clmdetail_admit_dt")
for c in ["clm_dtl_specific_dos_date", "clm_dtl_specific_dos_thru_date", "clm_dtl_apl_posting_date"]:
    gen = add_date(gen, c)
for c in ["clm_dtl_claim_receive_date", "clm_dtl_check_date", "clm_dtl_last_update_date"]:
    gen = add_ts(gen, c)
gen = add_string(gen, "clm_dtl_benefit_category", values=benefit_values)
gen = add_string(gen, "clm_dtl_benefit_level", values=["IN", "OUT", "TIER1", "TIER2", "NONCOVERED"])
gen = add_string(gen, "clm_dtl_claim_type", values=claim_types)
gen = add_decimal(gen, "clm_dtl_allowed_amt", 28, 4)
gen = add_decimal(gen, "clm_dtl_billed_amt", 27, 4, 25, 25000)
gen = add_decimal(gen, "clm_dtl_deduct_amt", 27, 4, 0, 2000)
gen = add_decimal(gen, "clm_dtl_net_amt", 28, 4)
gen = add_decimal(gen, "clm_dtl_paid_amt", 28, 4)
gen = add_decimal(gen, "clm_dtl_actual_paid_amt", 38, 4)
gen = add_decimal(gen, "clm_dtl_not_covered_amt", 27, 4)
gen = add_decimal(gen, "clm_dtl_co_insurance_amt", 27, 4)
gen = add_decimal(gen, "clm_dtl_other_adjustments_amt", 30, 2)
gen = add_decimal(gen, "clm_dtl_cob_savings", 32, 4)
gen = add_decimal(gen, "clm_dtl_oic_paid_amt", 19, 4)
gen = add_decimal(gen, "clm_dtl_oic_allowed_amt", 19, 4)
gen = add_decimal(gen, "clm_dtl_interest_amt", 38, 6, 0, 500)
gen = add_decimal(gen, "clm_dtl_prompt_pay_discount_amt", 20, 4, 0, 500)
gen = add_decimal(gen, "clm_dtl_interest_discount_amt", 38, 6, 0, 500)
gen = add_string(gen, "clm_dtl_interest_discount_flag", values=yn_values)
gen = add_decimal(gen, "clm_dtl_copay_amt", 27, 4, 0, 150)
for c in ["clm_dtl_copay_reason", "clm_dtl_sc_cd", "clm_dtl_reason_code_sk"]:
    gen = add_string(gen, c)
gen = add_string(gen, "clm_dtl_line_status", values=["PAID", "DENIED", "PENDED", "ADJUSTED"])
gen = add_string(gen, "clm_dtl_clean_claim_ind", values=yn_values)
gen = add_string(gen, "clm_dtl_place_of_service", values=pos_values)
for c in ["clm_dtl_fee_schedule_code", "clm_dtl_authorization_nbr", "clm_dtl_check_nbr", "clm_dtl_check_added_line_flag", "clm_dtl_check_message", "clm_dtl_submitting_provider", "clm_dtl_rendering_provider", "clm_dtl_rendering_provider_type", "clm_dtl_rendering_provider_spec", "clm_dtl_participating_provider"]:
    gen = add_string(gen, c)
gen = add_string(gen, "clm_dtl_adjudication_status", values=["APPROVED", "DENIED", "PENDED", "REVERSED"])
gen = add_string(gen, "clm_dtl_procedure_code", values=proc_values)
gen = add_string(gen, "clm_dtl_procedure_modifier", values=modifier_values)
gen = add_string(gen, "clm_dtl_modifier_2", values=modifier_values)
gen = add_string(gen, "clm_dtl_modifier_3", values=modifier_values)
gen = add_string(gen, "clm_dtl_modifier_4", values=modifier_values)
gen = add_string(gen, "clm_dtl_procedure_adj")
gen = add_decimal(gen, "clm_dtl_procedure_qty", 15, 3, 1, 20)
gen = add_string(gen, "clm_dtl_revenue_code", values=["0250", "0300", "0450", "0636", "0762"])
for i in range(1, 5):
    gen = add_string(gen, f"clm_dtl_diagnosis_ind_{i}", values=diag_values)
gen = add_decimal(gen, "clm_dtl_paid_days", 36, 3, 0, 30)
gen = add_decimal(gen, "clm_dtl_anesthesia_time_units", 12, 2, 0, 20)
for c in ["clm_dtl_cob_rule", "clm_dtl_wrap_network", "clm_dtl_returned_ntwrk_repric", "clm_dtl_user_id"]:
    gen = add_string(gen, c)
gen = add_ts(gen, "clm_dtl_extract_date")
gen = add_bool(gen, "is_active")
gen = add_ts(gen, "updated_at")
gen = add_ts(gen, "created_at")
df = gen.build()
df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{schema_name}.fact_claim_detail_v2")
print("Wrote fact_claim_detail_v2")

# COMMAND ----------

# DBTITLE 1,fact_member_enrollment_v2
gen = dg.DataGenerator(spark, rows=5000, partitions=8)
gen = add_pk_string_values(gen, "enrollment_sk", enrollment_ids)
gen = add_string(gen, "source_system", values=source_codes)
gen = add_int(gen, "src_member_business_id", 100000, 999999)
gen = add_string(gen, "mbr_enr_source_member_id")
gen = add_string(gen, "mbr_enr_insured_id")
gen = add_string(gen, "mbr_enr_contract_id")
gen = add_string(gen, "mbr_enr_insured_code")
gen = add_ts(gen, "mbr_enr_insured_add_date")
gen = add_ts(gen, "mbr_enr_insured_event_date")
gen = add_string(gen, "mbr_enr_insured_event_id")
gen = add_string(gen, "mbr_enr_insured_event_code")
gen = add_string(gen, "mbr_enr_status", values=status_values)
gen = add_ts(gen, "mbr_enr_insured_event_add_date")
gen = add_string(gen, "mbr_enr_plan_id", values=plan_values)
gen = add_string(gen, "mbr_enr_line_of_business", values=lob_values)
gen = add_string(gen, "mbr_enr_line_of_business_id")
gen = add_string(gen, "mbr_enr_group_name", values=["Acme Employees", "City Workers", "Retail Associates", "Teachers Trust", "Federal Group"])
gen = add_string(gen, "mbr_enr_subgroup_name", values=["North", "South", "East", "West", "Central"])
gen = add_date(gen, "mbr_enr_effective_date")
gen = add_date(gen, "mbr_enr_termination_date", nulls=0.45)
gen = add_date(gen, "mbr_enr_termination_event_date", nulls=0.50)
gen = add_string(gen, "mbr_enr_termination_reason", values=["VOLUNTARY", "NONPAYMENT", "GROUP_TERM", "DEATH", "OTHER"], nulls=0.45)
gen = add_string(gen, "mbr_enr_product_id")
gen = add_string(gen, "mbr_enr_group_ck")
gen = add_string(gen, "mbr_enr_group_code")
gen = add_string(gen, "mbr_enr_subgroup_ck")
gen = add_string(gen, "mbr_enr_subgroup_code")
gen = add_bool(gen, "is_active")
gen = add_string(gen, "id_value")
gen = add_string(gen, "id_type", values=id_types)
gen = add_fk_long(gen, "member_sk", "enrollment_sk", member_keys, nulls=0.02)
gen = add_string(gen, "payload_hash")
df = gen.build()
df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{schema_name}.fact_member_enrollment_v2")
print("Wrote fact_member_enrollment_v2")
