# State & Checkpoint Contract

## Portable transport precedence

`shared/agent_transport.md` governs host integration. In v2, freeze
`runtime.state_store: workspace_only` in every host. The registry, run context,
phase artifacts, and canonical manifest are authoritative workspace state. All
App/Lakebase/event-bridge sections below describe optional telemetry adapters only;
their absence or failure cannot gate a stage, resume, or lifecycle transaction.
Apply workspace parity and checkpoint checks in every agent. `created_by` is a
stable nonempty owner string, not a closed app/genie_code enum. Lifecycle writes
use the release-selected `run_contract` helper and its cooperative lock.

For a phase that consumes handoff coordinates before auto Metric View planning,
fingerprint only the canonical immutable handoff projection excluding
`metric_view_fqns`. Record this as CANONICAL_JSON with locator
`<step_handoff_path>#immutable_coordinates`. The plan phase fingerprints its final
handoff output; later identity consumers fingerprint the complete handoff. This
prevents the authorized auto-planning update from invalidating the data layer.

## Purpose

This cross-cutting contract defines how pipeline state is persisted, recovered, and
resumed. It applies uniformly to ALL pipeline steps (01–05) and governs how `report_progress`
calls follow durable workspace checkpoints in every host.

The system provides two guarantees after every required persistence write is acknowledged:

1. **Durability** — Every reusable phase first atomically persists and re-reads its exact
   fingerprinted record in `run_context.yaml`, because deterministic notebooks consume that file
   in every host. The verified `run_context.yaml` write is the acknowledgement;
   a rendered progress call or optional telemetry write is not checkpoint persistence.

2. **Resumability** — On restart, the pipeline reads durable checkpoint records and provides
   `RESUME_CONTEXT` to the LLM, which recomputes dependencies and skips only current `VALID`
   phases that pass every fingerprint and phase-specific verification gate.

### Authority Scope

This contract governs **orchestration state**: which run and phase were reported, where
their artifacts were written, and whether the phase-specific verification check passed.
It does not make Lakebase, `run_context.yaml`, or a completed checkpoint authoritative for
business meaning, physical schema, or deployed asset content.

Apply the claim-specific hierarchy in `{AGENT_SKILLS_DIR}/prompts/shared/global_guardrails.md` **G-3: Canonical
Authority Hierarchy** whenever a checkpoint or artifact is used:

- The selected workspace contracts are authoritative for lifecycle and checkpoint records.
- `run_context.yaml` is authoritative for the resolved configuration of that run.
- `step_handoff.yaml` is authoritative for the exact resolved identities it contains.
- Current catalog inspection is authoritative for deployed tables, columns, types, and
  Metric View surfaces.
- Current official API readback is authoritative for deployed Dashboard and Genie state.
- Business and design artifacts remain authoritative only for the intent assigned to them
  by G-3; a checkpoint never promotes them into proof of deployment.

If orchestration evidence says a phase completed but the applicable catalog or API
readback disagrees, the readback remains the factual observation and the owning validation
gate fails. Do not let a downstream stage choose a more convenient source or silently
repair the conflict.

### Run Lifecycle Authority and Parity

Lifecycle is field-scoped; no single file may be used as a substitute for all of the
others:

| Lifecycle fact | Authority |
|---|---|
| Version allocation, execution owner (`created_by`), selected `run_id`, and exact `run_context_path` | The exact registry entry selected by the shared resolver |
| Frozen run configuration and mutable phase envelope | The registry-selected `run_context.yaml` |
| Optional App telemetry | Observational mirror; never resume or lifecycle authority |
| Terminal orchestrator outcome, step results, and evidence locators | Canonical `{output_folder}/run_manifest.json` written by the master |
| Deployed object existence/content | Current catalog or official API readback, never a lifecycle record |

After a run contract exists, the canonical lifecycle tuple is:

```text
(lifecycle_contract_version, domain, version, run_id, created_by,
 output_folder, run_context_path, status)
```

Require exact parity for every tuple field carried by the selected registry entry,
`run_context.yaml`, and canonical final manifest once created. Normalize
only the two path fields before comparison. A record may be absent only before its defined
creation point; optional telemetry is excluded from this tuple. Do not choose one record
and rewrite the others silently.

Use the same status in registry, run context, and terminal manifest: `running`
while active; `completed`, `partial_success`, or `failed` when terminal. A final
manifest is absent before terminal commit. Cancellation after contract creation is
`failed`; native UI cancellation labels remain optional diagnostics. Lakebase absence,
lag, or failure never blocks a workspace checkpoint or terminal reconciliation.

Every lifecycle mutation uses the exact resolver-returned path frozen byte-for-byte as
`run_context.registry_path`; it is an immutable locator and is never reconstructed. Under the
lifecycle lock, read that exact file with duplicate-key rejection, require one selected entry whose
pre-transition lifecycle tuple matches the run, and retain the raw-byte SHA-256 as a preimage.
Immediately before atomic replacement, re-read the same path and require identical bytes/digest;
then mutate only the selected entry and verify the post-write tuple while every other entry remains
unchanged. This compare-and-swap rule applies to completion, partial success, failure, cancellation
mapped to failure, and failed-run reopen. Any path, preimage, entry-cardinality, or tuple mismatch is
`RUN_LIFECYCLE_AUTHORITY_ERROR`.

`abandoned` is accepted only when the shared resolver recognizes a legacy
**pre-contract orphan**: a registry allocation that predates
`lifecycle_contract_version` and for which no unique, authenticatable `run_context.yaml`
was ever established. No current-contract writer, stage, resume handler, cleanup step, or
operator may create or change a run to `abandoned`; use `failed` for an unsuccessful
contract-bound run. An `abandoned` registry entry has no resumable checkpoints and must
never be used to infer deployed assets.

A `running` run may resume directly only after this parity gate passes. A `failed` run is
retryable only after the master resolver completes the failed-run reopen transition defined here
and routed by `00_master_prompt.md`: preserve and hash the prior failed manifest in immutable attempt history,
use a locked transition marker, remove the canonical terminal manifest, change every participating
lifecycle store to the same `running` tuple with the original `run_id`, and verify readback parity.
A new run starts with top-level `run_context.retry_attempt: 0`. Only this locked transition may
increment it, by exactly one; it is audit metadata and is not part of the immutable lifecycle tuple.
A transition uses exactly `{output_folder}/.lifecycle/retry_transition.yaml` and this exact marker
schema:

```yaml
lifecycle_contract_version: 1
transition_id: <new non-empty UUID>
run_id: <same authenticated run_id>
version: <same positive version integer>
created_by: <same app|genie_code owner>
registry_path: <exact caller-supplied registry path>
output_folder: <same canonical output folder>
run_context_path: <same canonical context path>
prior_status: failed
target_status: running
prior_manifest_path: <verified immutable history-copy path>
prior_manifest_sha256: <lowercase 64-hex raw-byte digest>
retry_attempt_from: <authenticated current retry_attempt>
retry_attempt_to: <retry_attempt_from + 1>
started_at: <UTC ISO-8601 timestamp>
```

No other keys are allowed. The marker binds the identity/path tuple, prior-manifest path and raw
digest, consecutive attempt values, target `running`, and UTC start time. A pre-existing,
malformed, or unbound marker blocks every resolver and stage until the lifecycle owner completes a
verified transition or restores the exact failed tuple.
A registry-only `failed`→`running` flip is `RUN_LIFECYCLE_AUTHORITY_ERROR`. If the transition
cannot complete or roll back to the exact failed tuple, no phase may resume.

---

## 1. Checkpoint Semantics

A `report_progress` call with `status: "completed"` becomes a **DURABLE CHECKPOINT** only after the environment-specific persistence acknowledgement described above. Never announce durable completion before that acknowledgement. A durable completion is reusable only while its fingerprinted checkpoint remains `VALID`; durability alone never authorizes a skip.

The workspace checkpoint records contain (an optional telemetry adapter may mirror these):

