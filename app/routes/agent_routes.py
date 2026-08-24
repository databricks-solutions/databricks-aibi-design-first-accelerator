"""Agent Mode routes - SSE-based pipeline execution monitor.

Provides the Agent Mode UI that executes the same framework prompts
as Genie Code, with real-time streaming of step progress, tool calls,
and artifact generation.
"""

import json
import logging
import threading
import uuid
from flask import Blueprint, render_template, request, Response, jsonify, stream_with_context

logger = logging.getLogger(__name__)

agent_bp = Blueprint('agent', __name__)

# In-memory fallback + Lakebase persistence
_active_runs = {}  # In-memory for SSE streaming
_lakebase_store = None  # Initialized lazily
_lakebase_attempted = False  # Don't retry if init failed


def _get_store():
    """Get or create LakebaseStore (lazy init). Returns None if unavailable."""
    global _lakebase_store, _lakebase_attempted
    if _lakebase_store is None and not _lakebase_attempted:
        _lakebase_attempted = True
        try:
            import os
            dsn = os.environ.get('LAKEBASE_CONNECTION_STRING', '')
            if not dsn:
                logger.info("LakebaseStore: LAKEBASE_CONNECTION_STRING not set, skipping")
                return None
            from services.lakebase_store import LakebaseStore
            _lakebase_store = LakebaseStore(dsn)
            logger.info("LakebaseStore initialized for Agent Mode")
        except Exception as e:
            logger.warning(f"LakebaseStore not available, using in-memory only: {e}")
    return _lakebase_store


@agent_bp.route('/agent')
def agent_page():
    """Render the Agent Mode page."""
    return render_template('agent.html', active_page='agent')


@agent_bp.route('/api/agent/start', methods=['POST'])
def start_agent_run():
    """Start an agent pipeline run.

    Body: {"domain": "member_claims", "steps": ["all"] or ["create_dashboards"]}
    Returns: {"run_id": "..."}
    """
    from config import Config
    from llm.client import LLMClient
    from llm.tool_executor import ToolExecutor
    from llm.agent_loop import AgentLoop
    from llm.prompt_loader import PromptLoader
    from orchestrator.agent_step import (
        DataLayerAgentStep, MetricViewAgentStep,
        DashboardAgentStep, GenieSpaceAgentStep,
    )

    data = request.get_json()
    domain = data.get('domain', '')
    steps = data.get('steps', ['all'])

    if not domain:
        return jsonify({"error": "domain is required"}), 400

    run_id = str(uuid.uuid4())
    _active_runs[run_id] = {
        "status": "running",
        "domain": domain,
        "events": [],
        "current_step": None,
    }

    # Start pipeline in background thread
    thread = threading.Thread(
        target=_run_agent_pipeline,
        args=(run_id, domain, steps),
        daemon=True,
    )
    thread.start()

    return jsonify({"run_id": run_id})


