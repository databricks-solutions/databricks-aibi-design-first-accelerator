"""Pipeline execution routes for AI/BI Studio.

Handles pipeline run, status polling, cancellation, and SSE streaming.
See docs/design_phase2.md Section 5.1.
"""

import os
import uuid
import json
import time
import logging
import threading
import queue
from datetime import datetime
from flask import Blueprint, request, jsonify, Response, current_app

logger = logging.getLogger(__name__)

pipeline_bp = Blueprint('pipeline', __name__, url_prefix='/api/pipeline')

# In-memory run store (replace with Delta table in production)
_runs = {}
# SSE event queues per run_id (for real-time streaming)
_event_queues = {}
# Active PipelineRunner instances (for cancellation)
_runners = {}


def _get_services(user_token: str = None):
    """Lazy-initialize services.

    All services use SP default credentials. The SP has CAN_MANAGE on
    the project folder (granted by setup_app_permissions job), which
    allows directory creation and file writes via the Workspace API.
    The on-behalf-of user token scope does not cover the Workspace API.
    """
    from services.workspace_io import WorkspaceService
    from services.sql_client import SQLService
    from services.lakeview_client import LakeviewService
    from services.genie_client import GenieService
    from services.jobs_client import JobsService

    from config import get_config
    app_config = get_config()
    warehouse_id = app_config.SQL_WAREHOUSE_ID

    return {
        "workspace": WorkspaceService(),   # SP auth (CAN_MANAGE on project folder)
        "sql": SQLService(warehouse_id=warehouse_id),
        "lakeview": LakeviewService(),     # SP auth
        "genie": GenieService(),           # SP auth
        "jobs": JobsService(warehouse_id=warehouse_id),  # For execute_notebook tool
    }


def _get_llm_client():
    """Lazy-initialize LLM client."""
    import os
    from llm.client import LLMClient
    return LLMClient(
        endpoint_name=os.environ.get('LLM_ENDPOINT_NAME', 'databricks-gpt-5-5'),
        vision_endpoint_name=os.environ.get('VISION_ENDPOINT_NAME', 'databricks-gpt-5-5'),
        temperature=float(os.environ.get('LLM_TEMPERATURE', '0.1')),
        max_retries=int(os.environ.get('LLM_MAX_RETRIES', '3')),
    )


# Singleton StateStore instance (module-level, thread-safe for reads)
_state_store = None
_state_store_checked_at = 0.0  # timestamp of last discovery attempt
_STATE_STORE_RETRY_INTERVAL = 30  # seconds between retries when not provisioned


def _reset_state_store():
    """Reset the cached StateStore singleton (e.g. after Lakebase recreation)."""
    global _state_store, _state_store_checked_at
    _state_store = None
    _state_store_checked_at = 0.0
    logger.info("StateStore singleton reset — will re-discover on next call.")


def _get_state_store():
    """Get or create the StateStore singleton backed by Lakebase Data API.

    Discovery: uses SDK to find the Lakebase endpoint from the project ID.
    Returns None if Lakebase is not provisioned yet (app can still serve Admin page).
    Caches the 'not ready' state to avoid flooding the workspace API on every request.
    On connection failure (stale endpoint after recreation), resets and re-discovers.
    """
    global _state_store, _state_store_checked_at
    if _state_store is not None:
        # SafeStateStore.health_check() returns False on failure (non-fatal).
        # On a stale connection, just return the safe-wrapped store anyway
        # — individual calls will log warnings if Lakebase is truly down.
        return _state_store

    # Don't retry discovery more often than every 30s
    now = time.time()
    if now - _state_store_checked_at < _STATE_STORE_RETRY_INTERVAL:
        return None
    _state_store_checked_at = now

    import os
    from services.state_store import StateStore, SafeStateStore
    from databricks.sdk import WorkspaceClient

    project_id = os.environ.get("LAKEBASE_PROJECT_ID", "aibi-studio")
    branch_id = "production"

    try:
        w = WorkspaceClient()
        # Get endpoint host for direct pg8000 connection
        endpoints = list(w.postgres.list_endpoints(
            parent=f"projects/{project_id}/branches/{branch_id}"
        ))
        if not endpoints:
            logger.info(
                f"Lakebase project '{project_id}' not provisioned yet. "
                "Run 'Setup Infrastructure' from the Admin page."
            )
            return None
        endpoint_host = endpoints[0].status.hosts.host
    except Exception as e:
        logger.warning(f"Lakebase discovery failed: {e}")
        return None

    # User and token functions for pg8000 connection
    # For SPs: postgres_role is the applicationId (UUID), not the display name.
    # For users: postgres_role is the email (user_name).
    endpoint_name = f"projects/{project_id}/branches/{branch_id}/endpoints/primary"
    def _get_username():
        me = w.current_user.me()
        # SPs have application_id; users use user_name (email)
        return getattr(me, 'application_id', None) or me.user_name
    def _get_token():
        return w.postgres.generate_database_credential(endpoint=endpoint_name).token

    raw_store = StateStore(endpoint_host, "databricks_postgres", _get_username, _get_token)
    _state_store = SafeStateStore.wrap(raw_store)
    logger.info(f"StateStore initialized (safe-wrapped): {endpoint_host} (project={project_id}, direct pg8000)")

    return _state_store


def _finalize_run_manifest(run_id, run, domain, run_mode, config, services, run_store, log):
    """Build and persist run_manifest.json from tracked step/sub-step data.

    Called at pipeline completion (success or failure). Records every tool call
    as a sub-step so the UI can show granular progress on reload.
    """
    try:
        manifest = {
            "run_id": run_id,
            "domain": domain,
            "version": run.get('version'),
            "version_suffix": run.get('version_suffix', ''),
            "status": run.get('status', 'unknown'),
            "run_mode": run_mode,
            "started_at": run.get('started_at'),
            "completed_at": run.get('completed_at'),
            "duration_s": run.get('duration_s'),
            "error": run.get('error'),
            "steps": [],
        }
        for step_name, step_info in run.get('step_data', {}).items():
            manifest["steps"].append({
                "step_name": step_name,
                "status": step_info.get('status', 'unknown'),
                "duration_s": step_info.get('duration_s'),
                "substeps": step_info.get('phases', []),
            })
        # Save to workspace output folder
        output_folder = getattr(config, 'output_folder', None)
        if output_folder:
            manifest_path = f"{output_folder}/run_manifest.json"
            services["workspace"].write_file(manifest_path, json.dumps(manifest, indent=2))
            log.info(f"Written run_manifest.json to {manifest_path}")
        # Persist to Lakebase
        if run_store:
            run_store.save_run_manifest(run_id, manifest)
    except Exception as e:
        log.warning(f"Failed to finalize run_manifest: {e}")


def _persist_phase_to_lakebase(run_store, run_id, step, event_data, incoming_status, phases):
    """Write-through: persist phase_update event to Lakebase (non-blocking on failure).

    Also persists auto-completed prior phases when a new phase starts.
    """
    try:
        # Persist the current phase event
        run_store.persist_phase_update(run_id, step, event_data)

        # If we auto-completed prior phases, persist those too
        if incoming_status == 'started':
            for prior in phases:
                if prior.get('status') == 'completed' and prior.get('phase_id') != event_data.get('phase_id'):
                    # Only persist if it was just auto-completed (no completed_at yet in Lakebase)
                    run_store.persist_phase_update(run_id, step, {
                        'phase_id': prior.get('phase_id', ''),
                        'phase_name': prior.get('phase_name', ''),
                        'status': 'completed',
                        'stats': prior.get('stats', {}),
                        'findings': prior.get('findings', []),
                    })
    except Exception as e:
        logger.warning(f"_persist_phase_to_lakebase failed (non-fatal): {e}")


def _persist_tool_to_lakebase(run_store, run_id, step, tool_name, event_type, event_data):
    """Write-through: persist tool call event to Lakebase (non-blocking on failure)."""
    try:
        status_map = {
            'tool_started': 'running',
            'tool_completed': 'completed',
            'tool_failed': 'failed',
        }
        run_store.persist_tool_call(run_id, step, {
            'tool_name': tool_name,
            'status': status_map.get(event_type, 'running'),
            'args_summary': event_data.get('args_summary', ''),
            'duration_ms': event_data.get('duration_ms'),
            'error': event_data.get('error', '')[:500] if event_data.get('error') else None,
            'started_at': event_data.get('started_at'),
        })
    except Exception as e:
        logger.warning(f"_persist_tool_to_lakebase failed (non-fatal): {e}")


def _detect_resume_step_from_artifacts(output_folder: str, workspace_service) -> str:
    """Detect which pipeline step to resume from by checking output artifacts.

    When the app crashes mid-pipeline, Lakebase step records may be incomplete
    or a fresh run_id has no history. This function checks the filesystem for
    step completion markers to determine where to resume.

    Args:
        output_folder: The versioned output path (e.g. .../generated_outputs/v4)
        workspace_service: WorkspaceService instance for file checks.

    Returns:
        The step_name of the first INCOMPLETE step, or None if no steps are done.
        Ordered: create_data_layer -> create_metric_views -> create_dashboards
                 -> create_genie_space -> generate_documentation
    """
    # Step completion markers (file existence = step completed)
    step_markers = [
        ('create_data_layer', 'data_layer_validation.yaml'),
        ('create_metric_views', 'metric_views/metric_view_validation.yaml'),
        ('create_dashboards', 'dashboard_validation.yaml'),
        ('create_genie_space', 'genie_semantic_inventory.yaml'),
        ('generate_documentation', 'readme.md'),
    ]

    last_completed = None
    try:
        for step_name, marker_file in step_markers:
            marker_path = f"{output_folder}/{marker_file}"
            try:
                content = workspace_service.read_file(marker_path)
                if content and len(content.strip()) > 0:
                    last_completed = step_name
                else:
                    break
            except Exception:
                break
    except Exception as e:
        logger.warning(f"Artifact-based resume detection failed: {e}")
        return None

    if last_completed is None:
        return None  # No steps completed

    # Return the NEXT step after the last completed one
    step_order = [s[0] for s in step_markers]
    last_idx = step_order.index(last_completed)
    if last_idx + 1 < len(step_order):
        return step_order[last_idx + 1]
    else:
        return None  # All steps completed


