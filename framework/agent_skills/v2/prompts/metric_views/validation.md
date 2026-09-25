# Metric Views — Validation Contract

> **Always loaded.** This file owns executable gates and evidence requirements for `create_metric_views`. Operational history is intentionally excluded.

## Shared deployment boundary

Before importing any deployment notebook, apply `prepare_template_bindings` from the
frozen shared `agent_transport.md` to the exact template and complete logical values.
First apply this stage's authority/binding gates. Pass the resulting substitution strings
unchanged to the host deployment operation, and inspect its acknowledgement before
execution. Examples using lists/dicts require this conversion; do not send raw containers
or JSON booleans into Python slots. No code-cell rewriting is allowed.

## Gates

### GATE 8.SPEC-IO: Spec handoff before notebook submission (MV-G1)

Read the exact canonical spec path through workspace tools/SDK after its producer
write. Require nonempty raw bytes, a YAML mapping with a nonempty `metric_views`
list, and exact planned/handoff name coverage. Authenticate the producer checkpoint
and spec digest before deployment. Verify OUTPUT_FOLDER equals the authenticated
run root so the template appends `/metric_views/metric_view_spec.yaml` only once.

The notebook must complete the SDK input read and structural checks before any
Metric View mutation. Missing input is `METRIC_VIEW_INPUT_NOT_FOUND`; return it to
spec generation without querying other output versions. Preserve permission errors
as such. Manifest writes must use RAW format and exact byte readback; failure is
`METRIC_VIEW_OUTPUT_READBACK_ERROR` and cannot be acknowledged as completion.

### GATE 2.1: Schema Profile Exists
`schema_profile.yaml` must exist. HALT if missing.

### GATE 2.5: Relationship Verification
Relationship verification completed for all `semantic_model.yaml` relationships.

### GATE 2.6: Input Authority Reconciliation (MANDATORY)
Apply global G-3 by field. `semantic_model.yaml` supplies relationship/grain intent, while matching `data_layer_validation.yaml` relationship rows with `validation_status: PASS` supply upstream deployed-data evidence. `table_spec.yaml` supplies expected generated schema, while current `DESCRIBE TABLE` readback supplies observed deployed columns and types.

HALT with `METRIC_VIEW_INPUT_AUTHORITY_ERROR` if a required authority is missing, stale, belongs to another run/version, or conflicts with its paired expected/readback source. Preserve both sides of a conflict; do not rewrite the intent artifact or silently adapt the Metric View plan.

### GATE 3.0: Capability Contract Resolution (MANDATORY)
Load the exact frozen `run_context.inputs.metric_view_capabilities` path before capability classification. HALT with `CAPABILITY_CONTRACT_MISSING` if absent. HALT with `CAPABILITY_CONTRACT_INVALID` unless it parses; `contract.name == metric_view_capabilities`; `contract.status == APPROVED`; all required fields and enum values are known; and the configured execution target resolves to `SATISFIED`.

Compute SHA-256 over the exact raw file bytes and pin the immutable `capability_contract_name`, `capability_contract_version`, and `capability_contract_sha256` tuple. Copy the exact bytes to `{OUTPUT_FOLDER}/metric_views/resolved_metric_view_capabilities.yaml`. If the release package provides a trusted digest, verify it. The same version with a different digest is `CAPABILITY_CONTRACT_MUTATED`; HALT. A changed digest under a new version makes capability-dependent artifacts stale.

Runtime review expiry follows the pinned contract policy and never authorizes a live-document override.

### GATE 4.1: KPI Metric Mapping Exists
`kpi_metric_mapping.yaml` must exist. HALT if missing.

### GATE 4.2: KPI Enumeration Completeness (MANDATORY)
Compare normalized unique KPI-ID sets between the KPI specification and `kpi_metric_mapping.yaml`. HALT and report missing, unexpected, or duplicate IDs unless the sets match exactly. Counts alone are insufficient.

### GATE 4.3: Capability Resolution and No Premature NOT_IMPLEMENTED (MANDATORY)
Step 4 mapping may use only `READY`, `UNSUPPORTED`, `AMBIGUOUS`, or `UNSAFE`. Here, `UNSUPPORTED` means physically or business-unmappable; it is not a platform-capability verdict. `NOT_IMPLEMENTED` is introduced only in Step 4.5.

At Step 4.5, enumerate every `required_capability` by its exact contract key and resolve in this order:

