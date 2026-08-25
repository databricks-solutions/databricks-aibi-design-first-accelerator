# Databricks notebook source
# DBTITLE 1,Synthetic Data — member_claims
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

# --- Safety: disable ANSI mode to prevent DIVIDE_BY_ZERO in dbldatagen ---
# dbldatagen internally performs arithmetic (weight/distribution calculations)
# that can intermittently produce division-by-zero with small row counts.
# Disabling ANSI mode converts these to NULL instead of throwing.
spark.conf.set("spark.sql.ansi.enabled", "false")

# IMPORTANT: Do NOT set any spark.databricks.delta.* configurations.
# They are NOT supported on serverless compute and will raise CONFIG_NOT_AVAILABLE.
# If you need schema merge, use .option("mergeSchema", "true") on the write instead.

# --- Safety patch: auto-fix known dbldatagen issues ---
# 1. BooleanType + values=[True,False] causes DATATYPE_MISMATCH in CASE expression
#    (dbldatagen stringifies the ELSE fallback → type mismatch). Strip values/weights.
# 2. TimestampType + date-only strings → ValueError. Auto-append time component.
_orig_withColumn = dg.DataGenerator.withColumn
def _safe_withColumn(self, colName, colType, *args, **kwargs):
    # Fix BooleanType: remove values/weights to prevent DATATYPE_MISMATCH
    if colType == BooleanType() or colType is BooleanType:
        kwargs.pop('values', None)
        kwargs.pop('weights', None)
    # Fix TimestampType: auto-append time component to date-only strings
    if colType == TimestampType() or colType is TimestampType or str(colType).lower() in ('timestamp', 'timestamp_ntz'):
        for key in ('begin', 'end'):
            if key in kwargs and isinstance(kwargs[key], str) and len(kwargs[key]) == 10:
                kwargs[key] = f"{kwargs[key]} 00:00:00" if key == 'begin' else f"{kwargs[key]} 23:59:59"
    return _orig_withColumn(self, colName, colType, *args, **kwargs)
dg.DataGenerator.withColumn = _safe_withColumn

CATALOG = "aw_serverless_stable_catalog"
SCHEMA = "aibi_member_claims"
VERSION_SUFFIX = "_v3"  # e.g. "_v1", "_v2", or "" for unversioned



def discover_tables() -> dict:
    """Discover all tables belonging to THIS version in the schema.
    Returns {logical_name: actual_table_name} e.g. {"dim_example": "dim_example_v1"}.
    Filters by VERSION_SUFFIX so multiple versions can coexist in the same schema."""
    all_tables = [row.tableName for row in spark.sql(f"SHOW TABLES IN `{CATALOG}`.`{SCHEMA}`").collect()]
    version_tables = [t for t in all_tables if t.endswith(VERSION_SUFFIX)] if VERSION_SUFFIX else all_tables
    # Map logical name (without suffix) to actual name (with suffix)
    result = {}
    for t in version_tables:
        logical = t[:-len(VERSION_SUFFIX)] if VERSION_SUFFIX else t
        result[logical] = t
    print(f"Discovered {len(result)} tables for version '{VERSION_SUFFIX}': {list(result.values())}")
    return result


def get_table_col_types(table_name: str) -> dict:
    """Read actual DDL column types from the catalog. Returns {col_name: spark_type_str}.
    Pass the ACTUAL table name (with version suffix, e.g. 'dim_example_v1').

    IMPORTANT: Uses DESCRIBE TABLE (not DataFrame.schema) to preserve VARCHAR(N)
    length metadata. DataFrame.schema.simpleString() returns 'string' for all
    VARCHAR columns, losing the length constraint. DESCRIBE TABLE returns the
    original DDL type like 'varchar(35)' which is needed by extract_max_length()."""
    rows = spark.sql(f"DESCRIBE TABLE `{CATALOG}`.`{SCHEMA}`.`{table_name}`").collect()
    result = {}
    for row in rows:
        col_name = row['col_name'].strip()
        data_type = row['data_type'].strip()
        # DESCRIBE TABLE includes partition info and blank rows after columns — stop at first empty/# row
        if not col_name or col_name.startswith('#') or not data_type:
            break
        result[col_name] = data_type
    return result