def _collect_assets_created(run: dict) -> dict:
    """Extract created asset names from run step data for the version registry."""
    assets = {}
    step_data = run.get('step_data', {})
    for step_name, step_info in step_data.items():
        if step_name == 'create_metric_views':
            # Metric view names from sub-step artifacts
            mv_names = []
            for sub in step_info.get('sub_steps', []):
                name = sub.get('artifact_name', '')
                if name and 'metric_view' in name:
                    mv_names.append(name)
            if mv_names:
                assets['metric_views'] = mv_names
        elif step_name == 'create_dashboards':
            db_names = []
            for sub in step_info.get('sub_steps', []):
                name = sub.get('artifact_name', '')
                if name and 'dashboard' in name:
                    db_names.append(name)
            if db_names:
                assets['dashboards'] = db_names
        elif step_name == 'create_genie_space':
            genie_names = []
            for sub in step_info.get('sub_steps', []):
                name = sub.get('artifact_name', '')
                if name and 'genie' in name:
                    genie_names.append(name)
            if genie_names:
                assets['genie_spaces'] = genie_names
    return assets


def _sync_version_registry(run_mode, config, services, pipeline_run, run, log):
    """Sync version_registry.yaml after pipeline run completes or fails."""
    from orchestrator.version_resolver import VersionResolver
    if run_mode != 'versioned' or not hasattr(config, 'version'):
        return
    try:
        final_status = pipeline_run.status.value
        assets = _collect_assets_created(run)
        resolver = VersionResolver(
            services["workspace"], services["sql"],
            services.get("lakeview"), services.get("genie")
        )
        resolver.mark_version_status(
            config, config.version, final_status,
            assets_created=assets,
            error=pipeline_run.error,
        )
        log.info(f"Version registry synced: v{config.version} -> {final_status}")
    except Exception as e:
        log.warning(f"Version registry sync failed (non-fatal): {e}")


