# Data Layer — Validation Contract

> **Always loaded.** This file owns executable gates and evidence requirements for `create_data_layer`. Operational history is intentionally excluded.

## Gates

### GATE 2.1: Canonical ERD structure (mandatory before datatype resolution)

Execute `validate_erd_structure` below on the fresh vision candidate, every cache/resume
candidate, and the exact persisted readback before completing `parse_erd`. Repeat on the
persisted ERD before GATE 4.0 and DDL deployment. A nonempty table list alone is not PASS.
This gate validates structure only; datatype, source completeness, provenance, and projection
gates remain mandatory. Never use `table_spec.yaml` or inferred business knowledge to fill
missing observed columns.

```python
def validate_erd_structure(document):
    errors = []
    tables = document.get("tables") if isinstance(document, dict) else None
    if not isinstance(tables, list) or not tables:
        raise RuntimeError("ERD_EXTRACTION_ERROR: tables must be a nonempty list")
    table_names = set()
    for index, table in enumerate(tables):
        location = f"tables[{index}]"
        if not isinstance(table, dict):
            errors.append(f"{location}: expected mapping")
            continue
        name = table.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{location}.name: missing identity")
        elif name.casefold() in table_names:
            errors.append(f"{location}.name: duplicate {name!r}")
        else:
            table_names.add(name.casefold())
        location += f" ({name!r})"
        observed = table.get("observed")
        columns = observed.get("columns") if isinstance(observed, dict) else None
        if not isinstance(columns, list) or not columns:
            errors.append(f"{location}.observed.columns: expected nonempty list; table fields={sorted(map(str, table))}")
            continue
        column_names = set()
        for ci, column in enumerate(columns):
            cname = column.get("name") if isinstance(column, dict) else None
            if not isinstance(cname, str) or not cname.strip():
                errors.append(f"{location}.observed.columns[{ci}].name: missing identity")
            elif cname.casefold() in column_names:
                errors.append(f"{location}.observed.columns[{ci}].name: duplicate {cname!r}")
            else:
                column_names.add(cname.casefold())
    if errors:
        raise RuntimeError("ERD_EXTRACTION_ERROR: " + "; ".join(errors))
    return document
```

During candidate analysis, catch this gate's `ERD_EXTRACTION_ERROR` and apply instructions
§2.5a: accumulate findings, continue independent extraction within `parse_erd`, and perform
bounded source-based recovery. The function aggregates structural defects across all tables;
its exception is not permission to skip the remaining source analysis or fabricate PASS.
For a cache candidate, treat structural failure as a cache miss. Preserve rejected candidates
as diagnostics, never as accepted canonical outputs. Correct serialization only from exact
original vision evidence; never silently reinterpret missing observations in the DDL runtime.

After the analysis/recovery pass, unresolved structural findings block parse completion and
all dependent deployment. Persist all findings and diagnostic paths, report `failed`, and
return to the master for existing-checkpoint invalidation. Re-run the gate on the complete
recovered candidate and canonical readback before admitting DDL. See §2.5a for portable
findings persistence, retry accounting, and progress semantics.

### GATE 2.1a: Generated target names (DL-G1)

Before completing `parse_erd`, verify the source→target mapping required by this
step's `guardrails.md` DL-G1. Execute the pinned DDL template's pure
`validate_uc_target_names(catalog, schema, tables, asset_suffix)` over the entire
target inventory. Require legal suffixed names, no case-insensitive collisions,
and consistent relationship endpoints. Preserve source labels and mapping rationale
in the parse artifact and its existing checkpoint output hash. DDL repeats this gate
before mutation and records `GENERATED_IDENTIFIER_ERROR` on failure. Return control
to the master for owning-phase regeneration; never silently rename inside SQL.

### GATE 5.0: Executable synthetic specification (DL-G2 and DL-G3)

