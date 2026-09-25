# Dashboards — Validation Contract

> **Always loaded.** This file owns executable gates and evidence requirements for `create_dashboards`. Operational history is intentionally excluded.

## Enforcement Architecture

Dashboard deployment uses the **template notebook pattern** (`v2_dashboard_notebook.py.template`).
The LLM's job is to produce `dashboard_design.yaml` (a structured spec). The template notebook
compiles the spec into deployed dashboards with all guardrails in the code path.

**The stage and template enforce these rules:**
- The pre-design authority gate runs live DESCRIBE and SHOW CREATE for every exact handoff FQN
- Always uses `build_filter_widget()` → queryName always present
- The template rechecks live DESCRIBE before building datasets → deployed column names are used
- Always uses `build_bar_chart()`, `build_counter()`, etc. → no hand-rolled builders
- Always uses `build_text_widget()` for every title/header/narrative widget → no second text serializer
- Always calls `deploy_dashboard()` → pre-deploy gates + API readback

---

## Authority Boundaries

| Concern | Authority |
|---|---|
| KPI meaning and KPI-to-page intent | KPI specification |
| Resolved Metric View FQNs, dashboard names, warehouse, and paths | `step_handoff.yaml` |
| Intended KPI allocation and exclusions | `metric_view_plan.yaml` |
| Validated KPI eligibility and Metric View assignment | `metric_view_validation.yaml` |
| Expected Metric View design | `metric_view_design.yaml` |
| Actually deployed Metric View fields and types | live `DESCRIBE TABLE` |
| Actually deployed Metric View definition | live `SHOW CREATE TABLE` |
| Intended dashboard structure | validated `dashboard_design.yaml` |
| Serialized representation of every text widget | digest-attested `build_text_widget()` return value, treated as opaque |
| Actually deployed dashboard state | Lakeview API GET/readback |
| Locator and deployment-attempt evidence | dashboard manifest |

Planning and design files describe desired state; they never override live deployed state. API readback describes actual deployed state; it does not silently redefine the intended design. Any material expected-versus-actual difference is a validation failure and must be returned to the owning stage.

`step_handoff.yaml` is validation-only input in this stage. If it is missing, malformed, or inconsistent with `metric_view_plan.yaml` or `metric_view_validation.yaml`, HALT with `DASHBOARD_INPUT_AUTHORITY_ERROR`. Do not normalize, reconstruct, or overwrite it from `run_context.yaml`, `accelerator.yaml`, directory names, or model memory.

---

## Shared deployment boundary

Before importing any deployment notebook, apply `prepare_template_bindings` from the
frozen shared `agent_transport.md` to the exact template and complete logical values.
First apply this stage's authority/binding gates. Pass the resulting substitution strings
unchanged to the host deployment operation, and inspect its acknowledgement before
execution. Examples using lists/dicts require this conversion; do not send raw containers
or JSON booleans into Python slots. No code-cell rewriting is allowed.

## Gates

### GATE 0: Input Authority Parity (MANDATORY)
Bootstrap from the exact resolver-supplied `run_context_path` under G-12 before reading any
sibling artifact. Verify that every shared resolved field in `step_handoff.yaml` exactly
matches current-run `run_context.yaml`, that the canonical Metric View FQN sets in
`step_handoff.yaml`, `metric_view_plan.yaml`, and `metric_view_validation.yaml` are
identical, and that every `run_context.yaml assets.dashboards[].id` in the frozen inventory
has exactly one resolved handoff display name with no extra handoff IDs. Any mismatch →
HALT.

FQN-set equality alone is insufficient. Before consuming a Metric View identity, apply the
complete strategy-aware G-3 producer authentication:

- For both strategies, require top-level `run_id`, `asset_suffix`, and
  `metric_view_strategy` in both `metric_view_plan.yaml` and
  `metric_view_validation.yaml`. Require exact equality between those artifacts,
  current-run `run_context.yaml`, and `step_handoff.yaml` before accepting either artifact,
  even if validation says PASS.
- For `auto`, require the exact checkpoint key set
  `{producer_step, producer_phase, status, run_id, asset_suffix, metric_view_strategy,
  step_handoff_path, step_handoff_sha256, metric_view_plan_payload_sha256,
  metric_view_entries, capability_contract_version, capability_contract_sha256}`.
- Require `producer_step: create_metric_views`, `producer_phase: plan_metric_views`,
  `status: PASS`, exact run/suffix/strategy/path parity, the exact raw post-producer handoff
  hash, and the exact G-3 UTF-8 canonical-JSON plan-payload hash.
- Compare the complete `(name, normalized_sql_fqn, primary)` tuple collection with both
  plan and handoff; reject duplicates and require exactly one primary.
