# Databricks notebook source
# DBTITLE 1,Install dependencies
# MAGIC %pip install dbldatagen --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Setup and Utilities
import dbldatagen as dg
from pyspark.sql.types import *
from pyspark.sql import functions as F
from pyspark.sql.window import Window

spark.conf.set("spark.sql.ansi.enabled", "false")

CATALOG = "aw_serverless_stable_catalog"
SCHEMA = "aibi_member_claims"
VERSION_SUFFIX = "_v1"

def discover_tables() -> dict:
    all_tables = [row.tableName for row in spark.sql(f"SHOW TABLES IN `{CATALOG}`.`{SCHEMA}`").collect()]
    version_tables = [t for t in all_tables if t.endswith(VERSION_SUFFIX)] if VERSION_SUFFIX else all_tables
    result = {}
    for t in version_tables:
        logical = t[:-len(VERSION_SUFFIX)] if VERSION_SUFFIX else t
        result[logical] = t
    print(f"Discovered {len(result)} tables for version '{VERSION_SUFFIX}': {list(result.values())}")
    return result

def get_table_col_types(table_name: str) -> dict:
    rows = spark.sql(f"DESCRIBE TABLE `{CATALOG}`.`{SCHEMA}`.`{table_name}`").collect()
    result = {}
    for row in rows:
        col_name = row['col_name'].strip()
        data_type = row['data_type'].strip()
        if not col_name or col_name.startswith('#') or not data_type:
            break
        result[col_name] = data_type
    return result

def spark_type_for(type_str: str):
    t = type_str.lower().strip()
    if t in ('bigint', 'long'):
        return LongType()
    elif t in ('int', 'integer', 'smallint', 'tinyint'):
        return IntegerType()
    elif t == 'boolean':
        return BooleanType()
    elif t == 'date':
        return DateType()
    elif t in ('timestamp', 'timestamp_ntz'):
        return TimestampType()
    elif t in ('double', 'float'):
        return DoubleType()
    elif t.startswith('decimal'):
        return t
    else:
        return StringType()

def extract_max_length(type_str: str) -> int:
    import re
    m = re.match(r'(?:var)?char\((\d+)\)', type_str.lower().strip())
    return int(m.group(1)) if m else 0

def enforce_varchar_limits(df, table_name: str):
    col_types = get_table_col_types(table_name)
    for col_name, type_str in col_types.items():
        max_len = extract_max_length(type_str)
        if max_len > 0 and col_name in df.columns:
            df = df.withColumn(col_name, F.substring(F.col(col_name).cast("string"), 1, max_len))
    return df

def verify_before_write(df, table_name: str, pk_cols: list, fk_cols: list, categorical_cols: list):
    total = df.count()
    for pk in pk_cols:
        distinct = df.select(pk).distinct().count()
        assert distinct == total, f"[{table_name}] PK '{pk}' not unique: {distinct}/{total}"
    for fk in fk_cols:
        distinct = df.select(fk).distinct().count()
        assert distinct > 1, f"[{table_name}] FK '{fk}' has only {distinct} distinct value(s)"
    for col in categorical_cols:
        sample = [str(row[0]) for row in df.select(col).distinct().limit(10).collect()]
        bad_patterns = any(v.startswith("PLACEHOLDER") or v.startswith("ID-") or v.startswith("val_") for v in sample if v)
        assert not bad_patterns, f"[{table_name}] Column '{col}' has generic values {sample[:5]}"

def validate_domain_cols(table_name: str, domain_cols: dict) -> dict:
    actual_cols = get_table_col_types(table_name)
    actual_lower_map = {c.lower(): c for c in actual_cols.keys()}
    corrected = {}
    unmatched = []
    for col_key, val in domain_cols.items():
        if col_key in actual_cols:
            corrected[col_key] = val
        elif col_key.lower() in actual_lower_map:
            corrected[actual_lower_map[col_key.lower()]] = val
        else:
            unmatched.append(col_key)
    if unmatched:
        raise AssertionError(f"[{table_name}] DOMAIN_COLS unmatched: {unmatched}; available: {sorted(actual_cols.keys())}")
    print(f"  ✓ validate_domain_cols({table_name}): {len(corrected)} columns matched")
    return corrected