@agent_bp.route('/api/agent/stream/<run_id>')
def stream_events(run_id):
    """SSE endpoint for real-time agent progress."""
    import time as _time

    logger.info(f"SSE stream requested for run_id={run_id}")
    logger.info(f"Active runs: {list(_active_runs.keys())}")

    def generate():
        last_index = 0
        logger.info(f"SSE generator started for run_id={run_id}")

        while True:
            run = _active_runs.get(run_id)
            if not run:
                logger.error(f"SSE: run {run_id} not found in _active_runs")
                yield f"data: {json.dumps({'type': 'error', 'message': 'Run not found'})}\n\n"
                break

            # Send new events
            events = run["events"]
            while last_index < len(events):
                evt = events[last_index]
                try:
                    msg = json.dumps(evt, default=str)
                    yield f"data: {msg}\n\n"
                    logger.debug(f"SSE sent event #{last_index}: {evt.get('type', '?')}")
                except Exception as e:
                    logger.error(f"SSE serialization error: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                last_index += 1

            # Check if done
            if run["status"] in ("completed", "failed"):
                logger.info(f"SSE: run {run_id} finished with status={run['status']}")
                yield f"data: {json.dumps({'type': 'pipeline_done', 'status': run['status']})}\n\n"
                break

            _time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@agent_bp.route('/api/agent/poll/<run_id>')
def poll_events(run_id):
    """Polling fallback for environments where SSE doesn't work (e.g. buffering proxies).

    Query params:
        after: event index to start from (default 0)
    Returns: {events: [...], next_index: N, status: 'running'|'completed'|'failed'}
    """
    after = int(request.args.get('after', 0))
    run = _active_runs.get(run_id)
    if not run:
        return jsonify({"error": "Run not found", "status": "not_found"}), 404

    events = run["events"][after:after + 50]  # Max 50 events per poll
    next_index = after + len(events)

    result = {
        "events": events,
        "next_index": next_index,
        "status": run["status"],
    }
    # If done, append the final event
    if run["status"] in ("completed", "failed") and next_index >= len(run["events"]):
        result["done"] = True

    return jsonify(result)


@agent_bp.route('/api/agent/history')
def run_history():
    """Get past agent runs from Lakebase."""
    domain = request.args.get('domain')
    store = _get_store()
    if store:
        runs = store.list_runs(domain=domain, limit=20)
        return jsonify({"runs": runs})
    return jsonify({"runs": []})


@agent_bp.route('/api/agent/run/<run_id>')
def get_run_detail(run_id):
    """Get a single run with steps and events."""
    store = _get_store()
    if store:
        run = store.get_run(run_id)
        if run:
            # Also get events for timeline reconstruction
            events = store.get_events_since(run_id, after_id=0, limit=500)
            run['events'] = events
            return jsonify(run)
    return jsonify({"error": "Run not found"}), 404


@agent_bp.route('/api/agent/domains')
def list_domains():
    """List available KPI domains for the agent."""
    from config import Config
    cfg = Config()

    # Discover domains from kpi_domains/ directory
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.workspace import ObjectType
    w = WorkspaceClient()

    domains = []
    domains_root = f"{cfg.WORKSPACE_ROOT}/kpi_domains"
    try:
        for entry in w.workspace.list(domains_root):
            if entry.object_type == ObjectType.DIRECTORY:
                name = entry.path.rstrip('/').split('/')[-1]
                # Skip hidden/internal directories
                if not name.startswith('.'):
                    domains.append({
                        "name": name,
                        "path": entry.path,
                    })
    except Exception as e:
        logger.warning(f"Could not list domains from {domains_root}: {e}")

    return jsonify({"domains": domains})


# ---------------------------------------------------------------------------
# Background pipeline execution
# ---------------------------------------------------------------------------

def _run_agent_pipeline(run_id: str, domain: str, steps: list):
    """Execute the agent pipeline in a background thread."""
    from config import Config
    from services.workspace_io import WorkspaceService
    from services.sql_client import SQLService
    from services.lakeview_client import LakeviewService
    from services.genie_client import GenieService
    from llm.client import LLMClient
    from llm.tool_executor import ToolExecutor
    from llm.agent_loop import AgentLoop
    from llm.prompt_loader import PromptLoader
    from orchestrator.config_loader import ConfigLoader

    run = _active_runs[run_id]
    store = _get_store()
    current_step_name = [None]  # mutable for closure

    # Persist run creation to Lakebase
    if store:
        try:
            store.create_run(run_id, domain, total_steps=4)
        except Exception as e:
            logger.warning(f"Lakebase create_run failed: {e}")

    def emit(event_type, data=None):
        payload = {"type": event_type, **(data or {})}
        run["events"].append(payload)
        logger.debug(f"Agent event: {event_type} - {str(data)[:200]}")
        # Also persist to Lakebase for history
        if store:
            try:
                store.log_event(run_id, current_step_name[0] or '', event_type, data or {})
            except Exception:
                pass  # Don't block pipeline on persistence failures

    # Emit immediately so SSE confirms thread is alive
    emit("init", {"message": f"Starting agent pipeline for domain: {domain}..."})

    try:
        cfg = Config()
        emit("init", {"message": f"Configuration loaded. Initializing services..."})

        # Load domain config
        ws = WorkspaceService()
        config_loader = ConfigLoader(ws)
        accel_config = config_loader.load(
            domain=domain,
            deploy_root=cfg.WORKSPACE_ROOT,
            sql_warehouse_id=cfg.SQL_WAREHOUSE_ID,
            workspace_root=cfg.WORKSPACE_ROOT,
        )

        # Initialize services (including jobs for execute_notebook tool)
        from services.jobs_client import JobsService
        services = {
            "workspace": WorkspaceService(),
            "sql": SQLService(warehouse_id=cfg.SQL_WAREHOUSE_ID),
            "lakeview": LakeviewService(),
            "genie": GenieService(),
            "jobs": JobsService(warehouse_id=cfg.SQL_WAREHOUSE_ID),
        }

        # Initialize LLM
        llm = LLMClient(
            endpoint_name=cfg.LLM_ENDPOINT_NAME,
            vision_endpoint_name=cfg.VISION_ENDPOINT_NAME,
        )

        # Build agent components
        tool_executor = ToolExecutor(accel_config, services, llm_client=llm)
        prompt_loader = PromptLoader(services["workspace"], accel_config.framework_root)
        agent = AgentLoop(llm, tool_executor, accel_config)

        # Determine which steps to run
        all_steps = [
            ("create_data_layer", "Data Layer"),
            ("create_metric_views", "Metric Views"),
            ("create_dashboards", "Dashboards"),
            ("create_genie_space", "Genie Space"),
        ]

        if steps != ["all"]:
            all_steps = [(s, l) for s, l in all_steps if s in steps]

        emit("pipeline_started", {
            "total_steps": len(all_steps),
            "steps": [s[1] for s in all_steps],
        })

        # Execute each step
        for i, (step_name, step_label) in enumerate(all_steps):
            run["current_step"] = step_name
            current_step_name[0] = step_name

            # Persist step start to Lakebase
            if store:
                try:
                    store.create_step(run_id, step_name, i)
                    store.update_step(run_id, step_name, 'running')
                    store.update_run(run_id, 'running', current_step=step_name)
                except Exception:
                    pass

            emit("step_started", {
                "step_index": i,
                "step_name": step_name,
                "step_label": step_label,
            })

            # Load prompt
            emit("init", {"message": f"Loading prompt for {step_label}..."})
            prompt_content = prompt_loader.load_step_prompt(step_name)
            supplements = prompt_loader.load_supplements(step_name)
            context_vars = prompt_loader.build_context_vars(accel_config)
            emit("init", {"message": f"Prompt loaded ({len(prompt_content)} chars). Calling LLM..."})

            # Progress callback
            def step_callback(event_type, data=None):
                emit(event_type, {"step_name": step_name, **(data or {})})

            # Run agent loop
            result = agent.run(
                prompt_content=prompt_content,
                context_vars=context_vars,
                system_supplement=supplements,
                callback=step_callback,
            )

            if result.success:
                emit("step_completed", {
                    "step_index": i,
                    "step_name": step_name,
                    "step_label": step_label,
                    "summary": result.summary,
                    "artifacts": result.artifacts,
                    "iterations": result.iterations,
                    "tool_calls": result.tool_calls_made,
                })
                # Persist step completion to Lakebase
                if store:
                    try:
                        store.update_step(
                            run_id, step_name, 'completed',
                            iterations=result.iterations,
                            tool_calls=result.tool_calls_made,
                            summary=result.summary,
                            artifacts=result.artifacts,
                        )
                        store.update_run(run_id, 'running', steps_completed=i + 1)
                    except Exception:
                        pass
            else:
                error_msg = result.error or result.summary or 'Step failed (no details provided)'
                emit("step_failed", {
                    "step_index": i,
                    "step_name": step_name,
                    "step_label": step_label,
                    "error": error_msg,
                })
                if store:
                    try:
                        store.update_step(run_id, step_name, 'failed', error=error_msg)
                        store.update_run(run_id, 'failed', error=error_msg)
                    except Exception:
                        pass
                run["status"] = "failed"
                return

        # Pipeline complete - persist run_manifest.json to Lakebase
        run["status"] = "completed"
        if store:
            try:
                # Read the generated run_manifest.json from workspace
                manifest_path = f"{accel_config.output_folder}/run_manifest.json"
                manifest_content = services["workspace"].read_file(manifest_path)
                if manifest_content:
                    manifest = json.loads(manifest_content)
                    store.save_run_manifest(run_id, manifest)
                store.update_run(run_id, 'completed', steps_completed=len(all_steps))
            except Exception as e:
                logger.warning(f"Failed to persist run_manifest: {e}")
                store.update_run(run_id, 'completed', steps_completed=len(all_steps))

        emit("pipeline_completed", {"message": "All steps completed successfully."})

    except Exception as e:
        logger.error(f"Agent pipeline failed: {e}", exc_info=True)
        emit("pipeline_error", {"error": str(e)})
        run["status"] = "failed"
