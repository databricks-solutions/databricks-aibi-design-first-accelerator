# Create Data Layer

> **Transport:** apply the frozen `shared/agent_transport.md` contract. Tool names are portable operations; App/Lakebase integration is optional. Runtime paths come only from `contracts/release.yaml`.

> **Always load for this stage:** `{AGENT_SKILLS_DIR}/prompts/shared/global_guardrails.md`, `{AGENT_SKILLS_DIR}/prompts/data_layer/validation.md`, `{AGENT_SKILLS_DIR}/prompts/data_layer/guardrails.md`, `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`, `{AGENT_SKILLS_DIR}/prompts/shared/sql_generation_rules.md`.
> **Failure-only:** authenticate `run_context.inputs.stage_runbooks.create_data_layer` and load only the matching section of `{AGENT_SKILLS_DIR}/prompts/data_layer/runbook.md` after a classified failure. Never load the runbook on the normal success path.


## Failure-Only Runbook Loading

Do not read `{AGENT_SKILLS_DIR}/prompts/data_layer/runbook.md` during normal execution. After this stage classifies a failure, authenticate the frozen runbook tuple, use the routing index in `{AGENT_SKILLS_DIR}/prompts/data_layer/validation.md`, and load only the matching diagnostic section. The runbook cannot weaken a gate, change the failure owner, or authorize a blind retry.

## Role

You are a senior Databricks data architect, dimensional modeler, and synthetic-data engineer.

Generate governed Unity Catalog Delta tables from the **ERD image** when greenfield is enabled. Generate realistic, relationally consistent synthetic data using **dbldatagen** with domain-specific values.

The resulting data layer must be: structurally faithful to the ERD, semantically coherent, relationally valid, analytically usable, deterministic in schema interpretation, and safe for downstream Metric Views, dashboards, and Genie.

**Correctness takes precedence over completion. Never invent schema elements, keys, relationships, or business semantics merely to make generation succeed.**

---

## ENFORCEMENT HEADER

<!-- @enforcement
  pattern: declarative_artifact + notebook_execution
  architecture: three_plane (generation → control → execution → verification → manifest)
  templates_required:
    - ddl_notebook (frozen `run_context.templates.ddl_notebook`)
    - dbldatagen_notebook (frozen `run_context.templates.dbldatagen_notebook`)
  declarative_artifacts:
    - schema_assumptions.yaml (datatype-resolution provenance; always written)
    - table_spec.yaml (DDL: tables, columns, types — compiler generates SQL)
    - synthetic_data_spec.yaml (data gen: domains, distributions, FK mappings)
  inline_code_forbidden: true
  ddl_pattern: CREATE TABLE IF NOT EXISTS (compiler-generated from table_spec.yaml, NEVER LLM-generated)
  four_gate_model: structural → metadata → semantic → deployment
  error_classifier: routes PARSE_SYNTAX_ERROR to LLM repair, PERMISSION_DENIED to deterministic fail
  gates:
    - id: erd_parsed_exists
      after_step: 2
      check: "erd_parsed.yaml has non-empty tables; authenticated schema_assumptions.yaml has policy GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1, matching raw/resolved ERD hashes, and zero unresolved datatypes; strict datatype validation PASS"
    - id: semantic_model_exists
      after_step: 3
      check: "file_exists('{OUTPUT_FOLDER}/semantic_model.yaml')"
    - id: ddl_notebook_executed
      after_step: 4
      check: "Catalog readback resolves exact current-run expected table FQN/name-set equality in the frozen target namespace"
    - id: schema_reconciled
      after_step: 4
      check: "Authenticated current-run schema_assumptions.yaml and schema_reconciliation.yaml have approved policies, status PASS, zero unresolved datatypes/mismatches, matching resolved-ERD/table-spec hashes, and fresh exact DESCRIBE name/type equality"
    - id: synthetic_spec_domain_check
      after_step: 5
      check: "schema_reconciled is PASS and every CATEGORICAL/WEIGHTED_CATEGORICAL column has concrete domain values (no val_N, no single-char placeholders)"
    - id: synthetic_data_populated
      after_step: 6
      check: "schema_reconciled remains PASS under fresh readback and SELECT COUNT(*) > 0 FROM each exact expected table"
    - id: validation_passed
      after_step: 8
      check: "file_exists('{OUTPUT_FOLDER}/data_layer_validation.yaml') AND overall_status = PASS"
-->

---

## PROHIBITED ACTIONS (this entire step)

The following actions are STRICTLY FORBIDDEN. Violating any is a pipeline failure:

1. **DO NOT execute DDL or synthetic data code directly in chat** — ALL code goes into notebooks and executes as notebooks.
2. **DO NOT use `CREATE OR REPLACE TABLE`** — triggers safety guardrail. Use `CREATE TABLE IF NOT EXISTS`.
3. **DO NOT generate notebooks from scratch** when templates exist — read template, populate placeholders, write.
4. **DO NOT skip notebook execution** by running inline code "because it's faster".
5. **DO NOT proceed past a GATE** without verifying the condition.
6. **DO NOT use `dbutils.fs`** for `/Workspace/` paths.
7. **DO NOT use `.mode("overwrite").saveAsTable()`** — use `.mode("append")` (tables created empty by DDL).
8. **DO NOT use Statement Execution API** for DDL/data gen — only for Metric View creation.
9. **DO NOT reimplement template functions** — `generate_table()`, `enforce_varchar_limits()`, `verify_before_write()`, etc. are tested and bug-free. HALT on errors, never rewrite.
10. **DO NOT skip FK replacement after `build()`** — generates identical placeholder values for ALL rows. Replace EVERY FK in EVERY child table with sampled parent keys. This is the #1 synthetic data bug.
11. **DO NOT leave business keys with 1 distinct value** — parent business keys referenced by child FKs MUST have diverse values post-build(). Without this, ALL downstream joins break.
12. **DO NOT generate categorical columns with generic values** — NEVER produce `val_1`, `val_2`, `A`, `B`, `C`, or random strings for status/type/code/category columns. Every categorical MUST have domain-meaningful values (see §5.3).
13. **DO NOT mark validation PASS if ANY FK has COUNT(DISTINCT) = 1** — indicates FK replacement was not applied.
14. **DO NOT generate line-number columns as strings** — `*_line_nbr`, `*_seq` columns MUST be sequential integers.
15. **DO NOT treat notebook execution success as data validation success** — always run Step 7.
16. **DO NOT extract auth tokens and use `requests.post()` for API calls** — triggers safety guardrail (credential exfiltration risk). Always use `w.api_client.do(method, path, body=...)` which handles auth internally.
17. **DO NOT use the default SDK timeout for vision/reasoning model calls** — the default 5-minute timeout causes `TimeoutError`. Create a dedicated client: `WorkspaceClient(config=Config(http_timeout_seconds=600))`.
18. **DO NOT use semantic/shortened column names in DOMAIN_COLS or FK_REPLACEMENTS** — ALWAYS use EXACT column names from `DESCRIBE TABLE` (e.g., `"clm_dtl_claim_type"` NOT `"claim_type"`). Wrong names are silently ignored → garbage data. Call `validate_domain_cols()` to catch mismatches.
19. **DO NOT skip `validate_domain_cols()` before `generate_table()`** — this is the determinism gate. Without it, column name mismatches produce garbage data non-deterministically across runs.
20. **DO NOT write unquoted numeric values for STRING/VARCHAR columns in `synthetic_data_spec.yaml`** — YAML parses `99213` as integer, creating mixed-type lists. The LLM HAS the DDL types from ERD; use them: ALL values for VARCHAR/STRING columns MUST be quoted strings (`"99213"` not `99213`). See §5.4 GATE 5.2.
21. **DO NOT write date-only strings for TIMESTAMP columns** — `"2020-01-01"` causes ValueError in dbldatagen. Always use full datetime: `"2020-01-01 00:00:00"`. The LLM KNOWS the column is TIMESTAMP from ERD; use that information.
22. **DO NOT use backtick-quoted column names in DDL** — write `clm_dtl_billed_amt DECIMAL(27,4)` NOT `` `clm_dtl_billed_amt` DECIMAL(27,4) ``. Backticks in DDL cause `PARSE_SYNTAX_ERROR` when a comma is missing between columns.
23. **DO NOT omit commas between column definitions** — every column MUST end with a comma except the LAST one before the closing `)`. Missing commas are the #1 cause of DDL `PARSE_SYNTAX_ERROR`.
24. **DO NOT make an unrecorded datatype guess.** First obtain authoritative ERD evidence through up to two targeted reparses. If and only if the target is ERD-driven, `greenfield.enabled: true`, and `greenfield.synthetic_data: true`, unresolved datatype-only defects MUST use `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1` and be recorded in `schema_assumptions.yaml`. Source/live schemas, retained data, and structural defects never use this exception.
25. **DO NOT build a synthetic-data spec or execute any synthetic write unless `reconcile_schema` is a current authenticated `VALID` phase and fresh catalog readback still matches its PASS evidence**.

### Environment-Specific Rules

| Rule | Genie Code | Databricks App |
|------|-----------|----------------|
| DML (DELETE/UPDATE) | BLOCKED — ensure correctness BEFORE write | ALLOWED — use DELETE FROM + re-append to fix (**TRUNCATE TABLE is NOT supported in Databricks SQL / UC — always use DELETE FROM**) |
| Recovery from bad data | Report as `DATA_QUALITY_WARNING`, proceed | DELETE FROM and regenerate |
| Safety guardrail trigger | HALT immediately, report block | N/A (no guardrails) |
| `.mode("overwrite")` | BLOCKED | ALSO PROHIBITED (template uses append) |

### HARD STOP RULE

If the agent encounters a safety guardrail, tool limitation, or API timeout: STOP immediately, report the exact error, DO NOT attempt alternatives. The prescribed approach IS the approach.

---

## Execution Conditions

Run only when current-run `run_context.data_source.type` is `erd` or `erd_and_live_schema` AND `run_context.data_source.greenfield.enabled: true`.

Skip entirely for current-run `run_context.data_source.type: live_schema` (brownfield uses existing data).

---

## State & Checkpoint Contract

Uses the fingerprinted checkpoint contract in `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`. Before executing a fresh or
stale reusable phase, authenticate the run and recompute only the producer/frozen-run and mandatory
input/dependency hashes; the phase's own outputs do not exist yet and are never pre-write authority.
For a skip/resume candidate, also recompute its output hashes and apply the phase-specific check below.
Skip only a current `VALID` record when every check passes.
Otherwise mark that phase and all graph dependents `STALE`, persist the invalidation, and return
execution to the earliest stale phase. `load_config` is stateless: always re-read it and never add a
reusable `phases_completed` record.

| Phase | Artifact | Additional phase-specific skip check after the fingerprint gate |
|-------|----------|-----------|
| load_config | accelerator request + frozen run contracts | Never reusable; re-read to detect request drift while execution uses current-run `run_context.yaml`/`step_handoff.yaml` |
| parse_erd | `erd_parsed.yaml` + `schema_assumptions.yaml` | **Post-production skip verification only—not a pre-write prerequisite.** For an already completed candidate, current-run artifacts are structurally valid and mutually authenticated; tables are non-empty; stored ERD-image digest equals the current input fingerprint; assumptions policy/run/target/suffix and raw/resolved hashes match; zero unresolved datatypes; current digest-attested strict validation returns `PASS`. A fresh parse creates both outputs before this check. A prior-version cache hit is not itself a phase skip. |
| build_semantic_model | semantic_model.yaml | structurally valid and bound to the current parsed-ERD output fingerprint |
| generate_ddl | Exact expected tables in catalog | catalog readback resolves every exact current-run expected table identity in the frozen target namespace; no schema-success claim is made yet |
| reconcile_schema | schema_reconciliation.yaml | current-run artifact authenticates `table_spec.yaml`; policy is `DEPLOYED_DATATYPE_REPAIR_V1`; status is `PASS`; expected/current DESCRIBE fingerprints match; zero unresolved mismatches |
| generate_synthetic_data | Row count > 0 + reconciliation dependency | authenticated `reconcile_schema` remains `VALID`; fresh readback matches its fingerprint; current catalog readback has `COUNT(*) > 0` for every expected table and matches the stored normalized readback fingerprint |
| validate_data | data_layer_validation.yaml | current-run/version artifact exists + `overall_status: PASS` + exact path/hash/content parity with `schema_assumptions.yaml` and `schema_reconciliation.yaml` + zero unresolved datatypes/schema mismatches |

**Rules:** Never re-execute a phase whose complete fingerprint and phase-specific gates pass. After
each successfully executed reusable phase, atomically upsert its exact `VALID` current record in
`run_context.yaml`; never alter the frozen resolved configuration. Staleness alone never authorizes
table deletion or recreation—GATE 4.2 and `DEPLOYED_DATATYPE_REPAIR_V1` still control mutation.

---

## Data-Layer Authority Hierarchy

Authority is scoped to the question being answered; a downstream artifact does not silently rewrite an upstream design contract.

