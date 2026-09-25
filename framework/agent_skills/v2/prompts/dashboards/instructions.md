# Create Dashboards

> **Transport:** apply the frozen `shared/agent_transport.md` contract. Tool names are portable operations; App/Lakebase integration is optional. Runtime paths come only from `contracts/release.yaml`.

> **Always load for this stage:** `{AGENT_SKILLS_DIR}/prompts/shared/global_guardrails.md`, `{AGENT_SKILLS_DIR}/prompts/dashboards/validation.md`, `{AGENT_SKILLS_DIR}/prompts/dashboards/guardrails.md`, `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`, `{AGENT_SKILLS_DIR}/prompts/shared/sql_generation_rules.md`.
> **Failure-only:** authenticate `run_context.inputs.stage_runbooks.create_dashboards` and load only the matching section of `{AGENT_SKILLS_DIR}/prompts/dashboards/runbook.md` after a classified failure. Never load the runbook on the normal success path.


> Dashboard deployment uses `v2_dashboard_notebook.py.template` (the Deterministic Deployment Runtime).
> The LLM produces `dashboard_design.yaml` (declarative spec). The template handles compilation, deployment, and readback.
> Four-gate validation runs inside the template before API calls.


## Failure-Only Runbook Loading

Do not read `{AGENT_SKILLS_DIR}/prompts/dashboards/runbook.md` during normal execution. After this stage classifies a failure, authenticate the frozen runbook tuple, use the routing index in `{AGENT_SKILLS_DIR}/prompts/dashboards/validation.md`, and load only the matching diagnostic section. The runbook cannot weaken a gate, change the failure owner, or authorize a blind retry.

## CONTEXT ISOLATION — Read This First

Forget all execution details from prior steps (ERD parsing, synthetic data generation, metric view DDL). You do NOT need that context.

**Required authority-bearing inputs and readbacks are:**

1. Exact tool-supplied `run_context_path`, authenticated as `{run_context.output_folder}/run_context.yaml` before any sibling read — frozen resolved run configuration and executed dashboard inventory

2. `{OUTPUT_FOLDER}/step_handoff.yaml` — contains pre-formatted values (paste verbatim):
   - `metric_view_fqns[].sql_fqn` — the EXACT backtick-quoted FQN for SQL (do NOT re-derive) — contains at least one and no more than frozen `run_context.quality_gates.max_metric_views_per_domain`
   - `metric_view_fqns[].primary` — whether this is the primary metric view
   - `dashboard_display_names[].display_name` — the EXACT name for API calls (do NOT reformat)
   - `warehouse_id`, `parent_path`, `workspace_host`, `deploy_root`, `output_folder` — paste as-is
   - `catalog`, `schema` — exact resolved target coordinates; never substitute source coordinates
   - `version_suffix`, `asset_suffix` — exact frozen suffix values; never reconstruct them

3. `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` — which KPIs are IMPLEMENTED and which metric view implements each

4. `{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml` — the multi-metric-view plan including:
   - All metric views with their assigned KPIs
   - Intended NOT_IMPLEMENTED candidates with reasons/reference SQL; current-run `metric_view_validation.yaml` owns terminal status and downstream eligibility
   - Intermediate view details

5. KPI specification Dashboard Mapping — which KPIs go on which page

6. Live SQL readback for every exact handoff FQN:
   - `DESCRIBE TABLE` — deployed fields and types
   - `SHOW CREATE TABLE` — deployed Metric View definition

7. Lakeview API GET/readback after deployment — actual persisted dashboard state

### Invocation bootstrap (before any sibling-artifact read)

The invoking tool MUST supply the exact `run_context_path`. It is the only permitted bootstrap locator.

1. Read the exact raw bytes only at that path, parse one YAML mapping, and require non-empty `run_id` and a non-empty absolute `output_folder`; reject a relative output folder before path comparison.
2. Normalize the supplied path and `{run_context.output_folder}/run_context.yaml` without resolving symlinks or changing workspace-path semantics.
3. Require exact normalized-path equality. An absent supplied path/file, malformed mapping, relative output folder, or path mismatch is `DASHBOARD_INPUT_AUTHORITY_ERROR`. A permission denial, transport failure, or genuine workspace read/I/O failure is instead `WORKSPACE_IO_ERROR` (or the exact operational platform error) and MUST NOT be relabeled as malformed authority.
4. Only after this check passes, bind `OUTPUT_FOLDER` to `run_context.output_folder` and read the canonical sibling `{OUTPUT_FOLDER}/step_handoff.yaml`.

Do not scan version folders, select a latest run, accept a separate caller-provided output folder, or infer the run from the current directory. No sibling artifact may be read before this bootstrap gate passes.
Permission, transport, and genuine I/O failures retain that operational classification.

**Rules:**
- Bootstrap from the exact tool-supplied `run_context_path` before any sibling-artifact read; then read `step_handoff.yaml` before any other sibling artifact in this step
- Use `display_name` value EXACTLY as written (it is already snake_case validated)

### Validate `step_handoff.yaml` Before Use

`step_handoff.yaml` is the authoritative resolved-identity contract for this stage. The dashboard stage MUST NOT normalize, reconstruct, or overwrite it.

Validate before continuing:

1. Every `metric_view_fqns[].sql_fqn` contains exactly three separately backtick-quoted segments: `` `catalog`.`schema`.`object` ``.
2. `dashboard_display_names[]` contains one unique `id` and one non-empty `display_name` for every configured dashboard.
3. `warehouse_id`, `parent_path`, `workspace_host`, `deploy_root`, `output_folder`, target `catalog`, target `schema`, `version_suffix`, and `asset_suffix` are present and non-empty.
4. `parent_path` is a writable project subfolder, not a user home root.
5. The canonical FQN sets in `step_handoff.yaml`, `metric_view_plan.yaml`, and `metric_view_validation.yaml` are identical.
6. Every `IMPLEMENTED_AND_VALIDATED` KPI maps to exactly one Metric View in that set.
7. Every shared resolved field in `step_handoff.yaml` agrees with current-run `run_context.yaml`, including exact `step_handoff.deploy_root == run_context.runtime.deploy_root`, and the handoff dashboard ID set equals the set of `run_context.assets.dashboards[].id` values.
8. The Metric View producer checkpoint passes the exact authentication rules below; a matching FQN set by itself is insufficient.

### Authenticate the Metric View producer checkpoint

After reading the handoff raw bytes, load `metric_view_plan.yaml` and validate the strategy-specific top-level `auto_handoff_producer_checkpoint` before using any Metric View identity:

- Before selecting either strategy branch, require both `metric_view_plan.yaml` and `metric_view_validation.yaml` to contain non-empty top-level `run_id`, `asset_suffix`, and `metric_view_strategy` fields. Require exact equality for all three fields across the plan, validation, `step_handoff.yaml`, and their owning frozen values (`run_context.run_id`, `run_context.version.asset_suffix`, and `run_context.assets.metric_view_strategy`). Missing top-level fields are invalid; do not infer them from paths, identities, or a checkpoint.
- Select the branch only from that now-equal frozen `run_context.assets.metric_view_strategy` value and require it to be `auto` or `explicit`.
- For `metric_view_strategy: auto`, the checkpoint MUST be a mapping whose keys are exactly:
  `producer_step`, `producer_phase`, `status`, `run_id`, `asset_suffix`, `metric_view_strategy`, `step_handoff_path`, `step_handoff_sha256`, `metric_view_plan_payload_sha256`, `metric_view_entries`, `capability_contract_version`, and `capability_contract_sha256`.
- Require `producer_step: create_metric_views`, `producer_phase: plan_metric_views`, `status: PASS`, and `metric_view_strategy: auto`.
- Require checkpoint `run_id`, `asset_suffix`, and `metric_view_strategy` to equal the authenticated top-level plan and validation fields as well as the exact `run_context` and handoff values above.
- Require `step_handoff_path` to be the normalized canonical `{OUTPUT_FOLDER}/step_handoff.yaml` path and `step_handoff_sha256` to equal SHA-256 of the exact raw bytes just read, after the Metric View stage's final synchronized write.
- Recompute `metric_view_plan_payload_sha256` from the parsed plan after omitting the entire top-level `auto_handoff_producer_checkpoint` field: `sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()`. Require exact lowercase 64-hex equality.
- Require every stored SHA-256 value in the checkpoint to match `^[0-9a-f]{64}$` before comparing it.
- Require every `metric_view_entries[]` item to contain exactly `{name, normalized_sql_fqn, primary}`. Before normalization, require every raw executable `sql_fqn` in the handoff, `metric_view_plan.metric_views[]`, and `metric_view_validation.yaml` to contain exactly three separately backtick-quoted non-empty segments, with no surrounding whitespace or trailing content. Remove the one required outer backtick pair from each segment, unescape doubled backticks, apply Unicode `casefold()` to each segment, and join the three values unquoted with `.`. Do not resolve or otherwise rewrite identifiers. The stored checkpoint list itself MUST already be in ascending `normalized_sql_fqn` order; reject a reordered checkpoint instead of sorting it into compliance. Independently normalize and sort the complete handoff, plan, and validation lists, then require exact list equality with that already-canonical checkpoint list; do not compare only names or counts. Reject duplicate names, duplicate normalized FQNs, missing/extra entries, or any `primary` disagreement, and require exactly one `primary: true` across the complete set.
- Require `capability_contract_version` and `capability_contract_sha256` to match the plan, `metric_view_validation.yaml`, and the frozen approved capability contract resolved for this run. The digest is lowercase 64-hex SHA-256 of the exact raw contract bytes.
- Require one and only one matching `run_context.phases_completed[]` record with `step: create_metric_views`, `phase: plan_metric_views`, `checkpoint_status: VALID`, non-empty `completed_at`, and a passing fingerprint Resume Skip Gate. The phase record is separate evidence; it is not an extra producer-checkpoint key.
- For `metric_view_strategy: explicit`, require the top-level `auto_handoff_producer_checkpoint` value to be explicit YAML `null`; an absent key or auto checkpoint is forbidden. The authenticated top-level plan/validation `run_id`, `asset_suffix`, and `metric_view_strategy: explicit` are the mandatory replay binding even though no auto checkpoint exists. Authenticate exact `{name, normalized_sql_fqn, primary}` list parity across frozen `run_context.assets.metric_views[]`, handoff, plan, and validation, and require exactly one primary.

Any missing, malformed, stale, or mismatched top-level replay-binding field, or any missing, extra, malformed, stale, or mismatched checkpoint field, is `DASHBOARD_INPUT_AUTHORITY_ERROR`. Return it to the Metric View stage; do not regenerate identities, rewrite the plan/validation/checkpoint, switch runs, or accept a later manifest as a substitute.

If `step_handoff.yaml` is missing, malformed, incomplete, or inconsistent with the Metric View artifacts:

```text
❌ EXECUTION HALTED: DASHBOARD_INPUT_AUTHORITY_ERROR
Return bootstrap/shared-field defects to the upstream resolver. Return producer-checkpoint,
Metric View identity, plan, capability, or validation defects to the Metric View stage.
```

Do not derive replacement values from `run_context.yaml`, `accelerator.yaml`, directory names, or model memory. Do not modify `step_handoff.yaml` in this stage.

## Authority Hierarchy

Use the following authority boundaries throughout dashboard creation:

| Concern | Authority |
|---|---|
| Original requested dashboard inventory and design intent | `accelerator.yaml`; drift/audit evidence only after Step 0 |
| Frozen executed dashboard inventory, accepted design intent, and resolved run configuration | current-run `run_context.yaml` |
| KPI business meaning and requested KPI-to-page mapping | KPI specification |
| Exact Dashboard canvas-page inventory | KPI specification Dashboard Mapping when present; otherwise a non-empty fallback inventory |
| Dashboard structural-vs-quality classification | frozen `run_context.quality_gates.dashboard_policy` |
| Resolved Metric View FQNs, dashboard display names, warehouse, and workspace paths | `step_handoff.yaml` |
| Intended KPI-to-Metric-View allocation and terminal exclusions | `metric_view_plan.yaml` |
| KPI implementation/validation status and validated assignment | `metric_view_validation.yaml` |
| Expected Metric View design | `metric_view_design.yaml` |
| Actually deployed Metric View columns and types | live `DESCRIBE TABLE` against the exact handoff FQN |
| Actually deployed Metric View definition and measure expressions | live `SHOW CREATE TABLE` against the exact handoff FQN |
| Intended dashboard pages, datasets, widgets, and filters | validated `dashboard_design.yaml` |
| Serialized text-widget representation | exact digest-attested `build_text_widget()` return value |
| Actual deployed dashboard identity, serialized structure, and publication state | Lakeview API GET/readback |
| Asset locator and deployment-attempt evidence | dashboard manifest; never deployed-state authority |

Design and planning artifacts describe desired state. Runtime inspection describes deployed Metric View state. Lakeview API GET/readback describes deployed dashboard state. A lower-authority artifact MUST NOT override a higher-authority observation for the same concern.

If desired state conflicts with deployed state, preserve both as expected-versus-actual evidence, fail validation, and return the defect to the stage that owns it. Do not silently rewrite desired state to match the deployment, and do not claim the desired state was deployed.

---

## Role

You are a senior Databricks AI/BI dashboard architect and analytics visualization engineer.

Create production-quality **live Databricks AI/BI dashboards** using validated Metric Views and the KPI specification.

Dashboards MUST be created and managed through the **Databricks Lakeview REST API / Databricks SDK API client**.

The deliverable is a deployed and published workspace dashboard.

Do NOT treat dashboard JSON generation as the primary objective.

The objective is to produce dashboards that are:

- analytically correct;
- based only on validated metrics;
- aligned with the KPI specification;
- visually appropriate for each KPI;
- filter-compatible;
- backed by tested SQL;
- structurally valid according to the approved versioned Lakeview contract/template pinned for the run;
- deployed successfully;
- validated after deployment.

---

## ENFORCEMENT HEADER

<!-- @enforcement
  pattern: declarative_artifact + lakeview_api_execution
  architecture: three_plane (generation → control → execution → verification → manifest)
  declarative_artifact: dashboard_design.yaml (pages, widgets, datasets, filters)
  api_reference_required: lakeview_dashboard_api.md
  multi_dashboard_mandatory: true  # If current-run run_context.yaml assets.dashboards[] has N entries, create N dashboards
  filters_mandatory: true  # Every dashboard MUST have dimension filters
  validation_model: mandatory structural gates + non-blocking quality targets → metadata → semantic → deployment
  error_classifier: routes PERMISSION_DENIED to deterministic fail, API errors to LLM repair
  gates:
    - id: api_contract_loaded
      after_step: 1
      check: "lakeview_dashboard_api.md content is in memory"
    - id: design_contract_exists
      after_step: 3
      check: "file_exists('{OUTPUT_FOLDER}/dashboards/dashboard_design.yaml')"
    - id: datasets_validated
      after_step: 4
      check: "dashboard_dataset_validation.yaml contains every frozen-dashboard dataset and every row has sql_status PASS and semantic_status PASS"
    - id: dashboards_created
      after_step: 5
      check: "one exact manifest locator exists per frozen dashboard AND matching Lakeview-readback validation binds each ID to its exact handoff display name with overall_status PASS"
    - id: dashboards_published
      after_step: 6
      check: "Lakeview API readback confirms every resolved dashboard is published; manifests only record the attempt/evidence path"
-->

---

## PROHIBITED ACTIONS (this entire step)

The following actions are STRICTLY FORBIDDEN:

1. **DO NOT create only 1 dashboard when current-run `run_context.yaml assets.dashboards[]` specifies multiple** — each frozen entry MUST produce a separate deployed dashboard
2. **DO NOT create dashboards without filters** — every dashboard MUST include filter widgets for at least the primary dimensions (e.g., claim_type, line_of_business, service_month or equivalent)
3. **DO NOT create single-page dashboards when KPI spec Dashboard Mapping specifies multiple pages** — page count MUST match the mapping. A dashboard with 1 filter page + 1 canvas page is a SINGLE-PAGE dashboard (the filter page does not count). If the KPI spec maps N analytical pages, the dashboard MUST have N canvas pages + 1 filter page = N+1 total pages.
4. **DO NOT bypass `MEASURE()` syntax** — all validated KPI measures must use `MEASURE(measure_name)` from the appropriate Metric View. Each dataset references ONE metric view — do NOT mix measures from different metric views in a single dataset query. Use current-run `metric_view_validation.yaml` for the validated KPI assignment, `step_handoff.yaml` for the exact FQN, and live readback for the actual object; `metric_view_plan.yaml` remains desired-state comparison only.
5. **DO NOT construct dashboard JSON from memory** — ALWAYS use `lakeview_dashboard_api.md` as the structural authority
6. **DO NOT skip dataset SQL validation** — every dataset query must execute successfully BEFORE building the dashboard JSON
7. **DO NOT jump directly to Lakeview API** without completing the design contract (`dashboard_design.yaml`)
8. **DO NOT silently implement skipped or NOT_IMPLEMENTED KPIs in dashboard SQL** — if a KPI was SKIPPED or NOT_IMPLEMENTED in metric view validation, it stays excluded from the dashboard. NOT_IMPLEMENTED KPIs have validated reference SQL in `metric_view_plan.yaml` but are documentation-only artifacts — they do NOT appear as dashboard widgets or datasets.
9. **DO NOT create empty/placeholder widgets** — every widget must have a valid dataset with real data
10. **DO NOT improvise or use custom logic** — this prompt defines the exact sequence. Do not substitute another dashboard workflow, skip gates, or collapse numbered steps into one API call.
11. **DO NOT use `query` (string) in dataset objects** — MUST use `queryLines` (array of strings) per `lakeview_dashboard_api.md`. Using `query` causes silent rendering failures.
12. **DO NOT call `w.lakeview.create()` before Steps 1-11 are complete** — the design contract, dataset validation YAML, and preflight structural validation MUST all exist first. Jumping to API creation "because the dashboard seems simple" is the #1 cause of dashboard failures.
13. **DO NOT use the `create_dashboard` or `publish_dashboard` tools** — these tools are DISABLED. Dashboard creation MUST use the template notebook pattern (same as metric views and Genie spaces): the LLM produces `dashboard_design.yaml` (declarative spec), and `v2_dashboard_notebook.py.template` (the Deterministic Deployment Runtime) handles compilation, Lakeview API deployment, readback, and manifest writing. Any attempt to call `create_dashboard` or `publish_dashboard` directly will fail with `tool is disabled`.
14. **DO NOT serialize a text widget anywhere except the digest-attested `build_text_widget(name, markdown, position)` helper** — titles, section headers, narrative markdown, and every other text widget MUST enter the deployment runtime as semantic inputs to that helper. Inline text-widget dictionaries, copied wire-format examples, alternate text serializers, and post-helper patching are prohibited. A missing or incompatible helper is `DASHBOARD_HELPER_CONTRACT_ERROR`; there is no fallback.
15. **DO NOT hand-write filter widget JSON inline** — ALWAYS use `build_filter_widget()` or `build_filters_page()` from the digest-attested helper template. Hand-written filter JSON consistently omits `queryName` from `encodings.fields[]`, which makes filters appear as "no fields or parameters selected" in the Lakeview UI. The template function at line 454 ALWAYS includes `queryName: "main_query"`. Building dashboard JSON without the attested template callables violates this rule.
16. **DO NOT define your own widget builder functions** (e.g., `def bar(...)`, `def counter(...)`, `def line(...)`) — ALWAYS load and attest `build_bar_chart`, `build_counter`, `build_line_chart`, etc. from the exact frozen `lakeview_dashboard_helpers.py.template` path+digest. Hand-rolled builder functions have wrong signatures and produce `TypeError: bar() missing required positional argument` crashes. Execute the Step 0.8 digest-qualified loader before any helper call.
17. **DO NOT skip live Metric View readback before building datasets** — always run `DESCRIBE TABLE {metric_view_fqn}` and `SHOW CREATE TABLE {metric_view_fqn}` for every exact handoff FQN. Use returned column names in dataset SQL and filter references and the returned definition for deployed measure semantics. Source-table or planned column names may differ from deployed Metric View aliases.
18. **DO NOT use `spark.sql()` for any SQL execution** — the `spark` variable is NOT guaranteed to be available in the notebook execution context (serverless compute, job tasks). ALL SQL must go through the Statement Execution API (`w.statement_execution.execute_statement()`) or the template helper functions (`describe_metric_view()`, `validate_dataset_sql()`, `build_validated_dataset()`), which now use the Statement Execution API internally. Using `spark.sql()` will cause `NameError: name 'spark' is not defined` and crash the pipeline.
19. **DO NOT set `PARENT_PATH` to the user's home root** (e.g., `/Users/{username}`) — the service principal running the pipeline does NOT have create permission there. `step_handoff.yaml.parent_path` MUST already identify a writable project subfolder (e.g., `/Users/{username}/databricks-aibi-design-first-accelerator/kpi_domains/{domain}/generated_outputs/{version}/dashboards`). Consume it verbatim. If it is missing or invalid, HALT with `DASHBOARD_INPUT_AUTHORITY_ERROR`; do not reconstruct it locally.

