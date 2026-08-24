# Databricks notebook source
# DBTITLE 1,Synthetic Data — member_claims
# Uses dbldatagen to generate realistic sample data for all tables.
# CRITICAL: All generated columns MUST match DDL types exactly.

# COMMAND ----------

# DBTITLE 1,Install dependencies
%pip install dbldatagen pyyaml --quiet
dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Import dbldatagen
import dbldatagen as dg

# COMMAND ----------

# DBTITLE 1,Setup and Type Helpers
from pyspark.sql.types import *
from pyspark.sql import functions as F, Window
import re, yaml

spark.conf.set("spark.sql.ansi.enabled", "false")

_orig_withColumn = dg.DataGenerator.withColumn
def _safe_withColumn(self, colName, colType, *args, **kwargs):
    if colType == BooleanType() or colType is BooleanType:
        kwargs.pop('values', None)
        kwargs.pop('weights', None)
    if colType == TimestampType() or colType is TimestampType or str(colType).lower() in ('timestamp', 'timestamp_ntz'):
        for key in ('begin', 'end'):
            if key in kwargs and isinstance(kwargs[key], str) and len(kwargs[key]) == 10:
                kwargs[key] = f"{kwargs[key]} 00:00:00" if key == 'begin' else f"{kwargs[key]} 23:59:59"
    return _orig_withColumn(self, colName, colType, *args, **kwargs)
dg.DataGenerator.withColumn = _safe_withColumn

CATALOG = "aw_serverless_stable_catalog"
SCHEMA = "aibi_member_claims"
VERSION_SUFFIX = "_v2"


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
    elif t == 'string':
        return StringType()
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
    elif t.startswith('varchar') or t.startswith('char'):
        return StringType()
    else:
        return StringType()


def extract_max_length(type_str: str) -> int:
    m = re.match(r'(?:var)?char\((\d+)\)', type_str.lower().strip())
    return int(m.group(1)) if m else 0


def date_range_for(period: str = "5y") -> tuple[str, str]:
    return ("2020-01-01", "2024-12-31")


def _build_template(max_len: int) -> str:
    if max_len <= 4:
        return "\\n" * max_len
    elif max_len <= 10:
        return "\\x" * max_len
    else:
        prefix = "VAL-"
        return prefix + "\\n" * min(max_len - len(prefix), 16)


