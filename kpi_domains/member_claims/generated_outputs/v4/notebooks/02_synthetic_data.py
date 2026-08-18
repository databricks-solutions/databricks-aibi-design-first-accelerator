# Databricks notebook source
# DBTITLE 1,Synthetic Data — Member Claims
# Uses dbldatagen to generate realistic sample data for all tables.
# CRITICAL: All generated columns MUST match DDL types exactly.
# Use get_table_col_types() below to introspect actual DDL before generating.

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
    if colType == TimestampType() or colType is TimestampType or str(colType).lower() in ("timestamp", "timestamp_ntz"):
        for key in ("begin", "end"):
            if key in kwargs and isinstance(kwargs[key], str) and len(kwargs[key]) == 10:
                kwargs[key] = f"{kwargs[key]} 00:00:00" if key == "begin" else f"{kwargs[key]} 23:59:59"
    return _orig_withColumn(self, colName, colType, *args, **kwargs)
dg.DataGenerator.withColumn = _safe_withColumn

CATALOG = "aw_serverless_stable_catalog"
SCHEMA = "aibi_member_claims"
VERSION_SUFFIX = "_v4"
FULL_SCHEMA = f"`{CATALOG}`.`{SCHEMA}`"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {FULL_SCHEMA}")

member_keys = list(range(1, 501))
address_keys = list(range(1, 501))
claim_ids = [f"CLM{i:07d}" for i in range(1, 501)]

source_system_values = ["FACETS", "QNXT", "EPIC", "EDI", "CAREMGMT"]
state_values = ["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI", "AZ", "WA"]
city_values = ["Los Angeles", "Houston", "Miami", "New York", "Philadelphia", "Chicago", "Columbus", "Atlanta", "Charlotte", "Detroit", "Phoenix", "Seattle"]
county_values = ["Orange", "Harris", "Dade", "Kings", "Cook", "Franklin", "Fulton", "Mecklenburg", "Wayne", "Maricopa"]
lob_values = ["Commercial", "Medicare", "Medicaid", "Exchange", "TRICARE"]
yes_no_values = ["Y", "N"]
active_values = [True, False]
gender_values = ["F", "M", "U"]
race_values = ["White", "Black", "Asian", "Native American", "Pacific Islander", "Other", "Unknown"]
ethnicity_values = ["Hispanic", "Non-Hispanic", "Unknown"]
claim_type_values = ["Professional", "Institutional", "Dental", "Pharmacy"]
provider_type_values = ["PCP", "Specialist", "Facility", "Hospital", "Ancillary"]
status_values = ["Paid", "Denied", "Pended", "Adjusted"]
diagnosis_values = ["E119", "I10", "J45909", "M545", "N390", "R079", "Z0000", "K219", "F419", "G4700"]
procedure_values = ["99213", "99214", "99203", "93000", "80053", "85025", "97110", "70450", "36415", "J3490"]

def add_string(gen, name, values=None, template=None, percentNulls=0.05):
    if values is not None:
        return gen.withColumn(name, StringType(), values=values, random=True, percentNulls=percentNulls)
    if template is not None:
        return gen.withColumn(name, StringType(), template=template, percentNulls=percentNulls)
    return gen.withColumn(name, StringType(), template=r'\\w\\w\\w-\\d\\d\\d\\d', percentNulls=percentNulls)

def add_int(gen, name, minValue=1, maxValue=1000, percentNulls=0.05):
    return gen.withColumn(name, IntegerType(), minValue=minValue, maxValue=maxValue, random=True, percentNulls=percentNulls)

def add_bigint(gen, name, minValue=1, maxValue=1000, percentNulls=0.05):
    return gen.withColumn(name, LongType(), minValue=minValue, maxValue=maxValue, random=True, percentNulls=percentNulls)

def add_decimal(gen, name, precision, scale, minValue=0.0, maxValue=10000.0, percentNulls=0.05):
    return gen.withColumn(name, DecimalType(precision, scale), minValue=minValue, maxValue=maxValue, random=True, percentNulls=percentNulls)

def add_date(gen, name, begin="2020-01-01", end="2024-12-31", percentNulls=0.05):
    return gen.withColumn(name, DateType(), begin=begin, end=end, interval="1 day", random=True, percentNulls=percentNulls)

