"""Centralized configuration for AI/BI Studio.

All environment variables and application constants are managed here.
See docs/design_phase2.md Section 6 for full reference.

Config resolution (prompt-driven architecture):
  1. Environment variables (set in app.yaml) — fast path
  2. SDK discovery from setup job params + databricks.yml — when env vars
     don't reach the container (known platform issue with env_vars=[]).
  Fails loudly if critical values can't be resolved.
"""

import os
import logging

logger = logging.getLogger(__name__)


def _discover_config() -> dict:
    """Single discovery pass: resolve all config values from env vars or SDK.

    Returns dict with keys: workspace_root, sql_warehouse_id, catalog_name,
    lakebase_project_id, setup_job_id.
    """
    config = {
        'workspace_root': os.environ.get('WORKSPACE_ROOT', ''),
        'sql_warehouse_id': os.environ.get('SQL_WAREHOUSE_ID', ''),
        'catalog_name': os.environ.get('CATALOG_NAME', ''),
        'lakebase_project_id': os.environ.get('LAKEBASE_PROJECT_ID', 'aibi-studio'),
        'setup_job_id': os.environ.get('SETUP_JOB_ID', ''),
    }

    # If all critical values are set via env vars, skip SDK discovery
    if config['workspace_root'] and config['sql_warehouse_id']:
        return config

    # SDK discovery: read from setup job params + databricks.yml
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()

        # Find setup job
        full_job = None
        job_id = config['setup_job_id']
        if job_id:
            full_job = w.jobs.get(int(job_id))
        else:
            for job in w.jobs.list():
                if 'aibi-studio-setup-infrastructure' in (job.settings.name or ''):
                    full_job = w.jobs.get(job.job_id)
                    config['setup_job_id'] = str(job.job_id)
                    break

        # Extract job params
        if full_job:
            for param in (full_job.settings.parameters or []):
                if param.name == 'project_folder' and param.default and not config['workspace_root']:
                    config['workspace_root'] = param.default
                elif param.name == 'catalog_name' and param.default and not config['catalog_name']:
                    config['catalog_name'] = param.default
                elif param.name == 'lakebase_project_id' and param.default:
                    config['lakebase_project_id'] = param.default

        # sql_warehouse_id: read from databricks.yml at workspace root
        if not config['sql_warehouse_id'] and config['workspace_root']:
            try:
                import yaml
                from databricks.sdk.service.workspace import ExportFormat
                resp = w.workspace.export(
                    path=f"{config['workspace_root']}/databricks.yml",
                    format=ExportFormat.AUTO,
                )
                if resp.content:
                    import base64
                    yml_content = base64.b64decode(resp.content).decode('utf-8')
                    bundle_yml = yaml.safe_load(yml_content)
                    variables = bundle_yml.get('variables', {})
                    wh_var = variables.get('sql_warehouse_id', {})
                    config['sql_warehouse_id'] = wh_var.get('default', '')
                    logger.info(f"Resolved sql_warehouse_id from databricks.yml: {config['sql_warehouse_id']}")
            except Exception as e:
                logger.warning(f"Failed to read sql_warehouse_id from databricks.yml: {e}")

    except Exception as e:
        logger.error(f"SDK config discovery failed: {e}")

    # Validate critical values
    if not config['workspace_root']:
        raise RuntimeError(
            "Cannot resolve WORKSPACE_ROOT. Set WORKSPACE_ROOT env var or ensure "
            "the setup job 'aibi-studio-setup-infrastructure' has a 'project_folder' parameter."
        )
    if not config['sql_warehouse_id']:
        raise RuntimeError(
            "Cannot resolve SQL_WAREHOUSE_ID. Set SQL_WAREHOUSE_ID env var or ensure "
            "databricks.yml at workspace root has variables.sql_warehouse_id.default set."
        )

    return config


# Single discovery at module load
_config = _discover_config()


class Config:
    """Base configuration — reads from environment variables or SDK discovery."""

    # --- App Identity ---
    APP_NAME = 'AI/BI Studio'
    APP_SUBTITLE = 'Design-First Semantic Layer, Metric Views, Dashboards & Genie'

    # --- Paths ---
    # WORKSPACE_ROOT: /Workspace/... path to project source root.
    # WorkspaceService.read_file() uses the Workspace REST API for these paths.
    WORKSPACE_ROOT = _config['workspace_root']
    LOCAL_ROOT = WORKSPACE_ROOT  # alias (all reads go through Workspace API)
    DEPLOY_ROOT = WORKSPACE_ROOT  # legacy alias

    DATABRICKS_HOST = os.environ.get('DATABRICKS_HOST', '')

    # --- SQL Warehouse ---
    SQL_WAREHOUSE_ID = _config['sql_warehouse_id']

    # --- Catalog ---
    CATALOG_NAME = _config['catalog_name']

    # --- Lakebase ---
    LAKEBASE_PROJECT_ID = _config['lakebase_project_id']
    SETUP_JOB_ID = _config['setup_job_id']

    # --- LLM Configuration ---
    LLM_ENDPOINT_NAME = os.environ.get('LLM_ENDPOINT_NAME', 'databricks-gpt-5-5')
    VISION_ENDPOINT_NAME = os.environ.get('VISION_ENDPOINT_NAME', 'databricks-gpt-5-5')
    LLM_TEMPERATURE = float(os.environ.get('LLM_TEMPERATURE', '1'))
    LLM_MAX_RETRIES = int(os.environ.get('LLM_MAX_RETRIES', '3'))

    # --- Domain ---
    DEFAULT_EXAMPLE_DOMAIN = os.environ.get('DEFAULT_EXAMPLE_DOMAIN', 'member_claims')

    # --- Auth & Session ---
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')

    # --- Derived Paths ---
    @property
    def framework_root(self):
        """Absolute workspace path to framework/ directory."""
        return f"{self.DEPLOY_ROOT}/framework"

    @property
    def examples_root(self):
        """Absolute workspace path to examples/ directory."""
        return f"{self.DEPLOY_ROOT}/examples"


class DevelopmentConfig(Config):
    """Development overrides."""
    DEBUG = True
    SECRET_KEY = 'dev-secret-key-local'


class ProductionConfig(Config):
    """Production overrides."""
    DEBUG = False


def get_config():
    """Return appropriate config based on FLASK_ENV."""
    env = os.environ.get('FLASK_ENV', 'development')
    if env == 'production':
        return ProductionConfig()
    return DevelopmentConfig()
