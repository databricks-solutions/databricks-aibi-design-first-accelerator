# =============================================================================
# Gate Checks — Programmatic Enforcement for Dashboard & Genie Deployment
# =============================================================================
#
# This module provides runtime gate enforcement that PREVENTS the deployment of
# incomplete or empty assets. It is the programmatic counterpart to the prose
# gate instructions in the step prompts.
#
# PROBLEM SOLVED:
# Prompt-based gates ("check X before calling Y") rely on the executing agent
# to self-enforce. When agents shortcut through steps, they create API shells
# (dashboards with 0 widgets, Genie spaces with no instructions) and write
# PASS validation files that don't reflect reality. This module makes gates
# raise exceptions that physically block deployment of empty assets.
#
# THREE LAYERS OF DEFENSE:
#
# Layer 1 — Pre-deploy assertions (call BEFORE API create/publish):
#   assert_artifact_exists()           — prerequisite file must exist
#   assert_dashboard_has_widgets()     — serialized JSON must have widgets
#   assert_dashboard_has_filters()     — filter page must exist with bindings
#   assert_genie_config_complete()     — instructions, tables, questions set
#
# Layer 2 — Post-deploy API readback (call AFTER API create/publish):
#   validate_dashboard_from_api()      — GET dashboard, verify non-empty
#   validate_genie_from_api()          — GET space, verify configured
#
# Layer 3 — Terminal cross-validation sweep (call ONCE at end of run):
#   run_cross_validation()             — compare all manifests vs API reality
#
# USAGE:
#   from gate_checks import (
#       assert_artifact_exists,
#       assert_dashboard_has_widgets,
#       assert_dashboard_has_filters,
#       assert_genie_config_complete,
#       validate_dashboard_from_api,
#       validate_genie_from_api,
#       run_cross_validation,
#       write_ground_truth_validation,
#   )
#
# INTEGRATION POINTS:
#   - 03_create_dashboards.md Step 11 (pre-deploy): call Layer 1 assertions
#   - 03_create_dashboards.md Step 13 (post-deploy): call Layer 2 readback
#   - 04_create_genie_space.md pre-deploy: call Layer 1 genie assertions
#   - 04_create_genie_space.md post-deploy: call Layer 2 genie readback
#   - 00_master_prompt.md final step: call Layer 3 cross-validation
#
# GUARANTEE:
# After Layer 1 passes, the serialized dashboard JSON is structurally
# non-empty (has widgets on every canvas page, has a filters page).
# After Layer 2 passes, the deployed API object matches what was sent.
# After Layer 3 passes, every manifest claim is verified against the API.
# =============================================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


# =============================================================================
# DEFAULT QUALITY THRESHOLDS
# =============================================================================
# These can be overridden by passing a quality_gates dict from accelerator.yaml.
# The defaults represent the minimum acceptable quality for a production run.

DEFAULT_QUALITY_GATES = {
    # Dashboard thresholds
    "min_widgets_per_canvas_page": 2,
    "min_filters_per_dashboard": 3,
    "min_datasets_per_dashboard": 1,
    "min_canvas_pages_per_dashboard": 1,
    # Genie thresholds
    "min_genie_instruction_chars": 200,
    "min_genie_tables": 1,
    "min_genie_sample_questions": 5,
    "min_genie_example_sqls": 5,
    "min_genie_description_chars": 50,
}


def _get_threshold(quality_gates: dict | None, key: str) -> int:
    """Resolve a threshold from user-provided gates or defaults."""
    if quality_gates and key in quality_gates:
        return int(quality_gates[key])
    return DEFAULT_QUALITY_GATES[key]


# =============================================================================
# SECTION 1: Pre-Deploy Assertions (Layer 1)
# =============================================================================
# Call these BEFORE any Lakeview or Genie API create/publish call.
# They raise GateCheckError (subclass of RuntimeError) on failure,
# which physically prevents the API call from executing.


class GateCheckError(RuntimeError):
    """Raised when a programmatic gate check fails.

    Contains the gate_id and a human-readable explanation of what
    was expected vs what was found. Agents cannot catch-and-ignore
    this without explicitly handling the specific gate ID.
    """

    def __init__(self, gate_id: str, message: str):
        self.gate_id = gate_id
        super().__init__(f"GATE {gate_id} FAILED: {message}")