def add_timestamp(gen, name, begin="2020-01-01", end="2024-12-31", percentNulls=0.05):
    return gen.withColumn(name, TimestampType(), begin=begin, end=end, interval="1 day", random=True, percentNulls=percentNulls)

def add_bool(gen, name, percentNulls=0.05):
    return gen.withColumn(name, BooleanType(), values=active_values, random=True, percentNulls=percentNulls)

def write_delta(df, table_name):
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"`{CATALOG}`.`{SCHEMA}`.`{table_name}{VERSION_SUFFIX}`")
    print(f"Wrote {table_name}{VERSION_SUFFIX}")

member_attribute_specs = [("mbr_source_member_id", "string"), ("mbr_member_id", "int"), ("mbr_deers_beneficiary_id", "string"), ("mbr_deers_family_id", "string"), ("mbr_sponsor_ssn", "string"), ("mbr_current_pcp_eff_date", "date"), ("mbr_current_pcp_nbr", "string"), ("mbr_dob", "date"), ("mbr_race", "race"), ("mbr_sex", "sex"), ("mbr_ethnicity", "ethnicity"), ("mbr_first_name", "name"), ("mbr_middle_name", "name"), ("mbr_last_name", "name"), ("mbr_full_name", "name"), ("mbr_marital_status", "marital"), ("mbr_deceased_date", "date"), ("mbr_email", "email"), ("mbr_phone_nbr", "phone"), ("mbr_mobile_nbr", "phone"), ("mbr_work_nbr", "phone"), ("mbr_sub_group_cd", "string"), ("mbr_idcard_issue_date", "date"), ("mbr_line_of_business", "lob"), ("mbr_text_opt_in", "yesno"), ("mbr_current_riders", "string"), ("mbr_authorized_rep", "yesno"), ("mbr_alt_sub_nbr", "string"), ("mbr_relationship_type", "relationship"), ("mbr_salary_tier", "salary"), ("mbr_pcp_auto_assigned", "yesno"), ("mbr_secured_flag", "yesno"), ("mbr_pharmacy_discount_flag", "yesno"), ("mbr_employee_id", "string"), ("mbr_line_of_business_name", "lob"), ("mbr_responsible_party_id", "string"), ("mbr_responsible_party_name", "name"), ("mbr_deceased_flag", "yesno"), ("mbr_pcp_lock_in_indicator", "yesno"), ("mbr_alt_person_nbr", "string"), ("mbr_state", "state"), ("mbr_zip_code", "zip"), ("mbr_pcp_lock_in_type", "string"), ("mbr_provider_group_name", "provider_name"), ("mbr_name_suffix", "suffix"), ("mbr_sub_flag", "int_flag"), ("mbr_sub_ssn", "string"), ("mbr_extract_date", "date"), ("mbr_medicaid_case_nbr", "string"), ("mbr_relationship_ind", "relationship"), ("source_system_code", "source"), ("source_system_name", "source"), ("record_hash", "hash"), ("created_at", "timestamp"), ("updated_at", "timestamp"), ("is_active", "bool"), ("end_date", "timestamp")]

def add_member_attributes(gen, include_end_date=True):
    for name, kind in member_attribute_specs:
        if kind == "int":
            gen = add_int(gen, name, 100000, 999999)
        elif kind == "int_flag":
            gen = add_int(gen, name, 0, 1)
        elif kind == "date":
            gen = add_date(gen, name)
        elif kind == "timestamp":
            gen = add_timestamp(gen, name)
        elif kind == "bool":
            gen = add_bool(gen, name)
        elif kind == "race":
            gen = add_string(gen, name, values=race_values)
        elif kind == "sex":
            gen = add_string(gen, name, values=gender_values)
        elif kind == "ethnicity":
            gen = add_string(gen, name, values=ethnicity_values)
        elif kind == "lob":
            gen = add_string(gen, name, values=lob_values)
        elif kind == "yesno":
            gen = add_string(gen, name, values=yes_no_values)
        elif kind == "relationship":
            gen = add_string(gen, name, values=["Self", "Spouse", "Child", "Dependent", "Other"])
        elif kind == "salary":
            gen = add_string(gen, name, values=["Tier 1", "Tier 2", "Tier 3", "Tier 4"])
        elif kind == "state":
            gen = add_string(gen, name, values=state_values)
        elif kind == "zip":
            gen = add_string(gen, name, template=r'\\d\\d\\d\\d\\d')
        elif kind == "suffix":
            gen = add_string(gen, name, values=["Jr", "Sr", "II", "III", ""])
        elif kind == "source":
            gen = add_string(gen, name, values=source_system_values)
        elif kind == "hash":
            gen = add_string(gen, name, template=r'\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w')
        elif kind == "email":
            gen = add_string(gen, name, template=r'\\w\\w\\w\\w\\w\\w@example.com')
        elif kind == "phone":
            gen = add_string(gen, name, template=r'\\d\\d\\d-\\d\\d\\d-\\d\\d\\d\\d')
        elif kind == "provider_name":
            gen = add_string(gen, name, values=["Northside Medical Group", "Lakeside Health", "Valley Primary Care", "Metro Specialty Clinic", "Regional Health Partners"])
        elif kind == "name":
            gen = add_string(gen, name, values=["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Avery", "Jamie", "Cameron", "Drew"])
        else:
            gen = add_string(gen, name)
    return gen

