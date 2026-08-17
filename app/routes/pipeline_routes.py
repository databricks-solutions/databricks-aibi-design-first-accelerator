"""Pipeline execution routes for AI/BI Studio.

Handles pipeline run, status polling, cancellation, and SSE streaming.
See docs/design_phase2.md Section 5.1.
"""

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
        "workspace": WorkspaceService(),  # SP auth (CAN_MANAGE on project folder)
        "sql": SQLService(warehouse_id=warehouse_id),
        "lakeview": LakeviewService(),    # SP auth
        "genie": GenieService(),          # SP auth
        "jobs": JobsService(warehouse_id=warehouse_id),
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
        # Validate cached connection is still alive (detects stale endpoint after Lakebase recreation)
        if _state_store.health_check():
            return _state_store
        logger.warning("StateStore health check failed — re-discovering endpoint...")
        _state_store = None
        _state_store_checked_at = 0.0

    # Don't retry discovery more often than every 30s
    now = time.time()
    if now - _state_store_checked_at < _STATE_STORE_RETRY_INTERVAL:
        return None
    _state_store_checked_at = now

    import os
    from services.state_store import StateStore
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

    _state_store = StateStore(endpoint_host, "databricks_postgres", _get_username, _get_token)
    logger.info(f"StateStore initialized: {endpoint_host} (project={project_id}, direct pg8000)")

    return _state_store


