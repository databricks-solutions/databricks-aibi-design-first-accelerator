# Databricks notebook source
# DBTITLE 1,Configure AI Gateway
# MAGIC %md
# MAGIC # Configure AI Gateway for Pipeline Supervisor
# MAGIC
# MAGIC Applies rate limits, inference tables, and guardrails to the AI Gateway endpoint.

# COMMAND ----------

# DBTITLE 1,Setup
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

gateway_endpoint_name = dbutils.widgets.get("gateway_endpoint")
catalog_name = dbutils.widgets.get("catalog_name")

print(f"Configuring AI Gateway: {gateway_endpoint_name}")
print(f"Inference table catalog: {catalog_name}")

# COMMAND ----------

# DBTITLE 1,Apply AI Gateway Configuration
gateway_config = {
    "rate_limits": [
        {
            "key": "endpoint",
            "renewal_period": "minute",
            "calls": 100,
        }
    ],
    "usage_tracking_config": {
        "enabled": True,
    },
    "inference_table_config": {
        "catalog_name": catalog_name,
        "schema_name": "aibi_gateway_logs",
        "table_name_prefix": "pipeline",
        "enabled": True,
    },
    "guardrails": {
        "input": {
            "safety": True,
            "pii": {"behavior": "WARN"},
        },
        "output": {
            "safety": True,
            "pii": {"behavior": "WARN"},
        },
    },
}

try:
    result = w.api_client.do(
        "PUT",
        f"/api/2.0/serving-endpoints/{gateway_endpoint_name}/ai-gateway",
        body=gateway_config,
    )
    print(f"AI Gateway configured successfully")
    print(f"Rate limits: 100 calls/min")
    print(f"Inference tables: {catalog_name}.aibi_gateway_logs.pipeline_*")
    print(f"Guardrails: safety=ON, pii=WARN")
except Exception as e:
    print(f"Warning: AI Gateway config failed (endpoint may not exist yet): {e}")
    print("Deploy the bundle first, then re-run this notebook.")

# COMMAND ----------

# DBTITLE 1,Verify Gateway Health
try:
    endpoint = w.serving_endpoints.get(gateway_endpoint_name)
    print(f"Endpoint: {endpoint.name}")
    print(f"State: {endpoint.state.ready}")
    print(f"Config update: {endpoint.state.config_update}")
except Exception as e:
    print(f"Endpoint not found: {e}")