# COMMAND ----------

# DBTITLE 1,Create dim_member
print("Generating dim_member")
gen = dg.DataGenerator(spark, rows=500, partitions=4).withColumn("member_sk", LongType(), minValue=1, maxValue=500, step=1)
gen = add_member_attributes(gen)
df = gen.build()
write_delta(df, "dim_member")

# COMMAND ----------

# DBTITLE 1,Create dim_address
print("Generating dim_address")
gen = dg.DataGenerator(spark, rows=500, partitions=4).withColumn("address_key", LongType(), minValue=1, maxValue=500, step=1)
gen = add_string(gen, "entity_type_key", values=["MEMBER", "PROVIDER", "FACILITY"])
gen = gen.withColumn("entity_dimension_key", LongType(), values=member_keys, random=True, percentNulls=0.02)
gen = add_string(gen, "address_type_code", values=["HOME", "MAILING", "BILLING", "SERVICE"])
gen = add_string(gen, "street_address_1", values=["100 Main St", "225 Oak Ave", "411 Pine Rd", "880 Market Blvd", "1200 Lake Dr", "77 Health Pkwy"])
gen = add_string(gen, "street_address_2", values=["Apt 1", "Suite 200", "Unit B", "Floor 3", ""])
gen = add_string(gen, "city", values=city_values)
gen = add_string(gen, "state", values=state_values)
gen = add_string(gen, "zip_code", template=r'\\d\\d\\d\\d\\d')
gen = add_string(gen, "country_code", values=["US"])
gen = add_string(gen, "county", values=county_values)
gen = add_bool(gen, "is_active")
gen = add_timestamp(gen, "valid_from_date")
gen = add_timestamp(gen, "valid_to_date")
gen = add_string(gen, "source_system_code", values=source_system_values)
gen = add_string(gen, "source_system_name", values=source_system_values)
gen = add_string(gen, "record_hash", template=r'\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w')
gen = add_timestamp(gen, "created_at")
gen = add_timestamp(gen, "updated_at")
df = gen.build()
write_delta(df, "dim_address")

# COMMAND ----------

# DBTITLE 1,Create dim_provider
print("Generating dim_provider")
gen = dg.DataGenerator(spark, rows=500, partitions=4).withColumn("provider_sk", LongType(), minValue=1, maxValue=500, step=1)
gen = gen.withColumn("assigned_provider_sk", LongType(), minValue=1, maxValue=500, random=True, percentNulls=0.10)
gen = add_string(gen, "source_provider_id")
gen = add_string(gen, "provider_npi", template=r'\\d\\d\\d\\d\\d\\d\\d\\d\\d\\d')
gen = add_string(gen, "provider_tax_id", template=r'\\d\\d-\\d\\d\\d\\d\\d\\d\\d')
gen = add_string(gen, "provider_name", values=["Northside Medical Group", "Lakeside Health", "Valley Primary Care", "Metro Specialty Clinic", "Regional Health Partners", "Summit Hospital"])
gen = gen.withColumn("provider_address_sk", LongType(), values=address_keys, random=True, percentNulls=0.02)
gen = add_bool(gen, "pcp_flag")
gen = add_string(gen, "affiliation_id")
gen = add_timestamp(gen, "valid_from_date")
gen = add_timestamp(gen, "valid_to_date")
gen = add_bool(gen, "is_active")
gen = add_string(gen, "source_system", values=source_system_values)
gen = add_timestamp(gen, "created_at")
gen = add_timestamp(gen, "updated_at")
gen = add_timestamp(gen, "last_update_dt")
gen = add_string(gen, "record_hash", template=r'\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w')
df = gen.build()
write_delta(df, "dim_provider")