def _run_pipeline_background(run_id: str, domain: str, steps: list, run_mode: str,
                              version_override, user_token: str = "",
                              resume_from: dict = None, version_mode: str = "auto",
                              agent_skills_version: str = None):
    """Background thread: loads config, runs pipeline, updates _runs state.

    Args:
        resume_from: Optional dict {"step_name": str, "phase_name": str} for
                     phase-level resume on rerun. Passed through to PipelineRunner.run().
        version_mode: Version resolution mode — "auto", "retry", or "fresh".
                      "auto": running=resume, failed/completed=new version.
                      "retry": resume the latest failed version (rerun from failure point).
                      "fresh": always create a new version regardless of status.
    """
    import os
    import traceback
    from orchestrator.config_loader import ConfigLoader, ConfigError
    from orchestrator.pipeline import PipelineRunner
    from orchestrator.version_resolver import VersionResolver
    from services.state_store import StateStore

    run = _runs[run_id]
    app_mirror = None
    app_execution = None

    def event_callback(event):
        """Callback receives PipelineEvents, updates run state + pushes to SSE queue."""
        event_data = {
            "type": event.event_type,
            "timestamp": event.timestamp,
            **event.data
        }

        # Ensure step_data dict exists for structured status tracking
        if 'step_data' not in run:
            run['step_data'] = {}

        # Update run state (in-memory)
        if event.event_type == "step_started":
            step = event.data.get('step')
            run['current_step'] = step
            run['status'] = 'running'
            total = event.data.get('total', 6)
            idx = event.data.get('index', 0)
            run['progress_pct'] = int((idx / total) * 100)
            # Track in step_data
            run['step_data'][step] = {'step_name': step, 'status': 'running', 'duration_s': None, 'phases': []}
            # Persist to Lakebase (upsert — creates the step row if not exists)
            run_store.upsert_step(run_id, step, step_index=idx, status='running',
                                  started_at=datetime.utcnow().isoformat())
            run_store.update_run_status(run_id, 'running', current_step=step)
        elif event.event_type == "step_completed":
            step = event.data.get('step')
            duration_s = event.data.get('duration_s')
            run['steps_completed'].append(step)
            # Track in step_data
            if step in run['step_data']:
                run['step_data'][step]['status'] = 'completed'
                run['step_data'][step]['duration_s'] = duration_s
            else:
                run['step_data'][step] = {'step_name': step, 'status': 'completed', 'duration_s': duration_s, 'phases': []}
            # Persist to Lakebase
            run_store.update_step(run_id, step, 'completed',
                                  duration_s=duration_s,
                                  artifacts=event.data.get('artifacts'))
            run_store.update_run_status(run_id, 'running',
                                        steps_completed=len(run['steps_completed']))
            # Incremental manifest write — capture progress after each step
            _finalize_run_manifest(run_id, run, domain, run_mode, config,
                                   services, run_store, logger)
        elif event.event_type == "step_failed":
            step = event.data.get('step')
            duration_s = event.data.get('duration_s')
            run['status'] = 'failed'
            run['error'] = event.data.get('error', 'Unknown error')
            # Track in step_data
            if step in run['step_data']:
                run['step_data'][step]['status'] = 'failed'
                run['step_data'][step]['duration_s'] = duration_s
            else:
                run['step_data'][step] = {'step_name': step, 'status': 'failed', 'duration_s': duration_s, 'phases': []}
            # Persist to Lakebase
            run_store.update_step(run_id, step, 'failed',
                                  duration_s=duration_s,
                                  error=event.data.get('error'),
                                  error_detail=event.data.get('error_detail'),
                                  suggestion=event.data.get('suggestion'))
            # Incremental manifest write — capture error state immediately
            _finalize_run_manifest(run_id, run, domain, run_mode, config,
                                   services, run_store, logger)
        elif event.event_type == "step_skipped":
            step = event.data.get('step')
            # On rerun, if step was previously completed, keep its completed status
            if step in run.get('steps_completed', []):
                run['step_data'].setdefault(step, {'step_name': step, 'status': 'completed', 'duration_s': None, 'phases': []})
            else:
                run['step_data'].setdefault(step, {'step_name': step, 'status': 'skipped', 'duration_s': None, 'phases': []})
        elif event.event_type in ("phase_started", "phase_completed", "phase_failed", "phase_skipped"):
            step = event.data.get('step')
            phase = event.data.get('phase')
            phase_status = event.event_type.replace('phase_', '')
            # Map to CSS-compatible status names
            if phase_status == 'started':
                phase_status = 'running'
            duration_ms = event.data.get('duration_ms')
            # Add/update phase in step_data
            if step in run['step_data']:
                phases = run['step_data'][step].get('phases', [])
                # Find existing phase entry by phase_name OR phase_id
                existing = next((p for p in phases
                                 if p.get('phase_name') == phase or p.get('phase_id') == phase), None)
                if existing:
                    existing['status'] = phase_status
                    if duration_ms is not None:
                        existing['duration_ms'] = duration_ms
                else:
                    # Set both phase_name and phase_id so phase_update can find it
                    phases.append({'phase_id': phase, 'phase_name': phase, 'status': phase_status, 'duration_ms': duration_ms})
                run['step_data'][step]['phases'] = phases
        elif event.event_type == "phase_update":
            # Rich phase progress from LLM's report_progress tool
            step = event.data.get('step') or run.get('current_step')
            phase_id = event.data.get('phase_id', '')
            incoming_status = event.data.get('status', 'started')
            if step and step in run['step_data']:
                phases = run['step_data'][step].get('phases', [])
                # Upsert phase by phase_id
                existing = next((p for p in phases if p.get('phase_id') == phase_id), None)
                if existing:
                    existing.update({
                        'phase_name': event.data.get('phase_name', existing.get('phase_name', '')),
                        'status': incoming_status,
                        'current_task': event.data.get('current_task'),
                        'progress_pct': event.data.get('progress_pct'),
                        'stats': event.data.get('stats', existing.get('stats', {})),
                        'happenings': event.data.get('happenings', existing.get('happenings', [])),
                        'findings': event.data.get('findings', existing.get('findings', [])),
                    })
                else:
                    # NEW phase being added — auto-close any prior phases that are
                    # still in a non-terminal state. Phases are strictly sequential
                    # (single-threaded agent loop), so if phase N+1 appears, phase N
                    # must have functionally completed even if the LLM forgot to
                    # call report_progress(status="completed") for it.
                    # NOTE: trigger on ANY incoming_status (not just 'started')
                    # because the LLM often reports a phase directly as 'completed'
                    # without a preceding 'started' call.
                    for prior in phases:
                        if prior.get('status') not in ('completed', 'failed'):
                            prior['status'] = 'completed'
                            logger.info(
                                f"Auto-completing prior phase '{prior.get('phase_name')}' "
                                f"because new phase '{event.data.get('phase_name')}' appeared"
                            )

                    phases.append({
                        'phase_id': phase_id,
                        'phase_name': event.data.get('phase_name', ''),
                        'status': incoming_status,
                        'current_task': event.data.get('current_task'),
                        'progress_pct': event.data.get('progress_pct'),
                        'stats': event.data.get('stats', {}),
                        'happenings': event.data.get('happenings', []),
                        'findings': event.data.get('findings', []),
                    })
                run['step_data'][step]['phases'] = phases

                # ── DURABLE CHECKPOINT: write-through to Lakebase ──
                _persist_phase_to_lakebase(run_store, run_id, step, event.data, incoming_status, phases)

        elif event.event_type in ("tool_started", "tool_completed", "tool_failed"):
            # Track agent tool calls in a SEPARATE list (not phases) — these are
            # low-level implementation details, not user-facing progress events.
            # Only report_progress (phase_update) events go into 'phases'.
            step = event.data.get('step') or run.get('current_step')
            tool_name = event.data.get('tool_name', '')
            if step and step in run['step_data']:
                tool_calls = run['step_data'][step].setdefault('tool_calls', [])
                if event.event_type == 'tool_started':
                    tool_calls.append({
                        'tool_name': tool_name,
                        'status': 'running',
                        'started_at': datetime.utcnow().isoformat(),
                        'args_summary': event.data.get('args_summary', ''),
                    })
                elif event.event_type == 'tool_completed':
                    # Update the most recent matching tool call
                    existing = next((t for t in reversed(tool_calls)
                                     if t.get('tool_name') == tool_name and t.get('status') == 'running'), None)
                    if existing:
                        existing['status'] = 'completed'
                        existing['duration_ms'] = event.data.get('duration_ms')
                    else:
                        tool_calls.append({
                            'tool_name': tool_name,
                            'status': 'completed',
                            'duration_ms': event.data.get('duration_ms'),
                        })
                elif event.event_type == 'tool_failed':
                    existing = next((t for t in reversed(tool_calls)
                                     if t.get('tool_name') == tool_name and t.get('status') == 'running'), None)
                    if existing:
                        existing['status'] = 'failed'
                        existing['duration_ms'] = event.data.get('duration_ms')
                        existing['error'] = event.data.get('error', '')[:500]
                    else:
                        tool_calls.append({
                            'tool_name': tool_name,
                            'status': 'failed',
                            'duration_ms': event.data.get('duration_ms'),
                            'error': event.data.get('error', '')[:500],
                        })

                # Write-through: persist tool call to Lakebase
                _persist_tool_to_lakebase(run_store, run_id, step, tool_name, event.event_type, event.data)

        elif event.event_type == "pipeline_completed":
            run['status'] = event.data.get('status', 'completed')
            run['progress_pct'] = 100
            run['duration_s'] = event.data.get('duration_s', 0)
            # Persist final state
            run_store.update_run_status(run_id, run['status'],
                                        duration_s=run['duration_s'],
                                        error=event.data.get('error'),
                                        steps_completed=len(run['steps_completed']))
        elif event.event_type == "log":
            run['logs'].append(event.data.get('message', ''))
            # Also store per-step logs
            step = event.data.get('step') or run.get('current_step')
            if step:
                if 'step_logs' not in run:
                    run['step_logs'] = {}
                if step not in run['step_logs']:
                    run['step_logs'][step] = ''
                run['step_logs'][step] += event.data.get('message', '') + '\n'

        # Push to SSE queue
        q = _event_queues.get(run_id)
        if q:
            q.put(event_data)

    try:
        # ── Step 0: Load Configuration (per master prompt) ──
        config_start = time.time()
        run['current_step'] = 'load_configuration'
        run['status'] = 'running'
        run['step_data']['load_configuration'] = {
            'step_name': 'load_configuration', 'status': 'running', 'duration_s': None,
            'phases': [
                {'phase_id': 'load_yaml', 'phase_name': 'Load Configuration', 'status': 'running',
                 'current_task': 'Reading accelerator.yaml and resolving paths',
                 'happenings': ['Reading accelerator.yaml', 'Resolving workspace paths'],
                 'findings': [], 'stats': {}},
            ]
        }
        q = _event_queues.get(run_id)
        if q:
            q.put({"type": "step_started", "step": "load_configuration",
                   "index": 0, "total": 7, "timestamp": datetime.utcnow().isoformat()})

        # Initialize services with user's token for workspace writes
        services = _get_services(user_token=user_token or None)
        llm_client = _get_llm_client()

        # Load config per master prompt Step 0:
        # - Read accelerator.yaml from EXAMPLE_DIR
        # - Read databricks.yml for sql_warehouse_id
        # - Resolve output folder, name suffix, paths
        from config import get_config
        app_config = get_config()
        workspace_root = app_config.WORKSPACE_ROOT
        warehouse_id = app_config.SQL_WAREHOUSE_ID
        loader = ConfigLoader(services["workspace"])
        config = loader.load(domain, workspace_root, warehouse_id,
                             workspace_root=workspace_root)

        # v2 is master-led. Lakebase mirrors App state only; it never allocates
        # versions or writes the portable lifecycle manifest.
        if agent_skills_version:
            config.agent_skills_version = agent_skills_version
        if config.agent_skills_version == 'v2':
            from orchestrator.master_agent import MasterAgentHost
            from orchestrator.app_state import AppStateMirror
            run_store = _get_state_store()
            if not run_store:
                raise RuntimeError('Lakebase is required for durable App tracking. Genie Code can run v2 without it.')
            try:
                app_execution = run_store.open_app_execution(run_id)
            except Exception as _lb_err:
                logger.warning(f"Lakebase advisory lock failed (non-fatal, run continues): {_lb_err}")
                app_execution = None  # ownership tracking disabled for this run
            journal_path = config.example_dir + '/app_runs/' + run_id + '.json'
            if not run_store.get_run(run_id):
                run_store.create_run(run_id, domain, run_mode=run_mode, config_json={
                    'agent_skills_version': 'v2', 'app_journal_path': journal_path})
            run['agent_skills_version'] = 'v2'
            # Host configuration was loaded; the master still owns freeze/admission.
            config_info = run['step_data']['load_configuration']
            config_info['status'] = 'running'
            for phase in config_info['phases']:
                if phase.get('phase_id') == 'load_yaml':
                    phase.update(status='completed', current_task='Host configuration loaded; master freeze follows.')
            run['requested_steps'] = steps
            run['app_journal_path'] = journal_path
            app_mirror = AppStateMirror(services['workspace'], run_store, run, journal_path)
            app_mirror.save()
            host = MasterAgentHost(config, services, llm_client)
            _runners[run_id] = host
            def master_event(event_type, data):
                # Ownership heartbeat REMOVED — Lakebase connections are too
                # unreliable for a per-iteration health check.  The advisory
                # lock is acquired once at startup (open_app_execution) for
                # duplicate-worker prevention; ongoing verification is skipped
                # so a transient Lakebase disconnect can never kill a run.
                run['status'] = 'running'
                app_mirror.event(event_type, data)
                event_queue = _event_queues.get(run_id)
                if event_queue:
                    event_queue.put({'type': event_type, **data,
                        'timestamp': datetime.utcnow().isoformat()})
            result = host.run(domain=domain, run_id=run_id, version_mode=version_mode,
                              version_override=version_override, steps=steps, run_mode=run_mode,
                              callback=master_event)
            manifest = result['manifest']
            run.update(status=result['status'], error=result['error'], duration_s=result['duration_s'],
                       canonical_run_id=manifest['run_id'], version=manifest['version'],
                       output_folder=manifest['output_folder'], progress_pct=100,
                       completed_at=datetime.utcnow().isoformat())
            run['run_manifest'] = manifest
            run['run_context_path'] = manifest['run_context_path']
            status_map = {'PASS': 'completed', 'PARTIAL_SUCCESS': 'partial_success',
                          'FAIL': 'failed', 'SKIPPED': 'skipped'}
            for item in manifest.get('steps', []):
                step = item['step_name']
                info = run['step_data'].setdefault(step, {'step_name': step, 'phases': []})
                info.update(status=status_map.get(item['status'], 'failed'),
                            duration_s=item.get('duration_s'), error=item.get('error'))
            run['steps_completed'] = [s for s, info in run['step_data'].items() if info.get('status') == 'completed']
            app_mirror.save()
            event_queue = _event_queues.get(run_id)
            if event_queue:
                event_queue.put({'type': 'pipeline_completed', 'status': run['status'],
                    'error': run['error'], 'duration_s': run['duration_s'],
                    'timestamp': run['completed_at']})
            return

        # Legacy v1 UI persistence remains separate from portable v2 execution.
        run_store = _get_state_store()
        if not run_store:
            raise RuntimeError('Lakebase not provisioned for the legacy v1 pipeline.')

        # Handle versioning
        # Schema comes from accelerator.yaml (single source of truth).
        # The App no longer overrides catalog.source/target — both paths
        # (App + Genie Agent Code) read the same yaml values.
        config.run_mode = run_mode
        # Override agent_skills_version if explicitly provided by the UI
        if agent_skills_version:
            config.agent_skills_version = agent_skills_version
        if run_mode == 'versioned':
            resolver = VersionResolver(services["workspace"], services["sql"],
                                       services["lakeview"], services["genie"])
            version_info = resolver.resolve(config, override=version_override,
                                                run_id=run_id, mode=version_mode)
            config.version = version_info.version
            config.version_suffix = version_info.suffix
            # Output folder: output/v1/, output/v2/ etc.
            config.output_folder = config.output_folder + f"/v{version_info.version}"
            # Subfolder pre-creation moved to just before pipeline.run() where
            # the authenticated workspace service is available (SP w/ CAN_MANAGE).
            # Append version suffix to all asset names
            suffix = version_info.suffix  # "_v1", "_v2", etc.
            if config.assets.metric_view and config.assets.metric_view_strategy != "auto":
                config.assets.metric_view = config.assets.metric_view + suffix
            # For auto strategy, metric view names are determined dynamically by the pipeline agent
            if config.assets.dashboard:
                config.assets.dashboard = config.assets.dashboard + suffix
            if config.assets.dashboards:
                for d in config.assets.dashboards:
                    if 'name' in d:
                        d['name'] = d['name'] + suffix
            if config.assets.genie_space:
                config.assets.genie_space = config.assets.genie_space + suffix
            if config.assets.genie_notebook:
                config.assets.genie_notebook = config.assets.genie_notebook + suffix
            # Ensure version is always an int, not a dict (some resolvers
            # return a full version dict instead of the numeric id).
            _ver = version_info.version
            if isinstance(_ver, dict):
                _ver = _ver.get('number', _ver.get('version', 0))
            run['version'] = int(_ver) if _ver is not None else 0
            run['version_suffix'] = version_info.suffix

        # Update config phase as completed with rich detail
        config_phases = run['step_data']['load_configuration']['phases']
        data_source_type = getattr(config, 'data_source', None)
        ds_type_str = getattr(data_source_type, 'type', 'unknown') if data_source_type else 'unknown'
        config_phases[0]['status'] = 'completed'
        config_phases[0]['happenings'] = [
            'Reading accelerator.yaml',
            'Resolving workspace paths',
            f'Detected data source type: {ds_type_str}',
            f'Version resolution: v{run.get("version", "?")} ({run.get("version_suffix", "")})',
        ]
        config_phases[0]['findings'] = [
            f"Domain: {domain}",
            f"Version: v{run.get('version', '?')} ({run.get('version_suffix', '')})",
            f"Data source: {ds_type_str}",
            f"Output: {getattr(config, 'output_folder', '?').split('/')[-1]}",
        ]
        config_phases[0]['stats'] = {}
        config_phases.append({
            'phase_id': 'validate_config', 'phase_name': 'Validate Configuration',
            'status': 'running', 'current_task': 'Validating config and resolving assets',
            'happenings': ['Checking required fields', 'Verifying catalog/schema references'],
            'findings': [], 'stats': {},
        })

        # Populate run metadata for UI status bar
        catalog_target = getattr(config.catalog, 'target', '') or '' if hasattr(config, 'catalog') else ''
        if '.' in catalog_target:
            run['catalog'], run['schema'] = catalog_target.split('.', 1)
        else:
            run['catalog'] = catalog_target
            run['schema'] = getattr(config, 'schema', '') or ''

        # Validate config
        errors = loader.validate(config)
        if errors:
            error_msgs = "; ".join(f"{e.field}: {e.message}" for e in errors)
            run['status'] = 'failed'
            run['error'] = f"Config validation failed: {error_msgs}"
            event_callback_data = {"type": "pipeline_completed", "status": "failed",
                                   "duration_s": 0, "timestamp": datetime.utcnow().isoformat()}
            q = _event_queues.get(run_id)
            if q:
                q.put(event_callback_data)
            return

        # ── Artifact-based resume detection ──
        # When resuming a version but no explicit resume_from (e.g. app crash,
        # new run with version_mode='retry'), scan the output folder to determine
        # which steps are already completed. This is the CRASH-SAFE resume path.
        if version_info and version_info.is_resume and not resume_from:
            detected_step = _detect_resume_step_from_artifacts(config.output_folder, services.get('workspace'))
            if detected_step:
                resume_from = {"step_name": detected_step}
                logger.info(f"Artifact-based resume: detected resume point at '{detected_step}'")
            else:
                logger.info("Artifact-based resume: no completed steps detected, starting from beginning")

        # Set clean_start based on run_mode
        config.pipeline.clean_start = (run_mode == 'clean')

        # ── Step 0 complete ──
        config_duration = round(time.time() - config_start, 1)
        # Mark validate phase completed with rich summary
        config_phases = run['step_data']['load_configuration']['phases']
        for ph in config_phases:
            if ph.get('status') not in ('completed', 'failed'):
                ph['status'] = 'completed'
        # Enrich the validate phase with full config detail
        if config_phases:
            catalog_str = f"{run.get('catalog', '?')}.{run.get('schema', '?')}"
            warehouse_id = getattr(config, 'sql_warehouse_id', '?') or '?'
            clean_start = getattr(getattr(config, 'pipeline', None), 'clean_start', False)
            run_mode_str = run_mode or 'clean'
            steps_enabled = getattr(getattr(config, 'pipeline', None), 'steps', None)
            steps_list = [s.get('name', s) if isinstance(s, dict) else str(s)
                          for s in (steps_enabled or [])] if steps_enabled else ['all']
            config_phases[-1]['happenings'] = [
                'Checking required fields',
                'Verifying catalog/schema references',
                f'Resolved catalog target: {catalog_str}',
                f'Warehouse ID: {warehouse_id[:8]}...',
                f'Clean start: {"yes" if clean_start else "no"}',
            ]
            skills_ver = getattr(config, 'agent_skills_version', 'v1')
            config_phases[-1]['findings'] = [
                f"Catalog: {catalog_str}",
                f"Warehouse: {warehouse_id}",
                f"Run mode: {run_mode_str}",
                f"Agent skills: {skills_ver}",
                f"Steps: {', '.join(steps_list)}",
                f"Config loaded in {config_duration}s",
            ]
            config_phases[-1]['stats'] = {
                'duration_s': config_duration,
            }
        run['step_data']['load_configuration']['status'] = 'completed'
        run['step_data']['load_configuration']['duration_s'] = config_duration
        run['steps_completed'].append('load_configuration')
        q = _event_queues.get(run_id)
        if q:
            q.put({"type": "step_completed", "step": "load_configuration",
                   "duration_s": config_duration, "timestamp": datetime.utcnow().isoformat()})

        # Create and run pipeline (run_store enables phase-level tracking + persistence)
        runner = PipelineRunner(config, services, llm_client, run_store=run_store)
        _runners[run_id] = runner

        run['status'] = 'running'
        run['started_at'] = datetime.utcnow().isoformat()

        # Persist run creation to Lakebase (skip on rerun — record already exists)
        if not run.get('is_rerun'):
            run_store.create_run(
                run_id=run_id, domain=domain, run_mode=run_mode,
                version=run.get('version'), version_suffix=run.get('version_suffix'),
                total_steps=(len(steps) + 1) if steps else 7,  # +1 for load_configuration
                config_json=config.to_dict() if hasattr(config, 'to_dict') else None,
            )
        else:
            # Increment retry_count on the run record
            run_store.increment_retry(run_id)

        # Persist Config step + phases to Lakebase so they survive app restarts
        try:
            run_store.upsert_step(run_id, 'load_configuration', step_index=0,
                                  status='completed', duration_s=config_duration)
            for ph in run['step_data']['load_configuration'].get('phases', []):
                run_store.persist_phase_update(run_id, 'load_configuration', ph)
        except Exception as persist_err:
            logger.warning(f"Failed to persist config step to Lakebase: {persist_err}")

        # Pre-create expected output subfolders using the SP-authenticated
        # workspace service (CAN_MANAGE on project folder).  This prevents
        # "parent folder missing" errors when LLM code writes artifacts.
        _ws_svc = services.get('workspace')
        if _ws_svc and hasattr(config, 'output_folder'):
            for _sub in ('notebooks', 'metric_views', 'dashboards', 'genie_space',
                         'diagnostics', 'diagnostics/python', 'diagnostics/reconciliation'):
                _dir = f"{config.output_folder}/{_sub}"
                try:
                    _ws_svc.mkdirs(_dir)
                    logger.debug(f"Pre-created output subfolder: {_dir}")
                except Exception as _e:
                    logger.warning(f"Failed to pre-create {_dir}: {_e}")

        # Pass run_id so PipelineRunner reuses it (critical for phase-level resume
        # to match phase records already in pipeline_run_phases table)
        pipeline_run = runner.run(domain=domain, steps=steps, callback=event_callback,
                                   resume_from=resume_from, run_id=run_id)

        # Final state
        run['status'] = pipeline_run.status.value
        run['duration_s'] = pipeline_run.duration_s
        run['error'] = pipeline_run.error
        run['completed_at'] = pipeline_run.completed_at

        # Build run manifest from tracked sub-steps and persist
        _finalize_run_manifest(run_id, run, domain, run_mode, config,
                               services, run_store, logger)

        # Sync version registry so the UI reflects the final run outcome
        _sync_version_registry(run_mode, config, services, pipeline_run, run, logger)

    except Exception as e:
        logger.exception(f"Pipeline background execution failed: {e}")
        run['status'] = 'failed'
        run['error'] = str(e)
        if app_mirror is not None:
            try:
                app_mirror.fail_active(str(e))
                app_mirror.save()
            except Exception as persist_error:
                run['persistence_warning'] = str(persist_error)
                logger.exception('Failed to persist App failure snapshot')
        # Notify SSE
        q = _event_queues.get(run_id)
        if q:
            q.put({"type": "pipeline_completed", "status": "failed",
                   "error": str(e), "timestamp": datetime.utcnow().isoformat()})
    finally:
        if app_execution is not None:
            app_execution.close()
        # Cleanup runner reference
        _runners.pop(run_id, None)
        # Signal SSE stream end
        q = _event_queues.get(run_id)
        if q:
            q.put(None)  # Sentinel to close SSE


