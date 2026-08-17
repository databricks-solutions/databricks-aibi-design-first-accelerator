"""LakeviewService — Databricks Lakeview Dashboard API wrapper.

Provides dashboard CRUD operations for creating and publishing AI/BI dashboards.
All methods are stateless and accept explicit parameters.

API Reference:
    https://docs.databricks.com/api/workspace/lakeview

Design notes:
    - Uses the Lakeview REST API for dashboard lifecycle management
    - Supports create, publish, find-by-name, and idempotent delete
    - serialized_dashboard is the full JSON spec (pages, widgets, datasets)
    - Raises LakeviewError on API failures

See docs/design_phase2.md Section 2.3 for full method reference.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class Dashboard:
    """Lakeview dashboard metadata."""
    dashboard_id: str
    display_name: str
    path: Optional[str] = None
    warehouse_id: Optional[str] = None
    lifecycle_state: Optional[str] = None  # ACTIVE, TRASHED


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LakeviewError(Exception):
    """Raised when a Lakeview Dashboard API call fails."""

    def __init__(self, message: str, dashboard_id: str = "", operation: str = ""):
        self.dashboard_id = dashboard_id
        self.operation = operation
        super().__init__(f"LakeviewError [{operation}]: {message}")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class LakeviewService:
    """Stateless wrapper around the Databricks Lakeview Dashboard API.

    Usage:
        lv = LakeviewService()
        dashboard = lv.create_dashboard(
            display_name="Claims KPI Dashboard",
            warehouse_id="abc123",
            serialized_dashboard=json.dumps(spec),
            parent_path="/Workspace/Users/me/dashboards"
        )
        lv.publish_dashboard(dashboard.dashboard_id)
    """

    def __init__(self, client: Optional[WorkspaceClient] = None,
                 user_token: Optional[str] = None):
        """Initialize with an optional pre-configured WorkspaceClient.

        Args:
            client: Databricks SDK WorkspaceClient. If None, creates one
                    using default environment authentication (or user_token).
            user_token: If provided, authenticates as the logged-in user.
        """
        if client:
            self._client = client
        elif user_token:
            import os
            from databricks.sdk.config import Config
            host = os.environ.get('DATABRICKS_HOST', '')
            cfg = Config(host=host, token=user_token, auth_type="pat")
            self._client = WorkspaceClient(config=cfg)
        else:
            self._client = WorkspaceClient()

    # ------------------------------------------------------------------
    # Create & Publish
    # ------------------------------------------------------------------

    def create_dashboard(
        self,
        display_name: str,
        warehouse_id: str,
        serialized_dashboard: str,
        parent_path: Optional[str] = None
    ) -> Dashboard:
        """Create a new Lakeview dashboard.

        Args:
            display_name: Human-readable dashboard name.
            warehouse_id: SQL warehouse ID for executing dashboard queries.
            serialized_dashboard: JSON string of the full dashboard specification
                                  (pages, widgets, datasets, encodings, positions).
            parent_path: Optional workspace path for dashboard location.

        Returns:
            Dashboard object with the created dashboard's metadata.

        Raises:
            LakeviewError: If creation fails.
        """
        try:
            from databricks.sdk.service.dashboards import Dashboard as SDKDashboard
            dashboard_obj = SDKDashboard(
                display_name=display_name,
                warehouse_id=warehouse_id,
                serialized_dashboard=serialized_dashboard,
                parent_path=parent_path
            )
            response = self._client.lakeview.create(dashboard=dashboard_obj)
            dashboard = Dashboard(
                dashboard_id=response.dashboard_id,
                display_name=response.display_name,
                path=response.path,
                warehouse_id=response.warehouse_id,
                lifecycle_state=response.lifecycle_state.value if response.lifecycle_state else None
            )
            logger.info(f"Created dashboard: {display_name} (id={dashboard.dashboard_id})")
            return dashboard
        except Exception as e:
            raise LakeviewError(str(e), operation="create_dashboard") from e

    def publish_dashboard(
        self,
        dashboard_id: str,
        warehouse_id: Optional[str] = None,
        embed_credentials: bool = True
    ) -> None:
        """Publish a draft dashboard to make it live.

        Args:
            dashboard_id: ID of the dashboard to publish.
            warehouse_id: Optional warehouse override for published version.
            embed_credentials: Whether to embed credentials (default True).

        Raises:
            LakeviewError: If publishing fails.
        """
        try:
            self._client.lakeview.publish(
                dashboard_id=dashboard_id,
                warehouse_id=warehouse_id,
                embed_credentials=embed_credentials
            )
            logger.info(f"Published dashboard: {dashboard_id}")
        except Exception as e:
            raise LakeviewError(
                str(e), dashboard_id=dashboard_id, operation="publish_dashboard"
            ) from e

    # ------------------------------------------------------------------
    # Query & Search
    # ------------------------------------------------------------------

    def list_dashboards(self, page_size: int = 100) -> list:
        """List all Lakeview dashboards (paginated).

        Args:
            page_size: Number of dashboards per page.

        Returns:
            List of Dashboard objects.

        Raises:
            LakeviewError: If the list request fails.
        """
        try:
            dashboards = []
            for db in self._client.lakeview.list(page_size=page_size):
                dashboards.append(Dashboard(
                    dashboard_id=db.dashboard_id,
                    display_name=db.display_name,
                    path=db.path,
                    warehouse_id=db.warehouse_id,
                    lifecycle_state=db.lifecycle_state.value if db.lifecycle_state else None
                ))
            return dashboards
        except Exception as e:
            raise LakeviewError(str(e), operation="list_dashboards") from e

    def find_by_name(self, display_name: str) -> Optional[Dashboard]:
        """Find a dashboard by its display name.

        Args:
            display_name: Exact display name to search for.

        Returns:
            Dashboard if found, None otherwise.
        """
        dashboards = self.list_dashboards()
        for db in dashboards:
            if db.display_name == display_name:
                return db
        return None

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_dashboard(self, dashboard_id: str) -> None:
        """Delete a dashboard by ID.

        Args:
            dashboard_id: ID of the dashboard to trash.

        Raises:
            LakeviewError: If deletion fails.
        """
        try:
            self._client.lakeview.trash(dashboard_id=dashboard_id)
            logger.info(f"Deleted dashboard: {dashboard_id}")
        except Exception as e:
            raise LakeviewError(
                str(e), dashboard_id=dashboard_id, operation="delete_dashboard"
            ) from e

    def delete_by_name(self, display_name: str) -> bool:
        """Find and delete a dashboard by name (idempotent).

        Used to ensure clean slate before recreation.

        Args:
            display_name: Display name of the dashboard to delete.

        Returns:
            True if a dashboard was found and deleted, False if not found.
        """
        dashboard = self.find_by_name(display_name)
        if dashboard:
            self.delete_dashboard(dashboard.dashboard_id)
            return True
        logger.debug(f"Dashboard not found for deletion: {display_name}")
        return False

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def create_and_publish(
        self,
        display_name: str,
        warehouse_id: str,
        serialized_dashboard: str,
        parent_path: Optional[str] = None,
        replace_existing: bool = True
    ) -> Dashboard:
        """Create and immediately publish a dashboard.

        Optionally removes any existing dashboard with the same name first.

        Args:
            display_name: Dashboard name.
            warehouse_id: SQL warehouse ID.
            serialized_dashboard: Full JSON spec.
            parent_path: Optional workspace location.
            replace_existing: If True, delete any existing dashboard with
                              the same name before creating.

        Returns:
            The newly created and published Dashboard.
        """
        if replace_existing:
            self.delete_by_name(display_name)

        dashboard = self.create_dashboard(
            display_name=display_name,
            warehouse_id=warehouse_id,
            serialized_dashboard=serialized_dashboard,
            parent_path=parent_path
        )
        self.publish_dashboard(dashboard.dashboard_id, warehouse_id=warehouse_id)
        return dashboard
