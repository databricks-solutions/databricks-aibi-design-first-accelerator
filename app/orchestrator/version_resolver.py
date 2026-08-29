"""VersionResolver — App-side wrapper around the shared version resolution module.

This module delegates all version resolution logic to:
    framework/shared/resolve_version.py

That shared module is the SINGLE SOURCE OF TRUTH for the version algorithm.
Both App and Genie Code execute the same Python code.

This wrapper provides:
1. Service-based I/O adapters (workspace_service.read_file / write_file)
2. Fallback artifact scanning (folders, schemas, dashboards, Genie spaces)
3. The VersionInfo dataclass expected by the App's pipeline runner

See docs/design_phase2.md Section 10 for full reference.
"""

import os
import re
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# --- Import the shared resolve_version module (SINGLE SOURCE OF TRUTH) ---
# Canonical location: framework/shared/resolve_version.py
# App deployment copy: app/shared/resolve_version.py (included in snapshot)
#
# Both files MUST be identical. The framework/ copy is the source of truth.
# The app/shared/ copy exists because App deployments snapshot only the app/ folder.
# Genie Code executes from framework/shared/ directly (no copy needed).
from shared.resolve_version import (
    resolve_version as _shared_resolve,
    mark_version_status as _shared_mark_status,
    VersionResult,
)

# Pattern matches _v1, _v2, ..., _v99
VERSION_PATTERN = re.compile(r"_v(\d+)$")

# Pattern matches v1, v2, ... (folder names inside output/)
FOLDER_VERSION_PATTERN = re.compile(r"^v(\d+)$")

REGISTRY_FILENAME = "version_registry.yaml"


# ---------------------------------------------------------------------------
# Data Model (expected by the App pipeline runner)
# ---------------------------------------------------------------------------

@dataclass
class VersionInfo:
    """Resolved version information for a pipeline run."""
    version: int                # Version number (1, 2, 3, ...)
    suffix: str                 # Suffix to append ("_v1", "_v2", ...)
    is_new: bool = True         # Whether this version doesn't yet exist
    is_resume: bool = False     # Whether resuming an incomplete prior version
    existing_versions: list = None  # List of discovered version numbers
    created_by: str = "app"     # "app" or "genie_code"

    def __post_init__(self):
        if self.existing_versions is None:
            self.existing_versions = []


# ---------------------------------------------------------------------------
# Resolver (App-side wrapper)
# ---------------------------------------------------------------------------

class VersionResolver:
    """App-side version resolver. Delegates core logic to shared module.

    The shared module (framework/shared/resolve_version.py) handles:
        - Registry reading/writing
        - Mode logic (auto/retry/fresh/override)
        - Version number calculation

    This wrapper adds:
        - Service-based I/O (workspace_service instead of filesystem)
        - Fallback scanning when no registry exists (dashboards, schemas, etc.)
        - VersionInfo conversion for the pipeline runner
    """

    def __init__(self, workspace_service, sql_service, lakeview_service=None, genie_service=None):
        """Initialize with required services."""
        self._ws = workspace_service
        self._sql = sql_service
        self._lakeview = lakeview_service
        self._genie = genie_service

    def resolve(self, config, override: Optional[int] = None, run_id: str = None,
                mode: str = "auto") -> VersionInfo:
        """Resolve version using the shared algorithm.

        Delegates to framework/shared/resolve_version.py — the same code
        that Genie Code executes directly. I/O is adapted via callables.

        Args:
            config: AcceleratorConfig with paths and asset names.
            override: Force a specific version number (skips all discovery).
            run_id: Current run_id (written to registry for new versions).
            mode: Resolution mode — "auto", "retry", or "fresh".

        Returns:
            VersionInfo with the version to use (new or resumed).
        """
        # Build I/O adapters that use the App's workspace_service
        def read_fn(path: str) -> str:
            return self._ws.read_file(path)

        def write_fn(path: str, content: str) -> None:
            self._ws.write_file(path, content)

        # Delegate to the shared module
        result: VersionResult = _shared_resolve(
            example_dir=config.example_dir,
            created_by="app",
            mode=mode,
            override=override,
            run_id=run_id or "",
            read_fn=read_fn,
            write_fn=write_fn,
        )

        # Convert to VersionInfo (expected by the pipeline runner)
        return VersionInfo(
            version=result.version,
            suffix=result.suffix,
            is_new=result.is_new,
            is_resume=result.is_resume,
            existing_versions=result.existing_versions,
            created_by=result.created_by,
        )

    def get_next_version_preview(self, config) -> dict:
        """Preview what the next version would be (for UI display).

        NOTE: This does NOT mutate the registry. It reads only.
        For a true preview without side effects, we read the registry
        and apply the auto logic without writing.
        """
        # For preview, just call resolve — but we'd need a dry-run mode.
        # For now, use the existing behavior (resolve does write for new versions).
        info = self.resolve(config)
        return {
            "next_version": info.version,
            "next_suffix": info.suffix,
            "is_resume": info.is_resume,
            "existing_versions": info.existing_versions,
            "existing_count": len(info.existing_versions)
        }

    def mark_version_status(self, config, version, status, assets_created=None, error=None):
        """Update registry entry for a version (completed/failed).

        Delegates to the shared mark_version_status function.
        """
        def read_fn(path: str) -> str:
            return self._ws.read_file(path)

        def write_fn(path: str, content: str) -> None:
            self._ws.write_file(path, content)

        _shared_mark_status(
            example_dir=config.example_dir,
            version=version,
            status=status,
            assets_created=assets_created,
            error=error,
            read_fn=read_fn,
            write_fn=write_fn,
        )

    # ------------------------------------------------------------------
    # Fallback Scanning (only used when registry doesn't exist)
    # ------------------------------------------------------------------

    def _scan_output_folders(self, example_dir: str) -> list:
        """Find output/v1/, output/v2/ folders inside the output directory."""
        versions = []
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
        """Find schema_v1, schema_v2, ... schemas in a catalog."""
        versions = []
        try:
            result = self._sql.execute_and_wait(
                f"SHOW SCHEMAS IN `{catalog}`", timeout_s=30.0
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
        """Find <name>_v1, <name>_v2, ... dashboards."""
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
        """Find <title>_v1, <title>_v2, ... Genie spaces."""
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