```text
run_id, step_name, phase_id, phase_name, status, current_task,
progress_pct, stats (JSONB), happenings (JSONB), findings (JSONB),
checkpoint_contract_version, checkpoint_status, producer_prompt_path,
producer_prompt_version, producer_prompt_sha256, producer_bundle_sha256,
frozen_run_contract_sha256, input_fingerprints (JSONB),
output_fingerprints (JSONB), invalidated_at, invalidation_reason,
started_at, completed_at
```

### Canonical Progress-Event Serialization

Every `report_progress` invocation and every `phase_update` delivered to
`persist_phase_update(run_id, step, phase_data)` MUST use a native structured object. The event
bridge MUST NOT pass Markdown, YAML, a comma-delimited string, a Python `repr`, or a string that
it expects the state store to parse a second time. `run_id` and `step` are non-empty scalar
arguments to `persist_phase_update`; `phase_data` is one JSON object, never `null` or a JSON
string containing an object.

The progress object has these transport types:

| Field | Required transport type |
|---|---|
| `phase_id`, `phase_name`, `status`, `current_task` | non-empty JSON string |
| `progress_pct` | JSON integer from 0 through 100; booleans are invalid |
| `stats` | JSON object; use `{}` when empty |
| `happenings`, `findings` | JSON arrays of JSON strings; use `[]` when empty |

`status` is exactly `started`, `update`, `completed`, or `failed`. A comma, quote, newline, or
colon inside a message remains inside one JSON string and is escaped by the serializer. Never
flatten an array into bare text such as `"read schema, compare types"`. Never send `null` for a
required scalar or JSONB field. JSON values must be finite; `NaN`, `Infinity`, and
`-Infinity` are invalid.

This is a canonical example; replace values without changing their JSON types:

<!-- CANONICAL_PROGRESS_EVENT_START -->
```json
{
  "phase_id": "reconcile_schema",
  "phase_name": "Reconcile Schema",
  "status": "completed",
  "current_task": "Schema reconciliation checkpoint persisted",
  "progress_pct": 70,
  "stats": {
    "tables_checked": 8,
    "repaired_tables": 0,
    "unresolved_mismatches": 0
  },
  "happenings": [
    "Compared expected and deployed name/type schemas"
  ],
  "findings": [
    "Reconciliation passed, and the durable checkpoint was verified"
  ]
}
```
<!-- CANONICAL_PROGRESS_EVENT_END -->

Before any Lakebase call, schema-validate the native object, serialize exactly once with a real
JSON serializer configured to reject non-finite values, parse that serialization once, and
require structural equality with the original object. Bind JSONB values through the database
driver's JSON adapter (or the once-serialized JSON text); never build JSON with interpolation or
split on commas. A serialization, schema, non-null, or JSONB write failure is
`CHECKPOINT_PERSISTENCE_ERROR`, not a cosmetic progress failure.

### Canonical Fingerprint Contract (`checkpoint_contract_version: 1`)

Before the first reusable phase completes, `run_context.yaml` MUST contain this immutable
checkpoint envelope. Paths are the exact resolver-frozen paths. Every SHA-256 value is lowercase
64-hex. Always-loaded control entries are duplicate-free and sorted by normalized `path`.

```yaml
checkpointing:
  contract_version: 1
  canonicalization: CANONICAL_JSON_UTF8_SHA256_V1
  state_contract:
    path: "<exact {AGENT_SKILLS_DIR}/prompts/shared/state_contract.md path>"
    sha256: "<SHA-256 of exact raw bytes>"
  frozen_run_contract_sha256: "<digest defined below>"
  producer_bundles:
    create_data_layer:
      prompt:
        path: "<exact {AGENT_SKILLS_DIR}/prompts/data_layer/instructions.md path>"
        version: 1
        sha256: "<SHA-256 of exact raw bytes>"
      guardrails:
        - path: "<exact global, validation, stage-guardrail, or SQL-control path>"
          sha256: "<SHA-256 of exact raw bytes>"
    create_metric_views: "<same exact shape>"
    create_dashboards: "<same exact shape>"
    create_genie_space: "<same exact shape>"
    generate_documentation: "<same exact shape>"
```

`prompt.version` is a positive integer owned by the accelerator release. The raw-byte prompt hash
is still the exact content identity, so a missed version bump cannot make changed content reusable.
Each producer bundle includes the shared global guardrail, its stage validation contract, its stage
guardrails, and `{AGENT_SKILLS_DIR}/prompts/shared/sql_generation_rules.md` wherever that stage generates SQL. The historical
failure runbook is excluded because it is not loaded on a successful path. Its separately frozen
path/version/raw digest is authenticated only after a classified failure and is recorded in that
failure evidence before an authorized targeted retry. A runbook edit does not invalidate a
successful phase that never consumed it. The `producer_bundle_sha256` is the
canonical digest of the complete parsed value at
`checkpointing.producer_bundles[<step>]`; the state-contract digest is checked separately.

`CANONICAL_JSON_UTF8_SHA256_V1` means
`sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
ensure_ascii=False).encode("utf-8")).hexdigest()`. Raw file fingerprints hash exact bytes instead.

Compute `checkpointing.frozen_run_contract_sha256` from the complete parsed `run_context.yaml`
after removing these mutable top-level keys:

```text
current_step, status, phases_completed, findings, completed_at, error, retry_attempt
```

Also remove only the self-referential
`checkpointing.frozen_run_contract_sha256` field before canonicalization. No other field may be
omitted. Recompute it on every resume. This binds all immutable run inputs, capability contracts,
helper/template path-and-hash references, enabled stages, identities, quality gates, and producer
bundles while allowing an authenticated retry attempt to retain valid checkpoints.

### Frozen context write admission

Use the attested helper's `frozen_context_sha256(context)` for the exact canonical
projection; do not reimplement the exclusion list or hash raw YAML. At initial master
freeze only, compute and store the digest after all immutable fields are complete.
On later updates, retain the recorded digest verbatim and call `verify_frozen_context`
on the proposed context before writing it through the attested store. The store repeats
this check before mutation when a frozen digest is present.

Changes to progress/checkpoint records belong only in the documented mutable fields.
Do not add top-level debugging timestamps, move paths, update template/helper hashes,
or rewrite capability/configuration fields inside a frozen context. Put diagnostic
metadata in the existing findings/diagnostic artifacts instead. Never remove the
recorded digest or recompute it to make a later update pass. This write check verifies
internal digest consistency; it is not a replacement for preimage/identity authentication.

On mismatch, preserve the rejected candidate separately from canonical context and
report the exact context path, recorded/actual digests and executing script locator.
Compare against a known authenticated preimage to identify changed field paths; a digest
alone cannot reveal them. If no trusted preimage is available, report that limitation
and return to the master. Do not fabricate the old configuration or silently unfreeze
the run. Failed terminal commit must be reported honestly if context cannot authenticate.

### Exact Reusable Phase Record

`run_context.phases_completed` contains at most one current record per exact `(step, phase)` pair.
A reusable record has exactly these keys; aliases and additional keys are invalid:

```yaml
- step: create_metric_views
  phase: plan_metric_views
  checkpoint_contract_version: 1
  checkpoint_status: VALID          # VALID | STALE
  completed_at: "<UTC timestamp>"
  invalidated_at: null
  invalidation_reason: null
  producer_prompt_path: "<exact frozen producer prompt path>"
  producer_prompt_version: 1
  producer_prompt_sha256: "<exact raw-byte SHA-256>"
  producer_bundle_sha256: "<canonical producer-bundle SHA-256>"
  frozen_run_contract_sha256: "<exact frozen run-contract SHA-256>"
  input_fingerprints:
    - id: "<stable unique dependency id>"
      kind: RAW_BYTES                 # RAW_BYTES | CANONICAL_JSON | CATALOG_READBACK | API_READBACK
      locator: "<exact path, FQN, or API identity>"
      sha256: "<lowercase 64-hex>"
  output_fingerprints:
    - id: "<stable unique output id>"
      kind: CANONICAL_JSON
      locator: "<exact path, FQN, or API identity>"
      sha256: "<lowercase 64-hex>"
```