# COMMAND ----------

# DBTITLE 1,Create dim_member_identifier
print("Generating dim_member_identifier")
gen = dg.DataGenerator(spark, rows=500, partitions=4).withColumn("mbr_identifier_sk", LongType(), minValue=1, maxValue=500, step=1)
gen = gen.withColumn("member_sk", LongType(), values=member_keys, random=True, percentNulls=0.02)
gen = add_string(gen, "id_type", values=["MEMBER_ID", "MEDICAID_ID", "MEDICARE_ID", "SSN_LAST4", "EXTERNAL_ID"])
gen = add_string(gen, "id_value", template=r'\\w\\w\\w-\\d\\d\\d\\d')
gen = add_string(gen, "source_system_code", values=source_system_values)
gen = add_string(gen, "source_system_name", values=source_system_values)
gen = add_timestamp(gen, "valid_to_date")
gen = add_timestamp(gen, "valid_from_date")
gen = add_bool(gen, "is_active")
gen = add_timestamp(gen, "created_at")
gen = add_timestamp(gen, "updated_at")
gen = add_string(gen, "record_hash", template=r'\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w')
df = gen.build()
write_delta(df, "dim_member_identifier")

# COMMAND ----------

# DBTITLE 1,Create dim_member_history
print("Generating dim_member_history")
gen = dg.DataGenerator(spark, rows=500, partitions=4).withColumn("mbr_history_sk", LongType(), minValue=1, maxValue=500, step=1)
gen = gen.withColumn("member_sk", LongType(), values=member_keys, random=True, percentNulls=0.02)
gen = add_member_attributes(gen)
gen = add_timestamp(gen, "valid_to_date")
gen = add_timestamp(gen, "valid_from_date")
df = gen.build()
write_delta(df, "dim_member_history")

# COMMAND ----------