### HARD STOP RULE: No Divergence from This Prompt

If the executing agent:
- Skips reading `lakeview_dashboard_api.md` and constructs JSON from model knowledge → **INVALID**
- Creates 1 dashboard when 2+ are configured → **INVALID**
- Creates 1 canvas page per dashboard when KPI spec maps multiple pages → **INVALID**
- Calls `w.lakeview.create()` without first writing `dashboard_design.yaml` → **INVALID**
- Uses `"query": "..."` instead of `"queryLines": ["..."]` in datasets → **INVALID**
- Omits filter widgets entirely → **INVALID**
- Skips dataset SQL execution validation → **INVALID**
- Hand-writes filter JSON without using `build_filter_widget()` / `build_filters_page()` → **INVALID** (consistently omits `queryName`)
- Constructs or patches any serialized text-widget object outside `build_text_widget()` → **INVALID**
- Builds dataset SQL from `erd_parsed.yaml`, `kpi_metric_mapping.yaml`, or a design artifact without first running live `DESCRIBE TABLE` and `SHOW CREATE TABLE` for every exact handoff FQN → **INVALID**
- Defines its own `bar()`, `counter()`, `line()` or similar widget builder functions instead of importing from the template → **INVALID** (signature mismatch causes TypeError crashes)
- Uses `spark.sql()` for any SQL execution → **INVALID** (causes `NameError: name 'spark' is not defined` on serverless compute; use Statement Execution API or template helpers instead)

Any of these invalidate the dashboard and require re-execution from Step 1 of this prompt.

### Multi-Dashboard Enforcement

If `run_context.yaml assets.dashboards[]` contains N entries, this step MUST produce:
- N separate dashboard_design sections
- N separate Lakeview API POST calls
- N separate manifest JSON files
- N published dashboards

Creating fewer than N dashboards is a pipeline failure, not a partial success.

### Page-Contract Enforcement

The KPI spec's **Dashboard Mapping** section defines pages for each dashboard. When a mapping is
present, each mapped page becomes exactly one `PAGE_TYPE_CANVAS` page and the ordered canvas-page
inventory MUST equal the mapping. The mapped count overrides the frozen
`min_canvas_pages_per_dashboard` quality target and every informal page-count heuristic.

**Common failure mode:** The agent collapses all KPIs onto a single canvas page "for simplicity" or "because there are only 6 widgets." This is PROHIBITED regardless of widget count. If the KPI spec maps 2 pages (e.g., "Executive Summary" + "Trend Analysis"), the dashboard MUST have 2 canvas pages.

**Counting rule:**
- `PAGE_TYPE_GLOBAL_FILTERS` pages do NOT count as analytical pages
- Only `PAGE_TYPE_CANVAS` pages count
- If KPI spec maps P pages → dashboard has P canvas pages + 1 filter page = P+1 total pages

When no Dashboard Mapping exists for a dashboard, at least one non-empty canvas page is the
structural requirement. In that fallback branch only,
`run_context.quality_gates.min_canvas_pages_per_dashboard` remains a preferred quality target; a
miss is recorded as `WARN` and does not authorize invented filler pages.

**Validation (GATE 3.1):** After writing `dashboard_design.yaml`, compare the exact ordered canvas
page IDs with the resolved page contract. A mapped-page omission, addition, rename, reorder, or
collapse is a structural failure and HALTS before dataset SQL. A fallback page-count target miss is
not a structural failure.

### Filter Enforcement

Every dashboard MUST include:
- A global-filter page meeting frozen structural field `min_filter_pages_per_dashboard`
- At least one functional filter whenever the resolved design has an eligible dimension
- The frozen `min_filters_per_dashboard` count as a non-blocking quality target
- Date/time range filter if temporal dimensions exist
- Filters MUST be functional (bound to actual dataset columns)
- Dashboard without filters = pipeline failure

### Structural Gates vs Quality Targets

Apply the frozen `run_context.quality_gates.dashboard_policy` without local reinterpretation:

- **Structural gates** protect authority, executability, and deployed-state integrity: exact mapped
  pages (or a non-empty fallback canvas inventory), non-empty canvas pages, required global-filter
  page, valid filter bindings, validated dataset SQL, resolvable widget fields, exact API readback,
  and confirmed publication. A structural failure blocks deployment or the canonical manifest and
  results in `FAIL`.
- **Quality targets** are the preferred fallback page count, widget-density range, visualization
  diversity, filter count, and primary-KPI context count. Evaluate every target, record expected and
  actual values, and use `PASS` or `WARN`. Any `WARN` makes the Dashboard stage
  `PARTIAL_SUCCESS` but does not block deployment or the manifest.

Do not promote a target into a hard gate, downgrade a structural gate to a target, or use a target
to change an authoritative page mapping.

---

# Core Principle

Dashboard creation MUST follow this dependency chain:

```text
KPI specification
        +
metric_view_plan.yaml / metric_view_validation.yaml
        +
step_handoff.yaml resolved identities
        ↓
live DESCRIBE TABLE + SHOW CREATE TABLE
        ↓
Validated KPI inventory
        ↓
Dashboard analytical design
        ↓
Dataset design
        ↓
SQL execution validation
        ↓
Widget design
        ↓
serialized_dashboard
        ↓
Lakeview API
        ↓
GET persisted dashboard (deployed truth)
        ↓
Publish
        ↓
Post-deployment validation
```

Do not skip stages.

A dashboard API call succeeding does NOT prove that the dashboard is analytically or visually correct. Planning and design artifacts define what was intended; only live Metric View inspection and Lakeview API readback establish what is deployed.

---

# Step 0.8: Load and Attest Dashboard Helpers (EXECUTE BEFORE STEP 1)

Use project helpers defined by:

```text
lakeview_dashboard_api.md
```

and:

```text
framework/templates/lakeview_dashboard_helpers.py.template
framework/templates/gate_checks.py
```

where configured.

**MANDATORY**: Both files MUST be loaded from the exact frozen path-and-digest references in `run_context.templates`. `gate_checks.py` provides programmatic enforcement that PREVENTS deployment of empty or incomplete dashboards. A file with the expected basename, a module already present in `sys.modules`, or an unverified copy in `/tmp` is not authoritative.

### How to Load the Template Helpers

The release-selected helper may have a `.py` or `.template` extension and must be copied to a digest-qualified `.py` path before loading. Populate all four notebook placeholders below exactly from the already authenticated `run_context`; use this boilerplate at the top of every `execute_python` call that builds dashboards.

Use the **G-12 canonical path derivation** from `{AGENT_SKILLS_DIR}/prompts/shared/global_guardrails.md`:

```python
import hashlib
import importlib.util
import inspect
import os
import re
import shutil
import sys
from databricks.sdk import WorkspaceClient

# Notebook placeholders: populate verbatim from the authenticated run_context.
GATE_CHECKS_PATH = "<run_context.templates.gate_checks.path>"
GATE_CHECKS_SHA256 = "<run_context.templates.gate_checks.sha256>"
DASHBOARD_HELPERS_PATH = "<run_context.templates.lakeview_dashboard_helpers.path>"
DASHBOARD_HELPERS_SHA256 = "<run_context.templates.lakeview_dashboard_helpers.sha256>"

_templates = run_context.get("templates") if isinstance(run_context, dict) else None
_gate_ref = _templates.get("gate_checks") if isinstance(_templates, dict) else None
_helpers_ref = (
    _templates.get("lakeview_dashboard_helpers") if isinstance(_templates, dict) else None
)
for _label, _ref in (("gate_checks", _gate_ref), ("dashboard_helpers", _helpers_ref)):
    if (
        not isinstance(_ref, dict)
        or not isinstance(_ref.get("path"), str)
        or not _ref["path"]
        or not isinstance(_ref.get("sha256"), str)
    ):
        raise RuntimeError(
            f"DASHBOARD_HELPER_CONTRACT_ERROR: frozen {_label} path/hash mapping is missing or malformed"
        )
_expected_refs = (
    _gate_ref["path"],
    _gate_ref["sha256"],
    _helpers_ref["path"],
    _helpers_ref["sha256"],
)
_placeholder_refs = (
    GATE_CHECKS_PATH,
    GATE_CHECKS_SHA256,
    DASHBOARD_HELPERS_PATH,
    DASHBOARD_HELPERS_SHA256,
)
if _placeholder_refs != _expected_refs:
    raise RuntimeError("DASHBOARD_HELPER_CONTRACT_ERROR: notebook helper references are not the frozen run_context tuple")

# G-12: exact helper paths must be inside the canonical templates directory
# derived from the already authenticated handoff deploy_root.
deploy_root = step_handoff.get("deploy_root")
if not deploy_root:
    raise RuntimeError("DASHBOARD_INPUT_AUTHORITY_ERROR: step_handoff.yaml is missing deploy_root")
workspace_host = step_handoff.get("workspace_host")
warehouse_id = step_handoff.get("warehouse_id")
parent_path = step_handoff.get("parent_path")
OUTPUT_FOLDER = step_handoff.get("output_folder")
quality_gates = run_context.get("quality_gates")
if (
    not all(
        isinstance(value, str) and bool(value)
        for value in (workspace_host, warehouse_id, parent_path, OUTPUT_FOLDER)
    )
    or not isinstance(quality_gates, dict)
):
    raise RuntimeError(
        "DASHBOARD_INPUT_AUTHORITY_ERROR: frozen runtime/dashboard values are missing"
    )
dashboard_policy = quality_gates.get("dashboard_policy")
dashboard_target_fields = [
    "min_canvas_pages_per_dashboard",
    "min_widgets_per_canvas_page",
    "max_widgets_per_canvas_page",
    "min_visualization_types_per_dashboard",
    "min_filters_per_dashboard",
    "min_widget_contexts_per_primary_kpi",
]
if not (
    isinstance(dashboard_policy, dict)
    and dashboard_policy.get("policy_id") == "DASHBOARD_GATE_POLICY_V1"
    and dashboard_policy.get("mapped_page_requirement")
    == "EXACT_MAPPING_INVENTORY"
    and dashboard_policy.get("unmapped_page_requirement")
    == "NON_EMPTY_CANVAS_INVENTORY"
    and dashboard_policy.get("structural_gate_fields")
    == ["min_filter_pages_per_dashboard"]
    and dashboard_policy.get("structural_gates") == [
        "PAGE_CONTRACT_PRESERVED",
        "CANVAS_PAGES_NONEMPTY",
        "GLOBAL_FILTER_PAGE_PRESENT",
        "FILTER_BINDINGS_VALID",
        "DATASET_SQL_VALID",
        "WIDGET_REFERENCES_VALID",
        "API_READBACK_MATCHES_DESIGN",
        "PUBLISHED_STATE_CONFIRMED",
    ]
    and dashboard_policy.get("quality_target_fields")
    == dashboard_target_fields
    and dashboard_policy.get("quality_target_miss") == {
        "target_status": "WARN",
        "stage_status": "PARTIAL_SUCCESS",
        "blocks_deployment": False,
        "blocks_manifest": False,
    }
    and all(field in quality_gates for field in dashboard_target_fields)
    and "min_filter_pages_per_dashboard" in quality_gates
    and all(
        type(quality_gates[field]) is int and quality_gates[field] > 0
        for field in dashboard_target_fields + ["min_filter_pages_per_dashboard"]
    )
    and quality_gates["min_widgets_per_canvas_page"]
    <= quality_gates["max_widgets_per_canvas_page"]
):
    raise RuntimeError(
        "DASHBOARD_INPUT_AUTHORITY_ERROR: frozen dashboard gate classification is missing or incompatible"
    )
w = WorkspaceClient(host=workspace_host)
_bound_workspace_host = str(getattr(w.config, "host", "")).rstrip("/")
if _bound_workspace_host != workspace_host.rstrip("/"):
    raise RuntimeError(
        "DASHBOARD_INPUT_AUTHORITY_ERROR: WorkspaceClient host does not match frozen handoff"
    )
templates_dir = os.path.normpath(f"{deploy_root}/framework/templates")
for _source_path in (GATE_CHECKS_PATH, DASHBOARD_HELPERS_PATH):
    if os.path.dirname(os.path.normpath(_source_path)) != templates_dir:
        raise RuntimeError("DASHBOARD_HELPER_CONTRACT_ERROR: frozen helper path is outside canonical templates_dir")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
for _digest in (GATE_CHECKS_SHA256, DASHBOARD_HELPERS_SHA256):
    if not isinstance(_digest, str) or not _HEX64.fullmatch(_digest):
        raise RuntimeError("DASHBOARD_HELPER_CONTRACT_ERROR: helper digest must be lowercase SHA-256")

_bundle_sha = hashlib.sha256(
    f"{GATE_CHECKS_SHA256}:{DASHBOARD_HELPERS_SHA256}".encode("ascii")
).hexdigest()
_tmp_dir = f"/tmp/pipeline_python/{_bundle_sha}"
os.makedirs(_tmp_dir, exist_ok=True)

def _verified_copy(source_path, expected_sha256, destination_name):
    try:
        with open(source_path, "rb") as handle:
            source_bytes = handle.read()
    except (OSError, PermissionError) as exc:
        raise RuntimeError(f"DASHBOARD_HELPER_CONTRACT_ERROR: cannot read {source_path}: {exc}") from exc
    actual_source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if actual_source_sha256 != expected_sha256:
        raise RuntimeError(f"DASHBOARD_HELPER_CONTRACT_ERROR: source digest mismatch for {source_path}")
    destination_path = os.path.join(_tmp_dir, destination_name)
    try:
        shutil.copyfile(source_path, destination_path)
        with open(destination_path, "rb") as handle:
            copied_sha256 = hashlib.sha256(handle.read()).hexdigest()
    except OSError as exc:
        raise RuntimeError(
            f"DASHBOARD_HELPER_CONTRACT_ERROR: cannot copy/read attested helper {source_path}: {exc}"
        ) from exc
    if copied_sha256 != expected_sha256:
        raise RuntimeError(f"DASHBOARD_HELPER_CONTRACT_ERROR: copied digest mismatch for {destination_path}")
    return destination_path

_gate_copy = _verified_copy(GATE_CHECKS_PATH, GATE_CHECKS_SHA256, "gate_checks.py")
_helpers_copy = _verified_copy(
    DASHBOARD_HELPERS_PATH,
    DASHBOARD_HELPERS_SHA256,
    "lakeview_dashboard_helpers.py",
)

def _load_attested_module(module_name, module_path, expected_sha256):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"DASHBOARD_HELPER_CONTRACT_ERROR: cannot create loader for {module_path}")
    try:
        module = importlib.util.module_from_spec(spec)
    except (ImportError, AttributeError, TypeError) as exc:
        raise RuntimeError(
            f"DASHBOARD_HELPER_CONTRACT_ERROR: cannot construct module for {module_path}: {exc}"
        ) from exc
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise RuntimeError(
            f"DASHBOARD_HELPER_CONTRACT_ERROR: module execution failed for {module_path}: {exc}"
        ) from exc
    loaded_file = getattr(module, "__file__", None)
    if not isinstance(loaded_file, str) or not loaded_file:
        sys.modules.pop(module_name, None)
        raise RuntimeError(
            f"DASHBOARD_HELPER_CONTRACT_ERROR: loaded module has no file for {module_name}"
        )
    loaded_path = os.path.normpath(os.path.abspath(loaded_file))
    expected_path = os.path.normpath(os.path.abspath(module_path))
    try:
        with open(loaded_path, "rb") as handle:
            loaded_sha256 = hashlib.sha256(handle.read()).hexdigest()
    except OSError as exc:
        sys.modules.pop(module_name, None)
        raise RuntimeError(
            f"DASHBOARD_HELPER_CONTRACT_ERROR: cannot attest loaded file for {module_name}: {exc}"
        ) from exc
    if loaded_path != expected_path or loaded_sha256 != expected_sha256:
        sys.modules.pop(module_name, None)
        raise RuntimeError(f"DASHBOARD_HELPER_CONTRACT_ERROR: loaded-file attestation failed for {module_name}")
    return module

_gate_module_name = f"gate_checks_{GATE_CHECKS_SHA256[:16]}"
gate_checks_module = _load_attested_module(
    _gate_module_name, _gate_copy, GATE_CHECKS_SHA256
)

_gate_symbols = ("GateCheckError", "validate_dashboard_from_api")
for _name in _gate_symbols:
    _symbol = getattr(gate_checks_module, _name, None)
    if not callable(_symbol) or getattr(_symbol, "__module__", None) != _gate_module_name:
        raise RuntimeError(f"DASHBOARD_HELPER_CONTRACT_ERROR: unattested gate symbol {_name}")

_validator = gate_checks_module.validate_dashboard_from_api
try:
    _validator_signature = inspect.signature(_validator)
except (TypeError, ValueError) as exc:
    raise RuntimeError(
        f"DASHBOARD_HELPER_CONTRACT_ERROR: dashboard validator signature unavailable: {exc}"
    ) from exc
_validator_parameters = list(_validator_signature.parameters.values())
_validator_names = [parameter.name for parameter in _validator_parameters]
if _validator_names != [
    "workspace_client", "dashboard_id", "display_name", "quality_gates", "expected"
]:
    raise RuntimeError(
        "DASHBOARD_HELPER_CONTRACT_ERROR: expected "
        "validate_dashboard_from_api(workspace_client, dashboard_id, display_name, quality_gates=..., expected=...)"
    )
if (
    any(
        parameter.kind
        not in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        for parameter in _validator_parameters[:3]
    )
    or _validator_parameters[3].kind
    not in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
):
    raise RuntimeError(
        "DASHBOARD_HELPER_CONTRACT_ERROR: incompatible canonical dashboard validator signature"
    )

_sentinel = object()
try:
    _validator_signature.bind(
        _sentinel, _sentinel, _sentinel, quality_gates=_sentinel, expected=_sentinel
    )
except TypeError as exc:
    raise RuntimeError(
        f"DASHBOARD_HELPER_CONTRACT_ERROR: incompatible dashboard validator signature: {exc}"
    ) from exc

# The dependent helper may import `gate_checks` internally. Install this
# compatibility alias only after the gate module's file, callables, and
# canonical validator signature are fully attested.
sys.modules["gate_checks"] = gate_checks_module
_helpers_module_name = f"lakeview_dashboard_helpers_{DASHBOARD_HELPERS_SHA256[:16]}"
dashboard_helpers_module = _load_attested_module(
    _helpers_module_name, _helpers_copy, DASHBOARD_HELPERS_SHA256
)

_helper_symbols = (
    "build_dataset", "build_text_widget", "build_counter",
    "build_bar_chart", "build_line_chart", "build_filter_widget",
    "build_filters_page", "build_canvas_page", "build_serialized_dashboard",
    "deploy_dashboard", "describe_metric_view", "validate_column_refs",
    "validate_dataset_sql", "build_validated_dataset", "_execute_sql_via_api",
)
for _name in _helper_symbols:
    _symbol = getattr(dashboard_helpers_module, _name, None)
    if not callable(_symbol) or getattr(_symbol, "__module__", None) != _helpers_module_name:
        raise RuntimeError(f"DASHBOARD_HELPER_CONTRACT_ERROR: unattested dashboard helper symbol {_name}")

# Verify the exact documented invocation surface without executing any helper.
_signature_calls = {
    "build_dataset": ((_sentinel, _sentinel, _sentinel), {}),
    "build_text_widget": ((_sentinel, _sentinel, _sentinel), {}),
    "build_counter": ((_sentinel,) * 7, {}),
    "build_bar_chart": ((_sentinel,) * 8, {}),
    "build_line_chart": ((_sentinel,) * 8, {}),
    "build_filter_widget": ((_sentinel,) * 6, {}),
    "build_filters_page": ((_sentinel, _sentinel), {}),
    "build_canvas_page": ((_sentinel, _sentinel, _sentinel), {}),
    "build_serialized_dashboard": ((_sentinel, _sentinel, _sentinel), {}),
    "deploy_dashboard": (
        (_sentinel,) * 6,
        {
            "required_artifacts": _sentinel,
            "quality_gates": _sentinel,
            "output_folder": _sentinel,
        },
    ),
    "describe_metric_view": ((_sentinel, _sentinel), {}),
    "validate_column_refs": ((_sentinel, _sentinel, _sentinel), {}),
    "validate_dataset_sql": ((_sentinel, _sentinel, _sentinel), {}),
    "build_validated_dataset": ((_sentinel,) * 4, {}),
    "_execute_sql_via_api": ((_sentinel, _sentinel), {}),
}
try:
    for _name, (_args, _kwargs) in _signature_calls.items():
        inspect.signature(getattr(dashboard_helpers_module, _name)).bind(*_args, **_kwargs)
except (TypeError, ValueError) as exc:
    raise RuntimeError(
        f"DASHBOARD_HELPER_CONTRACT_ERROR: incompatible helper signature: {exc}"
    ) from exc

GateCheckError = gate_checks_module.GateCheckError
validate_dashboard_from_api = gate_checks_module.validate_dashboard_from_api
for _name in _helper_symbols:
    globals()[_name] = getattr(dashboard_helpers_module, _name)

# NOTE: describe_metric_view(fqn, warehouse_id), validate_dataset_sql(sql, name, warehouse_id),
# and build_validated_dataset(name, sql, display_name, warehouse_id) now require warehouse_id.
# NEVER use spark.sql() — it is not available in this execution context.
```