def validate_fk_replacements(table_name: str, fk_replacements: dict) -> dict:
    if not fk_replacements:
        return {}
    actual_cols = get_table_col_types(table_name)
    actual_lower_map = {c.lower(): c for c in actual_cols.keys()}
    corrected = {}
    for fk_key, val in fk_replacements.items():
        if fk_key in actual_cols:
            corrected[fk_key] = val
        elif fk_key.lower() in actual_lower_map:
            corrected[actual_lower_map[fk_key.lower()]] = val
        else:
            raise AssertionError(f"[{table_name}] FK column not found: {fk_key}; available: {sorted(actual_cols.keys())}")
    return corrected

def generate_table(table_name: str, rows: int, domain_cols: dict, pk_cols: list = None, fk_replacements: dict = None, date_range: tuple = ("2020-01-01", "2024-12-31")):
    col_types = get_table_col_types(table_name)
    pk_set = set(c.lower() for c in (pk_cols or []))
    fk_replacements = fk_replacements or {}
    fk_set = set(c.lower() for c in fk_replacements.keys())
    domain_set = set(c.lower() for c in domain_cols.keys())
    begin_date, end_date = date_range
    gen = dg.DataGenerator(spark, name=table_name, rows=rows, seedColumnName="_id")
    for col_name, type_str in col_types.items():
        col_lower = col_name.lower()
        ptype = spark_type_for(type_str)
        max_len = extract_max_length(type_str)
        is_pk = col_lower in pk_set
        if col_lower in domain_set:
            eff_len = min(max_len, 20) if max_len > 0 else 20
            gen = gen.withColumn(col_name, StringType(), template="X" * min(eff_len, 8), percentNulls=0.0)
        elif col_lower in fk_set:
            if isinstance(ptype, (LongType, IntegerType)):
                gen = gen.withColumn(col_name, ptype, minValue=1, maxValue=rows, percentNulls=0.0)
            else:
                gen = gen.withColumn(col_name, StringType(), template="FK000000", percentNulls=0.0)
        elif isinstance(ptype, LongType):
            gen = gen.withColumn(col_name, LongType(), minValue=1, maxValue=rows * 10, percentNulls=0.0)
        elif isinstance(ptype, IntegerType):
            gen = gen.withColumn(col_name, IntegerType(), minValue=1, maxValue=rows * 10 if is_pk else rows, percentNulls=0.0)
        elif isinstance(ptype, DateType):
            gen = gen.withColumn(col_name, DateType(), begin=begin_date, end=end_date, percentNulls=0.0)
        elif isinstance(ptype, TimestampType):
            gen = gen.withColumn(col_name, TimestampType(), begin=f"{begin_date} 00:00:00", end=f"{end_date} 23:59:59", percentNulls=0.0)
        elif isinstance(ptype, BooleanType):
            gen = gen.withColumn(col_name, BooleanType(), percentNulls=0.0)
        elif isinstance(ptype, str) and 'decimal' in ptype:
            gen = gen.withColumn(col_name, ptype, minValue=0.0, maxValue=5000.0, percentNulls=0.0)
        else:
            eff_len = min(max_len, 20) if max_len > 0 else 20
            gen = gen.withColumn(col_name, StringType(), template="X" * min(eff_len, 8), percentNulls=0.0)
    df = gen.build()
    for dc_name_orig, (dc_values, dc_weights) in domain_cols.items():
        actual_col = next((c for c in col_types if c.lower() == dc_name_orig.lower()), None)
        if not actual_col or actual_col not in df.columns:
            continue
        target_type = col_types.get(actual_col, "string").lower()
        if any(t in target_type for t in ('char', 'string')):
            dc_values = [str(v) for v in dc_values]
        cum_wts = []
        running = 0.0
        for wt in dc_weights:
            running += wt
            cum_wts.append(running)
        rand_col = F.rand(seed=abs(hash(actual_col)) % 10000)
        expr = F.lit(dc_values[-1])
        for i in range(len(dc_values) - 2, -1, -1):
            expr = F.when(rand_col <= cum_wts[i], F.lit(dc_values[i])).otherwise(expr)
        df = df.withColumn(actual_col, expr)
    if fk_replacements:
        w = Window.orderBy(F.monotonically_increasing_id())
        df = df.withColumn("_row_num", F.row_number().over(w))
        for fk_col, (parent_table, parent_pk_col) in fk_replacements.items():
            parent_fqn = f"{CATALOG}.{SCHEMA}.{parent_table}"
            parent_pks = [row[0] for row in spark.table(parent_fqn).select(parent_pk_col).distinct().collect()]
            assert parent_pks, f"No parent keys found for {fk_col} from {parent_fqn}.{parent_pk_col}"
            replacement = F.element_at(F.array([F.lit(v) for v in parent_pks]), (F.col("_row_num") % len(parent_pks) + 1).cast("int"))
            target_type = col_types.get(fk_col, "bigint").lower()
            if "bigint" in target_type or "long" in target_type:
                replacement = replacement.cast(LongType())
            elif "int" in target_type:
                replacement = replacement.cast(IntegerType())
            df = df.drop(fk_col).withColumn(fk_col, replacement)
        df = df.drop("_row_num")
    if pk_cols:
        w = Window.orderBy(F.monotonically_increasing_id())
        df = df.withColumn("_pk_num", F.row_number().over(w))
        for pk_col in pk_cols:
            pk_type = spark_type_for(col_types.get(pk_col, "bigint"))
            if isinstance(pk_type, LongType) or isinstance(pk_type, IntegerType):
                df = df.drop(pk_col).withColumn(pk_col, F.col("_pk_num").cast(pk_type))
            else:
                max_len = extract_max_length(col_types.get(pk_col, ""))
                prefix = table_name[:3].upper() + "-"
                pad_len = min(max_len - len(prefix), 10) if max_len > 0 else 10
                df = df.drop(pk_col).withColumn(pk_col, F.concat(F.lit(prefix), F.lpad(F.col("_pk_num").cast("string"), pad_len, "0")))
        df = df.drop("_pk_num")
    return df.select([c for c in col_types.keys() if c in df.columns])