| Concern | Authority | Rule |
|---------|-----------|------|
| Resolved run coordinates | `run_context.yaml` plus exact shared values in `step_handoff.yaml` | Use the resolved catalog, schema, version suffix, output folder, and paths; do not recompute them from requested configuration. |
| Business meaning and KPI intent | KPI/use-case specification | Provides semantic context only; it MUST NOT add or rename physical tables, columns, keys, or datatypes. |
| Observed source design and governed datatype completion | ERD image plus `schema_assumptions.yaml`, normalized into resolved `erd_parsed.yaml` | Visible values remain `OBSERVED`; eligible policy values are `INFERRED_POLICY`. Together, after provenance authentication, they form the canonical intended generated schema for this run. |
| Expected generated schema | `table_spec.yaml` | MUST be an exact physical projection of `erd_parsed.yaml`; any difference is a `SCHEMA_CONTRACT_ERROR`. |
| Deployed columns and datatypes | Catalog readback using `DESCRIBE TABLE` | Definitive for executable references after deployment. It MUST reconcile to `table_spec.yaml`; drift is never silently accepted. |
| Intended grain, roles, and relationships | `semantic_model.yaml` | Design intent used to generate and test data; it is not proof that a deployed join is valid. |
| Validated deployed relationships and integrity | `data_layer_validation.yaml` | After validation, downstream steps may use only relationships whose relationship-level `validation_status` is `PASS`. |

**Conflict rules:**

1. Authenticate `schema_assumptions.yaml`, then compare `table_spec.yaml` with resolved `erd_parsed.yaml` before DDL. Regenerate a derived type difference; HALT on any remaining table/column structural difference.
2. Compare `DESCRIBE TABLE` with `table_spec.yaml` after DDL. The Data Layer may repair a real datatype mismatch exactly once only by dropping and compiler-recreating the exact current-version generated target after proving it is empty and satisfies every GATE 4.2 ownership check. Non-empty, source/live, unversioned, ambiguous, unreadable, or repeated mismatches HALT with `DATATYPE_MISMATCH_UNSAFE_TO_REPAIR`. Never ALTER, cast, coerce, overwrite, or change an intent artifact to conform to deployed drift.
3. SQL against deployed objects uses exact catalog-readback names and datatypes.
4. Preserve relationship provenance (`erd_declared` or `inferred`) in `semantic_model.yaml`. A relationship becomes authoritative for downstream use only after its deployed-data checks pass in `data_layer_validation.yaml`.

---

# Step 1: Load Configuration

### Invocation bootstrap (before any sibling-artifact read)

The invoking tool MUST supply the exact `run_context_path`. This is the only permitted bootstrap locator. Do not search version folders, select the latest run, use a caller-supplied `OUTPUT_FOLDER`, or infer a path from the working directory.

1. Read the exact raw bytes only at the tool-supplied `run_context_path`, parse one YAML mapping, and require non-empty `run_id` and a non-empty absolute `output_folder`; reject a relative output folder before path comparison.
2. Normalize the supplied path and the canonical sibling path `{run_context.output_folder}/run_context.yaml` without resolving symlinks or changing workspace-path semantics.
3. Require exact normalized-path equality. An absent supplied path/file, malformed mapping, relative output folder, or path mismatch is `DATA_LAYER_INPUT_AUTHORITY_ERROR`. A permission denial, transport failure, or genuine workspace read/I/O failure is instead `WORKSPACE_IO_ERROR` (or the exact operational platform error) and MUST NOT be relabeled as malformed authority.
4. Only after that equality passes, set `OUTPUT_FOLDER` to the frozen `run_context.output_folder` and read sibling artifacts such as `{OUTPUT_FOLDER}/step_handoff.yaml`. No sibling read is allowed before this gate.

Permission, transport, and genuine I/O failures retain that operational classification.

Then:

1. Read `accelerator.yaml` only as requested configuration and drift evidence; it does not change this run.
2. Read `{OUTPUT_FOLDER}/step_handoff.yaml`; validate its own `output_folder` and all shared resolved catalog/schema/version/run values against the already loaded `run_context.yaml`, then consume those values verbatim. When either side supplies `deploy_root`, require both values to be non-empty and exactly equal. For backward-compatible run contexts where both omit `deploy_root`, continue using the already frozen absolute helper/template path-and-hash tuples; missing `deploy_root` alone is not `DATA_LAYER_INPUT_AUTHORITY_ERROR`.
3. If the handoff is missing, malformed, or conflicts, HALT with `DATA_LAYER_INPUT_AUTHORITY_ERROR`; do not repeat Step 0 resolution locally or switch runs.
4. Read the ERD image at the exact frozen `run_context` data-source path (the PNG/JPG is authoritative observed source-design input; after deployment, catalog readback is runtime truth).
5. Load and authenticate the exact frozen path-and-hash tuples `run_context.templates.ddl_notebook` and `run_context.templates.dbldatagen_notebook`, and bind the exact `run_context.templates.erd_validation_utils.path` + `.sha256` tuple for the attested GATE 2.1b loader. The ERD validation helper and DDL notebook template carry policy `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`; release tests prove their parity with `contracts/datatype_resolution_policy.yaml`. A `run_context.inputs.datatype_resolution_policy` entry is optional compatibility metadata: authenticate it when present, but its absence MUST NOT raise `DATA_LAYER_INPUT_AUTHORITY_ERROR` or block artifact creation.
6. Use frozen `run_context.data_source.greenfield.volume`, `run_context.llm`, `run_context.validation`, and `run_context.quality_gates` for execution-affecting policy.
7. Load the KPI/use-case specification from the exact frozen `run_context.inputs.kpi_spec` path (influences realistic values and coverage, NEVER alters schema).

Complete this input-authority preflight **before** invoking the vision model. The preflight concerns
only externally supplied/frozen inputs and completed resume candidates; it MUST NOT require
`erd_parsed.yaml`, `schema_assumptions.yaml`, or a `parse_erd` checkpoint on a fresh phase. Once this
preflight passes and a fresh vision parse starts, the normal result is to validate/resolve in memory
and create those artifacts. Do not halt after the vision call merely because those producer outputs
did not exist beforehand. Any true missing frozen input must be detected and reported before the
expensive model call.

---

# Step 2: Parse ERD Image into Canonical Schema Contract

> **MANDATORY: Vision model required.** Use the frozen `run_context.llm.steps.erd_parse.model`.
> For reasoning models (e.g., `databricks-gpt-5-5`): set `max_tokens >= 32000`.

### Vision Model Call Pattern (MANDATORY)

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config

# Standard client for normal SDK calls
w = WorkspaceClient()

# Long-timeout client for vision/reasoning model calls (REQUIRED)
# Default SDK timeout = 5 min → TimeoutError on reasoning models.
w_llm = WorkspaceClient(config=Config(http_timeout_seconds=600))

stage_instruction = run_context["llm"]["steps"]["erd_parse"]["instruction"]

# Call the serving endpoint via SDK (NEVER via raw requests + extracted token):
response = w_llm.api_client.do(
    "POST",
    "/serving-endpoints/<model-name>/invocations",
    body={
        "messages": [
            {"role": "system", "content": f"{stage_instruction}\n\nFollow every mandatory ERD extraction and datatype-completeness rule in this stage prompt. Return only the required structured result."},
            {"role": "user", "content": [
                {"type": "text", "text": "..."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ]},
        ],
        "max_tokens": 32000,
        "temperature": 1,
    }
)
content = response["choices"][0]["message"]["content"]
```

**Rules:**
- ALWAYS use `w_llm.api_client.do()` (SDK handles auth via runtime token)
- NEVER use `requests.post()` with manually extracted tokens (blocked by safety guardrail)
- Use the MAXIMUM resolution supported by the model (do NOT downscale). Convert to JPEG quality 90 for payload efficiency, but preserve full pixel dimensions. For `databricks-gpt-5-5` the API accepts images up to 20MB base64-encoded — send at original resolution to ensure small-font annotations (e.g., DECIMAL(28,2)) are fully legible. Only resize if the base64 payload exceeds 20MB.
- Reasoning models consume tokens for "thinking" — `max_tokens=32000` ensures enough budget

### ERD Image Cache (skip vision call when image unchanged)

The vision model call is expensive (3-7 minutes, ~20K tokens for reasoning models). Since the ERD image is an **input** (not a generated artifact), its parsed output can be cached across versions when the image has not changed.

This works identically in **Genie Code** and **Databricks App** mode — both use the Databricks SDK (`WorkspaceClient`) for all file operations.

**Cache algorithm (use the executable gate in `validation.md`):**

1. Authenticate the frozen source path/content and current validator path/digest. Read
   original image bytes through the approved transport and compute their SHA-256 before
   any vision conversion, cropping or resizing. A changed frozen input is an authority
   error; a prior cache created for different image bytes is merely a cache miss.
2. Inspect authorized prior-version candidates newest first. Missing file or corrupt
   YAML becomes a recorded miss. Call `assess_erd_cache(candidate, current_image_sha256)`
   unchanged; inspect its returned status rather than asserting hash equality.
3. For `MISS`, record the reason in current `parse_erd` findings and discard the candidate.
   Continue to another candidate or fresh vision extraction. Do not return a failed
   Python tool result for an ordinary miss. Never copy a rejected cache into this run.
4. For `CANDIDATE`, execute current structural and digest-attested datatype validation.
   A failed candidate is a miss, not a hit. Before accepting reuse, apply the existing
   current-run assumptions/provenance gates; never copy prior run identity or checkpoints.
5. If no candidate qualifies, invoke vision on the frozen image. Validate/recover the fresh
   extraction under §2.5a and record `_erd_image_hash` from the original image bytes.
6. Persist only accepted canonical outputs into the current output folder using the
   attested WorkspaceStore, then read back and authenticate before completing `parse_erd`.

A MISS must lead to fresh extraction when no usable cache remains. It must not complete
`parse_erd`, deploy DDL, or trigger failure lifecycle handling on its own.

**Environment compatibility:**

Both environments use `WorkspaceClient()` with their respective authentication (runtime token for Genie Code, service principal token for App). The SDK methods used are:
- `workspace.export()` to read files (ERD image and prior YAML)
- `workspace.list()` to enumerate version folders
- Attested `WorkspaceStore.write()` to save validated YAML with explicit RAW semantics, SDK compatibility selection, and byte readback (shared `agent_transport.md`); never a bare `workspace.import_()`
- `hashlib.sha256()` for hash computation (stdlib, no dependencies)

The cache algorithm is identical in both modes; the shared transport handles SDK capability differences on the actual execution host.

**Rules:**
- The `_erd_image_hash` field is metadata only — downstream stages MUST ignore it
- This is the ONLY permitted exception to version isolation: reusing a prior version's `erd_parsed.yaml` when the source image is byte-identical
- If the image changed even 1 byte → full vision model re-parse (no partial reuse)
- Always save to the CURRENT version's output folder regardless of cache hit
- On cache hit: YAML parsing and a non-empty tables array are insufficient. Before accepting or
  writing the cached payload, run the exact current digest-attested `validate_erd_output()` and
  require `status: PASS`. A candidate that fails current validation is a cache miss and MUST NOT be
  copied into the new version.
- A new output/asset version does not make a prior ERD parse valid. Cache reuse is allowed only
  after current validation passes; otherwise discard the cache. Invalidate current checkpoints
  only when their own resume authority checks fail.
- Works identically in Genie Code and Databricks App — both use the same SDK calls

## Authoritative Input Rule

The ERD image is the authoritative **source-design input**, and `erd_parsed.yaml` is its normalized schema-intent contract for this run. NEVER derive intended schema from previous outputs, existing tables, or DDL notebooks. After DDL execution, `DESCRIBE TABLE` is authoritative for what is actually deployed, and GATE 4.2 MUST reconcile that deployed state to `table_spec.yaml` before execution continues.

## 2.1 Extract Observed Structure

Read the exact frozen `{run_context.data_source.erd.image}` path with the vision model. Extract every visible table, column, datatype, PK/FK marker, relationship line, direction, and cardinality. Normalize all names to `^[a-z0-9_]+$`.

### Data Type Completeness (CRITICAL — DETERMINISM RULE)

**The vision model SHOULD return the datatype exactly as visible, including parameters.** Databricks-valid `DECIMAL`, `DECIMAL(p)`, and `DECIMAL(p,s)` are all complete syntax: canonicalization expands their documented defaults to `(10,0)` or `(p,0)`. Truly truncated types such as `decimal(28` are invalid input and enter the evidence-first self-correction flow before table creation.

**The LLM system prompt for ERD parsing MUST include this instruction:**

```text
For EVERY column, return the COMPLETE data type exactly as shown in the ERD image:
- decimal/numeric types: preserve exactly visible valid syntax (`decimal`, `decimal(28)`, or `decimal(28,4)`); NEVER return an unclosed value such as `decimal(28`
- varchar/char types: MUST include the length — e.g., varchar(100), NOT varchar
- If precision/scale/length is partially visible or cut off, request a targeted high-resolution crop/reparse and return the unresolved raw text for governed resolution if it remains unreadable
- NEVER return an unclosed parenthesis in a data type
- NEVER truncate a data type definition mid-specification
```

**Common vision model truncation errors (GATE 2.1b will catch these):**

| Incomplete value | Required result |
|------------------|-----------------|
| `decimal(28` | `UNRESOLVED` — targeted crop/reparse, then governed policy if eligible; never silently append scale `2` |
| `decimal(18)` | Valid Databricks syntax → canonical `decimal(18,0)` |
| `decimal` | Valid Databricks syntax → canonical `decimal(10,0)` |
| `varchar(` | `UNRESOLVED` — targeted crop/reparse, then eligible policy resolves to non-truncating `STRING` |
| `numeric(10` | `UNRESOLVED` — targeted crop/reparse, then governed policy if eligible |
| `char(` | `UNRESOLVED` — targeted crop/reparse, then eligible policy resolves to non-truncating `STRING` |

### Generated table-name resolution (before completing parse_erd)

Apply this stage’s `guardrails.md` **DL-G1** before completing the parse. Use its
source→target mapping contract and pinned target-name validator; then continue
with datatype validation below. DDL must consume the resolved names verbatim.

### GATE 2.1b: Data Type Validation (MANDATORY post-parse)

After the vision model returns the parsed ERD, load and run the exact frozen validation utility from `run_context.templates.erd_validation_utils`. The path and digest are a single authority tuple; a same-named ambient module is not an acceptable substitute.

**Load the utility:**
```python
import hashlib
import importlib.util
import inspect
import os
import re
import shutil
import sys

# Notebook placeholders: populate verbatim from the authenticated run_context.
ERD_VALIDATION_UTILS_PATH = "<run_context.templates.erd_validation_utils.path>"
ERD_VALIDATION_UTILS_SHA256 = "<run_context.templates.erd_validation_utils.sha256>"

_templates = run_context.get("templates") if isinstance(run_context, dict) else None
_expected_ref = (
    _templates.get("erd_validation_utils") if isinstance(_templates, dict) else None
)
if (
    not isinstance(_expected_ref, dict)
    or not isinstance(_expected_ref.get("path"), str)
    or not _expected_ref["path"]
    or not isinstance(_expected_ref.get("sha256"), str)
):
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: frozen ERD utility path/hash mapping is missing or malformed"
    )
if (
    ERD_VALIDATION_UTILS_PATH != _expected_ref["path"]
    or ERD_VALIDATION_UTILS_SHA256 != _expected_ref["sha256"]
):
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: notebook helper reference is not the frozen run_context tuple"
    )

# G-12: when deploy_root is frozen, bind the helper to its canonical template
# directory. Older contexts may omit deploy_root on both sides; the exact
# absolute path + raw SHA-256 tuple remains sufficient authority in that case.
handoff_deploy_root = step_handoff.get("deploy_root")
context_deploy_root = run_context.get("runtime", {}).get("deploy_root")
if bool(handoff_deploy_root) != bool(context_deploy_root):
    raise RuntimeError(
        "DATA_LAYER_INPUT_AUTHORITY_ERROR: deploy_root is present on only one authority artifact"
    )
if handoff_deploy_root and handoff_deploy_root != context_deploy_root:
    raise RuntimeError("DATA_LAYER_INPUT_AUTHORITY_ERROR: deploy_root authority mismatch")
if not os.path.isabs(os.path.normpath(ERD_VALIDATION_UTILS_PATH)):
    raise RuntimeError("ERD_VALIDATION_HELPER_CONTRACT_ERROR: utility path must be absolute")
if handoff_deploy_root:
    templates_dir = os.path.normpath(f"{handoff_deploy_root}/framework/templates")
    if os.path.dirname(os.path.normpath(ERD_VALIDATION_UTILS_PATH)) != templates_dir:
        raise RuntimeError(
            "ERD_VALIDATION_HELPER_CONTRACT_ERROR: frozen utility path is outside canonical templates_dir"
        )
if not re.fullmatch(r"[0-9a-f]{64}", ERD_VALIDATION_UTILS_SHA256):
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: utility digest must be lowercase SHA-256"
    )

try:
    with open(ERD_VALIDATION_UTILS_PATH, "rb") as handle:
        _source_bytes = handle.read()
except OSError as exc:
    raise RuntimeError(
        f"ERD_VALIDATION_HELPER_CONTRACT_ERROR: cannot read frozen utility: {exc}"
    ) from exc
if hashlib.sha256(_source_bytes).hexdigest() != ERD_VALIDATION_UTILS_SHA256:
    raise RuntimeError("ERD_VALIDATION_HELPER_CONTRACT_ERROR: source digest mismatch")

_tmp_dir = f"/tmp/pipeline_python/{ERD_VALIDATION_UTILS_SHA256}"
os.makedirs(_tmp_dir, exist_ok=True)
_utility_copy = os.path.join(_tmp_dir, "erd_validation_utils.py")
shutil.copyfile(ERD_VALIDATION_UTILS_PATH, _utility_copy)
with open(_utility_copy, "rb") as handle:
    if hashlib.sha256(handle.read()).hexdigest() != ERD_VALIDATION_UTILS_SHA256:
        raise RuntimeError("ERD_VALIDATION_HELPER_CONTRACT_ERROR: copied digest mismatch")

_module_name = f"erd_validation_utils_{ERD_VALIDATION_UTILS_SHA256[:16]}"
spec = importlib.util.spec_from_file_location(_module_name, _utility_copy)
if spec is None or spec.loader is None:
    raise RuntimeError("ERD_VALIDATION_HELPER_CONTRACT_ERROR: utility loader unavailable")
erd_utils = importlib.util.module_from_spec(spec)
sys.modules[_module_name] = erd_utils
try:
    spec.loader.exec_module(erd_utils)
except Exception as exc:
    sys.modules.pop(_module_name, None)
    raise RuntimeError(
        f"ERD_VALIDATION_HELPER_CONTRACT_ERROR: utility module execution failed: {exc}"
    ) from exc

_loaded_path = os.path.normpath(os.path.abspath(erd_utils.__file__))
_expected_loaded_path = os.path.normpath(os.path.abspath(_utility_copy))
with open(_loaded_path, "rb") as handle:
    _loaded_sha256 = hashlib.sha256(handle.read()).hexdigest()
if _loaded_path != _expected_loaded_path or _loaded_sha256 != ERD_VALIDATION_UTILS_SHA256:
    raise RuntimeError("ERD_VALIDATION_HELPER_CONTRACT_ERROR: loaded-file attestation failed")

_validate_erd_output = getattr(erd_utils, "validate_erd_output", None)
if (
    not callable(_validate_erd_output)
    or getattr(_validate_erd_output, "__module__", None) != _module_name
):
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: validate_erd_output is missing or unattested"
    )
_parameters = list(inspect.signature(_validate_erd_output).parameters.values())
if not (
    len(_parameters) == 1
    and _parameters[0].name == "tables"
    and _parameters[0].kind
    in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    and _parameters[0].default is inspect.Parameter.empty
):
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: expected validate_erd_output(tables)"
    )

_resolve_greenfield_datatypes = getattr(
    erd_utils, "resolve_greenfield_synthetic_datatypes", None
)
if (
    not callable(_resolve_greenfield_datatypes)
    or getattr(_resolve_greenfield_datatypes, "__module__", None) != _module_name
):
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: "
        "resolve_greenfield_synthetic_datatypes is missing or unattested"
    )
