# Portable agent execution contract

This file governs transport for every v2 prompt. The master remains the orchestrator:
helpers implement bounded operations and never choose the next pipeline stage. Use
the same master in Genie Code, the Agentic app, or another capable agent.

## Bootstrap

Start from the master prompt's own absolute workspace path. If REPO_ROOT was not
supplied, derive it by removing the exact suffix
`/framework/agent_skills/v2/prompts/00_master_prompt.md`; verify the resulting root.
If EXAMPLE_DIR was not supplied, use the current domain directory when it contains
accelerator.yaml; otherwise list REPO_ROOT/kpi_domains and use its sole configured
domain. If multiple domains exist, ask which to run before allocation. Never guess.
Default requested_mode to auto, requested_version to null, generate a candidate UUID,
and derive a stable execution_owner from the actual host identity when omitted.
The caller may override REPO_ROOT and EXAMPLE_DIR with absolute workspace paths. Bind
AGENT_SKILLS_DIR to REPO_ROOT/framework/agent_skills/v2. Before allocation, read
contracts/release.yaml there. Resolve its paths against REPO_ROOT; read and hash
every selected file. Freeze helpers and templates as `{path, sha256}` entries under
run_context.templates. Freeze inputs at their documented run_context.inputs keys.
The release manifest is the only selector; contracts/templates and nested historical
copies are not runtime alternatives. A configured template must resolve to the release
path or fail preflight; do not silently select an old template from accelerator.yaml.
Record the release path/raw SHA and this transport path/raw SHA in run_context.inputs.

### Required Step-0 executable reference inventory

`release.helpers` and `release.templates` are packaging categories, not separate
run-context namespaces. Merge both into `run_context.templates`. In particular,
`release.helpers.erd_validation_utils` becomes `run_context.templates.erd_validation_utils`.
Do not create only `run_context.helpers`, copy only the release `templates` section,
or freeze the conceptual empty-map example. Use this executable construction before
initial context freeze; `read_bytes` is the approved Workspace/native byte reader.

```python
def build_release_executable_references(release, repo_root, read_bytes):
    import hashlib
    import posixpath
    if not isinstance(repo_root, str) or not repo_root.startswith('/'):
        raise RuntimeError("MASTER_RESOLVER_ERROR: absolute repo root required")
    root = posixpath.normpath(repo_root)
    references = {}
    for section in ('helpers', 'templates'):
        entries = release.get(section)
        if not isinstance(entries, dict) or not entries:
            raise RuntimeError(f"MASTER_RESOLVER_ERROR: missing release {section}")
        for key, relative in entries.items():
            if key in references:
                raise RuntimeError(f"MASTER_RESOLVER_ERROR: duplicate executable key {key}")
            if not isinstance(relative, str) or not relative or relative.startswith('/'):
                raise RuntimeError(f"MASTER_RESOLVER_ERROR: invalid release path for {key}")
            path = posixpath.normpath(posixpath.join(root, relative))
            if not path.startswith(root.rstrip('/') + '/'):
                raise RuntimeError(f"MASTER_RESOLVER_ERROR: release path escapes root: {key}")
            raw = read_bytes(path)
            if not isinstance(raw, bytes) or not raw:
                raise RuntimeError(f"MASTER_RESOLVER_ERROR: missing/empty executable {key}: {path}")
            references[key] = {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    return references


def verify_release_executable_references(context, expected):
    actual = context.get('templates')
    if not isinstance(actual, dict):
        raise RuntimeError("MASTER_RESOLVER_ERROR: run_context.templates must be a mapping")
    invalid = sorted(key for key, value in expected.items() if actual.get(key) != value)
    if invalid:
        raise RuntimeError(f"MASTER_RESOLVER_ERROR: missing/conflicting frozen executable references: {invalid}")
```

For a fresh run, build this map from the selected release's verified bytes, assign it
to `run_context.templates` before computing the frozen context/producer hashes, then
verify the proposed context and exact persisted readback. Step-0 completion and Setup
are blocked until the whole expected inventory matches. Do not recompute an expected
hash from an untrusted download on resume: authenticate the existing frozen release
and executable references first. These functions construct/check inventory; they do
not replace release attestation, checkpoint validation or lifecycle locking.