There is no fixed-name import, `sys.path` mutation, hashless copy, alternate helper, or manual-validation fallback. A missing/incompatible symbol, source/copy/load digest mismatch, or failed file attestation HALTS with `DASHBOARD_HELPER_CONTRACT_ERROR` and is owned by the Dashboard stage/release contract. Do not reconstruct any helper in generated code.

`build_text_widget()` is the sole executable serialization authority for text widgets. The design
artifact may declare only semantic text intent (`id`, `content`, and `position`); it must not contain
Lakeview text-widget wire keys. The runtime must call this exact attested helper once for each text
widget and must not wrap, merge, patch, or reconstruct its returned widget object. The Lakeview API
reference remains the release schema authority, while this helper is the only approved code path
that emits that schema for text widgets.

**DO NOT define your own `bar()`, `counter()`, `line()`, or any other shorthand function.** The template provides the canonical builders. Defining your own function with a different signature is the #1 cause of `TypeError: bar() missing required positional argument` failures.

Inline widget builders are structurally prohibited because signature drift produces runtime
`TypeError` failures. Always use the digest-attested template callables.

---

## MANDATORY: Use Deterministic Helpers

The `lakeview_dashboard_helpers.py.template` provides **programmatic builders** that guarantee structurally valid dashboard JSON. The LLM decides WHAT goes in (which KPIs, chart types, filters) but MUST use these builders to construct the JSON.

**Execution-order precondition:** the invocation-bootstrap, handoff-parity, and Metric View
producer-checkpoint gates at the start of this prompt must pass first. Then the physically preceding
**Step 0.8: Load and Attest Dashboard Helpers** must succeed before running this workflow or any
later fence that names a helper callable. No ambient or undefined helper symbol is permitted.

**Required workflow:**

```python
# 1. Discover actual deployed Metric View columns (authority for this field)
#    For multi-metric-view domains: describe EACH metric view separately
#    Use metric_view_validation.yaml for eligible KPI assignments;
#    compare metric_view_plan.yaml as desired-state evidence
for mv_fqn in all_metric_view_fqns:
    columns_by_metric_view[mv_fqn] = describe_metric_view(mv_fqn, warehouse_id)
    validate_column_refs(
        columns_by_metric_view[mv_fqn],
        dataset_spec["field_refs"],
        f"datasets_for_{mv_fqn}",
    )

# 2. Build datasets WITH validation (SQL must execute before assembly)
#    Each dataset references ONE metric view — never mix measures across metric views
dataset_name = "ds_name"
ds = build_validated_dataset(dataset_name, sql, "Display Name", warehouse_id)

# 3. Build filters page using shared dataset (deterministic structure)
filters_page = build_filters_page(dataset_name, filter_dimensions)
filter_fields = [
    field
    for item in filters_page.get("layout", [])
    for field in item.get("widget", {}).get("spec", {}).get("encodings", {}).get("fields", [])
]
if not filter_fields or not all(
    field.get("queryName") == "main_query" for field in filter_fields
):
    raise GateCheckError("PRE_DEPLOY_FILTERS: missing canonical main_query binding")
deployed_field_names = {
    field_name
    for deployed_columns in columns_by_metric_view.values()
    for field_name in deployed_columns
}
if not all(field.get("fieldName") in deployed_field_names for field in filter_fields):
    raise GateCheckError("PRE_DEPLOY_FILTERS: filter references an undeployed field")
# NOTE: A filter widget with fieldName but NO queryName is structurally invalid for Lakeview UI binding.

# 4. Build canvas widgets using builder functions
counter_display_name = "Metric label"
widget = build_counter(name, dataset_name, field_name, counter_display_name, title, agg, position)
widget = build_bar_chart(name, dataset_name, x_field, y_field, y_display, title, agg, position)
widget = build_line_chart(name, dataset_name, x_field, y_field, y_display, title, agg, position)
text_widget = build_text_widget(text_name, markdown, position)

# 5. Derive expected readback counts independently from the two validated contracts.
#    Never use deployment-result or API-readback counts as expected values.
import os
import yaml

def _require_count_contract(condition, message):
    if not condition:
        raise GateCheckError(f"PRE_DEPLOY_EXPECTED_COUNTS: {message}")

class _DashboardUniqueKeyLoader(yaml.SafeLoader):
    pass

def _construct_unique_dashboard_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                "found an unhashable mapping key", key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping

_DashboardUniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_dashboard_mapping,
)

def _load_unique_dashboard_yaml(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.load(handle, Loader=_DashboardUniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise GateCheckError(
            f"PRE_DEPLOY_EXPECTED_COUNTS: malformed or duplicate-key YAML at {path}: {exc}"
        ) from exc

design_path = os.path.join(OUTPUT_FOLDER, "dashboards", "dashboard_design.yaml")
dataset_validation_path = os.path.join(
    OUTPUT_FOLDER, "dashboards", "dashboard_dataset_validation.yaml"
)
validated_dashboard_design = _load_unique_dashboard_yaml(design_path)
validated_dataset_evidence = _load_unique_dashboard_yaml(dataset_validation_path)

_require_count_contract(
    isinstance(validated_dashboard_design, dict)
    and isinstance(validated_dashboard_design.get("dashboards"), list),
    "validated dashboard_design.yaml has no dashboards list",
)
_require_count_contract(
    isinstance(validated_dataset_evidence, dict)
    and isinstance(validated_dataset_evidence.get("datasets"), list),
    "validated dashboard_dataset_validation.yaml has no datasets list",
)

dashboard_specs = validated_dashboard_design["dashboards"]
dataset_validation_rows = validated_dataset_evidence["datasets"]
expected_readback_counts_by_dashboard = {}

for dashboard_spec in dashboard_specs:
    _require_count_contract(isinstance(dashboard_spec, dict), "dashboard spec is not a mapping")
    dashboard_name = dashboard_spec.get("name")
    design_pages = dashboard_spec.get("pages")
    design_filters = dashboard_spec.get("filters")
    page_contract = dashboard_spec.get("page_contract")
    quality_target_evaluation = dashboard_spec.get("quality_target_evaluation")
    _require_count_contract(
        isinstance(dashboard_name, str) and dashboard_name,
        "dashboard name is missing",
    )
    _require_count_contract(
        dashboard_name not in expected_readback_counts_by_dashboard,
        f"duplicate dashboard design for {dashboard_name!r}",
    )
    _require_count_contract(
        isinstance(design_pages, list),
        f"pages missing for {dashboard_name!r}",
    )
    _require_count_contract(
        isinstance(design_filters, list),
        f"filters missing for {dashboard_name!r}",
    )
    _require_count_contract(
        isinstance(page_contract, dict),
        f"page contract missing for {dashboard_name!r}",
    )
    _require_count_contract(
        isinstance(quality_target_evaluation, dict)
        and set(quality_target_evaluation) == {"status", "checks"}
        and quality_target_evaluation.get("status") in {"PASS", "WARN"}
        and isinstance(quality_target_evaluation.get("checks"), list)
        and len(quality_target_evaluation["checks"])
        == len(dashboard_target_fields)
        and {
            item.get("field")
            for item in quality_target_evaluation["checks"]
            if isinstance(item, dict)
        } == set(dashboard_target_fields)
        and all(
            isinstance(item, dict)
            and set(item) == {"field", "expected", "actual", "status"}
            and item.get("status") in {"PASS", "WARN"}
            for item in quality_target_evaluation["checks"]
        ),
        f"quality-target evaluation missing or incomplete for {dashboard_name!r}",
    )
    quality_check_statuses = [
        item["status"] for item in quality_target_evaluation["checks"]
    ]
    _require_count_contract(
        quality_target_evaluation["status"]
        == ("PASS" if all(status == "PASS" for status in quality_check_statuses) else "WARN"),
        f"quality-target aggregate status is inconsistent for {dashboard_name!r}",
    )

    widget_count = 0
    design_page_ids = []
    for design_page in design_pages:
        _require_count_contract(
            isinstance(design_page, dict)
            and design_page.get("page_type") == "CANVAS"
            and isinstance(design_page.get("id"), str)
            and bool(design_page.get("id"))
            and isinstance(design_page.get("widgets"), list),
            f"invalid CANVAS page/widgets contract for {dashboard_name!r}",
        )
        design_page_ids.append(design_page["id"])
        widget_count += len(design_page["widgets"])
        _require_count_contract(
            bool(design_page["widgets"])
            and all(
                isinstance(widget_spec, dict)
                for widget_spec in design_page["widgets"]
            ),
            f"non-mapping widget in {dashboard_name!r}",
        )
    _require_count_contract(
        bool(design_page_ids) and len(design_page_ids) == len(set(design_page_ids)),
        f"empty or duplicate canvas page inventory for {dashboard_name!r}",
    )
    page_resolution_source = page_contract.get("resolution_source")
    expected_page_ids = page_contract.get("expected_page_ids")
    _require_count_contract(
        page_resolution_source
        in {"KPI_SPEC_DASHBOARD_MAPPING", "QUALITY_TARGET_FALLBACK"}
        and set(page_contract) == {
            "resolution_source", "expected_page_ids", "actual_page_ids",
            "structural_status",
        }
        and isinstance(expected_page_ids, list)
        and all(isinstance(item, str) and bool(item) for item in expected_page_ids)
        and page_contract.get("actual_page_ids") == design_page_ids
        and page_contract.get("structural_status") == "PASS",
        f"invalid page contract for {dashboard_name!r}",
    )
    if page_resolution_source == "KPI_SPEC_DASHBOARD_MAPPING":
        _require_count_contract(
            expected_page_ids == design_page_ids,
            f"mapped page inventory mismatch for {dashboard_name!r}",
        )
    else:
        _require_count_contract(
            expected_page_ids == [],
            f"fallback page contract invented mapped pages for {dashboard_name!r}",
        )

    expected_readback_counts_by_dashboard[dashboard_name] = {
        # Filled from the independently validated dataset inventory below.
        "dataset_count": None,
        "canvas_page_count": len(design_pages),
        # The pinned compiler emits one global-filter page iff filters are present.
        "filter_page_count": 1 if design_filters else 0,
        "widget_count": widget_count,
        "filter_count": len(design_filters),
    }

validation_dashboard_names = set()
validated_dataset_names_by_dashboard = {
    dashboard_name: set() for dashboard_name in expected_readback_counts_by_dashboard
}
for dataset_row in dataset_validation_rows:
    _require_count_contract(isinstance(dataset_row, dict), "dataset validation row is not a mapping")
    dashboard_name = dataset_row.get("dashboard")
    dataset_name = dataset_row.get("name")
    _require_count_contract(
        dashboard_name in expected_readback_counts_by_dashboard,
        f"dataset validation references unknown dashboard {dashboard_name!r}",
    )
    _require_count_contract(
        isinstance(dataset_name, str) and dataset_name,
        f"dataset validation has no name for {dashboard_name!r}",
    )
    _require_count_contract(
        dataset_row.get("sql_status") == "PASS"
        and dataset_row.get("semantic_status") == "PASS",
        f"dataset {dataset_name!r} is not fully validated for {dashboard_name!r}",
    )
    _require_count_contract(
        dataset_name not in validated_dataset_names_by_dashboard[dashboard_name],
        f"duplicate dataset validation row {dataset_name!r} for {dashboard_name!r}",
    )
    validation_dashboard_names.add(dashboard_name)
    validated_dataset_names_by_dashboard[dashboard_name].add(dataset_name)

_require_count_contract(
    validation_dashboard_names == set(expected_readback_counts_by_dashboard),
    "dataset-validation dashboard inventory does not equal the design inventory",
)
for dashboard_name in expected_readback_counts_by_dashboard:
    validated_dataset_names = validated_dataset_names_by_dashboard[dashboard_name]
    expected_readback_counts_by_dashboard[dashboard_name]["dataset_count"] = len(
        validated_dataset_names
    )

def _require_dashboard_readback(condition, message):
    if not condition:
        raise GateCheckError(f"POST_DEPLOY_DASHBOARD: {message}")


# 6–7. Deploy and attest every frozen dashboard exactly once. This mapping is assembled from the
# validated design/compiler output and must not be sourced from manifests or API responses.
_require_count_contract(
    "deployment_inputs_by_dashboard" in globals(),
    "compiler did not bind deployment_inputs_by_dashboard",
)
_require_count_contract(
    isinstance(deployment_inputs_by_dashboard, dict)
    and set(deployment_inputs_by_dashboard) == set(expected_readback_counts_by_dashboard),
    "deployment-input inventory does not equal the validated dashboard design inventory",
)
# `store` is the attested run_contract.WorkspaceStore(w).
# KPI context IDs come from the validated design; they must identify real compiled widgets.
expected_contracts = {}
dashboard_helpers_module.configure_runtime(w, gate_checks_module, store, expected_contracts)
for display_name in sorted(expected_readback_counts_by_dashboard):
    deployment_input = deployment_inputs_by_dashboard[display_name]
    _require_count_contract(
        isinstance(deployment_input, dict)
        and set(deployment_input) == {"datasets", "pages", "filter_dimensions"},
        f"invalid deployment inputs for {display_name!r}",
    )
    expected_readback_counts = expected_readback_counts_by_dashboard[display_name]
    expected_contracts[display_name] = {
        "workspace_host": run_context["runtime"]["workspace_host"],
        "warehouse_id": warehouse_id,
        "serialized_dashboard": dashboard_helpers_module.build_serialized_dashboard(
            deployment_input["datasets"], deployment_input["pages"], deployment_input["filter_dimensions"]),
        "primary_kpi_contexts": primary_kpi_contexts_by_dashboard[display_name],
    }
    result = deploy_dashboard(
        display_name,
        warehouse_id,
        parent_path,
        deployment_input["datasets"],
        deployment_input["pages"],
        deployment_input["filter_dimensions"],
        required_artifacts=required_artifacts,
        quality_gates=quality_gates,
        output_folder=OUTPUT_FOLDER,
    )
    if not isinstance(result, dict) or not result.get("dashboard_id"):
        raise GateCheckError(
            f"POST_DEPLOY_DASHBOARD: deployment returned no identity for {display_name}"
        )
    api_validation = validate_dashboard_from_api(
        w, result["dashboard_id"], display_name, quality_gates=quality_gates, expected=expected_contracts[display_name]
    )

    _require_dashboard_readback(
        isinstance(api_validation, dict), "validator returned non-mapping"
    )
    _require_dashboard_readback(
        api_validation.get("status") == "PASS", "status is not PASS"
    )
    _require_dashboard_readback(
        api_validation.get("source") == "api_readback", "source is not API readback"
    )
    _require_dashboard_readback(
        api_validation.get("structural_status") == "PASS"
        and api_validation.get("page_contract_status") == "PASS",
        "structural or page-contract status is not PASS",
    )
    quality_target_status = api_validation.get("quality_target_status")
    stage_status = api_validation.get("stage_status")
    _require_dashboard_readback(
        (quality_target_status, stage_status)
        in {("PASS", "PASS"), ("WARN", "PARTIAL_SUCCESS")},
        "invalid quality-target/stage outcome",
    )
    quality_target_results = api_validation.get("quality_target_results")
    _require_dashboard_readback(
        isinstance(quality_target_results, list)
        and len(quality_target_results) == len(dashboard_target_fields)
        and {item.get("field") for item in quality_target_results
             if isinstance(item, dict)} == set(dashboard_target_fields)
        and all(
            isinstance(item, dict)
            and set(item) == {"field", "expected", "actual", "status"}
            and item.get("status") in {"PASS", "WARN"}
            for item in quality_target_results
        ),
        "quality-target evidence is missing or incomplete",
    )
    _require_dashboard_readback(
        quality_target_status
        == (
            "PASS"
            if all(item["status"] == "PASS" for item in quality_target_results)
            else "WARN"
        ),
        "quality-target aggregate status is inconsistent",
    )
    _require_dashboard_readback(
        api_validation.get("dashboard_id") == result["dashboard_id"],
        "dashboard ID mismatch",
    )
    _require_dashboard_readback(
        api_validation.get("display_name") == display_name,
        "dashboard display-name mismatch",
    )
    _require_dashboard_readback(
        api_validation.get("workspace_host_binding") == "PASS",
        "workspace-host binding failed",
    )
    if api_validation.get("workspace_host") is not None:
        _require_dashboard_readback(
            str(api_validation["workspace_host"]).rstrip("/")
            == str(workspace_host).rstrip("/"),
            "workspace host mismatch",
        )
    _require_dashboard_readback(
        isinstance(api_validation.get("readback_counts"), dict),
        "readback counts missing",
    )
    _require_dashboard_readback(
        isinstance(expected_readback_counts, dict),
        "independent expected counts missing",
    )
    _require_dashboard_readback(
        set(api_validation["readback_counts"]) == set(expected_readback_counts),
        "readback count key set differs from the canonical expected schema",
    )
    for count_name in (
        "dataset_count", "canvas_page_count", "filter_page_count",
        "widget_count", "filter_count",
    ):
        actual_count = api_validation["readback_counts"].get(count_name)
        _require_dashboard_readback(
            isinstance(actual_count, int) and not isinstance(actual_count, bool),
            f"invalid {count_name}",
        )
        _require_dashboard_readback(
            actual_count == expected_readback_counts.get(count_name),
            f"{count_name} mismatch",
        )
    _require_dashboard_readback(
        api_validation.get("datasets_validated") is True,
        "dataset validation incomplete",
    )
```