The example `CANONICAL_JSON` output kind above is illustrative, not a default for
all phases. Stage-defined exact IDs, kinds, and locators take precedence. In particular,
`create_data_layer/reconcile_schema` requires these two outputs, sorted in this order:

- `schema_reconciliation_artifact`, `RAW_BYTES`, `{output_folder}/schema_reconciliation.yaml`.
- `schema_reconciliation_catalog_readback`, `CATALOG_READBACK`, `table_spec:{catalog}.{schema}:{asset_suffix}`.

Use the authenticated DDL-manifest `reconcile_schema_output_fingerprints` and the Data
Layer DL-G7 live-evidence validation. Never write a generic one-file CANONICAL_JSON
checkpoint for this phase. The attested store rejects that shape before writing a
context with a VALID reconciliation checkpoint. `authenticate_context` validates frozen
identity and supported checkpoint shapes; it does not execute phase gates, read live
catalogs, or authorize a PASS. Full phase validation remains required before commit.

Both fingerprint arrays are non-empty for a reusable phase, sorted ascending by `id`, and contain
unique IDs. Every item has exactly `id`, `kind`, `locator`, and `sha256`. `RAW_BYTES` hashes exact
file bytes. `CANONICAL_JSON` parses with duplicate-key rejection and hashes the canonical JSON
value. `CATALOG_READBACK` and `API_READBACK` hash the stage-defined deterministic normalized
readback, never a manifest claim. Each phase records every direct input it actually consumed,
every immediate predecessor output in the dependency graph, and every applicable helper/template
reference. The frozen contract and producer bundle provide additional mandatory bindings; they do
not permit omitting a phase dependency.

When an enabled reusable phase has a validated no-op outcome (for example, no intermediate views
are planned), persist and fingerprint a canonical current-run `NOT_APPLICABLE` decision artifact as
its output. Do not use an empty output list or fabricate a deployed object.

### Reusable-Phase Completion Commit

For every reusable phase, apply this barrier after all owned outputs and readbacks pass and before
starting any dependent phase or notebook:

1. Build the exact `VALID` phase record above from the verified inputs, outputs, producer, and
   frozen run contract. Do not derive it from display text in a progress message.
2. Re-read `run_context.yaml` with duplicate-key rejection and verify its authenticated preimage.
   Under the workspace-I/O contract, replace any prior record for the exact `(step, phase)` with
   exactly one new record, atomically write the complete file, then re-read it.
3. Require exactly one matching record, exact field/type/value equality with the intended record,
   and successful frozen-run digest recomputation. A PASS artifact with a missing record is not a
   completed phase.
4. Emit the canonical structured `report_progress(status="completed")` object after
   the workspace commit. An optional telemetry adapter may mirror this event; its
   availability and acknowledgement do not affect checkpoint validity.
5. Immediately before invoking a dependent consumer, re-read `run_context.yaml` again and require
   that the producer record remains the one exact current `VALID` record and still passes its
   phase-specific gate.

Do not acknowledge completion or invoke a dependent when any write, readback, serialization,
non-null, uniqueness, or parity check fails. Classify that failure as
`CHECKPOINT_PERSISTENCE_ERROR`. Telemetry failure is cosmetic after a verified workspace commit.

On resume, a producer artifact and its authoritative live readback may prove that the owned work
passed while exactly zero matching phase records prove that its checkpoint write was missed. In
that missing-only case, the producer may execute the completion commit once from authenticated
frozen metadata without rerunning the owned deployment. This is checkpoint recovery, not phase
success inference: any existing malformed, `STALE`, duplicate, conflicting, or unverifiable record
blocks recovery, and every normal phase-specific authority/readback gate must pass first.

For a legacy run with an entirely empty `phases_completed` list, that same fully authenticated
recovery may deterministically recompute and correct a stale/mis-sequenced
`frozen_run_contract_sha256` before creating the first phase record. Persist the corrected envelope
and recovered record in one atomic run-context write and verify readback. This exception never
applies after any phase record exists; established checkpoint history keeps the frozen digest
immutable.

Stateless bootstrap phases (`load_config`, `load_inputs`, and `gather_artifacts`) are always
re-read. They may report progress but MUST NOT create or reuse durable entries in
`phases_completed`.

The strategy-specific `metric_view_plan.yaml.auto_handoff_producer_checkpoint` is a separate
identity/handoff attestation with its existing exact key set. Never add these generic fields to that
object or use it instead of the phase record above.

### Resume Skip Gate

After lifecycle and resolver authentication, a phase may be skipped only when ALL conditions pass:

1. exactly one current phase record exists with `checkpoint_status: VALID`, contract version `1`,
   a non-empty `completed_at`, null invalidation fields, and the exact schema above;
2. the current state-contract raw bytes, producer instruction path/version/raw bytes, sorted
   validation/guardrail control bundle, producer-bundle digest, and recomputed frozen-run-contract
   digest match the record;
3. the current mandatory dependency-ID set exactly equals the stored `input_fingerprints` ID set,
   and every input fingerprint recomputes to the stored kind, locator, and digest;
4. the phase-specific structural, semantic, identity, catalog, or official API verification in
   this contract and the owning stage prompt passes; and
5. the current mandatory output-ID set exactly equals the stored `output_fingerprints` ID set, and
   every current output or normalized readback recomputes to the stored digest.

Only then replay `report_progress(status="completed")` without recreating the output. Existence,
structural validity, a manifest locator, a prior `completed` status, or a matching output hash alone
is insufficient.

### Retry granularity

Retry operates on `(step, phase)` records. A stage's aggregate FAIL never invalidates
all its phases. Locked failed-run reopen preserves existing phase records and artifact
bytes; the master then revalidates them under the Resume Skip Gate. Skip verified
predecessors, execute the first failed/missing/stale phase, and continue through its
actual dependents. Re-reading instructions, rechecking Setup, or replaying completed
progress events is not authorization to re-execute successful notebooks.

### `STALE` Invalidation and Regeneration

If a reusable record is missing, malformed, incompatible, or fails any digest/dependency/output
check, do not skip it. For an existing record, atomically set `checkpoint_status: STALE`, set a UTC
`invalidated_at`, and record a deterministic non-empty `invalidation_reason`. Then mark every
transitive dependent current record `STALE` using the graph in Section 5, even when its artifact
still exists. Persist this invalidation before re-execution.

Use one exact reason code, choosing the first applicable condition in this order:

```text
CHECKPOINT_SCHEMA_INVALID
CHECKPOINT_CONTRACT_INCOMPATIBLE
STATE_CONTRACT_CHANGED
PRODUCER_BUNDLE_CHANGED
FROZEN_RUN_CONTRACT_MISMATCH
INPUT_SET_CHANGED
INPUT_DIGEST_MISMATCH
OUTPUT_SET_CHANGED
OUTPUT_DIGEST_MISMATCH
PHASE_VERIFICATION_FAILED
UPSTREAM_STALE
EXPLICIT_DOCUMENTATION_RERUN
```

Staleness is orchestration state, not permission to mutate deployed assets. Re-execute from the
earliest stale phase under the existing ownership, idempotency, datatype-repair, and deployment
rules. If current catalog/API readback conflicts with the intended authority, HALT and return the
conflict to the owning stage; never delete or blindly recreate an asset merely because a checkpoint
is stale. After successful atomic output persistence plus fingerprint and phase-specific readback
verification, replace the current stale record with one new `VALID` record. Preserve prior record
history in Lakebase/events where available; `run_context.yaml` keeps only the current record.

Because the checkpoint envelope is frozen, a state-contract, producer instruction/control, or frozen
run-contract mismatch may be regenerated in the same run only after the exact frozen release bytes
are restored. If they are unavailable, keep the affected records `STALE`, HALT the resume, and start
a new versioned run under the new release; never rewrite the frozen envelope in place.

### Checkpoint Granularity