def assert_artifact_exists(
    path: str,
    gate_id: str,
    *,
    min_size_bytes: int = 10,
) -> None:
    """Assert that a prerequisite artifact file exists and is non-trivial.

    Call before any API call that depends on a prior step's output.
    Prevents the #1 failure mode: skipping design/validation steps
    and jumping directly to API creation.

    Args:
        path: Absolute workspace path to the expected artifact.
        gate_id: Identifier for this gate (e.g., 'GATE_3.2_DESIGN_CONTRACT').
        min_size_bytes: Minimum file size to consider non-trivial.

    Raises:
        GateCheckError: If file is missing or too small.

    Example:
        assert_artifact_exists(
            f"{output_folder}/dashboards/dashboard_design.yaml",
            "GATE_3.2_DESIGN_CONTRACT",
        )
    """
    if not os.path.exists(path):
        raise GateCheckError(
            gate_id,
            f"Required artifact not found: {path}\n"
            f"  This artifact must be created by a prior step before proceeding.\n"
            f"  Re-run the step that produces this artifact.",
        )
    size = os.path.getsize(path)
    if size < min_size_bytes:
        raise GateCheckError(
            gate_id,
            f"Artifact exists but is too small ({size} bytes < {min_size_bytes}): {path}\n"
            f"  This usually means the prior step wrote an empty/placeholder file.",
        )


def assert_dashboard_has_widgets(
    serialized_dashboard: dict,
    dashboard_name: str,
    *,
    quality_gates: dict | None = None,
) -> dict:
    """Assert that a dashboard JSON has widgets on every canvas page.

    Call AFTER building the serialized_dashboard dict and BEFORE passing
    it to create_dashboard() or patch_dashboard().

    This catches the exact v2 failure: dashboards created with datasets
    and page names but layout: [] and widgets: [] on every page.

    Args:
        serialized_dashboard: The full dashboard dict (datasets + pages).
        dashboard_name: Display name for error messages.
        quality_gates: Optional overrides from accelerator.yaml.

    Returns:
        Summary dict with counts for logging/audit.

    Raises:
        GateCheckError: If any canvas page has zero widgets or fewer
            than the minimum threshold.
    """
    min_widgets = _get_threshold(quality_gates, "min_widgets_per_canvas_page")
    min_canvas = _get_threshold(quality_gates, "min_canvas_pages_per_dashboard")
    min_datasets = _get_threshold(quality_gates, "min_datasets_per_dashboard")

    pages = serialized_dashboard.get("pages", [])
    datasets = serialized_dashboard.get("datasets", [])

    # Check datasets exist
    if len(datasets) < min_datasets:
        raise GateCheckError(
            "PRE_DEPLOY_DATASETS",
            f"Dashboard '{dashboard_name}' has {len(datasets)} dataset(s) "
            f"(minimum: {min_datasets}).\n"
            f"  Every dashboard must have at least one dataset with valid SQL.",
        )

    # Separate canvas pages from filter pages
    canvas_pages = []
    filter_pages = []
    for page in pages:
        page_type = page.get("pageType", "PAGE_TYPE_CANVAS")
        if page_type == "PAGE_TYPE_GLOBAL_FILTERS":
            filter_pages.append(page)
        else:
            canvas_pages.append(page)

    # Check canvas page count
    if len(canvas_pages) < min_canvas:
        raise GateCheckError(
            "PRE_DEPLOY_CANVAS_PAGES",
            f"Dashboard '{dashboard_name}' has {len(canvas_pages)} canvas page(s) "
            f"(minimum: {min_canvas}).\n"
            f"  KPI spec Dashboard Mapping defines the required page count.",
        )

    # Check each canvas page has widgets
    issues = []
    total_widgets = 0
    page_summary = []
    for page in canvas_pages:
        layout = page.get("layout", [])
        widget_count = len(layout)
        total_widgets += widget_count
        page_name = page.get("displayName", page.get("name", "unnamed"))
        page_summary.append({"page": page_name, "widgets": widget_count})

        if widget_count == 0:
            issues.append(
                f"Canvas page '{page_name}' has 0 widgets (layout is empty)."
            )
        elif widget_count < min_widgets:
            issues.append(
                f"Canvas page '{page_name}' has {widget_count} widget(s) "
                f"(minimum: {min_widgets})."
            )

    if issues:
        detail = "\n  ".join(issues)
        raise GateCheckError(
            "PRE_DEPLOY_WIDGETS",
            f"Dashboard '{dashboard_name}' has empty or under-populated canvas pages:\n"
            f"  {detail}\n\n"
            f"  Page summary: {page_summary}\n\n"
            f"  This means widget construction was skipped. Do NOT call \n"
            f"  create_dashboard() until every canvas page has widgets.\n"
            f"  Re-run the widget construction step.",
        )

    summary = {
        "dashboard_name": dashboard_name,
        "datasets": len(datasets),
        "canvas_pages": len(canvas_pages),
        "filter_pages": len(filter_pages),
        "total_widgets": total_widgets,
        "page_summary": page_summary,
    }
    print(
        f"  \u2705 PRE_DEPLOY_WIDGETS: '{dashboard_name}' — "
        f"{len(canvas_pages)} canvas pages, {total_widgets} widgets, "
        f"{len(datasets)} datasets"
    )
    return summary