- Require exact capability version/raw-byte SHA parity and one and only one separate durable
  same-run `plan_metric_views` record in `run_context.phases_completed`, with
  `checkpoint_status: VALID`, non-empty `completed_at`, and a passing fingerprint Resume Skip Gate.
- For `explicit`, require the top-level
  `auto_handoff_producer_checkpoint: null`, exact Step-0 handoff/plan/validation tuple
  parity, exact top-level run/suffix/strategy replay binding, and no producer mutation.
  Missing or `{}` is invalid.

Any checkpoint failure is `DASHBOARD_INPUT_AUTHORITY_ERROR` owned by
`METRIC_VIEW_STAGE`; do not repair the handoff or checkpoint, change runs, or substitute a
manifest.

### GATE 2.1: Deployed Metric View Readback (MANDATORY)
For every exact FQN in `step_handoff.yaml`, run live `DESCRIBE TABLE` and `SHOW CREATE TABLE`. Build field references from that readback, not from design artifacts. If validated intent cannot be resolved against the deployed object → HALT with `METRIC_VIEW_DEPLOYED_STATE_MISMATCH`.

A deployed datatype conflict is upstream drift, not a Dashboard repair opportunity. Preserve the
expected and observed types and return it to the Metric View owner. Do not add `CAST`, `TRY_CAST`,
string conversion, or a different visualization merely to make the mismatch pass.

### GATE 3.1: Page Contract Validation (MANDATORY)
After writing `dashboard_design.yaml`, compare its exact ordered canvas-page ID inventory with the
KPI-spec Dashboard Mapping. When a mapping exists, any omission, addition, rename, reorder, merge,
or filler page → HALT. The mapped count overrides the preferred page-count target. When no mapping
exists, require a non-empty canvas inventory and evaluate the preferred count only as a quality
target.

### GATE 3.2: Design Contract Validation
`dashboard_design.yaml` must be written and validated BEFORE any dashboard construction. No dashboard JSON may be built without this contract.

### HARD GATE: lakeview_dashboard_api.md Must Be Loaded
The agent must read the Lakeview API reference before building dashboards. This is non-negotiable.

### HARD GATE: Digest-Pinned Helpers and Canonical Validator

Load `gate_checks.py` and `lakeview_dashboard_helpers.py.template` only through the G-12
digest-qualified loader using each artifact's exact frozen source path and SHA-256. Verify
source and copied bytes, unique digest-qualified module identity, loaded `__file__`, and
the approved callable signatures before construction or validation. Never import a fixed
module name from ambient/shared `sys.path` or reuse a cached module.

The only accepted post-deployment validation entry point is the attested
`validate_dashboard_from_api` from the pinned `gate_checks.py`. Invoke its approved
release signature with the checked Workspace client bound to the exact frozen
`step_handoff.workspace_host`, exact `dashboard_id`, exact handoff display name, and frozen
quality policy. The return value MUST be a mapping with terminal structural PASS status, page
contract PASS, the same dashboard ID/display name and workspace-host binding, and
readback-derived page, widget, filter, dataset, and publication evidence satisfying the design.
It MUST separately return complete quality-target results with `PASS|WARN` and map them exactly to
Dashboard `stage_status: PASS|PARTIAL_SUCCESS`. Persist that result with `source: api_readback`.

Missing or incompatible pinned helpers, wrong host/client binding, a non-mapping result,
identity/count drift, or non-PASS structural status is `DASHBOARD_HELPER_CONTRACT_ERROR` or the
specific Dashboard API/deployment failure. Manual GET interpretation, locally recreated
validator logic, and agent-authored fallback validation are prohibited.

### Dashboard Gate Classification (MANDATORY)

Consume `run_context.quality_gates.dashboard_policy` exactly as frozen:

- Structural gates cover the exact page contract, non-empty canvas pages, required global-filter
  page, functional filter bindings, dataset SQL, widget references, readback parity, and published
  state. A structural failure blocks deployment or the canonical manifest and is `FAIL`.
- Quality targets cover the preferred fallback page count, widget density, visualization diversity,
  filter count, and primary-KPI context count. Evaluate every named target. A miss is `WARN`, maps
  the Dashboard stage to `PARTIAL_SUCCESS`, and does not block deployment or the manifest.

The compatibility names `min_*` and `max_*` do not make a field structurally mandatory; the
frozen classification owns behavior. Never use a quality target to add, drop, merge, or split
mapped pages.

### Text Widget Serialization Authority (MANDATORY)