**DO NOT:**
- Hand-write serialized_dashboard JSON from memory
- Use `"query"` (string) instead of `"queryLines"` (array)
- Create filter widgets without `queryName` in encodings
- Use `spec.version: 1` for filters (MUST be 2)
- Reference columns not returned by `describe_metric_view()`

---

# Critical Ownership Boundary

The Dashboard stage MUST NOT redefine metric semantics.

The Metric View stage owns:

- KPI definition;
- measure formula;
- numerator/denominator logic;
- aggregation semantics;
- fact grain;
- dimensional relationships;
- Metric View source selection.

The Dashboard stage owns:

- KPI presentation;
- dataset queries;
- visualization selection;
- filters;
- page composition;
- layout;
- interaction;
- deployment.

If a metric appears incorrect, missing, or unsupported:

```text
DO NOT REIMPLEMENT THE KPI IN DASHBOARD SQL
```

Return the issue to the Metric View contract.

Do not bypass `MEASURE()` with raw-table calculations merely to make a visualization work.

---

## MANIFEST INTEGRITY RULE (NON-NEGOTIABLE)

**NEVER write the canonical `<resolved_display_name>_manifest.json` with `published: true` unless ALL of these are true:**

1. The dashboard has been created via the Lakeview API (you have a `dashboard_id`)
2. The dashboard has been published via `POST /api/2.0/lakeview/dashboards/{id}/published`
3. `validate_dashboard_from_api(w, dashboard_id, name, quality_gates=quality_gates, expected=expected)` from the attested `gate_checks.py` has been called and returned the complete PASS mapping required below
4. The API readback confirmed every frozen Dashboard structural gate, exact page contract, and the
   complete `PASS|WARN` evaluation of all frozen quality targets
5. Every filter widget's `spec.encodings.fields[]` includes BOTH:
   - `fieldName`
   - `queryName: "main_query"`
6. Every filter widget query references the SAME dataset used by the widgets it is intended to filter
7. The manifest includes `validation_source: api_readback`

**A manifest that claims `published: true` without API readback is FRAUD.** It will be caught by the authenticated terminal cross-validation stage in `{AGENT_SKILLS_DIR}/prompts/cross_validation/instructions.md` and force a full re-execution.

A filter widget whose `encodings.fields[]` omits `queryName` is a deployment failure, even when the
widget and dataset references exist; the Lakeview UI cannot bind its selected field.

The single canonical manifest schema is defined in Step 20. Do not create an alternate early-stage schema. Every count and identity in that schema comes from `validate_dashboard_from_api()` readback evidence, never agent memory. A quality `WARN` permits the manifest but MUST be preserved as `stage_status: PARTIAL_SUCCESS`.

---

## State & Checkpoint Contract

This step uses **artifact-as-state** checkpointing (see `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`).
The same rules apply in App mode and Genie Code — no backend infrastructure required.

**Before executing each reusable phase**, require the complete fingerprint Resume Skip Gate and the
phase-specific verification below. A locator or manifest never proves deployed state, and readback
agreement alone does not prove upstream freshness. On a mismatch, mark the phase and its graph
dependents `STALE`, persist the invalidation, and return execution to the earliest stale phase.
`load_config` is stateless and always re-read without a reusable phase record.

**Verification flow (run at the START of this step, after loading config):**

1. List the output folder.
2. Manage `run_context.yaml` per `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md` Section 8.
3. Recompute each candidate record's exact producer/frozen-run, mandatory input, and output
   fingerprints, then apply its phase-specific check:
   - `profile_metrics`: normalized current catalog readback still equals the authenticated complete Metric View input set and its stored readback fingerprint.
   - `design_dashboard`: `dashboard_design.yaml` is structurally valid, current-run bound, and hashes to the stored output fingerprint.
   - `build_datasets`: `dashboard_dataset_validation.yaml` contains every dataset for every frozen dashboard and every row has `sql_status: PASS` plus `semantic_status: PASS`.
   - `create_dashboard`: exact dashboard manifest (`<resolved_display_name>_manifest.json`) supplies a `dashboard_id` locator **AND** the matching per-dashboard validation binds that ID/name, has `source: api_readback`, records `overall_status: PASS`, and current normalized Lakeview GET matches the stored output readback fingerprint.
   - `validate_publish`: official Lakeview readback for every exact ID confirms the required published state **AND** each matching readback validation binds ID/name, records `overall_status: PASS`, and has `published: true`. A manifest `published` field alone never permits a skip; `UNKNOWN` cannot pass.
   - **IMPORTANT:** A manifest is always locator/deployment-attempt evidence, even when it says `validation_source: api_readback`. Run or load the separate matching API-readback validation before skipping.
4. Skip only current `VALID` records that pass every check; otherwise continue from the earliest
   `STALE` or absent reusable phase.

**Rules:**

- A `report_progress(status="completed")` event is not reusable until the exact fingerprinted
  phase record is durably persisted.
- **Never re-execute a phase whose fingerprint gate and required readback-backed verification both pass.**
- **Never SKIP validation just because a manifest exists — require the separate matching API-readback comparison.**
- For dashboards, use a manifest `dashboard_id` only as a locator. **UPDATE** only after Lakeview GET resolves it and confirms the exact frozen handoff display name. If it is missing or identity-mismatched, do not update it; follow the matching frozen dashboard deployment/idempotency policy or HALT on conflicting ownership evidence.
- If `RESUME_CONTEXT` is provided, use it only to locate candidates; authenticate and recompute from
  the durable run context, frozen dependencies, exact artifacts, and current Lakeview readback.

**Artifact-as-State mapping:**

| Exact `phase_id` | Artifact | Additional phase-specific skip check after the fingerprint gate |
|-------|----------|----------|
| load_config | Config + contracts loaded | Never reusable; always re-read (stateless) |
| profile_metrics | normalized Metric View catalog readback/field inventory | exact authenticated Metric View set and current normalized readback match |
| design_dashboard | dashboard_design.yaml | structural/current-run binding passes |
| build_datasets | dashboard_dataset_validation.yaml | complete frozen-dashboard dataset inventory + every row `sql_status: PASS` and `semantic_status: PASS` |
| create_dashboard | `<resolved_display_name>_manifest.json` locator + matching `<resolved_display_name>_validation.yaml` | exact ID/name binding + current GET + `source: api_readback` + `overall_status: PASS` |
| validate_publish | Official publication/content readback + matching validation | exact ID/name/content comparison passes and readback confirms required published state; `UNKNOWN` cannot skip |

---

# Step 1: Load Configuration and Contracts

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "load_config"
> - `phase_name`: "Load Configuration"
> - `status`: "started"
> - `current_task`: "Loading configuration and metric contracts"
> - `happenings`: ["Reading accelerator.yaml", "Loading metric view contracts", "Resolving dashboard assets"]

Read:

```text
tool-supplied run_context_path
canonical sibling {run_context.output_folder}/step_handoff.yaml
accelerator.yaml (drift evidence only, after canonical run binding)
```

Apply the invocation-bootstrap gate above first. The tool-supplied path MUST equal the normalized `{run_context.output_folder}/run_context.yaml` path before reading `step_handoff.yaml` or any other sibling. Use `accelerator.yaml` only as original-request/drift evidence. Use current-run `run_context.yaml.assets.dashboards[]` for the frozen executed inventory and accepted design intent, and `run_context.llm`, `run_context.validation`, `run_context.quality_gates`, and `run_context.templates` for execution-affecting settings. Do not repeat Step 0 name/suffix resolution here; exact display names, FQNs, warehouse, host, and paths come from the already validated `step_handoff.yaml`. If the later request file has drifted, preserve and report both values for the next run, but do not alter or halt this active run unless `run_context.yaml` and `step_handoff.yaml` themselves conflict.

Load the **Lakeview API contract** (`lakeview_dashboard_api.md`):

1. **Check first:** A system section labeled `--- BEGIN inputs/lakeview_dashboard_api.md ---` may substitute for a file read only when its injection metadata binds it to the exact frozen `run_context.inputs.lakeview_dashboard_api` reference. A label without matching provenance is not authoritative; read the frozen path instead. A conflicting provenance value is `DASHBOARD_API_CONTRACT_AUTHORITY_ERROR`; HALT.
2. **Otherwise read it** from:
   ```text
   {run_context.inputs.lakeview_dashboard_api}
   ```

This file is **MANDATORY**.

### HARD GATE: lakeview_dashboard_api.md Must Be Loaded

If no provenance-bound supplement is present and the exact frozen path above is unreadable:

```text
❌ EXECUTION HALTED
Cannot proceed with dashboard creation without the Lakeview API contract reference.
Do NOT guess JSON structure from model knowledge.
```

This gate exists because the Lakeview serialized_dashboard format has non-obvious structural requirements (e.g., widget nesting under a `widget` key, page types, filter page separation) that CANNOT be reliably inferred from general knowledge. Every prior attempt to skip this file resulted in:

- `child node [widget] not found` errors
- Silent widget rendering failures
- Missing filters
- Incorrect disaggregated settings

The file is the project-level authoritative contract for:

- `serialized_dashboard` structure;
- page structure;
- widget structure;
- visualization specifications;
- supported `spec.version` values;
- encoding structures;
- field naming;
- dataset representation;
- filter representation;
- layout representation;
- API helper usage.

---

# Serialization Authority Rule

Do NOT construct Lakeview dashboard JSON from:

- model memory;
- prior generated dashboards;
- examples from unrelated projects;
- assumptions about widget JSON;
- hardcoded knowledge embedded in this prompt.

Always construct serialized-dashboard objects according to:

```text
lakeview_dashboard_api.md
```

and the project's dashboard helper library/template.

If the project contract conflicts with an API error returned by the current Databricks workspace:

1. capture the API error;
2. classify it as possible `LAKEVIEW_SERIALIZATION_CONTRACT_DRIFT`;
3. HALT without changing payload structure; and
4. route the approved local reference/template through the release contract-refresh and regression-test workflow.

Runtime execution MUST NOT browse current documentation or ad hoc reinterpret the schema. Do not randomly modify JSON fields until the API accepts the request.

### HARD GATE: No Dashboard Construction Without Design Contract

The following sequence is MANDATORY and non-negotiable:

```text
1. Load lakeview_dashboard_api.md             (JSON structure authority — use only a provenance-bound supplement or the exact frozen run_context.inputs.lakeview_dashboard_api path)
2. Validate step_handoff.yaml                 (resolved identities; consume verbatim)
3. Read metric_view_plan/validation artifacts (desired allocation and validated KPI eligibility)
4. DESCRIBE + SHOW CREATE every handoff FQN   (actual deployed Metric View state)
5. Read kpi_spec Dashboard Mapping            (which KPIs go on which dashboard/page)
6. Create dashboard_design.yaml               (validated desired dashboard contract)
7. Create + validate datasets SQL             (dashboard_dataset_validation.yaml)
8. ONLY THEN construct serialized_dashboard JSON
9. ONLY THEN call the Lakeview API
```

Skipping steps 1-7 and jumping directly to step 8 or 9 is PROHIBITED regardless of time pressure, context constraints, or perceived simplicity of the dashboard.

If current-run `run_context.yaml assets.dashboards[]` defines N dashboards, then N dashboards MUST be created (not 1). Each may have multiple pages as specified by the KPI spec's Dashboard Mapping.

---

# Step 1.1: Load Metric Contracts

Read as mandatory producer contracts:

```text
{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml
```

Then read the following supporting contracts when present:

```text
{OUTPUT_FOLDER}/metric_views/schema_profile.yaml
{OUTPUT_FOLDER}/metric_views/kpi_metric_mapping.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml
```

Missing or unauthenticated plan/validation artifacts HALT with `DASHBOARD_INPUT_AUTHORITY_ERROR`; they are never reconstructed from the supporting contracts or live catalog state.

These artifacts describe intended Metric View design, KPI allocation, and the Metric View stage's validation evidence. They do not override the live deployed definition. Use the exact FQNs from `step_handoff.yaml`, then run `DESCRIBE TABLE` and `SHOW CREATE TABLE` to establish the deployed state before designing datasets.

Metric Views MUST already exist.

If required Metric Views do not exist:

```text
RUN {AGENT_SKILLS_DIR}/prompts/metric_views/instructions.md
```

before continuing.

---

# Step 1.2: Determine Eligible KPIs

Read the KPI specification and Dashboard Mapping.

For every KPI referenced by Dashboard Mapping, check:

```text
metric_view_validation.yaml
```

Only KPIs with:

```text
IMPLEMENTED_AND_VALIDATED
```

may be visualized as authoritative dashboard KPIs.

KPIs with statuses such as:

```text
SKIPPED_MISSING_DATA
SKIPPED_UNRESOLVED_RELATIONSHIP
SKIPPED_UNSAFE_GRAIN
SKIPPED_UNSUPPORTED_SEMANTICS
NOT_IMPLEMENTED
```

must NOT be silently recreated in dashboard SQL.

Record them as:

```text
DASHBOARD_KPI_SKIPPED
```

with their existing Metric View reason.

---

# Step 1.3: Resolve Dashboard Assets

Use each logical dashboard entry in the frozen current-run inventory:

```text
run_context.yaml assets.dashboards[]
```

to locate the matching entry by `id` in:

```text
step_handoff.yaml dashboard_display_names[]
```

Read each concern only from its scoped authority:

```text
dashboard_id and requested design fields → run_context.yaml assets.dashboards[]
resolved_display_name                  → step_handoff.yaml dashboard_display_names[]
dashboard_mapping/target_pages/KPIs   → KPI specification Dashboard Mapping
```

The API `display_name` MUST be the exact matching `dashboard_display_names[].display_name` from `step_handoff.yaml`. `run_context.yaml.assets.dashboards` supplies the frozen logical inventory and accepted intent for this run; the live `accelerator.yaml` is original-request/drift evidence only. Neither is permission to append a suffix or independently recreate a resolved name. Missing, duplicate, or unmatched IDs are `DASHBOARD_INPUT_AUTHORITY_ERROR`.

Resolve one page contract per frozen dashboard before the design-model call:

```yaml
<dashboard_display_name>:
  resolution_source: KPI_SPEC_DASHBOARD_MAPPING | QUALITY_TARGET_FALLBACK
  expected_page_ids: []
```

When the KPI specification has a Dashboard Mapping entry, copy its exact ordered, unique,
non-empty page IDs and use `KPI_SPEC_DASHBOARD_MAPPING`. An ambiguous, duplicate, partial, or
unmatched mapping is `DASHBOARD_INPUT_AUTHORITY_ERROR`; do not choose pages heuristically. Only when
the mapping is absent may `expected_page_ids` be empty and the source be
`QUALITY_TARGET_FALLBACK`. Bind the complete mapping to `resolved_dashboard_page_contracts` for the
LLM call and copy it unchanged into the validated design's `page_contract`; the model does not
choose the resolution source.

---

# Step 1.4: Load Runtime Configuration

From `step_handoff.yaml`, obtain:

```text
warehouse_id
parent_path
workspace_host
```

Use:

```text
warehouse_id
```

for all dataset query execution and dashboard warehouse configuration. Do not replace these resolved runtime values with values re-derived from `databricks.yml`, `accelerator.yaml`, or the active SDK profile. A mismatch must be reported upstream rather than silently normalized.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "load_config"
> - `phase_name`: "Load Configuration"
> - `status`: "completed"
> - `findings`: ["{N} KPIs eligible for dashboard", "Dashboard target resolved"]
> - `stats`: {"kpis_eligible": N, "metric_views_loaded": M}

---

# Step 2: Profile Validated Metric Views

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "profile_metrics"
> - `phase_name`: "Profile Metrics"
> - `status`: "started"
> - `current_task`: "Profiling metric view fields for dashboard design"
> - `happenings`: ["Querying metric view schemas", "Building field inventory", "Resolving column types"]

## Mandatory Deployed Metric View Readback

For every exact Metric View FQN in `step_handoff.yaml`, always execute through the Statement Execution API:

```sql
DESCRIBE TABLE <exact_metric_view_sql_fqn>;
SHOW CREATE TABLE <exact_metric_view_sql_fqn>;
```

`DESCRIBE TABLE EXTENDED` is optional, but basic `DESCRIBE TABLE` and `SHOW CREATE TABLE` are not. Never build the field inventory from `metric_view_design.yaml`, `schema_profile.yaml`, stored DDL, or agent memory in place of these live calls.

Use the readback to establish the deployed:

- dimensions and measures;
- exact names and data types;
- Metric View definition and measure expressions.

Compare deployed readback with the desired state in `metric_view_plan.yaml`, `metric_view_design.yaml`, and the validated assignments in `metric_view_validation.yaml`. If a required FQN is absent, a validated field is absent, or a KPI assignment cannot be resolved against the deployed object, HALT with `METRIC_VIEW_DEPLOYED_STATE_MISMATCH` and return to the Metric View stage. Never substitute a similarly named column or a planned-but-undeployed object.

If an expected-versus-deployed datatype differs, preserve both type strings and route the mismatch
to the Metric View owner. Dashboard SQL may use an explicit conversion only when that conversion is
part of the already validated KPI/dashboard intent and the deployed upstream type itself is valid;
it MUST NOT add `CAST`/`TRY_CAST`, stringify a field, or change widget semantics to conceal upstream
datatype drift.

After building the live field inventory, batch the remaining data-profile queries where practical. Profile enough data to understand:

- dimensions;
- measures;
- dates/timestamps;
- valid categorical values;
- cardinality;
- data ranges;
- null behavior;
- available periods.

Do NOT infer deployed measure formulas from sample values. Use live `SHOW CREATE TABLE` for the deployed expression and the Metric View validation artifact for the KPI validation outcome. When they conflict, deployed readback is the actual state and the conflict is a validation failure; neither artifact silently overwrites the other.

### Zero-Data Guard

If profiling reveals that a required Metric View returns zero rows for any basic query:

```sql
SELECT COUNT(*) FROM `<catalog>`.`<schema>`.`<metric_view>`
```

Result = 0 → **HALT**.

```text
❌ EXECUTION HALTED
Metric View contains no data: {metric_view_fqn}
Dashboard widgets will render as empty.
Return to data layer / metric view validation.
```

Do not proceed to build widgets against an empty Metric View. This catches data layer failures before they propagate to confusing empty dashboards.

---

# Step 2.1: Build Dashboard Field Inventory

Create an internal inventory:

```yaml
metric_view:
  fqn:

measures:
  - name:
    validated_kpis:
    datatype:
    format:

dimensions:
  - name:
    datatype:
    approximate_cardinality:
    null_rate:
    used_by_kpis:
    filter_candidate:

temporal_dimensions:
  - name:
    datatype:
    min:
    max:
    used_by_kpis:
```

Use this inventory for visualization and filter selection.