@pipeline_bp.route('/run', methods=['POST'])
def start_run():
    """Start a new pipeline execution (async background thread).

    Request JSON:
        domain (str): Example domain name (e.g. 'member_claims')
        steps (list, optional): Specific steps to run; omit for all enabled steps
        run_mode (str, optional): 'clean' (default) or 'versioned'
        version_override (int, optional): Force specific version number

    Returns:
        {run_id: str, status: 'started', run_mode: str}
    """
    data = request.get_json(force=True)
    domain = data.get('domain')

    if not domain:
        return jsonify({'error': {'type': 'ValidationError', 'message': 'domain is required'}}), 400

    run_mode = data.get('run_mode', 'versioned')
    if run_mode not in ('clean', 'versioned', 'new'):
        return jsonify({'error': {'type': 'ValidationError', 'message': "run_mode must be 'clean' or 'versioned'"}}), 400

    version_override = data.get('version_override')  # int or None
    version_mode = data.get('version_mode', 'auto')  # "auto", "retry", or "fresh"
    agent_skills_version = data.get('agent_skills_version')  # str or None (falls back to config)

    run_id = str(uuid.uuid4())
    steps = data.get('steps')  # None means all enabled steps

    # Capture model names from environment for UI display
    _llm_model = os.environ.get('LLM_ENDPOINT_NAME', 'databricks-gpt-5-5')
    _vision_model = os.environ.get('VISION_ENDPOINT_NAME', 'databricks-gpt-5-5')

    # Initialize run state
    _runs[run_id] = {
        'run_id': run_id,
        'domain': domain,
        'status': 'started',
        'run_mode': run_mode,
        'version_override': version_override,
        'version_mode': version_mode,
        'current_step': None,
        'steps_completed': [],
        'step_data': {},
        'logs': [],
        'step_logs': {},
        'progress_pct': 0,
        'started_at': datetime.utcnow().isoformat(),
        'error': None,
        'duration_s': None,
        'llm_model': _llm_model,
        'vision_model': _vision_model,
    }

    # Create SSE event queue for this run
    _event_queues[run_id] = queue.Queue()

    # Capture user's OAuth token for workspace API calls in background thread
    user_token = request.headers.get('X-Forwarded-Access-Token', '')

    # Start background execution
    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(run_id, domain, steps, run_mode, version_override, user_token),
        kwargs={'version_mode': version_mode, 'agent_skills_version': agent_skills_version},
        daemon=True
    )
    thread.start()

    logger.info(f"Pipeline started: run_id={run_id}, domain={domain}, mode={run_mode}, version_mode={version_mode}, agent_skills={agent_skills_version or 'config-default'}")
    return jsonify({'run_id': run_id, 'status': 'started', 'run_mode': run_mode, 'version_mode': version_mode, 'agent_skills_version': agent_skills_version}), 202


