# Genie — Validation Contract

> **Always loaded.** This file owns executable gates and evidence requirements for `create_genie_space`. Operational history is intentionally excluded.

## Enforcement Architecture

Genie space deployment uses the **template notebook pattern** (`v2_genie_space_notebook.py.template`).
The LLM populates configuration cells (title, instructions, questions, SQL, benchmarks).
The template cells (8-10) handle API calls, validation, and post-deploy readback.

---

## Authority Boundaries

Authority is field-scoped:

| Information | Authority |
|-------------|-----------|
| KPI definition, business intent, and terminology | KPI specification |
| Exact Metric View FQNs, Genie title, warehouse, and resolved asset identity | `step_handoff.yaml` |
| KPI terminal status and KPI-to-Metric-View assignment | `metric_view_validation.yaml` |
| Deployed Metric View aliases, types, measures, dimensions, and expressions | Live `DESCRIBE TABLE` and `SHOW CREATE TABLE` |
| Intended Genie configuration | Validated generated configuration |
| Persisted Genie identity and content | `GET /api/2.0/genie/spaces/{id}?include_serialized_space=true` |
| Release-default thresholds and PASS/WARN/FAIL semantics | Approved `genie_quality` source contract |
| Executable thresholds/outcomes for the active run | Authenticated Step-0-frozen `run_context.validation` snapshot |

Plans, designs, inventories, request payloads, POST/PATCH responses, and manifests are intent or evidence. A manifest may locate an asset and record a prior attempt, but it never overrides current API readback.

---

## Shared deployment boundary

Before importing any deployment notebook, apply `prepare_template_bindings` from the
frozen shared `agent_transport.md` to the exact template and complete logical values.
First apply this stage's authority/binding gates. Pass the resulting substitution strings
unchanged to the host deployment operation, and inspect its acknowledgement before
execution. Examples using lists/dicts require this conversion; do not send raw containers
or JSON booleans into Python slots. No code-cell rewriting is allowed.

## Gates

### PRE-DEPLOY: Authority Resolution
Before designing or deploying Genie:
- Bootstrap from the exact resolver-supplied `run_context_path` under G-12 before reading any sibling artifact
- Validate `step_handoff.yaml`; do not modify or reconstruct it
- Verify every shared resolved field in `step_handoff.yaml` exactly matches current-run `run_context.yaml`
- Verify the normalized FQN sets in `step_handoff.yaml`, `metric_view_plan.yaml`, and `metric_view_validation.yaml` are identical
- Inspect every handoff FQN with both `DESCRIBE TABLE` and `SHOW CREATE TABLE`
- Verify the live aliases and semantics match the validated Metric View design
- Use only `IMPLEMENTED_AND_VALIDATED` KPI assignments

HALT on any missing handoff, FQN mismatch, missing deployed Metric View, or deployed-definition drift. Return the issue to the owning upstream stage; do not repair it inside Genie.

Matching FQN sets alone do not authenticate an auto-produced handoff. Before consuming
any Metric View identity, apply the complete strategy-aware G-3 producer contract:

- For both strategies, require top-level `run_id`, `asset_suffix`, and
  `metric_view_strategy` in both `metric_view_plan.yaml` and
  `metric_view_validation.yaml`; require exact equality between those artifacts,
  current-run `run_context.yaml`, and `step_handoff.yaml`, regardless of a PASS status.
- For `auto`, require exactly the checkpoint keys
  `{producer_step, producer_phase, status, run_id, asset_suffix, metric_view_strategy,
  step_handoff_path, step_handoff_sha256, metric_view_plan_payload_sha256,
  metric_view_entries, capability_contract_version, capability_contract_sha256}`.
- Require `producer_step: create_metric_views`, `producer_phase: plan_metric_views`,
  `status: PASS`, exact run/suffix/strategy/canonical-path parity, SHA-256 of the exact raw
  post-producer handoff, and the G-3 plan-payload digest computed with the exact UTF-8
  canonical-JSON recipe.
- Compare the complete `(name, normalized_sql_fqn, primary)` tuple collection with both
  plan and handoff, reject duplicate names/FQNs, and require exactly one primary.
- Require exact capability-contract version/raw-byte-hash parity and one and only one separate
  durable same-run `plan_metric_views` entry in `run_context.phases_completed`, with
  `checkpoint_status: VALID`, non-empty `completed_at`, and a passing fingerprint Resume Skip Gate.
- For `explicit`, require top-level `auto_handoff_producer_checkpoint: null`, exact Step-0
  handoff/plan/validation tuple parity, exact top-level run/suffix/strategy replay binding,
  and no producer mutation. Missing or `{}` is invalid.

Any checkpoint failure is `GENIE_HANDOFF_AUTHORITY_ERROR` owned by `METRIC_VIEW_STAGE`.
Genie MUST NOT rewrite the checkpoint/handoff, choose another run, or substitute a
manifest.

Datatype drift is included in deployed-definition drift. Preserve both type strings and return the
defect to the Metric View owner; never add casts, change the semantic inventory, or weaken example
SQL/benchmarks to hide it.

### PRE-DESIGN: Genie Quality Contract Authentication

