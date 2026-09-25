# Global Guardrails — Apply to ALL Pipeline Steps

These rules are BINDING for every step. Violations are pipeline failures.

---

## G-0: Three-Plane Architecture (MANDATORY)

All pipeline steps follow the three-plane architecture defined in `00_master_prompt.md`:

1. **Generation Plane**: LLM produces declarative artifact specifications (YAML/JSON) — NEVER raw SQL, API calls, or executable code
2. **Control Plane**: Deterministic validator/compiler runs four gates before execution
3. **Execution Plane**: Deterministic Deployment Runtime executes via platform APIs
4. **Verification**: Applicable catalog/SQL or official API readback + desired-state vs deployed-state comparison
5. **Manifest**: Immutable deployment evidence with hash chain

**The LLM's executable surface area is minimized.** It writes domain logic (measure expressions, column mappings, widget configs). It does NOT write structural SQL (CREATE TABLE, JOIN syntax) or make API calls directly. The compiler/runtime handles all structural concerns.

---

### Prompt ownership and deterministic enforcement

The master and these shared guardrails own orchestration and remediation policy.
The agent derives domain-specific names, relationships, distributions, and values
from authenticated inputs. Fixed artifact field names are interface contracts,
not hardcoded domain assumptions. Examples are illustrative, never runtime defaults.

Validators and notebook templates enforce these contracts, report precise failures,
and execute bounded operations. They must not guess missing keys, silently rename
assets, choose the next stage, or mutate frozen intent to make a validation pass.
Small transport glue may invoke attested helpers and serialize artifacts; it must
not recreate domain compilers or lifecycle selection logic. Host adapters supply
tools and durable UI state. The App may use Lakebase; Genie Code and other agents
must be able to execute this chain without Lakebase or App imports.

Step-local guardrails own stage-specific contracts and corrective actions. Shared
guardrails own only cross-step invariants. Instructions define workflow; validation
files define gates; runbooks hold diagnostics. Update the owning guardrail first,
then align its prompt references, bounded runtime enforcement, and regression tests.

---

## G-0.1: Four-Gate Validation Model (MANDATORY)

Every declarative artifact MUST pass four gates before execution:

| Gate | Validates | Failure Action |
|------|-----------|----------------|
| Gate 1: Structural | Schema-valid YAML/JSON, required fields, no malformed config | Regenerate spec |
| Gate 2: Metadata | Catalog/schema/columns exist, generated references fit reconciled types, relationships exist | Repair only a bad current-stage reference; deployed expected-vs-observed datatype drift routes to Data Layer GATE 4.2 |
| Gate 3: Semantic | Grain valid, KPI references valid, join paths safe, no fanout, no ambiguous dimensions | LLM repair (fix architecture) |
| Gate 4: Deployment | Permissions, naming conflicts, environment policy, expected readback | Deterministic fail (infrastructure) |

**"Valid SQL" is NOT the same as "correct architecture."** A generated view can compile perfectly and still be wrong because it joins two facts at incompatible grains. Gate 3 catches what SQL compilation cannot.

---

## G-0.2: Error Classification (MANDATORY)

Runtime failures are classified before routing to remediation:

| Error Pattern | Routing | Why |
|---------------|---------|-----|
| PARSE_SYNTAX_ERROR, UNRESOLVED_COLUMN | LLM repair | Fix generated SQL/spec using current schema and semantic evidence; preserve KPI grain |
| DEPLOYED_DATATYPE_MISMATCH | Data Layer owner gate | Preserve expected/observed types; only GATE 4.2 may perform one empty-current-version compiler recreation, otherwise halt with `DATATYPE_MISMATCH_UNSAFE_TO_REPAIR` |
| PERMISSION_DENIED, RESOURCE_EXHAUSTED, QUOTA_EXCEEDED | Deterministic fail | Infrastructure — LLM cannot fix |
| RATE_LIMIT, TIMEOUT | Retry with backoff (max 3) | Transient — retry, then fail |
| OBJECT_ALREADY_EXISTS | Deployment policy (idempotency check) | May be expected state |
| INVALID_KPI_GRAIN, FANOUT_RISK | Semantic validation fail | Gate 3 should have caught this |
| INTERNAL_ERROR | Deterministic fail | Platform issue — escalate |

The LLM must NEVER attempt to "fix" infrastructure, authorization, or governance errors.

### Failure owner is part of the error contract

Every authority, parity, drift, or validation failure MUST identify exactly one
`failure_owner`. The allowed owners and their scopes are:

| `failure_owner` | Owns |
|---|---|
| `MASTER_RESOLVER` | selected run, exact `run_context_path`, frozen configuration, and non-producer handoff fields |
| `DATA_LAYER_STAGE` | generated tables, deployed physical schema/types, and relationship/grain validation |
| `METRIC_VIEW_STAGE` | Metric View plan, producer checkpoint, capability binding, deployed Metric View surface, and Metric View validation |
| `DASHBOARD_STAGE` | dashboard design, locator, Lakeview deployment, and Lakeview readback validation |
| `GENIE_STAGE` | Genie design, locator, deployment, and full-GET validation |
| `CROSS_VALIDATION_SWEEP` | frozen sweep scope, pinned sweep helper execution, and ground-truth report persistence only |
| `DOCUMENTATION_STAGE` | README and documentation-draft generation only |
| `PLATFORM_OPERATOR` | permission, quota, platform, or non-contract I/O failures |

A stage may repair only artifacts and deployed resources owned by its assigned owner. A
cross-validation mismatch is routed by the mismatched field, not automatically to the
sweep: `metric_view_fqns` routes to `METRIC_VIEW_STAGE`;
`dashboard_display_names` and `dashboard_ids` route to `DASHBOARD_STAGE`; and
`genie_titles` and `genie_space_ids` route to `GENIE_STAGE`. Run/handoff selection
conflicts route to `MASTER_RESOLVER`. Deployed datatype mismatches remain exclusively
owned by `DATA_LAYER_STAGE` under `DEPLOYED_DATATYPE_REPAIR_V1`.

If deterministic classification does not yield one owner, HALT with
`AUTHORITY_OWNER_UNRESOLVED`; do not guess, mutate an artifact, cast around the problem,
or re-run multiple stages. Checkpoint invalidation may mark the owning phase and graph dependents
`STALE`, but only the orchestrator may schedule the owner-specific re-execution.

---

## G-1: Manifest Integrity (Applicable Direct Readback Required)

