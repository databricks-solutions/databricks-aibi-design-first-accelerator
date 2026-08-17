"""Cleanup service for removing versioned assets created by the pipeline.

Handles removal of: schema tables, output folders, dashboards, genie spaces,
and Lakebase run records for a given domain + version.
"""
import logging
import base64
import yaml

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ExportFormat
from databricks.sdk.service.sql import StatementState

logger = logging.getLogger(__name__)


class CleanupService:
    """Orchestrates version cleanup across all asset types."""

    def __init__(self, workspace_root: str, warehouse_id: str):
        self.workspace_root = workspace_root
        self.warehouse_id = warehouse_id
        self.w = WorkspaceClient()

    def load_domain_config(self, domain: str) -> dict:
        """Load accelerator.yaml for the domain."""
        config_path = f"{self.workspace_root}/examples/{domain}/accelerator.yaml"
        resp = self.w.workspace.export(path=config_path, format=ExportFormat.AUTO)
        content = base64.b64decode(resp.content).decode('utf-8')
        return yaml.safe_load(content) or {}

    def run_cleanup(self, domain: str, version_suffix: str, run_store=None) -> dict:
        """Execute full cleanup for a domain version.

        Args:
            domain: Domain name (e.g. 'member_claims')
            version_suffix: Version suffix (e.g. '_v5')
            run_store: Optional StateStore instance for run record cleanup

        Returns:
            dict with 'cleaned' counts and 'errors' list
        """
        cleaned = {'tables': 0, 'folder': False, 'dashboards': 0, 'genie': False, 'runs': 0}
        errors = []

        # Load domain config
        try:
            config = self.load_domain_config(domain)
        except Exception as e:
            return {'cleaned': cleaned, 'errors': [f'Cannot load config: {e}']}

        suffix = version_suffix  # e.g. "_v5"

        # Determine target schema
        target_schema = f"aibi_{domain}"
        catalog_cfg = config.get('catalog', {})
        target_cat_cfg = catalog_cfg.get('target', {})
        target_catalog = target_cat_cfg.get('catalog', '')
        if target_cat_cfg.get('schema'):
            target_schema = target_cat_cfg['schema']

        # --- 1. Tables ---
        tables_removed = self._cleanup_tables(target_catalog, target_schema, suffix)
        cleaned['tables'] = tables_removed['count']
        errors.extend(tables_removed.get('errors', []))

        # --- 2. Output folder ---
        folder_result = self._cleanup_output_folder(domain, suffix)
        cleaned['folder'] = folder_result['removed']
        errors.extend(folder_result.get('errors', []))

        # --- 3. Dashboards ---
        assets_cfg = config.get('assets', {})
        dash_result = self._cleanup_dashboards(assets_cfg.get('dashboards', []), suffix)
        cleaned['dashboards'] = dash_result['count']
        errors.extend(dash_result.get('errors', []))

        # --- 4. Genie space ---
        genie_result = self._cleanup_genie(assets_cfg.get('genie', {}), suffix)
        cleaned['genie'] = genie_result['removed']
        errors.extend(genie_result.get('errors', []))

        # --- 5. Run records ---
        if run_store:
            runs_result = self._cleanup_run_records(run_store, domain, version_suffix)
            cleaned['runs'] = runs_result['count']
            errors.extend(runs_result.get('errors', []))

        logger.info(f"Cleanup completed for {domain}{suffix}: {cleaned}")
        return {'cleaned': cleaned, 'errors': errors if errors else None}

    def _cleanup_tables(self, catalog: str, schema: str, suffix: str) -> dict:
        """Remove tables ending with the version suffix from target schema."""
        result = {'count': 0, 'errors': []}
        if not catalog or not schema:
            result['errors'].append('Missing catalog/schema for table cleanup')
            return result

        try:
            list_sql = f"SHOW TABLES IN {catalog}.{schema}"
            stmt = self.w.statement_execution.execute_statement(
                warehouse_id=self.warehouse_id,
                statement=list_sql,
                wait_timeout='30s'
            )
            if stmt.status and stmt.status.state == StatementState.SUCCEEDED and stmt.result:
                for row in (stmt.result.data_array or []):
                    table_name = row[1] if len(row) > 1 else row[0]
                    if table_name.endswith(suffix):
                        drop_sql = f"DROP TABLE IF EXISTS {catalog}.{schema}.{table_name}"
                        try:
                            self.w.statement_execution.execute_statement(
                                warehouse_id=self.warehouse_id,
                                statement=drop_sql,
                                wait_timeout='30s'
                            )
                            result['count'] += 1
                            logger.info(f"Dropped table: {catalog}.{schema}.{table_name}")
                        except Exception as e:
                            result['errors'].append(f"Drop {table_name}: {e}")
        except Exception as e:
            result['errors'].append(f"List tables: {e}")
        return result

    def _cleanup_output_folder(self, domain: str, suffix: str) -> dict:
        """Remove the output folder for this version."""
        result = {'removed': False, 'errors': []}
        version_num = suffix.replace('_v', '')
        output_path = f"{self.workspace_root}/examples/{domain}/output/v{version_num}"
        try:
            self.w.workspace.delete(path=output_path, recursive=True)
            result['removed'] = True
            logger.info(f"Removed output folder: {output_path}")
        except Exception as e:
            if 'RESOURCE_DOES_NOT_EXIST' in str(e):
                logger.debug(f"Output folder already gone: {output_path}")
            else:
                result['errors'].append(f"Output folder: {e}")
        return result

    def _cleanup_dashboards(self, dashboards_cfg: list, suffix: str) -> dict:
        """Remove Lakeview dashboards matching the versioned names."""
        result = {'count': 0, 'errors': []}
        for dash in dashboards_cfg:
            dash_name = dash.get('name', '') + suffix
            if not dash_name:
                continue
            try:
                for d in self.w.lakeview.list():
                    if d.display_name == dash_name:
                        self.w.lakeview.trash(d.dashboard_id)
                        result['count'] += 1
                        logger.info(f"Trashed dashboard: {dash_name}")
                        break
            except Exception as e:
                result['errors'].append(f"Dashboard {dash_name}: {e}")
        return result

    def _cleanup_genie(self, genie_cfg: dict, suffix: str) -> dict:
        """Remove the Genie space for this version."""
        result = {'removed': False, 'errors': []}
        space_name = genie_cfg.get('space_name', '') + suffix
        if not space_name:
            return result
        try:
            for space in self.w.genie.list():
                name = getattr(space, 'display_name', '') or getattr(space, 'name', '')
                if name == space_name:
                    self.w.genie.delete(space.space_id)
                    result['removed'] = True
                    logger.info(f"Removed genie space: {space_name}")
                    break
        except Exception as e:
            result['errors'].append(f"Genie space: {e}")
        return result

    def _cleanup_run_records(self, run_store, domain: str, version_suffix: str) -> dict:
        """Remove run records from Lakebase for this domain+version."""
        result = {'count': 0, 'errors': []}
        try:
            count = run_store.delete_runs_for_version(domain, version_suffix)
            result['count'] = count
        except Exception as e:
            result['errors'].append(f"Run records: {e}")
        return result