TABLES = discover_tables()

# COMMAND ----------

# DBTITLE 1,Generate all member claims tables

def write_generated(logical, rows, domain_cols, pk_cols, fk_replacements=None, extra_fn=None):
    table_name = TABLES[logical]
    print(f"Generating {table_name} rows={rows}")
    col_types = get_table_col_types(table_name)
    print(f"Columns in {table_name}: {list(col_types.keys())}")
    domain_cols = validate_domain_cols(table_name, domain_cols)
    fk_replacements = validate_fk_replacements(table_name, fk_replacements or {})
    df = generate_table(table_name, rows=rows, domain_cols=domain_cols, pk_cols=pk_cols, fk_replacements=fk_replacements)
    if extra_fn:
        df = extra_fn(df, table_name)
    df = enforce_varchar_limits(df, table_name)
    verify_before_write(df, table_name, pk_cols=pk_cols, fk_cols=list(fk_replacements.keys()), categorical_cols=list(domain_cols.keys()))
    df.write.format("delta").mode("append").saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")
    print(f"Wrote {df.count()} rows to {table_name}")

lob_vals = (["Commercial", "Medicare Advantage", "Medicaid", "TRICARE", "Exchange"], [0.44, 0.24, 0.20, 0.07, 0.05])
state_vals = (["CA", "TX", "FL", "NY", "PA", "OH", "GA", "NC"], [0.18, 0.16, 0.14, 0.13, 0.10, 0.09, 0.10, 0.10])
source_vals = (["FACETS", "QNXT", "EPIC", "EDI837"], [0.45, 0.30, 0.15, 0.10])
claim_type_vals = (["Professional", "Institutional", "Pharmacy", "Dental", "Vision"], [0.42, 0.28, 0.16, 0.09, 0.05])

