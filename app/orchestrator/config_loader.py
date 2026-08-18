"""ConfigLoader — Parse and validate accelerator.yaml + databricks.yml.

Resolves all paths, merges bundle variables, and produces a fully resolved
AcceleratorConfig object used by all pipeline steps.

See docs/design_phase2.md Section 4.2 for full reference.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration Models
# ---------------------------------------------------------------------------

@dataclass
class CatalogConfig:
    """Catalog/schema references for source and target."""
    source: Optional[str] = None
    target: Optional[str] = None


@dataclass
class DataSourceConfig:
    """Data source configuration (ERD, live_schema, or hybrid)."""
    type: str = "erd"
    erd_image: Optional[str] = None
    live_schema: Optional[dict] = None
    live_schemas: list = field(default_factory=list)
    greenfield_enabled: bool = True
    synthetic_data: bool = True
    volume: Optional[dict] = None


@dataclass
class PipelineConfig:
    """Pipeline execution settings."""
    clean_start: bool = True
    steps_enabled: list = field(default_factory=lambda: [
        "environment_setup", "create_data_layer", "create_metric_views",
        "create_dashboards", "create_genie_space", "generate_documentation"
    ])


@dataclass
class AssetsConfig:
    """Named asset identifiers (all must be snake_case)."""
    metric_view: Optional[str] = None
    dashboard: Optional[str] = None
    dashboards: list = field(default_factory=list)  # Full list: [{id, name}, ...]
    genie_space: Optional[str] = None
    ddl_notebook: Optional[str] = None
    synthetic_notebook: Optional[str] = None
    genie_notebook: Optional[str] = None


@dataclass
class AcceleratorConfig:
    """Fully resolved configuration for a pipeline run."""
    domain_name: str = ""
    domain_description: str = ""
    deploy_root: str = ""
    sql_warehouse_id: str = ""
    databricks_host: str = ""
    example_dir: str = ""
    output_folder: str = ""
    framework_root: str = ""
    prompts_dir: str = ""
    inputs_dir: str = ""
    catalog: CatalogConfig = field(default_factory=CatalogConfig)
    data_source: DataSourceConfig = field(default_factory=DataSourceConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    assets: AssetsConfig = field(default_factory=AssetsConfig)
    short_name: Optional[str] = None
    # Versioning (set by PipelineRunner based on run_mode)
    run_mode: str = "clean"          # "clean" or "versioned"
    version: Optional[int] = None    # None for clean, N for versioned
    version_suffix: str = ""         # "" for clean, "_v1" for versioned

    def to_dict(self) -> dict:
        """Serialize for API response / logging."""
        return {
            "domain_name": self.domain_name,
            "deploy_root": self.deploy_root,
            "example_dir": self.example_dir,
            "output_folder": self.output_folder,
            "data_source_type": self.data_source.type,
            "catalog_source": self.catalog.source,
            "catalog_target": self.catalog.target,
            "clean_start": self.pipeline.clean_start,
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """A single config validation error."""
    field: str
    message: str
    severity: str = "error"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class ConfigLoader:
    """Loads and validates accelerator configuration.

    Usage:
        loader = ConfigLoader(workspace_service)
        config = loader.load("member_claims", deploy_root="/Workspace/Users/me/accel")
        errors = loader.validate(config)
    """

    def __init__(self, workspace_service):
        """Initialize with workspace service for reading config files.

        Args:
            workspace_service: WorkspaceService instance.
        """
        self._ws = workspace_service

    def load(self, domain: str, deploy_root: str, sql_warehouse_id: str = "",
             workspace_root: str = "") -> AcceleratorConfig:
        """Load and resolve configuration for a domain.

        Args:
            domain: Domain name (maps to kpi_domains/<domain>/).
            deploy_root: Path to project root for READING configs (local or workspace).
            sql_warehouse_id: SQL warehouse ID from env/databricks.yml.
            workspace_root: Workspace path for WRITING outputs. If empty, uses deploy_root.

        Returns:
            Fully resolved AcceleratorConfig.
        """
        # Reading path (local filesystem or workspace)
        example_dir = f"{deploy_root}/kpi_domains/{domain}"
        accel_yaml_path = f"{example_dir}/accelerator.yaml"
        # Writing path (always workspace for persistent outputs)
        ws_root = workspace_root or deploy_root
        ws_example_dir = f"{ws_root}/kpi_domains/{domain}"

        try:
            raw = self._ws.read_yaml(accel_yaml_path)
        except Exception as e:
            raise ConfigError(f"Cannot read {accel_yaml_path}: {e}")

        # Parse domain block
        domain_block = raw.get("domain", {})
        domain_name = domain_block.get("name", domain)
        domain_desc = domain_block.get("description", "")

        # Parse workspace block
        workspace_block = raw.get("workspace", {})
        short_name = workspace_block.get("short_name")
        output_subpath = workspace_block.get("output_subpath", "generated_outputs")

        # Compute output folder (workspace path for writing)
        output_folder = f"{ws_example_dir}/{output_subpath}"
        if short_name:
            output_folder = f"{ws_example_dir}/{output_subpath}_{short_name}"

        # Parse catalog
        catalog_block = raw.get("catalog", {})
        catalog = CatalogConfig(
            source=self._format_schema_fqn(catalog_block.get("source", {})),
            target=self._format_schema_fqn(catalog_block.get("target", {}))
        )

        # Parse data_source
        ds_block = raw.get("data_source", {})
        greenfield_block = ds_block.get("greenfield", {})
        erd_block = ds_block.get("erd", {})
        data_source = DataSourceConfig(
            type=ds_block.get("type", "erd"),
            erd_image=erd_block.get("image"),
            live_schema=ds_block.get("live_schema"),
            live_schemas=ds_block.get("live_schemas", []),
            greenfield_enabled=greenfield_block.get("enabled", True),
            synthetic_data=greenfield_block.get("synthetic_data", True),
            volume=greenfield_block.get("volume")
        )

        # Parse pipeline
        pipeline_block = raw.get("pipeline", {})
        pipeline = PipelineConfig(
            clean_start=pipeline_block.get("clean_start", True)
        )

        # Parse assets — handle both singular and plural (list) formats
        assets_block = raw.get("assets", {})

        # metric_view: singular string or first primary from metric_views list
        mv = assets_block.get("metric_view")
        if not mv:
            mv_list = assets_block.get("metric_views", [])
            if mv_list:
                primary = next((m for m in mv_list if m.get("primary")), mv_list[0])
                mv = primary.get("name")

        # dashboard: singular string or first from dashboards list
        dash = assets_block.get("dashboard")
        dash_list = assets_block.get("dashboards", [])
        if not dash:
            if dash_list:
                dash = dash_list[0].get("name")

        # genie_space: singular string or from genie dict
        genie_space = assets_block.get("genie_space")
        genie_notebook = assets_block.get("genie_notebook")
        if not genie_space:
            genie_block = assets_block.get("genie", {})
            if genie_block:
                genie_space = genie_block.get("space_name")
                genie_notebook = genie_notebook or genie_block.get("notebook_name")

        assets = AssetsConfig(
            metric_view=mv,
            dashboard=dash,
            dashboards=dash_list,
            genie_space=genie_space,
            ddl_notebook=assets_block.get("ddl_notebook"),
            synthetic_notebook=assets_block.get("synthetic_notebook"),
            genie_notebook=genie_notebook
        )

        config = AcceleratorConfig(
            domain_name=domain_name,
            domain_description=domain_desc,
            deploy_root=deploy_root,
            sql_warehouse_id=sql_warehouse_id,
            example_dir=example_dir,
            output_folder=output_folder,
            framework_root=f"{deploy_root}/framework",
            prompts_dir=f"{deploy_root}/framework/prompts",
            inputs_dir=f"{example_dir}/inputs",
            catalog=catalog,
            data_source=data_source,
            pipeline=pipeline,
            assets=assets,
            short_name=short_name
        )

        logger.info(f"Config loaded: domain={domain_name}, type={data_source.type}")
        return config

    def validate(self, config: AcceleratorConfig) -> list:
        """Validate configuration against schema rules.

        Returns:
            List of ValidationError objects (empty = valid).
        """
        errors = []

        if not config.domain_name:
            errors.append(ValidationError("domain.name", "Domain name is required"))
        if not config.deploy_root:
            errors.append(ValidationError("deploy_root", "Deploy root path is required"))
        if not config.sql_warehouse_id:
            errors.append(ValidationError("sql_warehouse_id", "SQL warehouse ID is required"))
        if not config.catalog.target:
            errors.append(ValidationError("catalog.target", "Target catalog.schema is required"))

        if config.data_source.type == "erd":
            if not config.data_source.erd_image:
                errors.append(ValidationError("data_source.erd.image", "ERD image required for type=erd"))
            if not config.catalog.source:
                errors.append(ValidationError("catalog.source", "Source catalog.schema required for greenfield"))
        elif config.data_source.type == "live_schema":
            if not config.data_source.live_schema and not config.data_source.live_schemas:
                errors.append(ValidationError("data_source.live_schema", "live_schema or live_schemas[] required"))

        # Asset name format
        pattern = re.compile(r"^[a-z0-9_]+$")
        for field_name in ["metric_view", "dashboard", "genie_space"]:
            value = getattr(config.assets, field_name, None)
            if value and not pattern.match(value):
                errors.append(ValidationError(f"assets.{field_name}", f"Must be snake_case: got \'{value}\'"))

        return errors

    @staticmethod
    def _format_schema_fqn(block: dict) -> Optional[str]:
        """Format {catalog, schema} block into 'catalog.schema' string."""
        if not block:
            return None
        cat = block.get("catalog", "")
        sch = block.get("schema", "")
        return f"{cat}.{sch}" if cat and sch else None


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""
    def __init__(self, message: str, field: str = ""):
        self.field = field
        super().__init__(f"ConfigError: {message}")