All deployment manifests (`*_manifest.json`) MUST be produced only after validation against the applicable direct deployment readback, not agent self-reporting. Metric Views use catalog/SQL readback; Dashboards and Genie use official API GET readback.

**Required fields in every manifest:**
```yaml
validation_source: <catalog_readback|api_readback> # Metric Views use catalog_readback; Dashboard/Genie use api_readback; never agent_reported
```

**Manifest writing procedure (NON-NEGOTIABLE):**
1. Deploy through the owning deterministic runtime/API.
2. Run the owning validator against catalog/SQL readback for Metric Views or official GET readback for Dashboard/Genie.
3. Confirm the validation returns `PASS`.
4. Write the manifest using identities, hashes, and counts from that readback, not agent memory.
5. Use `validation_source: catalog_readback` for Metric Views or `validation_source: api_readback` for Dashboard/Genie.

**A manifest that claims success without its applicable direct readback is invalid.** Agent-written claims such as `published: true` or persisted-content counts do not prove deployed state.

**State checkpoint impact:**
- A manifest supplies only the asset locator/deployment-attempt record. It is eligible for a deployment-phase skip only together with the separate matching readback-backed validation required by `{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md`.
- The complete fingerprint Resume Skip Gate must also pass; manifest/readback agreement alone does not prove that its upstream dependencies are current.
- A manifest without matching readback-backed validation requires the applicable direct readback before the owning stage may skip, regardless of its own `validation_source` field.
- No manifest follows the owning stage's normal execution path.
- Checkpoint eligibility does not promote a manifest into semantic authority or current deployed-content authority; its individual claims remain scoped by G-3.
- A Dashboard `dashboard_id` or Genie `space_id` from a manifest may be used only as a locator for an official GET/full GET. The returned asset must match the exact frozen handoff identity before any current-state claim or update. A Metric View manifest FQN is likewise only a locator for current catalog/SQL readback.
- Manifests MUST NOT add assets to an expected inventory, choose between conflicting identities, authenticate an auto-produced handoff, or replace catalog/API readback. Missing, extra, duplicate, or identity-mismatched locators are owner-scoped failures, not permission to search for a convenient replacement.

---

## G-2: MEASURE() Syntax Enforcement

All KPI queries against metric views MUST use `MEASURE()` syntax, never raw `SUM()`/`COUNT()`/`AVG()`.

```sql
-- CORRECT
SELECT claim_type, MEASURE(total_paid_amount) FROM metric_view GROUP BY ALL

-- WRONG — bypasses metric view semantics
SELECT claim_type, SUM(total_paid_amount) FROM metric_view GROUP BY claim_type
```

This applies to:
- Dashboard dataset SQL
- Genie example SQL
- Documentation sample queries
- Cross-validation sweep queries

---

## G-3: Canonical Authority Hierarchy (MANDATORY)

Authority is scoped to the fact being resolved. No artifact is authoritative for every field.

| Fact Being Resolved | Canonical Authority | Required Handling |
|---|---|---|
| Requested assets and run options | `accelerator.yaml` | Requested configuration only; never proof of deployment |
| Resolved run configuration | Current-run `run_context.yaml` | Frozen configuration for orchestration; never schema, KPI, or deployed-content authority |
| Business definitions, KPI formulas, terminology, and requested dimensions | KPI specification | Business intent only; never physical-column authority |
| Approved Metric View feature policy and fallback behavior | Resolved `metric_view_capabilities.yaml` contract | Reproducible accelerator policy for the run; official documentation informs contract refresh, not live runtime reinterpretation |
| Genie release thresholds and benchmark outcome semantics | Approved `genie_quality` source contract | Step 0 authenticates it and freezes the only executable effective snapshot in `run_context.validation`; downstream defaults or reinterpretation are forbidden |
| Governed datatype-only completion policy | Digest-attested ERD helper and DDL template, release-parity-tested against `datatype_resolution_policy.yaml` | Only the attested Data Layer helper/runtime may apply it in eligible greenfield-synthetic scope; the descriptive contract need not be present in an existing run context |
| API/YAML request and serialization structure | Approved versioned platform references and deterministic runtime templates | Structure authority only; never proof of persisted asset content |
| Extracted source design | resolved `erd_parsed.yaml` plus `schema_assumptions.yaml` | Visible values are `OBSERVED`; policy-resolved values are `INFERRED_POLICY`; raw/resolved hashes and provenance must authenticate |
| Expected generated physical schema | `table_spec.yaml` | Planned greenfield tables, columns, and types; never proof of deployed reality |
| Deployed physical tables, columns, types, and existence | Current catalog inspection through `DESCRIBE TABLE`, `information_schema`, or an approved catalog API | Final authority for what physically exists |
| Relationship, classification, and grain intent | `semantic_model.yaml` | Intended semantic model |
| Validated deployed schema, relationships, and grain | standalone `schema_assumptions.yaml`, `schema_reconciliation.yaml`, plus `data_layer_validation.yaml`, backed by catalog and data checks | Assumptions must authenticate with policy `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1` and zero unresolved datatypes; reconciliation must authenticate with policy `DEPLOYED_DATATYPE_REPAIR_V1`, `status: PASS`, and zero unresolved mismatches before data generation; final validation must authenticate/embed both and record applicable relationship checks PASS; otherwise halt the dependent stage |
| Resolved target names, FQNs, paths, and runtime identifiers | `step_handoff.yaml` | Consume verbatim; never re-derive downstream |
| Desired Metric View architecture and definitions | `metric_view_plan.yaml`, `metric_view_design.yaml`, and `metric_view_spec.yaml` | Desired state only |
| Deployed Metric View semantic surface | Current Metric View `DESCRIBE`/query plus approved catalog or API readback | Final authority for deployed measures, dimensions, and aliases |
| KPI implementation and validation status | Current-run `metric_view_validation.yaml`, bound to the current plan/spec/capability/readback evidence | Authoritative for implemented, validated, skipped, and not-implemented status |
| Dashboard page inventory | KPI specification Dashboard Mapping | Exact ordered mapped pages override fallback page-count heuristics; if no mapping exists, require a non-empty fallback canvas inventory |
| Dashboard structural-vs-quality classification | Frozen `run_context.quality_gates.dashboard_policy` | Structural failures block; quality-target misses remain `WARN` and map the Dashboard stage to `PARTIAL_SUCCESS` |
| Desired Dashboard state | Validated `dashboard_design.yaml` | Intended pages, datasets, widgets, filters, and layout only |
| Serialized text-widget representation | Digest-attested `build_text_widget()` from the frozen Dashboard helper | Sole executable serializer; semantic design input only, opaque return value, no alternate or inline serializer |
| Desired Genie state | Validated Genie configuration/design artifacts | Intended instructions, questions, example SQL, benchmarks, and attached Metric View set only |
| Deployed Dashboard and Genie state | Current official API GET/readback | Final authority for deployed asset identity and content |
| API-created immutable asset locator | Readback-backed deployment manifest | Locates the asset for later GET/readback; never current-content authority by itself |
| Consolidated deployment-quality evidence | Readback-backed manifests, validations, and `ground_truth_validation.yaml` | Derived evidence; direct current readback remains authoritative if they disagree |

