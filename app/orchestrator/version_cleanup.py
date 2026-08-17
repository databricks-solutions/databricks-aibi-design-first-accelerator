"""VersionCleanup - Delete all assets associated with a specific version.

Cleans up a versioned run by removing:
    1. Output folder (output/v{N}/)
    2. Tables with the version suffix (_v{N}) in the domain schema
    3. Metric view with the version suffix
    4. Dashboard with the version suffix
    5. Genie space with the version suffix

Design:
    - Accepts version number and domain config
    - Uses services to delete each asset type
    - Returns a manifest of what was deleted
    - Non-destructive to other versions or shared schema
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class VersionCleanup:
    """Delete all assets tied to a specific version.

    Usage:
        cleanup = VersionCleanup(config, services)
        result = cleanup.execute(version=1)
    """

    def __init__(self, config, services: dict):
        """Initialize with resolved config and services.

        Args:
            config: AcceleratorConfig (with domain, catalog, assets info).
            services: {"workspace", "sql", "lakeview", "genie"} instances.
        """
        self._config = config
        self._ws = services["workspace"]
        self._sql = services["sql"]
        self._lakeview = services.get("lakeview")
        self._genie = services.get("genie")

    def execute(self, version: int) -> dict:
        """Delete all assets for the given version number.

        Args:
            version: Version number to clean up (e.g. 1 for _v1).

        Returns:
            Dict with deletion results per asset type.
        """
        suffix = f"_v{version}"
        results = {
            "version": version,
            "suffix": suffix,
            "deleted": [],
            "failed": [],
            "skipped": [],
        }

        logger.info(f"Starting cleanup for version {version} (suffix={suffix})")

        # 1. Delete output folder
        self._delete_output_folder(version, results)

        # 2. Drop versioned tables from the domain schema
        self._drop_versioned_tables(suffix, results)

        # 3. Drop metric view
        self._drop_metric_view(suffix, results)

        # 4. Delete dashboard
        self._delete_dashboard(suffix, results)

        # 5. Delete Genie space
        self._delete_genie_space(suffix, results)

        logger.info(
            f"Cleanup complete for v{version}: "
            f"{len(results['deleted'])} deleted, "
            f"{len(results['failed'])} failed, "
            f"{len(results['skipped'])} skipped"
        )
        return results

    # ------------------------------------------------------------------
    # Cleanup Methods
    # ------------------------------------------------------------------

    def _delete_output_folder(self, version: int, results: dict) -> None:
        """Delete the versioned output folder (output/v{N}/)."""
        base_output = f"{self._config.example_dir}/output"
        version_folder = f"{base_output}/v{version}"

        try:
            if self._ws.file_exists(version_folder):
                self._ws.delete(version_folder, recursive=True)
                results["deleted"].append({"type": "folder", "path": version_folder})
                logger.info(f"Deleted output folder: {version_folder}")
            else:
                results["skipped"].append({"type": "folder", "path": version_folder, "reason": "not found"})
                logger.info(f"Output folder not found (already clean): {version_folder}")
        except Exception as e:
            results["failed"].append({"type": "folder", "path": version_folder, "error": str(e)})
            logger.warning(f"Failed to delete output folder: {e}")

    def _drop_versioned_tables(self, suffix: str, results: dict) -> None:
        """Drop all tables ending with the version suffix from the domain schema."""
        catalog_name = self._config.catalog.source.split(".")[0] if self._config.catalog.source else ""
        schema_name = f"aibi_{self._config.domain_name}"
        schema_fqn = f"{catalog_name}.{schema_name}"

        if not catalog_name:
            results["skipped"].append({"type": "tables", "reason": "no catalog configured"})
            return

        try:
            result = self._sql.execute_and_wait(
                f"SHOW TABLES IN {schema_fqn}",
                timeout_s=30.0
            )
            if not result.data:
                results["skipped"].append({"type": "tables", "schema": schema_fqn, "reason": "no tables found"})
                return

            tables_dropped = []
            for row in result.data:
                table_name = row[1] if isinstance(row, (list, tuple)) else str(row)
                if table_name.endswith(suffix):
                    fqn = f"{schema_fqn}.{table_name}"
                    try:
                        self._sql.execute_and_wait(
                            f"DROP TABLE IF EXISTS {fqn}",
                            timeout_s=30.0
                        )
                        tables_dropped.append(fqn)
                    except Exception as te:
                        results["failed"].append({"type": "table", "name": fqn, "error": str(te)})

            if tables_dropped:
                results["deleted"].append({"type": "tables", "count": len(tables_dropped), "names": tables_dropped})
                logger.info(f"Dropped {len(tables_dropped)} tables with suffix \'{suffix}\'")
            else:
                results["skipped"].append({"type": "tables", "schema": schema_fqn, "reason": f"no tables with suffix {suffix}"})

        except Exception as e:
            results["failed"].append({"type": "tables", "schema": schema_fqn, "error": str(e)})
            logger.warning(f"Failed to list/drop tables: {e}")

    def _drop_metric_view(self, suffix: str, results: dict) -> None:
        """Drop the versioned metric view."""
        base_mv = self._config.assets.metric_view or f"{self._config.domain_name}_metric_view"
        if base_mv.endswith(suffix):
            mv_name = base_mv
        else:
            mv_name = f"{base_mv}{suffix}"

        target_schema = self._config.catalog.target
        if not target_schema:
            catalog_name = self._config.catalog.source.split(".")[0] if self._config.catalog.source else ""
            target_schema = f"{catalog_name}.aibi_{self._config.domain_name}"

        fqn = f"{target_schema}.{mv_name}"

        try:
            self._sql.execute_and_wait(
                f"DROP MATERIALIZED VIEW IF EXISTS {fqn}",
                timeout_s=30.0
            )
            results["deleted"].append({"type": "metric_view", "name": fqn})
            logger.info(f"Dropped metric view: {fqn}")
        except Exception as e:
            try:
                self._sql.execute_and_wait(
                    f"DROP VIEW IF EXISTS {fqn}",
                    timeout_s=30.0
                )
                results["deleted"].append({"type": "metric_view", "name": fqn})
                logger.info(f"Dropped view: {fqn}")
            except Exception as e2:
                results["failed"].append({"type": "metric_view", "name": fqn, "error": str(e2)})
                logger.warning(f"Failed to drop metric view {fqn}: {e2}")

    def _delete_dashboard(self, suffix: str, results: dict) -> None:
        """Delete the versioned dashboard(s)."""
        if not self._lakeview:
            results["skipped"].append({"type": "dashboard", "reason": "lakeview service not available"})
            return

        base_name = self._config.assets.dashboard or f"{self._config.domain_name}_dashboard"
        if base_name.endswith(suffix):
            dash_name = base_name
        else:
            dash_name = f"{base_name}{suffix}"

        try:
            deleted = self._lakeview.delete_by_name(dash_name)
            if deleted:
                results["deleted"].append({"type": "dashboard", "name": dash_name})
                logger.info(f"Deleted dashboard: {dash_name}")
            else:
                results["skipped"].append({"type": "dashboard", "name": dash_name, "reason": "not found"})
        except Exception as e:
            results["failed"].append({"type": "dashboard", "name": dash_name, "error": str(e)})
            logger.warning(f"Failed to delete dashboard {dash_name}: {e}")

        # Handle multiple dashboards from config
        if self._config.assets.dashboards:
            for dash_config in self._config.assets.dashboards:
                name = dash_config.get("name", "")
                if not name or name == dash_name:
                    continue
                versioned_name = name if name.endswith(suffix) else f"{name}{suffix}"
                try:
                    deleted = self._lakeview.delete_by_name(versioned_name)
                    if deleted:
                        results["deleted"].append({"type": "dashboard", "name": versioned_name})
                        logger.info(f"Deleted dashboard: {versioned_name}")
                except Exception as e:
                    results["failed"].append({"type": "dashboard", "name": versioned_name, "error": str(e)})

    def _delete_genie_space(self, suffix: str, results: dict) -> None:
        """Delete the versioned Genie space."""
        if not self._genie:
            results["skipped"].append({"type": "genie_space", "reason": "genie service not available"})
            return

        base_title = self._config.assets.genie_space or f"{self._config.domain_name}_genie"
        if base_title.endswith(suffix):
            space_title = base_title
        else:
            space_title = f"{base_title}{suffix}"

        try:
            deleted = self._genie.delete_by_title(space_title)
            if deleted:
                results["deleted"].append({"type": "genie_space", "name": space_title})
                logger.info(f"Deleted Genie space: {space_title}")
            else:
                results["skipped"].append({"type": "genie_space", "name": space_title, "reason": "not found"})
        except Exception as e:
            results["failed"].append({"type": "genie_space", "name": space_title, "error": str(e)})
            logger.warning(f"Failed to delete Genie space {space_title}: {e}")
