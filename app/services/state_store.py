"""StateStore - Durable pipeline state backed by Lakebase (pg8000 direct SQL).

Bypasses the Data API/PostgREST layer entirely. Connects directly to the
Lakebase Postgres endpoint using pg8000 (pure Python, no native deps).
Auth via generate_database_credential() JWT token.
"""

import json
import logging
import ssl
from datetime import datetime, timezone
from typing import Any, Optional, Callable

import pg8000

logger = logging.getLogger(__name__)


class StateStore:
    """Durable state backed by Lakebase (direct pg8000 SQL).

    Usage:
        store = StateStore(host, database, user_fn, token_fn)
        store.create_run(run_id, domain, ...)
        store.upsert_step(run_id, step_name, status='running')
    """

    def __init__(self, host: str, database: str, user_fn: Callable[[], str], token_fn: Callable[[], str]):
        self._host = host
        self._database = database
        self._user_fn = user_fn
        self._token_fn = token_fn
        self._ssl_context = ssl.create_default_context()
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_NONE

    @classmethod
    def from_config(cls, config: dict, user_fn: Callable[[], str], token_fn: Callable[[], str]) -> "StateStore":
        host = config["endpoint_host"]
        database = config.get("database", "databricks_postgres")
        return cls(host, database, user_fn, token_fn)

    # --- Connection Helper ---

    def _connect(self):
        """Create a fresh pg8000 connection (tokens expire after 1h)."""
        return pg8000.connect(
            host=self._host,
            port=5432,
            database=self._database,
            user=self._user_fn(),
            password=self._token_fn(),
            ssl_context=self._ssl_context,
        )

    # --- SQL Helpers ---

    def _execute(self, sql: str, params: tuple = ()) -> list:
        """Execute SQL and return all rows as list of dicts."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            else:
                rows = []
            conn.commit()
            return rows
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _execute_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """Execute SQL and return first row or None."""
        rows = self._execute(sql, params)
        return rows[0] if rows else None

    def _execute_write(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """Execute INSERT/UPDATE and return first row if RETURNING is used."""
        return self._execute_one(sql, params)

    def _insert(self, table: str, data: dict, conflict_cols: list = None) -> Optional[dict]:
        """INSERT with optional ON CONFLICT DO UPDATE (upsert)."""
        cols = list(data.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)
        sql = f'INSERT INTO public.{table} ({col_names}) VALUES ({placeholders})'

        if conflict_cols:
            conflict_col_str = ", ".join(conflict_cols)
            update_cols = [c for c in cols if c not in conflict_cols]
            update_str = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
            sql += f' ON CONFLICT ({conflict_col_str}) DO UPDATE SET {update_str}'

        sql += ' RETURNING *'
        values = tuple(json.dumps(v) if isinstance(v, dict) else v for v in data.values())
        return self._execute_one(sql, values)

    def _update(self, table: str, filters: dict, data: dict) -> None:
        """UPDATE rows matching filters."""
        set_parts = []
        values = []
        for col, val in data.items():
            set_parts.append(f"{col} = %s")
            values.append(json.dumps(val) if isinstance(val, dict) else val)

        where_parts = []
        for col, val in filters.items():
            where_parts.append(f"{col} = %s")
            values.append(val)

        sql = f'UPDATE public.{table} SET {", ".join(set_parts)} WHERE {" AND ".join(where_parts)}'
        self._execute(sql, tuple(values))

    def _select(self, table: str, filters: dict = None, order: str = None, limit: int = None) -> list:
        """SELECT rows with optional filters, ordering, limit."""
        sql = f'SELECT * FROM public.{table}'
        values = []

        if filters:
            where_parts = []
            for col, val in filters.items():
                where_parts.append(f"{col} = %s")
                values.append(val)
            sql += f' WHERE {" AND ".join(where_parts)}'

        if order:
            sql += f' ORDER BY {order}'
        if limit:
            sql += f' LIMIT {limit}'

        return self._execute(sql, tuple(values))

    # --- Runs ---

    def create_run(self, run_id: str, domain: str, run_mode: str = "versioned",
                   version: Optional[int] = None, version_suffix: Optional[str] = None,
                   total_steps: int = 6, config_json: Optional[dict] = None) -> None:
        self._insert("runs", {
            "run_id": run_id, "domain": domain, "run_mode": run_mode,
            "version": version, "version_suffix": version_suffix,
            "total_steps": total_steps, "config_json": config_json, "status": "pending",
        })

    def update_run(self, run_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._update("runs", {"run_id": run_id}, fields)

    def save_run_manifest(self, run_id: str, manifest: dict) -> None:
        """Persist the run_manifest JSON to the run record.

        Stores the full manifest (steps + sub-steps + errors) as a JSON field
        on the run record. Called incrementally after each step completes.
        Auto-adds the run_manifest column if it doesn't exist yet.
        """
        import json
        manifest_json = json.dumps(manifest)
        try:
            self.update_run(run_id, run_manifest=manifest_json)
        except Exception as e:
            if "column" in str(e).lower() and "does not exist" in str(e).lower():
                # Column missing — add it and retry
                try:
                    self._execute_write(
                        "ALTER TABLE public.runs ADD COLUMN IF NOT EXISTS run_manifest JSONB"
                    )
                    self.update_run(run_id, run_manifest=manifest_json)
                except Exception as e2:
                    logger.warning(f"Could not save run_manifest to Lakebase: {e2}")
            else:
                logger.warning(f"Could not save run_manifest to Lakebase: {e}")

    def get_run(self, run_id: str) -> Optional[dict]:
        runs = self._select("runs", {"run_id": run_id})
        if not runs:
            return None
        run = runs[0]
        steps = self._execute(
            "SELECT * FROM public.steps WHERE run_id = %s ORDER BY step_index ASC", (run_id,)
        )
        phases = self._execute(
            "SELECT * FROM public.phases WHERE run_id = %s ORDER BY step_name ASC, phase_index ASC", (run_id,)
        )
        phases_by_step = {}
        for p in phases:
            phases_by_step.setdefault(p["step_name"], []).append(p)
        for step in steps:
            step["phases"] = phases_by_step.get(step["step_name"], [])
        run["steps"] = steps
        return run

    def get_active_runs(self) -> list:
        return self._execute(
            "SELECT * FROM public.runs WHERE status IN ('running', 'pending') ORDER BY started_at ASC"
        )

    # --- Steps ---
    # steps table: run_id, step_name, step_index, status, error, started_at, completed_at

    def upsert_step(self, run_id: str, step_name: str, step_index: int = 0, **fields) -> None:
        # Only include columns that exist in the steps table
        valid_cols = {'status', 'error', 'started_at', 'completed_at'}
        filtered = {k: v for k, v in fields.items() if k in valid_cols}
        data = {"run_id": run_id, "step_name": step_name, "step_index": step_index, **filtered}
        self._insert("steps", data, conflict_cols=["run_id", "step_name"])

    def update_step(self, run_id: str, step_name: str, status: str, **kwargs) -> None:
        """Convenience: update step status with optional fields."""
        valid_cols = {'status', 'error', 'started_at', 'completed_at'}
        kwargs["status"] = status
        if status == "running":
            kwargs.setdefault("started_at", datetime.now(timezone.utc).isoformat())
        elif status in ("completed", "failed"):
            kwargs.setdefault("completed_at", datetime.now(timezone.utc).isoformat())
        filtered = {k: v for k, v in kwargs.items() if k in valid_cols}
        self._update("steps", {"run_id": run_id, "step_name": step_name}, filtered)

    def update_run_status(self, run_id: str, status: str, **kwargs) -> None:
        """Convenience: update run status with optional fields."""
        # runs table: run_id, domain, run_mode, status, version, version_suffix,
        #             total_steps, retry_count, config_json, error, created_at, started_at, completed_at
        valid_cols = {'status', 'error', 'started_at', 'completed_at', 'version',
                      'version_suffix', 'total_steps', 'retry_count', 'config_json'}
        kwargs["status"] = status
        if status == "running" and "started_at" not in kwargs:
            kwargs["started_at"] = datetime.now(timezone.utc).isoformat()
        elif status in ("completed", "failed"):
            kwargs.setdefault("completed_at", datetime.now(timezone.utc).isoformat())
        filtered = {k: v for k, v in kwargs.items() if k in valid_cols}
        self._update("runs", {"run_id": run_id}, filtered)

    def get_phases_for_step(self, run_id: str, step_name: str) -> list:
        """Get all phases for a specific run + step."""
        return self._execute(
            "SELECT * FROM public.phases WHERE run_id = %s AND step_name = %s ORDER BY phase_index ASC",
            (run_id, step_name),
        )

    def create_phases(self, run_id: str, step_name: str, phases: list) -> None:
        """Initialize phase records for a step execution.

        Creates one row per phase in the phases table with status='pending'.

        Args:
            run_id: The run identifier.
            step_name: The step being executed.
            phases: List of phase config dicts (from get_phase_config()).
        """
        for phase in phases:
            self._insert("phases", {
                "run_id": run_id,
                "step_name": step_name,
                "phase_name": phase.get("phase_name", ""),
                "phase_index": phase.get("phase_index", 0),
                "status": "pending",
            }, conflict_cols=["run_id", "step_name", "phase_name"])

    def get_resume_steps(self, run_id: str) -> list:
        """Get ordered list of step names that need to run (not completed)."""
        steps = self._execute(
            "SELECT step_name FROM public.steps WHERE run_id = %s AND status != 'completed' ORDER BY step_index ASC",
            (run_id,),
        )
        return [s["step_name"] for s in steps]

    def increment_retry(self, run_id: str) -> None:
        """Increment retry count on the run (for rerun tracking)."""
        runs = self._execute(
            "SELECT run_id, config_json FROM public.runs WHERE run_id = %s", (run_id,)
        )
        if runs:
            config = runs[0].get("config_json") or {}
            if isinstance(config, str):
                config = json.loads(config)
            config["retry_count"] = config.get("retry_count", 0) + 1
            self._update("runs", {"run_id": run_id}, {
                "config_json": config,
            })

    def reset_steps_for_rerun(self, run_id: str, step_names: list) -> None:
        """Reset steps and their phases to pending for rerun."""
        for step_name in step_names:
            # steps table columns: run_id, step_name, step_index, status, error, started_at, completed_at
            self._update("steps", {"run_id": run_id, "step_name": step_name}, {
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "error": None,
            })
            # phases table columns: run_id, step_name, phase_name, phase_index, status, error, started_at, completed_at
            self._update("phases", {"run_id": run_id, "step_name": step_name}, {
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "error": None,
            })

    # --- Phases ---

    def upsert_phase(self, run_id: str, step_name: str, phase_name: str,
                     phase_index: int = 0, **fields) -> None:
        # phases table: run_id, step_name, phase_name, phase_index, status, error, started_at, completed_at
        valid_cols = {'status', 'error', 'started_at', 'completed_at'}
        filtered = {k: v for k, v in fields.items() if k in valid_cols}
        data = {"run_id": run_id, "step_name": step_name,
                "phase_name": phase_name, "phase_index": phase_index, **filtered}
        self._insert("phases", data, conflict_cols=["run_id", "step_name", "phase_name"])

    def update_phase(self, run_id: str, step_name: str, phase_name: str,
                     status: str, **kwargs) -> None:
        """Update a phase record (called by PipelineRunner during execution)."""
        valid_cols = {'status', 'error', 'started_at', 'completed_at'}
        kwargs['status'] = status
        if status == 'running':
            kwargs.setdefault('started_at', datetime.now(timezone.utc).isoformat())
        elif status in ('completed', 'failed'):
            kwargs.setdefault('completed_at', datetime.now(timezone.utc).isoformat())
        filtered = {k: v for k, v in kwargs.items() if k in valid_cols}
        self._update("phases", {"run_id": run_id, "step_name": step_name, "phase_name": phase_name}, filtered)

    # --- Events (append-only for SSE replay) ---

    def append_event(self, run_id: str, event_type: str, event_data: dict) -> int:
        row = self._insert("events", {
            "run_id": run_id, "event_type": event_type, "event_data": event_data,
        })
        event_id = row.get("event_id", 0) if row else 0
        if event_id:
            self._update("runs", {"run_id": run_id}, {
                "event_seq": event_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        return event_id

    def get_events_since(self, run_id: str, after_event_id: int) -> list:
        return self._execute(
            "SELECT * FROM public.events WHERE run_id = %s AND event_id > %s ORDER BY event_id ASC",
            (run_id, after_event_id),
        )

    # --- Step Logs ---

    def append_log(self, run_id: str, step_name: str, line: str) -> None:
        existing = self._select("step_logs", {"run_id": run_id, "step_name": step_name})
        if existing:
            new_text = existing[0].get("log_text", "") + line + "\n"
            self._update("step_logs", {"run_id": run_id, "step_name": step_name}, {
                "log_text": new_text,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        else:
            self._insert("step_logs", {"run_id": run_id, "step_name": step_name, "log_text": line + "\n"})

    def get_step_log(self, run_id: str, step_name: str) -> str:
        rows = self._select("step_logs", {"run_id": run_id, "step_name": step_name})
        return rows[0]["log_text"] if rows else ""

    # --- Resume & Recovery ---

    def get_resume_point(self, run_id: str) -> Optional[dict]:
        rows = self._execute(
            "SELECT * FROM public.phases WHERE run_id = %s AND status != 'completed' ORDER BY phase_index ASC LIMIT 1",
            (run_id,),
        )
        return rows[0] if rows else None

    def list_runs(self, domain: Optional[str] = None, limit: int = 50) -> list:
        if domain:
            return self._execute(
                "SELECT * FROM public.runs WHERE domain = %s ORDER BY started_at DESC LIMIT %s",
                (domain, limit),
            )
        return self._execute(
            f"SELECT * FROM public.runs ORDER BY started_at DESC LIMIT %s", (limit,)
        )

    # --- Phase Config ---

    def get_phase_config(self, step_name: str = None) -> list:
        """Get phase configuration from Lakebase."""
        if step_name:
            return self._execute(
                "SELECT * FROM public.step_phases_config WHERE step_name = %s ORDER BY step_name ASC, phase_index ASC",
                (step_name,),
            )
        return self._execute("SELECT * FROM public.step_phases_config ORDER BY step_name ASC, phase_index ASC")

    def get_step_phases(self, step_name: str) -> list:
        """Get ordered phases for a specific step."""
        return self._execute(
            "SELECT * FROM public.step_phases_config WHERE step_name = %s AND enabled = true ORDER BY phase_index ASC",
            (step_name,),
        )

    # --- Phase-Boundary Checkpoint Persistence ---

    def persist_phase_update(self, run_id: str, step_name: str, phase_data: dict) -> None:
        """Persist a phase_update event to the phases table (write-through).

        Called on every phase_update event from the agent loop. This is the
        durable checkpoint — once a phase is persisted as 'completed', it
        will not be re-executed on resume.

        Args:
            run_id: The run identifier.
            step_name: Current step name.
            phase_data: Dict from phase_update event with keys:
                phase_id, phase_name, status, current_task, progress_pct,
                stats (dict), happenings (list), findings (list)
        """
        phase_name = phase_data.get('phase_name', '')
        status = phase_data.get('status', 'running')

        data = {
            'run_id': run_id,
            'step_name': step_name,
            'phase_name': phase_name,
            'phase_id': phase_data.get('phase_id', ''),
            'status': status,
            'current_task': phase_data.get('current_task'),
            'progress_pct': phase_data.get('progress_pct', 0),
            'stats': phase_data.get('stats') or {},
            'happenings': phase_data.get('happenings') or [],
            'findings': phase_data.get('findings') or [],
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

        if status == 'started':
            data['started_at'] = datetime.now(timezone.utc).isoformat()
        elif status in ('completed', 'failed'):
            data['completed_at'] = datetime.now(timezone.utc).isoformat()

        try:
            self._insert('phases', data, conflict_cols=['run_id', 'step_name', 'phase_name'])
        except Exception as e:
            logger.warning(f"persist_phase_update failed (non-fatal): {e}")

    def persist_tool_call(self, run_id: str, step_name: str, tool_data: dict) -> None:
        """Persist a tool call event to the tool_calls table.

        Called on tool_started (inserts), tool_completed/tool_failed (updates).

        Args:
            run_id: The run identifier.
            step_name: Current step name.
            tool_data: Dict with keys:
                tool_name, status, args_summary, error, duration_ms, started_at
        """
        status = tool_data.get('status', 'running')
        tool_name = tool_data.get('tool_name', '')

        try:
            if status == 'running':
                # INSERT new tool_call row
                self._insert('tool_calls', {
                    'run_id': run_id,
                    'step_name': step_name,
                    'tool_name': tool_name,
                    'status': 'running',
                    'args_summary': (tool_data.get('args_summary') or '')[:500],
                    'started_at': tool_data.get('started_at', datetime.now(timezone.utc).isoformat()),
                })
            else:
                # UPDATE the most recent running row for this tool
                update_data = {
                    'status': status,
                    'completed_at': datetime.now(timezone.utc).isoformat(),
                }
                if tool_data.get('duration_ms') is not None:
                    update_data['duration_ms'] = tool_data['duration_ms']
                if tool_data.get('error'):
                    update_data['error'] = tool_data['error'][:500]

                # Find the latest running row for this tool and update it
                self._execute(
                    """UPDATE public.tool_calls
                       SET status = %s, completed_at = %s, duration_ms = %s, error = %s
                       WHERE id = (
                           SELECT id FROM public.tool_calls
                           WHERE run_id = %s AND step_name = %s AND tool_name = %s AND status = 'running'
                           ORDER BY started_at DESC LIMIT 1
                       )""",
                    (
                        status,
                        update_data['completed_at'],
                        update_data.get('duration_ms'),
                        update_data.get('error'),
                        run_id, step_name, tool_name,
                    ),
                )
        except Exception as e:
            logger.warning(f"persist_tool_call failed (non-fatal): {e}")

    def load_run_full(self, run_id: str) -> Optional[dict]:
        """Load full run state from Lakebase for recovery after refresh.

        Returns a dict structured identically to the in-memory _runs format
        so the status endpoint can serve it directly.

        Returns None if run_id not found.
        """
        run = self._execute_one(
            "SELECT * FROM public.runs WHERE run_id = %s", (run_id,)
        )
        if not run:
            return None

        # Load steps
        steps = self._execute(
            "SELECT * FROM public.steps WHERE run_id = %s ORDER BY step_index ASC",
            (run_id,),
        )

        # Load phases
        phases = self._execute(
            "SELECT * FROM public.phases WHERE run_id = %s ORDER BY step_name ASC, phase_index ASC",
            (run_id,),
        )

        # Load recent tool calls (last 50 per step for performance)
        tool_calls = self._execute(
            """SELECT * FROM public.tool_calls
               WHERE run_id = %s
               ORDER BY step_name ASC, started_at ASC
               LIMIT 500""",
            (run_id,),
        )

        # Build step_data structure matching in-memory format
        step_data = {}
        for s in steps:
            sname = s['step_name']
            step_data[sname] = {
                'step_name': sname,
                'status': s.get('status', 'pending'),
                'duration_s': s.get('duration_s'),
                'phases': [],
                'tool_calls': [],
            }

        # Attach phases to their steps
        for p in phases:
            sname = p.get('step_name', '')
            if sname in step_data:
                step_data[sname]['phases'].append({
                    'phase_id': p.get('phase_id', ''),
                    'phase_name': p.get('phase_name', ''),
                    'status': p.get('status', 'pending'),
                    'current_task': p.get('current_task'),
                    'progress_pct': p.get('progress_pct'),
                    'stats': p.get('stats') or {},
                    'happenings': p.get('happenings') or [],
                    'findings': p.get('findings') or [],
                })

        # Attach tool_calls to their steps
        for tc in tool_calls:
            sname = tc.get('step_name', '')
            if sname in step_data:
                step_data[sname]['tool_calls'].append({
                    'tool_name': tc.get('tool_name', ''),
                    'status': tc.get('status', 'completed'),
                    'args_summary': tc.get('args_summary', ''),
                    'duration_ms': tc.get('duration_ms'),
                    'error': tc.get('error'),
                    'started_at': tc.get('started_at').isoformat() if hasattr(tc.get('started_at'), 'isoformat') else tc.get('started_at'),
                })

        # Build the run dict in the same shape as _runs[run_id]
        return {
            'run_id': run_id,
            'domain': run.get('domain', ''),
            'status': run.get('status', 'unknown'),
            'current_step': run.get('current_step'),
            'progress_pct': run.get('progress_pct', 0),
            'version': run.get('version'),
            'version_suffix': run.get('version_suffix', ''),
            'started_at': run.get('started_at').isoformat() if hasattr(run.get('started_at'), 'isoformat') else run.get('started_at'),
            'completed_at': run.get('completed_at').isoformat() if hasattr(run.get('completed_at'), 'isoformat') else run.get('completed_at'),
            'duration_s': run.get('duration_s'),
            'error': run.get('error'),
            'steps_completed': [s['step_name'] for s in steps if s.get('status') == 'completed'],
            'step_data': step_data,
            'logs': [],
        }

    # --- Health ---

    def health_check(self) -> bool:
        try:
            self._execute("SELECT 1 FROM public.runs LIMIT 1")
            return True
        except Exception as e:
            logger.warning(f"Lakebase health check failed: {e}")
            return False

    # --- Cleanup ---

    def delete_runs_for_version(self, domain: str, version_suffix: str) -> int:
        """Delete all run records (and associated steps, phases, logs) for a domain+version.

        Returns the number of run records removed.
        """
        # Find matching run_ids
        runs = self._execute(
            "SELECT run_id FROM public.runs WHERE domain = %s AND version_suffix = %s",
            (domain, version_suffix),
        )
        if not runs:
            return 0

        run_ids = [r["run_id"] for r in runs]
        count = len(run_ids)

        for rid in run_ids:
            # Delete child records first (phases, steps, logs, events)
            self._execute("DELETE FROM public.phases WHERE run_id = %s", (rid,))
            self._execute("DELETE FROM public.steps WHERE run_id = %s", (rid,))
            self._execute("DELETE FROM public.step_logs WHERE run_id = %s", (rid,))
            try:
                self._execute("DELETE FROM public.events WHERE run_id = %s", (rid,))
            except Exception:
                pass  # events table may not exist
            self._execute("DELETE FROM public.runs WHERE run_id = %s", (rid,))

        logger.info(f"Deleted {count} run records for {domain} {version_suffix}")

    def purge_all_runs(self) -> int:
        """Remove ALL run records and associated data (phases, steps, logs, events).

        Used for full reset from the Admin page. Clears pipeline execution
        history so the user can start fresh.

        Returns the number of run records removed.
        """
        runs = self._execute("SELECT run_id FROM public.runs")
        if not runs:
            return 0

        count = len(runs)
        run_ids = [r["run_id"] for r in runs]

        for rid in run_ids:
            for tbl in ("phases", "steps", "step_logs"):
                try:
                    self._execute(f"DELETE FROM public.{tbl} WHERE run_id = %s", (rid,))
                except Exception:
                    pass
            try:
                self._execute("DELETE FROM public.events WHERE run_id = %s", (rid,))
            except Exception:
                pass
            self._execute("DELETE FROM public.runs WHERE run_id = %s", (rid,))

        logger.info(f"Purged all {count} run records from Lakebase")
        return count
        return count