---

# Step 2.2: LLM-Assisted Dashboard Design (MANDATORY)

Before writing the design contract, call the **reasoning model frozen at `run_context.llm.steps.dashboard_design.model`** to propose a rich multi-page dashboard layout. This leverages the model's understanding of dashboard UX, analytical storytelling, and domain-specific visualization best practices; do not select or substitute a model locally.

## Why This Step Exists

The agent executing this pipeline may default to the simplest possible layout (one page, one counter per KPI). A reasoning model call produces domain-aware, analytically rich designs that:
- Adapt to the specific KPI domain (healthcare vs. finance vs. retail)
- Propose appropriate page structures based on KPI analytical categories
- Select visualization types matched to each KPI's data shape
- Identify optimal filter dimensions and scope
- Balance widget density across pages

## Context Assembly (BEFORE the LLM call)

Gather all of these inputs and include them in the prompt:

| Input | Source | What It Provides |
|-------|--------|------------------|
| KPI specification | Exact frozen `run_context.inputs.kpi_spec` path | Business definitions, KPI categories, Dashboard Mapping |
| Deployed Metric View definition | Live `SHOW CREATE TABLE` against each handoff FQN | Actual deployed definition and measure expressions |
| Metric View validation | `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` | Which KPIs are IMPLEMENTED vs SKIPPED |
| Live field inventory | Live `DESCRIBE TABLE` plus Step 2.1 profiling | Actual deployed names/types plus cardinalities and ranges |
| Dashboard identities | `step_handoff.yaml` `dashboard_display_names[]` | Exact resolved names for API calls |
| Frozen dashboard intent | `run_context.yaml` `assets.dashboards[].intent` | Accepted purposes and design constraints for this run |
| Executed dashboard inventory | `run_context.yaml` `assets.dashboards[]` | Frozen logical dashboard IDs for this run |
| Categorical samples | Profiling query from Step 2 | Actual dimension values (for the model to understand the domain) |

**The live Metric View definition is critical** — without it, the LLM may propose widgets using measures that are only planned, no longer deployed, or have different aggregation semantics.

Get the deployed definition from the exact handoff FQN:
```sql
SHOW CREATE TABLE <exact_metric_view_sql_fqn>
```

Do not reconstruct deployed state from stored creation DDL. Stored DDL and `metric_view_design.yaml` are desired-state evidence only.

## LLM Call Pattern

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config

w_llm = WorkspaceClient(config=Config(http_timeout_seconds=600))
quality_gates = run_context["quality_gates"]
dashboard_design_config = run_context["llm"]["steps"]["dashboard_design"]
design_model = dashboard_design_config.get("model")
if not isinstance(design_model, str) or not design_model:
    raise RuntimeError("DASHBOARD_LLM_CONFIGURATION_ERROR: frozen dashboard model is missing")

# Assemble context for the model
# CRITICAL: Include BOTH the KPI spec AND live Metric View readback.
# The LLM needs to know:
#   - What KPIs exist and their business meaning (from KPI spec)
#   - What measures/dimensions are ACTUALLY available (from metric view)
#   - How measures are computed (SUM, COUNT, ratio formulas)
#   - What aggregation semantics apply (additive vs ratio vs distinct)
#   - What the source grain is (claim line, enrollment, etc.)

design_prompt = f"""
You are a senior Databricks AI/BI dashboard architect.

Given the following inputs, design a grounded dashboard layout that preserves each resolved page contract.

## KPI Specification
{kpi_spec_content}

## Deployed Metric View Definition (live readback)
Metric View FQN: {metric_view_fqn}
Source Table: {source_table}
Source Grain: {source_grain}

### Measures (available via MEASURE() syntax)
{metric_view_measures_yaml}

### Dimensions (available for GROUP BY and filtering)
{metric_view_dimensions_yaml}

### SHOW CREATE TABLE output (complete deployed definition)
{metric_view_show_create_content}

## Metric View Validation Results
KPIs implemented and validated: {implemented_kpis}
KPIs skipped (DO NOT include these): {skipped_kpis}

## Data Profile
- Row count: {row_count}
- Date range: {min_date} to {max_date}
- Categorical value samples:
{categorical_samples}

## Dashboard Assets Configured
{dashboard_names_and_purposes}

## Resolved Page Contracts
{resolved_dashboard_page_contracts}

## Aggregation Semantics Reference
- Resolve every KPI's aggregation behavior from its validated mapping and the live deployed Metric View definition. Do not apply a generic rule based on labels such as total, rate, ratio, average, or distinct count. If the required widget roll-up cannot be proven from those authorities, return `AGGREGATION_SEMANTICS_UNRESOLVED`.

## Requirements
1. For `KPI_SPEC_DASHBOARD_MAPPING`, return exactly the supplied ordered page IDs—no missing,
   added, renamed, reordered, merged, or filler pages. For `QUALITY_TARGET_FALLBACK`, return at
   least one non-empty canvas page and prefer {quality_gates['min_canvas_pages_per_dashboard']}.
2. Prefer at least {quality_gates['min_widget_contexts_per_primary_kpi']} different visualization contexts for each primary KPI across its authorized pages
   (e.g., Total Paid as counter on Summary page AND as line chart on Trends page AND as bar chart on Segments page)
3. Pages must have clear analytical purposes:
   - Executive Summary: headline counters + 1-2 contextual charts
   - Trend Analysis: line charts showing KPIs over time (monthly/quarterly)
   - Segment Breakdown: bar/pie charts showing KPIs by each dimension
   - Quality/Performance: rate and ratio KPIs with comparisons
   - Detail View: tables with multi-dimensional breakdowns
4. Prefer between {quality_gates['min_widgets_per_canvas_page']} and {quality_gates['max_widgets_per_canvas_page']} widgets per page without changing the page contract
5. Prefer at least {quality_gates['min_visualization_types_per_dashboard']} analytically appropriate visualization types per dashboard (counter, line, bar, pie, table)
6. Identify which dimensions make the best global filters (high analytical value, moderate cardinality) and prefer at least {quality_gates['min_filters_per_dashboard']} when that many eligible dimensions exist
7. For each widget, specify: title, KPI/measure, visualization type, dimensions used, aggregation
8. Preserve the aggregation semantics proven by the validated Metric View. Do not invent a roll-up rule; if safe roll-up cannot be established, return `AGGREGATION_SEMANTICS_UNRESOLVED`.
9. Only use measures and dimensions that exist in the live DESCRIBE/SHOW CREATE readback above

## Output Format
Return a YAML structure with this exact format:

dashboards:
  - name: <dashboard_display_name>
    purpose: <one-line analytical purpose>
    page_contract:
      resolution_source: KPI_SPEC_DASHBOARD_MAPPING | QUALITY_TARGET_FALLBACK
      expected_page_ids: [<exact ordered mapped IDs, or empty list for fallback>]
      actual_page_ids: [<exact ordered proposed canvas-page IDs>]
      structural_status: PASS
    pages:
      - id: <stable page ID from the mapping, or stable fallback ID>
        page_name: <name>
        purpose: <analytical intent of this page>
        widgets:
          - title: <widget title>
            kpi: <KPI name from spec>
            measure: <exact metric view measure name>
            viz_type: counter | line | bar | pie | table
            dimensions: [<exact dimension names from metric view>]
            aggregation: <exact strategy resolved from validated KPI/Metric View semantics>
            rationale: <why this viz type for this KPI on this page>
        ...
    filters:
      - dimension: <exact dimension name from metric view>
        filter_type: multi-select | date-range-picker | single-select
        scope: global | page-specific
        rationale: <why this filter is valuable for analysis>
"""

stage_instruction = run_context["llm"]["steps"]["dashboard_design"]["instruction"]

response = w_llm.api_client.do(
    "POST",
    f"/serving-endpoints/{design_model}/invocations",
    body={
        "messages": [
            {"role": "system", "content": f"{stage_instruction}\n\nYou are a dashboard design architect. Follow every mandatory grounded-design rule in this stage and output valid YAML only."},
            {"role": "user", "content": design_prompt},
        ],
        "max_tokens": 16000,
        "temperature": 1,
    }
)
dashboard_design_yaml = response["choices"][0]["message"]["content"]
```

## Model Selection

Use the already resolved model in current-run `run_context.llm.steps.dashboard_design.model`. Any fallback must have been resolved and frozen by Step 0; if the field is missing, HALT rather than choosing a model locally from the current request file.

## Validation of LLM Output

After receiving the model's proposed design, validate:

**Structural validation (must PASS):**

1. **Page contract**: mapped page IDs equal the exact ordered Dashboard Mapping inventory; when no mapping exists, the canvas inventory is non-empty
2. **Non-empty pages**: every canvas page contains at least one valid widget
3. **KPI coverage**: every IMPLEMENTED_AND_VALIDATED KPI assigned to this dashboard appears in at least one authorized page widget
4. **Measure validity**: every `measure` field matches an exact measure name from live DESCRIBE output
5. **Dimension validity**: every `dimensions[]` entry matches an exact dimension name from live DESCRIBE output
6. **Aggregation correctness**: every widget aggregation is proven by validated KPI/Metric View semantics
7. **Filter validity**: proposed filters reference deployed dimensions and can be bound
8. **No SKIPPED KPIs**: no widget references a KPI that was SKIPPED in Metric View validation

**Quality-target evaluation (PASS or WARN):** evaluate the frozen preferred fallback page count,
widget-density bounds, visualization diversity, filter count, and primary-KPI context count. Record
each field's expected/actual/status. A miss is `WARN`; do not reject or rewrite an otherwise valid
mapped design merely to satisfy it.

If structural validation fails, either:
- Fix obvious issues (e.g., replace a non-existent column with the correct one from the metric view)
- Re-prompt the model with specific corrections (include the error and the correct metric view field list)
- Do NOT accept a page inventory that differs from the resolved page contract
- Do NOT invent measures/dimensions not in the metric view

## Output

Save the validated design to:

```text
{OUTPUT_FOLDER}/dashboards/llm_dashboard_design.yaml
```

This is a design proposal for Step 3, not an authority over the KPI specification, Metric View validation, live Metric View readback, or resolved handoff identities. Promote only validated portions into `dashboard_design.yaml`. Reject or re-prompt any proposed widget that conflicts with those authorities; never preserve an invalid widget merely to remain faithful to LLM output.

## Skip Condition

If `{OUTPUT_FOLDER}/dashboards/llm_dashboard_design.yaml` already exists, revalidate it against the current KPI eligibility, exact handoff identities, and live DESCRIBE/SHOW CREATE inventory. Skip the LLM call only when the existing proposal still passes those checks.

---

# Step 2.3: Dataset SQL Column Resolution Rules (CRITICAL)

This section prevents the most common dashboard rendering failure: `UNRESOLVED_COLUMN` errors caused by referencing columns that do not exist in the metric view.

### Rule 1: Only Use Actual Metric View Columns

Dataset SQL MUST reference only columns that appear in the DESCRIBE output (Step 2 above).

Do NOT assume derived or transformed column names exist. Common violations:

```text
✗ service_month     (does not exist — the dimension is service_date)
✗ claim_month       (does not exist — the dimension is admit_date)
✗ member_name       (does not exist — might be mbr_full_name)
✗ provider_state    (does not exist — might be member_state)
```

If a monthly/quarterly aggregation is needed, use the date expression in the SQL:

```sql
-- CORRECT: derive from actual dimension
SELECT DATE_TRUNC('MONTH', service_date) AS service_month, ...
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY DATE_TRUNC('MONTH', service_date), ...

-- INCORRECT: assume service_month exists
SELECT service_month, ...
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY service_month, ...
```

### Rule 2: Filter Widgets Must Share Dataset with Canvas Widgets (CRITICAL)

Global filter widgets MUST reference the **SAME dataset** as the canvas widgets they filter. Do NOT create a separate `ds_filter_values` dataset for filters.

**Binding invariant:** Lakeview API-created filter widgets do not auto-bind across datasets. A
filter and every canvas widget it controls must therefore reference the same dataset.

```text
✗ BROKEN: Filters reference separate dataset (binding never established)
  Filter widget:  datasetName = "ds_filter_values"
  Counter widget: datasetName = "ds_kpi_headline"
  → Selecting a filter value does NOT change counter values

✓ CORRECT: Filters and canvas widgets share the same dataset
  Filter widget:  datasetName = "ds_kpi_headline"
  Counter widget: datasetName = "ds_kpi_headline"
  → Selecting a filter value narrows shared rows → counter re-aggregates
```

**Implementation pattern:**

1. Create ONE dataset per canvas page that includes BOTH filter dimensions and measures:
   ```sql
   SELECT service_date, line_of_business, claim_type, member_state,
          MEASURE(total_paid) AS total_paid, MEASURE(total_claims) AS total_claims
   FROM `<catalog>`.`<schema>`.`<metric_view>`
   GROUP BY service_date, line_of_business, claim_type, member_state
   ```

2. Filter widgets on PAGE_TYPE_GLOBAL_FILTERS reference this same dataset with `disaggregated: true`
3. Counter/chart widgets on PAGE_TYPE_CANVAS reference this same dataset with `disaggregated: false` + SUM/AVG

The filter dimension column names MUST match actual metric view dimension names (from DESCRIBE).

Example: if the metric view has `service_date` (not `service_month`):

```text
✓ Filter on: service_date (date-range-picker)
  → Canvas datasets include: service_date in SELECT + GROUP BY
  → Filter binds correctly

✗ Filter on: service_month (derived alias)
  → Canvas datasets have: service_date (not matching)
  → Filter DOES NOT bind
