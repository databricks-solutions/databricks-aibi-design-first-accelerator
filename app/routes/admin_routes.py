"""Admin API routes for infrastructure management.

Provides endpoints to check infrastructure status and trigger setup jobs.
"""

import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


# Cached WorkspaceClient (avoid creating a new one per request)
_ws_client = None


def _get_workspace_client():
    """Get cached WorkspaceClient with app SP credentials."""
    global _ws_client
    if _ws_client is None:
        from databricks.sdk import WorkspaceClient
        _ws_client = WorkspaceClient()
    return _ws_client


# ------------------------------------------------------------------
# Infrastructure Status
# ------------------------------------------------------------------

@admin_bp.route("/setup-status")
def setup_status():
    """Check infrastructure component status.

    Returns status of: permissions, uc_access, metadata, lakebase.
    """
    status = {
        "permissions": {"status": "unknown"},
        "uc_access": {"status": "unknown"},
        "metadata": {"status": "unknown"},
        "lakebase": {"status": "unknown"},
    }

    import os
    from databricks.sdk import WorkspaceClient

    project_id = os.environ.get("LAKEBASE_PROJECT_ID", "aibi-studio")
    w = _get_workspace_client()

    # Resolve SP identity
    sp_id = ""
    try:
        me = w.current_user.me()
        sp_id = getattr(me, "application_id", None) or me.user_name or ""
    except Exception as e:
        status["permissions"] = {"status": "error", "message": str(e)[:80]}
        status["uc_access"] = {"status": "error", "message": str(e)[:80]}

    # Find setup job to read configured project_folder and catalog_name
    job_folder = ""
    job_catalog = ""
    try:
        for job in w.jobs.list():
            if "aibi-studio-setup-infrastructure" in (job.settings.name or ""):
                full_job = w.jobs.get(job.job_id)
                for param in (full_job.settings.parameters or []):
                    if param.name == "project_folder":
                        job_folder = param.default or ""
                    elif param.name == "catalog_name":
                        job_catalog = param.default or ""
                break
    except Exception as job_err:
        logger.info(f"Setup job lookup: {job_err}")

    # 3. Workspace Permissions — verify SP has access to the project folder
    if sp_id:
        try:
            if job_folder:
                w.workspace.get_status(job_folder)
                status["permissions"] = {
                    "status": "ready",
                    "detail": f"CAN_MANAGE",
                    "sp_id": sp_id,
                    "folder": job_folder,
                }
            else:
                status["permissions"] = {"status": "error", "message": "Setup job not found", "sp_id": sp_id}
        except Exception as e:
            status["permissions"] = {"status": "error", "message": f"No folder access: {str(e)[:50]}", "sp_id": sp_id}

    # 4. Unity Catalog Access — verify SP has access to the catalog
    if sp_id:
        try:
            if job_catalog:
                schemas = [s.name for s in w.schemas.list(catalog_name=job_catalog)
                           if s.name not in ("information_schema",)]
                status["uc_access"] = {
                    "status": "ready",
                    "detail": f"USE CATALOG, CREATE SCHEMA",
                    "sp_id": sp_id,
                    "catalog": job_catalog,
                    "schemas": schemas[:10],
                    "schema_count": len(schemas),
                }
            else:
                status["uc_access"] = {"status": "error", "message": "Setup job not found", "sp_id": sp_id}
        except Exception as e:
            status["uc_access"] = {"status": "error", "message": f"No catalog access: {str(e)[:50]}", "sp_id": sp_id}

    # Check Lakebase project state via direct pg8000 connection
    branch_id = "production"
    try:
        endpoints = list(w.postgres.list_endpoints(
            parent=f"projects/{project_id}/branches/{branch_id}"
        ))
        if endpoints:
            endpoint_host = endpoints[0].status.hosts.host
            status["lakebase"] = {
                "status": "ready",
                "detail": f"endpoint: {endpoint_host}",
                "project_state": "active",
            }
            # Verify direct pg8000 connection health
            try:
                from services.state_store import StateStore
                ep_name = f"projects/{project_id}/branches/{branch_id}/endpoints/primary"
                user_fn = lambda: getattr(w.current_user.me(), 'application_id', None) or w.current_user.me().user_name
                token_fn = lambda: w.postgres.generate_database_credential(endpoint=ep_name).token
                store = StateStore(endpoint_host, "databricks_postgres", user_fn, token_fn)
                if store.health_check():
                    status["metadata"] = {"status": "ready", "detail": "Phase config accessible"}
                else:
                    status["metadata"] = {"status": "error", "message": "Database unreachable"}
            except Exception as health_err:
                logger.info(f"Lakebase health check error: {health_err}")
                status["metadata"] = {"status": "error", "message": f"Connection failed: {str(health_err)[:80]}"}

            # Check SP role access in Lakebase
            try:
                sp_app_id = os.environ.get("DATABRICKS_CLIENT_ID", "")
                roles = list(w.postgres.list_roles(parent=f"projects/{project_id}/branches/{branch_id}"))
                sp_role = None
                for r in roles:
                    if r.status and r.status.postgres_role == sp_app_id:
                        sp_role = r
                        break
                if sp_role:
                    membership = [str(m.value) for m in (sp_role.status.membership_roles or [])]
                    status["lakebase_access"] = {
                        "status": "ready",
                        "detail": f"SP role: {sp_app_id[:12]}...",
                        "postgres_role": sp_role.status.postgres_role,
                        "membership": membership or ["table-level grants"],
                    }
                else:
                    status["lakebase_access"] = {
                        "status": "warning",
                        "message": "SP role not found in Lakebase",
                    }
            except Exception as role_err:
                logger.info(f"SP role check: {role_err}")
                status["lakebase_access"] = {"status": "unknown", "message": str(role_err)[:60]}
        else:
            status["lakebase"] = {
                "status": "error",
                "message": "Project exists but no endpoints yet",
                "project_state": "active",
            }
            status["metadata"] = {"status": "not_provisioned", "message": "No endpoints"}
    except Exception as e:
        err_msg = str(e).lower()
        logger.info(f"Lakebase endpoint check: {e}")
        # Use REST API with show_deleted=true to detect soft-deleted projects
        project_found = False
        project_deleted = False
        try:
            import requests
            token = w.config.token
            host = w.config.host.rstrip('/')
            resp = requests.get(
                f"{host}/api/2.0/postgres/projects",
                params={"show_deleted": "true"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.ok:
                for p in resp.json().get("projects", []):
                    if project_id in p.get("name", ""):
                        project_found = True
                        # Check if it's soft-deleted (delete_time present)
                        if p.get("deleteTime") or p.get("delete_time"):
                            project_deleted = True
                        break
        except Exception as api_err:
            logger.info(f"REST list_projects fallback: {api_err}")

        if project_found and project_deleted:
            status["lakebase"] = {
                "status": "error",
                "message": "Project is soft-deleted",
                "project_state": "soft_deleted",
            }
        elif project_found:
            status["lakebase"] = {
                "status": "error",
                "message": "Project exists (endpoint not accessible)",
                "project_state": "active",
            }
        else:
            status["lakebase"] = {
                "status": "not_provisioned",
                "message": "No project exists",
                "project_state": "not_found",
            }
        status["metadata"] = {"status": "not_provisioned", "message": "Lakebase not ready"}

    # Config info (derived from discovery, not env vars)
    status["config"] = {
        "lakebase_project_id": project_id,
    }

    return jsonify(status)




# ------------------------------------------------------------------
# Run Setup Jobs
# ------------------------------------------------------------------

@admin_bp.route("/run-setup", methods=["POST"])
def run_setup():
    """Trigger a setup job.

    Query params:
        job (str, optional): Specific job key to run. If omitted, runs all setup jobs.

    Returns:
        {status: 'triggered', run_id, job_id}
    """
    action = request.args.get("action", "create")  # create, purge_and_create

    try:
        w = _get_workspace_client()

        # Find job by base name substring (works regardless of [dev username] prefix)
        job_id = None
        for j in w.jobs.list():
            if j.settings and j.settings.name and "aibi-studio-setup-infrastructure" in j.settings.name:
                job_id = j.job_id
                break

        if not job_id:
            return jsonify({"error": "Setup job not found. Deploy the bundle first."}), 404

        # The job always runs purge_lakebase -> create_lakebase -> metadata -> permissions
        # The action param is passed to downstream tasks (metadata/perms skip on purge)
        run = w.jobs.run_now(
            job_id=job_id,
            job_parameters={"action": action}
        )
        logger.info(f"Setup job triggered: job_id={job_id}, run_id={run.run_id}")

        return jsonify({
            "status": "triggered",
            "job_id": str(job_id),
            "run_id": str(run.run_id),
        })

    except Exception as e:
        logger.error(f"Failed to trigger setup job: {e}")
        return jsonify({"error": str(e)[:200]}), 500


# ------------------------------------------------------------------
# Job Run Status (for polling)
# ------------------------------------------------------------------

@admin_bp.route("/job-status/<int:run_id>")
def job_status(run_id):
    """Get status of a job run for polling.

    Returns:
        {state, result_state, state_message, tasks_completed, tasks_total}
    """
    try:
        w = _get_workspace_client()
        run = w.jobs.get_run(run_id=run_id)

        tasks_total = len(run.tasks) if run.tasks else 0
        tasks_completed = sum(
            1 for t in (run.tasks or [])
            if t.state and t.state.life_cycle_state and "TERMINATED" in str(t.state.life_cycle_state)
        )

        # Extract enum .value to get clean strings (e.g. "TERMINATED" not "LifeCycleState.TERMINATED")
        life_cycle = run.state.life_cycle_state if run.state else None
        result = run.state.result_state if run.state else None
        return jsonify({
            "state": life_cycle.value if hasattr(life_cycle, 'value') else str(life_cycle or "UNKNOWN"),
            "result_state": result.value if hasattr(result, 'value') else str(result) if result else None,
            "state_message": run.state.state_message if run.state else None,
            "tasks_total": tasks_total,
            "tasks_completed": tasks_completed,
        })

    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500
