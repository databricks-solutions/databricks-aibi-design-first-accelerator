# Databricks notebook source
# MAGIC %md
# MAGIC # Seed Pipeline Metadata into Lakebase
# MAGIC
# MAGIC Idempotent - upserts config rows into step_phases_config.
# MAGIC Depends on: setup_lakebase (instance must exist).

# COMMAND ----------

# DBTITLE 1,Install Dependencies
# MAGIC %pip install -U "databricks-sdk>=0.81" "pg8000>=1.30"

# COMMAND ----------

# MAGIC %restart_python

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text('project_id', 'aibi-studio')
dbutils.widgets.text('action', 'create')
project_id = dbutils.widgets.get('project_id')
action = dbutils.widgets.get('action').strip().lower()
if action == 'purge_and_create':
    action = 'create'
print(f'Project ID: {project_id}')
print(f'Action: {action}')

if action == 'purge':
    print('Action is purge — skipping metadata seeding.')
    dbutils.notebook.exit('skipped:purge')

# COMMAND ----------

# DBTITLE 1,Connect to Lakebase
from databricks.sdk import WorkspaceClient
import pg8000
import ssl

w = WorkspaceClient()
branch_id = 'production'
db_name = 'databricks_postgres'  # Use default database

endpoints = list(w.postgres.list_endpoints(parent=f'projects/{project_id}/branches/{branch_id}'))
if not endpoints:
    raise RuntimeError(f'No endpoints for project={project_id}. Run setup_lakebase first.')

endpoint_host = endpoints[0].status.hosts.host
cred = w.postgres.generate_database_credential(
    endpoint=f'projects/{project_id}/branches/{branch_id}/endpoints/primary'
)
username = w.current_user.me().user_name
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
print(f'Connecting to: {endpoint_host}')

# COMMAND ----------

# DBTITLE 1,Seed Step Phases Config
PHASE_CONFIG = [
    ('environment_setup',      'setup_env',          0, 'Setup Environment',         '_setup_environment',           True, 120, 1),
    ('create_data_layer',      'parse_erd',          0, 'Parse ERD Image',           '_parse_erd',                   True, 300, 2),
    ('create_data_layer',      'generate_ddl',       1, 'Generate DDL Notebook',     '_generate_ddl_notebook',       True, 600, 2),
    ('create_data_layer',      'generate_synthetic', 2, 'Generate Synthetic Data',   '_generate_synthetic_notebook', True, 600, 2),
    ('create_data_layer',      'execute_validate',   3, 'Execute and Validate',      '_execute_and_validate',        True, 900, 1),
    ('create_metric_views',    'profile_schema',     0, 'Profile Schema',            '_profile_schema',              True, 300, 2),
    ('create_metric_views',    'generate_metrics',   1, 'Generate Metric Views',     '_generate_metric_views',       True, 600, 2),
    ('create_metric_views',    'execute_metrics',    2, 'Execute Metric DDL',        '_execute_metric_ddl',          True, 600, 1),
    ('create_dashboards',      'design_layout',      0, 'Design Dashboard Layout',   '_design_layout',               True, 300, 2),
    ('create_dashboards',      'generate_dashboard', 1, 'Generate Dashboard',        '_generate_dashboard',          True, 600, 2),
    ('create_dashboards',      'publish_dashboard',  2, 'Publish Dashboard',         '_publish_dashboard',           True, 300, 1),
    ('create_genie_space',     'configure_space',    0, 'Configure Genie Space',     '_configure_space',             True, 300, 2),
    ('create_genie_space',     'create_space',       1, 'Create Genie Space',        '_create_space',                True, 300, 1),
    ('generate_documentation', 'generate_docs',      0, 'Generate Documentation',    '_generate_docs',               True, 600, 2),
    ('generate_documentation', 'write_docs',         1, 'Write Documentation',       '_write_docs',                  True, 300, 1),
]

conn = pg8000.connect(
    host=endpoint_host,
    port=5432,
    database=db_name,
    user=username,
    password=cred.token,
    ssl_context=ssl_context,
)
try:
    cur = conn.cursor()
    for step, phase, idx, label, handler, enabled, timeout, retries in PHASE_CONFIG:
        cur.execute(
            '''INSERT INTO step_phases_config
            (step_name, phase_name, phase_index, phase_label, handler_method, enabled, timeout_s, max_retries)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (step_name, phase_name) DO UPDATE SET
                phase_index = EXCLUDED.phase_index, phase_label = EXCLUDED.phase_label,
                handler_method = EXCLUDED.handler_method, enabled = EXCLUDED.enabled,
                timeout_s = EXCLUDED.timeout_s, max_retries = EXCLUDED.max_retries,
                updated_at = now()''',
            (step, phase, idx, label, handler, enabled, timeout, retries)
        )
    conn.commit()
    cur.close()
finally:
    conn.close()

print(f'Seeded {len(PHASE_CONFIG)} phase config rows')
dbutils.notebook.exit(f'seeded:{len(PHASE_CONFIG)}')