Before deploying the synthetic notebook, execute its pinned pure
`validate_synthetic_spec(spec, table_spec_tables)` on every table. Require all fields
in DL-G2, existing FK endpoints, supported key shapes, and parent-before-child order.
Confirm the authenticated `generate_ddl` and `reconcile_schema` prerequisites before
admission. The notebook repeats validation before any data write. Missing `parent_pk`
or another malformed field returns to the spec-producing phase; never infer a missing
key in the runtime. Persist/hash the validated spec using the existing phase contract.

### GATE 2.1b: Data Type Validation (MANDATORY post-parse)
After parsing the ERD, verify every column has a Databricks-valid datatype. `DECIMAL`, `DECIMAL(p)`,
and `DECIMAL(p,s)` are complete platform syntax and canonicalize using documented defaults `p=10`,
`s=0`; enforce `1 <= p <= 38` and `0 <= s <= p`. For NULL, UNKNOWN, truncated, unbalanced, or
unsupported types, re-invoke the vision model with a targeted crop up to two times. If a datatype-only
defect remains and the run is ERD-driven with both `greenfield.enabled` and
`greenfield.synthetic_data` true, invoke `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`, persist every
decision in `schema_assumptions.yaml`, and rerun strict validation. This resolver is total for
datatype defects: recover visible components, prefer strict-majority semantic peers, apply the
release-pinned semantic policy, then use non-truncating `STRING`. Source/live, retained-data, and
structural defects remain `ERD_EXTRACTION_ERROR` deployment blockers. Structural findings
follow §2.5a collection/recovery before the final admission decision; they never qualify
for datatype-only inference.

This gate applies equally to a fresh vision response, a prior-version ERD cache candidate, and a
resume candidate. Matching ERD image hash, parseable YAML, non-empty tables, or an old phase status
cannot pass this gate. Run the current digest-attested validator before accepting or writing the
candidate. A cached candidate that fails becomes a cache miss; invalidate `parse_erd` and all
dependents and perform a fresh parse. Cache/resume PASS additionally requires a current authenticated
`schema_assumptions.yaml`, even when its resolution count is zero.

For a fresh parse, validate and resolve the vision response completely in memory, then create the
resolved `erd_parsed.yaml` and its matching `schema_assumptions.yaml`. Neither output is a required
input before that first persistence. After persistence, re-read and mutually authenticate both
before the phase can become `VALID` or any downstream consumer may run.

### GATE 4.0: Expected Schema Contract (MANDATORY before DDL execution)
`table_spec.yaml` must be an exact physical projection of the resolved `erd_parsed.yaml`. Before notebook
deployment or execution, invoke the digest-attested `validate_table_spec_projection(erd_tables,
table_spec)` function and require `PASS`. Normalize and compare every ordered table, column, and
datatype; reject duplicates and malformed parameterized types. Authenticate the assumptions artifact's
run/target/suffix, policy ID, raw/resolved ERD hashes, and ordered rows first. An eligible invalid ERD
datatype routes through bounded targeted reparse and governed resolution; a table-spec projection
difference routes to regeneration as `SCHEMA_CONTRACT_ERROR`. Neither rejected artifact may reach
`execute_notebook`.

Defense in depth inside the DDL runtime occurs before the first Spark SQL statement and writes
`ddl_preflight.yaml`. For an eligible datatype-only defect, the runtime independently applies the
same pinned resolver, atomically writes the resolved ERD and `schema_assumptions.yaml`, proves
idempotence, and then regenerates only table-spec type fields from the resolved ERD. Record every
old/new value, raw/resolved ERD hashes, assumptions digest, and both table-spec hashes; require a
second exact projection PASS. This never authorizes adopting catalog drift as intent. Structural
differences remain hard failures.

When the ERD is already strict-valid, the DDL runtime MUST authenticate the existing parse-owned
`schema_assumptions.yaml` and preserve its exact bytes; it must not replace parse evidence with an
empty runtime artifact. If the exceptional runtime backstop changes the ERD or assumptions, treat
that action as bounded `parse_erd` recovery: refresh the owning parse output fingerprints and
checkpoint before `generate_ddl` may become `VALID`. A downstream phase never leaves a mutated
parse artifact paired with its old fingerprint.