If an already frozen run lacks a required tuple, report the exact missing key and
return to master recovery. Never insert it and rehash that run in-place. Preserve
failed-run artifacts; use only the established lifecycle rules for subsequent execution.


Normalize configuration BEFORE freezing it:
- Invocation `requested_steps`, when supplied, narrows the configured enabled stages;
  validate dependencies before allocation. Never skip required producers based on a
  UI resume hint. Resume admission belongs to authenticated master checkpoints.
- `requested_mode` controls version selection. Legacy UI `requested_run_mode=clean`
  or `new` means a fresh version, never deletion of earlier versions. Record this
  normalization; reject a conflicting explicit retry/version request. No caller
  setting may disable the terminal sweep or required documentation for enabled assets.
- `llm.steps.erd_parse` is canonical. Accept legacy `parse_erd` only if erd_parse is
  absent, rename it once, and record the normalization. Reject conflicting definitions.
- Resolve missing stage models from llm.default_model (ERD may use llm.vision_model).
  Preserve an explicitly supplied instruction; never index an absent instruction.
- Resolve relative input paths against EXAMPLE_DIR, release paths against REPO_ROOT.
- Freeze runtime.state_store as `workspace_only`. This is the portable lifecycle
  authority in every host, including the App. Lakebase/UI progress is an optional
  observational mirror; it never gates or chooses a workspace run. A separate adapter
  may mirror events after durable workspace commits, but must not replace this master.
- The App enables a host-side Lakebase mirror for durable UI history and recovery.
  Its provisioned database is an App startup requirement, not a requirement of this
  prompt. Mid-run mirror failures retain a verified workspace outbox for replay and
  surface a UI warning. Genie Code and other hosts do not initialize this adapter.
- created_by is a nonempty stable caller-supplied execution-owner string, e.g.
  `genie_code`, `app`, or another host identifier. Do not impersonate another owner.

## Capability preflight (before creating assets)

Require authenticated workspace byte read/write/list/delete, create-only writes,
Python execution (native or a submitted notebook), SQL warehouse execution, vision
model invocation, notebook import/run, and enabled-asset SDK/API access. Verify the
host against requested runtime.workspace_host. Missing capabilities are
AGENT_CAPABILITY_ERROR. Report the exact missing operation before asset creation.
Permission denials remain operational errors. A different approved transport is
selected during this preflight, never after a safety/permission block.

Names in stage prompts denote OPERATIONS, not a required installed tool registry:

| Operation | Native implementation | Portable implementation |
|---|---|---|
| read/write workspace file | Host workspace tools | WorkspaceStore via authenticated SDK |
| execute Python | Genie Code/native Python | Import and execute a control notebook |
| execute_sql / describe_table | Host warehouse tool | SDK Statement Execution API, frozen warehouse |
| call_vision_model | Host vision tool with frozen model | SDK serving invocation with image bytes |
| deploy_from_template | Host substitution tool | Read verified bytes, literal `{{KEY}}` substitution, reject remaining placeholders, import notebook |
| execute_notebook | Host notebook runner | Jobs submit/run and poll terminal result |
| report_progress | Optional host event tool | Persist checkpoint first, then emit structured JSON to the transcript |
| report_step_complete | Optional host event tool | Return structured stage result to the master |

No stage requires Flask, app/shared imports, an app event bridge, or Lakebase.
Use the attested WorkspaceStore for lifecycle writes; do not invent a `put()` wrapper
that omits upload format. Plain-file writes use explicit RAW semantics, UTF-8 bytes, and verified readback.
Use the attested WorkspaceStore: when the installed SDK exposes `ImportFormat.RAW`,
it uses that enum; otherwise it sends authenticated Workspace import JSON with
`format: "RAW"`, base64 content, and the same overwrite flag through `w.api_client.do`.
This capability branch is selected before writing. Never use `ImportFormat("RAW")`,
a bare string passed to SDK upload, AUTO, or a silent SOURCE fallback. Never retry an
SDK/API write failure using a second transport. Server/permission errors propagate.
Probe installed SDK capabilities in each execution host; App and notebook environments
may have different SDK versions. Do not upgrade libraries mid-run to bypass admission. Notebook deployment uses its explicit notebook format.
Before executing any generated control/inspection notebook, inspect its full source, including
helper functions, against the same transport rules as inline Python. Syntax compilation alone
is insufficient. A setup inspection uses read operations; do not add scratch Workspace writes
merely to inspect configuration. Required lifecycle/diagnostic writes use the attested store.
Every direct SDK import/upload must state the appropriate format; do not let wrappers rely on
defaults. Check payload encoding and the target object type separately for files and notebooks.
If the host cannot inspect submitted source, stop before execution and report the missing capability.

