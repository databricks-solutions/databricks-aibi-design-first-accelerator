# Generate Documentation

> **Transport:** apply the frozen `shared/agent_transport.md` contract. Tool names are portable operations; App/Lakebase integration is optional. Runtime paths come only from `contracts/release.yaml`.

> **Always load for this stage:** `{AGENT_SKILLS_DIR}/prompts/shared/global_guardrails.md`, `{AGENT_SKILLS_DIR}/prompts/documentation/validation.md`, `{AGENT_SKILLS_DIR}/prompts/documentation/guardrails.md`, `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`.
> **Failure-only:** authenticate `run_context.inputs.stage_runbooks.generate_documentation` and load only the matching section of `{AGENT_SKILLS_DIR}/prompts/documentation/runbook.md` after a classified failure. Never load the runbook on the normal success path.


## Failure-Only Runbook Loading

Do not read `{AGENT_SKILLS_DIR}/prompts/documentation/runbook.md` during normal execution. After this stage classifies a failure, authenticate the frozen runbook tuple, use the routing index in `{AGENT_SKILLS_DIR}/prompts/documentation/validation.md`, and load only the matching diagnostic section. The runbook cannot weaken a gate, change the failure owner, or authorize a blind retry.

## Role

Produce a factual, auditable run summary after all accelerator pipeline stages complete.

The documentation must describe:

- what inputs were used;
- what semantic/data assets were created;
- which KPIs were successfully implemented;
- which KPIs were skipped and why;
- which dashboards and Genie assets were deployed;
- which validation checks passed or failed;
- how the generated assets relate to one another;
- how a user can consume the resulting solution.

The documentation MUST reconcile declared intent with validated deployed reality.

- Configuration, KPI specifications, ERD artifacts, and design artifacts describe intent.
- Deployment manifests describe deployment attempts, returned identifiers, and recorded handoff state.
- API readback, catalog inspection, executed validation queries, and the terminal cross-validation sweep describe observed deployed reality.
- A manifest or design artifact alone MUST NOT be presented as proof that an asset currently exists, is published, or passed validation.
- When intended and observed values differ, preserve both values and report the drift; do not overwrite either source.

Do not reconstruct results from memory or assumptions.

## Canonical Run Bootstrap (Mandatory)

The orchestrator MUST supply the exact `run_context_path` for this invocation. Read and parse the
raw bytes at that exact path before any documentation artifact. Do not search for a run context,
choose a run directory by recency, derive a path from the current working directory, or use a
request-time filename. Require a non-empty `run_context.run_id` and non-empty absolute
`run_context.output_folder`; reject relative output paths before comparison. Then require the
normalized basename to be `run_context.yaml` and the normalized parent to equal parsed
`run_context.output_folder`. The only handoff path is then
`{run_context.output_folder}/step_handoff.yaml`.

Missing, malformed, ambiguous, or path-inconsistent bootstrap input is
`HANDOFF_AUTHORITY_ERROR`. HALT without locating or synthesizing a replacement. In the remainder
of this prompt, `{OUTPUT_FOLDER}` means that exact frozen output folder. Permission, transport,
and other genuine I/O failures retain their operational classification.

---

## PROHIBITED ACTIONS (this entire step)

1. **DO NOT fabricate results** — every documented metric, KPI status, and asset reference must come from actual pipeline artifacts
2. **DO NOT skip the documentation manifest draft** — `documentation/run_manifest_draft.json` MUST be produced for master reconciliation; only the master writes canonical `{OUTPUT_FOLDER}/run_manifest.json`
3. **DO NOT document KPIs as "implemented"** unless verified validation evidence confirms them as `IMPLEMENTED_AND_VALIDATED`
4. **DO NOT document dashboards or Genie spaces as "deployed" or "published"** from a manifest alone — require API readback or the terminal cross-validation sweep
5. **DO NOT assume pipeline steps completed** — read actual artifacts to confirm
6. **DO NOT silently resolve artifact conflicts** — preserve intended and observed values, cite both sources, and classify the difference as `DRIFT`
7. **DO NOT document auto-generated Metric View identities** until the exact producer checkpoint, handoff bytes, canonical plan payload, and durable producer phase all authenticate

---

# Core Principle

Documentation must reflect the actual final state of the accelerator run:

```text
Configuration
    ↓
Data / Schema Layer
    ↓
Metric Layer
    ↓
Dashboard Layer
    ↓
Genie Layer
    ↓
Validation Artifacts
    ↓
README
```

If an asset failed or was skipped, document that explicitly.

Do not present planned assets as successfully created assets.

---

## State & Checkpoint Contract

This step uses **artifact-as-state** checkpointing (see `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`).
The same rules apply in App mode and Genie Code — no backend infrastructure required.

**Before executing or considering reuse of a phase**, apply shared state_contract.md
“Phase entry and read scope.” New phases authenticate only frozen inputs and verified
predecessors; their own outputs are checked after production. The complete Resume Skip Gate
and checks below apply only to existing checkpoint candidates. Missing-only checkpoint recovery
follows the shared rules; do not replay a successful producer because bookkeeping is absent.
Stateless load/gather phases are always re-read without reusable phase records.

**Candidate verification flow (after authenticated bootstrap; evaluate only existing candidates in dependency order):**

1. List the output folder.
2. Re-authenticate the exact tool-supplied `run_context_path` and canonical output-folder binding.
3. Authenticate the Metric View producer checkpoint, when applicable, using the current raw
   handoff bytes and canonical plan payload before reusing any documentation checkpoint.
4. Authenticate the exact raw Genie quality contract and canonical effective-policy value before
   reusing documentation that reports any Genie quality field.
5. Manage `run_context.yaml` per `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md` Section 8.
6. Recompute each candidate record's exact producer/frozen-run, mandatory input, and output
   fingerprints, then apply its phase-specific check:
   - `generate_documentation`: `{OUTPUT_FOLDER}/documentation/readme.md` exists and the paired draft
     has the exact current run/lifecycle/path bindings, checkpoint reconciliation, and authenticated
     evidence-scope fields.
   - `validate_documentation`: `{OUTPUT_FOLDER}/documentation/run_manifest_draft.json` matches the
     exact canonical schema, binds the exact current run/lifecycle/path, has current checkpoint
     reconciliation, preserves the authenticated cross-sweep scope fields, and passes the factual
     consistency/placeholder scan.
7. Skip only current `VALID` records that pass every check; otherwise continue from the earliest
   `STALE` or absent reusable phase.
8. On step completion, persist only the documentation phase/step completion evidence. Do **not**
   set the top-level lifecycle `run_context.status`: the master determines
   `completed|partial_success|failed` after reconciling and writing the canonical final manifest,
   then updates every lifecycle store in its defined terminal sequence.

**Note:** Documentation writes are idempotent, but an explicit re-run first marks the documentation
phase records `STALE` with reason `EXPLICIT_DOCUMENTATION_RERUN`, then regenerates and replaces them
with new `VALID` records. It does not bypass checkpoint audit history.

**Artifact-as-State mapping:**

| Exact `phase_id` | Artifact | Additional phase-specific skip check after the fingerprint gate |
|-------|----------|----------|
| gather_artifacts | Artifacts loaded | Never reusable; always re-read (stateless) |
| generate_documentation | `{OUTPUT_FOLDER}/documentation/readme.md` | canonical file and paired draft have exact current run/lifecycle/path, checkpoint, evidence-scope, and Genie quality-policy binding |
| validate_documentation | `documentation/run_manifest_draft.json` | canonical schema, placeholder scan, factual consistency, and current run/lifecycle/path/checkpoint/scope/quality-policy bindings pass |

---

# Step 1: Load Configuration

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "gather_artifacts"
> - `phase_name`: "Gather Artifacts"
> - `status`: "started"
> - `current_task`: "Loading configuration and run artifacts"
> - `happenings`: ["Reading accelerator.yaml", "Loading run artifacts", "Establishing artifact authority"]

