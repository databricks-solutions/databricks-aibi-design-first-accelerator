"""Domain management routes - list, configure, and run KPI domains."""

import os
import posixpath
import base64
import logging

import yaml
from flask import Blueprint, jsonify, request, Response, current_app
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ExportFormat, ObjectType

logger = logging.getLogger(__name__)

domain_bp = Blueprint('domains', __name__, url_prefix='/api/domains')


def _get_workspace_root():
    """Get resolved workspace root from Flask app config (set by config.py discovery)."""
    return current_app.config.get('WORKSPACE_ROOT', '')


def _get_examples_path():
    """Workspace path to kpi_domains/ folder."""
    return _get_workspace_root() + '/kpi_domains'


def _get_client():
    """Get a WorkspaceClient (uses app SP credentials)."""
    return WorkspaceClient()


def _read_workspace_file(ws_path):
    """Read a workspace file via SDK export and return its content as string."""
    w = _get_client()
    resp = w.workspace.export(path=ws_path, format=ExportFormat.AUTO)
    if resp.content:
        return base64.b64decode(resp.content).decode('utf-8')
    return ''


def _load_yaml_from_workspace(ws_path):
    """Load a YAML file from workspace path via SDK."""
    content = _read_workspace_file(ws_path)
    return yaml.safe_load(content) or {}


@domain_bp.route('', methods=['GET'])
def list_domains():
    """List all available domains under kpi_domains/."""
    examples_path = _get_examples_path()
    domains = []
    w = _get_client()
    debug_info = {'resolved_path': examples_path, 'items_found': 0, 'dirs_found': 0}
    try:
        items = list(w.workspace.list(path=examples_path))
        debug_info['items_found'] = len(items)
    except Exception as e:
        logger.warning(f"Cannot list examples at {examples_path}: {e}")
        return jsonify({'domains': [], 'error': str(e), 'debug': debug_info})

    for item in sorted(items, key=lambda x: x.path or ''):
        # Accept DIRECTORY or any folder-like type
        if item.object_type not in (ObjectType.DIRECTORY, ):
            continue
        debug_info['dirs_found'] += 1
        entry_name = (item.path or '').split('/')[-1]
        config_ws_path = f"{item.path}/accelerator.yaml"
        try:
            config = _load_yaml_from_workspace(config_ws_path)
            domain_info = config.get('domain', {})
            workspace = config.get('workspace', {})
            domains.append({
                'name': entry_name,
                'display_name': domain_info.get('display_name', entry_name.replace('_', ' ').title()),
                'description': domain_info.get('description', ''),
                'version': workspace.get('version', 'v1'),
                'version_suffix': workspace.get('version_suffix', ''),
            })
        except Exception as e:
            logger.debug(f"Skipping '{entry_name}': {e}")
            # Still include for debugging
            domains.append({
                'name': entry_name,
                'display_name': entry_name.replace('_', ' ').title(),
                'description': f'Config load error: {e}',
                'version': 'unknown',
                'version_suffix': '',
            })

    return jsonify({'domains': domains, 'debug': debug_info})


@domain_bp.route('/<domain_name>/config', methods=['GET'])
def get_domain_config(domain_name):
    """Get the full configuration for a domain."""
    config_ws_path = f"{_get_examples_path()}/{domain_name}/accelerator.yaml"
    try:
        config = _load_yaml_from_workspace(config_ws_path)
    except Exception as e:
        return jsonify({'error': f'Domain {domain_name} not found: {e}'}), 404
    return jsonify({'domain': domain_name, 'config': config})


@domain_bp.route('/<domain_name>/kpi-matrix', methods=['GET'])
def get_kpi_matrix(domain_name):
    """Get the KPI matrix/spec for a domain."""
    domain_ws_path = f"{_get_examples_path()}/{domain_name}"
    config_ws_path = f"{domain_ws_path}/accelerator.yaml"
    try:
        config = _load_yaml_from_workspace(config_ws_path)
    except Exception as e:
        return jsonify({'error': f'Domain {domain_name} not found: {e}'}), 404
    inputs = config.get('inputs', {})
    kpi_spec_rel = inputs.get('kpi_spec', 'inputs/kpi_spec.yaml')
    kpi_ws_path = posixpath.normpath(f"{domain_ws_path}/{kpi_spec_rel}")
    try:
        raw = _read_workspace_file(kpi_ws_path)
    except Exception:
        return jsonify({'domain': domain_name, 'kpi_matrix': [], 'raw': '', 'path': kpi_spec_rel})
    try:
        data = yaml.safe_load(raw) or {}
        return jsonify({'domain': domain_name, 'kpi_matrix': data, 'raw': raw, 'path': kpi_spec_rel})
    except Exception:
        return jsonify({'domain': domain_name, 'kpi_matrix': [], 'raw': raw, 'path': kpi_spec_rel})