def _string_col_kwargs(col_name: str, max_len: int, rows: int) -> dict:
    eff_len = max_len if max_len > 0 else 50
    if col_name.endswith(('_id', '_key', '_code', '_cd', '_nbr', '_num')):
        id_len = min(eff_len, 12)
        if id_len <= 6:
            return {"template": _build_template(id_len), "uniqueValues": min(rows, 10**id_len - 1), "percentNulls": 0.0}
        prefix = re.sub('[^A-Z]', '', col_name.upper())[:3] or 'ID'
        return {"template": prefix + "-" + "\\d" * min(eff_len - len(prefix) - 1, 8), "percentNulls": 0.0}
    if col_name.endswith(('_status', '_type', '_flag', '_ind', '_category')):
        return {"values": ["ACTIVE", "INACTIVE", "PENDING", "UNKNOWN"], "percentNulls": 0.0}
    if 'gender' in col_name or 'sex' in col_name:
        return {"values": ["F", "M", "U"], "percentNulls": 0.0}
    if col_name in ('state', 'state_code', 'st', 'state_cd') or col_name.endswith('_state'):
        return {"values": ["CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "WA"], "percentNulls": 0.0}
    if col_name.endswith(('_name', '_desc', '_description', '_text', '_note')):
        return {"values": ["North Medical", "Summit Health", "Riverside Clinic", "Central Care"], "percentNulls": 0.0}
    if 'email' in col_name:
        return {"values": ["member@example.com", "care@example.com", "claims@example.com"], "percentNulls": 0.0}
    return {"template": _build_template(eff_len), "percentNulls": 0.0}


def base_generator(table_name: str, rows: int, unique_columns: list = None) -> dg.DataGenerator:
    col_types = get_table_col_types(table_name)
    unique_set = set(c.lower() for c in (unique_columns or []))
    gen = dg.DataGenerator(spark, name=table_name, rows=rows, seedColumnName="_id")
    for col_name, type_str in col_types.items():
        ptype = spark_type_for(type_str)
        max_len = extract_max_length(type_str)
        col_lower = col_name.lower()
        needs_unique = col_lower in unique_set
        if ptype == LongType():
            gen = gen.withColumn(col_name, LongType(), minValue=1, maxValue=rows * 10, uniqueValues=rows if needs_unique else min(rows, rows * 10), percentNulls=0.0)
        elif ptype == IntegerType():
            gen = gen.withColumn(col_name, IntegerType(), minValue=1, maxValue=rows * 10, uniqueValues=rows if needs_unique else min(rows, rows * 10), percentNulls=0.0)
        elif ptype == StringType():
            kwargs = _string_col_kwargs(col_lower, max_len, rows)
            if needs_unique:
                kwargs["uniqueValues"] = rows if max_len == 0 else min(rows, 10**min(max_len, 8) - 1)
            gen = gen.withColumn(col_name, StringType(), **kwargs)
        elif ptype == DateType():
            gen = gen.withColumn(col_name, DateType(), begin="2020-01-01", end="2024-12-31", percentNulls=0.0)
        elif ptype == TimestampType():
            gen = gen.withColumn(col_name, TimestampType(), begin="2020-01-01 00:00:00", end="2024-12-31 23:59:59", percentNulls=0.0)
        elif ptype == BooleanType():
            gen = gen.withColumn(col_name, BooleanType(), percentNulls=0.0)
        elif isinstance(ptype, str) and 'decimal' in ptype:
            gen = gen.withColumn(col_name, ptype, minValue=0.0, maxValue=100000.0, percentNulls=0.0)
        else:
            gen = gen.withColumn(col_name, StringType(), template=_build_template(max_len if max_len > 0 else 20), percentNulls=0.0)
    return gen


def enforce_varchar_limits(df, table_name: str):
    col_types = get_table_col_types(table_name)
    for col_name, type_str in col_types.items():
        max_len = extract_max_length(type_str)
        if max_len > 0 and col_name in df.columns:
            df = df.withColumn(col_name, F.substring(F.col(col_name).cast("string"), 1, max_len))
    return df


def with_rn(df):
    return df.withColumn("__rn", F.row_number().over(Window.orderBy(F.monotonically_increasing_id())))

def replace_col(df, col, expr):
    if col in df.columns:
        pos_cols = df.columns
        df = df.drop(col).withColumn(col, expr)
        df = df.select(*pos_cols)
    return df

def write_table(logical, df):
    table_name = TABLES[logical]
    df = df.drop("__rn") if "__rn" in df.columns else df
    df = enforce_varchar_limits(df, table_name)
    spark.sql(f"TRUNCATE TABLE `{CATALOG}`.`{SCHEMA}`.`{table_name}`")
    df.write.mode("append").insertInto(f"`{CATALOG}`.`{SCHEMA}`.`{table_name}`")
    n = spark.table(f"`{CATALOG}`.`{SCHEMA}`.`{table_name}`").count()
    print(f"WROTE {logical}: {n} rows")
    return n

def assert_unique(logical, col):
    t = TABLES[logical]
    r = spark.sql(f"SELECT COUNT(*) total, COUNT(DISTINCT `{col}`) distinct_vals FROM `{CATALOG}`.`{SCHEMA}`.`{t}`").collect()[0]
    if r['total'] != r['distinct_vals']:
        raise Exception(f"FK_TARGET_NOT_UNIQUE: {logical}.{col} total_rows={r['total']} distinct_values={r['distinct_vals']}")
    print(f"UNIQUE OK: {logical}.{col} ({r['total']})")

TABLES = discover_tables()

# COMMAND ----------

# DBTITLE 1,Generate Relationship-Aware Data
ROWS = {
    "dim_address": 200,
    "dim_member": 500,
    "dim_provider": 150,
    "dim_member_identifier": 500,
    "dim_member_history": 500,
    "fact_member_enrollment": 1500,
    "fact_claim_header": 2000,
    "fact_claim_detail": 6000,
}
written = {}

# dim_address
logical = "dim_address"; table = TABLES[logical]
gen = base_generator(table, ROWS[logical], unique_columns=["address_key"])
df = with_rn(gen.build())
df = replace_col(df, "address_key", F.col("__rn").cast("bigint"))
df = replace_col(df, "state", F.expr("element_at(array('CA','TX','NY','FL','IL','PA','OH','GA','NC','WA'), pmod(__rn,10)+1)"))
df = replace_col(df, "city", F.expr("element_at(array('Los Angeles','Houston','New York','Miami','Chicago','Philadelphia','Columbus','Atlanta','Charlotte','Seattle'), pmod(__rn,10)+1)"))
df = replace_col(df, "country_code", F.lit("US"))
df = replace_col(df, "address_type_code", F.expr("element_at(array('HOME','BILL','SERV','MAIL'), pmod(__rn,4)+1)"))
df = replace_col(df, "zip_code", F.format_string("%05d", (F.col("__rn") % 90000) + 10000))
written[logical] = write_table(logical, df)
assert_unique("dim_address", "address_key")

# dim_member
logical = "dim_member"; table = TABLES[logical]
gen = base_generator(table, ROWS[logical], unique_columns=["member_sk"])
df = with_rn(gen.build())
df = replace_col(df, "member_sk", F.col("__rn").cast("bigint"))
df = replace_col(df, "mbr_member_id", F.col("__rn").cast("int"))
df = replace_col(df, "mbr_line_of_business", F.expr("element_at(array('COMMERCIAL','COMMERCIAL','COMMERCIAL','MEDICARE','MEDICARE','MEDICAID','MEDICAID','TRICARE','EXCHANGE','EXCHANGE'), pmod(__rn,10)+1)"))
df = replace_col(df, "mbr_line_of_business_name", F.col("mbr_line_of_business"))
df = replace_col(df, "mbr_state", F.expr("element_at(array('CA','TX','NY','FL','IL','PA','OH','GA','NC','WA'), pmod(__rn,10)+1)"))
df = replace_col(df, "mbr_sex", F.expr("element_at(array('F','M','F','M','F','M','F','M','F','U'), pmod(__rn,10)+1)"))
df = replace_col(df, "mbr_race", F.expr("element_at(array('WHITE','BLACK','ASIAN','HISPANIC','OTHER'), pmod(__rn,5)+1)"))
df = replace_col(df, "mbr_ethnicity", F.expr("element_at(array('NON_HISPANIC','HISPANIC','UNKNOWN'), pmod(__rn,3)+1)"))
df = replace_col(df, "mbr_first_name", F.expr("element_at(array('Alex','Jordan','Taylor','Morgan','Casey','Riley'), pmod(__rn,6)+1)"))
df = replace_col(df, "mbr_last_name", F.expr("element_at(array('Smith','Johnson','Williams','Brown','Jones','Garcia'), pmod(__rn,6)+1)"))
df = replace_col(df, "mbr_full_name", F.concat_ws(" ", F.col("mbr_first_name"), F.col("mbr_last_name")))
df = replace_col(df, "mbr_email", F.concat(F.lit("member"), F.col("__rn"), F.lit("@example.com")))
df = replace_col(df, "mbr_zip_code", F.format_string("%05d", (F.col("__rn") % 90000) + 10000))
written[logical] = write_table(logical, df)
assert_unique("dim_member", "member_sk")

# dim_provider
logical = "dim_provider"; table = TABLES[logical]
gen = base_generator(table, ROWS[logical], unique_columns=["provider_sk"])
df = with_rn(gen.build())
df = replace_col(df, "provider_sk", F.col("__rn").cast("bigint"))
df = replace_col(df, "provider_address_sk", ((F.col("__rn") - 1) % ROWS["dim_address"] + 1).cast("bigint"))
df = replace_col(df, "provider_name", F.concat(F.expr("element_at(array('Summit','Riverside','North','Central','Valley'), pmod(__rn,5)+1)"), F.lit(" Health")))
df = replace_col(df, "provider_npi", F.concat(F.lit("1"), F.format_string("%09d", F.col("__rn"))))
written[logical] = write_table(logical, df)
assert_unique("dim_provider", "provider_sk")

# dim_member_identifier
logical = "dim_member_identifier"; table = TABLES[logical]
gen = base_generator(table, ROWS[logical], unique_columns=["mbr_identifier_sk"])
df = with_rn(gen.build())
df = replace_col(df, "mbr_identifier_sk", F.col("__rn").cast("bigint"))
df = replace_col(df, "member_sk", ((F.col("__rn") - 1) % ROWS["dim_member"] + 1).cast("bigint"))
df = replace_col(df, "id_type", F.expr("element_at(array('MEMBER_ID','INSURED_ID','DEERS_ID'), pmod(__rn,3)+1)"))
df = replace_col(df, "id_value", F.concat(F.lit("MBR"), F.format_string("%09d", F.col("member_sk"))))
written[logical] = write_table(logical, df)
assert_unique("dim_member_identifier", "mbr_identifier_sk")

# dim_member_history
logical = "dim_member_history"; table = TABLES[logical]
gen = base_generator(table, ROWS[logical], unique_columns=["mbr_history_sk"])
df = with_rn(gen.build())
df = replace_col(df, "mbr_history_sk", F.col("__rn").cast("bigint"))
df = replace_col(df, "member_sk", ((F.col("__rn") - 1) % ROWS["dim_member"] + 1).cast("bigint"))
df = replace_col(df, "mbr_line_of_business", F.expr("element_at(array('COMMERCIAL','MEDICARE','MEDICAID','TRICARE','EXCHANGE'), pmod(__rn,5)+1)"))
written[logical] = write_table(logical, df)
assert_unique("dim_member_history", "mbr_history_sk")

# fact_member_enrollment
logical = "fact_member_enrollment"; table = TABLES[logical]
gen = base_generator(table, ROWS[logical], unique_columns=["enrollment_sk"])
df = with_rn(gen.build())
df = replace_col(df, "enrollment_sk", F.concat(F.lit("ENR"), F.format_string("%09d", F.col("__rn"))))
df = replace_col(df, "member_sk", ((F.col("__rn") - 1) % ROWS["dim_member"] + 1).cast("bigint"))
df = replace_col(df, "mbr_enr_status", F.expr("element_at(array('ACTIVE','ACTIVE','ACTIVE','TERMINATED','PENDING'), pmod(__rn,5)+1)"))
df = replace_col(df, "mbr_enr_line_of_business", F.expr("element_at(array('COMMERCIAL','COMMERCIAL','MEDICARE','MEDICAID','TRICARE','EXCHANGE'), pmod(__rn,6)+1)"))
df = replace_col(df, "id_type", F.lit("MEMBER_ID"))
df = replace_col(df, "id_value", F.concat(F.lit("MBR"), F.format_string("%09d", F.col("member_sk"))))
written[logical] = write_table(logical, df)
assert_unique("fact_member_enrollment", "enrollment_sk")

# fact_claim_header
logical = "fact_claim_header"; table = TABLES[logical]
gen = base_generator(table, ROWS[logical], unique_columns=["clm_header_sk", "clm_claim_id"])
df = with_rn(gen.build())
df = replace_col(df, "clm_header_sk", F.col("__rn").cast("bigint"))
df = replace_col(df, "clm_claim_id", F.concat(F.lit("CLM"), F.format_string("%09d", F.col("__rn"))))
df = replace_col(df, "clm_member_sk", ((F.col("__rn") - 1) % ROWS["dim_member"] + 1).cast("bigint"))
df = replace_col(df, "clm_service_facility_address_sk", ((F.col("__rn") - 1) % ROWS["dim_address"] + 1).cast("bigint"))
df = replace_col(df, "clm_line_of_business", F.expr("element_at(array('COMMERCIAL','COMMERCIAL','COMMERCIAL','MEDICARE','MEDICARE','MEDICAID','MEDICAID','TRICARE','EXCHANGE','EXCHANGE'), pmod(__rn,10)+1)"))
df = replace_col(df, "clm_claim_type", F.expr("element_at(array('PROFESSIONAL','PROFESSIONAL','INSTITUTIONAL','PHARMACY','PHARMACY','DENTAL','VISION'), pmod(__rn,7)+1)"))
df = replace_col(df, "clm_member_name", F.concat(F.lit("Member "), F.col("clm_member_sk")))
written[logical] = write_table(logical, df)
assert_unique("fact_claim_header", "clm_header_sk")
assert_unique("fact_claim_header", "clm_claim_id")

# fact_claim_detail
logical = "fact_claim_detail"; table = TABLES[logical]
gen = base_generator(table, ROWS[logical], unique_columns=["clm_dtl_claim_id", "clm_dtl_line_nbr"])
df = with_rn(gen.build())
claim_num = ((F.col("__rn") - 1) % ROWS["fact_claim_header"] + 1)
line_num = (F.floor((F.col("__rn") - 1) / ROWS["fact_claim_header"]) + 1).cast("int")
df = replace_col(df, "clm_dtl_claim_id", F.concat(F.lit("CLM"), F.format_string("%09d", claim_num)))
df = replace_col(df, "clm_dtl_line_nbr", F.format_string("%03d", line_num))
df = replace_col(df, "clm_dtl_claim_type", F.expr("element_at(array('PROFESSIONAL','PROFESSIONAL','INSTITUTIONAL','PHARMACY','PHARMACY','DENTAL','VISION'), pmod(__rn,7)+1)"))
df = replace_col(df, "clm_dtl_line_status", F.expr("element_at(array('APPROVED','APPROVED','APPROVED','DENIED','PENDING','IN_REVIEW'), pmod(__rn,6)+1)"))
df = replace_col(df, "clm_dtl_adjudication_status", F.col("clm_dtl_line_status"))
df = replace_col(df, "clm_dtl_clean_claim_ind", F.expr("case when pmod(__rn,10) < 8 then 'Y' else 'N' end"))
df = replace_col(df, "clm_dtl_participating_provider", F.expr("case when pmod(__rn,10) < 8 then 'PAR' else 'NON_PAR' end"))
base_paid = F.expr("case clm_dtl_claim_type when 'INSTITUTIONAL' then 25000 + pmod(__rn,55000) when 'PHARMACY' then 50 + pmod(__rn,900) when 'DENTAL' then 80 + pmod(__rn,1200) when 'VISION' then 25 + pmod(__rn,500) else 100 + pmod(__rn,3000) end")
for amt_col, factor in [("clm_dtl_paid_amt",1.0),("clm_dtl_actual_paid_amt",1.0),("clm_dtl_allowed_amt",1.15),("clm_dtl_billed_amt",1.45),("clm_dtl_net_amt",1.0),("clm_dtl_copay_amt",0.05),("clm_dtl_deduct_amt",0.08),("clm_dtl_not_covered_amt",0.04)]:
    if amt_col in df.columns:
        df = replace_col(df, amt_col, (base_paid * F.lit(factor)).cast(get_table_col_types(table)[amt_col]))
df = replace_col(df, "clm_dtl_place_of_service", F.expr("element_at(array('11','21','22','23','12'), pmod(__rn,5)+1)"))
df = replace_col(df, "clm_dtl_procedure_code", F.concat(F.lit("CPT"), F.format_string("%05d", (F.col("__rn") % 90000) + 10000)))
written[logical] = write_table(logical, df)

print("SYNTHETIC_ROWS", written, "TOTAL", sum(written.values()))