def assert_dashboard_has_filters(
    serialized_dashboard: dict,
    dashboard_name: str,
    *,
    quality_gates: dict | None = None,
) -> dict:
    """Assert that a dashboard has a filters page with functional bindings.

    Every dashboard MUST include a PAGE_TYPE_GLOBAL_FILTERS page with
    at least N filter widgets (default: 3). Filters must reference a
    dataset via queryName in their encodings.

    Args:
        serialized_dashboard: The full dashboard dict.
        dashboard_name: Display name for error messages.
        quality_gates: Optional overrides from accelerator.yaml.

    Returns:
        Summary dict with filter details.

    Raises:
        GateCheckError: If no filter page exists or filter count is
            below the minimum.
    """
    min_filters = _get_threshold(quality_gates, "min_filters_per_dashboard")
    pages = serialized_dashboard.get("pages", [])

    filter_pages = [
        p for p in pages
        if p.get("pageType") == "PAGE_TYPE_GLOBAL_FILTERS"
    ]

    if not filter_pages:
        raise GateCheckError(
            "PRE_DEPLOY_FILTERS",
            f"Dashboard '{dashboard_name}' has NO filter page.\n"
            f"  Every dashboard MUST include a PAGE_TYPE_GLOBAL_FILTERS page.\n"
            f"  Use build_filters_page() from lakeview_dashboard_helpers.py.",
        )

    total_filters = 0
    unbound_filters = []
    for fp in filter_pages:
        layout = fp.get("layout", [])
        for item in layout:
            widget = item.get("widget", {})
            total_filters += 1
            # Check that filter has a query binding
            spec = widget.get("spec", {})
            encodings = spec.get("encodings", {})
            fields = encodings.get("fields", [])
            has_binding = any(
                f.get("queryName") for f in fields
            ) if fields else False
            if not has_binding:
                w_name = widget.get("name", "unnamed")
                unbound_filters.append(w_name)

    if total_filters < min_filters:
        raise GateCheckError(
            "PRE_DEPLOY_FILTER_COUNT",
            f"Dashboard '{dashboard_name}' has {total_filters} filter widget(s) "
            f"(minimum: {min_filters}).\n"
            f"  Every dashboard needs at least {min_filters} functional filters "
            f"(date range, categorical selects for key dimensions).",
        )

    summary = {
        "dashboard_name": dashboard_name,
        "filter_pages": len(filter_pages),
        "total_filters": total_filters,
        "unbound_filters": unbound_filters,
    }

    if unbound_filters:
        raise GateCheckError(
            "PRE_DEPLOY_FILTER_BINDING",
            f"Dashboard '{dashboard_name}' has {len(unbound_filters)} filter(s) "
            f"missing 'queryName' in encodings.fields[].\n"
            f"  Unbound filters: {unbound_filters}\n"
            f"  Filters without queryName appear as 'no fields or parameters selected' in the UI.\n"
            f"  FIX: Use build_filter_widget() from lakeview_dashboard_helpers.py, which always\n"
            f"  includes queryName: 'main_query'. Never hand-write filter JSON.",
        )
    else:
        print(
            f"  \u2705 PRE_DEPLOY_FILTERS: '{dashboard_name}' — "
            f"{total_filters} filters, all bound"
        )
    return summary