@domain_bp.route('/<domain_name>/kpi-matrix', methods=['PUT'])
def save_kpi_matrix(domain_name):
    """Save updated KPI spec content back to workspace."""
    import base64
    from flask import request
    from databricks.sdk.service.workspace import ImportFormat

    data = request.get_json()
    new_content = data.get('content', '')
    if not new_content:
        return jsonify({'error': 'No content provided'}), 400

    domain_ws_path = f"{_get_examples_path()}/{domain_name}"
    config_ws_path = f"{domain_ws_path}/accelerator.yaml"
    try:
        config = _load_yaml_from_workspace(config_ws_path)
    except Exception as e:
        return jsonify({'error': f'Domain not found: {e}'}), 404

    inputs = config.get('inputs', {})
    kpi_spec_rel = inputs.get('kpi_spec', 'inputs/kpi_spec.md')
    kpi_ws_path = posixpath.normpath(f"{domain_ws_path}/{kpi_spec_rel}")

    try:
        w = _get_client()
        content_b64 = base64.b64encode(new_content.encode('utf-8')).decode('utf-8')
        w.workspace.import_(path=kpi_ws_path, content=content_b64, format=ImportFormat.AUTO, overwrite=True)
        logger.info(f"KPI spec saved at {kpi_ws_path}")
        return jsonify({'success': True, 'path': kpi_spec_rel})
    except Exception as e:
        logger.warning(f"KPI spec save failed for {kpi_ws_path}: {e}")
        return jsonify({'error': f'Save failed: {e}'}), 500

@domain_bp.route('/<domain_name>/best-practices', methods=['GET'])
def get_best_practices(domain_name):
    """Get the best practices markdown for a domain."""
    domain_ws_path = f"{_get_examples_path()}/{domain_name}"
    config_ws_path = f"{domain_ws_path}/accelerator.yaml"
    try:
        config = _load_yaml_from_workspace(config_ws_path)
    except Exception as e:
        return jsonify({'error': f'Domain {domain_name} not found: {e}'}), 404
    inputs = config.get('inputs', {})
    bp_rel = inputs.get('best_practices', 'inputs/best_practices.md')
    bp_ws_path = posixpath.normpath(f"{domain_ws_path}/{bp_rel}")
    try:
        content = _read_workspace_file(bp_ws_path)
    except Exception:
        content = ''
    return jsonify({'domain': domain_name, 'content': content, 'path': bp_rel})


@domain_bp.route('/<domain_name>/best-practices', methods=['PUT'])
def save_best_practices(domain_name):
    """Save updated best practices content back to workspace."""
    import base64
    from databricks.sdk.service.workspace import ImportFormat

    data = request.get_json()
    new_content = data.get('content', '')
    if not new_content:
        return jsonify({'error': 'No content provided'}), 400

    domain_ws_path = f"{_get_examples_path()}/{domain_name}"
    config_ws_path = f"{domain_ws_path}/accelerator.yaml"
    try:
        config = _load_yaml_from_workspace(config_ws_path)
    except Exception as e:
        return jsonify({'error': f'Domain not found: {e}'}), 404

    inputs = config.get('inputs', {})
    bp_rel = inputs.get('best_practices', 'inputs/best_practices.md')
    bp_ws_path = posixpath.normpath(f"{domain_ws_path}/{bp_rel}")

    try:
        w = _get_client()
        content_b64 = base64.b64encode(new_content.encode('utf-8')).decode('utf-8')
        w.workspace.import_(path=bp_ws_path, content=content_b64, format=ImportFormat.AUTO, overwrite=True)
        logger.info(f"Best practices saved at {bp_ws_path}")
        return jsonify({'success': True, 'path': bp_rel})
    except Exception as e:
        logger.warning(f"Best practices save failed for {bp_ws_path}: {e}")
        return jsonify({'error': f'Save failed: {e}'}), 500





def _save_yaml_to_workspace(ws_path, data):
    """Serialize dict to YAML and save to workspace (same pattern as save_best_practices)."""
    import base64
    from databricks.sdk.service.workspace import ImportFormat
    w = _get_client()
    raw = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    content_b64 = base64.b64encode(raw.encode('utf-8')).decode('utf-8')
    w.workspace.import_(path=ws_path, content=content_b64, format=ImportFormat.AUTO, overwrite=True)


@domain_bp.route('/<domain_name>/config', methods=['PATCH'])
def patch_domain_config(domain_name):
    """Patch fields in the domain accelerator.yaml (step toggles, clean_start, etc).

    Called by the UI before pipeline run so master prompt sees updated config.
    """
    overrides = request.get_json()
    if not overrides:
        return jsonify({'error': 'No overrides provided'}), 400

    config_ws_path = f"{_get_examples_path()}/{domain_name}/accelerator.yaml"
    try:
        config = _load_yaml_from_workspace(config_ws_path)
    except Exception as e:
        return jsonify({'error': f'Domain not found: {e}'}), 404

    def _deep_merge(base, patch):
        for key, val in patch.items():
            if isinstance(val, dict) and isinstance(base.get(key), dict):
                _deep_merge(base[key], val)
            else:
                base[key] = val

    _deep_merge(config, overrides)

    try:
        _save_yaml_to_workspace(config_ws_path, config)
        logger.info(f"Config patched for '{domain_name}': {list(overrides.keys())}")
        return jsonify({'success': True, 'patched_keys': list(overrides.keys())})
    except Exception as e:
        logger.warning(f"Config patch failed: {e}")
        return jsonify({'error': f'Save failed: {e}'}), 500