Every YAML authority artifact in this hierarchy MUST be parsed with a loader that rejects duplicate
mapping keys at every nesting level. A duplicate key is malformed authority and halts with the
owning authority/hand-off error; it must never be silently collapsed by a permissive YAML loader
before required-key, exact-key-set, hash, or identity checks run.

**Conflict rules:**

1. Resolve each fact using its row above; do not apply one generic artifact priority to every fact.
2. Intent describes what should exist. Catalog or API readback describes what does exist.
3. If expected and deployed state differ, deployed readback remains the factual observation, but the owning validation gate MUST fail. A downstream stage MUST NOT silently adapt to the drift.
4. If applicable authority is missing after its defined creation point, or is missing when a
   consumer/resume path authenticates it, HALT and report the owning stage; do not substitute a
   lower-authority artifact. Absence of a producer phase's own output before its first execution is
   expected and MUST NOT be classified as missing input authority.
5. Later stages consume validated upstream authority; they do not reinterpret or repair it locally.
6. Fields duplicated between `run_context.yaml` and `step_handoff.yaml` MUST match or the master resolver halts with `HANDOFF_AUTHORITY_ERROR`. The handoff owns only values actually present in it. Downstream consumers never modify it; the designated Metric View producer may idempotently update only `metric_view_fqns[]` under its documented planning contract.
7. A mismatch between an expected generated datatype and catalog readback is owned only by Data Layer GATE 4.2. The observed catalog type remains factual, but no downstream stage may cast around it or rewrite `table_spec.yaml`. Automatic mutation is limited to one compiler-driven recreation of an exact empty current-version generated target; every other case halts without mutation.
7a. Synthetic data MUST NOT be generated or inserted until the current-run `reconcile_schema`
    phase is reusable, `{OUTPUT_FOLDER}/schema_reconciliation.yaml` authenticates with
    `status: PASS`, and a fresh exact deployed name/type readback still matches
    `table_spec.yaml`. Missing, failed, stale, or contradictory reconciliation evidence is a hard
    stop before the first write.
7b. Precision, scale, length, and datatype are schema intent. Route incomplete extraction back to
    the owning Data Layer parsing gate for two evidence retries. The only inference exception is
    `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`, limited to ERD-driven generated targets with both
    `greenfield.enabled` and `greenfield.synthetic_data` true. Persist raw/resolved ERD hashes and
    every decision in `schema_assumptions.yaml`; label inferred values `INFERRED_POLICY`. Never apply
    this exception to source/live schemas, retained data, structural identity, or catalog drift.
8. Dashboard and Genie creation require the current-run Metric View producer stage to be enabled
   and validated. If `create_metric_views` is disabled, both dependent creation stages must also be
   disabled; an explicit FQN in frozen configuration is identity intent, not current-run validation.
9. A disabled pipeline stage has no `run_context.phases_completed` records for that stage. Preserve
   only its explicit `SKIPPED` stage status; stale phase or artifact presence is not resumable
   evidence and must fail authority reconciliation.

**Documentation exception:** Documentation may continue when an observation authority is unavailable only by labeling the claim `UNKNOWN` or `RECORDED_UNVERIFIED`, preserving the intended value separately, and making no success/deployment claim. It never promotes a lower-authority artifact.

**Column-name enforcement:**

- Before deployment, resolved `erd_parsed.yaml` plus authenticated `schema_assumptions.yaml` supply design context and `table_spec.yaml` defines the expected generated schema.
- After deployment, catalog inspection is physical truth. `data_layer_validation.yaml` records whether deployed reality matches the expected schema.
- Metric View consumers use current Metric View readback for deployed aliases; desired YAML definitions do not override readback.
- `describe_metric_view()` in the helpers template returns deployed columns.
- `validate_column_refs()` asserts that every reference exists.
- `validate_domain_cols()` in the dbldatagen template asserts that generated column names match the expected schema.

### Auto Metric View producer checkpoint (exact authentication contract)

The Metric View stage is the sole producer allowed to add auto-planned entries to
`step_handoff.yaml.metric_view_fqns[]`. For `metric_view_strategy: auto`, the top level of
`{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml` MUST contain exactly one
`auto_handoff_producer_checkpoint` mapping with these keys:

```yaml
auto_handoff_producer_checkpoint:
  producer_step: create_metric_views
  producer_phase: plan_metric_views
  status: PASS
  run_id: <exact current run_context.run_id>
  asset_suffix: <exact frozen asset_suffix>
  metric_view_strategy: auto
  step_handoff_path: <normalized canonical OUTPUT_FOLDER/step_handoff.yaml path>
  step_handoff_sha256: <lowercase SHA-256 of exact post-synchronization handoff bytes>
  metric_view_plan_payload_sha256: <lowercase canonical payload SHA-256>
  metric_view_entries:
    - name: <exact planned name>
      normalized_sql_fqn: <normalized exact three-part SQL FQN>
      primary: true
  capability_contract_version: <exact approved contract version>
  capability_contract_sha256: <lowercase SHA-256 of exact approved contract bytes>
```

Before applying either strategy branch, both `metric_view_plan.yaml` and
`metric_view_validation.yaml` MUST contain these three top-level replay bindings:

```yaml
run_id: <exact current run_context and handoff run_id>
asset_suffix: <exact frozen run_context and handoff asset_suffix>
metric_view_strategy: auto | explicit
```