def spark_type_for(type_str: str):
    """Map DDL type string to dbldatagen-compatible PySpark type.
    RULE: BIGINT/INT/LONG → LongType(), never StringType() with prefixed patterns."""
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
        return t  # pass as string for dbldatagen
    elif t.startswith('varchar') or t.startswith('char'):
        return StringType()  # handled via max_length in base_generator
    else:
        return StringType()  # safe fallback


def extract_max_length(type_str: str) -> int:
    """Extract max length from VARCHAR(N) or CHAR(N). Returns 0 if not constrained."""
    import re
    m = re.match(r'(?:var)?char\((\d+)\)', type_str.lower().strip())
    return int(m.group(1)) if m else 0


def date_range_for(type_str: str, begin: str, end: str) -> dict:
    """Return correct begin/end format based on column type.
    - DateType: use 'YYYY-MM-DD'
    - TimestampType: use 'YYYY-MM-DD HH:MM:SS'
    CRITICAL: dbldatagen raises ValueError if timestamp columns get date-only strings."""
    t = type_str.lower()
    if t in ('timestamp', 'timestamp_ntz'):
        # Ensure timestamp format
        if len(begin) == 10:  # date-only like '2024-01-01'
            begin = f"{begin} 00:00:00"
        if len(end) == 10:
            end = f"{end} 23:59:59"
    return {"begin": begin, "end": end}


def base_generator(table_name: str, rows: int, unique_columns: list = None) -> dg.DataGenerator:
    """Create a DataGenerator pre-configured with CORRECT types from DDL.
    This guarantees no CAST_INVALID_INPUT errors by reading actual column types.
    Generates ALL columns — do NOT call withColumn() after this (causes duplicates).

    CRITICAL: Respects VARCHAR(N) length constraints to prevent
    DELTA_EXCEED_CHAR_VARCHAR_LIMIT errors. Uses column naming conventions
    to generate semantically appropriate data.

    Args:
        table_name: Actual table name (with version suffix)
        rows: Number of rows to generate
        unique_columns: List of column names that MUST have unique values.
                        Use for PK columns and any column that is an FK target
                        from another table. Ensures uniqueValues=rows for these columns.
                        Example: ["provider_npi", "member_id"]
    """
    col_types = get_table_col_types(table_name)
    unique_set = set(c.lower() for c in (unique_columns or []))
    gen = dg.DataGenerator(spark, name=table_name, rows=rows, seedColumnName="_id")
    for col_name, type_str in col_types.items():
        ptype = spark_type_for(type_str)
        max_len = extract_max_length(type_str)
        col_lower = col_name.lower()
        needs_unique = col_lower in unique_set

        if ptype == LongType():
            gen = gen.withColumn(col_name, LongType(), minValue=1, maxValue=rows * 10, uniqueValues=rows, percentNulls=0.0)
        elif ptype == IntegerType():
            if needs_unique:
                gen = gen.withColumn(col_name, IntegerType(), minValue=1, maxValue=rows * 10, uniqueValues=rows, percentNulls=0.0)
            else:
                gen = gen.withColumn(col_name, IntegerType(), minValue=1, maxValue=rows, percentNulls=0.0)
        elif ptype == StringType():
            # If column must be unique (PK or FK target), force uniqueValues
            kwargs = _string_col_kwargs(col_lower, max_len, rows)
            if needs_unique:
                # CRITICAL: cap uniqueValues to what the value space allows.
                # For VARCHAR(N), a digit template can produce at most 10^N - 1 unique values.
                # Exceeding this makes dbldatagen ignore the template → longer values.
                if max_len > 0:
                    max_possible = 10**max_len - 1
                    kwargs["uniqueValues"] = min(rows, max_possible)
                else:
                    kwargs["uniqueValues"] = rows
            gen = gen.withColumn(col_name, StringType(), **kwargs)
        elif ptype == DateType():
            gen = gen.withColumn(col_name, DateType(), begin="2020-01-01", end="2024-12-31", percentNulls=0.0)
        elif ptype == TimestampType():
            gen = gen.withColumn(col_name, TimestampType(), begin="2020-01-01 00:00:00", end="2024-12-31 23:59:59", percentNulls=0.0)
        elif ptype == BooleanType():
            # NEVER use values=[True, False] for BooleanType — dbldatagen's internal
            # CASE expression stringifies the ELSE fallback causing DATATYPE_MISMATCH.
            gen = gen.withColumn(col_name, BooleanType(), percentNulls=0.0)
        elif ptype == DoubleType():
            if needs_unique:
                gen = gen.withColumn(col_name, DoubleType(), minValue=0.0, maxValue=rows * 100.0, uniqueValues=rows, percentNulls=0.0)
            else:
                gen = gen.withColumn(col_name, DoubleType(), minValue=0.0, maxValue=10000.0, percentNulls=0.0)
        elif isinstance(ptype, str) and 'decimal' in ptype:
            gen = gen.withColumn(col_name, ptype, minValue=0.0, maxValue=100000.0, percentNulls=0.0)
        else:
            eff_len = max_len if max_len > 0 else 20
            kwargs = {"template": _build_template(eff_len), "percentNulls": 0.0}
            if needs_unique:
                kwargs["uniqueValues"] = rows
            gen = gen.withColumn(col_name, StringType(), **kwargs)
    return gen


