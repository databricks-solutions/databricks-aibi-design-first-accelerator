"""PromptLoader - Reads framework prompt files for the agent loop.

Instead of hardcoding prompt content in Python, this module reads the
actual framework/prompts/*.md files at runtime. This ensures the app
uses exactly the same prompts as Genie Code.

The prompt files contain detailed step-by-step instructions that guide
the LLM through each pipeline step. Context variables are injected
via simple {placeholder} replacement.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Maps pipeline step names to their prompt files
STEP_PROMPT_FILES = {
    "master": "00_master_prompt.md",
    "create_data_layer": "01_create_data_layer.md",
    "create_metric_views": "02_create_metric_views.md",
    "create_dashboards": "03_create_dashboards.md",
    "create_genie_space": "04_create_genie_space.md",
    "generate_documentation": "05_generate_documentation.md",
}

# Supplementary input files that steps reference
SUPPLEMENT_FILES = {
    "create_dashboards": ["inputs/lakeview_dashboard_api.md"],
    "create_genie_space": ["inputs/genie_space_configuration.md"],
}


class PromptLoader:
    """Loads framework prompts from workspace files.

    Usage:
        loader = PromptLoader(workspace_service, framework_root)
        prompt = loader.load_step_prompt("create_dashboards")
        supplements = loader.load_supplements("create_dashboards")
    """

    def __init__(self, workspace_service, framework_root: str):
        """Initialize prompt loader.

        Args:
            workspace_service: WorkspaceService instance for reading files.
            framework_root: Absolute workspace path to framework/ directory.
                Example: /Workspace/Users/user/project/framework
        """
        self._ws = workspace_service
        self._root = framework_root

    def load_step_prompt(self, step_name: str) -> str:
        """Load the primary prompt file for a pipeline step.

        Args:
            step_name: Pipeline step (e.g. 'create_dashboards').

        Returns:
            Full prompt content as string.

        Raises:
            FileNotFoundError: If prompt file doesn't exist.
        """
        filename = STEP_PROMPT_FILES.get(step_name)
        if not filename:
            raise ValueError(f"Unknown step: {step_name}. Known: {list(STEP_PROMPT_FILES.keys())}")

        path = f"{self._root}/prompts/{filename}"
        content = self._ws.read_file(path)
        if content is None:
            raise FileNotFoundError(f"Prompt file not found: {path}")

        logger.info(f"Loaded prompt for '{step_name}': {len(content)} chars from {path}")
        return content

    def load_supplements(self, step_name: str) -> str:
        """Load supplementary reference files for a step.

        These are the input files (lakeview_dashboard_api.md, etc.) that
        the prompt references. They're concatenated and included as additional
        context for the LLM.

        Args:
            step_name: Pipeline step name.

        Returns:
            Concatenated supplement content (empty string if none).
        """
        filenames = SUPPLEMENT_FILES.get(step_name, [])
        if not filenames:
            return ""

        parts = []
        for filename in filenames:
            path = f"{self._root}/{filename}"
            content = self._ws.read_file(path)
            if content:
                parts.append(f"--- BEGIN {filename} ---\n{content}\n--- END {filename} ---")
                logger.info(f"Loaded supplement: {filename} ({len(content)} chars)")
            else:
                logger.warning(f"Supplement file not found: {path}")

        return "\n\n".join(parts)

    def load_domain_inputs(self, domain_root: str) -> dict:
        """Load domain-specific input files (KPI spec, ERD, accelerator.yaml).

        Args:
            domain_root: Path to the KPI domain directory.
                Example: /Workspace/Users/user/project/kpi_domains/member_claims

        Returns:
            Dict with keys: kpi_spec, accelerator_yaml, erd_image_path
        """
        inputs = {}

        # KPI spec
        kpi_path = f"{domain_root}/inputs/kpi_spec.md"
        inputs["kpi_spec"] = self._ws.read_file(kpi_path) or ""

        # Accelerator config
        accel_path = f"{domain_root}/accelerator.yaml"
        inputs["accelerator_yaml"] = self._ws.read_file(accel_path) or ""

        # ERD image path (for vision model)
        inputs["erd_image_path"] = f"{domain_root}/inputs/erd.png"

        return inputs

    def build_context_vars(self, config) -> dict:
        """Build the context variables dict from accelerator config.

        These are substituted into prompt {placeholder} references.

        Args:
            config: AcceleratorConfig instance.

        Returns:
            Dict of all context variables for prompt injection.
        """
        # Derive catalog and schema from config.catalog.target ("catalog.schema" string)
        catalog_target = config.catalog.target or ""
        parts = catalog_target.split(".", 1)
        catalog_name = parts[0] if parts else ""
        schema_name = parts[1] if len(parts) > 1 else ""

        return {
            # Core identifiers
            "CATALOG": catalog_name,
            "SCHEMA": schema_name,
            "VERSION_SUFFIX": config.version_suffix or "",
            "NEXT_VERSION": str(config.version) if config.version else "",
            "OUTPUT_FOLDER": config.output_folder,
            "EXAMPLE_DIR": config.example_dir,

            # Workspace paths
            "workspace.output_folder": config.output_folder,
            "workspace.host": config.databricks_host,
            "paths.framework_root": config.framework_root,

            # Runtime
            "sql_warehouse_id": config.sql_warehouse_id,
            "deploy_root": config.deploy_root,
        }
