"""Domain management routes - list, configure, and run KPI domains."""

import os
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
    """Workspace path to examples/ folder."""
    return _get_workspace_root() + '/examples'


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
    """List all available domains under examples/."""
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
    kpi_ws_path = f"{domain_ws_path}/{kpi_spec_rel}"
    try:
        raw = _read_workspace_file(kpi_ws_path)
    except Exception:
        return jsonify({'domain': domain_name, 'kpi_matrix': [], 'raw': '', 'path': kpi_spec_rel})
    try:
        data = yaml.safe_load(raw) or {}
        return jsonify({'domain': domain_name, 'kpi_matrix': data, 'raw': raw, 'path': kpi_spec_rel})
    except Exception:
        return jsonify({'domain': domain_name, 'kpi_matrix': [], 'raw': raw, 'path': kpi_spec_rel})


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
    bp_ws_path = f"{domain_ws_path}/{bp_rel}"
    try:
        content = _read_workspace_file(bp_ws_path)
    except Exception:
        content = ''
    return jsonify({'domain': domain_name, 'content': content, 'path': bp_rel})


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
    output_subpath = workspace.get('output_subpath', 'output')
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