The design may contain semantic `visualization: text` plus `content` and position only. Every such
entry MUST be serialized by the exact digest-attested `build_text_widget(name, markdown, position)`
callable. Treat its return value as opaque. Inline wire-format dictionaries, alternate serializers,
copied examples, wrappers that reshape the result, and post-helper patches are prohibited. Missing
or incompatible helper behavior is `DASHBOARD_HELPER_CONTRACT_ERROR`; do not fall back.

### HARD GATE: No Dashboard Construction Without Design Contract
If `dashboard_design.yaml` does not exist → HALT. Do NOT construct dashboards from memory.

### GATE 19.1: API Readback Validation Required
After each dashboard is deployed, retrieve it through the Lakeview API and compare the GET response with `dashboard_design.yaml`. The GET response is authoritative for actual deployed dashboard state; the design remains the expected state. Write per-dashboard validation evidence with `source: api_readback`. The run-level `ground_truth_validation.yaml` is written later by the master cross-asset validation sweep.

---

## Dashboard Design Spec Schema

The LLM produces `dashboard_design.yaml` with this structure:

```yaml
dashboards:
  - id: kpis
    name: my_dashboard_v1              # exact handoff display_name
    purpose: Executive KPI analysis
    metric_views:                       # always a list, even for one MV
      - "`catalog`.`schema`.`claims_mv_v1`"       # exact handoff sql_fqn
      - "`catalog`.`schema`.`enrollment_mv_v1`"   # exact handoff sql_fqn
    page_contract:
      resolution_source: KPI_SPEC_DASHBOARD_MAPPING
      expected_page_ids: [overview]
      actual_page_ids: [overview]
      structural_status: PASS
    primary_kpi_contexts: {KPI_001: [total_claims]} # exact compiled widget IDs
    filter_dimensions: [claim_type, service_date] # compiler input, same filters below
    filters:
      - dimension: claim_type
        filter_type: multi-select
        scope: global
        rationale: High-value segmentation
      - dimension: service_date
        filter_type: date-range-picker
        scope: global
        rationale: Time-window analysis
    pages:
      - id: overview
        title: Overview
        purpose: Executive summary
        page_type: CANVAS
        widgets:
          - id: total_claims
            type: counter
            visualization: counter # counter, bar, line, or text
            measure: total_claims  # column name from DESCRIBE output
            title: Total Claims
            display_name: Claims   # optional: counter label
            agg: SUM               # optional: SUM (default) or AVG
          - id: paid_by_type
            type: bar
            dimension: claim_type
            visualization: bar
            measure: total_paid_amount
            dimensions: [claim_type]
            title: Paid Amount by Type
          - id: paid_trend
            type: line
            dimension: service_date
            visualization: line
            measure: total_paid_amount
            dimensions: [service_date]
            title: Paid Amount Trend
          - id: section_header
            type: text
            visualization: text
            content: "## Section Header"
    quality_target_evaluation:
      status: PASS | WARN
      checks:
        - field: min_canvas_pages_per_dashboard
          expected: <frozen target>
          actual: <observed count>
          status: PASS | WARN
```

---

## Failure-Only Runbook Routing Index

| Runbook section | Load only when observed evidence matches |
|---|---|
| `AP-DB-1` | Missing queryName in Filter Widgets |
| `AP-DB-2` | bar() TypeError from Hand-Rolled Builders |
| `AP-DB-3` | Column Name Mismatch in Dataset SQL |
| `AP-DB-4` | f-string Backslash SyntaxError |
| `AP-DB-5` | Agent Bypasses Template Helpers |
| `AP-DB-6` | METRIC_VIEW_MISSING_MEASURE_FUNCTION |
| `AP-DB-7` | create_dashboard Tool Is Disabled |
| `AP-DB-8` | NameError spark is not defined |
| `AP-DB-9` | PermissionDenied on Dashboard Creation |
| `AP-DB-10` | Planned Metric View State Overrides Deployment |
| `AP-DB-11` | Manifest Treated as Dashboard Ground Truth |
| `AP-DB-12` | Second Text-Widget Serializer |
| `AP-DB-13` | Quality Target Used as a Structural Gate |

Classify the failure from current evidence before loading a runbook section. The index is a routing aid, not authority to bypass the stage owner or retry policy.


### GATE TEMPLATE-INPUT: Release and design admission (DB-G1)

Before notebook import/run, authenticate the release-selected dashboard template's
path and SHA-256 against the run context, then verify exact workspace design-file
readback at `<output_folder>/dashboards/dashboard_design.yaml`. Missing design is
DASHBOARD_DESIGN_NOT_FOUND; mismatched template is TEMPLATE_AUTHORITY_ERROR. Both
block dashboard deployment. Never execute a legacy notebook as a fallback.
