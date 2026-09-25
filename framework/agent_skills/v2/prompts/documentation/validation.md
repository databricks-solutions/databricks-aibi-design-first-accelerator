# Documentation — Validation Contract

> **Always loaded.** This file owns executable gates and evidence requirements for `generate_documentation`. Operational history is intentionally excluded.

## Gates

### Ground-Truth Validation Prerequisite
`ground_truth_validation.yaml` MUST be produced by the mandatory authenticated terminal
cross-validation stage in `{AGENT_SKILLS_DIR}/prompts/cross_validation/instructions.md`, NOT by the documentation step. Documentation may still run when it
is missing or unsuccessful only to produce a failure report; that condition can never yield overall
`PASS` or a `completed` root lifecycle status.

**If `ground_truth_validation.yaml` exists:** Use it as cross-validation evidence only when all of the following hold: `source: cross_validation_sweep` exactly; `overall_status: PASS` exactly; `run_id` exactly equals the frozen current `run_context.run_id`; `output_folder` exactly equals the frozen current `run_context.output_folder`; `scope_input_binding: PASS` exactly; `scope_inputs_sha256` is a non-empty lowercase 64-hex SHA-256 that exactly matches the frozen scope digest produced by the authenticated terminal sweep; `expected_inventory` and `observed_inventory` have the exact same key set and exact per-key duplicate-free contents, with no missing or extra key or item; the strategy-aware Metric View producer checkpoint authentication below passes; and, when Genie is enabled, the sweep's Genie quality tuple/effective-policy hash and per-asset outcome/action/stage status exactly match the authenticated same-run evidence. Use it only for fields/checks it actually verified. A fallback MUST use `source: documentation_fallback` and `overall_status: SWEEP_UNAVAILABLE` exactly (not a top-level `status` field); it is never ground truth and maps only to nested `validation.cross_validation.status: SWEEP_UNAVAILABLE` with both bindings `UNKNOWN`. The report does not overwrite configuration, KPI specifications, or design artifacts as the authority for intent.

**If `ground_truth_validation.yaml` is missing, unsuccessful, or sweep-unavailable:** The documentation step does NOT re-run the sweep and MUST set the overall validation outcome to `FAIL`. Use same-run per-step `catalog_readback`, `api_readback`, or `executed_sql_validation` evidence where available for individual claims. Manifests may document recorded attempts and identifiers, but manifest-only deployed-state claims MUST be labeled `RECORDED_UNVERIFIED`. Note the gap in the README. DO NOT execute Python code to load `gate_checks.py` or run `run_cross_validation()` — that is the sole responsibility of `{AGENT_SKILLS_DIR}/prompts/cross_validation/instructions.md`.

**DO NOT halt the documentation step because `ground_truth_validation.yaml` is missing.** Produce documentation from available artifacts, clearly state the limitation, and do not convert unverified manifest evidence into `DEPLOYED`, `PUBLISHED`, `IMPLEMENTED_AND_VALIDATED`, or `PASS`.

`scope_inputs_sha256` binds the immutable scope object frozen by the terminal sweep, including the
current run identity, exact expected inventory, exact locator paths, the quality-gate snapshot,
and the authenticated Genie quality source/effective-policy snapshot supplied to the pinned helper.
Documentation MUST NOT invent, normalize, or
repair this digest. If the field is absent, malformed, disagrees with the sweep's persisted
scope evidence, or `scope_input_binding` is not exactly `PASS`, classify the sweep evidence
as unavailable/drifted and route it to `CROSS_VALIDATION_SWEEP`.

### Strategy-aware Metric View producer authentication

Before documentation consumes Metric View identities, Metric View success, or a sweep
report containing Metric View evidence, authenticate the producer contract in G-3:

- bootstrap from the exact resolver-supplied `run_context_path` under G-12 and read the
  canonical handoff as raw bytes;