```text
Step level:  step_started → step_completed   (coarse — 6 per run)
Phase level: report_progress completed       (fine — 4-6 per step, ~30 per run)
```

Phases are the **resume and invalidation unit**. Steps are the **restart unit**.

---

## 2. Persistence Architecture

The master uses the release-selected WorkspaceStore and workspace lifecycle lock.
Persist phase records before progress events; verify frozen inputs and current
readbacks before reuse. In-memory App state is only a UI cache. Browser refresh or
worker replacement must resolve through the master rather than infer completion.

## 3. Optional telemetry

A host may mirror committed progress into Lakebase or another event store. Mirror
failures are diagnostic only. No table schema, HTTP endpoint, or provisioning step
is required by this portable prompt chain.

## 4. Resume Contract (LLM Behavior)

When a run resumes after interruption (refresh, crash, rerun), the system
provides `RESUME_CONTEXT` in the agent's system message.

### What the LLM receives:

```text
RESUME_CONTEXT:
  run_id: <uuid>
  checkpoint_contract_version: 1
  frozen_run_contract_sha256: <lowercase 64-hex>
  last_completed_step: create_metric_views
  last_completed_phase: validate_metric_views
  current_step: create_dashboards (restarting from beginning of step)
  checkpoint_records:
    - step: create_metric_views
      phase: validate_metric_views
      checkpoint_status: VALID
      producer_bundle_sha256: <lowercase 64-hex>
      input_fingerprints: <exact ordered list>
      output_fingerprints: <exact ordered list>
  stale_phases: []
  artifacts_written:
    - erd_parsed.yaml
    - schema_assumptions.yaml
    - semantic_model.yaml
    - data_layer_validation.yaml
    - {OUTPUT_FOLDER}/metric_views/schema_profile.yaml
    - {OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml
    - {OUTPUT_FOLDER}/metric_views/metric_view_design.yaml
    - {OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml
  prior_findings:
    - "8 tables created"
    - "3 metric views validated PASS"
    - "2 KPIs classified as NOT_IMPLEMENTED with reference SQL"
```

### What the LLM MUST do:

1. **BIND** the exact resolver-selected registry entry and its exact
   `run_context_path`; require the normalized parent directory to equal
   `run_context.output_folder`, and load `step_handoff.yaml` only from that exact sibling
   output folder. Reconcile the lifecycle identities above before using a checkpoint.
2. **RECOMPUTE** the frozen run-contract digest and current producer bundle before trusting any
   phase record. Treat `RESUME_CONTEXT` as a transport hint; the authenticated durable stores and
   current readbacks control.
3. **VERIFY** the exact reusable phase-record schema, complete mandatory input/output fingerprint
   sets, and every phase-specific authority check. Use one batched read/query where the owning
   prompt permits it.
4. If and only if the complete Resume Skip Gate passes, **SKIP** that phase and call
   `report_progress` with `status: "completed"` immediately to replay the checkpoint.
5. On a missing, malformed, incompatible, or mismatched checkpoint, mark the phase and all
   transitive dependents `STALE`, persist the invalidation, and re-execute from the earliest stale
   phase. If deployed readback conflicts, route to the owning stage; a downstream resume handler
   does not repair it.
6. **NEVER** re-execute a phase whose fingerprint gate and complete phase-specific verification
   both pass.

Before using any factual claim from a verified artifact, apply the G-3 authority row for
that fact. A completed checkpoint proves that the phase reported completion; it does not
override current catalog/API observation or a higher-authority intent artifact. If the
applicable authorities disagree, HALT the dependent work and report the conflict to the
owning stage.

### What the LLM MUST NOT do:

- Re-parse the ERD when the `parse_erd` fingerprint gate and structural verification pass
- Re-generate DDL when the `generate_ddl` fingerprint gate and exact target-identity readback pass
- Re-run schema reconciliation when the `reconcile_schema` fingerprint gate, authenticated
  `{OUTPUT_FOLDER}/schema_reconciliation.yaml`, and fresh exact name/type readback all pass
- Re-generate synthetic data when its fingerprint gate passes, its authenticated immediate
  `reconcile_schema` dependency remains valid, and every required table has rows
- Re-create Metric Views when their fingerprint gates and current catalog checks pass
- Re-create a dashboard when its fingerprint gate plus required Lakeview GET/name verification pass
- Re-create a Genie Space when its fingerprint gate plus required full GET/title verification pass

These prohibitions apply only after the phase-specific verification succeeds. A manifest
ID, final-manifest entry, or completed checkpoint by itself is not proof that the deployed
asset currently exists; it is locator or orchestration evidence. A deployment phase may be
skipped only when current catalog/API readback confirms the exact frozen identity, the phase's
required content/status checks pass, and all dependency fingerprints match. Whenever a stage
resolves or reports current deployed content, that readback controls. Any failed dependency gate
marks the phase and its transitive dependents `STALE` under this contract.

---

## 5. Artifact-as-State

Each phase produces durable orchestration evidence. The artifact records phase state, but
its individual claims retain the authorities assigned by G-3:

| Phase | Artifact | Verification |
|-------|----------|-------------|
| parse_erd | `erd_parsed.yaml` + `schema_assumptions.yaml` | post-production/resume check only: both exist; tables array non-empty; current digest-attested strict datatype validation PASS; assumptions policy/run/target/suffix and raw/resolved ERD hashes authenticate; zero unresolved datatypes. A fresh phase creates both outputs together and MUST NOT require either before its initial write |
| build_semantic_model | semantic_model.yaml | file exists |
| generate_ddl | authenticated parse assumptions dependency + `ddl_preflight.yaml` + tables in catalog | current-run preflight is `PASS`, authenticates assumptions digest, raw/resolved ERD and table-spec hashes, records any exceptional runtime-backstop resolutions and exact ERD-derived type regenerations, proves resolver idempotence, and precedes catalog mutation. A strict-valid ERD preserves the parse-owned assumptions bytes. If the runtime backstop mutates ERD/assumptions, the owning orchestrator refreshes the `parse_erd` output fingerprints/checkpoint before this phase becomes valid; after run_context/handoff parity, exact table identities from the resulting `table_spec.yaml` plus verbatim `step_handoff.asset_suffix` resolve by current catalog readback; this phase proves identity/existence only and does not claim deployed datatype reconciliation |
| reconcile_schema | `{OUTPUT_FOLDER}/schema_reconciliation.yaml` | current run/target/suffix; `producer_phase: reconcile_schema`; policy is `DEPLOYED_DATATYPE_REPAIR_V1`; `status: PASS`; exact ordered deployed name/type readback matches `table_spec.yaml`; expected/observed schema hashes match; zero unresolved mismatches |
| generate_synthetic_data | Row count > 0 plus authenticated reconciliation dependency | the immediate `reconcile_schema` phase remains reusable, its standalone artifact authenticates against a fresh exact name/type readback, and `SELECT COUNT(*) > 0` for each exact expected table |
| validate_data | data_layer_validation.yaml | current run/version; `overall_status: PASS`; authenticates both standalone assumptions and reconciliation artifact paths/hashes and embeds the same policy/status/hash/unresolved payloads without contradiction; zero unresolved datatypes or schema mismatches |
| profile_schema | `{OUTPUT_FOLDER}/metric_views/schema_profile.yaml` | file exists |
| map_kpis | kpi_metric_mapping.yaml | file exists |
| plan_metric_views | `{OUTPUT_FOLDER}/metric_views/metric_view_plan.yaml` | strategy-aware plan/handoff authentication below passes; ≥ 1 Metric View planned; capability tuple matches |
| design_metric_views | `{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml` | file exists |
| create_intermediate_views | Intermediate views in catalog | `SHOW VIEWS` returns expected intermediate view names (skip if none planned) |
| generate_metric_views | Metric views in catalog | `SHOW VIEWS` returns expected names |
| validate_metric_views | `{OUTPUT_FOLDER}/metric_views/metric_view_validation.yaml` | current-run `status: PASS` + exact planned/validated FQN parity + existing capability-contract parity gate passes |
| profile_metrics (Dashboard) | normalized Metric View readback used for dashboard design | current catalog readback still matches the complete authenticated input set |
| design_dashboard | dashboard_design.yaml | current-run bound; exact mapped-page inventory (or non-empty fallback) has `structural_status: PASS`; complete quality targets are recorded as `PASS|WARN` |
| build_datasets | dashboard_dataset_validation.yaml | complete frozen-dashboard inventory and all SQL/semantic checks PASS |
| create_dashboard | Exact dashboard manifest locator + matching per-dashboard validation | manifest contains the expected dashboard_id; matching validation binds the exact ID/name, has `source: api_readback`, records `overall_status: PASS`, `structural_status: PASS`, `page_contract_status: PASS`, and a valid quality/stage pair (`PASS/PASS` or `WARN/PARTIAL_SUCCESS`) |
| validate_publish | Official Lakeview readback + matching per-dashboard validation | exact identity/content/page-contract/published-state comparison passes; `UNKNOWN` cannot pass; a quality `WARN` remains reusable and does not become structural failure |
| profile_metrics (Genie) | genie_semantic_inventory.yaml | structurally valid and current catalog readback still matches |
| design_instructions | llm_genie_design.yaml | exact Genie quality tuple/effective-policy hash and instructions/questions meet all frozen gates |
| generate_sql | llm_genie_design.yaml plus executed SQL/benchmark evidence | exact quality tuple; every required example and benchmark fingerprint validates |
| create_genie_space | Exact Genie manifest locator + matching `{genie_title}_validation.yaml` | manifest contains the expected space_id; matching validation binds the exact ID/title, has `source: api_readback`, records the authenticated quality tuple and contract-selected accepted outcome/action/status, and full GET matches |
| validate_genie | `{genie_title}_validation.yaml` plus full GET | exact identity/content/count/quality-policy/outcome comparison passes |
| generate_documentation | `{OUTPUT_FOLDER}/documentation/readme.md` | current-run/path/scope-bound paired draft and README are structurally valid |
| validate_documentation | documentation/run_manifest_draft.json | canonical schema, placeholder scan, and authenticated evidence-scope checks pass |