_resolver_parameters = list(inspect.signature(_resolve_greenfield_datatypes).parameters.values())
if not (
    len(_resolver_parameters) == 1
    and _resolver_parameters[0].name == "tables"
    and _resolver_parameters[0].default is inspect.Parameter.empty
):
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: expected "
        "resolve_greenfield_synthetic_datatypes(tables)"
    )

_validate_table_spec_projection = getattr(
    erd_utils, "validate_table_spec_projection", None
)
if (
    not callable(_validate_table_spec_projection)
    or getattr(_validate_table_spec_projection, "__module__", None) != _module_name
):
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: "
        "validate_table_spec_projection is missing or unattested"
    )
_projection_parameters = list(
    inspect.signature(_validate_table_spec_projection).parameters.values()
)
if not (
    len(_projection_parameters) == 2
    and [_parameter.name for _parameter in _projection_parameters]
    == ["erd_tables", "table_spec"]
    and all(
        _parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and _parameter.default is inspect.Parameter.empty
        for _parameter in _projection_parameters
    )
):
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: expected "
        "validate_table_spec_projection(erd_tables, table_spec)"
    )
```

No fixed-name import, ambient module reuse, hashless copy, or locally reimplemented validator is permitted. Any path, digest, load, file, or callable attestation failure HALTS with `ERD_VALIDATION_HELPER_CONTRACT_ERROR` and is owned by the Data Layer release contract.

**Run the combined validation pipeline:**
```python
# parsed_tables = the tables list from vision model YAML output
_validation_result = _validate_erd_output(parsed_tables)
if not isinstance(_validation_result, tuple) or len(_validation_result) != 2:
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: validate_erd_output returned an incompatible shape"
    )
tables, report = _validation_result
if not isinstance(tables, list) or not isinstance(report, dict) or "status" not in report:
    raise RuntimeError(
        "ERD_VALIDATION_HELPER_CONTRACT_ERROR: validate_erd_output returned malformed tables/report"
    )
if report["status"] != "PASS":
    # Do not write yet. Run the targeted evidence retry protocol below.
    unresolved_datatype_errors = list(report.get("errors", []))
# A PASS is now safe to write. A datatype-only FAIL is resolved below only in
# the explicitly eligible greenfield-synthetic scope.
```

On the first and second datatype validation failure, do not write `erd_parsed.yaml` and do not
continue downstream. Reinvoke the vision model against an original-resolution crop containing each
named table/column; merge only evidence-backed datatype values; rerun the full attested validator.
After retry 2, a remaining **datatype-only** failure MUST self-correct when all eligibility checks
hold: `data_source.type` is `erd` or `erd_and_live_schema`, `greenfield.enabled` is true, and
`greenfield.synthetic_data` is true. Call the attested `_resolve_greenfield_datatypes(tables)`, then
rerun `_validate_erd_output()` and require PASS. The resolver uses, in order: recoverable visible
components, strict-majority same-table semantic peers, strict-majority cross-table semantic peers,
release-pinned semantic numeric defaults, and non-truncating `STRING`. It preserves visible decimal
precision when valid, enforces `1 <= p <= 38` and `0 <= s <= p`, and is total for datatype defects.

After the resolved document passes validation entirely in memory, persist `erd_parsed.yaml` and
`schema_assumptions.yaml` with individually atomic replace operations, even when there are zero
resolutions. Bind the assumptions artifact to run/target/suffix, policy
`GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`, raw and resolved ERD hashes, ordered resolution rows,
evidence, confidence, and `observed: false` for every inferred value. Re-read and mutually
authenticate both persisted artifacts before marking `parse_erd` valid; if the second write or
authentication fails, neither artifact may be consumed downstream and the phase remains stale.
Missing tables/columns, duplicate identity, source/live authority, synthetic-disabled runs, or a
broken resolver contract still HALT.

The attested functions are the only implementations of this gate. Do not define a local repair
helper. Databricks default expansion is platform canonicalization; all other fallback values are
accelerator policy and MUST be disclosed as `INFERRED_POLICY`, never as observed ERD text.

**Can there be zero synthetic errors?** With this validation gate:
- **Datatype-only errors: self-corrected before DDL** — authoritative evidence wins; eligible generated-synthetic fallback is deterministic, validated, and auditable
- **Column name errors: eliminated** — `validate_domain_cols()` catches mismatches (Step 6)
- **FK errors: eliminated** — `validate_fk_replacements()` catches mismatches (Step 6)
- **Value errors: eliminated** — `verify_before_write()` catches generic values (Step 6)

The combination of prompt instructions + programmatic validation makes zero-error synthetic data achievable.

## 2.2 Observation vs Inference

- **OBSERVED**: explicitly visible in ERD (table/column names, PK/FK markers, relationship lines)
- **INFERRED**: derived through reasoning (fact vs dimension, grain, cardinality when unmarked)
- **INFERRED_POLICY**: datatype-only fallback produced by `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`; its raw value, resolved value, evidence, confidence, and hashes live in `schema_assumptions.yaml`

Never present `INFERRED` or `INFERRED_POLICY` as observed.

## 2.3 Confidence Classification

Every inferred item: `HIGH | MEDIUM | LOW | UNRESOLVED`

A relationship MUST NOT be created solely from column-name similarity.

## 2.4 Determine Table Grain

For every table: "One row represents ______." Infer from key structure, relationships, column semantics. If uncertain: `grain: UNRESOLVED`.

## 2.5 Canonical Schema Contract

Write `{OUTPUT_FOLDER}/erd_parsed.yaml`:

```yaml
tables:
  - name: table_name
    observed:
      columns:
        - name: column_name
          datatype: string
          nullable: unknown
          key_marker: PK | FK | NONE | UNKNOWN
    inferred:
      semantic_role: FACT | DIMENSION | BRIDGE | EVENT | SNAPSHOT | REFERENCE | UNKNOWN
      business_entity: description
      grain: one row represents ...
      primary_key:
        columns: [...]
        confidence: HIGH | MEDIUM | LOW | UNRESOLVED
      foreign_keys:
        - columns: [...]
          references_table: ...
          references_columns: [...]
          cardinality: 1:1 | 1:N | N:1 | N:M | UNKNOWN
          confidence: ...
          evidence: ...
