# V2 prompt-chain review

Reviewed 2026-09-25. Scope: master, shared authority/state/transport contracts, and
Data Layer, Metric View, Dashboard, Genie, cross-validation and documentation
instructions/validation/guardrails, compared against release-selected template
interfaces and existing runtime tests. This is a local contract review, not proof
of live Databricks execution or comprehensive model compliance.

## Findings and corrections

| Boundary | Confirmed issue | Correction |
|---|---|---|
| Config → Setup | Supplied failed-run artifacts preserved the configured target, but SQL used a different target. | Exact context/handoff SQL builder and admission; expected/actual target evidence; resolver ownership rather than granting access to the wrong catalog. |
| Release → Dashboard/Genie | Active instructions/validation still named legacy deployment templates despite release selecting v2 files. | Align active names with release; frozen path/digest remains authority. |
| Frozen input → consumer | Some interpolated read paths used a reference mapping rather than its `.path`. | Fix concrete consumer examples and clarify reference shape centrally. |
| Inspection → deployment | Shared prohibition on reading/substituting templates conflicted with mandatory inspection and portable SDK transport. | Allow authenticated inspection and exact transport substitution; keep notebook logic rewriting prohibited. |
| Binding → Python notebook | Tool expects strings; Genie examples contain lists/dicts. Python literals, quoted strings and JSON are not interchangeable. | Shared serializer verifies exact placeholder inventory, escapes strings, preserves Python literal types, and parses rendered Python cells before import. Used by all deployment stages. |
| Master → ERD cache | Blanket prior-artifact prohibition conflicted with stage-owned optional cache policy. | Narrow explicit cache exception after run selection; it cannot select run identity or authorize other artifact reuse. |
| Failure → terminal lifecycle | Unconditional instruction to commit failure conflicts with an unauthenticated context. | Attempt commit only with authenticated identity; report uncommitted interruption honestly. |
| Dashboard failure → recovery | Recovery did not clearly separate artifact failure, missing checkpoint, unknown remote execution and changed frozen release. | Separate these cases; retain valid predecessors; never rehash an old run to adopt a new release. |
| Error ownership | Setup wording could create a phase name as a failure owner despite master's closed owner list. | Use MASTER_RESOLVER with environment_setup phase; preserve original platform error separately. |

## Stable ownership

- `accelerator.yaml`: requested configuration, never modified to fit generated SQL.
- Master: resolve/freeze, Setup, dependency admission, lifecycle commit.
- Shared contracts: transport, state shapes, global authority and recovery rules.
- Stage guardrails/validation: stage policy and evidence gates.
- Release-selected templates/helpers: deterministic implementation; no domain-specific overrides.
- Catalog/API readback: actual deployed state, not replacement intent.
- Documentation: report/draft only; cannot create canonical success evidence.
- Lakebase: optional App mirror, not required for portable execution.

## Regression coverage

Latest local result: 269 tests passed; `git diff --check` passed. No live run was performed.

Run the entire suite, not only the edited stage:

```sh
python3 -m unittest discover -s framework/tests -q
```

`test_v2_release_workflow.py` carries a single locally allocated run through:
real member-claims configuration → release helpers/templates inventory → frozen
context/handoff → Setup SQL admission → rendered DDL, synthetic, Metric View,
Dashboard and Genie templates → actual Dashboard/Genie readback validators against
simulated APIs → actual cross-validation sweep covering all four asset classes →
documentation draft → terminal registry/context/manifest commit.

A failure scenario injects Dashboard readback drift, commits failure, reopens the
same run through the real resolver, and proves earlier rendered artifacts remain
byte-identical and no Genie API readback was invoked after that failure. This tests
contract/lifecycle integration; it does not simulate the LLM's decision-making or
claim synthetic table contents were preserved in a real warehouse.

Additional tests cover the missing synthetic suffix, quoted/multiline string
serialization and nested Python booleans/nulls, plus the existing isolated gate,
identity, source drift, SQL timeout, preflight and stage admission regressions.

## Remaining acceptance boundary

Local tests do not run vision, model-serving decisions, Spark/dbldatagen notebooks,
real SQL, Lakeview deployment or Genie benchmark jobs. The workflow fixture compiles
all released notebooks; it does not execute their remote mutation cells. Its API
responses are controlled fixtures, not platform observations.

Before declaring the project working end to end, perform one authorized live run of
the complete deployed release, preserving actual tool calls, SQL/job IDs, phase
checkpoints, API readbacks and final sweep. Verify exact configured targets, stage
sequence, all requested dashboards, Genie and documentation. Do not modify the
release in the middle of that run. If it fails, diagnose its exact release and
artifacts rather than applying unrelated changes to earlier stages.

For an existing failed run, first establish whether its frozen executable bytes are
still available. Syncing changed templates to the same paths can make the old run
non-resumable; do not overwrite its hashes to hide that. A local passing suite and
a fresh-run success must never be described as recovery of a different frozen run.

## Fresh-run artifact ordering review

The v8 traceback establishes a download of a missing `schema_reconciliation.yaml`.
The user reports ERD was active. Without that execution's captured Python source and
phase events, the exact generated-code decision and any UI attribution error remain
unconfirmed. Reconciliation is produced by DDL, so it cannot be an ERD input.

Confirmed prompt conflicts corrected in this pass:

- Dashboard, Genie and Documentation required Resume Skip Gate before any execution,
  including new phases that have no outputs. Shared phase-entry classification now
  precedes generated-artifact I/O; only existing candidates verify their outputs.
- Shared portable execution flow asked for dependency/output fingerprints indiscriminately.
  It now distinguishes new work, checkpoint verification, attempted-work recovery and stale
  recovery, and starts through the master rather than standalone stage resolution.
- Data Layer and global invalidation wording bypassed missing-checkpoint recovery.
  They now defer to the shared recovery policy and preserve verified predecessor work.
- Whole-stage restart wording contradicted phase-level continuation; removed.
- Host-specific bad-data deletion/continue instructions contradicted portable ownership
  and quality rules; replaced with the shared owned recovery and unknown-execution policy.
- Documentation's memory-only verification, immediate completion and tool-call cap
  contradicted persisted-output/checkpoint readback; removed those exceptions.

`test_phase_entry_scope.py` exercises entry routing across all reusable stage phases,
missing-checkpoint attempt recovery, stale/duplicate/malformed records and sibling phase
identity isolation. It does not prove that a model follows the function. The cross-stage
release test now also admits the persisted DDL target envelope using actual configured
coordinates. No live run, deployment or notebook re-execution was performed.

Deployment: sync one coherent release before a fresh test. These prompt/control byte
changes alter frozen producer/state digests. Do not update an old run's frozen hashes to
force reuse; retry under its exact frozen release or start a fresh version with this release.
For v8 attribution, inspect the failing execute_python source in that run's
`diagnostics/python/` and its corresponding tool/phase events before claiming a precise cause.
