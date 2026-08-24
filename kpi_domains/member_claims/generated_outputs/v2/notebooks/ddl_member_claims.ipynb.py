# Databricks notebook source
# DBTITLE 1,DDL — member_claims
# Generated from ERD. Edit catalog/schema in accelerator.yaml only.
# Populated from framework/templates/ddl_notebook.py.template; generated cells below consume erd_parsed.yaml.

# COMMAND ----------

# DBTITLE 1,Install dependencies
%pip install dbldatagen pyyaml --quiet
dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Imports
import dbldatagen as dg
import yaml, re

# COMMAND ----------

# DBTITLE 1,Create Tables From Canonical ERD Contract
CATALOG = "aw_serverless_stable_catalog"
SCHEMA = "aibi_member_claims"
VERSION_SUFFIX = "_v2"
ERD_CONTRACT = "/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v2/erd_parsed.yaml"

with open(ERD_CONTRACT, "r") as f:
    contract = yaml.safe_load(f)

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`")

def repair_datatype(c: dict) -> str:
    dt = str(c.get('datatype','string')).strip()
    # YAML flow mappings with unquoted decimal(9,2) can parse as datatype='decimal(9' and key '2)'=None.
    if dt.lower().startswith('decimal(') and not dt.endswith(')'):
        for k in c.keys():
            ks = str(k).strip()
            if ks.endswith(')') and ks[:-1].isdigit():
                dt = dt + ',' + ks
                break
    return dt

def norm_type(t: str) -> str:
    s = str(t).strip().lower().replace(' ', '')
    m = re.match(r"decimal\((\d+),(\d+)\)", s)
    if m:
        return f"DECIMAL({m.group(1)},{m.group(2)})"
    m = re.match(r"varchar\((\d+)\)", s)
    if m:
        return f"VARCHAR({m.group(1)})"
    mapping = {"bigint":"BIGINT", "int":"INT", "integer":"INT", "string":"STRING", "boolean":"BOOLEAN", "date":"DATE", "timestamp":"TIMESTAMP"}
    return mapping.get(s, s.upper())

def q(name: str) -> str:
    return f"`{name}`"

created = []
for table in contract["tables"]:
    logical = table["name"]
    actual = logical + VERSION_SUFFIX
    cols = table["observed"].get("columns", [])
    if not cols:
        raise ValueError(f"No columns in canonical contract for {logical}")
    col_defs = []
    for c in cols:
        col_defs.append(f"  {q(c['name'])} {norm_type(repair_datatype(c))}")
    col_defs_sql = ",\n".join(col_defs)
    ddl = f"""
CREATE OR REPLACE TABLE `{CATALOG}`.`{SCHEMA}`.`{actual}` (
{col_defs_sql}
)
USING DELTA
COMMENT 'Greenfield ERD-derived table for member_claims logical table {logical}; version _v2'
"""
    print(f"Executing DDL for {actual} ({len(cols)} columns)")
    spark.sql(ddl)
    created.append((logical, actual, len(cols)))

print("Created tables:")
for logical, actual, ncols in created:
    print(f"{logical} -> {actual}: {ncols} columns")
print(f"TOTAL_TABLES={len(created)} TOTAL_COLUMNS={sum(x[2] for x in created)}")

