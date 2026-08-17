# Databricks notebook source
# DBTITLE 1,Setup Permissions for AI/BI Studio App
# Databricks notebook source
# Setup Permissions — grants the app's service principal access to project resources.
# Run this once after initial bundle deploy, or whenever the app is recreated.
#
# Parameters (passed from job):
#   app_name: The Databricks App name (e.g. "aibi-studio-arun-wagle")
#   project_folder: Workspace path to the project root

dbutils.widgets.text("app_name", "", "App Name")
dbutils.widgets.text("project_folder", "", "Project Folder Path")
dbutils.widgets.text("action", "create", "Action")

app_name = dbutils.widgets.get("app_name")
project_folder = dbutils.widgets.get("project_folder")
action = dbutils.widgets.get("action").strip().lower()
if action == "purge_and_create":
    action = "create"

if action == "purge":
    print("Action is purge — skipping workspace permissions.")
    dbutils.notebook.exit("skipped:purge")

# COMMAND ----------

# DBTITLE 1,Validate parameters
assert app_name, "app_name parameter is required"
assert project_folder, "project_folder parameter is required"
assert project_folder.startswith("/Workspace/"), "project_folder must be an absolute workspace path"

print(f"App name: {app_name}")
print(f"Project folder: {project_folder}")

# COMMAND ----------

# DBTITLE 1,Look up app service principal
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Get app details to find the service principal
app = w.apps.get(app_name)
sp_display_name = app.service_principal_name
sp_numeric_id = app.service_principal_id
print(f"SP display name: {sp_display_name}")
print(f"SP numeric ID: {sp_numeric_id}")

# Look up the SP's applicationId (UUID) — the Permissions API requires this
sp = w.service_principals.get(id=str(sp_numeric_id))
sp_application_id = sp.application_id
print(f"SP applicationId: {sp_application_id}")

# COMMAND ----------

# DBTITLE 1,Grant CAN_MANAGE on project folder
from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel

# Get the workspace object ID for the project folder
folder_status = w.workspace.get_status(project_folder)
folder_id = folder_status.object_id
print(f"Folder object ID: {folder_id}")

# Grant CAN_MANAGE to the app's service principal
# The Permissions API identifies SPs by their applicationId (UUID)
w.permissions.update(
    request_object_type="directories",
    request_object_id=str(folder_id),
    access_control_list=[
        AccessControlRequest(
            service_principal_name=sp_application_id,
            permission_level=PermissionLevel.CAN_MANAGE,
        )
    ],
)

print(f"\n✓ Granted CAN_MANAGE to '{sp_display_name}' (appId={sp_application_id}) on {project_folder}")

# COMMAND ----------

# DBTITLE 1,Verify permissions
# Verify the permission was applied
perms = w.permissions.get(
    request_object_type="directories",
    request_object_id=str(folder_id),
)

print("Current permissions on project folder:")
for acl in perms.access_control_list or []:
    name = acl.user_name or acl.group_name or acl.service_principal_name or "?"
    levels = [p.permission_level.value for p in (acl.all_permissions or [])]
    print(f"  {name}: {levels}")

print("\n✓ Setup complete. The app can now read/write to the project folder.")
