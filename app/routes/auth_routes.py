"""Authentication routes for AI/BI Studio.

Uses Databricks Apps platform identity (X-Forwarded-* headers).
No login form — users are authenticated at the platform level.
See docs/design_phase2.md Section 7.
"""

import logging
from flask import Blueprint, request, session, redirect, url_for, jsonify

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login')
def login():
    """Auto-login from Databricks platform identity headers."""
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

    logger.info(f"User logged in: {email}")
    return redirect(url_for('dashboard'))


@auth_bp.route('/logout')
def logout():
    """Clear session and redirect to login."""
    user = session.get('user_email', 'unknown')
    session.clear()
    logger.info(f"User logged out: {user}")
    return redirect(url_for('auth.login'))


@auth_bp.route('/api/auth/user')
def get_user():
    """Return current user info."""
    if not session.get('user_email'):
        return jsonify({'authenticated': False}), 401
    return jsonify({
        'authenticated': True,
        'email': session.get('user_email'),
        'name': session.get('user_name')
    })
