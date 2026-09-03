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
        bad_patterns = any(v.startswith("PLACEHOLDER") or v.startswith("val_") for v in sample if v)
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
        raise AssertionError(f"[{table_name}] DOMAIN_COLS unmatched {unmatched}; available {sorted(actual_cols.keys())}")
    print(f"validate_domain_cols({table_name}): {len(corrected)} matched")
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
            raise AssertionError(f"[{table_name}] FK col {fk_key} not found; available {sorted(actual_cols.keys())}")
    return corrected

def generate_table(table_name: str, rows: int, domain_cols: dict, pk_cols: list = None, fk_replacements: dict = None, date_range: tuple = ("2020-01-01", "2024-12-31")):
    col_types = get_table_col_types(table_name)
    begin_date, end_date = date_range
    base = spark.range(rows).withColumnRenamed("id", "_row_num")
    df = base
    domain_lower = {k.lower(): k for k in domain_cols.keys()}
    fk_replacements = fk_replacements or {}
    fk_lower = {k.lower(): k for k in fk_replacements.keys()}
    pk_set = set([p.lower() for p in (pk_cols or [])])
    for col_name, type_str in col_types.items():
        t = type_str.lower()
        if col_name.lower() in pk_set:
            if 'bigint' in t:
                expr = (F.col('_row_num') + F.lit(1)).cast('bigint')
            elif 'int' in t:
                expr = (F.col('_row_num') + F.lit(1)).cast('int')
            else:
                prefix = table_name[:3].upper() + '-'
                expr = F.concat(F.lit(prefix), F.lpad((F.col('_row_num') + F.lit(1)).cast('string'), 10, '0'))
        elif col_name.lower() in domain_lower:
            actual_key = domain_lower[col_name.lower()]
            vals, wts = domain_cols[actual_key]
            vals = [str(v) for v in vals] if ('string' in t or 'char' in t) else vals
            expr = F.lit(vals[-1])
            running = 0.0
            thresholds = []
            for wt in wts:
                running += float(wt)
                thresholds.append(running)
            r = F.rand(seed=abs(hash(col_name)) % 10000)
            for i in range(len(vals) - 2, -1, -1):
                expr = F.when(r <= thresholds[i], F.lit(vals[i])).otherwise(expr)
        elif col_name.lower() in fk_lower:
            expr = F.lit(None)
        elif 'bigint' in t:
            expr = (F.col('_row_num') + F.lit(1)).cast('bigint')
        elif 'int' in t:
            expr = ((F.col('_row_num') % F.lit(24)) + F.lit(1)).cast('int')
        elif 'decimal' in t or 'double' in t or 'float' in t:
            expr = (F.rand(seed=abs(hash(col_name)) % 10000) * F.lit(2500.0) + F.lit(25.0)).cast(type_str)
        elif t == 'date':
            expr = F.date_add(F.lit(begin_date).cast('date'), (F.col('_row_num') % F.lit(1460)).cast('int'))
        elif 'timestamp' in t:
            expr = F.to_timestamp(F.date_add(F.lit(begin_date).cast('date'), (F.col('_row_num') % F.lit(1460)).cast('int')))
        elif 'boolean' in t:
            expr = (F.col('_row_num') % F.lit(3) != F.lit(0))
        else:
            expr = F.concat(F.lit(col_name[:8].upper() + '-'), F.lpad((F.col('_row_num') + F.lit(1)).cast('string'), 8, '0'))
        df = df.withColumn(col_name, expr)
    if fk_replacements:
        for fk_col, (parent_table, parent_pk_col) in fk_replacements.items():
            parent_df = spark.table(f"{CATALOG}.{SCHEMA}.{parent_table}").select(F.col(parent_pk_col).alias(fk_col)).distinct()
            parent_count = parent_df.count()
            assert parent_count > 1, f"Parent {parent_table}.{parent_pk_col} has insufficient diversity"
            w = Window.orderBy(F.col(fk_col))
            keyed = parent_df.withColumn('_fk_rn', F.row_number().over(w)).withColumn('_fk_slot', ((F.col('_fk_rn') - 1) % F.lit(parent_count)).cast('long'))
            df = df.drop(fk_col).withColumn('_fk_slot', (F.col('_row_num') % F.lit(parent_count)).cast('long')).join(F.broadcast(keyed.select('_fk_slot', fk_col)), on='_fk_slot', how='left').drop('_fk_slot')
    select_cols = list(col_types.keys())
    return df.select(select_cols)

