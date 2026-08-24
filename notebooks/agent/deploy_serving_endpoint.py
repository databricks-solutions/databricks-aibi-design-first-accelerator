# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy Supervisor Serving Endpoint
# MAGIC
# MAGIC Creates or updates the AgentBricks supervisor serving endpoint.
# MAGIC Run after register_supervisor.py has registered the model to UC.

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput
from mlflow import MlflowClient

# COMMAND ----------

# DBTITLE 1,Parameters from job
# Parameters from job
catalog_name = dbutils.widgets.get("catalog_name")
model_schema = dbutils.widgets.get("model_schema")
model_name = dbutils.widgets.get("model_name")
llm_endpoint = dbutils.widgets.get("llm_endpoint")
sql_warehouse_id = dbutils.widgets.get("sql_warehouse_id")
force_recreate = dbutils.widgets.get("force_recreate").lower() == "true"

full_model_name = f"{catalog_name}.{model_schema}.{model_name}"
print(f"Model: {full_model_name}")
print(f"LLM endpoint: {llm_endpoint}")
print(f"Force recreate: {force_recreate}")

# COMMAND ----------

# Get latest registered model version
mlflow_client = MlflowClient()
versions = mlflow_client.search_model_versions(f"name='{full_model_name}'")
if not versions:
    raise ValueError(f"No versions found for {full_model_name}. Run register_supervisor.py first.")

latest = max(versions, key=lambda v: int(v.version))
model_version = str(latest.version)
print(f"Latest model version: {model_version}")

# COMMAND ----------

# Derive endpoint name from current user
w = WorkspaceClient()
user_email = w.current_user.me().user_name
user_domain = user_email.split("@")[0].replace(".", "-")
endpoint_name = f"aibi-supervisor-{user_domain}"
print(f"Target endpoint: {endpoint_name}")

# COMMAND ----------

# DBTITLE 1,Endpoint served entity configuration
# Endpoint served entity configuration
served_entity = ServedEntityInput(
    name="supervisor-agent",
    entity_name=full_model_name,
    entity_version=model_version,
    workload_size="Small",
    scale_to_zero_enabled=True,
    environment_vars={
        "LLM_ENDPOINT": llm_endpoint,
        "CATALOG_NAME": catalog_name,
        "SQL_WAREHOUSE_ID": sql_warehouse_id,
        "WORKSPACE_HOST": w.config.host,
    },
)

# COMMAND ----------

# DBTITLE 1,Deploy endpoint (fire-and-forget)
# Check if endpoint already exists
try:
    existing = w.serving_endpoints.get(endpoint_name)
    endpoint_exists = True
    print(f"Endpoint '{endpoint_name}' exists (state: {existing.state.ready})")
except Exception:
    endpoint_exists = False
    print(f"Endpoint '{endpoint_name}' does not exist yet.")

# If exists and not force_recreate, skip entirely
if endpoint_exists and not force_recreate:
    print(f"Endpoint already exists. Skipping (force_recreate=False).")
    action = "Exists (no-op)"
else:
    # Fire-and-forget: submit config and exit immediately.
    # Endpoint provisions asynchronously — no need to wait.
    if endpoint_exists:
        try:
            w.serving_endpoints.update_config(
                name=endpoint_name, served_entities=[served_entity]
            )
            action = "Updated (force_recreate)"
        except Exception as e:
            if "currently being updated" in str(e):
                print(f"Endpoint already updating — skipping.")
                action = "Skipped (already updating)"
            else:
                raise e
    else:
        w.serving_endpoints.create(
            name=endpoint_name,
            config=EndpointCoreConfigInput(served_entities=[served_entity]),
        )
        action = "Created"

print(f"{action} endpoint: {endpoint_name}")
print(f"Model: {full_model_name} v{model_version}")
print(f"Task complete.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant App Service Principal access to the endpoint

# COMMAND ----------

# DBTITLE 1,Grant App SP access to endpoint
# Grant CAN_QUERY to the App SP so it can invoke the supervisor
app_name = dbutils.widgets.get("app_name")

if app_name:
    app_info = w.apps.get(name=app_name)
    sp_client_id = app_info.service_principal_client_id
    print(f"App: {app_name}")
    print(f"App SP client_id: {sp_client_id}")

    # Get the numeric endpoint ID (permissions API requires ID, not name)
    endpoint_info = w.serving_endpoints.get(endpoint_name)
    endpoint_id = endpoint_info.id
    print(f"Endpoint ID: {endpoint_id}")

    from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel
    w.permissions.set(
        request_object_type="serving-endpoints",
        request_object_id=endpoint_id,
        access_control_list=[
            AccessControlRequest(
                service_principal_name=sp_client_id,
                permission_level=PermissionLevel.CAN_QUERY,
            )
        ],
    )
    print(f"Granted CAN_QUERY on '{endpoint_name}' (id={endpoint_id}) to App SP '{sp_client_id}'")
else:
    print("No app_name provided - skipping SP permission grant")
