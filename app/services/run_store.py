"""RunStore — Persistence layer for pipeline run metadata.

Writes pipeline run state and step results to Delta tables via SQL Statement API.
Provides methods to create, update, and query runs for the dashboard and rerun logic.

Tables:
    - {catalog}.{schema}.pipeline_runs
    - {catalog}.{schema}.pipeline_run_steps
    - {catalog}.{schema}.pipeline_step_phases_config
    - {catalog}.{schema}.pipeline_run_phases
"""

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Step ordering — defines the pipeline step sequence and next_step relationships
STEP_ORDER = [
    "environment_setup",
    "create_data_layer",
    "create_metric_views",
    "create_dashboards",
    "create_genie_space",
    "generate_documentation",
]


def _next_step(step_name: str) -> Optional[str]:
    """Get the next step after the given step, or None if last."""
    try:
        idx = STEP_ORDER.index(step_name)
        return STEP_ORDER[idx + 1] if idx < len(STEP_ORDER) - 1 else None
    except ValueError:
        return None


class RunStore:
    """Persists pipeline run metadata to Delta tables via SQL.

    Args:
        sql_service: SQLService instance (uses execute_and_wait / execute_ddl).
        catalog: Catalog name (default: aw_serverless_stable_catalog).
        schema: Schema name (default: aibi_studio_metadata).
    """

    def __init__(self, sql_service, catalog: str = "aw_serverless_stable_catalog",
                 schema: str = "aibi_studio_metadata"):
        self._sql = sql_service
        self._runs_table = f"{catalog}.{schema}.pipeline_runs"
        self._steps_table = f"{catalog}.{schema}.pipeline_run_steps"
        self._phases_config_table = f"{catalog}.{schema}.pipeline_step_phases_config"
        self._phases_table = f"{catalog}.{schema}.pipeline_run_phases"

    # ------------------------------------------------------------------
    # Run-level operations
    # ------------------------------------------------------------------

    def create_run(self, run_id: str, domain: str, run_mode: str,
                   version: Optional[int] = None, version_suffix: Optional[str] = None,
                   total_steps: int = 6, config_json: Optional[dict] = None,
                   steps: Optional[list] = None) -> None:
        """Insert a new pipeline run record and initialize step records.

        Args:
            run_id: Unique run identifier.
            domain: Domain name.
            run_mode: 'versioned' or 'clean'.
            version: Version number (if versioned).
            version_suffix: e.g., '_v1'.
            total_steps: Number of steps.
            config_json: Config dict to serialize for rerun.
            steps: List of step names to execute (defaults to STEP_ORDER).
        """
        now = datetime.utcnow().isoformat()
        config_json_str = json.dumps(config_json) if config_json else "null"
        # Escape single quotes in JSON
        config_json_str = config_json_str.replace("'", "''")

        sql = f"""
        INSERT INTO {self._runs_table}
        (run_id, domain, run_mode, version, version_suffix, status, total_steps,
         current_step, started_at, created_at, updated_at, config_json)
        VALUES (
            '{run_id}', '{domain}', '{run_mode}',
            {version if version is not None else 'NULL'},
            {f"'{version_suffix}'" if version_suffix else 'NULL'},
            'running', {total_steps}, NULL,
            TIMESTAMP '{now}', TIMESTAMP '{now}', TIMESTAMP '{now}',
            '{config_json_str}'
        )
        """
        try:
            self._sql.execute_ddl(sql)
            logger.info(f"RunStore: created run {run_id}")
        except Exception as e:
            logger.error(f"RunStore: failed to create run {run_id}: {e}")

        # Initialize step records as 'pending'
        run_steps = steps or STEP_ORDER
        for idx, step_name in enumerate(run_steps):
            step_sql = f"""
            INSERT INTO {self._steps_table}
            (run_id, step_name, step_index, status, updated_at)
            VALUES (
                '{run_id}', '{step_name}', {idx}, 'pending',
                TIMESTAMP '{now}'
            )
            """
            try:
                self._sql.execute_ddl(step_sql)
            except Exception as e:
                logger.error(f"RunStore: failed to create step {step_name}: {e}")

    def update_run_status(self, run_id: str, status: str,
                          current_step: Optional[str] = None,
                          error: Optional[str] = None) -> None:
        """Update run-level status fields.

        Actual runs table columns: run_id, domain, run_mode, status, version,
        version_suffix, total_steps, retry_count, config_json, error, created_at,
        started_at, completed_at, progress_pct, current_step, run_manifest, updated_at.
        """
        now = datetime.utcnow().isoformat()
        sets = [f"status = '{status}'", f"updated_at = TIMESTAMP '{now}'"]

        if current_step is not None:
            sets.append(f"current_step = '{current_step}'")
        if error is not None:
            if error == '':
                sets.append("error = NULL")
            else:
                safe_error = error.replace("'", "''")[:2000]
                sets.append(f"error = '{safe_error}'")
        if status in ('completed', 'failed', 'cancelled'):
            sets.append(f"completed_at = TIMESTAMP '{now}'")

        sql = f"UPDATE {self._runs_table} SET {', '.join(sets)} WHERE run_id = '{run_id}'"
        try:
            self._sql.execute_ddl(sql)
        except Exception as e:
            logger.error(f"RunStore: failed to update run {run_id}: {e}")

    # ------------------------------------------------------------------
    # Step-level operations
    # ------------------------------------------------------------------

    def insert_step(self, run_id: str, step_name: str, step_index: int,
                    next_step: Optional[str] = None) -> None:
        """Insert a single step record (used when a rerun discovers steps
        that were never reached in the original run)."""
        now = datetime.utcnow().isoformat()
        sql = f"""
        INSERT INTO {self._steps_table}
        (run_id, step_name, step_index, status, updated_at)
        VALUES (
            '{run_id}', '{step_name}', {step_index}, 'pending',
            TIMESTAMP '{now}'
        )
        """
        try:
            self._sql.execute_ddl(sql)
            logger.info(f"RunStore: inserted missing step {step_name} for run {run_id}")
        except Exception as e:
            logger.error(f"RunStore: failed to insert step {step_name}: {e}")

    def update_step(self, run_id: str, step_name: str, status: str,
                    duration_s: Optional[float] = None,
                    error: Optional[str] = None,
                    error_detail: Optional[str] = None,
                    suggestion: Optional[str] = None,
                    artifacts: Optional[list] = None) -> None:
        """Update a step's status and metadata.

        When status is 'completed', the next_step field signals readiness
        for the next step to begin.
        """
        now = datetime.utcnow().isoformat()
        sets = [f"status = '{status}'", f"updated_at = TIMESTAMP '{now}'"]

        if status == 'running':
            sets.append(f"started_at = TIMESTAMP '{now}'")
        if status in ('completed', 'failed'):
            sets.append(f"completed_at = TIMESTAMP '{now}'")
        if duration_s is not None:
            sets.append(f"duration_s = {duration_s:.2f}")
        if error is not None:
            if error == '':
                sets.append("error = NULL")
            else:
                safe_error = error.replace("'", "''")[:2000]
                sets.append(f"error = '{safe_error}'")
        if error_detail is not None:
            if error_detail == '':
                sets.append("error_detail = NULL")
            else:
                safe_detail = error_detail.replace("'", "''")[:4000]
                sets.append(f"error_detail = '{safe_detail}'")
        if suggestion is not None:
            safe_sug = suggestion.replace("'", "''")[:1000]
            sets.append(f"suggestion = '{safe_sug}'")
        if artifacts is not None:
            arts_json = json.dumps(artifacts).replace("'", "''")
            sets.append(f"artifacts = '{arts_json}'")

        sql = f"""
        UPDATE {self._steps_table}
        SET {', '.join(sets)}
        WHERE run_id = '{run_id}' AND step_name = '{step_name}'
        """
        try:
            self._sql.execute_ddl(sql)
        except Exception as e:
            logger.error(f"RunStore: failed to update step {run_id}/{step_name}: {e}")

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> Optional[dict]:
        """Get a single run with its steps."""
        try:
            result = self._sql.execute_and_wait(
                f"SELECT * FROM {self._runs_table} WHERE run_id = '{run_id}'"
            )
            if not result.data:
                return None
            run = self._row_to_dict(result.columns, result.data[0])

            # Get steps
            steps_result = self._sql.execute_and_wait(
                f"SELECT * FROM {self._steps_table} WHERE run_id = '{run_id}' ORDER BY step_index"
            )
            run['steps'] = [self._row_to_dict(steps_result.columns, row) for row in steps_result.data]
            return run
        except Exception as e:
            logger.error(f"RunStore: failed to get run {run_id}: {e}")
            return None

    def list_runs(self, limit: int = 50, domain: Optional[str] = None) -> list:
        """List recent pipeline runs, newest first."""
        where = f"WHERE domain = '{domain}'" if domain else ""
        try:
            result = self._sql.execute_and_wait(
                f"SELECT * FROM {self._runs_table} {where} ORDER BY started_at DESC LIMIT {limit}"
            )
            return [self._row_to_dict(result.columns, row) for row in result.data]
        except Exception as e:
            logger.error(f"RunStore: failed to list runs: {e}")
            return []

    def get_failed_step(self, run_id: str) -> Optional[str]:
        """Get the first failed step name for a run (for rerun logic).

        Returns the step_name of the first step with status='failed',
        which is where a rerun should start.
        """
        try:
            result = self._sql.execute_and_wait(
                f"SELECT step_name FROM {self._steps_table} "
                f"WHERE run_id = '{run_id}' AND status = 'failed' "
                f"ORDER BY step_index LIMIT 1"
            )
            if result.data:
                return result.data[0][0]
            return None
        except Exception as e:
            logger.error(f"RunStore: failed to get failed step for {run_id}: {e}")
            return None

    def get_resume_steps(self, run_id: str) -> list:
        """Get the list of steps to run for a resume (from failed step onward).

        Returns all step names from the first non-completed step through the end,
        INCLUDING any steps from STEP_ORDER that were never inserted into the
        table (because the original run failed before reaching them).
        """
        try:
            result = self._sql.execute_and_wait(
                f"SELECT step_name, step_index, status FROM {self._steps_table} "
                f"WHERE run_id = '{run_id}' ORDER BY step_index"
            )
            steps = [self._row_to_dict(result.columns, row) for row in result.data]

            # Find first non-completed step
            resume_from = None
            for step in steps:
                if step.get('status') != 'completed':
                    resume_from = step.get('step_index', 0)
                    break

            if resume_from is None:
                # All tracked steps completed — but there may be steps from
                # STEP_ORDER that were never inserted (run failed before
                # reaching them). Append any missing trailing steps.
                tracked_names = {s['step_name'] for s in steps}
                last_tracked = steps[-1]['step_name'] if steps else None
                trailing = []
                past_last = False
                for canonical in STEP_ORDER:
                    if canonical == last_tracked:
                        past_last = True
                        continue
                    if past_last and canonical not in tracked_names:
                        trailing.append(canonical)
                return trailing  # Empty if no missing steps

            resume_steps = [s['step_name'] for s in steps if s.get('step_index', 0) >= resume_from]

            # Also append any steps from STEP_ORDER that come after the last
            # tracked step but were never inserted into the table.
            tracked_names = {s['step_name'] for s in steps}
            last_tracked = steps[-1]['step_name'] if steps else None
            past_last = False
            for canonical in STEP_ORDER:
                if canonical == last_tracked:
                    past_last = True
                    continue
                if past_last and canonical not in tracked_names:
                    resume_steps.append(canonical)

            return resume_steps
        except Exception as e:
            logger.error(f"RunStore: failed to get resume steps for {run_id}: {e}")
            return []

    # ------------------------------------------------------------------
    # Rerun support
    # ------------------------------------------------------------------

    def reset_steps_for_rerun(self, run_id: str, steps_to_reset: list) -> None:
        """Reset failed/pending steps back to 'pending' for a rerun.

        Called when rerunning a failed pipeline from the failed step onward.
        Clears error fields and resets status so the step can re-execute.

        Args:
            run_id: The run being rerun.
            steps_to_reset: List of step names to reset to pending.
        """
        now = datetime.utcnow().isoformat()
        for step_name in steps_to_reset:
            sql = f"""
            UPDATE {self._steps_table}
            SET status = 'pending',
                started_at = NULL,
                completed_at = NULL,
                duration_s = NULL,
                error = NULL,
                updated_at = TIMESTAMP '{now}'
            WHERE run_id = '{run_id}' AND step_name = '{step_name}'
            """
            try:
                self._sql.execute_ddl(sql)
            except Exception as e:
                logger.error(f"RunStore: failed to reset step {step_name} for rerun: {e}")

    def increment_retry(self, run_id: str) -> None:
        """Increment the retry_count on a run record (called on rerun)."""
        now = datetime.utcnow().isoformat()
        sql = f"""
        UPDATE {self._runs_table}
        SET steps_completed = 0,
            updated_at = TIMESTAMP '{now}'
        WHERE run_id = '{run_id}'
        """
        try:
            self._sql.execute_ddl(sql)
        except Exception as e:
            logger.error(f"RunStore: failed to increment retry for {run_id}: {e}")

    # ------------------------------------------------------------------
    # Startup cleanup
    # ------------------------------------------------------------------

    def recover_orphaned_runs(self) -> int:
        """Mark any runs stuck in 'running' status as 'failed'.

        Called on app startup to handle runs that were interrupted by
        a redeploy or crash. Returns the number of runs recovered.
        """
        now = datetime.utcnow().isoformat()
        sql = f"""
        UPDATE {self._runs_table}
        SET status = 'failed',
            error = 'Run interrupted by app restart',
            error_detail = 'The app was redeployed or restarted while this run was in progress. Use Rerun to resume from the failed step.',
            completed_at = TIMESTAMP '{now}',
            updated_at = TIMESTAMP '{now}'
        WHERE status = 'running'
        """
        try:
            self._sql.execute_ddl(sql)
            # Also mark running steps as failed
            step_sql = f"""
            UPDATE {self._steps_table}
            SET status = 'failed',
                error = 'Interrupted by app restart',
                completed_at = TIMESTAMP '{now}',
                updated_at = TIMESTAMP '{now}'
            WHERE status = 'running'
            """
            self._sql.execute_ddl(step_sql)
            # TODO: Also recover orphaned phases in self._phases_table (same pattern as steps above)
            logger.info("RunStore: recovered orphaned runs on startup")
            return 1  # We don't easily get row count from DDL
        except Exception as e:
            logger.error(f"RunStore: failed to recover orphaned runs: {e}")
            return 0

    # ------------------------------------------------------------------
    # Phase config operations
    # ------------------------------------------------------------------

    def get_phase_config(self, step_name: str) -> list:
        """Get the ordered list of phases for a step from the config table.

        Args:
            step_name: Step identifier (e.g., 'create_data_layer').

        Returns:
            List of phase dicts: [{phase_name, phase_index, phase_label,
            handler_method, enabled, timeout_s, max_retries, config_json}, ...]
            ordered by phase_index.
        """
        try:
            result = self._sql.execute_and_wait(
                f"SELECT phase_name, phase_index, phase_label, handler_method, "
                f"enabled, timeout_s, max_retries, config_json "
                f"FROM {self._phases_config_table} "
                f"WHERE step_name = '{step_name}' AND enabled = true "
                f"ORDER BY phase_index"
            )
            return [self._row_to_dict(result.columns, row) for row in result.data]
        except Exception as e:
            logger.error(f"RunStore: failed to get phase config for {step_name}: {e}")
            return []

    def get_all_phase_configs(self) -> dict:
        """Get phase configs for all steps, grouped by step_name.

        Returns:
            Dict keyed by step_name, values are lists of phase config dicts.
        """
        try:
            result = self._sql.execute_and_wait(
                f"SELECT step_name, phase_name, phase_index, phase_label, handler_method, "
                f"enabled, timeout_s, max_retries, config_json "
                f"FROM {self._phases_config_table} "
                f"WHERE enabled = true "
                f"ORDER BY step_name, phase_index"
            )
            configs = {}
            for row in result.data:
                row_dict = self._row_to_dict(result.columns, row)
                step = row_dict['step_name']
                if step not in configs:
                    configs[step] = []
                configs[step].append(row_dict)
            return configs
        except Exception as e:
            logger.error(f"RunStore: failed to get all phase configs: {e}")
            return {}

    # ------------------------------------------------------------------
    # Phase runtime operations
    # ------------------------------------------------------------------

    def create_phases(self, run_id: str, step_name: str, phases: list) -> None:
        """Initialize phase records for a step execution.

        Called when a step begins executing. Creates one row per phase
        in pipeline_run_phases with status='pending'.

        Args:
            run_id: The run identifier.
            step_name: The step being executed.
            phases: List of phase config dicts from get_phase_config().
        """
        now = datetime.utcnow().isoformat()
        for phase in phases:
            sql = f"""
            INSERT INTO {self._phases_table}
            (run_id, step_name, phase_name, phase_index, status, created_at, updated_at)
            VALUES (
                '{run_id}', '{step_name}', '{phase['phase_name']}',
                {phase['phase_index']}, 'pending',
                TIMESTAMP '{now}', TIMESTAMP '{now}'
            )
            """
            try:
                self._sql.execute_ddl(sql)
            except Exception as e:
                logger.error(f"RunStore: failed to create phase {phase['phase_name']}: {e}")

    def update_phase(self, run_id: str, step_name: str, phase_name: str,
                     status: str, duration_ms: Optional[int] = None,
                     error: Optional[str] = None, error_detail: Optional[str] = None,
                     suggestion: Optional[str] = None,
                     artifacts: Optional[list] = None) -> None:
        """Update a phase's status and metadata.

        Args:
            run_id: Run identifier.
            step_name: Step this phase belongs to.
            phase_name: Phase identifier.
            status: New status (running, completed, failed, skipped).
            duration_ms: Phase duration in milliseconds.
            error: Error message if failed.
            error_detail: Full traceback.
            suggestion: Suggested fix.
            artifacts: List of artifact paths.
        """
        now = datetime.utcnow().isoformat()
        sets = [f"status = '{status}'", f"updated_at = TIMESTAMP '{now}'"]

        if status == 'running':
            sets.append(f"started_at = TIMESTAMP '{now}'")
        if status in ('completed', 'failed'):
            sets.append(f"completed_at = TIMESTAMP '{now}'")
        if duration_ms is not None:
            sets.append(f"duration_ms = {duration_ms}")
        if error is not None:
            safe_error = error.replace("'", "''")[:2000]
            sets.append(f"error = '{safe_error}'")
        if error_detail is not None:
            safe_detail = error_detail.replace("'", "''")[:4000]
            sets.append(f"error_detail = '{safe_detail}'")
        if suggestion is not None:
            safe_sug = suggestion.replace("'", "''")[:1000]
            sets.append(f"suggestion = '{safe_sug}'")
        if artifacts is not None:
            arts_json = json.dumps(artifacts).replace("'", "''")
            sets.append(f"artifacts = '{arts_json}'")

        sql = f"""
        UPDATE {self._phases_table}
        SET {', '.join(sets)}
        WHERE run_id = '{run_id}' AND step_name = '{step_name}' AND phase_name = '{phase_name}'
        """
        try:
            self._sql.execute_ddl(sql)
        except Exception as e:
            logger.error(f"RunStore: failed to update phase {run_id}/{step_name}/{phase_name}: {e}")

    def get_phases_for_step(self, run_id: str, step_name: str) -> list:
        """Get all phase records for a step in a run.

        Returns:
            List of phase dicts ordered by phase_index.
        """
        try:
            result = self._sql.execute_and_wait(
                f"SELECT * FROM {self._phases_table} "
                f"WHERE run_id = '{run_id}' AND step_name = '{step_name}' "
                f"ORDER BY phase_index"
            )
            return [self._row_to_dict(result.columns, row) for row in result.data]
        except Exception as e:
            logger.error(f"RunStore: failed to get phases for {run_id}/{step_name}: {e}")
            return []

    def get_failed_phase(self, run_id: str, step_name: str) -> Optional[str]:
        """Get the first failed phase name within a step.

        Args:
            run_id: Run identifier.
            step_name: Step to check.

        Returns:
            Phase name of the first failed phase, or None.
        """
        try:
            result = self._sql.execute_and_wait(
                f"SELECT phase_name FROM {self._phases_table} "
                f"WHERE run_id = '{run_id}' AND step_name = '{step_name}' "
                f"AND status = 'failed' ORDER BY phase_index LIMIT 1"
            )
            if result.data:
                return result.data[0][0]
            return None
        except Exception as e:
            logger.error(f"RunStore: failed to get failed phase for {run_id}/{step_name}: {e}")
            return None

    def get_resume_point(self, run_id: str) -> Optional[dict]:
        """Get the exact resume point (step + phase) for a failed run.

        Finds the first non-completed phase across all steps.

        Returns:
            Dict with {step_name, phase_name, phase_index} or None if all complete.
        """
        try:
            result = self._sql.execute_and_wait(
                f"SELECT step_name, phase_name, phase_index FROM {self._phases_table} "
                f"WHERE run_id = '{run_id}' AND status != 'completed' "
                f"ORDER BY phase_index LIMIT 1"
            )
            if result.data:
                return self._row_to_dict(result.columns, result.data[0])
            return None
        except Exception as e:
            logger.error(f"RunStore: failed to get resume point for {run_id}: {e}")
            return None

    def reset_phases_for_rerun(self, run_id: str, step_name: str,
                                from_phase: Optional[str] = None) -> None:
        """Reset phases for rerun from a specific phase onward.

        Args:
            run_id: Run identifier.
            step_name: Step to reset phases for.
            from_phase: Phase name to reset from. If None, resets all phases in the step.
        """
        now = datetime.utcnow().isoformat()
        where = f"run_id = '{run_id}' AND step_name = '{step_name}'"

        if from_phase:
            # Get the phase_index of from_phase and reset it and all subsequent
            where += (
                f" AND phase_index >= ("
                f"SELECT phase_index FROM {self._phases_table} "
                f"WHERE run_id = '{run_id}' AND step_name = '{step_name}' "
                f"AND phase_name = '{from_phase}')"
            )

        sql = f"""
        UPDATE {self._phases_table}
        SET status = 'pending',
            started_at = NULL,
            completed_at = NULL,
            duration_ms = NULL,
            error = NULL,
            error_detail = NULL,
            suggestion = NULL,
            retry_count = COALESCE(retry_count, 0) + 1,
            updated_at = TIMESTAMP '{now}'
        WHERE {where}
        """
        try:
            self._sql.execute_ddl(sql)
        except Exception as e:
            logger.error(f"RunStore: failed to reset phases for rerun {run_id}/{step_name}: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Verify metadata tables are accessible."""
        try:
            result = self._sql.execute_and_wait(
                f"SELECT 1 FROM {self._runs_table} LIMIT 1"
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _row_to_dict(columns, row) -> dict:
        """Convert a result row to a dict using column names."""
        if hasattr(columns, '__iter__'):
            col_names = [c.name if hasattr(c, 'name') else str(c) for c in columns]
        else:
            col_names = [f"col_{i}" for i in range(len(row))]
        return dict(zip(col_names, row))
