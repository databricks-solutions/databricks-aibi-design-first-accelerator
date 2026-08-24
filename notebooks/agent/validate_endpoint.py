# Databricks notebook source
# MAGIC %md
# MAGIC # Validate Supervisor Endpoint
# MAGIC Sends a smoke test request to the deployed supervisor endpoint.

# COMMAND ----------

import json
import time
from databricks.sdk import WorkspaceClient

# COMMAND ----------

serving_endpoint = dbutils.widgets.get("serving_endpoint")
catalog_name = dbutils.widgets.get("catalog_name")
sql_warehouse_id = dbutils.widgets.get("sql_warehouse_id")

print(f"Validating endpoint: {serving_endpoint}")

# COMMAND ----------

w = WorkspaceClient()

# Wait for endpoint to be ready (up to 10 minutes)
max_wait = 600
start = time.time()
while time.time() - start < max_wait:
    ep = w.serving_endpoints.get(serving_endpoint)
    state = ep.state
    if state and state.ready == "READY":
        print(f"Endpoint is READY (waited {int(time.time() - start)}s)")
        break
    print(f"Endpoint state: {state.ready if state else 'unknown'} - waiting...")
    time.sleep(30)
else:
    raise RuntimeError(f"Endpoint not ready after {max_wait}s")

# COMMAND ----------

# Send test request (minimal - just tests the model loads)
test_input = {
    "dataframe_records": [{
        "domain": "__validation_test__",
        "domain_path": "/tmp/test",
        "deploy_root": "/tmp",
        "catalog": catalog_name,
        "schema": "test",
        "sql_warehouse_id": sql_warehouse_id,
        "workspace_host": w.config.host,
        "gateway_endpoint": serving_endpoint.replace("supervisor", "gateway"),
        "master_prompt": "# Test\nRespond with report_pipeline_complete immediately.",
    }]
}

print("Sending validation request...")
response = w.serving_endpoints.query(
    name=serving_endpoint,
    dataframe_records=test_input["dataframe_records"],
)

print(f"Response: {json.dumps(response.as_dict(), indent=2)[:500]}")

# COMMAND ----------

# Verify response structure
predictions = response.predictions
if predictions:
    result = predictions[0] if isinstance(predictions, list) else predictions
    status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
    print(f"Validation result status: {status}")
    if status in ("completed", "success", "failed"):
        print("PASS: Endpoint responds with valid structure.")
    else:
        print(f"WARNING: Unexpected status '{status}' - endpoint may need investigation.")
else:
    print("WARNING: No predictions in response. Check endpoint logs.")

print("\nEndpoint validation complete.")