Dashboard phase reusability is based on mandatory structural evidence, not on satisfying every
design-quality target. `quality_target_status: WARN` with `stage_status: PARTIAL_SUCCESS` remains a
valid reusable checkpoint when all structural/page/readback/publication gates and fingerprints
pass. A missing quality evaluation, a suppressed warning, an invalid status pair, or any structural
failure makes the owning phase stale or failed as applicable.

### Canonical Dependency and Invalidation Graph

The nodes below are exact reusable `phase` IDs in `run_context.phases_completed`; arrows mean
"is an immediate dependency of." Invalidate all reachable downstream nodes when a node or one of
its mandatory inputs becomes stale.

```text
create_data_layer:
  parse_erd → build_semantic_model → generate_ddl → reconcile_schema → generate_synthetic_data → validate_data

create_metric_views:
  authenticated validate_data or authenticated live-source binding
    → profile_schema (includes catalog cross-check)
    → map_kpis → plan_metric_views → design_metric_views
    → create_intermediate_views → generate_metric_views → validate_metric_views

create_dashboards:
  validate_metric_views → profile_metrics → design_dashboard → build_datasets
    → create_dashboard → validate_publish

create_genie_space:
  validate_metric_views → profile_metrics → design_instructions → generate_sql
    → create_genie_space → validate_genie

generate_documentation:
  authenticated ground-truth/stage evidence + current terminal cross-sweep
    → generate_documentation → validate_documentation
```

Dashboard and Genie are independent sibling branches: staleness in one does not invalidate the
other unless their shared Metric View dependency becomes stale. The master terminal cross-sweep is
not a reusable phase checkpoint; it always performs current readback and depends on every enabled
deployed validation. Documentation therefore becomes stale whenever its authenticated stage
evidence or current cross-sweep changes.

An ERD, KPI specification, live-schema discovery, capability contract, frozen helper/template, or
other external input is attached to the first phase that consumes it. Its digest change invalidates
that phase and cascades through this graph. A phase that consumes an additional upstream artifact
not pictured here records it as a direct input fingerprint and invalidates from that phase.

### Datatype Resolution Policy Fingerprints

The frozen ERD validation helper is a mandatory direct input to `parse_erd`; the frozen DDL template
is a mandatory direct input to `generate_ddl`. Both carry policy
`GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`, and release tests prove their platform defaults and
semantic scale map equal `contracts/datatype_resolution_policy.yaml`. The contract file is
release-governance evidence, not a mandatory `run_context.inputs` member. If an optional frozen
reference is present, authenticate it; if absent, continue with the already authenticated executable
artifacts. Never classify that absence as `DATA_LAYER_INPUT_AUTHORITY_ERROR`.

Record `schema_assumptions.yaml` as a `parse_erd` output fingerprint. Policy-ID, raw/resolved ERD
hash, or helper/runtime parity mismatch invalidates `parse_erd` and all transitive dependents. On a
fresh parse, `schema_assumptions.yaml` and resolved `erd_parsed.yaml` are outputs created together;
neither may be required to exist before that first write. Existing artifacts become authority only
for resume/cache verification after their producing phase completes.

### Genie Quality Policy Fingerprints

The exact raw bytes at `run_context.inputs.genie_quality_contract` and the canonical effective value
`{policy_id, thresholds, benchmark_outcomes}` are separate mandatory inputs. Record the source as
`RAW_BYTES` and the effective value as `CANONICAL_JSON`, using stable distinct IDs.

They are mandatory direct input fingerprints for `design_instructions`, `generate_sql`,
`create_genie_space`, and `validate_genie`. The design, benchmark evidence, validation artifact, and
manifest must echo the exact source tuple and effective-policy SHA-256 required by their owning
phase. If the Metric View stage produces the frozen sample-query file governed by
`min_sample_query_file_queries`, its `validate_metric_views` phase also fingerprints both policy
inputs and includes that file in its outputs. Documentation phases fingerprint both policy inputs
when they report Genie thresholds or outcomes.

A source-path/raw-hash, contract name/version/policy ID, effective threshold, outcome mapping, or
effective-policy hash mismatch invalidates the first affected phase and every transitive dependent.
Existence of an otherwise valid design, deployed space, README, or manifest never permits reuse
under a mismatched quality policy. No phase may reconstruct a missing value from prompt prose.

For every disabled stage among `create_data_layer`, `create_metric_views`, `create_dashboards`,
`create_genie_space`, and `generate_documentation`, require zero `phases_completed` entries whose
`step` names that stage. Represent the stage only as `SKIPPED` with no completed substeps; stale
phase or artifact presence never turns a disabled stage into completed work.

### Metric View Plan/Handoff Resume Authentication

The `plan_metric_views` phase is skippable only after authenticating the complete plan,
not merely finding the file or comparing counts. Parse the exact
`{run_context.output_folder}/metric_views/metric_view_plan.yaml` and its exact sibling
`step_handoff.yaml`, then apply the branch selected by the frozen
`run_context.assets.metric_view_strategy`.

This gate applies when the Metric View stage is enabled. A frozen disabled stage has no
`plan_metric_views` phase to skip and does not authorize any inferred Metric View identity.
It also requires the current-run Dashboard and Genie creation flags to be disabled, because those
stages require authenticated current-run Metric View plan, validation, and deployed-readback
evidence. A frozen explicit identity alone does not satisfy that dependency.

For both strategies:

1. Require one and only one `run_context.phases_completed` entry whose
   `step` is `create_metric_views` and whose `phase` is `plan_metric_views`. This phase
   entry has `checkpoint_status: VALID`, a non-empty `completed_at`, and passes the complete
   fingerprint Resume Skip Gate. This durable phase evidence is checked
   independently; a producer checkpoint cannot invent it.
2. Require the plan's top-level `run_id`, `asset_suffix`, and
   `metric_view_strategy` to equal the exact `run_context.yaml` and `step_handoff.yaml`
   bindings. This applies to both `auto` and `explicit`; the artifact path alone is not a
   current-run binding.
