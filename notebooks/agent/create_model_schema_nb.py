# Databricks notebook source
# DBTITLE 1,Create Model Schema
# MAGIC %md
# MAGIC # Create Model Schema
# MAGIC Ensures the Unity Catalog schema for registered models exists.

# COMMAND ----------

# DBTITLE 1,Get parameters
catalog_name = dbutils.widgets.get("catalog_name")
model_schema = dbutils.widgets.get("model_schema")

print(f"Ensuring schema: {catalog_name}.{model_schema}")

# COMMAND ----------

# DBTITLE 1,Create schema
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog_name}.{model_schema}")
print(f"Schema {catalog_name}.{model_schema} ready.")