@pipeline_bp.route('/status/<run_id>')
def get_status(run_id):
    """Get current pipeline execution status with structured steps array.

    Only serves ACTIVE runs (running/started/cancelling). For completed/failed runs,
    returns 404 so the client falls through to /runs/<run_id> which reads from Lakebase.

    Returns:
        {run_id, status, current_step, steps: [{step_name, status, duration_s, phases}], ...}
    """
    run = _runs.get(run_id)
    if not run:
        return jsonify({'error': {'type': 'NotFound', 'message': f'Run {run_id} not found'}}), 404

    # For terminal-state runs, return 404 to force client to use /runs/<run_id> (Lakebase)
    # This avoids returning stale in-memory state with large logs/internal fields
    # Note: We intentionally do NOT reject completed/failed/cancelled runs here.
    # The UI needs this endpoint to render the final state with all phases visible
    # in the expandable accordion after completion.

    # Build structured steps array for the UI
    STEP_ORDER = [
        "load_configuration", "environment_setup", "create_data_layer",
        "create_metric_views", "create_dashboards", "create_genie_space",
        "generate_documentation",
    ]
    step_data = run.get('step_data', {})
    steps_completed = run.get('steps_completed', [])
    current_step = run.get('current_step')

    steps_array = []
    for step_name in STEP_ORDER:
        sd = step_data.get(step_name, {})
        if sd:
            steps_array.append(sd)
        elif step_name in steps_completed:
            steps_array.append({'step_name': step_name, 'status': 'completed', 'phases': []})
        elif step_name == current_step:
            steps_array.append({'step_name': step_name, 'status': 'running', 'phases': []})
        else:
            steps_array.append({'step_name': step_name, 'status': 'pending', 'phases': []})

    response = {**run, 'steps': steps_array}
    # Remove internal fields
    response.pop('step_data', None)
    return jsonify(response)


@pipeline_bp.route('/cancel/<run_id>', methods=['POST'])
def cancel_run(run_id):
    """Request cancellation of a running pipeline.

    Sets status to 'cancelled' immediately (not 'cancelling') so the frontend
    can transition the button to Resume All without waiting for the runner to exit.
    The background thread will notice the cancelled status and stop gracefully.
    """
    run = _runs.get(run_id)
    if run_id not in _runners:
        store = _get_state_store()
        record = store.get_run(run_id) if store else None
        if record and record.get('agent_skills_version') == 'v2':
            if store.app_execution_active(run_id):
                return jsonify({'error': {'type': 'Conflict',
                    'message': 'This run is executing on another worker; cancellation was not applied.'}}), 409
            from orchestrator.app_state import recover_snapshot, AppStateMirror
            workspace = _get_services()['workspace']
            run = recover_snapshot(workspace, store, record)
            if run.get('status') in ('completed', 'partial_success'):
                return jsonify({'error': {'type': 'Conflict', 'message': 'Run is already complete.'}}), 409
            run['status'] = 'cancelled'
            AppStateMirror(workspace, store, run, run['app_journal_path']).save()
            _runs[run_id] = run
            return jsonify({'run_id': run_id, 'status': 'cancelled'})
    if not run:
        # Zombie scenario: run exists in Lakebase but not in memory.
        # Allow cancel (just update Lakebase status directly).
        run_store = _get_state_store()
        if run_store:
            try:
                existing = run_store.get_run(run_id)
                if existing and existing.get('status') in ('running', 'pending'):
                    run_store.update_run_status(run_id, 'cancelled')
                    logger.info(f"Zombie run cancelled via Lakebase: run_id={run_id}")
                    return jsonify({'run_id': run_id, 'status': 'cancelled'})
            except Exception as e:
                logger.warning(f"Cancel fallback failed: {e}")
        return jsonify({'error': {'type': 'NotFound', 'message': f'Run {run_id} not found'}}), 404

    run['status'] = 'cancelled'
    runner = _runners.get(run_id)
    if runner:
        runner.cancel()

    # Persist to Lakebase so resume works even after server restart
    run_store = _get_state_store()
    if run_store:
        try:
            run_store.update_run_status(run_id, 'cancelled')
        except Exception as e:
            logger.warning(f"Failed to persist cancel to Lakebase: {e}")

    logger.info(f"Pipeline cancelled: run_id={run_id}")
    return jsonify({'run_id': run_id, 'status': 'cancelled'})


@pipeline_bp.route('/stream/<run_id>')
def stream_events(run_id):
    """Server-Sent Events stream for real-time pipeline progress.

    Client connects and receives events until pipeline completes or fails.
    Event types: connected, step_started, step_completed, step_failed, log, pipeline_completed
    """
    def generate():
        # Send initial connected event
        yield f"data: {json.dumps({'type': 'connected', 'run_id': run_id})}\n\n"

        # Get or create queue
        q = _event_queues.get(run_id)
        if not q:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Run not found'})}\n\n"
            return

        # Replay current state — ensures UI shows progress even on reconnect.
        # This sends all known phase_update events from step_data so the UI
        # can rebuild its state regardless of missed real-time events.
        run = _runs.get(run_id, {})
        for step_name, step_info in run.get('step_data', {}).items():
            # Replay step status
            step_status = step_info.get('status', 'pending')
            if step_status in ('running', 'completed', 'failed'):
                yield f"data: {json.dumps({'type': 'step_started', 'step': step_name})}\n\n"
            if step_status in ('completed',):
                yield f"data: {json.dumps({'type': 'step_completed', 'step': step_name})}\n\n"
            # Replay phase_update events for each phase in this step
            for phase in step_info.get('phases', []):
                replay_event = {
                    'type': 'phase_update',
                    'step': step_name,
                    'phase_id': phase.get('phase_id', ''),
                    'phase_name': phase.get('phase_name', ''),
                    'status': phase.get('status', 'started'),
                    'current_task': phase.get('current_task'),
                    'progress_pct': phase.get('progress_pct'),
                    'stats': phase.get('stats', {}),
                    'happenings': phase.get('happenings', []),
                    'findings': phase.get('findings', []),
                }
                yield f"data: {json.dumps(replay_event)}\n\n"

        # Stream events from queue
        while True:
            try:
                event = q.get(timeout=15)  # 15s heartbeat (must be < proxy idle timeout)
                if event is None:
                    # Sentinel — pipeline done
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                # Send heartbeat to keep connection alive
                yield f": heartbeat\n\n"

                # Check if run is still active
                run = _runs.get(run_id, {})
                if run.get('status') in ('completed', 'failed', 'cancelled'):
                    break

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

# ------------------------------------------------------------------
# Polling-Based Status Endpoint (primary UI data source)
# ------------------------------------------------------------------