### GATE 4.1: Table Count Verification
`SHOW TABLES IN {catalog}.{schema} LIKE '*{ASSET_SUFFIX}'` must return expected count, using the exact frozen `step_handoff.yaml.asset_suffix`. HALT if fewer.
**CRITICAL:** `SHOW TABLES LIKE` uses **glob syntax** (`*` = wildcard), NOT SQL LIKE syntax (`%` = wildcard). See **G-15** in `{AGENT_SKILLS_DIR}/prompts/shared/global_guardrails.md`. Using `%` returns zero results.

### GATE 4.2 / `reconcile_schema`: Schema Reconciliation (MANDATORY after DDL execution)
After GATE 4.1, verify each table's **actual deployed schema** from `DESCRIBE TABLE` matches the **expected generated schema** in `table_spec.yaml`, including normalized column names and datatypes. GATE 4.0 already proves that `table_spec.yaml` matches `erd_parsed.yaml`.

The canonical policy identifier is `DEPLOYED_DATATYPE_REPAIR_V1`.

Use only the release-approved deterministic datatype canonicalizer. Canonicalization may normalize case, insignificant whitespace, and aliases explicitly encoded by that canonicalizer; it MUST NOT infer widening compatibility, add a cast, change precision/scale/length, or treat two merely coercible types as equal. Preserve the exact expected and observed type strings as evidence.

For any real deployed datatype mismatch, the Data Layer is the sole repair owner. Automatic repair is permitted exactly once per table only when **all** of these checks pass:

1. the FQN is the exact current-run generated target from `table_spec.yaml`, in the frozen target catalog/schema, with the exact frozen `asset_suffix`;
2. the table is a greenfield accelerator-owned target, not a live/source table, unversioned object, or object discovered by a wildcard;
3. `SELECT COUNT(*)` succeeds and returns exactly zero;
4. the repair uses the pinned DDL compiler and unchanged `table_spec.yaml`; and
5. no earlier datatype repair attempt was made for that table in this run.

The only allowed **post-deployment drift** action is: record the mismatch, drop the exact empty table,
rerun its compiler-generated CREATE statement, rerun `DESCRIBE TABLE`, and require exact canonical
schema equality. `ALTER COLUMN`, casts, `TRY_CAST`, CTAS, overwrite, post-freeze mutation of
`erd_parsed.yaml`/`table_spec.yaml`, and adoption of the observed type are prohibited drift-repair
mechanisms. This does not prohibit the authenticated pre-DDL datatype-resolution phase above.

Within the DDL runtime: if ownership is ambiguous, the table is non-empty, row count cannot be proven, the object is source/live/unversioned, the operation lacks permission, or post-repair readback still differs, write failure evidence and HALT with `DATATYPE_MISMATCH_UNSAFE_TO_REPAIR`. Do not delete or coerce data. Missing/unexpected/renamed-column mismatches use the same empty-current-version-table eligibility gate and otherwise halt with `SCHEMA_CONTRACT_ERROR`.

Inside the frozen DDL runtime only, before any synthetic specification or write, atomically record every decision in `{OUTPUT_FOLDER}/schema_reconciliation.yaml`: current run/target/suffix binding, raw `table_spec.yaml` digest, expected/observed schema fingerprints, policy identifier, expected/observed schemas, canonical comparison, ownership checks, row count, action, attempt count, post-repair readback, unresolved mismatches, and terminal status. Persist both PASS and FAIL outcomes. Only PASS with zero unresolved mismatches creates a `VALID` `reconcile_schema` checkpoint. FAIL halts immediately and must not run later data-quality checks.

The agent's post-notebook GATE 4.2 is read-only with respect to this file. Read the
DDL manifest and require its `schema_reconciliation_sha256` to match exact current
bytes, then execute GATE RECONCILIATION-PROVENANCE and fresh schema comparisons.
Do not run a second Python reconciliation writer, copy a prior-version reconciliation,
or translate the runtime schema into a summary. Any separate agent observations go
under `diagnostics/reconciliation/`; they never replace runtime-owned evidence.
If fresh readback fails, return failure evidence to the master without rewriting PASS
as FAIL in the producer artifact. Mark the consumer checkpoint invalid instead.