# DBTITLE 1,Create fact_claim_header
print("Generating fact_claim_header")
gen = dg.DataGenerator(spark, rows=500, partitions=4).withColumn("clm_header_sk", LongType(), minValue=1, maxValue=500, step=1)
gen = add_int(gen, "clm_id", 100000, 999999)
gen = gen.withColumn("clm_claim_id", StringType(), values=claim_ids, random=False, percentNulls=0.0)
gen = add_string(gen, "clm_original_source_claim_id")
gen = add_string(gen, "clm_original_batch_nbr")
gen = add_string(gen, "clm_patient_control_nbr")
gen = add_string(gen, "clm_document_adj_control_nbr")
gen = add_string(gen, "clm_claim_type", values=claim_type_values)
gen = add_string(gen, "clm_bill_type", values=["111", "131", "137", "831", "851"])
gen = add_string(gen, "clm_authorization_nbr")
gen = add_string(gen, "clm_ext_authorization_nbr")
gen = add_date(gen, "clm_admit_date")
gen = add_date(gen, "clm_claim_thru_date")
gen = add_date(gen, "clm_discharge_date")
gen = add_int(gen, "clm_admission_hour", 0, 23)
gen = add_int(gen, "clm_discharge_hour", 0, 23)
gen = add_string(gen, "clm_admission_type", values=["Emergency", "Urgent", "Elective", "Newborn", "Trauma"])
gen = add_string(gen, "clm_admission_source", values=["Physician", "Clinic", "Transfer", "Emergency Room", "Other"])
gen = add_string(gen, "clm_member_nbr")
gen = add_string(gen, "clm_member_name", values=["Alex Smith", "Jordan Lee", "Taylor Brown", "Morgan Davis", "Casey Wilson", "Riley Miller"])
gen = gen.withColumn("clm_member_sk", LongType(), values=member_keys, random=True, percentNulls=0.02)
gen = add_string(gen, "clm_member_group_nbr")
gen = add_string(gen, "clm_member_subgroup_nbr")
gen = add_string(gen, "clm_plan_code", values=["PPO", "HMO", "EPO", "POS", "HDHP"])
gen = add_string(gen, "clm_line_of_business", values=lob_values)
gen = add_decimal(gen, "clm_birth_weight", 9, 2, 1.0, 15.0)
gen = add_int(gen, "clm_covered_days", 0, 30)
gen = add_string(gen, "clm_accident_st", values=state_values)
gen = add_string(gen, "clm_attending_physician", values=["Dr Adams", "Dr Baker", "Dr Clark", "Dr Evans", "Dr Patel"])
gen = add_string(gen, "clm_attending_physician_spec", values=["Family Medicine", "Cardiology", "Orthopedics", "Radiology", "Pediatrics"])
gen = add_string(gen, "clm_operating_provider_name", values=["Dr Adams", "Dr Baker", "Dr Clark", "Dr Evans", "Dr Patel"])
gen = add_string(gen, "clm_operating_provider_npi", template=r'\\d\\d\\d\\d\\d\\d\\d\\d\\d\\d')
gen = add_string(gen, "clm_submitting_provider", values=["Northside Medical Group", "Lakeside Health", "Valley Primary Care", "Metro Specialty Clinic"])
gen = add_string(gen, "clm_submitting_provider_spec", values=["Family Medicine", "Cardiology", "Orthopedics", "Radiology", "Pediatrics"])
gen = add_string(gen, "clm_submitting_provider_type", values=provider_type_values)
gen = add_string(gen, "clm_billing_provider", values=["Northside Medical Group", "Lakeside Health", "Valley Primary Care", "Metro Specialty Clinic"])
gen = add_string(gen, "clm_referring_provider", values=["Dr Adams", "Dr Baker", "Dr Clark", "Dr Evans", "Dr Patel"])
gen = add_string(gen, "clm_referring_provider_spec", values=["Family Medicine", "Cardiology", "Orthopedics", "Radiology", "Pediatrics"])
gen = add_string(gen, "clm_referring_provider_type", values=provider_type_values)
gen = add_string(gen, "clm_is_par_submitting_provider", values=yes_no_values)
gen = add_bool(gen, "clm_is_par_referring_provider")
gen = add_bool(gen, "clm_is_par_rendering_provider")
gen = add_string(gen, "clm_assigned_pcp", values=["Dr Adams", "Dr Baker", "Dr Clark", "Dr Evans", "Dr Patel"])
gen = add_string(gen, "clm_assigned_provider_site", values=["Main Clinic", "North Campus", "South Campus", "Downtown Office"])
gen = add_string(gen, "clm_insurance_id")
gen = add_string(gen, "clm_member_contract_id")
gen = add_int(gen, "clm_pcp_visit_flag", 0, 1)
gen = add_string(gen, "clm_pcp_in_type", values=["In Network", "Out of Network", "Unknown"])
gen = add_decimal(gen, "clm_pcp_wthld_pct", 9, 4, 0.0, 0.25)
gen = add_string(gen, "clm_service_fac_npi", template=r'\\d\\d\\d\\d\\d\\d\\d\\d\\d\\d')
gen = add_string(gen, "clm_service_fac_loc_name", values=["Summit Hospital", "Metro Imaging", "Valley Surgery Center", "Lakeside Lab", "Northside Clinic"])
gen = gen.withColumn("clm_service_facility_address_sk", LongType(), values=address_keys, random=True, percentNulls=0.02)
gen = add_string(gen, "clm_providers_account_no")
gen = add_string(gen, "clm_onset_of_illness_date")
gen = add_string(gen, "clm_admitting_diagnosis_code", values=diagnosis_values)
gen = add_string(gen, "clm_admitting_diagnosis_method", values=["ICD10", "ICD9"])
for i in range(1, 26):
    gen = add_string(gen, f"clm_diagnosis_{i}", values=diagnosis_values)
    gen = add_string(gen, f"clm_diagnosis_{i}_icd_method", values=["ICD10", "ICD9"])
for i in range(1, 26):
    gen = add_string(gen, f"clm_diagnosis_{i}_poa", values=["Y", "N", "U", "W"])