@pipeline_bp.route('/run/<run_id>/status')
def get_run_status(run_id):
    """Return full run state for polling-based UI.

    This is the PRIMARY data source for the pipeline monitor UI.
    The frontend polls every 3s and rebuilds its state from this response.
    No SSE, no lost events, no proxy timeouts — always returns current truth.

    Returns JSON:
    {
        "run_id": "...",
        "status": "running|completed|failed|cancelled",
        "progress_pct": 43,
        "current_step": "create_data_layer",
        "elapsed_s": 120.5,
        "error": null,
        "steps": [
            {
                "step_name": "create_data_layer",
                "status": "running",
                "duration_s": 45.2,
                "phases": [
                    {
                        "phase_id": "parse_erd",
                        "phase_name": "Parse ERD",
                        "status": "completed",
                        "current_task": "...",
                        "progress_pct": 100,
                        "stats": {...},
                        "happenings": [...],
                        "findings": [...]
                    }
                ]
            }
        ]
    }
    """
    run = _runs.get(run_id)
    if not run:
        # Lakebase fallback: hydrate from durable state on cache miss
        # (happens after server restart, worker recycling, or browser refresh
        # when the run is no longer in the in-memory dict)
        run_store = _get_state_store()
        if run_store:
            try:
                recovered = run_store.load_run_full(run_id)
                if recovered:
                    if recovered.get('agent_skills_version') == 'v2':
                        from orchestrator.app_state import recover_snapshot
                        record = run_store.get_run(run_id)
                        try:
                            recovered = recover_snapshot(_get_services()['workspace'], run_store, record) or recovered
                        except Exception as replay_error:
                            recovered['persistence_warning'] = f'Workspace replay unavailable: {replay_error}'
                    # Zombie detection: if Lakebase says 'running' but there's
                    # no active thread (app restarted), mark as failed so the
                    # UI shows the "Resume All" button.
                    if recovered.get('status') == 'running' and recovered.get('agent_skills_version') != 'v2':
                        recovered['status'] = 'failed'
                        recovered['error'] = 'Interrupted: app restarted during execution'
                        # Persist to Lakebase so rerun endpoint also sees 'failed'
                        try:
                            run_store.update_run_status(run_id, 'failed',
                                                       error='Interrupted: app restarted during execution')
                        except Exception as persist_err:
                            logger.warning(f"Failed to persist zombie reset: {persist_err}")
                        logger.warning(f"Zombie run {run_id}: was 'running' in Lakebase but no active thread. Reset to failed.")
                    _runs[run_id] = recovered  # Re-populate cache
                    run = recovered
                    logger.info(f"Recovered run {run_id} from Lakebase (cache miss)")
            except Exception as e:
                logger.warning(f"Lakebase fallback failed for {run_id}: {e}")

    if not run:
        return jsonify({"error": "Run not found"}), 404

    if run.get('agent_skills_version') == 'v2' and (run_id not in _runners or run.get('persistence_warning')):
        try:
            from orchestrator.app_state import recover_snapshot
            store = _get_state_store()
            recovered = recover_snapshot(_get_services()['workspace'], store, store.get_run(run_id))
            if recovered:
                run.update(recovered)
                if not recovered.get('persistence_warning'):
                    run.pop('persistence_warning', None)
        except Exception as replay_error:
            logger.warning('App mirror replay pending: %s', replay_error)

    # Build step list with phases and tool_calls
    steps = []
    for step_name, step_info in run.get('step_data', {}).items():
        step_status = step_info.get('status', 'pending')
        phases = step_info.get('phases', [])
        # v2 parent completion is not evidence for each reported phase.
        if step_status == 'completed' and run.get('agent_skills_version') == 'v2':
            phases = [
                {**ph, 'status': 'unverified',
                 'current_task': 'Step ended without a phase completion event; checkpoint verification required.'}
                if ph.get('status') in ('started', 'update', 'running') else ph
                for ph in phases
            ]
        elif step_status == 'completed':
            phases = [
                {**ph, 'status': 'completed'} if ph.get('status') not in ('completed', 'failed') else ph
                for ph in phases
            ]
        # Normalize: if step FAILED, no phase should still show 'running'.
        # This happens when the app crashes mid-step — phases stay 'running'
        # in Lakebase but the step itself was marked 'failed' by zombie
        # detection. Without this, the UI shows all phases as "In Progress"
        # simultaneously, which looks like parallel execution.
        elif step_status == 'failed':
            phases = [
                {**ph, 'status': 'failed'} if ph.get('status') == 'running' else ph
                for ph in phases
            ]
        steps.append({
            "step_name": step_name,
            "status": step_status,
            "duration_s": step_info.get('duration_s'),
            "phases": phases,
            "tool_calls": step_info.get('tool_calls', []),
        })

    # Calculate elapsed time
    started_at = run.get('started_at')
    elapsed_s = None
    if started_at:
        from datetime import datetime, timezone
        try:
            if isinstance(started_at, str):
                start_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            else:
                start_dt = started_at
            elapsed_s = round((datetime.now(timezone.utc) - start_dt).total_seconds(), 1)
        except Exception:
            elapsed_s = None

    # Compute duration_s for terminal states
    duration_s = run.get('duration_s')
    if not duration_s and run.get('status') in ('completed', 'failed', 'cancelled'):
        # Compute from started_at/completed_at
        completed_at = run.get('completed_at')
        if started_at and completed_at:
            try:
                from datetime import datetime, timezone
                start_dt = datetime.fromisoformat(str(started_at).replace('Z', '+00:00')) if isinstance(started_at, str) else started_at
                end_dt = datetime.fromisoformat(str(completed_at).replace('Z', '+00:00')) if isinstance(completed_at, str) else completed_at
                duration_s = round((end_dt - start_dt).total_seconds(), 1)
            except Exception:
                pass
        elif elapsed_s:
            duration_s = elapsed_s

    return jsonify({
        "run_id": run_id,
        "status": run.get('status', 'unknown'),
        "progress_pct": run.get('progress_pct', 0),
        "current_step": run.get('current_step'),
        "elapsed_s": elapsed_s,
        "duration_s": duration_s,
        "started_at": started_at,
        "error": run.get('error'),
        "persistence_warning": run.get('persistence_warning'),
        "domain": run.get('domain'),
        "version": run.get('version'),
        "version_suffix": run.get('version_suffix', ''),
        "catalog": run.get('catalog', ''),
        "schema": run.get('schema', ''),
        "llm_model": run.get('llm_model', os.environ.get('LLM_ENDPOINT_NAME', 'databricks-gpt-5-5')),
        "vision_model": run.get('vision_model', os.environ.get('VISION_ENDPOINT_NAME', 'databricks-gpt-5-5')),
        "steps": steps,
    })


# ------------------------------------------------------------------
# Runs List & Rerun Endpoints
# ------------------------------------------------------------------

@pipeline_bp.route('/runs')
def list_runs():
    """List all pipeline runs — journal files are the source of truth,
    enriched by Lakebase when available.

    Query params:
        domain (str, optional): Filter by domain name.
        limit (int, optional): Max results (default 50).

    Returns:
        [{run_id, domain, status, version, started_at, duration_s, error}, ...]
    """
    domain = request.args.get('domain')
    limit = int(request.args.get('limit', 50))
    runs = []  # accumulator
    seen_run_ids = set()

    # ── 1. Try Lakebase first (fast, structured) ──
    run_store = _get_state_store()
    if run_store:
        try:
            lakebase_runs = run_store.list_runs(limit=limit, domain=domain)
            for r in lakebase_runs:
                rid = r.get('run_id')
                if rid:
                    seen_run_ids.add(rid)
                runs.append(r)
        except Exception as e:
            logger.warning(f"Lakebase list_runs failed (falling back to journals): {e}")

    # ── 2. Journal-file fallback — always runs ──
    # Reads app_runs/*.json from workspace.  Picks up runs that Lakebase
    # is missing (SafeStateStore swallowed errors, runs predate Lakebase,
    # or Lakebase is entirely unavailable).
    try:
        from config import get_config
        app_config = get_config()
        from databricks.sdk import WorkspaceClient as _WC2
        _w2 = _WC2()

        if domain:
            scan_domains = [domain]
        else:
            # No domain filter — scan all domain directories
            scan_domains = []
            try:
                kpi_root = f"{app_config.WORKSPACE_ROOT}/kpi_domains"
                for d_item in _w2.workspace.list(kpi_root):
                    if d_item.object_type and d_item.object_type.value == 'DIRECTORY':
                        dname = d_item.path.rsplit('/', 1)[-1]
                        scan_domains.append(dname)
            except Exception:
                pass

        for scan_domain in scan_domains:
            try:
                journal_dir = f"{app_config.WORKSPACE_ROOT}/kpi_domains/{scan_domain}/app_runs"
                for item in _w2.workspace.list(journal_dir):
                    if not item.path or not item.path.endswith('.json'):
                        continue
                    fname = item.path.rsplit('/', 1)[-1]
                    rid = fname.replace('.json', '')
                    if rid in seen_run_ids:
                        continue
                    try:
                        import json as _json2
                        with _w2.workspace.download(item.path) as _reader:
                            _jdata = _json2.loads(_reader.read().decode('utf-8'))
                        _ver = _jdata.get('version')
                        if isinstance(_ver, dict):
                            _ver = _ver.get('number', 0)
                        runs.append({
                            'run_id': rid,
                            'domain': _jdata.get('domain', scan_domain),
                            'status': _jdata.get('status', 'unknown'),
                            'version': _ver,
                            'current_step': _jdata.get('current_step'),
                            'started_at': _jdata.get('started_at'),
                            'duration_s': _jdata.get('duration_s'),
                            'error': str(_jdata.get('error', ''))[:200] if _jdata.get('error') else None,
                            'source': 'journal',
                        })
                        seen_run_ids.add(rid)
                    except Exception:
                        pass  # Skip unreadable journals
            except Exception:
                pass  # Domain has no app_runs dir — skip
    except Exception as _je:
        logger.debug(f"Journal fallback skipped: {_je}")

    # ── 3. Reconcile statuses ──
    # Reconcile with version_registry.yaml (source of truth for final status).
    registry_status = {}  # run_id -> status from registry
    if domain:
        try:
            import yaml as _yaml
            from config import get_config
            app_config = get_config()
            reg_path = f"{app_config.WORKSPACE_ROOT}/kpi_domains/{domain}/version_registry.yaml"
            from databricks.sdk import WorkspaceClient
            _w = WorkspaceClient()
            with _w.workspace.download(reg_path) as reader:
                reg = _yaml.safe_load(reader.read().decode('utf-8'))
            for v in (reg or {}).get('versions', []):
                rid = v.get('run_id')
                if rid:
                    registry_status[rid] = v.get('status', 'unknown')
        except Exception:
            pass  # Registry not available — fall through to zombie detection

    for r in runs:
        rid = r.get('run_id')
        # Normalize version: ensure it's always an int for the UI
        _v = r.get('version')
        if isinstance(_v, dict):
            r['version'] = _v.get('number', _v.get('version', 0))
        # Registry reconciliation: if registry says completed/failed, trust it
        if rid in registry_status:
            reg_st = registry_status[rid]
            if reg_st in ('completed', 'failed') and r.get('status') != reg_st:
                r['status'] = reg_st
                if reg_st == 'completed':
                    r.pop('error', None)  # Clear stale error message
                continue
        # Zombie detection: runs in Lakebase as 'running' but no active thread
        if r.get('status') == 'running' and rid not in _runs:
            r['status'] = 'failed'
            r['error'] = r.get('error') or 'Interrupted: app restarted during execution'

    # Sort by started_at descending, apply limit
    runs.sort(key=lambda r: r.get('started_at') or '', reverse=True)
    return jsonify(runs[:limit])