relationships: [...]
unresolved_items: []
```

### Unresolved Items Decision Gate

Before marking UNRESOLVED, note candidate relationships using these quick signals:

1. **Column naming conventions** — matching `*_sk`, `*_id`, `*_key` patterns across tables
2. **Shared business-key patterns** — e.g., `clm_hdr_claim_nbr` ↔ `clm_dtl_claim_nbr` indicates header→detail
3. **Domain semantics** — tables named `*_header` and `*_detail` or `*_master` and `*_transaction`
4. **KPI spec join paths** — KPI definitions referencing measures from multiple tables
5. **Identical column name + compatible type** in two tables

Record candidates in `erd_parsed.yaml` under `unresolved_items` with their signal and estimated confidence. **The full inference protocol runs in Step 3.4** (Intelligent Relationship Inference), which formally classifies, adds to `semantic_model.yaml`, and ensures they flow into generation_order and FK_REPLACEMENTS.

Only mark UNRESOLVED after Step 3.4 has run and the relationship still cannot be classified as HIGH or MEDIUM confidence.

**HALT** if unresolved item blocks a required fact→dimension join, a PK referenced by an FK, or a KPI-referenced column. **WARN** otherwise.

## 2.5a Collect extraction findings before deployment admission

An unreadable table or unusable `observed.columns` list is a finding to investigate
within `parse_erd`; it is not permission to invent columns or immediately abandon
analysis of the remaining ERD. Apply this protocol for fresh, cached, and resumed input:

1. Keep the complete source table inventory, including unreadable tables. For each defect,
   append a finding to the current `parse_erd` findings using the existing shared progress
   and persistence contract. Include the table identity (or source location if unreadable),
   exact failing field, frozen source path and image region, observed evidence, attempted
   recovery/count, affected joins/KPIs when known, and the next action. Clearly distinguish
   missing source evidence from a serialization defect. Do not expose guesses as observations.
2. Continue extracting other readable tables and collecting their columns, relationships,
   and uncertainty within the same `parse_erd` phase. Keep analysis involving the unreadable
   table unresolved. Do not start `build_semantic_model`, DDL, synthetic generation, or any
   dependent stage; this is continued analysis, not parallel phase execution.
3. Attempt a targeted source crop for each affected table at most twice, tracking attempts
   across the current recovery/resume so repeated validation cannot reset the budget. If
   the original vision evidence already contains exact column identities and values, correct
   their serialization to §2.5 and record the evidence/mapping instead of inventing values.
   Update each finding with the recovery result; retain the attempt history. Datatype-only
   issues follow GATE 2.1b after structural recovery.
4. Persist the rejected/draft candidate and accumulated findings as diagnostic evidence under
   the current run's output folder using the shared transport. Label drafts incomplete and
   report their exact paths; never overwrite an accepted canonical artifact with a draft or
   register diagnostic files as successful parse outputs. With no `report_progress` tool,
   use the shared portable persistence path and include the same findings in the master handoff;
   no Lakebase dependency is introduced. Progress remains `update` while analysis continues.
5. After all independently readable tables have been analyzed and bounded recovery is exhausted,
   execute the complete structural and existing datatype/provenance gates. If defects remain,
   report `parse_erd` as `failed` with all unresolved blockers and diagnostic paths, then return
   to the master. Describe the schema as incomplete/blocked in the finding text; do not invent
   a new progress/checkpoint status. The master marks any existing parse checkpoint and its
   dependents `STALE`; no new `VALID` checkpoint or completion event is allowed. Do not deploy
   a subset, drop unreadable tables, or advance downstream. Request the specific missing source
   detail after collecting findings, rather than stopping at the first unreadable table.
6. If recovery succeeds, validate the complete candidate, persist the canonical artifacts,
   re-read and authenticate them, and only then complete `parse_erd` using the existing
   checkpoint contract. Preserve resolved findings as history.

Catch the structural gate's `ERD_EXTRACTION_ERROR` within this analysis/recovery protocol
and record it as a finding; do not let an expected candidate-validation exception escape
an analysis tool as an unhandled critical failure before the remaining tables are examined.
This does not suppress transport, authentication, or runtime failures and never converts
failed validation into PASS. A structural failure discovered by the DDL runtime still halts
that notebook; return to the master for parse-owned recovery rather than continuing DDL.

## 2.6 Structural Contract Rules

Once written, `erd_parsed.yaml` is authoritative for intended tables, columns, and datatypes. `table_spec.yaml` MUST reproduce that physical schema exactly. Downstream MUST NOT invent/remove columns, change datatypes, create surrogate keys, or reinterpret the ERD.

**GATE 2.1**: Execute `validate_erd_structure` from `validation.md` on the candidate and persisted `erd_parsed.yaml` readback. Require every table to have a nonempty `observed.columns` list with unique, nonempty identities; a nonempty `tables` array alone is insufficient. Apply the bounded source-based recovery in that gate on failure. Do not complete `parse_erd` or deploy DDL until structural, datatype, provenance, and projection validation pass.

---

# Step 3: Build Semantic/Data Model

Write `{OUTPUT_FOLDER}/semantic_model.yaml` consuming the Canonical Schema Contract.

## 3.1 Table Classification

For each table: `semantic_role` (FACT | DIMENSION | BRIDGE | EVENT | SNAPSHOT | REFERENCE), `business_entity`, `grain`.

## 3.2 Column Classification

Classify every column: PRIMARY_KEY, FOREIGN_KEY, BUSINESS_IDENTIFIER, MEASURE, CATEGORICAL_ATTRIBUTE, DESCRIPTIVE_ATTRIBUTE, DATE, TIMESTAMP, STATUS, QUANTITY, MONETARY, BOOLEAN, DERIVED, FREE_TEXT, UNKNOWN.

For measures, identify aggregation: SUM, COUNT, COUNT_DISTINCT, MIN, MAX, AVG, NON_ADDITIVE, UNKNOWN.

## 3.3 Relationship Graph & Generation Order

Construct dependency graph from PK/FK **AND inferred relationships** (from the Unresolved Items Decision Gate in Step 2). Both ERD-declared and inferred relationships participate in the generation order. Compute generation order (dimensions before facts, parents before children). For every relationship determine join safety:

```yaml
left_grain:
right_grain:
cardinality:
fanout_risk:
```

Mark `FANOUT_RISK` when joining could multiply rows.

## 3.4 Intelligent Relationship Inference (MANDATORY)

The ERD and initial FK parsing may not capture all valid relationships — especially between related fact tables (e.g., claim_header ↔ claim_detail) or when FK annotations are partially visible in the ERD image. This step uses schema analysis to discover relationships the ERD parsing missed, **before** DDL and synthetic data generation.

### Why this runs here (not downstream)

Inferred relationships MUST be in `semantic_model.yaml` BEFORE Step 5 (synthetic data spec) and Step 6 (data generation), because:
- The generation_order depends on parent→child relationships
- FK_REPLACEMENTS in Step 6 reads relationships from `semantic_model.yaml`
- If an inferred relationship is discovered AFTER data generation, the synthetic data won’t have linked FK values, and downstream cardinality probes will fail with zero matches

### Phase 1: Column-Name Pattern Analysis

For every pair of tables in the schema, identify candidate join keys using these signals (ordered by confidence):

| Signal | Confidence | Example |
|--------|-----------|----------|
| Matching PK/FK column names across tables | HIGH | `claim_id` in header and detail |
| Column name contains other table's entity name + `_sk`/`_id`/`_key` | HIGH | `clm_member_sk` in fact referencing `dim_member.member_sk` |
| Shared business-key column name pattern (prefix match) | HIGH | `clm_hdr_claim_nbr` ↔ `clm_dtl_claim_nbr` |
| Domain-standard naming (header/detail, parent/child, master/transaction) | MEDIUM | Tables named `*_header` and `*_detail` |
| KPI spec join paths — KPI definitions referencing measures from multiple tables | MEDIUM | KPI formula mentions columns from two tables |
| Same column type + name substring overlap | LOW | Requires downstream data validation |

### Phase 2: Classification

| Pattern Confidence | Action |
|-------------------|--------|
| HIGH (2+ signals align) | Add to `semantic_model.yaml` as a **first-class relationship** with `confidence: inferred`, `evidence: <signals>`. Include in generation_order and FK_REPLACEMENTS. |
| MEDIUM (1 signal) | Add with `confidence: inferred_medium`. Include in generation_order and FK_REPLACEMENTS. Flag for downstream validation. |
| LOW (type match only) | Record in `unresolved_items` with `confidence: low_needs_validation`. Do NOT include in FK_REPLACEMENTS. |

### Output

Inferred relationships are added directly to `semantic_model.yaml` under `relationships:` with the same shape as ERD-declared relationships so generation can process them consistently. Their provenance and confidence MUST remain distinguishable. `semantic_model.yaml` records relationship intent, not deployed-data proof.

```yaml
relationships:
  # ERD-declared:
  - parent: dim_member
    parent_key: member_sk
    child: fact_claim_header
    child_key: clm_member_sk
    cardinality: "1:N"
    confidence: erd_declared
  # Inferred:
  - parent: fact_claim_header
    parent_key: clm_hdr_claim_nbr
    child: fact_claim_detail
    child_key: clm_dtl_claim_nbr
    cardinality: "1:N"
    confidence: inferred
    evidence: "shared business-key pattern (claim_nbr) + header/detail table naming"
```

Because inferred relationships are first-class in `semantic_model.yaml`:
- Step 3.3 generation_order already includes them (parent before child)
- Step 5 synthetic data spec treats them like any FK
- Step 6 `FK_REPLACEMENTS` automatically includes them (reads from semantic_model.yaml)
- Step 7 validates every declared and inferred relationship against deployed data
- Downstream steps, including Metric Views, may use a relationship only when its matching relationship-level entry in `data_layer_validation.yaml` has `validation_status: PASS`

**GATE 3.2**: Relationship inference completed. Document results (empty list is acceptable if no new relationships found beyond ERD-declared ones).

**GATE 3.1**: `semantic_model.yaml` exists with `generation_order` and all relationships (ERD + inferred). HALT if missing.

---

# Step 4: Generate DDL from Declarative Table Spec

### Pre-Flight

- [ ] `erd_parsed.yaml` exists (this run)
- [ ] All HALT-level items resolved
- [ ] Every table has documented grain
- [ ] Every PK identified
- [ ] exact frozen `run_context.templates.ddl_notebook.path` loaded

### Process (Three-Plane Architecture)

**Generation Plane (LLM):**
1. Produce `{OUTPUT_FOLDER}/table_spec.yaml` — a declarative specification of all tables
2. This spec is derived from `erd_parsed.yaml` and contains table names, columns, types, and comments
3. The LLM does NOT write CREATE TABLE SQL — the compiler does that deterministically

Datatype fields are a deterministic projection, not a creative LLM output. The control/runtime
must copy each exact validated `erd_parsed.yaml` datatype into the corresponding table-spec column.
An eligible datatype-only inference must already be resolved and disclosed by the named policy in
`schema_assumptions.yaml`; the SQL generation plane never invents a type. If a derived table-spec
type is incomplete or differs, regenerate it from the resolved ERD and record the change in
`ddl_preflight.yaml`.

**Control Plane (Validator/Compiler):**
4. Run programmatic GATE 4.0 with the digest-attested
   `validate_table_spec_projection(erd_tables, table_spec)` function. A failure routes to the
   owning ERD-reparse or table-spec-regeneration action and MUST occur before notebook deployment.
5. **Apply guardrails DL-G4 and shared G-16, then deploy DDL notebook from template** — call the `deploy_from_template` tool with:
   - `template_path`: exact frozen `run_context.templates.ddl_notebook.path`
   - `output_path`: `{OUTPUT_FOLDER}/notebooks/ddl_{DOMAIN_NAME}.py`
   - `placeholders`: the complete map returned by executable GATE TEMPLATE-BINDING in `validation.md`, using this template’s authenticated bytes and the current context/handoff
   - Build the entire call with `build_data_deployment_request` from that gate and submit its returned request unchanged. For synthetic deployment, rebuild from the synthetic template: do not reuse the DDL request. Its `ASSET_SUFFIX` must be the authenticated persisted suffix.
   This tool reads the template verbatim and performs ONLY placeholder substitution.
   DO NOT use `import_notebook` for this — it will reject template-based paths (G-16 enforcement).
   Read the frozen template for binding validation; leave rendering and import to the deployment transport under shared G-16.
6. The DDL template reads `table_spec.yaml` and compiles it into CREATE TABLE IF NOT EXISTS statements
7. Four gates run before execution (see gate_checks framework)

**Execution Plane (Runtime):**
8. Execute the DDL notebook only after GATE 4.0 PASS (template revalidates the spec, generates SQL, and executes via spark.sql)

### Declarative Table Spec Schema

```yaml
# table_spec.yaml — declarative DDL specification
# LLM produces this. Compiler (ddl_notebook template) generates CREATE TABLE SQL from it.
catalog: "{{TARGET_CATALOG}}"
schema: "{{TARGET_SCHEMA}}"
asset_suffix: "{{ASSET_SUFFIX}}"
tables:
  - name: dim_member
    comment: "Member dimension from ERD"
    columns:
      - name: member_sk
        type: BIGINT
        nullable: false
      - name: mbr_source_member_id
        type: STRING
        nullable: true
      - name: mbr_dob
        type: DATE
        nullable: true
      # ... all columns from erd_parsed.yaml
  - name: fact_claim_detail
    comment: "Claim detail fact from ERD"
    columns:
      - name: clm_dtl_claim_id
        type: STRING
        nullable: false
      - name: clm_dtl_billed_amt
        type: DECIMAL(27,4)
        nullable: true
      # ... all columns from erd_parsed.yaml