For `The zip archive contains no items`, record the failing API operation, exact notebook path,
Jobs run ID, traceback/cell, and executed source digest when available. Inspect that cell and
its helper before assigning a cause: this message alone does not prove an omitted upload format.
Preserve the original error. Check existing writes and the frozen helper/template versions before
master-owned recovery; do not blindly resubmit the notebook or switch formats after failure.
A failed terminal transaction remains failed; use the existing master recovery lifecycle rather
than rewriting it to completed. Do not claim live recovery from local test results.

Templates and Python helpers may run in a notebook. If runtime filesystem access to
/Workspace files is required by a selected Spark template, verify that exact mount
is readable/writable in its execution environment before deployment. Do not assume
agent-local paths refer to remote workspace files. Control-plane writes use the SDK
store. A mounted runtime uses atomic replacement and verified readback under the same
single-writer run policy; never use dbutils.fs on /Workspace paths.

## Lifecycle helper calls

Read the exact release-selected run_contract.py bytes with workspace tools/SDK,
verify the frozen digest, stage in a digest-qualified local temporary directory,
re-hash, and import with importlib.util.spec_from_file_location. Do not discover it
through sys.path. Bind `runtime` to that attested module and `w` to the authenticated
WorkspaceClient whose host passed preflight.

Execute this bootstrap verbatim on the host Python surface (App `execute_python`,
Genie Code Python, or the preflight-selected control notebook). Supply `raw` from
the exact release-selected Workspace download and `expected_sha256` from the
current frozen reference (during initial bootstrap, the just-read release selection
whose identity the master will freeze). Do not use `exec(raw, ...)`, an ad hoc `rc`
module, or `inspect.getsource(WorkspaceStore)` to load or validate it.

```python
def load_lifecycle_runtime(raw, expected_sha256):
    import hashlib
    import importlib.util
    import inspect
    from pathlib import Path
    import re
    import sys
    import tempfile

    if (not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or not isinstance(raw, bytes)
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
        raise RuntimeError("HELPER_CONTRACT_ERROR: lifecycle source digest mismatch")
    directory = Path(tempfile.mkdtemp(prefix="aibi_" + expected_sha256 + "_"))
    module_path = directory / "run_contract.py"
    module_path.write_bytes(raw)
    if hashlib.sha256(module_path.read_bytes()).hexdigest() != expected_sha256:
        raise RuntimeError("HELPER_CONTRACT_ERROR: staged source digest mismatch")
    module_name = "aibi_lifecycle_" + expected_sha256 + "_" + directory.name.rsplit("_", 1)[-1]
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("HELPER_CONTRACT_ERROR: lifecycle loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module  # REQUIRED before exec_module, including in notebooks
    try:
        spec.loader.exec_module(module)
        if Path(module.__file__).resolve() != module_path.resolve():
            raise RuntimeError("HELPER_CONTRACT_ERROR: loaded lifecycle path mismatch")
        for name in ("WorkspaceStore", "resolve_version", "commit_terminal", "load_attested"):
            if not callable(getattr(module, name, None)):
                raise RuntimeError("HELPER_CONTRACT_ERROR: missing lifecycle callable " + name)
        inspect.signature(module.WorkspaceStore).bind(object())
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module
```

Bind `runtime = load_lifecycle_runtime(raw, expected_sha256)`. Keep the staged file
and registered module for the invocation lifetime. Inspect the already verified raw
bytes if source review is necessary; source reflection is not an execution gate.
`inspect.signature` checks callable interfaces and does not require `getsource`.
App Python tool calls are separate processes: reload this attested module in each
call that needs it. Do not assume an earlier call's `runtime`, `store`, or `w` survives.
Use `runtime.load_attested(store, frozen_reference)` for subsequent helpers; do not
rediscover their imports or copy their class bodies. None of this requires App
imports, Lakebase, or an agent-specific Python session.

