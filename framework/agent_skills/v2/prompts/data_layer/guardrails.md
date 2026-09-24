# Data Layer — Guardrails

> **Always loaded.** This file contains normative prohibitions and hard stops for `create_data_layer`. Historical incidents and fixes live only in the failure runbook.

## Shared rules

Use `../shared/global_guardrails.md` G-0 for prompt/runtime ownership, G-8 for
workspace transport, G-12 for bootstrap acknowledgement, and G-19 for checkpoint
and progress integrity. Data-layer-specific policies remain in this file below.

## Prohibited Actions

1. DO NOT skip ERD parsing by using a cached/assumed schema
2. DO NOT modify column names or constraints from the ERD; datatype-only resolution is permitted solely by `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1` in its eligible scope and must be disclosed in `schema_assumptions.yaml`
3. DO NOT create tables outside the configured catalog.schema
4. DO NOT use `DROP TABLE` on source tables
5. DO NOT proceed past a GATE without verifying the condition
6. DO NOT use generic column names (`col1`, `col2`, `value`)
7. DO NOT skip validation of generated synthetic data
8. DO NOT use `CTAS` (CREATE TABLE AS SELECT) for DDL — use explicit `CREATE TABLE` with column definitions
9. DO NOT invent new tables not in the ERD
10. DO NOT add columns beyond what the ERD specifies
11. DO NOT skip the vision model step if an ERD image is provided
12. DO NOT assume column types from names ad hoc — exact ERD evidence and semantic-peer evidence take precedence; column-name semantics may be used only by the pinned greenfield-synthetic resolver and must be labeled `INFERRED_POLICY`
13. DO NOT skip schema reconciliation (GATE 4.2)
14. DO NOT use unquoted numeric values for STRING/VARCHAR columns in synthetic_data_spec.yaml
15. DO NOT generate data without calling `validate_domain_cols()` first (DETERMINISM GATE)
16. DO NOT generate data without calling `validate_fk_replacements()` for FK columns (DETERMINISM GATE)
17. DO NOT use generic placeholder values (`val_1` through `val_5`) for categorical columns
18. DO NOT skip the Domain Value Inference Protocol for categorical columns
19. DO NOT write the data generation notebook without the safety utilities from `dbldatagen_notebook.py.template`
20. DO NOT execute data generation without `verify_before_write()` pre-write validation
21. DO NOT skip the `enforce_varchar_limits()` truncation safety net
22. Use the pinned DDL compiler for identifier quoting and comma placement. Quoting cannot legalize an invalid Unity Catalog object name; apply DL-G1 below.
23. DO NOT omit commas between column definitions
25. DO NOT omit `pk_columns` for ANY dimension/lookup table in `synthetic_data_spec.yaml` — this causes join fanout (AP-DL-7)
26. DO NOT proceed past validation check 7.7 (join cardinality) if `after_rows > before_rows` — dimension PK uniqueness must be fixed first
24. DO NOT generate the DDL notebook from scratch — always use `ddl_notebook.py.template` with resolved placeholders. The template is a tested Python notebook; the LLM writing its own version introduces syntax bugs (wrong SHOW TABLES wildcards, SQL/Python format mismatches, missing commas) that the template eliminates — every column definition MUST end with a comma except the LAST column before the closing parenthesis. Missing commas are the #1 cause of DDL PARSE_SYNTAX_ERROR
27. DO NOT silently accept schema drift after DDL — `DESCRIBE TABLE` must match `table_spec.yaml`; never skip an expected column or generate an unexpected deployed column with defaults
28. DO NOT treat a relationship in `semantic_model.yaml` as validated — downstream use requires its matching relationship-level `data_layer_validation.yaml` entry to be `PASS`
29. DO NOT recompute catalog, schema, asset/version suffixes, output folder, or paths from `accelerator.yaml`; use the current-run resolved configuration/handoff and halt on conflict
30. DO NOT make unrecorded datatype repairs. Perform up to two authoritative reparses first. Only an ERD-driven target with `greenfield.enabled: true` and `greenfield.synthetic_data: true` may use `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`; source/live schemas, retained data, and structural loss remain hard stops
31. DO NOT generate or insert synthetic data unless the current-run `reconcile_schema` phase is VALID, `{OUTPUT_FOLDER}/schema_reconciliation.yaml` authenticates with `status: PASS` and zero unresolved mismatches, and a fresh exact name/type readback still matches `table_spec.yaml`
32. DO NOT treat final `data_layer_validation.yaml` as a substitute for the pre-generation reconciliation artifact; final validation must authenticate and preserve the same reconciliation evidence
33. DO NOT accept or copy a prior-version `erd_parsed.yaml` using only image-hash equality and non-empty tables. Revalidate it with the current digest-attested helper. If legacy assumptions evidence is absent, create a new current-run `schema_assumptions.yaml` from the validated/resolved in-memory candidate rather than treating the missing generated output as input-authority failure. Existing current-contract assumptions, when present, must authenticate
34. DO NOT deploy or execute the DDL notebook until programmatic GATE 4.0 authenticates `schema_assumptions.yaml` and proves that `table_spec.yaml` is an exact projection of the resolved `erd_parsed.yaml`
35. DO NOT treat governed pre-DDL resolution as permission to widen, cast, or adopt a catalog datatype; catalog state is never inference evidence. Record policy decisions in `schema_assumptions.yaml`, derived type replacements in `ddl_preflight.yaml`, and rerun exact projection validation
36. DO NOT retry a failed DDL notebook unless authenticated `ddl_preflight.yaml` proves the failure occurred before any catalog mutation and selects the exact bounded ERD-reparse or table-spec-regeneration route

