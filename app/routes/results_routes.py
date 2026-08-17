"""Results routes for AI/BI Studio.

Handles run history and generated asset retrieval.
See docs/design_phase2.md Section 5.3.
"""

import logging
from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

results_bp = Blueprint('results', __name__, url_prefix='/api/results')


@results_bp.route('/history')
def get_history():
    """List past pipeline runs.

    Query params:
        limit (int): Max results (default 20)

    Returns:
        {runs: [{run_id, domain, status, started_at, duration_s}]}
    """
    # TODO: Read from run history store
    return jsonify({'runs': []})


@results_bp.route('/<run_id>')
def get_run_details(run_id):
    """Get full details for a specific run.

    Returns:
        {run_id, config, steps: [{name, status, duration_s}], assets, validation}
    """
    # TODO: Read from run history store
    return jsonify({'run_id': run_id, 'status': 'not_found'}), 404


@results_bp.route('/<run_id>/assets')
def get_run_assets(run_id):
    """Get generated asset links for a completed run.

    Returns:
        {dashboards: [], genie_space: {}, metric_views: [], notebooks: []}
    """
    # TODO: Read manifest files from output folder
    return jsonify({
        'run_id': run_id,
        'dashboards': [],
        'genie_space': None,
        'metric_views': [],
        'notebooks': []
    })