All three fields MUST be present in both artifacts and exactly equal each other,
current-run `run_context.yaml`, and `step_handoff.yaml`. `run_id` and `asset_suffix` must
also be non-empty, and `metric_view_strategy` must be exactly `auto` or `explicit`. A
missing or mismatched replay binding invalidates the plan or validation even when its
terminal status says PASS or its identity tuples otherwise match. In auto mode the plan's
three top-level fields remain inside the canonical payload hash and must also equal the
corresponding producer-checkpoint values; remove only the checkpoint field when hashing.
These replay bindings are plan/validation fields and MUST NOT be added to or otherwise
change the checkpoint's exact key set.

The key set above is the producer-checkpoint schema; consumers MUST reject missing keys,
unexpected strategy values, duplicate normalized FQNs, duplicate names, non-boolean
`primary` values, or any value mismatch. `metric_view_entries` authenticates the complete
tuple `(name, normalized_sql_fqn, primary)` for every planned entry, not only an FQN set.
Its tuple collection MUST equal both the plan's complete Metric View collection and the
post-synchronization handoff collection, and exactly one entry MUST have `primary: true`.
The checkpoint's stored `metric_view_entries` list MUST itself already be ordered ascending
by `normalized_sql_fqn`; consumers reject a reordered stored list rather than sorting it into
compliance. Consumers independently normalize and sort derived plan, validation, and handoff
collections before comparing those collections with the already-canonical checkpoint list.

`normalized_sql_fqn` has one canonical stored comparison form. Every raw executable
`sql_fqn` in the frozen run context, handoff, plan, validation, intermediate-view record,
or manifest MUST first be exactly three separately backtick-quoted non-empty segments;
unquoted, partially quoted, whole-FQN-quoted, or trailing-content forms are invalid. Parse
those three segments and, for each, remove the one required matching outer backtick pair,
replace every doubled-backtick escape with one literal backtick for comparison, apply Unicode
`casefold()`, and require the result to remain non-empty. Join
the three normalized segments with `.` and store the result unquoted. Reject an FQN that
cannot be parsed into exactly three such segments; no alternate quoting or
case-normalization rule is permitted for checkpoint comparison.

Compute `metric_view_plan_payload_sha256` from the fully parsed plan after removing the
entire top-level `auto_handoff_producer_checkpoint` field. Serialize that remaining value
exactly as UTF-8 JSON using:

```python
json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

Then apply SHA-256 and store the lowercase hexadecimal digest. No YAML text hash,
whitespace normalization, alternate JSON settings, or partial-subtree hash is valid.
`step_handoff_sha256` is instead the SHA-256 of the exact raw bytes read from the canonical
handoff after the producer's final atomic write.
The stored `step_handoff_path` string itself MUST equal that already-normalized canonical sibling
path byte-for-byte. Consumers must not normalize a noncanonical stored spelling (including `..`,
`.` segments, duplicate separators, or alternate roots) and then accept it as equal.

Before consuming auto-produced identities, every downstream stage, resume path,
cross-validation sweep, documentation reconciliation, and destructive cleanup path MUST
authenticate all checkpoint values, recompute both hashes, verify the capability tuple,
and require one and only one separately persisted durable `run_context.phases_completed` record for
`plan_metric_views` from the same run, with `checkpoint_status: VALID`, a non-empty `completed_at`,
and a passing fingerprint Resume Skip Gate. `producer_phase` does not replace that lifecycle
record. A failed check is owned by `METRIC_VIEW_STAGE` unless the exact run or canonical
path selection itself conflicts, which is owned by `MASTER_RESOLVER`.

For `metric_view_strategy: explicit`, the same top-level field MUST be present as an
explicit null:

```yaml
auto_handoff_producer_checkpoint: null
```

Missing, `{}`, or non-null is invalid in explicit mode. Explicit identities must retain
exact Step-0 handoff/plan/validation parity, including the mandatory top-level
`run_id`/`asset_suffix`/`metric_view_strategy` replay bindings, and the Metric View stage
MUST NOT write a producer checkpoint or mutate their handoff entries. These rules authenticate the
one documented producer mutation in addition to the separate generic phase checkpoint. Failure
marks `plan_metric_views` and its graph dependents `STALE` without changing the producer
checkpoint's exact key set.

---

## G-4: Deterministic Deployment Runtime (Always Use, Never Hand-Write)

All deployment artifacts MUST be built using the Deterministic Deployment Runtime (template notebooks that consume declarative specs). The LLM produces the declarative spec; the runtime handles compilation, validation, and execution. Never hand-write:
- DDL SQL → produce `table_spec.yaml`, let compiler generate CREATE TABLE
- Dashboard widgets → produce `dashboard_design.yaml`, let the template build Lakeview JSON; every
  text widget is emitted only by the digest-attested `build_text_widget()` callable
- Genie spaces → produce and validate `llm_genie_design.yaml`, pass its exact approved fields as template placeholders, and let the template call the Genie API
- Metric views → produce `metric_view_spec.yaml`, let template call Statement Execution API
- Synthetic data → produce `synthetic_data_spec.yaml`, let template run dbldatagen

**Why:** Hand-written JSON/SQL consistently omits required fields (e.g., `queryName` in filter widgets, commas in DDL). Template functions include these fields unconditionally. Declarative specs are diffable, reproducible, and CI/CD-friendly.

---

## G-5: No Silent Failures

NEVER catch and ignore errors during:
- SQL execution (dataset validation, metric view creation)
- API calls (dashboard create/publish, Genie space POST)
- Gate check assertions

If a step fails, it MUST either:
1. Raise an exception that halts the pipeline, OR
2. Write a FAIL status to the step's validation artifact

Catching an error and proceeding as if it succeeded is a pipeline violation.

---

## G-6: No Stage Re-Execution During Later Stages

NEVER re-run an earlier pipeline stage during a later stage:
- Do NOT re-run data layer notebooks during dashboard/Genie/documentation steps
- Do NOT re-create metric views during dashboard creation
- Do NOT regenerate synthetic data to fix a dashboard issue

If an earlier stage's output is missing or invalid:
1. HALT the current stage
2. Report the dependency failure
3. Let the orchestrator re-run the failed stage explicitly

**Specific prohibition:** Do NOT run any notebook that imports `dbldatagen` outside of Step 2 (Create Data Layer). The `dbldatagen` library is a Step 2 dependency only.

---

## G-19: Fingerprinted Phase Checkpoints and `STALE` Invalidation (MANDATORY)

`prompts/shared/state_contract.md` is the canonical checkpoint schema, digest algorithm, skip gate, and
dependency graph. Phase-specific artifact/readback checks are necessary but never sufficient.

Before any phase skip, require all of the following:

1. one exact current `(step, phase)` record with checkpoint contract version `1` and
   `checkpoint_status: VALID`;
2. current state-contract, producer prompt/version/hash, guardrail-bundle hash, and frozen-run
   digest parity;
3. exact mandatory input/output fingerprint ID sets and recomputed digest parity; and
4. the owning stage's complete structural, semantic, catalog, or official API readback check.

First apply shared “Phase entry and read scope”; this is a skip gate, never an output-existence
prerequisite for a new phase. A missing-only checkpoint with prior execution evidence uses shared
recovery before replay. If an existing candidate fails, atomically mark its record and every transitive graph dependent current record `STALE`
before regeneration. Do not treat existence, a completion event, a manifest, or a matching output
alone as freshness. Stateless load/gather phases are always re-read and never reusable.

`STALE` is not mutation authority. A later stage halts and returns the defect to the owning stage;
the orchestrator schedules re-execution from the earliest stale phase. Existing safety,
idempotency, deployment ownership, and `DEPLOYED_DATATYPE_REPAIR_V1` rules still control every
write. The Metric View auto-handoff producer checkpoint remains a separate exact-key attestation.

Completion is a consumer barrier, not a display event. For every reusable phase, atomically
upsert and re-read the one exact `run_context.phases_completed` record before emitting a completed
progress event. Optional host telemetry must not gate this acknowledgement. Do not launch a downstream
notebook while the workspace record is absent or fails parity; classify that
condition as `CHECKPOINT_PERSISTENCE_ERROR`.

---

### Sequential execution and truthful progress

The master owns stage boundaries. Use `report_progress` (or the same structured
transcript event on hosts without that tool) with exact stage identifiers:
`load_configuration`, `environment_setup`, then the enabled router stage names.
After a stage's required gates pass and its reusable checkpoints have been persisted
and read back, emit `phase_id=stage_completed`, `status=completed`, a stage-specific
`phase_name`, and `stats` identifying the validated evidence. This explicitly closes
the stage for observers; completing one phase does not close its parent stage.
Never use `report_step_complete` for this: that terminates the whole master in the App.
Do not copy or invent completion of other phases when closing a stage.

Before entering the next stage, verify the preceding stage's actual required evidence,
close its reporting, then emit the new owning phase's `started` event before its first
tool call. A progress event is a report of admission, not its proof. Missing telemetry
alone does not authorize replay of successful mutations or require Lakebase. Missing
or failed upstream evidence blocks the consumer under the existing owner gates.

Every host must enforce this ordering, including Genie Code. Include the owning
stage as `step_name` in progress events. Only acknowledge completion after the
phase's required readback and durable checkpoint commit. A missing event is not
proof of success: display it as unverified and authenticate the checkpoint before
reuse. On a failure, close active UI activity as failed; do not leave it running or
promote it to success. Progress display never determines execution eligibility.

When progress tools are available, emit `started` for the exact owning phase before
its first tool call, then `completed` only after its checkpoint/readback gate. Finish
Parse ERD reporting before starting Generate DDL; finish DDL and reconciliation
before starting Generate Synthetic Data. Do not leave the phase at `parse_erd`
while deploying/executing a synthetic-data notebook. If an event was omitted,
authenticate the existing checkpoint before reporting completion; never fabricate
success to clean up the UI. Without progress tools, retain the same checkpoint
barriers and communicate the current phase through the host's available channel.

Hosts must preserve unverified phase status even when the parent step is complete.
A later step's activity does not prove preceding steps completed. Tool activity
without explicit phase attribution belongs at step level, not under a stale phase.
These display rules do not add Lakebase or App telemetry as execution dependencies.

---

## G-7: Python 3.11 Compatibility

DO NOT use backslashes inside f-string `{}` expressions. This is a hard Python 3.11 syntax constraint.

```python
# ILLEGAL — SyntaxError on Python <3.12
f"{'\u2500' * 40}"
f"{'\n'.join(items)}"