def assert_genie_config_complete(
    *,
    title: str,
    description: str | None,
    table_identifiers: list[str],
    general_instructions: str,
    sample_questions: list[str],
    example_sqls: list[tuple[str, str]],
    quality_gates: dict | None = None,
) -> dict:
    """Assert that Genie space configuration is complete before API call.

    Call BEFORE the Genie create/update API call. Prevents deploying
    an empty shell with no instructions, tables, or questions.

    Args:
        title: Space title.
        description: Space description (shown in UI).
        table_identifiers: List of fully qualified metric view names.
        general_instructions: Markdown instructions for Genie.
        sample_questions: List of sample question strings.
        example_sqls: List of (question, sql) tuples.
        quality_gates: Optional overrides from accelerator.yaml.

    Returns:
        Summary dict with content metrics.

    Raises:
        GateCheckError: If any required content is missing or below threshold.
    """
    min_instr = _get_threshold(quality_gates, "min_genie_instruction_chars")
    min_tables = _get_threshold(quality_gates, "min_genie_tables")
    min_questions = _get_threshold(quality_gates, "min_genie_sample_questions")
    min_sqls = _get_threshold(quality_gates, "min_genie_example_sqls")
    min_desc = _get_threshold(quality_gates, "min_genie_description_chars")

    issues = []

    if not title or not title.strip():
        issues.append("Title is empty")

    if not description or len(description.strip()) < min_desc:
        actual = len(description.strip()) if description else 0
        issues.append(
            f"Description too short ({actual} chars, need >= {min_desc}). "
            f"The description appears in the Genie UI and should summarize "
            f"what this space covers."
        )

    if len(table_identifiers) < min_tables:
        issues.append(
            f"Only {len(table_identifiers)} table identifier(s) "
            f"(need >= {min_tables}). "
            f"At least the primary metric view must be attached."
        )

    instr_len = len(general_instructions.strip()) if general_instructions else 0
    if instr_len < min_instr:
        issues.append(
            f"Instructions too short ({instr_len} chars, need >= {min_instr}). "
            f"Must cover domain context, measures, dimensions, and query rules."
        )

    if len(sample_questions) < min_questions:
        issues.append(
            f"Only {len(sample_questions)} sample question(s) "
            f"(need >= {min_questions}). "
            f"Questions appear as suggestions in the Genie chat UI."
        )

    if len(example_sqls) < min_sqls:
        issues.append(
            f"Only {len(example_sqls)} example SQL(s) "
            f"(need >= {min_sqls}). "
            f"Example SQLs teach Genie how to answer with MEASURE() syntax."
        )

    if issues:
        detail = "\n  ".join(issues)
        raise GateCheckError(
            "PRE_DEPLOY_GENIE",
            f"Genie space '{title}' configuration is incomplete:\n"
            f"  {detail}\n\n"
            f"  Do NOT call the Genie API until all content is populated.\n"
            f"  Re-run the LLM design and configuration steps.",
        )

    summary = {
        "title": title,
        "description_chars": len(description) if description else 0,
        "table_identifiers": len(table_identifiers),
        "instruction_chars": instr_len,
        "sample_questions": len(sample_questions),
        "example_sqls": len(example_sqls),
    }
    print(
        f"  \u2705 PRE_DEPLOY_GENIE: '{title}' — "
        f"{instr_len} instruction chars, {len(table_identifiers)} tables, "
        f"{len(sample_questions)} questions, {len(example_sqls)} example SQLs"
    )
    return summary


# =============================================================================
# SECTION 2: Post-Deploy API Readback Validation (Layer 2)
# =============================================================================
# Call these AFTER the API create/publish call returns successfully.
# They read the deployed object back from the API and verify that what
# was deployed matches what was intended. This catches silent API failures
# where the call succeeds but the content is not persisted.