---

## Prohibited Value Patterns (GATE 5.1 rejects these)

```text
val_1, val_2, val_3, val_4, val_5           — generic placeholders
type_1, type_2, type_3                       — generic type names
category_a, category_b                       — generic categories
status_1, active, inactive (for non-status)  — wrong domain
```

## Prohibited Column Name Patterns

```text
table_name_column_name   — concatenated table+column
original_source_column   — source system prefix
any column not in ERD    — invented columns
```

---


## DL-G1: Source labels and generated target identifiers

For greenfield generated targets, `tables[].name` is one unqualified physical
table-name component, not a source-schema-qualified label or SQL FQN. Catalog and
schema come separately from the frozen handoff. Unity Catalog forbids periods
inside an object name, even when quoted.

The agent interprets source labels using the ERD and domain context, preserves the
original label as `source_name`, and resolves a legal target name before completing
the parse. Preserve namespace information in provenance; choose a collision-free,
descriptive unqualified name. Do not blindly strip prefixes or globally replace
punctuation. For example, `dim_provider` is a possible mapping for `dim.provider`,
not a mandated name or domain default. Record source→target mappings and rationale
in the parse artifact. Ask for clarification if evidence cannot distinguish entities.

Apply this mapping to every relationship endpoint and downstream semantic, table,
synthetic-data, and KPI reference, before datatype-assumption hashes and checkpoints
are created. `table_spec.yaml` remains an exact projection of the resolved parse.
Never rename only inside DDL or silently repair frozen inputs. Existing live-source
objects remain unchanged; represent their catalog/schema/table components separately.

Reject period, space, slash, ASCII control characters, DEL, and embedded backticks
in generated table-name components. Validate final names including the asset suffix
against the 255-character limit and detect collisions ignoring case. Execute the
pinned DDL template's pure `validate_uc_target_names(catalog, schema, tables,
asset_suffix)` before deployment. The notebook repeats it before catalog mutation.
`GENERATED_IDENTIFIER_ERROR` belongs to parse/name resolution, not datatype repair.
Return it to that owning phase; invalidate dependent fingerprints and regenerate
the consistent contracts before retrying. If prior catalog mutations or frozen
contracts prevent safe regeneration, use a fresh version rather than renaming
deployed objects or substituting names inside executable SQL.

## DL-G2: Executable synthetic-data specification

The following column-level strategy notes are planning metadata. They are **not**
the executable notebook input schema. Write `synthetic_data_spec.yaml` using this
exact table-level structure (logical table names without the asset suffix):

```yaml
tables:
  - name: dim_member
    rows: 100
    pk_columns: [member_id]
    date_range: ["2020-01-01", "2024-12-31"]
    domain_columns:
      status:
        values: ["Active", "Inactive"]
        weights: [0.8, 0.2]
    fk_columns: {}
  - name: fact_claim
    rows: 500
    pk_columns: [claim_id]
    domain_columns: {}
    fk_columns:
      member_id:
        parent_table: dim_member
        parent_pk: member_id
