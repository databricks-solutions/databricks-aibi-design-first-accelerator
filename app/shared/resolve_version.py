"""Standalone Version Resolution — shared by App and Genie Code.

This module is the SINGLE SOURCE OF TRUTH for version resolution logic.
Both execution environments use this same file:

  - App: imports resolve_version() and passes workspace_service I/O callables
  - Genie Code: executes this file via executeCode(python), using open() for I/O

Do NOT duplicate this logic elsewhere. If the algorithm changes, change it HERE.

Dependencies: stdlib only + PyYAML (available in both environments).
No Flask, no Databricks SDK, no service classes.

See 00_master_prompt.md Step 0.3 for the contract this implements.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, List

import yaml

logger = logging.getLogger(__name__)

REGISTRY_FILENAME = "version_registry.yaml"


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class VersionResult:
    """Result of version resolution."""
    version: int                    # Version number (1, 2, 3, ...)
    suffix: str                     # Suffix to append ("_v1", "_v2", ...)
    is_new: bool = True             # Whether this is a brand new version
    is_resume: bool = False         # Whether resuming an existing version
    created_by: str = "app"         # "app" or "genie_code"
    existing_versions: List[int] = field(default_factory=list)
    mode_used: str = "auto"         # Which mode was applied


# ---------------------------------------------------------------------------
# Core Resolution Function
# ---------------------------------------------------------------------------

def resolve_version(
    example_dir: str,
    created_by: str = "app",
    mode: str = "auto",
    override: Optional[int] = None,
    run_id: str = "",
    read_fn: Optional[Callable[[str], str]] = None,
    write_fn: Optional[Callable[[str, str], None]] = None,
) -> VersionResult:
    """Resolve which version to use for this pipeline run.

    This is the SHARED algorithm used by both App and Genie Code.
    The mode parameter controls behavior:

        mode="auto" (default):
            - `running` (same env) -> RESUME
            - `failed` / `completed` / `abandoned` -> NEW VERSION
            Used by: App "Run Pipeline" button, Genie Code default

        mode="retry":
            - Find latest `failed` or `running` entry from same env -> RESUME
            - If none found -> NEW VERSION
            Used by: App "Retry" button, Genie Code "retry the failed run"

        mode="fresh":
            - Always create a NEW VERSION regardless of any status
            Used by: App "New Version" button, Genie Code "start completely fresh"

    Args:
        example_dir: Path to the domain folder (contains version_registry.yaml).
        created_by: Current environment identifier ("app" or "genie_code").
        mode: Resolution mode — "auto", "retry", or "fresh".
        override: If provided, force this exact version number (skips all logic).
        run_id: Current run ID (written to registry for new versions).
        read_fn: Callable(path) -> str. Reads a file and returns content.
                 Default: uses built-in open() (works in Genie Code on serverless).
        write_fn: Callable(path, content) -> None. Writes content to a file.
                  Default: uses built-in open() (works in Genie Code on serverless).

    Returns:
        VersionResult with the resolved version info.
    """
    # Default I/O: filesystem (works in Genie Code executeCode environment)
    if read_fn is None:
        read_fn = _default_read
    if write_fn is None:
        write_fn = _default_write

    registry_path = f"{example_dir}/{REGISTRY_FILENAME}"

    # --- OVERRIDE: explicit version lock ---
    if override is not None:
        registry = _read_registry(registry_path, read_fn)
        if registry:
            for entry in registry.get('versions', []):
                if entry.get('version') == override:
                    entry['status'] = 'running'
                    _write_registry(registry_path, registry, write_fn)
                    break
        logger.info(f"Version override: forcing v{override} (resume)")
        return VersionResult(
            version=override,
            suffix=f"_v{override}",
            is_new=False,
            is_resume=True,
            created_by=created_by,
            mode_used="override",
        )

    # --- Read registry ---
    registry = _read_registry(registry_path, read_fn)

    if not registry or not registry.get('versions'):
        # No registry: first-ever run -> create v1
        next_version = 1
        registry = _bootstrap_registry(example_dir, next_version, created_by, run_id)
        _write_registry(registry_path, registry, write_fn)
        logger.info(f"No registry found. Bootstrapping v{next_version}.")
        return VersionResult(
            version=next_version,
            suffix=f"_v{next_version}",
            is_new=True,
            is_resume=False,
            created_by=created_by,
            existing_versions=[],
            mode_used=mode,
        )

    # --- Registry exists: apply mode logic ---
    versions_list = registry['versions']
    all_version_nums = sorted(v.get('version', 0) for v in versions_list)
    max_version = max(all_version_nums) if all_version_nums else 0

    # --- MODE: fresh — always new ---
    if mode == "fresh":
        next_version = max_version + 1
        _append_version(registry, next_version, created_by, run_id)
        _write_registry(registry_path, registry, write_fn)
        logger.info(f"[mode=fresh] Creating new v{next_version}")
        return VersionResult(
            version=next_version,
            suffix=f"_v{next_version}",
            is_new=True,
            is_resume=False,
            created_by=created_by,
            existing_versions=all_version_nums,
            mode_used="fresh",
        )

    # --- MODE: retry — resume latest failed/running from same env ---
    if mode == "retry":
        retryable = None
        for entry in reversed(sorted(versions_list, key=lambda v: v.get('version', 0))):
            if (entry.get('status') in ('failed', 'running')
                    and entry.get('created_by') == created_by):
                retryable = entry
                break
        if retryable:
            retry_version = retryable.get('version', 1)
            retryable['status'] = 'running'
            _write_registry(registry_path, registry, write_fn)
            logger.info(f"[mode=retry] Resuming v{retry_version} (was {retryable.get('status')})")
            return VersionResult(
                version=retry_version,
                suffix=f"_v{retry_version}",
                is_new=False,
                is_resume=True,
                created_by=created_by,
                existing_versions=all_version_nums,
                mode_used="retry",
            )
        # No retryable version found — fall through to create new
        logger.info(f"[mode=retry] No failed version found for {created_by}, creating new")

    # --- MODE: auto (default) — resume only 'running', else new ---
    resumable = None
    for entry in reversed(sorted(versions_list, key=lambda v: v.get('version', 0))):
        if (entry.get('status') == 'running'
                and entry.get('created_by') == created_by):
            resumable = entry
            break

    if resumable:
        resume_version = resumable.get('version', 1)
        logger.info(f"[mode=auto] Resuming v{resume_version} (status=running, created_by={created_by})")
        return VersionResult(
            version=resume_version,
            suffix=f"_v{resume_version}",
            is_new=False,
            is_resume=True,
            created_by=created_by,
            existing_versions=all_version_nums,
            mode_used="auto",
        )

    # No resumable version — create new
    next_version = max_version + 1
    _append_version(registry, next_version, created_by, run_id)
    _write_registry(registry_path, registry, write_fn)
    logger.info(f"[mode=auto] No resumable version. Creating v{next_version}")
    return VersionResult(
        version=next_version,
        suffix=f"_v{next_version}",
        is_new=True,
        is_resume=False,
        created_by=created_by,
        existing_versions=all_version_nums,
        mode_used="auto",
    )


# ---------------------------------------------------------------------------
# Registry update helper (for marking completion/failure)
# ---------------------------------------------------------------------------

def mark_version_status(
    example_dir: str,
    version: int,
    status: str,
    assets_created: Optional[dict] = None,
    error: Optional[str] = None,
    read_fn: Optional[Callable[[str], str]] = None,
    write_fn: Optional[Callable[[str, str], None]] = None,
) -> None:
    """Update a version's status in the registry.

    Called at end of run (completed/failed) by both App and Genie Code.

    Args:
        example_dir: Domain folder path.
        version: Version number to update.
        status: New status ("completed", "failed", "abandoned").
        assets_created: Optional dict of created asset counts.
        error: Optional error message (for failed status).
        read_fn/write_fn: I/O callables (same as resolve_version).
    """
    if read_fn is None:
        read_fn = _default_read
    if write_fn is None:
        write_fn = _default_write

    registry_path = f"{example_dir}/{REGISTRY_FILENAME}"
    registry = _read_registry(registry_path, read_fn)
    if not registry:
        logger.warning(f"Cannot update status: registry not found at {registry_path}")
        return

    for entry in registry.get('versions', []):
        if entry.get('version') == version:
            entry['status'] = status
            entry['completed_at'] = datetime.now(timezone.utc).isoformat()
            if status == 'completed' and assets_created:
                entry['assets_created'] = assets_created
            if error:
                entry['error_summary'] = str(error)[:500]
            break

    _write_registry(registry_path, registry, write_fn)
    logger.info(f"Registry updated: v{version} -> status={status}")


# ---------------------------------------------------------------------------
# Default I/O (filesystem — used by Genie Code executeCode)
# ---------------------------------------------------------------------------

def _default_read(path: str) -> str:
    """Read file from workspace filesystem (works on serverless compute)."""
    with open(path, 'r') as f:
        return f.read()


def _default_write(path: str, content: str) -> None:
    """Write file to workspace filesystem (works on serverless compute)."""
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

def _read_registry(path: str, read_fn: Callable) -> Optional[dict]:
    """Load registry YAML, return None if not found."""
    try:
        content = read_fn(path)
        return yaml.safe_load(content) if content else None
    except (FileNotFoundError, OSError, Exception) as e:
        logger.debug(f"Registry read failed ({path}): {e}")
        return None


def _write_registry(path: str, registry: dict, write_fn: Callable) -> None:
    """Persist registry YAML."""
    try:
        content = yaml.dump(registry, default_flow_style=False, sort_keys=False)
        write_fn(path, content)
    except Exception as e:
        logger.warning(f"Registry write failed ({path}): {e}")


def _append_version(registry: dict, version: int, created_by: str, run_id: str) -> None:
    """Append a new version entry to the registry."""
    registry.setdefault('versions', []).append({
        'version': version,
        'status': 'running',
        'created_by': created_by,
        'run_id': run_id or '',
        'started_at': datetime.now(timezone.utc).isoformat(),
        'assets_created': {},
    })


def _bootstrap_registry(example_dir: str, next_version: int,
                        created_by: str, run_id: str) -> dict:
    """Create a fresh registry with one new version entry."""
    domain_name = example_dir.rstrip('/').split('/')[-1]
    registry = {'domain': domain_name, 'versions': []}
    _append_version(registry, next_version, created_by, run_id)
    return registry


# ---------------------------------------------------------------------------
# CLI / Direct Execution (for Genie Code executeCode calls)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Direct execution interface for Genie Code.

    Usage (via executeCode):
        import sys
        sys.argv = [
            'resolve_version.py',
            '--example-dir', '/Workspace/.../kpi_domains/member_claims',
            '--mode', 'auto',           # auto | retry | fresh
            '--created-by', 'genie_code',
            '--run-id', '<uuid>',
            # Optional:
            # '--override', '2',
        ]
        exec(open('/Workspace/.../framework/shared/resolve_version.py').read())

    Or more simply:
        from resolve_version import resolve_version
        result = resolve_version(
            example_dir='/Workspace/.../kpi_domains/member_claims',
            created_by='genie_code',
            mode='auto',
        )
        print(result)
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Resolve pipeline version")
    parser.add_argument('--example-dir', required=True, help='Domain folder path')
    parser.add_argument('--mode', default='auto', choices=['auto', 'retry', 'fresh'])
    parser.add_argument('--created-by', default='genie_code')
    parser.add_argument('--run-id', default='')
    parser.add_argument('--override', type=int, default=None)

    args = parser.parse_args()

    result = resolve_version(
        example_dir=args.example_dir,
        created_by=args.created_by,
        mode=args.mode,
        override=args.override,
        run_id=args.run_id,
    )

    # Output as JSON for easy parsing
    print(json.dumps({
        'version': result.version,
        'suffix': result.suffix,
        'is_new': result.is_new,
        'is_resume': result.is_resume,
        'created_by': result.created_by,
        'mode_used': result.mode_used,
        'existing_versions': result.existing_versions,
    }, indent=2))
