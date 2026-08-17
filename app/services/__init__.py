"""Services layer — stateless Databricks API wrappers.

Each service wraps a single API surface:
- WorkspaceService: Workspace file/folder CRUD
- SQLService: Statement Execution API
- LakeviewService: Dashboard API
- GenieService: Genie Spaces API
- JobsService: One-time notebook runs

See docs/design_phase2.md Section 2 for full API reference.
"""

from services.workspace_io import WorkspaceService, WorkspaceError, FileInfo
from services.sql_client import SQLService, SQLError, StatementResult, Column
from services.lakeview_client import LakeviewService, LakeviewError, Dashboard
from services.genie_client import GenieService, GenieError, GenieSpace
from services.jobs_client import JobsService, JobsError, RunResult

__all__ = [
    # Services
    "WorkspaceService",
    "SQLService",
    "LakeviewService",
    "GenieService",
    "JobsService",
    # Errors
    "WorkspaceError",
    "SQLError",
    "LakeviewError",
    "GenieError",
    "JobsError",
    # Models
    "FileInfo",
    "StatementResult",
    "Column",
    "Dashboard",
    "GenieSpace",
    "RunResult",
]
