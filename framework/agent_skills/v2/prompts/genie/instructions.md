# Create Genie Space

> **Transport:** apply the frozen `shared/agent_transport.md` contract. Tool names are portable operations; App/Lakebase integration is optional. Runtime paths come only from `contracts/release.yaml`.

> **Always load for this stage:** `{AGENT_SKILLS_DIR}/prompts/shared/global_guardrails.md`, `{AGENT_SKILLS_DIR}/prompts/genie/validation.md`, `{AGENT_SKILLS_DIR}/prompts/genie/guardrails.md`, `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`, `{AGENT_SKILLS_DIR}/prompts/shared/sql_generation_rules.md`.
> **Failure-only:** authenticate `run_context.inputs.stage_runbooks.create_genie_space` and load only the matching section of `{AGENT_SKILLS_DIR}/prompts/genie/runbook.md` after a classified failure. Never load the runbook on the normal success path.


> **Additional authenticated input:** exact frozen `run_context.inputs.genie_quality_contract`
> (versioned threshold and outcome contract).
>
> Genie space deployment uses `v2_genie_space_notebook.py.template` (the Deterministic Deployment Runtime).
> The LLM produces and validates `llm_genie_design.yaml`, then passes its exact approved fields as placeholders to the frozen template. The template handles serialization and deployment.
> Four-gate validation runs inside the template before API calls.


## Failure-Only Runbook Loading

Do not read `{AGENT_SKILLS_DIR}/prompts/genie/runbook.md` during normal execution. After this stage classifies a failure, authenticate the frozen runbook tuple, use the routing index in `{AGENT_SKILLS_DIR}/prompts/genie/validation.md`, and load only the matching diagnostic section. The runbook cannot weaken a gate, change the failure owner, or authorize a blind retry.

## CONTEXT ISOLATION — Read This First

Forget all execution details from prior steps (ERD parsing, synthetic data, metric view creation, dashboard deployment). You do NOT need that context.

### Canonical Run Bootstrap (Mandatory)

The orchestrator MUST supply the exact `run_context_path` for this invocation. Read and parse the
raw bytes at that exact path before any stage artifact. Do not search for a run context, choose a
folder by recency, derive a path from the working directory, or use a request-time filename.
Require a non-empty `run_context.run_id` and non-empty absolute `run_context.output_folder`; reject
relative output paths before comparison. Then require the normalized basename to be
`run_context.yaml` and the normalized parent to equal parsed `run_context.output_folder`. The only handoff
path is then `{run_context.output_folder}/step_handoff.yaml`.

Missing, malformed, ambiguous, or path-inconsistent bootstrap input is
`HANDOFF_AUTHORITY_ERROR`. HALT without synthesizing or locating a replacement. In the remainder
of this prompt, `{OUTPUT_FOLDER}` means that exact frozen output folder. Permission, transport,
and other genuine I/O failures retain their operational classification.

**Your ONLY inputs are:**

1. Exact tool-supplied `run_context_path` — frozen resolved run configuration, after the canonical bootstrap above

2. `{OUTPUT_FOLDER}/step_handoff.yaml` — contains pre-formatted values (paste verbatim):
   - `metric_view_fqns[].sql_fqn` — the EXACT backtick-quoted FQN for example SQL (do NOT re-derive) — contains at least one and no more than frozen `run_context.quality_gates.max_metric_views_per_domain`
   - `metric_view_fqns[].primary` — whether this is the primary metric view
   - `genie_title` — the EXACT title for the Genie Space API call (do NOT reformat)
   - `warehouse_id`, `version_suffix`, `asset_suffix`, `genie_parent_path`, `workspace_host`, `deploy_root`, `output_folder` — paste as-is
   - current-run `run_context.assets.genie.notebook_name` — exact resolved supporting notebook filename

3. `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` — which KPIs are IMPLEMENTED and which metric view implements each

4. `{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml` — intended measure/dimension definitions for comparison with live deployed definitions

5. `{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml` — intended multi-metric-view architecture including:
   - All metric views with their assigned KPIs and grains
   - Intended NOT_IMPLEMENTED candidates with reasons/reference SQL; current-run `metric_view_validation.yaml` owns terminal status and downstream eligibility

6. KPI specification — business context for instructions

7. Exact frozen `run_context.inputs.genie_quality_contract` — approved source contract whose raw
   identity and Step-0-resolved effective policy are frozen in `run_context.validation`

**Rules:**
- After canonical run bootstrap, read the exact `step_handoff.yaml` BEFORE any other stage action
- Use `genie_title` value EXACTLY as written (it is already snake_case validated)

### Authority Hierarchy (Field-Scoped and Binding)

No single artifact is authoritative for every field. Use these ownership boundaries:

| Information | Authority |
|-------------|-----------|
| KPI definitions, business intent, and terminology | KPI specification |
| Frozen resolved run configuration | current-run `run_context.yaml` |
| Exact Metric View FQNs, Genie title, warehouse, and other resolved asset identity | `step_handoff.yaml` |
| KPI terminal status and KPI-to-Metric-View assignment | `metric_view_validation.yaml` |
| Deployed Metric View aliases, types, measures, dimensions, and expressions | Live `DESCRIBE TABLE` plus `SHOW CREATE TABLE` for each handoff FQN |
| Intended Genie instructions, questions, SQL, and benchmarks | Validated generated configuration artifacts |
| Persisted Genie identity, attached Metric Views, instructions, questions, SQL, and benchmarks | `GET /api/2.0/genie/spaces/{id}?include_serialized_space=true` |
| Genie threshold defaults and PASS/WARN/FAIL semantics | Exact approved `genie_quality` source contract |
| Executable threshold values and outcome mapping for this run | Authenticated frozen `run_context.validation` effective policy |

Plans, designs, semantic inventories, request payloads, POST/PATCH responses, and manifests are intent or evidence. They MUST NOT override verified deployed state. A manifest may locate an asset and record a prior deployment attempt; it does not prove the asset's current contents.

If two authorities disagree, do not choose one silently. HALT with the conflicting values and return the issue to the stage that owns the incorrect artifact.

### Validate `step_handoff.yaml` Before Use

The Genie stage is a consumer of `step_handoff.yaml`; it MUST NOT repair or rewrite it.

Validate that:

1. every `metric_view_fqns[].sql_fqn` is a complete three-part identifier in the required quoted form;
2. `genie_title`, `warehouse_id`, `version_suffix`, `asset_suffix`, `genie_parent_path`, `workspace_host`, `deploy_root`, and `output_folder` are present and non-empty;
3. normalized Metric View FQNs are unique; and
4. the normalized FQN sets in `step_handoff.yaml`, `metric_view_plan.yaml`, and `metric_view_validation.yaml` are identical.
5. every shared resolved field in `step_handoff.yaml` agrees exactly with current-run `run_context.yaml`.
6. the Metric View producer checkpoint is authenticated exactly as specified below.

Canonicalization may be used in memory only for equality comparison. Never write a normalized or reconstructed handoff from this stage.

If the handoff itself is missing/malformed or its shared run/path fields conflict, HALT with
`HANDOFF_AUTHORITY_ERROR` and return to `MASTER_RESOLVER`. If its authenticated Metric View tuple
content conflicts with the plan/validation/checkpoint, HALT with `GENIE_HANDOFF_AUTHORITY_ERROR`
and return to `METRIC_VIEW_STAGE`. Permission, transport, and genuine I/O failures keep their
operational classification.

### Authenticate the Metric View Producer Checkpoint

Read the top-level `metric_view_plan.yaml.auto_handoff_producer_checkpoint` before consuming any
Metric View identity.

Before branching on strategy, require both `metric_view_plan.yaml` and
`metric_view_validation.yaml` to contain top-level `run_id`, `asset_suffix`, and
`metric_view_strategy`. Each value MUST equal current run context and handoff exactly, and the two
artifacts MUST equal one another. This replay binding is mandatory in auto and explicit modes; a
PASS status cannot compensate for a missing/mismatched field.

- When `metric_view_strategy: auto`, it MUST be a mapping with exactly these keys:
  `producer_step`, `producer_phase`, `status`, `run_id`, `asset_suffix`,
  `metric_view_strategy`, `step_handoff_path`, `step_handoff_sha256`,
  `metric_view_plan_payload_sha256`, `metric_view_entries`,
  `capability_contract_version`, and `capability_contract_sha256`.
- Require exact values `producer_step: create_metric_views`,
  `producer_phase: plan_metric_views`, `status: PASS`, and
  `metric_view_strategy: auto`; exact run ID and asset suffix parity; exact canonical handoff path;
  SHA-256 equality over the current handoff's raw bytes; and capability version/hash parity with
  the current plan, validation, and exact resolved capability bytes.