Steps 5 and 6 must re-authenticate this artifact and freshly recompute catalog name/type equality before work. The final `data_layer_validation.yaml` records the reconciliation artifact's exact path/raw digest and embeds the same outcome; it does not first create or reinterpret reconciliation evidence.

### GATE 5.1: Domain Value Validation
Every categorical column MUST have domain-specific values (not `val_1`...`val_5`). Run the Domain Value Inference Protocol for any column with generic values.

### GATE 5.2: YAML Type Safety Validation (MANDATORY before writing spec)
All values for VARCHAR/STRING columns MUST be quoted strings in `synthetic_data_spec.yaml`. YAML parses `99213` as integer, creating mixed-type lists.

### GATE 6.1: Row Count Verification
ALL tables must have rows > 0 after synthetic data generation. HALT with `SYNTHETIC_GENERATION_ERROR` if any table is empty.

### GATE 7.1: Data Layer Validation
`data_layer_validation.yaml` must exist with `overall_status: PASS`; its recorded path/raw digest must authenticate the current `schema_reconciliation.yaml` and `schema_assumptions.yaml`; the embedded reconciliation payload must match and have policy `DEPLOYED_DATATYPE_REPAIR_V1`, status `PASS`, and zero unresolved mismatches; the assumptions payload must have policy `GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1`, matching raw/resolved ERD hashes, and zero unresolved datatypes. Every relationship in `semantic_model.yaml` must have exactly one relationship-level validation entry with `validation_status: PASS`. HALT otherwise. `semantic_model.yaml` is relationship intent; this relationship-level result is the authority for downstream use of the deployed relationship.

---

## Failure-Only Runbook Routing Index