@domain_bp.route('/<domain_name>/erd-image', methods=['GET'])
def get_erd_image(domain_name):
    """Serve the ERD image for a domain as binary (for inline preview or new window)."""
    import base64
    from flask import Response
    from databricks.sdk.service.workspace import ExportFormat

    domain_ws_path = f"{_get_examples_path()}/{domain_name}"
    config_ws_path = f"{domain_ws_path}/accelerator.yaml"
    try:
        config = _load_yaml_from_workspace(config_ws_path)
    except Exception as e:
        return Response(f"Domain not found: {e}", status=404, mimetype='text/plain')

    ds = config.get('data_source', {})
    erd_rel = ds.get('erd', {}).get('image', '')
    if not erd_rel:
        return Response("No ERD image configured", status=404, mimetype='text/plain')

    erd_ws_path = posixpath.normpath(f"{domain_ws_path}/{erd_rel}")
    try:
        w = _get_client()
        resp = w.workspace.export(path=erd_ws_path, format=ExportFormat.AUTO)
        image_bytes = base64.b64decode(resp.content)
        # Determine content type from extension
        ext = erd_rel.rsplit('.', 1)[-1].lower() if '.' in erd_rel else 'png'
        mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'svg': 'image/svg+xml', 'gif': 'image/gif'}.get(ext, 'image/png')
        return Response(image_bytes, status=200, mimetype=mime, headers={'Cache-Control': 'public, max-age=3600'})
    except Exception as e:
        logger.warning(f"ERD image export failed for {erd_ws_path}: {e}")
        return Response(f"Failed to load ERD: {e}", status=500, mimetype='text/plain')


@domain_bp.route('/<domain_name>/erd-image', methods=['POST'])
def upload_erd_image(domain_name):
    """Upload/replace the ERD image for a domain."""
    import base64
    from flask import Response, request
    from databricks.sdk.service.workspace import ImportFormat

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Empty filename'}), 400

    domain_ws_path = f"{_get_examples_path()}/{domain_name}"
    config_ws_path = f"{domain_ws_path}/accelerator.yaml"
    try:
        config = _load_yaml_from_workspace(config_ws_path)
    except Exception as e:
        return jsonify({'error': f'Domain not found: {e}'}), 404

    ds = config.get('data_source', {})
    erd_rel = ds.get('erd', {}).get('image', 'inputs/erd.png')
    erd_ws_path = posixpath.normpath(f"{domain_ws_path}/{erd_rel}")

    try:
        w = _get_client()
        file_bytes = file.read()
        content_b64 = base64.b64encode(file_bytes).decode('utf-8')
        w.workspace.import_(path=erd_ws_path, content=content_b64, format=ImportFormat.AUTO, overwrite=True)
        logger.info(f"ERD image replaced at {erd_ws_path}")
        return jsonify({'success': True, 'path': erd_rel})
    except Exception as e:
        logger.warning(f"ERD upload failed for {erd_ws_path}: {e}")
        return jsonify({'error': f'Upload failed: {e}'}), 500


@domain_bp.route('/<domain_name>/summary/<run_id>', methods=['GET'])
def get_run_summary(domain_name, run_id):
    """Get the summary of a completed run."""
    domain_ws_path = f"{_get_examples_path()}/{domain_name}"
    config_ws_path = f"{domain_ws_path}/accelerator.yaml"
    try:
        config = _load_yaml_from_workspace(config_ws_path)
    except Exception as e:
        return jsonify({'error': f'Domain {domain_name} not found: {e}'}), 404
    workspace = config.get('workspace', {})
    version = workspace.get('version_suffix', '_v1').lstrip('_')
    output_subpath = workspace.get('output_subpath', 'generated_outputs')
    output_ws_path = f"{domain_ws_path}/{output_subpath}/{version}"
    # List manifests
    w = _get_client()
    assets = []
    manifests_ws_path = f"{output_ws_path}/manifests"
    try:
        manifest_items = list(w.workspace.list(path=manifests_ws_path))
        for item in manifest_items:
            if item.object_type == ObjectType.FILE:
                fname = (item.path or '').split('/')[-1]
                try:
                    data = _load_yaml_from_workspace(item.path)
                    assets.append({'file': fname, 'data': data})
                except Exception:
                    assets.append({'file': fname, 'data': {}})
    except Exception:
        pass
    # List notebooks
    notebooks = []
    nb_ws_path = f"{output_ws_path}/notebooks"
    try:
        nb_items = list(w.workspace.list(path=nb_ws_path))
        notebooks = [(item.path or '').split('/')[-1] for item in nb_items]
    except Exception:
        pass
    return jsonify({'domain': domain_name, 'run_id': run_id, 'version': version, 'output_folder': output_ws_path, 'assets': assets, 'notebooks': notebooks})