3. Require the plan's `capability_contract_name`, `capability_contract_version`, and
   lowercase 64-hex `capability_contract_sha256` to match the exact-byte resolved
   capability contract and the frozen run tuple. The name is exactly
   `metric_view_capabilities`.
4. Compare complete Metric View entries as
   `{name, normalized_sql_fqn, primary}`. Before computing `normalized_sql_fqn`, require every
   raw executable `sql_fqn` in the frozen run context, handoff, plan, and validation to contain
   exactly three separately backtick-quoted non-empty identifier segments, with no surrounding
   whitespace or trailing content. Remove the one required outer backtick pair per segment,
   unescape doubled backticks, apply Unicode `casefold()`, then join the three unquoted segments
   with `.`. Reject malformed quoting or any other transformation. Reject missing fields,
   duplicate names, duplicate normalized FQNs, or non-boolean `primary`; require target
   catalog/schema and exact asset-suffix parity; sort by
   `normalized_sql_fqn`, and require exact list equality. Counts or FQN-only equality
   are insufficient. Require exactly one `primary: true` entry.

When strategy is `auto`, require a top-level
`auto_handoff_producer_checkpoint` object in the plan with exactly these authenticated
fields (additional fields are invalid):

```yaml
auto_handoff_producer_checkpoint:
  producer_step: create_metric_views
  producer_phase: plan_metric_views
  status: PASS
  run_id: "<exact run_context.run_id>"
  asset_suffix: "<exact run_context.version.asset_suffix>"
  metric_view_strategy: auto
  step_handoff_path: "<exact normalized sibling step_handoff.yaml path>"
  step_handoff_sha256: "<sha256 of exact raw step_handoff.yaml bytes>"
  metric_view_plan_payload_sha256: "<canonical plan payload sha256>"
  metric_view_entries:
    - name: "<exact name>"
      normalized_sql_fqn: "<canonical three-part FQN>"
      primary: true
  capability_contract_version: "<exact approved contract version>"
  capability_contract_sha256: "<exact raw contract sha256>"
```

Require every stored digest to be exactly 64 lowercase hexadecimal characters. Recompute
`step_handoff_sha256` from the exact raw sibling handoff bytes. Recompute
`metric_view_plan_payload_sha256` by deep-copying the parsed plan, removing the entire top-level
`auto_handoff_producer_checkpoint` key, and hashing the UTF-8 bytes of:

```python
json.dumps(
    plan_without_auto_checkpoint,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
)
```

Require every `metric_view_entries[]` item to contain exactly `name`,
`normalized_sql_fqn`, and `primary`. Require every scalar above to equal the current run,
require the checkpoint entry list
to equal both the plan and handoff full-entry lists, and require its producer step/phase
to equal the independently completed phase. Any missing key, extra key, digest mismatch,
entry mismatch, path mismatch, capability mismatch, or phase mismatch is
`HANDOFF_AUTHORITY_ERROR`; do not skip or consume the auto-populated handoff.

When strategy is `explicit`, require the plan's top-level
`auto_handoff_producer_checkpoint` value to be explicit YAML `null`. Require the complete
plan entry list to match both the Step-0-frozen `run_context.assets.metric_views[]` list
and `step_handoff.metric_view_fqns[]`. A missing field, an empty/missing null key, an auto
checkpoint object, or any full-entry difference is `HANDOFF_AUTHORITY_ERROR`.

These strategy-specific checks authenticate Metric View identity in addition to the generic
fingerprint Resume Skip Gate. Failure makes `plan_metric_views` and its transitive dependents
`STALE`; the generic fields remain outside `auto_handoff_producer_checkpoint`.

---

## 6. Idempotency Rules

### CREATE IF NOT EXISTS semantics:

- **Tables**: `CREATE TABLE IF NOT EXISTS` is idempotent only after GATE 4.2 proves exact deployed name/type equality. A stale datatype may be repaired once only for an exact empty current-version generated target by compiler-driven drop/recreate; all unsafe cases halt without mutation.
- **Metric Views**: `CREATE OR REPLACE` (always safe to re-apply)
- **Dashboards**: Use the exact manifest `dashboard_id` only as a locator, confirm it by Lakeview GET, then update the confirmed asset
- **Genie Spaces**: Use the exact manifest `space_id` only as a locator, confirm it by full Genie GET, then update the confirmed asset
- **Files**: Always overwrite (`write_workspace_file` is idempotent)

### Row data:

- If table exists with rows > 0 → do NOT regenerate synthetic data
- If table exists with rows = 0 → regenerate

---

## 7. Progress Reporting as State Machine

Each phase follows this state machine:

```text
PENDING ── report_progress(started) ──► RUNNING
RUNNING ── persist outputs + fingerprints + report_progress(completed)
        ──► COMPLETED / checkpoint_status=VALID
VALID ── any compatibility, dependency, producer, or output mismatch
      ──► checkpoint_status=STALE ──► RUNNING (re-execute under ownership rules)

On failure: report_progress status="failed"
On resume: authenticate state, recompute fingerprints, then replay VALID or invalidate STALE
```

### report_progress Field Mapping to Lakebase

| report_progress field | Lakebase column | Table |
|---|---|---|
| phase_id | phases.phase_id | phases |
| phase_name | phases.phase_name | phases |
| status | phases.status | phases |
| current_task | phases.current_task | phases |
| progress_pct | phases.progress_pct | phases |
| stats | phases.stats (JSONB) | phases |
| happenings | phases.happenings (JSONB) | phases |
| findings | phases.findings (JSONB) | phases |
| checkpoint_contract_version | phases.checkpoint_contract_version | phases |
| checkpoint_status | phases.checkpoint_status | phases |
| producer_prompt_path/version/SHA-256 | matching producer columns | phases |
| producer_bundle_sha256 | phases.producer_bundle_sha256 | phases |
| frozen_run_contract_sha256 | phases.frozen_run_contract_sha256 | phases |
| input_fingerprints | phases.input_fingerprints (JSONB) | phases |
| output_fingerprints | phases.output_fingerprints (JSONB) | phases |
| invalidated_at / invalidation_reason | matching invalidation columns | phases |

---

## 8. Genie Code Compatibility

The artifact-as-state contract works **identically** in App mode and Genie Code.
Every host persists the same workspace contracts and uses the same resume gates.
Native progress tools are optional; a transcript event is sufficient after verified
workspace persistence. The master remains the orchestrator in every host.

### run_context.yaml — The Genie Code State File

At the start of each run, the LLM writes the canonical `run_context.yaml` defined by `00_master_prompt.md` in the output folder. That full file retains the nested, frozen resolved-configuration tree. Only its orchestration-state fields are updated at phase boundaries. It is not proof of deployed schema or asset state; those facts still require the catalog/API authorities defined by G-3.

The following is a **state-field excerpt**, not a replacement schema:

```yaml
# Written by the LLM at the start of a new run
# Updated at each phase boundary (report_progress completed)
run_id: "550e8400-e29b-41d4-a716-446655440000"
retry_attempt: 0              # only the locked failed-run reopen may increment this
domain:
  name: member_claims
version:
  number: 2                  # from version_registry.yaml resolution
  version_suffix: "_v2"
  short_name_suffix: ""
  asset_suffix: "_v2"
created_by: genie_code        # app | genie_code
started_at: "2024-01-15T10:00:00Z"
current_step: create_data_layer
status: running               # running | completed | partial_success | failed
completed_at: null
error: null
checkpointing:
  contract_version: 1
  canonicalization: CANONICAL_JSON_UTF8_SHA256_V1
  state_contract:
    path: "/Workspace/.../{AGENT_SKILLS_DIR}/prompts/shared/state_contract.md"
    sha256: "<lowercase 64-hex>"
  frozen_run_contract_sha256: "<lowercase 64-hex>"
  producer_bundles: "<complete frozen mapping defined in Section 1>"
phases_completed:
  - step: create_data_layer
    phase: parse_erd
    checkpoint_contract_version: 1
    checkpoint_status: VALID
    completed_at: "2024-01-15T10:02:30Z"
    invalidated_at: null
    invalidation_reason: null
    producer_prompt_path: "/Workspace/.../{AGENT_SKILLS_DIR}/prompts/data_layer/instructions.md"
    producer_prompt_version: 1
    producer_prompt_sha256: "<lowercase 64-hex>"
    producer_bundle_sha256: "<lowercase 64-hex>"
    frozen_run_contract_sha256: "<lowercase 64-hex>"
    input_fingerprints:
      - {id: erd_image, kind: RAW_BYTES, locator: "/Workspace/.../erd.png", sha256: "<lowercase 64-hex>"}
    output_fingerprints:
      - {id: erd_parsed, kind: CANONICAL_JSON, locator: "/Workspace/.../erd_parsed.yaml", sha256: "<lowercase 64-hex>"}
      - {id: schema_assumptions, kind: CANONICAL_JSON, locator: "/Workspace/.../schema_assumptions.yaml", sha256: "<lowercase 64-hex>"}
findings:
  - "8 tables created from ERD"
  - "All FK relationships validated"
```

### Genie Code Execution Flow

```text
1. User pastes step prompt (e.g., {AGENT_SKILLS_DIR}/prompts/data_layer/instructions.md)
2. LLM invokes the shared resolver once with the caller-supplied exact registry path;
   accelerator.yaml is request/drift evidence, not resume identity
3. Resolver returns either:
   a. NEW RUN: exact version/run_id/output_folder/run_context_path allocation owned by genie_code; or
   b. RESUME: one exact same-environment registry entry and its exact run_context_path
4. Require normalized parent(run_context_path) == run_context.output_folder, load
   step_handoff.yaml only as the exact sibling, and reconcile lifecycle identity
5. Recompute the frozen run contract, producer bundle, required dependency/output fingerprints,
   and each phase's complete authority/readback check
6. Skip only `VALID` phases that pass the full Resume Skip Gate; mark mismatches and transitive
   dependents `STALE`, then execute from the earliest stale or absent phase
7. After each reusable phase: atomically update `run_context.yaml` with its exact current record
8. After all phases: write the master-owned final manifest, then transition
   run_context.yaml and the exact registry entry to the mapped terminal state as one
   lifecycle operation; verify readback parity before reporting completion
```

### Genie Code Resume Flow (Same-Environment Only)

```text
1. User re-opens same step prompt (same or new conversation)
2. Shared resolver reads the exact caller-supplied registry path:
   - Selects one entry with created_by=genie_code AND status=running → RESUME
   - Returns that entry's exact run_context_path; do not construct a v{N} path
3. LLM reads only that registry-selected run_context.yaml:
   - Gets run_id (for traceability)
   - Gets phases_completed list
   - Gets current_step (where it was when interrupted)
4. LLM validates output-folder/sibling-handoff and lifecycle parity, recomputes the frozen contract
   and producer bundle, then applies the complete fingerprint and authority/readback gate
5. Skip only current `VALID` records; invalidate mismatches and transitive dependents, then resume
   from the earliest `STALE` or absent reusable phase
6. Atomically update `run_context.yaml` as each reusable phase completes
```

**Important:** If an App-created version is `running` in the registry, Genie Code
does NOT resume it. It creates a new version instead. The App's partial work stays
untouched for the App to resume later.

### Genie Code Multi-Step Continuation

When the user moves to the next step (e.g., from 01 to 02), the LLM:

1. Uses the shared resolver's exact registry path → selects its own running entry
2. Reads that entry's exact `run_context_path`; never reconstructs the output path
3. Verifies the EXISTING `run_context.yaml` and sibling handoff (carries the same run_id forward)
4. Upserts one exact fingerprinted current record per reusable phase as step 02 executes
5. Updates `current_step` to the new step name

This gives a continuous run_id across all steps in a single "run," even across
multiple Genie Code conversations.

### What report_progress Does in Genie Code

In App mode, `report_progress` may update the UI after the workspace checkpoint commit.
In Genie Code, `report_progress` has no backend listener — but the LLM still calls it because:

1. It serves as a **self-structuring checkpoint** (forces the LLM to think in phases)
2. The prompt contract says to call it (consistent behavior across environments)
3. The LLM atomically updates `run_context.yaml` with the exact fingerprinted record after each
   reusable phase

The acknowledged atomic `run_context.yaml` update containing the exact `VALID` phase record IS the
durable checkpoint in Genie Code.

### Genie Code State Recovery Route

Do not load operational recovery instructions during a normal run. If a user requests status or an
interrupted run must be recovered, authenticate `run_context.inputs.shared_runbooks.state_recovery`
and load only the matching section of `{AGENT_SKILLS_DIR}/prompts/shared/state_runbook.md`.

### Version Registry Integration

The `version_registry.yaml` (in the domain root, NOT inside a version folder) coordinates
version numbering across App and Genie Code. `00_master_prompt.md` owns the resolver route and
lifecycle gates; the release-owned shared resolver is the executable source of truth for the full
registry schema and selection algorithm.

