# Databricks notebook source
# DBTITLE 1,Synthetic Data — Member Claims
# Uses dbldatagen to generate realistic sample data for all tables.
# CRITICAL: All generated columns match ERD names and Spark SQL types.
# Target schema: aw_serverless_stable_catalog.aibi_member_claims

# COMMAND ----------

# DBTITLE 1,Install dependencies
%pip install dbldatagen --quiet
dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Setup and Type Helpers
import dbldatagen as dg
from pyspark.sql.types import *

_orig_withColumn = dg.DataGenerator.withColumn
def _safe_withColumn(self, colName, colType, *args, **kwargs):
    if colType == TimestampType() or colType is TimestampType or str(colType).lower() in ('timestamp', 'timestamp_ntz'):
        for key in ('begin', 'end'):
            if key in kwargs and isinstance(kwargs[key], str) and len(kwargs[key]) == 10:
                kwargs[key] = f"{kwargs[key]} 00:00:00" if key == 'begin' else f"{kwargs[key]} 23:59:59"
    return _orig_withColumn(self, colName, colType, *args, **kwargs)
dg.DataGenerator.withColumn = _safe_withColumn

CATALOG = "aw_serverless_stable_catalog"
SCHEMA = "aibi_member_claims"
VERSION_SUFFIX = "_v3"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`")

member_ids = list(range(1, 501))
address_ids = list(range(100001, 100501))
provider_ids = list(range(200001, 200501))
claim_header_sks = list(range(300001, 300501))
claim_ids = [f"CLM{i:06d}" for i in range(1, 501)]
detail_claim_ids = claim_ids * 10
enrollment_ids = [f"ENR{i:07d}" for i in range(1, 5001)]

source_systems = ["FACETS", "QNXT", "AMISYS", "EDW", "CLAIMSX"]
source_names = ["Core Claims", "Enrollment Hub", "Provider Master", "Member Master"]
states = ["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI", "AZ", "WA"]
cities = ["Los Angeles", "Houston", "Miami", "New York", "Philadelphia", "Chicago", "Columbus", "Atlanta", "Charlotte", "Phoenix", "Seattle"]
counties = ["Orange", "Harris", "Miami-Dade", "Kings", "Cook", "Franklin", "Fulton", "Mecklenburg", "Maricopa", "King"]
names_first = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "William", "Elizabeth"]
names_middle = ["A", "B", "C", "D", "E", "F", "G"]
names_last = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Wilson", "Anderson"]
full_names = ["James Smith", "Mary Johnson", "Robert Williams", "Patricia Brown", "John Jones", "Jennifer Garcia", "Michael Miller", "Linda Davis"]
yes_no = ["Y", "N"]
sex_values = ["M", "F", "U"]
race_values = ["White", "Black", "Asian", "Native American", "Pacific Islander", "Other", "Unknown"]
ethnicity_values = ["Hispanic", "Non-Hispanic", "Unknown"]
lob_values = ["COMMERCIAL", "MEDICARE", "MEDICAID", "EXCHANGE", "TRICARE"]
plan_values = ["HMO", "PPO", "EPO", "POS", "HDHP"]
claim_types = ["MEDICAL", "INSTITUTIONAL", "PROFESSIONAL", "DENTAL", "VISION"]
provider_types = ["PCP", "SPECIALIST", "FACILITY", "ANCILLARY", "LAB"]
specialties = ["FAMILY PRACTICE", "INTERNAL MEDICINE", "CARDIOLOGY", "ORTHOPEDICS", "RADIOLOGY", "PEDIATRICS"]
status_values = ["ACTIVE", "PENDED", "PAID", "DENIED", "ADJUSTED"]
diagnosis_codes = ["E119", "I10", "J45909", "M545", "R079", "N390", "K219", "F419", "Z00129", "G4733"]
procedure_codes = ["99213", "99214", "93000", "80053", "36415", "97110", "71046", "99385", "12001", "88305"]
modifier_values = ["25", "59", "RT", "LT", "TC", "GP", "GA", "QW"]
id_types = ["MBR_ID", "SSN", "MEDICAID_ID", "MEDICARE_ID", "ALT_ID"]

def add_str(gen, name, values=None, nulls=0.1):
    if values is None:
        return gen.withColumn(name, StringType(), template=r'\\w\\w\\w-\\d\\d\\d\\d', random=True, percentNulls=nulls)
    return gen.withColumn(name, StringType(), values=values, random=True, percentNulls=nulls)

def add_int(gen, name, min_value=1, max_value=9999, nulls=0.1):
    return gen.withColumn(name, IntegerType(), minValue=min_value, maxValue=max_value, random=True, percentNulls=nulls)

def add_long(gen, name, min_value=1, max_value=999999, nulls=0.1):
    return gen.withColumn(name, LongType(), minValue=min_value, maxValue=max_value, random=True, percentNulls=nulls)

def add_bool(gen, name, nulls=0.1):
    return gen.withColumn(name, BooleanType(), values=[True, False], weights=[8, 2], random=True, percentNulls=nulls)

def add_date(gen, name, nulls=0.1):
    return gen.withColumn(name, DateType(), begin='2020-01-01', end='2024-12-31', interval='1 day', random=True, percentNulls=nulls)

def add_ts(gen, name, nulls=0.1):
    return gen.withColumn(name, TimestampType(), begin='2020-01-01 00:00:00', end='2024-12-31 23:59:59', interval='1 day', random=True, percentNulls=nulls)

def add_dec(gen, name, precision, scale, min_value=0.0, max_value=5000.0, nulls=0.1):
    return gen.withColumn(name, DecimalType(precision, scale), minValue=min_value, maxValue=max_value, random=True, percentNulls=nulls)

def add_hash(gen, name):
    return gen.withColumn(name, StringType(), template=r'\\w\\w\\w-\\d\\d\\d\\d', random=True, percentNulls=0.05)

def save_table(df, logical_name):
    table_name = f"`{CATALOG}`.`{SCHEMA}`.`{logical_name}{VERSION_SUFFIX}`"
    df.write.format('delta').mode('overwrite').option('overwriteSchema', 'true').saveAsTable(table_name)
    print(f"saved {logical_name}{VERSION_SUFFIX}")

def add_member_profile_columns(gen, include_end_date=True, include_valid_dates=False):
    gen = add_str(gen, "mbr_source_member_id", nulls=0.05)
    gen = add_int(gen, "mbr_member_id", 100000, 999999, 0.02)
    gen = add_str(gen, "mbr_deers_beneficiary_id", nulls=0.15)
    gen = add_str(gen, "mbr_deers_family_id", nulls=0.15)
    gen = gen.withColumn("mbr_sponsor_ssn", StringType(), template=r'\\d\\d\\d-\\d\\d-\\d\\d\\d\\d', random=True, percentNulls=0.2)
    gen = add_date(gen, "mbr_current_pcp_eff_date", 0.1)
    gen = add_str(gen, "mbr_current_pcp_nbr", nulls=0.12)
    gen = gen.withColumn("mbr_dob", DateType(), begin='1940-01-01', end='2010-12-31', interval='1 day', random=True, percentNulls=0.02)
    gen = add_str(gen, "mbr_race", race_values, 0.08)
    gen = add_str(gen, "mbr_sex", sex_values, 0.03)
    gen = add_str(gen, "mbr_ethnicity", ethnicity_values, 0.08)
    gen = add_str(gen, "mbr_first_name", names_first, 0.03)
    gen = add_str(gen, "mbr_middle_name", names_middle, 0.25)
    gen = add_str(gen, "mbr_last_name", names_last, 0.03)
    gen = add_str(gen, "mbr_full_name", full_names, 0.03)
    gen = add_str(gen, "mbr_marital_status", ["S", "M", "D", "W", "U"], 0.1)
    gen = add_date(gen, "mbr_deceased_date", 0.95)
    gen = gen.withColumn("mbr_email", StringType(), template=r'\\w\\w\\w\\w\\w@example.com', random=True, percentNulls=0.15)
    gen = gen.withColumn("mbr_phone_nbr", StringType(), template=r'\\d\\d\\d-\\d\\d\\d-\\d\\d\\d\\d', random=True, percentNulls=0.1)
    gen = gen.withColumn("mbr_mobile_nbr", StringType(), template=r'\\d\\d\\d-\\d\\d\\d-\\d\\d\\d\\d', random=True, percentNulls=0.15)
    gen = gen.withColumn("mbr_work_nbr", StringType(), template=r'\\d\\d\\d-\\d\\d\\d-\\d\\d\\d\\d', random=True, percentNulls=0.3)
    gen = add_str(gen, "mbr_sub_group_cd", ["SG100", "SG200", "SG300", "SG400"], 0.08)
    gen = add_date(gen, "mbr_idcard_issue_date", 0.12)
    gen = add_str(gen, "mbr_line_of_business", lob_values, 0.04)
    gen = add_str(gen, "mbr_text_opt_in", yes_no, 0.08)
    gen = add_str(gen, "mbr_current_riders", ["RX", "DENTAL", "VISION", "RX,DENTAL", "NONE"], 0.2)
    gen = add_str(gen, "mbr_authorized_rep", full_names, 0.75)
    gen = add_str(gen, "mbr_alt_sub_nbr", nulls=0.25)
    gen = add_str(gen, "mbr_relationship_type", ["SELF", "SPOUSE", "CHILD", "DEPENDENT", "OTHER"], 0.08)
    gen = add_str(gen, "mbr_salary_tier", ["TIER1", "TIER2", "TIER3", "TIER4"], 0.35)
    gen = add_str(gen, "mbr_pcp_auto_assigned", yes_no, 0.12)
    gen = add_str(gen, "mbr_secured_flag", yes_no, 0.08)
    gen = add_str(gen, "mbr_pharmacy_discount_flag", yes_no, 0.12)
    gen = add_str(gen, "mbr_employee_id", nulls=0.35)
    gen = add_str(gen, "mbr_line_of_business_name", ["Commercial", "Medicare Advantage", "Medicaid Managed Care", "Exchange"], 0.04)
    gen = add_str(gen, "mbr_responsible_party_id", nulls=0.3)
    gen = add_str(gen, "mbr_responsible_party_name", full_names, 0.3)
    gen = add_str(gen, "mbr_deceased_flag", yes_no, 0.05)
    gen = add_str(gen, "mbr_pcp_lock_in_indicator", yes_no, 0.15)
    gen = add_str(gen, "mbr_alt_person_nbr", nulls=0.25)
    gen = add_str(gen, "mbr_state", states, 0.04)
    gen = gen.withColumn("mbr_zip_code", StringType(), template=r'\\d\\d\\d\\d\\d', random=True, percentNulls=0.04)
    gen = add_str(gen, "mbr_pcp_lock_in_type", ["NONE", "VOLUNTARY", "MANDATORY"], 0.25)
    gen = add_str(gen, "mbr_provider_group_name", ["North Medical Group", "Central Care Partners", "Valley Health", "Premier Physicians"], 0.18)
    gen = add_str(gen, "mbr_name_suffix", ["JR", "SR", "II", "III"], 0.85)
    gen = add_int(gen, "mbr_sub_flag", 0, 1, 0.08)
    gen = gen.withColumn("mbr_sub_ssn", StringType(), template=r'\\d\\d\\d-\\d\\d-\\d\\d\\d\\d', random=True, percentNulls=0.2)
    gen = add_date(gen, "mbr_extract_date", 0.05)
    gen = add_str(gen, "mbr_medicaid_case_nbr", nulls=0.45)
    gen = add_str(gen, "mbr_relationship_ind", ["S", "D", "C", "O"], 0.1)
    gen = add_str(gen, "source_system_code", source_systems, 0.02)
    gen = add_str(gen, "source_system_name", source_names, 0.02)
    gen = add_hash(gen, "record_hash")
    gen = add_ts(gen, "created_at", 0.02)
    gen = add_ts(gen, "updated_at", 0.02)
    gen = add_bool(gen, "is_active", 0.02)
    if include_end_date:
        gen = add_ts(gen, "end_date", 0.85)
    if include_valid_dates:
        gen = add_ts(gen, "valid_to_date", 0.35)
        gen = add_ts(gen, "valid_from_date", 0.02)
    return gen

# COMMAND ----------

# DBTITLE 1,dim_member
gen = dg.DataGenerator(spark, rows=500)
gen = gen.withColumn("member_sk", LongType(), values=member_ids)
gen = add_member_profile_columns(gen, include_end_date=True, include_valid_dates=False)
df = gen.build()
save_table(df, "dim_member")

# COMMAND ----------

# DBTITLE 1,dim_address
gen = dg.DataGenerator(spark, rows=500)
gen = gen.withColumn("address_key", LongType(), values=address_ids)
gen = add_str(gen, "entity_type_key", ["MEMBER", "PROVIDER", "FACILITY"], 0.05)
gen = gen.withColumn("entity_dimension_key", LongType(), baseColumn="address_key", values=member_ids, random=True, percentNulls=0.05)
gen = add_str(gen, "address_type_code", ["HOME", "MAILING", "BILLING", "SERVICE", "OFFICE"], 0.05)
gen = gen.withColumn("street_address_1", StringType(), template=r'\\d\\d\\d Main St', random=True, percentNulls=0.03)
gen = gen.withColumn("street_address_2", StringType(), template=r'Apt \\d\\d', random=True, percentNulls=0.65)
gen = add_str(gen, "city", cities, 0.03)
gen = add_str(gen, "state", states, 0.03)
gen = gen.withColumn("zip_code", StringType(), template=r'\\d\\d\\d\\d\\d', random=True, percentNulls=0.03)
gen = add_str(gen, "country_code", ["US"], 0.01)
gen = add_str(gen, "county", counties, 0.08)
gen = add_bool(gen, "is_active", 0.02)
gen = add_ts(gen, "valid_from_date", 0.02)
gen = add_ts(gen, "valid_to_date", 0.35)
gen = add_str(gen, "source_system_code", source_systems, 0.02)
gen = add_str(gen, "source_system_name", source_names, 0.02)
gen = add_hash(gen, "record_hash")
gen = add_ts(gen, "created_at", 0.02)
gen = add_ts(gen, "updated_at", 0.02)
df = gen.build()
save_table(df, "dim_address")

# COMMAND ----------

# DBTITLE 1,dim_provider
gen = dg.DataGenerator(spark, rows=500)
gen = gen.withColumn("provider_sk", LongType(), values=provider_ids)
gen = gen.withColumn("assigned_provider_sk", LongType(), baseColumn="provider_sk", values=provider_ids, random=True, percentNulls=0.15)
gen = add_str(gen, "source_provider_id", nulls=0.05)
gen = gen.withColumn("provider_npi", StringType(), template=r'\\d\\d\\d\\d\\d\\d\\d\\d\\d\\d', random=True, percentNulls=0.05)
gen = gen.withColumn("provider_tax_id", StringType(), template=r'\\d\\d-\\d\\d\\d\\d\\d\\d\\d', random=True, percentNulls=0.08)
gen = add_str(gen, "provider_name", ["North Clinic", "Central Hospital", "Valley Medical", "Premier Lab", "Care First Physicians", "Community Imaging"], 0.04)
gen = gen.withColumn("provider_address_sk", LongType(), baseColumn="provider_sk", values=address_ids, random=True, percentNulls=0.05)
gen = add_bool(gen, "pcp_flag", 0.08)
gen = add_str(gen, "affiliation_id", nulls=0.2)
gen = add_ts(gen, "valid_from_date", 0.03)
gen = add_ts(gen, "valid_to_date", 0.35)
gen = add_bool(gen, "is_active", 0.02)
gen = add_str(gen, "source_system", source_systems, 0.02)
gen = add_ts(gen, "created_at", 0.02)
gen = add_ts(gen, "updated_at", 0.02)
gen = add_ts(gen, "last_update_dt", 0.02)
gen = add_hash(gen, "record_hash")
df = gen.build()
save_table(df, "dim_provider")

# COMMAND ----------

# DBTITLE 1,dim_member_identifier
gen = dg.DataGenerator(spark, rows=500)
gen = gen.withColumn("mbr_identifier_sk", LongType(), values=list(range(400001, 400501)))
gen = gen.withColumn("member_sk", LongType(), baseColumn="mbr_identifier_sk", values=member_ids, random=True, percentNulls=0.03)
gen = add_str(gen, "id_type", id_types, 0.03)
gen = add_str(gen, "id_value", nulls=0.03)
gen = add_str(gen, "source_system_code", source_systems, 0.02)
gen = add_str(gen, "source_system_name", source_names, 0.02)
gen = add_ts(gen, "valid_to_date", 0.3)
gen = add_ts(gen, "valid_from_date", 0.02)
gen = add_bool(gen, "is_active", 0.02)
gen = add_ts(gen, "created_at", 0.02)
gen = add_ts(gen, "updated_at", 0.02)
gen = add_hash(gen, "record_hash")
df = gen.build()
save_table(df, "dim_member_identifier")

# COMMAND ----------

# DBTITLE 1,dim_member_history
gen = dg.DataGenerator(spark, rows=500)
gen = gen.withColumn("mbr_history_sk", LongType(), values=list(range(500001, 500501)))
gen = gen.withColumn("member_sk", LongType(), baseColumn="mbr_history_sk", values=member_ids, random=True, percentNulls=0.03)
gen = add_member_profile_columns(gen, include_end_date=False, include_valid_dates=True)
df = gen.build()
save_table(df, "dim_member_history")

# COMMAND ----------

# DBTITLE 1,fact_claim_header
gen = dg.DataGenerator(spark, rows=500)
gen = gen.withColumn("clm_header_sk", LongType(), values=claim_header_sks)
gen = add_int(gen, "clm_id", 100000, 999999, 0.02)
gen = gen.withColumn("clm_claim_id", StringType(), values=claim_ids, percentNulls=0.0)
gen = add_str(gen, "clm_original_source_claim_id", nulls=0.08)
gen = add_str(gen, "clm_original_batch_nbr", nulls=0.08)
gen = add_str(gen, "clm_patient_control_nbr", nulls=0.1)
gen = add_str(gen, "clm_document_adj_control_nbr", nulls=0.15)
gen = add_str(gen, "clm_claim_type", claim_types, 0.03)
gen = add_str(gen, "clm_bill_type", ["111", "131", "137", "831", "851"], 0.08)
gen = add_str(gen, "clm_authorization_nbr", nulls=0.25)
gen = add_str(gen, "clm_ext_authorization_nbr", nulls=0.35)
gen = add_date(gen, "clm_admit_date", 0.2)
gen = add_date(gen, "clm_claim_thru_date", 0.05)
gen = add_date(gen, "clm_discharge_date", 0.25)
gen = add_int(gen, "clm_admission_hour", 0, 23, 0.25)
gen = add_int(gen, "clm_discharge_hour", 0, 23, 0.3)
gen = add_str(gen, "clm_admission_type", ["1", "2", "3", "4", "9"], 0.25)
gen = add_str(gen, "clm_admission_source", ["1", "2", "7", "8", "9"], 0.25)
gen = add_str(gen, "clm_member_nbr", nulls=0.03)
gen = add_str(gen, "clm_member_name", full_names, 0.03)
gen = gen.withColumn("clm_member_sk", LongType(), baseColumn="clm_header_sk", values=member_ids, random=True, percentNulls=0.03)
gen = add_str(gen, "clm_member_group_nbr", ["GRP100", "GRP200", "GRP300", "GRP400"], 0.05)
gen = add_str(gen, "clm_member_subgroup_nbr", ["SG100", "SG200", "SG300", "SG400"], 0.08)
gen = add_str(gen, "clm_plan_code", plan_values, 0.05)
gen = add_str(gen, "clm_line_of_business", lob_values, 0.04)
gen = add_dec(gen, "clm_birth_weight", 9, 2, 2.0, 15.0, 0.92)
gen = add_int(gen, "clm_covered_days", 0, 60, 0.12)
gen = add_str(gen, "clm_accident_st", states, 0.85)
gen = add_str(gen, "clm_attending_physician", full_names, 0.18)
gen = add_str(gen, "clm_attending_physician_spec", specialties, 0.18)
gen = add_str(gen, "clm_operating_provider_name", full_names, 0.45)
gen = gen.withColumn("clm_operating_provider_npi", StringType(), template=r'\\d\\d\\d\\d\\d\\d\\d\\d\\d\\d', random=True, percentNulls=0.45)
gen = add_str(gen, "clm_submitting_provider", full_names, 0.1)
gen = add_str(gen, "clm_submitting_provider_spec", specialties, 0.15)
gen = add_str(gen, "clm_submitting_provider_type", provider_types, 0.12)
gen = add_str(gen, "clm_billing_provider", full_names, 0.1)
gen = add_str(gen, "clm_referring_provider", full_names, 0.35)
gen = add_str(gen, "clm_referring_provider_spec", specialties, 0.4)
gen = add_str(gen, "clm_referring_provider_type", provider_types, 0.4)
gen = add_str(gen, "clm_is_par_submitting_provider", yes_no, 0.1)
gen = add_bool(gen, "clm_is_par_referring_provider", 0.25)
gen = add_bool(gen, "clm_is_par_rendering_provider", 0.15)
gen = add_str(gen, "clm_assigned_pcp", full_names, 0.25)
gen = add_str(gen, "clm_assigned_provider_site", ["SITE01", "SITE02", "SITE03", "SITE04"], 0.25)
gen = add_str(gen, "clm_insurance_id", nulls=0.06)
gen = add_str(gen, "clm_member_contract_id", nulls=0.08)
gen = add_int(gen, "clm_pcp_visit_flag", 0, 1, 0.1)
gen = add_str(gen, "clm_pcp_in_type", ["IN", "OUT", "N/A"], 0.18)
gen = add_dec(gen, "clm_pcp_wthld_pct", 9, 4, 0.0, 0.25, 0.25)
gen = gen.withColumn("clm_service_fac_npi", StringType(), template=r'\\d\\d\\d\\d\\d\\d\\d\\d\\d\\d', random=True, percentNulls=0.18)
gen = add_str(gen, "clm_service_fac_loc_name", ["North Clinic", "Central Hospital", "Valley Medical", "Premier Lab"], 0.18)
gen = gen.withColumn("clm_service_facility_address_sk", LongType(), baseColumn="clm_header_sk", values=address_ids, random=True, percentNulls=0.08)
gen = add_str(gen, "clm_providers_account_no", nulls=0.2)
gen = add_str(gen, "clm_onset_of_illness_date", nulls=0.3)
gen = add_str(gen, "clm_admitting_diagnosis_code", diagnosis_codes, 0.25)
gen = add_str(gen, "clm_admitting_diagnosis_method", ["ICD10", "ICD9"], 0.25)
for i in range(1, 26):
    gen = add_str(gen, f"clm_diagnosis_{i}", diagnosis_codes, 0.1 if i <= 3 else 0.45)
    gen = add_str(gen, f"clm_diagnosis_{i}_icd_method", ["ICD10", "ICD9"], 0.1 if i <= 3 else 0.45)
for i in range(1, 26):
    gen = add_str(gen, f"clm_diagnosis_{i}_poa", ["Y", "N", "U", "W"], 0.25 if i <= 3 else 0.55)
for i in range(1, 7):
    gen = add_str(gen, f"clm_surgical_{i}", procedure_codes, 0.5 if i == 1 else 0.75)
    gen = add_str(gen, f"clm_surgical_icd_method_{i}", ["ICD10", "ICD9"], 0.5 if i == 1 else 0.75)
gen = add_str(gen, "clm_drg_code", ["470", "871", "291", "392", "194", "603"], 0.35)
gen = add_str(gen, "clm_service_type_code", ["OFFICE", "INPATIENT", "OUTPATIENT", "ER", "LAB"], 0.08)
gen = add_str(gen, "clm_cob_type", ["PRIMARY", "SECONDARY", "NONE"], 0.25)
gen = add_str(gen, "clm_claim_timely_filing", yes_no, 0.12)
gen = add_str(gen, "clm_accept_assignment_indicator", yes_no, 0.12)
gen = add_date(gen, "clm_add_date", 0.05)
gen = add_str(gen, "clm_add_user", ["batch01", "batch02", "etl_user", "claims_ops"], 0.05)
gen = add_date(gen, "clm_update_date", 0.08)
gen = add_str(gen, "clm_update_user", ["batch01", "batch02", "etl_user", "claims_ops"], 0.08)
gen = add_ts(gen, "clm_extract_date", 0.05)
gen = add_date(gen, "clm_last_updated_date", 0.05)
gen = add_date(gen, "clm_original_insert_date", 0.05)
gen = add_str(gen, "clm_user_id", ["batch01", "batch02", "etl_user", "claims_ops"], 0.05)
gen = add_str(gen, "clm_orig_source", source_systems, 0.03)
gen = add_bool(gen, "is_active", 0.02)
gen = add_ts(gen, "end_date", 0.85)
gen = add_hash(gen, "record_hash")
gen = add_date(gen, "last_updated_date", 0.05)
gen = add_ts(gen, "created_at", 0.02)
gen = add_ts(gen, "updated_at", 0.02)
gen = add_str(gen, "source_system_code", source_systems, 0.02)
gen = add_str(gen, "source_system_name", source_names, 0.02)
df = gen.build()
save_table(df, "fact_claim_header")

# COMMAND ----------

# DBTITLE 1,fact_claim_detail
gen = dg.DataGenerator(spark, rows=5000)
gen = gen.withColumn("clm_dtl_claim_id", StringType(), values=detail_claim_ids, percentNulls=0.0)
gen = gen.withColumn("clm_dtl_line_nbr", StringType(), template=r'\\d\\d\\d', random=True, percentNulls=0.0)
gen = add_str(gen, "clm_dtl_original_source_claim_id", nulls=0.08)
gen = add_str(gen, "clm_dtl_source_system", source_systems, 0.03)
gen = add_str(gen, "clm_dtl_member_nbr_sk", nulls=0.05)
gen = add_ts(gen, "clmdetail_admit_dt", 0.4)
gen = add_date(gen, "clm_dtl_specific_dos_date", 0.05)
gen = add_date(gen, "clm_dtl_specific_dos_thru_date", 0.05)
gen = add_date(gen, "clm_dtl_ap_posting_date", 0.06)
gen = add_ts(gen, "clm_dtl_claim_receive_date", 0.05)
gen = add_ts(gen, "clm_dtl_check_date", 0.15)
gen = add_ts(gen, "clm_dtl_last_update_date", 0.05)
gen = add_str(gen, "clm_dtl_benefit_category", ["MEDICAL", "RX", "DENTAL", "VISION", "BEHAVIORAL"], 0.08)
gen = add_str(gen, "clm_dtl_benefit_level", ["IN", "OUT", "TIER1", "TIER2"], 0.1)
gen = add_str(gen, "clm_dtl_claim_type", claim_types, 0.03)
gen = add_dec(gen, "clm_dtl_allowed_amt", 28, 4, 0.0, 8000.0, 0.06)
gen = add_dec(gen, "clm_dtl_billed_amt", 27, 4, 0.0, 12000.0, 0.06)
gen = add_dec(gen, "clm_dtl_deduct_amt", 27, 4, 0.0, 1500.0, 0.12)
gen = add_dec(gen, "clm_dtl_net_amt", 28, 4, 0.0, 8000.0, 0.08)
gen = add_dec(gen, "clm_dtl_paid_amt", 28, 4, 0.0, 8000.0, 0.08)
gen = add_dec(gen, "clm_dtl_actual_paid_amt", 38, 4, 0.0, 8000.0, 0.08)
gen = add_dec(gen, "clm_dtl_not_covered_amt", 27, 4, 0.0, 2500.0, 0.15)
gen = add_dec(gen, "clm_dtl_co_insurance_amt", 27, 4, 0.0, 1500.0, 0.15)
gen = add_dec(gen, "clm_dtl_other_adjustments_amt", 30, 2, -500.0, 500.0, 0.2)
gen = add_dec(gen, "clm_dtl_cob_savings", 32, 4, 0.0, 2000.0, 0.3)
gen = add_dec(gen, "clm_dtl_oic_paid_amt", 19, 4, 0.0, 3000.0, 0.35)
gen = add_dec(gen, "clm_dtl_oic_allowed_amt", 19, 4, 0.0, 3000.0, 0.35)
gen = add_dec(gen, "clm_dtl_interest_amt", 38, 6, 0.0, 100.0, 0.75)
gen = add_dec(gen, "clm_dtl_prompt_pay_discount_amt", 20, 4, 0.0, 250.0, 0.8)
gen = add_dec(gen, "clm_dtl_interest_discount_amt", 38, 6, 0.0, 100.0, 0.85)
gen = add_str(gen, "clm_dtl_interest_discount_flag", yes_no, 0.75)
gen = add_dec(gen, "clm_dtl_copay_amt", 27, 4, 0.0, 250.0, 0.15)
gen = add_str(gen, "clm_dtl_copay_reason", ["OV", "ER", "RX", "WAIVED", "NONE"], 0.25)
gen = add_str(gen, "clm_dtl_sc_cd", ["A", "B", "C", "D"], 0.18)
gen = add_str(gen, "clm_dtl_reason_code_sk", ["R001", "R002", "R003", "R004", "R005"], 0.2)
gen = add_str(gen, "clm_dtl_line_status", status_values, 0.04)
gen = add_str(gen, "clm_dtl_clean_claim_ind", yes_no, 0.08)
gen = add_str(gen, "clm_dtl_place_of_service", ["11", "21", "22", "23", "24", "31"], 0.08)
gen = add_str(gen, "clm_dtl_fee_schedule_code", ["FS1", "FS2", "FS3", "FS4"], 0.25)
gen = add_str(gen, "clm_dtl_authorization_nbr", nulls=0.35)
gen = add_str(gen, "clm_dtl_check_nbr", nulls=0.18)
gen = add_str(gen, "clm_dtl_check_added_line_flag", yes_no, 0.2)
gen = add_str(gen, "clm_dtl_check_message", ["PAID", "DENIED", "PENDED", "ADJUSTED", "COB APPLIED"], 0.25)
gen = add_str(gen, "clm_dtl_submitting_provider", full_names, 0.12)
gen = add_str(gen, "clm_dtl_rendering_provider", full_names, 0.12)
gen = add_str(gen, "clm_dtl_rendering_provider_type", provider_types, 0.12)
gen = add_str(gen, "clm_dtl_rendering_provider_spec", specialties, 0.15)
gen = add_str(gen, "clm_dtl_participating_provider", yes_no, 0.12)
gen = add_str(gen, "clm_dtl_adjudication_status", status_values, 0.05)
gen = add_str(gen, "clm_dtl_procedure_code", procedure_codes, 0.08)
gen = add_str(gen, "clm_dtl_procedure_modifier", modifier_values, 0.35)
gen = add_str(gen, "clm_dtl_modifier_2", modifier_values, 0.6)
gen = add_str(gen, "clm_dtl_modifier_3", modifier_values, 0.75)
gen = add_str(gen, "clm_dtl_modifier_4", modifier_values, 0.85)
gen = add_str(gen, "clm_dtl_procedure_adj", ["NONE", "ADJ1", "ADJ2", "ADJ3"], 0.55)
gen = add_dec(gen, "clm_dtl_procedure_qty", 15, 3, 1.0, 20.0, 0.08)
gen = add_str(gen, "clm_dtl_revenue_code", ["0250", "0300", "0450", "0636", "0761"], 0.35)
gen = add_str(gen, "clm_dtl_diagnosis_ind_1", diagnosis_codes, 0.12)
gen = add_str(gen, "clm_dtl_diagnosis_ind_2", diagnosis_codes, 0.35)
gen = add_str(gen, "clm_dtl_diagnosis_ind_3", diagnosis_codes, 0.55)
gen = add_str(gen, "clm_dtl_diagnosis_ind_4", diagnosis_codes, 0.7)
gen = add_dec(gen, "clm_dtl_paid_days", 36, 3, 0.0, 60.0, 0.4)
gen = add_dec(gen, "clm_dtl_anesthesia_time_units", 12, 2, 0.0, 20.0, 0.75)
gen = add_str(gen, "clm_dtl_cob_rule", ["NONE", "COB1", "COB2", "MSP"], 0.45)
gen = add_str(gen, "clm_dtl_wrap_network", ["NONE", "WRAP1", "WRAP2"], 0.45)
gen = add_str(gen, "clm_dtl_returned_ntwrk_repric", yes_no, 0.55)
gen = add_str(gen, "clm_dtl_user_id", ["batch01", "batch02", "etl_user", "claims_ops"], 0.05)
gen = add_ts(gen, "clm_dtl_extract_date", 0.05)
gen = add_bool(gen, "is_active", 0.02)
gen = add_ts(gen, "updated_at", 0.02)
gen = add_ts(gen, "created_at", 0.02)
df = gen.build()
save_table(df, "fact_claim_detail")

# COMMAND ----------

# DBTITLE 1,fact_member_enrollment
gen = dg.DataGenerator(spark, rows=5000)
gen = gen.withColumn("enrollment_sk", StringType(), values=enrollment_ids, percentNulls=0.0)
gen = add_str(gen, "source_system", source_systems, 0.03)
gen = add_int(gen, "src_member_business_id", 100000, 999999, 0.05)
gen = add_str(gen, "mbr_enr_source_member_id", nulls=0.05)
gen = add_str(gen, "mbr_enr_insured_id", nulls=0.05)
gen = add_str(gen, "mbr_enr_contract_id", nulls=0.06)
gen = add_str(gen, "mbr_enr_insured_code", ["SUB", "DEP", "SPOUSE", "CHILD"], 0.08)
gen = add_ts(gen, "mbr_enr_insured_add_date", 0.06)
gen = add_ts(gen, "mbr_enr_insured_event_date", 0.08)
gen = add_str(gen, "mbr_enr_insured_event_id", nulls=0.12)
gen = add_str(gen, "mbr_enr_insured_event_code", ["ADD", "TERM", "CHANGE", "REINSTATE"], 0.1)
gen = add_str(gen, "mbr_enr_status", ["ACTIVE", "TERMINATED", "PENDING", "SUSPENDED"], 0.04)
gen = add_ts(gen, "mbr_enr_insured_event_add_date", 0.08)
gen = add_str(gen, "mbr_enr_plan_id", plan_values, 0.06)
gen = add_str(gen, "mbr_enr_line_of_business", lob_values, 0.04)
gen = add_str(gen, "mbr_enr_line_of_business_id", ["LOB1", "LOB2", "LOB3", "LOB4"], 0.05)
gen = add_str(gen, "mbr_enr_group_name", ["Acme Group", "Metro Schools", "State Employees", "Retail Workers"], 0.06)
gen = add_str(gen, "mbr_enr_subgroup_name", ["North Region", "South Region", "Hourly", "Salaried"], 0.08)
gen = add_date(gen, "mbr_enr_effective_date", 0.04)
gen = add_date(gen, "mbr_enr_termination_date", 0.35)
gen = add_date(gen, "mbr_enr_termination_event_date", 0.4)
gen = add_str(gen, "mbr_enr_termination_reason", ["VOLUNTARY", "NONPAYMENT", "GROUP TERM", "DECEASED", "OTHER"], 0.45)
gen = add_str(gen, "mbr_enr_product_id", ["PROD100", "PROD200", "PROD300", "PROD400"], 0.06)
gen = add_str(gen, "mbr_enr_group_ck", nulls=0.08)
gen = add_str(gen, "mbr_enr_group_code", ["GRP100", "GRP200", "GRP300", "GRP400"], 0.06)
gen = add_str(gen, "mbr_enr_subgroup_ck", nulls=0.1)
gen = add_str(gen, "mbr_enr_subgroup_code", ["SG100", "SG200", "SG300", "SG400"], 0.08)
gen = add_bool(gen, "is_active", 0.02)
gen = add_str(gen, "id_value", nulls=0.06)
gen = add_str(gen, "id_type", id_types, 0.06)
gen = gen.withColumn("member_sk", LongType(), baseColumn="enrollment_sk", values=member_ids, random=True, percentNulls=0.03)
gen = add_hash(gen, "payload_hash")
df = gen.build()
save_table(df, "fact_member_enrollment")

# COMMAND ----------

# DBTITLE 1,Completion
print("synthetic member claims data generation complete")