TABLES = discover_tables()

# COMMAND ----------

# DBTITLE 1,Generate dim_member
if spark.table(f"{CATALOG}.{SCHEMA}.{TABLES['dim_member']}").count() == 0:
    table_name = TABLES['dim_member']
    DOMAIN_COLS = {
        'mbr_sex': (["Female", "Male", "Unknown"], [0.51, 0.47, 0.02]),
        'mbr_race': (["White", "Black or African American", "Asian", "American Indian or Alaska Native", "Native Hawaiian or Pacific Islander", "Other", "Unknown"], [0.52, 0.18, 0.12, 0.03, 0.02, 0.08, 0.05]),
        'mbr_ethnicity': (["Hispanic or Latino", "Not Hispanic or Latino", "Unknown"], [0.18, 0.76, 0.06]),
        'mbr_marital_status': (["Single", "Married", "Divorced", "Widowed", "Separated"], [0.35, 0.42, 0.11, 0.08, 0.04]),
        'mbr_line_of_business': (["Commercial", "Medicare", "Medicaid", "Exchange", "TRICARE"], [0.42, 0.26, 0.22, 0.07, 0.03]),
        'mbr_state': (["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA"], [0.18, 0.15, 0.13, 0.12, 0.11, 0.10, 0.09, 0.12])
    }
    DOMAIN_COLS = validate_domain_cols(table_name, DOMAIN_COLS)
    df = generate_table(table_name, 500, DOMAIN_COLS, pk_cols=['member_sk'])
    df = enforce_varchar_limits(df, table_name)
    verify_before_write(df, table_name, ['member_sk'], [], list(DOMAIN_COLS.keys()))
    df.write.format('delta').mode('append').saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")

# COMMAND ----------

# DBTITLE 1,Generate dim_address
if spark.table(f"{CATALOG}.{SCHEMA}.{TABLES['dim_address']}").count() == 0:
    table_name = TABLES['dim_address']
    DOMAIN_COLS = {
        'entity_type_key': (["MEMBER", "PROVIDER", "FACILITY"], [0.55, 0.30, 0.15]),
        'address_type_code': (["HOME", "MAILING", "BILLING", "SERVICE", "PRACTICE"], [0.38, 0.20, 0.12, 0.15, 0.15]),
        'city': (["Los Angeles", "Houston", "Miami", "New York", "Philadelphia", "Chicago", "Columbus", "Atlanta"], [0.18, 0.15, 0.13, 0.12, 0.11, 0.10, 0.09, 0.12]),
        'state': (["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA"], [0.18, 0.15, 0.13, 0.12, 0.11, 0.10, 0.09, 0.12]),
        'country_code': (["US", "PR", "GU"], [0.96, 0.03, 0.01])
    }
    DOMAIN_COLS = validate_domain_cols(table_name, DOMAIN_COLS)
    FK_REPLACEMENTS = validate_fk_replacements(table_name, {'entity_dimension_key': (TABLES['dim_member'], 'member_sk')})
    df = generate_table(table_name, 500, DOMAIN_COLS, pk_cols=['address_key'], fk_replacements=FK_REPLACEMENTS)
    df = enforce_varchar_limits(df, table_name)
    verify_before_write(df, table_name, ['address_key'], list(FK_REPLACEMENTS.keys()), list(DOMAIN_COLS.keys()))
    df.write.format('delta').mode('append').saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")

# COMMAND ----------

# DBTITLE 1,Generate dim_provider
if spark.table(f"{CATALOG}.{SCHEMA}.{TABLES['dim_provider']}").count() == 0:
    table_name = TABLES['dim_provider']
    DOMAIN_COLS = {'source_system': (["Facets", "QNXT", "Epic", "ProviderOne"], [0.40, 0.30, 0.20, 0.10])}
    DOMAIN_COLS = validate_domain_cols(table_name, DOMAIN_COLS)
    FK_REPLACEMENTS = validate_fk_replacements(table_name, {'provider_address_sk': (TABLES['dim_address'], 'address_key')})
    df = generate_table(table_name, 300, DOMAIN_COLS, pk_cols=['provider_sk'], fk_replacements=FK_REPLACEMENTS)
    df = enforce_varchar_limits(df, table_name)
    verify_before_write(df, table_name, ['provider_sk'], list(FK_REPLACEMENTS.keys()), list(DOMAIN_COLS.keys()))
    df.write.format('delta').mode('append').saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")