@pipeline_bp.route('/version-status')
def get_version_status():
    """Get the latest version status from version_registry.yaml.

    This is the authoritative source for version resolution.
    The frontend uses this to display the correct 'Resume vN' label.

    Query params:
        domain (str): Domain name (e.g. 'member_claims').

    Returns:
        {latest_version, status, created_by, is_resumable, label}
    """
    import yaml
    from config import get_config

    domain = request.args.get('domain')
    if not domain:
        return jsonify({'error': 'domain query param required'}), 400

    app_config = get_config()
    registry_path = f"{app_config.WORKSPACE_ROOT}/kpi_domains/{domain}/version_registry.yaml"

    try:
        from databricks.sdk import WorkspaceClient
        import io
        w = WorkspaceClient()
        resp = w.workspace.get_status(registry_path)
        with w.workspace.download(registry_path) as reader:
            content = reader.read().decode('utf-8')
        registry = yaml.safe_load(content)
    except Exception as e:
        # Registry doesn't exist yet → no versions
        return jsonify({
            'latest_version': 0,
            'status': 'none',
            'is_resumable': False,
            'label': 'v1 (first run)',
        })

    if not registry or not registry.get('versions'):
        return jsonify({
            'latest_version': 0,
            'status': 'none',
            'is_resumable': False,
            'label': 'v1 (first run)',
        })

    # Find the latest version entry
    versions = sorted(registry['versions'], key=lambda v: v.get('version', 0), reverse=True)
    latest = versions[0]
    version_num = latest.get('version', 0)
    status = latest.get('status', 'unknown')

    # Determine if resumable:
    # - 'running' with no active thread = interrupted/crashed (resumable)
    # - 'failed' = resumable via retry mode
    run_id = latest.get('run_id', '')
    is_zombie = (status == 'running' and run_id not in _runs)
    is_resumable = status in ('running', 'failed') or is_zombie

    # Build display label — show 'failed' for zombies so the user knows
    # they can click Resume to retry from the failed step
    if is_zombie:
        display_status = 'failed'
    else:
        display_status = status

    label = f"v{version_num} ({display_status})"

    return jsonify({
        'latest_version': version_num,
        'status': display_status,
        'is_resumable': is_resumable,
        'label': label,
        'run_id': run_id,
        'created_by': latest.get('created_by', ''),
    })


@pipeline_bp.route('/runs/<run_id>')
def get_run_detail(run_id):
    """Get full run detail including steps and phases (for run details page).

    Normalizes the steps array to include all 7 expected steps in order,
    including load_configuration which is not persisted to Lakebase.

    Returns:
        {run_id, domain, status, steps: [{step_name, status, phases: [...], ...}], ...}
    """
    run_store = _get_state_store()

    run = None
    if run_store:
        run = run_store.get_run(run_id)
    if not run:
        # Fall back to in-memory
        run = _runs.get(run_id)
        if not run:
            return jsonify({'error': {'type': 'NotFound', 'message': f'Run {run_id} not found'}}), 404

    # Normalize steps array to include all expected steps in order.
    # load_configuration is handled in-memory only (not persisted to Lakebase).
    STEP_ORDER = [
        "load_configuration", "environment_setup", "create_data_layer",
        "create_metric_views", "create_dashboards", "create_genie_space",
        "generate_documentation",
    ]
    raw_steps = run.get('steps', [])
    steps_by_name = {(s.get('step_name') or s.get('name')): s for s in raw_steps}

    # If any step ran, load_configuration must have completed first
    has_any_step = len(steps_by_name) > 0

    normalized = []
    for step_name in STEP_ORDER:
        if step_name in steps_by_name:
            entry = steps_by_name[step_name]
            entry['step_name'] = step_name
            if 'phases' not in entry:
                entry['phases'] = []
            normalized.append(entry)
        elif step_name == 'load_configuration' and has_any_step:
            normalized.append({'step_name': step_name, 'status': 'completed', 'phases': []})
        else:
            normalized.append({'step_name': step_name, 'status': 'pending', 'phases': []})

    run['steps'] = normalized
    return jsonify(run)


