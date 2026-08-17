"""WorkspaceService — Databricks Workspace REST API wrapper.

Provides file/folder CRUD operations for the pipeline.
All methods are stateless and accept explicit parameters.

API Reference:
    https://docs.databricks.com/api/workspace/workspace

Design notes:
    - Never uses dbutils.fs on /Workspace/ paths (serverless-safe)
    - All paths must be absolute workspace paths
    - Content encoding: base64 for import/export
    - Raises WorkspaceError on API failures

See docs/design_phase2.md Section 2.1 for full method reference.
"""

import base64
import logging
from dataclasses import dataclass
from typing import Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import (
    ExportFormat,
    ImportFormat,
    Language,
    ObjectType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    """Metadata for a workspace object (file, directory, notebook)."""
    path: str
    object_type: str  # FILE, DIRECTORY, NOTEBOOK, REPO
    language: Optional[str] = None
    size: Optional[int] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WorkspaceError(Exception):
    """Raised when a Workspace API call fails."""

    def __init__(self, message: str, path: str = "", operation: str = ""):
        self.path = path
        self.operation = operation
        super().__init__(f"WorkspaceError [{operation}] {path}: {message}")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class WorkspaceService:
    """Stateless wrapper around the Databricks Workspace API.

    Supports two auth modes:
        - SP auth (default): uses the app's service principal credentials
        - User auth (token): uses the logged-in user's forwarded OAuth token
          for operations requiring the user's permissions (e.g. writing to
          their workspace folders). Pass user_token to enable this.

    Usage:
        ws = WorkspaceService()  # SP auth (default)
        ws = WorkspaceService(user_token="eyJ...")  # user auth for writes
        content = ws.read_file("/path/to/file.txt")
        ws.write_file("/Workspace/Users/me/output.yaml", yaml_content)
    """

    def __init__(self, client: Optional[WorkspaceClient] = None,
                 user_token: Optional[str] = None):
        """Initialize with an optional pre-configured WorkspaceClient.

        Args:
            client: Databricks SDK WorkspaceClient. If None, creates one
                    using default environment authentication (or user_token).
            user_token: If provided, creates a WorkspaceClient authenticated
                        as the user (for write operations on user-owned files).
        """
        if client:
            self._client = client
        elif user_token:
            import os
            from databricks.sdk.config import Config
            host = os.environ.get('DATABRICKS_HOST', '')
            # Force PAT auth to avoid conflict with SP OAuth env vars
            # (DATABRICKS_CLIENT_ID/SECRET are set by the app runtime)
            cfg = Config(host=host, token=user_token, auth_type="pat")
            self._client = WorkspaceClient(config=cfg)
        else:
            self._client = WorkspaceClient()

    # ------------------------------------------------------------------
    # Read Operations
    # ------------------------------------------------------------------

    def read_file(self, path: str) -> str:
        """Read file content as UTF-8 string.

        Supports both local filesystem paths and workspace API paths.
        If path starts with /Workspace, uses the workspace REST API.
        Otherwise, reads directly from local filesystem (for source-deployed files).

        Args:
            path: Absolute path (local or /Workspace/...)

        Returns:
            File content as string.

        Raises:
            WorkspaceError: If the file does not exist or cannot be read.
        """
        try:
            if path.startswith('/Workspace'):
                # Use workspace API
                response = self._client.workspace.export(
                    path=path,
                    format=ExportFormat.AUTO
                )
                if response.content:
                    return base64.b64decode(response.content).decode("utf-8")
                return ""
            else:
                # Read from local filesystem (deployed with source)
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception as e:
            raise WorkspaceError(str(e), path=path, operation="read_file") from e

    def read_binary(self, path: str) -> bytes:
        """Read file content as raw bytes (for images, binary files).

        Supports both local filesystem paths and workspace API paths.

        Args:
            path: Absolute path (local or /Workspace/...)

        Returns:
            File content as bytes.

        Raises:
            WorkspaceError: If the file does not exist or cannot be read.
        """
        try:
            if path.startswith('/Workspace'):
                response = self._client.workspace.export(
                    path=path,
                    format=ExportFormat.AUTO
                )
                if response.content:
                    return base64.b64decode(response.content)
                return b""
            else:
                with open(path, 'rb') as f:
                    return f.read()
        except Exception as e:
            raise WorkspaceError(str(e), path=path, operation="read_binary") from e

    def file_exists(self, path: str) -> bool:
        """Check if a path exists (local filesystem or workspace).

        Args:
            path: Absolute path (local or /Workspace/...).

        Returns:
            True if the path exists (file or directory), False otherwise.
        """
        if path.startswith('/Workspace'):
            try:
                self._client.workspace.get_status(path=path)
                return True
            except Exception:
                return False
        else:
            import os as _os
            return _os.path.exists(path)

    def list_dir(self, path: str) -> list:
        """List contents of a directory (local filesystem or workspace).

        Args:
            path: Absolute path (local or /Workspace/...).

        Returns:
            List of FileInfo objects for each entry in the directory.

        Raises:
            WorkspaceError: If the directory does not exist.
        """
        try:
            if path.startswith('/Workspace'):
                objects = self._client.workspace.list(path=path)
                results = []
                for obj in objects:
                    results.append(FileInfo(
                        path=obj.path,
                        object_type=obj.object_type.value if obj.object_type else "UNKNOWN",
                        language=obj.language.value if obj.language else None,
                        size=obj.size
                    ))
                return results
            else:
                import os as _os
                results = []
                for entry in _os.listdir(path):
                    full_path = _os.path.join(path, entry)
                    obj_type = "DIRECTORY" if _os.path.isdir(full_path) else "FILE"
                    size = _os.path.getsize(full_path) if obj_type == "FILE" else None
                    results.append(FileInfo(
                        path=full_path,
                        object_type=obj_type,
                        size=size
                    ))
                return results
        except Exception as e:
            raise WorkspaceError(str(e), path=path, operation="list_dir") from e

    # ------------------------------------------------------------------
    # Write Operations
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str, overwrite: bool = True) -> None:
        """Write string content to a workspace file.

        Creates parent directories automatically if they don't exist.

        Args:
            path: Absolute workspace path for the file.
            content: UTF-8 string content to write.
            overwrite: If True, overwrite existing file. Default True.

        Raises:
            WorkspaceError: If the write fails.
        """
        try:
            # Ensure parent directory exists
            parent = "/".join(path.rsplit("/", 1)[:-1])
            if parent:
                self.mkdirs(parent)

            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            self._client.workspace.import_(
                path=path,
                content=encoded,
                format=ImportFormat.AUTO,
                overwrite=overwrite
            )
            logger.debug(f"Written: {path} ({len(content)} chars)")
        except Exception as e:
            raise WorkspaceError(str(e), path=path, operation="write_file") from e

    def mkdirs(self, path: str) -> None:
        """Create directory and all parent directories.

        Args:
            path: Absolute workspace path for the directory.

        Raises:
            WorkspaceError: If directory creation fails.
        """
        try:
            self._client.workspace.mkdirs(path=path)
        except Exception as e:
            raise WorkspaceError(str(e), path=path, operation="mkdirs") from e

    def delete(self, path: str, recursive: bool = False) -> None:
        """Delete a workspace file or directory.

        Args:
            path: Absolute workspace path to delete.
            recursive: If True, delete directory contents recursively.

        Raises:
            WorkspaceError: If deletion fails (path not found is NOT an error).
        """
        try:
            self._client.workspace.delete(path=path, recursive=recursive)
            logger.info(f"Deleted: {path} (recursive={recursive})")
        except Exception as e:
            # Treat "not found" as success (idempotent delete)
            if "RESOURCE_DOES_NOT_EXIST" in str(e):
                logger.debug(f"Already absent: {path}")
                return
            raise WorkspaceError(str(e), path=path, operation="delete") from e

    # ------------------------------------------------------------------
    # Notebook Operations
    # ------------------------------------------------------------------

    def import_notebook(
        self,
        path: str,
        content: str,
        language: str = "PYTHON",
        fmt: str = "SOURCE",
        overwrite: bool = True
    ) -> None:
        """Import a notebook to the workspace.

        Args:
            path: Absolute workspace path for the notebook (no extension).
            content: Notebook source code (or base64-encoded Jupyter JSON).
            language: PYTHON, SQL, SCALA, or R.
            fmt: SOURCE (plain code) or JUPYTER (ipynb JSON).
            overwrite: If True, overwrite existing notebook.

        Raises:
            WorkspaceError: If import fails.
        """
        try:
            # Ensure parent directory exists
            parent = "/".join(path.rsplit("/", 1)[:-1])
            if parent:
                self.mkdirs(parent)

            language_enum = Language[language.upper()]
            format_enum = ImportFormat[fmt.upper()]

            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            self._client.workspace.import_(
                path=path,
                content=encoded,
                language=language_enum,
                format=format_enum,
                overwrite=overwrite
            )
            logger.info(f"Imported notebook: {path} (lang={language}, fmt={fmt})")
        except Exception as e:
            raise WorkspaceError(str(e), path=path, operation="import_notebook") from e

    # ------------------------------------------------------------------
    # Convenience Methods
    # ------------------------------------------------------------------

    def read_yaml(self, path: str) -> dict:
        """Read and parse a YAML file from the workspace.

        Args:
            path: Absolute workspace path to a .yaml/.yml file.

        Returns:
            Parsed YAML as a Python dict.

        Raises:
            WorkspaceError: If file cannot be read or parsed.
        """
        import yaml
        content = self.read_file(path)
        try:
            return yaml.safe_load(content) or {}
        except yaml.YAMLError as e:
            raise WorkspaceError(
                f"YAML parse error: {e}", path=path, operation="read_yaml"
            ) from e

    def write_yaml(self, path: str, data: dict) -> None:
        """Serialize a dict to YAML and write to workspace.

        Args:
            path: Absolute workspace path for the .yaml file.
            data: Python dict to serialize.
        """
        import yaml
        content = yaml.dump(data, default_flow_style=False, sort_keys=False)
        self.write_file(path, content)

    def ensure_clean_directory(self, path: str) -> None:
        """Delete and recreate a directory (idempotent clean start).

        Args:
            path: Absolute workspace path for the directory.
        """
        self.delete(path, recursive=True)
        self.mkdirs(path)
        logger.info(f"Clean directory ready: {path}")