# COMMAND ----------

# DBTITLE 1,Generate member dependent tables
for logical, rows, pk, domains in [
    ('dim_member_identifier', 800, 'mbr_identifier_sk', {'id_type': (["Member ID", "Subscriber ID", "Medicaid ID", "Medicare MBI", "DEERS Beneficiary ID"], [0.38, 0.24, 0.18, 0.14, 0.06]), 'source_system_code': (["FACETS", "QNXT", "EPIC", "ELIG"], [0.40, 0.30, 0.20, 0.10])}),
    ('dim_member_history', 1000, 'mbr_history_sk', {'mbr_line_of_business': (["Commercial", "Medicare", "Medicaid", "Exchange", "TRICARE"], [0.42, 0.26, 0.22, 0.07, 0.03]), 'mbr_state': (["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA"], [0.18, 0.15, 0.13, 0.12, 0.11, 0.10, 0.09, 0.12])}),
    ('fact_member_enrollment', 1500, 'enrollment_sk', {'source_system': (["Facets", "QNXT", "Eligibility Hub", "State Exchange"], [0.40, 0.30, 0.20, 0.10]), 'mbr_enr_status': (["Active", "Terminated", "Pending", "Suspended", "COBRA"], [0.68, 0.18, 0.07, 0.04, 0.03]), 'mbr_enr_line_of_business': (["Commercial", "Medicare", "Medicaid", "Exchange", "TRICARE"], [0.42, 0.26, 0.22, 0.07, 0.03]), 'mbr_enr_termination_reason': (["Voluntary Termination", "Nonpayment", "Employer Group Terminated", "Moved Out of Area", "Deceased", "Other Coverage"], [0.30, 0.18, 0.17, 0.14, 0.05, 0.16]), 'id_type': (["Member ID", "Subscriber ID", "Medicaid ID", "Medicare MBI"], [0.42, 0.26, 0.20, 0.12])})
]:
    table_name = TABLES[logical]
    if spark.table(f"{CATALOG}.{SCHEMA}.{table_name}").count() == 0:
        DOMAIN_COLS = validate_domain_cols(table_name, domains)
        FK_REPLACEMENTS = validate_fk_replacements(table_name, {'member_sk': (TABLES['dim_member'], 'member_sk')})
        df = generate_table(table_name, rows, DOMAIN_COLS, pk_cols=[pk], fk_replacements=FK_REPLACEMENTS)
        df = enforce_varchar_limits(df, table_name)
        verify_before_write(df, table_name, [pk], list(FK_REPLACEMENTS.keys()), list(DOMAIN_COLS.keys()))
        df.write.format('delta').mode('append').saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")

# COMMAND ----------

