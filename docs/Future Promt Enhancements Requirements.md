# Non-Prompt-Driven Gaps (Items requiring manual/UI action instead of prompts):

Infrastructure Setup (setup_app_infrastructure job) — Must be triggered manually via databricks bundle run setup_app_infrastructure. Not launchable from a prompt in Genie Code today. The Admin page in the app shows status but doesn't auto-trigger it.

databricks bundle deploy — Deployment itself is a CLI command, not prompt-driven. A user must run this from their terminal before anything works.

Domain onboarding — Creating a new kpi_domains/<domain>/ directory with accelerator.yaml, inputs/erd.png, and inputs/kpi_spec.md is a manual file-creation step. No prompt-driven wizard exists to bootstrap a new domain from scratch.

App app.yaml env vars — CATALOG_NAME is hardcoded in app.yaml (line 28). Changing catalogs requires manually editing this file — not configurable via prompt.

KPI spec editing — While the app has a PUT /api/domains/<name>/kpi-matrix endpoint, the actual authoring of the KPI spec is manual (markdown editing). There's no LLM-assisted "describe your KPIs and I'll generate the spec" flow.

ERD image creation — The pipeline reads an ERD image via vision model, but producing that ERD image is entirely manual/external.

execute_python tool runs in a subprocess (python -c) — Not on a Databricks cluster. This means no Spark, no dbldatagen, no PySpark. For the app mode, the data layer step that needs PySpark relies on execute_notebook (Jobs API) but execute_python is limited to plain Python.

Version/cleanup management (07_cleanup_versions.md) — Exists as a prompt but isn't wired into the app pipeline stages or the STEP_NAMES registry in pipeline.py.