def validate_dashboard_from_api(
    dashboard_id: str,
    expected_name: str,
    *,
    quality_gates: dict | None = None,
) -> dict:
    """Read back a deployed dashboard via Lakeview API and validate content.

    Call AFTER create_dashboard() and publish_dashboard() succeed.
    This is the ground-truth check that prevents fraudulent validation
    files (manifest says PASS but dashboard is actually empty).

    Args:
        dashboard_id: The dashboard UUID returned by the API.
        expected_name: Expected display name for verification.
        quality_gates: Optional overrides from accelerator.yaml.

    Returns:
        Ground-truth validation dict with source='api_readback'.

    Raises:
        GateCheckError: If the dashboard API object is empty or
            doesn't match expectations.
    """
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    min_widgets = _get_threshold(quality_gates, "min_widgets_per_canvas_page")
    min_filters = _get_threshold(quality_gates, "min_filters_per_dashboard")

    # GET the dashboard — use the DRAFT endpoint for structural validation
    # because the published endpoint strips page layout/widget details.
    # The draft endpoint returns the full serialized_dashboard with all
    # pages, widgets, and layout arrays intact.
    resp = w.api_client.do(
        "GET",
        f"/api/2.0/lakeview/dashboards/{dashboard_id}",
    )

    display_name = resp.get("display_name", "")
    sd_raw = resp.get("serialized_dashboard", "{}")
    sd = json.loads(sd_raw) if isinstance(sd_raw, str) else sd_raw

    # Also check publication status separately
    is_published = False
    try:
        pub_resp = w.api_client.do(
            "GET",
            f"/api/2.0/lakeview/dashboards/{dashboard_id}/published",
        )
        is_published = bool(pub_resp)
    except Exception:
        pass  # Not published yet — not a structural failure

    pages = sd.get("pages", [])
    datasets = sd.get("datasets", [])

    # Count widgets per page category
    canvas_pages = []
    filter_pages = []
    total_widgets = 0
    total_filters = 0
    page_details = []

    for page in pages:
        page_type = page.get("pageType", "PAGE_TYPE_CANVAS")
        layout = page.get("layout", [])
        page_name = page.get("displayName", page.get("name", "unnamed"))
        widget_count = len(layout)

        if page_type == "PAGE_TYPE_GLOBAL_FILTERS":
            filter_pages.append(page)
            total_filters += widget_count
        else:
            canvas_pages.append(page)
            total_widgets += widget_count

        page_details.append({
            "name": page_name,
            "type": page_type,
            "widgets": widget_count,
        })

    # Validate
    issues = []

    if total_widgets == 0:
        issues.append(
            f"Dashboard has 0 canvas widgets across {len(canvas_pages)} "
            f"canvas page(s). All pages have empty layout arrays."
        )

    for page in canvas_pages:
        layout = page.get("layout", [])
        page_name = page.get("displayName", page.get("name", "unnamed"))
        if len(layout) == 0:
            issues.append(f"Canvas page '{page_name}' has 0 widgets.")
        elif len(layout) < min_widgets:
            issues.append(
                f"Canvas page '{page_name}' has {len(layout)} widget(s) "
                f"(minimum: {min_widgets})."
            )

    if not filter_pages:
        issues.append("No filter page found in deployed dashboard.")
    elif total_filters < min_filters:
        issues.append(
            f"Dashboard has {total_filters} filter(s) "
            f"(minimum: {min_filters})."
        )

    if not datasets:
        issues.append("Dashboard has 0 datasets.")

    validation = {
        "source": "api_readback",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dashboard_id": dashboard_id,
        "display_name": display_name,
        "published": is_published,
        "datasets": len(datasets),
        "total_pages": len(pages),
        "canvas_pages": len(canvas_pages),
        "filter_pages": len(filter_pages),
        "total_canvas_widgets": total_widgets,
        "total_filters": total_filters,
        "page_details": page_details,
        "issues": issues,
        "status": "FAIL" if issues else "PASS",
    }

    if issues:
        detail = "\n  ".join(issues)
        raise GateCheckError(
            "POST_DEPLOY_DASHBOARD",
            f"Dashboard '{expected_name}' ({dashboard_id}) deployed but "
            f"API readback shows problems:\n  {detail}\n\n"
            f"  Readback summary: {json.dumps(validation, indent=2)}\n\n"
            f"  The dashboard must be rebuilt with actual widgets before "
            f"writing any validation artifact.",
        )

    print(
        f"  \u2705 POST_DEPLOY_DASHBOARD: '{display_name}' — "
        f"API confirms {total_widgets} canvas widgets, "
        f"{total_filters} filters, {len(datasets)} datasets"
    )
    return validation