# DBTITLE 1,Generate fact_claim_header
if spark.table(f"{CATALOG}.{SCHEMA}.{TABLES['fact_claim_header']}").count() == 0:
    table_name = TABLES['fact_claim_header']
    DOMAIN_COLS = {
        'clm_claim_type': (["Professional", "Institutional", "Pharmacy", "Dental", "Vision"], [0.44, 0.24, 0.18, 0.09, 0.05]),
        'clm_bill_type': (["Inpatient Hospital", "Outpatient Hospital", "Skilled Nursing", "Home Health", "Clinic"], [0.22, 0.34, 0.10, 0.08, 0.26]),
        'clm_admission_type': (["Emergency", "Urgent", "Elective", "Newborn", "Trauma"], [0.28, 0.20, 0.38, 0.09, 0.05]),
        'clm_admission_source': (["Physician Referral", "Clinic Referral", "Emergency Room", "Transfer", "Court/Law Enforcement"], [0.34, 0.21, 0.25, 0.15, 0.05]),
        'clm_line_of_business': (["Commercial", "Medicare", "Medicaid", "Exchange", "TRICARE"], [0.42, 0.26, 0.22, 0.07, 0.03]),
        'clm_is_par_submitting_provider': (["Participating", "Non-Participating", "Out-of-Network"], [0.72, 0.18, 0.10]),
        'clm_orig_source': (["EDI 837", "Provider Portal", "Paper Claim", "Clearinghouse", "Manual Entry"], [0.54, 0.20, 0.10, 0.12, 0.04])
    }
    DOMAIN_COLS = validate_domain_cols(table_name, DOMAIN_COLS)
    FK_REPLACEMENTS = validate_fk_replacements(table_name, {'clm_member_sk': (TABLES['dim_member'], 'member_sk'), 'clm_service_facility_address_sk': (TABLES['dim_address'], 'address_key')})
    df = generate_table(table_name, 500, DOMAIN_COLS, pk_cols=['clm_header_sk', 'clm_id'], fk_replacements=FK_REPLACEMENTS)
    df = enforce_varchar_limits(df, table_name)
    verify_before_write(df, table_name, ['clm_header_sk', 'clm_id'], list(FK_REPLACEMENTS.keys()), list(DOMAIN_COLS.keys()))
    df.write.format('delta').mode('append').saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")

# COMMAND ----------

# DBTITLE 1,Generate fact_claim_detail
if spark.table(f"{CATALOG}.{SCHEMA}.{TABLES['fact_claim_detail']}").count() == 0:
    table_name = TABLES['fact_claim_detail']
    DOMAIN_COLS = {
        'clm_dtl_benefit_category': (["Medical", "Surgical", "Pharmacy", "Behavioral Health", "Maternity", "Preventive Care"], [0.36, 0.18, 0.17, 0.11, 0.08, 0.10]),
        'clm_dtl_benefit_level': (["In Network", "Out of Network", "Tier 1", "Tier 2", "Emergency"], [0.58, 0.15, 0.12, 0.08, 0.07]),
        'clm_dtl_claim_type': (["Professional", "Institutional", "Pharmacy", "Dental", "Vision"], [0.44, 0.24, 0.18, 0.09, 0.05]),
        'clm_dtl_line_status': (["Paid", "Denied", "Pending", "Adjusted", "Reversed"], [0.68, 0.16, 0.07, 0.06, 0.03]),
        'clm_dtl_clean_claim_ind': (["Clean", "Not Clean", "Requires Review"], [0.74, 0.18, 0.08]),
        'clm_dtl_place_of_service': (["11", "21", "22", "23", "31", "32", "81"], [0.36, 0.13, 0.22, 0.09, 0.07, 0.05, 0.08]),
        'clm_dtl_adjudication_status': (["Auto Adjudicated", "Manual Review", "Denied Medical Necessity", "Pended for Records", "Coordination of Benefits"], [0.58, 0.18, 0.10, 0.08, 0.06]),
        'clm_dtl_procedure_code': (["99213", "99214", "93000", "80053", "J0585", "D0120", "99396"], [0.24, 0.20, 0.12, 0.16, 0.08, 0.09, 0.11])
    }
    DOMAIN_COLS = validate_domain_cols(table_name, DOMAIN_COLS)
    FK_REPLACEMENTS = validate_fk_replacements(table_name, {'clm_dtl_claim_id': (TABLES['fact_claim_header'], 'clm_id')})
    df = generate_table(table_name, 2000, DOMAIN_COLS, pk_cols=['clm_dtl_line_nbr'], fk_replacements=FK_REPLACEMENTS)
    df = df.withColumn('clm_dtl_line_nbr', F.col('clm_dtl_line_nbr').cast('string'))
    df = enforce_varchar_limits(df, table_name)
    verify_before_write(df, table_name, ['clm_dtl_line_nbr'], list(FK_REPLACEMENTS.keys()), list(DOMAIN_COLS.keys()))
    df.write.format('delta').mode('append').saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")

# COMMAND ----------

# DBTITLE 1,Post-generation counts
for logical, actual in TABLES.items():
    cnt = spark.table(f"{CATALOG}.{SCHEMA}.{actual}").count()
    print(logical, actual, cnt)