for i in range(1, 7):
    gen = add_string(gen, f"clm_surgical_{i}", values=["0DTJ0ZZ", "0FT44ZZ", "0WQF0ZZ", "3E0U33Z", "027034Z"])
    gen = add_string(gen, f"clm_surgical_icd_method_{i}", values=["ICD10", "ICD9"])
gen = add_string(gen, "clm_drg_code", values=["470", "871", "291", "392", "603", "190"])
gen = add_string(gen, "clm_service_type_code", values=["MED", "SURG", "ER", "LAB", "RAD"])
gen = add_string(gen, "clm_cob_type", values=["Primary", "Secondary", "None"])
gen = add_string(gen, "clm_claim_timely_filing", values=yes_no_values)
gen = add_string(gen, "clm_accept_assignment_indicator", values=yes_no_values)
gen = add_date(gen, "clm_add_date")
gen = add_string(gen, "clm_add_user", values=["svc_claims", "batch_user", "edi_loader", "audit_user"])
gen = add_date(gen, "clm_update_date")
gen = add_string(gen, "clm_update_user", values=["svc_claims", "batch_user", "edi_loader", "audit_user"])
gen = add_timestamp(gen, "clm_extract_date")
gen = add_date(gen, "clm_last_updated_date")
gen = add_date(gen, "clm_original_insert_date")
gen = add_string(gen, "clm_user_id", values=["svc_claims", "batch_user", "edi_loader", "audit_user"])
gen = add_string(gen, "clm_orig_source", values=source_system_values)
gen = add_bool(gen, "is_active")
gen = add_timestamp(gen, "end_date")
gen = add_string(gen, "record_hash", template=r'\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w')
gen = add_date(gen, "last_updated_date")
gen = add_timestamp(gen, "created_at")
gen = add_timestamp(gen, "updated_at")
gen = add_string(gen, "source_system_code", values=source_system_values)
gen = add_string(gen, "source_system_name", values=source_system_values)
df = gen.build()
write_delta(df, "fact_claim_header")

# COMMAND ----------

