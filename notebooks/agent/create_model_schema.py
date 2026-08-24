# Databricks notebook source
# MAGIC %md
# MAGIC # Create Model Schema
# MAGIC Ensures the Unity Catalog schema for registered models exists.

# COMMAND ----------

catalog_name = dbutils.widgets.get("catalog_name")
model_schema = dbutils.widgets.get("model_schema")

print(f"Ensuring schema: {catalog_name}.{model_schema}")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog_name}.{model_schema}")
print(f"Schema {catalog_name}.{model_schema} ready.")

