"""JobsService — Databricks Jobs API wrapper for one-time notebook runs.

Provides notebook execution via the Jobs API runs/submit endpoint.
Used by the pipeline orchestrator to execute generated notebooks
(DDL, synthetic data, Genie space configuration).

API Reference:
    https://docs.databricks.com/api/workspace/jobs

Design notes:
    - Uses runs/submit (one-time runs), NOT jobs/create (recurring jobs)
    - Polls run status with exponential backoff until completion
    - Supports SQL warehouse task type for notebook execution
    - Raises JobsError on submission or execution failures

See docs/design_phase2.md Section 2.5 for full method reference.
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import (
    RunLifeCycleState,
    RunResultState,
    SubmitTask,
    NotebookTask,
    RunTask,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Result of a one-time notebook run."""
    run_id: int
    state: str  # TERMINATED, SKIPPED, INTERNAL_ERROR, BLOCKED, CANCELED
    result_state: Optional[str] = None  # SUCCESS, FAILED, TIMEDOUT, CANCELED
    output: Optional[str] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class JobsError(Exception):
    """Raised when a Jobs API operation fails."""

    def __init__(self, message: str, run_id: int = 0, operation: str = ""):
        self.run_id = run_id
        self.operation = operation
        super().__init__(f"JobsError [{operation}] run_id={run_id}: {message}")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class JobsService:
    """Stateless wrapper around the Databricks Jobs API for one-time runs.

    Usage:
        jobs = JobsService(warehouse_id="abc123")
        result = jobs.run_and_wait("/Workspace/Users/me/my_notebook")
        if result.result_state == "SUCCESS":
            print("Notebook completed successfully")
    """

    # Polling configuration
    POLL_INTERVAL_INITIAL = 2.0  # seconds
    POLL_INTERVAL_MAX = 15.0  # seconds
    POLL_BACKOFF_FACTOR = 1.5

    def __init__(
        self,
        warehouse_id: str,
        client: Optional[WorkspaceClient] = None
    ):
        """Initialize with warehouse ID and optional client.

        Args:
            warehouse_id: SQL warehouse ID for notebook task execution.
            client: Databricks SDK WorkspaceClient. If None, creates one.
        """
        self._warehouse_id = warehouse_id
        self._client = client or WorkspaceClient()

    # ------------------------------------------------------------------
    # Run Operations
    # ------------------------------------------------------------------

    def run_notebook(self, path: str, language: str = "SQL") -> int:
        """Submit a one-time notebook run (non-blocking).

        Args:
            path: Absolute workspace path to the notebook.
            language: Notebook language — "SQL" uses SQL warehouse,
                      "PYTHON" uses serverless compute.

        Returns:
            Run ID for status polling.

        Raises:
            JobsError: If submission fails.
        """
        try:
            # SQL notebooks run on SQL warehouse; Python notebooks on serverless
            if language.upper() == "SQL":
                task = SubmitTask(
                    task_key="notebook_run",
                    notebook_task=NotebookTask(
                        notebook_path=path,
                        warehouse_id=self._warehouse_id
                    )
                )
            else:
                # Python/Scala/R — use serverless compute (no warehouse_id)
                task = SubmitTask(
                    task_key="notebook_run",
                    notebook_task=NotebookTask(
                        notebook_path=path
                    )
                )

            response = self._client.jobs.submit(
                run_name=f"aibi-studio-{path.split('/')[-1]}",
                tasks=[task]
            )
            run_id = response.run_id
            logger.info(f"Submitted notebook run: {path} (run_id={run_id}, lang={language})")
            return run_id
        except Exception as e:
            raise JobsError(str(e), operation="run_notebook") from e

    def wait_for_run(self, run_id: int, timeout_s: float = 600.0) -> RunResult:
        """Poll a run until it completes or times out.

        Args:
            run_id: Run ID to monitor.
            timeout_s: Maximum seconds to wait (default 600 = 10 minutes).

        Returns:
            RunResult with final state and output.

        Raises:
            JobsError: If the run fails or times out.
        """
        start = time.time()
        interval = self.POLL_INTERVAL_INITIAL

        while (time.time() - start) < timeout_s:
            try:
                run = self._client.jobs.get_run(run_id=run_id)
            except Exception as e:
                raise JobsError(str(e), run_id=run_id, operation="wait_for_run") from e

            life_cycle_state = run.state.life_cycle_state if run.state else None

            if life_cycle_state in (
                RunLifeCycleState.TERMINATED,
                RunLifeCycleState.SKIPPED,
                RunLifeCycleState.INTERNAL_ERROR
            ):
                result_state = run.state.result_state.value if run.state.result_state else None
                error_msg = None
                if run.state.state_message:
                    error_msg = run.state.state_message

                duration_s = None
                if run.end_time and run.start_time:
                    duration_s = (run.end_time - run.start_time) / 1000.0

                # Fetch detailed error from task-level run output
                if result_state == RunResultState.FAILED.value:
                    try:
                        # Get task-level run IDs for detailed error
                        if run.tasks:
                            for task in run.tasks:
                                if task.state and task.state.result_state == RunResultState.FAILED:
                                    task_output = self._client.jobs.get_run_output(
                                        run_id=task.run_id
                                    )
                                    if task_output.error:
                                        error_msg = task_output.error
                                    break
                    except Exception as detail_err:
                        logger.debug(f"Could not fetch run output detail: {detail_err}")

                result = RunResult(
                    run_id=run_id,
                    state=life_cycle_state.value,
                    result_state=result_state,
                    error=error_msg,
                    duration_s=duration_s
                )

                # Capture notebook output on success
                notebook_output = None
                if result_state == RunResultState.SUCCESS.value:
                    try:
                        if run.tasks:
                            task_output = self._client.jobs.get_run_output(
                                run_id=run.tasks[0].run_id
                            )
                            if task_output.notebook_output:
                                notebook_output = task_output.notebook_output.result
                    except Exception as out_err:
                        logger.debug(f"Could not fetch notebook output: {out_err}")
                    logger.info(f"Run completed: run_id={run_id} ({duration_s:.1f}s)")
                else:
                    logger.warning(f"Run failed: run_id={run_id}, state={result_state}, error={error_msg}")

                result.output = notebook_output
                return result

            time.sleep(interval)
            interval = min(interval * self.POLL_BACKOFF_FACTOR, self.POLL_INTERVAL_MAX)

        raise JobsError(
            f"Timeout after {timeout_s}s waiting for run",
            run_id=run_id,
            operation="wait_for_run"
        )

    def run_and_wait(
        self, path: str, timeout_s: float = 600.0, language: str = "SQL"
    ) -> RunResult:
        """Submit a notebook run and wait for completion.

        Convenience method combining run_notebook + wait_for_run.

        Args:
            path: Absolute workspace path to the notebook.
            timeout_s: Maximum seconds to wait.
            language: Notebook language — "SQL" for warehouse, "PYTHON" for serverless.

        Returns:
            RunResult with final state.

        Raises:
            JobsError: If submission or execution fails.
        """
        run_id = self.run_notebook(path, language=language)
        return self.wait_for_run(run_id, timeout_s=timeout_s)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_run_status(self, run_id: int) -> RunResult:
        """Get current status of a run (non-blocking).

        Args:
            run_id: Run ID to check.

        Returns:
            RunResult with current state (may still be RUNNING).
        """
        try:
            run = self._client.jobs.get_run(run_id=run_id)
            life_cycle_state = run.state.life_cycle_state.value if run.state and run.state.life_cycle_state else "UNKNOWN"
            result_state = run.state.result_state.value if run.state and run.state.result_state else None
            error_msg = run.state.state_message if run.state else None

            return RunResult(
                run_id=run_id,
                state=life_cycle_state,
                result_state=result_state,
                error=error_msg
            )
        except Exception as e:
            raise JobsError(str(e), run_id=run_id, operation="get_run_status") from e