# DBTITLE 1,Create fact_claim_detail
print("Generating fact_claim_detail")
gen = dg.DataGenerator(spark, rows=5000, partitions=8).withColumn("clm_dtl_claim_id", StringType(), values=claim_ids, random=True, percentNulls=0.0)
gen = gen.withColumn("clm_dtl_line_nbr", StringType(), values=[str(i) for i in range(1, 11)], random=True, percentNulls=0.0)
gen = add_string(gen, "clm_dtl_original_source_claim_id")
gen = add_string(gen, "clm_dtl_source_system", values=source_system_values)
gen = add_string(gen, "clm_dtl_member_nbr_sk")
gen = add_timestamp(gen, "clmdetail_admit_dt")
gen = add_date(gen, "clm_dtl_specific_dos_date")
gen = add_date(gen, "clm_dtl_specific_dos_thru_date")
gen = add_date(gen, "clm_dtl_ap_posting_date")
gen = add_timestamp(gen, "clm_dtl_claim_receive_date")
gen = add_timestamp(gen, "clm_dtl_check_date")
gen = add_timestamp(gen, "clm_dtl_last_update_date")
gen = add_string(gen, "clm_dtl_benefit_category", values=["Medical", "Surgical", "Pharmacy", "Behavioral", "Dental"])
gen = add_string(gen, "clm_dtl_benefit_level", values=["In Network", "Out of Network", "Tier 1", "Tier 2"])
gen = add_string(gen, "clm_dtl_claim_type", values=claim_type_values)
gen = add_decimal(gen, "clm_dtl_allowed_amt", 28, 4, 0.0, 25000.0)
gen = add_decimal(gen, "clm_dtl_billed_amt", 27, 4, 0.0, 30000.0)
gen = add_decimal(gen, "clm_dtl_deduct_amt", 27, 4, 0.0, 5000.0)
gen = add_decimal(gen, "clm_dtl_net_amt", 28, 4, 0.0, 25000.0)
gen = add_decimal(gen, "clm_dtl_paid_amt", 28, 4, 0.0, 25000.0)
gen = add_decimal(gen, "clm_dtl_actual_paid_amt", 38, 4, 0.0, 25000.0)
gen = add_decimal(gen, "clm_dtl_not_covered_amt", 27, 4, 0.0, 10000.0)
gen = add_decimal(gen, "clm_dtl_co_insurance_amt", 27, 4, 0.0, 5000.0)
gen = add_decimal(gen, "clm_dtl_other_adjustments_amt", 30, 2, -2000.0, 2000.0)
gen = add_decimal(gen, "clm_dtl_cob_savings", 32, 4, 0.0, 10000.0)
gen = add_decimal(gen, "clm_dtl_oic_paid_amt", 19, 4, 0.0, 5000.0)
gen = add_decimal(gen, "clm_dtl_oic_allowed_amt", 19, 4, 0.0, 5000.0)
gen = add_decimal(gen, "clm_dtl_interest_amt", 38, 6, 0.0, 250.0)
gen = add_decimal(gen, "clm_dtl_prompt_pay_discount_amt", 20, 4, 0.0, 500.0)
gen = add_decimal(gen, "clm_dtl_interest_discount_amt", 38, 6, 0.0, 250.0)
gen = add_string(gen, "clm_dtl_interest_discount_flag", values=yes_no_values)
gen = add_decimal(gen, "clm_dtl_copay_amt", 27, 4, 0.0, 500.0)
gen = add_string(gen, "clm_dtl_copay_reason", values=["Office Visit", "Emergency", "Specialist", "Waived", "None"])
gen = add_string(gen, "clm_dtl_sc_cd", values=["01", "02", "03", "04", "05"])
gen = add_string(gen, "clm_dtl_reason_code_sk")
gen = add_string(gen, "clm_dtl_line_status", values=status_values)
gen = add_string(gen, "clm_dtl_clean_claim_ind", values=yes_no_values)
gen = add_string(gen, "clm_dtl_place_of_service", values=["11", "21", "22", "23", "24", "31", "81"])
gen = add_string(gen, "clm_dtl_fee_schedule_code", values=["FS1", "FS2", "MCR", "MCD", "COM"])
gen = add_string(gen, "clm_dtl_authorization_nbr")
gen = add_string(gen, "clm_dtl_check_nbr")
gen = add_string(gen, "clm_dtl_check_added_line_flag", values=yes_no_values)
gen = add_string(gen, "clm_dtl_check_message", values=["Processed", "Adjusted", "Reviewed", "Manual Review", "No Message"])
gen = add_string(gen, "clm_dtl_submitting_provider", values=["Northside Medical Group", "Lakeside Health", "Valley Primary Care", "Metro Specialty Clinic"])
gen = add_string(gen, "clm_dtl_rendering_provider", values=["Dr Adams", "Dr Baker", "Dr Clark", "Dr Evans", "Dr Patel"])
gen = add_string(gen, "clm_dtl_rendering_provider_type", values=provider_type_values)
gen = add_string(gen, "clm_dtl_rendering_provider_spec", values=["Family Medicine", "Cardiology", "Orthopedics", "Radiology", "Pediatrics"])
gen = add_string(gen, "clm_dtl_participating_provider", values=yes_no_values)
gen = add_string(gen, "clm_dtl_adjudication_status", values=status_values)
gen = add_string(gen, "clm_dtl_procedure_code", values=procedure_values)
gen = add_string(gen, "clm_dtl_procedure_modifier", values=["25", "59", "TC", "RT", "LT", ""])
gen = add_string(gen, "clm_dtl_modifier_2", values=["25", "59", "TC", "RT", "LT", ""])
gen = add_string(gen, "clm_dtl_modifier_3", values=["25", "59", "TC", "RT", "LT", ""])
gen = add_string(gen, "clm_dtl_modifier_4", values=["25", "59", "TC", "RT", "LT", ""])
gen = add_string(gen, "clm_dtl_procedure_adj", values=["A1", "B2", "C3", "D4", ""])
gen = add_decimal(gen, "clm_dtl_procedure_qty", 15, 3, 1.0, 20.0)
gen = add_string(gen, "clm_dtl_revenue_code", values=["0250", "0300", "0450", "0636", "0762"])
gen = add_string(gen, "clm_dtl_diagnosis_ind_1", values=diagnosis_values)
gen = add_string(gen, "clm_dtl_diagnosis_ind_2", values=diagnosis_values)
gen = add_string(gen, "clm_dtl_diagnosis_ind_3", values=diagnosis_values)
gen = add_string(gen, "clm_dtl_diagnosis_ind_4", values=diagnosis_values)
gen = add_decimal(gen, "clm_dtl_paid_days", 36, 3, 0.0, 30.0)
gen = add_decimal(gen, "clm_dtl_anesthesia_time_units", 12, 2, 0.0, 25.0)
gen = add_string(gen, "clm_dtl_cob_rule", values=["COB1", "COB2", "COB3", "NONE"])
gen = add_string(gen, "clm_dtl_wrap_network", values=yes_no_values)
gen = add_string(gen, "clm_dtl_returned_ntwrk_repric", values=yes_no_values)
gen = add_string(gen, "clm_dtl_user_id", values=["svc_claims", "batch_user", "edi_loader", "audit_user"])
gen = add_timestamp(gen, "clm_dtl_extract_date")
gen = add_bool(gen, "is_active")
gen = add_timestamp(gen, "updated_at")
gen = add_timestamp(gen, "created_at")
df = gen.build()
write_delta(df, "fact_claim_detail")

