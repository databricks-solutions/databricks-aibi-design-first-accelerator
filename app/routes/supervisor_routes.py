"""Supervisor Agent Routes — Flask Blueprint for the supervisor pipeline.

Endpoints:
    POST /api/supervisor/run       - Start a new pipeline run
    GET  /api/supervisor/poll/<id>  - Poll for events
    POST /api/supervisor/cancel/<id> - Cancel a running pipeline
    GET  /supervisor/run/<id>       - Render the pipeline monitor UI
"""

import json
import logging
import threading
import time
import uuid
from collections import defaultdict

from flask import Blueprint, request, jsonify, render_template

logger = logging.getLogger(__name__)

supervisor_bp = Blueprint('supervisor', __name__)

# In-memory store for active runs (single-worker deployment)
_active_runs: dict = {}  # run_id -> RunState


class RunState:
    """Holds the state of a supervisor pipeline run."""

    def __init__(self, run_id: str, domain: str, config: dict):
        self.run_id = run_id
        self.domain = domain
        self.config = config
        self.events: list = []  # [{type, data, timestamp}]
        self.status = "running"  # running | completed | failed | cancelled
        self.result = None
        self.lock = threading.Lock()

    def add_event(self, event_type: str, data: dict):
        with self.lock:
            self.events.append({
                "type": event_type,
                "data": data,
                "timestamp": time.time(),
            })

    def get_events_after(self, index: int) -> list:
        with self.lock:
            return self.events[index:]


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _detect_version(ws, domain_path):
    """Detect current version from run_manifest.json in the output_subpath.

    Reads accelerator.yaml -> workspace.output_subpath for the output base path.
    Then reads run_manifest.json for the authoritative version number.
    Returns dict with current_version, next_version, output_subpath.
    """
    version_info = {
        'current_version': 0,
        'next_version': 1,
        'label': 'v1 (first run)',
        'previous_runs': 0,
        'output_subpath': 'generated_outputs',
    }

    # Read output_subpath from accelerator.yaml
    try:
        import yaml
        accel_content = ws.read_file(f"{domain_path}/accelerator.yaml")
        if accel_content:
            accel = yaml.safe_load(accel_content)
            ws_block = accel.get('workspace', {})
            version_info['output_subpath'] = ws_block.get('output_subpath', 'generated_outputs')
    except Exception:
        pass

    output_base = f"{domain_path}/{version_info['output_subpath']}"

    # Read run_manifest.json (authoritative version source)
    manifest_path = f"{output_base}/run_manifest.json"
    try:
        content = ws.read_file(manifest_path)
        if content:
            manifest = json.loads(content)
            current = manifest.get('version', manifest.get('run_number', 0))
            if isinstance(current, int) and current > 0:
                version_info['current_version'] = current
                version_info['next_version'] = current + 1
                version_info['label'] = f'v{current + 1}'
                version_info['previous_runs'] = current
                return version_info
    except Exception:
        pass

    # Scan output_subpath/ for v{N} folders
    try:
        entries = ws.list_dir(output_base)
        max_version = 0
        for entry in entries:
            name = entry.split('/')[-1] if '/' in str(entry) else str(entry)
            if hasattr(entry, 'path'):
                name = entry.path.split('/')[-1]
            if name.startswith('v') and name[1:].isdigit():
                v = int(name[1:])
                if v > max_version:
                    max_version = v
        if max_version > 0:
            version_info['current_version'] = max_version
            version_info['next_version'] = max_version + 1
            version_info['label'] = f'v{max_version + 1}'
            version_info['previous_runs'] = max_version
    except Exception:
        pass

    return version_info


# -------------------------------------------------------------------
# API: Start Pipeline
# -------------------------------------------------------------------