def _string_col_kwargs(col_name: str, max_len: int, rows: int) -> dict:
    """Build dbldatagen kwargs for a string column based on name semantics and length.

    Uses column naming conventions to produce meaningful sample data:
    - *_id, *_key, *_code: short alphanumeric identifiers
    - *_name, *_desc: readable text capped to max_len
    - *_status, *_type, *_flag: values from small sets
    - Everything else: safe template capped to max_len
    """
    eff_len = max_len if max_len > 0 else 50  # default cap if no VARCHAR constraint

    # ID / Key / Code columns → short unique identifiers
    if col_name.endswith(('_id', '_key', '_code', '_cd', '_nbr', '_num')):
        id_len = min(eff_len, 12)
        # CRITICAL: cap uniqueValues to what the template can actually produce.
        # A template of N digits can produce at most 10^N - 1 unique values.
        # If uniqueValues exceeds this, dbldatagen ignores the template and
        # generates longer strings → DELTA_EXCEED_CHAR_VARCHAR_LIMIT.
        max_unique_for_template = 10**id_len - 1
        capped_unique = min(rows, max_unique_for_template)
        if id_len <= 6:
            return {"template": _build_template(id_len), "uniqueValues": capped_unique, "percentNulls": 0.0}
        else:
            prefix = col_name[:3].upper()
            tpl_len = eff_len - len(prefix) - 1
            return {"template": prefix + "-" + "\\d" * min(tpl_len, 8), "percentNulls": 0.0}

    # Status / Type / Flag columns → categorical values
    if col_name.endswith(('_status', '_type', '_flag', '_ind', '_category')):
        return {"values": ["A", "B", "C", "D"], "percentNulls": 0.0}

    # Gender / Sex columns
    if 'gender' in col_name or 'sex' in col_name:
        return {"values": ["M", "F", "U"], "percentNulls": 0.0}

    # State / Region columns
    if col_name in ('state', 'state_code', 'st', 'state_cd'):
        return {"values": ["CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI"], "percentNulls": 0.0}

    # Name columns → readable text
    if col_name.endswith(('_name', '_desc', '_description', '_text', '_note')):
        return {"template": _build_template(eff_len), "percentNulls": 0.0}

    # Email columns
    if 'email' in col_name:
        tpl = "\\w" + "@" + "\\w" + ".com"
        return {"template": tpl[:eff_len] if len(tpl) > eff_len else tpl, "percentNulls": 0.0}

    # Default: safe capped template
    return {"template": _build_template(eff_len), "percentNulls": 0.0}


