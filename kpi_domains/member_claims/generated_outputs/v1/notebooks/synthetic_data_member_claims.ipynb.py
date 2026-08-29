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

_orig_withColumn = dg.DataGenerator.withColumn

def _safe_withColumn(self, colName, colType, *args, **kwargs):
    if isinstance(colType, BooleanType) or colType is BooleanType:
        kwargs.pop('values', None)
        kwargs.pop('weights', None)
    if isinstance(colType, TimestampType) or colType is TimestampType or str(colType).lower() in ('timestamp', 'timestamp_ntz'):
        for key in ('begin', 'end'):
            val = kwargs.get(key)
            if isinstance(val, str) and len(val) == 10:
                kwargs[key] = f"{val} 00:00:00" if key == 'begin' else f"{val} 23:59:59"
    return _orig_withColumn(self, colName, colType, *args, **kwargs)

dg.DataGenerator.withColumn = _safe_withColumn

CATALOG = "aw_serverless_stable_catalog"
SCHEMA = "aibi_member_claims"
VERSION_SUFFIX = "_v1"

# ============================================================================
# UTILITY FUNCTIONS (domain-agnostic - from template)
# ============================================================================

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
            actual_name = actual_lower_map[col_key.lower()]
            corrected[actual_name] = val
            print(f"  Domain col '{col_key}' corrected to '{actual_name}'")
        else:
            unmatched.append(col_key)
    if unmatched:
        raise AssertionError(f"[{table_name}] DOMAIN_COLS unmatched: {unmatched}. Available: {sorted(actual_cols.keys())}")
    print(f"  validate_domain_cols({table_name}): {len(corrected)} columns matched")
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
            actual_name = actual_lower_map[fk_key.lower()]
            corrected[actual_name] = val
        else:
            raise AssertionError(f"[{table_name}] FK col '{fk_key}' not found. Available: {sorted(actual_cols.keys())}")
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
            gen = gen.withColumn(col_name, StringType(), template="\\w" * min(eff_len, 8), percentNulls=0.0)
        elif col_lower in fk_set:
            if ptype == LongType() or ptype == IntegerType():
                gen = gen.withColumn(col_name, ptype, minValue=1, maxValue=rows, percentNulls=0.0)
            else:
                gen = gen.withColumn(col_name, StringType(), template="FK-\\n\\n\\n\\n", percentNulls=0.0)
        elif ptype == LongType():
            gen = gen.withColumn(col_name, LongType(), minValue=1, maxValue=rows * 10, uniqueValues=rows if is_pk else None, percentNulls=0.0)
        elif ptype == IntegerType():
            gen = gen.withColumn(col_name, IntegerType(), minValue=1, maxValue=rows * 10 if is_pk else rows, uniqueValues=rows if is_pk else None, percentNulls=0.0)
        elif ptype == DateType():
            gen = gen.withColumn(col_name, DateType(), begin=begin_date, end=end_date, percentNulls=0.0)
        elif ptype == TimestampType():
            gen = gen.withColumn(col_name, TimestampType(), begin=f"{begin_date} 00:00:00", end=f"{end_date} 23:59:59", percentNulls=0.0)
        elif ptype == BooleanType():
            gen = gen.withColumn(col_name, BooleanType(), percentNulls=0.0)
        elif ptype == DoubleType():
            gen = gen.withColumn(col_name, DoubleType(), minValue=0.0, maxValue=100000.0, percentNulls=0.0)
        elif isinstance(ptype, str) and 'decimal' in ptype:
            gen = gen.withColumn(col_name, ptype, minValue=0.0, maxValue=100000.0, percentNulls=0.0)
        else:
            eff_len = min(max_len, 20) if max_len > 0 else 20
            gen = gen.withColumn(col_name, StringType(), template="\\w" * min(eff_len, 10), uniqueValues=rows if is_pk else None, percentNulls=0.0)
    df = gen.build()
    for dc_name_orig, (dc_values, dc_weights) in domain_cols.items():
        actual_col = next((c for c in col_types if c.lower() == dc_name_orig.lower()), None)
        if not actual_col or actual_col not in df.columns:
            continue
        target_type = col_types.get(actual_col, "string").lower()
        if any(t in target_type for t in ('char', 'string')):
            dc_values = [str(v) for v in dc_values]
        elif 'timestamp' in target_type:
            dc_values = [f"{str(v)} 00:00:00" if len(str(v)) == 10 else str(v) for v in dc_values]
        elif any(t in target_type for t in ('bigint', 'long', 'int', 'integer')):
            dc_values = [int(v) for v in dc_values]
        elif any(t in target_type for t in ('double', 'float', 'decimal')):
            dc_values = [float(v) for v in dc_values]
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
            assert len(parent_pks) > 1, f"Parent {parent_table}.{parent_pk_col} lacks diversity"
            target_type = col_types.get(fk_col, "bigint").lower()
            replacement = F.element_at(F.array([F.lit(v) for v in parent_pks]), (F.col("_row_num") % len(parent_pks) + 1).cast("int"))
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
            if pk_type == LongType() or pk_type == IntegerType():
                df = df.drop(pk_col).withColumn(pk_col, F.col("_pk_num").cast(pk_type))
            else:
                max_len = extract_max_length(col_types.get(pk_col, ""))
                prefix = table_name[:3].upper() + "-"
                pad_len = min(max_len - len(prefix), 10) if max_len > 0 else 10
                df = df.drop(pk_col).withColumn(pk_col, F.concat(F.lit(prefix), F.lpad(F.col("_pk_num").cast("string"), pad_len, "0")))
        df = df.drop("_pk_num")
    table_columns = list(col_types.keys())
    return df.select([c for c in table_columns if c in df.columns])