write_generated("dim_member", 400, {
    "mbr_sex": (["Female", "Male", "Unknown"], [0.51, 0.47, 0.02]),
    "mbr_race": (["White", "Black or African American", "Asian", "Native American", "Pacific Islander", "Other", "Unknown"], [0.50, 0.18, 0.12, 0.03, 0.02, 0.10, 0.05]),
    "mbr_ethnicity": (["Hispanic or Latino", "Not Hispanic or Latino", "Unknown"], [0.20, 0.72, 0.08]),
    "mbr_marital_status": (["Single", "Married", "Divorced", "Widowed", "Domestic Partner"], [0.34, 0.44, 0.12, 0.07, 0.03]),
    "mbr_line_of_business": lob_vals,
    "mbr_state": state_vals,
    "mbr_relationship_type": (["Subscriber", "Spouse", "Child", "Domestic Partner", "Other Dependent"], [0.48, 0.22, 0.25, 0.03, 0.02]),
    "source_system_code": source_vals
}, ["member_sk"])

write_generated("dim_address", 300, {
    "entity_type_key": (["MEMBER", "PROVIDER", "FACILITY"], [0.55, 0.30, 0.15]),
    "address_type_code": (["HOME", "MAILING", "BILLING", "SERVICE", "PRACTICE"], [0.38, 0.24, 0.14, 0.14, 0.10]),
    "city": (["Los Angeles", "Houston", "Miami", "New York", "Philadelphia", "Columbus", "Atlanta", "Charlotte"], [0.18, 0.16, 0.14, 0.13, 0.10, 0.09, 0.10, 0.10]),
    "state": state_vals,
    "country_code": (["US", "PR", "VI"], [0.96, 0.03, 0.01])
}, ["address_key"])

write_generated("dim_member_identifier", 500, {
    "id_type": (["Member ID", "Subscriber ID", "Medicaid ID", "Medicare MBI", "Employer ID"], [0.38, 0.26, 0.16, 0.14, 0.06]),
    "source_system_code": source_vals
}, ["mbr_identifier_sk"], {"member_sk": (TABLES["dim_member"], "member_sk")})

write_generated("dim_member_history", 500, {
    "mbr_sex": (["Female", "Male", "Unknown"], [0.51, 0.47, 0.02]),
    "mbr_line_of_business": lob_vals,
    "mbr_state": state_vals
}, ["mbr_history_sk"], {"member_sk": (TABLES["dim_member"], "member_sk")})

write_generated("fact_member_enrollment", 800, {
    "mbr_enr_status": (["Active", "Terminated", "Pending", "Suspended", "COBRA"], [0.72, 0.14, 0.07, 0.04, 0.03]),
    "mbr_enr_line_of_business": lob_vals,
    "mbr_enr_insured_code": (["EE", "SP", "CH", "DP"], [0.48, 0.22, 0.27, 0.03]),
    "mbr_enr_insured_event_code": (["EN", "RN", "TR", "CH"], [0.42, 0.30, 0.18, 0.10]),
    "mbr_enr_termination_reason": (["Voluntary Disenrollment", "Non Payment", "Employer Group Termination", "Moved Out of Area", "Plan Change"], [0.30, 0.20, 0.18, 0.17, 0.15]),
    "id_type": (["Member ID", "Subscriber ID", "Medicaid ID", "Medicare MBI"], [0.42, 0.28, 0.16, 0.14])
}, ["enrollment_sk"], {"member_sk": (TABLES["dim_member"], "member_sk")})

