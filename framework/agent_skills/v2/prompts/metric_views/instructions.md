# Create Metric Views

> **Transport:** apply the frozen `shared/agent_transport.md` contract. Tool names are portable operations; App/Lakebase integration is optional. Runtime paths come only from `contracts/release.yaml`.

> **Always load for this stage:** `{AGENT_SKILLS_DIR}/prompts/shared/global_guardrails.md`, `{AGENT_SKILLS_DIR}/prompts/metric_views/validation.md`, `{AGENT_SKILLS_DIR}/prompts/metric_views/guardrails.md`, `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`, `{AGENT_SKILLS_DIR}/prompts/shared/sql_generation_rules.md`.
> **Failure-only:** authenticate `run_context.inputs.stage_runbooks.create_metric_views` and load only the matching section of `{AGENT_SKILLS_DIR}/prompts/metric_views/runbook.md` after a classified failure. Never load the runbook on the normal success path.


<!-- Capability decisions are pinned by the exact frozen run_context.inputs.metric_view_capabilities path. -->

> **Additional authenticated inputs:** exact frozen `run_context.inputs.metric_view_capabilities`
> and `run_context.inputs.genie_quality_contract` for the governed sample-query minimum.


## Failure-Only Runbook Loading

Do not read `{AGENT_SKILLS_DIR}/prompts/metric_views/runbook.md` during normal execution. After this stage classifies a failure, authenticate the frozen runbook tuple, use the routing index in `{AGENT_SKILLS_DIR}/prompts/metric_views/validation.md`, and load only the matching diagnostic section. The runbook cannot weaken a gate, change the failure owner, or authorize a blind retry.

## CONTEXT ISOLATION — Read This First

Forget all execution details from the Data Layer step (ERD parsing, synthetic data generation, DDL execution). You do NOT need that context.

### Canonical Run Bootstrap (Mandatory)

The orchestrator MUST supply the exact `run_context_path` for this invocation. Before reading any
stage artifact, read the raw bytes at that exact path and parse them as `run_context.yaml`. Do not
search for `run_context.yaml`, select the newest run folder, derive a path from the current working
directory, or accept a path copied from the current request.

After parsing, require all of the following:

1. the normalized basename of `run_context_path` is `run_context.yaml`;
2. `run_context.run_id` is non-empty and `run_context.output_folder` is a non-empty absolute path
   (reject a relative path before normalized comparison);
3. the normalized parent of `run_context_path` equals normalized
   `run_context.output_folder` exactly; and
4. `{run_context.output_folder}/step_handoff.yaml` is the one and only handoff path used by this
   stage.

Missing, malformed, ambiguous, or path-inconsistent bootstrap input is
`HANDOFF_AUTHORITY_ERROR`. HALT; do not locate or synthesize a replacement. In the remainder of
this prompt, `{OUTPUT_FOLDER}` means the exact frozen `run_context.output_folder` established by
this bootstrap. Permission, transport, and other genuine I/O failures retain their operational
classification; do not relabel them as malformed authority.

**Your ONLY stage inputs are:**

1. `{OUTPUT_FOLDER}/step_handoff.yaml` — contains:
   - `metric_view_fqns[]` — key is always present; pre-resolved FQN(s) when `strategy: explicit`, empty when `strategy: auto`
   - `metric_view_strategy` — `auto` or `explicit` (from run_context)
   - `metric_view_naming_prefix` — base prefix for auto-generated names (e.g., `member_claims`)
   - `catalog`, `schema`, `version_suffix`, `asset_suffix` — resolved run coordinates; use `asset_suffix` for dynamic asset names
   - `warehouse_id`, `deploy_root`, `output_folder` — exact resolved runtime/path values consumed by the deployment template

2. Exact frozen `run_context.inputs.metric_view_capabilities` — approved capability contract for this accelerator release

3. `{OUTPUT_FOLDER}/table_spec.yaml` — expected generated physical schema for greenfield runs

4. `{OUTPUT_FOLDER}/erd_parsed.yaml` — extracted source-design context; never deployed physical truth

5. `{OUTPUT_FOLDER}/semantic_model.yaml` — relationships and grain

6. `{OUTPUT_FOLDER}/data_layer_validation.yaml` — upstream deployment and relationship validation

7. KPI specification — business definitions and formulas

8. Exact frozen `run_context.inputs.genie_quality_contract` — authenticated source for
   `run_context.validation.min_sample_query_file_queries`; no other Genie policy is executed here

`run_context.yaml` is authoritative only for resolved run configuration, and `accelerator.yaml` contains requested configuration. Neither may substitute for the exact identity contract in `step_handoff.yaml`. Runtime catalog inspection (`DESCRIBE TABLE`, `SHOW CREATE TABLE`, `SHOW VIEWS`, and approved API readback) is required to observe deployed reality; it is not prior-stage prompt context.

**Rules:**
- After the canonical run bootstrap, read the exact `{OUTPUT_FOLDER}/step_handoff.yaml` first, then resolve `metric_view_capabilities.yaml` before profiling, planning, or generating YAML
- Treat handoff `catalog` and `schema` as resolved target coordinates for newly created Metric Views and intermediate objects
- Use each exact source-table FQN from the reconciled `schema_profile.yaml` and its current catalog inspection; never substitute current `accelerator.yaml` source coordinates or assume every profiled source shares the target namespace
- In `explicit` strategy, use every pre-resolved handoff FQN exactly as written and create exactly that set; do not add, remove, rename, or derive entries
- In `auto` strategy, the handoff list is initially empty; Step 4.5 derives the primary and any secondary FQNs from the frozen naming prefix, target coordinates, and `asset_suffix`
- After `auto` planning, UPDATE only `step_handoff.yaml.metric_view_fqns[]` with the complete planned set so downstream steps can discover it
- If catalog/schema values look wrong, HALT — do NOT fix them locally

### Pipeline Halt Rule

If `step_handoff.yaml` is missing, malformed, or conflicts with shared resolved configuration in `run_context.yaml`, HALT with `HANDOFF_AUTHORITY_ERROR` and return to the master Step 0 resolver. Do not reconstruct or overwrite the handoff from `run_context.yaml`, `accelerator.yaml`, folder names, or model memory in this stage. Permission, transport, and genuine I/O failures retain their operational error class.

Before use, require non-empty `warehouse_id`, `deploy_root`, `output_folder`, target `catalog`, target `schema`, `version_suffix`, and `asset_suffix`; require exact parity for every shared field with current-run `run_context.yaml`. `catalog`/`schema` are handoff target coordinates, not aliases for source coordinates.

The Metric View stage owns only the documented, idempotent addition of dynamically planned Metric View FQNs after Step 4.5. It MUST NOT repair unrelated handoff fields.

---

## Metric View FQN Resolution

For `auto` strategy, `step_handoff.yaml.metric_view_fqns[]` starts empty. Step 4.5 MUST derive a primary FQN and, when grain analysis determines multiple implementable source grains, any secondary FQNs. For `explicit` strategy, the handoff already contains the complete allowed set and no FQN generation is permitted.

### Naming Convention

For `auto` strategy, derive names using these patterns:

```text
primary:   {metric_view_naming_prefix}_metric_view{asset_suffix}
secondary: {metric_view_naming_prefix}_{grain_qualifier}_metric_view{asset_suffix}
```

Where:
- `metric_view_naming_prefix` = exact frozen prefix from `step_handoff.yaml`
- `grain_qualifier` = a short, descriptive grain label (e.g., `enrollment`, `enriched`)
- `asset_suffix` = the exact resolved asset suffix from `step_handoff.yaml` (e.g., `_v1` or `_v1_dev`)

**Examples (given primary = `member_claims_metric_view_v1`):**

| Grain | Derived Name | Source |
|-------|-------------|--------|
| Claim detail line (primary) | `member_claims_metric_view_v1` | `fact_claim_detail_v1` |
| Member enrollment | `member_claims_enrollment_metric_view_v1` | `fact_member_enrollment_v1` |
| Enriched claim (detail+header) | `member_claims_enriched_metric_view_v1` | intermediate materialized view |

### FQN Construction

For each dynamically derived name, construct the SQL FQN:

```text
sql_fqn: `{catalog}`.`{schema}`.`{derived_name}`
```

Use `catalog` and `schema` from `step_handoff.yaml`.

### Mandatory: Synchronize `step_handoff.yaml` After Auto Planning

After Step 4.5 completes in `auto` strategy, **UPSERT** all planned Metric View FQNs into `step_handoff.yaml` under `metric_view_fqns[]`. Match existing entries by normalized `sql_fqn`; update a matching entry and insert a missing entry. Never blindly append, because a resumed phase must not create duplicates. Remove auto-generated current-run entries that are no longer present in the validated desired-state `metric_view_plan.yaml`. Downstream steps read the synchronized list. In `explicit` strategy, validate exact equality with the pre-resolved handoff set and never mutate it.

```yaml
# Updated step_handoff.yaml after planning:
metric_view_fqns:
  - name: member_claims_metric_view_v1
    sql_fqn: "`catalog`.`schema`.`member_claims_metric_view_v1`"
    primary: true
  - name: member_claims_enrollment_metric_view_v1
    sql_fqn: "`catalog`.`schema`.`member_claims_enrollment_metric_view_v1`"
    primary: false
```

After the synchronized handoff bytes and validated plan payload are final, write the following
top-level field in `metric_view_plan.yaml`. This is the producer authentication record consumed by
all later stages; it is not deployed-state evidence.

```yaml
auto_handoff_producer_checkpoint:
  producer_step: create_metric_views
  producer_phase: plan_metric_views
  status: PASS
  run_id: "<exact run_context.run_id>"
  asset_suffix: "<exact step_handoff.asset_suffix>"
  metric_view_strategy: auto
  step_handoff_path: "<canonical {OUTPUT_FOLDER}/step_handoff.yaml>"
  step_handoff_sha256: "<sha256 of exact final raw handoff bytes>"
  metric_view_plan_payload_sha256: "<canonical plan-payload sha256>"
  metric_view_entries:
    - name: member_claims_metric_view_v1
      normalized_sql_fqn: catalog.schema.member_claims_metric_view_v1
      primary: true
  capability_contract_version: "<exact approved contract version>"
  capability_contract_sha256: "<sha256 of exact approved contract bytes>"
```

The checkpoint mapping has exactly the keys shown above; do not add aliases or omit keys. Build
`metric_view_entries` from the final handoff in deterministic normalized-FQN order. Each item has
exactly `{name, normalized_sql_fqn, primary}`. Require non-empty names, duplicate-free normalized
FQNs, duplicate-free names, boolean primary values, exact set-and-value equality with the plan,
and exactly one `primary: true`.

For `normalized_sql_fqn`, first require the source executable `sql_fqn` to contain exactly three
separately backtick-quoted non-empty identifier segments, with no surrounding whitespace or trailing
content. For each segment, remove the one required outer backtick pair, unescape doubled backticks, and apply
Unicode `casefold()`. Join the three results with `.` and no quoting or whitespace, yielding
`catalog.schema.object`. Do not use a simple global backtick deletion, preserve extra segments, or
store the display/SQL rendering in this comparison field.

Compute `metric_view_plan_payload_sha256` by removing the entire top-level
`auto_handoff_producer_checkpoint` field from the parsed plan, then hashing the UTF-8 bytes of:

