"""GenieService — Databricks Genie Spaces API wrapper.

Provides Genie space management operations (list, find, delete).
Space creation is handled by the configuration notebook template,
not direct API calls — see orchestrator/genie_space.py.

API Reference:
    https://docs.databricks.com/api/workspace/genie

Design notes:
    - Genie space creation uses the template notebook pattern (framework/templates/genie_space_notebook.py.template)
    - This service handles lifecycle management (find/delete for idempotent runs)
    - Raises GenieError on API failures

See docs/design_phase2.md Section 2.4 for full method reference.
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
class GenieSpace:
    """Genie space metadata."""
    space_id: str
    title: str
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class GenieError(Exception):
    """Raised when a Genie Spaces API call fails."""

    def __init__(self, message: str, space_id: str = "", operation: str = ""):
        self.space_id = space_id
        self.operation = operation
        super().__init__(f"GenieError [{operation}]: {message}")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class GenieService:
    """Stateless wrapper around the Databricks Genie Spaces API.

    Usage:
        genie = GenieService()
        space = genie.find_by_title("Claims Analytics")
        if space:
            genie.delete_space(space.space_id)
    """

    def __init__(self, client: Optional[WorkspaceClient] = None,
                 user_token: Optional[str] = None):
        """Initialize with an optional pre-configured WorkspaceClient.

        Args:
            client: Databricks SDK WorkspaceClient. If None, creates one.
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
    # Query & Search
    # ------------------------------------------------------------------

    def list_spaces(self) -> list:
        """List all Genie spaces accessible to the current user.

        Returns:
            List of GenieSpace objects.

        Raises:
            GenieError: If the list request fails.
        """
        try:
            response = self._client.genie.list_spaces()
            spaces = []
            for space in (response.spaces or []):
                spaces.append(GenieSpace(
                    space_id=space.space_id,
                    title=space.title or "",
                    description=space.description
                ))
            return spaces
        except Exception as e:
            raise GenieError(str(e), operation="list_spaces") from e

    def find_by_title(self, title: str) -> Optional[GenieSpace]:
        """Find a Genie space by its title (exact match).

        Args:
            title: Exact title to search for.

        Returns:
            GenieSpace if found, None otherwise.
        """
        spaces = self.list_spaces()
        for space in spaces:
            if space.title == title:
                return space
        return None

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_space(self, space_id: str) -> None:
        """Delete a Genie space by ID.

        Args:
            space_id: ID of the Genie space to delete.

        Raises:
            GenieError: If deletion fails.
        """
        try:
            self._client.genie.delete(space_id=space_id)
            logger.info(f"Deleted Genie space: {space_id}")
        except Exception as e:
            # Treat not-found as success (idempotent)
            if "NOT_FOUND" in str(e) or "RESOURCE_DOES_NOT_EXIST" in str(e):
                logger.debug(f"Genie space already absent: {space_id}")
                return
            raise GenieError(
                str(e), space_id=space_id, operation="delete_space"
            ) from e

    def delete_by_title(self, title: str) -> bool:
        """Find and delete a Genie space by title (idempotent).

        Used to ensure clean slate before recreation.

        Args:
            title: Title of the Genie space to delete.

        Returns:
            True if a space was found and deleted, False if not found.
        """
        space = self.find_by_title(title)
        if space:
            self.delete_space(space.space_id)
            return True
        logger.debug(f"Genie space not found for deletion: {title}")
        return False

    # ------------------------------------------------------------------
    # Create & Update
    # ------------------------------------------------------------------

    def create_space(self, title: str, serialized_space: str,
                     warehouse_id: str, description: str = "",
                     parent_path: str = "") -> dict:
        """Create a new Genie space via the official REST API.

        Uses POST /api/2.0/genie/spaces with full serialized_space payload.

        Args:
            title: Display title for the space.
            serialized_space: Full JSON configuration string (built by template helper).
            warehouse_id: SQL warehouse ID for the space.
            description: Optional description.
            parent_path: Optional parent workspace path.

        Returns:
            dict with space_id, title, and other response fields.

        Raises:
            GenieError: If creation fails.
        """
        payload = {
            "title": title,
            "warehouse_id": warehouse_id,
            "serialized_space": serialized_space,
        }
        if description:
            payload["description"] = description
        if parent_path:
            payload["parent_path"] = parent_path

        try:
            response = self._client.api_client.do(
                "POST", "/api/2.0/genie/spaces", body=payload
            )
            space_id = response.get("space_id") or response.get("id", "")
            logger.info(f"Created Genie space: {space_id} ({title})")
            return response
        except Exception as e:
            raise GenieError(
                str(e), operation="create_space"
            ) from e

    def update_space(self, space_id: str, title: str, serialized_space: str,
                     warehouse_id: str, description: str = "") -> dict:
        """Update an existing Genie space via the official REST API.

        Uses PUT /api/2.0/genie/spaces/{space_id} with full serialized_space.

        Args:
            space_id: ID of existing space to update.
            title: Updated title.
            serialized_space: Full JSON configuration string.
            warehouse_id: SQL warehouse ID.
            description: Optional updated description.

        Returns:
            dict with space_id and updated response fields.

        Raises:
            GenieError: If update fails.
        """
        payload = {
            "title": title,
            "warehouse_id": warehouse_id,
            "serialized_space": serialized_space,
        }
        if description:
            payload["description"] = description

        try:
            response = self._client.api_client.do(
                "PUT", f"/api/2.0/genie/spaces/{space_id}", body=payload
            )
            logger.info(f"Updated Genie space: {space_id} ({title})")
            return response
        except Exception as e:
            raise GenieError(
                str(e), space_id=space_id, operation="update_space"
            ) from e
