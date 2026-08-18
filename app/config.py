"""Centralized configuration for AI/BI Studio.

All environment variables and application constants are managed here.
See docs/design_phase2.md Section 6 for full reference.

Config resolution:
  SQL_WAREHOUSE_ID: injected via valueFrom (app resource in aibi.app.yml).
  CATALOG_NAME: set directly in app.yaml env section.
  WORKSPACE_ROOT: auto-derived from app's source_code_path (SDK discovery).
                  Can be overridden via env var for local dev.
"""

import os
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Required environment variables
# ---------------------------------------------------------------------------
_REQUIRED_ENV_VARS = {
    'SQL_WAREHOUSE_ID': 'Injected via valueFrom in app.yaml (app resource declared in aibi.app.yml)',
    'CATALOG_NAME': 'Hardcoded in app.yaml env section (no DABs interpolation available)',
}


def _discover_workspace_root() -> str:
    """Derive the project workspace root from the app's own source_code_path.

    The platform injects DATABRICKS_CLIENT_ID (the app SP's UUID). We find
    our own app object and read its default_source_code_path, then strip
    the '/app' suffix to get the project root.

    This eliminates the need to pass WORKSPACE_ROOT as an env var.
    """
    from databricks.sdk import WorkspaceClient

    client_id = os.environ.get('DATABRICKS_CLIENT_ID', '')
    if not client_id:
        raise RuntimeError(
            "Cannot derive WORKSPACE_ROOT: DATABRICKS_CLIENT_ID not set. "
            "Set WORKSPACE_ROOT env var explicitly or run inside a Databricks App."
        )

    w = WorkspaceClient()
    for app in w.apps.list():
        if app.service_principal_client_id == client_id:
            source_path = app.default_source_code_path or ''
            # source_code_path points to the app/ subfolder; project root is parent
            if source_path.endswith('/app'):
                root = source_path[:-4]
            else:
                root = source_path
            logger.info(f"Derived WORKSPACE_ROOT from app source_code_path: {root}")
            return root

    raise RuntimeError(
        f"Cannot derive WORKSPACE_ROOT: no app found with client_id={client_id}. "
        "Set WORKSPACE_ROOT env var explicitly."
    )


def _load_config() -> dict:
    """Load all config values from environment variables.

    All required values are injected by DABs at deploy time.
    Raises RuntimeError immediately if any required value is missing.

    Returns dict with keys: sql_warehouse_id, catalog_name, workspace_root.
    """
    # Check all required env vars are present
    missing = []
    for var_name, description in _REQUIRED_ENV_VARS.items():
        if not os.environ.get(var_name):
            missing.append(f"  - {var_name}: {description}")

    if missing:
        raise RuntimeError(
            "Missing required environment variables. These must be injected by DABs "
            "config.env (see resources/aibi.app.yml). Run 'databricks bundle deploy' "
            "to set them.\n\nMissing:\n" + "\n".join(missing)
        )

    config = {
        'sql_warehouse_id': os.environ['SQL_WAREHOUSE_ID'],
        'catalog_name': os.environ['CATALOG_NAME'],
        'workspace_root': os.environ.get('WORKSPACE_ROOT') or _discover_workspace_root(),
    }

    logger.info(
        f"Config loaded: workspace_root={config['workspace_root']}, "
        f"catalog={config['catalog_name']}, warehouse={config['sql_warehouse_id']}"
    )
    return config


# Load config at module import (fail-fast if env vars missing)
_config = _load_config()


class Config:
    """Base configuration — reads from environment variables."""

    # --- App Identity ---
    APP_NAME = 'AI/BI Studio'

    # --- Paths ---
    WORKSPACE_ROOT = _config['workspace_root']
    DATABRICKS_HOST = os.environ.get('DATABRICKS_HOST', '')

    # --- SQL Warehouse ---
    SQL_WAREHOUSE_ID = _config['sql_warehouse_id']

    # --- Catalog ---
    CATALOG_NAME = _config['catalog_name']

    # --- LLM Configuration ---
    LLM_ENDPOINT_NAME = os.environ.get('LLM_ENDPOINT_NAME', 'databricks-gpt-5-5')
    VISION_ENDPOINT_NAME = os.environ.get('VISION_ENDPOINT_NAME', 'databricks-gpt-5-5')
    LLM_TEMPERATURE = float(os.environ.get('LLM_TEMPERATURE', '1'))
    LLM_MAX_RETRIES = int(os.environ.get('LLM_MAX_RETRIES', '3'))


    # --- Auth & Session ---
    # Random per-instance key is fine — sessions are just cached identity from
    # platform headers and re-populate automatically on container restart.
    SECRET_KEY = os.urandom(32).hex()

    # --- Derived Paths ---
    @property
    def framework_root(self):
        """Absolute workspace path to framework/ directory."""
        return f"{self.WORKSPACE_ROOT}/framework"

    @property
    def kpi_domains_root(self):
        """Absolute workspace path to kpi_domains/ directory."""
        return f"{self.WORKSPACE_ROOT}/kpi_domains"


class DevelopmentConfig(Config):
    """Development overrides."""
    DEBUG = True


class ProductionConfig(Config):
    """Production overrides."""
    DEBUG = False


def get_config():
    """Return appropriate config based on FLASK_ENV."""
    env = os.environ.get('FLASK_ENV', 'development')
    if env == 'production':
        return ProductionConfig()
    return DevelopmentConfig()