def _run_pipeline_background(run_id: str, domain: str, steps: list, run_mode: str,
                              version_override, user_token: str = "",
                              resume_from: dict = None):
    """Background thread: loads config, runs pipeline, updates _runs state.

    Args:
        resume_from: Optional dict {"step_name": str, "phase_name": str} for
                     phase-level resume on rerun. Passed through to PipelineRunner.run().
    """
    import os
    import traceback
    from orchestrator.config_loader import ConfigLoader, ConfigError
    from orchestrator.pipeline import PipelineRunner
    from orchestrator.version_resolver import VersionResolver
    from services.state_store import StateStore

    run = _runs[run_id]

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
                # Find existing phase entry or create new
                existing = next((p for p in phases if p.get('phase_name') == phase), None)
                if existing:
                    existing['status'] = phase_status
                    if duration_ms is not None:
                        existing['duration_ms'] = duration_ms
                else:
                    phases.append({'phase_name': phase, 'status': phase_status, 'duration_ms': duration_ms})
                run['step_data'][step]['phases'] = phases
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
            'step_name': 'load_configuration', 'status': 'running', 'duration_s': None, 'phases': []
        }
        q = _event_queues.get(run_id)
        if q:
            q.put({"type": "step_started", "step": "load_configuration",
                   "index": 0, "total": 7, "timestamp": datetime.utcnow().isoformat()})

        # Initialize services with user's token for workspace writes
        services = _get_services(user_token=user_token or None)
        llm_client = _get_llm_client()

        # Initialize state store (Lakebase Data API)
        run_store = _get_state_store()
        if not run_store:
            run['status'] = 'failed'
            run['error'] = 'Lakebase not provisioned. Run Setup Infrastructure from Admin page.'
            q = _event_queues.get(run_id)
            if q:
                q.put({"type": "pipeline_completed", "status": "failed",
                       "error": run['error'], "timestamp": datetime.utcnow().isoformat()})
            return

        # Load config per master prompt Step 0:
        # - Read accelerator.yaml from EXAMPLE_DIR
        # - Read databricks.yml for sql_warehouse_id
        # - Resolve output folder, name suffix, paths
        from config import get_config
        app_config = get_config()
        local_root = app_config.LOCAL_ROOT
        workspace_root = app_config.WORKSPACE_ROOT
        warehouse_id = app_config.SQL_WAREHOUSE_ID
        loader = ConfigLoader(services["workspace"])
        config = loader.load(domain, local_root, warehouse_id,
                             workspace_root=workspace_root)

        # Handle versioning
        config.run_mode = run_mode
        if run_mode == 'versioned':
            resolver = VersionResolver(services["workspace"], services["sql"],
                                       services["lakeview"], services["genie"])
            version_info = resolver.resolve(config, override=version_override)
            config.version = version_info.version
            config.version_suffix = version_info.suffix
            # Output folder: output/v1/, output/v2/ etc.
            config.output_folder = config.output_folder + f"/v{version_info.version}"
            # Use a single schema per domain: aibi_{domain}
            # SP creates this schema at runtime → SP is owner → no grants needed.
            # Tables within get the version suffix (e.g. members_v1, claims_v1).
            catalog_name = config.catalog.source.split(".")[0] if config.catalog.source else ""
            domain_schema = f"{catalog_name}.aibi_{domain}"
            config.catalog.source = domain_schema
            config.catalog.target = domain_schema
            # Point live_schema to the domain schema (metric view profiler)
            domain_schema_name = f"aibi_{domain}"
            if config.data_source.live_schema:
                config.data_source.live_schema['schema'] = domain_schema_name
            if config.data_source.live_schemas:
                for ls in config.data_source.live_schemas:
                    ls['schema'] = domain_schema_name
            # Append version suffix to all asset names
            suffix = version_info.suffix  # "_v1", "_v2", etc.
            if config.assets.metric_view:
                config.assets.metric_view = config.assets.metric_view + suffix
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
            run['version'] = version_info.version
            run['version_suffix'] = version_info.suffix

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

        # Set clean_start based on run_mode
        config.pipeline.clean_start = (run_mode == 'clean')

        # ── Step 0 complete ──
        config_duration = round(time.time() - config_start, 1)
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

        # Pass run_id so PipelineRunner reuses it (critical for phase-level resume
        # to match phase records already in pipeline_run_phases table)
        pipeline_run = runner.run(domain=domain, steps=steps, callback=event_callback,
                                   resume_from=resume_from, run_id=run_id)

        # Final state
        run['status'] = pipeline_run.status.value
        run['duration_s'] = pipeline_run.duration_s
        run['error'] = pipeline_run.error
        run['completed_at'] = pipeline_run.completed_at

    except Exception as e:
        logger.exception(f"Pipeline background execution failed: {e}")
        run['status'] = 'failed'
        run['error'] = str(e)
        # Notify SSE
        q = _event_queues.get(run_id)
        if q:
            q.put({"type": "pipeline_completed", "status": "failed",
                   "error": str(e), "timestamp": datetime.utcnow().isoformat()})
    finally:
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

    run_id = str(uuid.uuid4())
    steps = data.get('steps')  # None means all enabled steps

    # Initialize run state
    _runs[run_id] = {
        'run_id': run_id,
        'domain': domain,
        'status': 'started',
        'run_mode': run_mode,
        'version_override': version_override,
        'current_step': None,
        'steps_completed': [],
        'step_data': {},
        'logs': [],
        'step_logs': {},
        'progress_pct': 0,
        'started_at': datetime.utcnow().isoformat(),
        'error': None,
        'duration_s': None,
    }

    # Create SSE event queue for this run
    _event_queues[run_id] = queue.Queue()

    # Capture user's OAuth token for workspace API calls in background thread
    user_token = request.headers.get('X-Forwarded-Access-Token', '')

    # Start background execution
    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(run_id, domain, steps, run_mode, version_override, user_token),
        daemon=True
    )
    thread.start()

    logger.info(f"Pipeline started: run_id={run_id}, domain={domain}, mode={run_mode}")
    return jsonify({'run_id': run_id, 'status': 'started', 'run_mode': run_mode}), 202


@pipeline_bp.route('/status/<run_id>')
def get_status(run_id):
    """Get current pipeline execution status with structured steps array.

    Returns:
        {run_id, status, current_step, steps: [{step_name, status, duration_s, phases}], ...}
    """
    run = _runs.get(run_id)
    if not run:
        return jsonify({'error': {'type': 'NotFound', 'message': f'Run {run_id} not found'}}), 404

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
    """Request cancellation of a running pipeline."""
    run = _runs.get(run_id)
    if not run:
        return jsonify({'error': {'type': 'NotFound', 'message': f'Run {run_id} not found'}}), 404

    run['status'] = 'cancelling'
    runner = _runners.get(run_id)
    if runner:
        runner.cancel()

    logger.info(f"Pipeline cancel requested: run_id={run_id}")
    return jsonify({'run_id': run_id, 'status': 'cancelling'})


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

        # Stream events from queue
        while True:
            try:
                event = q.get(timeout=30)  # 30s heartbeat timeout
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
# Runs List & Rerun Endpoints
# ------------------------------------------------------------------

