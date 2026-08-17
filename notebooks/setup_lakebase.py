# Databricks notebook source
# MAGIC %md
# MAGIC # Setup Lakebase State Store
# MAGIC
# MAGIC Provisions or purges a Lakebase Postgres Autoscaling project.
# MAGIC
# MAGIC **Actions:**
# MAGIC - `create` — provision project, database, schema tables, SP role
# MAGIC - `purge` — permanently delete the project (removes all data)

# COMMAND ----------

# DBTITLE 1,Install Dependencies
# MAGIC %pip install -U "databricks-sdk>=0.81" "pg8000>=1.30"

# COMMAND ----------

# MAGIC %restart_python

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text("project_id", "aibi-studio")
dbutils.widgets.text("app_sp_id", "")
dbutils.widgets.text("action", "create")

project_id = dbutils.widgets.get("project_id")
app_sp_id = dbutils.widgets.get("app_sp_id")
dbutils.widgets.text("app_sp_uuid", "")
app_sp_uuid = dbutils.widgets.get("app_sp_uuid").strip()
action = dbutils.widgets.get("action").strip().lower()

print(f"Project ID: {project_id}")
print(f"App SP ID:  {app_sp_id}")
print(f"Action:     {action}")

# Handle action routing:
#   cleanup_lakebase task passes the raw job action (create or purge_and_create)
#   create_lakebase task always passes action=create
#
# When action=purge_and_create: run purge (this is the cleanup task)
# When action=create: skip purge, just exit (cleanup not needed)
# When action=purge: run purge only

# task_mode: "cleanup" (from cleanup_lakebase task) or "provision" (from create_lakebase task)
dbutils.widgets.text("task_mode", "provision")
task_mode = dbutils.widgets.get("task_mode").strip().lower()

if task_mode == "cleanup":
    if action == "purge_and_create":
        action = "purge"
    else:
        # action=create means no purge needed — skip
        import json
        print("Task mode: cleanup, action: create — no purge needed. Exiting.")
        dbutils.notebook.exit(json.dumps({"status": "skipped", "reason": "no purge needed"}))
elif task_mode == "provision":
    action = "create"
else:
    raise ValueError(f"Invalid task_mode: {task_mode}. Must be 'cleanup' or 'provision'.")

# COMMAND ----------

# DBTITLE 1,Initialize SDK
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.postgres import Project, ProjectSpec
import time, json

w = WorkspaceClient()
branch_id = "production"
db_name = "databricks_postgres"  # Use default database (auto-created with project)

# COMMAND ----------

# DBTITLE 1,Execute Action
if action == "purge":
    # ─── PURGE: permanently delete the project ───
    print(f"Purging Lakebase project '{project_id}'...")
    try:
        op = w.postgres.delete_project(name=f"projects/{project_id}", purge=True)
        op.wait()
        print(f"✓ Project '{project_id}' permanently deleted")
    except Exception as e:
        if "not found" in str(e).lower():
            print(f"✓ Project '{project_id}' does not exist (nothing to purge)")
        else:
            raise
    dbutils.notebook.exit(json.dumps({"status": "purged", "project_id": project_id}))