def validate_genie_from_api(
    space_id: str,
    expected_title: str,
    *,
    quality_gates: dict | None = None,
) -> dict:
    """Read back a deployed Genie space via API and validate content.

    Call AFTER the Genie create/update API call succeeds.
    Reads back the space with serialized_space=true to inspect
    actual instructions, sample questions, example SQLs, and tables.

    Args:
        space_id: The Genie space UUID.
        expected_title: Expected title for verification.
        quality_gates: Optional overrides from accelerator.yaml.

    Returns:
        Ground-truth validation dict with source='api_readback'.

    Raises:
        GateCheckError: If the space is empty or misconfigured.
    """
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    min_instr = _get_threshold(quality_gates, "min_genie_instruction_chars")
    min_questions = _get_threshold(quality_gates, "min_genie_sample_questions")
    min_sqls = _get_threshold(quality_gates, "min_genie_example_sqls")
    min_desc = _get_threshold(quality_gates, "min_genie_description_chars")

    # GET the space with serialized content
    data = w.api_client.do(
        "GET",
        f"/api/2.0/genie/spaces/{space_id}",
        query={"include_serialized_space": "true"},
    )

    title = data.get("title", "")
    description = data.get("description", "") or ""
    warehouse_id = data.get("warehouse_id", "")

    # Parse serialized_space for content counts
    ss_raw = data.get("serialized_space", "{}")
    ss = json.loads(ss_raw) if isinstance(ss_raw, str) else (ss_raw or {})

    sample_questions = ss.get("config", {}).get("sample_questions", [])
    # API may store metric_views under "tables" key in read-back
    metric_views = (
        ss.get("data_sources", {}).get("metric_views", [])
        or ss.get("data_sources", {}).get("tables", [])
    )
    text_instructions = ss.get("instructions", {}).get("text_instructions", [])
    example_sqls = ss.get("instructions", {}).get("example_question_sqls", [])
    benchmarks = ss.get("benchmarks", {}).get("questions", [])

    # Calculate instruction text length (stored as multi-line arrays)
    instr_chars = sum(
        len("".join(t.get("content", []))) for t in text_instructions
    )

    # Validate
    issues = []

    if not description or len(description.strip()) < min_desc:
        actual = len(description.strip()) if description else 0
        issues.append(
            f"Description is {'empty' if actual == 0 else f'too short ({actual} chars)'}. "
            f"Need >= {min_desc} chars."
        )

    if not metric_views:
        issues.append("No metric views/tables attached to the space.")

    if instr_chars < min_instr:
        issues.append(
            f"Instructions too short ({instr_chars} chars, need >= {min_instr}). "
            f"The serialized_space has {len(text_instructions)} instruction block(s)."
        )

    if len(sample_questions) < min_questions:
        issues.append(
            f"Only {len(sample_questions)} sample question(s) "
            f"(need >= {min_questions})."
        )

    if len(example_sqls) < min_sqls:
        issues.append(
            f"Only {len(example_sqls)} example SQL(s) "
            f"(need >= {min_sqls})."
        )

    if not warehouse_id:
        issues.append("No warehouse_id set on the space.")

    validation = {
        "source": "api_readback",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "space_id": space_id,
        "title": title,
        "description_chars": len(description),
        "warehouse_id": warehouse_id,
        "metric_views": len(metric_views),
        "instruction_chars": instr_chars,
        "instruction_blocks": len(text_instructions),
        "sample_questions": len(sample_questions),
        "example_sqls": len(example_sqls),
        "benchmarks": len(benchmarks),
        "issues": issues,
        "status": "FAIL" if issues else "PASS",
    }

    if issues:
        detail = "\n  ".join(issues)
        raise GateCheckError(
            "POST_DEPLOY_GENIE",
            f"Genie space '{expected_title}' ({space_id}) deployed but "
            f"API readback shows problems:\n  {detail}\n\n"
            f"  Readback summary: {json.dumps(validation, indent=2)}\n\n"
            f"  The space must be reconfigured with complete content before "
            f"writing any validation artifact.",
        )

    print(
        f"  \u2705 POST_DEPLOY_GENIE: '{title}' — "
        f"API confirms {instr_chars} instruction chars, "
        f"{len(metric_views)} metric views, "
        f"{len(sample_questions)} questions, "
        f"{len(example_sqls)} example SQLs"
    )
    return validation


# =============================================================================
# SECTION 3: Terminal Cross-Validation Sweep (Layer 3)
# =============================================================================
# Call ONCE at the end of the entire run (before documentation).
# Reads every manifest in the output folder, GETs each deployed asset
# from the API, and produces a ground-truth validation report.


