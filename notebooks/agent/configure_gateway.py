# Databricks notebook source
# MAGIC %md
# MAGIC # Configure AI Gateway for Pipeline Supervisor
# MAGIC
# MAGIC Applies rate limits, inference tables, and guardrails to the
# MAGIC AI Gateway endpoint after bundle deployment.
# MAGIC
# MAGIC Run: `databricks bundle run deploy_agent -t dev` (which calls this as a step)
# MAGIC Or run standalone after `databricks bundle deploy -t dev`

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# COMMAND ----------

# Parameters
gateway_endpoint_name = dbutils.widgets.get("gateway_endpoint")
catalog_name = dbutils.widgets.get("catalog_name")

print(f"Configuring AI Gateway: {gateway_endpoint_name}")
print(f"Inference table catalog: {catalog_name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Apply AI Gateway Configuration

# COMMAND ----------

# Configure AI Gateway features via REST API
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

# Apply via API
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

# MAGIC %md
# MAGIC ## Verify Gateway Health

# COMMAND ----------

# Verify endpoint is ready
try:
    endpoint = w.serving_endpoints.get(gateway_endpoint_name)
    print(f"Endpoint: {endpoint.name}")
    print(f"State: {endpoint.state.ready}")
    print(f"Config update: {endpoint.state.config_update}")
except Exception as e:
    print(f"Endpoint not found: {e}")