# CORRECT — extract to variable
separator = '\u2500' * 40
f"{separator}"
joined = '\n'.join(items)
f"{joined}"
```

---

## G-8: Workspace I/O Rules

- Use `write_workspace_file` tool (Apps agent) or direct file I/O (Genie Code) for workspace files
- Do NOT use `dbutils.fs` for `/Workspace/` paths
- Do NOT use `os.makedirs` on `/Workspace/` paths from `execute_python` subprocess
- Do NOT use shell commands to create, write, or modify workspace files

---

### Explicit workspace file and notebook transport

Use the attested `WorkspaceStore.write()` for lifecycle files; do not invent an
untyped `put()` helper. For plain YAML, JSON, Markdown, SQL text, lock, and Python
helper files, explicitly use RAW transport through the attested WorkspaceStore, including the older-SDK enum fallback in `agent_transport.md`. SDK upload takes UTF-8 bytes;
REST/import_ takes base64 content. Verify byte readback. Never omit the format or
send these payloads as SOURCE/DBC. A Python helper stored as a file is distinct
from an executable notebook: notebooks use SOURCE with its language, or JUPYTER.
The shared workspace I/O input contains the transport examples.

A pre-execution format rejection is repairable by the agent before resubmission.
An archive/import error after execution is not evidence that nothing changed:
inspect prior writes before retrying. Do not change permissions or invent another
transport to bypass access errors. These rules apply to every host; App preflight
checks are additional enforcement, not a substitute for the prompt contract.

---

## G-9: Anti-Shortcut Enforcement

The agent MUST NOT take shortcuts even when:
- "It's just a small change"
- "The previous step already validated this"
- "I know what the columns are from the spec"
- The context window is running low

Every numbered step must execute. Every GATE must be verified. Every Output Contract artifact must exist.

---

## G-10: Idempotency (MANDATORY)

Every Deployment Runtime MUST be rerunnable safely. Same specification + same environment = same final state.

Each manifest MUST include:

```yaml
artifact_id: <unique_id>
source_hash: <sha256 of declarative spec>
generated_hash: <sha256 of compiled output>
readback_hash: <sha256 of deployed state from applicable catalog/SQL or official API readback>
state_comparison: match | mismatch
```

The manifest records the evidence chain from desired state through the readback performed for that deployment attempt. It is not a substitute for current catalog/API observation on a later resume. If `source_hash != readback_hash` after the contract's deterministic normalization, the deployment is incomplete and the pipeline MUST fail.

---

## G-12: Exact Run Bootstrap, Canonical Paths, and Pinned Helpers

Every stage MUST begin from the exact `run_context_path` selected and supplied by the
master resolver. It MUST NOT discover a run by listing version folders, choosing the
newest file, using the current directory, consulting a live request file, or rebuilding a
path from domain/version components.

### Exact bootstrap sequence

1. Accept the non-empty tool/orchestrator-supplied `run_context_path` as input. Normalize
   it only for path comparison; do not rewrite it or substitute another candidate.
2. Read the exact raw bytes at that path and parse one YAML mapping. Missing or malformed
   content is `HANDOFF_AUTHORITY_ERROR`. Permission and transport/I/O failures retain
   their operational classification and MUST NOT be mislabeled as malformed authority.
3. Require a non-empty absolute `run_context.output_folder`. The normalized parent of
   `run_context_path` MUST equal normalized `run_context.output_folder` exactly. Set
   `OUTPUT_FOLDER` only from that parsed value.
4. Load exactly `{OUTPUT_FOLDER}/step_handoff.yaml`; do not search. Require its
   `output_folder` to equal the frozen run-context value and validate every shared field
   under G-3 before using any downstream identity.
5. Read `deploy_root` from the parity-checked handoff and require it to equal the frozen
   run-context runtime value whenever either artifact supplies it. For a legacy Data Layer
   bootstrap only, if both omit it, continue with the frozen absolute helper/template path-and-hash
   tuples and do not reconstruct a root. All other stages require the value. `templates_dir`, when
   needed only to resolve an approved source artifact, is the single suffix
   `{deploy_root}/framework/templates`.

Any missing required authority after applying that explicit legacy Data Layer exception, or any
ambiguous/conflicting path or identity authority, halts and returns to `MASTER_RESOLVER`.
Downstream stages never repair `run_context.yaml`, non-producer handoff fields, or the selected path.

### Prohibited path patterns

- `os.environ.get("DEPLOY_ROOT", ...)` or another environment fallback
- Hardcoded user/workspace paths
- Counting `os.path.dirname()` levels to locate a run or deploy root
- Glob/latest-version selection after the resolver has selected a run
- Reconstructing `OUTPUT_FOLDER` from domain, version, suffix, or the request file
- Silently switching to another `run_context.yaml` after a parse or parity failure

### Digest-qualified framework/helper loading

Executable framework code is trusted only when both its exact approved source path and
expected lowercase 64-hex SHA-256 are supplied by the frozen resolver/template contract.
This applies to `gate_checks.py`, Dashboard helpers, Genie helpers, ERD utilities, and any
other imported accelerator helper.

The loader MUST:

1. read the exact source bytes and verify their SHA-256 before import;
2. copy those exact bytes, when a `.py` import copy is required, into a digest-qualified
   directory such as `/tmp/pipeline_python/<full_sha256>/`;
3. verify the copied bytes have the same digest;
4. load with a unique module name containing the digest (for example through
   `importlib.util.spec_from_file_location`), register it in `sys.modules` BEFORE
   `exec_module` (remove that entry on load failure), attest its `__file__`, and
   verify every required callable/signature before use; and
5. fail closed on missing path/hash, digest mismatch, stale module identity, missing
   callable, or incompatible signature.

Bootstrap the lifecycle helper with the exact loader in `shared/agent_transport.md`.
Do not authenticate helpers with `inspect.getsource`, `getfile`, or `getsourcefile`:
dynamic notebook/process loaders may not support source reflection. Hash original
bytes, verify the staged file, and check callable signatures. A source-reflection
failure is a loader/introspection problem, not evidence that a Workspace write failed.
Never respond by rewriting the helper or bypassing digest checks. Honor host process
boundaries: reload verified helpers when Python calls do not share a session.

Compatibility aliases may be installed only after this attestation and only for the
verified module instance needed by a verified dependent helper. A stage MUST NOT import a
fixed `gate_checks`, `lakeview_dashboard_helpers`, or similarly named module from ambient
`sys.path`; insert a shared `/tmp/pipeline_python` or `templates_dir` into `sys.path`; copy
an unverified helper beside an output artifact; use an already-cached module; or implement
a manual validation fallback when a pinned helper is absent or incompatible. Such a
failure is a helper-contract failure owned by the stage invoking it, not evidence that its
validation passed.

---

### Selection persistence and completion acknowledgement

**Allocation is not context persistence.** A new selection reserves the registry entry and
returns the future `run_context_path`; the file does not exist yet. Continue through 0.4–0.8,
build the full frozen context, persist it through the workspace store, and verify exact readback.
Do not read a newly allocated context as an existing input, emit `run_selected: completed`,
or launch asset creation before that barrier. Started/update progress is informational only.
A missing context during this same active bootstrap must be resolved by finishing its
authorized context write, not allocating another version or writing a placeholder context.
An orphan from a previous interrupted allocation still follows the resolver's recovery rules.

When a host provides `report_progress`, use `step_name=load_configuration`,
`phase_id=run_selected`, `status=completed`, and `stats.run_context_path` only after
verified context persistence. Started/update events make no persistence claim and
must not trigger a context read in a UI callback. A premature completion error
returns to the agent for the missing bootstrap step; it must not escape a display
callback and terminate orchestration. A host without a progress tool emits the
same structured event to its transcript after the same workspace checks.

For this event, `stats` is a mapping and `stats.run_context_path` is the exact plain
string from the persisted selection, not `{value: ...}`, a folder, a relative path,
or a path reconstructed from the latest version. Example call shape (substitute the
authenticated locator variable, never this illustrative variable name as text):

```python
report_progress(step_name="load_configuration", phase_id="run_selected",
                phase_name="Resolve and Freeze Run", status="completed",
                stats={"run_context_path": run_context_path})