1. If the key is absent, any required value is unknown, or execution-target requirements cannot be evaluated, HALT with `CAPABILITY_NOT_RESOLVED`.
2. If platform support is `SUPPORTED`, accelerator validation is `VALIDATED`, `enabled` is true, and target requirements are satisfied, use the native capability.
3. Otherwise, apply the contract-declared fallback. Resolve any capabilities required by that fallback and run every required safety and semantic-equivalence check.
4. If the fallback preserves the KPI definition and passes validation, keep the KPI `READY`/implemented and record `fallback_applied`; do not use `NOT_IMPLEMENTED`.
5. Unsafe data or relationships use a specific `SKIPPED_*` status with `constraint_scope: DATA`.
6. `NOT_IMPLEMENTED` is allowed only when the capability is present and resolved, native use is disallowed, and no applicable semantics-preserving fallback succeeds.

Every `NOT_IMPLEMENTED` entry must include complete KPI/physical mapping, validated reference SQL, `constraint_scope` (`PLATFORM` or `ACCELERATOR`), exact `required_capability`, the resolved contract tuple, native decision evidence, fallback considered, and rejection reason. Do not describe an accelerator-disabled feature as unsupported by Databricks.

Different grain alone is not a capability failure. An incompatible or unsafe cross-grain relationship uses a specific `SKIPPED_*` status.

**INVALID reasons at Step 4:**
- "Only 1 KPI for this grain" — a single KPI justifies a metric view if it belongs to a distinct valid grain
- "Enrollment grain — single KPI insufficient for MV" — grain validity, not KPI count, controls planning

### GATE 4.5: Multi-Grain Analysis Verification (MANDATORY)
Group all READY KPIs by normalized required grain. Verify every distinct valid grain containing at least one READY KPI has a planned metric view. Compare grain identities, not raw fact-table counts: multiple tables can participate in one validated grain, while one table can support more than one semantic grain. HALT and re-plan when any READY grain is missing.

### GATE 5.7: Planned-vs-Created Metric View Parity (MANDATORY)
```
each source list has no duplicate normalized FQNs
AND
set(normalized metric_view_plan sql_fqns)
  == set(normalized metric_view_validation sql_fqns)
  == set(normalized step_handoff metric_view_fqns)
```
Every implemented KPI must also appear exactly once in the planned metric view. Hard FAIL on missing/unexpected FQNs or KPI-assignment mismatch. Equal counts alone are insufficient.

### GATE 6.1: Metric View Design Exists
`metric_view_design.yaml` must exist with all joins validated. HALT if missing.

### GATE 7.5: Intermediate Views Exist
All planned intermediate views must exist in catalog. HALT if any are missing.

### GATE 8.1: Metric View Exists in Catalog
Every normalized `sql_fqn` in `metric_view_plan.yaml` must exist in the catalog. Report the exact missing FQNs and HALT if any are absent.

### GATE 8.2: Metric View Queryable
`SELECT MEASURE(first_measure) FROM mv LIMIT 1` must succeed.

### GATE 10.1: Validation Artifact Exists
`metric_view_validation.yaml` must exist. HALT if missing.

### GATE 10.2: Capability Evidence Parity (MANDATORY)
Recompute the raw-byte contract SHA-256 and verify that `metric_view_plan.yaml`, `metric_view_validation.yaml`, and `metric_view_manifest.json` contain the same contract name/version/hash tuple. Verify every KPI's required capabilities, native/fallback decision, constraint scope, and final status agree between plan and validation. HALT on missing evidence, hash mismatch, duplicate normalized FQNs, or decision drift.

---

## Failure-Only Runbook Routing Index

| Runbook section | Load only when observed evidence matches |
|---|---|
| `AP-MV-1` | Single Metric View When 2 Grains Exist |
| `AP-MV-2` | Column Name Mismatch |
| `AP-MV-4` | UNRESOLVED_COLUMN in Metric View Deployment |
| `AP-MV-3` | Premature NOT_IMPLEMENTED |
| `AP-MV-5` | Disabled Native Feature Without Fallback Evaluation |
| `AP-MV-6` | Capability Contract Drift on Resume |
| `AP-MV-7` | Join Entry Missing single-quoted `'on'` Field |

Classify the failure from current evidence before loading a runbook section. The index is a routing aid, not authority to bypass the stage owner or retry policy.