```

Use the actual authenticated names, rows, domains, and relationships for this run.
`parent_pk` is mandatory; do not substitute `parent_column`, `referenced_column`, or
other aliases, and never infer a missing key from the child column's name. Both
columns must match the reconciled deployed schema. Parents precede children. The
legacy `pk_columns` field controls independently unique generated columns: the
runtime generates each listed column uniquely. It is NOT a declaration that those
columns form one composite database primary key. Include the semantic primary key
and each authenticated single-column parent reference needing unique generation.
`parent_pk` names that exact referenced column, which may be an alternate/business
key. Preserve the true primary key and relationship grain in the semantic model;
never replace an alternate reference with a surrogate merely to pass preflight.

The sampler checks actual parent values for nonempty, nonnull, independent uniqueness
before sampling. It must not hide duplicates with DISTINCT. Multiple unique columns
are supported. A genuine multi-column relationship cannot be split into independent
scalar mappings: return an explicit tuple-generation capability error before deployment.
Cycles remain unsupported. No domain-specific key names or fallback substitutions
are permitted.

Before notebook deployment, run the exact frozen template's
`validate_synthetic_spec(spec, table_spec_tables)` against the **entire** spec using
the attested template bytes (extract that pure function with Python AST after
excluding notebook `%` magic lines).
The notebook repeats this check before the first data write. A preflight failure
returns to this spec-generation phase; fix the owned spec before execution.
Never blindly retry an append notebook after a partial write: inspect target row
counts and use a fresh version when existing rows prevent safe execution.

## DL-G3: Data-layer phase ordering

The phases are sequential: `generate_ddl` → `reconcile_schema` →
`generate_synthetic_data`. Wait for each notebook's terminal success, complete its
readback and workspace checkpoint commit, and emit its completed event before
starting the next phase. Never submit these notebooks concurrently. A missing
completion event is not proof of success and must not be bypassed.

Apply shared G-19 for checkpoint and progress-event integrity. On premature
synthetic-data admission, return control to the master and authenticate the DDL and
reconciliation checkpoints before any generation. UI labels alone never permit reuse.


## DL-G4: DDL and synthetic notebook placeholder binding

Apply shared G-16. Read the exact frozen template and enumerate its placeholders;
do not reuse the Metric View placeholder map. Bind TARGET_CATALOG and TARGET_SCHEMA
from the authenticated handoff's target catalog/schema for the current DDL and
synthetic templates. These interface keys differ from the Metric View template's
CATALOG and SCHEMA. No value may be missing, null, or empty. The template's actual
interface is authoritative; examples do not replace inspecting it.

Bind the current interfaces using this source map after authenticating both files:

| Template field | Persisted source |
|---|---|
| DOMAIN_NAME | `run_context.domain.name` |
| OUTPUT_FOLDER | `step_handoff.output_folder` |
| TARGET_CATALOG | `step_handoff.catalog` |
| TARGET_SCHEMA | `step_handoff.schema` |
| ASSET_SUFFIX (synthetic template) | `step_handoff.asset_suffix` |

`ASSET_SUFFIX` must be a nonempty string equal to
`run_context.version.asset_suffix`. It is distinct from `short_name_suffix`, which
may be empty. Never substitute that field, derive a suffix from the folder/version,
add a default, or silently repair persisted identity. A missing/empty/conflicting
persisted asset suffix is `HANDOFF_AUTHORITY_ERROR`: halt and return to the master.
If the persisted suffix is valid but the proposed binding omitted it, construct the
complete map from the authenticated files before calling deployment. Run executable
GATE TEMPLATE-BINDING separately for each template; the DDL map is not the synthetic
map. Reading template bytes to inspect placeholders is permitted; rewriting cells
is not. No App state or Lakebase lookup is needed for these bindings.

Template deployment failure blocks generate_ddl or generate_synthetic_data and
therefore blocks Metric Views. Require a successful import, terminal notebook
success, and the phase's catalog/checkpoint validation before releasing consumers.


## DL-G5: ERD-to-table-spec datatype projection

ERD columns use `tables[].observed.columns[].datatype`; DDL columns use
`tables[].columns[].type`. These are different artifact interfaces. Copy the exact
validated/resolved ERD datatype into `type`; copying observed column dictionaries
unchanged, looking up ERD `type`, or writing only a `datatype` key is invalid.
Do not supply default STRING/BIGINT types or infer from column names here.

Before deploying DDL, execute GATE 4.0's bounded projection in `validation.md`.
With exact ordered table/column identity, regenerate derived types from the resolved
ERD, record every replacement, then validate. This is allowed pre-deployment artifact
construction, not permission to change an ERD or deployed table. Never raise the
initial repairable projection report before performing this owned correction: in the
App an execute_python exception terminates the master. Structural mismatch or invalid
ERD datatype still halts and returns to its existing owner. Never catch unrelated
SDK, permission, or runtime failures as a projection repair.


## DL-G6: Reconciliation producer provenance

`schema_reconciliation.yaml` is owned by the exact frozen DDL runtime. The agent
reads/authenticates it and commits its checkpoint; it must not summarize, reconstruct,
or overwrite that file from SQL results or progress text. Required producer metadata:
`artifact_type: schema_reconciliation`, `contract_version: 1`,
`producer_step: create_data_layer`, `producer_phase: reconcile_schema`.
These fields are mandatory, including during checkpoint-only recovery. The limited
legacy exception for catalog/schema/output_folder does not apply to provenance.

Execute GATE RECONCILIATION-PROVENANCE before committing reconcile_schema VALID and
again before synthetic deployment. Missing provenance is an invalid producer artifact,
not a missing checkpoint. Do not insert constants into an existing file to manufacture
provenance or merely update its hash. Authenticate the frozen DDL template, executed
notebook and producer result, and exact artifact path to determine whether the runtime
is outdated or its output was replaced. Return to the master for producer recovery;
any DDL rerun remains subject to existing ownership, data-retention, and lifecycle gates.


### DL-G6 diagnostic capture for producer discrepancies

Before and after each operation that can produce or replace reconciliation evidence,
record the current artifact's raw SHA-256, exact path, canonical run ID, operation,
notebook path and Jobs run ID when applicable. Preserve changed before/after bytes
under the current run's `diagnostics/reconciliation/` directory; never overwrite the
canonical artifact to collect evidence. Record the frozen template SHA-256, rendered
notebook source SHA-256, and pre-execution exported source SHA-256 with their respective
operations. Export normalization may affect source hashes; inspect differences before
attributing them to a different notebook. Capture errors as unknown, never as absence.

The App transport captures this timeline after an authenticated selection or deployment
context read. On other hosts use the same evidence fields through the approved Workspace
transport and notebook runner. This is diagnostic evidence, not an alternate checkpoint
or permission to bypass producer validation. If diagnostics cannot be saved, disclose
that gap and preserve the original tool outcome. Never log credentials, process environment, or arbitrary tool output. To diagnose
agent-authored writers, preserve generated Python source before execution under the
current run's `diagnostics/python/`, with a content hash and unique invocation ID.
Keep source in the same access-controlled Workspace as run artifacts; do not print
it into application logs. Generated scripts must obtain authentication through the
approved SDK/environment, never embed secret values. Record only the source path and
hash in the reconciliation timeline. On hosts without automatic capture, the master
performs this capture through approved Workspace file operations. Capture failure is
reported explicitly and never misrepresented as a recoverable source record.

Before accepting reconcile_schema VALID, compare runtime-owned evidence with the
producer's manifest hash and perform the full admission gate. If mismatched, retain
both snapshots and identify the operation window where the change occurred. A change
across a tool call identifies a time window, not proof of an exclusive writer. No
mutation rerun is authorized merely to collect diagnostics.


A change to existing runtime-owned reconciliation bytes across a non-producer
operation is `RECONCILIATION_PRODUCER_VIOLATION`. Stop immediately before checkpoint
acceptance or consumer execution; preserve both versions. App tool transport enforces
this boundary around its tool calls. Other agent hosts apply the same before/after
hash check using Workspace reads. An authorized DDL producer rerun must still pass
master recovery and existing mutation gates. Never copy prior-version reconciliation,
validation results, or checkpoints into a new run; those are evidence, not reusable
specifications. An earlier declarative specification may only be reused under its
existing current-run revalidation rules and cannot authorize copying evidence.


Direct Workspace write/copy tools must reject writes to the authenticated current-run
`schema_reconciliation.yaml`. The App applies this before the write. This is not a
sandbox for arbitrary Python: before/after hash enforcement still detects replacement
through SDK calls and blocks consumers, but cannot undo the mutation. Do not claim
that every possible writer is prevented. The read-only post-DDL workflow and frozen
producer admission remain the primary cross-host contract.


## DL-G7: Exact reconciliation checkpoint fingerprints

The current DDL manifest emits `reconcile_schema_output_fingerprints` for the
checkpoint writer. Require exactly one `schema_reconciliation_artifact` / `RAW_BYTES`
entry and one `schema_reconciliation_catalog_readback` / `CATALOG_READBACK` entry.
Copy this runtime-produced list only after its artifact hash and current catalog
readback authenticate. Read back the committed checkpoint and validate again before
launching synthetic generation. `schema_reconciliation`, `catalog_tables`, and
`CANONICAL_JSON` are not aliases for these fields. Readback location is exactly
`table_spec:{catalog}.{schema}:{asset_suffix}`; its digest uses the ordered runtime
observed inventory, not a new summary of table names or simplified column types.

Use GATE RECONCILIATION-FINGERPRINTS. Existing malformed/stale checkpoint records
require the master's invalidation and authenticated recommit; never silently change
fingerprints or run the missing-record-only recovery on an existing record. An older
producer manifest lacking this list must follow the already documented exact schema
and all readback gates, not synthesize provenance or bypass the frozen template digest.


### Checkpoint writer and helper-attestation prohibitions

Never infer phase validity from `authenticate_context` success. Run the owning phase's
artifact and live-readback gates first, construct its exact stage-defined fingerprints,
then commit through the attested WorkspaceStore and verify readback. Generic checkpoint
helpers must accept the authenticated producer fingerprint list; they must not apply
CANONICAL_JSON uniformly to all output files. Reconciliation's list is owned by DL-G7.

Never fabricate a PASS `ddl_preflight.yaml` when a read fails, even if catalog tables
exist. Preserve the actual error and return to the producer owner. Missing output,
permission denial, and invalid YAML are not successful DDL evidence.

After context freezing, helper expected hashes come from the frozen path/hash tuple.
Computing `expected = sha256(downloaded_bytes)` and comparing those same bytes is not
attestation. Load the lifecycle helper using its existing frozen reference; preserve
source/copy verification and stop on mismatch. Do not recompute frozen identity to
legitimize changed configuration or substitute a current helper for the frozen one.

### DL-G8: ERD structure admission

Apply validation GATE 2.1 before datatype resolution, parse completion, and DDL deployment,
including cache/resume readbacks. ERD columns belong at `tables[].observed.columns`;
DDL-spec `tables[].columns` is a different interface. Missing/empty/misplaced observed
columns are structural defects, never datatype-policy inputs. Route recovery through
the master to the parse owner using original vision evidence or bounded source re-extraction.
Do not invent columns, use table-spec data as observed source evidence, or bypass the
runtime rejection. No domain-specific table or key exceptions are permitted.

During `parse_erd`, apply instructions §2.5a: record every extraction defect in current
findings, continue analyzing independent readable tables in the same phase, and exhaust
bounded evidence-based recovery before reporting the accumulated blockers. Catch candidate
structural validation errors for findings collection; never swallow authentication/transport
failures or report PASS after rejection. Keep incomplete drafts in diagnostics. Unresolved
structure blocks canonical parse completion and all dependent deployment, not independent
source analysis. Report `update` during analysis and `failed` on unresolved admission; use
only existing shared status/checkpoint values. No partial deployment or silent table omission.

### DL-G4 deployment request integrity

Use `build_data_deployment_request` in validation GATE TEMPLATE-BINDING to construct
all deployment arguments together. Pass its output unchanged; do not hand-transcribe a
partial placeholder map. Recompute it when changing templates. The DDL interface omits
`ASSET_SUFFIX`; the synthetic interface requires it. Both values and required keys come
from the frozen template and authenticated run handoff, never hardcoded domain/version
values. A rejected request remains a deployment failure and blocks all dependent calls.
No notebook import occurred for a missing-binding rejection, but earlier run operations
still require the master's normal recovery/readback checks.