```

Report selection completion at the Config boundary. Setup and later-stage updates
use their own owning step/phase; do not replay `run_selected` as a generic completion
signal. If a selection report is rejected, inspect its arguments and authenticate the
existing context. A malformed telemetry argument is not permission to reallocate,
overwrite the run context, or rerun successful Setup. Correct the report with the
same authenticated locator; actual identity conflicts still halt under owner gates.


The master reports final completion only after its terminal lifecycle commit and
includes the canonical root `run_manifest.json` locator, including on failure when
a valid run context exists. In the App, `report_step_complete` terminates the whole
master invocation; stage completion uses progress/checkpoint events instead.

---

## G-15: SHOW TABLES / SHOW VIEWS LIKE Uses Glob Syntax (Not SQL LIKE)

Databricks `SHOW TABLES LIKE` and `SHOW VIEWS LIKE` use **glob syntax** where `*` is the wildcard. They do NOT use SQL `LIKE` syntax where `%` is the wildcard.

```sql
-- CORRECT (glob wildcard)
SHOW TABLES IN catalog.schema LIKE '*_v2'

-- WRONG (SQL LIKE wildcard — returns 0 results)
SHOW TABLES IN catalog.schema LIKE '%_v2'
```

**Impact:** Using `%` returns zero results, causing GATE 4.1 (table existence check) to falsely report all tables as missing — even though the CREATE TABLE statements succeeded.

**This applies to all SHOW commands with LIKE:** `SHOW TABLES`, `SHOW VIEWS`, `SHOW SCHEMAS`, `SHOW DATABASES`.

For filtering in `information_schema` queries, SQL `LIKE` with `%` IS correct — this rule only applies to `SHOW ... LIKE`.

---

## G-13: No `spark.sql()` in execute_python Context

`spark.sql()` is NOT available in the `execute_python` subprocess used by the Apps agent. Any step that runs SQL in `execute_python` MUST use the **Statement Execution API** (`w.statement_execution.execute_statement()`) or the helper function `_execute_sql_via_api()` from the dashboard helpers template.

**Scope:** This applies to Steps 3 (dashboards), 4 (Genie), 5 (documentation), and any future step that uses `execute_python`. Step 2 (data layer) runs in a notebook where `spark.sql()` IS available — this rule does not apply there.

**Error signature:** `NameError: name 'spark' is not defined`

**Why per-step rules are not enough:** The LLM has attempted `spark.sql()` in dashboard, Genie, and documentation steps. Repeating the prohibition in each step guardrail is fragile. This global rule is the single authority.

---

## G-14: PARENT_PATH Must Be the Output Folder (Not User Home)

When creating dashboards, Genie spaces, or other workspace assets, the stage path MUST point to the versioned output subfolder, NOT the user's home root.

**Correct pattern (resolved once by master Step 0):**
```text
PARENT_PATH = "<resolved writable version-scoped dashboard parent>"
GENIE_PARENT_PATH = "<resolved writable version-scoped Genie/template parent>"
```

The master resolver owns platform-specific path construction and writes both values to `step_handoff.yaml`. Downstream stages use the appropriate resolved handoff value verbatim.

**Prohibited pattern:**
```text
PARENT_PATH = "/Users/{username}"              # PermissionDenied for service principal
PARENT_PATH = "/Users/arun.wagle@databricks.com"  # Hardcoded, non-portable
```

**Why:** The service principal that executes pipeline steps does NOT have create permissions at the user's home root. It only has permissions within the project directory tree. This caused `PermissionDenied` errors in dashboard deployment.

If `step_handoff.yaml` is missing the required stage path, HALT with `HANDOFF_AUTHORITY_ERROR` and rerun the master Step 0 resolver. Do not derive and write a replacement in a downstream stage.

---

## G-17: `%pip` Must Be Alone in Its Cell

`%pip install ...` is a Databricks cell magic. It MUST be the **only content** in its cell. Mixing `%pip` with Python code (e.g., `dbutils.library.restartPython()`) in the same cell causes preflight syntax rejection — the cell is parsed as Python, and `%pip` is not valid Python syntax.

**Correct pattern (two separate cells):**
```
Cell N:   %pip install somepackage --quiet
Cell N+1: dbutils.library.restartPython()
```

**Wrong pattern (single cell):**
```
%pip install somepackage --quiet
dbutils.library.restartPython()     # ← preflight rejects this cell
```

**Also prohibited:** Adding `%pip install` cells to generated notebooks when the package is already pre-installed on the runtime (e.g., `pyyaml`, `databricks-sdk`). Only add `%pip` when the package is genuinely not available.

---

## G-16: Template Notebooks Use `deploy_from_template` Tool

Pass the exact persisted `run_context_path` to deployment tools that accept it.
Authenticate that file and the output path directly. No prior progress event, host
memory flag, or Lakebase acknowledgement is deployment authority. For compatible
tools without a separate locator argument, the exact run-root OUTPUT_FOLDER binds
its canonical `run_context.yaml`; read and validate that file before trusting it.


Template deployment is a mandatory admission barrier. Select the exact release-owned
path and verify its frozen SHA-256; a legacy same-named template is not an alternative. Enumerate placeholders from
the actual frozen template and bind every required value before calling the tool.
A template read/render/import error means no successful deployment acknowledgement;
HALT the current run and dependent stages, persist failure evidence, and return to
the master. Do not treat tool failure as completion or proceed to another stage.
Corrections are made in the owning phase on authenticated retry, never by skipping
its producer. An old notebook at the intended output path does not prove success.


When deploying via a template notebook (`ddl_notebook.py.template`, `metric_view_notebook.py.template`, `dbldatagen_notebook.py.template`, etc.), the LLM MUST use the `deploy_from_template` tool. This tool:

1. Reads the template as a **single string**
2. Replaces **ONLY** the declared placeholders via deterministic string substitution
3. Imports the result **UNCHANGED** as a notebook
4. Validates that no unreplaced placeholders remain

**DO NOT:**
- Use `import_notebook` for template-based notebooks — it will reject paths containing template stems (ddl\_, dbldatagen\_, metric\_view\_, dashboard\_, genie\_space\_)
- Rewrite template logic or import a hand-built replacement. Reading authenticated template bytes for interface inspection and render preflight is required; shared portable transport may perform exact substitution when the host has no deployment tool.
- Rewrite, summarize, simplify, or "improve" any cell
- Remove docstrings, comments, or validation code (especially gate checks)
- Drop any gate (Gate 1, 2, 2b, 3, 4) or verification step

**Why:** LLMs reliably fail at "copy verbatim" — they truncate large code blocks, remove "unnecessary" comments, and "optimize" logic, which silently drops critical validation gates. The `deploy_from_template` tool removes the LLM from the file-copy loop entirely, making this failure mode impossible.

**Validation:** Require complete binding validation before deployment and an explicit successful import acknowledgement afterward. On unreplaced placeholders, halt and return to the master for an authenticated owning-phase retry under the admission rule above. Never execute an older notebook as a fallback.

---

## G-11: Context Window Optimization

Prompt files are large. To conserve context window:
- Each stage instructions file uses CONTEXT ISOLATION — forget prior stage execution details and read only required handoff/evidence artifacts
- Always-loaded validation/guardrail controls may be injected via `SUPPLEMENT_FILES` in the app — do not re-read them when their exact frozen bytes are already in context
- Failure runbooks are never startup supplements; authenticate and load only the matching diagnostic section after a classified failure
- Template notebooks are read ONCE per step — do not re-read across iterations
- Use `run_context.yaml` and `step_handoff.yaml` as the carriers of resolved configuration and identity. Continue to consume the semantic, validation, manifest, and readback artifacts identified by G-3 for their scoped facts.
- Avoid quoting large code blocks in progress reports — reference artifacts by path instead

## G-18: TRUNCATE TABLE Is Not Supported

`TRUNCATE TABLE` is **not supported** in Databricks SQL with Unity Catalog. Any `TRUNCATE TABLE` statement will fail with `PARSE_SYNTAX_ERROR`.

**Always use `DELETE FROM` instead:**
```sql
-- ❌ WRONG: TRUNCATE TABLE `catalog`.`schema`.`my_table`
-- ✓ CORRECT:
DELETE FROM `catalog`.`schema`.`my_table`
```

The `execute_sql` tool blocks TRUNCATE statements at the pre-flight gate. If you need to clear a table's data, use `DELETE FROM` (no WHERE clause = delete all rows). For full table recreation, use `DROP TABLE IF EXISTS` + `CREATE TABLE`.

---

## G-17: One SQL Statement Per Execution Call

Databricks SQL allows only **ONE statement per call**. This applies to both `execute_sql` (App tool) and `executeCode` with `language: "sql"` (Genie Code).

Never combine multiple statements with semicolons in a single call:

```text
-- WRONG (two statements in one call — causes PARSE_SYNTAX_ERROR):
execute_sql("DROP MATERIALIZED VIEW IF EXISTS `cat`.`sch`.`v`; CREATE MATERIALIZED VIEW `cat`.`sch`.`v` AS ...")