```

**Rules:**
- Apply DL-G5: copy each `erd_parsed.tables[].observed.columns[].datatype` to
  `table_spec.tables[].columns[].type`; preserve column identity/order and exact resolved types.
- The compiler (template) generates `CREATE TABLE IF NOT EXISTS` with proper SQL syntax
- The LLM NEVER writes SQL — only the declarative spec above
- Backtick and comma issues are eliminated because the compiler controls SQL syntax

**GATE 4.0: Expected Schema Contract (MANDATORY before DDL execution)**

Authenticate `schema_assumptions.yaml` first, including its run/target/suffix, policy ID, raw ERD
hash, resolved ERD hash, and ordered decision rows. Normalize and compare the table, column, and
datatype definitions in `table_spec.yaml` with the resolved `erd_parsed.yaml`; they MUST match
exactly. HALT with `SCHEMA_CONTRACT_ERROR` on any missing, unexpected, renamed, or retyped table or
column. `table_spec.yaml` is the expected deployment schema only after this gate passes.

This gate is programmatic, not a prose review. Parse both current-run artifacts with duplicate-key
rejection and call the already digest-attested helper before `deploy_from_template` or
`execute_notebook`:

Execute `project_table_spec_types` from GATE 4.0 in the already loaded `validation.md`:

```python
table_spec, type_replacements = project_table_spec_types(
    erd_parsed["tables"], table_spec, _validate_table_spec_projection
)
```

Persist only this validated candidate and its replacement evidence, then read back
and validate the persisted artifact per GATE 4.0. Do not raise a preliminary
SCHEMA_CONTRACT_ERROR for missing derived `type` before this bounded projection.
Do not persist or deploy a candidate whose final validation fails.

An eligible datatype-only `ERD_EXTRACTION_ERROR` routes through the bounded targeted-crop protocol,
then the governed resolver, and regenerates both `erd_parsed.yaml` and `table_spec.yaml` before
deployment. Structural extraction errors remain terminal. `SCHEMA_CONTRACT_ERROR` regenerates only
the deterministic table-spec projection from the already resolved ERD. Neither rejected artifact
may reach `execute_notebook`.

The DDL runtime repeats this gate before its first Spark SQL statement. As defense in depth, an
eligible unresolved datatype is passed through the same release-pinned resolver, the ERD is
atomically rewritten, resolver idempotence is proved, and `schema_assumptions.yaml` is written with
input/output hashes. The runtime then regenerates `table_spec.tables[].columns[].type` from the
resolved ERD, reruns exact projection validation, and writes `{OUTPUT_FOLDER}/ddl_preflight.yaml`.
Structural differences still fail. Source/live or synthetic-disabled inputs never enter this path.

### Pre-mutation DDL notebook routing exception

An `execute_notebook` failure remains critical by default. A datatype-only defect should not reach
execution because both the parse gate and runtime backstop self-correct it. The only retry exception
requires authenticated current-run `ddl_preflight.yaml` with `status: FAIL`,
`catalog_mutation_started: false`, matching run/target/suffix and raw/resolved ERD/table-spec hashes.
For an eligible datatype-only `ERD_EXTRACTION_ERROR`, perform the bounded reparse, invoke the governed
resolver, authenticate `schema_assumptions.yaml`, regenerate the table spec, and execute once. For a
projection-only `SCHEMA_CONTRACT_ERROR`, regenerate the table spec once from the resolved ERD. Never
retry blindly; missing/contradictory evidence, structural loss, or any catalog mutation halts.

### DDL Pattern (compiler-generated, NOT LLM-generated)

```sql
-- Generated by compiler from table_spec.yaml
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.{table_name}{asset_suffix} (
  column_name DATATYPE,
  column_name DATATYPE,
  last_column DATATYPE
) USING DELTA
COMMENT '{table description}';
```

**GATE 4.1**: `SHOW TABLES IN {catalog}.{schema} LIKE '*{ASSET_SUFFIX}'` returns expected count. `ASSET_SUFFIX` is the exact frozen `step_handoff.yaml.asset_suffix`. HALT if fewer.

### GATE 4.2 / `reconcile_schema`: Schema Reconciliation (MANDATORY after DDL execution)

Apply DL-G6 diagnostic capture starting with DDL deployment/execution, before any
agent-authored reconciliation or checkpoint operation. Preserve producer output;
validate it instead of replacing it. Include diagnostic evidence paths when returning
a producer-contract failure to the master.

After GATE 4.1 passes, verify that each table's **actual deployed schema** from `DESCRIBE TABLE` matches the **expected generated schema** in `table_spec.yaml`. GATE 4.0 already proves that `table_spec.yaml` is an exact projection of `erd_parsed.yaml`. This ensures `CREATE TABLE IF NOT EXISTS` cannot hide schema drift when an object already exists.

This is a distinct reusable phase and a hard execution boundary. Call `report_progress` with
`phase_id: reconcile_schema` before readback. The deterministic DDL runtime MUST atomically write
`{OUTPUT_FOLDER}/schema_reconciliation.yaml` on both PASS and FAIL before any Step 5 work. Mark the
phase `VALID` only after DL-G6 / GATE RECONCILIATION-PROVENANCE passes and a persisted PASS artifact authenticates the current run, asset suffix,
target, raw `table_spec.yaml` SHA-256, expected/readback schema fingerprints, policy ID, attempts,
and an empty `unresolved_mismatches` list. A FAIL artifact is durable diagnostic evidence, never
permission to continue.

After a PASS, apply the shared Reusable-Phase Completion Commit before Step 5: atomically upsert
the exact `create_data_layer` / `reconcile_schema` `VALID` record into `run_context.yaml`, re-read
and verify exactly one matching record, emit a schema-valid structured JSON progress object, and
let the App adapter mirror progress without making Lakebase readback a portable admission gate. Immediately before launching the
synthetic-data notebook, re-read `run_context.yaml` and require that same record to remain `VALID`.
A PASS `schema_reconciliation.yaml` with a missing/unacknowledged phase record is
`CHECKPOINT_PERSISTENCE_ERROR`; do not launch synthetic data and do not repeat reconciliation or
DDL merely to repair checkpoint persistence.

For the observed missing-write case only, perform one bounded checkpoint-only recovery before
Step 5: require zero existing `reconcile_schema` records, authenticate the current-run PASS
artifact and its table-spec digest, recompute the exact fresh catalog fingerprint, construct the
canonical record from frozen checkpoint metadata, and run the same workspace/App commit barrier.
This recovery writes orchestration state only; it never reruns DDL or reconciliation. A duplicate,
`STALE`, malformed, conflicting, or still-uncommittable record remains
`CHECKPOINT_PERSISTENCE_ERROR` and cannot admit synthetic writes.

If this missing-only recovery finds that `checkpointing.frozen_run_contract_sha256` differs from
the deterministic digest of the current immutable envelope, it may repair the stored digest only
when `phases_completed` is exactly empty and all artifact, identity, inventory, hash, fresh-readback,
and empty-target gates have already passed. Atomically persist the corrected envelope together with
the first recovered phase record and re-read both. Once any phase record exists, a frozen-digest
mismatch is immutable authority conflict and still halts.

**DDL-runtime algorithm (already executed inside the notebook):**

The following describes runtime behavior, not a second agent-authored Python script.
After notebook success, apply read-only GATE 4.2 validation: compare the artifact's
raw hash to the DDL manifest, validate the complete producer contract, perform fresh
catalog readback, and commit only the checkpoint. Never replace reconciliation with
a new summary or prior-version artifact. Write separate diagnostics for any drift.

```text
For each table in table_spec.yaml:
  1. Run DESCRIBE TABLE {catalog}.{schema}.{table_name}{asset_suffix}
  2. Extract actual column names and datatypes (excluding partition info/metadata rows)
  3. Extract expected column names and datatypes from table_spec.yaml
  4. Normalize equivalent Databricks type spellings, then compare actual_schema vs expected_schema

  If any normalized DATATYPE MISMATCH exists:
    a. Record the exact expected type from table_spec.yaml and observed type from DESCRIBE TABLE
    b. Prove the table is the exact current-run greenfield generated target in the frozen target
       catalog/schema with the exact asset_suffix; reject source/live/unversioned/wildcard identity
    c. Run SELECT COUNT(*) and require an exact result of 0
    d. Require no prior datatype-repair attempt for this table in the current run
    e. If every check passes:
       → DROP only that exact empty table
       → Re-run the pinned compiler-generated CREATE statement from unchanged table_spec.yaml
       → Re-run DESCRIBE TABLE and require exact canonical name/type equality
       → Record one successful DROP_RECREATE_FROM_TABLE_SPEC attempt
    f. Otherwise, or if post-repair readback still differs:
       → Write schema_reconciliation failure evidence
       → HALT with DATATYPE_MISMATCH_UNSAFE_TO_REPAIR
       → Do not DROP, ALTER, cast, coerce, overwrite, or mutate intent

  If the mismatch is limited to missing, unexpected, or renamed columns:
    a. Record the exact expected and observed column sets before any action
    b. Apply the SAME ownership and safety gate used above: prove the exact current-run
       greenfield generated FQN from table_spec.yaml in the frozen target catalog/schema with
       the exact asset_suffix; reject a source/live/unversioned/wildcard/ambiguous identity
    c. Run SELECT COUNT(*) successfully and require the exact result 0
    d. Require no earlier automatic schema-reconciliation repair attempt for this table in this run
    e. If every check passes:
       → DROP only that exact empty table
       → Re-run the pinned compiler-generated CREATE TABLE statement from unchanged table_spec.yaml
       → Re-run DESCRIBE TABLE and require exact canonical name/type equality
       → Record one DROP_RECREATE_FROM_TABLE_SPEC attempt and its post-repair readback
    f. Otherwise, or if post-repair readback still differs:
       → Write schema_reconciliation failure evidence
       → HALT with SCHEMA_CONTRACT_ERROR
       → Do not DROP, ALTER, cast, coerce, overwrite, or mutate intent

  If MATCH: continue
```

Any structural mismatch remaining after an empty-table recreation is a `SCHEMA_CONTRACT_ERROR`; HALT. Any datatype mismatch remaining after the single eligible repair is `DATATYPE_MISMATCH_UNSAFE_TO_REPAIR`; HALT. Never skip an expected column, include an unexpected deployed column, coerce a datatype, or modify an intent artifact to accept drift.

On PASS, persist the `reconcile_schema` checkpoint with the raw artifact digest and current catalog
readback fingerprint. On FAIL, persist the classified failure and HALT immediately; do not build
`synthetic_data_spec.yaml`, run PK/FK/domain checks, or execute dbldatagen.

Apply DL-G7: read the current DDL manifest's `reconcile_schema_output_fingerprints`.
After authenticating its artifact digest and fresh readback, copy that exact list into
the new checkpoint; do not reconstruct IDs, kinds, locators, or inventory shapes from
memory. Re-read the persisted checkpoint and compare every field before deployment.
A prior malformed checkpoint follows master invalidation/recommit rules, not missing-only
checkpoint recovery. Never modify the producer artifact to make a checkpoint match.

The phase's sorted `output_fingerprints` are exactly:

```yaml
- id: schema_reconciliation_artifact
  kind: RAW_BYTES
  locator: "{OUTPUT_FOLDER}/schema_reconciliation.yaml"
  sha256: <SHA-256 of exact artifact bytes>
- id: schema_reconciliation_catalog_readback
  kind: CATALOG_READBACK
  locator: "table_spec:{catalog}.{schema}:{asset_suffix}"
  sha256: <canonical CURRENT_OBSERVED_INVENTORY fingerprint, same ordered structure as the DDL runtime>