@pipeline_bp.route('/runs')
def list_runs():
    """List all pipeline runs from Lakebase (for dashboard).

    Query params:
        domain (str, optional): Filter by domain name.
        limit (int, optional): Max results (default 50).

    Returns:
        [{run_id, domain, status, version, started_at, duration_s, error}, ...]
    """
    run_store = _get_state_store()
    if not run_store:
        return jsonify([])  # No state store yet — return empty list

    domain = request.args.get('domain')
    limit = int(request.args.get('limit', 50))

    try:
        runs = run_store.list_runs(limit=limit, domain=domain)
        return jsonify(runs)
    except Exception as e:
        logger.warning(f"list_runs failed: {e}")
        return jsonify([])  # Return empty list on DB error (table may not exist yet)


@pipeline_bp.route('/runs/<run_id>')
def get_run_detail(run_id):
    """Get full run detail including steps and phases (for run details page).

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

    if original_run.get('status') != 'failed':
        return jsonify({'error': {'type': 'ValidationError',
                                   'message': 'Can only rerun failed pipelines'}}), 400

    # Get steps to resume from
    resume_steps = run_store.get_resume_steps(run_id)
    if not resume_steps:
        return jsonify({'error': {'type': 'ValidationError',
                                   'message': 'No steps to resume'}}), 400

    # Get phase-level resume point (if phases were tracked)
    resume_point = run_store.get_resume_point(run_id)
    resume_from = None
    if resume_point:
        resume_from = {
            "step_name": resume_point.get("step_name", resume_steps[0]),
            "phase_name": resume_point.get("phase_name"),
        }

    # Update the SAME run record back to running
    domain = original_run.get('domain')
    run_mode = original_run.get('run_mode', 'versioned')
    version_override = original_run.get('version')

    # Reset run status in Delta
    run_store.update_run_status(run_id, 'running', error='', error_detail='', current_step=resume_steps[0])
    # Reset failed/pending steps back to pending
    run_store.reset_steps_for_rerun(run_id, resume_steps)

    # Initialize in-memory run state (using same run_id, marked as rerun)
    completed_steps = []
    step_data = {}  # Pre-populate with completed step data from Delta
    if original_run.get('steps'):
        for s in original_run['steps']:
            sname = s.get('step_name') or s.get('name')
            if s.get('status') == 'completed':
                completed_steps.append(sname)
                # Preserve completed step info including phases from Delta
                phases = []
                step_phases = run_store.get_phases_for_step(run_id, sname)
                for p in step_phases:
                    phases.append({
                        'phase_name': p.get('phase_name'),
                        'status': p.get('status', 'completed'),
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
    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(run_id, domain, resume_steps, run_mode, version_override, user_token),
        kwargs={'resume_from': resume_from},
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
    """Delete all assets for a specific domain version.

    Removes: schema tables with version suffix, output folder,
    dashboards, genie space, and run records.

    Request JSON:
        domain (str): Domain name (e.g. 'member_claims')
        version_suffix (str): Version suffix (e.g. '_v5')

    Returns:
        {status: 'completed', cleaned: {tables, folder, dashboards, genie, runs}}
    """
    data = request.get_json(force=True)
    domain = data.get('domain')
    version_suffix = data.get('version_suffix', '')

    if not domain:
        return jsonify({'error': 'domain is required'}), 400
    if not version_suffix:
        return jsonify({'error': 'version_suffix is required'}), 400

    from config import get_config
    from services.cleanup_service import CleanupService

    app_config = get_config()
    workspace_root = app_config.WORKSPACE_ROOT
    warehouse_id = app_config.SQL_WAREHOUSE_ID

    service = CleanupService(workspace_root=workspace_root, warehouse_id=warehouse_id)
    run_store = _get_state_store()

    result = service.run_cleanup(domain=domain, version_suffix=version_suffix, run_store=run_store)

    logger.info(f"Cleanup API completed for {domain}{version_suffix}: {result}")
    return jsonify({
        'status': 'completed',
        'domain': domain,
        'version_suffix': version_suffix,
        **result,
    })