Read:

```text
accelerator.yaml
<exact tool-supplied run_context_path>
{OUTPUT_FOLDER}/step_handoff.yaml
{run_context.inputs.kpi_spec.path}
{run_context.inputs.genie_quality_contract.path}
```

Treat `accelerator.yaml` as requested configuration, `run_context.yaml` as the resolved configuration for this run, and `step_handoff.yaml` as the exact resolved identity/path contract. Resolve the KPI specification only from the frozen `run_context.inputs.kpi_spec` value; do not fall back to an example-directory default. Do not rewrite the requested file with resolved values or infer resolved identities from it.

If the canonical handoff is missing/malformed or conflicts with frozen shared run/path fields,
HALT with `HANDOFF_AUTHORITY_ERROR`; permission, transport, and genuine I/O errors remain
operational failures. Do not downgrade an authority failure into a documentation limitation.

### Metric View Producer Authentication

Read top-level `metric_view_plan.yaml.auto_handoff_producer_checkpoint` before using Metric View
identity in the README or draft manifest.

Before branching on strategy, require both `metric_view_plan.yaml` and
`metric_view_validation.yaml` to contain top-level `run_id`, `asset_suffix`, and
`metric_view_strategy`. Require exact equality with current run context/handoff and between the two
artifacts. This replay binding is mandatory even for explicit mode, where the auto checkpoint is
null; a successful-looking validation status cannot replace it.

- For `metric_view_strategy: auto`, require a mapping with exactly these keys:
  `producer_step`, `producer_phase`, `status`, `run_id`, `asset_suffix`,
  `metric_view_strategy`, `step_handoff_path`, `step_handoff_sha256`,
  `metric_view_plan_payload_sha256`, `metric_view_entries`,
  `capability_contract_version`, and `capability_contract_sha256`.
- Require exact constants `create_metric_views`, `plan_metric_views`, `PASS`, and
  `auto`; exact run/suffix/path parity; SHA-256 of the current handoff raw bytes; and capability
  tuple parity with the plan, validation, and exact resolved capability bytes.
- Require every stored SHA-256 to be exactly 64 lowercase hexadecimal characters.
- Remove the entire top-level checkpoint from the parsed plan and recompute the plan hash over
  UTF-8 `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
- Require each checkpoint item to contain exactly `{name, normalized_sql_fqn, primary}`; require
  non-empty duplicate-free names, boolean primary values, duplicate-free normalized FQNs, exact
  deterministic ordered tuple-list equality across checkpoint, handoff, plan, and validation, and
  exactly one primary.
  First require every raw executable `sql_fqn` in the frozen run context, handoff, plan, and
  validation to contain exactly three separately backtick-quoted non-empty segments, with no
  surrounding whitespace or trailing content. Remove the one required outer backtick pair per
  segment, unescape doubled backticks, Unicode-casefold each segment, and join the results unquoted
  with `.`.
- Require one and only one matching durable `run_context.phases_completed` record with
  `step=create_metric_views`, `phase=plan_metric_views`, `checkpoint_status: VALID`, non-empty
  `completed_at`, and a passing fingerprint Resume Skip Gate.
- For `metric_view_strategy: explicit`, require the
  `auto_handoff_producer_checkpoint` key to be present with value `null`; missing, `{}`, or any
  non-null value is invalid. Require exact duplicate-free ordered
  `{name, normalized_sql_fqn, primary}` parity across Step-0-frozen
  `run_context.assets.metric_views[]`, handoff, plan, and validation, with exactly one primary and
  the same capability tuple.

Authentication failure is `DOCUMENTATION_INPUT_ERROR`, owned by the Metric View producer (or the
master resolver for frozen run/path conflicts). Documentation records the failure; it never
updates the checkpoint, handoff, plan, phase history, or capability tuple.

### Genie Quality Policy Authentication

Before documenting any Genie threshold, benchmark outcome, or stage status, read the exact raw
bytes at `run_context.inputs.genie_quality_contract` with duplicate-key rejection. Require the
approved `genie_quality` name/version/raw SHA-256 and `GENIE_QUALITY_V1` policy ID to match the
frozen `run_context.validation` tuple. Validate the complete effective threshold map and exact
`benchmark_outcomes` mapping, then recompute the canonical effective-policy SHA-256 over
`{policy_id, thresholds, benchmark_outcomes}`.

The exact frozen identity fields are:

```text
genie_quality_contract_name
genie_quality_contract_version
genie_quality_contract_sha256
genie_quality_policy_id
genie_quality_effective_policy_sha256
```

Require `llm_genie_design.yaml`, `benchmark_results.yaml`, the matching Genie validation, and the
Genie manifest to carry the exact tuple/hash fields required at their creation points. Document the
selected benchmark outcome, action, and stage status from those authenticated artifacts; never
recalculate them from prose or substitute a request-time default. A mismatch is
`DOCUMENTATION_CONSISTENCY_ERROR` and is recorded as quality-policy drift, not silently repaired.

Capture:

```text
accelerator.yaml: domain, data_source.type, requested catalog/assets, and model/validation options
run_context.yaml: run_id, resolved version/version_suffix, enabled stages, resolved catalog/schema, output_folder, and frozen Genie quality policy
step_handoff.yaml: exact resolved Metric View FQNs, dashboard display names, Genie title, warehouse_id, and paths
```

Only include configuration values relevant to understanding the generated solution.

Do not dump the full configuration file into the README.

---

# Step 2: Load Run Artifacts

Read all artifacts that exist for this run.

Potential artifacts include:

```text
erd_parsed.yaml
schema_assumptions.yaml
table_spec.yaml
ddl_preflight.yaml
schema_reconciliation.yaml
semantic_model.yaml
synthetic_data_spec.yaml
data_layer_validation.yaml

{OUTPUT_FOLDER}/metric_views/schema_profile.yaml
{OUTPUT_FOLDER}/metric_views/kpi_metric_mapping.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml
{OUTPUT_FOLDER}/metric_views/resolved_metric_view_capabilities.yaml