-- CORRECT (separate calls):
execute_sql("DROP MATERIALIZED VIEW IF EXISTS `cat`.`sch`.`v`")
execute_sql("CREATE MATERIALIZED VIEW `cat`.`sch`.`v` AS ...")
```

**Impact:** The second statement triggers `PARSE_SYNTAX_ERROR: extra input 'CREATE'` after the first statement's semicolon. The App's `execute_sql` handler auto-splits multi-statement SQL as a safety net, but the Genie Code path does NOT — always issue one statement per call.

---

## G-18: No JSON-Style Booleans in Python Code

Python uses `True`/`False`/`None`. JSON uses `true`/`false`/`null`. These are **not interchangeable**.

LLMs frequently emit JSON booleans when generating Python dict literals, Lakeview dashboard configs, or API payloads. `compile()` won't catch this because `true`/`false`/`null` are valid Python identifiers — the error surfaces only at runtime as `NameError: name 'true' is not defined`.

```text
# WRONG (JSON booleans — causes NameError at runtime):
config = {"visible": true, "enabled": false, "value": null}

# CORRECT (Python booleans):
config = {"visible": True, "enabled": False, "value": None}
```

**Impact:** Dashboard creation notebooks, widget configs, and API payload construction are the most common failure sites. The App's pre-flight gate (Gate 3 in `_py_compile_check`) detects this before execution, but the Genie Code path does NOT — always use Python booleans.


### Unresolved SQL columns: evidence-bound repair

Before executing generated SQL, bind each qualified column to its actual alias/table
using current catalog readback and the authenticated semantic model. On
`UNRESOLVED_COLUMN`, inspect the exact failing SQL and current columns. A suggested
column is a diagnostic candidate, not authorization to substitute it. Confirm its
business meaning and the approved join/cardinality/aggregation grain; moving a filter
or measure from a header to a detail table can change results or multiply rows.
Repair only the owning generated query/spec, rerun its validation, and retain the
failed attempt and successful verification. Never add a fabricated source column,
change an ERD, or mark the stage complete solely because the error is repairable.
If no authoritative equivalent exists, return to the semantic/KPI owner and halt the
consumer. This procedure is domain-independent and applies on every agent host.

### Setup target admission and error ownership

The authenticated `run_context.target.catalog/schema` and `step_handoff.catalog/schema`
are the only Setup execution coordinates. They must match before SQL. Use the executable
Setup builder/admission gate in `agent_transport.md`; submit its returned request unchanged.
Neither an agent host's default catalog nor a domain name supplies missing coordinates.
Missing or conflicting values stop admission; never guess `main`, `default`, or any other
namespace. This rule is generic: no member-claims-specific target is embedded in prompts.

A successful config read does not prove subsequent SQL used that config. Compare the
actual CREATE/verification target with the handoff before submission and in completion
evidence. Never report Setup completed using a schema found in a different namespace.

For permission errors, establish target parity before assigning ownership. If submitted
SQL differs, record `SETUP_TARGET_BINDING_ERROR` under `environment_setup`, preserving
expected target, actual SQL, original permission error, and statement ID. Do not request
additional privileges for the unintended namespace. If target parity holds, preserve the
platform permission failure and route it to the operator. Do not rewrite frozen context
or current config to legitimize the wrong SQL. Existing lifecycle/recovery rules still apply.

### Instruction scope and stable recovery boundary

The selected v2 release and frozen runtime references govern executable selection.
Legacy filenames in API reference documents, examples and failure histories are not
alternative templates. Read those documents for platform payload semantics, not to
replace v2 orchestration, lifecycle ownership, or release-selected executable paths.
Frozen input references are `{path, sha256}` records: read `.path`, verify `.sha256`;
never pass the mapping itself to a Workspace file tool.

Master owns stage admission, Setup and lifecycle commit; each stage's guardrails and
validation own its implementation gates. Examples are illustrative and must pass the
actual selected template interface. Shared transport handles encoding and host tools;
it does not change target identities or policies. If authoritative contracts disagree,
report the exact competing requirements and owner instead of choosing a convenient one.

A downstream failure does not invalidate predecessors whose full checkpoint and current
readback verification still pass. Missing completion telemetry is not grounds to repeat
successful writes. Apply shared state recovery for release drift and unknown execution;
do not broaden frozen-hash exclusions or invent PASS evidence to continue.
