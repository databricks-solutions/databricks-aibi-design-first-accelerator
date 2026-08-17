"""VersionResolver — Discover existing versions and compute next suffix.

Scans workspace folders, UC schemas, and named assets (dashboards, Genie spaces)
to find the highest existing _vN suffix, then returns the next version.

Used by the orchestrator when run_mode="versioned" to ensure new assets get
a unique, incrementing version suffix without colliding with existing ones.

See docs/design_phase2.md Section 10 for full reference.
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Pattern matches _v1, _v2, ..., _v99
VERSION_PATTERN = re.compile(r"_v(\d+)$")

# Pattern matches v1, v2, ... (folder names inside output/)
FOLDER_VERSION_PATTERN = re.compile(r"^v(\d+)$")


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class VersionInfo:
    """Resolved version information for a pipeline run."""
    version: int                # Version number (1, 2, 3, ...)
    suffix: str                 # Suffix to append ("_v1", "_v2", ...)
    is_new: bool = True         # Whether this version doesn\'t yet exist
    existing_versions: list = None  # List of discovered version numbers

    def __post_init__(self):
        if self.existing_versions is None:
            self.existing_versions = []


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class VersionResolver:
    """Discovers existing versions and computes the next suffix.

    Scans multiple sources to find version artifacts:
        1. Workspace output folders (output/v1/, output/v2/, ...)
        2. UC schemas (schema_v1, schema_v2, ...)
        3. Dashboards by name (<name>_v1, <name>_v2, ...)
        4. Genie spaces by title (<title>_v1, <title>_v2, ...)

    Usage:
        resolver = VersionResolver(workspace_service, sql_service, lakeview_service, genie_service)
        info = resolver.resolve(config)
        # info.suffix == "_v3" if _v1 and _v2 exist
    """

    def __init__(self, workspace_service, sql_service, lakeview_service=None, genie_service=None):
        """Initialize with required services.

        Args:
            workspace_service: WorkspaceService for scanning folders.
            sql_service: SQLService for scanning schemas.
            lakeview_service: Optional LakeviewService for scanning dashboards.
            genie_service: Optional GenieService for scanning Genie spaces.
        """
        self._ws = workspace_service
        self._sql = sql_service
        self._lakeview = lakeview_service
        self._genie = genie_service

    def resolve(self, config, override: Optional[int] = None) -> VersionInfo:
        """Discover highest existing version and return next version info.

        Args:
            config: AcceleratorConfig with paths and asset names.
            override: Force a specific version number (skips discovery).

        Returns:
            VersionInfo with the next version to use.
        """
        if override is not None:
            return VersionInfo(
                version=override,
                suffix=f"_v{override}",
                is_new=True,
                existing_versions=[]
            )

        # Collect version numbers from all sources
        all_versions = set()

        # 1. Scan output folders
        try:
            folder_versions = self._scan_output_folders(config.example_dir)
            all_versions.update(folder_versions)
        except Exception as e:
            logger.debug(f"Output folder scan failed: {e}")

        # 2. Scan UC schemas
        try:
            if config.catalog.target:
                catalog, base_schema = config.catalog.target.rsplit(".", 1)
                schema_versions = self._scan_schemas(catalog, base_schema)
                all_versions.update(schema_versions)
        except Exception as e:
            logger.debug(f"Schema scan failed: {e}")

        # 3. Scan dashboards
        try:
            if self._lakeview and config.assets.dashboard:
                dash_versions = self._scan_dashboards(config.assets.dashboard)
                all_versions.update(dash_versions)
        except Exception as e:
            logger.debug(f"Dashboard scan failed: {e}")

        # 4. Scan Genie spaces
        try:
            if self._genie and config.assets.genie_space:
                genie_versions = self._scan_genie_spaces(config.assets.genie_space)
                all_versions.update(genie_versions)
        except Exception as e:
            logger.debug(f"Genie space scan failed: {e}")

        # Compute next version
        existing_sorted = sorted(all_versions)
        next_version = max(all_versions) + 1 if all_versions else 1

        logger.info(
            f"Version scan: found {len(all_versions)} existing versions "
            f"({existing_sorted}), next = _v{next_version}"
        )

        return VersionInfo(
            version=next_version,
            suffix=f"_v{next_version}",
            is_new=True,
            existing_versions=existing_sorted
        )

    # ------------------------------------------------------------------
    # Scanning Methods
    # ------------------------------------------------------------------

    def _scan_output_folders(self, example_dir: str) -> list:
        """Find output/v1/, output/v2/ folders inside the output directory.

        Also supports legacy output_v1/, output_v2/ pattern in example_dir.

        Args:
            example_dir: Path to examples/<domain>/ directory.

        Returns:
            List of version numbers found.
        """
        versions = []
        # New pattern: output/v1/, output/v2/ ...
        try:
            output_dir = f"{example_dir}/output"
            entries = self._ws.list_dir(output_dir)
            for entry in entries:
                name = entry.name if hasattr(entry, 'name') else str(entry)
                match = FOLDER_VERSION_PATTERN.match(name)
                if match:
                    versions.append(int(match.group(1)))
        except Exception:
            pass
        # Legacy pattern: output_v1/, output_v2/ in example_dir
        try:
            entries = self._ws.list_dir(example_dir)
            for entry in entries:
                name = entry.name if hasattr(entry, 'name') else str(entry)
                if name.startswith("output"):
                    match = VERSION_PATTERN.search(name)
                    if match:
                        versions.append(int(match.group(1)))
        except Exception:
            pass
        return versions

    def _scan_schemas(self, catalog: str, base_schema: str) -> list:
        """Find schema_v1, schema_v2, ... schemas in a catalog.

        Args:
            catalog: Catalog name.
            base_schema: Base schema name (without _vN suffix).

        Returns:
            List of version numbers found.
        """
        versions = []
        try:
            result = self._sql.execute_and_wait(
                f"SHOW SCHEMAS IN `{catalog}`",
                timeout_s=30.0
            )
            if result.rows:
                for row in result.rows:
                    schema_name = row[0] if isinstance(row, (list, tuple)) else str(row)
                    if schema_name.startswith(base_schema):
                        remainder = schema_name[len(base_schema):]
                        match = VERSION_PATTERN.match(remainder)
                        if match:
                            versions.append(int(match.group(1)))
        except Exception:
            pass
        return versions

    def _scan_dashboards(self, base_name: str) -> list:
        """Find <name>_v1, <name>_v2, ... dashboards.

        Args:
            base_name: Base dashboard display name.

        Returns:
            List of version numbers found.
        """
        versions = []
        try:
            dashboards = self._lakeview.list_dashboards()
            for db in dashboards:
                name = db.display_name or ""
                if name.startswith(base_name):
                    remainder = name[len(base_name):]
                    match = VERSION_PATTERN.match(remainder)
                    if match:
                        versions.append(int(match.group(1)))
        except Exception:
            pass
        return versions

    def _scan_genie_spaces(self, base_title: str) -> list:
        """Find <title>_v1, <title>_v2, ... Genie spaces.

        Args:
            base_title: Base Genie space title.

        Returns:
            List of version numbers found.
        """
        versions = []
        try:
            spaces = self._genie.list_spaces()
            for space in spaces:
                title = space.title or ""
                if title.startswith(base_title):
                    remainder = title[len(base_title):]
                    match = VERSION_PATTERN.match(remainder)
                    if match:
                        versions.append(int(match.group(1)))
        except Exception:
            pass
        return versions

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_next_version_preview(self, config) -> dict:
        """Preview what the next version would be (for UI display).

        Returns:
            Dict with version info for the UI to display.
        """
        info = self.resolve(config)
        return {
            "next_version": info.version,
            "next_suffix": info.suffix,
            "existing_versions": info.existing_versions,
            "existing_count": len(info.existing_versions)
        }