```

The dbldatagen runtime MUST authenticate both exact entries before checking that every append target
is empty. An existence-only artifact check or a phase status without these fingerprints cannot
admit a write.

**Why this is safe:**
- Suffix matching alone never proves ownership; the exact FQN must also be an expected current-run
  greenfield target in the frozen namespace and must not be source/live/unversioned or ambiguous
- A successful exact-zero row-count check is mandatory; unreadable or non-empty objects are never dropped
- Automatic schema reconciliation is bounded to one compiler-driven recreation attempt for one
  exact FQN from unchanged `table_spec.yaml`
- A non-empty target causes an immediate no-mutation HALT. Manual confirmation does not authorize
  this automatic pipeline to repair, drop, recreate, cast, or coerce it; any operator-led migration
  occurs outside the pipeline.

**Why this is necessary:**
- `CREATE TABLE IF NOT EXISTS` does NOT alter existing table schemas
- The ERD vision model is non-deterministic — it may parse different column counts on different runs
- Without this gate, the synthetic data step (Step 5/6) builds specs from `erd_parsed.yaml` that reference columns that don't exist in the actual table, causing `validate_domain_cols()` to raise `AssertionError`

---

# Step 5: Build Synthetic Data Specification

Run only when `run_context.data_source.greenfield.synthetic_data: true`.

**Hard admission gate:** execute DL-G6 / GATE RECONCILIATION-PROVENANCE on the runtime-owned artifact without rewriting it, then authenticate the current `reconcile_schema` phase record and exact
`schema_reconciliation.yaml` bytes. Require policy `DEPLOYED_DATATYPE_REPAIR_V1`, `status: PASS`,
zero unresolved mismatches, matching run/target/suffix/table-spec hashes, and a fresh `DESCRIBE`
fingerprint equal to the persisted readback fingerprint. Exactly zero phase records may enter only
the bounded checkpoint-only recovery defined above; it must atomically persist and re-read the
reconstructed record before proceeding. Failed, stale, duplicate, conflicting, changed, or
unrecoverable evidence HALTS before creating the synthetic specification.

For backward compatibility only, `schema_reconciliation.catalog`, `.schema`, and `.output_folder`
may be absent/null when the artifact was loaded from the exact canonical sibling path
`{OUTPUT_FOLDER}/schema_reconciliation.yaml` and every run, suffix, table-spec target,
assumptions, fully qualified expected/observed inventory, digest, and fresh readback gate passes.
Each present value must equal its frozen value exactly; any conflict still halts. Newly written
reconciliation artifacts always include all three fields.

Create `{OUTPUT_FOLDER}/synthetic_data_spec.yaml` from: `erd_parsed.yaml` + `semantic_model.yaml` + KPI context + volume config.

### Column Authority Rule (CRITICAL)

After GATE 4.2, the **actual deployed table schema** from `DESCRIBE TABLE` is authoritative for executable column names and datatypes. Its physical schema MUST equal `table_spec.yaml`, which GATE 4.0 has already reconciled to `erd_parsed.yaml`. Use `semantic_model.yaml` only for semantic roles, domains, grain, and relationship intent.

**Before building the synthetic data spec, for EACH table:**

```text
1. Run: DESCRIBE TABLE {catalog}.{schema}.{table_name}{asset_suffix}
2. Use the returned column names and datatypes as the definitive executable schema
3. Verify it still matches table_spec.yaml exactly
4. Cross-reference semantic_model.yaml for semantic context and relationship intent
5. If any expected column is missing or any unexpected column exists, HALT with SCHEMA_CONTRACT_ERROR and rerun GATE 4.2
```

Never silently skip an expected column or generate an unexpected deployed column with defaults. Schema drift must be reconciled or halted before synthetic specification generation.

## 5.1 Generation Philosophy

Synthetic data MUST be: **ENTITY-FIRST, RELATIONSHIP-AWARE, DOMAIN-AWARE, SEMANTICALLY COHERENT.** Not independent random columns.

### Demo-Quality Distribution Requirements (CRITICAL)

Uniform distributions produce useless dashboards (all bars same height, filters don't change values).

**Required skew patterns:**

1. **Financial measures by category** — different categories MUST have clearly different cost profiles (e.g., 100x difference between high-cost and low-cost categories)
2. **Volume by dimension** — primary values MUST have unequal row counts (e.g., top 3 get 50%, bottom 2 get 8%)
3. **Rate measures by category** — denial rates, approval rates, etc. MUST vary by dimension

Use `WEIGHTED_CATEGORICAL` for dimension columns. Vary `NUMERIC_RANGE` by category for financial columns.

## 5.2 Column Generation Specification

Apply this stage’s `guardrails.md` **DL-G2** for the executable
`synthetic_data_spec.yaml` schema, FK fields, and complete-spec preflight.
The column-level structure below is planning metadata, not the notebook input.

For every column:

```yaml
column:
datatype:
semantic_type:
generation_strategy:  # SEQUENTIAL_ID | PARENT_KEY_SAMPLE | CATEGORICAL_VALUES | WEIGHTED_CATEGORICAL | NUMERIC_RANGE | DISTRIBUTION | DATE_RANGE | TIMESTAMP_RANGE | BOOLEAN | DERIVED | FREE_TEXT | STATIC
nullable_probability:
domain:
distribution:
dependencies:
constraints:
```

## 5.3 Domain-Aware Value Generation (MANDATORY — CRITICAL)

This is the **#1 quality gate** for synthetic data. Generic values (`val_1`, `val_2`, `A`, `B`, `C`) render all downstream artifacts useless — dashboards show meaningless labels, Genie cannot answer questions about categories, filters have no semantic meaning.

### Domain Value Inference Protocol (MANDATORY for every categorical column)

For EVERY column classified as CATEGORICAL_ATTRIBUTE, STATUS, or having strategy CATEGORICAL_VALUES / WEIGHTED_CATEGORICAL, the LLM MUST execute this inference chain:

```text
Step 1: Parse column name → identify semantic concept
        (e.g., "claim_type" → type of insurance claim)

Step 2: Identify parent entity from table name
        (e.g., table "fact_claim_detail" → medical/insurance claims domain)

Step 3: Cross-reference with KPI spec terminology
        (e.g., KPI mentions "Institutional vs Professional" → use those exact terms)

Step 4: Generate 3-10 domain-realistic values using industry knowledge
        (e.g., ["Institutional", "Professional", "Pharmacy", "Dental", "Vision"])

Step 5: Assign weights reflecting real-world distribution skew
        (e.g., [0.30, 0.35, 0.15, 0.12, 0.08])
```

### Value Inference Patterns (by column name pattern)

| Column Name Contains | Semantic Concept | Example Values |
|---------------------|-----------------|----------------|
| `status`, `_sts` | Workflow state | Domain-specific states (Approved/Denied/Pending, Active/Inactive, Open/Closed) |
| `type`, `_typ` | Entity classification | Domain entity types (Institutional/Professional, Checking/Savings, Inbound/Outbound) |
| `category`, `_cat` | Grouping/segment | Business-meaningful segments |
| `code` (short VARCHAR) | Industry standard code | Format-correct codes (ICD-10, CPT, SIC, ZIP patterns) |
| `place`, `location`, `site` | Physical/logical location | Domain-appropriate location types |
| `flag`, `_ind` | Binary indicator | Y/N or domain-specific binary (Clean/Not Clean) |
| `region`, `state`, `country` | Geography | Real geography codes/names |
| `channel`, `source` | Origin/method | Business channels (Web/Phone/In-Person, Direct/Broker) |
| `priority`, `severity`, `level` | Ordinal ranking | Domain-appropriate levels (Critical/High/Medium/Low) |
| `gender`, `sex` | Demographics | M/F/U or Male/Female/Unknown |
| `plan`, `product`, `lob` | Business product | Actual product/plan types from the domain |

### PROHIBITED Value Patterns (GATE 5.1 will reject these)

```yaml
# ALL of these are FORBIDDEN in synthetic_data_spec.yaml:
values: ["val_1", "val_2", "val_3"]          # Generic numbered placeholders
values: ["A", "B", "C", "D"]                  # Single-character placeholders
values: ["type1", "type2", "type3"]           # Generic typed placeholders
values: ["cat_1", "cat_2", "cat_3"]           # Generic prefixed placeholders
values: ["status_a", "status_b"]              # Generic status placeholders
template: "\w\w\w\w"                       # Random Lorem Ipsum text
```

```yaml
# CORRECT — domain-meaningful values:
values: ["APPROVED", "DENIED", "PENDING", "IN_REVIEW"]
values: ["Institutional", "Professional", "Pharmacy", "Dental", "Vision"]
values: ["11", "21", "22", "23", "31", "32", "41"]  # CMS Place of Service codes
values: ["COMMERCIAL", "MEDICARE", "MEDICAID", "TRICARE"]
```

### GATE 5.1: Domain Value Validation

After writing `synthetic_data_spec.yaml`, scan ALL columns with strategy `CATEGORICAL_VALUES` or `WEIGHTED_CATEGORICAL`. The spec FAILS if ANY column has:
- Values matching pattern `val_\d+`, `[A-Z]` single chars, `type\d+`, `cat_\d+`, `status_[a-z]`
- Fewer than 3 values for a column with cardinality > 2
- Values that are clearly not domain-relevant (column is `claim_type` but values are `["foo", "bar", "baz"]`)

If GATE 5.1 fails: regenerate the spec for failing columns using the Domain Value Inference Protocol above. Do NOT proceed to Step 6 with generic values.

## 5.4 YAML Type Safety (DETERMINISM RULE — CRITICAL)

**Type-safety rationale:** YAML auto-parses unquoted numeric-looking values as integers. A procedure code `99213` written without quotes becomes `int(99213)` in Python, while `D0120` stays `str("D0120")`. Mixing both in a VARCHAR domain list causes a Spark write-time `NumberFormatException`.

**The LLM generating `synthetic_data_spec.yaml` already HAS the column types from `erd_parsed.yaml`.** It MUST use them to ensure proper YAML output:

### Rule: Match YAML Value Format to Column DDL Type

| Column DDL Type | YAML Value Format | Example |
|----------------|------------------|--------|
| VARCHAR(N), STRING, CHAR(N) | ALL values MUST be quoted strings | `values: ["99213", "D0120", "99396"]` |
| TIMESTAMP, TIMESTAMP_NTZ | Full datetime with time component | `begin: "2020-01-01 00:00:00"` |
| DATE | Date-only string (YYYY-MM-DD) | `begin: "2020-01-01"` |
| BIGINT, INT, INTEGER | Unquoted integers | `values: [1, 2, 3]` |
| DOUBLE, FLOAT, DECIMAL | Unquoted decimals | `values: [10.5, 20.3]` |
| BOOLEAN | Unquoted booleans | `values: [true, false]` |

### PROHIBITED (causes mixed-type lists):

```yaml
# WRONG — procedure codes without quotes (YAML parses 99213 as int):
values: [99213, D0120, 99396, J0585]

# WRONG — timestamps as date-only (causes ValueError in dbldatagen):
begin: 2020-01-01
end: 2024-12-31
```

### CORRECT:

```yaml
# CORRECT — ALL values quoted for VARCHAR column:
values: ["99213", "D0120", "99396", "J0585"]

# CORRECT — full datetime for TIMESTAMP column:
begin: "2020-01-01 00:00:00"
end: "2024-12-31 23:59:59"
```

### GATE 5.2: YAML Type Safety Validation (MANDATORY before writing spec)

After constructing the spec dict and BEFORE serializing to YAML, apply `coerce_spec_values_for_yaml(spec_tables, erd_tables)`. This function:

1. Builds a type lookup from ERD parse output (`{table: {col: ddl_type}}`)
2. For each column with domain values:
   - String columns (`char`, `string` in DDL type) → `str(v)` for ALL values
   - Timestamp columns → append ` 00:00:00` to any date-only value (10-char YYYY-MM-DD)
   - Integer columns → `int(v)` for all values
   - Float/decimal columns → `float(v)` for all values
3. Returns the coerced spec (safe for YAML serialization)

**Implementation pattern (in synthetic data spec generation cell):**

```python
# After LLM generates spec_tables, BEFORE yaml.dump:
for table in spec_tables:
    tname = table['name']
    col_types = type_map.get(tname, {})  # from erd_parsed.yaml
    for cname, domain in table.get('domain_columns', {}).items():
        ddl_type = col_types.get(cname, '').lower()
        values = domain.get('values', [])
        if not values:
            continue
        if any(t in ddl_type for t in ('char', 'string')):
            domain['values'] = [str(v) for v in values]
        elif 'timestamp' in ddl_type:
            domain['values'] = [
                f"{str(v)} 00:00:00" if len(str(v)) == 10 else str(v)
                for v in values
            ]
```

This ensures the YAML file contains correctly-typed values from the moment it is written. The runtime coercion in `generate_table()` is a SAFETY NET only — it should never need to fire if this gate runs.

## 5.5 Cross-Column Dependencies

Identify and store semantic constraints:

```yaml
semantic_constraints:
  - expression: "start_date <= end_date"
    type: TEMPORAL
    confidence: HIGH
  - expression: "child.FK IN parent.PK"
    type: STRUCTURAL
    confidence: HIGH
```

Types: STRUCTURAL (PK/FK, uniqueness), TEMPORAL (date ordering), SEMANTIC (cross-column business rules), STATISTICAL (distributions).

## 5.5 Volume Targets

Map the frozen `run_context.data_source.greenfield.volume` to row counts:

```yaml
volume_targets:
  low:    { dimension: 100-500, fact: 500-5000, detail_fact: 2000-10000 }
  medium: { dimension: 1000-5000, fact: 10000-50000, detail_fact: 50000-200000 }
  high:   { dimension: 10000-50000, fact: 100000-500000, detail_fact: 500000-2000000 }
```

---

# Step 6: Generate Synthetic Data Notebook

### Pre-Flight

- [ ] `reconcile_schema` is current `VALID`; authenticated `schema_reconciliation.yaml` is `PASS` with zero unresolved mismatches and fresh catalog name/type equality
- [ ] every exact expected append-only target is empty before the notebook's first write; a non-empty target HALTS to prevent duplicate data
- [ ] exact persisted `synthetic_data_spec.yaml` bytes passed `admit_synthetic_inputs` in validation GATE 5.0; existence alone is insufficient
- [ ] GATE 5.1 passed (domain values validated)
- [ ] Generation order computed from dependency graph
- [ ] `generate_table()` will be used for every table (domain-first pattern)
- [ ] ANSI mode will be disabled in setup cell
- [ ] `discover_tables()` will be used for version-aware references
- [ ] FK columns will sample from parent key domains

### Process

1. Produce `{OUTPUT_FOLDER}/synthetic_data_spec.yaml` — declarative specification of all tables, row counts, column domains, FK mappings, and PK columns. The LLM produces ONLY this spec.
2. Read back the persisted spec and table spec through the shared Workspace transport.
   Execute `admit_synthetic_inputs` from `validation.md` using the exact frozen dbldatagen
   template bytes/digest and attested duplicate-key decoder. Require a nonempty top-level
   `tables` list and the actual runtime validator's PASS before any deployment. Planning
   documents, a mapping keyed by table name, nested `synthetic_data.tables`, and `tables: []`
   are not executable inputs. On rejection, preserve findings and repair this spec only.
3. **Apply guardrails DL-G4 and shared G-16, then deploy dbldatagen notebook from template** — call `deploy_from_template` with:
   - `template_path`: exact frozen `run_context.templates.dbldatagen_notebook.path`
   - `output_path`: `{OUTPUT_FOLDER}/notebooks/synthetic_data_{DOMAIN_NAME}.py`
   - `placeholders`: the complete map returned by executable GATE TEMPLATE-BINDING in `validation.md`, using this template’s authenticated bytes and the current context/handoff
   - Build the entire call with `build_data_deployment_request` from that gate and submit its returned request unchanged. For synthetic deployment, rebuild from the synthetic template: do not reuse the DDL request. Its `ASSET_SUFFIX` must be the authenticated persisted suffix.
     Use the exact handoff target catalog/schema and `asset_suffix`; generated greenfield tables are not addressed through current accelerator source coordinates.
   The template is a Deterministic Deployment Runtime: it reads `synthetic_data_spec.yaml`, iterates over all tables in dependency order, calls `generate_table()` for each, enforces varchar limits, validates row counts, and writes the manifest. The LLM MUST NOT add custom cells — everything is driven by the spec.
4. Reread and rerun `admit_synthetic_inputs`; require the same admitted digests and
   current authenticated reconciliation/empty-target prerequisites. Only then execute
   the notebook via `execute_notebook`.
5. Verify execution completed without errors

### Notebook Execution

| Environment | Method |
|------------|--------|
| Genie Code | `openAsset` + `continueMessage` (preferred) OR SDK `w.jobs.submit()` OR `executeCode` (last resort, only after notebook artifact saved) |
| Databricks App | SDK `w.jobs.submit()` with `NotebookTask` |

### MANDATORY Write Pattern

```python
df.write.format("delta").mode("append").saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")
```

NEVER `.mode("overwrite")`. Tables are empty from DDL; append = initial load.

### MANDATORY Python 3.11 Compatibility

Serverless compute runs Python 3.11 which PROHIBITS backslashes inside f-string `{}` expressions:

```python
# ILLEGAL — causes SyntaxError:
f"{'\n'.join(items)}"        # backslash in f-string expression
f"{val.replace('\n', '')}"   # backslash in f-string expression