@supervisor_bp.route('/api/supervisor/run', methods=['POST'])
def start_pipeline_run():
    """Start a new supervisor pipeline run."""
    from orchestrator.supervisor import AIBIPipelineSupervisor, SupervisorConfig
    from orchestrator.generic_tool_executor import GenericToolExecutor
    from services.workspace_io import WorkspaceService
    from services.sql_client import SQLService
    from services.lakeview_client import LakeviewService
    from services.genie_client import GenieService
    from llm.client import LLMClient

    body = request.get_json(force=True)
    domain = body.get('domain', '')
    domain_path = body.get('domain_path', '')

    if not domain or not domain_path:
        return jsonify({"error": "domain and domain_path are required"}), 400

    run_id = str(uuid.uuid4())

    # Build config from request
    config = SupervisorConfig(
        gateway_endpoint=body.get('gateway_endpoint', 'databricks-gpt-5-5'),
        domain=domain,
        domain_path=domain_path,
        deploy_root=body.get('deploy_root', ''),
        catalog=body.get('catalog', ''),
        schema=body.get('schema', ''),
        sql_warehouse_id=body.get('sql_warehouse_id', ''),
        workspace_host=body.get('workspace_host', ''),
    )

    # Create run state
    run_state = RunState(run_id, domain, body)
    _active_runs[run_id] = run_state

    # Event callback
    def emit(event_type, data):
        run_state.add_event(event_type, data)

    # Launch in background thread
    def run_pipeline():
        try:
            # Initialize services
            ws = WorkspaceService()
            sql = SQLService(warehouse_id=config.sql_warehouse_id)
            lakeview = LakeviewService()
            genie = GenieService()
            llm = LLMClient(
                endpoint_name=body.get('gateway_endpoint', 'databricks-gpt-5-5'),
                vision_endpoint_name=body.get('vision_model', 'databricks-gpt-5-5'),
            )

            executor = GenericToolExecutor(
                services={
                    'workspace': ws,
                    'sql': sql,
                    'lakeview': lakeview,
                    'genie': genie,
                },
                llm_client=llm,
            )

            # Detect version and set output folder BEFORE pipeline starts
            # output_subpath comes from accelerator.yaml (workspace.output_subpath)
            version_info = _detect_version(ws, config.domain_path)
            output_subpath = version_info['output_subpath']
            config.version = version_info['next_version']
            config.output_folder = f"{config.domain_path}/{output_subpath}/v{config.version}"
            version_info['output_folder'] = config.output_folder
            run_state.version_info = version_info
            emit('version_info', version_info)

            # Create versioned output folder and write run_manifest.json
            try:
                ws.mkdirs(config.output_folder)
                manifest = {
                    'version': config.version,
                    'domain': config.domain,
                    'catalog': config.catalog,
                    'schema': config.schema,
                    'run_id': run_id,
                    'output_folder': config.output_folder,
                }
                manifest_path = f"{config.domain_path}/{output_subpath}/run_manifest.json"
                ws.write_file(manifest_path, json.dumps(manifest, indent=2))
                logger.info(f"Version {config.version}: output -> {config.output_folder}")
            except Exception as e:
                logger.warning(f"Could not write run_manifest.json: {e}")

            # Read master prompt
            prompt_path = f"{config.deploy_root}/framework/prompts/00_master_prompt.md"
            master_prompt = ws.read_file(prompt_path) or ""

            # Run supervisor
            supervisor = AIBIPipelineSupervisor()
            result = supervisor.run_with_events(
                config=config,
                master_prompt=master_prompt,
                tool_executor=executor,
                callback=emit,
            )

            run_state.result = result
            run_state.status = result.get('status', 'completed')

        except Exception as e:
            logger.error(f"Pipeline run {run_id} failed: {e}", exc_info=True)
            run_state.status = 'failed'
            run_state.result = {'status': 'failed', 'error': str(e)}
            emit('pipeline_error', {'error': str(e)})

    thread = threading.Thread(target=run_pipeline, daemon=True)
    thread.start()

    return jsonify({
        "run_id": run_id,
        "status": "started",
        "monitor_url": f"/domains/{domain}/run/{run_id}",
    })


# -------------------------------------------------------------------
# API: Poll Events
# -------------------------------------------------------------------

@supervisor_bp.route('/api/supervisor/poll/<run_id>')
def poll_events(run_id):
    """Poll for new events since index."""
    run_state = _active_runs.get(run_id)
    if not run_state:
        return jsonify({"error": "Run not found"}), 404

    after = int(request.args.get('after', 0))
    events = run_state.get_events_after(after)

    return jsonify({
        "run_id": run_id,
        "status": run_state.status,
        "events": events,
        "total_events": len(run_state.events),
    })


# -------------------------------------------------------------------
# API: Cancel
# -------------------------------------------------------------------

@supervisor_bp.route('/api/supervisor/cancel/<run_id>', methods=['POST'])
def cancel_run(run_id):
    """Cancel a running pipeline."""
    run_state = _active_runs.get(run_id)
    if not run_state:
        return jsonify({"error": "Run not found"}), 404

    run_state.status = 'cancelled'
    run_state.add_event('pipeline_cancelled', {'run_id': run_id})
    return jsonify({"status": "cancelled"})


# -------------------------------------------------------------------
# UI: Pipeline Monitor Page
# -------------------------------------------------------------------

@supervisor_bp.route('/supervisor')
def launch():
    """Supervisor launch page — start a new pipeline run."""
    return render_template('supervisor_launch.html')


@supervisor_bp.route('/supervisor/run/<run_id>')
@supervisor_bp.route('/domains/<domain_name>/run/<run_id>')
def pipeline_monitor(run_id, domain_name=None):
    """Render the pipeline monitor UI."""
    run_state = _active_runs.get(run_id)
    domain = domain_name or (run_state.domain if run_state else 'unknown')

    # Pass run metadata for the version/context banner
    run_meta = {}
    if run_state:
        cfg = run_state.config or {}
        run_meta = {
            'run_id': run_id,
            'domain': domain,
            'catalog': cfg.get('catalog', ''),
            'schema': cfg.get('schema', ''),
            'sql_warehouse_id': cfg.get('sql_warehouse_id', ''),
            'gateway_endpoint': cfg.get('gateway_endpoint', 'databricks-gpt-5-5'),
            'started_at': run_state.events[0]['timestamp'] if run_state.events else time.time(),
            'version_info': getattr(run_state, 'version_info', {}),
        }

    return render_template(
        'pipeline_monitor.html',
        run_id=run_id,
        domain=domain,
        run_meta=run_meta,
    )
