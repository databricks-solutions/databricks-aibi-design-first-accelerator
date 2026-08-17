"""Configuration routes for AI/BI Studio.

Handles domain listing, config retrieval, and validation.
See docs/design_phase2.md Section 5.2.
"""

import logging
from flask import Blueprint, jsonify, current_app

logger = logging.getLogger(__name__)

config_bp = Blueprint('config', __name__, url_prefix='/api/config')


@config_bp.route('/domains')
def list_domains():
    """List available example domains from the workspace.

    Scans {DEPLOY_ROOT}/examples/ for directories containing accelerator.yaml.

    Returns:
        {domains: [{name: str, path: str, type: str}]}
    """
    # TODO: Scan workspace for example domains
    default_domain = current_app.config.get('DEFAULT_EXAMPLE_DOMAIN', 'member_claims')
    return jsonify({
        'domains': [
            {'name': default_domain, 'path': f"examples/{default_domain}", 'type': 'erd'}
        ]
    })


@config_bp.route('/domain/<name>')
def get_domain_config(name):
    """Get accelerator.yaml configuration for a specific domain.

    Returns:
        {config: object, validation: {valid: bool, errors: list}}
    """
    # TODO: Read and parse accelerator.yaml via WorkspaceService
    return jsonify({
        'domain': name,
        'config': None,
        'validation': {'valid': True, 'errors': []}
    })


@config_bp.route('/domain/<name>/next-version')
def get_next_version(name):
    """Preview the next version number for a domain.

    Used by the UI to display "Next version: v3" when user selects
    "Create New Version" mode.

    Returns:
        {next_version: int, next_suffix: str, existing_versions: list}
    """
    # TODO: Instantiate VersionResolver with real services and scan
    # For now, return placeholder
    return jsonify({
        'next_version': 1,
        'next_suffix': '_v1',
        'existing_versions': [],
        'existing_count': 0
    })


@config_bp.route('/validate', methods=['POST'])
def validate_config():
    """Validate accelerator.yaml before pipeline run.

    Request JSON:
        domain (str): Domain name to validate

    Returns:
        {valid: bool, errors: list}
    """
    # TODO: Run ConfigLoader.validate()
    return jsonify({'valid': True, 'errors': []})