def run_cross_validation(
    output_folder: str,
    *,
    quality_gates: dict | None = None,
) -> dict:
    """Independent audit of all deployed assets against their manifests.

    Walks the output folder for manifest files, reads each one, then
    calls the API to verify the deployed asset matches the manifest's
    claims. Produces a ground_truth_validation.yaml that the
    documentation step must reference.

    Args:
        output_folder: Absolute path to the version output folder.
        quality_gates: Optional overrides from accelerator.yaml.

    Returns:
        Cross-validation report dict. Write this to
        {output_folder}/ground_truth_validation.yaml.

    Raises:
        GateCheckError: If any deployed asset fails cross-validation.
    """
    import glob

    report = {
        "source": "cross_validation_sweep",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "output_folder": output_folder,
        "dashboards": [],
        "genie_spaces": [],
        "issues": [],
        "overall_status": "PASS",
    }

    # ---- Dashboard manifests ----
    dashboard_dir = os.path.join(output_folder, "dashboards")
    if os.path.isdir(dashboard_dir):
        for manifest_path in sorted(glob.glob(
            os.path.join(dashboard_dir, "*_dashboard_manifest.json")
        )):
            try:
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
                dashboard_id = manifest.get("dashboard_id", "")
                display_name = manifest.get("display_name", "")

                if not dashboard_id:
                    report["issues"].append(
                        f"Manifest {os.path.basename(manifest_path)} has no dashboard_id"
                    )
                    continue

                # Readback from API (non-raising version)
                try:
                    result = validate_dashboard_from_api(
                        dashboard_id,
                        display_name,
                        quality_gates=quality_gates,
                    )
                    report["dashboards"].append(result)
                except GateCheckError as e:
                    report["issues"].append(str(e))
                    report["dashboards"].append({
                        "dashboard_id": dashboard_id,
                        "display_name": display_name,
                        "status": "FAIL",
                        "error": str(e),
                    })

            except (json.JSONDecodeError, OSError) as e:
                report["issues"].append(
                    f"Cannot read manifest {os.path.basename(manifest_path)}: {e}"
                )

    # ---- Genie manifests ----
    genie_dir = os.path.join(output_folder, "genie_space")
    if os.path.isdir(genie_dir):
        for manifest_path in sorted(glob.glob(
            os.path.join(genie_dir, "*_manifest.json")
        )):
            try:
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
                space_id = manifest.get("space_id", "")
                title = manifest.get("title", "")

                if not space_id:
                    report["issues"].append(
                        f"Manifest {os.path.basename(manifest_path)} has no space_id"
                    )
                    continue

                try:
                    result = validate_genie_from_api(
                        space_id,
                        title,
                        quality_gates=quality_gates,
                    )
                    report["genie_spaces"].append(result)
                except GateCheckError as e:
                    report["issues"].append(str(e))
                    report["genie_spaces"].append({
                        "space_id": space_id,
                        "title": title,
                        "status": "FAIL",
                        "error": str(e),
                    })

            except (json.JSONDecodeError, OSError) as e:
                report["issues"].append(
                    f"Cannot read manifest {os.path.basename(manifest_path)}: {e}"
                )

    # ---- Overall status ----
    all_dashboard_pass = all(
        d.get("status") == "PASS" for d in report["dashboards"]
    )
    all_genie_pass = all(
        g.get("status") == "PASS" for g in report["genie_spaces"]
    )

    if not all_dashboard_pass or not all_genie_pass or report["issues"]:
        report["overall_status"] = "FAIL"

    # ---- Summary ----
    n_dash = len(report["dashboards"])
    n_dash_pass = sum(1 for d in report["dashboards"] if d.get("status") == "PASS")
    n_genie = len(report["genie_spaces"])
    n_genie_pass = sum(1 for g in report["genie_spaces"] if g.get("status") == "PASS")

    status_icon = "\u2705" if report["overall_status"] == "PASS" else "\u274c"
    print(f"\n{'=' * 60}")
    print(f"CROSS-VALIDATION SWEEP: {status_icon} {report['overall_status']}")
    print(f"{'=' * 60}")
    print(f"  Dashboards : {n_dash_pass}/{n_dash} passed")
    print(f"  Genie      : {n_genie_pass}/{n_genie} passed")
    if report["issues"]:
        print(f"  Issues     : {len(report['issues'])}")
        for issue in report["issues"]:
            # Truncate long error messages for summary display
            short = issue.split("\n")[0][:120]
            print(f"    \u2022 {short}")
    print()

    if report["overall_status"] == "FAIL":
        raise GateCheckError(
            "CROSS_VALIDATION",
            f"Cross-validation sweep FAILED.\n"
            f"  Dashboards: {n_dash_pass}/{n_dash} passed\n"
            f"  Genie: {n_genie_pass}/{n_genie} passed\n"
            f"  Total issues: {len(report['issues'])}\n\n"
            f"  Do NOT write run_manifest.json or documentation until all \n"
            f"  deployed assets pass cross-validation.\n"
            f"  Write this report to ground_truth_validation.yaml for audit.",
        )

    return report


# =============================================================================
# SECTION 4: Validation YAML Writer
# =============================================================================
# Writes validation artifacts with a mandatory 'source' field that
# distinguishes ground-truth API readbacks from agent self-reports.