{OUTPUT_FOLDER}/dashboards/dashboard_design.yaml
{OUTPUT_FOLDER}/dashboards/dashboard_dataset_validation.yaml
{OUTPUT_FOLDER}/dashboards/llm_dashboard_design.yaml
dashboards/*_manifest.json
dashboards/*_validation.yaml

genie_space/genie_semantic_inventory.yaml
genie_space/llm_genie_design.yaml
genie_space/benchmark_results.yaml
genie_space/*_manifest.json
genie_space/*_validation.yaml

genie_space/{run_context.assets.sample_queries_file}

ground_truth_validation.yaml
```

### Ground-Truth Validation Artifact

`ground_truth_validation.yaml` SHOULD exist before documentation is written. Treat it as consolidated, readback-backed evidence only when all of the following hold:

- `source: cross_validation_sweep` exactly;
- `overall_status: PASS` exactly;
- `run_id` equals the frozen current `run_context.run_id` and `output_folder` equals the frozen
  current `run_context.output_folder`, both exactly;
- `scope_input_binding: PASS` exactly;
- `scope_inputs_sha256` is a non-empty 64-character lowercase hexadecimal digest that matches the
  frozen immutable-scope digest persisted by the authenticated terminal sweep; and
- `expected_inventory` and `observed_inventory` have the exact same key set and exact per-key
  duplicate-free contents, with no missing or extra inventory key or item; and
- the strategy-aware Metric View producer checkpoint authentication applicable to the current
  strategy passes; and
- when Genie is enabled, the sweep scope's `genie_quality_contract` tuple/effective-policy hash and
  each Genie asset result's selected outcome/action/stage status exactly match the authenticated
  current-run policy and same-run validation/manifest evidence.

The scope digest proves which immutable sweep inputs were validated; documentation must preserve
it in its evidence references and in the draft manifest. Do not recompute it over a guessed input
set. A missing/malformed digest or non-PASS scope binding makes the sweep untrusted for
consolidated ground-truth claims, even if another status field says PASS.

Also populate `validation.cross_validation.ground_truth_validation_sha256` from the SHA-256 of the
exact raw bytes re-read from the persisted `{OUTPUT_FOLDER}/ground_truth_validation.yaml`. A PASS
sweep requires a matching 64-character lowercase hexadecimal digest. A persisted FAIL or
`documentation_fallback` report also uses its exact raw-byte digest; use `null` only when no
ground-truth report was persisted. The digest is external orchestration/documentation evidence: never
write it into `ground_truth_validation.yaml` itself, which would create a self-referential hash.

A fallback file MUST use `source: documentation_fallback` and
`overall_status: SWEEP_UNAVAILABLE` exactly (not a top-level `status` field). It is evidence that the
sweep was unavailable and is never ground truth. Record the draft's nested
`validation.cross_validation.status` as `SWEEP_UNAVAILABLE`, with both bindings `UNKNOWN`, when this
fallback is used. Even a successful, scope-bound sweep covers only the fields/checks it actually
verified; direct current catalog/API readback remains factual authority if they disagree.

**If `ground_truth_validation.yaml` is missing, unsuccessful, or marked sweep-unavailable:**

This means the terminal cross-validation stage either failed or was unavailable. The documentation step does NOT re-run the sweep. Instead:

1. Document the gap and the artifact's actual missing/failure/unavailable status; do not describe a fallback artifact as a completed sweep.
2. Use same-run per-step evidence that records API readback or executed SQL validation where available.
3. Treat manifests, agent-reported validations, designs, and configuration as unverified evidence for deployed-state claims.
4. Do not convert manifest-only evidence into `DEPLOYED`, `PUBLISHED`, `IMPLEMENTED_AND_VALIDATED`, or `PASS`.
5. In the README, clearly state: "Cross-validation sweep did not complete. Claims without per-step readback are recorded as unverified rather than confirmed deployed state."

**DO NOT:**
- Run Python code to load `gate_checks.py` or execute a cross-validation sweep during the documentation step. The sweep is the sole responsibility of the authenticated `{AGENT_SKILLS_DIR}/prompts/cross_validation/instructions.md` stage, not the documentation stage.
- Re-execute earlier pipeline stages (data layer, metric views, dashboards, Genie).
- Run any notebook that imports `dbldatagen` — that is exclusively a Step 2 dependency.
- Halt the documentation step because `ground_truth_validation.yaml` is missing. Produce documentation from available artifacts.

**Observed-state evidence hierarchy** (documentation classifications; upstream artifacts need not use these exact strings):

1. `source: cross_validation_sweep` — terminal sweep whose expected inventory came from current-run resolved contracts, whose exact locators passed parity, whose `scope_input_binding: PASS` and lowercase 64-hex `scope_inputs_sha256` authenticate its immutable inputs, and which verified those assets via catalog/API readback
2. `source: api_readback` — post-deploy readback of individual assets
3. `source: executed_sql_validation` — result of a recorded validation query for the specific check it executed
4. deployment manifest — records an attempted write, returned identifier, or handoff, but does not independently prove current deployed state
5. `source: agent_reported` or no `source` field — written without readback verification; treat deployed-state claims as **unverified**

**Rules:**
- If a per-dashboard `*_validation.yaml` has `source: api_readback`, use its counts (widgets, filters, datasets) as verified same-run evidence for the README; direct current readback prevails if a conflict is observed.
- If a validation artifact has `source: agent_reported` or no `source` field, treat it as **unverified**. Cross-reference against `ground_truth_validation.yaml` if available.
- If `ground_truth_validation.yaml` conflicts with a per-asset artifact, preserve both values. Use the verified readback value for current deployed state, use the design/configuration value for intent, and record `DRIFT` with both source paths.
- The README's dashboard widget/filter counts and Genie instruction/question counts MUST come from `api_readback` or `cross_validation_sweep` artifacts when available, NOT from agent-reported manifests.
- A manifest may supply a recorded asset ID or requested publication flag, but it MUST NOT by itself establish that the asset currently exists or is published.
- **If `ground_truth_validation.yaml` shows `overall_status: FAIL`, never write root lifecycle
  `status: completed` in `documentation/run_manifest_draft.json`; use the Step 4 mapping below.**

### Artifact Completeness Check

Compare the files actually present in the output folder against the expected artifact list below. Any missing artifacts should be documented in the Known Limitations section.

**Expected dashboard artifacts** (per dashboard):
- `llm_dashboard_design.yaml`
- `dashboard_design.yaml`
- `dashboard_dataset_validation.yaml`
- `{resolved_display_name}_manifest.json`
- `{resolved_display_name}_validation.yaml`

**Expected Genie artifacts:**
- `genie_semantic_inventory.yaml`
- `llm_genie_design.yaml`
- `genie_space/{genie_title}_manifest.json`
- `benchmark_results.yaml`
- `genie_space/{genie_title}_validation.yaml`
- the exact `run_context.assets.sample_queries_file`
- Configuration notebook

Missing intermediate artifacts (e.g., no `dashboard_design.yaml`) indicate that the agent skipped mandatory steps. Flag these in the README.

Do not require artifacts that are not applicable to the frozen current-run `run_context.data_source.type`.

Examples:

- `live_schema` may not have `erd_parsed.yaml`.
- `erd` may not have live-schema drift information.
- Genie may be disabled.
- Dashboards may be disabled or only partially generated.

Document only artifacts applicable to the current run.

---

# Step 3: Establish Field-Scoped Artifact Authority

There is no single artifact authority order for every field. Apply authority according to the claim being documented:

| Claim | Intent authority | Observed/deployed authority |
|---|---|---|
| Enabled stages, requested asset names, model selection | `accelerator.yaml` | `run_context.yaml` for resolved/executed run configuration; verified readback for deployed state |
| KPI definition and expected business meaning | KPI specification | Never overwritten by deployment evidence |
| Expected schema, roles, grain, and relationships | resolved `erd_parsed.yaml`, authenticated `schema_assumptions.yaml`, `table_spec.yaml`, `semantic_model.yaml` | catalog/API readback and executed data-layer validation |
| Metric mapping and planned semantics | `{OUTPUT_FOLDER}/metric_views/kpi_metric_mapping.yaml`, `metric_view_plan.yaml`, and `metric_view_design.yaml` in the same directory | verified `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` and Metric View readback |
| Metric View feature decision | `{OUTPUT_FOLDER}/metric_views/resolved_metric_view_capabilities.yaml` and its recorded version/hash | verified generation and readback result |
| Dashboard design | dashboard design artifacts | dashboard API readback or terminal cross-validation |
| Genie design | Genie design artifacts | Genie API readback, verified benchmarks, or terminal cross-validation |
| Genie release thresholds/outcome semantics | approved `genie_quality` source contract | authenticated Step-0 effective snapshot and same-run quality-bound artifacts |
| Identifier returned by a deployment request | deployment manifest | API readback confirms whether the referenced asset currently exists |

Classify evidence used for a documented claim as:

- `VERIFIED` — supported by same-run API readback, catalog inspection, executed SQL validation, or cross-validation for that field;
- `DECLARED_INTENT` — supported only by specification, configuration, or design;
- `RECORDED_UNVERIFIED` — supported by a manifest or agent-reported result without readback;
- `DRIFT` — intended and observed values differ;
- `NOT_APPLICABLE` — the configured stage or field does not apply;
- `UNKNOWN` — evidence is absent or insufficient.

These are README/documentation classifications, not a requirement to retrofit new fields into upstream validation schemas.

When artifacts disagree:

1. Preserve the intended value and cite its source.
2. Preserve the observed value and cite its source.
3. Mark the claim `DRIFT`.
4. Use the observed value for statements about current deployment.
5. Use the intended value for statements about requested business meaning or design.
6. Never modify an upstream artifact or silently select one value merely to make the README internally consistent.

Do not state that an asset is successful solely because it appears in configuration, design, or a deployment manifest.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "gather_artifacts"
> - `phase_name`: "Gather Artifacts"
> - `status`: "completed"
> - `findings`: ["{N} artifacts loaded", "Artifact authority established"]
> - `stats`: {"artifacts_loaded": N, "steps_documented": M}

---

# Step 4: Determine Overall Run Status

Determine:

```text
PASS
PARTIAL_SUCCESS
FAIL
```

Use:

### PASS

All mandatory enabled pipeline stages completed successfully and their mandatory validations passed with `VERIFIED` evidence for the relevant fields. A manifest-only completion record cannot produce `PASS`.

### PARTIAL_SUCCESS

Core pipeline completed but one or more optional:

- KPIs;
- widgets;
- dashboards;
- Genie questions;
- semantic elements

were skipped or failed without invalidating the overall solution.

A structurally valid Dashboard with `quality_target_status: WARN` is exactly
`validation.dashboards: PARTIAL_SUCCESS`; preserve that value in the Dashboard step and overall run
status calculation. Do not call the deployment failed, and do not upgrade it to PASS merely because
the canonical dashboard manifest was allowed.

The terminal cross-validation sweep is mandatory. If it is missing, failed, unavailable, or not
fully authenticated for this run, the overall validation outcome is `FAIL`; documentation may run
only in failure-reporting mode. Same-run per-step API readback or executed validation may still
support individual `VERIFIED` subclaims, but it cannot replace the terminal sweep or produce an
overall `PASS`. Use `RECORDED_UNVERIFIED` for manifest/agent-reported evidence or `UNKNOWN` when
evidence is absent or insufficient; do not invent `PARTIALLY_VERIFIED`/`UNVERIFIED`.

### FAIL

A mandatory pipeline stage failed or required validation did not pass.

Document the reason.

The three values above are validation outcomes, not the draft's root lifecycle enum. Set
`documentation/run_manifest_draft.json.status` by this total, case-sensitive mapping only:

```text
PASS            -> completed
PARTIAL_SUCCESS -> partial_success
FAIL            -> failed
```

Never copy `PASS`, `PARTIAL_SUCCESS`, or `FAIL` directly into the draft's root `status`. Keep those
validation outcomes only in the applicable per-step and `validation` fields defined by the shared
manifest schema.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "generate_documentation"
> - `phase_name`: "Generate Documentation"
> - `status`: "started"
> - `current_task`: "Writing comprehensive README documentation"
> - `happenings`: ["Documenting data layer", "Documenting metric views", "Documenting dashboards and Genie"]

---

# Step 5: Write README

### Pre-Flight Checklist

Before writing the README, confirm:

- [ ] Current-run `run_context.yaml`/`step_handoff.yaml` loaded for resolved values; load `accelerator.yaml` only if readable, otherwise label original-request-only fields `UNKNOWN`
- [ ] All applicable run artifacts from Step 2 have been read (do not skip available artifacts)
- [ ] Field-scoped artifact authority and evidence classification applied (Step 3)
- [ ] Overall run status determined (Step 4)
- [ ] For every asset to be documented: corresponding manifest or validation artifact exists
- [ ] No artifact shows `status: FAIL` on a mandatory check without being classified correctly in Step 4

If a required artifact cannot be read (workspace IO error), classify as `DOCUMENTATION_ARTIFACT_MISSING` and document the gap rather than guessing.

Create:

```text
{OUTPUT_FOLDER}/documentation/readme.md
```

All documentation files MUST be written under `{OUTPUT_FOLDER}/documentation/`. Never write documentation to the project root or user home directory.

**Directory creation:** Before writing any documentation file, ensure the `documentation/` subdirectory exists. If it does not (e.g., Step 0 did not create it), create it using Workspace API `mkdirs` or agent tooling. In Genie Code context, `os.makedirs(f"{OUTPUT_FOLDER}/documentation", exist_ok=True)` is acceptable. Do NOT halt the documentation step because the directory is missing — create it and proceed.

using Workspace API / agent tools defined by:

```text
workspace_file_io.md
```

Never use `dbutils.fs` for `/Workspace/`.

The README must contain the following sections.

---

# 1. Solution Overview

Include:

- domain display name;
- resolved domain name;
- accelerator version suffix;
- data-source mode;
- source catalog/schema locations;
- target catalog/schema;
- overall run status.

Provide a short factual description of what the generated solution contains.

Example structure:

```text
This accelerator run created a semantic analytics solution for <domain> using <data source mode>. The solution includes <N> Metric Views, <N> dashboards, and <Genie status>.
```

Include reproducibility metadata:

```text
Generated: <ISO 8601 timestamp>
Requested Default Model: <llm.default_model from accelerator.yaml>
Requested Vision Model: <llm.vision_model from accelerator.yaml>
Executed ERD/Dashboard/Genie Models: <same-run model-call/stage metadata, or UNKNOWN>
Version: <run_context.version.asset_suffix>
```

Do not state that a requested model executed unless same-run stage/model-call metadata confirms it.

Do not use marketing language.

---

# 2. Architecture / Asset Flow

Document the generated solution flow.

Use a simple text diagram such as:

```text
Source Data / ERD
      ↓
Unity Catalog Tables
      ↓
Metric Views
      ↓
AI/BI Dashboards
      ↓
Genie Space / Agent
```

Modify this based on the actual run.

For brownfield runs where no tables were generated:

```text
Existing Unity Catalog Data
      ↓
Metric Views
      ↓
Dashboards / Genie
```

Do not show stages that did not execute.

---

# 3. Source Schema Summary

For `erd` or greenfield portions of `erd_and_live_schema`, summarize:

```text
erd_parsed.yaml
semantic_model.yaml
```

Include:

- number of tables;
- table roles;
- important grains;
- relationship count;
- unresolved ERD elements if any.

Do not reproduce every column.

Provide a compact table such as:

| Table | Role | Grain | Key Relationships |
|---|---|---|---|

---

For `live_schema` or live portions of `erd_and_live_schema`, summarize:

```text
{OUTPUT_FOLDER}/metric_views/schema_profile.yaml
```

Include:

- catalogs/schemas profiled;
- table count;
- fact/dimension/bridge/SCD classifications;
- significant schema gaps;
- schema drift if present.

For `erd_and_live_schema`, explicitly document ERD-vs-live drift.

Treat ERD and semantic-model values as intended design. Treat catalog/API readback and executed schema validation as observed state. If expected and observed schemas differ, show both values and classify the difference as `DRIFT`; do not rewrite the design artifact to match the deployed schema.

---

# 4. Data Layer

Include this section only when greenfield data generation ran.

Summarize:

- Unity Catalog tables created;
- synthetic-data generation status;
- row counts by major table;
- PK validation;
- FK validation;
- cardinality validation;
- semantic constraint validation.
- governed datatype-resolution status and every inferred datatype, including confidence and basis;
- deployed schema reconciliation status, including any bounded empty-table datatype repair.

Source these facts from:

```text
schema_assumptions.yaml
schema_reconciliation.yaml
data_layer_validation.yaml
```

Authenticate all three artifacts to the frozen current run before using them. Never describe an
`observed: false` datatype resolution as visible in the ERD; label it `INFERRED_POLICY` and show its
raw value, resolved value, resolution source, evidence, and confidence. For greenfield runs, do not
describe datatype reconciliation as successful unless
`schema_assumptions.policy_id: GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`,
`schema_assumptions.unresolved_datatypes: []`,
`schema_reconciliation.policy_id: DEPLOYED_DATATYPE_REPAIR_V1`,
`schema_reconciliation.status: PASS`, and
`schema_reconciliation.unresolved_mismatches: []` are all present exactly and its table identities
belong to the frozen run. Preserve that exact policy ID, status, unresolved-mismatch inventory,
and attempt evidence in the README and manifest draft. A missing field, mismatched policy, or
non-empty unresolved list is `DRIFT`/failure evidence; documentation must not infer success from a
stage-level PASS.

Use a row count or integrity result as verified only when the artifact records the executed check/readback evidence or the same check is confirmed by `ground_truth_validation.yaml`. Otherwise label the value `RECORDED_UNVERIFIED` in the documentation.

Report failures or generic fallback columns where relevant.

When `schema_reconciliation.attempts` is non-empty, report the exact table, expected and observed
types, ownership classification, row count, action, and post-repair result. Describe
`DROP_RECREATE_FROM_TABLE_SPEC` only as a bounded repair of an empty current-version generated
target under policy `DEPLOYED_DATATYPE_REPAIR_V1`. Never describe casts, ALTERs, non-empty
recreation, or intent changes as approved repair.
If reconciliation failed, preserve expected and observed types and classify the claim as `DRIFT`;
do not present the deployed schema as accepted.

Do not claim synthetic data is realistic merely because generation succeeded.

---

# 5. Metric Views

List every generated Metric View.

For each include:

```text
name
FQN
source table (or intermediate materialized view)
source grain
validated measures
major dimensions
validation status
```

Use `{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml` and `{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml` for intended grouping and semantics. Use verified `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml`, Metric View readback, or `ground_truth_validation.yaml` for deployed existence, actual measures/dimensions, and validation status.

Source from:

```text
{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml
```

Use a table such as:

| Metric View | Intended Source/Grain | Observed Source/Grain | Measures/Dimensions | Status | Evidence |
|---|---|---|---|---|---|

If no readback exists, describe the Metric View as `RECORDED_UNVERIFIED`, not as deployed. When planned and observed definitions differ, preserve both and mark `DRIFT`.

If multiple Metric Views were created because of incompatible fact grains, explain the grouping rationale briefly (e.g., claim-line grain vs member-month grain).

If any **intermediate materialized views** were intended or verified to support a metric view (e.g., joining fact_claim_detail with fact_claim_header), document them:

| Intermediate View | Source Tables | Join Type | Fanout Check |
|---|---|---|---|

Use `{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml` → `metric_views[].intermediate_view` only for intended definitions. Claim that an intermediate view was created, state its observed definition, or report its fanout result only when current-run catalog inspection or executed validation corroborates it. Otherwise label it `RECORDED_UNVERIFIED`.

---

# 6. KPI Catalog

Document every KPI from the KPI specification.

Use:

```text
{OUTPUT_FOLDER}/metric_views/kpi_metric_mapping.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml
```

For each KPI report its final status and evidence source. KPI intent comes from the KPI specification and mapping; implementation status comes from verified Metric View validation/readback. A planned mapping alone does not prove implementation.

Allowed documentation statuses should reflect the Metric View validation artifact, such as:

```text
IMPLEMENTED_AND_VALIDATED
NOT_IMPLEMENTED
SKIPPED_MISSING_DATA
SKIPPED_UNRESOLVED_RELATIONSHIP
SKIPPED_UNSAFE_GRAIN
SKIPPED_UNSUPPORTED_SEMANTICS
```

Use:

| KPI | Intended Mapping | Observed Metric View/Measure | Status | Evidence | Notes |
|---|---|---|---|---|---|

Do not collapse all skipped KPIs into a generic "not implemented."

Include the actual reason.

**NOT_IMPLEMENTED vs SKIPPED distinction in documentation:**
- `NOT_IMPLEMENTED`: The KPI was not generated under the resolved Metric View capability contract. Document the recorded capability key, policy scope (`PLATFORM` or `ACCELERATOR`), contract version/hash, reason, and fallback from `{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml` and `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml`. Do not infer current Databricks support from the SQL feature name. These KPIs are ineligible for dashboards or Genie; claim deployed absence only when downstream readback confirms it. Their reference SQL may be documented for manual implementation.
- `SKIPPED_*`: The KPI cannot be implemented due to data quality, missing relationships, or unsafe grain. No reference SQL is available.

---

# 6.1 Not Implemented KPIs

If current-run `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` contains one or more terminal `NOT_IMPLEMENTED` KPI results, include this dedicated section in the README. A plan entry alone cannot assign terminal status.

Use the matched pair:

```text
{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml → terminal KPI status and validated capability decision
{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml → matching intended reason, reference SQL, and manual notes
```

For each NOT_IMPLEMENTED KPI, document:

1. **KPI ID and name**
2. **Recorded capability decision and reason** it was not generated as a metric view measure
3. **Full reference SQL query** (copy from `{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml`)
4. **Manual implementation notes** (how to use the SQL if needed later)

Use this structure:

```markdown
## Not Implemented KPIs

The following KPIs were not generated under the resolved Metric View capability
contract. The policy scope, capability decision, and available reference SQL are
provided below for manual implementation if needed.

### <KPI-ID>: <KPI Name>

**Reason:** <reason from {OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml>

**Capability:** <capability key; PLATFORM or ACCELERATOR scope; contract version/hash>

**Status:** NOT_IMPLEMENTED — documentation only

<sql block with the full reference SQL from {OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml; label its validation status from evidence>

**To implement manually:** <manual_implementation_notes from {OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml>
```

**Rules:**
- Include the FULL SQL query — do not truncate or summarize
- Call the SQL `validated` only when an executed-query validation record exists; otherwise label it `UNVERIFIED_REFERENCE_SQL`
- These KPIs are ineligible for dashboards or Genie spaces. Claim they are absent from deployed downstream assets only when the corresponding API readback/ground-truth evidence confirms that absence.
- This section provides a clear handoff for anyone who wants to implement these KPIs manually (e.g., as named SQL datasets in a dashboard)

---

# 7. Dashboards

For every logical dashboard in the frozen current-run inventory:

```text
run_context.yaml assets.dashboards[]
```

locate its exact resolved display name in `step_handoff.yaml.dashboard_display_names[]`, then read only the matching design, manifest, validation, and API-readback evidence. Do not turn an arbitrary or stale manifest found in the output folder into a current-run dashboard.

include:

- display name;
- dashboard ID;
- source Metric View(s);
- page structure (filter page + canvas pages with page names);
- page-contract source, exact expected/observed mapped-page IDs, and structural page-contract status;
- total widget count (counters, charts, tables by type);
- filter count and filter dimensions;
- visualization diversity (how many distinct viz types used);
- design source (LLM-assisted from `llm_dashboard_design.yaml` or manual);
- publication status;
- structural validation status;
- quality-target status and every recorded warning;
- Dashboard stage status (`PASS`, `PARTIAL_SUCCESS`, or `FAIL`);
- workspace/AI/BI link only when the ID is corroborated by API readback or terminal cross-validation.

When `llm_dashboard_design.yaml` exists, note that dashboards were designed by the LLM reasoning
model and document the design quality (pages per dashboard, widget density, visualization
diversity, filter count, and primary-KPI contexts). Do not present a quality target as a mandatory
structural gate.

Use the dashboard design artifact for intended layout. Use `source: api_readback` validation or `ground_truth_validation.yaml` for current existence, publication state, and observed counts. A dashboard manifest may provide a recorded ID or deployment response, but it is not independent proof that the dashboard currently exists or remains published.

Use:

```text
*_manifest.json
*_validation.yaml
```

as complementary intent, deployment-record, and observed-state sources according to Step 3.

Example:

| Dashboard | Recorded ID | Page Contract | Observed Pages/Widgets | Structural | Quality Targets | Stage | Evidence |
|---|---|---|---|---|---|---|

### Deployed Asset Links

When the exact resolved `workspace_host` is available from `step_handoff.yaml`, construct clickable links:

```text
Dashboard: {workspace_host}/dashboardsv3/{dashboard_id}/published
Genie Space: {workspace_host}/genie/rooms/{space_id}
```

Only construct links when `step_handoff.yaml.workspace_host` is present and the asset ID is corroborated by API readback or the terminal cross-validation sweep. Do not re-resolve the host from `databricks.yml` in this stage.

Do not construct URLs from assumptions if a verified ID is unavailable.

---

# 8. Genie Space / Genie Agent

For the Genie entry frozen in current-run `run_context.yaml`, locate the exact `step_handoff.yaml.genie_title` and its matching artifacts. If API-readback evidence confirms successful deployment, document it as deployed; otherwise document the intended/recorded state with the applicable evidence label.

- title;
- space ID;
- warehouse ID;
- attached Metric Views;
- instruction quality (character count, format: markdown/plain, section count);
- sample-question count and pattern diversity (how many of 8 analytical patterns covered);
- example-SQL count and validation rate (e.g., "20/20 passed");
- benchmark count (with answer format);
- benchmark pass rate where available;
- authenticated Genie quality contract name/version/raw hash, policy ID, and effective-policy hash;
- effective threshold snapshot used by the run;
- contract-resolved benchmark outcome/action and resulting stage status;
- design source (LLM-assisted from `llm_genie_design.yaml` or manual);
- configuration notebook path;
- validation status.

When `llm_genie_design.yaml` exists, note that the Genie configuration was designed by the LLM reasoning model and document the design quality metrics.

Source from:

```text
genie_semantic_inventory.yaml
llm_genie_design.yaml
benchmark_results.yaml
*_manifest.json
*_validation.yaml
run_context.yaml
```

Use the Genie design and semantic-inventory artifacts for intended configuration. Use Genie API readback, verified benchmark results, or `ground_truth_validation.yaml` for current deployment and validation claims. A manifest-recorded space ID alone is `RECORDED_UNVERIFIED`.

Threshold values and outcome meanings come only from the authenticated frozen policy. Do not copy a
number or PASS/WARN/FAIL interpretation from this prompt, a guardrail, or the current request.

Do not report Genie as validated solely because the space exists, and do not report it as deployed solely because a manifest contains a space ID.

If Genie creation was skipped or failed, state that explicitly.

---

# 9. LLM-Assisted Design Summary

If LLM design artifacts exist (`llm_dashboard_design.yaml` and/or `llm_genie_design.yaml`), include a section documenting the AI-assisted design process:

### Dashboard Design

When `llm_dashboard_design.yaml` exists:

- Requested model (from `accelerator.yaml` → `llm.steps.dashboard_design.model`)
- Executed model, only when recorded by same-run dashboard-stage/model-call metadata; otherwise `UNKNOWN`
- Number of dashboards designed
- Page-contract resolution source and exact expected/actual page IDs; a mapped count overrides the
  frozen page-count target
- Frozen quality-target values and observed results for page count, widget density, visualization
  diversity, filter count, and primary-KPI contexts
- Whether design passed GATE 3.1 (exact mapped-page inventory or non-empty fallback inventory)
- `quality_target_status: PASS|WARN` and the derived Dashboard stage status
- Key design decisions (e.g., KPI grouping across pages)

### Genie Space Design

When `llm_genie_design.yaml` exists:

- Requested model (from `accelerator.yaml` → `llm.steps.genie_design.model`)
- Executed model, only when recorded by same-run Genie-stage/model-call metadata; otherwise `UNKNOWN`
- Instruction quality: character count, format (markdown with ## headers), content sections
- Question pattern coverage: how many of 8 analytical patterns (HEADLINE, TIME_TREND, DIMENSION_BREAKDOWN, FILTERED, RANKING, COMPARISON, MULTI_MEASURE, RATIO)
- Example SQL validation: count passed / total
- Benchmark questions: count and answer format
- Authenticated quality contract/effective-policy identity and contract-resolved benchmark outcome

This section helps consumers understand the AI-driven design quality and reproducibility.

Do not include this section if no LLM design artifacts exist (manual/template-only runs).

---

# 10. Validation Summary

Provide one concise consolidated validation table.

Example:

| Layer | Validation | Result | Evidence Status | Evidence Source |
|---|---|---|---|---|
| Data Layer | Schema integrity | PASS | VERIFIED | `data_layer_validation.yaml` executed schema checks |
| Data Layer | PK/FK integrity | PASS | VERIFIED | `ground_truth_validation.yaml` |
| Metric Layer | KPI reconciliation | PASS | VERIFIED | `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` readback-backed checks |
| Metric Layer | Join fanout checks | PASS | VERIFIED | `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` executed checks |
| Dashboards | Dataset SQL | PASS | VERIFIED | `ground_truth_validation.yaml` |
| Dashboards | Filter binding | UNKNOWN | RECORDED_UNVERIFIED | dashboard manifest only |
| Genie | Example SQL | PASS | VERIFIED | Genie validation artifact |
| Genie | Benchmarks | PASS | VERIFIED | Genie benchmark validation artifact |

Include only applicable checks.

If a validation failed, link it to the corresponding generated validation artifact path.

---

# 11. Known Limitations

Document known gaps and constraints of the generated solution.

Sources:

- Skipped or not-implemented KPIs from `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml`, reconciled with `{OUTPUT_FOLDER}/metric_views/resolved_metric_view_capabilities.yaml` (with policy scope and reasons)
- `GENERIC_FALLBACK` columns from `data_layer_validation.yaml`
- Unresolved ERD elements from `erd_parsed.yaml`
- Failed benchmark questions from Genie validation
- Any `WARN` conditions from upstream validations

Structure:

| Limitation | Layer | Impact | Reason |
|---|---|---|---|
| <KPI ID from validation> | Metric View | KPI not available | <recorded capability key, PLATFORM/ACCELERATOR scope, and reason from the resolved contract/validation> |

Do not speculate about limitations not evidenced by artifacts.

Do not minimize documented limitations with qualifiers like "minor" or "unlikely to matter."

This section is critical for consumer trust — it sets accurate expectations.

---

# 12. Usage

Explain how a consumer should use the generated assets.

## Query Metric Views

Provide a small generic example using the actual generated Metric View and measure names:

```sql
SELECT
    <dimension>,
    MEASURE(<validated_measure>)
FROM <metric_view_fqn>
GROUP BY ALL;
```

Use real validated asset names from this run.

Do not invent example measures.

---

## Dashboards

Explain:

- which dashboard(s) to open;
- their intended purpose;
- where to find the dashboard ID/link.

---

## Genie

Explain:

- which Genie Space to open;
- that questions should use the configured semantic model;
- examples of representative sample questions from the generated sample-question inventory.

Do not introduce new unsupported questions.

---

# 13. Troubleshooting

Include this section when overall status is `PARTIAL_SUCCESS` or `FAIL`.

For each failed or degraded layer, provide:

```text
Layer: <Data Layer | Metric Views | Dashboards | Genie>
Symptom: <what the user will observe>
Root Cause: <from validation artifact>
Resolution: <specific next step>
Artifact: <path to validation file with details>
```

Common patterns:

| Symptom | Likely Cause | Resolution |
|---|---|---|
| Dashboard shows "No rows returned" | FK integrity failure in data layer | Route correction to the Data Layer owner, fix FK generation, and revalidate the affected dependency graph |
| Metric View returns zero rows | Join column mismatch (STRING vs BIGINT) | Check `data_layer_validation.yaml` §7.9 analytical readiness |
| Data Layer reports `DATATYPE_MISMATCH_UNSAFE_TO_REPAIR` | Deployed type conflicts with `table_spec.yaml`, but the table was non-empty, not current-version-owned, ambiguous, unreadable, or already retried | Review standalone `schema_reconciliation.yaml` (and its authenticated copy in final `data_layer_validation.yaml`, if final validation ran); preserve the table and perform an explicitly approved migration/cleanup outside the automatic pipeline |
| Genie gives wrong answers | Incorrect MEASURE() SQL | Check `genie_space/{genie_title}_validation.yaml` benchmark failures |
| Dashboard filters don't respond | Missing filter column in dataset SQL | Check the matching `dashboards/{resolved_display_name}_validation.yaml` filter binding |

Adapt based on actual failures observed in this run's validation artifacts.

Do not include this section when status is `PASS`.

---

# 14. Generated Artifacts

List important generated files by logical category.

Example:

```text
Schema
- erd_parsed.yaml
- semantic_model.yaml

Metrics
- {OUTPUT_FOLDER}/metric_views/kpi_metric_mapping.yaml
- {OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml
- {OUTPUT_FOLDER}/metric_views/metric_view_design.yaml
- {OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml

Dashboards
- dashboard_design.yaml
- <dashboard>_manifest.json
- <dashboard>_validation.yaml

Genie
- genie_semantic_inventory.yaml
- llm_genie_design.yaml
- benchmark_results.yaml
- <space>_manifest.json
- <space>_validation.yaml
- the exact `run_context.assets.sample_queries_file`

Dashboards (LLM Design)
- llm_dashboard_design.yaml
```

Only list files that actually exist.

---

# 15. Configuration Reference

Summarize requested configuration from `accelerator.yaml` and the corresponding resolved values from the current run's `run_context.yaml` and `step_handoff.yaml`. Label them separately when they differ.

Include relevant keys such as:

```text
domain
data_source.type
catalog.source
catalog.target
assets.metric_views
assets.dashboards
assets.genie
run_context.version.version_suffix / run_context.version.asset_suffix
validation.genie_quality_contract_name/version/sha256
validation.genie_quality_policy_id
validation.genie_quality_effective_policy_sha256
validation effective Genie thresholds and benchmark outcome mapping
```

Reference:

```text
accelerator.yaml
run_context.yaml
step_handoff.yaml
run_context.inputs.genie_quality_contract
```

for full configuration.

Do not duplicate the complete YAML.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "generate_documentation"
> - `phase_name`: "Generate Documentation"
> - `status`: "completed"
> - `findings`: ["README.md generated", "All sections written from artifacts"]
> - `stats`: {"sections_written": N}

---

# Step 6: Validate, Check Placeholders, and Write Manifest (SINGLE PASS)

## CRITICAL — EFFICIENCY (saves 10+ tool calls)

Steps 6, 7, and 8 may reuse the authenticated evidence snapshot from Steps 1–2 for
composition. This optimization never overrides freshness checks, output readback, or checkpoint
persistence. Re-read whenever a consumed artifact may have changed or a gate requires it.

- Check consistency and placeholders against the authenticated evidence scope.
- Write `documentation/readme.md` and `documentation/run_manifest_draft.json`.
- Re-read both persisted outputs and validate exact content, identities and scope.
- Commit and re-read each owning phase checkpoint before reporting completed.
- Do not impose a tool-call limit that omits mandatory validation or persistence.

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_documentation"
> - `phase_name`: "Validate Documentation"
> - `status`: "started"
> - `current_task`: "Validating factual consistency and completeness"
> - `happenings`: ["Checking factual consistency", "Scanning for placeholders", "Writing documentation manifest draft"]

## 6.1 Factual Consistency (from context — NO file reads)

Validate every stated asset using the field-scoped authority and evidence classifications from Step 3 **using data already in your context from Step 2**.

Check:

```text
Metric View documented as deployed → corroborated by Metric View/API readback or cross-validation
Dashboard documented as deployed → dashboard_id corroborated by API readback or cross-validation
Published dashboard → published=true in API readback or cross-validation, not only in a manifest
Genie documented as deployed → space_id corroborated by API readback or cross-validation
Validated KPI → verified validation status is IMPLEMENTED_AND_VALIDATED
Skipped KPI → documented reason exists
Manifest-only deployment record → labeled RECORDED_UNVERIFIED
Intent/readback disagreement → both values retained and labeled DRIFT with both sources
```

If the documentation misstates or omits the available evidence:

```text
DOCUMENTATION_CONSISTENCY_ERROR
```

Fix the documentation. An upstream intent-versus-observed disagreement is not itself a documentation error; preserve it as `DRIFT`.

Do not modify upstream artifacts merely to make documentation consistent.

## 6.2 No Placeholder Check (inline — NO file reads)

Confirm the README contains none of:

```text
<<< REPLACE >>>
TODO
TBD
<placeholder>
example_dashboard_id
example_space_id
```

unless `TODO` or `TBD` is itself actual source content that must be documented.

## 6.3 Write Documentation Manifest Draft

After README generation, write the non-canonical machine-readable draft consumed by the master:

```text
{OUTPUT_FOLDER}/documentation/run_manifest_draft.json
```

using Workspace API / agent tools.

Use the same root and nested schema as canonical `{OUTPUT_FOLDER}/run_manifest.json`; the draft is
distinguished only by its path and by the master's later reconciliation of lifecycle timing and
terminal status. Do not invent a smaller documentation-only `assets`/`kpis` schema.

The immutable draft-to-final identity binding is exactly
`{lifecycle_contract_version, domain, version, run_id, created_by, output_folder,
run_context_path, version_suffix, asset_suffix}`. Require exact equality with the frozen run
context in the draft and require the master's final manifest to preserve the same binding; do not
regenerate, normalize, or partially copy it during reconciliation. Final `status` and timestamps
are intentionally excluded because the master recomputes them from terminal lifecycle evidence.

Structure:

```json
{
  "lifecycle_contract_version": 1,
  "run_id": "<exact run_context.run_id>",
  "created_by": "app|genie_code",
  "domain": "<run_context.domain.name>",
  "data_source_type": "<erd|live_schema|erd_and_live_schema>",
  "version": 1,
  "version_suffix": "_v1",
  "asset_suffix": "_v1",
  "output_folder": "<exact run_context.output_folder>",
  "run_context_path": "<exact canonical tool-supplied run_context_path>",
  "status": "completed|partial_success|failed",
  "started_at": "<same-run ISO timestamp or null>",
  "completed_at": "<same-run ISO timestamp or null>",
  "catalog": {
    "source_catalog": "<resolved source catalog>",
    "source_schema": "<resolved source schema>",
    "target_catalog": "<resolved target catalog>",
    "target_schema": "<resolved target schema>"
  },
  "steps": [
    {
      "step_name": "<canonical step name>",
      "step_order": 0,
      "status": "PASS|PARTIAL_SUCCESS|FAIL|SKIPPED",
      "started_at": null,
      "completed_at": null,
      "duration_s": 0,
      "error": null,
      "substeps": [],
      "stats": [],
      "findings": [],
      "decisions": []
    }
  ],
  "validation": {
    "data_layer": "PASS|PARTIAL_SUCCESS|FAIL|SKIPPED",
    "metric_views": "PASS|PARTIAL_SUCCESS|FAIL|SKIPPED",
    "dashboards": "PASS|PARTIAL_SUCCESS|FAIL|SKIPPED",
    "genie": "PASS|PARTIAL_SUCCESS|FAIL|SKIPPED",
    "cross_validation": {
      "status": "PASS|FAIL|SWEEP_UNAVAILABLE",
      "source": "cross_validation_sweep|documentation_fallback",
      "scope_input_binding": "PASS|FAIL|UNKNOWN",
      "scope_inputs_sha256": "<64 lowercase hex or null>",
      "workspace_host_binding": "PASS|FAIL|UNKNOWN",
      "ground_truth_validation_sha256": "<SHA-256 of exact persisted ground-truth bytes or null>"
    }
  },
  "checkpoint_reconciliation": {
    "contract_version": 1,
    "frozen_run_contract_sha256": "<64 lowercase hex>",
    "status": "PASS|FAIL",
    "valid_phase_count": 0,
    "stale_phase_count": 0,
    "valid_phases": [
      {"step": "create_data_layer", "phase": "parse_erd"}
    ],
    "stale_phases": [
      {"step": "create_metric_views", "phase": "plan_metric_views", "reason": "<non-empty reason>"}
    ],
    "producer_bundles": {
      "create_data_layer": "<64 lowercase hex>",
      "create_metric_views": "<64 lowercase hex>",
      "create_dashboards": "<64 lowercase hex>",
      "create_genie_space": "<64 lowercase hex>",
      "generate_documentation": "<64 lowercase hex>"
    }
  },
  "assets_created": {
    "tables": [],
    "metric_views": [],
    "dashboards": [],
    "genie_space": null
  },
  "artifact_paths": {
    "run_context": "<exact run_context_path>",
    "step_handoff": "{OUTPUT_FOLDER}/step_handoff.yaml",
    "erd_parsed": null,
    "semantic_model": null,
    "synthetic_data_spec": null,
    "data_layer_validation": null,
    "schema_profile": null,
    "kpi_metric_mapping": null,
    "metric_view_design": null,
    "metric_view_validation": null,
    "dashboard_design": null,
    "dashboard_dataset_validation": null,
    "dashboard_manifests": [],
    "dashboard_validations": [],
    "genie_semantic_inventory": null,
    "genie_manifest": null,
    "genie_validation": null,
    "ground_truth_validation": "{OUTPUT_FOLDER}/ground_truth_validation.yaml or null",
    "readme": "{OUTPUT_FOLDER}/documentation/readme.md"
  },
  "kpi_summary": {
    "total": 0,
    "implemented_and_validated": 0,
    "skipped": 0,
    "failed": 0
  },
  "evidence_classifications": {
    "VERIFIED": [
      {
        "claim": "<non-empty factual claim>",
        "sources": ["<canonical same-run artifact path>"]
      }
    ],
    "DECLARED_INTENT": [],
    "RECORDED_UNVERIFIED": [],
    "DRIFT": [],
    "NOT_APPLICABLE": [],
    "UNKNOWN": []
  },
  "error": null
}
```

Populate from the same field-scoped sources used for the README. `catalog` records frozen resolved
source/target coordinates; actual physical table FQNs and counts come from schema-profile/catalog
evidence. Preserve the authenticated cross-sweep scope fields exactly. Datatype reconciliation
remains evidence inside `data_layer_validation.yaml` and the Data Layer step's findings; do not add
a competing root manifest field for it. Do not copy the Metric View producer checkpoint into the
manifest—the authenticated checkpoint remains top-level in `metric_view_plan.yaml` and its paths
belong under `artifact_paths` only where the canonical schema provides them.

For the Genie step and `validation.genie`, preserve the authenticated selected quality rule's
`stage_status`. Do not promote a contract-accepted warning to stage `PASS` merely because its policy
evaluation and readback validation correctly record `overall_status: PASS`.

Build `checkpoint_reconciliation` from the exact authenticated current phase records and frozen
producer bundles. Sort `valid_phases` and `stale_phases` by `(step, phase)`, require their counts to
match their arrays, and use exact stale reasons. The documentation draft records the current
snapshot; the master independently recomputes it for the final manifest. This summary never replaces
the reusable phase records or deployed-state readback.

Do not promote manifest-only evidence to verified deployed state. This draft never owns final
stage status or timing and MUST NOT be written to `{OUTPUT_FOLDER}/run_manifest.json`; the master
reconciles same-run lifecycle records into this identical canonical schema. Before writing, compare
the draft's complete root key set and nested contract key sets to the canonical manifest schema;
missing, renamed, or alternate fields are `DOCUMENTATION_CONSISTENCY_ERROR`.

`evidence_classifications` has exactly the six uppercase keys shown. Each array item has exactly a
non-empty `claim` string and a non-empty `sources` array of canonical same-run artifact paths;
classification arrays may be empty. The master copies and reconciles this field without renaming
keys, flattening it, or collapsing it into counts.

Preserve the canonical schema for disabled stages using `SKIPPED`, empty arrays, or null values as
defined; do not drop their schema keys.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_documentation"
> - `phase_name`: "Validate Documentation"
> - `status`: "completed"
> - `findings`: ["Factual consistency: PASS", "No placeholders found", "Manifest written"]
> - `stats`: {"validation_checks": N, "checks_passed": N}

---

# Step 9: Final Output

Write:

```text
{OUTPUT_FOLDER}/documentation/readme.md
{OUTPUT_FOLDER}/documentation/run_manifest_draft.json
```

Then report:

```text
README path
Run manifest path
overall run status
Metric View count
validated KPI count
skipped KPI count
dashboard count
Genie status
```

---

# Error Classification

Use:

```text
DOCUMENTATION_INPUT_ERROR
DOCUMENTATION_ARTIFACT_MISSING
DOCUMENTATION_CONSISTENCY_ERROR
DOCUMENTATION_WORKSPACE_IO_ERROR
```

For errors report:

```text
Observed problem:
Root cause:
Missing/conflicting artifact:
Affected documentation section:
Corrective action:
```

---

# Pipeline Halt Rules

Documentation generation should NOT fail merely because an upstream optional asset failed.

Instead document that failure.

Return:

```text
❌ EXECUTION HALTED
```

only when:

- required run artifacts cannot be accessed;
- documentation cannot determine the actual run state;
- README cannot be written;
- factual consistency cannot be established.

If the later `accelerator.yaml` request file is unreadable, continue from frozen `run_context.yaml` and `step_handoff.yaml`; label original-request-only fields `UNKNOWN`. Its absence is not allowed to alter or halt the active run.

---

# Non-Negotiable Rules

1. **Documentation preserves both intended state and observed final state; verified observation governs deployed-state claims.**
2. **Validation artifacts are authoritative only for the checks they actually executed and only at their recorded evidence level.**
3. **Do not mark configured, designed, or manifest-recorded assets as deployed unless API readback or cross-validation confirms them.**
4. **Do not mark KPIs implemented unless verified Metric View validation/readback passed.**
5. **Skipped KPIs must include their actual reason.**
6. **Do not invent asset IDs or workspace links.**
7. **Do not infer publication or validation status.**
8. **Do not re-derive schema or metric semantics during documentation generation.**
9. **Only document artifacts applicable to the configured data-source mode.**
10. **Do not modify upstream artifacts to make the README look complete.**
11. **README must contain no unresolved placeholders.**
12. **Workspace writes use `workspace_file_io.md`, never `dbutils.fs`.**
13. **Every deployed-state claim must carry an evidence classification and source; artifact conflicts must be preserved as `DRIFT`.**
14. **Metric View feature/support explanations must come from the resolved capability contract recorded for the run, not hardcoded platform claims.**
15. **Genie thresholds and benchmark outcome semantics must come from the authenticated frozen quality policy, never prompt-local prose or defaults.**
16. On unrecoverable documentation failure:

```text
❌ EXECUTION HALTED
```

---

# Output Contract

| Artifact | Location | Validation Check |
|----------|----------|-----------------|
| run_manifest_draft.json | `{OUTPUT_FOLDER}/documentation/` | Exact canonical root/nested manifest schema, including lifecycle path/version, checkpoint reconciliation, and authenticated cross-sweep scope evidence, for deterministic master reconciliation |
| README.md or summary notebook | `{OUTPUT_FOLDER}/documentation/` | Human-readable summary of the run |
| run_context.yaml | `{OUTPUT_FOLDER}/` | Documentation phases listed; top-level lifecycle status is unchanged until master finalization |

If `run_manifest_draft.json` is missing, the documentation stage is incomplete. The master still exclusively owns the canonical `{OUTPUT_FOLDER}/run_manifest.json`.