@pipeline_bp.route('/rerun/<run_id>', methods=['POST'])
def rerun_from_failure(run_id):
    """Rerun a failed pipeline from the failed step onward.

    Updates the SAME run record back to 'running' status and resumes
    from the first failed/pending step. Does NOT create a new run.

    Returns:
        {run_id, status: 'started', resume_from: step_name, steps: [...]}
    """
    run_store = _get_state_store()
    if not run_store:
        return jsonify({'error': {'type': 'ServiceUnavailable',
                                   'message': 'Lakebase not provisioned. Run Setup from Admin.'}}), 503

    # Get the original run
    original_run = run_store.get_run(run_id)
    if not original_run:
        return jsonify({'error': {'type': 'NotFound', 'message': f'Run {run_id} not found'}}), 404

    if original_run.get('agent_skills_version') == 'v2':
        from orchestrator.app_state import recover_snapshot
        try:
            recovered = recover_snapshot(_get_services()['workspace'], run_store, original_run)
            original_run = recovered or original_run
        except Exception as exc:
            return jsonify({'error': {'type': 'RecoveryError', 'message': str(exc)}}), 503
        is_active = run_id in _runners
        run_status = original_run.get('status')
        is_zombie_running = (run_status == 'running' and not is_active)
        if is_active or (run_status not in ('failed', 'cancelled') and not is_zombie_running):
            return jsonify({'error': {'type': 'ValidationError',
                'message': 'Retry requires a stopped, failed or cancelled App run. A cache miss does not prove the execution stopped.'}}), 409
        # If the run was a zombie (registry/Lakebase said "running" but no thread
        # is active), mark it as failed so the retry proceeds cleanly.
        if is_zombie_running:
            original_run['status'] = 'failed'
            try:
                run_store.update_run_status(run_id, 'failed',
                    error='Interrupted: no active execution thread (zombie recovery)')
            except Exception:
                pass  # Best-effort; the retry will proceed anyway
        if not original_run.get('version'):
            return jsonify({'error': {'type': 'RecoveryError',
                'message': 'No verified version locator was saved. Start a fresh master run; do not guess which version to retry.'}}), 409
        _runs[run_id] = {**original_run, 'status': 'started', 'error': None}
        _event_queues[run_id] = queue.Queue()
        thread = threading.Thread(target=_run_pipeline_background,
            args=(run_id, original_run['domain'], original_run.get('requested_steps'),
                  'versioned', original_run.get('version'),
                  request.headers.get('X-Forwarded-Access-Token', '')),
            kwargs={'version_mode': 'retry', 'agent_skills_version': 'v2'}, daemon=True)
        thread.start()
        return jsonify({'run_id': run_id, 'status': 'started',
                        'resume_from': 'master_checkpoint_validation'}), 202

    run_status = original_run.get('status')
    # Allow rerun if failed/cancelled, OR if 'running' but no active thread
    # (zombie: app restarted while a rerun was in progress, thread was killed)
    if run_status not in ('failed', 'cancelled'):
        if run_status == 'running' and run_id not in _runs:
            # Zombie run — no active thread, safe to re-trigger
            logger.warning(f"Zombie run detected: {run_id} status='running' but no active thread. Resetting to failed for rerun.")
            run_store.update_run_status(run_id, 'failed', error='Interrupted: app restarted during execution')
        else:
            return jsonify({'error': {'type': 'ValidationError',
                                       'message': 'Can only rerun failed or cancelled pipelines'}}), 400

    # Get steps to resume from
    resume_steps = run_store.get_resume_steps(run_id)
    if not resume_steps:
        return jsonify({'error': {'type': 'ValidationError',
                                   'message': 'No steps to resume'}}), 400

    # Get phase-level resume point (if phases were tracked)
    resume_point = run_store.get_resume_point(run_id)
    resume_from = None
    if resume_point:
        resume_step_name = resume_point.get("step_name", resume_steps[0])
        # Guard: ensure resume step is actually in the steps to run.
        # Phases from already-completed steps may have been reset to 'pending'
        # by a prior rerun, causing get_resume_point to return a step that
        # isn't in resume_steps. If that happens, fall back to the first
        # pending step and skip phase-level resume.
        if resume_step_name not in resume_steps:
            logger.warning(
                f"Resume point step '{resume_step_name}' not in resume_steps "
                f"{resume_steps}. Falling back to '{resume_steps[0]}'."
            )
            resume_step_name = resume_steps[0]
            resume_phase_name = None  # Can't resume at phase level for a different step
        else:
            resume_phase_name = resume_point.get("phase_name")
        resume_from = {
            "step_name": resume_step_name,
            "phase_name": resume_phase_name,
        }

    # Update the SAME run record back to running
    domain = original_run.get('domain')
    run_mode = original_run.get('run_mode', 'versioned')
    version_override = original_run.get('version')

    # Reset run status in Delta
    run_store.update_run_status(run_id, 'running', error='', current_step=resume_steps[0])
    # Reset failed/pending steps back to pending
    run_store.reset_steps_for_rerun(run_id, resume_steps)

    # Insert step records for any steps that were never reached in the
    # original run (they won't exist in the steps table). Without this,
    # the pipeline runner can't update their status via update_step.
    from services.run_store import STEP_ORDER
    existing_steps = {s.get('step_name') or s.get('name') for s in (original_run.get('steps') or [])}
    max_idx = max((s.get('step_index', 0) for s in (original_run.get('steps') or [])), default=-1)
    for step_name in resume_steps:
        if step_name not in existing_steps:
            max_idx += 1
            next_s = None
            try:
                si = STEP_ORDER.index(step_name)
                next_s = STEP_ORDER[si + 1] if si < len(STEP_ORDER) - 1 else None
            except ValueError:
                pass
            run_store.insert_step(run_id, step_name, max_idx, next_step=next_s)

    # Initialize in-memory run state (using same run_id, marked as rerun)
    completed_steps = []
    step_data = {}  # Pre-populate with completed step data from Delta
    if original_run.get('steps'):
        for s in original_run['steps']:
            sname = s.get('step_name') or s.get('name')
            if s.get('status') == 'completed':
                completed_steps.append(sname)
                # Preserve completed step info including phases from Delta.
                # Force all phases to 'completed' — the step itself is completed
                # so all its phases must also be completed (Lakebase may still
                # have stale 'running' status from the original execution).
                phases = []
                step_phases = run_store.get_phases_for_step(run_id, sname)
                for p in step_phases:
                    phases.append({
                        'phase_name': p.get('phase_name'),
                        'status': 'completed',
                        'duration_ms': p.get('duration_ms'),
                    })
                step_data[sname] = {
                    'step_name': sname,
                    'status': 'completed',
                    'duration_s': s.get('duration_s'),
                    'phases': phases,
                }

    _runs[run_id] = {
        'run_id': run_id,
        'domain': domain,
        'status': 'running',
        'run_mode': run_mode,
        'version_override': version_override,
        'current_step': None,
        'steps_completed': completed_steps,
        'step_data': step_data,
        'logs': [],
        'step_logs': {},
        'progress_pct': 0,
        'started_at': original_run.get('started_at', datetime.utcnow().isoformat()),
        'error': None,
        'duration_s': None,
        'resume_step': resume_steps[0],
        'is_rerun': True,
    }

    # Create SSE queue
    _event_queues[run_id] = queue.Queue()

    # Get user token
    user_token = request.headers.get('X-Forwarded-Access-Token', '')

    # Start background execution with the remaining steps (same run_id)
    # version_mode='retry' tells the resolver to resume the failed version
    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(run_id, domain, resume_steps, run_mode, version_override, user_token),
        kwargs={'resume_from': resume_from, 'version_mode': 'retry'},
        daemon=True
    )
    thread.start()

    logger.info(f"Pipeline rerun started: run_id={run_id}, resume_from={resume_from or resume_steps[0]}")

    return jsonify({
        'run_id': run_id,
        'status': 'started',
        'resume_step': resume_steps[0],
        'resume_phase': resume_from.get('phase_name') if resume_from else None,
        'steps': resume_steps,
    }), 202


@pipeline_bp.route('/api/pipeline/logs/<run_id>/<step_name>', methods=['GET'])
def get_step_logs(run_id, step_name):
    """Get logs for a specific step in a pipeline run.

    Returns recent log lines filtered to the step name.
    """
    import os
    logs = []

    # Try to read from the Lakebase state store
    try:
        store = _get_state_store()
        run_data = store.get_run(run_id) if store else None
        if run_data:
            step_logs = run_data.get('step_logs', {}).get(step_name, '')
            if step_logs:
                return jsonify({'logs': step_logs, 'step': step_name})
    except Exception:
        pass

    # Fallback: read from the app log file filtered by step name
    try:
        log_path = os.environ.get('APP_LOG_FILE', '/tmp/app.log')
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                # Read last 500 lines
                all_lines = f.readlines()[-500:]
            # Filter lines related to this step or run
            step_keywords = [step_name, run_id[:12]]
            for line in all_lines:
                if any(kw in line for kw in step_keywords):
                    logs.append(line.rstrip())
            # Keep last 50 relevant lines
            logs = logs[-50:]
    except Exception:
        pass

    return jsonify({'logs': '\n'.join(logs) if logs else f'No logs available for {step_name}.', 'step': step_name})


@pipeline_bp.route('/cleanup', methods=['POST'])
def cleanup_version():
    """Remove all assets for one or more domain versions.

    Removes: schema tables with version suffix, output folder,
    dashboards, genie space, and run records.

    Request JSON (supports two formats):
        Format 1 (single version - legacy):
            domain (str): Domain name (e.g. 'member_claims')
            version_suffix (str): Version suffix (e.g. '_v5')

        Format 2 (multi-version, from Admin UI):
            domain (str): Domain name
            versions_to_clean (str): "3" or "1,2,3" or "all"

    Returns:
        {status: 'completed', domain, versions_cleaned: [...], results: [...]}
    """
    data = request.get_json(force=True)
    domain = data.get('domain')
    version_suffix = data.get('version_suffix', '')
    versions_to_clean = data.get('versions_to_clean', '')

    if not domain:
        return jsonify({'error': 'domain is required'}), 400
    if not version_suffix and not versions_to_clean:
        return jsonify({'error': 'version_suffix or versions_to_clean is required'}), 400

    from config import get_config
    from services.cleanup_service import CleanupService

    app_config = get_config()
    workspace_root = app_config.WORKSPACE_ROOT
    warehouse_id = app_config.SQL_WAREHOUSE_ID

    service = CleanupService(workspace_root=workspace_root, warehouse_id=warehouse_id)
    run_store = _get_state_store()

    # Resolve version suffixes to process
    suffixes_to_clean = []
    if versions_to_clean:
        if versions_to_clean.strip().lower() == 'all':
            # Discover all versions from the version registry or runs
            try:
                domain_root = f"{workspace_root}/kpi_domains/{domain}"
                import yaml
                registry_path = f"{domain_root}/version_registry.yaml"
                from services.workspace_service import WorkspaceService
                ws = WorkspaceService()
                registry_content = ws.read_file(registry_path)
                if registry_content:
                    registry = yaml.safe_load(registry_content)
                    for entry in registry.get('versions', []):
                        v = entry.get('version')
                        if v:
                            suffixes_to_clean.append(f"_v{v}")
            except Exception as e:
                logger.warning(f"Could not read version registry for 'all': {e}")
                # Fallback: try to discover from runs
                if run_store:
                    try:
                        runs = run_store.list_runs(domain=domain, limit=100)
                        versions_seen = set()
                        for r in runs:
                            vs = r.get('version_suffix') or r.get('version')
                            if vs:
                                suffix = vs if vs.startswith('_v') else f"_v{vs}"
                                versions_seen.add(suffix)
                        suffixes_to_clean = sorted(versions_seen)
                    except Exception:
                        pass
        else:
            # Parse comma-separated version numbers
            for part in versions_to_clean.split(','):
                part = part.strip()
                if part.isdigit():
                    suffixes_to_clean.append(f"_v{part}")
    else:
        suffixes_to_clean = [version_suffix]

    if not suffixes_to_clean:
        return jsonify({'error': 'No versions resolved. Check domain has existing versions.'}), 400

    # Run cleanup for each version suffix
    all_results = []
    for suffix in suffixes_to_clean:
        try:
            result = service.run_cleanup(domain=domain, version_suffix=suffix, run_store=run_store)
            all_results.append({'version_suffix': suffix, 'status': 'completed', **result})
        except Exception as e:
            all_results.append({'version_suffix': suffix, 'status': 'failed', 'error': str(e)[:200]})

    logger.info(f"Cleanup API completed for {domain} versions={suffixes_to_clean}: {len(all_results)} processed")
    return jsonify({
        'status': 'completed',
        'domain': domain,
        'versions_cleaned': suffixes_to_clean,
        'results': all_results,
    })


@pipeline_bp.route('/runs', methods=['DELETE'])
def purge_all_runs():
    """Purge ALL pipeline run records from Lakebase.

    Used from the Admin page to reset pipeline history after cleanup.
    Does NOT delete generated assets (tables, folders) — use /cleanup for that.

    Returns:
        {status: 'purged', count: <number of runs removed>}
    """
    run_store = _get_state_store()
    if not run_store:
        return jsonify({'error': 'Lakebase not available'}), 503

    try:
        count = run_store.purge_all_runs()
        logger.info(f"Purged {count} run records via Admin API")
        return jsonify({'status': 'purged', 'count': count})
    except Exception as e:
        logger.error(f"purge_all_runs failed: {e}")
        return jsonify({'error': str(e)[:200]}), 500
