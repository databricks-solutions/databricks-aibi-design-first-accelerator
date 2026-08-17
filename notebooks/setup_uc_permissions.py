# Databricks notebook source
# DBTITLE 1,Setup Unity Catalog Permissions for AI/BI Studio App
# Grants the app's service principal access to Unity Catalog resources.
#
# Parameters (passed from job):
#   sp_id: Numeric service_principal_id (from resources.apps.<key>.service_principal_id)
#   catalog_name: Unity Catalog catalog to grant access to
#   action: "create" or "purge" (purge skips this notebook)
#
# Note: Domain schemas (aibi_{domain}) are created at runtime by the SP.
# The SP becomes the owner automatically, so no pre-grants are needed.

dbutils.widgets.text("sp_id", "", "SP Numeric ID")
dbutils.widgets.text("catalog_name", "", "Catalog Name")
dbutils.widgets.text("action", "create", "Action")

sp_id = dbutils.widgets.get("sp_id")
catalog_name = dbutils.widgets.get("catalog_name")
action = dbutils.widgets.get("action").strip().lower()
if action == "purge_and_create":
    action = "create"

if action == "purge":
    print("Action is purge — skipping UC permissions.")
    dbutils.notebook.exit("skipped:purge")

# COMMAND ----------

# DBTITLE 1,Resolve SP application_id from numeric ID
assert sp_id, "sp_id parameter is required"
assert catalog_name, "catalog_name parameter is required"

# Resolve the application_id (UUID) from the numeric service_principal_id.
# UC GRANT statements require the application_id, not the numeric ID.
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
sp = w.service_principals.get(id=sp_id)
sp_application_id = sp.application_id

print(f"SP numeric ID: {sp_id}")
print(f"SP application_id (for GRANT): {sp_application_id}")
print(f"SP display name: {sp.display_name}")
print(f"Catalog: {catalog_name}")

# COMMAND ----------

# DBTITLE 1,Grant catalog-level permissions
spark.sql(f"GRANT USE CATALOG ON CATALOG `{catalog_name}` TO `{sp_application_id}`")
print(f"✓ Granted USE CATALOG on {catalog_name}")

spark.sql(f"GRANT BROWSE ON CATALOG `{catalog_name}` TO `{sp_application_id}`")
print(f"✓ Granted BROWSE on {catalog_name}")

spark.sql(f"GRANT CREATE SCHEMA ON CATALOG `{catalog_name}` TO `{sp_application_id}`")
print(f"✓ Granted CREATE SCHEMA on {catalog_name}")

# COMMAND ----------

# DBTITLE 1,Grant access on existing aibi_* schemas (for clean reruns)
# If schemas from previous runs exist (owned by a different user), the SP
# can't DROP or USE them. Grant ALL PRIVILEGES so the SP can manage them.
# This handles the rerun case where we want clean_start to work.

existing_schemas = [
    row[0] for row in
    spark.sql(f"SHOW SCHEMAS IN `{catalog_name}` LIKE 'aibi_*'").collect()
]

if existing_schemas:
    print(f"Found existing aibi_* schemas: {existing_schemas}")
    for schema in existing_schemas:
        try:
            spark.sql(f"GRANT ALL PRIVILEGES ON SCHEMA `{catalog_name}`.`{schema}` TO `{sp_application_id}`")
            print(f"  ✓ Granted ALL PRIVILEGES on {schema}")
        except Exception as e:
            print(f"  ⚠ Could not grant on {schema}: {str(e)[:80]}")
else:
    print("No existing aibi_* schemas — SP will create and own them at runtime.")

# COMMAND ----------

# DBTITLE 1,Verify permissions
print("\n=== Permission Summary ===")
print(f"SP: {sp_application_id} ({sp.display_name})")
print(f"Catalog: {catalog_name}")
print(f"  - USE CATALOG")
print(f"  - BROWSE")
print(f"  - CREATE SCHEMA")
print(f"\nDomain schemas (aibi_<domain>): SP-owned at runtime or ownership transferred above.")
print("\n✓ UC permissions setup complete")
dbutils.notebook.exit("success")