TABLES = discover_tables()

# COMMAND ----------

# DBTITLE 1,Generate all tables in dependency order

def write_generated(logical, rows, domain_cols, pk_cols, fk_replacements=None):
    table_name = TABLES[logical]
    print(f"Generating {logical} -> {table_name}, rows={rows}")
    print(f"Columns in {table_name}: {list(get_table_col_types(table_name).keys())}")
    domain_cols = validate_domain_cols(table_name, domain_cols)
    fk_replacements = validate_fk_replacements(table_name, fk_replacements or {})
    df = generate_table(table_name, rows=rows, domain_cols=domain_cols, pk_cols=pk_cols, fk_replacements=fk_replacements)
    if logical == "fact_claim_detail":
        w = Window.orderBy(F.monotonically_increasing_id())
        df = df.withColumn("_rn_line", F.row_number().over(w))
        df = df.drop("clm_dtl_line_nbr").withColumn("clm_dtl_line_nbr", F.col("_rn_line").cast("string")).drop("_rn_line")
        df = df.select(list(get_table_col_types(table_name).keys()))
    df = enforce_varchar_limits(df, table_name)
    verify_before_write(df, table_name, pk_cols=pk_cols, fk_cols=list(fk_replacements.keys()), categorical_cols=list(domain_cols.keys()))
    df.write.format("delta").mode("append").saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")
    print(f"Wrote {rows} rows to {table_name}")

write_generated("dim_member", 500, {
    "mbr_sex": (["Male", "Female", "Unknown"], [0.48, 0.48, 0.04]),
    "mbr_race": (["White", "Black or African American", "Asian", "American Indian or Alaska Native", "Native Hawaiian or Pacific Islander", "Other", "Unknown"], [0.54, 0.18, 0.08, 0.02, 0.01, 0.12, 0.05]),
    "mbr_ethnicity": (["Hispanic", "Non-Hispanic", "Unknown"], [0.19, 0.76, 0.05]),
    "mbr_marital_status": (["Single", "Married", "Divorced", "Widowed", "Separated"], [0.36, 0.42, 0.10, 0.08, 0.04]),
    "mbr_line_of_business": (["COMMERCIAL", "MEDICARE", "MEDICAID", "TRICARE", "EXCHANGE"], [0.42, 0.25, 0.20, 0.08, 0.05]),
    "mbr_line_of_business_name": (["Commercial PPO", "Medicare Advantage", "Managed Medicaid", "TRICARE Prime", "ACA Exchange"], [0.42, 0.25, 0.20, 0.08, 0.05]),
    "mbr_state": (["CA", "TX", "FL", "NY", "PA", "OH", "GA", "NC"], [0.18, 0.16, 0.14, 0.13, 0.10, 0.10, 0.10, 0.09]),
    "mbr_text_opt_in": (["Y", "N"], [0.62, 0.38]),
    "mbr_relationship_type": (["Subscriber", "Spouse", "Dependent Child", "Disabled Dependent", "Other Dependent"], [0.45, 0.22, 0.28, 0.03, 0.02]),
    "source_system_code": (["FACETS", "QNXT", "EPIC", "CAREMGMT"], [0.45, 0.30, 0.15, 0.10])
}, ["member_sk"])

write_generated("dim_address", 300, {
    "entity_type_key": (["MEMBER", "PROVIDER", "FACILITY", "GROUP"], [0.45, 0.25, 0.20, 0.10]),
    "address_type_code": (["HOME", "MAILING", "BILLING", "SERVICE", "PRIMARY"], [0.36, 0.24, 0.14, 0.16, 0.10]),
    "city": (["Los Angeles", "Houston", "Miami", "New York", "Philadelphia", "Columbus", "Atlanta", "Charlotte"], [0.18, 0.16, 0.14, 0.13, 0.10, 0.10, 0.10, 0.09]),
    "state": (["CA", "TX", "FL", "NY", "PA", "OH", "GA", "NC"], [0.18, 0.16, 0.14, 0.13, 0.10, 0.10, 0.10, 0.09]),
    "country_code": (["US", "PR", "GU"], [0.97, 0.02, 0.01])
}, ["address_key"])

