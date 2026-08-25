"""AIBIPipelineSupervisor — MLflow pyfunc wrapper for the Phase 4 pipeline.

This module provides an MLflow-compatible wrapper that allows the
AI/BI Studio pipeline to be registered as a Unity Catalog model and
served via Model Serving endpoints.

Architecture:
    Model Serving endpoint
      → AIBIPipelineSupervisor.predict()
        → PipelineRunner (sequential step orchestration)
          → AgentStep → AgentLoop → ToolExecutor

The supervisor accepts a DataFrame with pipeline configuration and
orchestrates the full pipeline run, returning status and artifacts.
"""

import json
import logging
import os
import traceback
from typing import Any

import mlflow
import pandas as pd

logger = logging.getLogger(__name__)


class AIBIPipelineSupervisor(mlflow.pyfunc.PythonModel):
    """MLflow pyfunc model wrapping the AI/BI Studio pipeline.

    Registered to Unity Catalog and served via Model Serving.
    Each predict() call runs a full pipeline execution.
    """

    def load_context(self, context: mlflow.pyfunc.PythonModelContext) -> None:
        """Initialize dependencies when model is loaded by serving."""
        # Lazy imports — these are available at serving time
        # via code_paths registered during log_model
        pass

    def predict(
        self,
        context: mlflow.pyfunc.PythonModelContext,
        model_input: pd.DataFrame,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Run the AI/BI Studio pipeline.

        Args:
            context: MLflow model context.
            model_input: DataFrame with one row containing:
                - domain: str — KPI domain name
                - domain_path: str — path to domain config
                - deploy_root: str — workspace root path
                - catalog: str — Unity Catalog name
                - schema: str — target schema name
                - sql_warehouse_id: str — SQL warehouse ID
                - workspace_host: str — Databricks workspace URL
                - llm_endpoint: str — LLM endpoint name
            params: Optional additional parameters.

        Returns:
            dict with: status, run_id, steps_completed, iterations,
            tool_calls_made, artifacts, summary
        """
        try:
            # Extract config from input row
            row = model_input.iloc[0].to_dict()

            # Lazy import the pipeline runner
            from orchestrator.pipeline import PipelineRunner
            from orchestrator.config_loader import ConfigLoader

            # Build config from input
            domain = row.get("domain", "")
            domain_path = row.get("domain_path", "")
            deploy_root = row.get("deploy_root", "")
            catalog = row.get("catalog", "")
            schema = row.get("schema", "")
            sql_warehouse_id = row.get("sql_warehouse_id", "")
            workspace_host = row.get("workspace_host", "")
            llm_endpoint = row.get("llm_endpoint", "")

            # Load accelerator config
            config = ConfigLoader.load_from_path(
                domain_path=domain_path,
                deploy_root=deploy_root,
                catalog=catalog,
                schema=schema,
                sql_warehouse_id=sql_warehouse_id,
            )

            # Build services dict (LLM client, workspace client, etc.)
            from llm.client import LLMClient
            from services.workspace_service import WorkspaceService
            from services.sql_service import SQLService

            llm_client = LLMClient(endpoint=llm_endpoint)
            services = {
                "workspace": WorkspaceService(host=workspace_host),
                "sql": SQLService(warehouse_id=sql_warehouse_id),
                "llm": llm_client,
            }

            # Run pipeline
            runner = PipelineRunner(config, services, llm_client)
            result = runner.run()

            return {
                "status": result.status.value if hasattr(result.status, 'value') else str(result.status),
                "run_id": result.run_id,
                "steps_completed": result.steps_completed,
                "iterations": result.total_iterations,
                "tool_calls_made": result.total_tool_calls,
                "artifacts": result.artifacts or [],
                "summary": result.summary or "Pipeline execution complete.",
            }

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            return {
                "status": "failed",
                "run_id": "",
                "steps_completed": 0,
                "iterations": 0,
                "tool_calls_made": 0,
                "artifacts": [],
                "summary": f"Pipeline failed: {str(e)}",
                "error": traceback.format_exc(),
            }
