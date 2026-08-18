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

    application.register_blueprint(auth_bp)
    application.register_blueprint(pipeline_bp)
    application.register_blueprint(admin_bp)
    application.register_blueprint(domain_bp)

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
        """Redirect to dashboard."""
        return redirect(url_for('dashboard'))

    @application.route('/dashboard')
    def dashboard():
        """Dashboard page — list of all pipeline runs."""
        return render_template('dashboard.html')

    @application.route('/domains')
    def domains_page():
        """KPI Domains management page."""
        return render_template('domains.html', active_page='domains')

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
        """Legacy pipeline view — redirect to new run details."""
        return redirect(url_for('run_detail', run_id=run_id))

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