| Runbook section | Load only when observed evidence matches |
|---|---|
| `AP-DL-1` | Vision Model Truncation |
| `AP-DL-2` | Mixed-Type YAML Lists |
| `AP-DL-3` | dbldatagen Boolean/Timestamp Bugs |
| `AP-DL-6` | Truncated Data Types from Vision Model (decimal(28) |
| `AP-DL-5` | LLM Generates DDL Notebook From Scratch Instead of Using Template |
| `AP-DL-4` | SHOW TABLES LIKE Uses Wrong Wildcard |
| `AP-DL-7` | Join Fanout From Missing pk_cols in Dimension Tables |
| `AP-DL-8` | DELTA_EXCEED_CHAR_VARCHAR_LIMIT from dbldatagen Generated Values |
| `AP-DL-9` | Populated Current-Version Schema Drift / `DATATYPE_MISMATCH_UNSAFE_TO_REPAIR` |

Classify the failure from current evidence before loading a runbook section. The index is a routing aid, not authority to bypass the stage owner or retry policy.


### GATE TEMPLATE-BINDING: Deployment acknowledgement (DL-G4)

Enumerate all placeholders in the frozen template and verify complete, nonempty
bindings before import. Require the deployment tool's success for the exact output
path, followed by notebook terminal success and the existing phase readback gates.
After authenticating the frozen template bytes, context, and handoff under the
existing identity/parity gates, execute this binding gate on the host's Python
execution surface. Pass its returned map directly to deployment; do not retype or
reuse the preceding template's map. This works with App tools or Genie Code.

```python
def bind_data_template(template_text, run_context, step_handoff):
    import re
    required = set(re.findall(r"\{\{([A-Z_][A-Z0-9_]*)\}\}", template_text))
    sources = {
        "DOMAIN_NAME": run_context["domain"]["name"],
        "OUTPUT_FOLDER": step_handoff["output_folder"],
        "TARGET_CATALOG": step_handoff["catalog"],
        "TARGET_SCHEMA": step_handoff["schema"],
    }
    if "ASSET_SUFFIX" in required:
        suffix = step_handoff.get("asset_suffix")
        if (not isinstance(suffix, str) or not suffix.strip()
                or suffix != run_context["version"].get("asset_suffix")):
            raise RuntimeError("HANDOFF_AUTHORITY_ERROR: missing, empty, or conflicting asset_suffix")
        sources["ASSET_SUFFIX"] = suffix
    invalid = sorted(key for key in required
                     if not isinstance(sources.get(key), str)
                     or not sources[key].strip()
                     or "{{" in sources[key] or "}}" in sources[key])
    if invalid:
        raise RuntimeError(f"TEMPLATE_BINDING_ERROR: unresolved bindings: {invalid}")
    return {key: sources[key] for key in sorted(required)}
```

Construct the **entire deployment request** on the same execution surface as this gate,
using the current template bytes and authenticated context/handoff. Return the serialized
request as a tool result and pass it unchanged to `deploy_from_template`; do not rebuild
`placeholders` from memory. For Genie Code, use the identical returned map with the shared
native/SDK deployment transport. The output path must already pass current-run ownership
checks; constructing this request does not authorize a new path.

```python
def build_data_deployment_request(template_text, run_context, step_handoff,
                                  template_path, output_path, run_context_path):
    return {
        "template_path": template_path,
        "output_path": output_path,
        "run_context_path": run_context_path,
        "language": "PYTHON",
        "placeholders": bind_data_template(template_text, run_context, step_handoff),
    }
```

Rebuild this request separately for each template, including after DDL succeeds. In
particular, a DDL map without `ASSET_SUFFIX` is not a synthetic-template binding map.
Before issuing deployment, compare the request's placeholder key set to the exact
frozen template interface and require equality. The synthetic suffix is copied verbatim
from authenticated persisted identity, never derived from a folder or version number.
Missing or conflicting persisted suffix is an authority failure, not permission to guess.

If an updated frozen template introduces an unmapped field, halt for its owning
contract to be resolved; do not guess a value. This gate does not replace template
digest authentication, persisted handoff parity, or runtime pre-data checks.

Any deployment error blocks dependent stages regardless of prior files or progress
labels. Classify missing values as TEMPLATE_BINDING_ERROR and return to the master.


### GATE 4.0: Bounded datatype projection (DL-G5)

After authenticating the resolved ERD, assumptions, and candidate table spec, execute
this function with the already attested `validate_table_spec_projection` callable.
It constructs a candidate in memory; no SQL or Workspace writes occur. Structural
mismatches are never repaired. Preserve returned replacement evidence in the owning
DDL preflight/checkpoint evidence, persist the validated candidate using the approved
Workspace transport, read it back with duplicate-key rejection, and rerun the validator
on that readback before deploying. A failed final gate must not persist a candidate.

```python
def project_table_spec_types(erd_tables, table_spec, validate_projection):
    import copy
    candidate = copy.deepcopy(table_spec)
    spec_tables = candidate.get("tables", [])
    if (not erd_tables or not spec_tables
            or [t["name"] for t in erd_tables] != [t["name"] for t in spec_tables]):
        raise RuntimeError("SCHEMA_CONTRACT_ERROR: table inventory/order mismatch; no projection repair")
    replacements = []
    for erd_table, spec_table in zip(erd_tables, spec_tables):
        observed = erd_table["observed"]["columns"]
        columns = spec_table["columns"]
        if [c["name"] for c in observed] != [c["name"] for c in columns]:
            raise RuntimeError("SCHEMA_CONTRACT_ERROR: column inventory/order mismatch; no projection repair")
        for source, target in zip(observed, columns):
            resolved_type = source.get("datatype")
            if target.get("type") != resolved_type:
                replacements.append({"table": spec_table["name"], "column": target["name"],
                                     "previous_type": target.get("type"), "type": resolved_type})
            target["type"] = resolved_type
            target.pop("datatype", None)  # ERD-only field, never the compiler interface
    report = validate_projection(erd_tables, candidate)
    if report.get("status") != "PASS":
        raise RuntimeError(str(report.get("failure_code") or "SCHEMA_CONTRACT_ERROR")
                           + ": GATE 4.0 projection failed: " + str(report.get("errors", [])))
    return candidate, replacements
```

Missing or invalid source datatypes remain ERD_EXTRACTION_ERROR, following existing
ERD reparse/resolution policy. Never use this function to manufacture source evidence.


### GATE RECONCILIATION-PROVENANCE (DL-G6)

Run against duplicate-key-rejecting readback of the exact current-run reconciliation
file before checkpoint admission and before synthetic deployment. This supplements,
not replaces, run/target/suffix/hash, inventory, assumptions, and fresh catalog checks.

```python
def validate_reconciliation_provenance(reconciliation):
    import re
    expected = {"artifact_type": "schema_reconciliation", "contract_version": 1,
                "producer_step": "create_data_layer", "producer_phase": "reconcile_schema",
                "policy_id": "DEPLOYED_DATATYPE_REPAIR_V1", "status": "PASS",
                "datatype_resolution_policy_id": "GREENFIELD_SYNTHETIC_DATATYPE_RESOLUTION_V1",
                "canonical_comparison": "MATCH", "unresolved_mismatches": []}
    if not isinstance(reconciliation, dict):
        raise RuntimeError("SCHEMA_RECONCILIATION_AUTHORITY_ERROR: expected a mapping")
    errors = []
    for field, value in expected.items():
        actual = reconciliation.get(field)
        if type(actual) is not type(value) or actual != value:
            errors.append(f"reconciliation.{field}={actual!r}, expected {value!r}")
    for field in ("table_spec_sha256", "schema_assumptions_sha256",
                  "expected_schema_sha256", "observed_schema_sha256"):
        if not isinstance(reconciliation.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", reconciliation[field]):
            errors.append(f"reconciliation.{field}: canonical SHA-256 required")
    for field in ("run_id", "asset_suffix", "table_spec_path", "schema_assumptions_path"):
        if not isinstance(reconciliation.get(field), str) or not reconciliation[field].strip():
            errors.append(f"reconciliation.{field}: nonempty string required")
    for field in ("expected_schema_inventory", "observed_schema_inventory"):
        if not isinstance(reconciliation.get(field), list) or not reconciliation[field]:
            errors.append(f"reconciliation.{field}: nonempty inventory required")
    if errors:
        raise RuntimeError("SCHEMA_RECONCILIATION_AUTHORITY_ERROR: " + "; ".join(errors))
    return reconciliation

```

This gate reports all structural defects together. Alternate keys such as `policy`,
`expected_schema_hash`, `observed_schema_hash`, and `deployed_tables` are not the runtime
contract. A count `0` does not replace the required empty mismatch list `[]`. Passing
this shape gate alone is not admission: compare actual file hashes, run identity,
canonical inventories, and fresh catalog readback under the existing gates before
committing VALID. Never backfill fields into an unverified artifact to make it pass.


### GATE RECONCILIATION-FINGERPRINTS (DL-G7)

After complete DL-G6 admission, compare the DDL-manifest list and checkpoint list
against these independently recomputed entries. Call once before checkpoint commit
and again on persisted checkpoint readback before synthetic deployment. Supply the
actual artifact bytes and fresh observed inventory in the runtime's exact ordered
`[{table_fqn, schema: [{column, datatype, canonical_datatype}]}]` representation.
Do not replace it with an expected inventory or a table-name-only catalog listing.

```python
def validate_reconciliation_fingerprints(entries, artifact_bytes, observed_inventory,
                                        output_folder, catalog, schema, asset_suffix):
    import hashlib
    import json
    expected = [
        {"id": "schema_reconciliation_artifact", "kind": "RAW_BYTES",
         "locator": output_folder + "/schema_reconciliation.yaml",
         "sha256": hashlib.sha256(artifact_bytes).hexdigest()},
        {"id": "schema_reconciliation_catalog_readback", "kind": "CATALOG_READBACK",
         "locator": f"table_spec:{catalog}.{schema}:{asset_suffix}",
         "sha256": hashlib.sha256(json.dumps(observed_inventory, sort_keys=True,
                     separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()},
    ]
    if entries != expected:
        raise RuntimeError(f"SCHEMA_RECONCILIATION_AUTHORITY_ERROR: checkpoint fingerprint mismatch; expected={expected!r}; observed={entries!r}")
    return expected
```