# LEGAL — use a variable instead:
nl = '\n'
f"{nl.join(items)}"
# Or assign first:
joined = '\n'.join(items)
f"{joined}"
```

This applies to ALL generated notebook code. Violation = `SyntaxError` at runtime.

---

## 6.1 Foreign Key Replacement (MANDATORY for every child table)

`generate_table()` handles FK replacement automatically via the `fk_replacements` parameter.
It samples actual parent keys and distributes them uniformly across child rows.

### Usage:

```python
FK_REPLACEMENTS = {
    "clm_member_sk": (TABLES["dim_member"], "member_sk"),
    "clm_provider_sk": (TABLES["dim_provider"], "provider_sk"),
}

df = generate_table(table_name, rows=5000,
    domain_cols=DOMAIN_COLS, pk_cols=["claim_id"],
    fk_replacements=FK_REPLACEMENTS)
```

`generate_table()` will:
1. Build the DataGenerator with domain values + type-appropriate random data
2. After `build()`: sample parent PKs and replace FK columns
3. After `build()`: ensure PK columns have unique sequential values

### Manual FK Pattern (if NOT using `generate_table()`):

```python
from pyspark.sql import functions as F
from pyspark.sql.window import Window

w = Window.orderBy(F.monotonically_increasing_id())
df = df.withColumn("_row_num", F.row_number().over(w))

parent_pks = [row[0] for row in
    spark.table(f"{CATALOG}.{SCHEMA}.{TABLES['parent_logical']}").select("pk_col").distinct().collect()]

df = df.drop("fk_col").withColumn("fk_col",
    F.element_at(
        F.array([F.lit(v) for v in parent_pks]),
        (F.col("_row_num") % len(parent_pks) + 1).cast("int")
    ))
df = df.drop("_row_num")
```

### Line Number / Sequence Columns

Columns named `*_line_nbr`, `*_seq` → sequential integers, NOT strings:

```python
df = df.drop("line_nbr_col").withColumn("line_nbr_col",
    (F.row_number().over(Window.orderBy(F.monotonically_increasing_id())) % max_lines + 1).cast("int"))
```

## 6.2 Domain Value Specification (MANDATORY — Domain-First Pattern)

The LLM defines ALL categorical/analytical columns upfront in a `DOMAIN_COLS` dict.
`generate_table()` handles everything in one pass — no separate "override" step needed.

### CRITICAL: Column Name Source (DETERMINISM RULE)

**Column names in `DOMAIN_COLS` and `FK_REPLACEMENTS` MUST come from `DESCRIBE TABLE` output — NEVER from memory, semantic inference, or the KPI spec.**

The LLM MUST follow this exact sequence for every table:

```text
1. Run: DESCRIBE TABLE `{catalog}`.`{schema}`.`{table_name}` → get exact column names
2. Identify which columns are categorical (from semantic_model.yaml classification)
3. Use the EXACT column name from DESCRIBE (e.g., "clm_dtl_claim_type", NOT "claim_type")
4. Call validate_domain_cols() to catch any remaining mismatches
```

**Why this matters:** If the DOMAIN_COLS key is `"claim_type"` but the actual column is `"clm_dtl_claim_type"`, the domain values are silently skipped and the column gets random garbage. The `validate_domain_cols()` function catches this, but the LLM should get it right in the first place.

### Correct Pattern (MANDATORY):

```python
table_name = TABLES["fact_claim_detail"]

# Step 1: Get ACTUAL deployed column names from DESCRIBE/catalog readback
col_types = get_table_col_types(table_name)
print(f"Columns in {table_name}: {list(col_types.keys())}")

# Step 2: Define DOMAIN_COLS using EXACT column names from Step 1
# (NOT semantic names like "claim_type" — use the actual "clm_dtl_claim_type")
DOMAIN_COLS = {
    "clm_dtl_claim_type": (["Institutional", "Professional", "Pharmacy", "Dental", "Vision"],
                            [0.30, 0.35, 0.15, 0.12, 0.08]),
    "clm_dtl_line_status": (["Paid", "Denied", "Pending", "Adjusted"],
                             [0.65, 0.20, 0.10, 0.05]),
    "clm_dtl_place_of_service": (["Office", "Inpatient", "Outpatient", "Emergency", "Lab"],
                                  [0.35, 0.15, 0.25, 0.10, 0.15]),
}

# Step 3: Validate (catches any remaining mismatches — RAISES on failure)
DOMAIN_COLS = validate_domain_cols(table_name, DOMAIN_COLS)

# Step 4: Define FK replacements using EXACT column names
FK_REPLACEMENTS = {
    "clm_dtl_member_sk": (TABLES["dim_member"], "member_sk"),
    "clm_dtl_provider_sk": (TABLES["dim_provider"], "provider_sk"),
}
FK_REPLACEMENTS = validate_fk_replacements(table_name, FK_REPLACEMENTS)

# Step 5: Generate + validate + write
df = generate_table(table_name, rows=5000,
    domain_cols=DOMAIN_COLS, pk_cols=["clm_dtl_claim_id"],
    fk_replacements=FK_REPLACEMENTS)
df = enforce_varchar_limits(df, table_name)
verify_before_write(df, table_name,
    pk_cols=["clm_dtl_claim_id"],
    fk_cols=list(FK_REPLACEMENTS.keys()),
    categorical_cols=list(DOMAIN_COLS.keys()))
df.write.format("delta").mode("append").saveAsTable(f"{CATALOG}.{SCHEMA}.{table_name}")
```

### PROHIBITED Column Name Patterns:

```python
# ❌ WRONG — semantic/shortened names (will be silently ignored):
DOMAIN_COLS = {
    "claim_type": ...,       # Actual column is "clm_dtl_claim_type"
    "line_status": ...,      # Actual column is "clm_dtl_line_status"
    "member_sk": ...,        # Actual column is "clm_dtl_member_sk"
}

# ✓ CORRECT — exact names from DESCRIBE TABLE:
DOMAIN_COLS = {
    "clm_dtl_claim_type": ...,
    "clm_dtl_line_status": ...,
}
```

**Every column in `synthetic_data_spec.yaml` with `CATEGORICAL_VALUES` or `WEIGHTED_CATEGORICAL` strategy MUST appear in the `DOMAIN_COLS` dict, using the EXACT column name from `DESCRIBE TABLE`.**

## 6.3 Spark Configuration

In setup cell, BEFORE any `dg.DataGenerator` call:

```python
spark.conf.set("spark.sql.ansi.enabled", "false")
```

## 6.4 Template Functions (DO NOT REIMPLEMENT)

| Function | Purpose |
|----------|---------|
| `discover_tables()` | Finds versioned tables, returns `{logical: versioned}` mapping |
| `get_table_col_types(table_name)` | Reads DDL column types from catalog (preserves VARCHAR(N)) — **USE THIS to get exact column names before building DOMAIN_COLS** |
| `validate_domain_cols(table_name, domain_cols)` | **DETERMINISM GATE**: Asserts all DOMAIN_COLS keys exist in table schema. RAISES with available column list if any don't match. Auto-corrects case. Returns corrected dict. **MUST be called before `generate_table()`** |
| `validate_fk_replacements(table_name, fk_replacements)` | Same as above for FK columns. Returns corrected dict |
| `generate_table(table, rows, domain_cols, pk_cols, fk_replacements, date_range)` | One-pass generation: domain cols → values, bulk cols → type loop, FK replacement + PK uniqueness |
| `spark_type_for(type_str)` | Maps DDL type string to PySpark type |
| `enforce_varchar_limits(df, table)` | Truncates overlong values — call LAST before write |
| `verify_before_write(df, table, pk_cols, fk_cols, categorical_cols)` | Pre-write gate: PK unique, FK diverse, no generic values |
| `extract_max_length(type_str)` | Returns max length for VARCHAR/CHAR (0 for plain string) |

### Mandatory Call Order (per table):

```text
1. get_table_col_types(table_name)     → discover exact column names
2. validate_domain_cols(table, DOMAIN_COLS)  → assert all keys match (RAISES on mismatch)
3. validate_fk_replacements(table, FK_REPLACEMENTS) → assert FK keys match
4. generate_table(...)                  → build data
5. enforce_varchar_limits(df, table)    → truncate
6. verify_before_write(...)             → final quality gate
7. df.write...                          → persist
```

Skipping steps 1-3 produces non-deterministic output (garbage data on some runs).

**GATE 6.1**: ALL tables have rows > 0. HALT with `SYNTHETIC_GENERATION_ERROR` if any table empty.

---

# Step 7: Integrity Validation

Synthetic-data generation is NOT successful because the notebook executed. Run deterministic validation.

### BATCH VALIDATION (combine into 2-3 SQL calls)

```sql
-- IMPORTANT: Databricks SQL Compatibility Notes:
-- • Do NOT use INFORMATION_SCHEMA.TABLES.table_rows (column does not exist in Databricks)
-- • Do NOT use INFORMATION_SCHEMA.TABLES.data_length or avg_row_length
-- • Use SELECT COUNT(*) FROM <table> for row counts
-- • Use DESCRIBE DETAIL <table> for file-level metadata (numFiles, sizeInBytes)
--
-- BATCH 1: Row counts + PK uniqueness for ALL tables
SELECT '{table_a}' t, COUNT(*) rows, COUNT(DISTINCT {pk}) pk_distinct,
       COUNT(*) - COUNT(DISTINCT {pk}) pk_dups
FROM {catalog}.{schema}.{table_a}
UNION ALL ...

-- BATCH 2: FK orphans + FK diversity
SELECT '{child}.{fk}' col, 'orphan_count' chk, COUNT(*) val
FROM {child} c LEFT ANTI JOIN {parent} p ON c.{fk} = p.{pk}
UNION ALL
SELECT '{child}.{fk}', 'distinct_vals', COUNT(DISTINCT {fk}) FROM {child}
UNION ALL ...

-- BATCH 3: Join stability (N:1 must NOT multiply rows)
SELECT '{join_name}' j,
  (SELECT COUNT(*) FROM {child}) before_rows,
  (SELECT COUNT(*) FROM {child} f JOIN {parent} d ON f.{fk} = d.{pk}) after_rows
UNION ALL ...
```

### Validation Matrix

| Check | Expected | Fail Code |
|-------|----------|-----------|
| 7.1 Schema: all tables exist, correct columns/types | Match DDL | `SCHEMA_VALIDATION_FAILURE` |
| 7.2 Row counts > 0 for all tables | rows > 0 | `EMPTY_TABLE_FAILURE` |
| 7.3 PK uniqueness (composite: CONCAT all key cols) | COUNT = COUNT(DISTINCT) | `PRIMARY_KEY_INTEGRITY_FAILURE` |
| 7.4 FK orphan count | 0 (unless nullable FK allowed) | `FOREIGN_KEY_INTEGRITY_FAILURE` |
| 7.5 FK diversity | COUNT(DISTINCT fk) > 1 | `FK_DIVERSITY_FAILURE` |
| 7.6 Business key diversity in parents | distinct_vals ≈ total_rows | `BUSINESS_KEY_DIVERSITY_FAILURE` |
| 7.7 Join cardinality (N:1 joins) | after_rows <= before_rows | `JOIN_CARDINALITY_FAILURE` |
| 7.8 Semantic constraints (dates, derivations) | Per spec | `SEMANTIC_DATA_ERROR` |
| 7.9 Analytical completeness | No NULL-only, no single-value categoricals | `ANALYTICAL_COMPLETENESS_FAILURE` |
| 7.10 Domain value check | No `val_\d+` in categorical columns | `DOMAIN_VALUE_FAILURE` |
| 7.11 Relationship authority | Every `semantic_model.yaml` relationship has one relationship-level validation result | `RELATIONSHIP_ERROR` |

**CRITICAL**: Do NOT mark `overall_status: PASS` if ANY join produces fanout, ANY FK has diversity = 1, or ANY relationship-level validation has `validation_status: FAIL`. These block ALL downstream stages.

---

# Step 8: Validation Report

Write `{OUTPUT_FOLDER}/data_layer_validation.yaml`:

```yaml
overall_status: PASS | FAIL
authority:
  expected_schema_source: table_spec.yaml
  deployed_schema_source: catalog_describe
assumptions_evidence:
  path: <exact current-run schema_assumptions.yaml path>
  sha256: <raw lowercase SHA-256>
schema_assumptions:
  policy_id: GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1
  scope: GREENFIELD_SYNTHETIC_GENERATED_TARGET_ONLY
  status: PASS
  erd_input_sha256: <raw lowercase SHA-256>
  erd_output_sha256: <raw lowercase SHA-256>
  resolution_count: N
  resolutions: []
  unresolved_datatypes: []