# COMMAND ----------

# DBTITLE 1,Create fact_member_enrollment
print("Generating fact_member_enrollment")
gen = dg.DataGenerator(spark, rows=5000, partitions=8)
gen = add_string(gen, "source_system", values=source_system_values)
gen = add_int(gen, "src_member_business_id", 100000, 999999)
gen = add_string(gen, "mbr_enr_source_member_id")
gen = add_string(gen, "mbr_enr_insured_id")
gen = add_string(gen, "mbr_enr_contract_id")
gen = add_string(gen, "mbr_enr_insured_code", values=["EMP", "DEP", "COB", "RET"])
gen = add_timestamp(gen, "mbr_enr_insured_add_date")
gen = add_timestamp(gen, "mbr_enr_insured_event_date")
gen = add_string(gen, "mbr_enr_insured_event_id")
gen = add_string(gen, "mbr_enr_insured_event_code", values=["ADD", "TERM", "CHANGE", "REINSTATE"])
gen = add_string(gen, "mbr_enr_status", values=["Active", "Terminated", "Pending", "Suspended"])
gen = add_timestamp(gen, "mbr_enr_insured_event_add_date")
gen = add_string(gen, "mbr_enr_plan_id", values=["PPO", "HMO", "EPO", "POS", "HDHP"])
gen = add_string(gen, "mbr_enr_line_of_business", values=lob_values)
gen = add_string(gen, "mbr_enr_line_of_business_id")
gen = add_string(gen, "mbr_enr_group_name", values=["Acme Corp", "Metro Schools", "State Employees", "Health Exchange", "Retiree Group"])
gen = add_string(gen, "mbr_enr_subgroup_name", values=["North", "South", "Union", "Non Union", "Executive"])
gen = add_date(gen, "mbr_enr_effective_date")
gen = add_date(gen, "mbr_enr_termination_date")
gen = add_date(gen, "mbr_enr_termination_event_date")
gen = add_string(gen, "mbr_enr_termination_reason", values=["Voluntary", "Non Payment", "Ineligible", "Deceased", "Other"])
gen = add_string(gen, "mbr_enr_product_id", values=["MED", "DEN", "VIS", "RX"])
gen = add_string(gen, "mbr_enr_group_ck")
gen = add_string(gen, "mbr_enr_group_code")
gen = add_string(gen, "mbr_enr_subgroup_ck")
gen = add_string(gen, "mbr_enr_subgroup_code")
gen = add_bool(gen, "is_active")
gen = add_string(gen, "id_value", template=r'\\w\\w\\w-\\d\\d\\d\\d')
gen = add_string(gen, "id_type", values=["MEMBER_ID", "MEDICAID_ID", "MEDICARE_ID", "EXTERNAL_ID"])
gen = gen.withColumn("member_sk", LongType(), values=member_keys, random=True, percentNulls=0.02)
gen = add_string(gen, "enrollment_sk")
gen = add_string(gen, "payload_hash", template=r'\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w')
df = gen.build()
write_delta(df, "fact_member_enrollment")

# COMMAND ----------

# DBTITLE 1,Summary
print("Synthetic data generation complete")
print("Generated exactly 8 tables with _v4 suffix")