def _build_template(max_len: int) -> str:
    """Build a dbldatagen template string that stays within max_len characters.
    Uses \\n (digits) instead of \\w (words) to ensure predictable length.
    Each \\n generates exactly 1 digit; each \\x generates 1 hex char."""
    if max_len <= 4:
        return "\\n" * max_len
    elif max_len <= 10:
        return "\\x" * max_len
    else:
        # Mix of fixed prefix + digits to keep under limit
        # e.g., for max_len=20: "VAL-" + 16 digits = 20 chars
        prefix = "VAL-"
        remaining = max_len - len(prefix)
        return prefix + "\\n" * min(remaining, 16)


def enforce_varchar_limits(df, table_name: str):
    """CRITICAL SAFETY NET: Truncate ALL VARCHAR/CHAR columns to their declared max length.

    This MUST be called on every DataFrame AFTER build() and AFTER any FK replacement,
    right before writing to Delta. It prevents DELTA_EXCEED_CHAR_VARCHAR_LIMIT errors
    regardless of how values were generated (template overflow, FK replacement, uniqueValues
    forcing longer values, etc.).

    Usage:
        df = gen.build()
        df = fix_fk_columns(df)       # optional FK patching
        df = enforce_varchar_limits(df, table_name)  # ALWAYS before write
        df.write.format("delta").mode("append").saveAsTable(...)
    """
    from pyspark.sql import functions as F
    col_types = get_table_col_types(table_name)
    for col_name, type_str in col_types.items():
        max_len = extract_max_length(type_str)
        if max_len > 0 and col_name in df.columns:
            df = df.withColumn(col_name, F.substring(F.col(col_name).cast("string"), 1, max_len))
    return df


# Discover tables for this version — use TABLES dict for all references
TABLES = discover_tables()

# COMMAND ----------

# DBTITLE 1,Generate Data — Relationship-aware member claims dataset
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from itertools import chain

ROWS = {
    "dim_member": 500,
    "dim_address": 350,
    "dim_provider": 300,
    "dim_member_identifier": 800,
    "dim_member_history": 1000,
    "fact_member_enrollment": 2000,
    "fact_claim_header": 3000,
    "fact_claim_detail": 9000,
}