else:
    # ─── CREATE: provision the full infrastructure ───
    print(f"\n{'═' * 50}")
    print(f"  PROVISIONING LAKEBASE: {project_id}")
    print(f"{'═' * 50}\n")

    # Step 1: Create project
    print("Step 1: Create project...")
    try:
        op = w.postgres.create_project(
            project=Project(spec=ProjectSpec(
                display_name="AI/BI Studio State Store",
                pg_version=17,
            )),
            project_id=project_id,
        )
        project = op.wait()
        print(f"  ✓ Project created: {project.name}")
    except Exception as e:
        if "already exists" in str(e).lower() or "slug" in str(e).lower():
            project = w.postgres.get_project(name=f"projects/{project_id}")
            print(f"  ✓ Project already exists: {project.name}")
        else:
            raise

    # Step 2: Wait for endpoint
    print("\nStep 2: Wait for endpoint...")
    endpoints = []
    for attempt in range(12):
        try:
            endpoints = list(w.postgres.list_endpoints(
                parent=f"projects/{project_id}/branches/{branch_id}"
            ))
            if endpoints:
                break
        except Exception:
            pass
        wait = 15
        print(f"  Waiting for endpoint... ({attempt + 1}/12, next retry in {wait}s)")
        time.sleep(wait)

    if not endpoints:
        raise RuntimeError(f"Endpoints not available after 3 minutes for project={project_id}")

    endpoint_host = endpoints[0].status.hosts.host
    print(f"  ✓ Endpoint: {endpoint_host}")

    # Step 3: Create schema tables (using default databricks_postgres database)
    print("\nStep 3: Create schema tables...")
    cred = w.postgres.generate_database_credential(
        endpoint=f"projects/{project_id}/branches/{branch_id}/endpoints/primary"
    )
    username = w.current_user.me().user_name

    import pg8000
    import ssl
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    DDL_STATEMENTS = [
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id       TEXT PRIMARY KEY,
            domain       TEXT NOT NULL,
            run_mode     TEXT NOT NULL DEFAULT 'full',
            status       TEXT NOT NULL DEFAULT 'pending',
            version      TEXT,
            version_suffix TEXT,
            total_steps  INT DEFAULT 0,
            retry_count  INT DEFAULT 0,
            config_json  JSONB,
            error        TEXT,
            created_at   TIMESTAMPTZ DEFAULT now(),
            started_at   TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS steps (
            run_id      TEXT NOT NULL REFERENCES runs(run_id),
            step_name   TEXT NOT NULL,
            step_index  INT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            error       TEXT,
            started_at  TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            PRIMARY KEY (run_id, step_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS phases (
            run_id      TEXT NOT NULL,
            step_name   TEXT NOT NULL,
            phase_name  TEXT NOT NULL,
            phase_index INT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            error       TEXT,
            started_at  TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            PRIMARY KEY (run_id, step_name, phase_name),
            FOREIGN KEY (run_id, step_name) REFERENCES steps(run_id, step_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id    BIGSERIAL PRIMARY KEY,
            run_id      TEXT NOT NULL REFERENCES runs(run_id),
            event_type  TEXT NOT NULL,
            event_data  JSONB,
            created_at  TIMESTAMPTZ DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS step_logs (
            run_id      TEXT NOT NULL,
            step_name   TEXT NOT NULL,
            line        TEXT NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT now(),
            FOREIGN KEY (run_id, step_name) REFERENCES steps(run_id, step_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS step_phases_config (
            step_name      TEXT NOT NULL,
            phase_name     TEXT NOT NULL,
            phase_index    INT NOT NULL,
            phase_label    TEXT NOT NULL,
            handler_method TEXT NOT NULL,
            enabled        BOOLEAN NOT NULL DEFAULT true,
            timeout_s      INT DEFAULT 300,
            max_retries    INT DEFAULT 2,
            config_json    JSONB,
            created_at     TIMESTAMPTZ DEFAULT now(),
            updated_at     TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (step_name, phase_name)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, event_id)",
        "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status) WHERE status IN ('running', 'pending')",
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
        for ddl in DDL_STATEMENTS:
            cur.execute(ddl)
        conn.commit()
        cur.close()
    finally:
        conn.close()

    print("  ✓ Schema tables created")
    print("  ✓ Indexes created")

    # Step 4: Create App SP role (BEFORE enabling Data API so authenticator picks it up)
    print("\nStep 4: Create App SP role...")
    sp_uuid = app_sp_uuid if app_sp_uuid else app_sp_id
    if sp_uuid:
        from databricks.sdk.service.postgres import Role, RoleRoleSpec, RoleIdentityType
        # role_id must match ^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$
        role_slug = f"app-sp-{sp_uuid[:8]}"
        print(f"  role_id: {role_slug}, postgres_role: {sp_uuid}")
        try:
            op = w.postgres.create_role(
                parent=f"projects/{project_id}/branches/{branch_id}",
                role=Role(spec=RoleRoleSpec(
                    postgres_role=sp_uuid,
                    identity_type=RoleIdentityType.SERVICE_PRINCIPAL,
                )),
                role_id=role_slug,
            )
            op.wait()  # Wait for full completion (includes authenticator setup)
            print(f"  ✓ SP role created and ready")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"  ✓ SP role already exists")
            else:
                print(f"  ⚠ SP role creation failed: {e}")
    else:
        print("  ⚠ No app_sp_uuid provided, skipping role creation")

    # Step 5: Enable Data API (PostgREST)
    # Enabling AFTER role creation ensures authenticator is configured for SP
    db_resource_id = "databricks-postgres"
    print("\nStep 5: Enable Data API...")
    try:
        from databricks.sdk.service.postgres import DataApi, DataApiDataApiSpec
        op = w.postgres.create_data_api(
            parent=f"projects/{project_id}/branches/{branch_id}/databases/{db_resource_id}",
            data_api=DataApi(spec=DataApiDataApiSpec(
                db_schemas=["public"],
            )),
        )
        data_api_result = op.wait()
        data_api_url = data_api_result.status.url if data_api_result.status else None
        print(f"  ✓ Data API enabled")
        print(f"  ✓ Data API URL: {data_api_url}")
    except Exception as e:
        if "already" in str(e).lower() or "exists" in str(e).lower():
            print("  ✓ Data API already enabled")
            try:
                existing = w.postgres.get_data_api(
                    name=f"projects/{project_id}/branches/{branch_id}/databases/{db_resource_id}/data-api"
                )
                data_api_url = existing.status.url if existing.status else None
                print(f"  ✓ Data API URL: {data_api_url}")
            except Exception:
                data_api_url = None
        else:
            print(f"  ⚠ Data API enable failed: {e}")
            data_api_url = None

    # Step 6: Grant table permissions to SP
    print("\nStep 6: Grant Data API table access to SP...")
    if sp_uuid:
        try:
            sp_role_name = sp_uuid
            grant_statements = [
                f'GRANT USAGE ON SCHEMA public TO "{sp_role_name}"',
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{sp_role_name}"',
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{sp_role_name}"',
            ]
            conn2 = pg8000.connect(
                host=endpoint_host,
                port=5432,
                database=db_name,
                user=username,
                password=cred.token,
                ssl_context=ssl_context,
            )
            try:
                cur2 = conn2.cursor()
                for stmt in grant_statements:
                    cur2.execute(stmt)
                conn2.commit()
                cur2.close()
            finally:
                conn2.close()
            print(f"  ✓ Table grants applied for: {sp_role_name}")
        except Exception as e:
            print(f"  ⚠ Grants failed: {e}")
    else:
        print("  ⚠ No SP UUID — skipping grants")

    # Done
    print(f"\n{'═' * 50}")
    print(f"  LAKEBASE PROVISIONING COMPLETE")
    print(f"{'═' * 50}")
    print(f"  Project:  {project_id}")
    print(f"  Branch:   {branch_id}")
    print(f"  Endpoint: {endpoint_host}")
    print(f"  Database: {db_name}")
    print(f"{'═' * 50}")

    dbutils.notebook.exit(json.dumps({
        "status": "ready",
        "project_id": project_id,
        "endpoint_host": endpoint_host,
        "database": db_name,
    }))