- for both strategies, require top-level `run_id`, `asset_suffix`, and
  `metric_view_strategy` in both `metric_view_plan.yaml` and
  `metric_view_validation.yaml`, with exact equality between those artifacts,
  current-run `run_context.yaml`, and `step_handoff.yaml`; a PASS status does not excuse a
  missing or mismatched replay binding;
- for `auto`, require the exact `auto_handoff_producer_checkpoint` key set and values:
  `producer_step`, `producer_phase`, `status`, `run_id`, `asset_suffix`,
  `metric_view_strategy`, `step_handoff_path`, `step_handoff_sha256`,
  `metric_view_plan_payload_sha256`, `metric_view_entries`,
  `capability_contract_version`, and `capability_contract_sha256`;
- require `producer_step: create_metric_views`, `producer_phase: plan_metric_views`,
  `status: PASS`, `metric_view_strategy: auto`, and exact run/suffix/canonical-path parity;
- recompute the raw post-producer handoff SHA-256 and the plan payload SHA-256 using the
  exact G-3 UTF-8 canonical-JSON recipe after omitting the entire top-level checkpoint;
- compare the complete `(name, normalized_sql_fqn, primary)` tuple collection with both
  the plan and handoff, reject duplicates, and require exactly one primary;
- require exact capability-contract version/raw-byte-digest parity across the checkpoint,
  plan, validation, and frozen approved contract; and
- separately require one and only one durable same-run `plan_metric_views` entry in
  `run_context.phases_completed`, with `checkpoint_status: VALID`, non-empty `completed_at`, and a
  passing fingerprint Resume Skip Gate.

For `explicit`, require the top-level
`auto_handoff_producer_checkpoint: null`, exact Step-0 handoff/plan/validation identity
parity, exact top-level `run_id`/`asset_suffix`/`metric_view_strategy` replay binding, and
no producer mutation. Missing or `{}` is not equivalent to null. A producer authentication
failure prevents a verified Metric View or downstream-success claim and is routed to
`METRIC_VIEW_STAGE`; documentation never recreates the checkpoint or edits the handoff.
The orchestrator marks `plan_metric_views` and its graph dependents `STALE` under
`{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`; documentation records the failure and never performs that regeneration.

### Genie quality policy authentication

Before reporting Genie thresholds or benchmark semantics, authenticate the exact raw source at
`run_context.inputs.genie_quality_contract`, its approved name/version/policy tuple, the complete
Step-0 effective threshold/outcome snapshot, and the canonical effective-policy SHA-256. Require
exact tuple/hash parity across same-run design, benchmark, validation, and manifest evidence at each
artifact's defined creation point. Documentation never supplies a default or reinterprets an
outcome. Missing or conflicting evidence is `DOCUMENTATION_CONSISTENCY_ERROR` and must be preserved
as drift.

### Documentation checkpoint freshness

`gather_artifacts` is stateless and always re-reads current evidence. Skip
`generate_documentation` or `validate_documentation` only when its current exact phase record is
`VALID`, every producer/frozen-run/input/output fingerprint recomputes, and all documentation
scope/schema checks pass. A changed ground-truth report, stage validation, prompt/guardrail bundle,
or upstream checkpoint invalidates the documentation phase and its dependent. Existence of a README
or draft manifest is never sufficient.

### Field-Scoped Authority and Reconciliation

Authority depends on the claim:

- specifications, configuration, ERD, and design artifacts own intended business meaning and requested design;
- deployment manifests own only the deployment attempt, returned identifiers, and recorded handoff state;
- API/catalog readback, executed validation queries, and cross-validation own the observed fields they verified;
- `{OUTPUT_FOLDER}/metric_views/resolved_metric_view_capabilities.yaml` owns the run's Metric View capability and fallback decisions, including `PLATFORM` versus `ACCELERATOR` scope.
- the approved `genie_quality` source contract owns release defaults/outcome semantics, while the
  authenticated Step-0-frozen snapshot owns the active run's executable values.