Before consuming any quality value, read the exact raw bytes at
`run_context.inputs.genie_quality_contract` with duplicate-key rejection. Require the approved
`genie_quality` name/version/raw SHA-256 and `GENIE_QUALITY_V1` policy ID to match the frozen
`run_context.validation` tuple. Validate the exact threshold key set, type/bounds, and invariants;
require the frozen `benchmark_outcomes` mapping to equal the approved source mapping; and recompute
the canonical effective-policy SHA-256 over exactly `{policy_id, thresholds, benchmark_outcomes}`.

Missing/mismatched evidence is `GENIE_QUALITY_CONTRACT_ERROR`. No stage prompt, guardrail, helper,
template, request file, or resume path may supply a number, comparator, action, manifest permission,
or status mapping when the authenticated snapshot is absent.

### GATE 2.2: LLM Design Validation
Before proceeding to Genie creation, validate:
- Instructions >= frozen `run_context.validation.min_instruction_chars`
- Sample questions >= frozen `run_context.validation.min_sample_questions`
- Analytical patterns >= frozen `run_context.validation.min_analytical_patterns`
- Every implemented KPI and dimension meets its frozen reference minimum
- Example SQL queries >= frozen `run_context.validation.min_example_sqls` (each syntactically valid)
- Benchmarks >= frozen `run_context.validation.min_benchmark_questions` (different phrasing from examples)
- Canonical helper `metric_view_fqns` exactly equals the sorted, normalized, complete handoff
  Metric View FQN collection; missing, duplicate, or extra attached sources are invalid
- Design envelope carries the exact quality-contract tuple, complete effective thresholds, exact
  benchmark outcome mapping, and effective-policy hash

HALT if a required frozen key is missing or any threshold is not met; never choose a local fallback.

### POST-DEPLOY: Blank Space Detection
After creation, call `GET /api/2.0/genie/spaces/{id}?include_serialized_space=true`, normalize the response shape, and verify:
- `sample_questions` count matches what was sent
- Instructions text is non-empty
- The attached Metric View FQN set exactly matches the validated handoff set

### POST-DEPLOY: API Readback
`validate_genie_from_api()` must return PASS using the full GET readback. Write a manifest only with `validation_source: api_readback`. Treat that manifest as deployment evidence and a locator, not as current deployed truth.

The matching `{genie_title}_validation.yaml` MUST persist `metric_views.expected` and
`metric_views.actual` as the same sorted canonical normalized complete handoff set, plus
`metric_views.status: PASS`. Its exact `readback_counts` keys are `instructions_chars`,
`sample_question_count`, `example_sql_count`, and `benchmark_count`; every value is a
full-GET-derived integer meeting the corresponding frozen `run_context.validation` minimum. The
terminal sweep compares these fields and the frozen minima exactly; request data or manifest counts
cannot fill a missing validation field.

The validation artifact, benchmark results, and manifest also carry the exact five-field quality
identity/effective-policy tuple. Resolve benchmark outcome by interpreting the approved predicate
enums and frozen threshold references in `run_context.validation.benchmark_outcomes`; persist the
selected action, validation status, manifest permission, and stage status without local
reinterpretation. Only a selected rule with `manifest_allowed: true` may produce a successful
canonical manifest. An accepted non-PASS result retains its exact contract-defined stage status.

### HARD GATE: Pinned Genie Helper Attestation

Load `gate_checks.py` and every Genie deployment/validation helper only through the G-12
digest-qualified loader using exact frozen source paths and expected SHA-256 digests.
Verify source and copied bytes, unique digest-qualified module identity, loaded
`__file__`, and the approved callable signatures—including `run_genie_predeploy_gates`
and `validate_genie_from_api`—before any API call. A compatibility alias may exist only
after the exact module instance is attested.

Invoke the attested canonical `validate_genie_from_api` using its approved release
signature, the checked Workspace client bound to exact frozen
`step_handoff.workspace_host`, exact `space_id`, exact handoff `genie_title`, exact
attached Metric View tuple set, and the complete authenticated frozen quality snapshot. It MUST
return a mapping with
terminal PASS status, the same space ID/title and host binding, the exact attached Metric
View set, and full-GET-derived instruction/sample-question/example-SQL/benchmark counts
that satisfy the sent design and frozen minima.

Missing/unreadable helpers, absent expected digests, digest or loaded-path mismatch,
stale cached modules, incompatible signatures, wrong client/host binding, non-mapping
results, identity/count drift, or non-PASS status fail closed with
`GENIE_HELPER_CONTRACT_ERROR` or the specific Genie API error. Fixed-name ambient imports,
an unverified helper copied beside the notebook, and manual/fallback validation are
prohibited.

---

## Failure-Only Runbook Routing Index

| Runbook section | Load only when observed evidence matches |
|---|---|
| `AP-GN-1` | Blank Genie Space |
| `AP-GN-2` | Raw Aggregation in Example SQL |
| `AP-GN-3` | Agent Bypasses Template |
| `AP-GN-4` | Wrong data_sources Key in serialized_space |
| `AP-GN-5` | Threshold or Outcome Drift |

Classify the failure from current evidence before loading a runbook section. The index is a routing aid, not authority to bypass the stage owner or retry policy.