write_generated("dim_provider", 300, {"source_system": (["FACETS", "QNXT", "NPPES", "PROVIDER_MASTER"], [0.34, 0.26, 0.25, 0.15])}, ["provider_sk"], {"provider_address_sk": (TABLES["dim_address"], "address_key")})
write_generated("dim_member_identifier", 800, {"id_type": (["Member ID", "Subscriber ID", "DEERS Beneficiary ID", "Medicaid Case Number", "Employer Employee ID"], [0.40, 0.24, 0.14, 0.12, 0.10])}, ["mbr_identifier_sk"], {"member_sk": (TABLES["dim_member"], "member_sk")})
write_generated("dim_member_history", 800, {"mbr_line_of_business": (["COMMERCIAL", "MEDICARE", "MEDICAID", "TRICARE", "EXCHANGE"], [0.42, 0.25, 0.20, 0.08, 0.05]), "mbr_state": (["CA", "TX", "FL", "NY", "PA", "OH", "GA", "NC"], [0.18, 0.16, 0.14, 0.13, 0.10, 0.10, 0.10, 0.09]), "mbr_sex": (["Male", "Female", "Unknown"], [0.48, 0.48, 0.04])}, ["mbr_history_sk"], {"member_sk": (TABLES["dim_member"], "member_sk")})
write_generated("fact_member_enrollment", 1200, {"source_system": (["FACETS", "QNXT", "EPIC", "CAREMGMT"], [0.45, 0.30, 0.15, 0.10]), "mbr_enr_status": (["Active", "Terminated", "Pending", "Suspended", "COBRA"], [0.72, 0.14, 0.07, 0.04, 0.03]), "mbr_enr_line_of_business": (["COMMERCIAL", "MEDICARE", "MEDICAID", "TRICARE", "EXCHANGE"], [0.42, 0.25, 0.20, 0.08, 0.05]), "id_type": (["Member ID", "Subscriber ID", "DEERS Beneficiary ID", "Medicaid Case Number", "Employer Employee ID"], [0.40, 0.24, 0.14, 0.12, 0.10])}, ["enrollment_sk"], {"member_sk": (TABLES["dim_member"], "member_sk")})
write_generated("fact_claim_header", 2000, {"clm_claim_type": (["Professional", "Institutional", "Pharmacy", "Dental", "Vision"], [0.38, 0.28, 0.18, 0.10, 0.06]), "clm_bill_type": (["Hospital Inpatient", "Hospital Outpatient", "Skilled Nursing", "Home Health", "Clinic"], [0.22, 0.32, 0.10, 0.11, 0.25]), "clm_line_of_business": (["COMMERCIAL", "MEDICARE", "MEDICAID", "TRICARE", "EXCHANGE"], [0.42, 0.25, 0.20, 0.08, 0.05]), "clm_admission_type": (["Emergency", "Elective", "Urgent", "Newborn", "Trauma"], [0.30, 0.28, 0.24, 0.12, 0.06]), "clm_service_type_code": (["Medical", "Surgical", "Maternity", "Behavioral Health", "Rehabilitation", "Pharmacy"], [0.34, 0.20, 0.08, 0.13, 0.10, 0.15]), "clm_cob_type": (["Primary", "Secondary", "Tertiary", "Medicare COB", "No COB"], [0.58, 0.16, 0.03, 0.08, 0.15])}, ["clm_header_sk"], {"clm_member_sk": (TABLES["dim_member"], "member_sk"), "clm_service_facility_address_sk": (TABLES["dim_address"], "address_key")})
write_generated("fact_claim_detail", 5000, {"clm_dtl_claim_type": (["Professional", "Institutional", "Pharmacy", "Dental", "Vision"], [0.38, 0.28, 0.18, 0.10, 0.06]), "clm_dtl_benefit_category": (["Primary Care", "Specialist", "Inpatient", "Outpatient", "Emergency", "Pharmacy", "Behavioral Health"], [0.18, 0.20, 0.12, 0.22, 0.08, 0.14, 0.06]), "clm_dtl_benefit_level": (["In Network", "Out of Network", "Tier 1", "Tier 2", "Non Covered"], [0.55, 0.15, 0.16, 0.10, 0.04]), "clm_dtl_line_status": (["Paid", "Denied", "Pending", "Adjusted", "Reversed"], [0.66, 0.16, 0.08, 0.07, 0.03]), "clm_dtl_adjudication_status": (["Auto Adjudicated", "Manual Review", "Clinical Review", "Denied", "Pended"], [0.54, 0.18, 0.12, 0.10, 0.06]), "clm_dtl_clean_claim_ind": (["Y", "N"], [0.78, 0.22]), "clm_dtl_place_of_service": (["11", "21", "22", "23", "31", "32", "41"], [0.36, 0.12, 0.22, 0.10, 0.07, 0.06, 0.07]), "clm_dtl_procedure_code": (["99213", "99214", "99203", "99396", "80053", "J0585", "D0120", "97110"], [0.20, 0.18, 0.14, 0.10, 0.12, 0.08, 0.08, 0.10]), "clm_dtl_copay_reason": (["Office Visit Copay", "Specialist Copay", "Emergency Copay", "Preventive Waived", "Pharmacy Tier Copay"], [0.34, 0.22, 0.14, 0.18, 0.12])}, ["clm_dtl_claim_id", "clm_dtl_line_nbr"])