LOB_VALUES = ["COMMERCIAL", "MEDICARE", "MEDICAID", "TRICARE", "EXCHANGE"]
STATE_VALUES = ["CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "AZ", "WA"]
CLAIM_TYPES = ["INSTITUTIONAL", "PROFESSIONAL", "PHARMACY", "DENTAL", "VISION"]
FIRST_NAMES = ["Ava", "Liam", "Noah", "Mia", "Emma", "Olivia", "Elijah", "Sophia", "James", "Amelia"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Wilson", "Anderson"]
PROVIDER_NAMES = ["North Valley Medical", "Summit Health", "Lakeside Clinic", "Community Care", "Metro Physician Group", "Evergreen Hospital"]
CITY_VALUES = ["Los Angeles", "Houston", "New York", "Miami", "Chicago", "Philadelphia", "Columbus", "Atlanta", "Charlotte", "Phoenix", "Seattle"]

def sequence_df(df, col_name, prefix=None, width=9):
    w = Window.orderBy(F.monotonically_increasing_id())
    df = df.withColumn("__rn", F.row_number().over(w))
    if prefix:
        df = df.withColumn(col_name, F.concat(F.lit(prefix), F.lpad(F.col("__rn").cast("string"), width, "0")))
    else:
        df = df.withColumn(col_name, F.col("__rn").cast("long"))
    return df.drop("__rn")

def cycle_value(values):
    arr = F.array([F.lit(v) for v in values])
    return F.element_at(arr, ((F.monotonically_increasing_id() % len(values)) + 1).cast("int"))

def sample_parent(df, target_col, values, cast_type=None):
    arr = F.array([F.lit(v) for v in values])
    c = F.element_at(arr, ((F.monotonically_increasing_id() % len(values)) + 1).cast("int"))
    if cast_type:
        c = c.cast(cast_type)
    return df.withColumn(target_col, c)

def save_df(df, logical):
    table_name = TABLES[logical]
    df = enforce_varchar_limits(df, table_name)
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "false").saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")
    print(f"Wrote {logical}: {df.count()} rows")

for logical in ROWS:
    spark.sql(f"TRUNCATE TABLE `{CATALOG}`.`{SCHEMA}`.`{TABLES[logical]}`")

# dim_member
mt = TABLES["dim_member"]
gen = base_generator(mt, ROWS["dim_member"], unique_columns=["member_sk"])
df = gen.build()
df = sequence_df(df, "member_sk")
df = df.withColumn("mbr_member_id", F.col("member_sk").cast("int"))
df = df.withColumn("mbr_source_member_id", F.concat(F.lit("MBR"), F.lpad(F.col("member_sk").cast("string"), 8, "0")))
df = df.withColumn("mbr_first_name", cycle_value(FIRST_NAMES)).withColumn("mbr_last_name", cycle_value(LAST_NAMES))
df = df.withColumn("mbr_full_name", F.concat_ws(" ", F.col("mbr_first_name"), F.col("mbr_last_name")))
df = df.withColumn("mbr_sex", cycle_value(["F", "M", "U"]))
df = df.withColumn("mbr_race", cycle_value(["WHITE", "BLACK", "ASIAN", "HISPANIC", "OTHER", "UNKNOWN"]))
df = df.withColumn("mbr_ethnicity", cycle_value(["HISPANIC", "NON_HISPANIC", "UNKNOWN"]))
df = df.withColumn("mbr_marital_status", cycle_value(["SINGLE", "MARRIED", "DIVORCED", "WIDOWED"]))
df = df.withColumn("mbr_line_of_business", cycle_value(LOB_VALUES)).withColumn("mbr_line_of_business_name", F.col("mbr_line_of_business"))
df = df.withColumn("mbr_state", cycle_value(STATE_VALUES)).withColumn("mbr_zip_code", F.lpad((90000 + (F.col("member_sk") % 9999)).cast("string"), 5, "0"))
df = df.withColumn("mbr_email", F.concat(F.lower(F.col("mbr_first_name")), F.lit("."), F.lower(F.col("mbr_last_name")), F.lit("@example-health.com")))
df = df.withColumn("mbr_phone_nbr", F.concat(F.lit("555"), F.lpad((F.col("member_sk") % 10000000).cast("string"), 7, "0")))
df = df.withColumn("mbr_deceased_flag", F.lit("N")).withColumn("is_active", F.lit(True))
save_df(df, "dim_member")
member_keys = [r[0] for r in spark.table(f"{CATALOG}.{SCHEMA}.{mt}").select("member_sk").collect()]

# dim_address
at = TABLES["dim_address"]
gen = base_generator(at, ROWS["dim_address"], unique_columns=["address_key"])
df = sequence_df(gen.build(), "address_key")
df = sample_parent(df, "entity_dimension_key", member_keys, "long")
df = df.withColumn("entity_type_key", F.lit("MEMBER")).withColumn("address_type_code", cycle_value(["HOME", "MAILING", "BILLING"]))
df = df.withColumn("street_address_1", F.concat(F.lit("100 "), cycle_value(["Main St", "Oak Ave", "Pine Rd", "Market St", "Lake Dr"])))
df = df.withColumn("city", cycle_value(CITY_VALUES)).withColumn("state", cycle_value(STATE_VALUES)).withColumn("country_code", F.lit("US"))
df = df.withColumn("zip_code", F.lpad((10000 + (F.col("address_key") % 89999)).cast("string"), 5, "0"))
df = df.withColumn("is_active", F.lit(True))
save_df(df, "dim_address")
address_keys = [r[0] for r in spark.table(f"{CATALOG}.{SCHEMA}.{at}").select("address_key").collect()]

# dim_provider
pt = TABLES["dim_provider"]
gen = base_generator(pt, ROWS["dim_provider"], unique_columns=["provider_sk", "provider_npi"])
df = sequence_df(gen.build(), "provider_sk")
df = df.withColumn("provider_npi", F.concat(F.lit("1"), F.lpad(F.col("provider_sk").cast("string"), 9, "0")))
df = sample_parent(df, "provider_address_sk", address_keys, "long")
df = sample_parent(df, "assigned_provider_sk", list(range(1, ROWS["dim_provider"] + 1)), "long")
df = df.withColumn("provider_name", cycle_value(PROVIDER_NAMES)).withColumn("source_provider_id", F.concat(F.lit("PRV"), F.lpad(F.col("provider_sk").cast("string"), 7, "0")))
df = df.withColumn("provider_tax_id", F.concat(F.lit("TAX"), F.lpad(F.col("provider_sk").cast("string"), 6, "0"))).withColumn("pcp_flag", (F.col("provider_sk") % 4 == 0))
df = df.withColumn("is_active", F.lit(True))
save_df(df, "dim_provider")
provider_npis = [r[0] for r in spark.table(f"{CATALOG}.{SCHEMA}.{pt}").select("provider_npi").collect()]
provider_keys = [r[0] for r in spark.table(f"{CATALOG}.{SCHEMA}.{pt}").select("provider_sk").collect()]

# FK target uniqueness checks before child generation
for tbl, col in [("dim_member", "member_sk"), ("dim_address", "address_key"), ("dim_provider", "provider_sk"), ("dim_provider", "provider_npi")]:
    row = spark.sql(f"SELECT COUNT(*) total, COUNT(DISTINCT `{col}`) distinct_vals FROM `{CATALOG}`.`{SCHEMA}`.`{TABLES[tbl]}`").first()
    if row.total != row.distinct_vals:
        raise ValueError(f"FK_TARGET_NOT_UNIQUE: {tbl}.{col} total_rows={row.total} distinct_values={row.distinct_vals}")

# dim_member_identifier
it = TABLES["dim_member_identifier"]
gen = base_generator(it, ROWS["dim_member_identifier"], unique_columns=["mbr_identifier_sk", "id_type", "id_value"])
df = sequence_df(gen.build(), "mbr_identifier_sk")
df = sample_parent(df, "member_sk", member_keys, "long")
df = df.withColumn("id_type", cycle_value(["MEMBER_ID", "DEERS_ID", "ALT_ID", "POLICY_ID"]))
df = df.withColumn("id_value", F.concat(F.col("id_type"), F.lit("-"), F.lpad(F.col("mbr_identifier_sk").cast("string"), 9, "0")))
df = df.withColumn("is_active", F.lit(True))
save_df(df, "dim_member_identifier")
identifier_pairs = [(r[0], r[1]) for r in spark.table(f"{CATALOG}.{SCHEMA}.{it}").select("id_type", "id_value").collect()]
row = spark.sql(f"SELECT COUNT(*) total, COUNT(DISTINCT concat(id_type,'|',id_value)) distinct_vals FROM `{CATALOG}`.`{SCHEMA}`.`{it}`").first()
if row.total != row.distinct_vals:
    raise ValueError(f"FK_TARGET_NOT_UNIQUE: dim_member_identifier.(id_type,id_value) total_rows={row.total} distinct_values={row.distinct_vals}")

# dim_member_history
ht = TABLES["dim_member_history"]
gen = base_generator(ht, ROWS["dim_member_history"], unique_columns=["mbr_history_sk"])
df = sequence_df(gen.build(), "mbr_history_sk")
df = sample_parent(df, "member_sk", member_keys, "long")
df = df.withColumn("mbr_line_of_business", cycle_value(LOB_VALUES)).withColumn("mbr_state", cycle_value(STATE_VALUES)).withColumn("is_active", F.col("mbr_history_sk") % 3 == 0)
df = df.withColumn("valid_from_date", F.to_timestamp(F.lit("2022-01-01 00:00:00"))).withColumn("valid_to_date", F.to_timestamp(F.lit("2024-12-31 23:59:59")))
save_df(df, "dim_member_history")

# fact_member_enrollment
et = TABLES["fact_member_enrollment"]
gen = base_generator(et, ROWS["fact_member_enrollment"], unique_columns=["enrollment_sk"])
df = sequence_df(gen.build(), "enrollment_sk", "ENR", 9)
df = sample_parent(df, "member_sk", member_keys, "long")
# sample composite identifier pair deterministically
pair_arr_type = ArrayType(StructType([StructField("id_type", StringType()), StructField("id_value", StringType())]))
pair_literals = F.array([F.struct(F.lit(a).alias("id_type"), F.lit(b).alias("id_value")) for a,b in identifier_pairs])
df = df.withColumn("__pair", F.element_at(pair_literals, ((F.monotonically_increasing_id() % len(identifier_pairs)) + 1).cast("int")))
df = df.withColumn("id_type", F.col("__pair.id_type")).withColumn("id_value", F.col("__pair.id_value")).drop("__pair")
df = df.withColumn("mbr_enr_status", cycle_value(["ACTIVE", "ACTIVE", "ACTIVE", "TERMINATED", "PENDING", "COBRA"]))
df = df.withColumn("mbr_enr_line_of_business", cycle_value(LOB_VALUES)).withColumn("mbr_enr_line_of_business_id", F.substring(F.col("mbr_enr_line_of_business"),1,8))
df = df.withColumn("mbr_enr_group_name", cycle_value(["Acme Employees", "Public Sector", "Senior Advantage", "Family Choice", "Exchange Silver"]))
df = df.withColumn("mbr_enr_subgroup_name", cycle_value(["NORTH", "SOUTH", "EAST", "WEST"]))
df = df.withColumn("is_active", F.col("mbr_enr_status") == "ACTIVE")
save_df(df, "fact_member_enrollment")

# fact_claim_header
ct = TABLES["fact_claim_header"]
gen = base_generator(ct, ROWS["fact_claim_header"], unique_columns=["clm_header_sk", "clm_claim_id"])
df = sequence_df(gen.build(), "clm_header_sk")
df = df.withColumn("clm_id", F.col("clm_header_sk").cast("int"))
df = df.withColumn("clm_claim_id", F.concat(F.lit("CLM"), F.lpad(F.col("clm_header_sk").cast("string"), 9, "0")))
df = sample_parent(df, "clm_member_sk", member_keys, "long")
df = sample_parent(df, "clm_service_facility_address_sk", address_keys, "long")
df = sample_parent(df, "clm_operating_provider_npi", provider_npis, "string")
df = df.withColumn("clm_claim_type", cycle_value(CLAIM_TYPES)).withColumn("clm_line_of_business", cycle_value(LOB_VALUES))
df = df.withColumn("clm_member_name", F.concat(F.lit("Member "), F.col("clm_member_sk"))).withColumn("clm_operating_provider_name", cycle_value(PROVIDER_NAMES))
df = df.withColumn("clm_is_par_referring_provider", F.col("clm_header_sk") % 5 != 0).withColumn("clm_is_par_rendering_provider", F.col("clm_header_sk") % 6 != 0)
df = df.withColumn("is_active", F.lit(True))
save_df(df, "fact_claim_header")
claim_ids = [r[0] for r in spark.table(f"{CATALOG}.{SCHEMA}.{ct}").select("clm_claim_id").collect()]
row = spark.sql(f"SELECT COUNT(*) total, COUNT(DISTINCT clm_claim_id) distinct_vals FROM `{CATALOG}`.`{SCHEMA}`.`{ct}`").first()
if row.total != row.distinct_vals:
    raise ValueError(f"FK_TARGET_NOT_UNIQUE: fact_claim_header.clm_claim_id total_rows={row.total} distinct_values={row.distinct_vals}")

# fact_claim_detail
lt = TABLES["fact_claim_detail"]
gen = base_generator(lt, ROWS["fact_claim_detail"], unique_columns=["clm_dtl_claim_id", "clm_dtl_line_nbr"])
df = gen.build()
w = Window.orderBy(F.monotonically_increasing_id())
df = df.withColumn("__rn", F.row_number().over(w))
claim_arr = F.array([F.lit(v) for v in claim_ids])
df = df.withColumn("clm_dtl_claim_id", F.element_at(claim_arr, (((F.col("__rn") - 1) % len(claim_ids)) + 1).cast("int")))
df = df.withColumn("clm_dtl_line_nbr", F.lpad((((F.col("__rn") - 1) / len(claim_ids)).cast("int") + 1).cast("string"), 3, "0"))
df = df.withColumn("clm_dtl_claim_type", cycle_value(CLAIM_TYPES)).withColumn("clm_dtl_benefit_category", cycle_value(["MEDICAL", "PHARMACY", "BEHAVIORAL", "DENTAL", "VISION"]))
df = df.withColumn("clm_dtl_line_status", cycle_value(["PAID", "PAID", "PAID", "DENIED", "PENDED", "ADJUSTED"]))
df = df.withColumn("clm_dtl_adjudication_status", cycle_value(["APPROVED", "APPROVED", "DENIED", "PENDING", "IN_REVIEW"]))
df = df.withColumn("clm_dtl_clean_claim_ind", F.when(F.col("clm_dtl_line_status") == "PAID", F.lit("Y")).otherwise(F.lit("N")))
base_amt = (F.when(F.col("clm_dtl_claim_type") == "INSTITUTIONAL", F.lit(45000.0))
             .when(F.col("clm_dtl_claim_type") == "PROFESSIONAL", F.lit(650.0))
             .when(F.col("clm_dtl_claim_type") == "PHARMACY", F.lit(350.0))
             .when(F.col("clm_dtl_claim_type") == "DENTAL", F.lit(420.0))
             .otherwise(F.lit(180.0)))
mult = ((F.col("__rn") % 13) + 5) / F.lit(10.0)
df = df.withColumn("clm_dtl_billed_amt", (base_amt * mult * F.lit(1.35)).cast("decimal(27,4)"))
df = df.withColumn("clm_dtl_allowed_amt", (base_amt * mult).cast("decimal(28,4)"))
df = df.withColumn("clm_dtl_paid_amt", F.when(F.col("clm_dtl_line_status") == "DENIED", F.lit(0.0)).otherwise(base_amt * mult * F.lit(0.82)).cast("decimal(28,4)"))
df = df.withColumn("clm_dtl_actual_paid_amt", F.col("clm_dtl_paid_amt").cast("decimal(38,4)"))
df = df.withColumn("clm_dtl_deduct_amt", (base_amt * F.lit(0.05)).cast("decimal(27,4)"))
df = df.withColumn("clm_dtl_copay_amt", (base_amt * F.lit(0.02)).cast("decimal(27,4)"))
df = df.withColumn("clm_dtl_net_amt", F.col("clm_dtl_paid_amt").cast("decimal(28,4)"))
df = df.withColumn("clm_dtl_place_of_service", cycle_value(["11", "21", "22", "23", "31", "81"]))
df = df.withColumn("clm_dtl_procedure_code", cycle_value(["99213", "99214", "93000", "A0428", "J3490", "D0120", "V2020"]))
df = df.withColumn("clm_dtl_procedure_qty", F.lit(1).cast("decimal(15,3)"))
df = df.withColumn("is_active", F.lit(True)).drop("__rn")
save_df(df, "fact_claim_detail")

print("Synthetic member claims data generation complete")