**Key principle: Resume ONLY within the same environment.** The registry coordinates
version selection; it does not prove that versioned assets currently exist.
- App resumes App's incomplete runs. Genie Code resumes Genie Code's incomplete runs.
- Cross-environment always creates a NEW version (never resumes the other's partial work).
- A partial version from the other environment is NOT inconsistent — it's just incomplete,
  and can be resumed by its original environment later or cleaned up.

Key interaction with `run_context.yaml`:

```text
version_registry.yaml        run_context.yaml
(exact resolver input)       (exact registry-selected path)
┌───────────────────────┐  ┌───────────────────────┐
│ Which version to use?     │  │ Where inside that version   │
│ Resume MY v2 or create v3?│  │ to resume from?             │
│                           │  │                             │
│ Answers: version number,  │  │ Answers: run_id, current    │
│ who created, status       │  │ step, phases_completed      │
└───────────────────────┘  └───────────────────────┘
```

The resolution order on any run start:
1. Invoke the shared resolver with the exact caller-supplied registry path → determine version/run:
   - In auto mode, resume the highest-version authenticated `running` entry for MY
     `created_by`, even when a newer entry belongs to the other environment
   - In explicit retry mode, a same-owner `failed` entry resumes only after the locked
     failed-run reopen transition restores full `running` parity
   - Otherwise → create next version (max + 1)
2. Consume the resolver-selected exact `run_context_path`; do not derive it from N
3. Require parent/output-folder parity and load the exact sibling handoff
4. Reconcile lifecycle identity, then apply the fingerprint/authority gates → skip only current
   `VALID` phases that pass every check

---

## 9. Optional frontend state

A frontend may retain a run locator and display committed progress. The master
resolves and authenticates workspace state after refresh or restart.

## 10. Host integration

Invoke the same master prompt with the portable transport contract. Do not preselect
stages by file existence or mutate lifecycle records in a host event callback.

## 11. Critical Tool Failure Contract

Certain tool failures leave the system in an **inconsistent state** that downstream
phases cannot recover from. When these fail, you MUST halt immediately — do NOT
adapt, skip, or retry with alternative approaches.

### Critical Tools (single failure = HALT)

| Tool | Why Critical | Exception |
|------|-------------|----------|
| `execute_sql` | DDL/DML creates schemas, tables, views | SELECT/SHOW/DESCRIBE are non-critical (read-only) |
| `execute_python` | Generates YAML artifacts and configs needed downstream | — |
| `execute_notebook` | ETL/data generation notebooks produce required data | Only the authenticated pre-mutation DDL-preflight route defined below |
| `create_notebook` | Can't create = can't execute = missing output | — |
| `write_file` | Produces artifacts that later phases depend on | — |
| `create_dashboard` | Step's primary deliverable | — |
| `create_genie_space` | Step's primary deliverable | — |

### Critical Error Patterns (any tool = HALT)

- `PermissionDenied` or `PERMISSION_DENIED`
- `RESOURCE_EXHAUSTED` or `QUOTA_EXCEEDED`
- `INTERNAL_ERROR` (server-side failure)

### On Critical Failure

**Narrow pre-mutation DDL-preflight exception:** datatype-only defects should be resolved before
execution by the parse gate and the notebook's defense-in-depth resolver. Before applying the
terminal steps below, inspect `{OUTPUT_FOLDER}/schema_assumptions.yaml` and
`{OUTPUT_FOLDER}/ddl_preflight.yaml` only when the DDL notebook error begins with exactly
`ERD_EXTRACTION_ERROR:` or `SCHEMA_CONTRACT_ERROR:`. Targeted routing is permitted only when both
artifacts authenticate the current run/target/suffix, assumptions policy, raw/resolved ERD hashes,
and table-spec hashes; preflight has `status: FAIL`, the same `failure_code`, and
`catalog_mutation_started: false`. An eligible datatype-only extraction error permits the remaining
bounded evidence reparses followed by the pinned resolver; a structural extraction error does not.
`SCHEMA_CONTRACT_ERROR` permits one deterministic table-spec regeneration from the resolved ERD.
Redeploy and execute only after assumptions authentication and GATE 4.0 PASS. Missing, malformed,
stale, contradictory, ineligible, exhausted, or post-mutation evidence falls through to terminal
critical-failure rules.

1. **DO NOT** call the next phase's tools
2. **DO NOT** attempt alternative approaches to work around the failure
3. **DO** call `report_progress(status="failed", ...)` with the error details
4. **DO** call `report_step_complete(status="failed", summary="Critical failure in {tool}: {error}")` 
5. **DO** invoke the master-owned all-store terminal-failure transaction for the exact run: write
   the canonical failed final manifest, update the selected `run_context.yaml`, update the exact
   registry entry; then re-read every workspace
   participating store and require the full lifecycle tuple to agree on `failed`. The progress and
   step-complete calls are failure inputs, not a committed terminal transition by themselves. Never
   write only `run_context.status` or only registry status; do not alter frozen resolved configuration.

In App mode, the failed progress/step calls persist phase/step failure evidence only; they MUST NOT
change the top-level Lakebase run lifecycle status ahead of the all-store terminal transaction.

This rule applies **identically in App mode and Genie Code**. In App mode,
the agent loop enforces it programmatically. In Genie Code, the LLM must
self-enforce by following this contract.

### Non-Critical Failures (adapt allowed)

- `read_file` returning "file not found" (legitimate check-before-create)
- `execute_sql` with SELECT/SHOW/DESCRIBE (informational queries)
- Display/telemetry failure is cosmetic after the verified workspace checkpoint commit. A failed workspace checkpoint write is state-critical in every host.
- `describe_table` failing (table may not exist yet)

For non-critical failures: retry once, then adapt or skip.

---

## 12. Non-Negotiable Rules

1. **A completed checkpoint requires verified workspace persistence.** A progress call alone is insufficient in every host.
2. **Existence is not freshness.** Skip only a current `VALID` record whose complete fingerprint and phase-specific gates pass.
3. **Invalidate transitively.** A missing, incompatible, or mismatched dependency makes the owning phase and every graph-dependent phase `STALE` before regeneration.
4. **Workspace contracts govern lifecycle and checkpoint records.**
   In-memory state is a cache; domain and deployed facts follow G-3.
5. **Block on required workspace persistence failure.** Optional telemetry never blocks execution.
6. **Same behavior in App and Genie Code.** State is environment-agnostic.
7. **Tool calls are persisted for debuggability.** All calls, not just failures.
8. **TTL cleanup at 30 days.** Tool calls and events are transient diagnostic data.
9. **Steps restart through the phase graph.** Reuse valid prefix phases and execute from the earliest stale or absent reusable phase.
10. **run_id survives browser refresh.** URL query param is the primary mechanism.
11. **Critical tool failures halt immediately.** See Section 11 above.
12. **Lifecycle identity is reconciled before resume or terminal reporting.** Registry,
    run context, and final manifest retain their field-scoped roles.
13. **`abandoned` is read-only legacy compatibility recognized by the shared resolver only
    for a pre-contract orphan.** No current writer creates it; contract-bound unsuccessful
    runs use `failed`.
14. **Metric View plan resume is strategy-aware.** Auto requires the authenticated full
    producer checkpoint; explicit requires that checkpoint to be exactly null.
15. **Generic and strategy-specific checkpoints stay separate.** The Metric View auto-handoff
    checkpoint never receives generic phase-record fields.

---

## 13. Alignment with Prompt Enforcement Headers

Each stage's `instructions.md` contains an `<!-- @enforcement -->` header and its always-loaded
`validation.md` contains the expanded GATE checks. These gates are the **artifact verification
points** for this state contract:

| Step | GATE ID | Artifact Check | Maps to Phase |
|------|---------|----------------|---------------|
| 01 | `erd_parsed_exists` | `erd_parsed.yaml` and authenticated `schema_assumptions.yaml` exist; strict datatype validation passes; zero unresolved datatypes | parse_erd |
| 01 | `ddl_notebook_executed` | exact expected table identities resolve in the frozen target namespace | generate_ddl |
| 01 | `schema_reconciled` | authenticated `{OUTPUT_FOLDER}/schema_reconciliation.yaml` has current-run policy `DEPLOYED_DATATYPE_REPAIR_V1`, `status: PASS`, exact fresh schema equality, and zero unresolved mismatches | reconcile_schema |
| 01 | `synthetic_data_populated` | immediate `reconcile_schema` dependency remains valid and COUNT(*) > 0 per exact expected table | generate_synthetic_data |
| 01 | `validation_passed` | current-run data_layer_validation.yaml has `overall_status: PASS` and authenticates the same standalone assumptions and reconciliation artifacts | validate_data |
| 02 | `schema_profiled` | `{OUTPUT_FOLDER}/metric_views/schema_profile.yaml` exists | profile_schema |
| 02 | `profile_cross_checked` | All profile columns verified against catalog via DESCRIBE TABLE (GATE 2.2) | profile_schema |
| 02 | `kpi_mapped` | kpi_metric_mapping.yaml exists | map_kpis |
| 02 | `metric_view_plan_authenticated` | strategy-aware full-entry/capability/checkpoint/hash/phase verification in Section 5 passes | plan_metric_views |
| 02 | `design_validated` | `{OUTPUT_FOLDER}/metric_views/metric_view_design.yaml` exists | design_metric_views |
| 02 | `metric_view_created` | exact expected handoff Metric View FQN set resolves by catalog readback | generate_metric_views |
| 03 | `design_contract_exists` | dashboard_design.yaml exists, preserves the exact mapped-page inventory or non-empty fallback, and records complete PASS/WARN quality-target evaluation | design_dashboard |
| 03 | `datasets_validated` | dashboard_dataset_validation.yaml records all frozen-dashboard datasets `PASS` | build_datasets |
| 03 | `dashboards_created` | exact locator per frozen dashboard + matching Lakeview-readback structural/page-contract `PASS` and valid quality/stage outcome | create_dashboard |
| 03 | `dashboards_published` | official publication-state readback confirms published; `UNKNOWN` cannot pass | validate_publish |
| 04 | `genie_space_created` | exact manifest locator + matching full-GET `{genie_title}_validation.yaml` binds ID/title and has `overall_status: PASS` | create_genie_space |

GATE checks in stage instructions and validation contracts are the phase-specific portion of artifact-as-state resume verification;
the fingerprint Resume Skip Gate is additionally mandatory. Together they serve double duty:
1. During fresh execution: enforce ordering (no skipping ahead)
2. During resume: determine which phases are already complete

They do not alter the canonical authority for the fact being checked. In particular,
checkpoint status cannot replace required catalog or official API readback.

The `PROHIBITED ACTIONS` blocks in each stage instructions/guardrails pair prevent bypassing these
artifacts (e.g., running inline code instead of creating notebooks, skipping dataset
validation before dashboard creation).