```

### Rule 3: Widget `disaggregated` Mode and Aggregation Semantics (CRITICAL)

Canvas widgets MUST use `disaggregated: false` + explicit aggregation. Filter widgets MUST use `disaggregated: true`.

```text
✗ BROKEN: disaggregated=true on counters → shows single row value (e.g. "1" instead of "500")
✓ CORRECT: disaggregated=false on counters → SUM/AVG aggregates all filtered rows into total
```

| Widget type | disaggregated | Field expression | Behavior |
|-------------|---------------|------------------|---------|
| Filter | `true` | `` `column` `` | Shows distinct values for user selection |
| Counter (additive) | `false` | `SUM(\`total_paid\`)` | Sums all filtered rows into total |
| Counter (non-additive) | `false` | `<validated expression>` | Preserves the KPI's validated roll-up semantics |
| Bar/Line (y-axis) | `false` | `SUM(\`total_paid\`)` | Aggregates by x-axis grouping |
| Bar/Line (x-axis) | `false` | `` `line_of_business` `` | Dimension for grouping |

When a counter widget's dataset includes filter dimensions (for cross-filter binding), the dataset returns multiple rows. The counter's field expression aggregates them.

For **additive measures** (totals, counts, sums):

```text
Widget expression: SUM(`total_paid`)     → correct (additive)
Widget expression: SUM(`total_claims`)   → correct (additive)
```

For non-additive, ratio, rate, average, or distinct-count measures, do not select
`SUM`, `AVG`, or component reconstruction from this prompt alone. Use only the
strategy explicitly established by the validated KPI mapping and live Metric View
definition. If changing the dataset or widget grain makes that strategy ambiguous,
HALT with `AGGREGATION_SEMANTICS_UNRESOLVED`.

### Rule 3b: SQL Generation Quality (Prevents Syntax Errors on First Execution)

When generating dataset SQL — especially UNION ALL queries:

1. **Column count alignment**: Every SELECT in a UNION ALL MUST have the exact same number of columns. Count them before writing UNION.
2. **No trailing commas**: Never leave a comma before FROM, UNION, or a closing parenthesis.
3. **Complete column names**: Never truncate or abbreviate column identifiers. Use the full column name as it appears in the metric view schema.
4. **One dataset per execute_sql**: Execute each dataset SQL individually for validation. Do NOT combine multiple unrelated datasets into one multi-statement call.
5. **Alias all computed columns**: Every expression (`SUM(...)`, `CASE WHEN...`, literals) must have an explicit `AS alias`.
6. **LIMIT inside UNION ALL is a PARSE_SYNTAX_ERROR**: In Databricks SQL, `LIMIT` binds to the entire statement, NOT to individual sub-queries. `SELECT ... LIMIT 1 UNION ALL SELECT ...` is INVALID. Either omit LIMIT from sub-queries, or wrap each in parentheses: `(SELECT ... LIMIT 1) UNION ALL (SELECT ... LIMIT 1)`.
7. **On SQL failure, fix the SQL — do NOT fall back to execute_python**: If a dataset SQL query fails, diagnose and correct the SQL syntax. NEVER switch to `execute_python` as a workaround — the Python subprocess has NO Databricks SDK access and cannot create or validate dashboards.

If a generated SQL exceeds ~30 lines, mentally verify the structure before calling `execute_sql`:
- Count the columns in the first SELECT
- Confirm every subsequent SELECT in the UNION has the same count
- Confirm no dangling commas

### Rule 4: Mandatory Dataset SQL Validation

Before constructing `serialized_dashboard` JSON, EVERY dataset's SQL must be executed on the SQL warehouse and confirmed to return rows without error.

This is NOT optional. It is a mandatory gate (Step 7 of this prompt).

The validation query:

```sql
SELECT * FROM (<dataset_sql>) LIMIT 5
```

must succeed for every dataset. If ANY dataset fails:

```text
❌ DATASET_SQL_VALIDATION_FAILURE
Dataset: <name>
Error: <sql_error_message>
```

Do NOT construct dashboard JSON until all datasets pass.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "profile_metrics"
> - `phase_name`: "Profile Metrics"
> - `status`: "completed"
> - `findings`: ["{N} measures available", "{D} dimensions available", "Field inventory complete"]
> - `stats`: {"measures": N, "dimensions": D, "datasets_planned": K}

---

# Step 3: Build Dashboard Design Contract

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "design_dashboard"
> - `phase_name`: "Design Dashboard"
> - `status`: "started"
> - `current_task`: "Designing pages, visualizations, and filters"
> - `happenings`: ["Mapping KPIs to visualizations", "Selecting chart types", "Designing filter controls"]

Before writing dataset SQL or constructing JSON, create:

```text
{OUTPUT_FOLDER}/dashboards/dashboard_design.yaml
```

using Workspace API / agent tools.

Never use `dbutils.fs` for `/Workspace/`.

For every dashboard define:

```yaml
dashboards:
  - id:
    name: <exact handoff display_name>
    purpose:
    metric_views: []
    page_contract:
      resolution_source: KPI_SPEC_DASHBOARD_MAPPING | QUALITY_TARGET_FALLBACK
      expected_page_ids: []  # exact ordered mapping IDs; [] only for fallback
      actual_page_ids: []    # exact ordered IDs from pages[]
      structural_status: PASS
    filters:
      - dimension:
        filter_type:
        scope:
        rationale:
    pages:
      - id:
        title:
        purpose:
        page_type: CANVAS
        widgets:
          - id:
            title:
            kpi:
            measure:
            dimensions:
            visualization:
            rationale:
            dataset:
            position:
            size:
    quality_target_evaluation:
      status: PASS | WARN
      checks:
        - field: <exact field from dashboard_policy.quality_target_fields>
          expected:
          actual:
          status: PASS | WARN
```

This design contract MUST be completed before serialized-dashboard construction.

### GATE 3.1: Page Contract Validation (MANDATORY)

After writing `dashboard_design.yaml`, verify its exact page contract:

```text
For each dashboard:
  mapped_page_ids = exact ordered IDs in KPI spec Dashboard Mapping, if present
  actual_page_ids = exact ordered IDs of PAGE_TYPE_CANVAS entries in dashboard_design.yaml

  IF a mapping exists AND actual_page_ids != mapped_page_ids:
    → HALT: "Page contract mismatch: expected {expected_ids}, got {actual_ids}"
    → DO NOT proceed to dataset SQL or API creation
    → Redesign dashboard_design.yaml to preserve the exact mapping

  IF no mapping exists AND actual_page_ids is empty:
    → HALT: "Page contract mismatch: fallback canvas inventory is empty"

  OTHERWISE:
    → structural page contract PASS
    → evaluate min_canvas_pages_per_dashboard separately as PASS or WARN
```

A dashboard with one mapped page is structurally valid even when the fallback page-count target is
higher. Conversely, extra filler pages are a structural violation when a mapping defines a smaller
exact inventory. The mapping, not the heuristic, owns the count.

---

# Step 3.1: Dashboard Mapping Is Authoritative (KPI-Driven Design)

Dashboard creation combines four non-overlapping authorities:

```text
Source 1: KPI Spec (Dashboard Mapping section)
  → defines WHICH pages each dashboard has
  → defines WHICH KPIs appear on each page
  → defines visualization types and layout intent
  → defines the ANALYTICAL DEPTH expected (summary vs detail vs trends)

Source 2: step_handoff.yaml
  → defines exact Metric View SQL FQNs
  → defines exact resolved dashboard display names
  → defines resolved warehouse and workspace paths

Source 3: metric_view_validation.yaml
  → defines which KPIs are IMPLEMENTED_AND_VALIDATED
  → defines which validated Metric View implements each eligible KPI

Source 4: Live Metric View DESCRIBE/SHOW CREATE output (Step 2 above)
  → defines ACTUAL column names available for SQL
  → defines data types (date, string, decimal, etc.)
  → defines which columns are dimensions vs measures
  → defines the ACTUAL deployed Metric View expression
  → defines which dimensions support different analytical views
```

**Deriving page richness from KPI spec:**

The KPI spec doesn't just list metrics — it defines analytical categories (e.g., Enrollment KPIs, Claims KPIs, Cost KPIs, Quality KPIs, Window/Trend KPIs). Each category typically maps to at least one page, and each page should present its KPIs in the visualization style most appropriate to that category:

```text
KPI Categories → Page Mapping:
  Headline/Summary KPIs     → Executive Summary page (counters + 1-2 charts)
  Time-series/Window KPIs   → Trend Analysis page (line charts, period-over-period)
  Segment/Category KPIs     → Segment Breakdown page (bar charts, stacked bars)
  Rate/Ratio KPIs           → Quality/Performance page (gauges, bar comparisons)
  Multi-dimensional KPIs    → Detail/Drill-down page (tables, heatmaps)
```

When the KPI spec has 10+ KPIs spanning multiple analytical categories, a SINGLE canvas page is almost certainly insufficient. The design contract MUST map KPIs to pages based on their analytical category, NOT cram everything into one page.

The dashboard design is the intersection of these scoped authorities:

```text
KPI Spec says: "Show Total Paid by Line of Business on Claims Analysis page"
DESCRIBE says: dimensions are [line_of_business, service_date, ...], measures are [total_paid, ...]
→ Dataset SQL: SELECT line_of_business, MEASURE(total_paid) AS total_paid FROM mv GROUP BY line_of_business
→ Widget: bar chart, x=line_of_business, y=sum(total_paid)
```

### What the KPI Spec determines:

```text
page names and purpose
KPI-to-page assignment
visualization type per KPI
filter dimensions (from KPI required dimensions)
```

`run_context.yaml assets.dashboards[]` defines the frozen logical dashboard inventory and accepted intent for this run. The live `accelerator.yaml assets.dashboards[]` is drift evidence only after Step 0, and matching `step_handoff.yaml dashboard_display_names[]` entries define the exact resolved API names.

### What DESCRIBE determines:

```text
exact column names for SQL
date/temporal dimension names for DATE_TRUNC
categorical dimension names for GROUP BY
measure names for MEASURE()
```

### Prohibited:

```text
✗ Inventing dashboards outside the frozen current-run `run_context.yaml assets.dashboards[]` inventory
✗ Inventing pages not in KPI Spec Dashboard Mapping
✗ Adding KPIs not in the spec
✗ Moving KPIs to different dashboards/pages
✗ Guessing column names without DESCRIBE verification
✗ Using derived aliases (service_month) as if they were actual columns
```

Minor layout changes within a mapped page are allowed.

Semantic mapping changes are not.

---

# Step 3.2: Page Design — Rich KPI Visualization Within the Page Contract

Each page should have a clear analytical purpose AND present KPIs in a visualization style appropriate to that page's intent.

**QUALITY TARGET: Show KPIs in multiple meaningful variations when the authorized page inventory and data shape support it.**

A single KPI (e.g., "Total Paid Amount") is not fully represented by a single counter widget. A rich dashboard shows the same KPI from different analytical angles:

```text
Page 1 (Executive Summary): Counter showing headline total
Page 2 (Trend Analysis):    Line chart showing the same KPI over time
Page 3 (Segment Breakdown): Bar chart showing the same KPI by category
Page 4 (Detail):             Table showing the same KPI with multiple dimensions
```

This multi-variation approach is preferred analytical richness, not permission to duplicate a KPI
onto an unauthorized page or invent a page. The KPI spec defines WHAT to measure; the Dashboard
Mapping defines WHERE to show it; the page purpose defines HOW to visualize it. Record an unmet
context-count target as `WARN`.

### Minimum Page Types (derive from KPI spec Dashboard Mapping)

| Page Purpose | Widget Types | KPI Presentation |
|---|---|---|
| Executive Summary | Counters, sparklines | Headline values, period comparison |
| Trend Analysis | Line charts, area charts | KPIs over time (monthly, quarterly) |
| Segment Performance | Bar charts, stacked bars | KPIs by dimension (type, status, geography) |
| Composition | Pie/donut charts | Part-to-whole distributions |
| Detailed Analysis | Tables, heatmaps | Multi-dimensional KPI breakdowns |

### Widget Density Guidelines

Prefer that each canvas page stay within the frozen
`run_context.quality_gates.min_widgets_per_canvas_page` and
`max_widgets_per_canvas_page`. Balance counters and contextual charts on summaries, time-oriented
charts on trend pages, dimensional breakdowns on segment pages, and tables plus supporting charts
on detail pages. A page outside the preferred range records a quality `WARN`; do not split, merge,
or pad mapped pages merely to reach the range.

### Prohibited Page-Design Patterns

```text
✗ Collapsing multiple mapped pages into one canvas page
✗ One counter per KPI and nothing else — produces a "wall of numbers" with no insight
✗ Putting ALL chart types on one page — splits analytical stories
✗ Skipping trend analysis when temporal data exists — wastes the time dimension
✗ Showing only top-level totals without dimensional breakdowns — hides patterns
```

Derive actual pages from Dashboard Mapping.

Avoid pages that are merely arbitrary collections of charts.

Widgets on the same page should answer related analytical questions.

---

# Step 4: Visualization Selection

Visualization choice MUST follow the analytical question and data shape.

Do not choose chart types merely to satisfy visual variety.

---

## Counter

Prefer counters for:

- headline KPIs;
- single-value measures;
- executive summary values.

Avoid counters for metrics where context/trend is essential.

---

## Line Chart

Prefer line charts for:

```text
measure over ordered time
```

provided sufficient periods exist.

Do not use a line chart merely because a date column exists.

---

## Bar Chart

Prefer bar charts for:

- category comparisons;
- rankings;
- top-N analysis;
- discrete dimension comparisons.

Horizontal bar charts are generally preferable when category labels are long.

---

## Pie / Donut

Use only when:

- representing part-to-whole composition;
- category count is small;
- categories are mutually understandable;
- percentages/composition are analytically meaningful.

Do NOT use pie charts solely to create chart-type diversity.

If cardinality is too high, use a bar chart.

---

## Table

Prefer tables when:

- precise values matter;
- multiple measures must be compared;
- detail inspection is required;
- categorical cardinality is too high for an effective chart.

---

## Visualization Diversity & Multi-Variation KPI Display

Aim for useful visualization diversity across dashboards.

If the KPI set naturally supports multiple visual forms, satisfy the frozen visualization-diversity minimum with meaningful choices rather than artificial variety.

**Visualization-type diversity target per dashboard:**

```text
Prefer at least
run_context.quality_gates.min_visualization_types_per_dashboard distinct types from:
  1. Counter (headline values)
  2. Line chart (temporal trends)
  3. Bar chart (categorical comparisons)
  4. Pie/Donut (composition/distribution)
  5. Table (detailed multi-measure view)
```

**KPI Multi-Variation Rule:**

For every primary KPI (defined in KPI spec as a headline metric), prefer at least frozen `run_context.quality_gates.min_widget_contexts_per_primary_kpi` different visualization contexts across its authorized dashboard pages:

```text
Example: "Total Paid Amount" appears as:
  - Counter on Executive Summary page (headline value)
  - Line chart on Trends page (monthly trend)
  - Bar chart on Segments page (by claim type)

Example: "Denial Rate" appears as:
  - Counter on Summary page (headline percentage)
  - Line chart on Trends page (monthly trend)
  - Bar chart on Segments page (by claim type or provider)
```

This ensures stakeholders can analyze each KPI from multiple analytical perspectives without needing to write their own queries.

However:

```text
ANALYTICAL APPROPRIATENESS
>
CHART TYPE COUNT
```

Do not select an inappropriate chart merely to satisfy a chart-count target. Show each major KPI in
multiple meaningful contexts when supported; otherwise record the target miss as `WARN` without
altering the page contract.

---

# Step 5: Determine Global Filters

Determine filters using BOTH:

```text
KPI specification
+
Metric View data profile
```

Do NOT hardcode domain-specific filter fields.

---

# Step 5.1: Filter Candidate Selection

A dimension is a strong global-filter candidate when:

1. it is used to slice/filter multiple KPIs;
2. it exists in the validated Metric View;
3. it has meaningful analytical variation;
4. its cardinality supports an appropriate control;
5. it can be made available to the required dashboard datasets.

Prefer dimensions that affect multiple widgets.

Avoid adding filters that apply to only one obscure visualization unless Dashboard Mapping specifically requires them.

---

# Step 5.2: Filter Type Selection

Determine filter widget type from:

```text
datatype
+
cardinality
+
business usage
```

Examples:

```text
DATE / TIMESTAMP → date-oriented control
low-cardinality categorical → multi-select/list control
numeric range → range control when supported
```

Use only filter widget types supported by:

```text
lakeview_dashboard_api.md
```

Do not invent unsupported filter types.

---

# Step 5.3: Filter Scope

Determine whether a filter should be:

```text
GLOBAL
PAGE_LEVEL
WIDGET_LEVEL
```

based on KPI Mapping and analytical intent.

**Pinned release constraint:** The approved versioned local Lakeview reference/template pinned for this run defines global filters via a `PAGE_TYPE_GLOBAL_FILTERS` page and does not expose page-level or widget-level filters as first-class concepts. To scope filter impact, control which datasets expose the filter column — a filter only affects widgets whose dataset includes the matching column name. Any newly observed platform-contract difference is routed to the out-of-run contract-refresh/regression workflow; it does not mutate this run.

Do not make every filter global by default.

Global filters should represent broadly applicable analytical dimensions.

To limit filter scope to specific widgets:

1. add the filter dimension column to the datasets of widgets that SHOULD respond;
2. omit it from datasets of widgets that should NOT respond.

This is the filter-scoping mechanism defined by the approved versioned local contract/template for this run.

---

# Step 6: Dataset Design

Every widget MUST map to an explicit dataset.

For each widget create a dataset design record:

```yaml
dataset:
  name:
  widget:
  metric_view:
  measures:
  dimensions:
  filters:
  order_by:
  limit:
  expected_shape:
```

Do not construct serialized-dashboard datasets before this design exists.

---

# Step 6.1: Metric View Queries Only

Where the KPI is implemented through a Metric View, use:

```sql
MEASURE(...)
```

against the validated Metric View.

Do not recalculate the KPI against raw source tables.

Do not reproduce complex KPI formulas in dashboard SQL.

The dashboard query should primarily perform:

```text
measure selection
dimension grouping
filter exposure
sorting
top-N
time presentation
```

not semantic-model repair.

---

# Step 6.2: Global Filter Compatibility

For every global filter determine which datasets it is intended to affect.

Each applicable dataset MUST expose the filter field using the exact compatible field name required by the dashboard filter contract.

Do not blindly add every global filter column to every dataset if doing so changes the dataset's analytical grain or makes the query semantically invalid.

Instead:

1. identify the intended filter scope;
2. ensure compatible datasets expose the field;
3. ensure the resulting grouping/query remains analytically correct.

If adding a filter dimension would change a counter from:

```text
one-row result
```

to:

```text
multiple rows
```

do not simply add it to the SELECT.

Design the dataset/filter binding according to the supported Lakeview filtering contract.

Analytical correctness takes precedence over simplistic column exposure.

---

# Important Grain Rule

Never modify dataset grain merely to satisfy filter binding.

Prohibited grain example:

```sql
SELECT
    region,
    MEASURE(total_revenue)
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY region
```

for a headline counter intended to show one total value, solely because `region` is a global filter.

If the dashboard/filter API supports binding filters to source fields without changing result grain, use the supported mechanism defined in:

```text
lakeview_dashboard_api.md
```

If not, redesign the dataset/filter scope intentionally.

Do not break widget semantics.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "design_dashboard"
> - `phase_name`: "Design Dashboard"
> - `status`: "completed"
> - `findings`: ["{P} pages designed", "{W} widgets planned", "{F} filters configured"]
> - `stats`: {"pages": P, "widgets": W, "filters": F}

---

# Step 7: Build Dataset SQL

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "build_datasets"
> - `phase_name`: "Build Datasets"
> - `status`: "started"
> - `current_task`: "Building and validating dataset SQL queries"
> - `happenings`: ["Writing dataset SQL", "Executing validation queries", "Checking column resolution"]

For each planned widget:

1. generate SQL against the validated Metric View;
2. **use `MEASURE()` for ALL validated measures** — this is NON-NEGOTIABLE;
3. include required grouping dimensions;
4. include only supported filters;
5. apply ordering/Top-N where required;
6. use CTE/window logic only when the KPI/dashboard design requires it.

### CRITICAL: MEASURE() Is Mandatory for ALL Measure References

Metric View measures are NOT regular columns — they are computed expressions in the deployed Metric View definition returned by live `SHOW CREATE TABLE`.
Accessing a measure column directly (without `MEASURE()`) causes:

```text
SQL ERROR: [METRIC_VIEW_MISSING_MEASURE_FUNCTION] The usage of measure column [Total Claims,Total Paid Amount]
```

**NEVER write dataset SQL like this:**
```sql
-- WRONG — direct column access causes METRIC_VIEW_MISSING_MEASURE_FUNCTION
SELECT `Total Claims`, `Total Paid Amount`
FROM `<catalog>`.`<schema>`.`<metric_view>`

-- WRONG — even with GROUP BY, measures MUST be wrapped in MEASURE()
SELECT claim_type, `Total Paid Amount`
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY claim_type
```

**ALWAYS write dataset SQL like this:**
```sql
-- CORRECT — measures wrapped in MEASURE()
SELECT MEASURE(`Total Claims`) AS total_claims,
       MEASURE(`Total Paid Amount`) AS total_paid
FROM `catalog`.`schema`.`metric_view`

-- CORRECT — with GROUP BY for dimensional analysis
SELECT claim_type,
       MEASURE(`Total Paid Amount`) AS total_paid
FROM `catalog`.`schema`.`metric_view`
GROUP BY claim_type
```

**Backtick-quoting rules for MEASURE():**
- Multi-word measure names (e.g., `Total Claims`, `Total Paid Amount`) MUST be backtick-quoted inside `MEASURE()`: `MEASURE(`Total Paid Amount`)`
- Single-word measure names (e.g., `denial_rate`) can be unquoted: `MEASURE(denial_rate)` — but backtick-quoting is always safe
- The measure name inside `MEASURE()` MUST match an EXACT deployed measure name returned by live `DESCRIBE TABLE` on the Metric View; use live `SHOW CREATE TABLE` to inspect its deployed expression

Each dataset SQL must have an expected result shape.

Expected shapes and SQL patterns:

```text
COUNTER → exactly one analytical row
TREND → one row per time grain
BAR → one row per category
TABLE → one row per requested dimensional combination
```

Reference MEASURE() query patterns:

**CRITICAL: Column names below are EXAMPLES ONLY. Replace with actual dimension names discovered from DESCRIBE in Step 2. Never assume a column name exists — verify against your Step 2.1 field inventory.**

```sql
-- COUNTER (one-row summary, no GROUP BY needed for overall totals)
SELECT MEASURE(total_paid) AS total_paid,
       MEASURE(total_claims) AS total_claims
FROM `<catalog>`.`<schema>`.`<metric_view>`

-- TREND (time series — use DATE_TRUNC on actual temporal dimension)
-- NOTE: Use the ACTUAL dimension name from DESCRIBE (e.g., service_date, NOT service_month)
SELECT DATE_TRUNC('MONTH', service_date) AS service_month,
       MEASURE(total_paid) AS total_paid
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY DATE_TRUNC('MONTH', service_date)
ORDER BY service_month

-- BAR (category comparison — use actual dimension name from DESCRIBE)
SELECT claim_type,
       MEASURE(total_paid) AS total_paid
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY claim_type

-- GLOBAL FILTER BINDING (not a dedicated dataset)
-- Include the exact filter dimensions in every canvas dataset that the filters control.
-- Filter widgets bind to that same dataset/queryName; do not create a separate filter-only query.
```

### Filter-Compatible Canvas Datasets

Every canvas-page dataset MUST also include the global filter dimension columns (so filters can bind), as defined in `lakeview_dashboard_api.md`.

The filter widget field names MUST exactly match columns in the same bound canvas dataset. Both
the widget binding and dataset SQL must use actual deployed Metric View dimension names.

```sql
-- CORRECT: filter on actual dimension (service_date), trend uses DATE_TRUNC alias
SELECT DATE_TRUNC('MONTH', service_date) AS service_month,
       service_date,           -- for filter binding
       line_of_business,       -- for filter binding
       claim_type,             -- for filter binding
       MEASURE(total_paid) AS total_paid
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY DATE_TRUNC('MONTH', service_date), service_date, line_of_business, claim_type
ORDER BY service_month

-- INCORRECT: filter on derived alias that doesn't match canvas datasets
SELECT service_month,        -- DOES NOT EXIST as a metric view dimension
       MEASURE(total_paid) AS total_paid
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY service_month       -- WILL FAIL: UNRESOLVED_COLUMN
```

### Counter Datasets with Filter Binding

For counters that should respond to global filters, include filter dims in the dataset:

```sql
-- Additive measures — widget uses SUM(`total_paid`) to collapse rows
SELECT service_date, line_of_business, claim_type,
       MEASURE(total_paid) AS total_paid,
       MEASURE(total_claims) AS total_claims
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY service_date, line_of_business, claim_type

-- Ratio measures — widget must reconstruct from components, NOT sum the ratio
SELECT service_date, line_of_business, claim_type,
       MEASURE(denied_lines) AS denied_lines,
       MEASURE(total_claim_lines) AS total_claim_lines
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY service_date, line_of_business, claim_type
-- Widget expression: "SUM(`denied_lines`) / SUM(`total_claim_lines`)"
-- NOT: "SUM(`denial_rate`)"  ← WRONG (cannot sum ratios)
```

---

# Step 7.1: Execute Every Dataset Query (INDIVIDUAL VALIDATION)

Before adding any dataset to a dashboard, ALL datasets must be validated.

Validate each dataset as its own SQL statement. Do not combine unrelated dashboard datasets with
`UNION ALL` or submit a multi-statement batch: doing so can hide per-dataset shape, alias, and error
evidence. The attested helper still uses the Statement Execution API; `spark.sql()` is forbidden.

```python
if "dataset_sql_by_name" not in globals() or not isinstance(dataset_sql_by_name, dict):
    raise GateCheckError("DATASET_SQL_VALIDATION_FAILURE: dataset SQL inventory is missing")
if not dataset_sql_by_name:
    raise GateCheckError("DATASET_SQL_VALIDATION_FAILURE: dataset SQL inventory is empty")

validated_columns_by_dataset = {}
for dataset_name, dataset_sql in dataset_sql_by_name.items():
    if not isinstance(dataset_name, str) or not dataset_name:
        raise GateCheckError("DATASET_SQL_VALIDATION_FAILURE: invalid dataset name")
    if not isinstance(dataset_sql, str) or not dataset_sql.strip():
        raise GateCheckError(f"DATASET_SQL_VALIDATION_FAILURE: empty SQL for {dataset_name}")
    validated_columns_by_dataset[dataset_name] = validate_dataset_sql(
        dataset_sql,
        dataset_name,
        warehouse_id,
    )
```

Validate:

```text
query executes successfully
result is non-empty when source data exists
expected columns exist
expected aliases exist
result shape matches widget expectation
measure values are non-null where expected
dimension values are usable
row count is reasonable
```

A successful SQL statement that returns the wrong shape is a failure.

---

# Step 7.2: Dataset Validation Contract

Write:

```text
{OUTPUT_FOLDER}/dashboards/dashboard_dataset_validation.yaml
```

containing:

```yaml
datasets:

  - name:
    dashboard:
    page:
    widget:

    sql_status:
      PASS | FAIL

    metric_view:

    expected_shape:
    actual_rows:
    actual_columns:

    measures:
    dimensions:
    filters:

    semantic_status:
      PASS | FAIL

    failure_reason:
```

Only datasets with:

```text
sql_status: PASS
semantic_status: PASS
```

may be included in `serialized_dashboard`.

---

# Step 8: Build Dataset Objects

Use the project's supported helpers:

```python
# Schema discovery + validation (use warehouse_id, NOT spark.sql)
describe_metric_view(metric_view_fqn, warehouse_id)  # → {col: {type, is_dimension, is_measure}}
validate_dataset_sql(sql, dataset_name, warehouse_id)  # → [col_name, ...]
build_validated_dataset(name, sql, display_name, warehouse_id)  # → dataset dict (validates + builds)
_execute_sql_via_api(stmt, warehouse_id)  # → (columns, rows) low-level Statement Execution API

# Dataset
build_dataset(name, sql, display_name)

# Widget builders (canvas pages)
build_text_widget(name, markdown, position)        # sole approved text-widget serializer
build_counter(name, dataset_name, field_name, display_name, title, agg, position)
build_bar_chart(name, dataset_name, x_field, y_field, y_display, title, agg, position)
build_line_chart(name, dataset_name, x_field, y_field, y_display, title, agg, position)

# Filter widgets (MUST use same dataset_name as canvas widgets)
build_filter_widget(name, dataset_name, field_name, display_name, widget_type, position)

# Page builders
build_filters_page(dataset_name, filter_dimensions)  # PAGE_TYPE_GLOBAL_FILTERS
build_canvas_page(name, display_name, layout)        # PAGE_TYPE_CANVAS

# Assembly + validation
build_serialized_dashboard(datasets, pages, filter_dimensions)

# End-to-end (PREFERRED — includes gate enforcement)
deploy_dashboard(
    display_name, warehouse_id, parent_path, datasets, pages, filter_dimensions,
    required_artifacts=[...],   # paths to design contract + dataset validation YAML
    quality_gates=quality_gates, # exact frozen run_context.quality_gates
    output_folder=OUTPUT_FOLDER, # writes dashboards/{display_name}_validation.yaml after deploy
)
```

### Gate Enforcement Built Into deploy_dashboard()

`deploy_dashboard()` MUST use the attested `gate_checks.py` and includes automatic structural-gate
enforcement plus separate quality-target evaluation:

- **Pre-deploy structural layer**: before the API call, verifies the exact page contract, at least
  one widget on every canvas page, the required global-filter page and functional bindings, valid
  dataset/widget references, and all `required_artifacts`. Any failure raises `GateCheckError` and
  the API call never executes.
- **Quality layer**: evaluates every field named by
  `quality_gates.dashboard_policy.quality_target_fields` and records `PASS` or `WARN`; a `WARN`
  never raises `GateCheckError` and never blocks the API call.
- **Post-deploy structural layer**: after create + publish, reads the dashboard back and verifies
  identity, exact expected counts, page contract, bindings, and published state. It writes
  `{OUTPUT_FOLDER}/dashboards/{display_name}_validation.yaml` with `source: api_readback`. Only the
  later master cross-asset sweep writes root `ground_truth_validation.yaml`.

This means a non-empty mapped page below the preferred widget count or a dashboard below the
preferred filter count receives a quality `WARN`, while a missing mapped page, empty canvas page,
missing required filter page, invalid binding, or readback mismatch raises `GateCheckError`.

Do NOT catch and suppress `GateCheckError`. If it fires, the dashboard is incomplete and must be fixed.

### Canonical API-readback result attestation

The `expected` argument is required and contains the frozen `workspace_host`,
`warehouse_id`, exact compiled `serialized_dashboard`, and `primary_kpi_contexts`
(mapping every primary KPI ID to its duplicate-free compiled widget IDs). Assemble
this from validated design/compiler output before any API call. In the executable
example, bind `primary_kpi_contexts_by_dashboard` from those design mappings.
Configure the attested builder with `configure_runtime(w, gate_checks_module, store,
expected_contracts)` before deployment. No ambient helper/client import is permitted.
The release-selected notebook takes `RUN_CONTEXT_PATH`, `RUN_CONTRACT_PATH`, and
`RUN_CONTRACT_SHA256` in addition to its existing placeholders; resolve these from
Step 0. Both validator keyword arguments are mandatory.


For every dashboard, the only accepted post-deploy validator is the attested `gate_checks_module.validate_dashboard_from_api`. Its canonical signature is `validate_dashboard_from_api(workspace_client, dashboard_id, display_name, quality_gates=..., expected=...)`; call it with the bound `WorkspaceClient`, exact returned dashboard ID, exact handoff display name, and frozen quality gates. Its return value MUST be a mapping and MUST attest all of the following before any validation artifact or successful manifest is accepted:

- `status: PASS`, `source: api_readback`, `structural_status: PASS`, and `page_contract_status: PASS`;
- `quality_target_status: PASS|WARN`, complete `quality_target_results`, and the exact derived pair
  `PASS -> stage_status: PASS` or `WARN -> stage_status: PARTIAL_SUCCESS`;
- `workspace_host_binding: PASS`, produced only after the validator compares the bound client's configured host to frozen `step_handoff.workspace_host` (normalize only a trailing `/`; never accept the active SDK profile as an implicit substitute); if the result also exposes the observed host, it MUST equal that frozen host after the same normalization;
- `dashboard_id` exactly equals the create/update result ID and manifest locator;
- `display_name` exactly equals the matching handoff display name;
- `readback_counts.dataset_count`, `canvas_page_count`, `filter_page_count`, `widget_count`, and `filter_count` exactly equal the counts independently derived from validated `dashboard_design.yaml` and `dashboard_dataset_validation.yaml` for that dashboard; and
- top-level `datasets_validated: true` proves the complete expected dataset set was validated.

Missing keys, a non-mapping result, host/identity/count/page-contract mismatch, or non-PASS
structural status raises `GateCheckError` and is a Dashboard-stage validation failure. A valid
quality `WARN` is preserved and does not raise. Step 16 separately requires supported official
publication-state readback; `UNKNOWN` still fails publication. Do not coerce either result, fill
missing values from the request, or replace it with a manual Lakeview GET assertion.

### CRITICAL: Shared Dataset Pattern

`build_filter_widget` takes `dataset_name` as its SECOND argument. This MUST be the same
dataset name used by canvas widgets on the page. Do NOT create a separate `ds_filter_values` dataset.

### CRITICAL: Text Widget Serialization Authority

Pass only `(name, markdown, position)` to the digest-attested `build_text_widget()`. Treat its
returned mapping as opaque and append it unchanged to the canvas layout. No prompt-generated code,
design artifact, compatibility adapter, or post-processing step may emit or patch text-widget wire
fields. If the helper cannot serialize the widget, halt with `DASHBOARD_HELPER_CONTRACT_ERROR`.

Every dashboard dataset MUST have a non-empty tested query.

Dataset format MUST follow `lakeview_dashboard_api.md` exactly:

```json
{
  "name": "ds_example",
  "displayName": "Example Dataset",
  "queryLines": ["SELECT ... FROM ..."]
}
```

Required properties:

- `name`: short identifier (referenced by widgets)
- `displayName`: human label
- `queryLines`: array of strings (NOT a `query` string field)

Prohibited:

```json
{"query": ""}
{"query": "SELECT ..."}
```

Using `query` (string) instead of `queryLines` (array) causes silent rendering failures. An empty-query dataset is a pipeline error.

---

# Step 8.1: Filter Dataset (DEPRECATED — Use Shared Dataset Pattern)

Do NOT create a separate `ds_filter_values` dataset. The `build_filter_dataset()` function is DEPRECATED.

Instead, include filter dimension columns in each canvas-page dataset and have filter widgets reference that same dataset. This is the ONLY pattern that enables cross-filtering in API-created dashboards.

The shared dataset pattern is:
1. ONE dataset per canvas page includes BOTH filter dimensions AND measures in GROUP BY
2. Filter widgets reference this dataset with `disaggregated: true`
3. Canvas widgets reference this dataset with `disaggregated: false` + SUM/AVG

See `lakeview_dashboard_api.md` § "Shared Dataset Pattern (REQUIRED for filters to work)" for details.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "build_datasets"
> - `phase_name`: "Build Datasets"
> - `status`: "completed"
> - `findings`: ["{N} datasets validated", "All queries execute successfully"]
> - `stats`: {"datasets_built": N, "queries_validated": N}

---

# Step 9: Construct Widgets

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "create_dashboard"
> - `phase_name`: "Create Dashboard"
> - `status`: "started"
> - `current_task`: "Constructing widgets and creating via Lakeview API"
> - `happenings`: ["Building widget specifications", "Constructing layout", "Calling Lakeview API"]

Only after dataset validation passes may widgets be generated.

For every widget validate:

```text
dataset exists
field names exist in dataset
encoding field names exactly match dataset field names
visualization type matches expected data shape
title matches KPI meaning
```

Widget JSON MUST follow:

```text
lakeview_dashboard_api.md
```

exactly.

### Critical Field Name Convention

The `query.fields[].name` MUST exactly match `spec.encodings.*.fieldName`.

For aggregated measures, the field name includes the aggregation function:

```json
"fields": [{"name": "sum(total_paid)", "expression": "SUM(`total_paid`)"}]
```

And the encoding references the same string:

```json
"encodings": {"y": {"fieldName": "sum(total_paid)", "displayName": "Total Paid"}}
```

For dimension fields, the field name matches the column:

```json
"fields": [{"name": "claim_type", "expression": "`claim_type`"}]
```

Mismatch between `fields[].name` and `encodings.*.fieldName` produces:

```text
"Visualization has no fields selected"
```

This is the single most common widget rendering failure.

---

# Widget Specification Rule

Do NOT hardcode widget:

```text
spec.version
encodings
field structures
queryName behavior
```

from model memory.

Use the exact current definitions contained in:

```text
lakeview_dashboard_api.md
```

If that file defines different structures for:

```text
counter
bar
line
pie
table
filter
```

follow them exactly.

---

# Step 10: Layout Design

Build canvas layouts according to the grid/layout contract in:

```text
lakeview_dashboard_api.md
```

Design rules:

- avoid overlapping widgets;
- avoid unintended gaps;
- align related widgets;
- use consistent sizing;
- make headline KPIs visually prominent;
- give detailed charts sufficient space;
- keep analytical flow readable from top to bottom.

Do not optimize for maximum widget density.

Prefer clarity.

---

# Step 10.1: Page Validation

Before API creation validate every page:

```text
page has valid page type
page has widgets
all widget positions are valid
no overlapping layout coordinates
all referenced datasets exist
all widget field references resolve
```

---

# Step 11: Build serialized_dashboard

Construct the dashboard only through the project builder defined by:

```text
lakeview_dashboard_api.md
```

For example, when supported:

```python
serialized_dashboard = build_serialized_dashboard(
    datasets=datasets,
    pages=pages,
    filter_dimensions=filter_dimensions
)
```

The exact signature must come from the current project helper.

Do not guess helper arguments.

---

# Step 11.1: Preflight Structural Validation

Before calling the Lakeview API validate:

```text
serialized_dashboard is non-empty
datasets exist
every dataset has tested non-empty SQL
pages exist
every page contains valid widgets
every widget references an existing dataset
every encoding field resolves
filter references resolve
layout is complete
```

If any preflight check fails:

```text
DASHBOARD_SERIALIZATION_VALIDATION_FAILURE
```

Do NOT call the Create Dashboard API.

---

# Step 12: Idempotency

For every resolved dashboard display name:

list existing dashboards using the supported Lakeview API.

Handle pagination completely.

Match only exact `step_handoff.yaml.dashboard_display_names[].display_name` values for the frozen current-run dashboard IDs. The accelerator request file is not the idempotency identity authority.

Do NOT use:

```text
subprocess
databricks CLI
```

inside notebooks.

Use:

```text
Databricks SDK
WorkspaceClient API client
or supported REST agent tools
```

---

# Idempotency Strategy

Use the exact `deployment.idempotency_strategy` frozen on the matching `run_context.assets.dashboards[]` entry. The accelerator value is requested/drift evidence only. HALT with `DASHBOARD_DEPLOYMENT_POLICY_MISSING` if this field was not frozen.

Preferred behavior:

```text
existing matching dashboard
        ↓
update existing draft when supported/configured
```

rather than deleting a dashboard unnecessarily.

If the project's versioning strategy intentionally creates immutable versioned dashboard names, creation of the new version is acceptable.

If the configured strategy requires replacement:

```text
delete existing matching version
        ↓
create replacement
```

Do not delete unrelated dashboard versions.

---

# Step 13: Create Dashboard Through Lakeview API

### Pre-Flight Checklist

Before calling the Lakeview Create/Update API, confirm ALL of:

- [ ] `dashboard_design.yaml` exists (Step 3 complete)
- [ ] Live `DESCRIBE TABLE` and `SHOW CREATE TABLE` were captured for every exact FQN in `step_handoff.yaml`
- [ ] Planned/validated Metric View assignments resolve against that deployed readback
- [ ] `dashboard_dataset_validation.yaml` shows ALL datasets as `sql_status: PASS` + `semantic_status: PASS`
- [ ] `serialized_dashboard` contains `datasets` AND `pages` (never datasets-only)
- [ ] Every page has `pageType` set (`PAGE_TYPE_GLOBAL_FILTERS` or `PAGE_TYPE_CANVAS`)
- [ ] Every widget references an existing dataset by `datasetName`
- [ ] Every widget `query.fields[].name` exactly matches `spec.encodings.*.fieldName`
- [ ] Counter widgets use `spec.version: 2`
- [ ] Chart widgets (bar/line/pie) use `spec.version: 3`
- [ ] Filter widgets use `spec.version: 2` with `queryName` in `encodings.fields[]`
- [ ] Canvas widget queries have `disaggregated: false`; filter queries have `disaggregated: true`
- [ ] `display_name` exactly matches the corresponding `step_handoff.yaml dashboard_display_names[].display_name`
- [ ] `warehouse_id` is set

If any item fails, return to the relevant design/build step. Do NOT call the API with known defects.

### Critical Lakeview JSON Structure Rules

These rules reflect the approved versioned local Lakeview contract/template pinned and regression-validated for this run. Violations produce `child node [widget] not found` or silent rendering failures. Live documentation or model memory cannot replace the pinned contract during execution.

**1. Layout item nesting:** Each layout item wraps the widget under a `widget` key, with `position` as a sibling:

```text
pages[].layout[] = {
  "widget": { "name": ..., "queries": [...], "spec": {...} },
  "position": { "x": 0, "y": 0, "width": 2, "height": 2 }
}
```

INCORRECT (causes `child node [widget] not found`):

```text
pages[].layout[] = {
  "name": ..., "queries": [...], "spec": {...}, "position": {...}
}
```

**2. Page types:** The `serialized_dashboard` must include a `PAGE_TYPE_GLOBAL_FILTERS` page for filters, and `PAGE_TYPE_CANVAS` pages for widgets. Filter pages are separate from canvas pages.

**3. Deployment method — use the template notebook pattern (MANDATORY):**

The `create_dashboard` and `publish_dashboard` tools are DISABLED. Dashboard deployment MUST follow the template notebook pattern (same as metric views and Genie spaces):

1. The LLM produces `dashboard_design.yaml` (declarative spec — pages, widgets, datasets, filters)
2. The LLM uses the exact `run_context.templates.dashboard_notebook.path` and paired SHA-256 (selected by contracts/release.yaml), and populates Cell 1 with configuration from `step_handoff.yaml` and `dashboard_design.yaml`
3. The LLM copies Cells 2-N VERBATIM from the template (they handle compilation, deployment, readback, and manifest writing)
4. The LLM saves the notebook to `{OUTPUT_FOLDER}/dashboards/dashboard_deployment.ipynb`
5. The LLM executes the notebook

The template handles:
- Gate 1 (structural validation of design spec)
- Gate 2 (metadata validation — metric view columns accessible)
- Gate 3 (semantic validation — widget/field references resolve)
- Gate 4 (deployment — Lakeview API create + publish, readback, manifest writing)

**CRITICAL:** Do NOT use `create_dashboard` or `publish_dashboard` tools — they are DISABLED.
Do NOT use `execute_python` with SDK calls (`w.lakeview.create(...)`, `w.api_client.do(...)`) — the subprocess has NO WorkspaceClient and NO access to Databricks APIs.
Do NOT use `requests.post()` with tokens.
The template notebook handles authentication, compilation, deployment, and error handling internally.

**5. Multiple dashboards:** When current-run `run_context.yaml` defines `assets.dashboards[]` with multiple entries, create ALL frozen configured dashboards — not just one. Each may have multiple pages. Do not change that set from a later edit to `accelerator.yaml`.

Use the official Lakeview Dashboard API.

The API call MUST use the exact Create Dashboard request contract defined by the approved versioned local reference and project helper implementation.

Conceptually:

```text
POST
/api/2.0/lakeview/dashboards
```

using the required fields such as the resolved dashboard metadata and serialized definition according to the approved versioned local contract.

Do not construct undocumented top-level request properties.

Do not use Workspace file import as a substitute for the Lakeview Create Dashboard API unless the matching frozen `run_context.assets.dashboards[].deployment.transport` is exactly `workspace_import_export`. Do not consult the live accelerator to choose transport.

---

# Step 13.1: Capture Create Response

Capture:

```text
dashboard_id
display_name
etag when available
path when available
API status
```

Do not assume creation succeeded solely because no exception was thrown.

Validate the response contains the required dashboard identity.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "create_dashboard"
> - `phase_name`: "Create Dashboard"
> - `status`: "started"
> - `findings`: ["Dashboard Create/Update request accepted provisionally", "Dashboard ID returned; persisted state not yet validated"]
> - `stats`: {"widgets_requested": W, "pages_requested": P, "dashboard_id_returned": true}

---

# Step 14: Retrieve Persisted Draft

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_publish"
> - `phase_name`: "Validate & Publish"
> - `status`: "started"
> - `current_task`: "Validating dashboard and running post-publish checks"
> - `happenings`: ["Structural diff check", "Filter validation", "KPI coverage validation"]

Immediately after create/update, retrieve the dashboard through the Lakeview Get Dashboard API.

Compare the persisted representation with the intended dashboard design.

Validate at minimum:

```text
dashboard exists
display_name matches
warehouse configuration matches
serialized dashboard exists
expected pages exist
expected datasets exist
expected widgets exist
```

This step is mandatory.

The Lakeview API GET response is authoritative for the dashboard state actually persisted by the service. `dashboard_design.yaml` remains the desired-state contract. A material difference between them is a deployment validation failure; do not rewrite the design or manifest to make the difference appear intentional.

---

# Step 14.1: Structural Diff

Compare:

```text
INTENDED DASHBOARD
vs
PERSISTED DASHBOARD
```

Check:

```text
dataset count
page count
widget count
filter count
dataset names
page names
widget identities
```

Do not require byte-for-byte serialized JSON equality because the service may normalize representation.

Validate semantically relevant structure.

Only after this persisted-draft comparison passes, call `report_progress` for `create_dashboard` with `status: "completed"`, findings that the draft was verified by GET, and page/widget counts from that GET readback.

---

# Step 15: Publish

Only publish after persisted-draft validation passes.

Use the supported Lakeview Publish Dashboard API/helper.

Capture publication response.

If publishing fails:

```text
DASHBOARD_PUBLISH_ERROR
```

Do not report the dashboard as complete.

---

# Step 16: Post-Publish Validation

Validate the published dashboard.

Using the approved versioned Lakeview contract's official publication-state readback, verify:

```text
published state
dashboard identity
warehouse
page/widget inventory
```

Also execute representative underlying dataset queries to ensure data remains available.

If the approved readback cannot expose or confirm publication state, record it as `UNKNOWN`; do not write `published: true`, claim publication success, or infer it from request acceptance.

---

# Step 16.1: Filter Validation

For every filter validate:

```text
filter field exists
filter dataset/source exists where required
compatible target datasets exist
field names match exactly
filter has usable values
```

For categorical filters:

```text
distinct usable values > 0
```

when source data exists.

For temporal filters:

```text
valid min/max range
```

when source data exists.

---

# Step 16.2: Filter Impact Validation

Do not validate filters only structurally.

For representative filters, test that applying a valid dimension value changes or appropriately constrains the underlying KPI dataset.

Conceptually:

```text
UNFILTERED KPI
vs
FILTERED KPI
```

The filtered result should be analytically consistent with the filter.

This test must use the same validated Metric View.

---

# Step 17: KPI Coverage Validation

For every KPI from Dashboard Mapping report one of:

```text
RENDERED_AND_VALIDATED
SKIPPED_NOT_VALIDATED_IN_METRIC_LAYER
SKIPPED_MISSING_DATA
SKIPPED_UNSUPPORTED_VISUALIZATION
DASHBOARD_GENERATION_FAILURE
```

Every validated KPI assigned to the dashboard must either be rendered successfully or have an explicit dashboard-stage failure reason.

---

# Step 18: Visualization Validation

For every widget validate:

```text
KPI maps to correct measure
dimensions match Dashboard Mapping
chart type is appropriate
dataset shape matches visualization
field references resolve
data exists when expected
title accurately describes content
```

Do NOT consider a widget valid simply because its JSON is accepted by the API.

---

# Step 19: Dashboard Validation Artifact

### GATE 19.1: Ground-Truth Validation Required

Because the digest-pinned `gate_checks.py` contract and its canonical validator are mandatory, `deploy_dashboard()` with `output_folder` and the subsequent `validate_dashboard_from_api()` attestation MUST produce per-dashboard validation YAMLs with `source: api_readback`. These are derived evidence of the Lakeview API GET response captured at validation time. The API response is the deployed-state authority; the validation artifact records the expected-versus-actual comparison.

Do NOT overwrite `source: api_readback` validation files with `source: agent_reported` content. If the API readback validation already exists and shows `overall_status: PASS`, use it directly.

If the frozen helper is missing, unreadable, digest-mismatched, incompatible, or cannot perform official GET/readback, HALT with `DASHBOARD_HELPER_CONTRACT_ERROR` or `DASHBOARD_API_GET_ERROR` as applicable. Manual/fallback validation and manually authored readback assertions are prohibited.

The canonical helper MUST write:

```text
{OUTPUT_FOLDER}/dashboards/{name}_validation.yaml
```

Do not write or patch this artifact manually. Require the helper-produced artifact to include:

```yaml
source: api_readback
readback_timestamp:
workspace_host_binding: PASS
datasets_validated: true
structural_status: PASS
page_contract_status: PASS
quality_target_status: PASS | WARN
stage_status: PASS | PARTIAL_SUCCESS
quality_target_results:
  - field:
    expected:
    actual:
    status: PASS | WARN
dashboard:
  dashboard_id:
  display_name:
  status:
  published:

source_metric_views: []

readback_counts:
  dataset_count:
  canvas_page_count:
  filter_page_count:
  widget_count:
  filter_count:

pages:
  expected:
  actual:
  status:

datasets:
  expected:
  actual:
  empty_queries:
  failed_queries:
  status:

widgets:
  expected:
  actual:
  invalid_widgets:
  status:

filters:
  expected:
  actual:
  binding_failures:
  impact_tests:
  status:

kpis:
  - name:
    metric_validation_status:
    dashboard_status:
    widget:
    page:

api:
  create_status:
  get_status:
  publish_status:

overall_status:
  PASS | FAIL
```

`overall_status` reports mandatory structural validity only. It is `PASS` for either valid quality
outcome; `quality_target_status: WARN` must pair with `stage_status: PARTIAL_SUCCESS` and must remain
visible in documentation and the master reconciliation.

---

# Step 20: Dashboard Manifest

Write:

```text
{OUTPUT_FOLDER}/dashboards/{name}_manifest.json
```

containing:

```json
{
  "evidence_type": "asset_locator_and_deployment_attempt",
  "artifact_id": "<unique manifest/deployment artifact ID>",
  "source_hash": "<sha256 of dashboard_design.yaml after deterministic normalization>",
  "generated_hash": "<sha256 of the serialized dashboard request>",
  "readback_hash": "<sha256 of normalized Lakeview GET state>",
  "state_comparison": "match",
  "dashboard_id": "...",
  "display_name": "...",
  "metric_views": [],
  "pages": [],
  "dataset_count": "<readback-derived integer>",
  "canvas_page_count": "<readback-derived integer>",
  "filter_page_count": "<readback-derived integer>",
  "widget_count": "<readback-derived integer>",
  "filter_count": "<readback-derived integer>",
  "datasets_validated": true,
  "published": true,
  "structural_status": "PASS",
  "page_contract_status": "PASS",
  "quality_target_status": "PASS|WARN",
  "stage_status": "PASS|PARTIAL_SUCCESS",
  "quality_target_warnings": [
    {"field": "<target field>", "expected": "<frozen target>", "actual": "<observed>", "status": "WARN"}
  ],
  "validation_source": "api_readback",
  "validation_artifact": "<path-to-api-readback-validation>"
}
```

Write this canonical manifest only when the matching validation artifact has `overall_status: PASS`,
`structural_status: PASS`, `page_contract_status: PASS`, `state_comparison` is `match`, top-level
`datasets_validated: true`, and official readback confirms `published: true`; otherwise write the
failed validation evidence and HALT without a successful canonical manifest. A
`quality_target_status: WARN` does not block the manifest: copy it, its warnings, and
`stage_status: PARTIAL_SUCCESS` exactly. Map the five count fields directly from `readback_counts`
and map `datasets_validated` from the matching validation artifact's top-level boolean. The
manifest is an asset locator and deployment-attempt evidence only; it MUST NOT override a later
Lakeview API GET response.

The actual deliverable remains the live Lakeview dashboard.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_publish"
> - `phase_name`: "Validate & Publish"
> - `status`: "completed"
> - `findings`: ["Dashboard published", "Structural validation PASS", "Quality targets: PASS|WARN", "KPI coverage: {N}/{T}"]
> - `stats`: {"validations_passed": N, "quality_target_warnings": W, "kpi_coverage_pct": P}

---

# Step 21: Final Summary

For each dashboard present:

| Check | Result |
|---|---|
| Validated KPIs mapped | PASS/FAIL |
| Dataset SQL | PASS/FAIL |
| Widget definitions | PASS/FAIL |
| Page contract | PASS/FAIL |
| Structural validation | PASS/FAIL |
| Quality targets | PASS/WARN |
| Create API | PASS/FAIL |
| Persisted draft GET | PASS/FAIL |
| Publish API | PASS/FAIL |
| Filters | PASS/FAIL |
| KPI coverage | PASS/FAIL |
| Dashboard stage | PASS/PARTIAL_SUCCESS/FAIL |

Include the deployed dashboard ID.

---

# Error Classification

Use one of:

```text
DASHBOARD_INPUT_AUTHORITY_ERROR
DASHBOARD_INPUT_ERROR
DASHBOARD_HELPER_CONTRACT_ERROR
METRIC_VIEW_NOT_VALIDATED
METRIC_VIEW_DEPLOYED_STATE_MISMATCH
KPI_MAPPING_ERROR
DASHBOARD_DESIGN_ERROR
DATASET_SQL_ERROR
DATASET_SHAPE_ERROR
FILTER_DESIGN_ERROR
FILTER_BINDING_ERROR
FILTER_IMPACT_ERROR
WIDGET_SPEC_ERROR
WIDGET_FIELD_ERROR
LAYOUT_ERROR
DASHBOARD_SERIALIZATION_ERROR
DASHBOARD_API_CREATE_ERROR
DASHBOARD_API_UPDATE_ERROR
DASHBOARD_API_GET_ERROR
DASHBOARD_API_DELETE_ERROR
DASHBOARD_PUBLISH_ERROR
PERSISTED_DASHBOARD_MISMATCH
WORKSPACE_IO_ERROR
```

## Owner-scoped repair routing

Classify ownership from authoritative evidence before proposing a repair. A consumer may report an upstream defect but MUST NOT mutate the owning artifact.

| Failure evidence | Owning repair stage | Required action here |
|---|---|---|
| Tool-supplied `run_context_path` is missing/malformed, is not the canonical path, or shared resolver fields in the original handoff conflict before Metric View finalization | Master resolver / Step 0 | HALT with `DASHBOARD_INPUT_AUTHORITY_ERROR`; preserve both values and rerun the resolver. |
| Plan/validation top-level run/suffix/strategy replay binding, auto producer checkpoint, synchronized Metric View entries, plan-payload/handoff digest, capability tuple, Metric View completion record, or plan/validation parity fails | Metric View stage | HALT and return the exact comparison to `{AGENT_SKILLS_DIR}/prompts/metric_views/instructions.md`; never rewrite the plan, handoff identities, checkpoint, validation, or phase history here. |
| Live Metric View FQN, column/type, definition, measure, or KPI assignment differs from validated upstream intent | Metric View stage (or Data Layer only when Metric View evidence explicitly identifies a source-table defect) | HALT with `METRIC_VIEW_DEPLOYED_STATE_MISMATCH`; do not add casts, aliases, substitute FQNs, or raw-table calculations in Dashboard SQL. |
| Digest-pinned dashboard helper/reference is missing, mismatched, incompatible, or fails callable/file attestation | Dashboard release contract | HALT with `DASHBOARD_HELPER_CONTRACT_ERROR`; do not synthesize helpers or use fallback validation. |
| Dashboard design, dataset shape, widget/filter/page layout, serialization, Lakeview deployment, or dashboard API readback differs | Dashboard stage | Repair only the owned dashboard design/deployment artifact, rerun its gates, and preserve upstream Metric View contracts unchanged. |
| Authentication, permission, transport, or workspace I/O fails | Operational owner | HALT with the exact platform error; content regeneration is not a repair. |

`GateCheckError` is never suppressed. Route its evidence using this table: pre-deploy/dashboard post-deploy gate failures belong to the Dashboard stage; an embedded upstream identity or deployed-Metric-View mismatch belongs to the Metric View stage. Never use a generic retry to cross an ownership boundary.

For every error provide:

```text
Observed problem:
Root cause:
Authoritative evidence:
Dashboard:
Page:
Widget:
Dataset:
Affected KPI(s):
Corrective action:
Affected downstream artifacts:
```

---

# Retry Policy

Blind retries are prohibited.

Do NOT:

```text
create
fail
change random JSON
retry
change widget version
retry
change encodings
retry
```

When an error occurs:

1. capture the complete API response or SQL error;
2. classify the failure;
3. identify the responsible contract;
4. make one targeted correction;
5. rerun the relevant preflight validation;
6. retry only after the root cause is understood.

Maximum API creation/update attempts:

```text
3
```

Each retry must have a documented cause and correction.

---

# Pipeline Halt Rules

Return:

```text
❌ EXECUTION HALTED
```

when any mandatory dashboard cannot be reliably deployed.

Halt conditions include:

- required Metric View does not exist;
- required KPI is marked validated but its Metric View measure cannot be queried;
- dataset SQL fails after diagnosed corrections;
- dataset result shape is incompatible with the intended widget;
- serialized dashboard fails preflight validation;
- required widget references nonexistent fields;
- Lakeview API rejects the dashboard after diagnosed corrections;
- persisted dashboard differs materially from intended design;
- dashboard cannot be published;
- mandatory filters cannot be bound correctly.

A failure isolated to an optional KPI/widget does not necessarily halt unrelated dashboards.

Document and continue when safe.

---

# Non-Negotiable Rules

1. **Dashboard logic consumes validated Metric Views; it does not redefine metrics.**
2. **Only `IMPLEMENTED_AND_VALIDATED` KPIs are authoritative dashboard KPIs.**
3. **Never repair Metric View modeling problems inside dashboard SQL.**
4. **Use `MEASURE()` for validated Metric View measures.**
5. **Dashboard Mapping controls KPI-to-dashboard/page assignment.**
6. **Visualization type must follow analytical intent and result shape.**
7. **Do not use pie charts merely for visual diversity.**
8. **Do not hardcode domain-specific filters.**
9. **Do not change dataset grain merely to expose a global filter column.**
10. **Every widget dataset must be executed and validated before dashboard creation.**
11. **Every dataset must contain non-empty SQL.**
12. **Dataset execution success alone does not prove correct dataset shape.**
13. **Every widget field reference must exactly resolve to its dataset.**
14. **`lakeview_dashboard_api.md` is authoritative for serialized-dashboard structure.**
15. **Do not hardcode widget serialization details in this orchestration prompt; every text widget
    must be serialized only by the attested `build_text_widget()` helper.**
16. **Use the official Lakeview API / SDK API client for live dashboard deployment.**
17. **Do not use Databricks CLI via subprocess in notebooks.**
18. **Do not use `.lvdash.json` workspace files as the deployed dashboard deliverable.**
19. **Retrieve the persisted dashboard after creation/update and validate it.**
20. **Publish only after persisted-draft validation passes.**
21. **API success does not prove analytical dashboard correctness.**
22. **Validate filter binding and representative filter impact.**
23. **Never use blind API retries.**
24. **Workspace artifact writes use `workspace_file_io.md`, never `dbutils.fs`.**
25. On unrecoverable mandatory failure:

```text
❌ EXECUTION HALTED
```

---

# Output Contract

At the END of this step, the following artifacts MUST exist for EACH dashboard in current-run `run_context.yaml assets.dashboards[]`:

| Artifact | Location | Validation Check |
|----------|----------|-----------------|
| dashboard_design.yaml | `{OUTPUT_FOLDER}/dashboards/` | Contains pages[], widgets[], filters[] for EACH dashboard |
| dashboard_dataset_validation.yaml | `{OUTPUT_FOLDER}/dashboards/` | All dataset queries executed successfully |
| `{name}_manifest.json` | `{OUTPUT_FOLDER}/dashboards/` | Locates `dashboard_id` and records deployment attempt/readback evidence; not deployed-state proof |
| {name}_validation.yaml | `{OUTPUT_FOLDER}/dashboards/` | `source: api_readback`; records desired-versus-deployed comparison |
| Live dashboard in workspace | Databricks workspace | GET /api/2.0/lakeview/dashboards/{id} returns valid response |
| Published dashboard | Databricks workspace | Dashboard is accessible via published URL |

### Per-Dashboard Requirements

Each manifest MUST record the canonical schema fields above as locator/attempt metadata. The
corresponding API-readback validation artifact MUST independently confirm: the exact mapped-page
inventory (or non-empty fallback inventory) passes; every canvas page is non-empty; required filter
pages and bindings pass; `dataset_count` matches the validated dataset inventory;
`datasets_validated: true`; and `published: true`. It MUST separately record PASS/WARN results for
the preferred page count, widget density, visualization diversity, filter count, and primary-KPI
contexts. Those targets do not become manifest-blocking structural gates.

If ANY artifact is missing or any dashboard is not published, the step has NOT completed successfully.

---

# MANDATORY PRE-DEPLOY SELF-CHECK (read LAST before any API call)

## Purpose

This final gate prevents name drift, invalid FQN quoting, unvalidated dataset SQL, and bypass of the
digest-attested deployment template. The checks are non-negotiable.

## Pre-Deploy Check Artifact (GATE)

**Before ANY dashboard deployment via the template notebook**, the agent MUST produce and print the following self-check. If ANY check shows `FAIL`, the agent MUST NOT proceed.

```yaml
# pre_deploy_check (print to stdout before API call)
dashboard_name_check:
  configured_name: "{exact matching dashboard_display_names[].display_name from step_handoff.yaml}"
  name_being_used: "{exact value being passed as display_name}"
  match: true/false  # MUST be true

fqn_format_check:
  fqn_in_dataset_sql: "{exact FQN string as it appears in queryLines}"
  format: "3_separate_backtick_pairs"  # MUST be this value
  # CORRECT: `catalog`.`schema`.`table`
  # WRONG:  `catalog.schema.table`
  valid: true/false  # MUST be true

template_usage_check:
  helper_function_used: "{function name from lakeview_dashboard_helpers.py.template}"
  # Expected: deploy_dashboard() or build_validated_dataset()
  # FAIL if: "none" or "hand-constructed JSON"
  valid: true/false

dataset_sql_execution_check:
  all_datasets_executed: true/false  # MUST be true
  failed_datasets: []  # MUST be empty
```

**Rules:**
- If `dashboard_name_check.match` is `false` → **HALT. Fix the name.**
- If `fqn_format_check.valid` is `false` → **HALT. Fix the quoting.**
- If `template_usage_check.valid` is `false` → **HALT. Use the template.**
- If `dataset_sql_execution_check.all_datasets_executed` is `false` → **HALT. Execute SQL first.**

---

# Final Instruction (HIGHEST PRIORITY)

If you are about to deploy a dashboard and you have NOT:
1. Printed the pre_deploy_check to stdout
2. Confirmed all checks are `true`
3. Used a template helper function (not hand-constructed JSON)
4. Used the EXACT resolved `dashboard_display_names[].display_name` from `step_handoff.yaml`
5. Used 3-part backtick quoting in ALL dataset SQL
6. Used MEASURE() for ALL measure references in dataset SQL (NEVER direct column access)
7. Used the template notebook pattern (NOT the disabled create_dashboard tool)
8. Used Statement Execution API or template helpers for ALL SQL (NEVER `spark.sql()`)

Then **STOP. Go back. Do it correctly.**
