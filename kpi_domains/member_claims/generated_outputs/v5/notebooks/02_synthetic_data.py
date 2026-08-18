# Databricks notebook source
# DBTITLE 1,Synthetic Data — Member Claims
# Uses dbldatagen to generate realistic sample data for all requested tables.
# CRITICAL: All generated columns match the ERD column names and Spark SQL data types.

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
VERSION_SUFFIX = "_v5"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`")

member_ids = list(range(1, 501))
address_ids = list(range(1, 501))
claim_ids = [f"CLM-{i:07d}" for i in range(1, 501)]

states = ["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI", "AZ", "WA", "CO", "VA", "MA"]
cities = ["Los Angeles", "Houston", "Miami", "New York", "Philadelphia", "Chicago", "Columbus", "Atlanta", "Charlotte", "Detroit", "Phoenix", "Seattle", "Denver", "Richmond", "Boston"]
zips = ["90001", "77001", "33101", "10001", "19101", "60601", "43215", "30301", "28201", "48201", "85001", "98101", "80201", "23218", "02108"]
source_systems = ["FACETS", "QNXT", "EPIC", "LEGACY", "EDI"]
lob_values = ["COMMERCIAL", "MEDICARE", "MEDICAID", "EXCHANGE", "TRICARE"]
yn_values = ["Y", "N"]
claim_types = ["PROFESSIONAL", "INSTITUTIONAL", "PHARMACY", "DENTAL", "VISION"]
status_values = ["ACTIVE", "PENDED", "PAID", "DENIED", "VOID"]
benefit_categories = ["MEDICAL", "SURGICAL", "RX", "BEHAVIORAL", "PREVENTIVE"]
provider_specs = ["PRIMARY CARE", "CARDIOLOGY", "ORTHOPEDICS", "PEDIATRICS", "RADIOLOGY", "ANESTHESIA"]
id_types = ["MEMBER_ID", "INSURED_ID", "SSN", "ALT_ID", "MEDICAID_ID"]

def table_name(logical_name):
    return f"`{CATALOG}`.`{SCHEMA}`.`{logical_name}{VERSION_SUFFIX}`"

def spark_type(type_name):
    if type_name == "bigint":
        return LongType()
    if type_name == "int":
        return IntegerType()
    if type_name == "string":
        return StringType()
    if type_name == "date":
        return DateType()
    if type_name == "timestamp":
        return TimestampType()
    if type_name == "boolean":
        return BooleanType()
    if type_name == "decimal":
        return DecimalType(18, 2)
    return StringType()

def add_col(gen, name, type_name, nullable=True, minValue=None, maxValue=None, step=None, random=True, values=None, weights=None, template=None, begin=None, end=None, interval=None, uniqueValues=None, baseColumn=None, percentNulls=0.1):
    kwargs = {}
    if minValue is not None:
        kwargs["minValue"] = minValue
    if maxValue is not None:
        kwargs["maxValue"] = maxValue
    if step is not None:
        kwargs["step"] = step
    if random is not None:
        kwargs["random"] = random
    if values is not None:
        kwargs["values"] = values
    if weights is not None:
        kwargs["weights"] = weights
    if template is not None:
        kwargs["template"] = template
    if begin is not None:
        kwargs["begin"] = begin
    if end is not None:
        kwargs["end"] = end
    if interval is not None:
        kwargs["interval"] = interval
    if uniqueValues is not None:
        kwargs["uniqueValues"] = uniqueValues
    if baseColumn is not None:
        kwargs["baseColumn"] = baseColumn
    if nullable:
        kwargs["percentNulls"] = percentNulls
    return gen.withColumn(name, spark_type(type_name), **kwargs)

def add_standard_col(gen, name, type_name, nullable=True):
    lname = name.lower()
    if type_name == "bigint":
        return add_col(gen, name, type_name, nullable, minValue=1, maxValue=100000, random=True)
    if type_name == "int":
        if "hour" in lname:
            return add_col(gen, name, type_name, nullable, minValue=0, maxValue=23, random=True)
        if "flag" in lname:
            return add_col(gen, name, type_name, nullable, values=[0, 1], random=True)
        return add_col(gen, name, type_name, nullable, minValue=1, maxValue=999999, random=True)
    if type_name == "decimal":
        if "pct" in lname:
            return add_col(gen, name, type_name, nullable, minValue=0.00, maxValue=1.00, random=True)
        if "qty" in lname or "days" in lname or "units" in lname:
            return add_col(gen, name, type_name, nullable, minValue=0.00, maxValue=30.00, random=True)
        if "weight" in lname:
            return add_col(gen, name, type_name, nullable, minValue=500.00, maxValue=5000.00, random=True)
        return add_col(gen, name, type_name, nullable, minValue=0.00, maxValue=5000.00, random=True)
    if type_name == "date":
        return add_col(gen, name, type_name, nullable, begin="2020-01-01", end="2024-12-31", interval="1 day", random=True)
    if type_name == "timestamp":
        return add_col(gen, name, type_name, nullable, begin="2020-01-01 00:00:00", end="2024-12-31 23:59:59", interval="1 day", random=True)
    if type_name == "boolean":
        return add_col(gen, name, type_name, nullable, values=[True, False], weights=[8, 2], random=True)
    if "state" in lname or lname.endswith("_st"):
        return add_col(gen, name, type_name, nullable, values=states, random=True)
    if "city" in lname:
        return add_col(gen, name, type_name, nullable, values=cities, random=True)
    if "zip" in lname:
        return add_col(gen, name, type_name, nullable, values=zips, random=True)
    if "country" in lname:
        return add_col(gen, name, type_name, nullable, values=["US"], random=True)
    if "email" in lname:
        return add_col(gen, name, type_name, nullable, template=r'\\w\\w\\w\\w\\w@example.com', random=True)
    if "phone" in lname or lname.endswith("_nbr") or lname.endswith("_no"):
        return add_col(gen, name, type_name, nullable, template=r'\\d\\d\\d-\\d\\d\\d-\\d\\d\\d\\d', random=True)
    if "npi" in lname:
        return add_col(gen, name, type_name, nullable, template=r'\\d\\d\\d\\d\\d\\d\\d\\d\\d\\d', random=True)
    if "tax_id" in lname:
        return add_col(gen, name, type_name, nullable, template=r'\\d\\d-\\d\\d\\d\\d\\d\\d\\d', random=True)
    if "ssn" in lname:
        return add_col(gen, name, type_name, nullable, template=r'\\d\\d\\d-\\d\\d-\\d\\d\\d\\d', random=True)
    if "sex" in lname:
        return add_col(gen, name, type_name, nullable, values=["F", "M", "U"], weights=[49, 49, 2], random=True)
    if "race" in lname:
        return add_col(gen, name, type_name, nullable, values=["White", "Black", "Asian", "Native American", "Pacific Islander", "Other", "Unknown"], random=True)
    if "ethnicity" in lname:
        return add_col(gen, name, type_name, nullable, values=["Hispanic", "Non-Hispanic", "Unknown"], random=True)
    if "marital" in lname:
        return add_col(gen, name, type_name, nullable, values=["S", "M", "D", "W", "U"], random=True)
    if "line_of_business" in lname or "lob" in lname:
        return add_col(gen, name, type_name, nullable, values=lob_values, random=True)
    if "claim_type" in lname:
        return add_col(gen, name, type_name, nullable, values=claim_types, random=True)
    if "status" in lname:
        return add_col(gen, name, type_name, nullable, values=status_values, random=True)
    if "benefit_category" in lname:
        return add_col(gen, name, type_name, nullable, values=benefit_categories, random=True)
    if "benefit_level" in lname:
        return add_col(gen, name, type_name, nullable, values=["IN_NETWORK", "OUT_OF_NETWORK", "TIER_1", "TIER_2"], random=True)
    if "provider_spec" in lname or "physician_spec" in lname or "rendering_provider_spec" in lname:
        return add_col(gen, name, type_name, nullable, values=provider_specs, random=True)
    if "provider_type" in lname:
        return add_col(gen, name, type_name, nullable, values=["INDIVIDUAL", "GROUP", "FACILITY"], random=True)
    if "source_system" in lname or lname == "source_system":
        return add_col(gen, name, type_name, nullable, values=source_systems, random=True)
    if "source_system_code" in lname:
        return add_col(gen, name, type_name, nullable, values=["FAC", "QNX", "EPC", "LEG", "EDI"], random=True)
    if "source_system_name" in lname:
        return add_col(gen, name, type_name, nullable, values=source_systems, random=True)
    if "hash" in lname:
        return add_col(gen, name, type_name, nullable, template=r'\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w\\w', random=True)
    if "flag" in lname or "indicator" in lname or lname.endswith("_ind"):
        return add_col(gen, name, type_name, nullable, values=yn_values, random=True)
    if "first_name" in lname:
        return add_col(gen, name, type_name, nullable, values=["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "William", "Elizabeth"], random=True)
    if "middle_name" in lname:
        return add_col(gen, name, type_name, nullable, values=["A", "B", "C", "D", "E", "F", "G", "H"], random=True)
    if "last_name" in lname:
        return add_col(gen, name, type_name, nullable, values=["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"], random=True)
    if "full_name" in lname or lname.endswith("_name") or "provider_name" in lname:
        return add_col(gen, name, type_name, nullable, values=["James Smith", "Mary Johnson", "Robert Williams", "Patricia Brown", "John Jones", "Jennifer Garcia", "Michael Miller", "Linda Davis"], random=True)
    if "diagnosis" in lname:
        return add_col(gen, name, type_name, nullable, values=["E119", "I10", "J45909", "M545", "N390", "R079", "Z0000", "K219"], random=True)
    if "procedure" in lname or "surgical" in lname:
        return add_col(gen, name, type_name, nullable, values=["99213", "99214", "93000", "80053", "36415", "71046", "97110"], random=True)
    if "icd_method" in lname or "method" in lname:
        return add_col(gen, name, type_name, nullable, values=["ICD10", "ICD9", "CPT", "HCPCS"], random=True)
    if "poa" in lname:
        return add_col(gen, name, type_name, nullable, values=["Y", "N", "U", "W"], random=True)
    if "id_type" == lname:
        return add_col(gen, name, type_name, nullable, values=id_types, random=True)
    if lname.endswith("_id") or "_id" in lname or lname.endswith("_sk") or "_sk" in lname:
        return add_col(gen, name, type_name, nullable, template=r'\\w\\w\\w-\\d\\d\\d\\d', random=True)
    if "code" in lname or lname.endswith("_cd"):
        return add_col(gen, name, type_name, nullable, template=r'\\w\\w\\d\\d', random=True)
    return add_col(gen, name, type_name, nullable, template=r'\\w\\w\\w-\\d\\d\\d\\d', random=True)

def write_delta(df, logical_name):
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table_name(logical_name))
    print(f"Wrote {logical_name}{VERSION_SUFFIX}")

member_profile_cols = [("mbr_source_member_id", "string"), ("mbr_member_id", "int"), ("mbr_deers_beneficiary_id", "string"), ("mbr_deers_family_id", "string"), ("mbr_sponsor_ssn", "string"), ("mbr_current_pcp_eff_date", "date"), ("mbr_current_pcp_nbr", "string"), ("mbr_dob", "date"), ("mbr_race", "string"), ("mbr_sex", "string"), ("mbr_ethnicity", "string"), ("mbr_first_name", "string"), ("mbr_middle_name", "string"), ("mbr_last_name", "string"), ("mbr_full_name", "string"), ("mbr_marital_status", "string"), ("mbr_deceased_date", "date"), ("mbr_email", "string"), ("mbr_phone_nbr", "string"), ("mbr_mobile_nbr", "string"), ("mbr_work_nbr", "string"), ("mbr_sub_group_cd", "string"), ("mbr_idcard_issue_date", "date"), ("mbr_line_of_business", "string"), ("mbr_text_opt_in", "string"), ("mbr_current_riders", "string"), ("mbr_authorized_rep", "string"), ("mbr_alt_sub_nbr", "string"), ("mbr_relationship_type", "string"), ("mbr_salary_tier", "string"), ("mbr_pcp_auto_assigned", "string"), ("mbr_secured_flag", "string"), ("mbr_pharmacy_discount_flag", "string"), ("mbr_employee_id", "string"), ("mbr_line_of_business_name", "string"), ("mbr_responsible_party_id", "string"), ("mbr_responsible_party_name", "string"), ("mbr_deceased_flag", "string"), ("mbr_pcp_lock_in_indicator", "string"), ("mbr_alt_person_nbr", "string"), ("mbr_state", "string"), ("mbr_zip_code", "string"), ("mbr_pcp_lock_in_type", "string"), ("mbr_provider_group_name", "string"), ("mbr_name_suffix", "string"), ("mbr_sub_flag", "int"), ("mbr_sub_ssn", "string"), ("mbr_extract_date", "date"), ("mbr_medicaid_case_nbr", "string"), ("mbr_relationship_ind", "string"), ("source_system_code", "string"), ("source_system_name", "string"), ("record_hash", "string"), ("created_at", "timestamp"), ("updated_at", "timestamp"), ("is_active", "boolean")]

# COMMAND ----------

# DBTITLE 1,dim_member
gen = dg.DataGenerator(spark, rows=500)
gen = add_col(gen, "member_sk", "bigint", nullable=False, minValue=1, maxValue=500, step=1, random=False)
for col_name, col_type in member_profile_cols:
    gen = add_standard_col(gen, col_name, col_type, nullable=True)
gen = add_standard_col(gen, "end_date", "timestamp", nullable=True)
df = gen.build()
write_delta(df, "dim_member")

# COMMAND ----------

# DBTITLE 1,dim_address
gen = dg.DataGenerator(spark, rows=500)
gen = add_col(gen, "address_key", "bigint", nullable=False, minValue=1, maxValue=500, step=1, random=False)
gen = add_col(gen, "entity_type_key", "string", nullable=True, values=["MEMBER"], random=True)
gen = add_col(gen, "entity_dimension_key", "bigint", nullable=True, values=member_ids, random=True, baseColumn="address_key", percentNulls=0.02)
gen = add_col(gen, "address_type_code", "string", nullable=True, values=["HOME", "MAILING", "BILLING", "SERVICE"], random=True)
gen = add_col(gen, "street_address_1", "string", nullable=True, template=r'\\d\\d\\d Main St', random=True)
gen = add_col(gen, "street_address_2", "string", nullable=True, values=["Apt 1", "Apt 2", "Suite 100", "Unit B", "Floor 3"], random=True, percentNulls=0.4)
gen = add_standard_col(gen, "city", "string", nullable=True)
gen = add_standard_col(gen, "state", "string", nullable=True)
gen = add_standard_col(gen, "zip_code", "string", nullable=True)
gen = add_standard_col(gen, "country_code", "string", nullable=True)
gen = add_col(gen, "county", "string", nullable=True, values=["Los Angeles", "Harris", "Miami-Dade", "New York", "Cook", "Maricopa"], random=True)
gen = add_standard_col(gen, "is_active", "boolean", nullable=True)
gen = add_standard_col(gen, "valid_from_date", "timestamp", nullable=True)
gen = add_standard_col(gen, "valid_to_date", "timestamp", nullable=True)
gen = add_standard_col(gen, "source_system_code", "string", nullable=True)
gen = add_standard_col(gen, "source_system_name", "string", nullable=True)
gen = add_standard_col(gen, "record_hash", "string", nullable=True)
gen = add_standard_col(gen, "created_at", "timestamp", nullable=True)
gen = add_standard_col(gen, "updated_at", "timestamp", nullable=True)
df = gen.build()
write_delta(df, "dim_address")

# COMMAND ----------

# DBTITLE 1,dim_provider
gen = dg.DataGenerator(spark, rows=500)
gen = add_col(gen, "provider_sk", "bigint", nullable=False, minValue=1, maxValue=500, step=1, random=False)
gen = add_col(gen, "assigned_provider_sk", "bigint", nullable=True, minValue=1, maxValue=500, random=True)
gen = add_standard_col(gen, "source_provider_id", "string", nullable=True)
gen = add_standard_col(gen, "provider_npi", "string", nullable=True)
gen = add_standard_col(gen, "provider_tax_id", "string", nullable=True)
gen = add_col(gen, "provider_name", "string", nullable=True, values=["Northside Clinic", "Valley Medical Group", "Lakeside Pediatrics", "Metro Health Partners", "Summit Specialty Care", "Evergreen Family Practice"], random=True)
gen = add_col(gen, "provider_address_sk", "bigint", nullable=True, values=address_ids, random=True, baseColumn="provider_sk", percentNulls=0.02)
gen = add_standard_col(gen, "pcp_flag", "boolean", nullable=True)
gen = add_standard_col(gen, "affiliation_id", "string", nullable=True)
gen = add_standard_col(gen, "valid_from_date", "timestamp", nullable=True)
gen = add_standard_col(gen, "valid_to_date", "timestamp", nullable=True)
gen = add_standard_col(gen, "is_active", "boolean", nullable=True)
gen = add_standard_col(gen, "source_system", "string", nullable=True)
gen = add_standard_col(gen, "created_at", "timestamp", nullable=True)
gen = add_standard_col(gen, "updated_at", "timestamp", nullable=True)
gen = add_standard_col(gen, "last_update_dt", "timestamp", nullable=True)
gen = add_standard_col(gen, "record_hash", "string", nullable=True)
df = gen.build()
write_delta(df, "dim_provider")

# COMMAND ----------

# DBTITLE 1,dim_member_identifier
gen = dg.DataGenerator(spark, rows=500)
gen = add_col(gen, "mbr_identifier_sk", "bigint", nullable=False, minValue=1, maxValue=500, step=1, random=False)
gen = add_col(gen, "member_sk", "bigint", nullable=True, values=member_ids, random=True, baseColumn="mbr_identifier_sk", percentNulls=0.02)
gen = add_col(gen, "id_type", "string", nullable=True, values=id_types, random=True)
gen = add_col(gen, "id_value", "string", nullable=True, template=r'\\w\\w\\w-\\d\\d\\d\\d', random=True)
gen = add_standard_col(gen, "source_system_code", "string", nullable=True)
gen = add_standard_col(gen, "source_system_name", "string", nullable=True)
gen = add_standard_col(gen, "valid_to_date", "timestamp", nullable=True)
gen = add_standard_col(gen, "valid_from_date", "timestamp", nullable=True)
gen = add_standard_col(gen, "is_active", "boolean", nullable=True)
gen = add_standard_col(gen, "created_at", "timestamp", nullable=True)
gen = add_standard_col(gen, "updated_at", "timestamp", nullable=True)
gen = add_standard_col(gen, "record_hash", "string", nullable=True)
df = gen.build()
write_delta(df, "dim_member_identifier")

# COMMAND ----------

# DBTITLE 1,dim_member_history
gen = dg.DataGenerator(spark, rows=500)
gen = add_col(gen, "mbr_history_sk", "bigint", nullable=False, minValue=1, maxValue=500, step=1, random=False)
gen = add_col(gen, "member_sk", "bigint", nullable=True, values=member_ids, random=True, baseColumn="mbr_history_sk", percentNulls=0.02)
for col_name, col_type in member_profile_cols:
    gen = add_standard_col(gen, col_name, col_type, nullable=True)
gen = add_standard_col(gen, "valid_to_date", "timestamp", nullable=True)
gen = add_standard_col(gen, "valid_from_date", "timestamp", nullable=True)
df = gen.build()
write_delta(df, "dim_member_history")

# COMMAND ----------

# DBTITLE 1,fact_claim_header
gen = dg.DataGenerator(spark, rows=500)
gen = add_col(gen, "clm_header_sk", "bigint", nullable=False, minValue=1, maxValue=500, step=1, random=False)
gen = add_standard_col(gen, "clm_id", "int", nullable=True)
gen = add_col(gen, "clm_claim_id", "string", nullable=True, values=claim_ids, random=False, percentNulls=0.0)
header_before_diag = [("clm_original_source_claim_id", "string"), ("clm_original_batch_nbr", "string"), ("clm_patient_control_nbr", "string"), ("clm_document_adj_control_nbr", "string"), ("clm_claim_type", "string"), ("clm_bill_type", "string"), ("clm_authorization_nbr", "string"), ("clm_ext_authorization_nbr", "string"), ("clm_admit_date", "date"), ("clm_claim_thru_date", "date"), ("clm_discharge_date", "date"), ("clm_admission_hour", "int"), ("clm_discharge_hour", "int"), ("clm_admission_type", "string"), ("clm_admission_source", "string"), ("clm_member_nbr", "string"), ("clm_member_name", "string")]
for col_name, col_type in header_before_diag:
    gen = add_standard_col(gen, col_name, col_type, nullable=True)
gen = add_col(gen, "clm_member_sk", "bigint", nullable=True, values=member_ids, random=True, baseColumn="clm_header_sk", percentNulls=0.02)
header_mid_cols = [("clm_member_group_nbr", "string"), ("clm_member_subgroup_nbr", "string"), ("clm_plan_code", "string"), ("clm_line_of_business", "string"), ("clm_birth_weight", "decimal"), ("clm_covered_days", "int"), ("clm_accident_st", "string"), ("clm_attending_physician", "string"), ("clm_attending_physician_spec", "string"), ("clm_operating_provider_name", "string"), ("clm_operating_provider_npi", "string"), ("clm_submitting_provider", "string"), ("clm_submitting_provider_spec", "string"), ("clm_submitting_provider_type", "string"), ("clm_billing_provider", "string"), ("clm_referring_provider", "string"), ("clm_referring_provider_spec", "string"), ("clm_referring_provider_type", "string"), ("clm_is_par_submitting_provider", "string"), ("clm_is_par_referring_provider", "boolean"), ("clm_is_par_rendering_provider", "boolean"), ("clm_assigned_pcp", "string"), ("clm_assigned_provider_site", "string"), ("clm_insurance_id", "string"), ("clm_member_contract_id", "string"), ("clm_pcp_visit_flag", "int"), ("clm_pcp_in_type", "string"), ("clm_pcp_wthld_pct", "decimal"), ("clm_service_fac_npi", "string"), ("clm_service_fac_loc_name", "string")]
for col_name, col_type in header_mid_cols:
    gen = add_standard_col(gen, col_name, col_type, nullable=True)
gen = add_col(gen, "clm_service_facility_address_sk", "bigint", nullable=True, values=address_ids, random=True, baseColumn="clm_header_sk", percentNulls=0.02)
header_after_fk = [("clm_providers_account_no", "string"), ("clm_onset_of_illness_date", "string"), ("clm_admitting_diagnosis_code", "string"), ("clm_admitting_diagnosis_method", "string")]
for col_name, col_type in header_after_fk:
    gen = add_standard_col(gen, col_name, col_type, nullable=True)
for i in range(1, 26):
    gen = add_standard_col(gen, f"clm_diagnosis_{i}", "string", nullable=True)
    gen = add_standard_col(gen, f"clm_diagnosis_{i}_icd_method", "string", nullable=True)
for i in range(1, 26):
    gen = add_standard_col(gen, f"clm_diagnosis_{i}_poa", "string", nullable=True)
for i in range(1, 7):
    gen = add_standard_col(gen, f"clm_surgical_{i}", "string", nullable=True)
    gen = add_standard_col(gen, f"clm_surgical_icd_method_{i}", "string", nullable=True)
header_tail_cols = [("clm_drg_code", "string"), ("clm_service_type_code", "string"), ("clm_cob_type", "string"), ("clm_claim_timely_filing", "string"), ("clm_accept_assignment_indicator", "string"), ("clm_add_date", "date"), ("clm_add_user", "string"), ("clm_update_date", "date"), ("clm_update_user", "string"), ("clm_extract_date", "timestamp"), ("clm_last_updated_date", "date"), ("clm_original_insert_date", "date"), ("clm_user_id", "string"), ("clm_orig_source", "string"), ("is_active", "boolean"), ("end_date", "timestamp"), ("record_hash", "string"), ("last_updated_date", "date"), ("created_at", "timestamp"), ("updated_at", "timestamp"), ("source_system_code", "string"), ("source_system_name", "string")]
for col_name, col_type in header_tail_cols:
    gen = add_standard_col(gen, col_name, col_type, nullable=True)
df = gen.build()
write_delta(df, "fact_claim_header")

# COMMAND ----------

# DBTITLE 1,fact_claim_detail
gen = dg.DataGenerator(spark, rows=5000)
gen = add_col(gen, "clm_dtl_claim_id", "string", nullable=False, values=claim_ids, random=True)
gen = add_col(gen, "clm_dtl_line_nbr", "string", nullable=False, values=[str(i) for i in range(1, 51)], random=True)
detail_pre_amount_cols = [("clm_dtl_original_source_claim_id", "string"), ("clm_dtl_source_system", "string"), ("clm_dtl_member_nbr_sk", "string"), ("clmedetail_admit_dt", "timestamp"), ("clm_dtl_specific_dos_date", "date"), ("clm_dtl_specific_dos_thru_date", "date"), ("clm_dtl_ap_posting_date", "date"), ("clm_dtl_claim_receive_date", "timestamp"), ("clm_dtl_check_date", "timestamp"), ("clm_dtl_last_update_date", "timestamp"), ("clm_dtl_benefit_category", "string"), ("clm_dtl_benefit_level", "string"), ("clm_dtl_claim_type", "string")]
for col_name, col_type in detail_pre_amount_cols:
    gen = add_standard_col(gen, col_name, col_type, nullable=True)
detail_amount_cols = ["clm_dtl_allowed_amt", "clm_dtl_billed_amt", "clm_dtl_deduct_amt", "clm_dtl_net_amt", "clm_dtl_paid_amt", "clm_dtl_actual_paid_amt", "clm_dtl_not_covered_amt", "clm_dtl_co_insurance_amt", "clm_dtl_other_adjustments_amt", "clm_dtl_cob_savings", "clm_dtl_oic_paid_amt", "clm_dtl_oic_allowed_amt", "clm_dtl_interest_amt", "clm_dtl_prompt_pay_discount_amt", "clm_dtl_interest_discount_amt"]
for col_name in detail_amount_cols:
    gen = add_standard_col(gen, col_name, "decimal", nullable=True)
detail_mid_cols = [("clm_dtl_interest_discount_flag", "string"), ("clm_dtl_copay_amt", "decimal"), ("clm_dtl_copay_reason", "string"), ("clm_dtl_sc_cd", "string"), ("clm_dtl_reason_code_sk", "string"), ("clm_dtl_line_status", "string"), ("clm_dtl_clean_claim_ind", "string"), ("clm_dtl_place_of_service", "string"), ("clm_dtl_fee_schedule_code", "string"), ("clm_dtl_authorization_nbr", "string"), ("clm_dtl_check_nbr", "string"), ("clm_dtl_check_added_line_flag", "string"), ("clm_dtl_check_message", "string"), ("clm_dtl_submitting_provider", "string"), ("clm_dtl_rendering_provider", "string"), ("clm_dtl_rendering_provider_type", "string"), ("clm_dtl_rendering_provider_spec", "string"), ("clm_dtl_participating_provider", "string"), ("clm_dtl_adjudication_status", "string"), ("clm_dtl_procedure_code", "string"), ("clm_dtl_procedure_modifier", "string"), ("clm_dtl_modifier_2", "string"), ("clm_dtl_modifier_3", "string"), ("clm_dtl_modifier_4", "string"), ("clm_dtl_procedure_adj", "string"), ("clm_dtl_procedure_qty", "decimal"), ("clm_dtl_revenue_code", "string"), ("clm_dtl_diagnosis_ind_1", "string"), ("clm_dtl_diagnosis_ind_2", "string"), ("clm_dtl_diagnosis_ind_3", "string"), ("clm_dtl_diagnosis_ind_4", "string"), ("clm_dtl_paid_days", "decimal"), ("clm_dtl_anesthesia_time_units", "decimal"), ("clm_dtl_cob_rule", "string"), ("clm_dtl_wrap_network", "string"), ("clm_dtl_returned_ntwrk_repric", "string"), ("clm_dtl_user_id", "string"), ("clm_dtl_extract_date", "timestamp"), ("is_active", "boolean"), ("updated_at", "timestamp"), ("created_at", "timestamp")]
for col_name, col_type in detail_mid_cols:
    gen = add_standard_col(gen, col_name, col_type, nullable=True)
df = gen.build()
write_delta(df, "fact_claim_detail")

# COMMAND ----------

# DBTITLE 1,fact_member_enrollment
gen = dg.DataGenerator(spark, rows=5000)
gen = add_col(gen, "enrollment_sk", "string", nullable=False, template=r'\\w\\w\\w-\\d\\d\\d\\d', random=True, uniqueValues=5000)
enrollment_before_member = [("source_system", "string"), ("src_member_business_id", "int"), ("mbr_enr_source_member_id", "string"), ("mbr_enr_insured_id", "string"), ("mbr_enr_contract_id", "string"), ("mbr_enr_insured_code", "string"), ("mbr_enr_insured_add_date", "timestamp"), ("mbr_enr_insured_event_date", "timestamp"), ("mbr_enr_insured_event_id", "string"), ("mbr_enr_insured_event_code", "string"), ("mbr_enr_status", "string"), ("mbr_enr_insured_event_add_date", "timestamp"), ("mbr_enr_plan_id", "string"), ("mbr_enr_line_of_business", "string"), ("mbr_enr_line_of_business_id", "string"), ("mbr_enr_group_name", "string"), ("mbr_enr_subgroup_name", "string"), ("mbr_enr_effective_date", "date"), ("mbr_enr_termination_date", "date"), ("mbr_enr_termination_event_date", "date"), ("mbr_enr_termination_reason", "string"), ("mbr_enr_product_id", "string"), ("mbr_enr_group_ck", "string"), ("mbr_enr_group_code", "string"), ("mbr_enr_subgroup_ck", "string"), ("mbr_enr_subgroup_code", "string"), ("is_active", "boolean"), ("id_value", "string"), ("id_type", "string")]
for col_name, col_type in enrollment_before_member:
    gen = add_standard_col(gen, col_name, col_type, nullable=True)
gen = add_col(gen, "member_sk", "bigint", nullable=True, values=member_ids, random=True, baseColumn="enrollment_sk", percentNulls=0.02)
gen = add_standard_col(gen, "payload_hash", "string", nullable=True)
df = gen.build()
write_delta(df, "fact_member_enrollment")

# COMMAND ----------

# DBTITLE 1,Done
print("Synthetic member claims data generation complete")