Every deployed-state claim MUST be classified as `VERIFIED`, `DECLARED_INTENT`, `RECORDED_UNVERIFIED`, `DRIFT`, `NOT_APPLICABLE`, or `UNKNOWN` and cite its source artifact.

For Dashboards, report mandatory structural validation separately from non-blocking quality
targets. An exact mapped-page inventory overrides the preferred page-count target. A structurally
valid dashboard with `quality_target_status: WARN` remains deployed/verified, but its Dashboard
stage and `validation.dashboards` value are `PARTIAL_SUCCESS`; never relabel the warning as either a
structural failure or PASS.

The documentation draft root uses lifecycle statuses, not validation statuses. Map the overall
documentation outcome exactly as `PASS -> completed`,
`PARTIAL_SUCCESS -> partial_success`, and `FAIL -> failed`. Never write `PASS`,
`PARTIAL_SUCCESS`, or `FAIL` directly into `documentation/run_manifest_draft.json.status`; those
values remain confined to the shared schema's per-step and validation fields.

When intent and observed state differ, preserve both values, cite both sources, mark `DRIFT`, and use the observed value only for current deployment claims. Never rewrite intent or silently choose one artifact to hide a conflict.

**Documentation output path:** All documentation files (README.md, architecture diagrams, etc.) MUST be written to `{OUTPUT_FOLDER}/documentation/` (i.e. `generated_outputs/{version}/documentation/`). NEVER write documentation to the project root, the user's home directory, or any location outside `generated_outputs/{version}/`.

**Directory creation:** The `documentation/` subdirectory should be created by Step 0, but if it does not exist at documentation time, create it and proceed. In Genie Code context, `os.makedirs(f"{OUTPUT_FOLDER}/documentation", exist_ok=True)` is acceptable. In App context, use the Workspace API `mkdirs` tool. Do NOT halt the documentation step because the directory is missing.

---

## Required README Sections (ALL 11 MANDATORY)

The README MUST have ALL of these sections from `{AGENT_SKILLS_DIR}/prompts/documentation/instructions.md`:

1. **Solution Overview** — domain, version, status, generation date
2. **Architecture / Asset Flow** — text diagram: ERD → Tables → MVs → Dashboards → Genie
3. **Source Schema Summary** — table listing with roles, grains, relationships
4. **Data Layer** — table/row counts, validation status
5. **Metric Views** — MV listing with source, measures, dimensions, status
6. **KPI Catalog** — EVERY KPI from spec with status and notes
7. **Not Implemented KPIs** — reference SQL for each, reason, manual implementation guide
8. **Dashboards** — ID, exact page contract, page/widget/filter counts, structural status,
   quality-target PASS/WARN details, and Dashboard stage status
9. **Genie Space** — ID, instruction length, question counts, authenticated quality policy, benchmark outcome/action, and stage status
10. **Validation Summary** — per-layer pass/fail table
11. **Generated Artifacts** — complete inventory of all output files

---

## Failure-Only Runbook Routing Index

| Runbook section | Load only when observed evidence matches |
|---|---|
| `AP-DOC-1` | Flat README Instead of Structured Documentation |
| `AP-DOC-2` | dbldatagen Import in Documentation Stage |
| `AP-DOC-3` | Missing Ground-Truth Reference |
| `AP-DOC-4` | shutil.copy2 FileNotFoundError from Placeholder Path |
| `AP-DOC-5` | Documentation Written Outside generated_outputs |
| `AP-DOC-6` | Manifest Treated as Deployed Truth |
| `AP-DOC-7` | Intent Overwritten by Readback |
| `AP-DOC-8` | Hardcoded Metric View Support Claim |
| `AP-DOC-9` | Unbound Sweep Report Treated as Ground Truth |
| `AP-DOC-10` | Auto Handoff Trusted Without Producer Authentication |
| `AP-DOC-11` | Genie Quality Policy Reinterpreted |

Classify the failure from current evidence before loading a runbook section. The index is a routing aid, not authority to bypass the stage owner or retry policy.