def write_ground_truth_validation(
    path: str,
    validation_data: dict,
    *,
    source: str = "api_readback",
) -> None:
    """Write a validation YAML file with source attribution.

    The source field enables the documentation step to distinguish
    between verified (api_readback, cross_validation_sweep) and
    unverified (agent_reported) validation claims.

    Args:
        path: Absolute path to write the YAML file.
        validation_data: The validation dict to write.
        source: One of 'api_readback', 'cross_validation_sweep',
            or 'agent_reported'. Default is 'api_readback'.
    """
    import yaml

    output = {
        "source": source,
        "written_at": datetime.now(timezone.utc).isoformat(),
        **validation_data,
    }

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(output, f, default_flow_style=False, sort_keys=False)

    print(f"  \u2705 Validation written ({source}): {os.path.basename(path)}")


# =============================================================================
# SECTION 5: Convenience — Full Pre-Deploy Dashboard Gate
# =============================================================================
# Combines all Layer 1 dashboard checks into a single call.


def run_dashboard_predeploy_gates(
    serialized_dashboard: dict,
    dashboard_name: str,
    *,
    required_artifacts: list[str] | None = None,
    quality_gates: dict | None = None,
) -> dict:
    """Run all pre-deploy checks for a single dashboard.

    Combines artifact existence, widget, and filter checks into one
    call. Use this as the single gate before create_dashboard().

    Args:
        serialized_dashboard: The built dashboard JSON dict.
        dashboard_name: Display name for error messages.
        required_artifacts: List of file paths that must exist.
        quality_gates: Optional overrides from accelerator.yaml.

    Returns:
        Combined summary dict.

    Raises:
        GateCheckError: On first failing check.
    """
    separator = '\u2500' * 40
    print(f"\n{separator}")
    print(f"Pre-deploy gates: {dashboard_name}")
    print(separator)

    # Check prerequisite artifacts
    if required_artifacts:
        for artifact_path in required_artifacts:
            artifact_name = os.path.basename(artifact_path)
            assert_artifact_exists(
                artifact_path,
                f"PRE_DEPLOY_ARTIFACT_{artifact_name}",
            )
            print(f"  \u2705 Artifact exists: {artifact_name}")

    # Check widgets
    widget_summary = assert_dashboard_has_widgets(
        serialized_dashboard,
        dashboard_name,
        quality_gates=quality_gates,
    )

    # Check filters
    filter_summary = assert_dashboard_has_filters(
        serialized_dashboard,
        dashboard_name,
        quality_gates=quality_gates,
    )

    return {
        "dashboard_name": dashboard_name,
        "artifacts_checked": len(required_artifacts or []),
        **widget_summary,
        **filter_summary,
    }


def run_genie_predeploy_gates(
    *,
    title: str,
    description: str | None,
    table_identifiers: list[str],
    general_instructions: str,
    sample_questions: list[str],
    example_sqls: list[tuple[str, str]],
    required_artifacts: list[str] | None = None,
    quality_gates: dict | None = None,
) -> dict:
    """Run all pre-deploy checks for a Genie space.

    Combines artifact existence and content completeness checks
    into one call. Use this as the single gate before the Genie API.

    Args:
        title: Space title.
        description: Space description.
        table_identifiers: Fully qualified metric view names.
        general_instructions: Markdown instructions.
        sample_questions: Sample question strings.
        example_sqls: (question, sql) tuples.
        required_artifacts: List of file paths that must exist.
        quality_gates: Optional overrides from accelerator.yaml.

    Returns:
        Summary dict.

    Raises:
        GateCheckError: On first failing check.
    """
    separator = '\u2500' * 40
    print(f"\n{separator}")
    print(f"Pre-deploy gates: Genie '{title}'")
    print(separator)

    # Check prerequisite artifacts
    if required_artifacts:
        for artifact_path in required_artifacts:
            artifact_name = os.path.basename(artifact_path)
            assert_artifact_exists(
                artifact_path,
                f"PRE_DEPLOY_ARTIFACT_{artifact_name}",
            )
            print(f"  \u2705 Artifact exists: {artifact_name}")

    # Check content completeness
    return assert_genie_config_complete(
        title=title,
        description=description,
        table_identifiers=table_identifiers,
        general_instructions=general_instructions,
        sample_questions=sample_questions,
        example_sqls=example_sqls,
        quality_gates=quality_gates,
    )