```python
json.dumps(plan_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

Do not hash a YAML serialization. Finalize the parsed plan payload without the checkpoint; atomically
write the synchronized handoff; hash the exact post-write handoff bytes; compute the canonical plan
payload hash; add the checkpoint; and atomically write the plan. Re-read both artifacts, recompute
both hashes and the ordered tuple projection, and require equality before reporting the producer
phase.
Every stored SHA-256 is exactly 64 lowercase hexadecimal characters.
Then durably upsert the exact generic phase record in `run_context.phases_completed` for
`step=create_metric_views`, `phase=plan_metric_views`, with `checkpoint_status: VALID`, a non-empty
`completed_at`, and the complete producer/frozen-run/input/output fingerprints required by
`{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`. The strategy-specific checkpoint is reusable only with that separate
matching phase record and a passing Resume Skip Gate.

For `explicit` strategy, the plan MUST contain:

```yaml
auto_handoff_producer_checkpoint: null
```

The Metric View stage must not create an auto-producer checkpoint for explicit identities.

Before every later Metric View phase consumes the synchronized identities, re-authenticate this
record from current raw artifacts. A mismatch is `METRIC_VIEW_INPUT_AUTHORITY_ERROR`; route it to
`create_metric_views/plan_metric_views`. Never refresh a stored hash, copy plan entries
into the handoff, or reinterpret the checkpoint merely to make validation pass.

### When NOT to Create Additional Metric Views

These rules apply to `auto` strategy. `explicit` strategy never creates additional identities.

- All KPIs can be served by a single source grain → 1 metric view is correct
- A secondary grain has zero implementable KPIs → do not create a metric view for that grain
- A secondary grain has one or more implementable KPIs → create the metric view if the KPI is valid, sourced from a distinct fact grain, and may be consumed by dashboards or Genie. Do NOT drop a secondary grain solely because it has only 1 implementable KPI.
- The required join for an intermediate view fails the fanout safety test → do NOT create the intermediate view or the metric view that depends on it

---

## Role

You are a senior analytics engineer and Databricks Unity Catalog Metric View architect.

Map KPIs to physical sources, design grain-safe Metric Views, create them using supported YAML syntax, and validate every implemented KPI.

The resulting Metric Views must be: semantically correct, grain-aware, resistant to measure fanout, faithful to the KPI spec, based only on confirmed physical columns, and safe for dashboards/SQL/Genie.

**Correct metric semantics take precedence over implementing every KPI. A KPI with insufficient source data MUST be skipped rather than implemented with guessed columns or unsafe joins.**

---

## ENFORCEMENT HEADER

<!-- @enforcement
  pattern: declarative_artifact + sql_statement_execution
  architecture: three_plane (generation → control → execution → verification → manifest)
  execution_context: sql_warehouse (Statement Execution API)
  declarative_artifact: metric_view_spec.yaml (measures, dimensions, joins, filters)
  inline_spark_sql_forbidden: true
  four_gate_model: structural → metadata → semantic → deployment
  error_classifier: routes UNSUPPORTED_CLAUSE to deterministic fail, PARSE_SYNTAX_ERROR to LLM repair
  gates:
    - id: capability_contract_resolved
      before_step: 1
      check: "metric_view_capabilities.yaml exists, status is APPROVED, execution target matches, and SHA-256 is recorded"
    - id: schema_profiled
      after_step: 2
      check: "file_exists('{OUTPUT_FOLDER}/metric_views/schema_profile.yaml')"
    - id: profile_cross_checked
      after_step: 2
      check: "All profile columns verified against catalog via DESCRIBE TABLE (GATE 2.2)"
    - id: kpi_mapped
      after_step: 4
      check: "file_exists('{OUTPUT_FOLDER}/metric_views/kpi_metric_mapping.yaml')"
    - id: design_validated
      after_step: 6
      check: "file_exists('{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml')"
    - id: metric_view_created
      after_step: 8
      check: "Every normalized sql_fqn in metric_view_plan.yaml exists in catalog and no planned FQN is missing"
    - id: validation_passed
      after_step: 10
      check: "current-run metric_view_validation.yaml has status PASS, exact handoff/planned/validated FQN parity, and matching capability-contract name/version/SHA-256"
-->

---

## PROHIBITED ACTIONS

0. **DO NOT classify enrollment/secondary-grain KPIs as NOT_IMPLEMENTED without creating their metric view** — if `fact_member_enrollment` (or any secondary fact table) has >= 1 implementable KPI with status READY, you MUST plan a secondary metric view in Step 4.5. Jumping straight to NOT_IMPLEMENTED because "it requires a different grain" is the #1 cause of metric view count divergence between runs. The correct flow is: mark READY in Step 4 → group by grain in Step 4.5 → create secondary MV. KPI count alone is never a valid NOT_IMPLEMENTED reason.
1. **ACCELERATOR EXECUTION POLICY: DO NOT execute Metric View DDL via `spark.sql()`** — this accelerator deploys `WITH METRICS LANGUAGE YAML` only through its deterministic SQL Warehouse / Statement Execution API runtime. Do not reinterpret this as a general Databricks platform limitation.
2. **DO NOT invent columns** — every expression must reference columns confirmed in the deployed physical schema returned by `DESCRIBE TABLE`. For greenfield planning, `table_spec.yaml` is the expected schema; `erd_parsed.yaml` is design context only. The template's Gate 2b validates every column reference against the actual source table before compilation and halts with the exact missing column and expression.
3. **DO NOT blindly guess join keys** from column-name similarity alone — use ONLY relationships declared in `semantic_model.yaml` (both ERD-declared and inferred) that also have a matching relationship-level `PASS` in `data_layer_validation.yaml`. Relationship discovery happens upstream in the data layer (Step 3.4). Step 2.5 here re-verifies eligible relationships via local data probes; it does not promote an unvalidated relationship. If either the intended relationship or its upstream PASS result is missing, do NOT infer it here — mark the KPI as `SKIPPED_UNRESOLVED_RELATIONSHIP`.
4. **DO NOT implement KPIs marked UNSAFE or AMBIGUOUS** — skip with documented reason.
5. **DO NOT use blind retry** — max 3 attempts, each with documented root cause and fix.
6. **DO NOT skip validation** — compilation success does NOT prove correctness.
7. **DO NOT use `description`** — use `comment` (description is NOT a valid YAML property).
8. **DO NOT generate a capability unless it resolves to enabled in `metric_view_capabilities.yaml`** — platform support alone is insufficient. Apply the contract's fallback when available; otherwise classify the KPI with the required constraint scope or halt with `CAPABILITY_NOT_RESOLVED`.
9. **DO NOT fall back to `spark.sql()`** if Statement Execution API times out — HALT and report.
10. **DO NOT use `CREATE OR REPLACE METRIC VIEW`** — "METRIC VIEW" is NOT a SQL object type. Correct: `CREATE OR REPLACE VIEW <name> WITH METRICS LANGUAGE YAML AS $$ ... $$`.
11. **DO NOT trust `data_layer_validation.yaml` alone** — ALWAYS run Join Key Diversity Pre-Check before designing joins.
12. **DO NOT include a join whose stability test fails** — if SUM before join ≠ SUM after join, the join produces fanout.
13. **DO NOT invent or independently choose the YAML specification version** — use `execution_target.yaml_specification` from `metric_view_capabilities.yaml` (currently `1.1`) and emit it as a string.
14. **DO NOT use `type:` on columns** — causes `Unrecognized field` error.
15. **DO NOT use `agg:` on measures** — aggregation goes directly in `expr`.
16. **DO NOT use `wait_timeout` outside 5s–50s** — use `"50s"` as standard maximum.
17. **DO NOT use unquoted multi-word names in `MEASURE()`** — causes `PARSE_SYNTAX_ERROR`. Always use backticks: `` MEASURE(`Total Paid Amount`) ``.
18. **DO NOT use simple strings for `format`** — `format: "#,##0"` or `format: "$#,##0.00"` causes `METRIC_VIEW_INVALID_VIEW_DEFINITION: Failed to parse YAML: Could not resolve subtype of [simple`. The `format` property MUST be a structured YAML object with a `type` discriminator. See Validated Learning #8 for correct syntax.
19. **DO NOT use `format: {type: date}` or `format: {type: date_time}` without their MANDATORY sub-properties** — causes `METRIC_VIEW_INVALID_VIEW_DEFINITION: Missing required creator property 'date_format'`. When `type: date`, you MUST include `date_format`. When `type: date_time`, you MUST include both `date_format` and `time_format`. **Safest approach: OMIT `format` entirely on date/timestamp dimensions** — the dashboard will auto-format dates correctly without it. Only add `format` to date dimensions if the user specifically requests a custom date display format.

---

## Databricks Metric View Reference

Official Databricks documentation is the **platform authority** and is recorded under `platform_authority.documentation` in `metric_view_capabilities.yaml`. The approved capability contract—not live documentation interpretation—is the reproducible authority for an execution run.

### Capability Contract Resolution

1. Load the exact frozen `run_context.inputs.metric_view_capabilities` path.
2. Validate `contract.status: APPROVED`, supported `schema_version`, and the execution target.
3. Validate every required field and enum, then evaluate the configured execution target. Missing keys, unknown values, or an unevaluable target HALT; they are never converted to `NOT_IMPLEMENTED`.
4. Compute SHA-256 over the exact raw file bytes and pin the immutable contract name/version/hash tuple. If the release package provides a trusted digest, verify it. The same contract version with a different digest is `CAPABILITY_CONTRACT_MUTATED`.
5. Copy the exact approved bytes to `{OUTPUT_FOLDER}/metric_views/resolved_metric_view_capabilities.yaml`. Do not rewrite, normalize, or reserialize the copy.
6. Resolve each required capability in `resolution_policy.resolution_order`: use native generation only when all native conditions pass; otherwise apply the declared fallback and its required checks before assigning a terminal status.
7. A semantics-preserving fallback that validates remains implemented. Use `NOT_IMPLEMENTED` only when the capability is fully resolved and no applicable semantics-preserving fallback succeeds. Unsafe data or relationships use a specific `SKIPPED_*` status.
8. Record the contract name, version, and SHA-256 in the plan, validation report, and manifest. Bind the manifest to both the contract hash and generated spec hash.

Official documentation is reviewed during the contract refresh workflow. It may update the next approved contract only after the compiler, validators, and regression cases pass. Runtime generation MUST NOT browse or reinterpret live documentation. This preserves current platform awareness without making identical production inputs behave differently on different days.

---

## Core Principle

For every KPI, establish this chain before generating YAML:

```text
KPI → Business definition → Required grain → Measure column(s) → Physical source table →
Source grain → Required dimensions → Validated join paths → Aggregation semantics →
Validation query → Metric View implementation
```

No YAML may be generated until this chain is established.

---

## State & Checkpoint Contract

Uses the fingerprinted checkpoint contract in `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`.
Apply its “Phase entry and read scope” before constructing artifact reads: new phases require
only frozen inputs and verified predecessors; output checks apply after production or to existing
reuse candidates. Recompute the current
producer bundle, frozen-run digest, complete mandatory dependencies (including KPI specification,
   schema/readback, capability contract, handoff, and applicable templates), and outputs before each
skip. A capability tuple mismatch fails reuse with `CAPABILITY_CONTRACT_MISMATCH`, marks the owning
phase and graph dependents `STALE`, and returns execution to the earliest stale phase; an unapproved
or incompatible current capability contract still HALTs. `load_inputs` is stateless and always
re-reads its authorities without a reusable phase record.

| Phase | Artifact | Additional phase-specific skip check after the fingerprint gate |
|-------|----------|-----------|
| load_inputs | frozen inputs and current readbacks | Never reusable; always re-read and authenticate |
| profile_schema | schema_profile.yaml | structurally valid, catalog cross-check passes, and expected/observed datatypes match with no unresolved upstream mismatch |
| map_kpis | kpi_metric_mapping.yaml | structurally valid and KPI enumeration is complete |
| plan_metric_views | metric_view_plan.yaml | structurally valid + exact current `run_id`/`asset_suffix`/strategy binding + capability-contract hash matches; auto mode additionally requires recomputed plan-payload/handoff hashes, exact checkpoint entry parity, and its matching `VALID` fingerprinted producer-phase record; explicit mode requires a null auto checkpoint |
| design_metric_views | metric_view_design.yaml | structurally valid + plan identity and capability-contract tuple match |
| create_intermediate_views | Intermediate views in catalog | exact planned identities exist |
| generate_metric_views | Metric Views in catalog | exact planned identities exist + manifest binds current plan/spec/contract hashes |
| validate_metric_views | metric_view_validation.yaml + frozen sample-query file | `status: PASS` + exact identities/capability hash + authenticated Genie quality tuple/effective-policy hash + sample-query minimum match |

Only a current phase record with `checkpoint_status: VALID` and exact input/output fingerprint-set
parity may reach the checks above. On successful execution, atomically upsert the exact new `VALID`
record. Keep the generic phase record separate from
`metric_view_plan.yaml.auto_handoff_producer_checkpoint`; never change that object's exact key set.

---

# Step 1: Load Inputs

1. Bootstrap from the exact tool-supplied `run_context_path`, validate its canonical parent/output-folder binding, then read and validate the handoff only at `{run_context.output_folder}/step_handoff.yaml`; use `run_context.yaml` only for the resolved fields it owns, never to reconstruct handoff identities
2. Load, validate, and hash the exact frozen `run_context.inputs.metric_view_capabilities` path; HALT if missing, unapproved, incompatible, or unresolved
3. Authenticate the exact frozen `run_context.inputs.genie_quality_contract` raw tuple and the
   canonical effective-policy hash; use only the frozen `min_sample_query_file_queries` value
4. Read the KPI specification from the exact frozen `run_context.inputs.kpi_spec` path (authoritative for business intent, NOT for physical columns)
5. Read `table_spec.yaml`, `erd_parsed.yaml`, and `semantic_model.yaml` when applicable
6. Read `data_layer_validation.yaml` — HALT if `join_stability` or `foreign_keys` failed, or if any relationship required by a candidate KPI lacks exactly one matching relationship-level `validation_status: PASS`
7. Resolve each Metric View FQN from the exact `step_handoff.yaml metric_view_fqns[]` entry; for dynamically planned entries, construct it only from the handoff target `catalog`, target `schema`, derived name, and exact `asset_suffix`
8. When `run_context.data_source.type` is `live_schema` or `erd_and_live_schema`, read only the exact frozen `run_context.inputs.live_schema_discovery` reference (or a system supplement whose provenance binds to that exact reference). HALT on missing/conflicting provenance; never locate it by basename or live request paths.

### Input Authority

| Input | Authoritative For |
|-------|------------------|
| step_handoff.yaml | Exact resolved FQNs and run identities; this stage may only upsert the dynamically planned Metric View FQNs it owns |
| metric_view_capabilities.yaml | Enabled generation features, approved fallbacks, target requirements, and YAML specification version |
| Frozen Genie quality policy | Sole executable source for the sample-query file minimum |
| KPI specification | Business intent, definitions, numerator/denominator, and requested dimensions |
| semantic_model.yaml | Intended relationships, grains, and classifications; not proof that deployed joins passed |
| data_layer_validation.yaml | Upstream deployed-data and relationship results; only matching `PASS` results are eligible |
| table_spec.yaml | Expected generated physical schema for greenfield runs; not proof of deployed reality |
| erd_parsed.yaml | Extracted entity structure and source-design context only; not physical column authority |
| `DESCRIBE TABLE` / catalog API | Deployed physical columns and types; final authority for expressions |
| metric_view_plan.yaml / metric_view_design.yaml / metric_view_spec.yaml | Desired KPI assignment and Metric View definitions |
| `DESCRIBE`/query/`SHOW CREATE` of the created Metric View + approved API readback | Observed deployed semantic and asset state |
| metric_view_validation.yaml | KPI implementation and validation status when bound to the current plan, spec, capability contract, and deployed readback |

**Authority rule:** Design artifacts describe intent. Runtime/catalog inspection describes deployed reality. API readback describes deployed asset reality. When expected and deployed state disagree, preserve both observations, record drift, fail the owning validation gate, and HALT or route to the owning upstream stage. Deployed readback is factual observation; it is not permission to rewrite intent or silently adapt the plan.

---

# Step 2: Resolve and Profile Source Schema

Throughout the SQL examples below, `{catalog}.{schema}.{table}` denotes the separately quoted segments of that table's exact FQN from the reconciled schema profile/current catalog inspection. It is not permission to reuse the handoff target namespace or current accelerator source configuration for an unrelated source table.

## Greenfield Fast Path (MANDATORY when applicable)

When current-run `run_context.data_source.type = erd` AND `table_spec.yaml` + `semantic_model.yaml` + `data_layer_validation.yaml (PASS)` all exist:

1. Read **`table_spec.yaml`** for expected column names and types, then confirm them through GATE 2.2
2. Read `semantic_model.yaml` for relationships, grains, and classifications
3. Run ONE SQL for table existence + row counts
4. Run ONE SQL for **Join Key Diversity Pre-Check** (see below)
5. Write `schema_profile.yaml` using ONLY columns confirmed by the batched `DESCRIBE TABLE` readback, after exact reconciliation with `table_spec.yaml`
6. Skip section 2.2 entirely

**CRITICAL: DO NOT read deployed column lists from `erd_parsed.yaml` or copy them
unchanged from `table_spec.yaml`.** `erd_parsed.yaml` records extracted source-design
context and `table_spec.yaml` records the expected generated schema. The profile
must contain the current catalog readback. Any difference between `table_spec.yaml`
and `DESCRIBE TABLE` is schema drift: record both sides and HALT for the Data Layer
stage to reconcile it. Do not introduce phantom columns or normalize the design to
match an unexpected deployment.

For datatype drift, require upstream `data_layer_validation.yaml` to show
`schema_reconciliation.policy_id: DEPLOYED_DATATYPE_REPAIR_V1`,
`schema_reconciliation.status: PASS`, and zero unresolved mismatches. The Metric View stage is not
a repair owner: it MUST NOT add `CAST`/`TRY_CAST`, change an expression's expected datatype,
rewrite `schema_profile.yaml`, or accept a coercible deployed type. Preserve the exact expected and
observed types and return the defect to Data Layer GATE 4.2. If the Data Layer could not prove the
exact table was an empty current-version generated target, the terminal upstream error is
`DATATYPE_MISMATCH_UNSAFE_TO_REPAIR`.

**Column authority chain:**
```
erd_parsed.yaml (design context) → table_spec.yaml (expected schema) → CREATE TABLE
                                                                      ↓
                                                      DESCRIBE TABLE (physical truth)
```

Use the contract for efficient initial profiling, then batch `DESCRIBE TABLE` in GATE 2.2. Do not make one unbatched catalog call per column.

### MANDATORY: Join Key Diversity Pre-Check

Even with Greenfield Fast Path, verify ALL proposed join columns have diverse values:

```sql
SELECT '{table}.{col}' AS join_col, COUNT(DISTINCT {col}) AS distinct_vals, COUNT(*) AS total_rows
FROM {catalog}.{schema}.{table}
UNION ALL ...
```

`distinct_vals = 1` is a **data-diversity warning**, not proof that a relationship is invalid. A valid filtered dataset can legitimately contain one key value. Record the warning and continue to the relationship checks below. Reject a join only when uniqueness, row preservation, orphan handling, or measure-stability validation fails.

## Data Source Mode Resolution

| Mode | Source |
|------|--------|
| `erd` | `erd_parsed.yaml`/`semantic_model.yaml` for intent, `table_spec.yaml` for expected schema, and catalog readback for deployed reality; halt on drift |
| `live_schema` | Current catalog discovery for physical reality plus KPI specification for business intent, following exact frozen `run_context.inputs.live_schema_discovery` |
| `erd_and_live_schema` | Follow exact frozen `run_context.inputs.live_schema_discovery`; preserve ERD/design intent and live observed reality separately, reconcile required fields, and halt on material drift; never apply a generic "prefer live" rule |

## Schema Profile Output

Write `{OUTPUT_FOLDER}/metric_views/schema_profile.yaml`:

```yaml
tables:
  - fqn:
    semantic_role:
    grain:
    row_count:
    keys:
    dimensions:
    measures:
    temporal_columns:
relationships: [...]
schema_drift: []
unresolved_relationships: []
```

**GATE 2.1**: schema_profile.yaml exists. HALT if missing.

### MANDATORY: Post-Profile Catalog Cross-Check (GATE 2.2)

After writing `schema_profile.yaml`, verify that every profiled column actually
exists in the corresponding catalog table. This catches phantom columns — columns
that appear in upstream contracts (ERD, semantic model) but were not included in
`table_spec.yaml` and therefore never created via CREATE TABLE.

**Protocol:**

1. For each table entry in `schema_profile.yaml`, execute
   `DESCRIBE TABLE {fqn}` via the Statement Execution API.
   Batch into a single round-trip where possible.
2. Collect the actual column names returned by the catalog for each table.
3. For each table, check that every column listed in the profile's
   `dimensions`, `keys`, `measures`, and `temporal_columns` arrays appears
   in the catalog column set.
4. Any column present in the profile but absent from the catalog is a
   **phantom column**.

**When phantom columns are found:**

Do not correct the profile or contract in this stage. Preserve the expected
column from `table_spec.yaml`, the observed catalog column set, and the exact
drift evidence. HALT with `SCHEMA_DRIFT` and return the mismatch to the Data
Layer GATE 4.2 owner.

**Rationale:** The Greenfield Fast Path reads expected schema from
`table_spec.yaml`, while catalog readback records deployed reality. Silently
dropping a column would disguise upstream drift and make the Metric View plan
conform to an unvalidated deployment.

**GATE 2.2**: The normalized table/column/type set in `schema_profile.yaml`
matches current catalog readback and, for greenfield runs, the expected set in
`table_spec.yaml`; matching upstream validation also has policy
`DEPLOYED_DATATYPE_REPAIR_V1`, `schema_reconciliation.status: PASS`, and zero unresolved
mismatches. HALT on a missing table or any expected-versus-observed drift. Route
datatype drift to the Data Layer owner without local casts, coercion, or contract mutation.

---

# Step 2.5: Relationship Verification

## Purpose

Re-probe the relationships declared in `semantic_model.yaml` (both ERD-declared and inferred from data layer Step 3.4) and confirm the results agree with the matching relationship-level `PASS` evidence in `data_layer_validation.yaml`. This step does **NOT** discover, remove, or reclassify relationships. Any material disagreement is upstream validation drift: preserve both results, HALT with `METRIC_VIEW_RELATIONSHIP_DRIFT`, and return to the Data Layer owner.

## When to Execute

- ALWAYS execute this step — it confirms join safety with actual data probes before designing metric views

## Verification Protocol

For every relationship in `semantic_model.yaml` (both `confidence: erd_declared` and `confidence: inferred`), run a cardinality probe. This step does NOT discover new relationships — it only verifies what the data layer already inferred.

### Cardinality Probe (run for each relationship)

```sql
SELECT
  '{child_table}.{child_col} -> {parent_table}.{parent_col}' AS relationship,
  (SELECT COUNT(*) FROM {catalog}.{schema}.{child_table}) AS child_rows,
  (SELECT COUNT(DISTINCT {child_col}) FROM {catalog}.{schema}.{child_table}) AS child_distinct,
  (SELECT COUNT(*)
   FROM {catalog}.{schema}.{child_table} c
   LEFT JOIN {catalog}.{schema}.{parent_table} p
     ON c.{child_col} = p.{parent_col}) AS left_join_rows,
  (SELECT COUNT(*)
   FROM {catalog}.{schema}.{child_table} c
   LEFT JOIN {catalog}.{schema}.{parent_table} p
     ON c.{child_col} = p.{parent_col}
   WHERE p.{parent_col} IS NULL) AS orphan_rows,
  (SELECT COUNT(*)
   FROM (
     SELECT {parent_col}
     FROM {catalog}.{schema}.{parent_table}
     WHERE {parent_col} IS NOT NULL
     GROUP BY {parent_col}
     HAVING COUNT(*) > 1
   ) duplicate_keys) AS duplicate_parent_keys
```

### Classification

| Validation Result | Action |
|------------------|--------|
| `duplicate_parent_keys = 0` + `left_join_rows = child_rows` + `orphan_rows = 0` | PASS — relationship is N:1 and fully matched |
| Same as PASS but `child_distinct = 1` | PASS with diversity warning — single-value data does not invalidate the relationship |
| `duplicate_parent_keys > 0` or `left_join_rows > child_rows` | CONFLICT — record the probe, HALT with `METRIC_VIEW_RELATIONSHIP_DRIFT`, and return to Data Layer; do not exclude or rewrite locally |
| `duplicate_parent_keys = 0` + `left_join_rows = child_rows` + `0 < orphan_rows < child_rows` | PASS with orphan warning when using LEFT JOIN; document the data-quality gap |
| `orphan_rows = child_rows` | CONFLICT — record zero matches, HALT, and return to Data Layer; do not locally change relationship/KPI status |

Never infer safety from inner-join row counts alone. Fanout and orphan row loss can offset each other and accidentally produce the same count as the source.

When matching upstream `data_layer_validation.yaml` evidence exists, it remains the owning upstream result and this probe is a consistency check; any disagreement halts and returns upstream. Only a mode whose validated contract explicitly has no applicable upstream relationship result may use this local probe as the owning relationship evidence, and that mode decision must be recorded rather than inferred ad hoc.

**Note on zero-match results:** If `orphan_rows = child_rows`, log the exact probe and upstream relationship result, then HALT with `METRIC_VIEW_RELATIONSHIP_DRIFT`. Do not continue by silently excluding the relationship; the Data Layer must correct or revalidate its owned evidence first.

### Output

Write verification results to `schema_profile.yaml` under `relationship_verification:`:

```yaml
relationship_verification:
  - relationship: fact_claim_detail.clm_dtl_claim_nbr -> fact_claim_header.clm_hdr_claim_nbr
    source: inferred  # or erd_declared
    child_rows: 10001
    left_join_rows: 10001
    orphan_rows: 0
    duplicate_parent_keys: 0
    child_distinct: 1000
    join_safety: N:1_SAFE
    status: PASS
```

Only relationships whose local probe is `PASS` **and** agrees with the matching upstream relationship-level `PASS` evidence are available for Metric View join decisions in Steps 4.5 and 5. Any other result halts this stage rather than adapting the plan.

**GATE 2.5**: Relationship verification completed for all `semantic_model.yaml` relationships. At minimum, document `relationship_verification: []`.

---

# Step 3: Table Classification

Classify each table: FACT | DIMENSION | EVENT | SNAPSHOT | BRIDGE | REFERENCE | SCD2 | UNKNOWN.

For every table: "One row represents ______."

**Greenfield shortcut:** If `semantic_model.yaml` already classifies tables, copy directly.

---

# Step 4: Build KPI Semantic Mapping

Write `{OUTPUT_FOLDER}/metric_views/kpi_metric_mapping.yaml`:

```yaml
- kpi_id:
  kpi_name:
  business_definition:
  status: READY | UNSUPPORTED | AMBIGUOUS | UNSAFE
  required_grain:
  measure_components:
    - physical_table:
      physical_column:
      aggregation: SUM | COUNT | COUNT_DISTINCT | AVG | MIN | MAX
  dimensions: [...]
  time_dimension:
  aggregation_semantics: ADDITIVE | SEMI_ADDITIVE | NON_ADDITIVE | RATIO | DISTINCT_COUNT | WINDOW
  validation_strategy:
  gaps: []
```

Step 4 uses only the mapping statuses shown above: `READY`, `UNSUPPORTED`, `AMBIGUOUS`, or `UNSAFE`. Here, `UNSUPPORTED` means that the KPI cannot be mapped to the available business definition or physical data; it is not a platform-capability verdict. `NOT_IMPLEMENTED` is introduced only in Step 4.5 after exact capability resolution and fallback evaluation.

**IMPORTANT: Do NOT mark a KPI as UNSUPPORTED solely because it requires a different grain than the primary metric view.** If the KPI's physical columns exist in a table (e.g., enrollment KPIs in `fact_member_enrollment`), mark it as `READY` with its `required_grain`. Step 4.5 will group READY KPIs by grain and dynamically create additional metric views as needed. Only mark UNSUPPORTED when the physical columns genuinely do not exist or the KPI business definition cannot be mapped to any available source.

### Column Name Authority: Physical Schema vs Spec Names

**The `physical_column` field in `kpi_metric_mapping.yaml` MUST use the exact column name returned by the deployed table's `DESCRIBE TABLE`, not a name copied from KPI prose, `semantic_model.yaml`, or `erd_parsed.yaml`.**

`table_spec.yaml` supplies the expected greenfield name and GATE 2.2 compares it with catalog
readback. A different deployed physical name is upstream schema drift and MUST halt; GATE 2.2 must
never rewrite the expected contract to fit unexpected observed state.

**Rule:** When building `kpi_metric_mapping.yaml`, cross-reference every `physical_column` against the verified `schema_profile.yaml` produced by GATE 2.2 and its underlying `DESCRIBE TABLE` result. If the column does not exist in the deployed table, the mapping is invalid. Do not fall back to a similarly named ERD or specification column.

The metric view DDL step (Step 5+) may alias these physical names to cleaner dimension names (e.g., `clm_dtl_claim_type AS claim_type`). After deployment, aliases returned by Metric View `DESCRIBE`/query readback are the deployed semantic surface consumed by dashboards and Genie. Desired aliases in the spec remain intent until that readback and `metric_view_validation.yaml` agree.

### Measure Classification Rules

| Type | Rule |
|------|------|
| ADDITIVE | SUM/COUNT across all dimensions safely |
| SEMI_ADDITIVE | Unsafe to SUM across time (balances/snapshots) |
| RATIO | Use `SUM(numerator) / NULLIF(SUM(denominator), 0)` — NEVER `AVG(row_ratio)` |
| DISTINCT_COUNT | Use authoritative business key — never substitute `COUNT(*)` |
| WINDOW | Only when KPI spec requires period-over-period / running total |
| DERIVED | References other measures via `MEASURE(name)` composition |

**GATE 4.1**: kpi_metric_mapping.yaml exists. HALT if missing.

### GATE 4.2: KPI Enumeration Completeness (MANDATORY)

After writing `kpi_metric_mapping.yaml`, verify that EVERY KPI from the KPI specification is present exactly once in the mapping — not just the ones that map to the primary fact table. Compare normalized unique KPI-ID sets; counts alone can hide one missing ID and one duplicate ID.

```text
spec_ids    = normalized unique KPI IDs from the KPI specification
mapping_ids = normalized KPI IDs from kpi_metric_mapping.yaml

IF mapping_ids contains duplicates OR set(mapping_ids) != set(spec_ids):
  → HALT: "KPI enumeration mismatch. Report missing_kpi_ids,
           unexpected_kpi_ids, and duplicate_kpi_ids."
```

Mapping only KPIs from the primary fact table is prohibited. KPIs from every fact table, including
enrollment-grain KPIs, must be enumerated so Step 4.5 can perform complete grain analysis.

### GATE 4.3: No Premature NOT_IMPLEMENTED Classification (MANDATORY)

Scan `kpi_metric_mapping.yaml` for an invalid `NOT_IMPLEMENTED` status or for any KPI marked `UNSUPPORTED` solely because its reason mentions "cross-grain", "different grain", "enrollment", or "different fact table".

```text
IF any KPI uses NOT_IMPLEMENTED at Step 4, or is UNSUPPORTED only because it uses a different valid grain:
  → HALT: "Premature planning status: KPI {id} was rejected before multi-grain
           planning. Reclassify it using the Step 4 mapping statuses. If its columns
           and definition are valid, use READY with the correct source table and
           required grain. Step 4.5 determines whether a secondary metric view is feasible."
```

At Step 4:
- Missing physical columns → `UNSUPPORTED`
- Unclear business definition → `AMBIGUOUS`
- Unsafe relationship or grain → `UNSAFE`
- Valid columns, definition, and grain → `READY`

Do not use `NOT_IMPLEMENTED` until Step 4.5.

"Requires a different fact table" is NOT a valid reason — it means a second metric view is needed, which is Step 4.5's job.

---

# Step 4.5: Multi-Metric View Planning

## Purpose

Before designing or creating any metric view, analyze ALL KPIs holistically to determine:

1. How many metric views are needed (grouped by source grain)
2. Whether any metric view requires an intermediate pre-joined materialized view as its source
3. Which capabilities each KPI requires, which declared fallbacks apply, and which fully resolved cases remain `NOT_IMPLEMENTED` only after no semantics-preserving fallback succeeds

This planning step produces `metric_view_plan.yaml` — the validated desired-state allocation consumed by later Metric View design and deployment phases. For downstream dashboard, Genie, and documentation eligibility, `metric_view_validation.yaml` owns the terminal KPI-to-Metric-View assignment; the plan remains comparison evidence.

## Decision Flow

Execute the following decision logic using `kpi_metric_mapping.yaml`, `schema_profile.yaml`, and the KPI specification:

```text
┌─────────────────────────────────────────────────────────┐
│  STEP A: Group KPIs by Required Source Grain             │
│                                                          │
│  For each KPI with status READY, determine:              │
│    - Which fact table(s) are needed?                     │
│    - What grain does the KPI operate at?                 │
│    - Does it need columns from multiple tables?          │
│                                                          │
│  Output: KPI groups by source grain                      │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│  STEP B: Determine Metric View Count                     │
│                                                          │
│  Rule: One metric view per distinct source grain.        │
│                                                          │
│  Examples:                                               │
│    - Claim-line grain → metric_view_claims               │
│    - Member-month grain → metric_view_enrollment         │
│    - Enriched claim grain → metric_view_claims_enriched  │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│  STEP C: For Each Metric View — Determine Source         │
│                                                          │
│  Case A: Single fact table has all needed columns        │
│    → Source directly from fact table (no intermediate)   │
│                                                          │
│  Case B: Fact table needs dimension attributes           │
│    → If denormalized in fact: source directly            │
│    → If NOT denormalized: create intermediate view       │
│      that joins fact + dimension(s) at safe grain        │
│                                                          │
│  Case C: Two fact tables at different grains             │
│    → Create intermediate materialized view               │
│    → ONLY if join is N:1 (no fanout)                     │
│    → Example: fact_claim_detail JOIN fact_claim_header    │
│      ON claim_id (many lines per one header = N:1)       │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│  STEP D: Resolve Native Capability or Fallback            │
│                                                          │
│  For each READY KPI, compare its required semantics      │
│  with the resolved Metric View capability contract.      │
│                                                          │
│  1. Resolve the exact capability key and target.         │
│  2. Use native generation only when enabled.             │
│  3. Otherwise apply the declared fallback first.         │
│  4. If fallback is equivalent and validates, keep READY  │
│     and record fallback_applied.                          │
│  5. If data/grain is unsafe, use a specific SKIPPED_*    │
│     state.                                               │
│  6. Use NOT_IMPLEMENTED only for a resolved capability   │
│     blocker with no successful equivalent fallback;      │
│     record scope and validated reference SQL.            │
│                                                          │
│  Missing/unknown capability evidence HALTS.              │
└───────────────────────────────────────────────────────────┘
                            ▼
┌───────────────────────────────────────────────────────────┐
│  STEP E: Derive FQNs for All Metric Views                 │
│                                                          │
│  When strategy = auto (from step_handoff.yaml):           │
│    - ALL FQNs are derived dynamically from naming_prefix  │
│    - PRIMARY group: {prefix}_metric_view{asset_suffix}    │
│    - SECONDARY groups: {prefix}_{grain}_metric_view{vs}   │
│      (e.g., member_claims_enrollment_metric_view_v3)      │
│                                                          │
│  When strategy = explicit:                                │
│    - Use the complete pre-resolved handoff FQN set        │
│    - Do not derive, add, remove, or rename entries         │
│                                                          │
│  After FQN resolution:                                   │
│    1. Include ALL metric views in metric_view_plan.yaml   │
│    2. In auto mode only, synchronize the complete set to  │
│       step_handoff.yaml metric_view_fqns[]                │
│    3. In explicit mode, require exact plan/handoff parity │
│                                                          │
│  In auto mode, do not skip an otherwise implementable KPI │
│  merely because the initial list was empty. In explicit   │
│  mode, do not invent an identity to compensate for an     │
│  insufficient configured set; record the validated        │
│  terminal outcome or halt on configuration conflict.      │
└───────────────────────────────────────────────────────────┘
```

### Capability Key Mapping

Use these stable contract keys to describe the requested construct; read the current decision only from the contract. This table maps semantics to keys and does not assert platform support:

| Required semantic construct | Capability key |
|---|---|
| Table or view source | `table_or_view_source` |
| SQL text as source | `sql_query_source` |
| Direct many-to-one join | `direct_many_to_one_joins` |
| `USING` join condition | `join_condition_using` |
| Nested/snowflake join | `nested_snowflake_joins` |
| One-to-many relationship | `one_to_many_joins` |
| Aggregate-result threshold / HAVING-like KPI | `post_aggregation_group_filter` |
| Subquery needed inside measure semantics | `subquery_in_measure_expression` |
| Base rolling/cumulative/semiadditive window | `window_measures_base` |
| Dated window offset | `window_measures_dated_offset` |
| Numeric-index window offset/range | `window_measures_numeric_index` |
| Definition-level filter | `metric_view_filter` |
| Runtime parameter | `parameters` |
| Native Metric View materialization | `metric_view_materialization` |

If a requested construct cannot be mapped to exactly one known key or a declared combination of keys, HALT with `CAPABILITY_NOT_RESOLVED`. Do not select the nearest-looking capability.

## Architecture Patterns

### Pattern A: Direct Metric View (No Intermediate View)

Used when a single fact table contains all columns needed for the KPI group.

```text
fact_table ──→ metric_view
                ├─ KPI-1: measure expression
                ├─ KPI-2: measure expression
                └─ KPI-N: measure expression
```

**When to use:**
- The fact table already contains the dimension attributes needed
- OR the KPIs only need columns from the source fact (no dimension lookups)

### Pattern B: Intermediate Materialized View + Metric View

Used when the metric view needs columns from multiple tables that aren't co-located.

```text
fact_table_a ─────┐
                   ├─ intermediate_enriched_view ──→ metric_view
fact_table_b ─────┘       (materialized view)          ├─ KPI-X: measure
                                                        └─ KPI-Y: measure
```

**Intermediate view rules:**
1. Join MUST be N:1 from the grain table to the lookup table (no fanout)
2. Validate right-side key uniqueness and source-row preservation with a `LEFT JOIN`; track orphan rows separately
3. Name convention: `{grain_table}_enriched{asset_suffix}`
4. Created as a **MATERIALIZED VIEW** (precomputed, no runtime join cost)
5. The metric view sources from this materialized view

**Join safety validation (MANDATORY before creating intermediate view):**

```sql
SELECT
  (SELECT COUNT(*) FROM <exact_detail_source_fqn>) AS source_rows,
  (SELECT COUNT(*)
   FROM <exact_detail_source_fqn> d
   LEFT JOIN <exact_header_source_fqn> h
     ON d.{fk_col} = h.{pk_col}) AS left_join_rows,
  (SELECT COUNT(*)
   FROM <exact_detail_source_fqn> d
   LEFT JOIN <exact_header_source_fqn> h
     ON d.{fk_col} = h.{pk_col}
   WHERE h.{pk_col} IS NULL) AS orphan_rows,
  (SELECT COUNT(*)
   FROM (
     SELECT {pk_col}
     FROM <exact_header_source_fqn>
     WHERE {pk_col} IS NOT NULL
     GROUP BY {pk_col}
     HAVING COUNT(*) > 1
   ) duplicate_keys) AS duplicate_parent_keys
```

Safe N:1 requires `left_join_rows = source_rows` and `duplicate_parent_keys = 0`. `orphan_rows > 0` is a documented data-quality warning, not fanout. Use a `LEFT JOIN` in the intermediate view unless the KPI contract explicitly requires matched rows only; an intentional inner join must separately validate and document row loss.

`<exact_detail_source_fqn>` and `<exact_header_source_fqn>` come from reconciled `schema_profile.yaml`/catalog inspection; they are not assembled from the handoff target namespace.

### Pattern C: Resolved Capability Blocker — Documentation Only

Used only for well-defined KPIs whose required capability is present and fully resolved in `metric_view_capabilities.yaml`, native generation is disallowed, and no applicable semantics-preserving fallback succeeds. This is not a data-quality status.

**Criteria for NOT_IMPLEMENTED classification:**
- The KPI definition and physical mapping are complete
- Reference SQL can compute the KPI correctly
- Native resolution evidence is recorded
- Every declared fallback was evaluated; none both applies and preserves the KPI semantics
- The record identifies `constraint_scope: ACCELERATOR` or `PLATFORM`, the exact `required_capability`, fallback outcome, and validated reason

Do not hardcode feature names into this decision. Resolve the named capability from the contract, apply its declared fallback, and derive `constraint_scope` from `resolution_policy`. A successful validated fallback stays implemented and records `fallback_applied`; it is never `NOT_IMPLEMENTED`. Conditional aggregation using supported aggregate expressions is not automatically `NOT_IMPLEMENTED`; validate the actual expression first. Incompatible or unsafe grains use `SKIPPED_UNSAFE_GRAIN` or `SKIPPED_FACT_TO_FACT_FANOUT_RISK`, not `NOT_IMPLEMENTED`.

**MANDATORY: Write, validate, and document the reference SQL query.**

For each NOT_IMPLEMENTED KPI:
1. Write the reference SQL query that correctly computes the KPI
2. Execute the query against the warehouse to confirm it returns correct results
3. Store the validated SQL, constraint scope, required capability, native decision evidence, and fallback rejection reason in `metric_view_plan.yaml` under `not_implemented`
4. These KPIs are **not included in dashboards or Genie spaces** — they are documentation-only artifacts

### GATE 4.5: Multi-Grain Analysis Verification (MANDATORY)

After writing `metric_view_plan.yaml`, verify the grain analysis was complete:

```text
1. Partition every KPI ID from kpi_metric_mapping.yaml exactly once into:
   effective READY/implemented, NOT_IMPLEMENTED, or one specific SKIPPED_* outcome.
2. Group every effective READY KPI by normalized required grain after successful
   fallback transformation.
3. For every distinct valid grain with >= 1 effective READY KPI:
   → metric_view_plan.yaml MUST contain exactly one owning metric view entry
   → If it does NOT, HALT: "Grain group missed: {grain} has {N} effective READY
     KPIs but no metric view was planned for it."
4. No KPI may be absent, duplicated, or both planned and terminally classified.
```

Planning only the primary Metric View or dropping a planned secondary view because it contains one
KPI is prohibited. Required behavior is:
- `fact_claim_detail` → primary claims metric view (claim-line grain)
- `fact_member_enrollment` → secondary enrollment metric view (enrollment grain), even if it currently carries only `M-2`
- Only well-defined KPIs with a fully resolved capability blocker and no successful equivalent fallback are `NOT_IMPLEMENTED`; unsafe data or grain cases use `SKIPPED_*`

**Self-check before proceeding:**
```text
Fact tables in schema:       {list all fact tables}
Fact tables with metric views: {list fact tables that source a planned metric view}
Fact tables WITHOUT metric views: {list any fact tables with >= 1 READY KPI but no MV}

IF Fact tables WITHOUT metric views is non-empty:
  → Go back to STEP B and create the missing metric view(s)
```

### GATE 5.7: Planned-vs-Created Metric View Parity (MANDATORY)

Before marking the metric-view stage complete, compare:
- `metric_view_plan.yaml` → `metric_views[]`
- `metric_view_validation.yaml` → `metric_views[]`
- `step_handoff.yaml` → `metric_view_fqns[]`

Normalize each FQN to a canonical three-part identifier before comparison. Validate identity and KPI assignment, not counts alone:

```text
planned_fqns   = set(metric_view_plan.metric_views[].sql_fqn)
validated_fqns = set(metric_view_validation.metric_views[].sql_fqn)
handoff_fqns   = set(step_handoff.metric_view_fqns[].sql_fqn)

IF planned_fqns != validated_fqns OR validated_fqns != handoff_fqns:
  → FAIL the stage and report missing_fqns and unexpected_fqns for each artifact.
  → Do NOT downgrade a missing metric view's KPI(s) to NOT_IMPLEMENTED.
  → Fix creation or handoff state and rerun validation.

IF any IMPLEMENTED_AND_VALIDATED KPI is missing from its planned metric view,
   appears in a different metric view, or appears more than once:
  → FAIL with KPI_ASSIGNMENT_PARITY_ERROR.
```

Equal counts are insufficient: two artifacts can contain different FQNs while having the same size.

A run is NOT allowed to end Step 5 with:
- plan says 2 metric views
- validation says 1 metric view
- downstream dashboards/Genie proceed anyway

That exact mismatch caused fresh-run divergence and must now be treated as a hard failure.

## Guard Rails

1. **Metric-view count design target**: prefer no more than frozen `run_context.quality_gates.max_metric_views_per_domain` per domain. This is not permission to drop a valid grain. If the number of distinct valid grains containing implementable KPIs exceeds that frozen maximum, HALT with `METRIC_VIEW_COUNT_REVIEW_REQUIRED`; propose safe consolidation only when grain semantics remain correct.
2. **Intermediate view fanout validation is MANDATORY** — never create an intermediate view without proving row count is preserved
3. **A distinct valid grain with >= 1 implementable KPI is eligible for a metric view.** If an approved downstream asset requires that KPI, the metric view is mandatory. KPI count alone must never suppress it.
4. **Prefer direct source over intermediate view** — only create intermediate views when columns are genuinely missing from the grain table
5. **NOT_IMPLEMENTED classification requires constraint scope + explicit reason + validated reference SQL** — record whether the blocker belongs to the platform or this accelerator, name the required capability, and provide a query that runs successfully
6. **Common time dimension** — metric views participating in the same cross-view date filter must expose a semantically compatible canonical time field (for example, `service_month`). If a grain has no compatible physical time column, do not invent one; record `shared_time_filter_compatible: false` and keep that view out of the shared filter.

## Output: `metric_view_plan.yaml`

Write `{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml`:

```yaml
run_id: "<exact run_context.run_id>"
asset_suffix: "<exact step_handoff.asset_suffix>"
metric_view_strategy: auto | explicit
capability_contract_name: metric_view_capabilities
capability_contract_version: "<contract.contract_version>"
capability_contract_sha256: "<sha256-of-exact-raw-contract-bytes>"
capability_contract_resolved_artifact: "{OUTPUT_FOLDER}/metric_views/resolved_metric_view_capabilities.yaml"
auto_handoff_producer_checkpoint: null  # explicit strategy; auto strategy uses the authenticated mapping defined above

metric_view_plan:
  total_kpis: <N>
  implementable_in_metric_views: <N>
  not_implemented_count: <N>
  skipped_count: <N>

  capability_decisions:
    - kpi: <KPI-ID>
      required_capability: <exact-capability-key>
      platform_support: SUPPORTED | NOT_SUPPORTED
      accelerator_validation: VALIDATED | PENDING | NOT_PLANNED
      enabled: true | false
      target_status: SATISFIED | NOT_SATISFIED
      native_outcome: USED | DISALLOWED
      fallback_considered: true | false
      fallback_strategy: <strategy-or-null>
      fallback_outcome: APPLIED_AND_VALIDATED | NOT_APPLICABLE | REJECTED_CAPABILITY | REJECTED_DATA_OR_GRAIN
      fallback_checks: {}  # when applied: exact contract required_checks keys mapped to PASS, backed by persisted probe evidence
      final_status: READY | NOT_IMPLEMENTED | SKIPPED_*

  metric_views:
    - name: <metric_view_name_with_version>
      sql_fqn: "`catalog`.`schema`.`<metric_view_name_with_version>`"  # from step_handoff (primary)
      source_fqn: "`source_catalog`.`source_schema`.`<source_table>`"  # exact schema_profile/catalog FQN, or exact intermediate target FQN
      primary: true
      intermediate_view: null  # or object (see below)
      grain: "<one-row-represents description>"
      kpis: [<KPI-ID-1>, <KPI-ID-2>, ...]

    - name: <secondary_metric_view_name>  # dynamically derived name
      sql_fqn: "`catalog`.`schema`.`<secondary_metric_view_name>`"  # dynamically generated FQN
      source_fqn: "`source_catalog`.`source_schema`.`<fact_table>`"
      primary: false
      intermediate_view: null
      grain: "<one-row-represents description>"
      kpis: [<KPI-ID-A>]  # A single implementable KPI is sufficient for a distinct valid grain

    - name: <enriched_metric_view_name>  # dynamically derived name
      sql_fqn: "`catalog`.`schema`.`<enriched_metric_view_name>`"  # dynamically generated FQN
      source_fqn: "`target_catalog`.`target_schema`.`<intermediate_view_name>`"
      primary: false
      intermediate_view:
        name: <intermediate_view_name>
        sql_fqn: "`target_catalog`.`target_schema`.`<intermediate_view_name>`"  # handoff target namespace
        source_fqns:
          detail: "`source_catalog`.`source_schema`.`<detail_table>`"
          header: "`source_catalog`.`source_schema`.`<header_table>`"
        join_sql: |
          SELECT d.*, h.<col1>, h.<col2>
          FROM <exact_detail_source_fqn> d
          LEFT JOIN <exact_header_source_fqn> h ON d.<fk> = h.<pk>
        join_type: "N:1 (<detail> to <header>)"
        fanout_validated: true
        source_rows: <N>
        left_join_rows: <N>
        orphan_rows: <N>
        duplicate_parent_keys: 0
      grain: "<one-row-represents description>"
      kpis: [<KPI-ID-X>, <KPI-ID-Y>, ...]

  not_implemented:
    - kpi: <KPI-ID>
      name: "<KPI Name>"
      reason: "<Why metric view syntax is insufficient>"
      status: NOT_IMPLEMENTED
      constraint_scope: ACCELERATOR | PLATFORM
      required_capability: <exact-resolved-capability-key>
      capability_decision_ref: <KPI-ID>/<required_capability>
      fallback_considered: true
      fallback_rejection_reason: "<why no declared fallback preserves the KPI semantics>"
      documentation_only: true
      sql: |
        <Full validated SQL query>
      validated: true
      validation_row_count: <N>
      manual_implementation_notes: |
        To implement: Add as a named SQL dataset in the dashboard.
        Cannot be a metric view measure due to <reason>.
```

The plan's top-level `run_id`, `asset_suffix`, and `metric_view_strategy` are mandatory replay
bindings for both strategies. They MUST equal current `run_context.yaml` and `step_handoff.yaml`
exactly. They are part of the canonical plan payload hashed by an auto checkpoint; for explicit
strategy they remain mandatory even though the checkpoint is null.

Every source and join-source FQN in the plan MUST be copied from the reconciled `schema_profile.yaml` and current catalog inspection. Every Metric View and intermediate-view target FQN MUST use the validated handoff target catalog/schema. Source and target namespaces are independent; never substitute one for the other.

**GATE 4.5**: `metric_view_plan.yaml` exists with >= 1 Metric View (each with exact target `sql_fqn` and exact `source_fqn`); every intermediate view has an exact target `sql_fqn` plus exact source FQNs; every input KPI appears exactly once in an effective READY/implemented, `NOT_IMPLEMENTED`, or specific `SKIPPED_*` outcome; all `NOT_IMPLEMENTED` KPIs include validated SQL, capability evidence, fallback rejection, and constraint scope; and `step_handoff.yaml` has been idempotently synchronized with all planned `metric_view_fqns` entries. In auto mode, require the exact authenticated producer checkpoint, raw handoff hash, canonical plan-payload hash, duplicate-free `{name, normalized_sql_fqn, primary}` parity, exactly one primary, capability tuple parity, and one and only one matching `VALID` fingerprinted `plan_metric_views` phase record with non-empty `completed_at`. In explicit mode, require `auto_handoff_producer_checkpoint: null`. HALT if any invariant fails.

---

# Step 5: Source Selection & Join Safety

## Source Selection Rules

**This step now executes per metric view as defined in `metric_view_plan.yaml`.**

For each metric view in the plan, validate the source selection:
1. Contains or safely supports the measures assigned to this metric view
2. Represents the grain documented in the plan
3. Supports safe navigation to dimensions
4. If an intermediate view is planned: validate the join safety (Step 5.1 below)
5. Minimizes fanout

Within Metric View design and deployment, `metric_view_plan.yaml` is the validated desired-state allocation for which KPIs go to which Metric View. Do NOT re-derive groupings here. After deployment, `metric_view_validation.yaml` owns the terminal validated assignment used by downstream stages.

## Join Validation (for every proposed join)

Document and verify:

```text
LEFT/RIGHT table, grain, key → Expected vs Observed cardinality → Rows before/after → SAFE/UNSAFE
```

**Rules:**
- Dimension joins must preserve source fact grain (N:1 = no row increase)
- Column-name similarity alone is INSUFFICIENT — use semantic_model.yaml
- Fact-to-fact joins = HIGH_RISK — establish grain compatibility before attempting
- Resolve `nested_snowflake_joins` from the capability contract. When disabled, use only direct joins and apply the declared fallback. When enabled, the generated structure must satisfy its target requirements and dedicated regression-backed validator.
- SCD2 dimensions require temporal join conditions; if a planned join is not representable, record the conflict and HALT for plan/upstream correction rather than skipping it locally

**Measure Stability Test (MANDATORY for every join):**
```sql
-- Pre-join:
SELECT SUM(measure_col) FROM source_table
-- Post-join:
SELECT SUM(s.measure_col) FROM source_table s LEFT JOIN dim d ON s.fk = d.pk
-- MUST be equal. If not: JOIN_FANOUT_FAILURE — preserve evidence and HALT; do not remove or rewrite the planned join locally.
```

Also require `LEFT JOIN` row-count preservation and uniqueness of the lookup key. Run the stability check for every affected additive base measure, not just one representative column. Track orphans separately; an orphan is a data-quality gap, while duplicated lookup matches are a fanout failure.

---

# Step 6: Build Metric View Design Contract

Write `{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml`.

**This file now contains an array of metric view designs** — one per entry in `metric_view_plan.yaml`.

```yaml
metric_view_designs:
  - metric_view:
      name: <metric_view_name>
      source_fqn: <exact_source_or_intermediate_view_fqn_from_plan>
      source_grain: <grain description>
    measures: [...]
    dimensions: [...]
    joins: [...]
    kpis_supported: []
    kpis_skipped: []
    data_quality_blockers: []

  - metric_view:
      name: <secondary_metric_view_name>
      source_fqn: <exact_source_fqn_from_plan>
      source_grain: <grain description>
    measures: [...]
    dimensions: [...]
    joins: [...]
    kpis_supported: []
    kpis_skipped: []
    data_quality_blockers: []

not_implemented_kpis:
  - kpi: <KPI-ID>
    name: <KPI Name>
    reason: <reason>
    reference_sql: <validated SQL from metric_view_plan.yaml>

intermediate_views:
  - name: <view_name>
    sql_fqn: <exact_target_fqn_from_plan>
    source_fqns: [<exact_source_fqn_1>, <exact_source_fqn_2>]
    join_type: "N:1"
    fanout_check: PASS
    source_rows: <N>
    left_join_rows: <N>
    orphan_rows: <N>
    duplicate_parent_keys: 0
```

**Rules for multi-view design:**
- Each metric view in the plan gets its own design entry
- Metric views participating in a shared date filter MUST expose the same semantically compatible time field name. Views without a compatible physical time column set `shared_time_filter_compatible: false`; never fabricate a time field.
- Intermediate views are documented with their fanout validation results
- NOT_IMPLEMENTED KPIs are documented with the validated reference SQL from the plan

**GATE 6.1**: metric_view_design.yaml exists with all joins validated and all planned metric views represented. HALT if missing.

---

# Step 7: KPI Coverage Gate

Before YAML generation, produce a planning table:

| KPI | Source | Grain | Measure | Join Safety | Status |
|-----|--------|-------|---------|-------------|--------|

Only effective `READY` KPIs—after capability resolution and any validated fallback—proceed. Every non-READY KPI needs one exact terminal status and evidence; every applied fallback must remain visible in the planning table.

---

# Step 7.5: Create Intermediate Views

If `metric_view_plan.yaml` specifies any metric views with a non-null `intermediate_view`, create them **before** generating metric view YAML.

### For each intermediate view in the plan:

1. **Validate join safety (MANDATORY):**

```sql
SELECT
  (SELECT COUNT(*) FROM <exact_detail_source_fqn_from_plan>) AS source_rows,
  (SELECT COUNT(*)
   FROM <exact_detail_source_fqn_from_plan> d
   LEFT JOIN <exact_header_source_fqn_from_plan> h
     ON d.{fk_col} = h.{pk_col}) AS left_join_rows,
  (SELECT COUNT(*)
   FROM <exact_detail_source_fqn_from_plan> d
   LEFT JOIN <exact_header_source_fqn_from_plan> h
     ON d.{fk_col} = h.{pk_col}
   WHERE h.{pk_col} IS NULL) AS orphan_rows,
  (SELECT COUNT(*)
   FROM (
     SELECT {pk_col}
     FROM <exact_header_source_fqn_from_plan>
     WHERE {pk_col} IS NOT NULL
     GROUP BY {pk_col}
     HAVING COUNT(*) > 1
   ) duplicate_keys) AS duplicate_parent_keys
```

If `left_join_rows != source_rows`, `duplicate_parent_keys > 0`, or the result materially disagrees with the upstream relationship-level `PASS` evidence → **HALT the current deployment** and do NOT create the intermediate view. Preserve the plan, handoff, upstream result, and new probe as drift evidence; return the conflict to the Data Layer validation owner. Do not rewrite KPI status, plan membership, or handoff identity locally. If only `orphan_rows > 0`, continue only when that result and LEFT JOIN policy agree with the upstream validated evidence and KPI contract; otherwise halt on relationship drift.

2. **Create the materialized view** using the DDL pattern:

```text
DDL Pattern: CREATE MATERIALIZED VIEW <exact_intermediate_target_fqn_from_plan> AS
  SELECT d.*, h.{col1}, h.{col2}, ...
  FROM <exact_detail_source_fqn_from_plan> d
  LEFT JOIN <exact_header_source_fqn_from_plan> h ON d.{fk_col} = h.{pk_col}
```

Use CREATE OR REPLACE MATERIALIZED VIEW to handle the case where the view already exists. If a pre-removal step is needed, execute it as a SEPARATE call — Databricks SQL allows only ONE statement per call (never combine with semicolons). Do NOT use `spark.sql()`.

3. **Verify the materialized view exists:**

Use catalog readback to resolve the exact `<exact_intermediate_target_fqn_from_plan>`; do not verify it through a source namespace or a name-only match.

**GATE 7.5**: All planned intermediate views exist in catalog. HALT if any are missing.

---

# Step 8: Generate Metric View Spec (Declarative)

**This step now produces a declarative spec consumed by the Deterministic Deployment Runtime.**

Instead of writing DDL and executing via Statement Execution API directly, the LLM produces `metric_view_spec.yaml`. The `metric_view_notebook.py.template` reads this spec, compiles it to DDL, executes, and validates.

**This step iterates over ALL metric views in `metric_view_plan.yaml`.**

For each metric view in `metric_view_designs[]` from the design contract:

### Pre-Flight (per metric view)

- [ ] metric_view_design.yaml exists with this metric view's entry
- [ ] All joins validated (no unresolved JOIN_FANOUT_FAILURE)
- [ ] All READY KPIs assigned to this metric view have confirmed measure columns
- [ ] Every executable Metric View FQN comes from the complete `step_handoff.yaml.metric_view_fqns[]` set; `metric_view_plan.yaml` is checked only for desired-architecture parity
- [ ] If sourced from an intermediate view: that view exists in catalog
- [ ] Resolved contract bytes still match the name/version/SHA-256 tuple in `metric_view_plan.yaml`
- [ ] Every generated construct is native-enabled or is the validated output of a declared fallback

### Produce `metric_view_spec.yaml`

Write `{OUTPUT_FOLDER}/metric_views/metric_view_spec.yaml`:

```yaml
metric_views:
  - name: <view_name_with_version>
    yaml:
      version: "<execution_target.yaml_specification>"  # resolved string; currently "1.1"
      comment: "..."
      source: <exact_source_fqn_from_plan>
      fields:
        - name: Dimension Name
          expr: column_name
          comment: "..."
      measures:
        - name: Claim Count
          expr: COUNT(*)
          comment: "..."
          format:
            type: number
            decimal_places:
              type: exact
              places: 0
      joins:
        - name: header
          source: <exact_join_source_fqn_from_schema_profile>
          'on': source.claim_id = header.claim_id
          rely:
            at_most_one_match: true
```

**Required Join Fields (MANDATORY for every join entry):**

Every entry under `joins:` MUST contain these fields — the Gate 1 structural validator asserts each one:

| Field | Required | YAML Key | Notes |
|------|----------|----------|-------|
| `name` | YES | `name` | Short identifier for the joined table (e.g., `header`, `member`) |
| `source` | YES | `source` | Fully qualified table name: `catalog.schema.table_name` |
| `on` | YES for the current contract | `'on'` (single-quote for parser stability) | `join_condition_using` currently resolves through the declared `JOIN_CONDITION_ON` fallback; a future release may change this only with matching compiler/validator coverage |
| `rely` | Conditional | `rely` | Emit `rely: { at_most_one_match: true }` only after the uniqueness and row-preservation probes pass |

**Critical rules:**
- `'on'` MUST be single-quoted in YAML because `on` is a reserved keyword. Writing `on:` without quotes will cause a YAML parse error or silently produce the wrong structure.
- When `nested_snowflake_joins.enabled: false`, the `'on'` expression may reference only `source.<col>` and the current join alias. When enabled, generate only structures permitted by the contract and validated template.
- If a metric view does NOT need any joins (single-source, all columns in the source table), **omit the `joins` key entirely**. Do NOT include a `joins:` section with incomplete or empty entries.
- Under the current approved contract, a join entry missing any of `name`, `source`, or `'on'` will cause `AssertionError` in Gate 1 and halt the pipeline.

**Example — metric view WITH a join:**
```yaml
joins:
  - name: header
    source: catalog.schema.fact_claim_header_v1
    'on': source.clm_dtl_claim_nbr = header.clm_hdr_claim_nbr
    rely:
      at_most_one_match: true
```

**Example — metric view WITHOUT joins (omit the key entirely):**
```yaml
# No joins: key at all — source table has all needed columns
measures:
  - name: Active Members
    expr: COUNT(DISTINCT member_sk)
```

**Key rules for the declarative spec:**
- The `yaml` key contains the EXACT YAML content that the template will wrap in `CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML AS $$ ... $$`
- The YAML `version` is the quoted string resolved from the contract; the LLM does not select it independently
- The LLM does NOT write DDL or execute SQL — only the declarative YAML spec
- The template handles compilation, execution (Statement Execution API), and validation
- All syntax rules from the DDL Syntax section below apply to the YAML content

### DDL Syntax (reference — template generates this from spec)

The template compiles the YAML to:

```sql
CREATE OR REPLACE VIEW <exact_metric_view_target_fqn_from_handoff> WITH METRICS LANGUAGE YAML AS
$$
<yaml content from spec>
$$
```

### Execution Pattern (handled by template — NOT by LLM)

The `metric_view_notebook.py.template` handles:
1. Running Gate 0: load the resolved contract, validate its tuple against the plan, and enforce capability decisions
2. Reading `metric_view_spec.yaml`
3. Running Gate 1 (structural validation of spec)
4. Running Gate 2 (metadata validation — source tables accessible)
5. Running Gate 3 (semantic validation — join safety, duplicate detection)
6. Compiling YAML to DDL
7. Executing via Statement Execution API
8. Verifying via SHOW VIEWS + MEASURE() smoke test
9. Writing the manifest with contract/spec/deployed-readback hash binding

If the deployed template does not implement Gate 0 and the required manifest fields, HALT with `TEMPLATE_CAPABILITY_ENFORCEMENT_MISSING`. Do not patch the template ad hoc during the run; update and regression-test it through the release workflow.

**The LLM does NOT call `execute_sql` or `w.statement_execution` directly.**

### Intermediate Views (Step 7.5 — unchanged)

If `metric_view_plan.yaml` specifies intermediate views, create them FIRST via Statement Execution API (these are regular MATERIALIZED VIEWs, not metric views). The intermediate view DDL can still be executed directly by the LLM.

**GATE 8.SPEC-IO**: Apply this step's `guardrails.md` MV-G1 and validation GATE 8.SPEC-IO.
Persist and verify exact workspace byte readback of `metric_view_spec.yaml` with all
planned views before notebook submission. Return a missing input to its producer.

---

# Step 9: Deploy and Validate Metric Views

### Deploy via Deterministic Deployment Runtime

**CRITICAL: Use `deploy_from_template` tool.** The template is a complete, tested notebook. The tool reads it verbatim and performs ONLY placeholder substitution. DO NOT use `import_notebook` for this — it will reject template-based paths (G-16 enforcement).

Call `deploy_from_template` with:
- `template_path`: exact frozen `run_context.templates.metric_view_notebook.path` (verify its paired SHA-256)
- `output_path`: `{OUTPUT_FOLDER}/metric_views/metric_view_deployment.ipynb`
- `placeholders`: `{"DOMAIN_NAME": "<run_context.domain.name>", "OUTPUT_FOLDER": "<handoff.output_folder>", "WAREHOUSE_ID": "<handoff.warehouse_id>", "CATALOG": "<handoff target catalog>", "SCHEMA": "<handoff target schema>", "VERSION_SUFFIX": "<handoff.version_suffix>", "DEPLOY_ROOT": "<handoff.deploy_root>"}`

Then execute the notebook via `execute_notebook`.

**DO NOT:**
- Rewrite template logic or hand-build a substitute; authenticated template reads and shared render preflight are required — the tool handles everything
- Use `import_notebook` for template-based notebooks
- Rewrite, summarize, or "improve" any cell
- Remove docstrings, comments, or validation code
- Drop Gate 2b (column reference validation) or any other gate

The approved template contains the release-tested Gate 0 capability resolver, Gates 1–4, execution, verification, and manifest writing. All gates, including Gate 2b (column reference validation against DESCRIBE TABLE), are tested and MUST be preserved. The `deploy_from_template` tool guarantees the output has the same line count as the approved template.

The template handles:
- Gate 0 (contract identity, target compatibility, capability/fallback decision enforcement)
- Gate 1 (structural validation of spec)
- Gate 2 (metadata validation — source tables accessible via Statement Execution API)
- Gate 2b (column reference validation — every expr column checked against DESCRIBE TABLE)
- Gate 3 (semantic validation — join safety, duplicate detection)
- Gate 4 (deployment — execute DDL, verify SHOW VIEWS, MEASURE() smoke test)
- Manifest writing with hash chain (`capability_contract_sha256`, `metric_view_spec_sha256`, `deployed_readback_sha256`)

The canonical `{OUTPUT_FOLDER}/metric_views/metric_view_manifest.json` MUST use this required schema and is written only after catalog/SQL readback validation passes:

```json
{
  "evidence_type": "asset_locator_and_deployment_attempt",
  "artifact_id": "<unique manifest/deployment artifact ID>",
  "validation_source": "catalog_readback",
  "source_hash": "<same value as metric_view_spec_sha256>",
  "generated_hash": "<sha256 of the deterministic compiled DDL set>",
  "readback_hash": "<same value as deployed_readback_sha256>",
  "state_comparison": "match",
  "capability_contract_name": "metric_view_capabilities",
  "capability_contract_version": "<contract.contract_version>",
  "capability_contract_sha256": "<sha256 of exact raw contract bytes>",
  "capability_contract_resolved_artifact": "{OUTPUT_FOLDER}/metric_views/resolved_metric_view_capabilities.yaml",
  "metric_view_spec_sha256": "<sha256 of exact persisted metric_view_spec.yaml bytes>",
  "deployed_readback_sha256": "<sha256 of normalized catalog/query readback>",
  "metric_views": [
    {
      "name": "<exact resolved name>",
      "sql_fqn": "<exact handoff target FQN>",
      "source_fqn": "<exact validated source or intermediate FQN>",
      "validation_status": "PASS"
    }
  ],
  "validation_artifact": "{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml"
}
```

The manifest is locator/hash-chain evidence, not current deployed-state authority. Any later current-state claim still requires current catalog/SQL readback. Do not write the canonical manifest on a mismatch; record the failure in `metric_view_validation.yaml` and halt.

### Batch Validation (if template validation is insufficient)

If additional validation is needed beyond the template's smoke test, run these queries via Statement Execution API:

**CRITICAL SQL SYNTAX RULE**: In Databricks SQL, `LIMIT` binds to the entire
statement, NOT to individual sub-queries. Placing `LIMIT` inside a `UNION ALL`
sub-query is a **PARSE_SYNTAX_ERROR**. Either:
- Run each metric view's structural check as a **separate** `execute_sql` call, OR
- Wrap each sub-query in parentheses: `(SELECT ... LIMIT 1) UNION ALL (SELECT ... LIMIT 1)`

Prefer separate calls — they are easier to diagnose on failure.

```sql
-- BATCH 1: Structural (all measures/dimensions exist)
SELECT MEASURE(measure_1), MEASURE(measure_2), ... FROM metric_view LIMIT 1

-- BATCH 2: Baseline reconciliation (direct SQL vs MEASURE)
SELECT 'baseline_total_paid' check, SUM(col) val FROM source_table
UNION ALL
SELECT 'mv_total_paid', (SELECT MEASURE(total_paid) FROM metric_view)

-- BATCH 3: Measure stability (pre-join vs post-join)
SELECT 'pre_join' check, SUM(col) FROM source
UNION ALL
SELECT 'post_join', SUM(s.col) FROM source s JOIN dim d ON s.fk = d.pk

-- BATCH 4: Dimension slices
SELECT dim_col, MEASURE(total_paid) FROM metric_view GROUP BY dim_col LIMIT 10
```

### Validation Matrix

| Check | Expected | Fail Code |
|-------|----------|-----------|
| Structural: all measures/dimensions resolve | Query succeeds | `METRIC_VIEW_SYNTAX_ERROR` |
| Baseline reconciliation: direct SQL = MEASURE() | Values match (tolerance 0 for integers) | `METRIC_RECONCILIATION_ERROR` |
| Measure stability: SUM before join = after join | Equal | `MEASURE_FANOUT_FAILURE` |
| Dimension slice: grouped totals match baseline | Match | `DIMENSION_SLICE_ERROR` |
| Ratio: numerator + denominator independently validated | Match baseline | `RATIO_DEFINITION_ERROR` |
| Distinct count: matches direct COUNT(DISTINCT) | Equal | `DISTINCT_COUNT_ERROR` |
| Temporal: multiple periods produce expected results | Non-zero per period | `TEMPORAL_VALIDATION_ERROR` |

---

# Step 10: Write Validation Report

Write `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml`:

```yaml
run_id: "<exact run_context.run_id>"
asset_suffix: "<exact step_handoff.asset_suffix>"
metric_view_strategy: auto | explicit
capability_contract_name: metric_view_capabilities
capability_contract_version: "<contract.contract_version>"
capability_contract_sha256: "<sha256-of-exact-raw-contract-bytes>"
capability_contract_resolved_artifact: "{OUTPUT_FOLDER}/metric_views/resolved_metric_view_capabilities.yaml"

status: PASS | FAIL
metric_views:
  - name: <metric_view_name>
    sql_fqn: <exact_metric_view_target_fqn_from_handoff>
    primary: true
    source_fqn: <exact_source_or_intermediate_view_fqn>
    source_grain: <grain description>
    validation_status: PASS | FAIL
    kpi_count: <N>
  - name: <secondary_metric_view_name>
    sql_fqn: <exact_metric_view_target_fqn_from_handoff>
    primary: false
    source_fqn: <exact_source_fqn>
    validation_status: PASS | FAIL
    kpi_count: <N>

intermediate_views:
  - name: <intermediate_view_name>
    sql_fqn: <exact_target_fqn>
    source_fqns: [<exact_source_fqn_1>, <exact_source_fqn_2>]
    fanout_check: PASS | FAIL
    source_rows: <N>
    left_join_rows: <N>
    orphan_rows: <N>
    duplicate_parent_keys: <N>

kpis:
  - kpi: <KPI-ID>
    metric_view: <metric_view_name>  # which metric view implements this KPI
    status: IMPLEMENTED_AND_VALIDATED | SKIPPED_* | NOT_IMPLEMENTED
    capability_decisions:
      - required_capability: <exact-capability-key>
        native_outcome: USED | DISALLOWED
        fallback_strategy: <strategy-or-null>
        fallback_outcome: APPLIED_AND_VALIDATED | NOT_APPLICABLE | REJECTED_CAPABILITY | REJECTED_DATA_OR_GRAIN
      fallback_checks: {}  # when applied: exact contract required_checks keys mapped to PASS, backed by persisted probe evidence
    baseline_result: <value>
    metric_view_result: <value>
    difference: <value>
    validation_status: PASS | FAIL
  - kpi: <KPI-ID>
    metric_view: null  # NOT_IMPLEMENTED KPIs have no metric view
    status: NOT_IMPLEMENTED
    reason: "<reason>"
    constraint_scope: ACCELERATOR | PLATFORM
    required_capability: <capability>
    native_outcome: DISALLOWED
    fallback_considered: true
    fallback_outcome: NOT_APPLICABLE | REJECTED_CAPABILITY
    fallback_rejection_reason: "<reason>"
    sql_ref: "See metric_view_plan.yaml"
    documentation_only: true

join_validation: [...]
measure_stability: [...]
skipped_kpis: [...]
```

Every `metric_views[]` validation entry MUST contain a boolean `primary` copied from the exact
matching plan/handoff entry; never infer it from array position, naming, or deployment order.
Normalize each `sql_fqn` with the canonical three-segment algorithm, then require the complete
ordered `{name, normalized_sql_fqn, primary}` projection to have duplicate-free names/FQNs and
exactly one `primary: true`. In `auto`, it must equal the authenticated producer-checkpoint,
plan, and handoff projections exactly. In `explicit`, the checkpoint key must be present with a
null value and the projection must equal the frozen Step-0 run-context, handoff, and plan lists.

The validation report's top-level `run_id`, `asset_suffix`, and `metric_view_strategy` are also
mandatory. Require exact equality with current run context, handoff, and the plan before accepting
the report. A missing or mismatched replay binding invalidates the artifact even if `status: PASS`.

### KPI Terminal States

```text
IMPLEMENTED_AND_VALIDATED
NOT_IMPLEMENTED
SKIPPED_MISSING_DATA
SKIPPED_UNRESOLVED_RELATIONSHIP
SKIPPED_UNSAFE_GRAIN
SKIPPED_UNSUPPORTED_SEMANTICS
SKIPPED_FACT_TO_FACT_FANOUT_RISK
```

**NOT_IMPLEMENTED vs SKIPPED distinction:**
- `NOT_IMPLEMENTED`: The KPI is well-defined and validated reference SQL is known; the exact capability and target fully resolve; native use is disallowed; and no applicable semantics-preserving fallback succeeds. Record the contract tuple, capability evidence, fallback outcome, `constraint_scope`, and `required_capability`. Do not describe an accelerator-disabled feature as unsupported by Databricks.
- `SKIPPED_*`: The KPI cannot be safely implemented because of data quality, missing columns/relationships, or unsafe grain. A diagnostic SQL query may be recorded, but it is not a validated semantic implementation.
- Missing, unknown, malformed, or unevaluable capability evidence is a stage HALT, not either terminal KPI status.

**GATE 10.1**: metric_view_validation.yaml exists. HALT if missing.

**GATE 10.2 — Capability, Replay, and Identity Evidence Parity**: Recompute the raw-byte contract SHA-256 and verify that `metric_view_plan.yaml`, `metric_view_validation.yaml`, and `metric_view_manifest.json` contain the identical contract name/version/hash tuple. Require exact plan/validation/current-run parity for top-level `run_id`, `asset_suffix`, and `metric_view_strategy`. Verify every KPI's required capabilities, native/fallback decision, constraint scope, and final status agree between plan and validation. Require every validation `primary` to be boolean and exactly one primary. In `auto`, require the exact deterministic ordered `{name, normalized_sql_fqn, primary}` list to match plan, handoff, validation, and the authenticated checkpoint. In `explicit`, require `auto_handoff_producer_checkpoint: null` with the key present and require that same ordered full-entry list to match the Step-0-frozen run-context entries, handoff, plan, and validation; there is no checkpoint entry list in this branch. HALT on missing replay evidence, hash mismatch, duplicate name/FQN, primary drift, or decision drift.

---

# Step 11: Generate Sample Queries

Only for KPIs with `IMPLEMENTED_AND_VALIDATED` status.

Before using the sample-query minimum, re-authenticate the exact approved `genie_quality` raw
contract tuple and recompute the Step-0 effective-policy hash. Require
`min_sample_query_file_queries` to be a valid frozen field in the complete effective threshold map.
Do not use a prompt-local number or fallback. Record the raw contract and canonical effective policy
as mandatory `validate_metric_views` input fingerprints, and fingerprint the written sample-query
file as an output.

Write `{OUTPUT_FOLDER}/genie_space/{run_context.assets.sample_queries_file}` using the exact frozen resolved filename from current-run `run_context.yaml`.

Generate at least the frozen `run_context.validation.min_sample_query_file_queries` representative `MEASURE()` queries **spanning ALL metric views**. Queries should cover overall measures, dimension grouping, filtering, time trends, multiple measures, and ratios. Include window-measure queries only when `capabilities.window_measures_base.enabled: true` and the deployed metric view contains a validated window measure.

Each query must reference the correct metric view FQN for the KPIs it uses. Do NOT mix measures from different metric views in a single query — `MEASURE()` operates on one metric view at a time.

**Exclude NOT_IMPLEMENTED KPIs** — these have no metric view and cannot be queried with `MEASURE()`.

---

# Error Classification

| Code | Meaning |
|------|---------|
| `SCHEMA_DISCOVERY_ERROR` | Cannot resolve source tables |
| `SCHEMA_DRIFT` | Physical schema disagrees with contracts |
| `GRAIN_INFERENCE_ERROR` | Cannot determine source grain |
| `KPI_MAPPING_ERROR` | KPI cannot map to physical columns |
| `RELATIONSHIP_MAPPING_ERROR` | Join key not confirmed |
| `JOIN_FANOUT_ERROR` | Join multiplies rows |
| `FACT_TO_FACT_FANOUT_RISK` | Unsafe fact-to-fact join |
| `SCD_JOIN_UNSAFE` | Temporal dimension cannot be safely joined |
| `METRIC_VIEW_SYNTAX_ERROR` | YAML compilation failure |
| `METRIC_RECONCILIATION_ERROR` | Baseline ≠ MEASURE() result |
| `CAPABILITY_CONTRACT_MISSING` | Approved Metric View capability contract is absent |
| `CAPABILITY_CONTRACT_INVALID` | Contract is malformed, unapproved, or contains an unknown enum/value |
| `CAPABILITY_CONTRACT_MUTATED` | Same contract version has a different raw-byte SHA-256 |
| `CAPABILITY_NOT_RESOLVED` | Exact required capability is absent or cannot be deterministically evaluated |
| `CAPABILITY_TARGET_INCOMPATIBLE` | Approved execution target does not satisfy the resolved capability |
| `CAPABILITY_FALLBACK_FAILED` | Declared fallback deployment or validation failed |
| `TEMPLATE_CAPABILITY_ENFORCEMENT_MISSING` | Deployment template cannot enforce or persist the resolved contract |

---

# Pipeline Halt Rules

HALT with `❌ EXECUTION HALTED` when: the capability contract cannot be trusted or resolved; the deployment template lacks required contract enforcement; no viable source exists for primary KPIs; primary grain is unestablishable; a required measure column is missing; a mandatory join produces fanout; a declared fallback fails to deploy or validate; plan/spec/deployment/validation parity breaks; or YAML remains invalid after 3 root-cause-based retries.

A pre-planning data or business-mapping issue that affects only an individual KPI may use its exact `SKIPPED_*` classification. After `metric_view_plan.yaml` becomes the validated desired-state contract, silently dropping or reclassifying a planned KPI is forbidden: update and revalidate the plan or HALT on parity drift.

---

# Output Contract

| Artifact | Location | Validation |
|----------|----------|-----------|
| resolved_metric_view_capabilities.yaml | `{OUTPUT_FOLDER}/metric_views/` | Exact-byte copy of approved contract; name/version/raw SHA-256 pinned |
| schema_profile.yaml | `{OUTPUT_FOLDER}/metric_views/` | Tables + relationships documented |
| kpi_metric_mapping.yaml | `{OUTPUT_FOLDER}/metric_views/` | Every KPI mapped or skipped |
| metric_view_plan.yaml | `{OUTPUT_FOLDER}/metric_views/` | >= 1 metric view planned; `NOT_IMPLEMENTED` KPIs have validated SQL, constraint scope, and required capability; auto producer checkpoint is authenticated, or explicitly null for explicit strategy |
| metric_view_design.yaml | `{OUTPUT_FOLDER}/metric_views/` | All metric views designed, all joins validated safe |
| **metric_view_spec.yaml** | `{OUTPUT_FOLDER}/metric_views/` | **Declarative spec consumed by template** |
| metric_view_manifest.json | `{OUTPUT_FOLDER}/metric_views/` | Written by template; binds contract, spec, and deployed-readback hashes |
| metric_view_validation.yaml | `{OUTPUT_FOLDER}/metric_views/` | `status: PASS`; all Metric Views, KPI outcomes, FQNs, and contract evidence validated |
| sample_queries file | `{OUTPUT_FOLDER}/genie_space/` | At least frozen `run_context.validation.min_sample_query_file_queries` MEASURE() queries spanning all metric views |

---

# Progress Reporting Reference

| Phase | phase_id | Key Stats |
|-------|----------|-----------|
| Load Inputs | `load_inputs` | kpis_defined, source_tables |
| Profile Schema | `profile_schema` | tables_profiled, columns_total, relationships |
| Map KPIs | `map_kpis` | kpis_mapped, kpis_skipped, measures_classified |
| Plan Metric Views | `plan_metric_views` | metric_views_planned, intermediate_views_needed, kpis_not_implemented |
| Design Metric Views | `design_metric_views` | metric_views_designed, join_paths_validated |
| Create Intermediate Views | `create_intermediate_views` | intermediate_views_created, fanout_checks_passed |
| Generate Metric Views | `generate_metric_views` | metric_views_created, measures_total, dimensions_total |
| Validate | `validate_metric_views` | validations_run, passed, failed |

Call `report_progress` with `status: "started"` before, `status: "completed"` after each phase.
