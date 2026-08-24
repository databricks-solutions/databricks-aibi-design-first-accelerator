# Databricks notebook source
# MAGIC %md
# MAGIC # Register AIBIPipelineSupervisor to Unity Catalog
# MAGIC
# MAGIC Logs and registers the supervisor agent as an MLflow pyfunc model.
# MAGIC Deployed as part of the `deploy_agent` job.

# COMMAND ----------

import os
import sys
import mlflow
import pandas as pd
from mlflow.models.signature import infer_signature

# COMMAND ----------

# Parameters from job
catalog_name = dbutils.widgets.get("catalog_name")
model_schema = dbutils.widgets.get("model_schema")
model_name = dbutils.widgets.get("model_name")
llm_endpoint = dbutils.widgets.get("llm_endpoint")
source_root = dbutils.widgets.get("source_root")

full_model_name = f"{catalog_name}.{model_schema}.{model_name}"
print(f"Registering model: {full_model_name}")
print(f"LLM endpoint: {llm_endpoint}")
print(f"Source root: {source_root}")

# COMMAND ----------

# Add project to path so imports work
sys.path.insert(0, source_root)
sys.path.insert(0, f"{source_root}/app")

from orchestrator.supervisor import AIBIPipelineSupervisor

# COMMAND ----------

# Set registry to Unity Catalog
mlflow.set_registry_uri("databricks-uc")
mlflow.set_tracking_uri("databricks")

experiment_name = f"/Users/{os.getenv('DB_USER_EMAIL', 'arun.wagle@databricks.com')}/aibi-supervisor-experiment"
mlflow.set_experiment(experiment_name)

# COMMAND ----------

# Define input/output signature
input_example = pd.DataFrame([{
    "domain": "member_claims",
    "domain_path": f"{source_root}/kpi_domains/member_claims",
    "deploy_root": source_root,
    "catalog": catalog_name,
    "schema": "aibi_member_claims",
    "sql_warehouse_id": "2d8e531640ffa469",
    "workspace_host": "https://fevm-aw-serverless-stable.cloud.databricks.com",
    "llm_endpoint": llm_endpoint,
}])

output_example = {
    "status": "completed",
    "run_id": "example-uuid",
    "steps_completed": 15,
    "iterations": 45,
    "tool_calls_made": 15,
    "artifacts": ["/path/to/artifact1.yaml"],
    "summary": "Pipeline completed successfully.",
}

# COMMAND ----------

# Log and register
with mlflow.start_run(run_name="supervisor-agent-register") as run:
    model_info = mlflow.pyfunc.log_model(
        artifact_path="supervisor",
        python_model=AIBIPipelineSupervisor(),
        input_example=input_example,
        signature=infer_signature(input_example, output_example),
        registered_model_name=full_model_name,
        pip_requirements=[
            "mlflow>=2.20.2",
            "databricks-sdk>=0.118.0",
            "pyyaml",
            "requests",
            "Pillow>=10.0.0",
        ],
        code_paths=[
            f"{source_root}/app/orchestrator",
        ],
    )
    print(f"Model registered: {full_model_name}")
    print(f"Run ID: {run.info.run_id}")
    print(f"Model URI: {model_info.model_uri}")

# COMMAND ----------

# Get latest version
from mlflow import MlflowClient

client = MlflowClient()
versions = client.search_model_versions(f"name='{full_model_name}'")
latest = max(versions, key=lambda v: int(v.version))
print(f"Latest version: {latest.version}")
print(f"Status: {latest.status}")

