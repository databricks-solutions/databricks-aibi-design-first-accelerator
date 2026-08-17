"""SQLService — Databricks Statement Execution API wrapper.

Provides SQL execution against a SQL warehouse with polling and result parsing.
All methods are stateless and accept explicit parameters.

API Reference:
    https://docs.databricks.com/api/workspace/statementexecution

Design notes:
    - Uses Statement Execution API (not DBSQL connector) for serverless compat
    - Polls for completion with exponential backoff
    - Returns structured results (schema + data rows)
    - Raises SQLError on execution failures with full error context

See docs/design_phase2.md Section 2.2 for full method reference.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    StatementState,
    Disposition,
    Format,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class Column:
    """Column metadata from a table schema."""
    name: str
    type: str
    comment: Optional[str] = None
    nullable: bool = True


@dataclass
class StatementResult:
    """Result of a SQL statement execution."""
    statement_id: str
    status: str  # SUCCEEDED, FAILED, CANCELED, RUNNING, PENDING
    columns: list = field(default_factory=list)  # list[Column]
    data: list = field(default_factory=list)  # list[list[Any]]
    error: Optional[str] = None
    row_count: int = 0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SQLError(Exception):
    """Raised when a SQL statement execution fails."""

    def __init__(self, message: str, sql: str = "", statement_id: str = ""):
        self.sql = sql
        self.statement_id = statement_id
        super().__init__(f"SQLError: {message}")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SQLService:
    """Stateless wrapper around the Databricks Statement Execution API.

    Usage:
        sql_svc = SQLService(warehouse_id="abc123")
        result = sql_svc.execute_and_wait("SELECT 1 AS x")
        print(result.data)  # [[1]]
    """

    # Polling configuration
    POLL_INTERVAL_INITIAL = 0.5  # seconds
    POLL_INTERVAL_MAX = 5.0  # seconds
    POLL_BACKOFF_FACTOR = 1.5

    def __init__(
        self,
        warehouse_id: str,
        client: Optional[WorkspaceClient] = None
    ):
        """Initialize with warehouse ID and optional client.

        Args:
            warehouse_id: SQL warehouse ID to execute statements against.
            client: Databricks SDK WorkspaceClient. If None, creates one.
        """
        self._warehouse_id = warehouse_id
        self._client = client or WorkspaceClient()

    # ------------------------------------------------------------------
    # Core Execution
    # ------------------------------------------------------------------

    def execute(self, sql: str, catalog: str = None, schema: str = None) -> str:
        """Submit a SQL statement for execution (non-blocking).

        Args:
            sql: SQL statement to execute.
            catalog: Optional default catalog for the statement.
            schema: Optional default schema for the statement.

        Returns:
            Statement ID for polling.

        Raises:
            SQLError: If the submission fails.
        """
        try:
            response = self._client.statement_execution.execute_statement(
                statement=sql,
                warehouse_id=self._warehouse_id,
                catalog=catalog,
                schema=schema,
                disposition=Disposition.INLINE,
                format=Format.JSON_ARRAY,
                wait_timeout="0s"  # non-blocking
            )
            return response.statement_id
        except Exception as e:
            raise SQLError(str(e), sql=sql) from e

    def execute_and_wait(
        self,
        sql: str,
        timeout_s: float = 120.0,
        catalog: str = None,
        schema: str = None
    ) -> StatementResult:
        """Execute SQL and poll until completion.

        Args:
            sql: SQL statement to execute.
            timeout_s: Maximum seconds to wait for completion.
            catalog: Optional default catalog.
            schema: Optional default schema.

        Returns:
            StatementResult with columns, data, and status.

        Raises:
            SQLError: If execution fails or times out.
        """
        try:
            response = self._client.statement_execution.execute_statement(
                statement=sql,
                warehouse_id=self._warehouse_id,
                catalog=catalog,
                schema=schema,
                disposition=Disposition.INLINE,
                format=Format.JSON_ARRAY,
                wait_timeout=f"{min(int(timeout_s), 50)}s"  # API max is 50s; poll for longer
            )

            # Check if we need to poll
            if response.status and response.status.state in (
                StatementState.PENDING, StatementState.RUNNING
            ):
                return self._poll_until_complete(response.statement_id, timeout_s)

            return self._parse_response(response)

        except SQLError:
            raise
        except Exception as e:
            raise SQLError(str(e), sql=sql) from e

    # ------------------------------------------------------------------
    # Convenience Methods
    # ------------------------------------------------------------------

    def get_table_schema(self, fqn: str) -> list:
        """Get column metadata for a table or view.

        Args:
            fqn: Fully qualified table name (catalog.schema.table).

        Returns:
            List of Column objects.

        Raises:
            SQLError: If table does not exist.
        """
        result = self.execute_and_wait(f"DESCRIBE TABLE EXTENDED {fqn}")
        columns = []
        for row in result.data:
            if row and len(row) >= 2:
                name, col_type = row[0], row[1]
                # Skip metadata rows (start with # or are empty)
                if name and not name.startswith("#") and name.strip():
                    comment = row[2] if len(row) > 2 else None
                    columns.append(Column(
                        name=name.strip(),
                        type=col_type.strip() if col_type else "string",
                        comment=comment
                    ))
        return columns

    def table_exists(self, fqn: str) -> bool:
        """Check if a table or view exists.

        Args:
            fqn: Fully qualified table name (catalog.schema.table).

        Returns:
            True if the table exists, False otherwise.
        """
        try:
            self.execute_and_wait(f"DESCRIBE TABLE {fqn}")
            return True
        except SQLError:
            return False

    def get_row_count(self, fqn: str) -> int:
        """Get row count for a table.

        Args:
            fqn: Fully qualified table name.

        Returns:
            Number of rows.
        """
        result = self.execute_and_wait(f"SELECT COUNT(*) AS cnt FROM {fqn}")
        if result.data and result.data[0]:
            return int(result.data[0][0])
        return 0

    def sample_rows(self, fqn: str, n: int = 5) -> list:
        """Get sample rows from a table.

        Args:
            fqn: Fully qualified table name.
            n: Number of rows to sample.

        Returns:
            List of dicts (column_name -> value).
        """
        result = self.execute_and_wait(f"SELECT * FROM {fqn} LIMIT {n}")
        col_names = [c.name for c in result.columns]
        rows = []
        for row_data in result.data:
            rows.append(dict(zip(col_names, row_data)))
        return rows

    def execute_ddl(self, sql: str) -> StatementResult:
        """Execute a DDL statement (CREATE, DROP, ALTER).

        Convenience wrapper that uses a longer timeout for DDL operations.

        Args:
            sql: DDL SQL statement.

        Returns:
            StatementResult (usually empty data for DDL).
        """
        return self.execute_and_wait(sql, timeout_s=300.0)

    # ------------------------------------------------------------------
    # Internal Methods
    # ------------------------------------------------------------------

    def _poll_until_complete(
        self, statement_id: str, timeout_s: float
    ) -> StatementResult:
        """Poll statement status until completion or timeout."""
        start = time.time()
        interval = self.POLL_INTERVAL_INITIAL

        while (time.time() - start) < timeout_s:
            response = self._client.statement_execution.get_statement(statement_id)
            state = response.status.state if response.status else None

            if state == StatementState.SUCCEEDED:
                return self._parse_response(response)
            elif state in (StatementState.FAILED, StatementState.CANCELED, StatementState.CLOSED):
                error_msg = ""
                if response.status and response.status.error:
                    error_msg = response.status.error.message or str(response.status.error)
                raise SQLError(
                    error_msg or f"Statement {state.value}",
                    statement_id=statement_id
                )

            time.sleep(interval)
            interval = min(interval * self.POLL_BACKOFF_FACTOR, self.POLL_INTERVAL_MAX)

        raise SQLError(
            f"Timeout after {timeout_s}s waiting for statement",
            statement_id=statement_id
        )

    def _parse_response(self, response) -> StatementResult:
        """Parse API response into StatementResult.

        Raises SQLError if the statement failed.
        """
        columns = []
        data = []
        error = None

        # Parse status
        status = "UNKNOWN"
        if response.status:
            status = response.status.state.value if response.status.state else "UNKNOWN"
            if response.status.error:
                error = response.status.error.message

        # Raise on FAILED/CANCELED (same behavior as _poll_until_complete)
        if status in ("FAILED", "CANCELED", "CLOSED"):
            raise SQLError(
                error or f"Statement {status}",
                statement_id=response.statement_id or ""
            )

        # Parse schema
        if response.manifest and response.manifest.schema:
            for col in response.manifest.schema.columns or []:
                columns.append(Column(
                    name=col.name,
                    type=col.type_text or "string",
                    comment=None
                ))

        # Parse data
        if response.result and response.result.data_array:
            data = response.result.data_array

        row_count = len(data)
        if response.manifest and response.manifest.total_row_count:
            row_count = response.manifest.total_row_count

        return StatementResult(
            statement_id=response.statement_id or "",
            status=status,
            columns=columns,
            data=data,
            error=error,
            row_count=row_count
        )
