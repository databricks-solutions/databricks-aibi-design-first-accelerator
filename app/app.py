"""AI/BI Studio — Flask application entry point.

Factory pattern creates and configures the app with modular blueprints.
See docs/design_phase2.md for full architecture.
"""

import os
import logging
from flask import Flask, redirect, url_for, session, render_template, request

from config import get_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app():
    """Application factory — creates and configures the Flask app."""
    application = Flask(__name__)

    # Load configuration
    config = get_config()
    application.config.from_object(config)

    # --- Register Blueprints ---
    from routes.auth_routes import auth_bp
    from routes.pipeline_routes import pipeline_bp
    from routes.admin_routes import admin_bp
    from routes.domain_routes import domain_bp
    from routes.agent_routes import agent_bp
    # supervisor_bp removed — Phase 4 uses pipeline_routes + agent_routes

    application.register_blueprint(auth_bp)
    application.register_blueprint(pipeline_bp)
    application.register_blueprint(admin_bp)
    application.register_blueprint(domain_bp)
    application.register_blueprint(agent_bp)
    # application.register_blueprint(supervisor_bp)  # Removed: Phase 4 architecture

    # --- Auto-authenticate from platform headers on every request ---
    @application.before_request
    def auto_authenticate():
        """Capture Databricks Apps identity headers into session automatically.

        This ensures the user is always authenticated without requiring
        an explicit /login redirect. Falls back to 'dev@localhost' for
        local development.
        """
        if not session.get('user_email'):
            email = request.headers.get('X-Forwarded-Email', '')
            username = request.headers.get('X-Forwarded-Preferred-Username', '')
            access_token = request.headers.get('X-Forwarded-Access-Token', '')

            if not email and not username:
                # Local development fallback
                email = 'dev@localhost'
                username = 'dev'

            session['user_email'] = email
            session['user_name'] = username
            session['access_token'] = access_token

    # --- Page Routes ---
    @application.route('/')
    def index():
        """Redirect to KPI Domains page."""
        return redirect(url_for('domains_page'))

    @application.route('/dashboard')
    def dashboard():
        """Dashboard page — list of all pipeline runs."""
        return render_template('dashboard.html')

    @application.route('/domains')
    def domains_page():
        """KPI Domains selection and launch page."""
        return render_template('domains.html', active_page='domains')

    @application.route('/runs')
    def runs_page():
        """Pipeline runs history page."""
        return render_template('runs.html', active_page='runs')

    @application.route('/alerts')
    def alerts_page():
        """Alerts page."""
        return render_template('domains.html', active_page='alerts')  # TODO: dedicated alerts template

    @application.route('/settings')
    def settings_page():
        """Settings page."""
        return render_template('domains.html', active_page='settings')  # TODO: dedicated settings template

    @application.route('/run/latest')
    def run_latest():
        """Redirect to the most recent run, or show empty state."""
        return render_template('run_details.html', run_id='latest')

    @application.route('/run/<run_id>')
    def run_detail(run_id):
        """Run details page — step progress, errors, rerun."""
        return render_template('run_details.html', run_id=run_id)

    @application.route('/admin')
    def admin():
        """Admin page (TODO placeholder)."""
        return render_template('admin.html')

    @application.route('/pipeline/new')
    def pipeline_new():
        """New pipeline run launcher page."""
        return render_template('pipeline.html')

    @application.route('/pipeline/<run_id>')
    def pipeline_view(run_id):
        """Pipeline monitor page (Phase 4 UI)."""
        return render_template('pipeline_monitor.html',
                               run_id=run_id,
                               domain=request.args.get('domain', ''),
                               run_meta={})

    @application.route('/domains/<domain_name>/run/<run_id>')
    def domain_pipeline_monitor(run_id, domain_name):
        """Pipeline monitor page launched from domains page."""
        return render_template('pipeline_monitor.html',
                               run_id=run_id,
                               domain=domain_name,
                               run_meta={})

    @application.route('/results/<run_id>')
    def results_view(run_id):
        """Run results page with generated asset links."""
        return render_template('results.html', run_id=run_id)


    logger.info(f"{config.APP_NAME} initialized (env={os.environ.get('FLASK_ENV', 'development')})")
    return application


# Create the app instance (used by gunicorn: `app:app`)
app = create_app()


if __name__ == '__main__':
    port = int(os.environ.get('DATABRICKS_APP_PORT', '8080'))
    logger.info(f"Starting Flask dev server on 0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