```python
store = runtime.WorkspaceStore(w)
selection = runtime.resolve_version(
    registry_path=EXAMPLE_DIR + '/version_registry.yaml',
    domain=request['domain']['name'],
    output_root=resolved_output_root,  # EXAMPLE_DIR + requested output_subpath
    created_by=execution_owner,
    run_id=candidate_uuid,
    store=store,
    mode=requested_mode,              # auto, retry, fresh
    explicit_version=requested_version,
)
```

This returns a mapping with the exact master selection fields. The master builds
and persists run_context and step_handoff, then invokes stages with run_context_path.
A fresh allocation has no context until that master write. An interrupted allocation
without context cannot resume; a fresh version preserves the orphan for diagnosis.
A missing registry reserves exact existing vN folders before allocation.

WorkspaceStore's cooperative lock is a create-only workspace file, shared by every
lifecycle writer. It is never stolen based on age. A crashed lock requires explicit
owner recovery after checking the previous execution stopped. Retry uses immutable
history and a transition marker; malformed or incomplete transitions halt.

The master composes the canonical terminal manifest from authenticated evidence and calls:

```python
runtime.commit_terminal(
    store=store, registry_path=run_context['registry_path'],
    run_context_path=run_context_path, manifest=canonical_manifest,
)
```

Do not separately flip registry status. Keep optional App telemetry outside this
transaction. WorkspaceStore replaces one complete object per SDK upload and verifies
exact byte readback while holding the cooperative lifecycle lock. Multi-file changes
are a verified transaction with rollback, not a claim of distributed ACID semantics.
All readers must reject an active lifecycle lock/transition before trusting parity.

If bootstrap or allocation fails before a valid run context exists, report the
bootstrap failure and retained allocation evidence. Do not invent a terminal manifest
or mutate another run to satisfy the post-allocation failure transaction.


Template deployment carries the master's persisted `run_context_path` explicitly.
A fresh host process can authenticate it without replaying `run_selected` progress.
When an older caller supplies only OUTPUT_FOLDER, use its canonical context child
as a candidate locator and authenticate identity before deployment. Never consult
an in-memory acknowledgement flag or scan output versions to choose a context.


## Recovery after host interruption

Loss of an App/Lakebase ownership session proves only that the tracking session is
absent. It does not prove a submitted Jobs run, SQL statement, or notebook stopped.
Before any retry mutation, the master must inspect the exact current-run remote
execution identifiers and their terminal results, then authenticate durable phase
checkpoints under the existing Resume Skip Gate. If an operation remains active,
observe it to terminal status; do not submit a duplicate or cancel it implicitly.
If execution identity cannot be established from persisted evidence and authorized
API readback, halt recovery for reconciliation rather than guessing or appending data
again. Preserve the existing run identity and lifecycle-lock recovery rules.

An App snapshot marked failed is observational state; it does not reopen a portable
registry entry or clear its lock. Never rewrite portable lifecycle state merely to
match UI status. These checks also apply after a Genie Code session or other agent
host is interrupted and do not require Lakebase outside the App.

### Model endpoint timeout

A model-request timeout is not a notebook result or proof that previous tool work failed.
The host may retry the unanswered inference request once with the same conversation and
completed tool results, provided this request only produces a response and has no server-side
tool execution. Never replay completed tool calls, submit a duplicate job, change the frozen
model, or mark a phase complete to overcome a timeout. If the host executes tools server-side
or request outcome is ambiguous, reconcile execution first; do not retry blindly.

After retry exhaustion, preserve the endpoint error and the exact run identity, last acknowledged
phase, notebook path and Jobs run ID when known. Resume through the master using the host
interruption protocol above: inspect existing remote jobs and persisted artifacts, wait on active
jobs, authenticate completed output before checkpoint reuse, and rerun only work proven necessary.
An unavailable model cannot write its own terminal manifest; the host must report interrupted
execution honestly rather than inventing a successful master commit. Use the existing lifecycle
recovery protocol, including for a failed terminal run.

Keep model turns bounded: use frozen templates, declarative specs, and targeted reads instead
of asking the model to reproduce full notebook bodies or repeatedly loading all artifact content.
Retain required instructions, guardrails, run identity and tool results; reducing context must not
remove admission evidence. These rules apply to App and Genie Code without requiring Lakebase.