schema: { tables_expected: N, tables_created: N, missing: [], unexpected: [] }
reconciliation_evidence:
  path: <exact current-run schema_reconciliation.yaml path>
  sha256: <raw lowercase SHA-256>
schema_reconciliation:
  policy_id: DEPLOYED_DATATYPE_REPAIR_V1
  status: PASS | FAIL
  datatype_policy: EMPTY_CURRENT_VERSION_TABLE_RECREATE_ONLY
  unresolved_mismatches: []
  attempts:
    - table_fqn: "`catalog`.`schema`.`table_vN`"
      mismatch_kind: DATATYPE | STRUCTURAL
      expected_schema: [{column: col_name, datatype: DECIMAL(18,2)}]
      observed_schema: [{column: col_name, datatype: STRING}]
      canonical_comparison: MISMATCH
      ownership: CURRENT_VERSION_GENERATED_TARGET | SOURCE_OR_LIVE | AMBIGUOUS
      row_count_before: 0 | null
      action: DROP_RECREATE_FROM_TABLE_SPEC | HALT_NO_MUTATION
      attempt: 1
      post_repair_schema: []
      status: PASS | FAIL
      error_code: null | DATATYPE_MISMATCH_UNSAFE_TO_REPAIR | SCHEMA_CONTRACT_ERROR
primary_keys: { tested: N, failures: [] }
foreign_keys: { tested: N, orphan_counts: {}, diversity: {}, failures: [] }
join_stability: { tested: N, fanout_failures: [] }
relationships:
  - relationship_id: parent_table.parent_key__child_table.child_key
    source: erd_declared | inferred
    confidence: <copied from semantic_model.yaml>
    parent: parent_table
    parent_key: parent_key
    child: child_table
    child_key: child_key
    expected_cardinality: "1:N"
    orphan_count: 0
    parent_key_duplicates: 0
    before_rows: 0
    after_rows: 0
    validation_status: PASS | FAIL
semantic_constraints: { tested: N, failures: [] }
domain_values: { columns_checked: N, generic_value_failures: [] }
data_quality: { null_violations: [], generic_fallback_columns: [] }
```

Authenticate `{OUTPUT_FOLDER}/schema_assumptions.yaml` and
`{OUTPUT_FOLDER}/schema_reconciliation.yaml`, record their exact paths/raw digests, and copy both
payloads without reinterpretation. The final report may add later integrity results, but it must not
recompute or rewrite either earlier schema outcome. A GATE 4.2 failure writes
`schema_reconciliation.yaml` with `status: FAIL` and halts before Step 5; it does not fabricate a
partial final validation report.

Every relationship in `semantic_model.yaml` MUST have exactly one matching entry in `relationships:`. Preserve its source provenance. After this report exists, it supersedes `semantic_model.yaml` for the question "is this deployed relationship safe to use?"

**GATE 7.1**: `data_layer_validation.yaml` exists with `overall_status: PASS`; its assumptions and reconciliation paths/raw SHAs authenticate the current standalone artifacts; embedded content matches exactly; assumptions use policy `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`, `status: PASS`, and zero unresolved datatypes; reconciliation uses policy `DEPLOYED_DATATYPE_REPAIR_V1`, `status: PASS`, and zero unresolved mismatches; every intended relationship has exactly one validation entry with `validation_status: PASS`. HALT otherwise.

---

# Step 9: Final Summary

| Category | Result |
|----------|--------|
| ERD tables parsed | count |
| Tables created | count |
| Schema reconciliation | PASS/FAIL; repaired table count; unresolved mismatch count |
| Facts/Events | count |
| Dimensions/Reference | count |
| PK validations | PASS/FAIL |
| FK validations | PASS/FAIL |
| FK diversity | PASS/FAIL |
| Domain values | PASS/FAIL |
| Join stability | PASS/FAIL |
| Overall | PASS/FAIL |

---

# Versioning Rules

Use the exact `ASSET_SUFFIX` from `step_handoff.yaml.asset_suffix`. Reference tables via `discover_tables()` → `TABLES["logical_name"]`. Never reconstruct the suffix from current configuration or hardcode versionless names.

---

# Datatype Rules

| Type | Rule |
|------|------|
| PK/FK/IDs | Use datatype from `get_table_col_types()`. Never force StringType for numeric IDs. |
| DateType | `begin="YYYY-MM-DD"`, `end="YYYY-MM-DD"` |
| TimestampType | `begin="YYYY-MM-DD HH:MM:SS"` (date-only PROHIBITED). Pass `date_range` tuple to `generate_table()`. |
| DECIMAL/FLOAT | Numeric values and ranges. Never formatted currency strings. |
| BOOLEAN | Use `BooleanType()` without explicit `values=[True,False]`. |

### dbldatagen Template Syntax on Serverless (Spark Connect)

`template=` does NOT reliably generate unique values on serverless. Backslash-digit escapes are literal.

For **business keys / FK targets** (uniqueness required): use `F.row_number()` over a Window:

```python
w = Window.orderBy(F.monotonically_increasing_id())  # ordering seed only
df = df.withColumn("_row_num", F.row_number().over(w))
df = df.drop("business_key").withColumn("business_key",
    F.concat(F.lit("PREFIX-"), F.lpad(F.col("_row_num").cast("string"), 7, "0")))
df = df.drop("_row_num")
```

For **non-key descriptive columns**: `template=` acceptable (non-unique values OK).

**Rule: Use `monotonically_increasing_id()` ONLY as a Window ordering seed. NEVER in expressions requiring sequential/uniform values.**

---

# Pre-Write Verification (MANDATORY before every `.write`)

```python
# PK unique:
assert df.select("pk_col").distinct().count() == df.count(), "PK not unique!"
# Business key unique (if FK target):
assert df.select("business_key").distinct().count() == df.count(), "Business key not unique!"
# FK replaced:
assert df.select("fk_col").distinct().count() > 1, "FK replacement not applied!"
```

If verification fails: fix DataFrame in memory, re-verify, THEN write. Never write first and fix later.

---

# Failure Classification

| Code | Meaning |
|------|---------|
| `DATA_LAYER_INPUT_AUTHORITY_ERROR` | Tool-supplied run-context path or canonical run/handoff binding failed; owned by the upstream resolver, not repairable in this stage |
| `ERD_VALIDATION_HELPER_CONTRACT_ERROR` | Frozen ERD utility path/digest, copied/loaded file, or required callable failed attestation; owned by the Data Layer release contract with no local fallback |
| `ERD_EXTRACTION_ERROR` | Structural ERD extraction failed, or datatype resolution was ineligible/broken after evidence retries |
| `SCHEMA_CONTRACT_ERROR` | Contract violation in downstream step |
| `GRAIN_INFERENCE_ERROR` | Cannot determine table grain |
| `RELATIONSHIP_ERROR` | Cannot establish required relationship |
| `DDL_GENERATION_ERROR` | DDL notebook execution failed |
| `DATATYPE_MISMATCH_UNSAFE_TO_REPAIR` | Deployed datatype differs and the exact empty/current-version/single-attempt repair gate did not pass, or verified recreation still mismatched |
| `DBLDATAGEN_API_ERROR` | dbldatagen API misuse |
| `TYPE_SAFETY_ERROR` | Generated value/spec does not conform to an already reconciled deployed datatype; repair generation logic, not schema |
| `SYNTHETIC_GENERATION_ERROR` | Data generation notebook failed |
| `DOMAIN_VALUE_FAILURE` | Generic/placeholder values in categorical columns |
| `PRIMARY_KEY_INTEGRITY_ERROR` | PK not unique |
| `FOREIGN_KEY_INTEGRITY_ERROR` | FK orphans exist |
| `FK_DIVERSITY_FAILURE` | FK column has only 1 distinct value |
| `JOIN_FANOUT_ERROR` | N:1 join produces row multiplication |
| `WORKSPACE_IO_ERROR` | File write/read failure |

For any failure: report Observed problem, Root cause, Evidence, Corrective action, Affected downstream.

---

# Pipeline Halt Rules

HALT with `❌ EXECUTION HALTED` when: ERD structure is unreadable, the vision model is unavailable,
required FK identity is unresolvable, governed datatype resolution is ineligible or violates its
contract, DDL execution fails for a non-datatype reason, a deployed datatype mismatch is unsafe or
remains after its single eligible repair, dbldatagen type conflicts, PK/FK validation fails, join
fanout occurs, or domain values are generic/placeholder. Eligible greenfield-synthetic datatype-only
defects are self-corrected and do not trigger a terminal halt.

---

# Non-Negotiable Rules

1. ERD image is authoritative for observed source-design intent; `table_spec.yaml` is the reconciled expected schema; `DESCRIBE TABLE` is deployed runtime truth.
2. Never reuse previous generated artifacts as schema evidence.
3. Authoritative evidence is preferred; when an eligible generated-synthetic datatype remains unknown, use only the named deterministic policy and disclose it as `INFERRED_POLICY`.
4. Every table has explicitly documented grain.
5. Never create relationships from column-name similarity alone.
6. Never invent columns/keys to make generation easier.
7. Generate parents before dependents.
8. Foreign keys MUST reuse parent key domains.
9. Never independently random-generate both sides of PK/FK.
10. Every DDL column gets exactly one effective generation definition.
11. Use `generate_table()` with `domain_cols` + `pk_cols` + `fk_replacements` for every table.
12. Call `enforce_varchar_limits()` LAST, after FK replacement, before write.
13. Use project templates; do not recreate notebooks.
14. Use version-aware `TABLES[...]` references.
15. Disable Spark ANSI mode before dbldatagen.
16. Notebook execution ≠ data validation.
17. Structural integrity must be proven deterministically.
18. Semantic realism inferred from model/use-case, not hardcoded domain assumptions.
19. Schema does not adapt to generation; generation adapts to schema.
20. Every categorical column MUST have domain-meaningful values — NEVER generic placeholders.
21. `semantic_model.yaml` records relationship intent; downstream use requires the matching `data_layer_validation.yaml` relationship result to be `PASS`.
22. A deployed datatype mismatch may be auto-repaired only once, only for an exact empty current-version generated target, and only by pinned-compiler recreation from unchanged `table_spec.yaml` followed by exact readback.
23. Never use `ALTER COLUMN`, casts, coercion, CTAS, overwrite, or intent mutation to conceal deployed datatype drift.

---

# Output Contract

| Artifact | Location | Validation |
|----------|----------|-----------|
| erd_parsed.yaml | `{OUTPUT_FOLDER}/` | Complete source inventory; GATE 2.1 structure and GATE 2.1b datatypes passed on persisted readback; no unresolved structural blockers |
| schema_assumptions.yaml | `{OUTPUT_FOLDER}/` | Always present; policy `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`; current run/target/suffix; authenticated raw/resolved ERD hashes; ordered evidence/confidence rows; zero unresolved datatypes |
| table_spec.yaml | `{OUTPUT_FOLDER}/` | Exact expected-schema projection of `erd_parsed.yaml`; GATE 4.0 passed |
| ddl_preflight.yaml | `{OUTPUT_FOLDER}/` | Current-run pre-mutation GATE 4.0 evidence; assumptions digest, raw/resolved ERD hashes, table-spec hashes, policy resolutions, exact type regenerations, action, status/failure code, and `catalog_mutation_started: false` |
| schema_reconciliation.yaml | `{OUTPUT_FOLDER}/` | Current-run GATE 4.2 evidence; policy `DEPLOYED_DATATYPE_REPAIR_V1`; `status: PASS`; exact expected/readback name-type fingerprints; zero unresolved mismatches |
| semantic_model.yaml | `{OUTPUT_FOLDER}/` | Contains `generation_order:` |
| synthetic_data_spec.yaml | `{OUTPUT_FOLDER}/` | Entry for every table, GATE 5.1 passed |
| DDL notebook | `{OUTPUT_FOLDER}/notebooks/ddl_{domain}.py` | All tables in catalog |
| Synthetic data notebook | `{OUTPUT_FOLDER}/notebooks/synthetic_data_{domain}.py` | Executed, all tables populated |
| data_layer_validation.yaml | `{OUTPUT_FOLDER}/` | `overall_status: PASS`; `schema_reconciliation.status: PASS`; zero unresolved schema mismatches; every semantic-model relationship has exactly one relationship-level `PASS` result |

---

# Progress Reporting Reference

| Phase | phase_id | Key Stats |
|-------|----------|-----------|
| Load Config | `load_config` | templates_loaded |
| Parse ERD | `parse_erd` | tables, relationships, columns |
| Semantic Model | `build_semantic_model` | facts, dimensions, relationships_resolved |
| Generate DDL | `generate_ddl` | tables_created, columns_total |
| Reconcile Schema | `reconcile_schema` | tables_checked, repaired_tables, unresolved_mismatches |
| Synthetic Data | `generate_synthetic_data` | tables_populated, total_rows, fk_linked |
| Validate | `validate_data` | pk_tests, fk_tests, pk_failures, fk_failures |

Apply this stage’s `guardrails.md` **DL-G3** for sequential execution and
checkpoint-backed progress. The phase table above supplies stage-specific IDs.

Call `report_progress` with `status: "started"` before each phase, `status: "completed"` after, and
`status: "update"` with `progress_pct` during long phases. Every call uses the native JSON-object
schema in the shared state contract: `stats` is an object, `happenings` and `findings` are arrays,
and empty JSONB values are `{}` or `[]`, never null or comma-delimited bare text.