- Require every stored SHA-256 to be exactly 64 lowercase hexadecimal characters.
- Recompute `metric_view_plan_payload_sha256` after removing the entire top-level checkpoint from
  the parsed plan, using SHA-256 over the UTF-8 result of
  `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
- Require `metric_view_entries` to contain exactly `{name, normalized_sql_fqn, primary}` per item,
  with non-empty duplicate-free names, boolean primary values, no duplicate normalized FQNs,
  exact deterministic ordered tuple-list parity with the handoff, plan, and validation, and
  exactly one primary.
  First require every raw executable `sql_fqn` in the handoff, plan, and validation to contain
  exactly three separately backtick-quoted non-empty segments, with no surrounding whitespace or
  trailing content. Remove the one required outer backtick pair per segment, unescape doubled
  backticks, Unicode-casefold each segment, and join the results unquoted with `.`.
- Require one and only one matching durable `run_context.phases_completed` record with
  `step=create_metric_views`, `phase=plan_metric_views`, `checkpoint_status: VALID`, non-empty
  `completed_at`, and a passing fingerprint Resume Skip Gate.
- When `metric_view_strategy: explicit`, require the
  `auto_handoff_producer_checkpoint` key to be present with value `null`; missing, `{}`, or any
  non-null value is an authority conflict. Require exact duplicate-free ordered
  `{name, normalized_sql_fqn, primary}` parity across Step-0-frozen
  `run_context.assets.metric_views[]`, handoff, plan, and validation, with exactly one primary and
  the same capability tuple.

Any failure is `GENIE_HANDOFF_AUTHORITY_ERROR` owned by the Metric View stage. Genie must not
rewrite the plan, handoff, hashes, primary flag, or phase history.

### Authenticate the Genie Quality Contract

Before profiling or design, read the exact raw bytes at
`run_context.inputs.genie_quality_contract` with duplicate-key rejection. Require the approved
source tuple `name: genie_quality`, non-empty `contract_version`,
`policy_id: GENIE_QUALITY_V1`, and `status: APPROVED`; hash the exact raw bytes and require exact
parity with these frozen fields:

```text
run_context.validation.genie_quality_contract_name
run_context.validation.genie_quality_contract_version
run_context.validation.genie_quality_contract_sha256
run_context.validation.genie_quality_policy_id
```

Require the source contract's `thresholds`, `threshold_schema`, and
`resolution_policy.allowed_override_keys` to have the same exact key set. Validate every frozen
effective threshold against the source type/bounds and require all invariants to pass. Require
`run_context.validation.benchmark_outcomes` to exactly equal the source
`outcome_semantics.benchmark` mapping; neither the outcome mapping nor its comparator/action/status
meaning is locally overridable.

Recompute `run_context.validation.genie_quality_effective_policy_sha256` using
`CANONICAL_JSON_UTF8_SHA256_V1` over exactly:

```yaml
policy_id: <frozen genie_quality_policy_id>
thresholds: <complete flat frozen threshold map>
benchmark_outcomes: <exact frozen benchmark_outcomes mapping>
```

The flat threshold map contains exactly the keys allowed by the approved source contract. A raw
contract mismatch, missing/extra threshold, invalid value, outcome drift, or effective hash mismatch
is `GENIE_QUALITY_CONTRACT_ERROR`. HALT without reading `accelerator.yaml`, inventing a number,
using a prompt-local default, or reconstructing PASS/WARN/FAIL behavior. Include the authenticated
contract tuple and effective-policy hash in the design trace, validation artifact, manifest, and
every reusable phase input fingerprint from the first phase that consumes the policy.

### Pipeline Halt Rules & Recovery

If `step_handoff.yaml` does NOT exist in `{OUTPUT_FOLDER}`:

```text
❌ EXECUTION HALTED: step_handoff.yaml is missing.
The Genie stage cannot reconstruct resolved asset identity from run_context.yaml,
accelerator.yaml, output-folder naming, or prior memory. Re-run the owning stage.
```

Do not create or modify `step_handoff.yaml` in this stage.

**MANDATORY FIRST ACTIONS (execute these in order before anything else):**
1. Read `{OUTPUT_FOLDER}/step_handoff.yaml` → extract ALL `metric_view_fqns[].sql_fqn` entries, `genie_title`, `warehouse_id`, `version_suffix`, `asset_suffix`, `genie_parent_path`, `workspace_host`, `deploy_root`, and `output_folder`; also read the exact frozen `run_context.assets.genie.notebook_name`
2. Read `{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml` for intended Metric View architecture, exclusions, reasons, and reference SQL
3. Read `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` → know which KPIs are IMPLEMENTED and terminally eligible
4. Authenticate the plan's strategy-aware producer checkpoint/null contract and verify exact identity parity with handoff/validation
5. Resolve and validate the exact frozen `run_context.templates.gate_checks.path` plus lowercase 64-hex `.sha256`; do not derive or discover a helper
6. Authenticate the exact frozen `run_context.inputs.genie_quality_contract` bytes and the complete
   `run_context.validation` effective-policy hash; do not proceed with local defaults
7. Read the exact frozen `{run_context.inputs.genie_space_configuration.path}` path → understand the template workflow
8. Read the exact frozen `run_context.templates.genie_notebook` → understand the notebook structure (cells 1-10)

If ANY of these reads fail, HALT. Do NOT proceed to generate content without these inputs.

---

## ⚠️ CONDENSED EXECUTION CONTRACT (READ THIS FIRST — 5 PHASES, NO SHORTCUTS)

This prompt is long (2500+ lines). To prevent shortcutting, here is the EXACT execution sequence.
**If you skip any phase, the Genie Space will be BLANK/BROKEN.**

```text
PHASE A — LOAD & PROFILE (Steps 1-2)
  1. Read step_handoff.yaml (has ALL metric_view_fqns[], genie_title, warehouse_id)
  2. Read metric_view_validation.yaml + metric_view_design.yaml + metric_view_plan.yaml
  3. Authenticate the frozen Genie quality contract and effective-policy hash
  4. Read genie_space_configuration.md (MANDATORY — defines serialized_space contract)
  5. DESCRIBE ALL metric views + profile categorical values for each
  6. Write genie_semantic_inventory.yaml (covering ALL metric views)
     NOTE: The Genie table list MUST equal the validated handoff FQN set.
     NOT_IMPLEMENTED KPIs are excluded from sample questions and instructions.

PHASE B — LLM DESIGN (Step 2.2)
  6. Call reasoning model with metric view DDL + KPI spec + semantic inventory
  7. Get back: instructions, sample questions, example SQL, and benchmarks meeting the exact frozen `run_context.validation` minima
  8. Validate LLM output (GATE 2.2)
  9. Write llm_genie_design.yaml

PHASE C — VALIDATE SQL (Steps 3-8)
  10. Execute ALL example SQL queries against the warehouse (batch validation)
  11. Fix any failing SQL (wrong column names, etc.)
  12. Generate benchmark ground truth

PHASE D — BUILD & DEPLOY NOTEBOOK (Steps 9-13)
  13. Call `deploy_from_template` to create the Genie notebook from the template:
      - `template_path`: exact frozen `run_context.templates.genie_notebook`
      - `output_path`: `{OUTPUT_FOLDER}/genie_space/{run_context.assets.genie.notebook_name}`
      - `placeholders`: dict with ALL of the following keys (values from your config):
          - `DOMAIN_NAME`: domain name (e.g., "member_claims")
          - `SPACE_TITLE`: genie_title from step_handoff.yaml (versioned)
          - `SPACE_DESCRIPTION`: domain-specific description mentioning key metrics
          - `WAREHOUSE_ID`: warehouse_id from step_handoff.yaml
          - `PARENT_PATH`: genie_parent_path from step_handoff.yaml
          - `GATE_CHECKS_PATH`: exact frozen `run_context.templates.gate_checks.path`
          - `GATE_CHECKS_SHA256`: exact frozen lowercase SHA-256 from `run_context.templates.gate_checks.sha256`
          - `TABLE_IDENTIFIERS`: Python list literal of metric view FQNs, e.g. `["catalog.schema.view_v9", ...]`
          - `GENERAL_INSTRUCTIONS`: full multi-line instructions text (the LLM-designed content)
          - `METRIC_VIEW_DESCRIPTIONS`: Python dict literal, e.g. `{"catalog.schema.view": "description", ...}`
          - `SAMPLE_QUESTIONS`: Python list literal of question strings
          - `EXAMPLE_SQLS`: Python list literal of (question, sql) tuples
          - `BENCHMARK_QUESTIONS`: Python list literal of (question, sql) tuples
      This tool reads the template verbatim and performs ONLY placeholder substitution.
      Cells 8-10 (helpers, create/update, validate) are guaranteed VERBATIM from the template.
      DO NOT use `import_notebook` or `write_workspace_file` for this — they are blocked for genie_space_ paths (G-16).
      DO NOT read the template yourself and do string manipulation — the tool handles everything.
      NOTE: The template verifies and digest-loads the pinned gate_checks.py for enforcement.
      Gate checks run automatically:
        - PRE-DEPLOY: run_genie_predeploy_gates() verifies description,
          instructions, tables, questions, and example SQLs are all populated.
          Raises GateCheckError if ANY content is missing — API call is blocked.
        - POST-DEPLOY: validate_genie_from_api(workspace_client, space_id, title, validation=..., expected=...)
          reads the space back from
          the API and verifies the deployed content matches.
  14. Require the template to verify the exact raw bytes at `GATE_CHECKS_PATH` against
      `GATE_CHECKS_SHA256`, copy those bytes only to
      `/tmp/pipeline_python/{sha256_prefix}/gate_checks.py`, and load that exact file under a
      digest-qualified module name. Do not create an output-folder helper copy.
  15. Execute the notebook: Cell 8 (validate_genie_config) → Cell 9 (helpers) → Cell 10 (create/update API)
  16. Cell 10 calls POST /api/2.0/genie/spaces with FULL serialized_space
      Gate enforcement fires automatically within Cell 10.
      The template includes a format validation guard that asserts `data_sources`
      contains `"metric_views"` (NOT `"tables"`) before the API call.

PHASE E — VALIDATE & PERSIST (Steps 14-22)
  19. Require the digest-attested gate_checks post-deploy validator to perform the full GET and
      return its schema-valid PASS result. Missing/incompatible/non-PASS helper output HALTS;
      do not replace it with a handwritten GET validator.
  20. Verify all persisted counts against `run_context.validation.min_instruction_chars`, `min_sample_questions`, `min_example_sqls`, and `min_benchmark_questions`
  21. Resolve benchmark outcome/action/stage status from frozen `benchmark_outcomes`; write
      `{genie_title}_manifest.json`, benchmark_results.yaml, and validation artifact with the exact
      quality-contract tuple and effective-policy hash
      NOTE: If gate_checks wrote source:api_readback validation, do NOT
      overwrite it with source:agent_reported content.
```

### SHORTCUT DETECTION (agent self-check BEFORE any action)

If you are about to do ANY of the following, **STOP — you are shortcutting:**

| Action | Why It's Wrong | Correct Path |
|--------|---------------|-------------|
| `createAsset(assetType="genie")` | Creates blank title-only space | Use template notebook → `POST /api/2.0/genie/spaces` with full `serialized_space` |
| `POST /api/2.0/genie/spaces` without `serialized_space` | Creates empty space | Must include instructions + sample_questions + example_sqls + benchmarks |
| Writing `{genie_title}_manifest.json` with just `{"space_id": "...", "status": "CREATED"}` | Declares success without configuration | Manifest must include `sample_questions_count`, `example_sqls_count`, `benchmarks_count` |
| Skipping the LLM design call | Produces thin/generic instructions | LLM generates domain-specific, analytically rich configuration |
| Skipping `validate_genie_config()` execution | Deploys broken SQL | Must execute ALL example SQL before API call |
| Writing 4-line instruction text | Fails the frozen `run_context.validation.min_instruction_chars` quality gate | LLM produces rich markdown-formatted instructions meeting the frozen minimum |
| Reading template and copying cells manually | LLM rewrites helper functions, introducing bugs (AP-GN-4) | Use `deploy_from_template` tool — it guarantees verbatim template content |
| Using `write_workspace_file` to create the notebook | Bypasses template enforcement, allows LLM to introduce code errors | Use `deploy_from_template` — `write_workspace_file` is blocked for genie_space_ paths |

**The ONLY valid deployment path is: template notebook populated → pinned gate-check bytes verified and digest-loaded → validate_genie_config() passes → gate_checks pre-deploy passes → build_serialized_space() → POST/PATCH API with full payload → gate_checks post-deploy readback passes.**

The exact frozen `run_context.templates.gate_checks.path` and `.sha256` tuple is the only allowed
source for `gate_checks.py`. The notebook must attest the loaded module file and required callables
before use. Missing bytes, digest mismatch, load-path mismatch, or an incompatible helper surface
is `GENIE_HELPER_CONTRACT_ERROR`; there is no fixed-path import, `sys.path` fallback, output-folder
copy fallback, or manual validation fallback. Do NOT catch or suppress the attested module's
`GateCheckError`.

---

## Role

You are a senior Databricks Genie architect and semantic analytics engineer.

Create a production-quality **Databricks Genie Space / Genie Agent** for natural-language analytics over validated Metric Views.

The Genie configuration must be:

* grounded only in validated Metric Views and dimensions;
* aligned with the KPI specification;
* configured with high-quality business instructions;
* populated with representative sample questions;
* supplied with accurate example SQL;
* benchmarked with analytically meaningful questions;
* deployed through the official Databricks Genie management API;
* retrieved and validated after deployment.

The objective is NOT merely to create a Genie Space that exists.

The objective is to create a Genie Space that is:

```text
SEMANTICALLY GROUNDED
+
CONFIGURED
+
DEPLOYED
+
BENCHMARKED
+
VALIDATED
```

A title-only or minimally configured Genie Space is invalid.

---

## ENFORCEMENT HEADER

<!-- @enforcement
  pattern: notebook_execution_for_genie
  template_required: genie_notebook (frozen `run_context.templates.genie_notebook`)
  api_method: Genie Management API (POST /api/2.0/genie/spaces)
  gates:
    - id: quality_contract_authenticated
      before_step: 1
      check: "Approved source tuple/raw hash and frozen effective-policy hash match"
    - id: semantic_inventory_built
      after_step: 2
      check: "Internal inventory of validated measures/dimensions exists"
    - id: instructions_designed
      after_step: 3
      check: "Genie instructions text meets frozen run_context.validation.min_instruction_chars with MEASURE() guidance"
    - id: sample_questions_ready
      after_step: 4
      check: "Sample questions count >= frozen run_context.validation.min_sample_questions"
    - id: example_sql_validated
      after_step: 5
      check: "All example SQL queries execute without error"
    - id: genie_space_created
      after_step: 6
      check: "GET /api/2.0/genie/spaces/{id}?include_serialized_space=true returns persisted content matching intent"
    - id: benchmark_passed
      after_step: 7
      check: "Benchmark outcome/action/status match frozen benchmark_outcomes and manifest permission is true"
-->

---

## PROHIBITED ACTIONS (this entire step)

The following actions are STRICTLY FORBIDDEN:

1. **DO NOT create a blank or title-only Genie Space** — the space MUST have instructions, sample questions, AND example SQL
2. **DO NOT bypass the notebook template** — use `deploy_from_template` to create the Genie notebook from `v2_genie_space_notebook.py.template`. DO NOT read the template and copy cells manually — the LLM rewrites helper functions introducing bugs (AP-GN-4: `"tables"` vs `"metric_views"` key). DO NOT use `write_workspace_file` or `import_notebook` for genie_space_ paths — they are blocked by G-16 enforcement.
3. **DO NOT hardcode domain-specific instructions** in the template — instructions are generated from the validated KPI/metric inventory
4. **DO NOT skip benchmark validation** — sample questions must be tested against the Genie space to verify it answers correctly
5. **DO NOT create sample questions that cannot be answered** by the metric view — every sample question must map to available measures/dimensions from IMPLEMENTED metric views. Exclude only KPIs whose exact current-run terminal status in `metric_view_validation.yaml` is `NOT_IMPLEMENTED` or a `SKIPPED_*` status. Never infer exclusion from a feature name such as HAVING, LAG, or window semantics; the resolved capability decision and current-run validation status control eligibility.
6. **DO NOT use raw SQL in example queries** when `MEASURE()` syntax should be used — Genie must learn the metric view query pattern
7. **DO NOT skip the instruction quality check** — instructions must explicitly mention: measure names, dimension names, MEASURE() syntax rules, ratio non-additivity warnings
8. **DO NOT create fewer sample questions than frozen `run_context.validation.min_sample_questions`**
9. **DO NOT use `createAsset(assetType="genie")` as the deployment mechanism** — this creates a blank title-only space. Genie Spaces MUST be created via the official Genie Management API (`POST /api/2.0/genie/spaces`) with a complete `serialized_space` payload.
10. **DO NOT improvise or use custom logic** — this prompt defines the exact sequence. Do not substitute another Genie workflow, skip gates, or collapse numbered steps into one API call.
11. **DO NOT call the Genie Create/Update API before Steps 1-10 are complete** — the semantic inventory, instructions, sample questions, example SQL (validated), and benchmarks MUST all be designed and tested before constructing `serialized_space`. Jumping to API creation "because the space seems simple" produces blank or misconfigured spaces.
12. **DO NOT construct `serialized_space` from model memory** — ALWAYS read `genie_space_configuration.md` first and follow its exact payload structure. The JSON schema has non-obvious requirements (newline truncation, column_configs sorting, UUID format) that CANNOT be reliably inferred.
13. **DO NOT skip reading `genie_space_configuration.md`** — if this file is neither in the system supplement NOR readable from the exact frozen `run_context.inputs.genie_space_configuration` path, HALT immediately. Do NOT guess the payload format.
14. **DO NOT submit `serialized_space` with unsorted ID arrays** — ALL arrays containing `id` fields (`example_question_sqls`, `sample_questions`, `benchmarks.questions`, `text_instructions`) MUST be sorted by `id` ascending. The API rejects with `must be sorted by id` otherwise. Always call `sorted(items, key=lambda x: x['id'])` before serializing.
15. **DO NOT treat POST/PATCH acceptance as deployed-content validation** — after every create or update, call `GET /api/2.0/genie/spaces/{id}?include_serialized_space=true`. The normalized GET readback is the authority for persisted Genie content. A GET without `include_serialized_space=true` is insufficient.
16. **DO NOT use assumed or semantic column names in example SQL** — ALWAYS use EXACT column names from `DESCRIBE TABLE` / `genie_semantic_inventory.yaml`. Common failures: `service_month` (doesn't exist — use `DATE_TRUNC('MONTH', service_date)`), `claim_month`, `member_name`. If a column is not in the inventory, it MUST NOT appear in any SQL.
17. **DO NOT skip `validate_genie_config()` before deployment** — the Genie notebook template includes a validation cell that executes ALL example SQL queries before calling the Genie API. This is the determinism gate — it catches SQL with wrong column names before they become broken Genie examples. If validation fails, FIX the SQL, do not proceed.
18. **DO NOT use `execute_python` for writing YAML/JSON files to /Workspace paths** — `execute_python` runs in a local subprocess where /Workspace paths are NOT accessible as local filesystem paths. Use `write_workspace_file` tool to save artifacts. For YAML serialization, build the YAML string in `execute_python`, then pass the result to `write_workspace_file`. DO NOT use `open('/Workspace/...')` inside `execute_python`.
19. **DO NOT define threshold numbers locally** — every Genie minimum, rate, and correction limit
    comes from the authenticated Step-0 effective quality policy.
20. **DO NOT reinterpret benchmark outcomes locally** — comparators, actions, manifest permission,
    validation status, and stage status come from frozen `benchmark_outcomes`.

### HARD STOP RULE: No Divergence from This Prompt

If the executing agent:
- Uses `createAsset(assetType="genie")` instead of the Genie Management API → **INVALID**
- Skips reading `genie_space_configuration.md` and constructs payload from memory → **INVALID**
- Calls `POST /api/2.0/genie/spaces` without a complete `serialized_space` → **INVALID**
- Omits instructions, sample questions, or example SQL from the payload → **INVALID**
- Includes example SQL that was NOT executed and validated first → **INVALID**
- Skips the template-based notebook and writes one from scratch → **INVALID**
- Fails to use `deploy_from_template` for Genie notebook creation → **INVALID**
- Creates fewer benchmark questions than frozen `run_context.validation.min_benchmark_questions` → **INVALID**

Any of these invalidate the Genie Space and require re-execution from Step 1 of this prompt.

### Minimum Configuration Requirements

A valid Genie Space MUST contain ALL of:
- Title exactly equal to `step_handoff.yaml.genie_title`
- Description (domain-specific, mentioning key metrics)
- Table identifiers (metric view FQN)
- Warehouse ID
- Instructions meeting frozen `run_context.validation.min_instruction_chars` with MEASURE() guidance, aggregation warnings, and a dimension list
- Sample/curated questions meeting frozen `min_sample_questions` and `min_analytical_patterns`
- Example SQL meeting frozen `min_example_sqls`, with every query validated and using MEASURE() syntax
- Benchmark questions meeting frozen `min_benchmark_questions`, using different phrasing than samples

Creating a space without ANY of these is a pipeline failure.

### Instruction Richness Requirements (Expanded)

Instructions MUST contain ALL of the following content sections (not just length):

1. **Domain introduction**: 1-2 sentences explaining what data this Genie Space provides
2. **Measure catalog**: List EVERY validated measure with a brief business meaning
3. **Dimension catalog**: List EVERY validated dimension with typical use (filter, group, slice)
4. **MEASURE() syntax rule**: Explicit statement that all measures must be queried via `MEASURE(\`measure_name\`)`
5. **Aggregation warnings**: Which measures are ratios (non-additive) and must NOT be summed
6. **Time interpretation**: Which column represents time, what format, how to do monthly aggregation
7. **Terminology**: Common business terms and their mapping to measure/dimension names

An instruction string that meets the frozen length minimum but only says "This is a claims analytics space with some metrics" → **INVALID** (fails content richness even when length passes).

### Sample Question Diversity Gate

Sample questions MUST cover at least frozen `run_context.validation.min_analytical_patterns` of these analytical patterns:

| Pattern | Example | Measures Involved |
|---------|---------|------------------|
| HEADLINE | "What is total paid amount?" | Single measure, no dimensions |
| TIME_TREND | "How has denial rate changed over time?" | Measure + temporal dimension |
| DIMENSION_BREAKDOWN | "Show paid amount by claim type" | Measure + categorical dimension |
| FILTERED | "What is clean claim rate for Institutional?" | Measure + WHERE filter |
| RANKING | "Which benefit category has the highest paid?" | Measure + ORDER BY + LIMIT |
| COMPARISON | "Compare denial rate across claim types" | Measure + multiple dimension values |
| MULTI_MEASURE | "Show paid and allowed amounts by status" | Multiple measures + dimension |
| RATIO | "What percentage of claims are denied?" | Ratio/rate measure |

If fewer than frozen `run_context.validation.min_analytical_patterns` patterns are represented → **FAIL** (regenerate with explicit pattern targeting).

Duplicate paraphrases (same pattern + same measure + same dimension) count as ONE question regardless of phrasing.

# Core Principle

Genie must consume validated semantic assets.

The dependency chain is:

```text
KPI specification
        +
step_handoff.yaml (exact identity)
        +
metric_view_validation.yaml (eligible KPI mapping)
        +
live DESCRIBE + SHOW CREATE (deployed semantics)
        ↓
Validated Genie semantic inventory
        ↓
Genie instruction design
        ↓
Sample questions
        ↓
Example question SQL
        ↓
Benchmark questions
        ↓
serialized_space
        ↓
Genie Create / Update API
        ↓
Get Genie Space with include_serialized_space=true
        ↓
Persisted configuration validation
        ↓
Benchmark validation
```

Do not skip stages.

---

# Critical Ownership Boundary

The Genie stage MUST NOT redefine metric semantics.

The Metric View layer owns:

* KPI formulas;
* aggregation semantics;
* fact grain;
* numerator/denominator logic;
* dimensional relationships;
* validated measures;
* validated dimensions.

The Genie layer owns:

* natural-language interpretation guidance;
* semantic descriptions;
* terminology and synonyms;
* question examples;
* SQL examples;
* benchmark questions;
* instructions for how users should query the validated semantic model.

If a required KPI, measure, dimension, or relationship is missing or invalid:

```text
DO NOT REPAIR IT INSIDE GENIE
```

Return the issue to the Metric View layer.

Do not compensate by querying raw tables or recreating KPI formulas inside Genie examples.

---

## MANIFEST INTEGRITY RULE (NON-NEGOTIABLE)

A Genie manifest records a validated deployment attempt and provides the `space_id` needed to locate the asset. It is not the authority for the asset's current contents. Checkpoint reuse follows `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`; whenever this or a later stage makes a current-state or current-content claim, it must first GET the live space with `include_serialized_space=true`.

**NEVER write the canonical `{genie_title}_manifest.json` unless ALL of these are true:**

1. The Genie space has been created/updated via `POST /api/2.0/genie/spaces` with a FULL `serialized_space` payload
2. `validate_genie_from_api(workspace_client, space_id, title, validation=..., expected=...)` from the digest-attested `gate_checks.py` has been called and returned a mapping with `status: PASS`, `source: api_readback`, `workspace_host_binding: PASS`, exact `space_id`/`title`, and the canonical `readback_counts`; the persisted validation artifact separately records `overall_status: PASS`
3. The API readback confirmed all frozen `run_context.validation` minima and exact normalized set equality for every expected Metric View attachment
4. The manifest includes `validation_source: api_readback`
5. The manifest's `sample_questions_count`, `example_sqls_count`, `benchmarks_count` come from the **API readback** result, NOT from counting Python variables
6. The manifest and matching validation artifact contain the exact authenticated quality-contract
   tuple/effective-policy hash, and their benchmark outcome/action/stage status match the selected
   frozen rule with `manifest_allowed: true`

**A manifest whose counts differ from API readback is invalid.** Requested or in-memory counts never
override the full-GET evidence.

The single canonical manifest schema is defined in Step 22. Do not create an alternate early-stage schema. Every persisted-content count and identity in that schema comes from `validate_genie_from_api()` full-GET evidence, never agent memory.

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
2. Re-authenticate the canonical `run_context_path`, handoff, Metric View producer checkpoint,
   raw handoff hash, canonical plan-payload hash, capability tuple, and matching durable producer
   phase. Also authenticate the raw Genie quality contract and complete effective-policy hash. Do
   this before considering any Genie checkpoint.
3. Manage `run_context.yaml` per `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md` Section 8.
4. Recompute each candidate record's exact producer/frozen-run, mandatory input, and output
   fingerprints, then apply its phase-specific check:
   - `profile_metrics`: `genie_semantic_inventory.yaml` is structurally valid, current-run bound, and current catalog readback matches its stored output/readback fingerprints.
   - `design_instructions`: `llm_genie_design.yaml` is current-run bound, echoes the exact quality-contract/effective-policy tuple, and its instructions, descriptions, and sample questions meet every frozen gate.
   - `generate_sql`: the current design's example SQL and benchmark evidence are complete, execute successfully where required, match their stored fingerprints, and carry the same quality tuple.
   - `create_genie_space`: exact Genie manifest (`{genie_title}_manifest.json`) supplies a `space_id` locator **AND** matching `{genie_title}_validation.yaml` binds that ID/title, has `source: api_readback`, records the selected rule's validation status/outcome/action/stage status, and normalized full GET matches the stored output fingerprint.
   - **IMPORTANT:** A manifest is always locator/deployment-attempt evidence, even when it says `validation_source: api_readback`. Run or load the separate matching full-GET validation before skipping. If readback fails, invalidate from the earliest affected owning phase; HALT on identity/ownership conflict rather than blindly recreating.
   - `validate_genie`: `{genie_title}_validation.yaml` binds the exact ID/title, has `source: api_readback`, carries the authenticated quality tuple and contract-resolved accepted outcome, and matches current normalized full GET.
5. Skip only current `VALID` records that pass every check; otherwise continue from the earliest
   `STALE` or absent reusable phase.
6. Atomically maintain the exact current checkpoint record in `run_context.yaml` at each reusable
   phase boundary.

**Rules:**

- A `report_progress(status="completed")` event is not reusable until the exact fingerprinted
  phase record is durably persisted.
- **Never re-execute a phase whose fingerprint gate and required full-GET readback verification both pass.**
- **Never SKIP validation just because a manifest exists — require the separate matching readback comparison.**
- For Genie spaces, use a manifest `space_id` only as a locator. **UPDATE** only after full GET resolves it and confirms the exact frozen handoff title. If it is missing or identity-mismatched, do not update it; follow the frozen Genie create/idempotency policy or HALT on conflicting ownership evidence.
- If `RESUME_CONTEXT` is provided, use it only to locate candidates; authenticate and recompute from
  the durable run context, frozen dependencies, exact artifacts, and current full GET.
- `design_instructions`, `generate_sql`, `create_genie_space`, and `validate_genie` each fingerprint
  the exact raw quality-contract bytes and the canonical effective-policy value as mandatory direct
  inputs. A mismatch invalidates that phase and all transitive dependents.

**Artifact-as-State mapping:**

| Exact `phase_id` | Artifact | Additional phase-specific skip check after the fingerprint gate |
|-------|----------|----------|
| load_inputs | Config + contracts loaded | Never reusable; always re-read (stateless) |
| profile_metrics | genie_semantic_inventory.yaml + current catalog readback | structural/current-run binding and exact observed Metric View surface match |
| design_instructions | llm_genie_design.yaml | exact quality tuple/effective snapshot + instructions/descriptions/questions meet all frozen gates |
| generate_sql | llm_genie_design.yaml + executed SQL/benchmark evidence | exact quality tuple + complete examples/benchmarks + required execution checks pass |
| create_genie_space | `{genie_title}_manifest.json` locator + `{genie_title}_validation.yaml` | exact ID/title/full GET + quality tuple + contract-selected accepted outcome/action/status |
| validate_genie | `{genie_title}_validation.yaml` + current full GET | exact ID/title/content/count binding + quality tuple + contract-selected accepted outcome/action/status |

---

# KPI-Driven Genie Design (Mandatory)

Genie Space configuration is the intersection of field-scoped authorities:

| Authority | Contribution to Genie configuration |
|-----------|-------------------------------------|
| KPI specification | Business definitions, analytical intent, terminology, and requested slicing |
| `step_handoff.yaml` | Exact Genie title, warehouse, and Metric View FQNs |
| `metric_view_validation.yaml` | Only `IMPLEMENTED_AND_VALIDATED` KPIs and their Metric View assignments |
| Live `DESCRIBE TABLE` and `SHOW CREATE TABLE` | Actual deployed aliases, types, measures, dimensions, and expressions |
| Runtime profiling queries | Actual categorical values used in filter examples |
| Frozen Genie quality policy | Executable minimums, benchmark predicates/actions, manifest permission, and stage status |

The plan and design artifacts explain intended architecture, but they cannot override the handoff identity, KPI validation state, or live deployed Metric View definition.

The Genie configuration is the INTERSECTION of these authorities:

```text
KPI Spec says: "Users should be able to ask about denial rates by LOB"
DESCRIBE says: measure=denial_rate, dimension=line_of_business, values=['Commercial','Medicare','Medicaid']
→ Instruction: "denial_rate measures the percentage of denied claim lines. Can be grouped by line_of_business."
→ Sample question: "What is the denial rate for Commercial claims?"
→ Example SQL: SELECT MEASURE(denial_rate) FROM mv WHERE line_of_business = 'Commercial'
```

### Prohibited (No Making Things Up)

```text
✗ Inventing KPIs not in metric_view_validation.yaml
✗ Inventing dimensions not in DESCRIBE output
✗ Inventing filter values not discovered during profiling
✗ Using assumed column names (service_month, claim_month, etc.) without DESCRIBE verification
✗ Generating sample questions about measures/dimensions that don't exist
✗ Including example SQL that hasn't been validated on the warehouse
✗ Adding instructions about capabilities the metric view doesn't support
✗ Using shortened/semantic column names from memory instead of exact DDL names
✗ Creating sample questions for KPIs whose exact current-run `metric_view_validation.yaml` status is NOT_IMPLEMENTED or SKIPPED
✗ Mixing measures from different metric views in a single example SQL query
```

Every instruction, sample question, and example SQL must trace to business intent in the KPI specification, an eligible KPI assignment in `metric_view_validation.yaml`, and actual deployed aliases/semantics from live Metric View inspection. If it cannot be traced across those authorities, it must not be included.

### Multi-Metric View Instructions

When multiple Metric Views exist in the validated `step_handoff.yaml` FQN set, use `metric_view_plan.yaml` only for intended purpose/grain context. The Genie instructions MUST include:

1. **Metric view catalog** — list each metric view with its purpose and the KPI categories it covers
2. **Which metric view to query** — for each KPI category, specify which metric view FQN to use
3. **Cross-metric-view guidance** — explain that measures from different metric views cannot be mixed in a single query
4. **Common dimensions** — document shared dimensions (e.g., `service_month`) that enable cross-view filtering

Example instruction snippet:
```text
This analytics space has 2 metric views:
- `member_claims_metric_view_v2`: For claims metrics (Total Claims, Paid Amount, Denial Rate, etc.)
- `member_enrollment_metric_view_v2`: For enrollment metrics (Active Members, Member Months, etc.)

Always query the correct metric view for the KPI category.
Do NOT combine measures from different metric views in a single SELECT statement.
```

### Column Name Source of Truth (DETERMINISM RULE)

**Column names used anywhere in the Genie configuration (instructions, SQL, questions) MUST come from deployed Metric View inspection:**

| Source | What it provides |
|--------|------------------|
| `DESCRIBE TABLE {metric_view_fqn}` | Exact measure and dimension column names |
| `SHOW CREATE TABLE {metric_view_fqn}` | Persisted measure, dimension, expression, and relationship semantics |

`genie_semantic_inventory.yaml` is a derived working inventory of those inspected values. `metric_view_design.yaml` is design intent. Neither may override the live definition.

**NEVER** derive column names from:
- The KPI spec text (it uses business language, not DDL names)
- Memory of similar healthcare schemas
- Assumed abbreviation patterns
- Prior examples in this prompt (they are illustrative patterns, NOT actual names)

**Required sequence for every SQL you write:**
```text
1. Inspect the handoff FQN with `DESCRIBE TABLE` and `SHOW CREATE TABLE`
2. Record the deployed alias in `genie_semantic_inventory.yaml`
3. Use that exact deployed alias in the SQL
4. `validate_genie_config()` executes the SQL to confirm correctness
```

---

# Step 1: Load Inputs

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "load_inputs"
> - `phase_name`: "Load Inputs"
> - `status`: "started"
> - `current_task`: "Loading configuration and semantic contracts"
> - `happenings`: ["Comparing requested configuration", "Loading frozen run configuration", "Loading metric view contracts"]

Read:

```text
accelerator.yaml
{OUTPUT_FOLDER}/run_context.yaml
```

Treat `accelerator.yaml` only as requested configuration and drift evidence. Use current-run `run_context.llm`, `run_context.validation`, `run_context.quality_gates`, and `run_context.templates` for execution-affecting settings. Do not resolve or override asset identities from the request file; exact FQNs, title, warehouse, and version values come from `step_handoff.yaml`.

Load the **Genie Space configuration contract** (`genie_space_configuration.md`):

1. **Check first:** A system section labeled `--- BEGIN inputs/genie_space_configuration.md ---` may substitute for a file read only when its injection metadata binds it to the exact frozen `run_context.inputs.genie_space_configuration` reference. A label without matching provenance is not authoritative; read the frozen path instead. A conflicting provenance value is `GENIE_API_CONTRACT_AUTHORITY_ERROR`; HALT.
2. **Otherwise read it** from:
   ```text
   {run_context.inputs.genie_space_configuration.path}
   ```

This file is mandatory.

It is the project-level contract for:

* Genie `serialized_space` construction;
* template structure;
* configuration fields;
* API helper usage;
* validation expectations;
* forbidden shortcuts.

Do not construct `serialized_space` from model memory.

### If `genie_space_configuration.md` is missing

If no provenance-bound supplement is present and the exact frozen path above is unreadable:

```text
❌ EXECUTION HALTED
Required configuration file not found: genie_space_configuration.md
Cannot construct serialized_space without project-level serialization contract.
```

Do not fall back to guessing the serialized_space format. This file defines the exact payload structure, API field names, and helper function contracts that vary between projects.

---

# Step 1.1: Load Semantic Contracts

Read when available:

```text
{OUTPUT_FOLDER}/metric_views/schema_profile.yaml
{OUTPUT_FOLDER}/metric_views/kpi_metric_mapping.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml
{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml
```

These artifacts record Metric View intent and validation results. Their authority is field-scoped: `metric_view_validation.yaml` owns KPI status and assignment; plan/design artifacts describe intent. Live inspection of each exact handoff FQN owns the deployed aliases and semantics.

Metric Views must already exist.

If required Metric Views are missing:

```text
❌ EXECUTION HALTED
Required deployed Metric View is missing.
Return control to the orchestrator so the Metric View stage can be rerun.
```

The Genie stage MUST NOT recreate or repair the Metric View locally.

---

# Step 1.2: Determine Eligible Semantic Assets

Only consume Metric Views that were successfully created and validated.

For KPIs, only use:

```text
IMPLEMENTED_AND_VALIDATED
```

KPIs from:

```text
metric_view_validation.yaml
```

Do NOT include skipped or failed KPIs in:

* Genie instructions;
* sample questions;
* SQL examples;
* benchmarks.

Do NOT silently repair failed KPIs in Genie.

---

# Step 1.3: Resolve Runtime Configuration

Read connection/runtime identity only from the frozen current-run contracts:

```text
run_context.yaml runtime.user_name
step_handoff.yaml workspace_host
```

The authenticated SDK profile is an execution credential, not configuration authority. Validate that its effective workspace agrees with `step_handoff.yaml.workspace_host`; on mismatch, HALT instead of changing the resolved host locally.

Read resolved asset identity only from `step_handoff.yaml`:

```text
SPACE_TITLE = genie_title
WAREHOUSE_ID = warehouse_id
TABLE_IDENTIFIERS = metric_view_fqns[].sql_fqn
VERSION_SUFFIX = version_suffix
ASSET_SUFFIX = asset_suffix
PARENT_PATH = genie_parent_path
WORKSPACE_HOST = workspace_host
```

Use the pre-resolved `PARENT_PATH` from `step_handoff.yaml.genie_parent_path`. Deployment API identity and runtime/path values come from the handoff; resolved supporting filenames such as the configuration notebook come from current-run `run_context.yaml`. Do not recompute either class from `accelerator.yaml`, `databricks.yml`, folder names, or naming rules. `SPACE_DESCRIPTION` is generated content rather than asset identity and must remain grounded in the validated KPI and deployed Metric View authorities.

Resolve executable helper trust separately and only from the frozen template contract:

```text
GATE_CHECKS_PATH = run_context.templates.gate_checks.path
GATE_CHECKS_SHA256 = run_context.templates.gate_checks.sha256
```

## API Authentication Pattern (MANDATORY)

All API calls to Databricks endpoints MUST use the authenticated SDK client:

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config

# Standard calls (Genie CRUD, SQL execution)
w = WorkspaceClient()
result = w.api_client.do("POST", "/api/2.0/genie/spaces", body={...})

# LLM calls (need longer timeout)
w_llm = WorkspaceClient(config=Config(http_timeout_seconds=600))
result = w_llm.api_client.do("POST", "/serving-endpoints/{model}/invocations", body={...})
```

**NEVER** use:
- `requests.post()` with extracted tokens
- `requests.get()` with manual Authorization headers
- `urllib` or `httpx` for API calls
- Token extraction from `dbutils.notebook.entry_point`

The SDK handles authentication automatically. Raw HTTP calls are forbidden.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "load_inputs"
> - `phase_name`: "Load Inputs"
> - `status`: "completed"
> - `findings`: ["{N} semantic assets eligible", "Runtime configuration resolved"]
> - `stats`: {"metric_views_loaded": N, "tables_eligible": M}

---

# Step 2: Profile Validated Metric Views

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "profile_metrics"
> - `phase_name`: "Profile Metrics"
> - `status`: "started"
> - `current_task`: "Building semantic inventory for Genie"
> - `happenings`: ["Querying metric view schemas", "Building Genie semantic inventory"]

## Mandatory Deployed Metric View Inspection

Prior-step artifacts never replace runtime inspection. For every exact Metric View FQN in `step_handoff.yaml`:

1. Run `DESCRIBE TABLE EXTENDED <metric_view_fqn>` to obtain deployed aliases and types.
2. Run `SHOW CREATE TABLE <metric_view_fqn>` to obtain deployed measure, dimension, expression, and relationship semantics.
3. Compare the normalized live FQN set with `step_handoff.yaml`, `metric_view_plan.yaml`, and `metric_view_validation.yaml`; require exact set equality.
4. Compare the live definition with the validated design. If an alias or semantic definition has drifted, HALT with `METRIC_VIEW_DEPLOYED_STATE_MISMATCH`; do not silently adapt Genie to an unvalidated deployment.
5. Only after these checks, run a combined SQL for row counts where practical:
   ```sql
   SELECT 'mv1' AS mv, COUNT(*) AS rows FROM `<catalog>`.`<schema>`.`<metric_view_1>`
   UNION ALL
   SELECT 'mv2', COUNT(*) FROM `<catalog>`.`<schema>`.`<metric_view_2>`
   ```
6. If any row count = 0, HALT (Zero-Data Guard).
7. Run one SQL per Metric View for categorical profiling, batching dimensions where practical:
   ```sql
   SELECT 'claim_type' AS dim, claim_type AS val FROM `<catalog>`.`<schema>`.`<metric_view>` GROUP BY claim_type LIMIT 10
   UNION ALL
   SELECT 'line_status', line_status FROM `<catalog>`.`<schema>`.`<metric_view>` GROUP BY line_status LIMIT 10
   UNION ALL ...
   ```
8. Write `genie_semantic_inventory.yaml` from the deployed readback, validated KPI mapping, KPI specification, and profiling results.

Build an inventory of:

* validated measures;
* validated dimensions;
* time dimensions;
* categorical values;
* units/formats;
* supported groupings;
* common terminology;
* KPI mappings.

Do NOT infer new measure definitions from profiling.

The live deployed definition is the truth for what currently exists. The validated design remains intent. Any difference is an upstream deployment/validation failure and must be resolved by the Metric View stage before Genie continues.

### Zero-Data Guard

For every Metric View intended for the Genie Space, execute:

```sql
SELECT COUNT(*) FROM <metric_view_fqn>
```

If result = 0:

```text
❌ EXECUTION HALTED
Metric View contains no data: {metric_view_fqn}
Genie example SQL and benchmarks will produce empty results.
Return to data layer / metric view validation.
```

Do not proceed to build instructions, examples, or benchmarks against an empty Metric View.

---

# Step 2.1: Build Genie Semantic Inventory

Create:

```text
{OUTPUT_FOLDER}/genie_space/genie_semantic_inventory.yaml
```

containing:

```yaml
metric_views:

  - fqn:
    description:

    measures:
      - name:
        description:
        datatype:
        aggregation_semantics:
        kpis_supported:
        synonyms: []

    dimensions:
      - name:
        description:
        datatype:
        sample_values:
        synonyms: []

validated_kpis:

  - name:
    definition:
    metric_view:
    measure:
    dimensions:
    time_dimension:

unsupported_kpis: []
```

This artifact is a validated, derived working inventory for Genie configuration generation. It does not override the KPI specification, handoff identity, KPI validation state, or live deployed Metric View definition.

If a live datatype conflicts with the validated Metric View intent, record the expected and
observed types and HALT with `METRIC_VIEW_DEPLOYED_STATE_MISMATCH`. Genie MUST NOT repair the
upstream defect by changing the inventory, adding `CAST`/`TRY_CAST` to example SQL, stringifying the
field, or weakening a benchmark.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "profile_metrics"
> - `phase_name`: "Profile Metrics"
> - `status`: "completed"
> - `findings`: ["{N} measures inventoried", "{D} dimensions cataloged"]
> - `stats`: {"measures": N, "dimensions": D}

---

# Step 2.2: LLM-Assisted Genie Design (MANDATORY)

Before manually writing instructions, sample questions, and example SQL, call a **reasoning model** to propose production-quality Genie configuration. This ensures:
- Domain-specific instructions (not generic boilerplate)
- Analytically diverse sample questions (not paraphrases)
- Proper MEASURE() syntax in all examples
- Aggregation semantics warnings for non-additive measures
- Natural business terminology appropriate to the domain

## Why This Step Exists

The executing agent may generate minimal instructions ("This Genie Space has metrics") and repetitive sample questions ("What is total paid? / Show total paid / How much paid?"). A reasoning model produces domain-aware, analytically rich configuration that covers multiple question patterns per KPI.

## Context Assembly (BEFORE the LLM call)

Gather all of these inputs and include them in the prompt:

| Input | Source | What It Provides |
|-------|--------|------------------|
| KPI specification | Exact frozen `run_context.inputs.kpi_spec` path | Business definitions, analytical intent, terminology |
| Metric View YAML | `SHOW CREATE TABLE {metric_view_fqn}` | Exact measure names, expressions, dimension names, MEASURE() syntax |
| Metric View validation | `metric_view_validation.yaml` | Which KPIs are IMPLEMENTED vs SKIPPED |
| Semantic inventory | `genie_semantic_inventory.yaml` | Profiled values, synonyms, data types |
| Categorical samples | From Step 2 profiling | Actual dimension values for grounded examples |

**The metric view definition is critical** — without it, the LLM may propose questions about measures that don't exist or generate SQL that misuses MEASURE() syntax.

## LLM Call Pattern

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config

w_llm = WorkspaceClient(config=Config(http_timeout_seconds=600))

# CRITICAL: Include the FULL metric view definition in context
validation_policy = run_context["validation"]
genie_design_config = run_context["llm"]["steps"]["genie_design"]
design_model = genie_design_config.get("model")
if not isinstance(design_model, str) or not design_model:
    raise RuntimeError("GENIE_LLM_CONFIGURATION_ERROR: frozen Genie design model is missing")
genie_design_prompt = f"""
You are a senior Databricks Genie Space architect.

Given the following validated semantic model, design a complete Genie Space configuration.

## Metric View Definition (COMPLETE — this is the ACTUAL view Genie will query)
~~~sql
{metric_view_ddl}
~~~

## Metric View Validation Results
KPIs implemented and validated: {implemented_kpis}
KPIs skipped (DO NOT reference these): {skipped_kpis}

## KPI Specification (business context)
{kpi_spec_content}

## Semantic Inventory
{semantic_inventory_yaml}

## Data Profile
- Row count: {row_count}
- Date range: {min_date} to {max_date}
- Categorical samples:
{categorical_samples}

## Design Requirements

### 1. General Instructions (markdown-formatted for readability)
Write comprehensive Genie instructions using markdown structure (## headers, - bullets, blank lines between sections). The instructions should:
- Introduce the analytical domain (what this data represents)
- List ALL available measures with their business meaning and aggregation semantics
- List ALL available dimensions with their purpose and sample values
- Explain MEASURE() syntax rules (MUST use MEASURE(`measure_name`) for all measures)
- Explain that aggregation and roll-up behavior must follow each KPI's validated Metric View semantics. Do not prescribe a generic `SUM`, `AVG`, or reconstruction rule from a measure label; unresolved behavior must be reported.
- Provide time interpretation guidance (which temporal column to use, date format)
- Define common business terminology and synonyms
- At least {validation_policy['min_instruction_chars']} characters; richness requirements still apply
- FORMAT: Use markdown structure — ## headers to separate sections, - bullet points for lists, blank lines between sections

### 2. Sample Questions (at least {validation_policy['min_sample_questions']}, analytically diverse)
Generate questions covering these DISTINCT analytical patterns:
- HEADLINE: "What is the total X?" (one per primary measure)
- TIME_TREND: "How has X changed over time?" / "Monthly trend for X"
- DIMENSION_BREAKDOWN: "Show X by Y" (different dimension each time)
- FILTERED: "What is X for [specific value]?" (use actual categorical values)
- RANKING: "Which [dimension] has the highest/lowest X?"
- COMPARISON: "Compare X across [dimension values]"
- MULTI_MEASURE: "Show both X and Y by Z"
- RATIO: "What is the denial rate for [segment]?"

Each question must:
- Reference ONLY measures/dimensions in the metric view
- Use actual categorical values from the data profile
- Be phrased as a business user would ask (NOT SQL syntax)
- Test a DIFFERENT analytical pattern than other questions

### 3. Example SQL (at least {validation_policy['min_example_sqls']} validated queries using MEASURE() syntax)
For each sample question, provide the correct SQL. Rules:
- ALWAYS use MEASURE(`measure_name`) — never raw SUM/COUNT
- Use backtick-quoted dimension names if they contain spaces
- Use GROUP BY ALL for dimensional queries
- Use actual filter values from the data profile
- ORDER BY for trends and rankings

### 4. Benchmark Questions (at least {validation_policy['min_benchmark_questions']}, generalization test)
Different wording than sample questions but testing the same semantic patterns.
Genie should be able to answer these WITHOUT memorizing sample phrasing.

## Output Format
Return ONLY a YAML structure (no markdown fencing) with this format:

genie_design:
  instructions: "<markdown-formatted string with ## headers and - bullets meeting the frozen minimum>"
  metric_view_description: "<2-3 sentence description of what this metric view provides>"
  sample_questions:
    - question: "<natural language question>"
      pattern: HEADLINE | TIME_TREND | DIMENSION_BREAKDOWN | FILTERED | RANKING | COMPARISON | MULTI_MEASURE | RATIO
      measures_tested: [<measure names>]
      dimensions_tested: [<dimension names>]
  example_sqls:
    - question: "<the question this SQL answers>"
      sql: "<valid SQL using MEASURE() syntax>"
  benchmark_questions:
    - question: "<differently worded question>"
      expected_measures: [<measures Genie should select>]
      expected_dimensions: [<dimensions Genie should use>]
"""

stage_instruction = run_context["llm"]["steps"]["genie_design"]["instruction"]

response = w_llm.api_client.do(
    "POST",
    f"/serving-endpoints/{design_model}/invocations",
    body={
        "messages": [
            {"role": "system", "content": f"{stage_instruction}\n\nYou are a Genie Space design architect. Follow every mandatory grounded-design rule in this stage. Output valid YAML only, with no markdown fencing or explanatory text."},
            {"role": "user", "content": genie_design_prompt},
        ],
        "max_tokens": 16000,
        "temperature": 1,
    }
)
genie_design_yaml = response["choices"][0]["message"]["content"]
```

## Model Selection

Use the already resolved model in current-run `run_context.llm.steps.genie_design.model`. Any fallback must have been resolved and frozen by Step 0; if the field is missing, HALT rather than selecting a model locally.

## Validation of LLM Output

After receiving the model's proposed design, validate:

1. **Instructions length**: >= frozen `run_context.validation.min_instruction_chars` (reject thin instructions)
2. **Instructions format**: Uses markdown structure (## headers, - bullets) for readability
3. **Instructions content**: Must mention MEASURE() syntax, list measures, list dimensions
4. **Sample question count**: >= frozen `run_context.validation.min_sample_questions`
5. **Sample question diversity**: Meet frozen `run_context.validation.min_analytical_patterns` across HEADLINE, TIME_TREND, DIMENSION_BREAKDOWN, FILTERED, RANKING, COMPARISON, MULTI_MEASURE, and RATIO
6. **Measure coverage**: Every IMPLEMENTED KPI referenced at least `run_context.validation.min_kpi_question_references` times
7. **Dimension coverage**: Every dimension meets frozen `run_context.validation.min_dimension_question_references`
8. **Example SQL validity**: Every SQL uses MEASURE() syntax (not raw SUM/COUNT)
9. **Example SQL measure names**: All referenced measures exist in the metric view
10. **No SKIPPED KPIs**: Questions/examples do NOT reference skipped KPIs
11. **Grounded filter values**: Any WHERE clause filter values match actual profiled values
12. **Benchmark distinctness**: Benchmark questions use different phrasing than sample questions

If validation fails:
- Fix obvious issues (replace non-existent measure names with correct ones)
- Re-prompt the model with specific corrections
- Do NOT accept thin/generic instructions

## Output

Save the validated design to:

```text
{OUTPUT_FOLDER}/genie_space/llm_genie_design.yaml
```

Persist a stage-owned envelope around the model's validated `genie_design` payload. It MUST record:

```yaml
genie_quality_contract_name: <frozen value>
genie_quality_contract_version: <frozen value>
genie_quality_contract_sha256: <frozen raw-byte hash>
genie_quality_policy_id: <frozen value>
genie_quality_effective_policy_sha256: <frozen canonical hash>
effective_quality_thresholds: <complete authenticated threshold map>
benchmark_outcomes: <exact frozen mapping>
genie_design: <validated model payload>
```

The stage—not the model—adds this envelope. On resume, require exact identity, effective-policy,
threshold, and outcome parity before reusing the payload.

This becomes the validated intended configuration for Steps 3-8. It remains subordinate to the KPI specification, handoff identity, KPI validation state, and deployed Metric View readback. If it conflicts with any owning authority, reject or regenerate it; never use it to redefine the authority.

## Skip Condition

Skip the LLM call and reuse `{OUTPUT_FOLDER}/genie_space/llm_genie_design.yaml` only when the owning
`design_instructions` fingerprint Resume Skip Gate passes and its instructions, sample questions,
example SQL, benchmarks, pattern coverage, and KPI/dimension coverage meet every frozen
`run_context.validation` gate. The mandatory input fingerprints include the exact raw source quality
contract and canonical effective-policy snapshot, and the design envelope must echo both hashes.
File existence alone never authorizes reuse.

---

# Step 3: Design Genie Instructions

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "design_instructions"
> - `phase_name`: "Design Instructions"
> - `status`: "started"
> - `current_task`: "Building Genie instructions, samples, and descriptions"
> - `happenings`: ["Writing system instructions", "Generating sample questions", "Creating metric descriptions"]

## GATE 2.2: LLM Design Validation

Before proceeding to Step 3, verify the LLM design artifact:

```python
# Pseudocode — execute this validation
validation_policy = run_context['validation']
assert_quality_contract_authenticated(run_context)  # exact raw source + effective-policy hashes
assert llm_design_artifact['genie_quality_contract_sha256'] == validation_policy['genie_quality_contract_sha256']
assert llm_design_artifact['genie_quality_effective_policy_sha256'] == validation_policy['genie_quality_effective_policy_sha256']
assert llm_design_artifact['benchmark_outcomes'] == validation_policy['benchmark_outcomes']
llm_design = llm_design_artifact['genie_design']
assert len(llm_design['instructions']) >= validation_policy['min_instruction_chars'], "Instructions too short"
assert 'MEASURE' in llm_design['instructions'], "Instructions don't mention MEASURE() syntax"
assert '##' in llm_design['instructions'], "Instructions should use markdown headers for structure"
assert len(llm_design['sample_questions']) >= validation_policy['min_sample_questions'], "Too few sample questions"
patterns = set(q['pattern'] for q in llm_design['sample_questions'])
assert len(patterns) >= validation_policy['min_analytical_patterns'], "Too few analytical patterns"
assert len(llm_design['example_sqls']) >= validation_policy['min_example_sqls'], "Too few example SQL queries"
for sql in llm_design['example_sqls']:
    assert 'MEASURE' in sql['sql'].upper(), f"SQL missing MEASURE(): {sql['sql'][:50]}"
assert len(llm_design['benchmark_questions']) >= validation_policy['min_benchmark_questions'], "Too few benchmarks"
```

If ANY assertion fails:
```text
❌ GATE 2.2 FAILED: LLM design does not meet quality requirements
Failing check: <which assertion>
Action: Re-prompt the model with specific correction guidance
```

Do NOT proceed to Step 3 until GATE 2.2 passes.

---

Use the validated LLM design from Step 2.2 as the intended source for instructions, questions, and SQL. Do not discard or thin out its content, but reject or regenerate any part that conflicts with an owning authority.

Generate `GENERAL_INSTRUCTIONS` from:

```text
genie_semantic_inventory.yaml
+
KPI specification
+
metric_view_validation.yaml
```

Do not use generic boilerplate unrelated to the current domain.

Instructions should help Genie understand:

* the analytical domain;
* authoritative Metric Views;
* measure meanings;
* dimensional meanings;
* business terminology;
* common synonyms;
* time interpretation;
* metric-selection rules;
* ambiguity resolution;
* expected use of `MEASURE()`.

### Critical: Instructions String Format

The Genie Space API `text_instructions[].content[]` field supports **markdown formatting**. Use markdown structure for readability:

```text
✓ Use ## headers to separate sections (Domain, Measures, Dimensions, Rules)
✓ Use - bullet points to list measures and dimensions
✓ Use blank lines between sections
✓ Use `backticks` for measure/dimension names
```

Example structure:

```markdown
## Domain
This Genie Space provides healthcare claims analytics...

## Measures (use MEASURE(`name`) syntax)
- `Total Paid Amount` — sum of insurer-paid dollars
- `Denial Rate` — percentage of denied lines (non-additive; follow its validated Metric View semantics)

## Dimensions
- `Claim Type`: Professional, Institutional, Pharmacy, Dental, Vision

## Query Rules
- Always use MEASURE(`measure_name`) — never raw SUM() or COUNT()
```

This renders properly in the Genie admin UI with clear visual structure.

---

# Step 3.1: Instruction Requirements

Instructions must clearly state:

1. Which Metric Views are authoritative.

2. Which measures are available.

3. What each measure means.

4. Which dimensions can be used for:

   * filtering;
   * grouping;
   * slicing.

5. How time questions should map to available date/time dimensions.

6. How ambiguous business terms should be interpreted when supported by the KPI specification.

7. That validated measures must be queried using Metric View semantics.

8. That raw source-table reconstruction of validated KPIs is prohibited.

---

# Do Not Over-Instruct

Do not create instructions that:

* restate every SQL query;
* encode hundreds of brittle column-specific rules;
* invent business rules not present in the KPI/semantic contracts;
* tell Genie to guess missing relationships;
* duplicate Metric View formulas.

The Metric View remains the semantic computation layer.

Genie instructions should guide interpretation, not recreate the semantic model.

---

# Step 4: Create Metric View Descriptions

Generate:

```text
METRIC_VIEW_DESCRIPTIONS
```

for every attached Metric View.

Descriptions should explain:

```text
business purpose
primary analytical grain
major measure families
major dimensions
typical questions answered
```

Do not simply repeat the FQN or table name.

Example conceptual format:

```python
{
    "catalog.schema.metric_view": (
        "Provides validated analytical measures for ... "
        "at the ... grain, with dimensions for ..."
    )
}
```

Keys must be deterministic and sorted where required by the template.

---

# Step 5: Generate Sample Questions

Generate representative natural-language questions based only on:

```text
IMPLEMENTED_AND_VALIDATED KPIs
+
validated dimensions
+
validated measures
```

Generate at least frozen `run_context.validation.min_sample_questions` high-quality sample questions when that minimum can be grounded in distinct, meaningful semantic combinations.

Do not artificially generate low-quality duplicates solely to satisfy the frozen minimum.

If fewer meaningful combinations exist, report the limitation and follow the configured minimum validation policy.

---

# Step 5.1: Sample Question Coverage

Questions should collectively cover:

* headline measures;
* time trends;
* dimension breakdowns;
* filtered analysis;
* rankings / Top-N where appropriate;
* comparisons;
* ratios where validated;
* multiple measures where analytically meaningful.

Avoid superficial paraphrase duplication.

Bad:

```text
What is total revenue?
Show total revenue.
Tell me total revenue.
How much total revenue?
```

These count as essentially one semantic pattern.

Prefer diversity of analytical intent.

### Question Quality Criteria

Every sample question must be:

1. **Answerable** — resolvable to one SQL query against the validated Metric View.
2. **Specific** — specifies a concrete analytical intent (not "tell me about claims").
3. **Grounded** — references only measures/dimensions in `genie_semantic_inventory.yaml`.
4. **Distinct** — tests a different analytical pattern than other questions in the set.
5. **Natural** — phrased as a business user would ask (not SQL syntax disguised as English).

Bad:

```text
"Show me the MEASURE(total_paid) grouped by claim_type"  ← SQL disguised as English
"Tell me about the data"  ← not specific
"What is the YTD revenue adjusted for inflation?"  ← not answerable (no inflation measure)
```

Good:

```text
"What is the average paid amount per claim this year?"
"Which states have the highest denial rate?"
"How has PMPM trended over the last 12 months?"
```

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "design_instructions"
> - `phase_name`: "Design Instructions"
> - `status`: "completed"
> - `findings`: ["Instructions generated", "{N} sample questions created", "Metric descriptions written"]
> - `stats`: {"sample_questions": N, "metric_descriptions": M}

---

# Step 6: Generate Example Question SQL

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "generate_sql"
> - `phase_name`: "Generate SQL & Benchmarks"
> - `status`: "started"
> - `current_task`: "Generating example SQL and benchmark questions"
> - `happenings`: ["Writing example SQL queries", "Validating SQL execution", "Generating benchmark ground truth"]

Generate:

```text
EXAMPLE_QUESTION_SQLS
```

using validated Metric Views only.

Generate at least frozen `run_context.validation.min_example_sqls` examples. Add more only where they provide meaningful additional coverage; never introduce a local numeric target.

Every SQL example MUST execute successfully before inclusion.

---

# Step 6.1: SQL Rules

Use:

```sql
MEASURE(...)
```

for Metric View measures.

Use the Metric View's validated dimensions.

Do NOT:

* query raw source tables to recreate KPIs;
* invent columns;
* invent joins;
* bypass Metric View calculations;
* use measures that failed validation.

Use:

```sql
GROUP BY ALL
```

where appropriate and required by project conventions.

### Reference SQL Patterns for Example Questions

**CRITICAL: Column names below are PATTERNS ONLY. Replace with actual measure/dimension names from DESCRIBE output (Step 2) and `genie_semantic_inventory.yaml`. Never assume a column exists — verify against the profiled inventory.**

```sql
-- Headline KPI ("What is total paid amount?")
SELECT MEASURE(total_paid) AS total_paid
FROM `<catalog>`.`<schema>`.`<metric_view>`

-- Time trend ("Show monthly paid trend")
-- NOTE: Use actual temporal dimension from DESCRIBE (e.g., service_date)
-- If monthly aggregation needed, use DATE_TRUNC:
SELECT DATE_TRUNC('MONTH', service_date) AS service_month, MEASURE(total_paid) AS total_paid
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY ALL
ORDER BY service_month

-- Dimension breakdown ("Total paid by claim type")
SELECT claim_type, MEASURE(total_paid) AS total_paid
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY ALL

-- Filtered ("Total paid for Medicare members")
-- NOTE: Use actual dimension values from profiling (Step 2)
SELECT MEASURE(total_paid) AS total_paid
FROM `<catalog>`.`<schema>`.`<metric_view>`
WHERE line_of_business = 'MEDICARE'

-- Top-N ("Top 5 states by claims count")
SELECT member_state, MEASURE(total_claims) AS total_claims
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY ALL
ORDER BY total_claims DESC
LIMIT 5

-- Multi-measure ("Show paid and denied amounts by LOB")
SELECT line_of_business,
       MEASURE(total_paid) AS total_paid,
       MEASURE(denial_rate) AS denial_rate
FROM `<catalog>`.`<schema>`.`<metric_view>`
GROUP BY ALL
```

### Column Name Resolution (MANDATORY)

Do NOT copy these patterns verbatim. Every example SQL must use:

1. **Actual measure names** from `genie_semantic_inventory.yaml` (sourced from DESCRIBE)
2. **Actual dimension names** from `genie_semantic_inventory.yaml` (sourced from DESCRIBE)
3. **Actual filter values** from metric view profiling (Step 2)

Common violations that WILL cause SQL failures:

```text
✗ service_month     → does not exist; use DATE_TRUNC('MONTH', service_date) if MV has service_date
✗ claim_month       → does not exist; check DESCRIBE for actual temporal dimensions
✗ member_name       → may not exist; check DESCRIBE for actual column names
✗ 'MEDICARE'        → may not be a valid value; profile actual categorical values first
```

If a SQL pattern references a column that does not appear in `genie_semantic_inventory.yaml`, it is INVALID and must not be included.

### Determinism Gate: `validate_genie_config()` (MANDATORY)

The Genie notebook template (`v2_genie_space_notebook.py.template`) includes a **validation cell** that runs BEFORE the Create/Update API call. This cell:

1. Verifies all `TABLE_IDENTIFIERS` are accessible
2. **Executes every example SQL query** with `LIMIT 1` to confirm it runs without error
3. Checks sample question count and instruction length
4. **RAISES AssertionError** if any SQL fails (preventing deployment of broken examples)

This is the programmatic enforcement of column name correctness:

```text
LLM writes SQL with wrong column name (e.g., "service_month")
  → validate_genie_config() executes it
  → Spark raises UNRESOLVED_COLUMN
  → AssertionError with "Example SQL #3 failed: ..."
  → Notebook halts BEFORE API call
  → LLM fixes the SQL using correct column from DESCRIBE
```

**Prompt + Validation = Deterministic:**
- The prompt instructs the LLM to use correct names (~98% success)
- The validation catches the remaining ~2% before deployment
- Result: Every deployed Genie space has working example SQL, guaranteed

The LLM MUST:
1. Get actual column names from `DESCRIBE TABLE` / inventory FIRST
2. Use those exact names in all example SQL
3. Let the validation cell confirm correctness before proceeding

---

# Step 6.2: SQL Validation (BATCH — saves 15+ tool calls)

**CRITICAL EFFICIENCY RULE:** Do NOT validate example SQL queries one-by-one. Batch validate using this safe pattern:

```sql
-- Wrap each query as an existence check (always returns 1 column — compatible for UNION ALL)
SELECT 'q1' AS qid, CASE WHEN cnt > 0 THEN 'PASS' ELSE 'EMPTY' END AS status FROM (SELECT COUNT(*) AS cnt FROM (SELECT MEASURE(total_paid) AS total_paid FROM `<catalog>`.`<schema>`.`<metric_view>`))
UNION ALL
SELECT 'q2', CASE WHEN cnt > 0 THEN 'PASS' ELSE 'EMPTY' END FROM (SELECT COUNT(*) AS cnt FROM (SELECT claim_type, MEASURE(total_paid) AS total_paid FROM `<catalog>`.`<schema>`.`<metric_view>` GROUP BY ALL))
UNION ALL
SELECT 'q3', CASE WHEN cnt > 0 THEN 'PASS' ELSE 'EMPTY' END FROM (SELECT COUNT(*) AS cnt FROM (SELECT service_month, MEASURE(claim_count) FROM `<catalog>`.`<schema>`.`<metric_view>` GROUP BY ALL))
```

**Why this pattern works:** Every SELECT in the UNION ALL returns exactly 2 columns (`qid STRING, status STRING`) regardless of how many columns the inner query produces. This avoids UNION column-count mismatch errors.

**DO NOT use `SELECT *, ...` in UNION ALL batches** — different queries have different column counts and will cause PARSE_SYNTAX_ERROR.

This reduces many individual `execute_sql` calls to a small number of batched validations.

Use:

```text
sql_warehouse_id
```

Validate:

```text
SQL executes (no UNRESOLVED_COLUMN errors)
required measure exists
required dimensions exist
result is non-empty where data exists
result shape matches question
```

Failed SQL examples must be corrected or removed.

Never include untested example SQL.

---

# Step 7: Generate Benchmark Questions

Generate:

```text
BENCHMARK_QUESTIONS
```

using different wording and analytical formulations from the example questions.

Benchmarks should test whether Genie can generalize rather than memorize sample phrasing.

Generate at least frozen `run_context.validation.min_benchmark_questions` benchmarks. Add more only when they provide meaningful additional coverage; never introduce a local numeric target.

---

# Benchmark Design Principles

Benchmarks should include a mix of:

```text
DIRECT KPI
DIMENSION BREAKDOWN
TEMPORAL
FILTERED
COMPARISON
RANKING
MULTI-MEASURE
AMBIGUITY / SYNONYM
```

where supported.

Avoid benchmarks that depend on:

* unavailable measures;
* unsupported dimensions;
* raw-table semantics;
* business rules absent from the semantic model.

---

# Step 8: Benchmark Ground Truth

Where the template/configuration supports expected SQL or expected analytical output, derive benchmark ground truth from the validated Metric Views.

Do not use LLM-generated expected values without executing the authoritative query.

Conceptually:

```text
BENCHMARK QUESTION
        ↓
authoritative Metric View SQL
        ↓
expected semantics/result
```

Store benchmark ground truth in the format required by:

```text
genie_space_configuration.md
```

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "generate_sql"
> - `phase_name`: "Generate SQL & Benchmarks"
> - `status`: "completed"
> - `findings`: ["{N} example queries validated", "{B} benchmark questions generated"]
> - `stats`: {"example_queries": N, "benchmarks": B, "sql_validations_passed": V}

---

# Step 9: Create Configuration Notebook

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "create_genie_space"
> - `phase_name`: "Create Genie Space"
> - `status`: "started"
> - `current_task`: "Creating Genie space via API"
> - `happenings`: ["Deploying notebook from template", "Constructing space payload", "Calling Genie API"]

Create the notebook at:

```text
{OUTPUT_FOLDER}/genie_space/{run_context.assets.genie.notebook_name}
```

by calling the `deploy_from_template` tool:

```
deploy_from_template(
  template_path = run_context["templates"]["genie_notebook"]["path"],
  output_path  = "{OUTPUT_FOLDER}/genie_space/{run_context.assets.genie.notebook_name}",
  placeholders = {
    "RUN_CONTEXT_PATH": "<exact supplied run_context_path>",
    "RUN_CONTRACT_PATH": "<run_context.templates.run_contract.path>",
    "RUN_CONTRACT_SHA256": "<run_context.templates.run_contract.sha256>",
    "DOMAIN_NAME": "...",
    "SPACE_TITLE": "...",
    "SPACE_DESCRIPTION": "...",
    "WAREHOUSE_ID": "...",
    "PARENT_PATH": "<exact step_handoff.yaml genie_parent_path>",
    "GATE_CHECKS_PATH": "<exact run_context.templates.gate_checks.path>",
    "GATE_CHECKS_SHA256": "<exact run_context.templates.gate_checks.sha256>",
    "TABLE_IDENTIFIERS": [...],
    "GENERAL_INSTRUCTIONS": "...",
    "METRIC_VIEW_DESCRIPTIONS": {...},
    "SAMPLE_QUESTIONS": [...],
    "EXAMPLE_SQLS": [...],
    "BENCHMARK_QUESTIONS": [...],
  }
)
```

The tool reads the template verbatim, performs placeholder substitution, and
creates the notebook. Cells 8-10 (helpers, API call, validation) are guaranteed
unchanged from the template — the LLM never touches them.

Do not copy `gate_checks.py` to the output folder. The frozen template must verify the raw source
bytes against `GATE_CHECKS_SHA256`, copy only the verified bytes to
`/tmp/pipeline_python/{sha256_prefix}/gate_checks.py`, and load that exact file with
`importlib.util.spec_from_file_location()` under a digest-qualified module name. It must verify
the copied file's raw SHA-256 again, attest the loaded module's resolved `__file__`, retain the
module object, and obtain all helper callables and `GateCheckError` from that object. A
compatibility alias in `sys.modules` is allowed only
after this attestation and only for a verified helper's internal imports; it is never a discovery
mechanism.

Never use `dbutils.fs` for `/Workspace/`.

---

# Step 9.1: Template Guarantees (Automatic)

The `deploy_from_template` tool reads the exact frozen current-run template at:

```text
run_context.templates.genie_notebook
```

and performs deterministic placeholder substitution. The LLM does NOT read
the template or manipulate its content. This guarantees cells 8-10 are
verbatim from the template (G-16 enforcement).

---

# Step 9.2: Placeholder Values (LLM-Generated Config)

The LLM generates the following values (from Phases A-C) and passes them as
the `placeholders` dict to `deploy_from_template`:

| Placeholder | Source | Format |
|-------------|--------|--------|
| DOMAIN_NAME | `run_context.yaml domain.name` | string |
| SPACE_TITLE | step_handoff.yaml genie_title | string (versioned) |
| SPACE_DESCRIPTION | LLM-generated | string |
| WAREHOUSE_ID | step_handoff.yaml | string |
| PARENT_PATH | `step_handoff.yaml genie_parent_path` | string |
| GATE_CHECKS_PATH | `run_context.templates.gate_checks.path` | exact canonical string |
| GATE_CHECKS_SHA256 | `run_context.templates.gate_checks.sha256` | 64-character lowercase hexadecimal digest |
| TABLE_IDENTIFIERS | step_handoff.yaml metric_view_fqns | Python list literal |
| GENERAL_INSTRUCTIONS | LLM Phase B output | multi-line string |
| METRIC_VIEW_DESCRIPTIONS | LLM Phase A output | Python dict literal |
| SAMPLE_QUESTIONS | LLM Phase B output | Python list literal |
| EXAMPLE_SQLS | LLM Phase B output (validated) | Python list of tuples |
| BENCHMARK_QUESTIONS | LLM Phase B output | Python list of tuples |

All placeholders must be resolved — no `{{...}}` may remain after substitution.

---

# Step 9.3: Infrastructure Cells (Guaranteed Verbatim)

Cells 8-10 (helper functions, create/update API call, validation) are copied
verbatim from the template by `deploy_from_template`. The LLM must NOT modify
these cells. The template includes:
- `build_serialized_space()` with correct `"metric_views"` key (NOT `"tables"`)
- Format validation guard that asserts `data_sources` contains `"metric_views"`
- Digest-qualified pre-deploy and post-deploy gate enforcement via the exact pinned `gate_checks.py`

Before any API operation, attest that the loaded helper exposes the exact required callable
surface, including `run_genie_predeploy_gates` and `validate_genie_from_api`, and that the
validator accepts the frozen client/host binding used by this run. Any incompatibility is
`GENIE_HELPER_CONTRACT_ERROR`; do not replace the canonical validator with inline or manual logic.

The final API operation conforms to the official Databricks Genie management API contract.

---

# Step 10: Build serialized_space

Construct:

```text
serialized_space
```

using the builder/helper defined in:

```text
genie_space_configuration.md
```

and the configured template.

### Approved Schema Reference

Runtime serialization authority is the approved, versioned `genie_space_configuration.md` plus the deterministic deployment template. The official Databricks documentation URL is recorded for the release refresh workflow:

```text
https://docs.databricks.com/aws/en/genie-agents/conversation-api#understanding-the-serialized_space-field
```

During contract refresh, use that official reference to review:

* the complete field structure (version, config, data_sources, instructions, benchmarks);
* required vs optional fields;
* correct nesting and array formats;
* field semantics and behavior.

Do NOT construct the payload from LLM memory or prior examples alone. During a run, validate against the approved local contract/template and then the persisted API readback. If the workspace rejects that approved structure in a way indicating contract drift, HALT with `GENIE_SERIALIZATION_CONTRACT_DRIFT`; do not browse or reinterpret live documentation inside the run.

### Required Sections

The serialization must include all required configuration, including the appropriate combination of:

```text
version (currently 2)
config.sample_questions
data_sources.metric_views (metric views are listed here — NOT data_sources.tables)
instructions.text_instructions
instructions.example_question_sqls
benchmarks.questions
```

**CRITICAL:** The serialized_space POST/PATCH body MUST use `data_sources.metric_views`.
The GET readback response renames this to `data_sources.tables`, but the
POST/PATCH must use `metric_views`. Using `tables` in the serialized_space
causes `BadRequest: The zip archive contains no items`.

as defined by the current project contract and the docs schema.

### Critical API Behaviors (Learned from Deployment)

| Field | Behavior | Fix |
|-------|----------|-----|
| `data_sources` | POST/PATCH uses `metric_views` key; GET readback renames to `tables` | Use `data_sources.metric_views[]` in serialized_space |
| `text_instructions[].content[]` | Supports markdown formatting (## headers, - bullets, newlines, `backticks`) | Use markdown structure for readability |
| `column_configs[]` | Must be sorted alphabetically by `column_name` or API rejects with InvalidParameterValue | Sort before submission |
| All IDs | Must be 32-character lowercase hex UUIDs | Use `uuid.uuid4().hex` |
| All text fields | Wrapped in arrays `["text"]` | Never use bare strings |

Do not infer serialized-space JSON structure from memory.

---

# Step 10.1: Preflight Validation

Before invoking the Create or Update API validate:

```text
serialized_space exists
serialized_space is non-empty
Metric View references exist
instructions are populated
sample questions meet configured minimum
example SQL meets configured minimum
benchmarks meet configured minimum
all example SQL was executed successfully
no template placeholders remain
WAREHOUSE_ID is populated
SPACE_TITLE is populated
GATE_CHECKS_PATH/SHA256 source and copied-byte attestations pass
canonical Genie helper callable signatures pass
```

If preflight fails:

```text
GENIE_SERIALIZATION_VALIDATION_FAILURE
```

Do NOT call the API.

---

# Step 11: Resolve Existing Genie Space

Use the official Genie management APIs or approved SDK/API client to determine whether the resolved space already exists.

Do not use UI shortcuts.

Do not use `createAsset`.

Do not issue a blank/bare Create Space call.

Use the exact `genie_title` from `step_handoff.yaml`. Do not re-resolve the title from accelerator naming rules.

### Matching Strategy

To determine if the resolved Genie Space already exists:

1. Check if a previous manifest exists at `{OUTPUT_FOLDER}/genie_space/{genie_title}_manifest.json` — if so, use its `space_id` only as a locator and GET the live space. The manifest does not prove the current title or contents; `genie_title` is the exact handoff value.
2. If no manifest, list existing Genie Spaces and match by `title` (case-insensitive exact match against the exact resolved `SPACE_TITLE` from `step_handoff.yaml.genie_title`; do not append or reconstruct a suffix).
3. If a match is found: use UPDATE flow.
4. If no match: use CREATE flow.

Do not match by partial title or substring. The full versioned title is the identity key.

---

# Idempotency Strategy

Preferred:

```text
existing matching space
        ↓
GET existing space
        ↓
UPDATE with full serialized_space
```

when updating the same resolved asset.

For a new versioned name:

```text
CREATE new space
```

Do not delete older versions unless explicitly required.

Do not delete an existing configured Genie Space merely to achieve idempotency when Update can safely replace its configuration.

---

# Step 12: Create Genie Space Through Official API

For a new space use the official Databricks Genie Create Space API.

Conceptually:

```text
POST /api/2.0/genie/spaces
```

using the request contract defined by the approved versioned local reference/template pinned for the run.

The creation request MUST include a complete:

```text
serialized_space
```

payload.

**CRITICAL: Always pass `headers={"Content-Type": "application/json"}` on ALL POST/PATCH calls to the Genie spaces API.** Without this explicit header, newer SDK versions may auto-negotiate a different serialization format, causing the server to return `BadRequest: The zip archive contains no items`.

A Create call without full configuration is prohibited.

Databricks' Create Genie Space API is the deployment execution mechanism. Successful request acceptance is not proof of persisted configuration; the subsequent GET readback is the deployment authority.

Do not use UI creation or generic workspace-asset creation as a substitute.

---

# Step 12.1: Create Response Validation

Capture:

```text
space_id
title
warehouse_id
API status
```

and any other returned identity/version information.

Creation is provisionally accepted only when a valid:

```text
space_id
```

is returned. Do not declare success until Step 14 reads the persisted space and validates it against the intended configuration.

---

# Step 13: Update Existing Genie Space

When the resolved Genie Space already exists and should be updated, use the official Genie Update Space API with the full intended configuration.

Treat `serialized_space` update semantics according to the approved versioned local reference/template pinned for this run. Route any observed platform-contract drift to the out-of-run refresh/regression workflow; do not reinterpret live documentation during the run.

Do not assume patch/merge behavior when the API defines full replacement semantics.

Retrieve the existing configuration first when necessary.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "create_genie_space"
> - `phase_name`: "Create Genie Space"
> - `status`: "started"
> - `findings`: ["Genie Create/Update request accepted provisionally", "Space ID returned; persisted configuration not yet validated"]
> - `stats`: {"metric_views_requested": N, "instructions_requested": 1, "space_id_returned": true}

---

# Step 14: GET Persisted Genie Space

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_genie"
> - `phase_name`: "Validate Genie Space"
> - `status`: "started"
> - `current_task`: "Validating configuration and running benchmarks"
> - `happenings`: ["Checking persisted configuration", "Running benchmark questions", "Validating semantic coverage"]

Immediately after Create or Update, call:

```text
GET /api/2.0/genie/spaces/{id}?include_serialized_space=true
```

A GET without `include_serialized_space=true` is not sufficient for content validation.

Retrieve the persisted:

```text
serialized_space
```

and metadata.

The normalized GET readback is authoritative for the deployed Genie identity and content. Normalize documented response-shape differences such as `data_sources.tables` versus the request-side `data_sources.metric_views` before comparison.

The desired configuration, request payload, POST/PATCH response, and manifest remain intent or evidence. None may override the GET readback. Do not assume the request payload was stored exactly as intended.

The digest-attested helper is the canonical implementation of this GET and comparison. Call
`validate_genie_from_api(workspace_client, space_id, title, validation=..., expected=...)` with the exact
frozen-host-bound SDK/API client and frozen validation thresholds. `expected` contains
`workspace_host`, `warehouse_id`, the validated `serialized_space` mapping, and the
complete quoted handoff `metric_view_fqns` list. The runtime compares semantic content,
allowing API-generated IDs and the documented tables/metric_views response alias.
Record its `readback_sha256` in benchmark evidence with run_id, space_id, passed, total,
and per-question execution evidence, so the sweep rejects benchmarks for changed content;
 do not pass an unbound client
or reconstruct the host. The returned value MUST
be a mapping and MUST prove all of the following before it can be used:

- `source: api_readback`;
- `status: PASS` exactly in the helper result;
- `workspace_host_binding: PASS`, proving the client host equals both frozen
  `run_context.runtime.workspace_host` and handoff `workspace_host`;
- exact requested/observed `space_id` and `title` equality, plus exact readback `warehouse_id`;
- `metric_view_fqns` equal to the complete expected FQN collection as sorted canonical
  unquoted comparison strings (`catalog.schema.object`, with every segment Unicode-casefolded),
  with no missing, duplicate, or extra entry; and
- `readback_counts` containing exact integer `instructions_chars`, `sample_question_count`,
  `example_sql_count`, and `benchmark_count`, each derived from full GET and meeting its frozen
  minimum.

Missing fields, an incompatible result schema, host/identity drift, or a non-PASS result fails
validation. Never fill missing helper results from request variables, the manifest, or a manual
GET comparison.

---

# Step 14.1: Persisted Configuration Validation

Compare:

```text
INTENDED CONFIGURATION
vs
PERSISTED GENIE CONFIGURATION
```

Validate at minimum:

```text
space ID
title
warehouse
attached Metric Views
instructions
sample questions
example SQL
benchmark inventory
```

The normalized attached Metric View FQN set from GET MUST exactly equal the validated FQN set from `step_handoff.yaml`; presence of merely one Metric View is insufficient. All persisted content counts and values used in validation or reporting must come from this GET readback.

Do not require byte-for-byte JSON equality if the service normalizes serialization.

Validate semantically important structure.

Failure:

```text
PERSISTED_GENIE_CONFIGURATION_MISMATCH
```

### Owner-Scoped Recovery

The Genie stage may repair only Genie-owned desired content (instructions, sample questions,
example SQL, benchmarks, and serialized-space construction), then redeploy and repeat the same
attested readback validation. Metric View identity/checkpoint/hash failures belong to
`create_metric_views`; frozen run/handoff/path conflicts belong to the master resolver; helper
path/digest/surface failures belong to the release/runtime contract. Do not modify those upstream
artifacts in Genie. API permission, connectivity, or service errors are operational failures, not
content-repair prompts. A `GateCheckError` must be classified by its structured owner/code and
routed accordingly; never catch it and run a local fallback validator.

Only after this normalized persisted-configuration comparison passes, call `report_progress` for `create_genie_space` with `status: "completed"`, findings that GET verified the space, and attached Metric View/content counts from that GET readback.

---

# Step 15: Configuration Quality Validation

Validate:

```text
Metric Views attached >= 1
all Metric Views expected for this space are attached
instructions length >= run_context.validation.min_instruction_chars
sample questions >= run_context.validation.min_sample_questions
example SQL examples >= run_context.validation.min_example_sqls
benchmark questions >= run_context.validation.min_benchmark_questions
```

Every minimum MUST come from the exact frozen `run_context.validation` fields resolved in Step 0. Do not read the live accelerator here and do not choose a local fallback. If a required minimum is missing from the frozen contract, HALT with `GENIE_VALIDATION_POLICY_MISSING`; any project default must already have been resolved and serialized into `run_context.validation`.

Before using those values, require the authenticated source-contract tuple and effective-policy hash
to pass. A present threshold under a missing or mismatched contract identity is not executable.

---

# Step 16: Semantic Coverage Validation

Validate that the Genie configuration covers the available semantic model.

Report coverage for:

```text
validated measures
validated dimensions
validated KPI families
temporal dimensions
major synonyms
```

Do not require every measure/dimension to appear in an example if doing so creates meaningless examples.

However, all major user-facing semantic concepts must be represented in:

```text
instructions
descriptions
examples
or benchmarks
```

---

# Step 17: Benchmark Validation

Run or evaluate benchmarks using the project's supported validation mechanism.

For every benchmark capture:

```yaml
question:
expected_semantics:
actual_result:
status:
failure_reason:
```

Where API/conversation execution is available, test Genie itself rather than only validating benchmark count.

Benchmark presence alone is NOT sufficient.

### Contract-Resolved Benchmark Outcome

Evaluate the measured `pass_rate` by iterating the exact frozen
`run_context.validation.benchmark_outcomes.evaluation_order`. Interpret only the approved predicate
enums in that mapping and resolve every threshold reference against the authenticated flat frozen
threshold fields. Persist the selected outcome, action, validation status, manifest permission, and
stage status exactly as the selected rule specifies.

Do not restate those action/status mappings as local rules. The frozen mapping is executable; a
later edit to `accelerator.yaml`, a prompt-local comparison, or a helper default cannot alter the
active run.

When the selected rule requires correction, run Step 18 for at most the frozen
`max_genie_correction_cycles`. Re-evaluate through the same frozen outcome mapping after every
cycle. If the final outcome still forbids a manifest, write failure evidence and HALT. Any accepted
non-PASS outcome proceeds only under its exact contract-defined action and stage status.

Write `{OUTPUT_FOLDER}/genie_space/benchmark_results.yaml` with this policy-binding summary plus the
per-question results:

```yaml
genie_quality_contract_name: <frozen value>
genie_quality_contract_version: <frozen value>
genie_quality_contract_sha256: <frozen raw-byte hash>
genie_quality_policy_id: <frozen value>
genie_quality_effective_policy_sha256: <frozen canonical hash>
pass_rate: <measured rate>
outcome: PASS | WARN | FAIL
action: <exact selected rule action>
validation_overall_status: <exact selected rule value>
manifest_allowed: <exact selected rule boolean>
stage_status: <exact selected rule value>
correction_cycles_used: <integer bounded by frozen max_genie_correction_cycles>
benchmarks: []
```

Re-read this file before deployment/finalization and require exact parity with the authenticated
policy and validation artifact. The selected result is computed; it is never supplied by the model.

---

# Step 17.1: Benchmark Failure Classification

Classify benchmark failures as:

```text
QUESTION_INTERPRETATION_ERROR
METRIC_SELECTION_ERROR
DIMENSION_SELECTION_ERROR
FILTER_ERROR
TIME_INTERPRETATION_ERROR
SQL_GENERATION_ERROR
UNSUPPORTED_QUESTION
AMBIGUOUS_QUESTION
```

Do not immediately alter Metric View definitions because Genie answered one benchmark incorrectly.

First identify whether the problem belongs to:

```text
Genie instructions
example SQL
synonyms
question ambiguity
or upstream metric semantics
```

---

# Step 18: Iterative Genie Quality Correction

If the selected benchmark rule requires a correction cycle:

1. identify the failure pattern;
2. determine the correct ownership layer;
3. correct only the responsible configuration;
4. rebuild `serialized_space`;
5. update through the official Genie Update Space API;
6. GET the persisted configuration again;
7. rerun affected benchmarks.

Do NOT use blind retries.

Do NOT add arbitrary instructions after every failure.

Changes must address an identified failure pattern.

---

# Step 19: Persist SPACE_ID

After successful Create/Update and validation:

persist the returned:

```text
SPACE_ID
```

in the configuration notebook's runtime/configuration cell when the template requires it.

This supports deterministic future updates.

---

# Step 20: Notebook Validation

The notebook deliverable must:

```text
exist at configured path
use the configured template
contain no unresolved placeholders
contain the deployed SPACE_ID
contain the final instructions
contain sample questions
contain tested example SQL
contain benchmarks
contain deployment/validation helpers
```

The notebook is an auditable configuration artifact.

The live Genie Space remains the deployed runtime asset.

---

# Step 21: Genie Validation Artifact

Write:

```text
{OUTPUT_FOLDER}/genie_space/{genie_title}_validation.yaml
```

containing:

```yaml
source: api_readback
readback_timestamp:
workspace_host_binding: PASS
status: PASS
genie_quality_contract_name: genie_quality
genie_quality_contract_version:
genie_quality_contract_sha256:
genie_quality_policy_id: GENIE_QUALITY_V1
genie_quality_effective_policy_sha256:
benchmark_outcome: PASS | WARN | FAIL
benchmark_action:
stage_status: PASS | PARTIAL_SUCCESS | FAIL
space:
  space_id:
  title:
  warehouse_id:
  status:

metric_views:
  expected: [] # sorted canonical normalized catalog.schema.object strings from authenticated handoff
  actual: []   # sorted canonical normalized strings from full GET readback
  status:

instructions:
  character_count:
  status:

sample_questions:
  expected_minimum:
  count:
  status:

example_sql:
  expected_minimum:
  count:
  executed:
  failed:
  status:

benchmarks:
  expected_minimum:
  count:
  passed:
  failed:
  pass_rate:
  outcome: PASS | WARN | FAIL
  action:
  status: PASS | WARN | FAIL

semantic_coverage:
  measures:
  dimensions:
  kpis:

api:
  create_status:
  update_status:
  get_status:

persisted_configuration:
  status:

readback_counts:
  instructions_chars:
  sample_question_count:
  example_sql_count:
  benchmark_count:

overall_status:
  PASS | FAIL
```

`overall_status` records whether the deployed configuration and policy evaluation were validated
correctly. Set it from the selected benchmark rule's `validation_overall_status`; the separate
`stage_status` preserves an accepted warning as `PARTIAL_SUCCESS`. All five quality-contract identity
fields must exactly match the authenticated frozen effective policy.

---

# Step 22: Manifest

Write:

```text
{OUTPUT_FOLDER}/genie_space/{genie_title}_manifest.json
```

containing:

```json
{
  "evidence_type": "asset_locator_and_deployment_attempt",
  "artifact_id": "<unique manifest/deployment artifact ID>",
  "source_hash": "<sha256 of validated intended Genie configuration>",
  "generated_hash": "<sha256 of serialized_space request>",
  "readback_hash": "<sha256 of normalized full GET state>",
  "state_comparison": "match",
  "space_id": "...",
  "title": "...",
  "description": "...",
  "warehouse_id": "...",
  "workspace_host_binding": "PASS",
  "validation_source": "api_readback",
  "genie_quality_contract_name": "genie_quality",
  "genie_quality_contract_version": "<exact frozen version>",
  "genie_quality_contract_sha256": "<exact frozen raw-byte hash>",
  "genie_quality_policy_id": "GENIE_QUALITY_V1",
  "genie_quality_effective_policy_sha256": "<exact frozen canonical hash>",
  "benchmark_outcome": "PASS|WARN|FAIL",
  "benchmark_action": "<exact selected contract action>",
  "stage_status": "PASS|PARTIAL_SUCCESS|FAIL",
  "metric_views": [],
  "sample_questions_count": "<full-GET-derived integer>",
  "example_sqls_count": "<full-GET-derived integer>",
  "benchmarks_count": "<full-GET-derived integer>",
  "instruction_chars": "<full-GET-derived integer>",
  "notebook_path": "...",
  "validated": true,
  "validation_artifact": "{OUTPUT_FOLDER}/genie_space/{genie_title}_validation.yaml"
}
```

Write this canonical manifest only when the matching validation artifact has the selected rule's
`validation_overall_status`, that rule has `manifest_allowed: true`, `state_comparison` is `match`,
all frozen count/content minima pass, and full GET binds the exact handoff title/ID. Persist the exact
selected outcome/action/stage status and all five quality-contract identity fields. Otherwise write
failed validation evidence and HALT without a successful canonical manifest. Populate the identity,
Metric View list, counts, and validation result from normalized full-GET readback, not from the
desired configuration or request payload. The manifest remains deployment evidence and an asset
locator; future stages must GET the live space before treating these values as current.

Use Workspace API / agent tools.

Never use `dbutils.fs` for `/Workspace/`.

---

> **PROGRESS REPORT:** Call `report_progress` with:
> - `phase_id`: "validate_genie"
> - `phase_name`: "Validate Genie Space"
> - `status`: "completed"
> - `findings`: ["Configuration validated", "Benchmark accuracy: {pct}%", "Semantic coverage: {cov}%"]
> - `stats`: {"benchmarks_passed": P, "benchmarks_total": T, "coverage_pct": C}

---

# Step 23: Final Status

Report:

| Check                           | Result    |
| ------------------------------- | --------- |
| Validated Metric Views attached | PASS/FAIL |
| Instructions populated          | PASS/FAIL |
| Sample question quality         | PASS/FAIL |
| Example SQL execution           | PASS/FAIL |
| Benchmarks configured           | PASS/FAIL |
| Create/Update API               | PASS/FAIL |
| Persisted configuration GET     | PASS/FAIL |
| Benchmark execution             | PASS/WARN/FAIL (contract-resolved) |
| Overall stage status            | PASS/PARTIAL_SUCCESS/FAIL (contract-resolved) |

Include:

```text
space_id
genie_quality_contract_name/version/sha256
genie_quality_policy_id
genie_quality_effective_policy_sha256
benchmark_outcome/action
```

for the deployed Genie Space.

---

# Forbidden

❌ `createAsset` for Genie Space creation

❌ UI "Create Genie Space" shortcuts as the deployment mechanism

❌ bare:

```text
POST /api/2.0/genie/spaces
```

without a complete `serialized_space`

❌ hand-written serialized-space payloads that bypass the project builder

❌ querying raw source tables to recreate Metric View KPIs

❌ using skipped/unvalidated KPIs in sample questions

❌ including untested SQL examples

❌ notebook containing unresolved placeholders

❌ declaring success based only on a returned `space_id`

❌ declaring quality success based only on benchmark count

❌ blind retries with arbitrary instruction changes

---

# Error Classification

Use one of:

```text
GENIE_INPUT_ERROR
METRIC_VIEW_NOT_VALIDATED
GENIE_QUALITY_CONTRACT_ERROR
GENIE_VALIDATION_POLICY_MISSING
GENIE_SEMANTIC_INVENTORY_ERROR
GENIE_INSTRUCTION_ERROR
SAMPLE_QUESTION_ERROR
EXAMPLE_SQL_ERROR
BENCHMARK_DESIGN_ERROR
BENCHMARK_EXECUTION_ERROR
GENIE_SERIALIZATION_ERROR
GENIE_API_CREATE_ERROR
GENIE_API_UPDATE_ERROR
GENIE_API_GET_ERROR
PERSISTED_GENIE_CONFIGURATION_MISMATCH
WORKSPACE_IO_ERROR
```

For every error report:

```text
Observed problem:
Root cause:
Authoritative evidence:
Affected KPI(s):
Affected Metric View(s):
Corrective action:
Affected downstream artifacts:
```

---

# Retry Policy

Blind retry behavior is prohibited.

Do NOT:

```text
create
fail
change random serialized_space
retry
add arbitrary instruction
retry
```

Instead:

1. capture the complete API / SQL / benchmark failure;
2. classify it;
3. identify the responsible contract;
4. make a targeted correction;
5. rerun preflight validation;
6. call Update or Create again only after the correction is understood.

Maximum deployment attempts:

```text
3
```

Each attempt must have a documented cause and correction.

---

# Pipeline Halt Rules

Return:

```text
❌ EXECUTION HALTED
```

when a mandatory Genie Space cannot be reliably configured.

Halt conditions include:

* required Metric Views do not exist;
* required Metric Views are not validated;
* `serialized_space` cannot be constructed;
* no Metric View can be attached;
* example SQL consistently fails;
* required benchmark minimum cannot be met;
* Genie Create/Update API continues to fail after diagnosed corrections;
* persisted configuration does not contain required semantic assets;
* mandatory benchmark quality threshold fails after targeted corrections.

---

# Non-Negotiable Rules

1. **Genie consumes validated Metric Views; it does not redefine metrics.**
2. **Only `IMPLEMENTED_AND_VALIDATED` KPIs may drive Genie examples and benchmarks.**
3. **Do not repair Metric View issues in Genie SQL or instructions.**
4. **Use `MEASURE()` for validated Metric View measures.**
5. **Example SQL must execute successfully before inclusion.**
6. **Benchmark questions must test generalization, not just paraphrase samples.**
7. **Instructions should guide interpretation, not duplicate Metric View formulas.**
8. **Do not invent joins or source-table relationships inside Genie.**
9. **Use the configured Genie template and serialization builder.**
10. **Do not build `serialized_space` from model memory.**
11. **Use the official Databricks Genie Create Space API for new spaces.**
12. **Use the official Update Space API for existing spaces where appropriate.**
13. **Use Get Genie Space after Create/Update and validate persisted configuration.**
14. **A returned `space_id` does not prove correct configuration.**
15. **Benchmark count does not prove Genie quality.**
16. **Do not use `createAsset` as a Genie deployment mechanism.**
17. **Do not create title-only or blank spaces.**
18. **Do not use ad-hoc API calls that bypass the validated serialization contract.**
19. **Workspace file writes use `workspace_file_io.md`, never `dbutils.fs`.**
20. On unrecoverable mandatory failure:

```text
❌ EXECUTION HALTED
```

---

# Output Contract

At the END of this step, the following artifacts MUST exist:

| Artifact | Location | Validation Check |
|----------|----------|-----------------|
| LLM Genie Design | `{OUTPUT_FOLDER}/genie_space/llm_genie_design.yaml` | Instructions, questions, SQL, benchmarks, and pattern coverage meet frozen `run_context.validation` minima |
| Semantic Inventory | `{OUTPUT_FOLDER}/genie_space/genie_semantic_inventory.yaml` | All validated measures + dimensions cataloged |
| Genie Space (live) | Databricks workspace | GET with `include_serialized_space=true` returns persisted content matching intended configuration |
| `{genie_title}_manifest.json` | `{OUTPUT_FOLDER}/genie_space/` | Contains the `space_id` locator and `validation_source: api_readback`; current content still comes from GET |
| `{run_context.assets.genie.notebook_name}` | `{OUTPUT_FOLDER}/genie_space/` | Exact frozen resolved notebook file exists |
| `{run_context.assets.sample_queries_file}` | `{OUTPUT_FOLDER}/genie_space/` | Exact frozen resolved file contains at least `run_context.validation.min_sample_query_file_queries` queries |
| benchmark_results.yaml | `{OUTPUT_FOLDER}/genie_space/` | Outcome/action/stage status exactly match the authenticated frozen quality policy; only a rule with `manifest_allowed: true` may complete |
| run_context.yaml | `{OUTPUT_FOLDER}/` | `phases_completed` includes genie phases |

### Minimum Quality Gates

- Instructions length >= frozen `run_context.validation.min_instruction_chars` AND passes the content richness check
- Instructions use markdown formatting (## headers, - bullets) for structure and readability
- Sample questions meet frozen `min_sample_questions` and `min_analytical_patterns`
- Example SQL meets frozen `min_example_sqls`; every query is validated and uses MEASURE() syntax
- All example SQL queries execute without error on the SQL warehouse
- Benchmark questions meet frozen `min_benchmark_questions` using different phrasing than sample questions
- Benchmark outcome is resolved by frozen `benchmark_outcomes` and the selected rule permits a manifest
- Every IMPLEMENTED KPI meets frozen `min_kpi_question_references`
- Every dimension meets frozen `min_dimension_question_references`
- Design, validation, benchmark evidence, manifest, and reusable phase fingerprints carry the exact
  quality-contract tuple and effective-policy hash

If ANY artifact is missing or quality gate fails, the step has NOT completed successfully.

---

# MANDATORY PRE-DEPLOY SELF-CHECK (read LAST before any API call)

## Purpose

This final gate prevents title drift, invalid FQN quoting, unvalidated example SQL, malformed IDs or
arrays, and bypass of the digest-attested deployment template. The checks are non-negotiable.

## Pre-Deploy Check Artifact (GATE)

**Before ANY call to `POST /api/2.0/genie/spaces`**, the agent MUST produce and print the following self-check. If ANY check shows `FAIL`, the agent MUST NOT proceed.

```yaml
# pre_deploy_check (print to stdout before API call)
space_title_check:
  configured_name: "{exact value from step_handoff.yaml.genie_title}"
  title_being_used: "{exact value being passed as title}"
  match: true/false  # MUST be true

fqn_format_check:
  fqn_in_example_sql: "{exact FQN string as it appears in example SQL}"
  format: "3_separate_backtick_pairs"  # MUST be this value
  # CORRECT: `catalog`.`schema`.`table`
  # WRONG:  `catalog.schema.table`
  valid: true/false  # MUST be true

template_usage_check:
  method: "{template notebook execution OR build_serialized_space()}"
  # Expected: "v2_genie_space_notebook.py.template executed" or "build_serialized_space() called"
  # FAIL if: "hand-constructed JSON" or "createAsset(assetType=genie)"
  valid: true/false

example_sql_validation_check:
  total_example_sqls: N
  all_executed_successfully: true/false  # MUST be true
  failed_sqls: []  # MUST be empty

id_format_check:
  sample_id: "{one example UUID being used}"
  format: "32_char_hex_no_hyphens"  # MUST be this value
  # CORRECT: "a1b2c3d4e5f6789012345678abcdef01"
  # WRONG:  "a1b2c3d4-e5f6-7890-1234-5678abcdef01"
  valid: true/false  # MUST be true

array_sorting_check:
  all_id_arrays_sorted: true/false  # MUST be true
  # sample_questions, text_instructions, example_question_sqls, benchmarks.questions

text_field_format_check:
  question_fields_are_arrays: true/false  # MUST be true
  sql_fields_are_arrays: true/false  # MUST be true
  content_fields_are_arrays: true/false  # MUST be true
  # CORRECT: {"question": ["What is..."], "sql": ["SELECT ..."]}
  # WRONG:  {"question": "What is...", "sql": "SELECT ..."}
```

**Rules:**
- If `space_title_check.match` is `false` → **HALT. Fix the title.**
- If `fqn_format_check.valid` is `false` → **HALT. Fix the quoting in ALL SQL.**
- If `template_usage_check.valid` is `false` → **HALT. Use the template.**
- If `example_sql_validation_check.all_executed_successfully` is `false` → **HALT. Fix broken SQL.**
- If `id_format_check.valid` is `false` → **HALT. Use uuid.uuid4().hex (no hyphens).**
- If `array_sorting_check.all_id_arrays_sorted` is `false` → **HALT. Sort by id ascending.**
- If `text_field_format_check` has any `false` → **HALT. Wrap all text in arrays.**

---

# Final Instruction (HIGHEST PRIORITY)

If you are about to make an API call and you have NOT:
1. Printed the pre_deploy_check to stdout
2. Confirmed ALL checks are `true`
3. Used the EXACT resolved space title from `step_handoff.yaml.genie_title`
4. Used 3-part backtick quoting in ALL example SQL
5. Validated ALL example SQL queries execute successfully
6. Sorted ALL ID-containing arrays by `id` ascending
7. Wrapped ALL text fields (question, sql, content) in arrays
8. Used `uuid.uuid4().hex` for all IDs (no hyphens)

Then **STOP. Go back. Do it correctly.**
