# Databricks notebook source
# DBTITLE 1,Install dependencies
%pip install dbldatagen pyyaml --quiet
dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Imports
import dbldatagen
import re

# COMMAND ----------

# DBTITLE 1,DDL — member_claims
# Populated from ddl_notebook.py.template structure. Uses raw erd_parsed.yaml text to preserve decimal(p,s) values in YAML flow mappings.
CATALOG = "aw_serverless_stable_catalog"
SCHEMA = "aibi_member_claims"
VERSION_SUFFIX = "_v3"
ERD_CONTRACT = "/Workspace/Users/arun.wagle@databricks.com/databricks-aibi-design-first-accelerator/kpi_domains/member_claims/generated_outputs/v3/erd_parsed.yaml"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`")

# COMMAND ----------

# DBTITLE 1,Create Tables
raw = open(ERD_CONTRACT, "r").read().splitlines()

def normalize_type(dtype):
    d = str(dtype).strip().lower().strip('"\'')
    if d in ("bigint", "int", "integer", "string", "boolean", "date", "timestamp") or re.match(r"decimal\(\d+,\d+\)$", d) or re.match(r"var?char\(\d+\)$", d) or re.match(r"char\(\d+\)$", d):
        return d
    return "string"

tables = []
current = None
in_observed = False
in_columns = False
in_inferred = False
for line in raw:
    if re.match(r"^  - name: ", line):
        if current:
            tables.append(current)
        current = {"name": line.split(":",1)[1].strip(), "columns": []}
        in_observed = in_columns = in_inferred = False
    elif current and re.match(r"^    observed:", line):
        in_observed = True; in_inferred = False
    elif current and re.match(r"^    inferred:", line):
        in_inferred = True; in_observed = False; in_columns = False
    elif current and in_observed and re.match(r"^      columns:", line):
        in_columns = True
    elif current and in_columns and "- {name:" in line:
        m = re.search(r"name:\s*([^,}]+),\s*datatype:\s*(.*?),\s*nullable:", line)
        if not m:
            raise ValueError(f"Cannot parse column line: {line}")
        current["columns"].append({"name": m.group(1).strip(), "datatype": m.group(2).strip()})
if current:
    tables.append(current)

created = []
columns_total = 0
for table in tables:
    logical = table["name"]
    actual = logical + VERSION_SUFFIX
    seen = set(); col_defs = []
    for col in table["columns"]:
        cname = col["name"]
        if cname in seen:
            raise ValueError(f"Duplicate column in ERD contract: {logical}.{cname}")
        seen.add(cname)
        col_defs.append(f"  `{cname}` {normalize_type(col['datatype'])}")
    ddl = f"CREATE OR REPLACE TABLE `{CATALOG}`.`{SCHEMA}`.`{actual}` (\n" + ",\n".join(col_defs) + "\n) USING DELTA"
    spark.sql(ddl)
    created.append(actual)
    columns_total += len(table["columns"])
    print(f"Created {CATALOG}.{SCHEMA}.{actual} with {len(table['columns'])} columns")
print({"tables_created": len(created), "columns_total": columns_total, "tables": created})