write_generated("dim_provider", 300, {
    "source_system": (["Provider Master", "NPPES", "Credentialing", "Network Contracting"], [0.42, 0.28, 0.18, 0.12])
}, ["provider_sk"], {"provider_address_sk": (TABLES["dim_address"], "address_key")})

def header_extras(df, table_name):
    w = Window.orderBy(F.monotonically_increasing_id())
    df = df.withColumn("_rn", F.row_number().over(w))
    df = df.drop("clm_claim_id").withColumn("clm_claim_id", F.concat(F.lit("CLM-"), F.lpad(F.col("_rn").cast("string"), 8, "0")))
    return df.drop("_rn")

write_generated("fact_claim_header", 300, {
    "clm_claim_type": claim_type_vals,
    "clm_bill_type": (["Outpatient Hospital", "Inpatient Hospital", "Skilled Nursing", "Home Health", "Clinic"], [0.38, 0.22, 0.10, 0.12, 0.18]),
    "clm_line_of_business": lob_vals,
    "clm_admission_type": (["Elective", "Emergency", "Urgent", "Newborn", "Trauma"], [0.34, 0.30, 0.18, 0.12, 0.06]),
    "clm_cob_type": (["Primary", "Secondary", "Tertiary", "No COB"], [0.45, 0.18, 0.04, 0.33]),
    "clm_claim_timely_filing": (["Timely", "Late", "Exception Approved"], [0.84, 0.11, 0.05])
}, ["clm_header_sk"], {"clm_member_sk": (TABLES["dim_member"], "member_sk"), "clm_service_facility_address_sk": (TABLES["dim_address"], "address_key")}, header_extras)

write_generated("fact_claim_detail", 900, {
    "clm_dtl_claim_type": claim_type_vals,
    "clm_dtl_benefit_category": (["Medical", "Hospital", "Prescription Drug", "Behavioral Health", "Dental", "Vision", "Preventive Care"], [0.35, 0.20, 0.16, 0.09, 0.08, 0.05, 0.07]),
    "clm_dtl_benefit_level": (["In Network", "Out of Network", "Tier 1 Preferred", "Tier 2 Standard"], [0.64, 0.14, 0.15, 0.07]),
    "clm_dtl_line_status": (["Paid", "Denied", "Pending", "Adjusted", "Reversed"], [0.68, 0.16, 0.08, 0.06, 0.02]),
    "clm_dtl_clean_claim_ind": (["Clean", "Not Clean", "Corrected"], [0.76, 0.18, 0.06]),
    "clm_dtl_place_of_service": (["11", "21", "22", "23", "31", "41"], [0.40, 0.14, 0.24, 0.08, 0.07, 0.07]),
    "clm_dtl_fee_schedule_code": (["CMS", "RBR", "DRG", "ASC", "LAB"], [0.40, 0.25, 0.16, 0.10, 0.09]),
    "clm_dtl_adjudication_status": (["Auto Adjudicated", "Manual Review", "Medical Review", "Coordination of Benefits", "Appeal Review"], [0.58, 0.18, 0.10, 0.09, 0.05]),
    "clm_dtl_procedure_code": (["99213", "99214", "93000", "80053", "J0585", "D0120", "V2020"], [0.28, 0.20, 0.14, 0.16, 0.07, 0.08, 0.07]),
    "clm_dtl_revenue_code": (["0450 Emergency Room", "0300 Lab", "0360 Operating Room", "0510 Clinic", "0250 Pharmacy", "0420 Physical Therapy"], [0.18, 0.25, 0.10, 0.22, 0.15, 0.10])
}, ["clm_dtl_line_nbr"], {"clm_dtl_claim_id": (TABLES["fact_claim_header"], "clm_claim_id")})

