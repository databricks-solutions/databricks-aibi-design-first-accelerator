"""Gunicorn production configuration for AI/BI Studio."""

import os

# Bind to the port assigned by Databricks Apps platform
bind = f"0.0.0.0:{os.environ.get('DATABRICKS_APP_PORT', '8080')}"

# Workers: LLM calls are I/O-bound, 2 workers sufficient
workers = int(os.environ.get('GUNICORN_WORKERS', '2'))

# Timeout: pipeline LLM calls can take 30-60s each
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '600'))

# Graceful restart
max_requests = 500
max_requests_jitter = 50

# Logging — both access and error to stdout so Databricks App logs capture them
accesslog = '-'
errorlog = '-'
loglevel = 'info'
